#!/usr/bin/env python3
"""
Unit tests for HTML autoparser.
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.html_autoparser import parse_html_autoparser


def test_jsonld_events():
    """Test JSON-LD event extraction."""
    fixture_path = backend_dir / "_fixtures" / "case_jsonld_event.html"
    with open(fixture_path, 'r') as f:
        html = f.read()
    
    result = parse_html_autoparser("https://example.com/events", html)
    
    assert result['detected_mode'] == 'jsonld', f"Expected jsonld, got {result['detected_mode']}"
    assert result['tier'] == 'A', f"Expected tier A, got {result['tier']}"
    assert len(result['sample_events']) >= 3, f"Expected >= 3 events, got {len(result['sample_events'])}"
    assert result['selectors_json'], "Expected selectors_json to be populated"
    
    print("✓ JSON-LD test passed")


def test_time_datetime():
    """Test time[datetime] extraction."""
    fixture_path = backend_dir / "_fixtures" / "case_time_datetime.html"
    with open(fixture_path, 'r') as f:
        html = f.read()
    
    result = parse_html_autoparser("https://example.com/events", html)
    
    assert result['detected_mode'] in ['dom_cluster', 'jsonld', 'microdata'], \
        f"Expected dom_cluster/jsonld/microdata, got {result['detected_mode']}"
    assert len(result['sample_events']) >= 3, f"Expected >= 3 events, got {len(result['sample_events'])}"
    
    # Check that dates are extracted
    events_with_dates = sum(1 for e in result['sample_events'] if e.get('date_iso') or e.get('date_text'))
    assert events_with_dates > 0, "Expected at least some events to have dates"
    
    print("✓ Time datetime test passed")


def test_list_no_dates_detail_has_date():
    """Test detail-only mode (events found but no dates on list page)."""
    fixture_path = backend_dir / "_fixtures" / "case_list_no_dates_detail_has_date.html"
    with open(fixture_path, 'r') as f:
        html = f.read()
    
    result = parse_html_autoparser("https://example.com/events", html)
    
    # Should detect events but no dates
    assert result['detected_mode'] in ['dom_cluster', 'detail_only'], \
        f"Expected dom_cluster or detail_only, got {result['detected_mode']}"
    
    if result['detected_mode'] == 'detail_only':
        assert result['detail_fetch_patch'] is not None, "Expected detail_fetch_patch for detail_only mode"
        assert result['detail_fetch_patch']['enabled'] is True
        assert 'date_selector' in result['detail_fetch_patch']
    
    assert len(result['sample_events']) >= 3, f"Expected >= 3 events, got {len(result['sample_events'])}"
    
    print("✓ Detail-only test passed")


def test_nav_heavy_false_positive():
    """Test that nav links don't create false positives."""
    fixture_path = backend_dir / "_fixtures" / "case_nav_heavy_false_positive.html"
    with open(fixture_path, 'r') as f:
        html = f.read()
    
    result = parse_html_autoparser("https://example.com", html)
    
    # Should not detect events (nav links are not event items)
    # Either no_events or very few events
    assert result['detected_mode'] in ['no_events', 'dom_cluster'], \
        f"Expected no_events or dom_cluster, got {result['detected_mode']}"
    
    if result['detected_mode'] == 'dom_cluster':
        # If it detected something, should be very few
        assert len(result['sample_events']) < 3, \
            f"Expected < 3 events (nav false positives), got {len(result['sample_events'])}"
    
    print("✓ Nav false positive test passed")


def main():
    """Run all tests."""
    print("=== Testing HTML Autoparser ===\n")
    
    try:
        test_jsonld_events()
        test_time_datetime()
        test_list_no_dates_detail_has_date()
        test_nav_heavy_false_positive()
        
        print("\n✓ All tests passed!")
        return 0
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
