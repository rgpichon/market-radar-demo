import json
from pathlib import Path
import sys
from datetime import datetime, timezone

# Add backend directory to path for imports
backend_dir = Path(__file__).parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources, upsert_event, create_notification, get_event_by_id
from utils.json_utils import ensure_list, ensure_dict
from utils.pipeline import run_source_pipeline
from utils.quality_gates import enforce_quality_gates_on_scrape
from utils.event_aggregator import aggregate_events, get_existing_event_hashes


def load_preferences():
    """Load preferences.json."""
    prefs_path = Path(__file__).parent / "preferences.json"
    with open(prefs_path, 'r') as f:
        return json.load(f)


def load_packs():
    """Load packs.json."""
    packs_path = Path(__file__).parent / "packs.json"
    with open(packs_path, 'r') as f:
        return json.load(f)


def normalize_for_comparison(s):
    """Normalize a string for case-insensitive comparison."""
    if not s:
        return ""
    return str(s).lower().strip()


def should_notify(event, preferences, packs):
    """
    Determine if a new event should trigger a notification.
    Returns True if notification should be created.
    Uses normalized (lowercase, stripped) comparisons for robustness.
    """
    # Check if event is confirmed
    confirmed = bool(event.get('date_time') and event.get('link'))
    
    if preferences.get('require_confirmed_for_notifications') and not confirmed:
        return False
    
    # Normalize event firm name for comparison
    firm_name = normalize_for_comparison(event.get('firm_name', ''))
    
    # Ensure tags is a list and normalize
    event_tags = ensure_list(event.get('tags'))
    event_tags_normalized = {normalize_for_comparison(t) for t in event_tags if t}
    
    # Normalize follow_firms for comparison
    follow_firms = ensure_list(preferences.get('follow_firms'))
    follow_firms_normalized = {normalize_for_comparison(f) for f in follow_firms if f}
    
    # Check firm match (normalized)
    if firm_name and firm_name in follow_firms_normalized:
        return True
    
    # Check pack match (normalized)
    follow_packs = ensure_list(preferences.get('follow_packs'))
    for pack_id in follow_packs:
        pack = packs.get(pack_id, {})
        pack_firms = ensure_list(pack.get('firms'))
        pack_firms_normalized = {normalize_for_comparison(f) for f in pack_firms if f}
        if firm_name and firm_name in pack_firms_normalized:
            return True
    
    # Check tag match (normalized)
    follow_tags = ensure_list(preferences.get('follow_tags'))
    follow_tags_normalized = {normalize_for_comparison(t) for t in follow_tags if t}
    
    if event_tags_normalized.intersection(follow_tags_normalized):
        # Basic matching passed, now evaluate alert rules (Phase 1: Intelligent Alerting Rules)
        alert_rules = preferences.get('alert_rules', {})
        if alert_rules:
            from utils.notification_rules import evaluate_all_rules
            if not evaluate_all_rules(event, alert_rules):
                return False  # Alert rules failed, don't notify
        
        return True
    
    return False


