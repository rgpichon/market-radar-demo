#!/usr/bin/env python3
"""
Newsletter Subscription Execution

Attempts to subscribe to newsletters using extracted form data.
Supports HTTP mode (requests) and optional Playwright mode.
"""
import sys
import json
import argparse
import hashlib
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List
from urllib.parse import urljoin, urlparse

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    import requests
except ImportError:
    print("Required: pip install requests")
    sys.exit(1)

# Subscription email
SUBSCRIBE_EMAIL = "rdr.events.rp@gmail.com"
SUBSCRIBE_NAME = "RDR Events"

# Success indicators in response
SUCCESS_INDICATORS = [
    'check your email', 'confirmation', 'subscribed', 'thank you',
    'thanks for signing up', 'verify your email', 'welcome',
    'successfully registered', 'you have been added'
]

# Failure indicators
FAILURE_INDICATORS = [
    'error', 'invalid', 'already subscribed', 'please try again',
    'something went wrong', 'captcha', 'verify you are human'
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
    """Ensure target has acquisition fields."""
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


def save_evidence(target_id: str, attempt: Dict) -> str:
    """Save subscription attempt evidence."""
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'subscribe' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    json_path = evidence_dir / f"attempt_{ts}.json"
    
    with open(json_path, 'w') as f:
        json.dump(attempt, f, indent=2)
    
    return str(json_path)


def analyze_response(html: str, status_code: int) -> Tuple[str, str]:
    """
    Analyze response to determine subscription outcome.
    
    Returns:
        (outcome, reason) tuple
    """
    if status_code >= 400:
        return 'failure', f'HTTP {status_code}'
    
    html_lower = html.lower()
    
    # Check for CAPTCHA
    if 'captcha' in html_lower or 'recaptcha' in html_lower:
        return 'blocked', 'captcha_required'
    
    # Check for success
    for indicator in SUCCESS_INDICATORS:
        if indicator in html_lower:
            return 'success', indicator
    
    # Check for failure
    for indicator in FAILURE_INDICATORS:
        if indicator in html_lower:
            return 'failure', indicator
    
    # If 200/302 and no clear indicators, assume pending
    if status_code in [200, 302, 303]:
        return 'pending', 'no_clear_indicator'
    
    return 'unknown', 'could_not_determine'


def subscribe_http(form: Dict, target_id: str) -> Dict:
    """
    Attempt subscription via HTTP form submit.
    
    Returns:
        Attempt result dict
    """
    attempt = {
        'ts_utc': datetime.now(timezone.utc).isoformat(),
        'page_url': form.get('page_url', ''),
        'method': 'http',
        'outcome': 'unknown',
        'reason': '',
        'evidence_path': ''
    }
    
    # Check prerequisites
    if not form.get('email_field'):
        attempt['outcome'] = 'skipped'
        attempt['reason'] = 'no_email_field'
        return attempt
    
    if form.get('obstacles', {}).get('captcha'):
        attempt['outcome'] = 'skipped'
        attempt['reason'] = 'captcha_detected'
        return attempt
    
    if form.get('obstacles', {}).get('login_required'):
        attempt['outcome'] = 'skipped'
        attempt['reason'] = 'login_required'
        return attempt
    
    # Build form data
    form_data = {}
    
    # Add email
    email_name = form['email_field'].get('name', 'email')
    form_data[email_name] = SUBSCRIBE_EMAIL
    
    # Add name if present
    if form.get('name_field'):
        name_field = form['name_field'].get('name', 'name')
        form_data[name_field] = SUBSCRIBE_NAME
    
    # Add hidden fields
    for hidden in form.get('hidden_fields', []):
        if hidden.get('name'):
            form_data[hidden['name']] = hidden.get('value', '')
    
    # Add consent checkbox if present
    if form.get('consent_checkbox'):
        checkbox_name = form['consent_checkbox'].get('name', 'consent')
        form_data[checkbox_name] = 'on'
    
    # Determine action URL
    action = form.get('action', '')
    if not action:
        action = form.get('page_url', '')
    elif not action.startswith('http'):
        action = urljoin(form.get('page_url', ''), action)
    
    if not action:
        attempt['outcome'] = 'skipped'
        attempt['reason'] = 'no_action_url'
        return attempt
    
    # Make request
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'text/html,application/xhtml+xml',
            'Referer': form.get('page_url', '')
        }
        
        method = form.get('method', 'POST').upper()
        
        if method == 'POST':
            response = requests.post(action, data=form_data, headers=headers, timeout=30, allow_redirects=True)
        else:
            response = requests.get(action, params=form_data, headers=headers, timeout=30, allow_redirects=True)
        
        # Analyze response
        outcome, reason = analyze_response(response.text, response.status_code)
        attempt['outcome'] = outcome
        attempt['reason'] = reason
        attempt['status_code'] = response.status_code
        attempt['response_snippet'] = response.text[:2000]
        
    except requests.RequestException as e:
        attempt['outcome'] = 'error'
        attempt['reason'] = str(e)
    
    # Save evidence
    attempt['evidence_path'] = save_evidence(target_id, attempt)
    
    return attempt


