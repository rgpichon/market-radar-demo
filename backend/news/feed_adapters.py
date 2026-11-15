import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime as _rfc2822_parse
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

import requests

try:
    import yfinance
except ImportError:  # optional for portfolio demo / lean deploys
    yfinance = None  # type: ignore

logger = logging.getLogger(__name__)
_NEUTRAL_OLD_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SECTOR_FROM_THEME_SECTOR = {
    "Semiconductors": "Technology",
    "Technology Hardware": "Technology",
    "Data Centers": "Technology",
    "Software": "Technology",
    "Cybersecurity": "Technology",
    "Energy": "Energy",
    "Renewable Energy": "Energy",
    "Utilities": "Energy",
    "Materials": "Energy",
    "Mining": "Energy",
    "Agriculture": "Energy",
    "Consumer": "Macro",
    "Industrials": "Macro",
    "Real Estate": "Macro",
    "REITs": "Macro",
    "Healthcare": "Macro",
    "Pharmaceuticals": "Macro",
    "Biotechnology": "Macro",
    "Medical Devices": "Macro",
    "Insurance": "Macro",
    "Aerospace & Defense": "Geopolitics",
    "Banks": "Fixed Income",
    "Fintech": "Fixed Income",
}

SOURCE_DISPLAY_NAMES = {
    # Signal RSS slugs -> display names
    "fed_speeches_rss": "Federal Reserve",
    "ecb_press_rss": "ECB",
    "ecb_speeches_rss": "ECB",
    "bis_working_papers_rss": "BIS",
    "bis_research_rss": "BIS",
    "foreign_affairs_rss": "Foreign Affairs",
    "project_syndicate_rss": "Project Syndicate",
    "cfr_rss": "CFR",
    "chatham_house_rss": "Chatham House",
    "politico_world_rss": "Politico",
    "mit_tech_review_rss": "MIT Technology Review",
    "ars_technica_rss": "Ars Technica",
    "the_verge_rss": "The Verge",
    "wired_rss": "Wired",
    "techcrunch_rss": "TechCrunch",
    "carbon_brief_rss": "Carbon Brief",
    "iea_rss": "IEA",
    "energy_monitor_rss": "Energy Monitor",
    "bloomberg_green_rss": "Bloomberg Green",
    "bbc_world_rss": "BBC World",
    "bbc_business_rss": "BBC Business",
    "guardian_world_rss": "The Guardian",
    "guardian_business_rss": "The Guardian",
    "economist_rss": "The Economist",
    "nyt_world_rss": "The New York Times",
    "nyt_business_rss": "The New York Times",
    "ft_world_rss": "Financial Times",
    "vox_rss": "Vox",
    # Common Google News source name cleanups
    "CNBC Top News": "CNBC",
    "CNBC World News": "CNBC",
    "CNBC Economy": "CNBC",
    "Bloomberg Markets": "Bloomberg",
    "Bloomberg Technology": "Bloomberg",
    "Bloomberg Politics": "Bloomberg",
    "MarketWatch Top Stories": "MarketWatch",
    "Seeking Alpha Market News": "Seeking Alpha",
    "The New York Times": "NYT",
    "Financial Times": "FT",
    "The Wall Street Journal": "WSJ",
    "European Central Bank": "ECB",
    "Federal Reserve Board (.gov)": "Federal Reserve",
    "Federal Reserve Bank of Cleveland": "Fed Cleveland",
    "Federal Reserve Bank of Dallas": "Fed Dallas",
    "U.S. Energy Information Administration (EIA) (.gov)": "EIA",
    "North Atlantic Treaty Organization": "NATO",
    "The World Economic Forum": "WEF",
    # Event source cleanups
    "ECB": "ECB",
    "BIS IFC": "BIS",
    "NBER": "NBER",
    "IIF": "IIF",
    "ICMA": "ICMA",
    "Brookings Institution": "Brookings",
    "Bruegel": "Bruegel",
    "CSIS": "CSIS",
    "MIT Sloan": "MIT Sloan",
    "Oxford Said Business School": "Oxford Saïd",
    "Imperial College Business School": "Imperial",
    "Cambridge Judge Business School": "Cambridge Judge",
}


