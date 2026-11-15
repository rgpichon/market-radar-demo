# Market Events Radar - Personal Event Discovery Platform

A personalised event discovery platform where users register interests and are shown relevant upcoming events they can directly sign up for — not a news site, not a database.

**Core Purpose**: Help users efficiently decide which events to attend by providing a decision-focused interface structured around personal relevance, urgency, and intentional exploration.

**Product Vision**: Transform from an events database into a personal event discovery product focused on decision + action. The system actively helps users choose which events to register for, structured around the user's needs rather than data completeness.

---

## Quick Start

### Run the Interface

```bash
./run.sh
```

This starts the Flask server and opens the interface in your browser.

### Manual Start

```bash
cd backend
python app.py --port 5001
```

Then open `http://127.0.0.1:5001` in your browser.

---

## Current Status

### ✅ Completed

- **Backend Intelligence**: Event classification, signal scoring, participant roles, theme tagging
- **4-Zone Architecture**: Database schema, APIs, and basic UI structure
- **Source Coverage**: 27 active sources, **11 working at 100%** (see Source Status section below)
- **Data Acquisition**: Multiple adapter types (JSON-LD, HTML, JSON API, Playwright, RSS, iCal)
- **HTML Autoparser**: Automated selector generation with detail_fetch support for date extraction
- **Homepage**: 4-zone card layout with previews
- **Source Maintenance System**: Automated health monitoring, degradation detection, and repair playbooks (NEW)

### ⚠️ In Progress

- **Zone Pages**: Events loading and filtering (see fix plan below)
- **Source Expansion**: Adding more sources (see expansion plan below)

### 📋 Planned

- **Frontend Redesign**: Clean zone-based navigation (see design plan below)
- **User Accounts**: Personalization and behavior tracking
- **AI Recommendations**: Enhanced ranking algorithms

---

## Project Structure

```
project_root/
├── backend/
│   ├── app.py                 # Flask server
│   ├── db.py                  # Database schema
│   ├── scrape_runner.py       # Scraping orchestration
│   ├── sources.json           # Source configurations
│   ├── adapters/              # Scraping adapters
│   └── utils/                  # Utilities
├── frontend/
│   ├── index.html             # Homepage with zone cards
│   ├── zone1.html             # Zone 1 detailed view
│   ├── zone2.html             # Zone 2 detailed view
│   ├── zone3.html             # Zone 3 detailed view
│   ├── zone4.html             # Zone 4 advanced view
│   ├── app.js                 # Frontend logic
│   └── styles.css              # Styling
└── README.md
```

---

## The 4-Zone Architecture

### Zone 1: Recommended for You
High signal score events, personalized by relevance. **Status**: ✅ API complete, ⚠️ UI loading needs fix

### Zone 2: Happening Soon
Time-sorted events within next 7-14 days. **Status**: ✅ API complete, ⚠️ UI loading needs fix

### Zone 3: Explore by Interest
Topic-based exploration with filters. **Status**: ✅ API complete, ⚠️ UI loading needs fix

### Zone 4: All Events / Advanced
Full event catalog with advanced filtering. **Status**: ✅ Complete

---

## 📋 Implementation Plans (Not Yet Complete)

### 1. Zone Pages Functionality Fix

**Problem**: Events don't load when clicking "View All" on zone cards.

**Solution**:
- Use `/api/events` endpoint (not limited endpoints) to get all events
- Add rescrape button to Zone 1, 2, 3
- Populate topic filters on all zone pages
- Ensure proper initialization

**Status**: ⚠️ In Progress - Functions created in `app.js`, needs HTML updates

**Files to Update**:
- `frontend/zone1.html` - Use `initializeZonePage(1)`
- `frontend/zone2.html` - Use `initializeZonePage(2)`
- `frontend/zone3.html` - Use `initializeZonePage(3)`
- `frontend/zone4.html` - Ensure `loadEvents()` works

**See**: Full plan in README section "🔧 Zone Pages Functionality Fix Plan"

---

### 2. Source Expansion Plan

**Goal**: Add more event sources across all categories.

**Current**: 27 active sources, ~500+ events per scrape

