import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from dateutil import parser as dateutil_parser

from backend.news.feed_adapters import RawItem, fetch_all

logger = logging.getLogger(__name__)

BLOCKED_SOURCES = {
    "eurosport",
    "espn",
    "cosmopolitan",
    "vogue",
    "bike - das mountainbike magazin",
    "ppa tour",
    "university of arizona athletics",
    "west midlands police",
    "pinellas county",
    "wfmynews2.com",
    "fox 13 tampa bay",
    "news on 6",
    "ozarksfirst.com",
    "myrgv.com",
    "ktla",
    "anchorage daily news",
    "indiana daily student",
    "wqad",
    "fox weather",
    "maine public",
    "england and wales cricket board (ecb)",
    "dpa",
    "facebook.com",
    "linkedin",
}


class FeedItem(TypedDict):
    item_type: str  # "article", "event", "signal"
    title: str
    url: str
    source_name: str
    source_tier: int  # 1=primary institutional, 2=secondary, 3=general
    date_published: str  # ISO 8601 UTC string, or "" if unknown
    description: str  # max 500 chars
    topic: str  # human-readable topic name, e.g. "Monetary Policy"
    topic_id: str  # raw theme/tag id, preserved for filtering
    score: float  # raw score from adapter (match score or signal score)
    relevance: float  # computed composite relevance (used for ranking)
    age_hours: float  # hours since date_published, -1 if unknown
    extra: dict  # passthrough from RawItem (event_id, intel_type, etc.)


_themes_cache: Optional[Dict[str, str]] = None  # themeId → topic name
_themes_cache_lower: Optional[Dict[str, str]] = None  # lowercase(themeId) → topic name


def _load_themes() -> Dict[str, str]:
    """Load themes.json and return {id: name} mapping. Returns {} on failure."""
    global _themes_cache, _themes_cache_lower
    if _themes_cache is not None and _themes_cache_lower is not None:
        return _themes_cache

    path = Path(__file__).resolve().parents[4] / "Reports" / "tool" / "data" / "themes.json"
    backup_path = Path(__file__).resolve().parents[4] / "Reports" / "tool" / "data" / "themes_backup.json"
    try:
        mapping: Dict[str, str] = {}

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        for t in raw if isinstance(raw, list) else []:
            if not isinstance(t, dict):
                continue
            key = str(t.get("id") or t.get("themeId") or "").strip()
            if not key:
                continue
            mapping[key] = str(t.get("name") or key)

        # Legacy compatibility: evidence may reference older theme IDs.
        if backup_path.exists():
            with open(backup_path, encoding="utf-8") as f:
                raw_bak = json.load(f)
            for t in raw_bak if isinstance(raw_bak, list) else []:
                if not isinstance(t, dict):
                    continue
                key = str(t.get("id") or t.get("themeId") or "").strip()
                if not key:
                    continue
                mapping.setdefault(key, str(t.get("name") or key))

        _themes_cache = mapping
        _themes_cache_lower = {k.lower(): v for k, v in mapping.items()}
        logger.info("[feed_aggregator] Loaded %d themes from themes.json", len(_themes_cache))
    except FileNotFoundError:
        logger.warning("[feed_aggregator] themes.json not found at %s — topic names will use raw ids", path)
        _themes_cache = {}
        _themes_cache_lower = {}
    except Exception as e:
        logger.warning("[feed_aggregator] Failed to load themes.json: %s", e)
        _themes_cache = {}
        _themes_cache_lower = {}
    return _themes_cache


def _resolve_topic(topic_id: str, item_type: str) -> str:
    """Resolve a raw topic_id to a human-readable name."""
    if item_type == "signal":
        return "Market"
    if item_type == "event":
        return topic_id.title() if topic_id else "Event"
    themes = _load_themes()
    if topic_id in themes:
        return themes[topic_id]
    lower_map = _themes_cache_lower or {}
    t_lower = (topic_id or "").lower()
    if t_lower and t_lower in lower_map:
        return lower_map[t_lower]
    return topic_id.replace("-", " ").title() if topic_id else "General"


def _age_hours(date_str: str, now_utc: datetime) -> float:
    if not date_str:
        return -1.0
    try:
        dt = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now_utc - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return -1.0