def subscribe_playwright(form: Dict, target_id: str, headed: bool = True) -> Dict:
    """
    Attempt subscription via Playwright browser automation.
    Stops before submit if CAPTCHA is detected.
    """
    attempt = {
        'ts_utc': datetime.now(timezone.utc).isoformat(),
        'page_url': form.get('page_url', ''),
        'method': 'playwright',
        'outcome': 'unknown',
        'reason': '',
        'evidence_path': ''
    }
    
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        attempt['outcome'] = 'skipped'
        attempt['reason'] = 'playwright_not_installed'
        return attempt
    
    evidence_dir = Path(backend_dir) / 'backend' / '_evidence' / 'newsletter_acq' / 'subscribe' / target_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed)
            page = browser.new_page()
            
            page.goto(form.get('page_url', ''))
            time.sleep(2)
            
            # Check for CAPTCHA
            html = page.content().lower()
            if 'captcha' in html or 'recaptcha' in html:
                attempt['outcome'] = 'blocked'
                attempt['reason'] = 'captcha_detected_manual_required'
                page.screenshot(path=str(evidence_dir / f"screenshot_{ts}.png"))
                print(f"  CAPTCHA detected. Page left open for manual completion.")
                print(f"  Press Enter after completing CAPTCHA...")
                input()
                html = page.content()
            
            # Fill email
            if form.get('email_field', {}).get('selector'):
                try:
                    page.fill(form['email_field']['selector'], SUBSCRIBE_EMAIL)
                except:
                    page.fill("input[type='email']", SUBSCRIBE_EMAIL)
            
            # Fill name
            if form.get('name_field', {}).get('selector'):
                try:
                    page.fill(form['name_field']['selector'], SUBSCRIBE_NAME)
                except:
                    pass
            
            # Check consent
            if form.get('consent_checkbox', {}).get('selector'):
                try:
                    page.check(form['consent_checkbox']['selector'])
                except:
                    pass
            
            # Take screenshot before submit
            page.screenshot(path=str(evidence_dir / f"before_submit_{ts}.png"))
            
            # Submit
            if form.get('submit_selector'):
                try:
                    page.click(form['submit_selector'])
                except:
                    page.click("button[type='submit']")
            
            time.sleep(3)
            
            # Take screenshot after submit
            page.screenshot(path=str(evidence_dir / f"after_submit_{ts}.png"))
            
            # Analyze result
            result_html = page.content()
            outcome, reason = analyze_response(result_html, 200)
            attempt['outcome'] = outcome
            attempt['reason'] = reason
            
            browser.close()
            
    except Exception as e:
        attempt['outcome'] = 'error'
        attempt['reason'] = str(e)
    
    attempt['evidence_path'] = str(evidence_dir)
    return attempt


