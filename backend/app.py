from flask import Flask, jsonify, request, send_from_directory, session
from pathlib import Path
import json
import sys
import os
import secrets
import logging
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

# Add backend directory to path for imports
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
project_root = backend_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from db import init_db, get_db, get_event_by_id, get_user_event, upsert_user_event, get_all_user_events, list_saved_event_ids
from scrape_runner import run_scrape
from utils.aggregation import get_events as get_events_aggregated, get_source_health, get_source_summary
from backend.news.news_routes import news_bp
from backend.news.signals_routes import signals_bp

# File logging for background service mode
_log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "market_radar.log")

_file_handler = RotatingFileHandler(
    _log_file, maxBytes=5 * 1024 * 1024, backupCount=3
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
logging.getLogger().addHandler(_file_handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Market Radar starting up...")

app = Flask(__name__, static_folder=None)
app.secret_key = secrets.token_hex(16)  # For session management (4-Zone Architecture)
app.register_blueprint(news_bp)
app.register_blueprint(signals_bp)

# Add CORS headers to prevent 403 errors
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Paths
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
PREFERENCES_PATH = Path(__file__).parent / "preferences.json"
PACKS_PATH = Path(__file__).parent / "packs.json"


@app.route('/')
def index():
    """Serve index.html"""
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


@app.route("/journalist")
def journalist():
    return send_from_directory(
        os.path.join(os.path.dirname(__file__), '..', 'frontend'),
        'journalist.html'
    )


@app.route('/editorial')
def editorial():
    """Serve editorial dashboard (Priority 7, Phase 3)."""
    return send_from_directory(str(FRONTEND_DIR), 'editorial.html')


@app.route('/storyline')
def storyline():
    """Serve storyline page (Priority 7, Phase 4)."""
    return send_from_directory(str(FRONTEND_DIR), 'storyline.html')


# Zone Pages
@app.route('/zone1')
def zone1():
    """Zone 1: Recommended for You."""
    return send_from_directory(str(FRONTEND_DIR), 'zone1.html')


@app.route('/zone2')
def zone2():
    """Zone 2: Happening Soon."""
    return send_from_directory(str(FRONTEND_DIR), 'zone2.html')


@app.route('/zone3')
def zone3():
    """Zone 3: Explore by Interest."""
    return send_from_directory(str(FRONTEND_DIR), 'zone3.html')


@app.route('/zone4')
def zone4():
    """Zone 4: All Events / Advanced."""
    return send_from_directory(str(FRONTEND_DIR), 'zone4.html')


# 4-Zone Architecture: Zone 1 - Recommendations (no auth required)
@app.route('/api/recommendations', methods=['GET'])
def get_recommendations():
    """Get recommended events (Zone 1) - high signal score events."""
    from db import get_db
    from datetime import datetime, timedelta, timezone
    import json
    
    limit = request.args.get('limit', 20, type=int)
    days_ahead = request.args.get('days_ahead', 365, type=int)
    min_signal_score = request.args.get('min_signal_score', type=int)
    
    # Calculate cutoff date
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
    
    # Get events with high signal score, sorted by signal score and date
    conn = get_db()
    cursor = conn.cursor()
    
    if min_signal_score:
        cursor.execute("""
            SELECT * FROM events
            WHERE date_time >= datetime('now')
            AND date_time <= ?
            AND signal_score IS NOT NULL
            AND signal_score >= ?
            ORDER BY signal_score DESC, date_time ASC
            LIMIT ?
        """, (cutoff_date, min_signal_score, limit))
    else:
        cursor.execute("""
            SELECT * FROM events
            WHERE date_time >= datetime('now')
            AND date_time <= ?
            AND signal_score IS NOT NULL
            ORDER BY signal_score DESC, date_time ASC
            LIMIT ?
        """, (cutoff_date, limit))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(events)


# 4-Zone Architecture: Zone 2 - Happening Soon
@app.route('/api/events/happening-soon', methods=['GET'])
def get_happening_soon():
    """Get events happening soon (Zone 2)."""
    from db import get_events_happening_soon
    
    days = request.args.get('days', 14, type=int)
    events = get_events_happening_soon(days)
    return jsonify(events)


# Homepage Preview API - Returns preview data for all zones
@app.route('/api/homepage/preview', methods=['GET'])
def get_homepage_preview():
    """Get preview data for homepage zone cards."""
    from db import get_db
    from datetime import datetime, timedelta, timezone
    
    conn = get_db()
    cursor = conn.cursor()
    
    preview = {
        'zone1': {'title': 'Recommended for You', 'description': 'Events most relevant to your interests', 'preview_events': [], 'total_count': 0, 'url': '/zone1'},
        'zone2': {'title': 'Happening Soon', 'description': 'Upcoming events you shouldn\'t miss', 'preview_events': [], 'total_count': 0, 'url': '/zone2'},
        'zone3': {'title': 'Explore by Interest', 'description': 'Discover events by topic or theme', 'preview_events': [], 'topics': [], 'url': '/zone3'},
        'zone4': {'title': 'All Events / Advanced', 'description': 'Full event catalog with powerful filtering', 'preview_events': [], 'total_count': 0, 'url': '/zone4'}
    }
    
    # Zone 1: Top 5 recommended events (highest signal score)
    cursor.execute("""
        SELECT id, event_name, date_time, link, format, signal_score, firm_name
        FROM events
        WHERE date_time >= datetime('now')
        AND signal_score IS NOT NULL
        ORDER BY signal_score DESC, date_time ASC
        LIMIT 5
    """)
    zone1_events = [dict(row) for row in cursor.fetchall()]
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE date_time >= datetime('now')
        AND signal_score IS NOT NULL
    """)
    zone1_total = cursor.fetchone()[0]
    preview['zone1']['preview_events'] = zone1_events
    preview['zone1']['total_count'] = zone1_total
    
    # Zone 2: Next 5 events by date (within 14 days)
    days = 14
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    cursor.execute("""
        SELECT id, event_name, date_time, link, format, signal_score, firm_name
        FROM events
        WHERE date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 5
    """, (cutoff,))
    zone2_events = [dict(row) for row in cursor.fetchall()]
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE date_time >= datetime('now')
        AND date_time <= ?
    """, (cutoff,))
    zone2_total = cursor.fetchone()[0]
    preview['zone2']['preview_events'] = zone2_events
    preview['zone2']['total_count'] = zone2_total
    
    # Zone 3: Get topics and preview events from first topic
    try:
        # Get unique topics from tags_json
        cursor.execute("""
            SELECT DISTINCT tags_json
            FROM events
            WHERE date_time >= datetime('now')
            AND tags_json IS NOT NULL
            LIMIT 100
        """)
        all_tags = set()
        for row in cursor.fetchall():
            try:
                tags = json.loads(row[0])
                all_tags.update(tags)
            except:
                pass
        
        # Create topic list with counts
        topics = []
        for tag in sorted(all_tags)[:8]:
            cursor.execute("""
                SELECT COUNT(*) FROM events
                WHERE date_time >= datetime('now')
                AND tags_json LIKE ?
            """, (f'%{tag}%',))
            count = cursor.fetchone()[0]
            topics.append({'name': tag, 'slug': tag.lower().replace(' ', '-'), 'count': count})
        
        preview['zone3']['topics'] = topics
        
        # Get preview events from first topic if available
        if topics:
            first_topic = topics[0]['name']
            cursor.execute("""
                SELECT id, event_name, date_time, link, format, signal_score, firm_name
                FROM events
                WHERE date_time >= datetime('now')
                AND tags_json LIKE ?
                ORDER BY date_time ASC
                LIMIT 5
            """, (f'%{first_topic}%',))
            zone3_events = [dict(row) for row in cursor.fetchall()]
            preview['zone3']['preview_events'] = zone3_events
    except Exception as e:
        print(f"Error loading Zone 3 topics: {e}")
        preview['zone3']['topics'] = []
    
    # Zone 4: Total count and sample events
    cursor.execute("""
        SELECT COUNT(*) FROM events
        WHERE date_time >= datetime('now')
    """)
    zone4_total = cursor.fetchone()[0]
    cursor.execute("""
        SELECT id, event_name, date_time, link, format, signal_score, firm_name
        FROM events
        WHERE date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 3
    """)
    zone4_events = [dict(row) for row in cursor.fetchall()]
    preview['zone4']['preview_events'] = zone4_events
    preview['zone4']['total_count'] = zone4_total
    
    conn.close()
    return jsonify(preview)


# 4-Zone Architecture: Zone 3 - Explore by Interest
@app.route('/api/events/by-topic', methods=['GET'])
def get_events_by_topic():
    """Get events by topic (Zone 3)."""
    from db import get_events_by_topic
    
    topic = request.args.get('topic')
    if not topic:
        return jsonify({'error': 'Topic required'}), 400
    
    events = get_events_by_topic(topic)
    return jsonify(events)


@app.route('/frontend/<path:filename>')
def frontend_files(filename):
    """Serve static frontend files"""
    return send_from_directory(str(FRONTEND_DIR), filename)


@app.route('/api/events', methods=['GET'])
def get_events():
    """Get events with filtering."""
    # Parse query parameters
    q = request.args.get('q', '').strip() or None
    firms_param = request.args.get('firms', '').strip()
    firm_param = request.args.get('firm', '').strip()
    saved_only = request.args.get('saved_only', '0') == '1'
    with_date = request.args.get('with_date', '1') == '1'
    days_ahead = int(request.args.get('days_ahead', 365))
    limit = request.args.get('limit', type=int)
    min_signal_score = request.args.get('min_signal_score', type=int)  # PHASE 6
    
    # Parse firms list
    firms = None
    if firms_param:
        firms = [f.strip() for f in firms_param.split(',') if f.strip()]
    firm = firm_param if firm_param else None
    
    # Phase 3: Parse additional filter parameters (Priority 6, Phase 3)
    tags = request.args.get('tags', '').split(',') if request.args.get('tags') else []
    tags = [t.strip() for t in tags if t.strip()] or None
    format_filter = request.args.get('format', '').strip() or None
    date_start = request.args.get('date_start', '').strip() or None
    date_end = request.args.get('date_end', '').strip() or None
    
    # Get events using aggregation layer
    events = get_events_aggregated(
        q=q,
        firms=firms,
        firm=firm,
        saved_only=saved_only,
        with_date=with_date,
        days_ahead=days_ahead,
        limit=limit,
        min_signal_score=min_signal_score,  # PHASE 6
        tags=tags,  # Priority 6, Phase 3
        format_filter=format_filter,  # Priority 6, Phase 3
        date_start=date_start,  # Priority 6, Phase 3
        date_end=date_end  # Priority 6, Phase 3
    )
    
    # Note: Sorting is handled by aggregation layer (dated first ascending, then undated)
    # sort parameter is not currently supported in aggregation layer
    
    return jsonify(events)


@app.route('/api/source_stats', methods=['GET'])
def get_source_stats():
    """Get source scorecard statistics."""
    try:
        stats = get_source_health()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/new_sources_validation', methods=['GET'])
def get_new_sources_validation():
    """Get validation results for new sources from bulk discovery."""
    try:
        validation_file = Path(__file__).parent / "new_sources_validation_results.json"
        if validation_file.exists():
            with open(validation_file, 'r') as f:
                return jsonify(json.load(f))
        else:
            return jsonify({'error': 'Validation results not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    """Get notifications with event details."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT n.id, n.event_id, n.created_at, n.reason, n.seen,
               e.firm_name, e.event_name, e.date_time, e.link
        FROM notifications n
        JOIN events e ON n.event_id = e.id
        ORDER BY n.created_at DESC
    """)
    
    rows = cursor.fetchall()
    notifications = [dict(row) for row in rows]
    
    conn.close()
    return jsonify(notifications)


@app.route('/api/events/calendar', methods=['GET'])
def export_calendar():
    """Export events as iCal calendar file."""
    try:
        from utils.calendar_generator import create_ical_calendar
        
        # Get filter params
        firm = request.args.get('firm')
        tags = request.args.get('tags', '').split(',') if request.args.get('tags') else []
        days_ahead = int(request.args.get('days_ahead', 90))
        
        # Query events
        from db import get_db
        from datetime import datetime, timedelta, timezone
        import json
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Build query
        query = "SELECT * FROM events WHERE date_time IS NOT NULL AND date_time >= datetime('now')"
        params = []
        
        if firm:
            query += " AND firm_name = ?"
            params.append(firm)
        
        # Filter by tags (if provided)
        if tags:
            # Tags are stored as JSON, need to check if any tag matches
            tag_conditions = []
            for tag in tags:
                if tag.strip():
                    tag_conditions.append("tags_json LIKE ?")
                    params.append(f'%"{tag.strip()}"%')
            if tag_conditions:
                query += " AND (" + " OR ".join(tag_conditions) + ")"
        
        query += " ORDER BY date_time ASC LIMIT 500"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Convert to event dicts
        events = []
        for row in rows:
            event = dict(row)
            # Parse tags_json
            if event.get('tags_json'):
                try:
                    event['tags'] = json.loads(event['tags_json'])
                except:
                    event['tags'] = []
            events.append(event)
        
        conn.close()
        
        # Create calendar
        cal = create_ical_calendar(events, "Market Radar Events")
        
        # Return as iCal file
        from flask import Response
        response = Response(
            cal.to_ical(),
            mimetype='text/calendar',
            headers={
                'Content-Disposition': 'attachment; filename=market_radar_events.ics'
            }
        )
        return response
        
    except ImportError:
        return jsonify({'error': 'icalendar package not available'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notifications/mark_seen', methods=['POST'])
def mark_notifications_seen():
    """Mark notifications as seen."""
    data = request.get_json()
    notification_ids = data.get('notification_ids', [])
    
    if not notification_ids:
        return jsonify({'error': 'No notification_ids provided'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    placeholders = ','.join(['?'] * len(notification_ids))
    cursor.execute(f"""
        UPDATE notifications 
        SET seen = 1 
        WHERE id IN ({placeholders})
    """, notification_ids)
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'marked': len(notification_ids)})


@app.route('/api/scrape', methods=['POST'])
def trigger_scrape():
    """Run scrape immediately."""
    try:
        result = run_scrape()
        return jsonify({
            'status': 'success',
            'inserted_count': result['total_inserted'],
            'updated_count': result['total_updated'],
            'notifications_created': result['total_notifications']
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/recommendations/legacy', methods=['GET'])
def get_recommendations_legacy():
    """Get event recommendations based on user engagement (legacy endpoint)."""
    try:
        from utils.recommendation_engine import recommend_events
        
        limit = int(request.args.get('limit', 10))
        recommendations = recommend_events(limit=limit)
        
        return jsonify(recommendations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/engagement/track', methods=['POST'])
def track_engagement():
    """Track user engagement with an event."""
    try:
        from utils.recommendation_engine import track_engagement as track_eng
        
        data = request.get_json()
        event_id = data.get('event_id')
        action = data.get('action', 'view')
        
        if not event_id:
            return jsonify({'error': 'event_id required'}), 400
        
        track_eng(event_id, action)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences', methods=['GET'])
def get_preferences():
    """Get current preferences (read-only)."""
    try:
        with open(PREFERENCES_PATH, 'r') as f:
            prefs = json.load(f)
        
        # Load packs for display
        with open(PACKS_PATH, 'r') as f:
            packs = json.load(f)
        
        # Expand pack names
        expanded_packs = []
        for pack_id in prefs.get('follow_packs', []):
            pack = packs.get(pack_id, {})
            expanded_packs.append({
                'id': pack_id,
                'display_name': pack.get('display_name', pack_id)
            })
        
        return jsonify({
            'follow_firms': prefs.get('follow_firms', []),
            'follow_packs': expanded_packs,
            'follow_tags': prefs.get('follow_tags', []),
            'require_confirmed_for_notifications': prefs.get('require_confirmed_for_notifications', False)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user_events', methods=['GET'])
def get_user_events():
    """Get all user event metadata."""
    try:
        user_events = get_all_user_events()
        return jsonify(user_events)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user_events', methods=['POST'])
def update_user_event():
    """Create or update user event metadata (saved/note)."""
    try:
        data = request.get_json()
        event_id = data.get('event_id')
        if not event_id:
            return jsonify({'error': 'event_id required'}), 400
        
        saved = data.get('saved')
        note = data.get('note')
        
        result = upsert_user_event(event_id, saved=saved, note=note)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/meta', methods=['GET'])
def get_meta():
    """Get metadata (last scrape time, total events)."""
    try:
        meta_path = Path(__file__).parent / "meta.json"
        if meta_path.exists():
            with open(meta_path, 'r') as f:
                meta = json.load(f)
        else:
            # Fallback: compute from DB
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM events")
            total_events = cursor.fetchone()[0]
            conn.close()
            meta = {
                'last_scrape_at': None,
                'total_events': total_events
            }
        return jsonify(meta)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/sources', methods=['GET'])
def get_dashboard_sources():
    """Get source health data for dashboard (Priority 5, Phase 6)."""
    try:
        from utils.health_monitor import load_health_history, detect_trend
        
        sources_file = Path(__file__).parent / "sources.json"
        with open(sources_file) as f:
            sources = json.load(f)
        
        dashboard_data = []
        
        for source in sources:
            source_id = source['id']
            history = load_health_history(source_id)
            trend = detect_trend(source_id)
            
            # Load current stats
            stats_file = Path(__file__).parent / "source_stats.json"
            if stats_file.exists():
                with open(stats_file) as f:
                    all_stats = json.load(f)
                current_stats = all_stats.get(source_id, {})
            else:
                current_stats = {}
            
            dashboard_data.append({
                'id': source_id,
                'firm_name': source.get('firm_name'),
                'active': source.get('active', 1),
                'current_stats': current_stats,
                'trend': trend,
                'history_count': len(history)
            })
        
        return jsonify(dashboard_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/topics', methods=['GET'])
def get_topics():
    """Get all available topics with event counts (Priority 7, Phase 1)."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get all events with tags
        cursor.execute("""
            SELECT tags_json FROM events
            WHERE tags_json IS NOT NULL
        """)
        
        all_tags = set()
        for row in cursor.fetchall():
            tags_json = row[0]
            if tags_json:
                try:
                    tags = json.loads(tags_json) if isinstance(tags_json, str) else tags_json
                    if isinstance(tags, list):
                        all_tags.update(tags)
                except:
                    pass
        
        # Get counts per topic
        topics_with_counts = []
        for tag in sorted(all_tags):
            cursor.execute("""
                SELECT COUNT(*) FROM events
                WHERE tags_json LIKE ?
            """, (f'%"{tag}"%',))
            count = cursor.fetchone()[0]
            topics_with_counts.append({
                'name': tag,
                'count': count,
                'slug': tag.lower().replace(' ', '-').replace('/', '-')
            })
        
        conn.close()
        return jsonify(topics_with_counts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/events/featured', methods=['GET'])
def get_featured_events():
    """Get featured events (highest signal_score, recent, important participants) (Priority 7, Phase 2)."""
    try:
        limit = int(request.args.get('limit', 3))
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get events with high signal_score, recent, future-dated
        # Also check for is_featured flag if it exists
        cursor.execute("""
            SELECT * FROM events
            WHERE (signal_score >= 70 OR is_featured = 1)
            AND date_time >= datetime('now')
            ORDER BY 
                CASE WHEN is_featured = 1 THEN 0 ELSE 1 END,
                signal_score DESC, 
                date_time ASC
            LIMIT ?
        """, (limit,))
        
        events = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify(events)
    except Exception as e:
        # Fallback if is_featured column doesn't exist yet
        try:
            limit = int(request.args.get('limit', 3))
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM events
                WHERE signal_score >= 70
                AND date_time >= datetime('now')
                ORDER BY signal_score DESC, date_time ASC
                LIMIT ?
            """, (limit,))
            events = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return jsonify(events)
        except Exception as e2:
            return jsonify({'error': str(e2)}), 500


@app.route('/api/storylines', methods=['GET'])
def get_storylines():
    """Get detected storylines (Priority 7, Phase 2)."""
    try:
        from utils.storyline_detector import detect_storylines
        from utils.aggregation import get_events
        
        # Get all future events
        all_events = get_events(with_date=True, days_ahead=365)
        
        # Detect storylines
        storylines = detect_storylines(all_events)
        
        return jsonify(storylines)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/events/<event_id>/editorial', methods=['POST'])
def update_event_editorial(event_id):
    """Update editorial tags/notes for an event (Priority 7, Phase 3)."""
    try:
        data = request.get_json()
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE events
            SET editorial_tags_json = ?,
                editorial_notes = ?,
                is_featured = ?
            WHERE id = ?
        """, (
            json.dumps(data.get('editorial_tags', [])),
            data.get('editorial_notes', ''),
            int(data.get('is_featured', False)),
            event_id
        ))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/news/article/fetch")
def fetch_article():
    """
    Fetch and extract article body text from a URL using newspaper3k.
    Returns extracted text, title, authors, publish_date.
    Falls back gracefully if extraction fails.
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    try:
        reports_backend = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "Reports", "tool", "backend")
        )
        if reports_backend not in sys.path:
            sys.path.insert(0, reports_backend)

        try:
            from adapters.article_extractor import extract_article  # type: ignore

            result = extract_article(url)
            return jsonify(
                {
                    "url": url,
                    "title": result.get("title", ""),
                    "text": result.get("text", ""),
                    "authors": result.get("authors", []),
                    "publish_date": str(result.get("publish_date", "")),
                    "success": result.get("success", False),
                }
            )
        except Exception:
            from newspaper import Article  # type: ignore

            art = Article(url)
            art.download()
            art.parse()
            text = (art.text or "").strip()
            return jsonify(
                {
                    "url": url,
                    "title": art.title or "",
                    "text": text,
                    "authors": art.authors or [],
                    "publish_date": str(art.publish_date or ""),
                    "success": bool(text and len(text) > 200),
                }
            )
    except Exception as e:
        return jsonify(
            {
                "url": url,
                "title": "",
                "text": "",
                "authors": [],
                "publish_date": "",
                "success": False,
                "error": str(e),
            }
        )


if __name__ == '__main__':
    # Initialize database
    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5001"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)

