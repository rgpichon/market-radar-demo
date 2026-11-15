"""
Aggregate sector scores from evidence.json (Source A) and signals.db (Source B).

Standalone/offline:
  cd ".../Market Radar/Codes/backend"
  python -m news.sector_scorer
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure backend/ is on path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE_DIR = Path(__file__).resolve().parents[1]
SIGNALS_DB_PATH = BASE_DIR / "signals.db"
EVIDENCE_PATH = (
    Path(__file__).resolve().parents[4]
    / "Reports"
    / "tool"
    / "backend"
    / "data"
    / "evidence.json"
)
THEMES_PATH = (
    Path(__file__).resolve().parents[4]
    / "Reports"
    / "tool"
    / "data"
    / "themes.json"
)
OUTPUT_PATH = BASE_DIR / "data" / "sector_scores.json"

CANONICAL_SECTORS = [
    "technology",
    "energy",
    "macro",
    "geopolitics",
    "fixed_income",
    "equities",
]

# Source A: themes.json "sectors"[] values (exact strings) → canonical sector.
# First listed sector on the theme that appears here wins.
SECTOR_FROM_THEME_SECTOR = {
    "Semiconductors": "technology",
    "Technology Hardware": "technology",
    "Data Centers": "technology",
    "Software": "technology",
    "Cybersecurity": "technology",
    "Energy": "energy",
    "Renewable Energy": "energy",
    "Utilities": "energy",
    "Materials": "energy",
    "Mining": "energy",
    "Agriculture": "energy",
    "Consumer": "macro",
    "Industrials": "macro",
    "Real Estate": "macro",
    "REITs": "macro",
    "Healthcare": "macro",
    "Pharmaceuticals": "macro",
    "Biotechnology": "macro",
    "Medical Devices": "macro",
    "Insurance": "macro",
    "Aerospace & Defense": "geopolitics",
    "Banks": "fixed_income",
    "Fintech": "fixed_income",
}

# Source B: freeform Ollama sector string → canonical (first match wins)
_SIGNAL_SECTOR_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("technology", ("technology", "ai", "semiconductor", "chip", "software", "cloud", "gpu", "nvidia", "llm", "model")),
    ("energy", ("energy", "oil", "crude", "renewabl", "gas", "opec", "lng")),
    ("macro", ("macro", "gdp", "recession", "sovereign", "consumer", "private_credit", "credit")),
    ("geopolitics", ("geopolit", "middle_east", "defense", "us_china", "sanction", "war", "nato")),
    ("fixed_income", ("fixed_income", "central_bank", "rate", "treasury", "bond", "yield")),
    ("equities", ("equit", "private_equity", "private_market", "ipo", "market_structure")),
]

_TECH_SUB_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    (
        "ai_infrastructure",
        ("chip", "semiconductor", "data center", "data centre", "compute", "infrastructure", "gpu"),
    ),
    (
        "ai_platforms",
        ("model", "llm", "openai", "anthropic", "foundation", "ai model", "platform"),
    ),
    (
        "ai_enterprise",
        ("enterprise", "saas", "adoption", "software", "deployment"),
    ),
]


def _normalize_sector_label(s: Any) -> str:
    return str(s or "").strip().lower()


def _theme_canonical_sector(theme: Dict[str, Any]) -> str:
    """
    Map one theme to canonical sector from its sectors[] array only.
    Iterate in array order; first value that exists in SECTOR_FROM_THEME_SECTOR wins.
    """
    raw = theme.get("sectors") or []
    if not isinstance(raw, list):
        return "other"
    for entry in raw:
        if entry is None:
            continue
        label = str(entry).strip()
        if not label:
            continue
        canonical = SECTOR_FROM_THEME_SECTOR.get(label)
        if canonical:
            return canonical
    return "other"


def _build_theme_id_maps() -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """themeId → canonical sector, themeId → theme dict."""
    if not THEMES_PATH.exists():
        return {}, {}
    try:
        with open(THEMES_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}, {}

    themes_list: List[Dict[str, Any]] = raw if isinstance(raw, list) else []
    sector_map: Dict[str, str] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for t in themes_list:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        if not tid:
            continue
        tid_s = str(tid)
        by_id[tid_s] = t
        sector_map[tid_s] = _theme_canonical_sector(t)
    return sector_map, by_id


def _map_signal_sector_string(sector_str: Any) -> str:
    s = _normalize_sector_label(sector_str)
    if not s:
        return "other"
    for canonical, needles in _SIGNAL_SECTOR_RULES:
        if any(n in s for n in needles):
            return canonical
    return "other"


def _tech_sub_bucket(theme_name: str) -> Optional[str]:
    tl = theme_name.lower()
    for key, needles in _TECH_SUB_RULES:
        if any(n in tl for n in needles):
            return key
    return None


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.strptime(text[:10], "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _tier_weight(tier: Any) -> float:
    try:
        t = int(tier)
    except Exception:
        return 0.4
    if t <= 1:
        return 1.0
    if t == 2:
        return 0.7
    return 0.4


def _recency_weight(published_at: datetime, now: datetime) -> float:
    age_days = (now - published_at).days
    if age_days <= 7:
        return 1.0
    if age_days <= 14:
        return 0.7
    return 0.4


def _direction_value(label: Any) -> float:
    s = str(label or "").strip().lower()
    if s == "bullish":
        return 1.0
    if s == "bearish":
        return -1.0
    return 0.0


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        f = float(x)
    except Exception:
        return default
    return max(0.0, min(1.0, f))


def _safe_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _utc_monday_start(dt: datetime) -> datetime:
    """Monday 00:00 UTC for the ISO week containing dt."""
    d = dt.astimezone(timezone.utc).date()
    monday = d - timedelta(days=d.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def _sentiment_label_from_item(item: Dict[str, Any]) -> str:
    s = str(item.get("sentiment") or "").strip().lower()
    if s in ("bullish", "bearish", "neutral"):
        return s
    return "neutral"


def _weighted_score_from_items(
    items: List[Dict[str, Any]],
) -> Tuple[float, int]:
    """Return (rounded score, article_count). Empty → (0.0, 0)."""
    total_w = 0.0
    wsum = 0.0
    for it in items:
        w = float(it["weight"])
        dv = float(it["direction_value"])
        total_w += w
        wsum += dv * w
    if total_w <= 0:
        return 0.0, len(items)
    return round(wsum / total_w, 2), len(items)


def _compute_conviction(
    weighted_score: float,
    article_count: int,
    bull_count: int,
    bear_count: int,
) -> str:
    if article_count == 0:
        return "low"

    directional = bull_count + bear_count
    if directional == 0:
        return "low"

    dominant_count = max(bull_count, bear_count)
    dominant_ratio = dominant_count / directional

    abs_score = abs(weighted_score)

    if abs_score >= 0.3 and article_count >= 30 and dominant_ratio >= 0.65:
        return "high"
    elif abs_score >= 0.12 and article_count >= 15 and dominant_ratio >= 0.55:
        return "medium"
    else:
        return "low"


def _aggregate_items(
    items: List[Dict[str, Any]], now: datetime
) -> Dict[str, Any]:
    """Single sector bucket from scored contributions."""
    total_w = 0.0
    wsum = 0.0
    bull = bear = neutral = 0
    for it in items:
        w = float(it["weight"])
        dv = float(it["direction_value"])
        total_w += w
        wsum += dv * w
        if dv > 0:
            bull += 1
        elif dv < 0:
            bear += 1
        else:
            neutral += 1

    if total_w > 0:
        score = wsum / total_w
    else:
        score = 0.0
    score = round(score, 2)
    n = len(items)
    conviction = _compute_conviction(score, n, bull, bear)
    if score > 0.1:
        direction = "bullish"
    elif score < -0.1:
        direction = "bearish"
    else:
        direction = "neutral"
    return {
        "score": score,
        "direction": direction,
        "conviction": conviction,
        "article_count": n,
        "bull_count": bull,
        "bear_count": bear,
        "neutral_count": neutral,
    }


def _load_source_a(
    cutoff: datetime,
    now: datetime,
    theme_sector: Dict[str, str],
    theme_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    if not EVIDENCE_PATH.exists():
        return rows, 0
    try:
        with open(EVIDENCE_PATH, encoding="utf-8") as f:
            raw_ev = json.load(f)
    except Exception:
        return rows, 0
    items = raw_ev if isinstance(raw_ev, list) else raw_ev.get("evidence", raw_ev.get("items", []))
    if not isinstance(items, list):
        return rows, 0

    for item in items:
        if not isinstance(item, dict):
            continue
        pub = _parse_date(item.get("datePublished"))
        if pub is None or pub < cutoff or pub > now + timedelta(days=1):
            continue
        tid = str(item.get("themeId") or "")
        sector = theme_sector.get(tid, "other")
        if sector == "other":
            continue
        theme_rec = theme_by_id.get(tid, {})
        theme_name = str(theme_rec.get("name") or "")

        sent_l = _sentiment_label_from_item(item)
        dv = _direction_value("bullish" if sent_l == "bullish" else "bearish" if sent_l == "bearish" else "neutral")

        src = item.get("source") if isinstance(item.get("source"), dict) else {}
        tw = _tier_weight(src.get("tier"))

        ms = item.get("matchScore")
        if ms is None and isinstance(item.get("matchDetails"), dict):
            ms = item["matchDetails"].get("score")
        try:
            match_w = min(float(ms or 0) / 5.0, 1.0)
        except Exception:
            match_w = 0.0

        rw = _recency_weight(pub, now)
        weight = tw * rw * match_w
        if weight <= 0:
            weight = 1e-9

        rows.append(
            {
                "source": "a",
                "sector": sector,
                "theme_id": tid,
                "theme_name": theme_name,
                "sentiment": sent_l,
                "direction_value": dv,
                "weight": weight,
                "published_at": pub,
            }
        )
    return rows, len(rows)


def _source_a_row_for_trend_item(
    item: Dict[str, Any],
    theme_sector_col: Dict[str, str],
    theme_by_id: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build Source A contribution row with recency_weight=1.0 (tier * match only)."""
    if not isinstance(item, dict):
        return None
    pub = _parse_date(item.get("datePublished"))
    if pub is None:
        return None
    tid = str(item.get("themeId") or "")
    sector = theme_sector_col.get(tid, "other")
    if sector == "other":
        return None
    theme_rec = theme_by_id.get(tid, {})
    theme_name = str(theme_rec.get("name") or "")

    sent_l = _sentiment_label_from_item(item)
    dv = _direction_value("bullish" if sent_l == "bullish" else "bearish" if sent_l == "bearish" else "neutral")

    src = item.get("source") if isinstance(item.get("source"), dict) else {}
    tw = _tier_weight(src.get("tier"))

    ms = item.get("matchScore")
    if ms is None and isinstance(item.get("matchDetails"), dict):
        ms = item["matchDetails"].get("score")
    try:
        match_w = min(float(ms or 0) / 5.0, 1.0)
    except Exception:
        match_w = 0.0

    weight = tw * 1.0 * match_w
    if weight <= 0:
        weight = 1e-9

    return {
        "source": "a",
        "sector": sector,
        "theme_id": tid,
        "theme_name": theme_name,
        "sentiment": sent_l,
        "direction_value": dv,
        "weight": weight,
        "published_at": pub,
    }


