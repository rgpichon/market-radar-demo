import sqlite3
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, List

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
            format TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id)
        )
    """)
    
    # Add format column if it doesn't exist (migration)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN format TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Add semantic columns if they don't exist (migration)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN event_type TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN signal_level TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN market_scope_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN bank_participants_json TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Add intel classification columns (PHASE 1)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN intel_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN has_explicit_date INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN confidence_score INTEGER DEFAULT 50")
    except sqlite3.OperationalError:
        pass
    
    # Add description column (PHASE 3)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN description TEXT")
    except sqlite3.OperationalError:
        pass
    
    # Add participant_roles_json column (PHASE 4)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN participant_roles_json TEXT")
    except sqlite3.OperationalError:
        pass
    
    # Add signal_score column (PHASE 6)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN signal_score INTEGER DEFAULT 50")
    except sqlite3.OperationalError:
        pass
    
    # Add location columns (PRIORITY 2, Phase 3)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location_text TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location_city TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location_country TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location_lat REAL")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN location_lng REAL")
    except sqlite3.OperationalError:
        pass
    
    # Add registration columns (PRIORITY 2, Phase 4)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN registration_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN registration_url TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN registration_deadline TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN registration_fee TEXT")
    except sqlite3.OperationalError:
        pass
    
    # Add speakers_json column (PRIORITY 2, Phase 2)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN speakers_json TEXT")
    except sqlite3.OperationalError:
        pass
    
    # Newsletter quality tracking table (PHASE 2)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS newsletter_quality (
            newsletter_id TEXT PRIMARY KEY,
            emails_seen INTEGER DEFAULT 0,
            intel_items_extracted INTEGER DEFAULT 0,
            rejection_rate REAL DEFAULT 0.0,
            quality_score INTEGER DEFAULT 50,
            last_updated TEXT NOT NULL,
            FOREIGN KEY (newsletter_id) REFERENCES newsletter_targets(id)
        )
    """)
    
    # Sender statistics table (PHASE 4)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sender_stats (
            sender_email TEXT PRIMARY KEY,
            newsletter_id TEXT,
            emails_seen INTEGER DEFAULT 0,
            intel_items_extracted INTEGER DEFAULT 0,
            rejection_rate REAL DEFAULT 0.0,
            promotion_level TEXT DEFAULT 'unknown',
            last_seen TEXT,
            last_updated TEXT NOT NULL
        )
    """)
    
    # Newsletter decision records table (GOVERNANCE)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS newsletter_decisions (
            newsletter_id TEXT PRIMARY KEY,
            decision_status TEXT NOT NULL,
            decision_score INTEGER NOT NULL,
            decision_reason TEXT,
            decision_features_json TEXT,
            recommended_next_action TEXT,
            last_evaluated_at TEXT NOT NULL,
            evidence_path TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            last_failure_type TEXT,
            paused INTEGER DEFAULT 0,
            paused_reason TEXT,
            cooldown_until TEXT,
            FOREIGN KEY (newsletter_id) REFERENCES newsletter_targets(id)
        )
    """)
    
    # Decision audit trail table (GOVERNANCE)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS decision_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            newsletter_id TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT NOT NULL,
            previous_score INTEGER,
            new_score INTEGER NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (newsletter_id) REFERENCES newsletter_targets(id)
        )
    """)
    
    # Ingested emails table (for Gmail deduplication)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingested_emails (
            gmail_id TEXT PRIMARY KEY,
            thread_id TEXT,
            internal_date TEXT,
            subject TEXT,
            from_addr TEXT,
            sha256 TEXT,
            status TEXT NOT NULL,
            failure_reason TEXT,
            ingested_at TEXT NOT NULL
        )
    """)
    
    # Create index on sha256 for fast lookups
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ingested_emails_sha256 ON ingested_emails(sha256)")
    except sqlite3.OperationalError:
        pass
    
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
    
    # Phase 3: Aggregated notifications table
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aggregated_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                aggregation_key TEXT NOT NULL,
                notification_ids TEXT NOT NULL,
                event_ids TEXT NOT NULL,
                count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                sent INTEGER DEFAULT 0,
                UNIQUE(aggregation_key)
            )
        """)
    except sqlite3.OperationalError:
        pass  # Table already exists
    
    # Phase 4: User engagement table (for recommendations)
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                action TEXT NOT NULL,
                action_timestamp TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id)
            )
        """)
    except sqlite3.OperationalError:
        pass  # Table already exists
    
    # User events table (saved/notes)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_events (
            event_id TEXT PRIMARY KEY,
            saved INTEGER DEFAULT 0,
            note TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    # Phase 3: Add editorial columns (Priority 7, Phase 3)
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN editorial_tags_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN editorial_notes TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN curator_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN is_featured INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # Phase 4: Add storylines tables (Priority 7, Phase 4)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS storylines (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            firm_name TEXT,
            primary_topic TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS storyline_events (
            storyline_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            PRIMARY KEY (storyline_id, event_id),
            FOREIGN KEY (storyline_id) REFERENCES storylines(id),
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    """)
    
    # 4-Zone Architecture: User account tables (Phase 1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TEXT NOT NULL,
            last_login TEXT,
            preferences_json TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            interest_type TEXT NOT NULL,
            interest_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, interest_type, interest_value)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_behavior (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            UNIQUE(user_id, event_id, action_type)
        )
    """)
    
    # Create indexes for user tables
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_interests_user_id ON user_interests(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_behavior_user_id ON user_behavior(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_behavior_event_id ON user_behavior(event_id)")
    except sqlite3.OperationalError:
        pass

    # Source health snapshots (Phase 0 maintenance loop)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS source_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            ts_utc TEXT NOT NULL,
            raw_count INTEGER,
            kept_count INTEGER,
            dated_count INTEGER,
            undated_count INTEGER,
            future_count INTEGER,
            dated_ratio REAL,
            kept_ratio REAL,
            error_class TEXT,
            error_evidence TEXT,
            run_id TEXT
        )
    """)
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_health_source_id_ts ON source_health(source_id, ts_utc)")
    except sqlite3.OperationalError:
        pass
    
    # 4-Zone Architecture: User account tables (Phase 1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            created_at TEXT NOT NULL,
            last_login TEXT,
            preferences_json TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            interest_type TEXT NOT NULL,
            interest_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, interest_type, interest_value)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_behavior (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            UNIQUE(user_id, event_id, action_type)
        )
    """)
    
    # Create indexes for user tables
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_interests_user_id ON user_interests(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_behavior_user_id ON user_behavior(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_behavior_event_id ON user_behavior(event_id)")
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()


def insert_source_health(snapshot: Dict):
    """
    Insert a single source_health snapshot row.

    Snapshot keys (expected):
      source_id (required), ts_utc (required ISO)
      raw_count, kept_count, dated_count, undated_count, future_count
      dated_ratio, kept_ratio
      error_class (nullable), error_evidence (nullable), run_id (nullable)
    """
    if not snapshot or not snapshot.get("source_id") or not snapshot.get("ts_utc"):
        raise ValueError("insert_source_health requires source_id and ts_utc")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO source_health
        (source_id, ts_utc, raw_count, kept_count, dated_count, undated_count, future_count,
         dated_ratio, kept_ratio, error_class, error_evidence, run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.get("source_id"),
            snapshot.get("ts_utc"),
            snapshot.get("raw_count"),
            snapshot.get("kept_count"),
            snapshot.get("dated_count"),
            snapshot.get("undated_count"),
            snapshot.get("future_count"),
            snapshot.get("dated_ratio"),
            snapshot.get("kept_ratio"),
            snapshot.get("error_class"),
            snapshot.get("error_evidence"),
            snapshot.get("run_id"),
        ),
    )
    conn.commit()
    conn.close()


def get_last_source_health(source_id: str, limit: int = 14) -> List[Dict]:
    """Fetch recent source_health rows for one source, newest-first."""
    if not source_id:
        return []
    limit = int(limit or 0)
    if limit <= 0:
        limit = 14

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT *
        FROM source_health
        WHERE source_id = ?
        ORDER BY ts_utc DESC, id DESC
        LIMIT ?
        """,
        (source_id, limit),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_latest_source_health_map(source_ids: List[str]) -> Dict[str, Dict]:
    """
    Convenience: get latest snapshot per source_id.

    Returns: {source_id: row_dict}
    """
    if not source_ids:
        return {}
    # Preserve order? caller can re-order; we just return map.
    unique_ids = [s for s in dict.fromkeys([sid for sid in source_ids if sid])]
    if not unique_ids:
        return {}

    conn = get_db()
    cursor = conn.cursor()
    # SQLite window functions are not guaranteed; do a simple approach:
    # fetch latest ts_utc per source, then join back.
    placeholders = ",".join(["?"] * len(unique_ids))
    cursor.execute(
        f"""
        SELECT sh.*
        FROM source_health sh
        JOIN (
            SELECT source_id, MAX(ts_utc) AS max_ts
            FROM source_health
            WHERE source_id IN ({placeholders})
            GROUP BY source_id
        ) latest
        ON sh.source_id = latest.source_id AND sh.ts_utc = latest.max_ts
        """,
        tuple(unique_ids),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # If multiple rows share same ts_utc for a source, prefer highest id.
    best = {}
    for r in rows:
        sid = r.get("source_id")
        if not sid:
            continue
        if sid not in best or int(r.get("id", 0) or 0) > int(best[sid].get("id", 0) or 0):
            best[sid] = r
    return best


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events
    
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
            
            # Check if comment column exists
            try:
                cursor.execute("SELECT comment FROM sources LIMIT 1")
                has_comment_column = True
            except sqlite3.OperationalError:
                has_comment_column = False
                try:
                    cursor.execute("ALTER TABLE sources ADD COLUMN comment TEXT")
                except sqlite3.OperationalError:
                    pass
            
            if has_comment_column or 'comment' in [col[1] for col in cursor.execute("PRAGMA table_info(sources)").fetchall()]:
                cursor.execute("""
                    INSERT OR REPLACE INTO sources 
                    (id, firm_name, firm_type, url, adapter_type, selectors_json, default_tags_json, 
                     title_extraction_json, postprocess_rules_json, detail_fetch_json, api_config_json, active, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source.get('active', 1),
                    source.get('comment')
                ))
            else:
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


