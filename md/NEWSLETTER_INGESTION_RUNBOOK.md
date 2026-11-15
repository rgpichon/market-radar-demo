# Newsletter Ingestion Runbook

**Purpose**: Complete operational guide for the Newsletter Acquisition and Ingestion Pipeline.

---

## Overview

This system automates the discovery, subscription, and ingestion of macro-signal event invitations from bulge bracket bank newsletters. It does NOT ingest earnings calls, press releases, or marketing content.

**Key Principles**:
- Respect website ToS and robots.txt
- No CAPTCHA bypass or credential stuffing
- Human-in-the-loop for opt-in confirmation
- Deterministic, auditable artifacts

---

## Quick Start

```bash
# Run the complete subscription loop
python backend/scripts/run_subscription_loop.py --priority p0

# Or run steps individually:
python backend/scripts/report_newsletter_targets.py
python backend/scripts/discover_signup_pages.py --priority p0 --apply
python backend/scripts/extract_signup_forms.py --priority p0 --apply
python backend/scripts/subscribe_newsletters.py --priority p0 --apply
python backend/scripts/find_opt_in_emails.py --days 14
```

---

## Discovery Strategy: Event Pages (NOT General Newsletters)

**IMPORTANT**: The system is configured to discover **event registration pages** (webinars, conferences, roundtables), NOT general newsletter signup pages.

**What We Discover:**
- Event calendars with registration links
- Webinar registration pages
- Conference/roundtable signup pages
- Event notification preferences

**What We Avoid:**
- Generic newsletter signups (e.g., `/newsletters`, `/subscribe`)
- General email alerts
- Marketing newsletter subscriptions

**Seed URLs** are configured to start from event-focused paths (`/events`, `/webinars`, `/conferences`) rather than generic `/insights` or `/research`.

---

## First Live Run (P0)

**Step 1: Baseline Validation**
```bash
python -m compileall backend
python backend/scripts/smoke_test.py
```

**Step 2: Check Current State**
```bash
python backend/scripts/report_newsletter_targets.py
python backend/scripts/ingest_gmail.py --print-live-plan
python backend/scripts/ingest_gmail.py --print-query-components
```

**Step 3: Manual Subscription (2-3 targets)**
```bash
# Get URLs for manual subscription
python backend/scripts/open_target_urls.py --priority p0 --only requires_manual

# Subscribe manually in browser to 2-3 targets from the list above
# After subscribing, mark as confirmed:
python backend/scripts/mark_opt_in_confirmed.py --target-id <target_id>
```

**Step 4: Sender Discovery**
```bash
# Discover actual sender addresses from Gmail
python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report
```

**Step 5: Gmail Ingestion (Dry-Run then Live)**
```bash
# Verify plan again (should show learned senders now)
python backend/scripts/ingest_gmail.py --print-live-plan

# Small dry-run test
python backend/scripts/ingest_gmail.py --days 14 --max 30 --dry-run

# Small live ingestion
python backend/scripts/ingest_gmail.py --days 14 --max 30

# Review post-ingest summary (counts by intel_type, top senders, examples)
```

**Step 6: UI Verification**
```bash
# Start server
python backend/app.py

# Check /api/events endpoint
curl http://localhost:5000/api/events?with_date=0 | jq 'length'

# Verify INTEL/EVENT labels appear in UI
# Verify undated items appear at the end of the list
```

---

## Workflow Phases

### Phase 1: Discovery

**Goal**: Find newsletter signup pages for each target.

```bash
# Discover signup pages for P0 targets
python backend/scripts/discover_signup_pages.py --priority p0 --apply

# Or for a specific target
python backend/scripts/discover_signup_pages.py --target-id jpmorgan_markets --apply
```

**What it does**:
- Starts from expected domains or seed URLs
- Follows links containing: subscribe, newsletter, events, webinar, research
- Scores candidate pages by URL patterns
- Saves evidence to `backend/_evidence/newsletter_acq/discovery/`

**Options**:
- `--max-pages-per-domain 15`: Limit pages fetched
- `--rate-limit-ms 800`: Delay between requests
- `--dry-run`: Preview without writing

### Phase 2: Form Extraction

**Goal**: Extract signup form details from discovered pages.

```bash
python backend/scripts/extract_signup_forms.py --priority p0 --apply
```

**What it does**:
- Parses HTML for subscription forms
- Identifies email fields, consent checkboxes, submit buttons
- Detects obstacles: CAPTCHA, login walls, JS-heavy pages
- Sets `automation_feasibility` label

**Feasibility Labels**:
- `feasible_auto`: Can subscribe via HTTP
- `requires_opt_in`: Subscription works but needs email confirmation
- `captcha_blocked`: CAPTCHA detected
- `login_required`: Authentication required
- `unknown`: Not enough information

