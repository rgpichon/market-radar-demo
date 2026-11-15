"""
Auto-detect JavaScript-rendered sources and suggest adapter updates.

This script:
1. Reads source_stats.json to find sources with JS detection
2. Identifies sources that should use Playwright adapter
3. Suggests configuration updates
4. Optionally auto-updates sources.json (with confirmation)
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from db import get_sources


def load_source_stats() -> Dict:
    """Load source_stats.json."""
    stats_path = backend_dir / "source_stats.json"
    if not stats_path.exists():
        return {}
    
    try:
        with open(stats_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def identify_js_sources(source_stats: Dict) -> List[Dict]:
    """
    Identify sources that should use Playwright adapter.
    
    Returns:
        List of dicts with source_id, reason, and suggested config
    """
    js_sources = []
    
    for source_id, stats in source_stats.items():
        js_detected = stats.get('js_detected', False)
        suggested_adapter = stats.get('suggested_adapter_type')
        playwright_fallback_attempted = stats.get('playwright_fallback_attempted', False)
        playwright_fallback_success = stats.get('playwright_fallback_success', False)
        
        # Criteria for suggesting Playwright:
        # 1. JS detected during scrape
        # 2. Playwright fallback was attempted and succeeded
        # 3. Suggested adapter type is 'playwright'
        
        should_suggest = False
        reason = None
        
        if js_detected and suggested_adapter == 'playwright':
            should_suggest = True
            reason = 'JS detected during scrape'
        elif playwright_fallback_attempted and playwright_fallback_success:
            should_suggest = True
            reason = 'Playwright fallback succeeded'
        elif js_detected:
            should_suggest = True
            reason = 'JS detected (Playwright not available or failed)'
        
        if should_suggest:
            js_sources.append({
                'source_id': source_id,
                'reason': reason,
                'js_detected': js_detected,
                'suggested_adapter': suggested_adapter,
                'playwright_fallback_attempted': playwright_fallback_attempted,
                'playwright_fallback_success': playwright_fallback_success,
                'last_scrape_at': stats.get('last_scrape_at')
            })
    
    return js_sources


def suggest_updates(js_sources: List[Dict], sources: List[Dict]) -> List[Dict]:
    """
    Generate suggested configuration updates.
    
    Returns:
        List of suggested updates with source_id and new config
    """
    suggestions = []
    sources_by_id = {s['id']: s for s in sources}
    
    for js_source in js_sources:
        source_id = js_source['source_id']
        source = sources_by_id.get(source_id)
        
        if not source:
            continue
        
        current_adapter = source.get('adapter_type', 'html_list')
        
        # Only suggest if not already using Playwright
        if current_adapter != 'playwright':
            suggestion = {
                'source_id': source_id,
                'firm_name': source.get('firm_name', ''),
                'current_adapter': current_adapter,
                'suggested_adapter': 'playwright',
                'reason': js_source['reason'],
                'preserve_selectors': True,  # Keep existing selectors
                'new_config': {
                    'adapter_type': 'playwright',
                    'js_required': True
                }
            }
            suggestions.append(suggestion)
    
    return suggestions


def print_report(js_sources: List[Dict], suggestions: List[Dict]):
    """Print a report of detected JS sources and suggestions."""
    print("=" * 70)
    print("JavaScript-Rendered Sources Detection Report")
    print("=" * 70)
    print()
    
    if not js_sources:
        print("✅ No JavaScript-rendered sources detected.")
        print("   All sources appear to work with static HTML extraction.")
        return
    
    print(f"Found {len(js_sources)} source(s) that may require Playwright:")
    print()
    
    for js_source in js_sources:
        print(f"  • {js_source['source_id']}")
        print(f"    Reason: {js_source['reason']}")
        if js_source['playwright_fallback_attempted']:
            status = "✅ Succeeded" if js_source['playwright_fallback_success'] else "❌ Failed"
            print(f"    Playwright fallback: {status}")
        print()
    
    if suggestions:
        print(f"\nSuggested Configuration Updates ({len(suggestions)} source(s)):")
        print()
        for suggestion in suggestions:
            print(f"  • {suggestion['source_id']} ({suggestion['firm_name']})")
            print(f"    Current: {suggestion['current_adapter']}")
            print(f"    Suggested: {suggestion['suggested_adapter']}")
            print(f"    Reason: {suggestion['reason']}")
            print()
    
    print("=" * 70)


def auto_update_sources(suggestions: List[Dict], confirm: bool = True) -> bool:
    """
    Auto-update sources.json with suggested changes.
    
    Args:
        suggestions: List of suggested updates
        confirm: If True, require confirmation before updating
        
    Returns:
        True if updated, False otherwise
    """
    if not suggestions:
        return False
    
    if confirm:
        print(f"\n⚠️  About to update {len(suggestions)} source(s) in sources.json")
        response = input("Continue? (yes/no): ").strip().lower()
        if response != 'yes':
            print("Update cancelled.")
            return False
    
    sources_path = backend_dir / "sources.json"
    if not sources_path.exists():
        print(f"❌ sources.json not found at {sources_path}")
        return False
    
    try:
        with open(sources_path, 'r') as f:
            sources = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ Error reading sources.json: {e}")
        return False
    
    # Update sources
    sources_by_id = {s['id']: s for s in sources}
    updated_count = 0
    
    for suggestion in suggestions:
        source_id = suggestion['source_id']
        if source_id in sources_by_id:
            source = sources_by_id[source_id]
            source['adapter_type'] = 'playwright'
            source['js_required'] = True
            updated_count += 1
    
    # Save updated sources
    try:
        with open(sources_path, 'w') as f:
            json.dump(sources, f, indent=2)
        print(f"✅ Updated {updated_count} source(s) in sources.json")
        return True
    except IOError as e:
        print(f"❌ Error writing sources.json: {e}")
        return False


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Auto-detect JS-rendered sources')
    parser.add_argument('--auto-update', action='store_true', 
                       help='Auto-update sources.json (requires --confirm)')
    parser.add_argument('--confirm', action='store_true',
                       help='Skip confirmation prompt (use with --auto-update)')
    args = parser.parse_args()
    
    # Load data
    source_stats = load_source_stats()
    if not source_stats:
        print("❌ source_stats.json not found or empty.")
        print("   Run a scrape first to generate statistics.")
        return
    
    sources = get_sources()
    
    # Identify JS sources
    js_sources = identify_js_sources(source_stats)
    suggestions = suggest_updates(js_sources, sources)
    
    # Print report
    print_report(js_sources, suggestions)
    
    # Auto-update if requested
    if args.auto_update:
        auto_update_sources(suggestions, confirm=not args.confirm)


if __name__ == '__main__':
    main()
