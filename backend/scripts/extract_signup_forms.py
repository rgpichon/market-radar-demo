#!/usr/bin/env python3
"""
Newsletter Signup Form Extraction

Extracts signup form details from discovered signup pages.
Detects obstacles like CAPTCHAs and login walls.
"""
import sys
import json
import argparse
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
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


# CAPTCHA indicators
CAPTCHA_INDICATORS = [
    'recaptcha', 'hcaptcha', 'captcha', 'g-recaptcha',
    'h-captcha', 'cf-turnstile', 'turnstile'
]

# Login wall indicators
LOGIN_INDICATORS = [
    'sign in', 'log in', 'login', 'signin', 'authentication',
    'sso', 'single sign-on', 'create account'
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


def fetch_page(url: str, timeout: int = 15) -> Tuple[Optional[str], Optional[str]]:
    """Fetch a page with error handling."""
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


def detect_captcha(html: str, soup: BeautifulSoup) -> bool:
    """Detect if page has CAPTCHA."""
    html_lower = html.lower()
    for indicator in CAPTCHA_INDICATORS:
        if indicator in html_lower:
            return True
    
    # Check for reCAPTCHA script
    for script in soup.find_all('script', src=True):
        src = script.get('src', '').lower()
        if 'recaptcha' in src or 'hcaptcha' in src:
            return True
    
    return False


def detect_login_wall(html: str, soup: BeautifulSoup) -> bool:
    """Detect if page requires login."""
    html_lower = html.lower()
    
    # Check for login forms
    for form in soup.find_all('form'):
        form_html = str(form).lower()
        if 'password' in form_html:
            return True
    
    # Check for login indicators in prominent positions
    for indicator in LOGIN_INDICATORS:
        # Check if login is required (not just a link)
        if f'must {indicator}' in html_lower or f'please {indicator}' in html_lower:
            return True
    
    return False


def detect_js_heavy(html: str, soup: BeautifulSoup) -> bool:
    """Detect if page is JS-heavy with no forms in HTML."""
    forms = soup.find_all('form')
    
    # Check for JS framework indicators
    js_indicators = ['react', 'angular', 'vue', '__NEXT_DATA__', 'window.__INITIAL_STATE__']
    html_lower = html.lower()
    
    has_js_framework = any(ind in html_lower for ind in js_indicators)
    
    # JS-heavy if no forms but has framework indicators
    return len(forms) == 0 and has_js_framework


def extract_form_details(form: BeautifulSoup, page_url: str) -> Dict:
    """Extract details from a form element."""
    result = {
        'page_url': page_url,
        'form_selector': '',
        'email_field': None,
        'name_field': None,
        'consent_checkbox': None,
        'submit_selector': None,
        'method': 'POST',
        'action': '',
        'hidden_fields': [],
        'confidence': 'low'
    }
    
    # Get form attributes
    result['method'] = form.get('method', 'POST').upper()
    result['action'] = form.get('action', '')
    
    # Build form selector
    form_id = form.get('id')
    form_class = form.get('class', [])
    if form_id:
        result['form_selector'] = f"#{form_id}"
    elif form_class:
        result['form_selector'] = f".{'.'.join(form_class)}"
    else:
        result['form_selector'] = "form"
    
    # Find email field
    email_fields = form.find_all('input', type='email')
    if not email_fields:
        # Try by name/id
        for inp in form.find_all('input'):
            name = (inp.get('name', '') + inp.get('id', '')).lower()
            if 'email' in name:
                email_fields = [inp]
                break
    
    if email_fields:
        ef = email_fields[0]
        result['email_field'] = {
            'name': ef.get('name', ''),
            'id': ef.get('id', ''),
            'selector': f"input[name='{ef.get('name', '')}']" if ef.get('name') else f"input[type='email']"
        }
    
    # Find name field
    for inp in form.find_all('input', type='text'):
        name = (inp.get('name', '') + inp.get('id', '')).lower()
        if 'name' in name and 'email' not in name:
            result['name_field'] = {
                'name': inp.get('name', ''),
                'id': inp.get('id', ''),
                'selector': f"input[name='{inp.get('name', '')}']"
            }
            break
    
    # Find consent checkbox
    for inp in form.find_all('input', type='checkbox'):
        name = (inp.get('name', '') + inp.get('id', '')).lower()
        # Check nearby label text
        label = inp.find_next('label') or inp.find_previous('label')
        label_text = label.get_text(strip=True).lower() if label else ''
        
        if any(kw in name or kw in label_text for kw in ['consent', 'agree', 'gdpr', 'privacy', 'accept', 'terms']):
            result['consent_checkbox'] = {
                'name': inp.get('name', ''),
                'id': inp.get('id', ''),
                'selector': f"input[name='{inp.get('name', '')}']" if inp.get('name') else f"#{inp.get('id', '')}"
            }
            break
    
    # Find submit button
    submit = form.find('button', type='submit') or form.find('input', type='submit')
    if not submit:
        submit = form.find('button')
    if submit:
        result['submit_selector'] = f"button[type='submit']" if submit.name == 'button' else "input[type='submit']"
    
    # Find hidden fields
    for inp in form.find_all('input', type='hidden'):
        result['hidden_fields'].append({
            'name': inp.get('name', ''),
            'value': inp.get('value', '')
        })
    
    # Calculate confidence
    if result['email_field'] and result['action']:
        result['confidence'] = 'high'
    elif result['email_field']:
        result['confidence'] = 'medium'
    
    return result


def extract_forms_from_page(url: str, html: str = None) -> Dict:
    """
    Extract all subscription forms from a page.
    
    Returns:
        Dict with forms, obstacles, and metadata
    """
    result = {
        'url': url,
        'forms': [],
        'obstacles': {
            'captcha': False,
            'login_required': False,
            'js_heavy': False
        },
        'error': None
    }
    
    if html is None:
        html, error = fetch_page(url)
        if error:
            result['error'] = error
            return result
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Detect obstacles
    result['obstacles']['captcha'] = detect_captcha(html, soup)
    result['obstacles']['login_required'] = detect_login_wall(html, soup)
    result['obstacles']['js_heavy'] = detect_js_heavy(html, soup)
    
    # Find forms
    for form in soup.find_all('form'):
        form_html = str(form).lower()
        
        # Skip login forms
        if 'password' in form_html:
            continue
        
        # Check if form looks like subscription
        is_subscription = False
        for kw in ['subscribe', 'newsletter', 'email', 'signup', 'sign-up', 'register', 'updates']:
            if kw in form_html:
                is_subscription = True
                break
        
        if not is_subscription:
            continue
        
        form_details = extract_form_details(form, url)
        result['forms'].append(form_details)
    
    return result


def save_evidence(target_id: str, url: str, html: str, extraction: Dict) -> str:
    """Save form extraction evidence."""
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'forms' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    
    # Save HTML
    html_path = evidence_dir / f"{url_hash}.html"
    with open(html_path, 'w', encoding='utf-8', errors='ignore') as f:
        f.write(html[:100000])
    
    # Save extraction JSON
    json_path = evidence_dir / f"{url_hash}_forms.json"
    with open(json_path, 'w') as f:
        json.dump(extraction, f, indent=2)
    
    return str(evidence_dir)


def determine_feasibility(target: dict) -> str:
    """
    Determine automation feasibility for a target.
    
    Returns one of:
    - feasible_http_post: Can subscribe via HTTP form submit
    - requires_manual: Manual subscription required (complex form)
    - captcha_blocked: CAPTCHA detected
    - login_required: Authentication required
    - js_heavy_form: No actionable form in HTML
    - mailto_only: Only mailto: links found
    - unknown: Not enough information
    """
    acq = target.get('acquisition', {})
    forms = acq.get('discovered_forms', [])
    pages = acq.get('discovered_signup_pages', [])
    
    if not pages:
        return 'unknown'
    
    if not forms:
        return 'js_heavy_form'
    
    # Check all forms for obstacles and capabilities
    best_form = None
    has_captcha = False
    has_login = False
    has_js_heavy = False
    
    for form in forms:
        obstacles = form.get('obstacles', {})
        
        if obstacles.get('captcha'):
            has_captcha = True
        if obstacles.get('login_required'):
            has_login = True
        if obstacles.get('js_heavy'):
            has_js_heavy = True
        
        # Check if form is actionable
        if form.get('confidence') in ['high', 'medium'] and form.get('email_field'):
            if not obstacles.get('captcha') and not obstacles.get('login_required'):
                if best_form is None or form.get('confidence') == 'high':
                    best_form = form
    
    # Determine feasibility
    if has_login:
        return 'login_required'
    if has_captcha:
        return 'captcha_blocked'
    if best_form and best_form.get('confidence') == 'high' and best_form.get('action'):
        return 'feasible_http_post'
    if best_form:
        return 'requires_manual'
    if has_js_heavy:
        return 'js_heavy_form'
    
    return 'unknown'


def save_best_candidate_forms(target_id: str, forms: List[Dict]):
    """Save the best candidate forms for a target."""
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'forms' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    # Sort by confidence and pick top 3
    sorted_forms = sorted(forms, key=lambda f: (
        0 if f.get('confidence') == 'high' else (1 if f.get('confidence') == 'medium' else 2),
        0 if f.get('email_field') else 1,
        0 if f.get('action') else 1
    ))
    
    best_forms = sorted_forms[:3]
    
    output = {
        'target_id': target_id,
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'best_forms': best_forms,
        'total_forms_found': len(forms)
    }
    
    path = evidence_dir / 'best_candidate_forms.json'
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)
    
    return str(path)