### Phase 3: Subscription

**Goal**: Attempt to subscribe using extracted form data.

```bash
# HTTP mode (default, no browser)
python backend/scripts/subscribe_newsletters.py --priority p0 --apply

# Playwright mode (for JS-heavy sites)
python backend/scripts/subscribe_newsletters.py --priority p0 --use-playwright --apply
```

**What it does**:
- Submits form with `rdr.events.rp@gmail.com`
- Analyzes response for success/failure indicators
- Records attempt outcome in target registry
- Saves evidence to `backend/_evidence/newsletter_acq/subscribe/`

**IMPORTANT**: Does NOT complete CAPTCHAs or click confirmation links.

### Phase 4: Opt-In Confirmation (Human Required)

**Goal**: Find and present confirmation links for manual action.

```bash
python backend/scripts/find_opt_in_emails.py --days 14
```

**What it does**:
- Searches Gmail for confirmation emails
- Extracts confirmation links
- Creates queue at `backend/opt_in_queue.json`

**Human Action Required**:
1. Review `backend/opt_in_queue.json`
2. Open confirmation links in browser
3. Click to confirm subscription
4. Mark target as confirmed:

```bash
python backend/scripts/mark_opt_in_confirmed.py --target-id jpmorgan_markets
```

### Phase 5: Sender Discovery

**Goal**: Learn actual sender addresses from Gmail.

```bash
python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report
```

**What it does**:
- Searches Gmail for messages from expected domains
- Extracts actual sender emails
- Calculates confidence score
- Updates `discovered_senders` in target registry

### Phase 6: Event Ingestion

**Goal**: Ingest macro-signal events from newsletters.

```bash
# Dry run
python backend/scripts/ingest_gmail.py --mode targets --days 30 --dry-run

# Full ingestion
python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200
```

---

## Safety Constraints

1. **No CAPTCHA Bypass**: If CAPTCHA detected, stop and mark target as `captcha_blocked`
2. **No Auto-Confirm**: Never click email confirmation links automatically
3. **Rate Limiting**: Default 800ms between requests
4. **Robots.txt**: Respect crawling restrictions
5. **Read-Only Gmail**: Never modify, delete, or archive emails

---

## Target Registry Schema

Each target in `backend/newsletter_targets.json` has:

```json
{
  "id": "jpmorgan_markets",
  "org_name": "JPMorgan",
  "category": "bulge_bracket",
  "priority": "p0",
  "status": "todo|subscribed|paused|rejected",
  "signup_url": "https://...",
  "expected_from_domains": ["jpmorgan.com"],
  "discovered_senders": [],
  "sender_confidence": "low|medium|high",
  "subject_include_any": ["webinar", "outlook", "strategy"],
  "subject_exclude_any": ["earnings", "press release"],
  "acquisition": {
    "discovery_seed_urls": [],
    "discovered_signup_pages": [],
    "discovered_forms": [],
    "subscribe_attempts": [],
    "automation_feasibility": "unknown",
    "opt_in_required": null,
    "last_success_utc": null,
    "last_failure_utc": null
  }
}
```

---

## Troubleshooting

### No Signup Pages Found
- Add seed URLs to `acquisition.discovery_seed_urls`
- Try broader search: `python backend/scripts/discover_signup_pages.py --target-id X --max-pages-per-domain 30`

### CAPTCHA Detected
- Use Playwright mode with headed browser
- Complete CAPTCHA manually when prompted
- Consider manual subscription as fallback

### No Confirmation Email
- Check Gmail spam/promotions folders
- Verify email address is correct
- Some banks require account registration first

### Low Sender Confidence
- Wait for more emails (need 3+ for high confidence)
- Check that sender domain matches expected
- Manually verify subscription is active

---

## Files Reference

| File | Purpose |
|------|---------|
| `backend/newsletter_targets.json` | Target registry |
| `backend/newsletter_discovery_results.json` | Discovery output |
| `backend/newsletter_forms.json` | Form extraction output |
| `backend/newsletter_subscribe_results.json` | Subscription results |
| `backend/opt_in_queue.json` | Pending opt-in confirmations |
| `backend/_evidence/newsletter_acq/` | All evidence artifacts |

---

## Commands Reference

```bash
# Full loop
python backend/scripts/run_subscription_loop.py --priority p0

# Discovery
python backend/scripts/discover_signup_pages.py --priority p0 --apply

# Form extraction
python backend/scripts/extract_signup_forms.py --priority p0 --apply

# Subscription
python backend/scripts/subscribe_newsletters.py --priority p0 --apply

# Opt-in finder
python backend/scripts/find_opt_in_emails.py --days 14

# Mark confirmed
python backend/scripts/mark_opt_in_confirmed.py --target-id <id>

# Sender discovery
python backend/scripts/discover_newsletter_senders.py --days 30 --apply

# Status report
python backend/scripts/report_newsletter_targets.py

# Gmail ingestion
python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200
```