class RawItem(TypedDict):
    item_type: str  # "article", "event", or "signal"
    title: str
    url: str
    source_name: str
    source_tier: int  # 1=primary, 2=secondary, 3=general. Events default to 1.
    date_published: str  # ISO 8601 string, UTC, e.g. "2025-03-20T14:30:00Z"
    description: str  # Short summary or description, max ~500 chars
    topic: str  # Theme name, event tag, or signal label
    score: float  # Match score, signal score, or event signal_score
    extra: dict  # Any additional fields (theme_id, event_id, intel_type, etc.)


# sys.path injection for reports/ (local monorepo only — skipped in cloud demo)
_REPORTS_AVAILABLE = False
try:
    _here = Path(__file__).resolve()
    if len(_here.parents) > 4:
        _REPORTS_BACKEND = _here.parents[4] / "Reports" / "tool" / "backend"
        if _REPORTS_BACKEND.is_dir() and str(_REPORTS_BACKEND) not in sys.path:
            sys.path.insert(0, str(_REPORTS_BACKEND))
        from adapters.rss_adapter import fetch_rss
        from adapters.google_news_adapter import fetch_google_news_for_themes
        from theme_matcher import match_article_to_themes

        _REPORTS_AVAILABLE = True
except (ImportError, IndexError) as e:
    logging.warning(f"[feed_adapters] reports/ not importable: {e}. Article feed disabled.")
    _REPORTS_AVAILABLE = False


def _parse_article_date(date_str: str):
    if not date_str:
        return None
    max_future = datetime.now(timezone.utc) + timedelta(days=1)

    def _normalize_and_guard(parsed_date: Optional[datetime]) -> Optional[datetime]:
        if parsed_date is None:
            return None
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        else:
            parsed_date = parsed_date.astimezone(timezone.utc)
        if parsed_date > max_future:
            return None
        return parsed_date

    try:
        return _normalize_and_guard(datetime.fromisoformat(date_str.replace("Z", "+00:00")))
    except (ValueError, AttributeError):
        pass
    try:
        return _normalize_and_guard(_rfc2822_parse(date_str))
    except Exception:
        pass
    return None


