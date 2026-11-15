import logging
import re
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, List, Optional, TypedDict

import requests

from backend.news.feed_aggregator import (
    FeedItem,
    get_digest_context,
    get_signals_feed,
    get_topic_feed,
)

logger = logging.getLogger(__name__)


class DigestGenerationError(Exception):
    pass


OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = 60
OLLAMA_OPTIONS = {
    "temperature": 0.3,
    "top_p": 0.9,
    "num_predict": 512,
}


BASE_PERSONA = """You are a senior financial intelligence analyst writing
for institutional investors - portfolio managers, macro strategists, and
senior analysts at hedge funds and asset managers.

Your style: direct, specific, and signal-focused. You write like the
best FT or Economist briefings: confident, concise, never hedging with
empty phrases like "it is worth noting" or "it is important to consider".
You cite specific institutions, names, dates, and numbers when available.
You never use bullet points or numbered lists. You never mention being an AI.
You do not add disclaimers. You write in short, dense paragraphs."""


FORMAT_SPECS = {
    "weekly_briefing": {
        "length": "350-450 words total across three sections",
        "structure": """Write exactly three sections, each a full paragraph of
5-7 sentences. Label each section exactly as shown:

EVENTS TO WATCH:
[paragraph - name specific upcoming events, their dates, who is organising
them, and what signals they send about market conditions or policy direction]

INTELLIGENCE DIGEST:
[paragraph - synthesise the 2-3 dominant themes from recent research and
commentary. Quote specific sources by name. Identify tensions or divergences
between different views]

MARKET PULSE:
[paragraph - describe current market positioning using the exact price data
provided. Note the most significant moves, what they signal about risk
appetite, and what contradictions exist between different assets]""",
    },
    "flash_note": {
        "length": "60-90 words exactly - no more",
        "structure": """Write 2-3 sentences only. Structure:
Sentence 1: What is happening (factual, specific).
Sentence 2: Why it matters to institutional investors right now.
Sentence 3: What to watch for in the next 48-72 hours.
CRITICAL: Only use facts explicitly stated in the item data provided.
Do not add company valuations, executive names, product names, dates,
or any other details not present in the Title or Description fields.
If the description is empty, base the note only on the title.
Never invent supporting details to make the note sound more specific.
No section labels. No preamble. Start directly with the substance.""",
    },
    "topic_roundup": {
        "length": "200-280 words",
        "structure": """Write one dense, focused paragraph covering all
relevant developments in the topic area. Structure the paragraph to move
from: current state -> recent developments -> market implications -> what
to watch in the next two weeks. Do not use section labels. Write as a
single continuous analytical narrative. Name specific companies,
institutions, or officials when the data provides them.""",
    },
    "market_pulse": {
        "length": "80-120 words",
        "structure": """Write 3-4 sentences covering: the dominant market
direction this week, the most notable individual move and what it signals,
any notable divergences between asset classes, and the overall risk tone.
Use the exact percentage figures from the data. No section labels.
Start directly with the market assessment.""",
    },
}

TOPIC_PERSONAS = {
    "central_bank": {
        "keywords": [
            "central bank", "fed", "ecb", "monetary policy", "interest rate",
            "inflation", "rate hike", "rate cut", "fomc", "lagarde", "powell",
            "hawkish", "dovish",
        ],
        "persona_addon": (
            "You specialise in central bank policy and fixed income markets. "
            "You track Fed and ECB communications closely and understand how "
            "rate decisions transmit through bond yields, credit spreads, and "
            "equity valuations. You note the difference between what central "
            "banks say and what markets price in."
        ),
    },
    "geopolitics": {
        "keywords": [
            "nato", "china", "russia", "iran", "sanctions", "trade war",
            "tariff", "geopolitics", "foreign policy", "war", "middle east",
            "ukraine", "defense",
        ],
        "persona_addon": (
            "You specialise in geopolitical risk and its market implications. "
            "You analyse how political developments affect commodity prices, "
            "supply chains, defence stocks, and safe-haven flows. You connect "
            "diplomatic signals to portfolio positioning."
        ),
    },
    "technology": {
        "keywords": [
            "ai", "semiconductor", "chip", "nvidia", "data center",
            "artificial intelligence", "machine learning", "tech", "software",
            "cloud", "gpu", "tsmc",
        ],
        "persona_addon": (
            "You specialise in technology sector analysis with focus on AI "
            "infrastructure, semiconductor supply chains, and platform economics. "
            "You distinguish between hype and fundamental value drivers, and "
            "track capex cycles in data center buildout."
        ),
    },
    "energy": {
        "keywords": [
            "oil", "gas", "crude", "lng", "opec", "energy", "renewable",
            "solar", "wind", "carbon", "climate", "emissions", "net zero",
            "fossil fuel",
        ],
        "persona_addon": (
            "You specialise in energy markets - both traditional commodities "
            "(oil, gas, LNG) and the energy transition (renewables, carbon "
            "markets, grid infrastructure). You track OPEC+ decisions, "
            "geopolitical supply risks, and the pace of electrification."
        ),
    },
    "macro": {
        "keywords": [
            "gdp", "recession", "growth", "fiscal", "debt", "deficit",
            "treasury", "yield curve", "credit", "banking", "emerging markets",
            "dollar", "fx",
        ],
        "persona_addon": (
            "You specialise in global macro - growth, fiscal policy, credit "
            "cycles, and cross-asset flows. You think in terms of regime "
            "shifts: what the growth/inflation mix means for asset allocation "
            "and which sectors benefit from the current macro backdrop."
        ),
    },
}


