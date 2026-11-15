import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "events.db"


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database schema and sync sources from sources.json."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Sources table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            firm_name TEXT NOT NULL,
            firm_type TEXT,
            url TEXT NOT NULL,
            adapter_type TEXT NOT NULL,
            selectors_json TEXT,
            default_tags_json TEXT,
            title_extraction_json TEXT,
            postprocess_rules_json TEXT,
            detail_fetch_json TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    
    # Add columns if they don't exist (for migrations)
    try:
        cursor.execute("ALTER TABLE sources ADD COLUMN title_extraction_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE sources ADD COLUMN postprocess_rules_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE sources ADD COLUMN detail_fetch_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE sources ADD COLUMN api_config_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            firm_name TEXT NOT NULL,
            event_name TEXT NOT NULL,
            date_time TEXT,
            link TEXT NOT NULL,
            source_id TEXT NOT NULL,
            tags_json TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        )
    """)
    
    # Notifications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            seen INTEGER DEFAULT 0,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    conn.commit()
    conn.close()
    
    # Sync sources from sources.json
    sync_sources_from_json()


def sync_sources_from_json():
    """Load sources from sources.json and upsert into database.
    Sources removed from JSON are marked inactive.
    """
    sources_json_path = Path(__file__).parent / "sources.json"
    
    if not sources_json_path.exists():
        return
    
    try:
        with open(sources_json_path, 'r') as f:
            sources_data = json.load(f)
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get IDs of sources in JSON
        json_source_ids = {source['id'] for source in sources_data}
        
        # Upsert sources from JSON
        for source in sources_data:
            selectors_json_str = json.dumps(source.get('selectors_json')) if source.get('selectors_json') else None
            tags_json_str = json.dumps(source.get('default_tags_json')) if source.get('default_tags_json') else None
            title_extraction_str = json.dumps(source.get('title_extraction')) if source.get('title_extraction') else None
            postprocess_rules_str = json.dumps(source.get('postprocess_rules')) if source.get('postprocess_rules') else None
            detail_fetch_str = json.dumps(source.get('detail_fetch')) if source.get('detail_fetch') else None
            api_config_str = json.dumps(source.get('api_config')) if source.get('api_config') else None
            
            cursor.execute("""
                INSERT OR REPLACE INTO sources 
                (id, firm_name, firm_type, url, adapter_type, selectors_json, default_tags_json, 
                 title_extraction_json, postprocess_rules_json, detail_fetch_json, api_config_json, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                source['id'],
                source['firm_name'],
                source.get('firm_type'),
                source['url'],
                source['adapter_type'],
                selectors_json_str,
                tags_json_str,
                title_extraction_str,
                postprocess_rules_str,
                detail_fetch_str,
                api_config_str,
                source.get('active', 1)
            ))
        
        # Mark sources not in JSON as inactive
        cursor.execute("SELECT id FROM sources")
        db_source_ids = {row['id'] for row in cursor.fetchall()}
        
        removed_ids = db_source_ids - json_source_ids
        for source_id in removed_ids:
            cursor.execute("UPDATE sources SET active = 0 WHERE id = ?", (source_id,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        # Silently fail - sources.json might not exist or be malformed
        pass


def generate_event_id(firm_name, event_name, date_time, link):
    """Generate stable hash ID for event."""
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from utils.normalize import normalize_string, normalize_url
    
    normalized_firm = normalize_string(firm_name)
    normalized_event = normalize_string(event_name)
    normalized_link = normalize_url(link)
    date_str = date_time or ""
    
    hash_input = f"{normalized_firm}|{normalized_event}|{date_str}|{normalized_link}"
    return hashlib.sha256(hash_input.encode()).hexdigest()


def upsert_event(firm_name, event_name, date_time, link, source_id, tags_json=None):
    """Insert or update event. Returns (is_new, event_id)."""
    event_id = generate_event_id(firm_name, event_name, date_time, link)
    now = datetime.utcnow().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT id, first_seen FROM events WHERE id = ?", (event_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing
        cursor.execute("""
            UPDATE events 
            SET last_seen = ?,
                date_time = COALESCE(?, date_time),
                link = COALESCE(?, link),
                tags_json = COALESCE(?, tags_json)
            WHERE id = ?
        """, (now, date_time, link, tags_json, event_id))
        conn.commit()
        conn.close()
        return (False, event_id)
    else:
        # Insert new
        cursor.execute("""
            INSERT INTO events 
            (id, firm_name, event_name, date_time, link, source_id, tags_json, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, firm_name, event_name, date_time, link, source_id, tags_json, now, now))
        conn.commit()
        conn.close()
        return (True, event_id)


def create_notification(event_id, reason="new_match"):
    """Create a notification for an event."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if notification already exists for this event with this reason
    cursor.execute("""
        SELECT id FROM notifications 
        WHERE event_id = ? AND reason = ?
    """, (event_id, reason))
    
    if cursor.fetchone():
        conn.close()
        return False
    
    now = datetime.utcnow().isoformat()
    cursor.execute("""
        INSERT INTO notifications (event_id, created_at, reason, seen)
        VALUES (?, ?, ?, 0)
    """, (event_id, now, reason))
    
    conn.commit()
    conn.close()
    return True


def get_sources(active_only=True):
    """Get all sources."""
    conn = get_db()
    cursor = conn.cursor()
    
    if active_only:
        cursor.execute("SELECT * FROM sources WHERE active = 1")
    else:
        cursor.execute("SELECT * FROM sources")
    
    sources = []
    for row in cursor.fetchall():
        source = dict(row)
        if source.get('selectors_json'):
            source['selectors_json'] = json.loads(source['selectors_json'])
        if source.get('default_tags_json'):
            source['default_tags_json'] = json.loads(source['default_tags_json'])
        # Parse new config fields
        if source.get('title_extraction_json'):
            source['title_extraction'] = json.loads(source['title_extraction_json'])
        if source.get('postprocess_rules_json'):
            source['postprocess_rules'] = json.loads(source['postprocess_rules_json'])
        if source.get('detail_fetch_json'):
            source['detail_fetch'] = json.loads(source['detail_fetch_json'])
        if source.get('api_config_json'):
            source['api_config'] = json.loads(source['api_config_json'])
        sources.append(source)
    
    conn.close()
    return sources


def get_event_by_id(event_id):
    """Get event by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        event = dict(row)
        if event.get('tags_json'):
            event['tags_json'] = json.loads(event['tags_json'])
        return event
    return None