---

## Governance & Decisions

### Decision States

Each newsletter target has a decision record with status:

- `auto_subscribe`: High quality (score >= 70), ready for automated subscription
- `manual_review`: Medium quality (40 <= score < 70), requires human evaluation
- `rejected`: Low quality (score < 40), insufficient macro-signal content
- `paused`: Manually paused or auto-paused after 3 consecutive failures
- `cooldown`: Temporary block (24 hours) after failures

### Pause & Cooldown

- **Paused targets**: Skipped in all subscription attempts (hard block)
- **Cooldown targets**: Skipped until cooldown expires (hard block)
- **Auto-pause**: Triggered after 3 consecutive subscription failures

### Dry-Run Guarantee

All orchestration scripts support `--dry-run`:
- Computes decisions and prints reports
- **Never** performs network requests
- **Never** writes to database
- **Never** modifies files (except logs/reports)

### Safety Guarantees

- No email ingested twice (SHA256 deduplication)
- No confirmation links clicked automatically
- Paused/cooldown targets excluded from all operations
- All decisions audited in `decision_audit_log` table

---

## Operational Commands

### Evaluate Decisions

```bash
# Dry-run (compute but don't persist)
python backend/scripts/evaluate_decisions.py --dry-run

# Evaluate and persist decisions
python backend/scripts/evaluate_decisions.py
```

### Run Subscription Loop

```bash
# Full loop with dry-run
python backend/scripts/run_subscription_loop.py --priority p0 --dry-run

# Execute (respects pause/cooldown)
python backend/scripts/run_subscription_loop.py --priority p0
```

### Ingest Gmail

```bash
# Dry-run (print query, no API calls)
python backend/scripts/ingest_gmail.py --mode targets --dry-run

# Ingest (respects sender promotion levels)
python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200
```

---

## Source Expansion Engine

**Purpose**: Systematic discovery, validation, and onboarding of new event sources from a firm universe.

**Workflow**: Wave Discovery → Validation → Onboarding

---

### Overview

The Source Expansion Engine automates the process of discovering and onboarding new event sources at scale. It follows a structured pipeline:

1. **Discovery**: Crawl firm websites to find RSS/ICS feeds and event hubs
2. **Validation**: Fast-fail validation of candidates (RSS/ICS parsing, HTML assessment)
3. **Generation**: Convert validated candidates into sources.json entries (inactive)
4. **Onboarding**: Run standard onboarding workflow to activate sources

---

### Phase 1: Firm Universe

The firm universe (`backend/firm_universe.json`) contains structured firm data:

```json
{
  "firms": [
    {
      "firm_name": "BlackRock",
      "firm_type": "Asset Manager",
      "priority": "p0",
      "home_url": "https://www.blackrock.com",
      "seed_urls": ["https://www.blackrock.com/us/individual/insights/events"],
      "notes": "Largest asset manager globally"
    }
  ]
}
```

**Firm Types**: Asset Manager, Hedge Fund, Association, Academic, Think Tank, Conference, Central Bank, Regulator, Data Provider

**Priorities**: p0 (highest), p1, p2

---

### Phase 2: Bulk Discovery

**Script**: `backend/scripts/discover_sources_bulk.py`

Discovers candidates from firm universe:

- RSS/Atom feeds (via `<link rel="alternate">` tags)
- ICS calendars (`.ics` links, `webcal://` URLs)
- Event hubs (crawls `/events`, `/webinars`, `/conferences` paths)

**Usage**:
```bash
# Dry-run discovery
python backend/scripts/discover_sources_bulk.py --universe backend/firm_universe.json --priority p0 --dry-run

# Apply discovery (writes source_candidates.json)
python backend/scripts/discover_sources_bulk.py --universe backend/firm_universe.json --priority p0 --apply
```

**Output**: `backend/source_candidates.json`

**Acceptance Criteria**: At least 70% of firms should have candidates discovered.

---

### Phase 3: Bulk Validation

**Script**: `backend/scripts/validate_candidates_bulk.py`

Validates candidates with fast-fail checks using the **HTML Autoparser** for automatic selector extraction.

