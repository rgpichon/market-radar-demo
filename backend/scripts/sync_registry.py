#!/usr/bin/env python3
"""
Sync Source Registry

Syncs source_registry.json from sources.json, preserving existing failure evidence.
"""
import sys
import json
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.utils.source_registry import sync_registry, load_registry


def main():
    """Sync registry from sources.json."""
    print("Syncing source registry from sources.json...")
    
    registry = sync_registry()
    
    print(f"Synced {len(registry)} sources")
    print()
    print("Registry updated: backend/source_registry.json")
    
    # Print summary
    active_count = sum(1 for s in registry.values() if s.get('active'))
    inactive_count = len(registry) - active_count
    
    print(f"Active: {active_count}")
    print(f"Inactive: {inactive_count}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
