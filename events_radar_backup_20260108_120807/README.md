# Market Events Radar MVP v1

A personal "Market Events Radar" that scrapes curated sources for firm events/webinars, stores them in a local SQLite database, and provides a simple web interface with notifications for new matches.

## Features

- **Scraping**: Extracts events from firm event/webinar pages using three adapter types:
  - `json_ld`: Parses JSON-LD structured data
  - `html_list`: Uses CSS selectors to extract events from HTML lists
  - `json_api`: Fetches JSON from API endpoints and extracts events using configurable paths
- **Database**: SQLite storage with automatic deduplication
- **Notifications**: Creates notifications only for NEW events that match user preferences
- **Web UI**: Simple, clean interface with white background
- **Filtering**: Search, date filtering, and days-ahead filtering
- **Chronological Ordering**: Events sorted by date (upcoming first), undated items at bottom

## Project Structure

```
events_radar_mvp_v1/
├── backend/
│   ├── app.py                 # Flask server
│   ├── db.py                  # Database schema and helpers
│   ├── scrape_runner.py       # Scraping orchestration
│   ├── sources.json           # Curated sources list
│   ├── preferences.json       # User preferences
│   ├── packs.json             # Firm pack definitions
│   ├── adapters/
│   │   ├── html_list.py       # HTML list extractor
│   │   ├── json_ld.py         # JSON-LD extractor
│   │   └── json_api.py        # JSON API extractor
│   ├── utils/
│   │   ├── normalize.py       # String/URL normalization
│   │   ├── dates.py           # Date parsing
│   │   ├── json_path.py       # JSON path extraction
│   │   ├── event_filter.py    # Event-likeness filtering
│   │   └── postprocess.py     # Per-source post-processing
│   └── scripts/
│       ├── run_scrape.py      # CLI scrape runner
│       └── test_source.py     # Debug single source
└── frontend/
    ├── index.html             # Main UI
    ├── styles.css             # Styling
    └── app.js                 # Frontend logic
```

## Setup

### 1. Create Virtual Environment

```bash
cd events_radar_mvp_v1
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install flask requests beautifulsoup4 python-dateutil
```

### 3. Run the Application

```bash
cd backend
python app.py
```

The application will:
- Auto-create the SQLite database (`events.db`) if it doesn't exist
- Load sources from `sources.json`
- Start the Flask server on `http://127.0.0.1:5000`

**IMPORTANT: How to Open the UI**

✅ **CORRECT**: Open your browser and navigate to:
```
http://127.0.0.1:5000
```