**Target Categories**:
- **Associations**: ISDA, SIFMA, FIA (some blocked by Cloudflare)
- **Central Banks**: Fed Reserve, BoE, BoJ, SNB, RBA (in progress)
- **Think Tanks**: PIIE, Chatham House, AEI (blocked), Carnegie (✅ done)
- **Academic**: Harvard (✅ done), MIT (✅ done), Stanford (✅ done), Oxford (✅ done), Wharton, Yale, Chicago Booth
- **Conferences**: Milken (✅ done), WEF (✅ done), Bretton Woods (blocked)

**Status**: 
- ✅ 5 new sources added from bulk discovery (49 events)
- ⚠️ 3 sources partial (events but no dates: AIMA, CFA, Cambridge HTML)
- ❌ 16 sources need selector refinement (AQR, BoE, CAIA, Chicago Booth, HEC Paris, Man Group, PIMCO, Schroders, Wharton, etc.)

**Quick Wins Remaining**:
- Wharton, Yale, Chicago Booth (academic)
- More think tanks (if not blocked)

**See**: Full plan in README section "📈 Comprehensive Source Expansion Plan"

---

### 3. Frontend Redesign

**Goal**: Clean homepage with 4 zone cards, detailed views on click.

**Status**: ⚠️ Partially implemented
- ✅ Homepage with zone cards
- ✅ Zone pages created
- ⚠️ Zone pages need event loading fixes (see Plan 1)
- ⚠️ Filters need to be fully functional

**Remaining Work**:
- Fix zone page event loading
- Ensure filters work on all zone pages
- Add rescrape buttons to all zones
- Polish UI/UX

**See**: Full design in README section "🎨 Frontend Redesign: Clean Zone-Based Navigation"

---

## Source Status

**Last Updated**: January 27, 2026

### 📊 Source Health Summary

**Test Results** (All 54 sources tested):
- ✅ **Working (100%)**: 11 sources (20.4%)
  - Meet all criteria: 3+ events, 50%+ dated ratio, has future events
- ⚠️ **Partial**: 14 sources (25.9%)
  - Have events but missing dates or no future events (candidates for detail_fetch)
- ❌ **Failed**: 29 sources (53.7%)
  - No events found (mostly inactive sources needing selector fixes)

**By Adapter Type**:
- `html_list`: 9/45 working (20.0%)
- `json_api`: 1/1 working (100.0%)
- `rss`: 1/4 working (25.0%)
- `ics`: 0/1 working (0.0%)
- `playwright`: 0/3 working (0.0%)

**Test Command**: `python backend/scripts/test_all_sources.py`

### ✅ Active Sources (27 sources)

**✅ Working Sources (11 - 100% functional)**:
1. **BIS IFC** - 18 events, 94.4% dated, 7 future
2. **Brookings Institution** - 14 events, 100% dated, 10 future
3. **Bruegel** - 15 events, 100% dated, 4 future
4. **CSIS** - 4 events, 100% dated, 4 future
5. **Cambridge Judge Business School (RSS)** - 10 events, 100% dated, 1 future
6. **ICMA** - 14 events, 100% dated, 14 future
7. **IIF** - 12 events, 100% dated, 11 future
8. **Imperial College Business School** - 13 events, 92.3% dated, 12 future
9. **MIT Sloan** - 9 events, 100% dated, 9 future
10. **NBER** - 50 events, 98% dated, 49 future
11. **Oxford Said Business School** - 19 events, 100% dated, 5 future

**Inactive/Needs Work (16 sources)**:
- AQR, Bank of England, CAIA Association, Chicago Booth, HEC Paris, Man Group, PIMCO, Schroders, Wharton School (selectors need refinement or pages are JS-rendered)

**Think Tanks (7)**:
- ✅ Brookings Institution
- ✅ CEPR (Centre for Economic Policy Research)
- ✅ CSIS (Center for Strategic and International Studies)
- ✅ Bruegel
- ✅ Wilson Center
- ✅ CFR (Council on Foreign Relations)
- ✅ Carnegie Endowment

**Academic Institutions (5)**:
- ✅ LSE (London School of Economics)
- ✅ MIT Sloan
- ✅ Stanford GSB
- ✅ Oxford Said Business School
- ✅ Harvard Kennedy School

