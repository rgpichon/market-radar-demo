# 🎯 Comprehensive Zero-Cost Bank Event Acquisition Strategy Guide

**Version**: 1.0  
**Last Updated**: January 29, 2026  
**Purpose**: Detailed implementation guide for acquiring bank macro/policy events without cost

---

## 📋 Table of Contents

1. [Strategic Overview](#strategic-overview)
2. [Strategy 1: Email-First Approach](#strategy-1-email-first-approach)
3. [Strategy 2: Calendar Feed Discovery](#strategy-2-calendar-feed-discovery)
4. [Strategy 3: Smart Gmail Query Optimization](#strategy-3-smart-gmail-query-optimization)
5. [Strategy 4: Search Engine Discovery](#strategy-4-search-engine-discovery)
6. [Strategy 5: Webinar Platform Monitoring](#strategy-5-webinar-platform-monitoring)
7. [Strategy 6: Investor Relations Calendar Mining](#strategy-6-investor-relations-calendar-mining)
8. [Strategy 7: Participant Feedback Loop](#strategy-7-participant-feedback-loop)
9. [Strategy 8: Automated RSS Discovery](#strategy-8-automated-rss-discovery)
10. [Strategy 9: Stealth Mode for Blocked Sources](#strategy-9-stealth-mode-for-blocked-sources)
11. [Strategy 10: Third-Party Event Platforms](#strategy-10-third-party-event-platforms)
12. [Implementation Roadmap](#implementation-roadmap)
13. [Success Metrics & Validation](#success-metrics--validation)
14. [Troubleshooting Guide](#troubleshooting-guide)
15. [Maintenance & Continuous Improvement](#maintenance--continuous-improvement)

---

## Strategic Overview

### Core Problem Statement

**Current Situation**:
- ✅ Academic sources work well (Harvard, MIT, Oxford, etc.)
- ✅ Association sources work well (ICMA, IIF, AFME, etc.)
- ✅ Think tank sources work well (Brookings, CSIS, CFR, etc.)
- ❌ Bank sources don't work (JPMorgan, Goldman Sachs, Morgan Stanley, etc.)
- ❌ Investor/asset manager sources limited

**Why Banks Are Different**:
1. **Banks don't publish events prominently** - Events are for clients, often semi-private
2. **Banks use third-party platforms** - Events hosted on Zoom, ON24, GoToWebinar
3. **Banks promote via email** - Newsletters, research distribution, client alerts
4. **Banks hide in IR sections** - Investor Relations calendars under obscure URLs
5. **Banks participate, don't host** - They speak at association/think tank events

### Strategic Shift

**Old Approach** (doesn't work):
```
Try to scrape bank websites → Get blocked or find nothing
```

**New Approach** (this guide):
```
1. Email-First: Subscribe to bank newsletters → Events delivered to you
2. Platform-First: Scrape where banks HOST events (ON24, Zoom)
3. Aggregator-First: Scrape where banks are LISTED (FT Events, Bloomberg Live)
4. Discovery-First: Use search engines to FIND hidden event pages
5. Feed-First: Discover hidden RSS/iCal feeds that bypass web scraping
```

### Success Criteria

**Target**: Increase bank/investor event coverage by 300-500% in 4 weeks

**Metrics**:
- Bank newsletter sources: 0 → 20-30
- Hidden RSS/iCal feeds: 5 → 15-20
- Third-party platform sources: 0 → 3-5
- Unblocked difficult sources: 0 → 3-5
- **Total new sources**: 40-60+
- **Event volume increase**: 3-5x current

---

## Strategy 1: Email-First Approach

### 🎯 Overview

**Core Concept**: Banks send event invitations via email. Instead of scraping websites, subscribe to newsletters and parse emails automatically.

**Why This Works**:
- Banks WANT you to register for events (lead generation)
- Newsletter signup is free and public
- Emails contain structured data (dates, links, descriptions)
- Gmail API integration already exists in your system

**Expected Outcome**: 20-30 new bank sources within 2 weeks

---

### Phase 1A: Newsletter Discovery Automation

**Goal**: Find all newsletter signup pages for target banks.

#### Step 1.1: Create Newsletter Discovery Script

**File**: Create `backend/scripts/discover_newsletter_signup_pages.py`

```python
"""
Automated newsletter signup page discovery for banks.

Systematically finds newsletter subscription pages across bank websites.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
from pathlib import Path
import time
import re


# Target banks for macro/policy events
TARGET_BANKS = [
    # US Banks
    ("JPMorgan Chase", "https://www.jpmorgan.com", "Investment Bank"),
    ("Goldman Sachs", "https://www.goldmansachs.com", "Investment Bank"),
    ("Morgan Stanley", "https://www.morganstanley.com", "Investment Bank"),
    ("Bank of America", "https://www.bankofamerica.com", "Investment Bank"),
    ("Citigroup", "https://www.citigroup.com", "Investment Bank"),
    ("Wells Fargo", "https://www.wellsfargo.com", "Investment Bank"),
    
    # European Banks
    ("Barclays", "https://www.barclays.com", "Investment Bank"),
    ("Deutsche Bank", "https://www.db.com", "Investment Bank"),
    ("UBS", "https://www.ubs.com", "Investment Bank"),
    ("Credit Suisse", "https://www.credit-suisse.com", "Investment Bank"),
    ("BNP Paribas", "https://www.bnpparibas.com", "Investment Bank"),
    ("Société Générale", "https://www.societegenerale.com", "Investment Bank"),
    ("HSBC", "https://www.hsbc.com", "Investment Bank"),
    ("Standard Chartered", "https://www.sc.com", "Investment Bank"),
    
    # Asset Managers
    ("BlackRock", "https://www.blackrock.com", "Asset Manager"),
    ("Vanguard", "https://www.vanguard.com", "Asset Manager"),
    ("Fidelity", "https://www.fidelity.com", "Asset Manager"),
    ("State Street", "https://www.statestreet.com", "Asset Manager"),
    ("PIMCO", "https://www.pimco.com", "Asset Manager"),
    ("T. Rowe Price", "https://www.troweprice.com", "Asset Manager"),
    
    # Hedge Funds / Alternative
    ("Bridgewater", "https://www.bridgewater.com", "Hedge Fund"),
    ("AQR", "https://www.aqr.com", "Hedge Fund"),
    ("Two Sigma", "https://www.twosigma.com", "Hedge Fund"),
]


# Common newsletter signup URL patterns
SIGNUP_PATTERNS = [
    # Research/Insights subscriptions
    "/insights/subscribe",
    "/research/subscribe",
    "/research/email-signup",
    "/insights/email-signup",
    "/insights/newsletter",
    "/research/newsletter",
    
    # General newsletter
    "/newsletter-signup",
    "/newsletter",
    "/subscribe",
    "/email-signup",
    "/email-alerts",
    "/email-preferences",
    "/subscription-center",
    "/subscriptions",
    
    # Investor Relations
    "/investor-relations/email-alerts",
    "/investor-relations/subscribe",
    "/ir/email-alerts",
    
    # Thought leadership
    "/thought-leadership/subscribe",
    "/perspectives/subscribe",
    "/outlook/subscribe",
    
    # Specific content types
    "/economic-research/subscribe",
    "/market-insights/subscribe",
    "/macro-research/subscribe"
]


def check_url_exists(url, timeout=10):
    """Check if URL returns 200 status."""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        return response.status_code == 200
    except:
        return False


def find_signup_links_in_html(html, base_url):
    """
    Parse HTML to find newsletter signup links.
    
    Args:
        html: HTML content
        base_url: Base URL for resolving relative links
    
    Returns:
        List of (link_text, link_url) tuples
    """
    soup = BeautifulSoup(html, 'html.parser')
    signup_links = []
    
    # Keywords that indicate newsletter signup
    signup_keywords = [
        'subscribe', 'newsletter', 'email alert', 'email signup',
        'sign up', 'stay informed', 'get updates', 'email updates',
        'research alerts', 'insights delivery'
    ]
    
    for link in soup.find_all('a', href=True):
        link_text = link.get_text().lower().strip()
        link_url = link.get('href', '')
        
        # Check if link text contains signup keywords
        if any(keyword in link_text for keyword in signup_keywords):
            full_url = urljoin(base_url, link_url)
            signup_links.append((link.get_text().strip(), full_url))
    
    return signup_links


def discover_newsletter_signups_for_bank(bank_name, base_url):
    """
    Find all newsletter signup pages for a specific bank.
    
    Args:
        bank_name: Bank name
        base_url: Bank's base URL
    
    Returns:
        Dict with findings
    """
    findings = {
        'bank_name': bank_name,
        'base_url': base_url,
        'pattern_matches': [],
        'html_discoveries': [],
        'recommendations': []
    }
    
    print(f"\n{'='*60}")
    print(f"Discovering newsletter signups for: {bank_name}")
    print(f"Base URL: {base_url}")
    print(f"{'='*60}\n")
    
    # Method 1: Try common URL patterns
    print("Method 1: Testing common URL patterns...")
    for pattern in SIGNUP_PATTERNS:
        test_url = base_url + pattern
        
        if check_url_exists(test_url):
            print(f"  ✅ FOUND: {test_url}")
            findings['pattern_matches'].append(test_url)
        else:
            # Try with different path variants
            # Some banks use /en/ prefix or /us/ prefix
            variants = [
                base_url + '/en' + pattern,
                base_url + '/us' + pattern,
                base_url + '/global' + pattern
            ]
            
            for variant_url in variants:
                if check_url_exists(variant_url):
                    print(f"  ✅ FOUND (variant): {variant_url}")
                    findings['pattern_matches'].append(variant_url)
                    break
        
        time.sleep(0.5)  # Be respectful
    
    # Method 2: Parse homepage for signup links
    print("\nMethod 2: Parsing homepage for signup links...")
    try:
        response = requests.get(base_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            signup_links = find_signup_links_in_html(response.text, base_url)
            
            if signup_links:
                print(f"  Found {len(signup_links)} potential signup links:")
                for link_text, link_url in signup_links:
                    print(f"    • {link_text}: {link_url}")
                    findings['html_discoveries'].append({
                        'text': link_text,
                        'url': link_url
                    })
            else:
                print("  No signup links found in homepage")
    except Exception as e:
        print(f"  ❌ Error parsing homepage: {e}")
    
    # Method 3: Check common subdomains
    print("\nMethod 3: Checking common subdomains...")
    subdomain_patterns = [
        "insights", "research", "perspectives", "email", "subscribe"
    ]
    
    for subdomain in subdomain_patterns:
        # Extract domain from base_url
        parsed = urlparse(base_url)
        domain_parts = parsed.netloc.split('.')
        
        if len(domain_parts) >= 2:
            # Try subdomain.bank.com
            test_url = f"https://{subdomain}.{'.'.join(domain_parts[-2:])}"
            
            if check_url_exists(test_url):
                print(f"  ✅ FOUND subdomain: {test_url}")
                findings['pattern_matches'].append(test_url)
                
                # Also check subdomain/subscribe
                subscribe_url = f"{test_url}/subscribe"
                if check_url_exists(subscribe_url):
                    print(f"  ✅ FOUND: {subscribe_url}")
                    findings['pattern_matches'].append(subscribe_url)
        
        time.sleep(0.5)
    
    # Generate recommendations
    if findings['pattern_matches'] or findings['html_discoveries']:
        findings['recommendations'].append(f"Subscribe to newsletters from {bank_name}")
        findings['recommendations'].append("Create email parsing template for this bank")
    else:
        findings['recommendations'].append(f"Manual search needed for {bank_name}")
        findings['recommendations'].append(f"Check: {base_url}/investor-relations")
        findings['recommendations'].append(f"Check: Google search for '{bank_name} newsletter signup'")
    
    return findings


def save_findings_to_file(all_findings, output_file='newsletter_discovery_results.json'):
    """Save discovery results to JSON file."""
    output_path = Path(__file__).parent.parent / output_file
    
    with open(output_path, 'w') as f:
        json.dump(all_findings, f, indent=2)
    
    print(f"\n✅ Results saved to: {output_path}")


def generate_markdown_report(all_findings, output_file='newsletter_discovery_report.md'):
    """Generate human-readable Markdown report."""
    output_path = Path(__file__).parent.parent / output_file
    
    with open(output_path, 'w') as f:
        f.write("# Newsletter Signup Discovery Report\n\n")
        f.write(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Banks Analyzed**: {len(all_findings)}\n\n")
        
        # Summary statistics
        total_found = sum(len(r['pattern_matches']) + len(r['html_discoveries']) for r in all_findings)
        banks_with_findings = sum(1 for r in all_findings if r['pattern_matches'] or r['html_discoveries'])
        
        f.write(f"**Total URLs Found**: {total_found}\n")
        f.write(f"**Banks with Findings**: {banks_with_findings}/{len(all_findings)}\n\n")
        f.write("---\n\n")
        
        # Detailed findings per bank
        for finding in all_findings:
            f.write(f"## {finding['bank_name']}\n\n")
            f.write(f"**Base URL**: {finding['base_url']}\n\n")
            
            if finding['pattern_matches']:
                f.write("### ✅ Pattern Matches\n\n")
                for url in finding['pattern_matches']:
                    f.write(f"- {url}\n")
                f.write("\n")
            
            if finding['html_discoveries']:
                f.write("### 📝 Homepage Discoveries\n\n")
                for discovery in finding['html_discoveries']:
                    f.write(f"- **{discovery['text']}**: {discovery['url']}\n")
                f.write("\n")
            
            if finding['recommendations']:
                f.write("### 💡 Recommendations\n\n")
                for rec in finding['recommendations']:
                    f.write(f"- {rec}\n")
                f.write("\n")
            
            f.write("---\n\n")
    
    print(f"✅ Markdown report saved to: {output_path}")


def main():
    """Run discovery for all target banks."""
    all_findings = []
    
    print("\n" + "="*60)
    print("NEWSLETTER SIGNUP DISCOVERY TOOL")
    print("="*60)
    print(f"\nAnalyzing {len(TARGET_BANKS)} banks...")
    
    for bank_name, base_url, bank_type in TARGET_BANKS:
        findings = discover_newsletter_signups_for_bank(bank_name, base_url)
        all_findings.append(findings)
        
        # Brief pause between banks
        time.sleep(2)
    
    # Save results
    save_findings_to_file(all_findings)
    generate_markdown_report(all_findings)
    
    # Print summary
    print("\n" + "="*60)
    print("DISCOVERY SUMMARY")
    print("="*60)
    
    banks_with_findings = [f for f in all_findings if f['pattern_matches'] or f['html_discoveries']]
    
    print(f"\n✅ Banks with findings: {len(banks_with_findings)}/{len(all_findings)}")
    print("\nTop discoveries:")
    
    for finding in banks_with_findings[:10]:
        total_urls = len(finding['pattern_matches']) + len(finding['html_discoveries'])
        print(f"  • {finding['bank_name']}: {total_urls} URLs found")
    
    print("\n📄 See full report in: newsletter_discovery_report.md")


if __name__ == '__main__':
    main()
```

**How to Run**:
```bash
cd backend
python scripts/discover_newsletter_signup_pages.py
```

**Expected Output**:
- `newsletter_discovery_results.json` - Machine-readable results
- `newsletter_discovery_report.md` - Human-readable report
- Console output with progress and summary

**Time Required**: 15-20 minutes for script to complete

---

#### Step 1.2: Manual Newsletter Subscription Phase

**Goal**: Subscribe to discovered newsletters (one-time manual effort).

**Process**:

1. **Review Discovery Report**:
   ```bash
   cat backend/newsletter_discovery_report.md
   ```

2. **Create Subscription Tracking Spreadsheet**:
   ```
   Bank Name | Signup URL | Subscribed (Y/N) | Email Used | Date Subscribed | Notes
   ```

3. **Subscription Process** (per bank):
   - Open signup URL in browser
   - Use dedicated email: `marketradar.events@gmail.com` (create if needed)
   - ✅ Check boxes for: "Research", "Economic Insights", "Webinars", "Events"
   - ❌ Uncheck: "Marketing", "Product Updates", "Investor Relations" (unless IR includes macro events)
   - Complete signup form
   - Confirm subscription via confirmation email
   - Update tracking spreadsheet

4. **Email Organization**:
   - Create Gmail labels: "Events/JPMorgan", "Events/Goldman", etc.
   - Set up filters to auto-label by sender domain
   - Example filter:
     ```
     From: *@jpmorgan.com
     Has the words: (webinar OR event OR conference OR register)
     Apply label: Events/JPMorgan
     ```

**Time Required**: 
- Setup: 30 minutes (email creation, spreadsheet setup)
- Subscriptions: 5-7 minutes per bank × 30 banks = **2.5-3.5 hours one-time**
- Gmail filter setup: 30 minutes

**Expected Outcome**: Within 1 week, you'll start receiving 10-20 event emails per week from banks.

---

### Phase 1B: Bank-Specific Email Parsing Templates

**Goal**: Create parsing templates for each bank's email format.

#### Step 1.3: Create Email Template System

**File**: Create `backend/utils/bank_email_templates.py`

```python
"""
Bank-specific email parsing templates.

Each bank has unique newsletter format. This module provides
optimized extraction patterns per bank.
"""
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup


# Bank-specific parsing templates
BANK_EMAIL_TEMPLATES = {
    "jpmorgan.com": {
        "bank_name": "JPMorgan Chase",
        
        # Section markers (text that indicates start of event section)
        "event_section_markers": [
            "upcoming events",
            "webinar series",
            "join us for",
            "register now",
            "save the date",
            "upcoming webinars",
            "research events"
        ],
        
        # Date extraction patterns
        "date_patterns": [
            r"(\w+ \d{1,2},? \d{4})",           # January 15, 2026
            r"(\d{1,2}/\d{1,2}/\d{4})",         # 01/15/2026
            r"(\d{4}-\d{2}-\d{2})",             # 2026-01-15
            r"(\w+ \d{1,2}(?:st|nd|rd|th),? \d{4})"  # January 15th, 2026
        ],
        
        # Link extraction patterns (specific to JPM email structure)
        "link_patterns": [
            r'href="(https://[^"]*jpmorgan[^"]*(?:event|webinar|registration)[^"]*)"',
            r'href="(https://[^"]*(?:register|rsvp|join)[^"]*)"',
            r'href="(https://event\.on24\.com/[^"]*)"',  # ON24 platform
            r'href="(https://[^"]*zoom\.us/webinar/[^"]*)"'  # Zoom
        ],
        
        # Rejection patterns (avoid non-macro content)
        "reject_patterns": [
            "earnings call",
            "quarterly results", 
            "investor update",
            "quarterly earnings",
            "q1 results", "q2 results", "q3 results", "q4 results",
            "annual report",
            "shareholder meeting"
        ],
        
        # Acceptance patterns (ensure macro/policy focus)
        "accept_patterns": [
            "economic outlook",
            "interest rate",
            "monetary policy",
            "fiscal policy",
            "macro",
            "market outlook",
            "strategy",
            "fixed income",
            "rates",
            "credit",
            "global markets"
        ],
        
        # Title extraction (how to find event title in email)
        "title_selectors": [
            "h2", "h3", "strong", "b",
            ".event-title", ".webinar-title"
        ]
    },
    
    "gs.com": {
        "bank_name": "Goldman Sachs",
        "event_section_markers": [
            "upcoming webcasts",
            "research events",
            "economic outlook",
            "goldman sachs presents",
            "join our experts"
        ],
        "date_patterns": [
            r"(\w+ \d{1,2},? \d{4})",
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ],
        "link_patterns": [
            r'href="(https://[^"]*goldmansachs[^"]*event[^"]*)"',
            r'href="(https://[^"]*gs\.com[^"]*webinar[^"]*)"',
            r'href="(https://event\.on24\.com/[^"]*goldman[^"]*)"'
        ],
        "reject_patterns": [
            "earnings", "quarterly results", "investor",
            "stock price", "financial results"
        ],
        "accept_patterns": [
            "macro", "economic", "outlook", "policy",
            "rates", "fixed income", "markets"
        ],
        "title_selectors": ["h2", "h3", "strong"]
    },
    
    "morganstanley.com": {
        "bank_name": "Morgan Stanley",
        "event_section_markers": [
            "upcoming events",
            "webinars",
            "thought leadership events",
            "research webinars"
        ],
        "date_patterns": [
            r"(\w+ \d{1,2},? \d{4})",
            r"(\d{1,2}/\d{1,2}/\d{4})"
        ],
        "link_patterns": [
            r'href="(https://[^"]*morganstanley[^"]*event[^"]*)"',
            r'href="(https://[^"]*registration[^"]*)"'
        ],
        "reject_patterns": ["earnings", "quarterly", "investor relations"],
        "accept_patterns": ["economic", "macro", "outlook", "strategy", "policy"],
        "title_selectors": ["h2", "h3", "strong"]
    },
    
    # Add more banks as you discover their formats
    "bankofamerica.com": {
        "bank_name": "Bank of America",
        "event_section_markers": ["upcoming events", "webinar", "register"],
        "date_patterns": [r"(\w+ \d{1,2},? \d{4})"],
        "link_patterns": [r'href="(https://[^"]*event[^"]*)"'],
        "reject_patterns": ["earnings", "investor"],
        "accept_patterns": ["economic", "macro", "policy"],
        "title_selectors": ["h2", "h3"]
    },
    
    "barclays.com": {
        "bank_name": "Barclays",
        "event_section_markers": ["upcoming events", "research webinar"],
        "date_patterns": [r"(\d{1,2} \w+ \d{4})"],  # 15 January 2026
        "link_patterns": [r'href="(https://[^"]*barclays[^"]*event[^"]*)"'],
        "reject_patterns": ["earnings", "results announcement"],
        "accept_patterns": ["economic", "macro", "outlook"],
        "title_selectors": ["h2", "h3"]
    },
    
    "ubs.com": {
        "bank_name": "UBS",
        "event_section_markers": ["upcoming events", "webinar", "conference"],
        "date_patterns": [r"(\d{1,2}\.\d{1,2}\.\d{4})"],  # Swiss format: 15.01.2026
        "link_patterns": [r'href="(https://[^"]*ubs[^"]*event[^"]*)"'],
        "reject_patterns": ["earnings", "quarterly"],
        "accept_patterns": ["economic", "macro", "investment outlook"],
        "title_selectors": ["h2", "h3"]
    }
}


def get_template_for_sender(sender_email: str) -> Optional[Dict]:
    """
    Get parsing template for a sender email domain.
    
    Args:
        sender_email: Email address (e.g., "alerts@jpmorgan.com")
    
    Returns:
        Template dict or None
    """
    if not sender_email or '@' not in sender_email:
        return None
    
    sender_domain = sender_email.split('@')[-1].lower()
    
    # Direct match
    if sender_domain in BANK_EMAIL_TEMPLATES:
        return BANK_EMAIL_TEMPLATES[sender_domain]
    
    # Partial match (e.g., "mail.jpmorgan.com" matches "jpmorgan.com")
    for template_domain, template in BANK_EMAIL_TEMPLATES.items():
        if template_domain in sender_domain:
            return template
    
    return None


def extract_sections_containing(text: str, marker: str, context_lines: int = 10) -> List[str]:
    """
    Extract text sections containing a specific marker.
    
    Args:
        text: Email body text
        marker: Section marker (e.g., "upcoming events")
        context_lines: Number of lines to include before/after marker
    
    Returns:
        List of text sections
    """
    lines = text.split('\n')
    sections = []
    
    for i, line in enumerate(lines):
        if marker.lower() in line.lower():
            # Extract context around this line
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            section = '\n'.join(lines[start:end])
            sections.append(section)
    
    return sections


def extract_title_from_section(section: str, html_section: Optional[str] = None) -> Optional[str]:
    """
    Extract event title from a text section.
    
    Tries multiple strategies:
    1. Lines in ALL CAPS or Title Case
    2. Lines with 20-100 characters
    3. Lines before date mentions
    4. HTML headers if HTML provided
    """
    if html_section:
        # Try HTML parsing first
        soup = BeautifulSoup(html_section, 'html.parser')
        for selector in ['h2', 'h3', 'h4', 'strong', 'b']:
            element = soup.find(selector)
            if element:
                title = element.get_text().strip()
                if 10 < len(title) < 200:
                    return title
    
    # Fallback to text parsing
    lines = [line.strip() for line in section.split('\n') if line.strip()]
    
    for line in lines:
        # Skip very short or very long lines
        if len(line) < 10 or len(line) > 200:
            continue
        
        # Look for title-like patterns
        # Usually before date mentions
        if re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', line):
            # This line has a date, might be metadata
            continue
        
        # Check if mostly capitalized (title case)
        words = line.split()
        if not words:
            continue
            
        capitalized_words = sum(1 for word in words if word and word[0].isupper())
        
        if capitalized_words / len(words) > 0.5:
            # Likely a title
            return line
    
    return None


def parse_bank_email_with_template(email_body: str, sender_domain: str, 
                                   email_html: Optional[str] = None) -> List[Dict]:
    """
    Parse bank email using bank-specific template.
    
    Args:
        email_body: Plain text email body
        sender_domain: Sender's domain (e.g., "jpmorgan.com")
        email_html: HTML version of email (if available)
    
    Returns:
        List of extracted event dicts
    """
    template = get_template_for_sender(f"x@{sender_domain}")
    
    if not template:
        return []  # No template, use generic parsing
    
    events = []
    
    # Combine plain text and HTML for analysis
    combined_text = email_body
    if email_html:
        soup = BeautifulSoup(email_html, 'html.parser')
        combined_text += "\n" + soup.get_text()
    
    # Find event sections using markers
    all_sections = []
    for marker in template["event_section_markers"]:
        sections = extract_sections_containing(combined_text, marker, context_lines=15)
        all_sections.extend(sections)
    
    # If no sections found, treat whole email as one section
    if not all_sections:
        all_sections = [combined_text]
    
    # Process each section
    for section in all_sections:
        # Check rejection patterns first (skip earnings/IR content)
        if any(reject.lower() in section.lower() for reject in template.get("reject_patterns", [])):
            continue
        
        # Check acceptance patterns (ensure macro/policy focus)
        has_accept_pattern = False
        for accept in template.get("accept_patterns", []):
            if accept.lower() in section.lower():
                has_accept_pattern = True
                break
        
        if not has_accept_pattern and template.get("accept_patterns"):
            continue  # Skip if no macro keywords found
        
        # Extract event details
        event = {
            'source_type': 'newsletter',
            'source_domain': sender_domain,
            'firm_name': template['bank_name']
        }
        
        # Extract title
        html_section = None
        if email_html:
            html_section = email_html
        
        title = extract_title_from_section(section, html_section)
        if title:
            event['event_name'] = title
        else:
            continue  # No title found, skip this section
        
        # Extract date
        for pattern in template["date_patterns"]:
            date_match = re.search(pattern, section)
            if date_match:
                event['date_text'] = date_match.group(1)
                break
        
        # Extract link
        link_found = False
        for pattern in template["link_patterns"]:
            link_match = re.search(pattern, section if not email_html else email_html)
            if link_match:
                event['link'] = link_match.group(1)
                link_found = True
                break
        
        if not link_found:
            # Try generic link extraction as fallback
            link_match = re.search(r'href="(https://[^"]+)"', section if not email_html else email_html)
            if link_match:
                event['link'] = link_match.group(1)
        
        # Only include if we have title and link (minimum requirements)
        if event.get('event_name') and event.get('link'):
            events.append(event)
    
    return events


def parse_generic_email_for_events(email_body: str, email_html: Optional[str] = None) -> List[Dict]:
    """
    Generic email parsing when no template exists.
    Uses conservative heuristics.
    """
    events = []
    
    # Look for common event indicators
    event_indicators = [
        "register now", "registration", "join us", "save the date",
        "upcoming webinar", "upcoming event", "rsvp"
    ]
    
    text_to_search = email_body
    if email_html:
        soup = BeautifulSoup(email_html, 'html.parser')
        text_to_search += "\n" + soup.get_text()
    
    # Simple heuristic: find sections with event indicators
    for indicator in event_indicators:
        if indicator.lower() in text_to_search.lower():
            # Extract section around indicator
            sections = extract_sections_containing(text_to_search, indicator)
            
            for section in sections:
                # Extract basic info
                event = {'source_type': 'newsletter_generic'}
                
                # Try to find title (line before or after indicator)
                event['event_name'] = extract_title_from_section(section)
                
                # Try to find link
                link_match = re.search(r'https://[^\s<>"]+', section)
                if link_match:
                    event['link'] = link_match.group(0)
                
                # Try to find date
                date_match = re.search(r'\w+ \d{1,2},? \d{4}', section)
                if date_match:
                    event['date_text'] = date_match.group(0)
                
                if event.get('event_name') and event.get('link'):
                    events.append(event)
                    break  # One event per indicator to avoid duplicates
    
    return events


# Export main function
def parse_bank_newsletter(email_body: str, sender_email: str, 
                         email_html: Optional[str] = None) -> List[Dict]:
    """
    Main entry point for parsing bank newsletters.
    
    Args:
        email_body: Plain text email body
        sender_email: Sender email address
        email_html: HTML version of email (optional)
    
    Returns:
        List of extracted event dicts
    """
    sender_domain = sender_email.split('@')[-1].lower() if '@' in sender_email else ''
    
    # Try template-based parsing
    events = parse_bank_email_with_template(email_body, sender_domain, email_html)
    
    if events:
        return events
    
    # Fallback to generic parsing
    return parse_generic_email_for_events(email_body, email_html)
```

---

#### Step 1.4: Integrate Templates into Email Adapter

**File**: Modify `backend/adapters/email_event.py`

**Enhancement**:
```python
def extract_events_from_email(email_body: str, sender_email: str, 
                              email_subject: str = '', email_html: str = None) -> List[Dict]:
    """
    Extract events from email using template-based parsing.
    
    Args:
        email_body: Plain text email body
        sender_email: Sender email address
        email_subject: Email subject line
        email_html: HTML version of email (if available)
    
    Returns:
        List of event dicts
    """
    events = []
    
    # Try bank-specific template first
    try:
        from utils.bank_email_templates import parse_bank_newsletter
        
        template_events = parse_bank_newsletter(email_body, sender_email, email_html)
        
        if template_events:
            print(f"  ✅ Extracted {len(template_events)} events using bank template")
            events.extend(template_events)
            return events  # Return early if template worked
    except ImportError:
        print("  ⚠️  Bank email templates not available, using generic parsing")
    except Exception as e:
        print(f"  ⚠️  Template parsing failed: {e}, falling back to generic")
    
    # Fallback to existing generic parsing
    generic_events = extract_events_generic(email_body, email_subject, email_html)
    events.extend(generic_events)
    
    return events


def extract_events_generic(email_body, email_subject, email_html=None):
    """Your existing generic extraction logic."""
    # Keep existing code as fallback
    pass
```

---

### Phase 1C: Smart Gmail Query System

#### Step 1.5: Create Smart Gmail Query Builder

**File**: Create `backend/utils/smart_gmail_queries.py`

```python
"""
Smart Gmail query builder for bank event discovery.

Builds optimized Gmail queries to find bank event emails while
filtering out earnings/investor relations content.
"""
from typing import List


# Event indicators (broad)
EVENT_KEYWORDS = [
    "webinar",
    "register",
    "registration", 
    "join us",
    "upcoming event",
    "save the date",
    "rsvp",
    "conference",
    "panel discussion",
    "roundtable",
    "live event",
    "virtual event",
    "online event",
    "seminar",
    "workshop",
    "symposium"
]


# Macro/policy keywords (ensure relevance)
MACRO_KEYWORDS = [
    "economic outlook",
    "interest rates",
    "interest rate",
    "monetary policy",
    "fiscal policy",
    "market outlook",
    "macro trends",
    "macro view",
    "central bank",
    "fed policy",
    "inflation",
    "fixed income",
    "rates strategy",
    "macro strategy",
    "credit strategy",
    "economic forecast",
    "market forecast",
    "policy outlook",
    "geopolitical",
    "sovereign risk"
]


# Exclusion keywords (avoid earnings/IR)
EXCLUDE_KEYWORDS = [
    "earnings",
    "quarterly results",
    "investor relations",
    "stock performance",
    "shareholder meeting",
    "annual report",
    "10-K", "10-Q",
    "dividend",
    "stock split"
]


# Financial institution domains
FINANCIAL_DOMAINS = [
    # US Investment Banks
    "jpmorgan.com", "jpmchase.com",
    "gs.com", "goldmansachs.com",
    "morganstanley.com", "ms.com",
    "bankofamerica.com", "bofa.com", "ml.com",
    "citi.com", "citigroup.com",
    "wellsfargo.com", "wf.com",
    
    # European Investment Banks
    "barclays.com", "barclays.co.uk",
    "db.com", "deutsche-bank.com",
    "ubs.com",
    "credit-suisse.com",
    "bnpparibas.com",
    "societegenerale.com", "sgcib.com",
    "hsbc.com", "hsbc.co.uk",
    "sc.com", "standardchartered.com",
    "ing.com",
    "commerzbank.com",
    "natixis.com",
    
    # Asset Managers
    "blackrock.com",
    "vanguard.com",
    "fidelity.com",
    "statestreet.com",
    "pimco.com",
    "troweprice.com",
    "invesco.com",
    "franklintempleton.com",
    "wellington.com",
    "capital.com",
    "mfs.com",
    
    # Hedge Funds / Alternative
    "bridgewater.com",
    "aqr.com",
    "twosigma.com",
    "citadel.com",
    "deshaw.com",
    "renaissancetechnologies.com",
    "millennium.com"
]


def build_basic_event_query() -> str:
    """
    Build basic Gmail query for event emails.
    
    Returns:
        Gmail search query string
    """
    # Event keywords (at least one must be present)
    event_part = "(" + " OR ".join(EVENT_KEYWORDS) + ")"
    
    # Macro keywords (at least one must be present)
    macro_part = "(" + " OR ".join(MACRO_KEYWORDS) + ")"
    
    # Exclude keywords (none should be present)
    exclude_part = " ".join(f"-{word}" for word in EXCLUDE_KEYWORDS)
    
    query = f"{event_part} AND {macro_part} {exclude_part}"
    
    return query


def build_bank_sender_filter() -> str:
    """
    Build sender filter for financial institutions.
    
    Returns:
        Gmail sender filter string
    """
    sender_part = "(" + " OR ".join(f"from:*@{domain}" for domain in FINANCIAL_DOMAINS) + ")"
    return sender_part


def build_full_bank_event_query() -> str:
    """
    Build comprehensive Gmail query for bank events.
    
    Returns:
        Complete Gmail search query
    """
    event_query = build_basic_event_query()
    sender_filter = build_bank_sender_filter()
    
    full_query = f"{event_query} AND {sender_filter}"
    
    return full_query


def build_query_with_date_filter(days_back: int = 7) -> str:
    """
    Build query with date filter.
    
    Args:
        days_back: How many days back to search
    
    Returns:
        Gmail query with date filter
    """
    base_query = build_full_bank_event_query()
    
    # Gmail date syntax: after:YYYY/MM/DD
    from datetime import datetime, timedelta
    date_threshold = datetime.now() - timedelta(days=days_back)
    date_str = date_threshold.strftime('%Y/%m/%d')
    
    query_with_date = f"{base_query} after:{date_str}"
    
    return query_with_date


def print_query_explanation(query: str):
    """Print human-readable explanation of query."""
    print("\n" + "="*60)
    print("GMAIL QUERY EXPLANATION")
    print("="*60)
    print(f"\nQuery: {query}\n")
    print("This query will find emails that:")
    print("  1. ✅ Have event keywords (webinar, conference, etc.)")
    print("  2. ✅ Have macro keywords (economic outlook, rates, etc.)")
    print("  3. ❌ Don't have exclusion keywords (earnings, quarterly results)")
    print("  4. ✅ Come from financial institution domains")
    print("\n" + "="*60 + "\n")


# CLI interface
if __name__ == '__main__':
    import sys
    
    if '--explain' in sys.argv:
        query = build_full_bank_event_query()
        print_query_explanation(query)
    elif '--with-date' in sys.argv:
        try:
            days_idx = sys.argv.index('--with-date')
            days = int(sys.argv[days_idx + 1]) if len(sys.argv) > days_idx + 1 else 7
        except:
            days = 7
        query = build_query_with_date_filter(days)
        print(query)
    else:
        query = build_full_bank_event_query()
        print(query)
```

**How to Use**:
```bash
# Generate query
cd backend
python utils/smart_gmail_queries.py

# Explain query
python utils/smart_gmail_queries.py --explain

# Generate with date filter
python utils/smart_gmail_queries.py --with-date 30
```

---

#### Step 1.6: Update Gmail Ingestion to Use Smart Queries

**File**: Modify `backend/scripts/ingest_gmail.py`

```python
# At the top, import the query builder
from utils.smart_gmail_queries import build_query_with_date_filter

# Replace your current query building logic with:
def build_query(days_back=7):
    """Build optimized Gmail query."""
    return build_query_with_date_filter(days_back)

# Then use in main():
def main():
    args = parse_args()
    days = args.days or 7
    
    query = build_query(days)
    print(f"Using query: {query}")
    
    # ... rest of Gmail ingestion logic ...
```

---

### Strategy 1 Summary & Checklist

**Implementation Steps**:

- [ ] **Step 1.1**: Create `discover_newsletter_signup_pages.py` script
- [ ] **Step 1.2**: Run discovery script to find signup URLs
- [ ] **Step 1.3**: Manual subscription to 20-30 bank newsletters (2-3 hours)
- [ ] **Step 1.4**: Create `bank_email_templates.py` with parsing patterns
- [ ] **Step 1.5**: Integrate templates into `email_event.py` adapter
- [ ] **Step 1.6**: Create `smart_gmail_queries.py` for better Gmail filtering
- [ ] **Step 1.7**: Update Gmail ingestion to use smart queries
- [ ] **Step 1.8**: Set up scheduled email checking
- [ ] **Step 1.9**: Add quality tracking for bank newsletters

**Expected Timeline**:
- Week 1: Scripts creation and discovery (Steps 1.1-1.2) - 1-2 days
- Week 1-2: Manual subscriptions (Step 1.3) - 3 hours spread over 1 week
- Week 2: Template creation and integration (Steps 1.4-1.7) - 2-3 days
- Week 2: Automation setup (Steps 1.8-1.9) - 1 day

**Expected Outcome**:
- 20-30 bank newsletter sources added
- 10-30 events per week from email ingestion
- Automated daily checking
- Quality tracking to optimize over time

---

## Strategy 2: Calendar Feed Discovery

### 🎯 Overview

**Core Concept**: Banks provide iCal/ICS calendar feeds for clients to import into Outlook/Google Calendar. These are often public but not advertised.

**Why This Works**:
- Calendar feeds bypass web scraping entirely
- Structured data (dates, locations, descriptions)
- Less protected than HTML pages
- Update automatically (subscriptions)
- Zero-cost, fully automated

**Expected Outcome**: 10-15 new iCal/ICS sources

---

### Phase 2A: iCal Feed Discovery

#### Step 2.1: Create iCal Discovery Script

**File**: Create `backend/scripts/discover_ics_calendars.py`

```python
"""
Automated iCal/ICS calendar feed discovery.

Finds hidden calendar feeds that bypass web scraping.
"""
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
from pathlib import Path
import time
import re


# iCal URL patterns to test
ICAL_PATTERNS = [
    "/events.ics",
    "/calendar.ics",
    "/events/feed.ics",
    "/webcal/events",
    "/ical/events",
    "/calendar/export",
    "/calendar/feed",
    "/feed.ics",
    
    # Outlook integration patterns
    "/outlook-calendar",
    "/subscribe-calendar",
    "/calendar/subscribe",
    
    # Common calendar tools
    "/events/ical",
    "/icalendar",
    "/calendar.ical",
    
    # Date-specific (sometimes banks organize by year)
    "/events/2026.ics",
    "/calendar/2026.ics"
]


def is_valid_ical_feed(content: str) -> bool:
    """Check if content is a valid iCal feed."""
    if not content:
        return False
    
    # Must contain VCALENDAR
    if 'BEGIN:VCALENDAR' not in content:
        return False
    
    # Should contain at least one VEVENT
    if 'BEGIN:VEVENT' not in content:
        return False
    
    return True


def extract_ical_metadata(content: str) -> Dict:
    """Extract basic metadata from iCal feed."""
    metadata = {
        'event_count': content.count('BEGIN:VEVENT'),
        'calendar_name': None,
        'timezone': None
    }
    
    # Extract calendar name
    name_match = re.search(r'X-WR-CALNAME:(.+)', content)
    if name_match:
        metadata['calendar_name'] = name_match.group(1).strip()
    
    # Extract timezone
    tz_match = re.search(r'X-WR-TIMEZONE:(.+)', content)
    if tz_match:
        metadata['timezone'] = tz_match.group(1).strip()
    
    return metadata


def test_ical_url(url: str, timeout: int = 10):
    """
    Test if URL is a valid iCal feed.
    
    Args:
        url: URL to test
        timeout: Request timeout
    
    Returns:
        Dict with feed info if valid, None otherwise
    """
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            content = response.text
            
            if is_valid_ical_feed(content):
                metadata = extract_ical_metadata(content)
                
                return {
                    'url': url,
                    'status': 'valid',
                    'event_count': metadata['event_count'],
                    'calendar_name': metadata['calendar_name'],
                    'content_length': len(content)
                }
    except:
        pass
    
    return None


def find_ical_links_in_html(html: str, base_url: str) -> List[str]:
    """
    Parse HTML for calendar subscription links.
    
    Looks for:
    - Links with text containing "calendar", "ical", "subscribe"
    - Links to .ics files
    - webcal:// protocol links
    """
    soup = BeautifulSoup(html, 'html.parser')
    calendar_links = []
    
    # Calendar-related keywords
    calendar_keywords = [
        'subscribe', 'calendar', 'ical', 'outlook',
        'add to calendar', 'download calendar', 'calendar feed',
        'ics', 'webcal'
    ]
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text().lower()
        
        # Check if link text suggests calendar
        if any(keyword in text for keyword in calendar_keywords):
            full_url = urljoin(base_url, href)
            
            # Convert webcal:// to https://
            if full_url.startswith('webcal://'):
                full_url = full_url.replace('webcal://', 'https://')
            
            if '.ics' in full_url or 'calendar' in full_url:
                calendar_links.append(full_url)
    
    # Also check for link tags
    for link_tag in soup.find_all('link', attrs={'rel': 'alternate'}):
        href = link_tag.get('href', '')
        link_type = link_tag.get('type', '')
        
        if 'calendar' in link_type.lower() or '.ics' in href:
            full_url = urljoin(base_url, href)
            calendar_links.append(full_url)
    
    return list(set(calendar_links))  # Deduplicate


def discover_ical_for_source(source_id: str, source_url: str) -> Dict:
    """
    Discover iCal feeds for a specific source.
    
    Args:
        source_id: Source identifier
        source_url: Source URL
    
    Returns:
        Dict with findings
    """
    findings = {
        'source_id': source_id,
        'source_url': source_url,
        'pattern_matches': [],
        'html_discoveries': [],
        'tested_urls': 0,
        'valid_feeds': 0
    }
    
    print(f"\nDiscovering iCal feeds for: {source_id}")
    print(f"URL: {source_url}\n")
    
    # Extract base URL
    parsed = urlparse(source_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # Method 1: Test common patterns
    print("Testing common iCal patterns...")
    for pattern in ICAL_PATTERNS:
        test_url = base_url + pattern
        findings['tested_urls'] += 1
        
        result = test_ical_url(test_url)
        if result:
            print(f"  ✅ FOUND: {test_url} ({result['event_count']} events)")
            findings['pattern_matches'].append(result)
            findings['valid_feeds'] += 1
        
        time.sleep(0.3)  # Be respectful
    
    # Method 2: Parse HTML for calendar links
    print("\nSearching HTML for calendar links...")
    try:
        response = requests.get(source_url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        if response.status_code == 200:
            calendar_links = find_ical_links_in_html(response.text, base_url)
            
            if calendar_links:
                print(f"  Found {len(calendar_links)} potential calendar links")
                
                for cal_url in calendar_links:
                    result = test_ical_url(cal_url)
                    if result:
                        print(f"  ✅ VALID: {cal_url} ({result['event_count']} events)")
                        findings['html_discoveries'].append(result)
                        findings['valid_feeds'] += 1
                    
                    time.sleep(0.3)
    except Exception as e:
        print(f"  ❌ Error parsing HTML: {e}")
    
    return findings


def discover_all_existing_sources():
    """
    Run iCal discovery on all existing sources in sources.json.
    """
    sources_file = Path(__file__).parent.parent / "sources.json"
    
    if not sources_file.exists():
        print("❌ sources.json not found")
        return
    
    with open(sources_file) as f:
        sources = json.load(f)
    
    all_findings = []
    sources_with_ical = []
    
    print("\n" + "="*60)
    print("iCAL FEED DISCOVERY FOR EXISTING SOURCES")
    print("="*60)
    print(f"\nAnalyzing {len(sources)} sources...\n")
    
    for source in sources:
        source_id = source.get('id')
        source_url = source.get('url')
        adapter_type = source.get('adapter_type', '')
        
        # Skip if already using ICS adapter
        if adapter_type == 'ics_calendar':
            print(f"⏭️  Skipping {source_id} (already using ICS adapter)")
            continue
        
        findings = discover_ical_for_source(source_id, source_url)
        all_findings.append(findings)
        
        if findings['valid_feeds'] > 0:
            sources_with_ical.append(findings)
        
        time.sleep(1)  # Respectful delay between sources
    
    # Save results
    results_file = Path(__file__).parent.parent / "ical_discovery_results.json"
    with open(results_file, 'w') as f:
        json.dump(all_findings, f, indent=2)
    
    # Generate report
    generate_ical_report(all_findings, sources_with_ical)


def generate_ical_report(all_findings: List[Dict], successful_sources: List[Dict]):
    """Generate Markdown report of iCal discoveries."""
    report_file = Path(__file__).parent.parent / "ical_discovery_report.md"
    
    with open(report_file, 'w') as f:
        f.write("# iCal Feed Discovery Report\n\n")
        f.write(f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Sources Analyzed**: {len(all_findings)}\n")
        f.write(f"**Sources with iCal Feeds**: {len(successful_sources)}\n\n")
        f.write("---\n\n")
        
        if successful_sources:
            f.write("## ✅ Sources with iCal Feeds\n\n")
            
            for finding in successful_sources:
                f.write(f"### {finding['source_id']}\n\n")
                f.write(f"**Source URL**: {finding['source_url']}\n\n")
                
                all_feeds = finding['pattern_matches'] + finding['html_discoveries']
                
                for feed in all_feeds:
                    f.write(f"- **Feed URL**: `{feed['url']}`\n")
                    f.write(f"  - Events: {feed['event_count']}\n")
                    if feed.get('calendar_name'):
                        f.write(f"  - Name: {feed['calendar_name']}\n")
                    f.write("\n")
                
                # Generate source config suggestion
                f.write("**Suggested source.json entry**:\n\n")
                f.write("```json\n")
                f.write("{\n")
                f.write(f'  "id": "{finding["source_id"]}_ics",\n')
                f.write(f'  "url": "{all_feeds[0]["url"]}",\n')
                f.write('  "adapter_type": "ics_calendar",\n')
                f.write('  "firm_name": "...",\n')
                f.write('  "active": 1\n')
                f.write("}\n```\n\n")
                f.write("---\n\n")
    
    print(f"\n✅ Report saved to: {report_file}")


if __name__ == '__main__':
    discover_all_existing_sources()
```

**How to Run**:
```bash
cd backend
python scripts/discover_ics_calendars.py
```

---

### Strategy 2 Summary & Checklist

**Implementation Steps**:

- [ ] **Step 2.1**: Create `discover_ics_calendars.py` script
- [ ] **Step 2.2**: Run discovery on all existing sources
- [ ] **Step 2.3**: Review iCal discovery report
- [ ] **Step 2.4**: Add discovered iCal feeds to sources.json
- [ ] **Step 2.5**: Test each new iCal source
- [ ] **Step 2.6**: Run discovery for bank websites specifically

**Expected Timeline**:
- Day 1: Script creation and initial run (Steps 2.1-2.3) - 2-3 hours
- Day 2: Testing and integration (Steps 2.4-2.6) - 2-3 hours

**Expected Outcome**:
- 10-15 new iCal sources discovered
- 5-10 events per source = 50-150 new events
- Fully automated (calendar feeds update automatically)

---

## Strategy 3: Smart Gmail Query Optimization

### 🎯 Overview

**Core Concept**: Optimize Gmail search queries to find more relevant bank event emails while filtering out noise.

**Why This Works**:
- Gmail has powerful search operators
- Can combine multiple criteria
- Filters out earnings/IR content automatically
- Zero cost, uses existing Gmail integration

**Expected Outcome**: 2-3x more relevant emails found

---

### Phase 3A: Query Testing and Optimization

#### Step 3.1: Create Query Testing Tool

**File**: Create `backend/scripts/test_gmail_query.py`

```python
"""
Test Gmail queries to see what they return.

Helps optimize queries before running full ingestion.
"""
import sys
from pathlib import Path
import time

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.smart_gmail_queries import (
    build_full_bank_event_query,
    build_query_with_date_filter,
    print_query_explanation
)


def test_query(query: str, max_results: int = 20):
    """
    Test a Gmail query and show sample results.
    
    Args:
        query: Gmail search query
        max_results: Maximum results to retrieve
    """
    print("\n" + "="*60)
    print("GMAIL QUERY TEST")
    print("="*60)
    print(f"\nQuery: {query}\n")
    
    try:
        # Import Gmail functions
        from scripts.ingest_gmail import get_gmail_service, search_messages
        
        service = get_gmail_service()
        messages = search_messages(service, query, max_results=max_results)
        
        print(f"✅ Found {len(messages)} messages\n")
        
        if messages:
            print("Sample results:")
            print("-" * 60)
            
            for i, msg in enumerate(messages[:10], 1):
                # Get message details
                msg_detail = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metad