class DigestResult(TypedDict):
    format: str  # "weekly_briefing", "flash_note", "topic_roundup", "market_pulse"
    content: str  # the generated text
    model: str  # which Ollama model was used
    context_items: int  # how many FeedItems were in context
    generated_at: str  # ISO UTC timestamp
    topic: str  # topic if applicable, else ""
    error: str  # non-empty if generation failed, content will be ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    model: str = OLLAMA_MODEL,
    timeout: int = OLLAMA_TIMEOUT,
    max_tokens: int = 512,
) -> str:
    try:
        options = {**OLLAMA_OPTIONS, "num_predict": int(max_tokens)}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": options,
        }
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=(10, timeout),
        )
        response.raise_for_status()
        data = response.json()
        return str(data["message"]["content"]).strip()
    except Exception as e:
        logger.exception("[digest_generator] Ollama call failed")
        raise DigestGenerationError(str(e))


def _call_ollama_with_timeout(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    timeout_secs: int,
) -> str:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(
            _call_ollama,
            system_prompt,
            user_prompt,
            model,
            timeout_secs,
            max_tokens,
        )
        try:
            return future.result(timeout=timeout_secs + 5)
        except concurrent.futures.TimeoutError:
            raise DigestGenerationError(f"Generation timed out after {timeout_secs}s")


def is_ollama_available(model: str = OLLAMA_MODEL) -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        tags = r.json().get("models", [])
        return any(model in (t.get("name", "") or "") for t in tags if isinstance(t, dict))
    except Exception:
        return False


def _truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _build_signals_block(signals: List[FeedItem]) -> str:
    lines = [_truncate(str(s.get("title") or "").strip(), 80) for s in (signals or [])]
    return "MARKET SNAPSHOT:\n" + ("\n".join(lines) if lines else "")


def _build_structured_context(
    events: List[FeedItem],
    articles: List[FeedItem],
    signals: List[FeedItem],
    topic: Optional[str] = None,
) -> str:
    lines = []

    if topic:
        lines.append(f"FOCUS TOPIC: {topic}")
        lines.append("")

    if signals:
        lines.append("MARKET SNAPSHOT:")
        for s in signals[:7]:
            lines.append(f"  {s.get('title', '')}")
        lines.append("")

    if events:
        today = [e for e in events if 0 <= (e.get("age_hours", 999) * -1) <= 48]
        this_week = [e for e in events if 48 < (e.get("age_hours", 0) * -1) <= 168]
        later = [e for e in events if (e.get("age_hours", 0) * -1) > 168]

        if today:
            lines.append("EVENTS - TODAY & TOMORROW:")
            for e in today[:3]:
                date = (e.get("date_published") or "")[:10]
                lines.append(f"  [{date}] {e.get('source_name', 'Unknown')}: {e.get('title', '')}")
            lines.append("")

        if this_week:
            lines.append("EVENTS - THIS WEEK:")
            for e in this_week[:5]:
                date = (e.get("date_published") or "")[:10]
                lines.append(f"  [{date}] {e.get('source_name', 'Unknown')}: {e.get('title', '')}")
            lines.append("")

        if later:
            lines.append("EVENTS - COMING UP:")
            for e in later[:4]:
                date = (e.get("date_published") or "")[:10]
                lines.append(f"  [{date}] {e.get('source_name', 'Unknown')}: {e.get('title', '')}")
            lines.append("")

    if articles:
        by_topic: Dict[str, List[FeedItem]] = {}
        for a in articles:
            t = a.get("topic") or "General"
            by_topic.setdefault(str(t), []).append(a)

        sorted_topics = sorted(by_topic.items(), key=lambda x: -len(x[1]))
        lines.append("INTELLIGENCE - BY THEME:")
        for topic_name, topic_articles in sorted_topics[:6]:
            lines.append(f"\n  [{topic_name.upper()}]")
            for a in topic_articles[:3]:
                age_hours = a.get("age_hours", -1)
                age = f"{int(age_hours)}h ago" if isinstance(age_hours, (int, float)) and age_hours >= 0 else ""
                desc = f" - {str(a.get('description') or '')[:80]}" if a.get("description") else ""
                lines.append(
                    f"  * {a.get('source_name', 'Unknown')} ({age}): {str(a.get('title') or '')[:80]}{desc}"
                )
        lines.append("")

    return "\n".join(lines)


