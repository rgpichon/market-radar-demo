import logging
import threading
import time
import time as _time
from datetime import datetime, timezone
from typing import List

from flask import Blueprint, jsonify, request

from backend.news.digest_generator import OLLAMA_MODEL
from backend.news.feed_aggregator import (
    FeedItem,
    aggregate,
    get_articles_feed,
    get_digest_context,
    get_events_feed,
    get_feed,
    get_feed_stats,
    get_signals_feed,
    get_topic_feed,
)

logger = logging.getLogger(__name__)

news_bp = Blueprint("news", __name__, url_prefix="/api/news")


_cache: dict = {"raw": None, "fetched_at": 0.0}
CACHE_TTL_SECONDS = 300  # 5 minutes

_pipeline_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",  # idle | running | success | error
    "error": None,
    "articles_before": 0,
    "articles_after": 0,
}
_pipeline_lock = threading.Lock()


def _get_cached_feed(force_refresh: bool = False) -> List[FeedItem]:
    """Return cached full feed, refreshing if stale or forced."""
    now = time.time()
    if force_refresh or _cache["raw"] is None or (now - _cache["fetched_at"]) > CACHE_TTL_SECONDS:
        _cache["raw"] = get_feed(limit=500)
        _cache["fetched_at"] = now
    return _cache["raw"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@news_bp.get("/feed")
def api_news_feed():
    try:
        filter_type = request.args.get("type") or None
        filter_topic = request.args.get("topic") or None
        filter_source = request.args.get("source") or None
        sort_by = (request.args.get("sort") or "relevance").strip().lower()
        limit = int(request.args.get("limit") or 100)
        limit = max(1, min(500, limit))
        days_ahead = int(request.args.get("days_ahead") or 30)
        min_relevance = float(request.args.get("min_relevance") or 0.0)
        refresh = (request.args.get("refresh") or "").strip().lower() == "true"

        # Use cached full feed; apply filters locally to avoid re-fetching.
        items = list(_get_cached_feed(force_refresh=refresh))

        # Apply days_ahead only when type is event or not specified.
        # Cached feed uses the default; if caller asks for a different window, refresh and re-aggregate.
        if (filter_type is None or (filter_type or "").lower() == "event") and days_ahead != 30:
            items = aggregate(events_days_ahead=days_ahead, limit=500, sort_by="relevance")
            _cache["raw"] = items
            _cache["fetched_at"] = time.time()

        ft = (filter_type or "").strip().lower() if filter_type else None
        ftopic = (filter_topic or "").strip().lower() if filter_topic else None
        fsource = (filter_source or "").strip().lower() if filter_source else None

        filtered: List[FeedItem] = []
        for it in items:
            if ft and it["item_type"] != ft:
                continue
            if ftopic:
                if ftopic not in (it.get("topic") or "").lower() and ftopic not in (it.get("topic_id") or "").lower():
                    continue
            if fsource:
                if fsource not in (it.get("source_name") or "").lower():
                    continue
            if float(it.get("relevance") or 0.0) < min_relevance:
                continue
            filtered.append(it)

        if sort_by == "date":
            with_date = [i for i in filtered if i.get("date_published")]
            no_date = [i for i in filtered if not i.get("date_published")]
            with_date.sort(key=lambda x: x["date_published"], reverse=True)
            sorted_items = with_date + no_date
        elif sort_by == "score":
            sorted_items = sorted(filtered, key=lambda x: x.get("score", 0.0), reverse=True)
        else:
            sorted_items = sorted(filtered, key=lambda x: x.get("relevance", 0.0), reverse=True)

        out = sorted_items[:limit]
        return jsonify(
            {
                "items": out,
                "total": len(out),
                "cached": not refresh,
                "generated_at": _now_iso(),
            }
        )
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.get("/events")
def api_news_events():
    try:
        days_ahead = int(request.args.get("days_ahead") or 30)
        limit = int(request.args.get("limit") or 50)
        limit = max(1, min(200, limit))
        topic = request.args.get("topic") or None
        refresh = (request.args.get("refresh") or "").strip().lower() == "true"

        items = list(_get_cached_feed(force_refresh=refresh))
        events = [i for i in items if i.get("item_type") == "event"]

        if days_ahead != 30:
            events = aggregate(filter_type="event", events_days_ahead=days_ahead, limit=500, sort_by="date")

        if topic:
            ft = topic.strip().lower()
            events = [
                e
                for e in events
                if ft in (e.get("topic") or "").lower() or ft in (e.get("topic_id") or "").lower()
            ]

        with_date = [i for i in events if i.get("date_published")]
        no_date = [i for i in events if not i.get("date_published")]
        with_date.sort(key=lambda x: x["date_published"], reverse=True)
        out = (with_date + no_date)[:limit]

        return jsonify({"items": out, "total": len(out), "cached": not refresh, "generated_at": _now_iso()})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.get("/articles")
def api_news_articles():
    try:
        max_age_days = int(request.args.get("max_age_days") or 7)
        limit = int(request.args.get("limit") or 50)
        limit = max(1, min(200, limit))
        topic = request.args.get("topic") or None
        refresh = (request.args.get("refresh") or "").strip().lower() == "true"

        items = list(_get_cached_feed(force_refresh=refresh))
        articles = [i for i in items if i.get("item_type") == "article"]

        if max_age_days != 7:
            articles = aggregate(filter_type="article", articles_max_age_days=max_age_days, limit=500, sort_by="relevance")

        if topic:
            ft = topic.strip().lower()
            articles = [
                a
                for a in articles
                if ft in (a.get("topic") or "").lower() or ft in (a.get("topic_id") or "").lower()
            ]

        out = sorted(articles, key=lambda x: x.get("relevance", 0.0), reverse=True)[:limit]
        return jsonify({"items": out, "total": len(out), "cached": not refresh, "generated_at": _now_iso()})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.get("/signals")
def api_news_signals():
    try:
        limit = int(request.args.get("limit") or 20)
        limit = max(1, min(200, limit))
        refresh = (request.args.get("refresh") or "").strip().lower() == "true"

        items = list(_get_cached_feed(force_refresh=refresh))
        signals = [i for i in items if i.get("item_type") == "signal"]
        out = sorted(signals, key=lambda x: x.get("score", 0.0), reverse=True)[:limit]
        return jsonify({"items": out, "total": len(out), "cached": not refresh, "generated_at": _now_iso()})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.get("/topics")
def api_news_topics():
    try:
        items = list(_get_cached_feed(force_refresh=False))
        counts: dict = {}
        for it in items:
            t = it.get("topic") or ""
            if not t:
                continue
            counts[t] = counts.get(t, 0) + 1
        topics = [{"topic": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]
        return jsonify({"topics": topics})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.get("/stats")
def api_news_stats():
    try:
        return jsonify(get_feed_stats())
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.route("/search")
def news_search():
    """
    Full-text search across all articles and events.
    Query params:
      q     - search query (required)
      limit - max results (default 30, max 100)
      type  - filter by item_type: "article", "event", "signal"
    """
    from backend.news.search_engine import search as search_fn

    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 30)), 100)
    type_filter = request.args.get("type", "").strip()

    if not q:
        return jsonify({"items": [], "query": "", "total": 0})

    try:
        all_items = aggregate(
            limit=5000,
            events_days_ahead=90,
            include_market_signals=False,
            sort_by="relevance",
        )

        if type_filter:
            all_items = [i for i in all_items if i.get("item_type") == type_filter]

        results = search_fn(q, all_items, limit=limit)

        return jsonify(
            {
                "items": results,
                "query": q,
                "total": len(results),
                "searched": len(all_items),
            }
        )
    except Exception as e:
        logger.exception("[news_routes] search error")
        return jsonify({"error": str(e), "items": [], "query": q, "total": 0}), 500