def main():
    parser = argparse.ArgumentParser(description='Extract newsletter signup forms')
    parser.add_argument('--target-id', type=str, help='Process specific target ID')
    parser.add_argument('--priority', type=str, choices=['p0', 'p1', 'p2'], help='Process targets by priority')
    parser.add_argument('--all', action='store_true', help='Process all targets')
    parser.add_argument('--apply', action='store_true', help='Apply extractions to newsletter_targets.json')
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
    
    print(f"Extracting forms for {len(targets)} target(s)")
    print()
    
    # Filter targets by governance (GOVERNANCE - before any network requests)
    from backend.utils.decision_engine import filter_targets_by_governance
    if not args.dry_run:
        targets = filter_targets_by_governance(targets, allowed_statuses=None)  # Check pause/cooldown only
    
    all_results = []
    
    for target in targets:
        target = ensure_acquisition_fields(target)
        target_id = target.get('id')
        org_name = target.get('org_name')
        
        print(f"[{target_id}] {org_name}")
        
        # Get discovered pages
        pages = target['acquisition'].get('discovered_signup_pages', [])
        
        # Also check signup_url
        signup_url = target.get('signup_url', '')
        if signup_url and signup_url != 'FILL_ME':
            pages.append({'url': signup_url, 'score': 100})
        
        if not pages:
            print("  No discovered pages to extract from")
            continue
        
        result = {
            'target_id': target_id,
            'org_name': org_name,
            'pages_processed': 0,
            'forms_found': [],
            'obstacles': []
        }
        
        for page in pages[:5]:  # Limit to top 5 pages
            url = page['url'] if isinstance(page, dict) else page
            print(f"  Extracting: {url[:60]}...")
            
            if args.dry_run:
                print(f"    [DRY RUN] Would fetch and extract forms from {url}")
                extraction = {
                    'url': url,
                    'forms': [],
                    'obstacles': {'captcha': False, 'login_required': False, 'js_heavy': False},
                    'error': None
                }
                evidence_path = None
            else:
                html, error = fetch_page(url)
                if error:
                    print(f"    Error: {error}")
                    continue
                
                extraction = extract_forms_from_page(url, html)
                result['pages_processed'] += 1
                
                # Save evidence
                evidence_path = save_evidence(target_id, url, html, extraction)
                
                for form in extraction['forms']:
                    form['evidence_path'] = evidence_path
                    form['obstacles'] = extraction['obstacles']
                    result['forms_found'].append(form)
            
            # Track obstacles (for both dry-run and real)
            if extraction['obstacles']['captcha']:
                result['obstacles'].append('captcha')
            if extraction['obstacles']['login_required']:
                result['obstacles'].append('login_required')
            if extraction['obstacles']['js_heavy']:
                result['obstacles'].append('js_heavy')
        
        # Save best candidate forms
        if result['forms_found']:
            save_best_candidate_forms(target_id, result['forms_found'])
        
        # Update target with forms
        if args.apply and not args.dry_run:
            for form in result['forms_found']:
                # Check if form already exists
                existing = [f['page_url'] for f in target['acquisition']['discovered_forms']]
                if form['page_url'] not in existing:
                    target['acquisition']['discovered_forms'].append(form)
            
            # Update feasibility
            target['acquisition']['automation_feasibility'] = determine_feasibility(target)
        
        all_results.append(result)
        
        print(f"  Pages processed: {result['pages_processed']}")
        print(f"  Forms found: {len(result['forms_found'])}")
        if result['obstacles']:
            print(f"  Obstacles: {', '.join(set(result['obstacles']))}")
        print()
    
    # Save results
    results_path = Path(backend_dir) / 'backend' / 'newsletter_forms.json'
    if not args.dry_run:
        with open(results_path, 'w') as f:
            json.dump({
                'extracted_at': datetime.now(timezone.utc).isoformat(),
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
    print("FORM EXTRACTION SUMMARY")
    print("=" * 60)
    total_forms = sum(len(r['forms_found']) for r in all_results)
    total_pages = sum(r['pages_processed'] for r in all_results)
    print(f"Targets processed: {len(all_results)}")
    print(f"Pages processed: {total_pages}")
    print(f"Forms found: {total_forms}")
    print("=" * 60)


if __name__ == '__main__':
    main()