**Associations (5)**:
- ✅ ICMA (International Capital Market Association)
- ✅ ISDA (International Swaps and Derivatives Association) - RSS feed
- ✅ IIF (Institute of International Finance)
- ✅ AFME (Association for Financial Markets in Europe)
- ✅ FIA (Futures Industry Association) - Playwright

**Central Banks (2)**:
- ✅ BIS IFC (Irving Fisher Committee)
- ⚠️ ECB (European Central Bank) - Conferences (258 events, 0% dated - detail_fetch enabled)

**Conferences (2)**:
- ✅ Milken Institute
- ✅ World Economic Forum (WEF) - Playwright

**Research (1)**:
- ✅ NBER (National Bureau of Economic Research)

**New Sources from Bulk Discovery (5 active)**:
- ✅ **Cambridge Judge Business School (RSS)**: 10 events, 100% dated, 1 future
- ✅ **Imperial College Business School**: 13 events, 92% dated, 12 future
- ⚠️ **AIMA**: 18 events (no dates extracted yet)
- ⚠️ **CFA Society Global**: 5 events (no dates extracted yet)
- ⚠️ **Cambridge Judge Business School (HTML)**: 3 events (no dates extracted yet)

---

### ❌ Inactive/Disabled Sources (11 sources)

**Disabled - Wrong Content Type**:
- ❌ Federal Reserve - Mostly news/speeches, not events
- ❌ FDIC - Mostly press releases, not webinars
- ❌ BNP Paribas RSS - Press releases only, not events

**Disabled - Technical Issues**:
- ❌ Moody's - 404 error (URL not found)
- ❌ ECB RSS Feed - HTTP error (feed URL invalid)
- ❌ LSE ICS Calendar - HTTP error (feed URL invalid)

**Disabled - Not Working**:
- ❌ CFA Institute - Selectors not working
- ❌ World Bank - Selectors not working
- ❌ OECD - Selectors not working
- ❌ IMF - Selectors not working
- ❌ Heritage Foundation - Selectors not working

---

### ⚠️ Blocked Sources (Not in sources.json yet)

These sources were attempted but blocked by bot protection:
- ❌ PIIE (Peterson Institute) - 403 Forbidden (Cloudflare)
- ❌ Chatham House - 403 Forbidden
- ❌ SIFMA - 403 Forbidden (Cloudflare challenge page)
- ❌ AEI (American Enterprise Institute) - 403 Forbidden

**Potential Solutions**: Use Playwright with stealth plugins, proxy rotation, or manual curation.

---

### 🔄 In Progress Sources

These sources are being worked on:
- ⚠️ Federal Reserve - Playwright works but selectors need refinement
- ⚠️ Bank of England - Page appears empty, need alternative URL
- ⚠️ Bank of Japan - Need to find correct URL (404 on tested URLs)
- ⚠️ FIA - Playwright works but title extraction needs refinement

---

## Source Management

### Source Maintenance Loop

Automatically detects and repairs source degradation:

```bash
# Dry-run: detect issues without applying changes
python backend/scripts/maintain_sources.py --dry-run --max-sources 5

# Apply patches to sources.json
python backend/scripts/maintain_sources.py --apply --max-sources 10

# Run repair actions (autoparser, detail enrichment)
python backend/scripts/maintain_sources.py --apply --repair --only-degraded
```

### Wave-1 Mass Repair (NEW)

Automated batch repair of failing/partial sources with smart retry handling:

```bash
# Dry-run: detect repairable sources (no network, no writes)
python backend/scripts/wave1_repair_sources.py --dry-run --max-sources 10

# Repair mode but no writes (network ok, no sources.json writes)
python backend/scripts/wave1_repair_sources.py --repair --dry-run --max-sources 10

# Apply mode (writes patches only when verified working)
python backend/scripts/wave1_repair_sources.py --repair --apply --max-sources 10

# With host budget controls and host diversification
python backend/scripts/wave1_repair_sources.py --repair --apply \
  --max-sources 10 \
  --max-unique-hosts 5 \
  --max-transient-failures 5 \
  --per-host-max 20 \
  --per-host-delay 1.0 \
  --sampling-mode adaptive
```