def _parse_published_datetime(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        dt = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _recency_score(date_published: Optional[datetime]) -> float:
    now = datetime.now(timezone.utc)
    if not date_published:
        return 0.0
    days_ago = max(0.0, (now - date_published).total_seconds() / 86400)
    if days_ago <= 1:
        return 1.0
    if days_ago <= 3:
        return 0.9
    if days_ago <= 7:
        return 0.75
    if days_ago <= 14:
        return 0.5
    if days_ago <= 30:
        return 0.25
    if days_ago <= 60:
        return 0.1
    return 0.05


def _compute_relevance(item: RawItem, now_utc: datetime) -> float:
    """
    Composite relevance score. Higher = show first.

    Components:
    - Base signal:    raw score normalised, capped at 8.0
    - Tier bonus:     tier 1 = +3.0, tier 2 = +1.5, tier 3 = 0
    - Type bonus:     event = +1.5, article = +1.0, signal = 0
    - Recency:        decays over 7 days for articles/signals
    - Urgency:        for events, boost by how soon they are
    - Source quality: extra boost for known premium sources
    """
    item_type = item.get("item_type", "")
    date_str = item.get("date_published", "")
    score = item.get("score", 0.0)
    tier = item.get("source_tier", 3)
    source = item.get("source_name", "").lower()

    # Base: normalise raw score to 0-8 range
    base = min(float(score) / 12.0 * 8.0, 8.0)

    # Tier bonus
    tier_bonus = {1: 3.0, 2: 1.5, 3: 0.0}.get(int(tier), 0.0)

    # Type bonus
    type_bonus = {"event": 1.5, "article": 1.0, "signal": 0.0}.get(item_type, 0.0)

    # Parse date once
    age_hours = -1.0
    dt_parsed = None
    if date_str:
        try:
            dt_parsed = dateutil_parser.parse(date_str)
            if dt_parsed.tzinfo is None:
                dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
            age_hours = (now_utc - dt_parsed).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    # Recency bonus (articles and signals only — decays over 7 days)
    recency_bonus = 0.0
    if item_type in ("article", "signal") and age_hours >= 0:
        if age_hours < 6:
            recency_bonus = 4.0
        elif age_hours < 24:
            recency_bonus = 3.0
        elif age_hours < 48:
            recency_bonus = 2.0
        elif age_hours < 96:
            recency_bonus = 1.0
        elif age_hours < 168:
            recency_bonus = 0.5

    # Urgency bonus for events (how soon is it?)
    urgency_bonus = 0.0
    if item_type == "event" and dt_parsed is not None:
        days_until = (dt_parsed - now_utc).total_seconds() / 86400
        if 0 <= days_until <= 1:
            urgency_bonus = 5.0   # happening today/tomorrow
        elif days_until <= 3:
            urgency_bonus = 4.0
        elif days_until <= 7:
            urgency_bonus = 3.0
        elif days_until <= 14:
            urgency_bonus = 2.0
        elif days_until <= 30:
            urgency_bonus = 1.0

    # Source quality bonus for premium sources
    PREMIUM_SOURCES = {
        "foreign affairs", "financial times", "ft", "the economist",
        "project syndicate", "mit technology review", "brookings",
        "bis", "ecb", "federal reserve", "imf", "world bank",
        "nber", "iif", "icma", "nyt", "the new york times",
        "bloomberg", "wsj", "the wall street journal",
        "carbon brief", "chatham house", "cfr",
    }
    source_bonus = 1.5 if source in PREMIUM_SOURCES else 0.0

    total = base + tier_bonus + type_bonus + recency_bonus + urgency_bonus + source_bonus
    return round(total, 3)


def aggregate(
    articles_max_age_days: int = 7,
    events_days_ahead: int = 30,
    include_market_signals: bool = True,
    min_relevance: float = 0.0,
    filter_type: Optional[str] = None,  # "article", "event", "signal", or None for all
    filter_topic: Optional[str] = None,  # partial match on topic (case-insensitive)
    filter_source: Optional[str] = None,  # partial match on source_name (case-insensitive)
    date_from: Optional[str] = None,  # ISO string, filter date_published >= this
    date_to: Optional[str] = None,  # ISO string, filter date_published <= this
    limit: int = 100,
    sort_by: str = "relevance",  # "relevance", "date", "score"
) -> List[FeedItem]:
    try:
        raw = fetch_all(
            articles_max_age_days=articles_max_age_days,
            events_days_ahead=events_days_ahead,
            include_market_signals=include_market_signals,
        )

        seen_urls: set = set()
        deduped: List[RawItem] = []
        for item in raw:
            url = item.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            deduped.append(item)

        seen_titles: set = set()
        title_deduped: List[RawItem] = []
        for item in deduped:
            title_key = str(item.get("title") or "").strip().lower()[:80]
            if title_key and title_key in seen_titles:
                continue
            if title_key:
                seen_titles.add(title_key)
            title_deduped.append(item)
        deduped = title_deduped

        now_utc = datetime.now(timezone.utc)
        converted: List[FeedItem] = []
        for item in deduped:
            item_type = str(item.get("item_type") or "")
            topic_id = str(item.get("topic") or "")
            topic = _resolve_topic(topic_id, item_type)
            dp = str(item.get("date_published") or "")
            dt_published = _parse_published_datetime(dp)
            age_h = _age_hours(dp, now_utc)
            relevance = _compute_relevance(item, now_utc)
            recency = _recency_score(dt_published)
            relevance_score = max(0.0, min(1.0, float(relevance) / 15.0))
            final_score = recency * 0.85 + relevance_score * 0.15
            source_name = str(item.get("source_name") or "")
            if source_name.lower().strip() in BLOCKED_SOURCES:
                continue
            try:
                score = float(item.get("score", 0.0))
            except Exception:
                score = 0.0

            desc = str(item.get("description") or "").strip()
            title = str(item.get("title") or "").strip()
            if desc and title:
                desc_norm = " ".join(desc.lower().split())
                title_norm = " ".join(title.lower().split())
                if (
                    desc_norm == title_norm
                    or (desc_norm.startswith(title_norm) and len(desc_norm) <= len(title_norm) + 16)
                ):
                    desc = ""
            description = desc[:1000]

            converted.append(
                {
                    "item_type": item_type,
                    "type": item_type,
                    "title": title,
                    "url": str(item.get("url") or ""),
                    "source_name": source_name,
                    "source_tier": int(item.get("source_tier") or 3),
                    "date_published": dp,
                    "description": description,
                    "topic": topic,
                    "topic_id": topic_id,
                    "score": score,
                    "relevance": relevance,
                    "recency_score": recency,
                    "final_score": final_score,
                    "age_hours": age_h,
                    "extra": item.get("extra") or {},
                }
            )

        filtered: List[FeedItem] = []
        ft = (filter_type or "").strip().lower() if filter_type else None
        ftopic = (filter_topic or "").strip().lower() if filter_topic else None
        fsource = (filter_source or "").strip().lower() if filter_source else None

        for it in converted:
            if ft and it["item_type"] != ft:
                continue
            if ftopic:
                if ftopic not in (it["topic"] or "").lower() and ftopic not in (it["topic_id"] or "").lower():
                    continue
            if fsource:
                if fsource not in (it["source_name"] or "").lower():
                    continue
            if float(it["relevance"]) < float(min_relevance):
                continue
            if date_from:
                if it["date_published"] and it["date_published"] < date_from:
                    continue
            if date_to:
                if it["date_published"] and it["date_published"] > date_to:
                    continue
            filtered.append(it)

        if sort_by == "date":
            if ft == "event":
                items_with_date = [i for i in filtered if i["date_published"]]
                items_no_date = [i for i in filtered if not i["date_published"]]
                items_with_date.sort(key=lambda x: x["date_published"], reverse=True)
                sorted_items = items_with_date + items_no_date
            else:
                sorted_items = sorted(
                    filtered,
                    key=lambda x: (float(x.get("final_score") or 0.0), float(x.get("relevance") or 0.0)),
                    reverse=True,
                )
        elif sort_by == "score":
            sorted_items = sorted(filtered, key=lambda x: x["score"], reverse=True)
        else:
            sorted_items = sorted(
                filtered,
                key=lambda x: (float(x.get("final_score") or 0.0), float(x.get("relevance") or 0.0)),
                reverse=True,
            )

        return sorted_items[: int(limit)]
    except Exception as e:
        logger.warning("[feed_aggregator] aggregate failed: %s", e)
        return []


def get_feed(limit: int = 100) -> List[FeedItem]:
    """Full mixed feed, ranked by relevance. Primary endpoint for news app."""
    return aggregate(limit=limit, sort_by="relevance")


def get_events_feed(days_ahead: int = 30, limit: int = 50) -> List[FeedItem]:
    """Events only, sorted by date ascending (soonest first)."""
    return aggregate(
        filter_type="event",
        events_days_ahead=days_ahead,
        sort_by="date",
        limit=limit,
    )


def get_articles_feed(max_age_days: int = 7, limit: int = 50) -> List[FeedItem]:
    """Articles only, sorted by relevance."""
    return aggregate(
        filter_type="article",
        articles_max_age_days=max_age_days,
        sort_by="relevance",
        limit=limit,
    )


def get_signals_feed(limit: int = 20) -> List[FeedItem]:
    """Market signals only."""
    return aggregate(filter_type="signal", limit=limit, sort_by="score")


def get_topic_feed(topic: str, limit: int = 30) -> List[FeedItem]:
    """All item types filtered by topic, ranked by relevance."""
    return aggregate(filter_topic=topic, limit=limit, sort_by="relevance")


def get_digest_context(
    max_items: int = 40,
    events_days_ahead: int = 14,
) -> Dict[str, List[FeedItem]]:
    """
    Returns a structured context dict for the LLM digest generator.
    Groups items by type for easier prompt construction.
    max_items is split roughly: 20 events, 15 articles, 5 signals.
    """
    _ = max_items
    return {
        "events": get_events_feed(days_ahead=events_days_ahead, limit=20),
        "articles": get_articles_feed(limit=15),
        "signals": get_signals_feed(limit=5),
    }


def get_feed_stats() -> Dict[str, Any]:
    """
    Returns a summary dict for the /api/feed/stats endpoint and dashboard.
    Does a full fetch but returns counts and metadata rather than items.
    """
    all_items = aggregate(limit=5000, events_days_ahead=60)
    now = datetime.now(timezone.utc)
    by_type: Dict[str, int] = {}
    by_topic: Dict[str, int] = {}
    for item in all_items:
        t = item["item_type"]
        by_type[t] = by_type.get(t, 0) + 1
        topic = item["topic"]
        by_topic[topic] = by_topic.get(topic, 0) + 1

    return {
        "total": len(all_items),
        "by_type": by_type,
        "by_topic": sorted(by_topic.items(), key=lambda x: x[1], reverse=True),
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