def _parse_date_utc_no_future_guard(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass
    try:
        dt = _rfc2822_parse(str(date_str))
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        pass
    return None


def _is_recent(dt: Optional[datetime], max_age_days: int) -> bool:
    if dt is None:
        return True
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= (now - timedelta(days=max_age_days))


def _build_theme_sector_map() -> Dict[str, str]:
    try:
        candidates = []
        env_path = os.environ.get("MARKET_RADAR_THEMES_JSON")
        if env_path:
            candidates.append(Path(env_path))
        here = Path(__file__).resolve()
        candidates.extend(
            [
                here.parents[3] / "Reports" / "tool" / "data" / "themes.json",
                Path.home()
                / "Desktop"
                / "Projets"
                / "Trading"
                / "Reports"
                / "tool"
                / "data"
                / "themes.json",
            ]
        )
        themes_path = next((p for p in candidates if p.is_file()), None)
        if themes_path is None:
            return {}
        themes = json.loads(themes_path.read_text())
        result: Dict[str, str] = {}
        for t in themes:
            if not isinstance(t, dict):
                continue
            theme_id = str(t.get("id") or "").strip()
            if not theme_id:
                continue
            for sector_label in t.get("sectors", []):
                canonical = _SECTOR_FROM_THEME_SECTOR.get(str(sector_label))
                if canonical:
                    result[theme_id] = canonical
                    break
            if theme_id not in result:
                result[theme_id] = "Other"
        return result
    except Exception as e:
        import sys
        print(f'[feed_adapters] theme map build failed: {e}', file=sys.stderr)
        return {}


_THEME_SECTOR_MAP = _build_theme_sector_map()
if not _THEME_SECTOR_MAP:
    import sys
    print('[feed_adapters] WARNING: _THEME_SECTOR_MAP is empty', file=sys.stderr)
else:
    mapped = sum(1 for v in _THEME_SECTOR_MAP.values() if v != 'Other')
    print(f'[feed_adapters] theme map loaded: {mapped}/{len(_THEME_SECTOR_MAP)} themes mapped to sectors', file=sys.stderr)


def _sector_from_dominant_theme(value: Any) -> str:
    s = str(value or "").strip().lower()
    if not s:
        return "Other"
    if any(n in s for n in ("technology", "ai", "semiconductor")):
        return "Technology"
    if any(n in s for n in ("energy", "oil", "crude", "renewabl", "gas")):
        return "Energy"
    if any(n in s for n in ("geopolit", "middle_east", "defense", "us_china")):
        return "Geopolitics"
    if any(n in s for n in ("macro", "gdp", "recession", "credit", "sovereign")):
        return "Macro"
    if any(n in s for n in ("fixed_income", "central_bank", "rate", "treasury")):
        return "Fixed Income"
    if any(n in s for n in ("equit", "private_equity", "private_market", "ipo")):
        return "Equities"
    return "Other"


def _sector_from_text(*parts: Any) -> str:
    text = " ".join(str(p or "") for p in parts).lower()
    if any(n in text for n in ("technology", "ai", "semiconductor", "chip", "software", "cloud", "gpu")):
        return "Technology"
    if any(n in text for n in ("energy", "oil", "crude", "renewabl", "gas", "opec", "lng")):
        return "Energy"
    if any(n in text for n in ("geopolit", "middle east", "defense", "us-china", "us china", "sanction", "war", "nato")):
        return "Geopolitics"
    if any(n in text for n in ("fixed income", "bond")):
        return "Fixed Income"
    if any(
        n in text
        for n in (
            "macro",
            "recession",
            "gdp",
            "inflation",
            "federal reserve",
            "fed ",
            "interest rate",
            "treasury",
            "yield",
            "economy",
            "economic",
            "growth",
            "fiscal",
            "debt",
            "credit",
            "consumer",
            "housing",
            "employment",
            "jobs",
            "labor",
            "wage",
            "market",
            "stocks",
            "s&p",
            "dow",
            "nasdaq",
            "earnings",
            "analyst",
            "outlook",
            "forecast",
            "monetary",
            "central bank",
            "ecb",
            "boe",
            "sovereign",
            "cpi",
        )
    ):
        return "Macro"
    if any(n in text for n in ("equit", "private equity", "private market", "ipo", "stock market")):
        return "Equities"
    if any(
        n in text
        for n in (
            "bloomberg",
            "reuters",
            "wsj",
            "wall street journal",
            "ft",
            "financial times",
            "cnbc",
            "yahoo finance",
            "marketwatch",
            "seeking alpha",
        )
    ):
        return "Macro"
    return "Other"


def fetch_articles_from_reports(
    max_age_days: int = 60,
    min_score: float = 5.0,
) -> List[RawItem]:
    try:
        path = (
            Path(__file__).resolve().parents[4]
            / "Reports"
            / "tool"
            / "backend"
            / "data"
            / "evidence.json"
        )
        if not path.exists():
            logger.warning("[feed_adapters] evidence.json not found: %s", str(path))
            return []

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.warning("[feed_adapters] evidence.json malformed (not a list): %s", str(path))
            return []

        out: List[RawItem] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            try:
                score = float(item.get("matchScore") or 0.0)
            except Exception:
                score = 0.0
            if score < float(min_score):
                continue

            review_status = str(item.get("reviewStatus") or "").strip().lower()
            if review_status == "rejected":
                continue

            dp = item.get("datePublished") or ""
            dt = _parse_article_date(str(dp)) if dp else None
            if dt is None:
                # Keep item visible when source date is malformed/unparseable,
                # but push recency lower with a neutral old date.
                dt_for_feed = _NEUTRAL_OLD_DATE
            else:
                dt_for_feed = dt
            if dt is not None and not _is_recent(dt, max_age_days):
                continue

            date_published = dt_for_feed.isoformat().replace("+00:00", "Z")

            theme_id = str(item.get("themeId") or "")
            raw_source = (item.get("source") or {}).get("name", "") or item.get("sourceName", "")
            source_name = SOURCE_DISPLAY_NAMES.get(raw_source, raw_source)
            topic = _THEME_SECTOR_MAP.get(theme_id, "Other")
            url = (
                item.get("url")
                or item.get("link")
                or item.get("articleUrl")
                or item.get("sourceUrl")
                or (item.get("source") or {}).get("url")
                or ""
            ).strip()
            title = str(item.get("title") or "").strip()
            raw_desc = (
                item.get("summary")
                or item.get("description")
                or item.get("snippet")
                or item.get("excerpt")
                or item.get("content")
                or item.get("text")
                or ""
            )
            desc = str(raw_desc).strip()
            if desc and title:
                title_l = title.lower().strip()
                desc_l = desc.lower().strip()
                # Remove common "title + separator + snippet" patterns.
                for sep in (" - ", " — ", " | ", ": "):
                    prefix = title_l + sep
                    if desc_l.startswith(prefix):
                        desc = desc[len(prefix):].strip()
                        break
                # If description is just the title (or near-identical), drop it.
                if desc_l == title_l or desc_l in title_l or title_l in desc_l:
                    if len(desc) <= len(title) + 10:
                        desc = ""

            feed_item = {
                "item_type": "article",
                "type": "article",
                "title": title,
                "url": str(url),
                "source_name": str(source_name or "Unknown"),
                "source_tier": int(((item.get("source") or {}).get("tier")) or item.get("sourceTier") or 3),
                "date_published": date_published,
                "description": desc[:500],
                "topic": topic,
                "score": score,
                "extra": {
                    "sentiment": str(item.get("sentiment") or ""),
                    "theme_id": theme_id,
                },
            }
            out.append(feed_item)

        return out
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_reports failed: %s", e)
        return []


def fetch_articles_from_signal_rss(
    max_age_days: int = 7,
) -> List[RawItem]:
    try:
        path = (
            Path(__file__).resolve().parents[4]
            / "Research Interface"
            / "signals"
            / "config"
            / "sources.yaml"
        )
        if not path.exists():
            logger.warning("[feed_adapters] signal sources.yaml not found: %s", str(path))
            return []

        try:
            import yaml  # type: ignore
        except Exception as e:
            logger.warning("[feed_adapters] PyYAML not available (%s); signal RSS disabled.", e)
            return []

        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        rss_sources = []
        if isinstance(cfg, dict) and isinstance(cfg.get("rss"), list):
            rss_sources = [s for s in cfg.get("rss") if isinstance(s, dict)]
        elif isinstance(cfg, dict) and isinstance(cfg.get("sources"), list):
            for s in cfg.get("sources") or []:
                if not isinstance(s, dict):
                    continue
                stype = (s.get("type") or "").strip().lower()
                if stype == "rss":
                    rss_sources.append(s)

        if not rss_sources:
            return []

        out: List[RawItem] = []

        for src in rss_sources:
            name = (src.get("name") or src.get("id") or "RSS").strip() if isinstance(src, dict) else "RSS"
            url = (src.get("url") or "").strip() if isinstance(src, dict) else ""
            if not url:
                continue
            tier = src.get("tier")
            try:
                tier_i = int(tier) if tier is not None else 2
            except Exception:
                tier_i = 2

            articles = []
            if _REPORTS_AVAILABLE:
                articles, err, _bozo = fetch_rss({"url": url, "name": name, "tier": tier_i})
                if err:
                    logger.warning("[feed_adapters] signal RSS fetch failed for %s: %s", url, err)
                    continue
            else:
                try:
                    import feedparser  # local import per requirement

                    feed = feedparser.parse(url)
                    for entry in getattr(feed, "entries", None) or []:
                        title = (getattr(entry, "title", None) or "").strip()
                        link = (getattr(entry, "link", None) or "").strip()
                        raw_summary = getattr(entry, "summary", None) or getattr(entry, "description", None) or ""
                        desc = str(raw_summary)
                        published = getattr(entry, "published", None) or getattr(entry, "updated", None) or ""
                        articles.append(
                            {
                                "title": title,
                                "url": link,
                                "datePublished": str(published),
                                "description": desc,
                                "sourceName": name,
                                "sourceTier": tier_i,
                            }
                        )
                except Exception as e:
                    logger.warning("[feed_adapters] signal RSS fallback parse failed for %s: %s", url, e)
                    continue

            for a in articles or []:
                if not isinstance(a, dict):
                    continue
                dp = str(a.get("datePublished") or "")
                dt = _parse_article_date(dp)
                if dt is None:
                    dt_for_feed = _NEUTRAL_OLD_DATE
                else:
                    dt_for_feed = dt
                if dt is not None and not _is_recent(dt, max_age_days):
                    continue

                source_name = SOURCE_DISPLAY_NAMES.get(str(a.get("sourceName") or name), str(a.get("sourceName") or name))
                inferred_topic = _sector_from_text(a.get("title"), a.get("description"), source_name, name)
                out.append(
                    {
                        "item_type": "article",
                        "type": "article",
                        "title": str(a.get("title") or ""),
                        "url": str(a.get("url") or ""),
                        "source_name": source_name,
                        "source_tier": int(a.get("sourceTier") or tier_i),
                        "date_published": dt_for_feed.isoformat().replace("+00:00", "Z"),
                        "description": str(a.get("description") or "")[:500],
                        "topic": inferred_topic,
                        "score": 1.0,
                        "extra": {"signal_source": name, "signal_url": url},
                    }
                )

        return out
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_signal_rss failed: %s", e)
        return []


def fetch_articles_from_signals_db(
    max_age_days: int = 7,
) -> List[RawItem]:
    try:
        db_path = Path(__file__).resolve().parents[1] / "signals.db"
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT title, source, date_published, dominant_theme, market_impact_score, failed
                FROM article_signals
                WHERE failed = 0
                """
            ).fetchall()
        finally:
            conn.close()

        out: List[RawItem] = []
        for row in rows or []:
            dp = str(row["date_published"] or "")
            dt = _parse_article_date(dp)
            dt_for_feed = dt if dt is not None else _NEUTRAL_OLD_DATE
            if dt is not None and not _is_recent(dt, max_age_days):
                continue
            topic = _sector_from_dominant_theme(row["dominant_theme"])
            source_name = SOURCE_DISPLAY_NAMES.get(str(row["source"] or ""), str(row["source"] or "Signals"))
            try:
                score = float(row["market_impact_score"] or 0.0)
            except Exception:
                score = 0.0
            out.append(
                {
                    "item_type": "article",
                    "type": "article",
                    "title": str(row["title"] or ""),
                    "url": "",
                    "source_name": source_name,
                    "source_tier": 2,
                    "date_published": dt_for_feed.isoformat().replace("+00:00", "Z"),
                    "description": "",
                    "topic": topic,
                    "score": score,
                    "extra": {"dominant_theme": str(row["dominant_theme"] or "")},
                }
            )
        return out
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_signals_db failed: %s", e)
        return []


def fetch_events_from_radar(
    days_ahead: int = 30,
    days_behind: int = 3,
    min_signal_score: float = 0.0,
    limit: int = 200,
) -> List[RawItem]:
    try:
        db_path = Path(__file__).resolve().parents[1] / "events.db"
        if not db_path.exists():
            logger.warning("[feed_adapters] events.db not found: %s", str(db_path))
            return []

        now = datetime.now(timezone.utc)
        from_dt = (now - timedelta(days=days_behind)).isoformat()
        to_dt = (now + timedelta(days=days_ahead)).isoformat()

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT
                        id,
                        event_name,
                        firm_name,
                        date_time,
                        link,
                        description,
                        tags,
                        intel_type,
                        signal_score,
                        format,
                        location
                    FROM events
                    WHERE
                        date_time IS NOT NULL
                        AND date_time != ''
                        AND date_time >= :from_dt
                        AND date_time <= :to_dt
                        AND (signal_score IS NULL OR signal_score >= :min_score)
                    ORDER BY
                        CASE WHEN date_time IS NULL OR date_time = '' THEN 1 ELSE 0 END,
                        date_time ASC
                    LIMIT :limit
                    """,
                    {"from_dt": from_dt, "to_dt": to_dt, "min_score": float(min_signal_score), "limit": int(limit)},
                )
            except sqlite3.OperationalError:
                # Workspace schema uses tags_json and location_text instead of tags/location
                cur.execute(
                    """
                    SELECT
                        id,
                        event_name,
                        firm_name,
                        date_time,
                        link,
                        description,
                        tags_json AS tags,
                        intel_type,
                        signal_score,
                        format,
                        location_text AS location
                    FROM events
                    WHERE
                        date_time IS NOT NULL
                        AND date_time != ''
                        AND date_time >= :from_dt
                        AND date_time <= :to_dt
                        AND (signal_score IS NULL OR signal_score >= :min_score)
                    ORDER BY
                        CASE WHEN date_time IS NULL OR date_time = '' THEN 1 ELSE 0 END,
                        date_time ASC
                    LIMIT :limit
                    """,
                    {"from_dt": from_dt, "to_dt": to_dt, "min_score": float(min_signal_score), "limit": int(limit)},
                )

            rows = cur.fetchall()
            cur.close()
        finally:
            conn.close()

        out: List[RawItem] = []
        for row in rows or []:
            tags_raw = row["tags"] if "tags" in row.keys() else None
            tags_list: List[str] = []
            if tags_raw:
                try:
                    parsed = json.loads(tags_raw)
                    if isinstance(parsed, list):
                        tags_list = [str(x).strip() for x in parsed if str(x).strip()]
                    elif isinstance(parsed, str):
                        tags_list = [t.strip() for t in parsed.split(",") if t.strip()]
                except Exception:
                    tags_list = [t.strip() for t in str(tags_raw).split(",") if t.strip()]

            topic = tags_list[0] if tags_list else ""

            try:
                score = float(row["signal_score"] or 0.0)
            except Exception:
                score = 0.0

            raw_firm = str(row["firm_name"] or "Unknown")
            out.append(
                {
                    "item_type": "event",
                    "title": str(row["event_name"] or ""),
                    "url": str(row["link"] or ""),
                    "source_name": SOURCE_DISPLAY_NAMES.get(raw_firm, raw_firm),
                    "source_tier": 1,
                    "date_published": str(row["date_time"] or ""),
                    "description": str(row["description"] or "")[:500],
                    "topic": topic,
                    "score": score,
                    "extra": {
                        "event_id": str(row["id"]),
                        "intel_type": str(row["intel_type"] or ""),
                        "format": str(row["format"] or ""),
                        "location": str(row["location"] or ""),
                        "firm_name": str(row["firm_name"] or ""),
                    },
                }
            )

        return out
    except Exception as e:
        logger.warning("[feed_adapters] fetch_events_from_radar failed: %s", e)
        return []


