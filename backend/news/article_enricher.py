"""
Article enrichment pipeline.
Reads unenriched articles from evidence.json, extracts structured
signals using Ollama/llama3, and stores results in signals.db.

Designed to be:
- Incremental: only processes articles not yet in signals.db
- Resilient: failures are recorded, not fatal
- Observable: progress logged, stats tracked
- Independent: runs separately from data sourcing pipeline
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = (10, 90)
OLLAMA_TEMPERATURE = 0.1
OLLAMA_NUM_PREDICT = 1200
BATCH_DELAY = 0.5
MAX_RETRIES = 1

EVIDENCE_PATH = (
    Path(__file__).resolve().parents[4]
    / "Reports"
    / "tool"
    / "backend"
    / "data"
    / "evidence.json"
)

TAXONOMY = """
geopolitics: middle_east, europe, us_china, russia_ukraine, nato,
  trade_war, sanctions, emerging_markets, africa, latin_america,
  asia_pacific, multilateral_institutions, election_risk,
  political_instability

central_banks: fed, ecb, boe, boj, pboc, rba, snb, emerging_cb,
  rate_policy, qe_qt, forward_guidance, inflation_target,
  fx_intervention, cbdc, financial_stability

fixed_income: us_treasuries, eu_bonds, uk_gilts, em_debt,
  credit_spreads, yield_curve, high_yield, investment_grade,
  structured_products, sovereign_debt, municipal_bonds,
  inflation_linked

equities: us_large_cap, european_equities, asian_equities,
  em_equities, growth_stocks, value_stocks, dividends,
  buybacks, ipo_markets, short_selling

energy_markets: crude_oil, natural_gas, lng, opec, shale,
  refining, pipelines, energy_storage, nuclear, coal,
  energy_transition, renewables, power_grids, electricity_prices

commodities: gold, silver, platinum, copper, iron_ore, aluminum,
  zinc, nickel, lithium, cobalt, rare_earths, agricultural,
  wheat, corn, soybeans, coffee, cotton, timber

fx_and_rates: dollar, euro, yen, gbp, yuan, chf, em_currencies,
  crypto_fx, carry_trade, fx_volatility, remittances,
  dollarization

credit_and_banking: bank_earnings, credit_cycle, private_credit,
  bank_regulation, capital_requirements, lending_standards,
  npl_ratios, deposit_flows, investment_banking,
  retail_banking, shadow_banking

technology: ai_infrastructure, semiconductors, data_centers,
  cyber_security, platforms, fintech, saas, cloud_computing,
  robotics, quantum_computing, biotech_tech, space_tech

defense_security: defense_spending, weapons_systems,
  nato_spending, active_conflict, cyber_warfare, intelligence,
  arms_trade, military_technology, homeland_security,
  nuclear_deterrence

climate_energy: carbon_markets, net_zero_policy, renewable_policy,
  energy_transition_risk, physical_climate_risk, esg_investing,
  green_bonds, carbon_border_adjustment, water_scarcity,
  biodiversity

macro_economy: inflation, recession_risk, gdp_growth, employment,
  fiscal_policy, trade_balance, productivity, supply_chains,
  deglobalization, demographics, housing_markets,
  consumer_spending, wage_growth

private_markets: private_equity, venture_capital, private_debt,
  real_assets, infrastructure_investment, hedge_funds,
  fund_flows, family_offices, secondaries, co_investment

real_estate: commercial_real_estate, residential, reits,
  office_markets, retail_property, logistics_property,
  data_center_real_estate, hospitality, land

healthcare: pharmaceuticals, biotech, medical_devices,
  health_insurance, hospital_systems, drug_pricing,
  fda_approvals, clinical_trials, glp1_obesity, gene_therapy,
  diagnostics

consumer: luxury_goods, retail, e_commerce, consumer_credit,
  consumer_confidence, brand_strategy, food_beverage,
  automotive, travel_leisure, media_entertainment, gaming,
  sports