def _weekly_trend_source_a(
    now: datetime,
    theme_sector: Dict[str, str],
    theme_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Eight ISO weeks (Monday-bound), most recent first in output list.
    week_start = Monday 00:00 UTC; score uses tier*match only (recency 1.0).
    """
    if not EVIDENCE_PATH.exists():
        return {s: [] for s in CANONICAL_SECTORS}

    try:
        with open(EVIDENCE_PATH, encoding="utf-8") as f:
            raw_ev = json.load(f)
    except Exception:
        return {s: [] for s in CANONICAL_SECTORS}

    items_list = raw_ev if isinstance(raw_ev, list) else raw_ev.get("evidence", raw_ev.get("items", []))
    if not isinstance(items_list, list):
        return {s: [] for s in CANONICAL_SECTORS}

    mon0 = _utc_monday_start(now)

    # Pre-collect rows per sector, partitioned by week index 0..7
    per_sector_week: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
        s: defaultdict(list) for s in CANONICAL_SECTORS
    }

    for item in items_list:
        row = _source_a_row_for_trend_item(item, theme_sector, theme_by_id)
        if row is None:
            continue
        pub = row["published_at"]
        for k in range(8):
            wstart = mon0 - timedelta(days=7 * k)
            wend = wstart + timedelta(days=7)
            if wstart <= pub < wend:
                per_sector_week[row["sector"]][k].append(row)
                break

    out: Dict[str, List[Dict[str, Any]]] = {}
    for sec in CANONICAL_SECTORS:
        trend_list: List[Dict[str, Any]] = []
        for k in range(8):
            wstart = mon0 - timedelta(days=7 * k)
            week_items = per_sector_week[sec].get(k, [])
            score, acount = _weighted_score_from_items(week_items)
            trend_list.append(
                {
                    "week_start": wstart.date().isoformat(),
                    "score": score if acount else 0.0,
                    "article_count": acount,
                }
            )
        out[sec] = trend_list
    return out


def _themes_detail_for_sector(
    sector: str,
    source_a_rows: List[Dict[str, Any]],
    theme_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Per-theme breakdown from Source A only, 30-day window (same rows as main load)."""
    by_theme: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in source_a_rows:
        if r.get("source") != "a" or r.get("sector") != sector:
            continue
        tid = str(r.get("theme_id") or "")
        if not tid:
            continue
        by_theme[tid].append(r)

    def _dominant_direction(rows: List[Dict[str, Any]]) -> str:
        c = Counter(str(x.get("sentiment") or "neutral") for x in rows)
        # Prefer max count; tie-break bullish > bearish > neutral
        order = ["bullish", "bearish", "neutral"]
        best = "neutral"
        best_n = -1
        for lab in order:
            n = c.get(lab, 0)
            if n > best_n:
                best_n = n
                best = lab
        return best

    detail: List[Dict[str, Any]] = []
    for tid, trows in by_theme.items():
        if not trows:
            continue
        rec = theme_by_id.get(tid, {})
        name = str(rec.get("name") or trows[0].get("theme_name") or tid)
        tickers_raw = rec.get("linkedTickers") or []
        tickers = list(tickers_raw[:8]) if isinstance(tickers_raw, list) else []

        detail.append(
            {
                "id": tid,
                "name": name,
                "article_count": len(trows),
                "direction": _dominant_direction(trows),
                "tickers": tickers,
            }
        )

    detail.sort(key=lambda x: -int(x["article_count"]))
    return detail


def _load_source_b(cutoff: datetime, now: datetime) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    if not SIGNALS_DB_PATH.exists():
        return rows, 0
    conn = sqlite3.connect(str(SIGNALS_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        q = conn.execute(
            """
            SELECT sector_signals, market_impact_score, date_published, title
            FROM article_signals
            WHERE failed = 0
            """
        )
        db_rows = q.fetchall()
    except Exception:
        db_rows = []
    finally:
        conn.close()

    for row in db_rows:
        pub = _parse_date(row["date_published"])
        if pub is None or pub < cutoff or pub > now + timedelta(days=1):
            continue
        ss = _safe_json(row["sector_signals"], [])
        if not isinstance(ss, list) or not ss:
            continue
        first = ss[0] if isinstance(ss[0], dict) else {}
        sec_str = first.get("sector", "")
        sector = _map_signal_sector_string(sec_str)
        if sector == "other":
            continue

        dv = _direction_value(first.get("direction"))
        conf = _clamp01(first.get("confidence"), 0.5)
        impact = _clamp01(row["market_impact_score"], 0.5)
        rw = _recency_weight(pub, now)
        weight = conf * impact * rw
        if weight <= 0:
            weight = 1e-9

        try:
            impact_sort = float(row["market_impact_score"] or 0)
        except Exception:
            impact_sort = 0.0

        rows.append(
            {
                "source": "b",
                "sector": sector,
                "theme_name": str(row["title"] or ""),
                "direction_value": dv,
                "weight": weight,
                "published_at": pub,
                "_impact_sort": impact_sort,
                "_title": str(row["title"] or ""),
            }
        )
    return rows, len(rows)


def run() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    theme_sector, theme_by_id = _build_theme_id_maps()

    source_a, source_a_total = _load_source_a(cutoff, now, theme_sector, theme_by_id)
    source_b, source_b_total = _load_source_b(cutoff, now)
    all_rows = source_a + source_b

    by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in all_rows:
        by_sector[r["sector"]].append(r)

    sectors_out: Dict[str, Any] = {}
    article_count_total = 0

    for sec in CANONICAL_SECTORS:
        items = by_sector.get(sec, [])
        article_count_total += len(items)

        src_a = sum(1 for x in items if x["source"] == "a")
        src_b = sum(1 for x in items if x["source"] == "b")

        theme_counter: Counter = Counter()
        for it in items:
            if it["source"] == "a" and it.get("theme_name"):
                theme_counter[str(it["theme_name"])] += 1
        top_themes = [name for name, _ in theme_counter.most_common(3)]

        b_titles: List[Tuple[float, str]] = []
        for it in items:
            if it["source"] == "b":
                b_titles.append((float(it.get("_impact_sort", 0)), str(it.get("_title", ""))))
        b_titles.sort(key=lambda x: -x[0])
        sample_evidence: List[str] = []
        seen = set()
        for _, title in b_titles:
            t = title.strip()
            if t and t not in seen:
                seen.add(t)
                sample_evidence.append(t)
            if len(sample_evidence) >= 3:
                break

        metrics = _aggregate_items(items, now)
        sectors_out[sec] = {
            **metrics,
            "source_a_count": src_a,
            "source_b_count": src_b,
            "top_themes": top_themes,
            "sample_evidence": sample_evidence,
        }

        if sec == "technology":
            sub_groups: Dict[str, List[Dict[str, Any]]] = {
                "ai_infrastructure": [],
                "ai_platforms": [],
                "ai_enterprise": [],
            }
            for it in items:
                if it["source"] != "a":
                    continue
                tn = str(it.get("theme_name") or "")
                bucket = _tech_sub_bucket(tn)
                if bucket and bucket in sub_groups:
                    sub_groups[bucket].append(it)
            sectors_out[sec]["sub_sectors"] = {
                sub_key: _aggregate_items(sub_items, now)
                for sub_key, sub_items in sub_groups.items()
            }

    trend_by_sector = _weekly_trend_source_a(now, theme_sector, theme_by_id)
    for sec in CANONICAL_SECTORS:
        sectors_out[sec]["trend"] = trend_by_sector.get(sec, [])
        sectors_out[sec]["themes_detail"] = _themes_detail_for_sector(sec, source_a, theme_by_id)

    output = {
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "article_count_total": article_count_total,
        "source_a_total": source_a_total,
        "source_b_total": source_b_total,
        "sectors": sectors_out,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"Sector scores written to {OUTPUT_PATH}")
    for sec in CANONICAL_SECTORS:
        s = sectors_out[sec]
        print(
            f"{sec:<14}: {s['direction']:<8} "
            f"(score: {s['score']:.2f}, n={s['article_count']}, "
            f"a={s['source_a_count']}, b={s['source_b_count']}, "
            f"conviction: {s['conviction']})"
        )


if __name__ == "__main__":
    run()