**Features**:
- **Persistent host cooldowns**: Hosts that hit 429/503 are skipped for X hours across runs (saved to `backend/_cache/host_cooldowns.json`)
- **Host diversification**: Cohort selection shuffles and limits by unique hosts to avoid hitting the same host repeatedly
- **Early escalation**: Sources with 0 successes and >K transient failures are marked as `deferred_transient_network` and skipped early
- **Adaptive sampling**: Smart detail page sampling (first 3, middle 3, last 3, plus date-hint items) with early stopping

**Evidence**: Saved to `backend/_evidence/wave1_repair/<run_id>/<source_id>/result.json` and `run_summary.json`

**Features**:
- **Health Snapshots**: Tracks per-source metrics (kept_count, dated_ratio, future_count) in `source_health` DB table
- **Degradation Detection**: Uses trailing median baselines to detect drops in performance
- **Repair Playbooks**: 6 automated playbooks (dates-on-detail, ICS-backed, embedded JSON, selector drift, rate-limited, hard block)
- **Evidence**: All results saved to `backend/_evidence/maintenance/<run_id>/`

See `md/NEWSLETTER_INGESTION_RUNBOOK.md` for detailed documentation.

### Add a New Source

1. Add entry to `backend/sources.json`
2. Test: `python backend/scripts/test_source.py <source_id>`
3. Refine selectors if needed
4. Run full scrape: `python backend/scripts/run_scrape.py`
5. Verify in UI

### Test a Source

```bash
cd backend
python scripts/test_source.py <source_id> 10
```

### Run Scrape

```bash
cd backend
python scripts/run_scrape.py
```

Or use the "Run scrape now" button in the UI.

---

## Troubleshooting

### Port 5000 in Use

Port 5000 is used by macOS AirPlay. The app runs on port 5001 by default (see `run.sh`).

### Events Not Loading

1. Check browser console for errors
2. Verify Flask server is running
3. Check API endpoints: `curl http://127.0.0.1:5001/api/events?days_ahead=365`
4. See "Zone Pages Functionality Fix Plan" for detailed fixes

### Source Not Working

1. Test source: `python backend/scripts/test_source.py <source_id>`
2. Check for 403 errors (blocked by bot protection)
3. Try Playwright adapter for JS-rendered pages
4. See "Troubleshooting: Handling Blocked Sources" for solutions

---

## API Endpoints

- `GET /api/events` - All events (with filters)
- `GET /api/recommendations` - High signal score events
- `GET /api/events/happening-soon` - Events in next 14 days
- `GET /api/events/by-topic?topic=X` - Events by topic
- `GET /api/homepage/preview` - Homepage preview data
- `POST /api/scrape` - Run scrape
- `GET /api/topics` - Available topics

---

## Database

SQLite database: `backend/events.db`

**Key Tables**:
- `events` - All events
- `sources` - Source configurations
- `notifications` - User notifications
- `users` - User accounts (for future personalization)
- `user_interests` - User interests (for future personalization)

---

## Source Maintenance System (NEW)

**Automated source health monitoring and repair** - Detects degradation and applies repair playbooks automatically.

### Overview

The Source Maintenance Loop automatically monitors source health over time, detects degradation patterns, and applies appropriate repair playbooks to fix common issues. This ensures sources remain healthy as websites change their structure or implement rate limiting.

### Components

1. **Health Snapshots** (`backend/db.py`):
   - `source_health` table stores time-series metrics per source
   - Tracks: kept_count, dated_count, undated_count, future_count, dated_ratio, kept_ratio, error_class
   - Functions: `insert_source_health()`, `get_last_source_health()`, `get_latest_source_health_map()`
   - Snapshots computed from `run_stats` (source of truth, not DB queries)

2. **Degradation Detection** (`backend/utils/source_degradation.py`):
   - Deterministic rules using trailing median baselines (last 5 non-zero snapshots)
   - Detects 7 degradation classes:
     - `drop_kept_count`: Latest < 40% of baseline
     - `drop_dated_ratio`: Latest < baseline - 25% AND < 60%
     - `drop_future_count`: Latest < 40% of baseline
     - `spike_errors_transient`: Timeouts, 429, 503 dominate
     - `spike_errors_blocked`: Repeated 403/401
     - `flat_zero_events`: 2+ consecutive runs with kept_count=0
     - `unknown`: Degraded but no specific class