def _detect_topic_persona(topic: Optional[str], articles: List[FeedItem], events: List[FeedItem]) -> str:
    corpus = " ".join(
        [
            topic or "",
            " ".join(str(a.get("topic", "")) for a in articles[:10]),
            " ".join(str(a.get("title", "")) for a in articles[:5]),
            " ".join(str(e.get("title", "")) for e in events[:5]),
        ]
    ).lower()

    scores = {}
    for persona_key, persona_data in TOPIC_PERSONAS.items():
        score = sum(1 for kw in persona_data["keywords"] if kw in corpus)
        if score > 0:
            scores[persona_key] = score

    if not scores:
        return ""
    best = max(scores, key=scores.get)
    return TOPIC_PERSONAS[best]["persona_addon"]


def generate_weekly_briefing(
    context: Optional[Dict[str, List[FeedItem]]] = None,
    model: str = OLLAMA_MODEL,
) -> DigestResult:
    fmt = "weekly_briefing"
    generated_at = _now_iso()
    try:
        ctx = context or get_digest_context(events_days_ahead=14, max_items=40)
        events = ctx.get("events") or []
        articles = ctx.get("articles") or []
        signals = ctx.get("signals") or []
        context_items = len(events) + len(articles) + len(signals)

        persona_addon = _detect_topic_persona(None, articles, events)
        spec = FORMAT_SPECS[fmt]
        system_prompt = BASE_PERSONA
        if persona_addon:
            system_prompt += f"\n\n{persona_addon}"
        system_prompt += f"\n\nLength requirement: {spec['length']}."
        system_prompt += f"\n\n{spec['structure']}"

        structured_ctx = _build_structured_context(events, articles, signals)
        user_prompt = f"Here is this week's intelligence data:\n\n{structured_ctx}\n\nWrite the briefing now."

        content = _call_ollama_with_timeout(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=700,
            timeout_secs=OLLAMA_TIMEOUT,
        )
        return {
            "format": fmt,
            "content": content,
            "model": model,
            "context_items": context_items,
            "generated_at": generated_at,
            "topic": "",
            "error": "",
        }
    except DigestGenerationError as e:
        return {
            "format": fmt,
            "content": "",
            "model": model,
            "context_items": 0,
            "generated_at": "",
            "topic": "",
            "error": str(e),
        }


def generate_flash_note(
    item: FeedItem,
    model: str = OLLAMA_MODEL,
) -> DigestResult:
    fmt = "flash_note"
    generated_at = _now_iso()
    try:
        source = str(item.get("source_name") or "")
        dp = (item.get("date_published") or "")
        date_str = dp[:10] if dp else "TBD"
        title = str(item.get("title") or "").strip()
        desc = str(item.get("description") or "").strip()
        topic = str(item.get("topic") or "")

        title_norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        desc_norm = re.sub(r"[^a-z0-9]+", " ", desc.lower()).strip()
        if (
            not desc
            or len(desc) < 30
            or not desc_norm
            or desc_norm == title_norm
            or desc_norm in title_norm
            or title_norm in desc_norm
        ):
            return {
                "format": fmt,
                "content": "",
                "model": model,
                "context_items": 0,
                "generated_at": generated_at,
                "topic": "",
                "error": "Insufficient article content for flash note",
            }

        spec = FORMAT_SPECS[fmt]
        system_prompt = BASE_PERSONA
        system_prompt += f"\n\nLength requirement: {spec['length']}."
        system_prompt += f"\n\n{spec['structure']}"
        system_prompt += (
            "\n\nFor flash notes, do not infer implications from general market knowledge. "
            "Use only facts that are explicitly present in Title or Content."
        )

        user_prompt = f"""ARTICLE TO ANALYSE:
Source: {source}
Topic: {topic}
Date: {date_str}
Title: {title}
Content: {desc}

Write a flash note of 60-90 words based ONLY on the Title and Content above.
Do not add executive names, company valuations, product names, dates,
or any detail not explicitly stated in Title or Content above.
If a detail is not in the text, do not include it.
Start directly with what is happening."""

        content = _call_ollama_with_timeout(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=150,
            timeout_secs=OLLAMA_TIMEOUT,
        )
        return {
            "format": fmt,
            "content": content,
            "model": model,
            "context_items": 1,
            "generated_at": generated_at,
            "topic": topic,
            "error": "",
        }
    except DigestGenerationError as e:
        return {
            "format": fmt,
            "content": "",
            "model": model,
            "context_items": 1,
            "generated_at": generated_at,
            "topic": str(item.get("topic") or ""),
            "error": str(e),
        }


