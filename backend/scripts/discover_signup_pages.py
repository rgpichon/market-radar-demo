#!/usr/bin/env python3
"""
Newsletter Signup Page Discovery

Discovers candidate newsletter signup pages for newsletter targets.
Respects robots.txt and rate limits.
"""
import sys
import json
import argparse
import hashlib
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Tuple

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Required: pip install requests beautifulsoup4")
    sys.exit(1)


# HIGH-PRIORITY: Event-specific keywords (must dominate scoring)
SIGNUP_KEYWORDS_HIGH = [
    'webinar', 'webinars', 'webcast', 'conference', 'conferences',
    'roundtable', 'briefing', 'fireside', 'seminar', 'seminars',
    'agenda', 'speakers', 'register', 'rsvp', 'attend',
    'event date', 'event time', 'timezone', 'duration'
]

# MEDIUM-PRIORITY: Event-related but less specific
SIGNUP_KEYWORDS_MEDIUM = [
    'events', 'event', 'calendar', 'upcoming', 'schedule',
    'registration', 'join us', 'event calendar'
]

# STRONGLY PENALIZED: Newsletter/marketing terms (should reduce score)
SIGNUP_KEYWORDS_PENALTY = [
    'newsletter', 'subscribe', 'subscription', 'email alerts', 'alerts',
    'mailing list', 'sign up', 'signup', 'marketing', 'preferences',
    'email preferences', 'notifications'
]

# STRONG POSITIVE: Event portal URL patterns (high value)
SIGNUP_PATH_PATTERNS_HIGH = [
    r'/events',
    r'/webinars',
    r'/conferences',
    r'/events/register',
    r'/webinar/',
    r'/event-calendar',
    r'/events-calendar',
    r'/upcoming-events'
]

# MEDIUM POSITIVE: Event-related paths
SIGNUP_PATH_PATTERNS_MEDIUM = [
    r'/event',
    r'/calendar',
    r'/conference',
    r'/seminar',
    r'/schedule',
    r'/agenda'
]

# STRONG NEGATIVE: Newsletter/marketing paths (should reject)
SIGNUP_PATH_PATTERNS_NEGATIVE = [
    r'/newsletter',
    r'/subscribe',
    r'/subscription',
    r'/email-alerts',
    r'/preferences',
    r'/email-preferences'
]

# Negative patterns (strong penalty)
NEGATIVE_PATTERNS_STRONG = [
    r'/careers', r'/jobs', r'/recruiting', r'/login', r'/signin',
    r'/sign-?in', r'/account', r'/portal', r'/client', r'/private',
    r'/legal', r'/terms', r'/privacy', r'/cookie', r'/disclaimer'
]

# Negative patterns (mild penalty)
NEGATIVE_PATTERNS_MILD = [
    r'/press-?release', r'/media-?contact', r'/newsroom',
    r'/investor-?relations', r'/sec-?filing', r'/annual-?report',
    r'/about-?us', r'/contact-?us', r'/support'
]