def fetch_market_signals(
    instruments: Optional[List[str]] = None,
) -> List[RawItem]:
    DEFAULT_INSTRUMENTS = [
        "^GSPC",
        "^TNX",
        "^VIX",
        "DX-Y.NYB",
        "GC=F",
        "CL=F",
        "BTC-USD",
    ]
    DISPLAY_NAMES = {
        "^GSPC": "S&P 500",
        "^TNX": "10Y Treasury",
        "^VIX": "VIX",
        "DX-Y.NYB": "US Dollar",
        "GC=F": "Gold",
        "CL=F": "Crude Oil",
        "BTC-USD": "Bitcoin",
    }

    if yfinance is None:
        logger.warning("[feed_adapters] yfinance not installed — skipping market signals")
        return []

    syms = instruments if instruments else DEFAULT_INSTRUMENTS
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    out: List[RawItem] = []

    for sym in syms:
        try:
            ticker = yfinance.Ticker(sym)
            hist = ticker.history(period="5d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                logger.warning("[feed_adapters] yfinance empty for %s", sym)
                continue

            closes = [float(x) for x in hist["Close"].tolist() if x is not None]
            if len(closes) < 2:
                logger.warning("[feed_adapters] yfinance insufficient data for %s", sym)
                continue

            latest = closes[-1]
            base = closes[0]
            pct = 0.0
            if base != 0:
                pct = round(((latest / base) - 1.0) * 100.0, 2)

            direction = "flat"
            if pct > 0:
                direction = "up"
            elif pct < 0:
                direction = "down"

            name = DISPLAY_NAMES.get(sym, sym)
            title = f"{name}: {latest:.2f} ({pct:+.2f}% 1w)"

            out.append(
                {
                    "item_type": "signal",
                    "title": title,
                    "url": "",
                    "source_name": "yfinance",
                    "source_tier": 1,
                    "date_published": now_iso,
                    "description": f"{direction.capitalize()} {abs(pct):.2f}% over past week",
                    "topic": "Market",
                    "score": float(abs(pct)),
                    "extra": {
                        "symbol": sym,
                        "latest_price": latest,
                        "pct_change_1w": pct,
                        "direction": direction,
                    },
                }
            )
        except Exception as e:
            logger.warning("[feed_adapters] yfinance failed for %s: %s", sym, e)
            continue

    return out


def ping_signal_enrichment(
    host: str = "http://localhost:8000",
    timeout: float = 2.0,
) -> bool:
    try:
        url = host.rstrip("/") + "/api/status"
        resp = requests.get(url, timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def fetch_all(
    articles_max_age_days: int = 7,
    events_days_ahead: int = 30,
    include_market_signals: bool = True,
) -> List[RawItem]:
    events: List[RawItem] = []
    reports_articles: List[RawItem] = []
    signal_articles: List[RawItem] = []
    db_signal_articles: List[RawItem] = []
    signals: List[RawItem] = []

    try:
        events = fetch_events_from_radar(days_ahead=events_days_ahead)
    except Exception as e:
        logger.warning("[feed_adapters] fetch_events_from_radar error: %s", e)

    try:
        reports_articles = fetch_articles_from_reports(max_age_days=max(articles_max_age_days, 60))
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_reports error: %s", e)

    try:
        signal_articles = fetch_articles_from_signal_rss(max_age_days=articles_max_age_days)
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_signal_rss error: %s", e)

    try:
        db_signal_articles = fetch_articles_from_signals_db(max_age_days=articles_max_age_days)
    except Exception as e:
        logger.warning("[feed_adapters] fetch_articles_from_signals_db error: %s", e)

    if include_market_signals:
        try:
            signals = fetch_market_signals()
        except Exception as e:
            logger.warning("[feed_adapters] fetch_market_signals error: %s", e)

    combined = [*events, *reports_articles, *signal_articles, *db_signal_articles, *signals]
    _max_date = datetime.now(timezone.utc) + timedelta(days=1)
    filtered_combined: List[RawItem] = []
    for i in combined:
        dp = str(i.get("date_published") or "")
        if not dp:
            filtered_combined.append(i)
            continue
        parsed = _parse_date_utc_no_future_guard(dp)
        if parsed is None:
            # Keep malformed/unknown dates; they are handled downstream.
            filtered_combined.append(i)
            continue
        if parsed <= _max_date:
            filtered_combined.append(i)
    combined = filtered_combined

    n_events = len(events)
    n_articles = len(reports_articles) + len(signal_articles) + len(db_signal_articles)
    n_signals = len(signals)
    logger.info(
        "[feed_adapters] fetch_all complete: %s events, %s articles, %s signals",
        n_events,
        n_articles,
        n_signals,
    )

    return combined