def scrape_source(source, preferences, packs):
    """
    Scrape a single source using the pipeline.
    Returns (events_found, inserted_count, updated_count, notifications_created, error, diagnostics).
    """
    try:
        # Run pipeline (extraction + normalization + filtering)
        pipeline_result = run_source_pipeline(source)
        
        kept_events = pipeline_result['kept_events']
        diagnostics = pipeline_result['diagnostics']
        run_stats = pipeline_result['run_stats']
        
        # Deduplicate within this scrape run (prevent same event twice in one run)
        # Note: We still process events that exist in DB (they will be updated, not inserted)
        from utils.event_aggregator import compute_event_hash
        
        canonical_events = []
        seen_hashes_in_run = set()
        
        for event in kept_events:
            event_hash = compute_event_hash(event)
            # Only skip if we've seen this exact event in THIS scrape run
            if event_hash in seen_hashes_in_run:
                run_stats['rejected']['duplicate_in_run'] = run_stats['rejected'].get('duplicate_in_run', 0) + 1
                continue
            seen_hashes_in_run.add(event_hash)
            canonical_events.append(event)
        
        # Update stats (use kept_events count, not canonical - canonical is just for within-run dedup)
        run_stats['kept_count'] = len(kept_events)  # All kept events should be processed
        if run_stats['raw_count'] > 0:
            run_stats['kept_ratio'] = len(kept_events) / run_stats['raw_count']
        
        # Merge run_stats into diagnostics for backward compatibility
        diagnostics['run_stats'] = run_stats
        if 'extraction_stats' in diagnostics:
            diagnostics['extraction_stats'] = diagnostics['extraction_stats']
        
        inserted_count = 0
        updated_count = 0
        notifications_created = 0
        
        # Upsert canonical events
        for event in canonical_events:
            # Ensure tags is a list and serialize
            tags = ensure_list(event.get('tags_json', []))
            tags_json = json.dumps(tags) if tags else None
            
            # Get semantic fields
            event_type = event.get('event_type')
            signal_level = event.get('signal_level')
            market_scope_json = event.get('market_scope_json')  # Already JSON string from pipeline
            
            is_new, event_id = upsert_event(
                firm_name=event['firm_name'],
                event_name=event['event_name'],
                date_time=event.get('date_time'),
                link=event['link'],
                source_id=source['id'],
                bank_participants_json=event.get('bank_participants_json'),
                tags_json=tags_json,
                format=event.get('format'),
                event_type=event_type,
                signal_level=signal_level,
                market_scope_json=market_scope_json,
                description=event.get('description'),  # PHASE 3
                intel_type=event.get('intel_type'),  # PHASE 1
                confidence_score=event.get('confidence_score'),  # PHASE 1
                participant_roles_json=event.get('participant_roles_json'),  # PHASE 4
                signal_score=event.get('signal_score', 50),  # PHASE 6
                location_text=event.get('location_text'),  # PRIORITY 2, Phase 3
                location_city=event.get('location_city'),  # PRIORITY 2, Phase 3
                location_country=event.get('location_country'),  # PRIORITY 2, Phase 3
                registration_type=event.get('registration_type'),  # PRIORITY 2, Phase 4
                registration_url=event.get('registration_url'),  # PRIORITY 2, Phase 4
                registration_deadline=event.get('registration_deadline'),  # PRIORITY 2, Phase 4
                registration_fee=event.get('registration_fee'),  # PRIORITY 2, Phase 4
                speakers_json=event.get('speakers_json')  # PRIORITY 2, Phase 2
            )
            
            if is_new:
                inserted_count += 1
                # Check if should notify (new matches only)
                if should_notify(event, preferences, packs):
                    if create_notification(event_id, reason="new_match"):
                        notifications_created += 1
                        
                        # Phase 2: Send notifications via configured channels
                        channels = preferences.get('notification_channels', {})
                        
                        # Email channel
                        if channels.get('email', {}).get('enabled'):
                            try:
                                from utils.email_sender import send_notification_email
                                email_config = channels.get('email', {})
                                recipient = email_config.get('recipient')
                                if recipient:
                                    send_notification_email(event, recipient, email_config)
                            except Exception as e:
                                print(f"Error sending email notification: {e}")
                        
                        # Webhook channel
                        if channels.get('webhook', {}).get('enabled'):
                            try:
                                from utils.webhook_sender import send_webhooks_for_event
                                webhook_configs = channels.get('webhook', {}).get('webhooks', [])
                                send_webhooks_for_event(event, webhook_configs)
                            except Exception as e:
                                print(f"Error sending webhook notification: {e}")
                        
                        # Calendar channel (no immediate action, handled via API endpoint)
                        # Calendar export available via GET /api/events/calendar
            else:
                updated_count += 1
        
        # Check for error in diagnostics
        error = diagnostics.get('error')
        if error:
            return (0, 0, 0, 0, error, diagnostics)
        
        # QUALITY GATE: Check for degradation
        gate_passed, warnings = enforce_quality_gates_on_scrape(source)
        if warnings:
            # Add warnings to diagnostics
            if 'quality_gate_warnings' not in diagnostics:
                diagnostics['quality_gate_warnings'] = []
            diagnostics['quality_gate_warnings'].extend(warnings)
        
        # Update source KPIs (operational improvements)
        try:
            from utils.source_kpis import update_source_kpis
            scrape_stats = {
                'kept_count': len(canonical_events),
                'dated_count': run_stats.get('dated_count', 0),
                'undated_count': run_stats.get('undated_count', 0),
                'future_count': run_stats.get('future_count', 0)
            }
            update_source_kpis(source.get('id', ''), scrape_stats, extraction_stats)
        except Exception:
            pass  # Non-blocking
        
        return (len(canonical_events), inserted_count, updated_count, notifications_created, None, diagnostics)
        
    except Exception as e:
        diagnostics = {
            'adapter_type': source.get('adapter_type'),
            'url': source.get('url'),
            'error': f"Error: {str(e)}",
            'error_type': type(e).__name__
        }
        return (0, 0, 0, 0, f"Error: {str(e)}", diagnostics)