def generate_topic_roundup(
    topic: str,
    context: Optional[Dict[str, List[FeedItem]]] = None,
    model: str = OLLAMA_MODEL,
) -> DigestResult:
    fmt = "topic_roundup"
    generated_at = _now_iso()
    try:
        if context is None:
            items = get_topic_feed(topic=topic, limit=20)
            ctx = {
                "events": [i for i in items if i.get("item_type") == "event"],
                "articles": [i for i in items if i.get("item_type") == "article"],
                "signals": [i for i in items if i.get("item_type") == "signal"],
            }
        else:
            ctx = context

        events = ctx.get("events") or []
        articles = ctx.get("articles") or []
        signals = ctx.get("signals") or []
        context_items = len(events) + len(articles) + len(signals)

        persona_addon = _detect_topic_persona(topic, articles, events)
        spec = FORMAT_SPECS[fmt]
        system_prompt = BASE_PERSONA
        if persona_addon:
            system_prompt += f"\n\n{persona_addon}"
        system_prompt += f"\n\nLength requirement: {spec['length']}."
        system_prompt += f"\n\n{spec['structure']}"

        structured_ctx = _build_structured_context(events, articles, signals, topic=topic)
        user_prompt = f"Here is the topic intelligence data:\n\n{structured_ctx}\n\nWrite the topic roundup now."

        content = _call_ollama_with_timeout(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=400,
            timeout_secs=OLLAMA_TIMEOUT,
        )
        return {
            "format": fmt,
            "content": content,
            "model": model,
            "context_items": context_items,
            "generated_at": generated_at,
            "topic": topic,
            "error": "",
        }
    except DigestGenerationError as e:
        return {
            "format": fmt,
            "content": "",
            "model": model,
            "context_items": 0 if context is None else sum(len(v) for v in context.values()),
            "generated_at": generated_at,
            "topic": topic,
            "error": str(e),
        }


def generate_market_pulse(
    signals: Optional[List[FeedItem]] = None,
    model: str = OLLAMA_MODEL,
) -> DigestResult:
    fmt = "market_pulse"
    generated_at = _now_iso()
    try:
        sigs = signals if signals is not None else get_signals_feed(limit=20)
        ctx = get_digest_context(events_days_ahead=14, max_items=30)
        events = ctx.get("events") or []
        articles = ctx.get("articles") or []
        persona_addon = _detect_topic_persona(None, articles, events)
        spec = FORMAT_SPECS[fmt]
        system_prompt = BASE_PERSONA
        if persona_addon:
            system_prompt += f"\n\n{persona_addon}"
        system_prompt += f"\n\nLength requirement: {spec['length']}."
        system_prompt += f"\n\n{spec['structure']}"
        user_prompt = f"MARKET DATA:\n{_build_signals_block(sigs)}\n\nWrite the market pulse now. Remember: 80-120 words."
        content = _call_ollama_with_timeout(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=200,
            timeout_secs=OLLAMA_TIMEOUT,
        )
        return {
            "format": fmt,
            "content": content,
            "model": model,
            "context_items": len(sigs),
            "generated_at": generated_at,
            "topic": "",
            "error": "",
        }
    except DigestGenerationError as e:
        return {
            "format": fmt,
            "content": "",
            "model": model,
            "context_items": 0 if signals is None else len(signals),
            "generated_at": generated_at,
            "topic": "",
            "error": str(e),
        }


def generate(
    format: str,
    topic: Optional[str] = None,
    item: Optional[FeedItem] = None,
    model: str = OLLAMA_MODEL,
) -> DigestResult:
    """
    Single entry point for digest generation.
    format: "weekly_briefing", "flash_note", "topic_roundup", "market_pulse"
    topic: required for "topic_roundup"
    item: required for "flash_note"
    """
    if format == "weekly_briefing":
        return generate_weekly_briefing(model=model)
    elif format == "flash_note":
        if item is None:
            raise ValueError("item is required for flash_note")
        return generate_flash_note(item=item, model=model)
    elif format == "topic_roundup":
        if not topic:
            raise ValueError("topic is required for topic_roundup")
        return generate_topic_roundup(topic=topic, model=model)
    elif format == "market_pulse":
        return generate_market_pulse(model=model)
    else:
        raise ValueError(f"Unknown digest format: {format}")