def upsert_event(firm_name, event_name, date_time, link, source_id, tags_json=None, format=None,
                 event_type=None, signal_level=None, market_scope_json=None, bank_participants_json=None,
                 intel_type=None, has_explicit_date=None, confidence_score=None, description=None,
                 participant_roles_json=None, signal_score=None, location_text=None, location_city=None,
                 location_country=None, location_lat=None, location_lng=None, registration_type=None,
                 registration_url=None, registration_deadline=None, registration_fee=None, speakers_json=None):
    """
    Insert or update event/intel item. Returns (is_new, event_id).
    
    Args:
        intel_type: 'event' | 'briefing' | 'outlook' | 'webinar' | 'note' | 'invite'
        has_explicit_date: True if date_time is explicit, False if inferred/undated
        confidence_score: 0-100 confidence in classification
    """
    event_id = generate_event_id(firm_name, event_name, date_time, link)
    now = datetime.utcnow().isoformat()
    
    # Serialize bank_participants_json if it's a list
    if bank_participants_json is not None and isinstance(bank_participants_json, list):
        bank_participants_json = json.dumps(bank_participants_json) if bank_participants_json else None
    
    # Serialize participant_roles_json if it's a dict/list (PHASE 4)
    if participant_roles_json is not None and isinstance(participant_roles_json, (dict, list)):
        participant_roles_json = json.dumps(participant_roles_json) if participant_roles_json else None
    
    # Serialize speakers_json if it's a list (PRIORITY 2, Phase 2)
    if speakers_json is not None and isinstance(speakers_json, list):
        speakers_json = json.dumps(speakers_json) if speakers_json else None
    
    # Determine has_explicit_date if not provided
    if has_explicit_date is None:
        has_explicit_date = 1 if date_time else 0
    
    # Default intel_type if not provided
    if intel_type is None:
        intel_type = 'event' if date_time else 'note'
    
    # Default confidence_score
    if confidence_score is None:
        confidence_score = 70 if date_time else 50
    
    # Default signal_score (PHASE 6)
    if signal_score is None:
        signal_score = 50
    
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
                tags_json = COALESCE(?, tags_json),
                format = COALESCE(?, format),
                event_type = COALESCE(?, event_type),
                signal_level = COALESCE(?, signal_level),
                market_scope_json = COALESCE(?, market_scope_json),
                bank_participants_json = COALESCE(?, bank_participants_json),
                intel_type = COALESCE(?, intel_type),
                has_explicit_date = COALESCE(?, has_explicit_date),
                confidence_score = COALESCE(?, confidence_score),
                description = COALESCE(?, description),
                participant_roles_json = COALESCE(?, participant_roles_json),
                signal_score = COALESCE(?, signal_score),
                location_text = COALESCE(?, location_text),
                location_city = COALESCE(?, location_city),
                location_country = COALESCE(?, location_country),
                location_lat = COALESCE(?, location_lat),
                location_lng = COALESCE(?, location_lng),
                registration_type = COALESCE(?, registration_type),
                registration_url = COALESCE(?, registration_url),
                registration_deadline = COALESCE(?, registration_deadline),
                registration_fee = COALESCE(?, registration_fee),
                speakers_json = COALESCE(?, speakers_json)
            WHERE id = ?
        """, (now, date_time, link, tags_json, format, event_type, signal_level, market_scope_json, 
              bank_participants_json, intel_type, has_explicit_date, confidence_score, description, participant_roles_json, signal_score,
              location_text, location_city, location_country, location_lat, location_lng,
              registration_type, registration_url, registration_deadline, registration_fee, speakers_json, event_id))
        conn.commit()
        conn.close()
        return (False, event_id)
    else:
        # Insert new
        cursor.execute("""
            INSERT INTO events 
            (id, firm_name, event_name, date_time, link, source_id, tags_json, format, 
             event_type, signal_level, market_scope_json, bank_participants_json, 
             intel_type, has_explicit_date, confidence_score, description, participant_roles_json, signal_score,
             location_text, location_city, location_country, location_lat, location_lng,
             registration_type, registration_url, registration_deadline, registration_fee, speakers_json, 
             editorial_tags_json, editorial_notes, curator_id, is_featured, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, firm_name, event_name, date_time, link, source_id, tags_json, format,
              event_type, signal_level, market_scope_json, bank_participants_json,
              intel_type, has_explicit_date, confidence_score, description, participant_roles_json, signal_score,
              location_text, location_city, location_country, location_lat, location_lng,
              registration_type, registration_url, registration_deadline, registration_fee, speakers_json,
              None, None, None, 0, now, now))
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


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events
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
            try:
                event['tags_json'] = json.loads(event['tags_json'])
            except:
                pass
        if event.get('market_scope_json'):
            try:
                event['market_scope_json'] = json.loads(event['market_scope_json'])
            except:
                pass
        if event.get('bank_participants_json'):
            try:
                event['bank_participants_json'] = json.loads(event['bank_participants_json'])
            except:
                pass
        return event
    return None