**Metadata-First Validation** (`backend/utils/metadata_first_validator.py`):
- **Phase 1 - Structured Metadata**: JSON-LD, microdata, meta tags (runs BEFORE selectors)
- **Phase 2 - Detail Recovery**: ICS harvesting + structured metadata on detail pages
- **Phase 3 - JS Data Detection**: Next.js `__NEXT_DATA__`, JSON scripts, API endpoints
- **Phase 4 - Selector Autoparser**: Fallback only if metadata extraction fails
  - **JSON-LD**: Extracts events from structured data (schema.org/Event) - Tier A
  - **Microdata**: Detects microdata event markup - Tier A/B
  - **DOM Clustering**: Automatically finds event containers and generates CSS selectors - Tier B/C
    - **Strict Scoring**: Penalizes low unique link ratio, low event-link hints, repeated titles, nav links
    - **Self-Check**: Validates event-likeness ratio (flags if < 40% look event-like as `needs_refinement`)
- **Detail-Only Mode**: **First-class lane** - detects when events exist but dates are only on detail pages
  - **ICS Harvesting**: Detects and parses `.ics` calendar files from detail pages (most reliable)
  - **Structured Date Extraction**: Prioritizes JSON-LD Event.startDate, time[datetime], meta tags before fuzzy parsing
  - **Aggressive but Safe**: Default detail_fetch template with `stop_after_first_valid` and priority order
- **JS-Rendered Detection**: Evidence-based (requires explicit markers + content check)
- **Gated Detection**: Only if explicit markers AND no meaningful content (less aggressive, adds `gated_suspected` flag)

**Validation Statuses** (Phase 5 - Clear Classification):
- `validated_structured`: Events found via JSON-LD/microdata/meta tags (highest quality)
- `validated_detail_recovered`: Events found, dates recovered from detail pages (ICS or structured metadata)
- `validated_json_api`: Events found in embedded JSON/JS data (treat as JSON API lane)
- `validated_selector`: Events found via CSS selectors (fallback method)
- `partial_needs_detail`: Events found but need detail_fetch for dates
- `no_events`: No events detected
- `press_release_only`: Content detected but not events
- `js_rendered_blocked`: JS-rendered page, needs Playwright
- `gated_login`: Login/gated content detected

**Legacy Status Mapping** (for backward compatibility):
- `ready_to_onboard`: Maps from `validated_structured`, `validated_json_api`, or `validated_selector`
- `ready_to_onboard_with_detail_fetch`: Maps from `validated_detail_recovered` or `partial_needs_detail`
- `deferred`: Maps from `no_events`, `js_rendered_blocked`, or other non-ready statuses
- `failed`: Maps from `gated_login` or HTTP errors

**Source-Specific Patching**:
- `selector_overrides` in sources.json allows manual refinement without changing autoparser
- Use `find_low_confidence_sources.py` to identify sources that would benefit from 1 override
- Overrides apply on top of autoparser output during extraction

**Operational KPIs** (`backend/utils/source_kpis.py`):
- Tracks per-source: `kept_count`, `dated_ratio`, `event_likeness_rate`, `detail_date_hit_rate`, `churn_rate`
- Auto-pause sources below thresholds for 3+ consecutive runs
- Auto-promote sources exceeding thresholds consistently

**Evidence**: Saved to `backend/_evidence/source_validation/<candidate_id>/autoparser.json`

**End-to-End Pipeline** (`backend/scripts/run_source_pipeline_end_to_end.py`):
- Runs complete loop: discovery → validation (with enrichment) → generation → promotion → summary
- **Usage**:
  ```bash
  # Full pipeline with strict caps
  python backend/scripts/run_source_pipeline_end_to_end.py \
    --priority p0 \
    --max-new-fetches 20 \
    --max-sources 50 \
    --max-detail 25 \
    --min-sample-ok 8 \
    --dry-run
  
  # Skip steps if needed
  python backend/scripts/run_source_pipeline_end_to_end.py \
    --priority p0 \
    --skip-discovery \
    --skip-generation \
    --apply
  ```
- **Cache-First**: Second run uses cached detail pages, much faster and promotes more sources
- **Strict Caps**: All limits configurable via flags to prevent rate limiting

**Detail Enrichment Promotion Loop** (`backend/scripts/promote_partial_sources.py`):
- Automatically enriches `partial_needs_detail` sources by fetching detail pages
- Extracts dates using: ICS → JSON-LD → HTML fallback (with improved heuristics)
- Promotes sources to `ready_to_onboard` if they meet thresholds after enrichment
- **Network Resilience**: Retries (3x), exponential backoff, proper timeout handling, structured error classification
- **Smart Sampling**: Stratified (default), date_hint_priority, or top_n modes
- **Provider Throttling**: Per-host cooldown tracking, automatic concurrency reduction on 429/503
- **Improved Date Extraction**: 
  - Range dates (e.g., "Jan 15-17, 2026")
  - Time-only cases (normalizes timezone, defaults to Europe/London)
  - Multiple format variants (US, European, ISO, day month year)
  - Expanded label proximity matching
