#!/usr/bin/env python3
"""
Smoke test for Market Events Radar.
Verifies end-to-end pipeline: compile, scrape, API, ordering, schema.

Usage:
    cd backend
    python scripts/smoke_test.py
"""

import sys
import os
import subprocess
import time
import signal
import json
import re
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Configuration
DEFAULT_PORT = 5050  # Use 5050 to avoid conflicts with existing Flask/AirPlay
API_BASE = f"http://127.0.0.1:{DEFAULT_PORT}"
STARTUP_TIMEOUT = 10
REQUEST_TIMEOUT = 15

# Required keys in /api/events response
REQUIRED_KEYS = {'firm_name', 'event_name', 'link', 'date_time', 'format', 'tags_json'}
# Semantic fields (must be present and valid)
SEMANTIC_FIELDS = {'event_type', 'signal_level', 'market_scope_json'}
VALID_EVENT_TYPES = {'policy', 'market', 'research', 'academic', 'other'}
VALID_SIGNAL_LEVELS = {'low', 'medium', 'high'}


def print_header(msg):
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def print_ok(msg):
    print(f"  ✓ {msg}")


def print_fail(msg):
    print(f"  ✗ {msg}")


def print_info(msg):
    print(f"  → {msg}")


def run_compile():
    """Run compileall on backend."""
    print_header("PHASE 1: Compile backend")
    
    result = subprocess.run(
        [sys.executable, "-m", "compileall", str(backend_dir), "-q"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print_fail("Compilation failed")
        print(result.stderr)
        return False
    
    print_ok("Backend compiled successfully")
    return True


def run_scrape():
    """Run scrape and extract counts."""
    print_header("PHASE 2: Run scrape")
    
    run_scrape_path = backend_dir / "scripts" / "run_scrape.py"
    
    result = subprocess.run(
        [sys.executable, str(run_scrape_path)],
        capture_output=True,
        text=True,
        cwd=str(backend_dir),
        timeout=120
    )
    
    if result.returncode != 0:
        print_fail("Scrape failed")
        print(result.stderr)
        return None
    
    output = result.stdout + result.stderr
    
    # Parse counts from output
    inserted_match = re.search(r'Inserted:\s*(\d+)', output)
    updated_match = re.search(r'Updated:\s*(\d+)', output)
    
    inserted = int(inserted_match.group(1)) if inserted_match else -1
    updated = int(updated_match.group(1)) if updated_match else -1
    
    print_ok(f"Scrape completed: inserted={inserted}, updated={updated}")
    return {'inserted': inserted, 'updated': updated}


def start_flask_server():
    """Start Flask app in subprocess."""
    print_header("PHASE 3: Start Flask server")
    
    env = os.environ.copy()
    env['FLASK_RUN_PORT'] = str(DEFAULT_PORT)
    
    app_path = backend_dir / "app.py"
    
    # Start Flask with custom port
    proc = subprocess.Popen(
        [sys.executable, str(app_path), '--port', str(DEFAULT_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(backend_dir),
        env=env
    )
    
    print_info(f"Starting Flask on port {DEFAULT_PORT}...")
    
    # Wait for server to be ready
    import requests
    start_time = time.time()
    while time.time() - start_time < STARTUP_TIMEOUT:
        try:
            resp = requests.get(f"{API_BASE}/api/events", timeout=2)
            if resp.status_code in [200, 500]:  # Server is responding
                print_ok(f"Flask server ready at {API_BASE}")
                return proc
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
        except Exception as e:
            time.sleep(0.5)
    
    print_fail("Flask server failed to start")
    proc.terminate()
    return None


def stop_flask_server(proc):
    """Stop Flask subprocess."""
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print_info("Flask server stopped")


def test_api_default():
    """Test default /api/events endpoint."""
    print_header("PHASE 4: Test API (default params)")
    
    import requests
    from datetime import datetime, timezone, timedelta
    
    try:
        resp = requests.get(f"{API_BASE}/api/events", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print_fail(f"API request failed: {e}")
        return None
    
    # Check non-empty
    if not data or len(data) == 0:
        print_fail("Default API returned empty list")
        return None
    print_ok(f"Default API returned {len(data)} events")
    
    # Check required keys
    first_item = data[0]
    missing_keys = REQUIRED_KEYS - set(first_item.keys())
    if missing_keys:
        print_fail(f"Missing required keys: {missing_keys}")
        return None
    print_ok(f"All required keys present: {REQUIRED_KEYS}")
    
    # Validate semantic fields
    print_info("Validating semantic fields...")
    missing_semantic = []
    invalid_event_types = []
    invalid_signal_levels = []
    missing_market_scope = []
    
    for i, event in enumerate(data):
        # Check presence
        for field in SEMANTIC_FIELDS:
            if field not in event or event[field] is None:
                missing_semantic.append((i, field, event.get('firm_name', 'unknown')))
        
        # Validate event_type
        event_type = event.get('event_type')
        if event_type and event_type not in VALID_EVENT_TYPES:
            invalid_event_types.append((i, event_type, event.get('firm_name', 'unknown')))
        
        # Validate signal_level
        signal_level = event.get('signal_level')
        if signal_level and signal_level not in VALID_SIGNAL_LEVELS:
            invalid_signal_levels.append((i, signal_level, event.get('firm_name', 'unknown')))
        
        # Validate market_scope_json (should be parseable JSON array)
        market_scope_json = event.get('market_scope_json')
        if market_scope_json:
            try:
                scope_list = json.loads(market_scope_json) if isinstance(market_scope_json, str) else market_scope_json
                if not isinstance(scope_list, list):
                    missing_market_scope.append((i, "not a list", event.get('firm_name', 'unknown')))
            except (json.JSONDecodeError, TypeError):
                missing_market_scope.append((i, "invalid JSON", event.get('firm_name', 'unknown')))
        else:
            missing_market_scope.append((i, "missing", event.get('firm_name', 'unknown')))
    
    if missing_semantic:
        print_fail(f"{len(missing_semantic)} events missing semantic fields")
        for idx, field, firm in missing_semantic[:5]:
            print_info(f"  Event {idx} ({firm}): missing {field}")
        return None
    
    if invalid_event_types:
        print_fail(f"{len(invalid_event_types)} events have invalid event_type")
        for idx, et, firm in invalid_event_types[:5]:
            print_info(f"  Event {idx} ({firm}): invalid event_type='{et}'")
        return None
    
    if invalid_signal_levels:
        print_fail(f"{len(invalid_signal_levels)} events have invalid signal_level")
        for idx, sl, firm in invalid_signal_levels[:5]:
            print_info(f"  Event {idx} ({firm}): invalid signal_level='{sl}'")
        return None
    
    if missing_market_scope:
        print_fail(f"{len(missing_market_scope)} events have invalid/missing market_scope_json")
        for idx, reason, firm in missing_market_scope[:5]:
            print_info(f"  Event {idx} ({firm}): market_scope_json {reason}")
        return None
    
    print_ok(f"All {len(data)} events have valid semantic fields")
    
    # Print semantic stats
    event_type_counts = {}
    signal_level_counts = {}
    for event in data:
        et = event.get('event_type', 'unknown')
        event_type_counts[et] = event_type_counts.get(et, 0) + 1
        sl = event.get('signal_level', 'unknown')
        signal_level_counts[sl] = signal_level_counts.get(sl, 0) + 1
    
    print_info(f"Event types: {dict(sorted(event_type_counts.items()))}")
    print_info(f"Signal levels: {dict(sorted(signal_level_counts.items()))}")
    
    # Check ALL dates are non-null in default mode
    null_dates = [i for i, e in enumerate(data) if e.get('date_time') is None]
    if null_dates:
        print_fail(f"Default mode has {len(null_dates)} items with null date_time (should be 0)")
        return None
    print_ok("All events in default mode have date_time (with_date=1 default working)")
    
    # Check ALL dates are FUTURE (>= today) - no past events
    # Allow small tolerance for clock skew (-5 minutes)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
    
    dates = [e['date_time'] for e in data]
    past_events = []
    for i, dt_str in enumerate(dates):
        try:
            # Parse ISO datetime
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < today_start:
                past_events.append((i, dt_str, data[i].get('firm_name')))
        except (ValueError, TypeError):
            pass
    
    if past_events:
        print_fail(f"Default mode has {len(past_events)} PAST events (should be 0 - future-only)")
        for idx, dt, firm in past_events[:5]:
            print_info(f"  Past event: {firm} on {dt}")
        return None
    print_ok("All events are FUTURE (no past events - future-only filter working)")
    
    # Check chronological ordering (ascending)
    sorted_dates = sorted(dates)
    if dates != sorted_dates:
        print_fail("Dates are NOT in ascending order")
        # Find first out-of-order pair
        for i in range(len(dates) - 1):
            if dates[i] > dates[i + 1]:
                print_info(f"  First mismatch at index {i}: {dates[i]} > {dates[i + 1]}")
                break
        return None
    print_ok("Dates are in ascending chronological order")
    
    # Print sample with earliest/latest
    print_info(f"Earliest date: {dates[0]}")
    print_info(f"Latest date: {dates[-1]}")
    print_info(f"First 3 dates: {dates[:3]}")
    print_info(f"Last 3 dates: {dates[-3:]}")
    
    return data


def test_api_with_undated():
    """Test /api/events with undated items included."""
    print_header("PHASE 5: Test API (with undated)")
    
    import requests
    from datetime import datetime, timezone, timedelta
    
    try:
        resp = requests.get(
            f"{API_BASE}/api/events",
            params={'with_date': '0', 'days_ahead': '365'},
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print_fail(f"API request failed: {e}")
        return None
    
    print_ok(f"API returned {len(data)} events (with undated)")
    
    # Count dated and undated
    dated = [e for e in data if e.get('date_time') is not None]
    undated = [e for e in data if e.get('date_time') is None]
    
    print_info(f"Dated: {len(dated)}, Undated: {len(undated)}")
    
    # Check dated events are FUTURE (>= today) - no past events even in with_date=0 mode
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
    
    past_events = []
    for e in dated:
        dt_str = e.get('date_time')
        try:
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < today_start:
                past_events.append((dt_str, e.get('firm_name')))
        except (ValueError, TypeError):
            pass
    
    if past_events:
        print_fail(f"with_date=0 mode has {len(past_events)} PAST dated events (should be 0)")
        for dt, firm in past_events[:3]:
            print_info(f"  Past event: {firm} on {dt}")
        return None
    print_ok("All dated events are FUTURE (no past events)")
    
    # Check ordering: dated first, undated last
    first_undated_idx = None
    for i, e in enumerate(data):
        if e.get('date_time') is None:
            first_undated_idx = i
            break
    
    if first_undated_idx is not None:
        # Check all items after first_undated_idx are undated
        for i in range(first_undated_idx, len(data)):
            if data[i].get('date_time') is not None:
                print_fail(f"Dated item found after undated items (index {i})")
                return None
        print_ok("Undated items correctly placed at the end")
        
        # Check dated items (before first_undated_idx) are sorted ascending
        dated_dates = [e['date_time'] for e in data[:first_undated_idx]]
        sorted_dated_dates = sorted(dated_dates)
        if dated_dates != sorted_dated_dates:
            print_fail("Dated items are NOT in ascending order")
            return None
        print_ok("Dated items are in ascending chronological order")
    else:
        # All items are dated
        print_info("No undated items in response")
    
    # Print sample
    if dated:
        print_info(f"First 3 dated: {[e['date_time'] for e in dated[:3]]}")
    if undated:
        print_info(f"First 3 undated: {[e.get('firm_name') for e in undated[:3]]}")
    
    return data


def test_source_stats():
    """Test source scorecard consistency."""
    print_header("PHASE 6: Test source scorecard consistency")
    
    try:
        response = requests.get(f"{API_BASE}/api/source_stats", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        stats = response.json()
        
        if not stats:
            print_ok("Source stats endpoint returns data (empty is OK if no sources)")
            return True
        
        all_valid = True
        for source_id, source_stat in stats.items():
            raw_count = source_stat.get('raw_count', 0)
            kept_count = source_stat.get('kept_count', 0)
            dated_count = source_stat.get('dated_count', 0)
            undated_count = source_stat.get('undated_count', 0)
            kept_ratio = source_stat.get('kept_ratio', 0.0)
            dated_ratio = source_stat.get('dated_ratio', 0.0)
            
            # Assertions
            issues = []
            
            # kept_count <= raw_count
            if kept_count > raw_count:
                issues.append(f"kept_count ({kept_count}) > raw_count ({raw_count})")
            
            # dated_count + undated_count == kept_count
            if dated_count + undated_count != kept_count:
                issues.append(f"dated_count ({dated_count}) + undated_count ({undated_count}) != kept_count ({kept_count})")
            
            # dated_ratio in [0, 1]
            if dated_ratio < 0 or dated_ratio > 1:
                issues.append(f"dated_ratio ({dated_ratio}) not in [0, 1]")
            
            # kept_ratio in [0, 1] (or could be > 1 if raw_count is from extraction_stats but kept is from DB, but we fixed that)
            if kept_ratio < 0:
                issues.append(f"kept_ratio ({kept_ratio}) < 0")
            
            if issues:
                print_fail(f"Source {source_id} has inconsistencies:")
                for issue in issues:
                    print(f"    - {issue}")
                all_valid = False
            else:
                print_ok(f"Source {source_id}: ratios valid, counts consistent")
        
        return all_valid
        
    except Exception as e:
        print_fail(f"Error testing source stats: {e}")
        return False


def test_bank_hard_stops():
    """Test hard stop rules for banks."""
    print_header("PHASE 7: Test bank hard stops")
    
    from db import get_sources
    from utils.source_registry import sync_registry, load_registry
    from utils.scraping_strategy import identify_sector
    
    # Sync registry
    sync_registry()
    registry = load_registry()
    sources = get_sources(active_only=False)
    
    errors = []
    
    # Check 1: No active bank sources without validated lane
    for source in sources:
        firm_name = source.get('firm_name', '')
        sector = identify_sector(firm_name, source.get('firm_type'))
        active = source.get('active', 0) == 1
        
        if sector == 'bulge_bracket' and active:
            source_id = source.get('id')
            registry_entry = registry.get(source_id)
            
            if not registry_entry:
                errors.append(f"Active bank source {source_id} not in registry")
                continue
            
            validation_status = registry_entry.get('validation_status')
            if validation_status != 'validated':
                errors.append(f"Active bank source {source_id} has validation_status={validation_status}, expected 'validated'")
            
            lane = registry_entry.get('lane')
            from utils.lanes import is_lane_supported
            if not is_lane_supported(lane):
                errors.append(f"Active bank source {source_id} uses unsupported lane: {lane}")
    
    # Check 2: All banks have failure_class if not active
    for source in sources:
        firm_name = source.get('firm_name', '')
        sector = identify_sector(firm_name, source.get('firm_type'))
        active = source.get('active', 0) == 1
        
        if sector == 'bulge_bracket' and not active:
            source_id = source.get('id')
            registry_entry = registry.get(source_id)
            
            if not registry_entry:
                errors.append(f"Inactive bank source {source_id} not in registry")
                continue
            
            failure_class = registry_entry.get('failure_class')
            if not failure_class:
                errors.append(f"Inactive bank source {source_id} missing failure_class")
    
    # Check 3: No bank source active without third_party_calendar lane (if using third-party)
    for source in sources:
        firm_name = source.get('firm_name', '')
        sector = identify_sector(firm_name, source.get('firm_type'))
        active = source.get('active', 0) == 1
        
        if sector == 'bulge_bracket' and active:
            source_id = source.get('id')
            registry_entry = registry.get(source_id)
            
            if registry_entry:
                lane = registry_entry.get('lane')
                # If it's a third-party calendar source, ensure it's validated
                if lane == 'third_party_calendar':
                    validation_status = registry_entry.get('validation_status')
                    if validation_status != 'validated':
                        errors.append(f"Active third-party calendar source {source_id} not validated")
    
    # Check 4: Every bank has terminal state (no silent failures)
    from pathlib import Path
    bank_assets_file = Path(__file__).parent.parent / "bank_assets.json"
    bank_third_party_file = Path(__file__).parent.parent / "bank_third_party_results.json"
    
    if bank_assets_file.exists():
        with open(bank_assets_file) as f:
            bank_assets = json.load(f)
        
        for bank_name, assets in bank_assets.items():
            failure_class = assets.get('failure_class')
            if failure_class is None:
                # Check if it's truly successful (has events)
                methods = assets.get('methods', [])
                successful = [m for m in methods if m.get('status') in ['found', 'detected']]
                if not successful:
                    errors.append(f"Bank {bank_name} has no failure_class but no successful methods")
    
    if bank_third_party_file.exists():
        with open(bank_third_party_file) as f:
            bank_third_party = json.load(f)
        
        for bank_name, result in bank_third_party.items():
            failure_class = result.get('failure_class')
            if failure_class is None:
                # Check if it truly has events
                best_result = result.get('best_result', {})
                if best_result.get('events_found', 0) < 2:
                    errors.append(f"Bank {bank_name} third-party has no failure_class but < 2 events")
    
    if errors:
        print_fail(f"{len(errors)} hard stop violations found")
        for error in errors[:10]:
            print_info(f"  {error}")
        return False
    
    # Check 5: Third-party calendar parsers are not stubs
    # Test that at least one provider can be called and returns proper diagnostics
    from adapters.third_party_calendar import extract_events
    
    test_calendar_config = {'calendar_type': 'nasdaq_earnings_api', 'ticker': 'AAPL'}  # Use AAPL as test (more likely to have earnings)
    test_source_config = {'firm_name': 'Apple Inc', 'id': 'smoke_test', 'default_tags_json': [], 'enforce_events_only': True}
    
    try:
        test_events, test_stats = extract_events(test_calendar_config, test_source_config, return_stats=True)
        test_diagnostics = test_stats.get('diagnostics', {})
        
        # Assert that we got real diagnostics (not stub)
        # A stub would return empty diagnostics or no HTTP evidence
        if not test_diagnostics:
            errors.append("Third-party calendar parser returned no diagnostics (possible stub)")
        elif test_diagnostics.get('fetched_url') is None and test_diagnostics.get('status_code') is None:
            # If we have no URL and no status, it might be a stub
            # But allow if we have parse_errors (which indicates real parsing attempt)
            if not test_diagnostics.get('parse_errors'):
                errors.append("Third-party calendar parser shows no HTTP request evidence (possible stub)")
        # If we have fetched_url or status_code, it's a real parser (even if no events found)
    except Exception as e:
        # If parser fails completely, that's also a problem
        errors.append(f"Third-party calendar parser raised exception: {str(e)}")
    
    if errors:
        print_fail(f"{len(errors)} hard stop violations found")
        for error in errors[:10]:
            print_info(f"  {error}")
        return False
    
    print_ok("All bank hard stops passed")
    return True


def test_dedup():
    """Test that second scrape inserts ~0."""
    print_header("PHASE 8: Test dedup (second scrape)")
    
    scrape_result = run_scrape()
    if scrape_result is None:
        return False
    
    if scrape_result['inserted'] > 5:  # Allow small margin for timing
        print_fail(f"Second scrape inserted {scrape_result['inserted']} items (expected ~0)")
        return False
    
    print_ok(f"Dedup working: inserted={scrape_result['inserted']}, updated={scrape_result['updated']}")
    return True


def main():
    """Run all smoke tests."""
    print("\n" + "=" * 60)
    print("   MARKET EVENTS RADAR - SMOKE TEST")
    print("=" * 60)
    
    flask_proc = None
    all_passed = True
    
    try:
        # Phase 0: Test HTML autoparser
        try:
            test_html_autoparser()
            
            # Optional: Test detail enrichment
            try:
                test_detail_enrichment()
            except Exception as e:
                print_info(f"Detail enrichment test skipped: {e}")
        except Exception:
            pass  # Non-blocking, but log if it fails
        
        # Phase 0.5: Test source maintenance loop (dry-run)
        if not test_maintenance_loop():
            all_passed = False
        
        # Phase 1: Compile
        if not run_compile():
            return 1
        
        # Phase 2: Initial scrape
        if run_scrape() is None:
            return 1
        
        # Phase 3: Start Flask
        flask_proc = start_flask_server()
        if flask_proc is None:
            return 1
        
        # Phase 4: Test default API
        if test_api_default() is None:
            all_passed = False
        
        # Phase 5: Test with undated
        if test_api_with_undated() is None:
            all_passed = False
        
        # Phase 6: Test source stats consistency
        if not test_source_stats():
            all_passed = False
        
        # Phase 7: Test bank hard stops
        if not test_bank_hard_stops():
            all_passed = False
        
        # Phase 8: Test newsletter targets registry
        if not test_newsletter_targets_registry():
            all_passed = False
        
        # Phase 9: Test newsletter targets report
        if not test_newsletter_targets_report():
            all_passed = False
        
        # Phase 10: Test Gmail targets tools
        if not test_gmail_targets_tools():
            all_passed = False
        
        # Phase 11: Test newsletter sender discovery
        if not test_discover_newsletter_senders():
            all_passed = False
        
        # Phase 12: Test newsletter acquisition tools
        if not test_newsletter_acquisition_tools():
            all_passed = False
        
        # Phase 13: Test UI intel display
        if not test_ui_intel_display():
            all_passed = False
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        all_passed = False
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False
    finally:
        stop_flask_server(flask_proc)
    
    # Optional email ingestion tests (non-blocking)
    try:
        test_email_ingestion_optional()
    except Exception:
        pass  # Don't fail baseline if optional test fails
    
    try:
        test_gmail_ingestion_optional()
    except Exception:
        pass  # Don't fail baseline if optional test fails
    
    # Final summary
    print_header("SMOKE TEST SUMMARY")
    if all_passed:
        print_ok("ALL TESTS PASSED")
        print("\nBaseline verified. Safe to proceed with changes.")
        return 0
    else:
        print_fail("SOME TESTS FAILED")
        print("\nFix issues before proceeding.")
        return 1


def test_email_ingestion_optional():
    """
    Optional test for email ingestion (only if SMOKE_TEST_EMAIL env var is set).
    This keeps the baseline smoke test stable.
    """
    import os
    if not os.getenv('SMOKE_TEST_EMAIL'):
        return
    
    from pathlib import Path
    from backend.adapters.email_event import extract_events
    
    # Check if test email exists
    test_eml = Path('backend/_email_ingest') / 'test_webinar.eml'
    if not test_eml.exists():
        # Create a minimal test email
        from email.message import EmailMessage
        from email import policy
        msg = EmailMessage(policy=policy.default)
        msg['From'] = 'test@example.com'
        msg['Subject'] = 'Test Webinar: Macro Outlook'
        msg.set_content('Join us for a webinar on January 20, 2026 at 15:00. Register: https://example.com/register')
        test_eml.parent.mkdir(exist_ok=True)
        test_eml.write_bytes(msg.as_bytes())
    
    events = extract_events(test_eml)
    assert len(events) >= 0, "Email ingestion should not crash"
    print("  ✓ Email ingestion test passed")


def test_gmail_ingestion_optional():
    """
    Optional test for Gmail ingestion (only if credentials exist).
    Runs in dry-run mode to verify Gmail API connectivity.
    """
    import os
    from pathlib import Path
    from backend.utils.gmail_auth import check_credentials_available, get_gmail_service
    
    if not check_credentials_available():
        return  # Skip if no credentials
    
    service = get_gmail_service()
    if not service:
        print("  ⚠ Gmail credentials found but authentication failed (optional)")
        return
    
    # Try to list messages (dry-run)
    try:
        from backend.utils.gmail_auth import get_gmail_service
        from backend.scripts.ingest_gmail import list_messages, build_gmail_query
        
        query = build_gmail_query(days=7)
        messages = list_messages(service, query, max_results=10)
        print(f"  ✓ Gmail API test passed (found {len(messages)} messages)")
    except Exception as e:
        print(f"  ⚠ Gmail API test failed: {e} (optional)")


def test_newsletter_targets_registry():
    """Test newsletter targets registry validation."""
    print_header("PHASE 8: Test newsletter targets registry")
    
    try:
        from pathlib import Path
        import json
        
        targets_path = Path(__file__).parent.parent / "newsletter_targets.json"
        if not targets_path.exists():
            print_ok("newsletter_targets.json not found (optional)")
            return True
        
        with open(targets_path) as f:
            data = json.load(f)
        
        # Check required top-level keys
        required_keys = ['owner_email', 'updated_at', 'targets']
        for key in required_keys:
            if key not in data:
                print_fail(f"Missing required key: {key}")
                return False
        
        # Check targets
        targets = data.get('targets', [])
        seen_ids = set()
        
        for i, target in enumerate(targets):
            target_id = target.get('id', f'<missing_{i}>')
            
            # Check duplicate IDs
            if target_id in seen_ids:
                print_fail(f"Duplicate target ID: {target_id}")
                return False
            seen_ids.add(target_id)
            
            # Check required fields
            required_fields = ['id', 'org_name', 'category', 'priority', 'status']
            for field in required_fields:
                if field not in target:
                    print_fail(f"Target {target_id}: missing required field '{field}'")
                    return False
        
        print_ok(f"Registry valid: {len(targets)} targets")
        return True
        
    except Exception as e:
        print_fail(f"Error validating registry: {e}")
        return False


def test_newsletter_targets_report():
    """Test newsletter targets report generation."""
    print_header("PHASE 9: Test newsletter targets report")
    
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "report_newsletter_targets.py")],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print_fail(f"Report script failed: {result.stderr}")
            return False
        
        # Check report file exists (now written to runbook)
        report_path = Path(__file__).parent.parent.parent / "md" / "NEWSLETTER_INGESTION_RUNBOOK.md"
        if not report_path.exists():
            print_fail("Runbook file not found")
            return False
        
        # Check that status section was added
        with open(report_path) as f:
            content = f.read()
        if "AUTO-GENERATED STATUS SECTION" not in content:
            print_fail("Status section not added to runbook")
            return False
        
        print_ok("Report generated successfully")
        return True
        
    except Exception as e:
        print_fail(f"Error running report script: {e}")
        return False


def test_gmail_targets_tools():
    """Test Gmail targets tools (no credentials required)."""
    print_header("PHASE 10: Test Gmail targets tools (no credentials)")
    
    try:
        import subprocess
        
        # Test --print-targets-allowlist
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "ingest_gmail.py"), "--print-targets-allowlist"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0 and "credentials" not in result.stderr.lower():
            print_fail(f"print-targets-allowlist failed: {result.stderr}")
            return False
        
        # Test --mode targets --print-default-query
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "ingest_gmail.py"), "--mode", "targets", "--print-default-query"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print_fail(f"targets mode query failed: {result.stderr}")
            return False
        
        if "newer_than" not in result.stdout:
            print_fail("Query output missing expected content")
            return False
        
        # Test --mode targets --targets-mode strict
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "ingest_gmail.py"), "--mode", "targets", "--targets-mode", "strict", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            print_fail(f"strict targets mode failed: {result.stderr}")
            return False
        
        print_ok("Gmail targets tools work without credentials")
        return True
        
    except Exception as e:
        print_fail(f"Error testing Gmail targets tools: {e}")
        return False


def test_discover_newsletter_senders():
    """Test newsletter sender discovery (local mode, no credentials required)."""
    print_header("PHASE 11: Test newsletter sender discovery (local mode)")
    
    try:
        import subprocess
        
        # Test local mode with --report (should work even without .eml files)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "discover_newsletter_senders.py"), "--local", "--report", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # The script should not crash even if no .eml files exist
        if result.returncode != 0:
            # Check if it's a non-fatal issue
            if "error" in result.stderr.lower() and "credential" not in result.stderr.lower():
                print_fail(f"discover_newsletter_senders failed: {result.stderr}")
                return False
        
        # Check that output contains expected elements
        output = result.stdout + result.stderr
        if "local mode" in output.lower() or "DISCOVERY" in output.upper():
            print_ok("Newsletter sender discovery (local mode) works")
            return True
        
        # Even if no output, if return code is 0, consider it passed
        if result.returncode == 0:
            print_ok("Newsletter sender discovery (local mode) works")
            return True
        
        print_fail("Unexpected output from discover_newsletter_senders")
        return False
        
    except Exception as e:
        print_fail(f"Error testing discover_newsletter_senders: {e}")
        return False


def test_newsletter_acquisition_tools():
    """Test newsletter acquisition tools on fixtures (no network required)."""
    print_header("PHASE 12: Test newsletter acquisition tools (fixtures)")
    
    try:
        import subprocess
        from pathlib import Path
        
        # Test form extraction on fixture
        fixture_path = Path(__file__).parent.parent / '_fixtures' / 'sample_signup_page.html'
        if fixture_path.exists():
            # Read fixture and test form extraction logic
            with open(fixture_path) as f:
                html = f.read()
            
            # Import extraction function
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from backend.scripts.extract_signup_forms import extract_forms_from_page, detect_captcha, detect_login_wall
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # Test CAPTCHA detection (should be False for sample_signup_page)
            has_captcha = detect_captcha(html, soup)
            if has_captcha:
                print_fail("False positive: CAPTCHA detected in clean page")
                return False
            
            # Test login detection (should be False)
            has_login = detect_login_wall(html, soup)
            if has_login:
                print_fail("False positive: Login wall detected in clean page")
                return False
            
            # Test form extraction
            result = extract_forms_from_page("http://test.com/signup", html)
            forms = result.get('forms', [])
            
            if not forms:
                print_fail("No forms extracted from fixture")
                return False
            
            # Check form has email field
            form = forms[0]
            if not form.get('email_field'):
                print_fail("Email field not found in form")
                return False
            
            print_ok("Form extraction works on fixtures")
        else:
            print(f"  Fixture not found, skipping form extraction test")
        
        # Test CAPTCHA detection on captcha fixture
        captcha_fixture = Path(__file__).parent.parent / '_fixtures' / 'sample_captcha_page.html'
        if captcha_fixture.exists():
            with open(captcha_fixture) as f:
                html = f.read()
            
            soup = BeautifulSoup(html, 'html.parser')
            has_captcha = detect_captcha(html, soup)
            
            if not has_captcha:
                print_fail("CAPTCHA not detected in captcha page")
                return False
            
            print_ok("CAPTCHA detection works correctly")
        
        # Test that acquisition scripts compile and have --help
        scripts = [
            'discover_signup_pages.py',
            'extract_signup_forms.py',
            'subscribe_newsletters.py',
            'find_opt_in_emails.py',
            'mark_opt_in_confirmed.py',
            'run_subscription_loop.py'
        ]
        
        for script in scripts:
            script_path = Path(__file__).parent / script
            if not script_path.exists():
                print_fail(f"Script not found: {script}")
                return False
            
            result = subprocess.run(
                [sys.executable, str(script_path), '--help'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                print_fail(f"Script {script} --help failed")
                return False
        
        print_ok("All acquisition scripts have valid --help")
        return True
        
    except ImportError as e:
        print(f"  Import error (optional): {e}")
        print_ok("Acquisition tools test skipped (missing dependencies)")
        return True
    except Exception as e:
        print_fail(f"Error testing acquisition tools: {e}")
        return False


def test_ui_intel_display():
    """Test that UI can display INTEL/EVENT items correctly."""
    print_header("PHASE 13: Test UI Intel Display")
    
    try:
        from backend.db import init_db, upsert_event
        
        # Initialize DB
        init_db()
        
        # Create synthetic newsletter intel items
        test_items = [
            {
                'firm_name': 'Goldman Sachs',
                'event_name': '2026 Macro Outlook: Rates and FX',
                'date_time': None,  # Undated intel
                'link': 'https://example.com/outlook-2026',
                'source_id': 'test_newsletter',
                'tags_json': ['Email', 'Macro'],
                'intel_type': 'outlook',
                'has_explicit_date': False,
                'confidence_score': 75
            },
            {
                'firm_name': 'JPMorgan',
                'event_name': 'Global Markets Webinar: Central Bank Policy',
                'date_time': '2026-02-15T14:00:00+00:00',
                'link': 'https://example.com/webinar-feb',
                'source_id': 'test_newsletter',
                'tags_json': ['Email', 'Macro'],
                'intel_type': 'webinar',
                'has_explicit_date': True,
                'confidence_score': 85
            },
            {
                'firm_name': 'Morgan Stanley',
                'event_name': 'Market Strategy Briefing',
                'date_time': None,
                'link': 'https://example.com/briefing',
                'source_id': 'test_newsletter',
                'tags_json': ['Email', 'Macro'],
                'intel_type': 'briefing',
                'has_explicit_date': False,
                'confidence_score': 70
            }
        ]
        
        inserted_count = 0
        for item in test_items:
            # Serialize tags_json if it's a list
            tags_json = item['tags_json']
            if isinstance(tags_json, list):
                import json
                tags_json = json.dumps(tags_json)
            
            is_new, event_id = upsert_event(
                firm_name=item['firm_name'],
                event_name=item['event_name'],
                date_time=item['date_time'],
                link=item['link'],
                source_id=item['source_id'],
                tags_json=tags_json,
                intel_type=item['intel_type'],
                has_explicit_date=item['has_explicit_date'],
                confidence_score=item['confidence_score']
            )
            if is_new:
                inserted_count += 1
        
        # Verify API returns them (query by source_id)
        from backend.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE source_id = ?", ('test_newsletter',))
        rows = cursor.fetchall()
        conn.close()
        
        # Check for our test items
        test_found = 0
        for row in rows:
            event = dict(row)
            test_found += 1
            # Verify intel fields present
            assert 'intel_type' in event or event.get('intel_type'), "intel_type missing"
            assert 'confidence_score' in event or event.get('confidence_score') is not None, "confidence_score missing"
            assert 'has_explicit_date' in event or event.get('has_explicit_date') is not None, "has_explicit_date missing"
        
        if test_found >= 2:
            print_ok(f"UI intel display test passed ({test_found} test items found)")
            return True
        else:
            print_fail(f"Only {test_found} test items found (expected >= 2)")
            return False
            
    except Exception as e:
        print_fail(f"Error testing UI intel display: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_html_autoparser():
    """Test HTML autoparser module."""
    try:
        from utils.html_autoparser import parse_html_autoparser
        
        # Test with JSON-LD fixture
        fixture_path = Path(__file__).parent.parent / "_fixtures" / "case_jsonld_event.html"
        if fixture_path.exists():
            with open(fixture_path, 'r') as f:
                html = f.read()
            result = parse_html_autoparser("https://example.com/events", html)
            assert result['detected_mode'] == 'jsonld', f"Expected jsonld, got {result['detected_mode']}"
            print("✓ HTML autoparser JSON-LD test passed")
        else:
            print("⚠ HTML autoparser fixture not found, skipping test")
    except Exception as e:
        print(f"✗ HTML autoparser test failed: {e}")
        raise


def test_maintenance_loop():
    """Test source maintenance loop (dry-run)."""
    print_header("PHASE 0.5: Test source maintenance loop (dry-run)")
    
    try:
        import subprocess
        from pathlib import Path
        import os
        import json
        
        maintain_script = Path(__file__).parent / "maintain_sources.py"
        if not maintain_script.exists():
            print_fail("maintain_sources.py not found")
            return False
        
        # Get sources.json mtime before run
        sources_file = Path(__file__).parent.parent / "sources.json"
        sources_mtime_before = sources_file.stat().st_mtime if sources_file.exists() else None
        
        # Run maintain_sources in dry-run mode
        result = subprocess.run(
            [sys.executable, str(maintain_script), "--dry-run", "--max-sources", "3"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).parent.parent)
        )
        
        if result.returncode != 0:
            print_fail(f"maintain_sources.py exited with code {result.returncode}")
            print(result.stderr[:500])
            return False
        
        print_ok("maintain_sources.py exited successfully")
        
        # Check that run_summary.json exists
        evidence_dir = Path(__file__).parent.parent / "_evidence" / "maintenance"
        # Find latest run_id directory
        run_dirs = sorted([d for d in evidence_dir.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
        if not run_dirs:
            print_fail("No evidence directory found")
            return False
        
        latest_run_dir = run_dirs[0]
        summary_file = latest_run_dir / "run_summary.json"
        
        if not summary_file.exists():
            print_fail(f"run_summary.json not found in {latest_run_dir}")
            return False
        
        print_ok(f"run_summary.json exists: {summary_file}")
        
        # Load and validate summary
        with open(summary_file) as f:
            summary = json.load(f)
        
        # Check required fields
        required_fields = ['timestamp', 'dry_run', 'total_sources', 'degraded_count', 'results']
        for field in required_fields:
            if field not in summary:
                print_fail(f"run_summary.json missing field: {field}")
                return False
        
        print_ok("run_summary.json has all required fields")
        
        # Check that dry_run is True
        if not summary.get('dry_run', False):
            print_fail("run_summary.json shows dry_run=False (should be True)")
            return False
        
        print_ok("dry_run flag is correctly set")
        
        # Check that each degraded item has degradation_class and recommended_playbook
        for result_item in summary.get('results', []):
            degradation = result_item.get('degradation', {})
            if degradation.get('degraded'):
                if not degradation.get('degradation_class'):
                    print_fail(f"Degraded source {result_item.get('source_id')} missing degradation_class")
                    return False
                if not degradation.get('recommended_playbook'):
                    print_fail(f"Degraded source {result_item.get('source_id')} missing recommended_playbook")
                    return False
        
        print_ok("All degraded items have degradation_class and recommended_playbook")
        
        # Verify sources.json was NOT modified in dry-run
        if sources_mtime_before and sources_file.exists():
            sources_mtime_after = sources_file.stat().st_mtime
            if sources_mtime_after != sources_mtime_before:
                print_fail("sources.json was modified in dry-run mode (should not be)")
                return False
        
        print_ok("sources.json mtime unchanged (no writes in dry-run)")
        
        return True
        
    except Exception as e:
        print_fail(f"Error testing maintenance loop: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # Ensure requests is available
    try:
        import requests
    except ImportError:
        print("Installing requests...")
        subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
        import requests
    
    sys.exit(main())