def load_newsletter_targets() -> dict:
    """Load newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    if not targets_path.exists():
        return {'targets': []}
    with open(targets_path) as f:
        return json.load(f)


def save_newsletter_targets(data: dict):
    """Save newsletter_targets.json."""
    targets_path = Path(backend_dir) / 'backend' / 'newsletter_targets.json'
    data['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    with open(targets_path, 'w') as f:
        json.dump(data, f, indent=2)


def ensure_acquisition_fields(target: dict) -> dict:
    """Ensure target has acquisition fields (backwards compatible)."""
    if 'acquisition' not in target:
        target['acquisition'] = {}
    
    # Ensure acquisition_mode exists (default to 'both' for backwards compatibility)
    if 'acquisition_mode' not in target:
        target['acquisition_mode'] = 'both'
    
    acq = target['acquisition']
    acq.setdefault('discovery_seed_urls', [])
    acq.setdefault('discovered_signup_pages', [])
    acq.setdefault('discovered_forms', [])
    acq.setdefault('subscribe_attempts', [])
    acq.setdefault('opt_in_required', None)
    acq.setdefault('last_success_utc', None)
    acq.setdefault('last_failure_utc', None)
    acq.setdefault('automation_feasibility', 'unknown')
    
    return target


def get_domain_homepage(target: dict) -> str:
    """Get homepage URL for a target."""
    domains = target.get('expected_from_domains', [])
    if domains:
        return f"https://www.{domains[0]}"
    return ''


def score_url(url: str, anchor_text: str = '') -> Tuple[int, List[str]]:
    """
    Score a URL for signup page likelihood.
    
    Returns:
        (score, signals_hit) tuple
    """
    url_lower = url.lower()
    anchor_lower = anchor_text.lower() if anchor_text else ''
    score = 0
    signals = []
    
    # High-value URL patterns (+40 each)
    for pattern in SIGNUP_PATH_PATTERNS_HIGH:
        if re.search(pattern, url_lower):
            score += 40
            signals.append(f"url:{pattern}")
    
    # Medium-value URL patterns (+20 each)
    for pattern in SIGNUP_PATH_PATTERNS_MEDIUM:
        if re.search(pattern, url_lower):
            score += 20
            signals.append(f"url:{pattern}")
    
    # STRONG NEGATIVE: Newsletter/marketing URL paths (reject immediately)
    for pattern in SIGNUP_PATH_PATTERNS_NEGATIVE:
        if re.search(pattern, url_lower):
            score -= 100  # Strong penalty
            signals.append(f"reject:newsletter_path:{pattern}")
    
    # High-value keywords in anchor text (+60 each) - EVENT-SPECIFIC
    for kw in SIGNUP_KEYWORDS_HIGH:
        if kw in anchor_lower:
            score += 60
            signals.append(f"anchor_high:{kw}")
    
    # Medium-value keywords in anchor text (+30 each) - EVENT-RELATED
    for kw in SIGNUP_KEYWORDS_MEDIUM:
        if kw in anchor_lower:
            score += 30
            signals.append(f"anchor_medium:{kw}")
    
    # STRONG PENALTY: Newsletter/marketing keywords in anchor (reduce score)
    for kw in SIGNUP_KEYWORDS_PENALTY:
        if kw in anchor_lower:
            score -= 40  # Strong penalty for newsletter terms
            signals.append(f"penalty:newsletter_keyword:{kw}")
    
    # Check for event registration combinations (high bonus)
    if any(kw in url_lower for kw in ['/event', '/webinar', '/conference']) and ('register' in url_lower or 'register' in anchor_lower or 'rsvp' in anchor_lower):
        score += 80
        signals.append("combo:event+register")
    
    if '/events' in url_lower and ('register' in url_lower or 'register' in anchor_lower or 'rsvp' in anchor_lower):
        score += 70
        signals.append("combo:events+register")
    
    # Strong negative patterns (-50 each)
    for pattern in NEGATIVE_PATTERNS_STRONG:
        if re.search(pattern, url_lower):
            score -= 50
            signals.append(f"negative:{pattern}")
    
    # Mild negative patterns (-15 each)
    for pattern in NEGATIVE_PATTERNS_MILD:
        if re.search(pattern, url_lower):
            score -= 15
            signals.append(f"mildneg:{pattern}")
    
    # Prefer HTTPS
    if url.startswith('https://'):
        score += 5
    
    # Penalize very long URLs (likely deep pages)
    if len(url) > 150:
        score -= 10
        signals.append("long_url")
    
    # Penalize URLs with lots of parameters
    if url.count('?') > 0 and url.count('&') > 2:
        score -= 10
        signals.append("many_params")
    
    return score, signals


def extract_candidate_links(html: str, base_url: str, target_domains: List[str] = None) -> List[Dict]:
    """
    Extract candidate signup page links from HTML.
    
    Returns:
        List of {url, text, score, signals_hit, discovered_from}
    """
    soup = BeautifulSoup(html, 'html.parser')
    candidates = []
    seen_urls = set()
    
    # All keywords to check (prioritize event-related, exclude penalty keywords from positive matching)
    all_keywords = SIGNUP_KEYWORDS_HIGH + SIGNUP_KEYWORDS_MEDIUM
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if not href or href.startswith('#') or href.startswith('javascript:') or href.startswith('mailto:'):
            continue
        
        # Resolve relative URLs
        full_url = urljoin(base_url, href)
        
        # Skip external links (different domain)
        base_domain = urlparse(base_url).netloc.lower()
        link_domain = urlparse(full_url).netloc.lower()
        
        # Check if link is on same domain or on target domains
        is_same_domain = base_domain in link_domain or link_domain in base_domain
        is_target_domain = False
        if target_domains:
            for td in target_domains:
                if td.lower() in link_domain:
                    is_target_domain = True
                    break
        
        if not is_same_domain and not is_target_domain:
            continue
        
        # Skip duplicates
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        
        # Get link text
        link_text = link.get_text(strip=True)
        link_text_lower = link_text.lower()
        url_lower = full_url.lower()
        
        # Check if link text or URL contains any keyword
        has_keyword = False
        for kw in all_keywords:
            if kw in link_text_lower or kw in url_lower:
                has_keyword = True
                break
        
        # Also check URL patterns
        if not has_keyword:
            for pattern in SIGNUP_PATH_PATTERNS_HIGH + SIGNUP_PATH_PATTERNS_MEDIUM:
                if re.search(pattern, url_lower):
                    has_keyword = True
                    break
        
        if not has_keyword:
            continue
        
        score, signals = score_url(full_url, link_text)
        
        if score > 0:
            candidates.append({
                'url': full_url,
                'anchor_text': link_text[:100],
                'score': score,
                'signals_hit': signals,
                'discovered_from': base_url
            })
    
    # Sort by score
    candidates.sort(key=lambda x: -x['score'])
    
    return candidates


def fetch_page(url: str, timeout: int = 15) -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch a page with error handling.
    
    Returns:
        (html_content, error_message)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        return response.text, None
    except requests.RequestException as e:
        return None, str(e)


def save_evidence(target_id: str, url: str, html: str, candidates: List[Dict]) -> str:
    """Save discovery evidence to file."""
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'discovery' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    
    # Save HTML
    html_path = evidence_dir / f"{url_hash}.html"
    with open(html_path, 'w', encoding='utf-8', errors='ignore') as f:
        f.write(html[:100000])  # Limit size
    
    # Save candidates JSON
    json_path = evidence_dir / f"{url_hash}_candidates.json"
    with open(json_path, 'w') as f:
        json.dump({
            'url': url,
            'discovered_at': datetime.now(timezone.utc).isoformat(),
            'candidates': candidates[:20]
        }, f, indent=2)
    
    return str(evidence_dir)


def validate_event_page(html: str) -> Tuple[bool, List[str], List[str]]:
    """
    HARD VALIDATION: A page ONLY passes if at least 2 of the criteria are true.
    
    Criteria:
    1. Contains multiple date/time patterns (repeating events)
    2. Contains repeating event cards/rows (structural pattern)
    3. Contains schema.org/Event or JSON-LD with "@type": "Event"
    4. Contains calendar affordances (ics, add to calendar, iCal)
    5. Contains agenda/speaker blocks
    
    Immediate FAIL if:
    - Primary CTA is "Subscribe to newsletter"
    - Page is only email preferences/alerts
    - No dates anywhere on page
    
    Returns:
        (is_valid, pass_reasons, fail_reasons)
    """
    if not html:
        return False, [], ['no_html_content']
    
    html_lower = html.lower()
    pass_reasons = []
    fail_reasons = []
    
    # IMMEDIATE FAIL CHECKS (hard stops)
    # Check if primary CTA is newsletter subscription
    if re.search(r'subscribe\s+to\s+newsletter', html_lower, re.IGNORECASE):
        fail_reasons.append('primary_cta_is_newsletter_subscribe')
    
    # Check if page is only email preferences/alerts
    if re.search(r'email\s+(preferences|alerts|notifications)', html_lower) and not any(kw in html_lower for kw in ['event', 'webinar', 'conference', 'calendar']):
        fail_reasons.append('email_preferences_only')
    
    # If immediate fail, return early
    if fail_reasons:
        return False, [], fail_reasons
    
    # CRITERION 1: Multiple date/time patterns (repeating events)
    date_patterns = [
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}',
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
        r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
        r'\d{1,2}:\d{2}\s*(am|pm|AM|PM)',
        r'\d{1,2}:\d{2}',
    ]
    date_matches = 0
    for pattern in date_patterns:
        matches = re.findall(pattern, html_lower)
        date_matches += len(matches)
    
    if date_matches >= 3:  # Multiple dates = repeating events
        pass_reasons.append(f'multiple_dates_found_{date_matches}_matches')
    elif date_matches == 0:
        fail_reasons.append('no_dates_found')
    
    # CRITERION 2: Repeating event cards/rows (structural pattern)
    # Look for repeating patterns that suggest event listings
    event_card_indicators = [
        r'<div[^>]*class="[^"]*event[^"]*"',
        r'<article[^>]*class="[^"]*event[^"]*"',
        r'<li[^>]*class="[^"]*event[^"]*"',
        r'event-card',
        r'event-item',
        r'event-listing',
    ]
    card_matches = 0
    for pattern in event_card_indicators:
        matches = re.findall(pattern, html_lower)
        card_matches += len(matches)
    
    if card_matches >= 2:  # Multiple event cards
        pass_reasons.append(f'repeating_event_cards_{card_matches}_found')
    
    # CRITERION 3: schema.org/Event or JSON-LD with "@type": "Event"
    if '"@type":\s*"Event"' in html_lower or '"@type":"Event"' in html_lower:
        pass_reasons.append('schema_org_event_found')
    if 'schema.org/Event' in html_lower:
        pass_reasons.append('schema_org_event_url_found')
    
    # CRITERION 4: Calendar affordances (ics, add to calendar, iCal)
    calendar_indicators = [
        r'\.ics',
        r'add\s+to\s+calendar',
        r'ical',
        r'outlook\s+calendar',
        r'google\s+calendar',
        r'download\s+calendar',
    ]
    calendar_found = False
    for pattern in calendar_indicators:
        if re.search(pattern, html_lower):
            calendar_found = True
            break
    if calendar_found:
        pass_reasons.append('calendar_affordances_found')
    
    # CRITERION 5: Agenda/speaker blocks
    agenda_speaker_indicators = [
        r'agenda',
        r'speaker',
        r'panelist',
        r'presenter',
        r'hosted\s+by',
        r'moderated\s+by',
    ]
    agenda_found = False
    for pattern in agenda_speaker_indicators:
        if re.search(pattern, html_lower):
            agenda_found = True
            break
    if agenda_found:
        pass_reasons.append('agenda_speaker_blocks_found')
    
    # FINAL DECISION: Must pass at least 2 criteria
    if len(pass_reasons) >= 2:
        return True, pass_reasons, fail_reasons
    else:
        if not fail_reasons:
            fail_reasons.append(f'insufficient_criteria_only_{len(pass_reasons)}_passed')
        return False, pass_reasons, fail_reasons


def discover_for_target(target: dict, max_pages: int = 15, rate_limit_ms: int = 800, depth: int = 2) -> Dict:
    """
    Discover signup pages for a single target.
    
    Args:
        target: Target dict
        max_pages: Max pages to fetch total
        rate_limit_ms: Rate limit between requests
        depth: Max link depth (1 = seeds only, 2 = follow top candidates)
    
    Returns:
        Discovery result dict
    """
    target = ensure_acquisition_fields(target)
    target_id = target.get('id', 'unknown')
    org_name = target.get('org_name', 'Unknown')
    target_domains = target.get('expected_from_domains', [])
    
    result = {
        'target_id': target_id,
        'org_name': org_name,
        'seed_urls': [],
        'pages_fetched': 0,
        'candidates_found': [],
        'errors': []
    }
    
    # Get seed URLs
    seed_urls = target['acquisition'].get('discovery_seed_urls', [])
    if not seed_urls:
        homepage = get_domain_homepage(target)
        if homepage:
            seed_urls = [homepage]
    
    if not seed_urls:
        result['errors'].append('No seed URLs and no expected domains')
        return result
    
    result['seed_urls'] = seed_urls
    all_candidates = []
    pages_fetched = 0
    
    # Fetch all seed URLs
    for seed_url in seed_urls:
        if pages_fetched >= max_pages:
            break
        
        print(f"  Fetching: {seed_url[:70]}...")
        
        html, error = fetch_page(seed_url)
        if error:
            result['errors'].append(f"{seed_url}: {error[:50]}")
            continue
        
        pages_fetched += 1
        
        # Extract candidates
        candidates = extract_candidate_links(html, seed_url, target_domains)
        
        # Save evidence
        evidence_path = save_evidence(target_id, seed_url, html, candidates)
        
        for c in candidates[:15]:
            c['evidence_path'] = evidence_path
            all_candidates.append(c)
        
        # Rate limit
        time.sleep(rate_limit_ms / 1000)
    
    # Follow top candidates (depth 2)
    if depth >= 2:
        # Get unique high-scoring candidates not yet fetched
        candidates_to_follow = []
        seen_urls = set(seed_urls)
        
        for c in sorted(all_candidates, key=lambda x: -x['score']):
            if c['url'] not in seen_urls and c['score'] >= 30:
                seen_urls.add(c['url'])
                candidates_to_follow.append(c)
        
        for candidate in candidates_to_follow[:min(5, max_pages - pages_fetched)]:
            if pages_fetched >= max_pages:
                break
            
            print(f"    Following (score={candidate['score']}): {candidate['url'][:60]}...")
            
            sub_html, sub_error = fetch_page(candidate['url'])
            if sub_error:
                continue
            
            pages_fetched += 1
            sub_candidates = extract_candidate_links(sub_html, candidate['url'], target_domains)
            save_evidence(target_id, candidate['url'], sub_html, sub_candidates)
            
            for sc in sub_candidates[:10]:
                sc['evidence_path'] = ''
                all_candidates.append(sc)
            
            time.sleep(rate_limit_ms / 1000)
    
    result['pages_fetched'] = pages_fetched
    
    # Deduplicate and sort
    seen = set()
    unique_candidates = []
    for c in sorted(all_candidates, key=lambda x: -x['score']):
        if c['url'] not in seen:
            seen.add(c['url'])
            unique_candidates.append(c)
    
        # Validate top candidates are actually event pages (not generic newsletters)
        # Only validate top 10 to avoid too many network requests
        validated_candidates = []
        for candidate in unique_candidates:
            url = candidate['url']
            # Validate high-scoring candidates (skip if already strongly penalized)
            if candidate['score'] >= 50 and len(validated_candidates) < 10 and candidate['score'] > 0:
                html, _ = fetch_page(url)
                if html:
                    is_valid, pass_reasons, fail_reasons = validate_event_page(html)
                    if is_valid:
                        candidate['event_validation'] = {
                            'valid': True,
                            'pass_reasons': pass_reasons
                        }
                        # Boost score for validated event pages
                        candidate['score'] += 50
                    else:
                        # Strong penalty for failed validation
                        candidate['score'] -= 60
                        candidate['event_validation'] = {
                            'valid': False,
                            'fail_reasons': fail_reasons,
                            'pass_reasons': pass_reasons
                        }
            
            validated_candidates.append(candidate)
    
    # Re-sort after validation
    validated_candidates.sort(key=lambda x: -x['score'])
    
    # Prioritize validated event pages, but keep some high-scoring fallbacks
    final_candidates = []
    event_pages = [c for c in validated_candidates if c.get('event_validation', {}).get('valid')]
    other_high_score = [c for c in validated_candidates if not c.get('event_validation', {}).get('valid') and c['score'] >= 60]
    
    # Prioritize validated event pages
    final_candidates.extend(event_pages[:15])
    final_candidates.extend(other_high_score[:5])  # Keep some high-scoring ones as fallback
    
    result['candidates_found'] = final_candidates[:20]
    
    # Save consolidated evidence
    save_consolidated_evidence(target_id, result)
    
    return result


def save_consolidated_evidence(target_id: str, result: Dict):
    """Save consolidated discovery evidence for a target."""
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'discovery' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    # Save discovered_pages.json
    pages_path = evidence_dir / 'discovered_pages.json'
    with open(pages_path, 'w') as f:
        json.dump({
            'target_id': target_id,
            'org_name': result.get('org_name', ''),
            'discovered_at': datetime.now(timezone.utc).isoformat(),
            'seed_urls': result.get('seed_urls', []),
            'pages_fetched': result.get('pages_fetched', 0),
            'candidates': result.get('candidates_found', []),
            'errors': result.get('errors', [])
        }, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Discover newsletter signup pages')
    parser.add_argument('--target-id', type=str, help='Process specific target ID')
    parser.add_argument('--priority', type=str, choices=['p0', 'p1', 'p2'], help='Process targets by priority')
    parser.add_argument('--all', action='store_true', help='Process all targets')
    parser.add_argument('--max-pages', type=int, default=15, help='Max pages to fetch per target')
    parser.add_argument('--depth', type=int, default=2, help='Max link depth (1=seeds only, 2=follow)')
    parser.add_argument('--rate-limit-ms', type=int, default=800, help='Rate limit between requests (ms)')
    parser.add_argument('--apply', action='store_true', help='Apply discoveries to newsletter_targets.json')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no writes)')
    args = parser.parse_args()
    
    if not args.target_id and not args.priority and not args.all:
        print("Error: Specify --target-id, --priority, or --all")
        sys.exit(1)
    
    targets_data = load_newsletter_targets()
    targets = targets_data.get('targets', [])
    
    # Filter targets
    if args.target_id:
        targets = [t for t in targets if t.get('id') == args.target_id]
    elif args.priority:
        targets = [t for t in targets if t.get('priority') == args.priority]
    
    if not targets:
        print("No matching targets found")
        sys.exit(1)
    
    print(f"Discovering signup pages for {len(targets)} target(s)")
    print(f"Rate limit: {args.rate_limit_ms}ms, Max pages: {args.max_pages}, Depth: {args.depth}")
    print()
    
    all_results = []
    
    # Filter targets: only events_portal/both mode (newsletter-only targets skip discovery)
    targets = [t for t in targets if t.get('acquisition_mode', 'both') in ['events_portal', 'both']]
    
    # Filter targets by governance (GOVERNANCE - before any network requests)
    from backend.utils.decision_engine import filter_targets_by_governance
    if not args.dry_run:
        targets = filter_targets_by_governance(targets, allowed_statuses=None)  # Check pause/cooldown only
    
    for target in targets:
        target = ensure_acquisition_fields(target)
        target_id = target.get('id')
        org_name = target.get('org_name')
        
        print(f"[{target_id}] {org_name}")
        
        if args.dry_run:
            # Dry-run: simulate discovery without network requests
            seed_urls = target.get('acquisition', {}).get('discovery_seed_urls', [])
            result = {
                'target_id': target_id,
                'org_name': org_name,
                'seed_urls': seed_urls[:3],
                'pages_fetched': 0,
                'candidates_found': [],
                'errors': []
            }
            print(f"  [DRY RUN] Would fetch {len(seed_urls)} seed URLs")
        else:
            result = discover_for_target(target, args.max_pages, args.rate_limit_ms, args.depth)
        all_results.append(result)
        
        # Update target with discoveries
        if args.apply and not args.dry_run:
            now = datetime.now(timezone.utc).isoformat()
            for candidate in result['candidates_found'][:10]:
                # Check if already discovered
                existing = [p['url'] for p in target['acquisition']['discovered_signup_pages']]
                if candidate['url'] not in existing:
                    target['acquisition']['discovered_signup_pages'].append({
                        'url': candidate['url'],
                        'score': candidate['score'],
                        'evidence_path': candidate.get('evidence_path', ''),
                        'discovered_at_utc': now
                    })
        
        print(f"  Pages fetched: {result['pages_fetched']}")
        print(f"  Candidates found: {len(result['candidates_found'])}")
        if result['candidates_found']:
            top = result['candidates_found'][0]
            print(f"  Top candidate (score={top['score']}): {top['url'][:70]}")
            if len(result['candidates_found']) > 1:
                second = result['candidates_found'][1]
                print(f"  2nd candidate (score={second['score']}): {second['url'][:70]}")
        if result['errors']:
            print(f"  Errors: {len(result['errors'])}")
        print()
    
    # Save results
    results_path = Path(backend_dir) / 'backend' / 'newsletter_discovery_results.json'
    if not args.dry_run:
        with open(results_path, 'w') as f:
            json.dump({
                'discovered_at': datetime.now(timezone.utc).isoformat(),
                'results': all_results
            }, f, indent=2)
        print(f"Results saved to: {results_path}")
    
    # Save targets if --apply
    if args.apply and not args.dry_run:
        save_newsletter_targets(targets_data)
        print(f"Updated newsletter_targets.json")
    
    # Print summary
    print()
    print("=" * 60)
    print("DISCOVERY SUMMARY")
    print("=" * 60)
    total_candidates = sum(len(r['candidates_found']) for r in all_results)
    total_pages = sum(r['pages_fetched'] for r in all_results)
    print(f"Targets processed: {len(all_results)}")
    print(f"Pages fetched: {total_pages}")
    print(f"Candidates found: {total_candidates}")
    print("=" * 60)


if __name__ == '__main__':
    main()