@news_bp.post("/refresh")
def api_news_refresh():
    try:
        _get_cached_feed(force_refresh=True)
        return jsonify({"refreshed": True, "stats": get_feed_stats()})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.route("/pipeline/run", methods=["POST"])
def run_pipeline():
    """
    Trigger the Reports theme pipeline in a background thread.
    Returns immediately. Poll /api/news/pipeline/status for progress.
    """
    with _pipeline_lock:
        if _pipeline_state["running"]:
            return jsonify(
                {
                    "started": False,
                    "message": "Pipeline already running",
                    "state": _pipeline_state,
                }
            )

    def _run():
        import os
        import sys

        with _pipeline_lock:
            _pipeline_state["running"] = True
            _pipeline_state["status"] = "running"
            _pipeline_state["started_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            _pipeline_state["error"] = None

        try:
            before = len(aggregate(limit=5000, include_market_signals=False))
            with _pipeline_lock:
                _pipeline_state["articles_before"] = before
        except Exception:
            pass

        try:
            reports_tool_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "Reports", "tool")
            )
            import subprocess

            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, r'{reports_tool_root}'); "
                        "from backend import theme_pipeline; "
                        "theme_pipeline.run_pipeline()"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            # Auto-enrich new articles after pipeline completes
            try:
                from backend.news.article_enricher import run_enrichment

                logger.info("[pipeline] Starting post-pipeline enrichment...")
                run_enrichment(scope_days=7)
                logger.info("[pipeline] Post-pipeline enrichment complete.")
            except Exception as e:
                logger.warning("[pipeline] Post-pipeline enrichment failed: %s", e)
                # Don't fail the pipeline run if enrichment fails

            try:
                after = len(aggregate(limit=5000, include_market_signals=False))
                with _pipeline_lock:
                    _pipeline_state["articles_after"] = after
            except Exception:
                pass

            with _pipeline_lock:
                _pipeline_state["status"] = "success"
                _pipeline_state["finished_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            logger.info("[pipeline] Background pipeline run complete.")
        except Exception as e:
            with _pipeline_lock:
                _pipeline_state["status"] = "error"
                _pipeline_state["error"] = str(e)
                _pipeline_state["finished_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
            logger.error("[pipeline] Background pipeline run failed: %s", e)
        finally:
            with _pipeline_lock:
                _pipeline_state["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify(
        {
            "started": True,
            "message": "Pipeline running in background — poll /api/news/pipeline/status",
        }
    )


@news_bp.route("/pipeline/status")
def pipeline_status():
    """Returns current pipeline state for UI polling."""
    with _pipeline_lock:
        state = dict(_pipeline_state)

    if state["running"] and state["started_at"]:
        try:
            started = datetime.strptime(state["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
            state["elapsed_seconds"] = elapsed
        except Exception:
            state["elapsed_seconds"] = None

    return jsonify(state)


@news_bp.get("/digest/context")
def api_news_digest_context():
    try:
        days_ahead = int(request.args.get("days_ahead") or 14)
        max_items = int(request.args.get("max_items") or 40)
        ctx = get_digest_context(max_items=max_items, events_days_ahead=days_ahead)
        total = sum(len(v) for v in ctx.values())
        return jsonify({**ctx, "total_context_items": total})
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.route("/digest/status")
def digest_status():
    try:
        from backend.news.digest_generator import is_ollama_available

        available = is_ollama_available()
        return jsonify(
            {
                "ollama_available": available,
                "model": OLLAMA_MODEL,
                "base_url": "http://localhost:11434",
            }
        )
    except Exception as e:
        logger.exception("[news_routes] Unhandled error in %s", request.path)
        return jsonify({"error": str(e)}), 500


@news_bp.route("/digest/generate", methods=["POST"])
def digest_generate():
    from backend.news.digest_generator import OLLAMA_MODEL, generate

    body = request.get_json(silent=True) or {}
    fmt = body.get("format", "weekly_briefing")
    topic = body.get("topic")
    model = body.get("model", OLLAMA_MODEL)
    context_items = body.get("context_items")

    try:
        if context_items:
            events = [i for i in context_items if i.get("item_type") == "event"][:20]
            articles = [i for i in context_items if i.get("item_type") == "article"][:15]
            signals = [i for i in context_items if i.get("item_type") == "signal"][:5]
            context = {"events": events, "articles": articles, "signals": signals}

            from backend.news.digest_generator import (
                generate_flash_note,
                generate_market_pulse,
                generate_topic_roundup,
                generate_weekly_briefing,
            )

            if fmt == "weekly_briefing":
                result = generate_weekly_briefing(context=context, model=model)
            elif fmt == "topic_roundup":
                result = generate_topic_roundup(topic=topic or "current search", context=context, model=model)
            elif fmt == "market_pulse":
                result = generate_market_pulse(signals=signals, model=model)
            elif fmt == "flash_note":
                target = context_items[0]
                result = generate_flash_note(item=target, model=model)
            else:
                result = generate(format=fmt, topic=topic, model=model)
        else:
            result = generate(format=fmt, topic=topic, model=model)
        return jsonify(result)
    except Exception as e:
        logger.exception("[news_routes] digest generation failed")
        return jsonify({"error": str(e)}), 500

