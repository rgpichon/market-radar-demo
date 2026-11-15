"""
Flask blueprint for /api/signals/* endpoints.
"""
import json
import logging
import subprocess
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request
import requests

logger = logging.getLogger(__name__)
signals_bp = Blueprint("signals", __name__, url_prefix="/api/signals")
SECTOR_SCORES_PATH = Path(__file__).resolve().parents[1] / "data" / "sector_scores.json"
EVIDENCE_JSON_PATH = Path("/Users/raphael/Desktop/Trading/Reports/tool/backend/data/evidence.json")
SCORER_PYTHON = "/Users/raphael/Desktop/Trading/Market Radar/Codes/venv/bin/python"
SCORER_CWD = "/Users/raphael/Desktop/Trading/Market Radar/Codes/backend"


def _evidence_items_list(raw) -> list:
    """Normalize evidence.json root to a list of items."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "articles", "evidence", "data"):
            v = raw.get(key)
            if isinstance(v, list):
                return v
        return []
    return []


def _evidence_match_score(item: dict) -> float:
    """Sort key: top-level matchScore, else matchDetails.combinedScore, else matchDetails.score."""
    ms = item.get("matchScore")
    if ms is not None:
        try:
            return float(ms)
        except (TypeError, ValueError):
            pass
    md = item.get("matchDetails") or {}
    if isinstance(md, dict):
        for key in ("combinedScore", "score"):
            v = md.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
    return 0.0


def _truncate_summary(text, max_len: int = 200) -> str:
    if not text:
        return ""
    s = str(text).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


@signals_bp.route("/summary")
def signals_summary():
    """Sector signal summary for last N days."""
    from backend.news.signals_db import get_run_stats, get_sector_summary, init_db

    init_db()
    days = int(request.args.get("days", 7))
    summary = get_sector_summary(days=days)
    run = get_run_stats()
    return jsonify({"sectors": summary, "last_run": run, "days": days})


@signals_bp.route("/search")
def signals_search():
    """Query signals by sector, signal type, confidence."""
    from backend.news.signals_db import get_signals, init_db

    init_db()
    sector = request.args.get("sector")
    signal_type = request.args.get("type")
    min_conf = float(request.args.get("min_confidence", 0.5))
    min_impact = float(request.args.get("min_impact", 0.0))
    days = int(request.args.get("days", 7))
    limit = min(int(request.args.get("limit", 20)), 100)
    results = get_signals(
        sector=sector,
        signal_type=signal_type,
        min_confidence=min_conf,
        min_impact=min_impact,
        days=days,
        limit=limit,
    )
    return jsonify({"items": results, "total": len(results)})


@signals_bp.route("/article/<content_hash>")
def signal_for_article(content_hash):
    """Get signal for a specific article by content hash."""
    import json as _json

    from backend.news.signals_db import get_conn, init_db

    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM article_signals WHERE id = ?", (content_hash,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    r = dict(row)
    for field in ["entities", "actions", "quantitative", "sector_signals", "signal_types"]:
        r[field] = _json.loads(r.get(field) or "[]")
    return jsonify(r)


@signals_bp.route("/enrich", methods=["POST"])
def trigger_enrichment():
    """
    Trigger article enrichment in background thread.
    Body: {"scope_days": 7, "max_articles": 50}
    """
    import threading

    from backend.news.signals_db import get_conn, init_db

    init_db()
    body = request.get_json(silent=True) or {}
    scope_days = int(body.get("scope_days", 7))
    max_articles = body.get("max_articles")

    with get_conn() as conn:
        running = conn.execute(
            "SELECT id FROM enrichment_runs WHERE status='running' LIMIT 1"
        ).fetchone()
    if running:
        return jsonify({"started": False, "message": "Enrichment already running"})

    def _run():
        try:
            from backend.news.article_enricher import run_enrichment

            run_enrichment(scope_days=scope_days, max_articles=max_articles)
        except Exception as e:
            import traceback

            logger.error(
                "[signals] Enrichment thread failed: %s\n%s",
                e,
                traceback.format_exc(),
            )

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify(
        {
            "started": True,
            "scope_days": scope_days,
            "max_articles": max_articles,
            "message": "Enrichment running - poll /api/signals/status",
        }
    )


@signals_bp.route("/status")
def enrichment_status():
    """Current enrichment run status."""
    from backend.news.signals_db import get_conn, get_run_stats, init_db

    init_db()
    run = get_run_stats()

    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM article_signals").fetchone()[0]
        succeeded = conn.execute("SELECT COUNT(*) FROM article_signals WHERE failed=0").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM article_signals WHERE failed=1").fetchone()[0]

    return jsonify(
        {
            "last_run": run,
            "total_enriched": total,
            "succeeded": succeeded,
            "failed": failed,
        }
    )


@signals_bp.route("/theme-articles")
def theme_articles():
    """Articles from evidence.json for a single themeId."""
    theme_id = request.args.get("themeId")
    if not theme_id:
        return jsonify({"error": "themeId required"}), 400
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))

    if not EVIDENCE_JSON_PATH.exists():
        return jsonify({"themeId": str(theme_id), "article_count": 0, "articles": []})

    try:
        with EVIDENCE_JSON_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.exception("[signals] Failed to read evidence.json")
        return jsonify({"error": str(e)}), 500

    items = _evidence_items_list(raw)
    matching = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("themeId") or "") != str(theme_id):
            continue
        matching.append(it)

    matching.sort(key=lambda x: _evidence_match_score(x), reverse=True)
    total = len(matching)
    limited = matching[:limit]

    out_articles = []
    for it in limited:
        src = it.get("source") or {}
        if not isinstance(src, dict):
            src = {}
        summary_raw = it.get("summary") or ""
        aid = str(it.get("id") or it.get("contentHash") or "")
        out_articles.append(
            {
                "id": aid,
                "title": str(it.get("title") or ""),
                "source_name": str(src.get("name") or ""),
                "source_url": str(src.get("url") or ""),
                "date_published": str(it.get("datePublished") or ""),
                "sentiment": str(it.get("sentiment") or ""),
                "match_score": _evidence_match_score(it),
                "summary": _truncate_summary(summary_raw, 200),
            }
        )

    return jsonify(
        {
            "themeId": str(theme_id),
            "article_count": total,
            "articles": out_articles,
        }
    )


@signals_bp.route("/theme-brief", methods=["POST"])
def theme_brief():
    body = request.get_json(silent=True) or {}
    theme_id = str(body.get("themeId") or "").strip()
    theme_name = str(body.get("themeName") or "").strip()
    articles = body.get("articles") or []

    if not theme_id or not isinstance(articles, list) or not articles:
        return jsonify({"error": "themeId and articles are required"}), 400

    trimmed_articles = []
    for a in articles[:15]:
        if not isinstance(a, dict):
            continue
        trimmed_articles.append(
            {
                "title": str(a.get("title") or "").strip(),
                "summary": str(a.get("summary") or "").strip(),
                "source_name": str(a.get("source_name") or "").strip(),
                "date_published": str(a.get("date_published") or "").strip(),
                "sentiment": str(a.get("sentiment") or "neutral").strip(),
            }
        )
    if not trimmed_articles:
        return jsonify({"error": "themeId and articles are required"}), 400

    system_prompt = (
        "You are a financial analyst writing a concise intelligence brief.\n"
        "Write in a direct, professional tone. No disclaimers. No preamble.\n"
        "Always cite your sources using [N] notation where N is the\n"
        "1-based article index. Every factual claim must have a citation.\n"
        "Do not include any preamble, introduction, or title.\n"
        "Start directly with the first paragraph of analysis.\n"
        "Do not repeat the theme name as a heading."
    )

    lines = [
        f"Theme: {theme_name or theme_id}",
        "",
        f"Here are {len(trimmed_articles)} recent articles on this theme:",
        "",
    ]
    for i, a in enumerate(trimmed_articles, start=1):
        lines.extend(
            [
                f"[{i}] {a['source_name']} | {a['date_published']} | {a['sentiment']}",
                a["title"],
                a["summary"],
                "",
            ]
        )
    lines.extend(
        [
            "Important: Begin your response immediately with the first",
            "paragraph. Do not write any title, heading, or intro sentence.",
            "",
            "Write a 3-paragraph intelligence brief covering:",
            "1. What is happening right now in this theme (key developments)",
            "2. What the market/geopolitical implications are",
            "3. What to watch next (key risks or catalysts)",
            "",
            "Use [N] citations for every claim. End with:",
            "CITED: comma-separated list of article numbers you used",
        ]
    )
    user_prompt = "\n".join(lines)

    prompt = f"{system_prompt}\n\n{user_prompt}"
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "temperature": 0.2,
                "num_predict": 800,
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        return jsonify({"error": f"Brief generation failed: {e}"}), 500

    response_text = str(payload.get("response") or "").strip()
    # Extract cited indices.
    cited_match = re.search(r"CITED:\s*([\d,\s]+)", response_text, re.IGNORECASE)
    if cited_match:
        cited_str = cited_match.group(1)
        cited_indices = []
        for part in cited_str.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1  # convert to 0-based
                if 0 <= idx < len(trimmed_articles):
                    cited_indices.append(idx)
    else:
        cited_indices = []

    # Strip the CITED line from brief text.
    brief_text = re.sub(
        r"\n?CITED:.*$",
        "",
        response_text,
        flags=re.IGNORECASE | re.MULTILINE,
    ).strip()
    return jsonify(
        {
            "themeName": theme_name or theme_id,
            "brief": brief_text,
            "cited_indices": cited_indices,
            "article_count": len(trimmed_articles),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
    )


@signals_bp.route("/sector-scores")
def sector_scores():
    """Serve cached sector scores from sector_scores.json."""
    if not SECTOR_SCORES_PATH.exists():
        return jsonify(
            {
                "error": "sector_scores.json not found. Run sector_scorer.py first.",
                "sectors": {},
            }
        )

    try:
        with SECTOR_SCORES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e), "sectors": {}}), 500

    generated_at = data.get("generated_at")
    if generated_at:
        try:
            dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - dt > timedelta(hours=24):
                data["stale"] = True
        except Exception:
            pass
    return jsonify(data)


@signals_bp.route("/sector-scores/refresh", methods=["POST"])
def refresh_sector_scores():
    """Run sector scorer synchronously and refresh score file."""
    try:
        result = subprocess.run(
            [SCORER_PYTHON, "-m", "news.sector_scorer"],
            cwd=SCORER_CWD,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        if result.stderr and result.stderr.strip():
            logger.info("[signals] sector_scorer stderr: %s", result.stderr.strip())
        return jsonify({"success": True, "message": "Sector scores refreshed"})
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        return jsonify({"success": False, "error": err}), 500
    except subprocess.TimeoutExpired as e:
        err = (e.stderr or e.stdout or "sector scorer timed out").strip()
        return jsonify({"success": False, "error": err}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