- **Actionable Output**: Stores `recommended_detail_fetch` config for partial sources (ready for onboarding)
- **Usage**: 
  ```bash
  # Dry-run with stratified sampling
  python backend/scripts/promote_partial_sources.py --sources sources.json --dry-run --sampling-mode stratified
  
  # Cache-only mode (no new fetches)
  python backend/scripts/promote_partial_sources.py --sources sources.json --use-cache-only
  
  # Limit new fetches to avoid rate limiting
  python backend/scripts/promote_partial_sources.py --sources sources.json --max-new-fetches 10
  ```
- **Integration**: Add `--enable-detail-enrichment` flag to `validate_candidates_bulk.py` to enable during validation
- **Caching**: Detail page fetches are cached for 12 hours in `backend/_cache/detail/` (cache keys include parser mode)
- **Classification**: Distinguishes `deferred_transient_network` (timeouts, 429, 503) from hard failures
- **Minimum Sample**: Requires `--min-sample-ok` (default 8) successful detail page fetches before judging
- **Evidence**: Saved to `backend/_evidence/detail_enrich/<source_id>/summary.json` with classification breakdown and recommended_detail_fetch

**Source Maintenance Loop** (`backend/scripts/maintain_sources.py`):
- Automatically detects source degradation from time-series health snapshots
- Applies repair playbooks to fix common issues (selector drift, low dated_ratio, rate limits, etc.)
- **Health Snapshots**: Stored in `source_health` DB table with metrics (kept_count, dated_ratio, future_count, error_class)
- **Degradation Detection**: Uses trailing median baselines to detect drops in kept_count, dated_ratio, future_count
- **Repair Playbooks**:
  - **A - Dates-on-detail**: Enable/enhance detail enrichment for low dated_ratio
  - **B - ICS-backed**: Enable ICS calendar harvesting when ICS links detected
  - **C - Embedded JSON**: Enable JSON-LD extraction for Next.js/structured data
  - **D - Selector drift**: Regenerate selectors using autoparser when structure changes
  - **E - Rate-limited**: Adjust crawl budget for transient network errors (429, 503, timeouts)
  - **F - Hard block**: Mark source inactive for repeated 403/401 errors
- **Usage**:
  ```bash
  # Dry-run: detect degradation without applying changes
  python backend/scripts/maintain_sources.py --dry-run --max-sources 5
  
  # Apply patches to sources.json (writes config changes)
  python backend/scripts/maintain_sources.py --apply --max-sources 10
  
  # Run repair actions (autoparser, detail enrichment)
  python backend/scripts/maintain_sources.py --apply --repair --only-degraded
  
  # Run scrape first to generate fresh stats
  python backend/scripts/maintain_sources.py --run-scrape-first --apply
  ```
- **Evidence**: Saved to `backend/_evidence/maintenance/<run_id>/<source_id>/maintenance_result.json`
- **Run Summary**: `backend/_evidence/maintenance/<run_id>/run_summary.json` with degradation breakdown and playbook recommendations
- **Safety**: Dry-run is default; patches are minimal (only relevant fields updated); never auto-activates hard-blocked sources

**For RSS/ICS**:
- HTTP fetch (status/content-type)
- Parse items
- Compute: item count, dated ratio, future ratio
- Detect press release patterns

**For HTML**:
- Run HTML assessment (Tier A/B/C)
- Detect JS-rendered pages
- Check for login/auth requirements
- Test extraction (if possible)

**Usage**:
```bash
# Dry-run validation
python backend/scripts/validate_candidates_bulk.py --priority p0 --dry-run

# Apply validation (writes source_candidates_validated.json)
python backend/scripts/validate_candidates_bulk.py --priority p0 --apply
```

**Output**: `backend/source_candidates_validated.json`

**Failure Classes**: `no_events`, `press_release_only`, `js_rendered`, `blocked`, `gated_login`, `format_incompatible`, `low_date_coverage`, `no_future_events`

**Acceptance Criteria**: For each firm, at least 1 candidate is either "ready_to_onboard" OR "deferred" with explicit reason.

---

### Phase 4: Generate Sources

**Script**: `backend/scripts/generate_sources_from_candidates.py`

Converts validated candidates into sources.json entries:

- Generates stable source IDs (slug from firm_name + lane)
- Adds sensible defaults (tags, postprocess_rules)
- Sets `active: 0` (inactive by default)
- Includes failure metadata for deferred candidates