3. **Repair Playbooks** (`backend/utils/source_repair.py`):
   - **A - Dates-on-detail**: Enable/enhance detail enrichment for low dated_ratio
   - **B - ICS-backed**: Enable ICS harvesting when ICS links detected
   - **C - Embedded JSON**: Enable JSON-LD extraction for Next.js/structured data
   - **D - Selector drift**: Regenerate selectors using autoparser
   - **E - Rate-limited**: Adjust crawl budget for transient network errors
   - **F - Hard block**: Mark inactive for repeated 403/401 errors
   - Each playbook returns: `patch` (config changes), `repair_actions` (scripts to run), `why` (explanation)

4. **Maintenance Loop** (`backend/scripts/maintain_sources.py`):
   - Orchestrates: load sources → compute snapshots → detect degradation → select playbooks → apply patches
   - **Dry-run by default** (no DB writes, no sources.json writes)
   - `--apply`: Writes patches to sources.json (minimal, safe updates)
   - `--repair`: Runs automated repair actions (autoparser, detail enrichment)
   - `--run-scrape-first`: Runs scrape to generate fresh run_stats
   - Evidence saved to `backend/_evidence/maintenance/<run_id>/<source_id>/maintenance_result.json`
   - Run summary: `backend/_evidence/maintenance/<run_id>/run_summary.json`

### Usage

```bash
# Dry-run: detect issues without applying changes
python backend/scripts/maintain_sources.py --dry-run --max-sources 5

# Apply patches to sources.json
python backend/scripts/maintain_sources.py --apply --max-sources 10

# Run repair actions (autoparser, detail enrichment)
python backend/scripts/maintain_sources.py --apply --repair --only-degraded

# With fresh scrape first
python backend/scripts/maintain_sources.py --run-scrape-first --apply
```

### Safety Features

- **Dry-run default**: No changes unless `--apply` flag is used
- **Minimal patches**: Only updates relevant fields (selectors, detail_fetch, flags)
- **Never auto-activates**: Hard-blocked sources remain inactive
- **Never deletes**: Sources are never removed, only marked inactive
- **Evidence-backed**: All decisions saved with evidence

### Integration

- **Bulk Validation**: `validate_candidates_bulk.py --use-maintenance-playbooks` reuses playbook logic for partial_needs_detail candidates
- **Smoke Tests**: `smoke_test.py` includes maintenance loop dry-run phase with mtime assertion
- **Runbook**: See `md/NEWSLETTER_INGESTION_RUNBOOK.md` section "Source Maintenance Loop" for detailed documentation

### Acceptance Criteria (Verified)

✅ `python -m compileall backend` passes  
✅ `python backend/scripts/maintain_sources.py --dry-run --max-sources 5` produces run_summary.json  
✅ Dry-run does not modify sources.json (mtime unchanged)  
✅ All degraded items have degradation_class and recommended_playbook  
✅ Evidence folder contains per-source repair evidence

## Next Priorities

1. **Fix Zone Pages** - Make events load correctly (Plan 1)
2. **Add More Sources** - Expand coverage (Plan 2)
3. **Polish Frontend** - Complete redesign (Plan 3)
4. **User Accounts** - Enable personalization
5. **AI Recommendations** - Enhanced ranking

---

## Detailed Plans

For detailed implementation plans, troubleshooting guides, and comprehensive documentation, see:
- **README_FULL.md** - Complete documentation with all implementation details, troubleshooting guides, and historical context

**Key Sections in README_FULL.md**:
- **Zone Pages Fix Plan**: Complete fix implementation for event loading
- **Source Expansion Plan**: Detailed guide for adding new sources (associations, central banks, think tanks, academic, conferences)
- **Frontend Redesign**: Complete UI/UX design specification
- **Troubleshooting Guides**: Solutions for blocked sources, JS-rendered pages, 404 errors
- **Adapter Implementation Guides**: Step-by-step for each adapter type (JSON-LD, RSS, HTML, Playwright, etc.)
