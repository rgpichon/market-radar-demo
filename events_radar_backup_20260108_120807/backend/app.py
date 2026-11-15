from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path
import json
import sys
import os
from datetime import datetime, timedelta, timezone

# Add backend directory to path for imports
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import init_db, get_db, get_event_by_id
from scrape_runner import run_scrape

app = Flask(__name__, static_folder=None)

# Paths
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
PREFERENCES_PATH = Path(__file__).parent / "preferences.json"
PACKS_PATH = Path(__file__).parent / "packs.json"


@app.route('/')
def index():
    """Serve index.html"""
    return send_from_directory(str(FRONTEND_DIR), 'index.html')


@app.route('/frontend/<path:filename>')
def frontend_files(filename):
    """Serve static frontend files"""
    return send_from_directory(str(FRONTEND_DIR), filename)


@app.route('/api/events', methods=['GET'])
def get_events():
    """Get events with filtering."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Build query
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    # Search filter
    q = request.args.get('q', '').strip()
    if q:
        query += " AND (firm_name LIKE ? OR event_name LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    
    # Firm filter
    firm = request.args.get('firm', '').strip()
    if firm:
        query += " AND firm_name = ?"
        params.append(firm)
    
    # Date filter
    with_date = request.args.get('with_date', '0') == '1'
    days_ahead = int(request.args.get('days_ahead', 30))
    
    if with_date:
        query += " AND date_time IS NOT NULL"
        # Filter by days ahead
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
        query += " AND date_time <= ?"
        params.append(cutoff)
    else:
        # If with_date=0, include all (both with and without dates)
        # But if days_ahead is specified and event has date, still filter
        if days_ahead:
            cutoff = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
            query += " AND (date_time IS NULL OR date_time <= ?)"
            params.append(cutoff)
    
    # Sorting
    query += " ORDER BY "
    query += "CASE WHEN date_time IS NULL THEN 1 ELSE 0 END, "  # nulls last
    query += "date_time ASC, "
    query += "last_seen DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    events = []
    for row in rows:
        event = dict(row)
        if event.get('tags_json'):
            try:
                event['tags_json'] = json.loads(event['tags_json'])
            except:
                pass
        events.append(event)
    
    conn.close()
    return jsonify(events)


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


if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run Flask app
    app.run(debug=True, host='127.0.0.1', port=5000)