industrials: manufacturing, aerospace, shipping_freight,
  logistics, supply_chain, construction, engineering,
  chemicals, packaging, automation, industrial_metals

financial_infrastructure: payments, exchanges,
  clearing_settlement, market_structure, regulation_sec_fca,
  accounting_standards, audit, legal_risk,
  sanctions_compliance, aml_kyc

digital_assets: bitcoin, ethereum, stablecoins, defi,
  nft_web3, cbdc_crypto, crypto_regulation,
  blockchain_enterprise, tokenization

labour_markets: employment_data, wage_inflation, unions,
  remote_work, immigration_labour, skills_shortage,
  ai_displacement, pension_funds, retirement, social_security
"""

SIGNAL_TYPES = (
    "policy_decision, market_move, conflict_event, earnings_signal, "
    "data_release, supply_shock, demand_signal, sentiment_shift, "
    "structural_change, geopolitical_risk, regulatory_action"
)

SYSTEM_PROMPT = f"""You are a financial intelligence extraction system.
Your job is to analyse a financial news article and extract structured signals.

You must respond with a single valid JSON object - nothing else.
No explanation, no preamble, no markdown, no code blocks. Just raw JSON.

Use ONLY the taxonomy values listed below using dot notation
(e.g. "energy_markets.crude_oil", "geopolitics.middle_east").
Do not invent new sector tags. If something does not fit, omit it
rather than approximate it - except use "other.unclassified" if the
article is financially relevant but fits nothing else.

SECTOR TAXONOMY:
{TAXONOMY}

SIGNAL TYPES (pick 1-3): {SIGNAL_TYPES}

CONFIDENCE SCALE:
  1.0 = sector explicitly named, central to article
  0.7 = clearly implied, strong inference
  0.5 = plausibly relevant, moderate inference
  0.3 = weakly implied - OMIT (threshold is 0.5)

DIRECTION VALUES: bullish, bearish, neutral, mixed"""
SYSTEM_PROMPT += """

CRITICAL RULES FOR SECTOR MAPPING:
- PRIMARY SUBJECT RULE: The sector that is the direct subject of
  the article headline must always appear in sector_signals with
  confidence >= 0.7, even if it seems obvious. Examples:
  - Bond/yield/debt article -> fixed_income.* must be present
  - Chip/semiconductor article -> technology.semiconductors must be present
  - Oil price article -> energy_markets.crude_oil must be present
  - IPO/listing article -> equities.ipo_markets must be present
  - Central bank rate decision -> central_banks.rate_policy must be present
  - Currency/FX article -> fx_and_rates.* must be present
  - M&A/acquisition article -> financial_infrastructure.market_structure
    or private_markets.* must be present
- Only tag a sector if the article EXPLICITLY mentions it or directly
  implies it through named entities, prices, or events
- Do NOT infer distant second-order effects unless they are explicitly
  discussed in the article
- A chip performance article should NOT get energy_markets tags unless
  the article explicitly discusses energy consumption or power costs
- A geopolitics article should NOT get fixed_income tags unless it
  explicitly discusses bond markets, yields, or debt
- When uncertain between two sectors, pick the one with stronger
  direct evidence and lower confidence, not both at high confidence
- Aim for 2-4 highly confident sector tags rather than 6 weakly
  inferred ones"""

USER_PROMPT_TEMPLATE = """Analyse this financial news article:

SOURCE: {source}
DATE: {date}
TITLE: {title}
CONTENT: {content}

Extract and return as a single JSON object with exactly these fields:

{{
  "entities": [
    {{"name": "string", "type": "central_bank|government|company|person|commodity|index|country|institution", "role": "string"}}
  ],
  "actions": [
    {{"subject": "string", "verb": "string", "object": "string", "magnitude": "string or null", "tense": "past|present|future|expected"}}
  ],
  "quantitative": [
    {{"metric": "string", "value": number_or_null, "unit": "string", "direction": "up|down|flat|volatile|null", "asset": "string or null"}}
  ],
  "sector_signals": [
    {{"sector": "domain.subsector", "confidence": 0.0-1.0, "direction": "bullish|bearish|neutral|mixed", "evidence": "one sentence max"}}
  ],
  "signal_types": ["list from allowed types"],
  "dominant_theme": "single most important sector tag",
  "summary_signal": "max 20 words - the core financial signal",
  "geopolitical_risk_score": 0.0-1.0,
  "market_impact_score": 0.0-1.0
}}

Rules:
- sector_signals: minimum 1, maximum 6, confidence >= 0.5 only
- entities: minimum 1
- quantitative: empty array [] if no numbers present
- summary_signal: under 20 words, specific not generic
- If financially relevant but no taxonomy fit: add {{"sector": "other.unclassified", "confidence": 0.5, "direction": "neutral", "evidence": "describe the topic"}}
- If article is not financially relevant: set market_impact_score <= 0.1"""


def _call_ollama(system: str, user: str) -> str:
    """Call Ollama chat endpoint. Returns raw text response."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_NUM_PREDICT,
            "top_p": 0.9,
        },
    }
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def _extract_json(text: str) -> Dict:
    """
    Extract JSON from LLM response.
    Handles cases where model wraps JSON in markdown or adds preamble.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}")


def _validate_output(data: Dict) -> Dict:
    """
    Validate and normalise extracted signal data.
    Fills missing fields with safe defaults.
    """
    for field in ["entities", "actions", "quantitative", "sector_signals", "signal_types"]:
        if not isinstance(data.get(field), list):
            data[field] = []

    valid_sectors = []
    for s in data["sector_signals"]:
        if not isinstance(s, dict):
            continue
        confidence = float(s.get("confidence", 0))
        if confidence < 0.5:
            continue
        if not s.get("sector"):
            continue
        valid_sectors.append(
            {
                "sector": str(s["sector"]),
                "confidence": round(min(confidence, 1.0), 2),
                "direction": s.get("direction", "neutral"),
                "evidence": str(s.get("evidence", ""))[:200],
            }
        )
    data["sector_signals"] = valid_sectors[:6]

    if not data["sector_signals"] and data.get("market_impact_score", 0) > 0.1:
        data["sector_signals"] = [
            {
                "sector": "other.unclassified",
                "confidence": 0.5,
                "direction": "neutral",
                "evidence": "Article had no clear taxonomy match",
            }
        ]

    data["geopolitical_risk_score"] = round(float(data.get("geopolitical_risk_score") or 0), 2)
    data["market_impact_score"] = round(float(data.get("market_impact_score") or 0), 2)

    summary = str(data.get("summary_signal") or "")
    data["summary_signal"] = " ".join(summary.split()[:20])

    return data


def enrich_article(article: Dict) -> Tuple[Dict, bool, Optional[str]]:
    """
    Enrich a single article. Returns (signal_dict, success, error_msg).
    Retries once on JSON parse failure.
    """
    title = article.get("title", "")
    content = (article.get("summary") or article.get("description") or "")[:800]
    source = (article.get("source") or {}).get("name", "") or article.get("sourceName", "")
    date = str(article.get("datePublished") or "")[:10]

    user_prompt = USER_PROMPT_TEMPLATE.format(
        source=source,
        date=date,
        title=title,
        content=content or "(no content available)",
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            raw = _call_ollama(SYSTEM_PROMPT, user_prompt)
            data = _extract_json(raw)
            data = _validate_output(data)
            return data, True, None
        except ValueError as e:
            if attempt < MAX_RETRIES:
                logger.warning("[enricher] JSON parse failed for '%s', retrying: %s", title[:50], e)
                time.sleep(1)
            else:
                return {}, False, f"JSON parse failed after {MAX_RETRIES + 1} attempts: {e}"
        except requests.RequestException as e:
            return {}, False, f"Ollama request failed: {e}"
        except Exception as e:
            return {}, False, f"Unexpected error: {e}"

    return {}, False, "Max retries exceeded"


def _parse_date(date_str: str):
    """Parse any common date format to datetime. Returns None on failure."""
    if not date_str:
        return None
    try:
        d = date_str[:10]
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ["%d %b %Y", "%B %d, %Y", "%d/%m/%Y"]:
        try:
            return datetime.strptime(date_str.strip()[:20], fmt).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
    return None


def run_enrichment(
    scope_days: int = 7,
    batch_delay: float = BATCH_DELAY,
    max_articles: Optional[int] = None,
) -> Dict:
    """
    Main enrichment entry point. Incremental - skips already-enriched articles.

    Args:
        scope_days:   only enrich articles from last N days
        batch_delay:  seconds between articles
        max_articles: cap for testing (None = no cap)

    Returns dict with run stats.
    """
    from backend.news.signals_db import (
        finish_run,
        get_enriched_ids,
        init_db,
        start_run,
        upsert_signal,
    )

    init_db()

    if not EVIDENCE_PATH.exists():
        logger.error("[enricher] evidence.json not found at %s", EVIDENCE_PATH)
        return {"error": "evidence.json not found"}

    with open(EVIDENCE_PATH, encoding="utf-8") as f:
        all_articles = json.load(f)

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=scope_days)
    in_scope = []
    for a in all_articles:
        pub = a.get("datePublished") or ""
        if not pub:
            continue
        dt = _parse_date(pub)
        if dt is not None and dt >= cutoff_dt:
            in_scope.append(a)

    enriched_ids = get_enriched_ids()
    to_process = [a for a in in_scope if a.get("contentHash") and a["contentHash"] not in enriched_ids]

    if max_articles:
        to_process = to_process[:max_articles]

    total = len(to_process)
    skipped = len(in_scope) - total
    logger.info(
        "[enricher] Starting enrichment: %d articles to process, %d already done", total, skipped
    )

    if total == 0:
        logger.info("[enricher] Nothing to enrich.")
        return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": skipped}

    run_id = start_run(scope_days)
    processed = succeeded = failed = 0

    try:
        for i, article in enumerate(to_process):
            content_hash = article.get("contentHash", "")
            title = article.get("title", "")[:60]

            logger.info("[enricher] %d/%d: %s (%s)", i + 1, total, title, content_hash[:12])

            data, success, error = enrich_article(article)

            signal = {
                "id": content_hash,
                "title": article.get("title", ""),
                "source": (article.get("source") or {}).get("name", ""),
                "date_published": str(article.get("datePublished") or "")[:10],
                "theme_id": article.get("themeId", ""),
                "enriched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "model": OLLAMA_MODEL,
                "failed": 0 if success else 1,
                "error": error,
                "raw_output": None,
            }

            if success:
                signal.update(data)
                succeeded += 1
            else:
                signal.update(
                    {
                        "entities": [],
                        "actions": [],
                        "quantitative": [],
                        "sector_signals": [],
                        "signal_types": [],
                        "dominant_theme": None,
                        "summary_signal": None,
                        "geopolitical_risk_score": 0.0,
                        "market_impact_score": 0.0,
                    }
                )
                failed += 1
                logger.warning("[enricher] Failed: %s - %s", title, error)

            upsert_signal(signal)
            processed += 1

            if batch_delay > 0:
                time.sleep(batch_delay)
    except Exception as e:
        import traceback

        logger.error("[enricher] Fatal error in enrichment loop: %s\n%s", e, traceback.format_exc())
        finish_run(
            run_id, processed, succeeded, failed, skipped, status="error", error=str(e)
        )
        return {"error": str(e), "processed": processed}
    else:
        finish_run(run_id, processed, succeeded, failed, skipped)

    logger.info(
        "[enricher] Run complete: %d processed, %d succeeded, %d failed", processed, succeeded, failed
    )
    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
    }