❌ **WRONG**: Do NOT open `frontend/index.html` directly from the filesystem (file://)

If you see "file://" in your browser's address bar, you opened it incorrectly. The app requires the Flask server to handle API requests. If you open the HTML file directly, you'll see a warning banner explaining that you need to use the Flask server.

### Troubleshooting

**Problem**: UI shows "Loading..." forever or "Error loading events"
- **Solution**: Make sure you opened `http://127.0.0.1:5000` (not file://)
- Check that `python app.py` is running in the backend directory
- Check browser console (F12) for API errors

**Problem**: See "file://" in the address bar
- **Solution**: You opened the HTML file directly. Close it and open `http://127.0.0.1:5000` instead

## Usage

### Running Scrapes

**Via UI:**
- Click the "Run scrape now" button in the Events tab

**Via CLI:**
```bash
cd backend
python scripts/run_scrape.py
```

### Testing a Single Source

```bash
cd backend
python scripts/test_source.py <source_id> [N]
```

Example:
```bash
python scripts/test_source.py cme_events 10
```

This will test the `cme_events` source and display the first 10 extracted events.

### Analyzing Page Structure

To get hints for deriving CSS selectors:

```bash
cd backend
python scripts/test_source.py <source_id> --print-selectors-hints
```

This prints:
- Page title and first H1
- Count of links on the page
- Top 15 most common CSS classes
- Potential event container patterns
- Sample card/article structure

---

## Source Onboarding Checklist

Follow these steps to add and verify a new source:

### Step 1: Add Source to sources.json

Add an entry with estimated selectors:

```json
{
  "id": "my_new_source",
  "firm_name": "Firm Name",
  "firm_type": "Exchange",
  "url": "https://example.com/events",
  "adapter_type": "html_list",
  "selectors_json": {
    "item_selector": ".event-card",
    "title_selector": "h3",
    "link_selector": "a",
    "date_selector": ".date"
  },
  "default_tags_json": ["Macro"],
  "active": 1
}
```

### Step 2: Run test_source with Hints

```bash
cd backend
python scripts/test_source.py my_new_source --print-selectors-hints
```

Look for:
- Common class names containing "event", "card", "item", "article"
- The structure of repeating containers

### Step 3: If 0 Results, Refine Selectors

Run without hints to see diagnostics:

```bash
python scripts/test_source.py my_new_source
```

If 0 events:
1. Open the URL in a browser
2. Inspect the HTML (right-click → Inspect)
3. Find the repeating event cards/items
4. Update `item_selector` to match them (e.g., `.card`, `article`, `.event-item`)
5. Find title, link, and date elements within each item
6. Update selectors in `sources.json`

### Step 4: Verify ≥3 Events

Rerun until you get results:

```bash
python scripts/test_source.py my_new_source 10
```

You should see:
- `Events found: X` where X ≥ 3
- Listed events with firm, title, date, link

### Step 5: Run Full Scrape and Check UI

```bash
python scripts/run_scrape.py
```

Then start the app:
```bash
python app.py
```

Open `http://127.0.0.1:5000` and verify events appear in the Events tab.

### Common Issues

| Issue | Solution |
|-------|----------|
| 0 events, HTML fetched | Wrong `item_selector` - use browser inspector |
| Request error | URL may require auth or be blocked |
| Events found but no links | Check `link_selector` or ensure items have `<a href>` |
| Wrong firm name | Verify `firm_name` matches exactly in source config |

---

## Adding a Source

Edit `backend/sources.json` and add a new source object:

```json
{
  "id": "unique_source_id",
  "firm_name": "Firm Name",
  "firm_type": "Investment Bank",
  "url": "https://example.com/events",
  "adapter_type": "html_list",
  "selectors_json": {
    "item_selector": ".event-item",
    "title_selector": "h3",
    "link_selector": "a.event-link",
    "date_selector": ".date"
  },
  "default_tags_json": ["Macro", "Rates"],
  "active": 1
}
```

### Adapter Types

**html_list:**
- `item_selector` (required): CSS selector for each event item
- `title_selector` (required): CSS selector for event title within item
- `link_selector` (optional): CSS selector for link; if missing, tries to find link in title element
- `date_selector` (optional): CSS selector for date

**json_ld:**
- No selectors needed; automatically extracts events from `<script type="application/ld+json">` tags

**json_api:**
- `api_config` (required): JSON configuration for API extraction:
  - `endpoint`: API URL to fetch (if different from `url`)
  - `items_path`: JSON path to array of items (e.g., "results", "data.items")
  - `title_path`: Path within each item to title field
  - `link_path`: Path to URL/link field
  - `date_path`: Path to date field (optional)
  - `base_url`: Base URL for relative links

## Event Sorting

Events are displayed in **chronological order** (upcoming first):

1. **Primary sort**: Events with dates sorted by `date_time` ascending
2. **Secondary sort**: For same date: by `firm_name` ascending
3. **Undated items**: Always shown at the bottom, sorted by `last_seen` descending (most recent first)

## Notifications

Notifications are created **only for NEW events** that match your preferences.

### Notification Match Logic

A new event triggers a notification if:
1. Event is "confirmed" (has `date_time` and `link`) OR `require_confirmed_for_notifications` is `false`
2. AND at least one of:
   - `firm_name` is in `follow_firms`
   - `firm_name` is in any firm from `follow_packs`
   - Event tags intersect with `follow_tags`

### Configuring Preferences

Edit `backend/preferences.json`:

```json
{
  "follow_firms": ["JPMorgan", "Goldman Sachs"],
  "follow_packs": ["bulge_brackets"],
  "follow_tags": ["Rates", "FX", "Macro"],
  "require_confirmed_for_notifications": true
}
```

### Packs

Edit `backend/packs.json` to define firm packs:

```json
{
  "bulge_brackets": {
    "display_name": "Bulge Brackets",
    "firms": ["JPMorgan", "Goldman Sachs", "Morgan Stanley"],
    "default_tags": ["Macro", "Rates"]
  }
}
```

## API Endpoints

- `GET /api/events` - Get events with filtering
  - Query params: `q` (search), `firm`, `with_date` (0/1), `days_ahead`
- `GET /api/notifications` - Get all notifications
- `POST /api/notifications/mark_seen` - Mark notifications as seen
  - Body: `{ "notification_ids": [1,2,3] }`
- `POST /api/scrape` - Run scrape immediately
- `GET /api/preferences` - Get current preferences (read-only)

## Database Schema

**sources:**
- `id`, `firm_name`, `firm_type`, `url`, `adapter_type`, `selectors_json`, `default_tags_json`, `active`

**events:**
- `id` (hash), `firm_name`, `event_name`, `date_time`, `link`, `source_id`, `tags_json`, `first_seen`, `last_seen`

**notifications:**
- `id`, `event_id`, `created_at`, `reason`, `seen`

Event deduplication uses a hash of: `normalize(firm_name) + normalize(event_name) + (date_time or "") + normalize(link)`

## Notes

- The database file (`events.db`) is created automatically in the `backend/` directory
- Sources with `active: 0` are skipped during scraping
- Scraping failures for one source don't stop the entire run
- The UI loads even if no events exist yet
- All dates are stored in ISO format (UTC)

