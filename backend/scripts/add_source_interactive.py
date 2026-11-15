#!/usr/bin/env python3
"""
Interactive script to add a new source to sources.json.
Reduces friction for adding sources safely.

Usage:
    python add_source_interactive.py
"""
import sys
import json
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

SOURCES_FILE = backend_dir / "sources.json"


def load_sources():
    """Load sources.json."""
    if not SOURCES_FILE.exists():
        return []
    
    try:
        with open(SOURCES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading sources.json: {e}")
        sys.exit(1)


def save_sources(sources):
    """Save sources.json with validation."""
    try:
        # Validate JSON by serializing
        json_str = json.dumps(sources, indent=2)
        json.loads(json_str)  # Validate
        
        # Write with backup
        backup_file = SOURCES_FILE.with_suffix('.json.bak')
        if SOURCES_FILE.exists():
            import shutil
            shutil.copy2(SOURCES_FILE, backup_file)
        
        with open(SOURCES_FILE, 'w') as f:
            f.write(json_str)
        
        print(f"\n✓ Source added successfully (backup saved to {backup_file.name})")
        return True
    except (json.JSONDecodeError, IOError) as e:
        print(f"\n✗ Error saving sources.json: {e}")
        if backup_file.exists():
            print(f"  Restore from backup: {backup_file.name}")
        return False


def prompt(question, default=None, required=True):
    """Prompt user for input."""
    if default:
        prompt_text = f"{question} [{default}]: "
    else:
        prompt_text = f"{question}: "
    
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        elif default:
            return default
        elif not required:
            return None
        else:
            print("  This field is required.")


def prompt_yes_no(question, default=True):
    """Prompt for yes/no."""
    default_str = "Y/n" if default else "y/N"
    while True:
        value = input(f"{question} [{default_str}]: ").strip().lower()
        if not value:
            return default
        if value in ['y', 'yes']:
            return True
        if value in ['n', 'no']:
            return False
        print("  Please enter 'y' or 'n'")


def prompt_json(question, default=None):
    """Prompt for JSON input."""
    if default:
        print(f"{question}")
        print(f"  Default: {json.dumps(default, indent=2)}")
        use_default = prompt_yes_no("  Use default?", True)
        if use_default:
            return default
    
    while True:
        value = input(f"{question} (JSON): ").strip()
        if not value:
            if default:
                return default
            return {}
        
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            print(f"  Invalid JSON: {e}")
            print("  Try again or leave empty for {}")


def main():
    print("\n=== Add New Source to sources.json ===\n")
    
    sources = load_sources()
    
    # Check for duplicate IDs
    existing_ids = {s.get('id') for s in sources if s.get('id')}
    
    # Collect source info
    source_id = prompt("Source ID (unique identifier)", required=True)
    if source_id in existing_ids:
        print(f"\n✗ Error: Source ID '{source_id}' already exists")
        sys.exit(1)
    
    firm_name = prompt("Firm name", required=True)
    url = prompt("URL", required=True)
    
    print("\nAdapter types: html_list, json_api, rss, ics")
    adapter_type = prompt("Adapter type", required=True)
    if adapter_type not in ['html_list', 'json_api', 'rss', 'ics']:
        print(f"\n✗ Error: Invalid adapter type '{adapter_type}'")
        sys.exit(1)
    
    # Default tags
    print("\nEnter default tags (comma-separated, or JSON array)")
    tags_input = prompt("Default tags", default="[]", required=False)
    try:
        if tags_input.startswith('['):
            default_tags = json.loads(tags_input)
        else:
            default_tags = [t.strip() for t in tags_input.split(',') if t.strip()]
    except json.JSONDecodeError:
        default_tags = [t.strip() for t in tags_input.split(',') if t.strip()]
    
    # Enforce events only
    enforce_events_only = prompt_yes_no("Enforce events-only policy?", default=True)
    
    # Adapter-specific config
    selectors_json = {}
    api_config = {}
    
    if adapter_type == 'html_list':
        print("\n=== HTML List Selectors ===")
        print("Enter CSS selectors (leave empty to skip)")
        item_selector = prompt("Item selector", required=False)
        title_selector = prompt("Title selector", required=False)
        link_selector = prompt("Link selector", required=False)
        date_selector = prompt("Date selector", required=False)
        
        if item_selector:
            selectors_json['item_selector'] = item_selector
        if title_selector:
            selectors_json['title_selector'] = title_selector
        if link_selector:
            selectors_json['link_selector'] = link_selector
        if date_selector:
            selectors_json['date_selector'] = date_selector
    
    elif adapter_type == 'json_api':
        print("\n=== JSON API Config ===")
        endpoint = prompt("API endpoint URL", required=True)
        items_path = prompt("Items path (JSONPath)", default="items", required=False)
        title_path = prompt("Title path", default="title", required=False)
        link_path = prompt("Link path", default="link", required=False)
        date_path = prompt("Date path", default="date", required=False)
        base_url = prompt("Base URL (for relative links)", required=False)
        
        api_config = {
            'endpoint': endpoint,
            'items_path': items_path or 'items',
            'title_path': title_path or 'title',
            'link_path': link_path or 'link',
            'date_path': date_path or 'date'
        }
        if base_url:
            api_config['base_url'] = base_url
    
    # Postprocess rules
    print("\n=== Postprocess Rules ===")
    add_postprocess = prompt_yes_no("Add postprocess rules?", default=False)
    postprocess_rules = {}
    
    if add_postprocess:
        min_title_length = prompt("Min title length", default="", required=False)
        if min_title_length:
            try:
                postprocess_rules['min_title_length'] = int(min_title_length)
            except ValueError:
                pass
        
        require_url_patterns = prompt("Require URL contains (comma-separated)", required=False)
        if require_url_patterns:
            patterns = [p.strip() for p in require_url_patterns.split(',') if p.strip()]
            if patterns:
                postprocess_rules['require_url_contains_one_of'] = patterns
    
    # Build source dict
    source = {
        'id': source_id,
        'firm_name': firm_name,
        'url': url,
        'adapter_type': adapter_type,
        'default_tags_json': default_tags,
        'enforce_events_only': enforce_events_only,
        'active': 1
    }
    
    if adapter_type == 'html_list' and selectors_json:
        source['selectors_json'] = selectors_json
    elif adapter_type == 'json_api' and api_config:
        source['api_config'] = api_config
    
    if postprocess_rules:
        source['postprocess_rules'] = postprocess_rules
    
    # Add firm_type if not specified (optional)
    print("\n=== Optional Fields ===")
    firm_type = prompt("Firm type (optional)", required=False)
    if firm_type:
        source['firm_type'] = firm_type
    
    # Show summary
    print("\n=== Source Summary ===")
    print(json.dumps(source, indent=2))
    
    confirm = prompt_yes_no("\nAdd this source?", default=True)
    if not confirm:
        print("Cancelled.")
        sys.exit(0)
    
    # Add to sources
    sources.append(source)
    
    # Save
    if save_sources(sources):
        print(f"\nNext steps:")
        print(f"  1. Test the source: python scripts/test_source.py --source {source_id}")
        print(f"  2. Run scrape: python scripts/run_scrape.py")
        print(f"  3. Check results in database or API")
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