**Usage**:
```bash
# Dry-run generation
python backend/scripts/generate_sources_from_candidates.py --priority p0 --dry-run

# Apply generation (writes to sources.json)
python backend/scripts/generate_sources_from_candidates.py --priority p0 --apply
```

**Output**: New entries added to `backend/sources.json` (inactive)

**Acceptance Criteria**: After Wave 1, +20 sources added (inactive or active), at least +8 newly active sources across non-bank categories.

---

### Phase 5: Onboarding

**Script**: `backend/scripts/onboard_source.py`

For each new candidate source:

```bash
# Dry-run onboarding (validate without activating)
python backend/scripts/onboard_source.py --source_id <source_id> --dry-run

# Activate if passes quality gates
python backend/scripts/onboard_source.py --source_id <source_id> --activate
```

**Quality Gates**:
- >= 3 real events
- >= 70% dated
- >= 1 future event
- Lane is supported
- No hard stops (press_release_only, js_rendered, gated_login)

**Terminal States**: Every source must end in:
- **active**: Passed validation and activated
- **inactive**: With explicit reason (failure_class/evidence/recommended_next_action)

---

### Operational Loop

**Weekly Source Expansion Workflow**:

```bash
# 1. Discover bulk
python backend/scripts/discover_sources_bulk.py --priority p0 --apply

# 2. Validate bulk
python backend/scripts/validate_candidates_bulk.py --priority p0 --apply

# 3. Generate sources (inactive)
python backend/scripts/generate_sources_from_candidates.py --priority p0 --apply

# 4. Batch onboard (dry-run first)
for source_id in $(python -c "import json; sources=json.load(open('backend/sources.json')); print('\n'.join([s['id'] for s in sources if s.get('active')==0 and 'Generated from bulk discovery' in s.get('comment','')]))"); do
  python backend/scripts/onboard_source.py --source_id "$source_id" --dry-run --print-reasons
done

# 5. Activate passing sources
for source_id in $(...); do
  python backend/scripts/onboard_source.py --source_id "$source_id" --activate
done

# 6. Full scrape + verify UI
python backend/scripts/run_scrape.py
# Open UI and confirm event count increases
```

---

### Lane Priority

**Preferred Order**:
1. **ICS/RSS** (highest priority - structured, reliable)
2. **JSON API** (if obvious endpoints)
3. **HTML list** (Tier A/B only)
4. **Playwright** (only when ROI is obvious)

**Hard Constraints**:
- Do not use Playwright unless absolutely necessary
- Prefer feeds over HTML scraping
- Every source must have terminal state (active OR inactive with reason)

---

### Coverage Goals

**Target Categories** (beyond banks):
- Asset managers (BlackRock, PIMCO, Vanguard, etc.)
- Hedge funds (public research/events pages only)
- Associations (CFA, CAIA, SIFMA, AIMA, etc.)
- Academic finance centers (Cambridge, Imperial, HEC, INSEAD, etc.)
- Think tanks (Peterson, Chatham House, etc.)
- Conferences (Milken, WEF - already have)
- Central banks (BIS, BoE, BoJ, SNB events pages)

**Missing Categories Report**: Run `python backend/scripts/report_sources.py` to see coverage gaps.

---

### Evidence & Artifacts

**Evidence Directory**: `backend/_evidence/source_discovery/<firm>/<timestamp>/`

Contains:
- `discovery.json`: Full discovery results per firm
- Feed URLs found
- Event hubs discovered
- Candidate scores

**Candidate Files**:
- `backend/source_candidates.json`: Raw discovery results
- `backend/source_candidates_validated.json`: Validation results

---

### Troubleshooting

**No Candidates Found**:
- Check firm_universe.json has correct URLs
- Verify network connectivity
- Check robots.txt restrictions

**Validation Failures**:
- Review failure_class in validated candidates
- Check evidence for specific errors
- For HTML: may need manual selector extraction

**Onboarding Failures**:
- Review quality gate errors
- Check if selectors needed (HTML sources)
- Verify lane is supported

---

**Last Updated**: 2026-01-27

<!-- AUTO-GENERATED STATUS SECTION -->

# Newsletter Targets Status Report

**Generated**: 2026-01-28 19:33:35
**Owner Email**: rdr.events.rp@gmail.com
**Last Updated**: 2026-01-14

---

## Summary by Status

| Status | Count |
|--------|-------|
| todo | 0 |
| subscribed | 10 |
| rejected | 0 |
| unknown | 0 |
| requires_manual | 0 |
| confirmed | 0 |

## Summary by Category

| Category | Count |
|----------|-------|
| bulge_bracket | 10 |

## Summary by Priority

| Priority | Count |
|----------|-------|
| p0 | 10 |
| p1 | 0 |
| p2 | 0 |

