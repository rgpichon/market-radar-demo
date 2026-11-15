#!/usr/bin/env python3
"""
Bank Third-Party Calendar Discovery: Systematic discovery of bank events via third-party calendars.

For each bank:
- Resolve ticker symbol
- Query third-party calendars (Nasdaq, Yahoo Finance, MarketWatch)
- Record events found, coverage ratio, failure class, evidence

Results persisted to backend/bank_third_party_results.json
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from adapters.third_party_calendar import BANK_TICKERS, extract_events


BANK_THIRD_PARTY_RESULTS_FILE = backend_dir / "bank_third_party_results.json"
BULGE_BRACKETS_FILE = backend_dir / "bulge_brackets.json"


def load_banks() -> List[Dict]:
    """Load banks from bulge_brackets.json."""
    if not BULGE_BRACKETS_FILE.exists():
        return []
    
    with open(BULGE_BRACKETS_FILE, 'r') as f:
        return json.load(f)


def resolve_ticker(firm_name: str) -> Optional[str]:
    """Resolve ticker symbol for a bank."""
    return BANK_TICKERS.get(firm_name)


def test_calendar_for_bank(firm_name: str, ticker: str, calendar_type: str) -> Dict:
    """
    Test a third-party calendar for a bank.
    
    Args:
        firm_name: Bank name
        ticker: Stock ticker symbol
        calendar_type: "nasdaq_earnings", "yahoo_earnings", etc.
    
    Returns:
        Result dict with events, stats, failure_class
    """
    result = {
        'firm_name': firm_name,
        'ticker': ticker,
        'calendar_type': calendar_type,
        'tested_at': datetime.now(timezone.utc).isoformat(),
        'events_found': 0,
        'events': [],
        'failure_class': None,
        'evidence': '',
        'stats': {}
    }
    
    if not ticker:
        result['failure_class'] = 'no_coverage'
        result['evidence'] = f'Ticker not found for {firm_name}'
        return result
    
    # Create source config
    source_config = {
        'id': f'{calendar_type}_{ticker}',
        'firm_name': firm_name,
        'default_tags_json': ['Banking', 'Earnings'],
        'enforce_events_only': True
    }
    
    # Create calendar config
    calendar_config = {
        'calendar_type': calendar_type,
        'ticker': ticker
    }
    
    try:
        # Extract events
        events, stats = extract_events(calendar_config, source_config, return_stats=True)
        
        result['events'] = events
        result['events_found'] = len(events)
        result['stats'] = stats
        
        # Extract diagnostics
        diagnostics = stats.get('diagnostics', {})
        status_code = diagnostics.get('status_code')
        
        # Check for blocking
        if status_code in [403, 401]:
            result['failure_class'] = 'licensing_blocked'
            result['evidence'] = f'Blocked: HTTP {status_code} - {diagnostics.get("error", "Access denied")}'
            return result
        
        # Check for parse errors
        parse_errors = diagnostics.get('parse_errors', [])
        if parse_errors and len(events) == 0:
            result['failure_class'] = 'format_incompatible'
            result['evidence'] = f'Parse errors: {"; ".join(parse_errors[:2])}'
            return result
        
        # Classify result
        if len(events) == 0:
            result['failure_class'] = 'no_coverage'
            error_msg = diagnostics.get('error', 'No events found')
            result['evidence'] = f'No events found in {calendar_type} for {ticker}: {error_msg}'
        else:
            # Check date coverage
            dated_count = sum(1 for e in events if e.get('date_time'))
            dated_ratio = dated_count / len(events) if events else 0
            
            # Check future events
            now = datetime.now(timezone.utc)
            future_count = 0
            earliest_date = None
            for event in events:
                date_time = event.get('date_time')
                if date_time:
                    try:
                        if isinstance(date_time, str):
                            if date_time.endswith('Z'):
                                date_time = date_time[:-1] + '+00:00'
                            dt = datetime.fromisoformat(date_time)
                        else:
                            dt = date_time
                        
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        else:
                            dt = dt.astimezone(timezone.utc)
                        
                        if dt >= now:
                            future_count += 1
                            if earliest_date is None or dt < earliest_date:
                                earliest_date = dt
                    except:
                        pass
            
            future_ratio = future_count / len(events) if events else 0
            
            # More realistic thresholds: min 1 event, dated ratio should be high, future ratio flexible
            if dated_ratio < 0.90:
                result['failure_class'] = 'partial_coverage'
                result['evidence'] = f'Dated ratio {dated_ratio:.1%} < 90%'
            elif future_count == 0:
                result['failure_class'] = 'stale_data'
                result['evidence'] = f'No future events found (all {len(events)} events are past)'
            else:
                # Success - at least 1 future event with good date coverage
                result['failure_class'] = None
                result['future_events_found'] = future_count
                result['dated_ratio'] = dated_ratio
                result['earliest_date'] = earliest_date.isoformat() if earliest_date else None
                result['evidence'] = f'Success: {len(events)} events ({future_count} future), {dated_ratio:.1%} dated, earliest: {earliest_date.strftime("%Y-%m-%d") if earliest_date else "N/A"}'
                
                # Add evidence file paths
                from pathlib import Path
                evidence_dir = Path(__file__).parent.parent / "_evidence"
                result['evidence_files'] = {
                    'response_head': str(evidence_dir / f"{ticker}_{calendar_type}_response_head.txt"),
                    'parsed': str(evidence_dir / f"{ticker}_{calendar_type}_parsed.json")
                }
        
    except Exception as e:
        result['failure_class'] = 'format_incompatible'
        result['evidence'] = f'Error parsing {calendar_type}: {str(e)}'
    
    return result


def discover_bank_third_party(bank: Dict) -> Dict:
    """Discover third-party calendar events for a bank."""
    firm_name = bank.get('firm_name', '')
    
    print(f"\n=== Third-Party Calendar Discovery: {firm_name} ===")
    
    # Resolve ticker
    ticker = resolve_ticker(firm_name)
    if not ticker:
        print(f"  ✗ Ticker not found for {firm_name}")
        return {
            'firm_name': firm_name,
            'ticker': None,
            'discovered_at': datetime.now(timezone.utc).isoformat(),
            'calendars_tested': [],
            'failure_class': 'no_coverage',
            'evidence': f'Ticker not found for {firm_name}',
            'recommended_next_action': 'ticker_lookup'
        }
    
    print(f"  Ticker: {ticker}")
    
    # Test calendars - use real provider
    calendars_to_test = ['nasdaq_earnings_api']  # Real provider (NASDAQ API)
    results = {
        'firm_name': firm_name,
        'ticker': ticker,
        'discovered_at': datetime.now(timezone.utc).isoformat(),
        'calendars_tested': [],
        'best_result': None,
        'failure_class': None,
        'recommended_next_action': None,
        'evidence': ''
    }
    
    best_events = 0
    best_calendar = None
    
    for calendar_type in calendars_to_test:
        print(f"  Testing: {calendar_type}")
        calendar_result = test_calendar_for_bank(firm_name, ticker, calendar_type)
        results['calendars_tested'].append(calendar_result)
        
        if calendar_result['events_found'] > best_events:
            best_events = calendar_result['events_found']
            best_calendar = calendar_result
            results['best_result'] = calendar_result
        
        if calendar_result['failure_class'] is None:
            print(f"    ✓ Found {calendar_result['events_found']} events")
        else:
            print(f"    ✗ {calendar_result['failure_class']}: {calendar_result['evidence']}")
    
    # Determine overall failure class
    if best_calendar and best_calendar['failure_class'] is None:
        results['failure_class'] = None
        results['recommended_next_action'] = None
        results['evidence'] = f"Success: {best_events} events from {best_calendar['calendar_type']}"
    elif best_calendar:
        results['failure_class'] = best_calendar['failure_class']
        results['recommended_next_action'] = {
            'no_coverage': 'try_alternative_calendar',
            'partial_coverage': 'combine_sources',
            'stale_data': 'find_fresher_source',
            'format_incompatible': 'find_alternative_format'
        }.get(best_calendar['failure_class'], 'abandon')
        results['evidence'] = best_calendar['evidence']
    else:
        results['failure_class'] = 'no_coverage'
        results['recommended_next_action'] = 'try_alternative_calendar'
        results['evidence'] = 'No events found in any tested calendar'
    
    return results


def update_registry_from_results(results: Dict):
    """Update source_registry.json with third-party calendar results."""
    from utils.source_registry import load_registry, save_registry
    
    registry = load_registry()
    
    for firm_name, bank_result in results.items():
        # Find source_id for this bank
        source_id = None
        for sid, entry in registry.items():
            if entry.get('firm_name') == firm_name and entry.get('sector') == 'bulge_bracket':
                source_id = sid
                break
        
        if not source_id:
            # Create new registry entry
            source_id = f"{firm_name.lower().replace(' ', '_')}_third_party"
        
        # Update registry entry
        if source_id in registry:
            entry = registry[source_id]
        else:
            entry = {
                'source_id': source_id,
                'firm_name': firm_name,
                'sector': 'bulge_bracket',
                'lane': 'third_party_calendar',
                'active': False,
                'last_checked': datetime.now(timezone.utc).isoformat()
            }
        
        # Update with third-party results
        entry['lane'] = 'third_party_calendar'
        entry['failure_class'] = bank_result.get('failure_class')
        entry['failure_evidence'] = bank_result.get('evidence', '')
        entry['recommended_next_action'] = bank_result.get('recommended_next_action')
        entry['last_checked'] = bank_result.get('discovered_at', datetime.now(timezone.utc).isoformat())
        
        if bank_result.get('best_result'):
            best = bank_result['best_result']
            entry['calendar_source'] = best.get('calendar_type')
            entry['events_found'] = best.get('events_found', 0)
            entry['ticker'] = bank_result.get('ticker')
        
        # Set acquisition status
        if bank_result.get('failure_class') is None:
            entry['acquisition_status'] = 'ready_third_party'
            entry['validation_status'] = 'validated'
        else:
            entry['acquisition_status'] = f"failed_{bank_result.get('failure_class')}"
            entry['validation_status'] = 'failed'
            entry['active'] = False
        
        registry[source_id] = entry
    
    save_registry(registry)


def main():
    """Run third-party calendar discovery for all banks."""
    banks = load_banks()
    
    if not banks:
        print("No banks found in bulge_brackets.json")
        return
    
    # Load existing results
    if BANK_THIRD_PARTY_RESULTS_FILE.exists():
        with open(BANK_THIRD_PARTY_RESULTS_FILE, 'r') as f:
            results = json.load(f)
    else:
        results = {}
    
    # Discover for each bank
    for bank in banks:
        firm_name = bank.get('firm_name', '')
        if not firm_name:
            continue
        
        print(f"\n{'='*60}")
        print(f"Bank: {firm_name}")
        print(f"{'='*60}")
        
        # Discover third-party calendars
        bank_result = discover_bank_third_party(bank)
        
        # Store result
        results[firm_name] = bank_result
        
        # Print summary
        print(f"\nSummary:")
        print(f"  Failure class: {bank_result['failure_class'] or 'None (success)'}")
        print(f"  Recommended action: {bank_result['recommended_next_action'] or 'None'}")
        print(f"  Evidence: {bank_result['evidence']}")
        if bank_result.get('best_result'):
            print(f"  Best calendar: {bank_result['best_result']['calendar_type']} ({bank_result['best_result']['events_found']} events)")
    
    # Save results
    with open(BANK_THIRD_PARTY_RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Update registry
    update_registry_from_results(results)
    print(f"\nRegistry updated with third-party calendar results")
    
    print(f"\n{'='*60}")
    print(f"Discovery complete. Results saved to {BANK_THIRD_PARTY_RESULTS_FILE}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
