"""
signals.db - schema and query helpers for article signal extraction.
Stored separately from events.db to keep enrichment independent
from Market Radar's operational data.
"""
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / "signals.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS article_signals (
            id                      TEXT PRIMARY KEY,
            title                   TEXT,
            source                  TEXT,
            date_published          TEXT,
            theme_id                TEXT,

            -- Layer 1: raw extraction
            entities                TEXT DEFAULT '[]',
            actions                 TEXT DEFAULT '[]',
            quantitative            TEXT DEFAULT '[]',

            -- Layer 2: semantic mapping
            sector_signals          TEXT DEFAULT '[]',
            signal_types            TEXT DEFAULT '[]',
            dominant_theme          TEXT,
            summary_signal          TEXT,

            -- Layer 3: composite scores
            geopolitical_risk_score REAL DEFAULT 0.0,
            market_impact_score     REAL DEFAULT 0.0,

            -- Metadata
            enriched_at             TEXT,
            model                   TEXT,
            failed                  INTEGER DEFAULT 0,
            error                   TEXT,
            raw_output              TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_signals_date
            ON article_signals(date_published);
        CREATE INDEX IF NOT EXISTS idx_signals_theme
            ON article_signals(theme_id);
        CREATE INDEX IF NOT EXISTS idx_signals_dominant
            ON article_signals(dominant_theme);
        CREATE INDEX IF NOT EXISTS idx_signals_impact
            ON article_signals(market_impact_score);
        CREATE INDEX IF NOT EXISTS idx_signals_failed
            ON article_signals(failed);

        CREATE TABLE IF NOT EXISTS enrichment_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            scope_days      INTEGER,
            processed       INTEGER DEFAULT 0,
            succeeded       INTEGER DEFAULT 0,
            failed          INTEGER DEFAULT 0,
            skipped         INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'running',
            error           TEXT
        );
        """
        )
    logger.info("[signals_db] Database initialised at %s", DB_PATH)


def upsert_signal(signal: Dict[str, Any]) -> None:
    """Insert or replace an article signal record."""
    with get_conn() as conn:
        conn.execute(
            """
        INSERT OR REPLACE INTO article_signals (
            id, title, source, date_published, theme_id,
            entities, actions, quantitative,
            sector_signals, signal_types, dominant_theme, summary_signal,
            geopolitical_risk_score, market_impact_score,
            enriched_at, model, failed, error, raw_output
        ) VALUES (
            :id, :title, :source, :date_published, :theme_id,
            :entities, :actions, :quantitative,
            :sector_signals, :signal_types, :dominant_theme, :summary_signal,
            :geopolitical_risk_score, :market_impact_score,
            :enriched_at, :model, :failed, :error, :raw_output
        )
        """,
            {
                **signal,
                "entities": json.dumps(signal.get("entities", [])),
                "actions": json.dumps(signal.get("actions", [])),
                "quantitative": json.dumps(signal.get("quantitative", [])),
                "sector_signals": json.dumps(signal.get("sector_signals", [])),
                "signal_types": json.dumps(signal.get("signal_types", [])),
            },
        )


def get_enriched_ids() -> set:
    """Return set of content_hash IDs already enriched (including failed)."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id FROM article_signals").fetchall()
    return {row["id"] for row in rows}


def get_signals(
    sector: Optional[str] = None,
    signal_type: Optional[str] = None,
    min_confidence: float = 0.5,
    min_impact: float = 0.0,
    days: int = 7,
    limit: int = 50,
    failed: bool = False,
) -> List[Dict]:
    """
    Query signals with filters.
    sector: dot notation e.g. "energy_markets.crude_oil" or just "energy_markets"
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()[:10]

    with get_conn() as conn:
        rows = conn.execute(
            """
        SELECT * FROM article_signals
        WHERE failed = ?
          AND (date_published >= ? OR date_published IS NULL)
          AND market_impact_score >= ?
        ORDER BY market_impact_score DESC, date_published DESC
        LIMIT ?
        """,
            (1 if failed else 0, cutoff, min_impact, limit * 3),
        ).fetchall()

    results = []
    for row in rows:
        r = dict(row)
        r["entities"] = json.loads(r.get("entities") or "[]")
        r["actions"] = json.loads(r.get("actions") or "[]")
        r["quantitative"] = json.loads(r.get("quantitative") or "[]")
        r["sector_signals"] = json.loads(r.get("sector_signals") or "[]")
        r["signal_types"] = json.loads(r.get("signal_types") or "[]")

        if sector:
            matching = [
                s
                for s in r["sector_signals"]
                if (sector in s.get("sector", ""))
                and s.get("confidence", 0) >= min_confidence
            ]
            if not matching:
                continue
            r["matched_sectors"] = matching

        if signal_type and signal_type not in r.get("signal_types", []):
            continue

        results.append(r)
        if len(results) >= limit:
            break

    return results


def get_sector_summary(days: int = 7) -> List[Dict]:
    """
    Return aggregated sector signal counts and average sentiment
    for the last N days. Used for the signals dashboard.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()[:10]

    with get_conn() as conn:
        rows = conn.execute(
            """
        SELECT sector_signals, geopolitical_risk_score, market_impact_score
        FROM article_signals
        WHERE failed = 0
          AND (date_published >= ? OR date_published IS NULL)
        """,
            (cutoff,),
        ).fetchall()

    sector_stats: Dict[str, Dict] = {}
    for row in rows:
        signals = json.loads(row["sector_signals"] or "[]")
        for s in signals:
            sector = s.get("sector", "")
            if not sector:
                continue
            if sector not in sector_stats:
                sector_stats[sector] = {
                    "sector": sector,
                    "count": 0,
                    "bullish": 0,
                    "bearish": 0,
                    "neutral": 0,
                    "avg_confidence": 0.0,
                    "total_confidence": 0.0,
                }
            st = sector_stats[sector]
            st["count"] += 1
            st["total_confidence"] += s.get("confidence", 0)
            direction = s.get("direction", "neutral")
            if direction in st:
                st[direction] += 1

    result = []
    for _, st in sector_stats.items():
        if st["count"] > 0:
            st["avg_confidence"] = round(st["total_confidence"] / st["count"], 2)
            total_directional = st["bullish"] + st["bearish"]
            if total_directional > 0:
                st["sentiment_score"] = round(
                    (st["bullish"] - st["bearish"]) / total_directional, 2
                )
            else:
                st["sentiment_score"] = 0.0
            del st["total_confidence"]
            result.append(st)

    return sorted(result, key=lambda x: -x["count"])


def get_run_stats() -> Optional[Dict]:
    """Return the most recent enrichment run stats."""
    with get_conn() as conn:
        row = conn.execute(
            """
        SELECT * FROM enrichment_runs
        ORDER BY id DESC LIMIT 1
        """
        ).fetchone()
    return dict(row) if row else None


def start_run(scope_days: int) -> int:
    """Record the start of an enrichment run. Returns run ID."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO enrichment_runs (started_at, scope_days, status) VALUES (?, ?, 'running')",
            (now, scope_days),
        )
        return cursor.lastrowid


def finish_run(
    run_id: int,
    processed: int,
    succeeded: int,
    failed: int,
    skipped: int,
    status: str = "success",
    error: str = None,
) -> None:
    """Update enrichment run on completion."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with get_conn() as conn:
        conn.execute(
            """
        UPDATE enrichment_runs
        SET finished_at=?, processed=?, succeeded=?, failed=?,
            skipped=?, status=?, error=?
        WHERE id=?
        """,
            (now, processed, succeeded, failed, skipped, status, error, run_id),
        )
