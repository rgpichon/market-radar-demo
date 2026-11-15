# Newsletter → Event Discovery Improvement Plan

## Problem Analysis

### Issue 1: Wrong Links Discovered
**Current State:**
- Discovery finds general newsletter signup pages (e.g., `/newsletters`, `/subscribe`)
- These lead to generic email newsletters, not event/webinar registration
- We need **event registration pages** that send invitations to specific webinars/conferences

**What We Need:**
- Pages with event calendars
- Webinar registration pages
- Conference/roundtable signup pages
- Event notification preferences (not general newsletters)

### Issue 2: File Sprawl
**Current State:**
- Multiple redundant scripts (auto_subscribe_all.py, run_automated_subscription.py, run_full_newsletter_workflow.py, run_subscription_loop.py)
- Multiple markdown files (SUBSCRIPTION_GUIDE.md, plus runbook)
- Discovery scripts that find wrong targets

## Solution Plan

### Phase 1: Improve Discovery to Find Event Pages (NOT General Newsletters)

**1.1 Update Discovery Keywords**
- **Remove/Deprioritize**: `newsletter`, `subscribe`, `email alerts` (too generic)
- **Prioritize**: `webinar`, `event registration`, `conference`, `calendar`, `roundtable`, `briefing`
- **Add URL patterns**: `/events/register`, `/webinar/register`, `/conference/registration`, `/calendar`, `/upcoming-events`

**1.2 Add Event-Specific Discovery Logic**
- Look for pages with event listings (not just signup forms)
- Prioritize pages that show multiple events with registration links
- Score higher for pages with dates/times visible
- Prefer pages with "Register" or "RSVP" buttons over "Subscribe" buttons

**1.3 Update Seed URLs**
- Instead of generic `/insights` or `/research`, use:
  - `/events`
  - `/webinars`
  - `/conferences`
  - `/calendar`
  - `/client-events`
  - `/market-outlook-events`

### Phase 2: File Cleanup

**2.1 Consolidate Subscription Scripts**
- Keep: `subscribe_newsletters.py` (core)
- Keep: `run_subscription_loop.py` (orchestration)
- Delete: `auto_subscribe_all.py` (redundant)
- Delete: `run_automated_subscription.py` (redundant)
- Delete: `run_full_newsletter_workflow.py` (redundant)

**2.2 Consolidate Documentation**
- Keep: `md/NEWSLETTER_INGESTION_RUNBOOK.md` (single source of truth)
- Delete: `SUBSCRIPTION_GUIDE.md` (merge into runbook if needed)

**2.3 Archive/Remove Unused Discovery Scripts**
- Review: `discover_bulge_brackets.py`, `discover_bank_assets.py`, `discover_bank_third_party.py`
- If not used for newsletter workflow, move to archive or delete

### Phase 3: Refocus Discovery Strategy

**3.1 Two-Tier Discovery**
1. **Tier 1**: Event registration pages (webinars, conferences, roundtables)
   - These send individual event invitations
   - Higher priority for macro-signal events
   
2. **Tier 2**: Event notification preferences (if Tier 1 fails)
   - Pages to opt-in to event notifications
   - Still better than general newsletters

**3.2 Better Scoring**
- Event registration page: Score 200
- Event calendar with registration: Score 150
- Event notification preferences: Score 100
- General newsletter signup: Score 50 (low priority)

**3.3 Validation**
- After discovery, validate that page actually shows events/webinars
- Check for event listings, dates, registration buttons
- Reject pages that are just generic newsletter signups

## Implementation Steps

### Step 1: Update Discovery Keywords & Patterns
- Modify `discover_signup_pages.py` to prioritize event-related keywords
- Add event-specific URL patterns
- Update scoring to deprioritize generic newsletters

### Step 2: Update Seed URLs in newsletter_targets.json
- Replace generic seed URLs with event-specific paths
- Add `/events`, `/webinars`, `/conferences` paths for each bank

### Step 3: Add Event Page Validation
- After discovery, fetch page and check for event indicators
- Reject pages that don't show events/webinars

### Step 4: Clean Up Files
- Delete redundant scripts
- Consolidate documentation
- Update runbook with new discovery strategy

### Step 5: Re-run Discovery
- Run discovery with new keywords/patterns
- Validate discovered pages are event-focused
- Update targets with better signup URLs

## Expected Outcome

After improvements:
- Discovery finds event registration pages (not general newsletters)
- Signup URLs lead to pages that send event invitations
- Gmail ingestion extracts actual webinar/conference invitations
- Cleaner codebase with focused scripts

## Files Modified

1. ✅ `backend/scripts/discover_signup_pages.py` - Updated keywords, patterns, scoring, added validation
2. ✅ `backend/newsletter_targets.json` - Updated seed URLs to event-specific paths
3. ✅ Deleted redundant scripts: `auto_subscribe_all.py`, `run_automated_subscription.py`, `run_full_newsletter_workflow.py`, `SUBSCRIPTION_GUIDE.md`
4. ✅ Updated `md/NEWSLETTER_INGESTION_RUNBOOK.md` with new discovery strategy

## Next Steps

1. **Re-run discovery** with new event-focused seed URLs:
   ```bash
   python backend/scripts/discover_signup_pages.py --priority p0 --apply
   ```

2. **Verify discovered pages** are event-focused (not generic newsletters)

3. **Update signup URLs** in targets if better event pages are found

4. **Test subscription** to event registration pages (should send event invitations, not general newsletters)