## Discovered Senders (Learned from Gmail)

| Org | Confidence | Discovered Senders | Last Seen |
|-----|------------|-------------------|-----------|
| UBS | low | - | Never |
| Societe Generale | low | - | Never |
| Morgan Stanley | low | - | Never |
| JPMorgan | low | - | Never |
| Goldman Sachs | low | - | Never |
| Deutsche Bank | low | - | Never |
| Citigroup | low | - | Never |
| Barclays | low | - | Never |
| Bank of America | low | - | Never |
| BNP Paribas | low | - | Never |

## Per-Bank Acquisition Status

| Org | Acquisition Mode | Newsletter Path | Event Portal | Status | Reason |
|-----|----------------|-----------------|--------------|--------|--------|
| BNP Paribas | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Bank of America | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Barclays | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Citigroup | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Deutsche Bank | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Goldman Sachs | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| JPMorgan | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Morgan Stanley | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| Societe Generale | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |
| UBS | both | subscribed (no senders yet) | discovered (not validated) | subscribed | pending |

## All Targets by Last Seen

| Org | ID | Status | Confidence | Last Seen |
|-----|----|--------|------------|-----------|
| UBS | ubs_markets | subscribed | low | None |
| Societe Generale | socgen_markets | subscribed | low | None |
| Morgan Stanley | morgan_stanley_markets | subscribed | low | None |
| JPMorgan | jpmorgan_markets | subscribed | low | None |
| Goldman Sachs | goldman_markets | subscribed | low | None |
| Deutsche Bank | deutsche_bank_markets | subscribed | low | None |
| Citigroup | citigroup_markets | subscribed | low | None |
| Barclays | barclays_markets | subscribed | low | None |
| Bank of America | bofa_markets | subscribed | low | None |
| BNP Paribas | bnpp_markets | subscribed | low | None |

## Recommended Next Actions

### 3. Run Sender Discovery

Run `python backend/scripts/discover_newsletter_senders.py --apply --report` for:

- JPMorgan
- Goldman Sachs
- Morgan Stanley
- Citigroup
- Bank of America
- ...and 5 more

### Quick Commands

```bash
# Generate this report
python backend/scripts/report_newsletter_targets.py

# Discover senders from Gmail
python backend/scripts/discover_newsletter_senders.py --days 30 --apply --report

# Dry-run ingestion
python backend/scripts/ingest_gmail.py --mode targets --dry-run

# Full ingestion
python backend/scripts/ingest_gmail.py --mode targets --days 30 --max 200
```

## P0 Subscription Checklist

| Org | ID | Signup URL | Status | Notes |
|-----|----|-----------|--------|-------|
| BNP Paribas | bnpp_markets | https://economic-research.bnpparibas.com/Subscriptions/fr-FR | subscribed | Primary markets/research newsletter |
| Bank of America | bofa_markets | https://institute.bankofamerica.com/subscribe.html | subscribed | Primary markets/research newsletter |
| Barclays | barclays_markets | https://www.barclays.co.uk/subscriptions?scl=8_sb | subscribed | Primary markets/research newsletter |
| Citigroup | citigroup_markets | https://www.citigroup.com/global/insights/citi-institute#newsletter | subscribed | Primary markets/research newsletter |
| Deutsche Bank | deutsche_bank_markets | https://flow.db.com/newsletter/subscribe-to-flow-digest-newsletter | subscribed | Primary markets/research newsletter |
| Goldman Sachs | goldman_markets | https://www.goldmansachs.com/insights/outlooks/2026-outlooks | subscribed | Primary markets/research newsletter |
| JPMorgan | jpmorgan_markets | https://www.jpmorgan.com/newsletters | subscribed | Primary markets/research newsletter |
| Morgan Stanley | morgan_stanley_markets | https://www.morganstanley.com/newsletter/subscribe | subscribed | Primary markets/research newsletter |
| Societe Generale | socgen_markets | https://wholesale.banking.societegenerale.com/en/news-insights/ | subscribed | Primary markets/research newsletter |
| UBS | ubs_markets | https://www.ubs.com/global/en/wealthmanagement/insights.html | subscribed | Primary markets/research newsletter |

## Sender Allowlist Suggestions

These domains/emails are from subscribed targets and can be added to Gmail ingestion config.

### Domains

- `bankofamerica.com`
- `barclays.co.uk`
- `barclays.com`
- `bnpparibas.com`
- `bofa.com`
- `bofasecurities.com`
- `citi.com`
- `citigroup.com`
- `db.com`
- `deutsche-bank.com`
- `goldmansachs.com`
- `group.bnpparibas`
- `gs.com`
- `jpmorgan.com`
- `jpmorganchase.com`
- `morganstanley.com`
- `sgresearch.com`
- `societegenerale.com`
- `ubs.com`