def get_user_event(event_id):
    """Get user metadata for an event."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_events WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def upsert_user_event(event_id, saved=None, note=None):
    """Create or update user event metadata."""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # Get existing record
    cursor.execute("SELECT * FROM user_events WHERE event_id = ?", (event_id,))
    existing = cursor.fetchone()
    
    if existing:
        # Update
        updates = []
        params = []
        if saved is not None:
            updates.append("saved = ?")
            params.append(1 if saved else 0)
        if note is not None:
            updates.append("note = ?")
            params.append(note)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(event_id)
        
        cursor.execute(
            f"UPDATE user_events SET {', '.join(updates)} WHERE event_id = ?",
            params
        )
    else:
        # Insert
        cursor.execute("""
            INSERT INTO user_events (event_id, saved, note, updated_at)
            VALUES (?, ?, ?, ?)
        """, (event_id, 1 if saved else 0, note or '', now))
    
    conn.commit()
    conn.close()


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events
    return get_user_event(event_id)


def is_email_ingested(gmail_id: str = None, sha256: str = None) -> bool:
    """
    Check if email has already been ingested.
    
    Args:
        gmail_id: Gmail message ID
        sha256: SHA256 hash of message content
    
    Returns:
        True if already ingested
    """
    conn = get_db()
    cursor = conn.cursor()
    
    if gmail_id:
        cursor.execute("SELECT 1 FROM ingested_emails WHERE gmail_id = ?", (gmail_id,))
        result = cursor.fetchone() is not None
    elif sha256:
        cursor.execute("SELECT 1 FROM ingested_emails WHERE sha256 = ?", (sha256,))
        result = cursor.fetchone() is not None
    else:
        result = False
    
    conn.close()
    return result


def record_ingested_email(gmail_id: str, thread_id: str, internal_date: str, subject: str,
                         from_addr: str, sha256: str, status: str, failure_reason: str = None):
    """
    Record an ingested email in the database.
    
    Args:
        gmail_id: Gmail message ID
        thread_id: Thread ID
        internal_date: Internal date timestamp
        subject: Email subject
        from_addr: Sender email
        sha256: SHA256 hash
        status: 'ingested', 'rejected', or 'error'
        failure_reason: Rejection reason (if rejected)
    """
    conn = get_db()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT OR REPLACE INTO ingested_emails
        (gmail_id, thread_id, internal_date, subject, from_addr, sha256, status, failure_reason, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (gmail_id, thread_id, internal_date, subject, from_addr, sha256, status, failure_reason, now))
    
    conn.commit()
    conn.close()


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def list_saved_event_ids():
    """Get list of event IDs that are saved."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT event_id FROM user_events WHERE saved = 1")
    event_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return event_ids