def run_scrape():
    """
    Run scraping for all active sources.
    Returns summary dict with detailed statistics.
    """
    sources = get_sources(active_only=True)
    
    # Load preferences and packs once for all sources
    preferences = load_preferences()
    packs = load_packs()
    
    total_inserted = 0
    total_updated = 0
    total_notifications = 0
    total_extracted = 0
    total_raw = 0
    sources_ok = 0
    sources_zero = 0
    sources_failed = 0
    source_results = []
    
    # Semantic stats
    semantic_stats = {
        'event_type': {},
        'signal_level': {}
    }
    
    # Source scorecard stats (computed after scrape)
    source_stats = {}
    
    for source in sources:
        events_found, inserted, updated, notifications, error, diagnostics = scrape_source(
            source, preferences, packs
        )
        
        # Get stats from run_stats (computed during scrape from events list)
        if diagnostics and 'run_stats' in diagnostics:
            run_stats = diagnostics['run_stats']
            raw_count = run_stats['raw_count']
            kept_count = run_stats['kept_count']
            dated_count = run_stats['dated_count']
            undated_count = run_stats['undated_count']
            future_count = run_stats['future_count']
            kept_ratio = run_stats['kept_ratio']
            dated_ratio = run_stats['dated_ratio']
            # Get top rejection reasons from rejected dict
            rejected = run_stats.get('rejected', {})
            if rejected:
                sorted_reasons = sorted(rejected.items(), key=lambda x: -x[1])[:5]
                top_rejection_reasons = dict(sorted_reasons)
            else:
                top_rejection_reasons = {}
        else:
            # Fallback if run_stats not available (error case)
            raw_count = 0
            kept_count = 0
            dated_count = 0
            undated_count = 0
            future_count = 0
            kept_ratio = 0.0
            dated_ratio = 0.0
            top_rejection_reasons = {}
            if diagnostics and 'extraction_stats' in diagnostics:
                raw_count = diagnostics['extraction_stats'].get('raw', 0)
            kept_count = events_found
        
        total_raw += raw_count
        total_extracted += events_found
        total_inserted += inserted
        total_updated += updated
        total_notifications += notifications
        
        if error:
            sources_failed += 1
        elif events_found == 0:
            sources_zero += 1
        else:
            sources_ok += 1
        
        result = {
            'source_id': source['id'],
            'firm_name': source['firm_name'],
            'raw_items': raw_count,
            'events_found': events_found,
            'inserted': inserted,
            'updated': updated,
            'notifications': notifications,
            'error': error
        }
        
        # Add rejection reasons if available
        if diagnostics and 'extraction_stats' in diagnostics:
            stats = diagnostics['extraction_stats']
            if stats.get('rejected'):
                result['rejected_reasons'] = stats['rejected']
        
        # Add diagnostics if 0 events found or error
        if (events_found == 0 or error) and diagnostics:
            result['diagnostics'] = diagnostics
        
        source_results.append(result)
        
        # Store run-based stats (computed from events list, not DB)
        from datetime import datetime
        # Collect JS detection info from diagnostics (Phase 4: Source Classification)
        js_detected = diagnostics.get('is_js_rendered', False)
        js_detection_method = diagnostics.get('js_detection', None)
        suggested_adapter = diagnostics.get('suggested_adapter_type', None)
        playwright_fallback_attempted = diagnostics.get('playwright_fallback_attempted', False)
        playwright_fallback_success = diagnostics.get('playwright_fallback_success', False)
        
        # Track retry statistics if present in diagnostics (Priority 5, Phase 1)
        retry_attempts = diagnostics.get('retry_attempts', 0)
        retry_success = diagnostics.get('retry_success', None)
        
        # Phase 3: Health monitoring (Priority 5, Phase 3)
        try:
            from utils.health_monitor import save_health_snapshot, detect_selector_breakage
            
            # Save health snapshot
            save_health_snapshot(source['id'], {
                'kept_ratio': kept_ratio,
                'dated_ratio': dated_ratio,
                'raw_count': raw_count,
                'future_count': future_count
            })
            
            # Check for selector breakage
            breakage = detect_selector_breakage(source['id'], {
                'kept_ratio': kept_ratio,
                'raw_count': raw_count
            })
            if breakage:
                diagnostics['selector_breakage'] = breakage
                diagnostics['alert'] = 'selector_breakage_detected'
        except Exception as e:
            # Health monitoring is optional, don't fail on errors
            pass
        
        source_stats[source['id']] = {
            'raw_count': raw_count,
            'kept_count': kept_count,
            'dated_count': dated_count,
            'undated_count': undated_count,
            'future_count': future_count,
            'kept_ratio': kept_ratio,
            'dated_ratio': dated_ratio,
            'top_rejection_reasons': top_rejection_reasons,
            'last_scrape_at': datetime.now().isoformat(),
            # Phase 4: JS detection tracking (Priority 3, Phase 4)
            'js_detected': js_detected,
            'js_detection_method': js_detection_method,
            'suggested_adapter_type': suggested_adapter,
            'playwright_fallback_attempted': playwright_fallback_attempted,
            'playwright_fallback_success': playwright_fallback_success,
            # Phase 1: Retry statistics (Priority 5, Phase 1)
            'retry_attempts': retry_attempts,
            'retry_success': retry_success
        }
    
    # Collect semantic stats from database
    from db import get_db
    conn = get_db()
    cursor = conn.cursor()
    
    # Count by event_type
    cursor.execute("SELECT event_type, COUNT(*) as cnt FROM events WHERE event_type IS NOT NULL GROUP BY event_type")
    for row in cursor.fetchall():
        semantic_stats['event_type'][row['event_type']] = row['cnt']
    
    # Count by signal_level
    cursor.execute("SELECT signal_level, COUNT(*) as cnt FROM events WHERE signal_level IS NOT NULL GROUP BY signal_level")
    for row in cursor.fetchall():
        semantic_stats['signal_level'][row['signal_level']] = row['cnt']
    
    conn.close()
    
    # Update meta.json with last scrape time and total events count
    from datetime import datetime
    from db import get_db
    
    meta_path = Path(__file__).parent / "meta.json"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]
    conn.close()
    
    meta = {
        'last_scrape_at': datetime.now().isoformat(),
        'total_events': total_events
    }
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    
    # Save source stats to separate file
    source_stats_path = Path(__file__).parent / "source_stats.json"
    with open(source_stats_path, 'w') as f:
        json.dump(source_stats, f, indent=2)
    
    # Phase 3: Notification Aggregation (if configured)
    if total_notifications > 0:
        try:
            # Get recent notifications
            from db import get_db
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT n.*, e.firm_name, e.tags_json
                FROM notifications n
                JOIN events e ON n.event_id = e.id
                WHERE n.created_at >= datetime('now', '-1 hour')
                AND n.seen = 0
            """)
            
            recent_notifs = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            # Aggregate if configured
            agg_mode = preferences.get('notification_aggregation', {}).get('mode', 'none')
            
            if agg_mode != 'none' and recent_notifs:
                try:
                    from utils.notification_aggregator import aggregate_notifications
                    aggregated = aggregate_notifications(recent_notifs, agg_mode)
                    # Store aggregated notifications in database (optional - can be used for delivery)
                    # For now, aggregation is available via API if needed
                except Exception as e:
                    print(f"Error aggregating notifications: {e}")
        except Exception as e:
            print(f"Error in notification aggregation: {e}")
    
    # Close browser pool if it exists (Phase 3: Performance Optimization)
    try:
        from utils.browser_pool import close_browser_pool
        close_browser_pool()
    except ImportError:
        pass
    
    # Reset rate limiter (Phase 2: Rate Limiting)
    try:
        from utils.rate_limiter import reset_rate_limiter
        reset_rate_limiter()
    except ImportError:
        pass
    
    return {
        'total_sources': len(sources),
        'sources_ok': sources_ok,
        'sources_zero': sources_zero,
        'sources_failed': sources_failed,
        'total_raw': total_raw,
        'total_extracted': total_extracted,
        'total_inserted': total_inserted,
        'total_updated': total_updated,
        'total_notifications': total_notifications,
        'semantic_stats': semantic_stats,
        'source_results': source_results
    }