## Keyword Suggestions

These keywords are aggregated from all targets and can inform Gmail query building.

### Include Keywords (subject_include_any)

- `conference`
- `macro`
- `markets`
- `outlook`
- `roundtable`
- `strategy`
- `webinar`

### Exclude Keywords (subject_exclude_any)

- `appointment`
- `dividend`
- `earnings`
- `press release`
- `quarter`
- `results`

## Governance Decision Status

| Org | Decision | Score | Status | Next Action |
|-----|----------|-------|--------|-------------|
| BNP Paribas | manual_review | 50 | active | open_signup_page |
| Bank of America | manual_review | 50 | active | open_signup_page |
| Barclays | manual_review | 50 | active | open_signup_page |
| Citigroup | manual_review | 50 | active | open_signup_page |
| Deutsche Bank | manual_review | 50 | active | open_signup_page |
| Goldman Sachs | manual_review | 50 | active | open_signup_page |
| JPMorgan | manual_review | 50 | active | open_signup_page |
| Morgan Stanley | manual_review | 50 | active | open_signup_page |
| Societe Generale | manual_review | 50 | active | open_signup_page |
| UBS | manual_review | 50 | active | open_signup_page |

## Acquisition Pipeline Status

| Org | Feasibility | Pages | Forms | Top Candidate (score) |
|-----|-------------|-------|-------|----------------------|
| BNP Paribas | captcha_blocked | 7 | 2 | https://economic-research.bnpparibas.com/Subscript... (100) |
| Bank of America | captcha_blocked | 12 | 3 | https://investor.bankofamerica.com/events-and-pres... (135) |
| Barclays | js_heavy_form | 12 | 0 | https://www.barclays.co.uk/subscriptions?scl=8_sb (100) |
| Citigroup | js_heavy_form | 14 | 0 | https://www.citigroup.com/global/insights/citi-ins... (100) |
| Deutsche Bank | requires_manual | 13 | 2 | https://flow.db.com/newsletter/subscribe-to-flow-d... (180) |
| Goldman Sachs | requires_manual | 14 | 4 | https://www.goldmansachs.com/insights/outlooks/202... (100) |
| JPMorgan | js_heavy_form | 15 | 0 | https://www.jpmorgan.com/newsletters (100) |
| Morgan Stanley | unknown | 12 | 1 | https://www.morganstanley.com/newsletter/subscribe (180) |
| Societe Generale | js_heavy_form | 12 | 0 | https://wholesale.banking.societegenerale.com/en/n... (100) |
| UBS | feasible_http_post | 12 | 1 | https://www.ubs.com/global/en/wealthmanagement/ins... (100) |

## Next Actions by Category

### Auto-Subscribe Possible

Run: `python backend/scripts/subscribe_newsletters.py --priority p0 --apply`

- **UBS**: AUTO_DISCOVER

### Manual Subscribe Required

Visit these pages manually and subscribe with rdr.events.rp@gmail.com:

- **Goldman Sachs**: [https://www.goldmansachs.com/insights/outlooks/2026-outlooks...](https://www.goldmansachs.com/insights/outlooks/2026-outlooks)
- **Morgan Stanley**: [https://www.morganstanley.com/newsletter/subscribe...](https://www.morganstanley.com/newsletter/subscribe)
- **Deutsche Bank**: [https://flow.db.com/newsletter/subscribe-to-flow-digest-news...](https://flow.db.com/newsletter/subscribe-to-flow-digest-newsletter)

### Blocked (CAPTCHA/Login/JS)

These require manual intervention or Playwright:

- **JPMorgan** (js_heavy_form): https://www.jpmorgan.com/newsletters
- **Citigroup** (js_heavy_form): https://www.citigroup.com/global/insights/citi-institute#new
- **Bank of America** (captcha_blocked): https://investor.bankofamerica.com/events-and-presentations/
- **Barclays** (js_heavy_form): https://www.barclays.co.uk/subscriptions?scl=8_sb
- **Societe Generale** (js_heavy_form): https://wholesale.banking.societegenerale.com/en/news-insigh
- **BNP Paribas** (captcha_blocked): https://economic-research.bnpparibas.com/Subscriptions/fr-FR

## Governance Summary

| Category | Count |
|----------|-------|
| Auto-subscribe candidates | 0 |
| Manual review required | 10 |
| Rejected | 0 |
| Paused | 0 |
| Cooldown | 0 |

**Note**: Run `python backend/scripts/evaluate_decisions.py` to update decisions.


<!-- END AUTO-GENERATED STATUS SECTION -->