def main():
    parser = argparse.ArgumentParser(description='Subscribe to newsletters')
    parser.add_argument('--target-id', type=str, help='Process specific target ID')
    parser.add_argument('--priority', type=str, choices=['p0', 'p1', 'p2'], help='Process targets by priority')
    parser.add_argument('--all', action='store_true', help='Process all targets')
    parser.add_argument('--use-playwright', action='store_true', help='Use Playwright for JS-heavy sites')
    parser.add_argument('--headed', action='store_true', default=True, help='Run browser in headed mode (default)')
    parser.add_argument('--apply', action='store_true', help='Record attempts to newsletter_targets.json')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no actual subscriptions)')
    parser.add_argument('--bypass-decision', action='store_true', help='Bypass decision engine check (attempt subscription even if manual_review)')
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
    
    # Only process targets with forms and feasible automation
    targets = [t for t in targets if ensure_acquisition_fields(t)['acquisition'].get('discovered_forms')]
    
    if not targets:
        print("No matching targets with discovered forms found")
        sys.exit(1)
    
    print(f"Subscribing for {len(targets)} target(s)")
    print(f"Mode: {'Playwright' if args.use_playwright else 'HTTP'}")
    print(f"Email: {SUBSCRIBE_EMAIL}")
    print()
    
    all_results = []
    
    for target in targets:
        target = ensure_acquisition_fields(target)
        target_id = target.get('id')
        org_name = target.get('org_name')
        
        print(f"[{target_id}] {org_name}")
        
        # Check pause/cooldown (GOVERNANCE - hard block before any network request)
        from backend.db import is_paused_or_cooldown, get_decision
        is_blocked, block_reason = is_paused_or_cooldown(target_id)
        if is_blocked:
            print(f"  Skipped: {block_reason}")
            continue
        
        # Consult decision engine (PHASE 3)
        decision = get_decision(target_id)
        if decision:
            decision_status = decision.get('decision_status', '')
            decision_score = decision.get('decision_score', 0)
            recommended_action = decision.get('recommended_next_action', '')
            
            # Terminal states: rejected, paused (manual)
            if decision_status == 'rejected':
                print(f"  Skipped: Rejected by decision engine (score: {decision_score})")
                continue
            
            if decision_status == 'paused' and decision.get('paused_reason', '').startswith('manual'):
                print(f"  Skipped: Manually paused")
                continue
            
            # Only auto-subscribe if decision engine says so (unless bypass flag)
            bypass_decision = getattr(args, 'bypass_decision', False)
            if decision_status != 'auto_subscribe' and not bypass_decision:
                print(f"  Skipped: Decision status is '{decision_status}' (not auto_subscribe)")
                print(f"    Score: {decision_score}, Recommended: {recommended_action}")
                print(f"    Use --bypass-decision to attempt anyway")
                continue
            
            if bypass_decision and decision_status != 'auto_subscribe':
                print(f"  [BYPASS] Attempting despite decision status '{decision_status}' (score: {decision_score})")
            else:
                print(f"  Decision: {decision_status} (score: {decision_score}, action: {recommended_action})")
        
        forms = target['acquisition'].get('discovered_forms', [])
        feasibility = target['acquisition'].get('automation_feasibility', 'unknown')
        
        if feasibility in ['captcha_blocked', 'login_required']:
            print(f"  Skipped: {feasibility}")
            continue
        
        result = {
            'target_id': target_id,
            'org_name': org_name,
            'attempts': []
        }
        
        for form in forms[:2]:  # Try top 2 forms
            if form.get('confidence') not in ['high', 'medium']:
                continue
            
            print(f"  Form: {form.get('page_url', '')[:60]}...")
            
            if args.dry_run:
                print("    [DRY RUN] Would attempt subscription")
                attempt = {
                    'ts_utc': datetime.now(timezone.utc).isoformat(),
                    'page_url': form.get('page_url', ''),
                    'method': 'dry_run',
                    'outcome': 'skipped',
                    'reason': 'dry_run'
                }
            elif args.use_playwright:
                attempt = subscribe_playwright(form, target_id, args.headed)
            else:
                attempt = subscribe_http(form, target_id)
            
            result['attempts'].append(attempt)
            
            print(f"    Outcome: {attempt['outcome']}")
            print(f"    Reason: {attempt['reason']}")
            
            # Record attempt
            if args.apply and not args.dry_run:
                target['acquisition']['subscribe_attempts'].append({
                    'ts_utc': attempt['ts_utc'],
                    'page_url': attempt['page_url'],
                    'outcome': attempt['outcome'],
                    'reason': attempt['reason'],
                    'evidence_path': attempt.get('evidence_path', '')
                })
                
                # Update status and record failures (GOVERNANCE)
                if attempt['outcome'] == 'success':
                    target['acquisition']['last_success_utc'] = attempt['ts_utc']
                    target['acquisition']['opt_in_required'] = True
                    target['status'] = 'subscribed'
                    if not args.dry_run:
                        from backend.db import record_subscription_success
                        record_subscription_success(target_id)
                elif attempt['outcome'] == 'failure':
                    target['acquisition']['last_failure_utc'] = attempt['ts_utc']
                    if not args.dry_run:
                        from backend.db import record_subscription_failure
                        # Determine failure type from reason
                        failure_type = 'unknown'
                        reason_lower = attempt.get('reason', '').lower()
                        if 'captcha' in reason_lower:
                            failure_type = 'captcha'
                        elif 'timeout' in reason_lower:
                            failure_type = 'timeout'
                        elif 'blocked' in reason_lower or '403' in reason_lower or '401' in reason_lower:
                            failure_type = 'blocked'
                        elif 'parse' in reason_lower:
                            failure_type = 'parse_error'
                        record_subscription_failure(target_id, failure_type)
            
            # Stop if successful
            if attempt['outcome'] == 'success':
                break
        
        all_results.append(result)
        print()
    
    # Save results
    results_path = Path(backend_dir) / 'backend' / 'newsletter_subscribe_results.json'
    if not args.dry_run:
        with open(results_path, 'w') as f:
            json.dump({
                'subscribed_at': datetime.now(timezone.utc).isoformat(),
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
    print("SUBSCRIPTION SUMMARY")
    print("=" * 60)
    success = sum(1 for r in all_results if any(a['outcome'] == 'success' for a in r['attempts']))
    pending = sum(1 for r in all_results if any(a['outcome'] == 'pending' for a in r['attempts']))
    blocked = sum(1 for r in all_results if any(a['outcome'] == 'blocked' for a in r['attempts']))
    print(f"Targets processed: {len(all_results)}")
    print(f"Successful: {success}")
    print(f"Pending (check email): {pending}")
    print(f"Blocked (CAPTCHA/login): {blocked}")
    print("=" * 60)


if __name__ == '__main__':
    main()