def get_all_user_events():
    """Get all user event metadata as a dict keyed by event_id."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_events")
    rows = cursor.fetchall()
    conn.close()
    return {row['event_id']: dict(row) for row in rows}


# Decision management functions (GOVERNANCE)
def get_decision(newsletter_id: str) -> Optional[Dict]:
    """Get current decision for a newsletter."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM newsletter_decisions WHERE newsletter_id = ?", (newsletter_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def is_paused_or_cooldown(newsletter_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check if newsletter is paused or in cooldown.
    
    Returns:
        (is_blocked, reason)
    """
    from datetime import datetime, timezone
    decision = get_decision(newsletter_id)
    if not decision:
        return (False, None)
    
    if decision.get('paused'):
        return (True, f"Paused: {decision.get('paused_reason', 'No reason')}")
    
    cooldown_until = decision.get('cooldown_until')
    if cooldown_until:
        try:
            cooldown_dt = datetime.fromisoformat(cooldown_until.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) < cooldown_dt:
                return (True, f"Cooldown until {cooldown_until}")
        except (ValueError, AttributeError):
            pass
    
    return (False, None)


def record_subscription_failure(newsletter_id: str, failure_type: str):
    """
    Record a subscription failure and update consecutive_failures.
    
    Args:
        newsletter_id: Target ID
        failure_type: 'captcha', 'timeout', 'blocked', 'parse_error', etc.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    # Get current decision
    cursor.execute("""
        SELECT consecutive_failures, last_failure_type
        FROM newsletter_decisions
        WHERE newsletter_id = ?
    """, (newsletter_id,))
    row = cursor.fetchone()
    
    if row:
        consecutive_failures = (row['consecutive_failures'] or 0) + 1
    else:
        consecutive_failures = 1
        # Create decision record if it doesn't exist
        from datetime import datetime, timezone
        cursor.execute("""
            INSERT INTO newsletter_decisions
            (newsletter_id, decision_status, decision_score, decision_reason,
             decision_features_json, recommended_next_action, last_evaluated_at,
             consecutive_failures, last_failure_type, paused)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            newsletter_id,
            'paused',
            0,
            f'Auto-paused after {consecutive_failures} failures',
            '{}',
            'do_nothing',
            datetime.now(timezone.utc).isoformat(),
            consecutive_failures,
            failure_type,
            0
        ))
        conn.commit()
        conn.close()
        return
    
    # Update decision
    cursor.execute("""
        UPDATE newsletter_decisions
        SET consecutive_failures = ?,
            last_failure_type = ?
        WHERE newsletter_id = ?
    """, (consecutive_failures, failure_type, newsletter_id))
    
    conn.commit()
    conn.close()


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def record_subscription_success(newsletter_id: str):
    """Reset consecutive failures on successful subscription."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE newsletter_decisions
        SET consecutive_failures = 0,
            last_failure_type = NULL
        WHERE newsletter_id = ?
    """, (newsletter_id,))
    conn.commit()
    conn.close()


# 4-Zone Architecture: User account helper functions
def get_user_by_email(email):
    """Get user by email."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(email, name=None):
    """Create a new user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)',
        (email, name, created_at)
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {'id': user_id, 'email': email, 'name': name, 'created_at': created_at}


def get_user_interests(user_id):
    """Get all interests for a user, grouped by type."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT interest_type, interest_value FROM user_interests WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    # Group by type
    interests = {'topic': [], 'institution': [], 'format': [], 'region': []}
    for row in rows:
        interest_type = row['interest_type']
        if interest_type in interests:
            interests[interest_type].append(row['interest_value'])
    return interests


def add_user_interest(user_id, interest_type, interest_value):
    """Add an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    from datetime import datetime, timezone
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute(
            'INSERT INTO user_interests (user_id, interest_type, interest_value, created_at) VALUES (?, ?, ?, ?)',
            (user_id, interest_type, interest_value, created_at)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already exists
    conn.close()


def remove_user_interest(user_id, interest_type, interest_value):
    """Remove an interest for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM user_interests WHERE user_id = ? AND interest_type = ? AND interest_value = ?',
        (user_id, interest_type, interest_value)
    )
    conn.commit()
    conn.close()


def get_user_behavior(user_id):
    """Get behavior history for a user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT event_id, action_type, action_at FROM user_behavior WHERE user_id = ?',
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_events_happening_soon(days=14):
    """Get events happening in the next N days, sorted by date (Zone 2)."""
    conn = get_db()
    cursor = conn.cursor()
    
    from datetime import datetime, timedelta, timezone
    cutoff_date = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE date_time IS NOT NULL
        AND date_time >= datetime('now')
        AND date_time <= ?
        ORDER BY date_time ASC
        LIMIT 50
    """, (cutoff_date,))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events


def get_events_by_topic(topic):
    """Get events matching a specific topic (Zone 3)."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM events
        WHERE tags_json LIKE ?
        AND date_time >= datetime('now')
        ORDER BY date_time ASC
        LIMIT 50
    """, (f'%"{topic}"%',))
    
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events

