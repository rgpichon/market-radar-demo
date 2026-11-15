// Global error handler - keep for debugging
window.onerror = function(msg, url, line) {
    console.error("JS ERROR:", msg, "at", url, "line", line);
    const debugDiv = document.getElementById('debugStatus');
    if (debugDiv) {
        debugDiv.textContent = "JS ERROR: " + msg + " at line " + line;
        debugDiv.style.display = "block";
        debugDiv.style.cssText = "display: block; background: red; color: white; padding: 10px; margin: 10px;";
    }
};

// Configuration
const FILE_MODE = window.location.protocol === 'file:';
const API_BASE = FILE_MODE ? null : (new URLSearchParams(window.location.search).get('apiBase') || '');

// State
let currentTab = 'events';
let events = [];
let notifications = [];
let meta = { last_scrape_at: null, total_events: 0 };
let allTags = new Set(); // For tag filter
let allFirms = new Set(); // For firm filter
let selectedFirms = new Set(); // Selected firm names
let currentView = 'list'; // Phase 2: Calendar view (Priority 6, Phase 2)
let calendar = null; // Phase 2: Calendar instance
let selectedTags = new Set(); // Phase 3: Selected tags (Priority 6, Phase 3)
let currentTopic = 'all'; // Phase 1: Topic navigation (Priority 7, Phase 1)
let topics = []; // Phase 1: Topics list (Priority 7, Phase 1)
let selectedZone3Topic = null; // 4-Zone Architecture: Currently selected topic in Zone 3

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Check if running in file:// mode
    if (FILE_MODE) {
        showFileModeBanner();
        disableActions();
        return; // Don't initialize normal functionality
    }
    
    setupTabs();
    
    // Check if we're on a zone page or homepage
    const isHomepage = window.location.pathname === '/' || window.location.pathname === '/index.html' || window.location.pathname === '';
    const isZonePage = window.location.pathname.startsWith('/zone');
    
    if (isHomepage) {
        // Homepage: Load previews only
        // Ensure DOM is ready before loading previews
        if (document.getElementById('zone1-preview')) {
            loadHomepagePreviews();
        } else {
            // Wait for DOM to be ready
            setTimeout(() => {
                if (document.getElementById('zone1-preview')) {
                    loadHomepagePreviews();
                } else {
                    console.error('Zone preview containers not found');
                }
            }, 100);
        }
    } else {
        // Zone pages and other pages: Setup full functionality
        setupEventsTab();
        setupNotificationsTab();
        setupSettingsTab();
        
        // Only run homepage zone loading if NOT on a zone page
        if (!isZonePage) {
            initZones();
        }
        // Zone pages handle their own initialization via initializeZonePage()
    }
    
    // Load meta and notifications (always needed)
    loadMeta();
    loadNotifications();
    
    // Phase 2: Initialize view toggle (Priority 6, Phase 2)
    initViewToggle();
    
    // Phase 3: Initialize tag filter (Priority 6, Phase 3)
    setupTagFilter();
    
    // Phase 4: Initialize saved searches (Priority 6, Phase 4)
    initSavedSearches();
    
    // Phase 5: Initialize export buttons (Priority 6, Phase 5)
    initExportButtons();
    
    // Phase 6: Initialize theme toggle (Priority 6, Phase 6)
    initThemeToggle();
    
    // Phase 1: Initialize topic navigation (Priority 7, Phase 1) - for Zone 3
    loadTopics();
    
    // Phase 3: Initialize filter groups (Priority 8, Phase 3)
    initFilterGroups();
});

function showFileModeBanner() {
    const banner = document.createElement('div');
    banner.id = 'file-mode-banner';
    banner.style.cssText = 'background-color: #ff6b6b; color: white; padding: 20px; margin: 0; text-align: center; font-weight: bold;';
    banner.innerHTML = `
        <p style="margin: 0 0 10px 0; font-size: 16px;">
            Warning: This page was opened from a file path (file://)
        </p>
        <p style="margin: 0; font-size: 14px;">
            The app must be opened via the Flask server. Start <code>backend/app.py</code> and open <a href="http://127.0.0.1:5000/" style="color: white; text-decoration: underline;">http://127.0.0.1:5000/</a>
        </p>
    `;
    document.body.insertBefore(banner, document.body.firstChild);
    
    // Replace all loading states with error message
    document.getElementById('events-list').innerHTML = '<p class="error">Cannot load: opened via file://. Use Flask server.</p>';
    document.getElementById('notifications-list').innerHTML = '<p class="error">Cannot load: opened via file://. Use Flask server.</p>';
    document.getElementById('settings-content').innerHTML = '<p class="error">Cannot load: opened via file://. Use Flask server.</p>';
}

function disableActions() {
    const runScrapeBtn = document.getElementById('run-scrape-btn');
    const markAllSeenBtn = document.getElementById('mark-all-seen-btn');
    
    if (runScrapeBtn) {
        runScrapeBtn.disabled = true;
        runScrapeBtn.textContent = 'Not available (file:// mode)';
        runScrapeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            alert('This app must be run via the Flask server. Start backend/app.py and open http://127.0.0.1:5000/');
        });
    }
    
    if (markAllSeenBtn) {
        markAllSeenBtn.disabled = true;
        markAllSeenBtn.textContent = 'Not available (file:// mode)';
    }
}

function apiUrl(path) {
    if (FILE_MODE) {
        throw new Error('API calls not available in file:// mode');
    }
    // If API_BASE is empty, just return the path (relative URL works)
    return API_BASE ? `${API_BASE}${path}` : path;
}

async function fetchWithErrorHandling(url, options = {}) {
    try {
        console.log(`[API] Fetching: ${url}`);
        const response = await fetch(url, options);
        console.log(`[API] Response: ${response.status} ${response.statusText}`);
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 200)}`);
        }
        
        const data = await response.json();
        console.log(`[API] Success: ${url}`);
        return data;
    } catch (error) {
        console.error(`[API] Error: ${url}`, error);
        throw error;
    }
}

// Tab switching
function setupTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tab = button.dataset.tab;
            switchTab(tab);
        });
    });
}

function switchTab(tab) {
    currentTab = tab;
    
    // Update buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    
    // Update content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tab}-tab`);
    });
    
    // Reload data if needed
    if (tab === 'events') {
        loadEvents();
    } else if (tab === 'notifications') {
        loadNotifications();
    } else if (tab === 'settings') {
        loadSettings();
    }
}

// Events tab
function setupEventsTab() {
    const searchInput = document.getElementById('search-input');
    const withDateCheckbox = document.getElementById('with-date-checkbox');
    const daysAheadSelect = document.getElementById('days-ahead-select');
    const runScrapeBtn = document.getElementById('run-scrape-btn');
    
    // Set defaults: dated events only, 365 days
    withDateCheckbox.checked = true;
    daysAheadSelect.value = '365';
    
    // Debounce search
    let searchTimeout;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            loadEvents();
        }, 300);
    });
    
    withDateCheckbox.addEventListener('change', () => {
        loadEvents();
    });
    
    daysAheadSelect.addEventListener('change', () => {
        loadEvents();
    });
    
    runScrapeBtn.addEventListener('click', async () => {
        runScrapeBtn.disabled = true;
        const originalText = runScrapeBtn.textContent;
        runScrapeBtn.textContent = 'Scraping...';
        
        const statusDiv = document.createElement('div');
        statusDiv.className = 'success';
        statusDiv.style.marginBottom = '10px';
        const eventsList = document.getElementById('events-list');
        eventsList.insertBefore(statusDiv, eventsList.firstChild);
        statusDiv.textContent = 'Running scrape...';
        
        try {
            const data = await fetchWithErrorHandling(apiUrl('/api/scrape'), { method: 'POST' });
            
            if (data.status === 'success') {
                statusDiv.className = 'success';
                statusDiv.textContent = `Scrape completed: ${data.inserted_count} inserted, ${data.updated_count} updated, ${data.notifications_created} notifications created`;
                await loadMeta();
                await loadUserEvents();
                loadEvents();
                loadNotifications();
            } else {
                statusDiv.className = 'error';
                statusDiv.textContent = `Error: ${data.message || 'Unknown error'}`;
            }
        } catch (error) {
            statusDiv.className = 'error';
            statusDiv.textContent = `Error: ${error.message}`;
        } finally {
            runScrapeBtn.disabled = false;
            runScrapeBtn.textContent = originalText;
            setTimeout(() => {
                if (statusDiv.parentNode) {
                    statusDiv.remove();
                }
            }, 10000);
        }
    });
    
    // Format filter
    const formatFilter = document.getElementById('format-filter');
    if (formatFilter) {
        formatFilter.addEventListener('change', () => {
            loadEvents();
        });
    }
    
    // Theme filter (populated dynamically)
    const themeFilter = document.getElementById('theme-filter');
    if (themeFilter) {
        themeFilter.addEventListener('change', () => {
            loadEvents();
        });
    }
    
    // Type filter
    const typeFilter = document.getElementById('type-filter');
    if (typeFilter) {
        typeFilter.addEventListener('change', () => {
            loadEvents();
        });
    }
    
    // Signal filter
    const signalFilter = document.getElementById('signal-filter');
    if (signalFilter) {
        signalFilter.addEventListener('change', () => {
            loadEvents();
        });
    }
    
    // Sort select
    const sortSelect = document.getElementById('sort-select');
    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            loadEvents();
        });
    }
    
    
    // Firm filter
    setupFirmFilter();
}

function setupFirmFilter() {
    const firmFilterBtn = document.getElementById('firm-filter-btn');
    const firmFilterDropdown = document.getElementById('firm-filter-dropdown');
    const firmSelectAll = document.getElementById('firm-select-all');
    const firmClearAll = document.getElementById('firm-clear-all');
    
    if (!firmFilterBtn || !firmFilterDropdown) return;
    
    // Toggle dropdown
    firmFilterBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isVisible = firmFilterDropdown.style.display !== 'none';
        firmFilterDropdown.style.display = isVisible ? 'none' : 'block';
    });
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!firmFilterDropdown.contains(e.target) && e.target !== firmFilterBtn) {
            firmFilterDropdown.style.display = 'none';
        }
    });
    
    // Select all
    if (firmSelectAll) {
        firmSelectAll.addEventListener('click', () => {
            selectedFirms = new Set(allFirms);
            updateFirmFilterUI();
            loadEvents();
        });
    }
    
    // Clear all
    if (firmClearAll) {
        firmClearAll.addEventListener('click', () => {
            selectedFirms.clear();
            updateFirmFilterUI();
            loadEvents();
        });
    }
}

function updateFirmFilterUI() {
    const firmFilterBtn = document.getElementById('firm-filter-btn');
    const firmFilterChecklist = document.getElementById('firm-filter-checklist');
    
    if (!firmFilterBtn || !firmFilterChecklist) return;
    
    // Update button text
    if (selectedFirms.size === 0) {
        firmFilterBtn.textContent = 'Firms: All';
    } else if (selectedFirms.size === 1) {
        firmFilterBtn.textContent = `Firms: ${Array.from(selectedFirms)[0]}`;
    } else {
        firmFilterBtn.textContent = `Firms: ${selectedFirms.size} selected`;
    }
    
    // Update checklist
    firmFilterChecklist.innerHTML = '';
    Array.from(allFirms).sort().forEach(firm => {
        const item = document.createElement('div');
        item.className = 'firm-filter-item';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = firm;
        checkbox.checked = selectedFirms.has(firm);
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedFirms.add(firm);
            } else {
                selectedFirms.delete(firm);
            }
            updateFirmFilterUI();
            loadEvents();
        });
        item.appendChild(checkbox);
        item.appendChild(document.createTextNode(firm));
        firmFilterChecklist.appendChild(item);
    });
}

async function loadMeta() {
    try {
        meta = await fetchWithErrorHandling(apiUrl('/api/meta'));
        updateStatusBar();
    } catch (error) {
        console.error("loadMeta error:", error);
    }
}


function updateStatusBar() {
    const statusBar = document.getElementById('status-bar');
    if (!statusBar) return;
    
    const count = events.length;
    let statusText = `Showing ${count} event${count !== 1 ? 's' : ''}`;
    
    if (meta.last_scrape_at) {
        const lastScrape = new Date(meta.last_scrape_at);
        const timeAgo = formatTimeAgo(lastScrape);
        statusText += ` • Last updated: ${timeAgo}`;
    }
    
    statusBar.textContent = statusText;
}

function formatTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
}


async function loadEvents() {
    const searchInput = document.getElementById('search-input');
    const withDateCheckbox = document.getElementById('with-date-checkbox');
    const daysAheadSelect = document.getElementById('days-ahead-select');
    const formatFilter = document.getElementById('format-filter');
    const themeFilter = document.getElementById('theme-filter');
    const typeFilter = document.getElementById('type-filter');
    const signalFilter = document.getElementById('signal-filter');
    const sortSelect = document.getElementById('sort-select');
    const dateStart = document.getElementById('date-start');
    const dateEnd = document.getElementById('date-end');
    const eventsList = document.getElementById('events-list');
    
    if (currentView === 'list') {
        eventsList.innerHTML = '<p class="loading">Loading events...</p>';
    }
    
    try {
        const params = new URLSearchParams();
        const q = searchInput.value.trim();
        if (q) {
            params.append('q', q);
        }
        
        // Firm filter (multi-select)
        if (selectedFirms.size > 0) {
            params.append('firms', Array.from(selectedFirms).join(','));
        }
        
        // Phase 1: Topic filter (Priority 7, Phase 1)
        if (currentTopic && currentTopic !== 'all') {
            const topicName = topics.find(t => t.slug === currentTopic)?.name;
            if (topicName) {
                // Add to tags filter (events can have multiple tags)
                if (selectedTags.size > 0) {
                    selectedTags.add(topicName);
                } else {
                    selectedTags = new Set([topicName]);
                }
            }
        }
        
        // Phase 3: Tag filter (Priority 6, Phase 3)
        if (selectedTags.size > 0) {
            params.append('tags', Array.from(selectedTags).join(','));
        }
        
        // Phase 3: Date range filter (Priority 6, Phase 3)
        if (dateStart && dateStart.value) {
            params.append('date_start', dateStart.value);
        }
        if (dateEnd && dateEnd.value) {
            params.append('date_end', dateEnd.value);
        }
        
        params.append('with_date', withDateCheckbox.checked ? '1' : '0');
        params.append('days_ahead', daysAheadSelect.value);
        
        // Signal score filter (PHASE 6)
        if (signalFilter && signalFilter.value) {
            params.append('min_signal_score', signalFilter.value);
        }
        
        const url = apiUrl(`/api/events?${params}`);
        let fetchedEvents = await fetchWithErrorHandling(url);
        
        // Client-side filters (format, theme, type)
        if (formatFilter && formatFilter.value) {
            fetchedEvents = fetchedEvents.filter(e => e.format === formatFilter.value);
        }
        if (themeFilter && themeFilter.value) {
            fetchedEvents = fetchedEvents.filter(e => {
                const tags = e.tags_json || [];
                return tags.includes(themeFilter.value);
            });
        }
        if (typeFilter && typeFilter.value) {
            fetchedEvents = fetchedEvents.filter(e => e.intel_type === typeFilter.value);
        }
        
        // Client-side sorting (PHASE 5)
        if (sortSelect && sortSelect.value) {
            fetchedEvents = sortEvents(fetchedEvents, sortSelect.value);
        }
        
        events = fetchedEvents;
        
        // Update firm filter options (collect from all fetched events)
        updateFirmFilter();
        
        // Update theme filter options
        updateThemeFilter();
        
        // Phase 2: Update view based on current view mode (Priority 6, Phase 2)
        if (currentView === 'list') {
            renderEvents();
        } else if (calendar) {
            calendar.updateEvents(events);
        }
        
        // Phase 3: Update tag filter (Priority 6, Phase 3)
        updateTagFilter();
        
        updateStatusBar();
    } catch (error) {
        console.error("loadEvents error:", error);
        eventsList.innerHTML = `<p class="error">Error loading events: ${error.message}</p>`;
        events = [];
    }
}

function updateFirmFilter() {
    // Collect all unique firm names from events
    allFirms.clear();
    events.forEach(e => {
        if (e.firm_name) {
            allFirms.add(e.firm_name);
        }
    });
    
    // Update firm filter UI
    updateFirmFilterUI();
}

function updateThemeFilter() {
    const themeFilter = document.getElementById('theme-filter');
    if (!themeFilter) return;
    
    // Collect all unique tags from current events (primary themes: Macro, Geopolitics, Markets)
    const primaryThemes = new Set(['Macro', 'Geopolitics', 'Markets', 'Rates', 'FX', 'Credit', 'Equities', 'Commodities']);
    const allThemes = new Set();
    
    events.forEach(e => {
        const tags = e.tags_json || [];
        tags.forEach(tag => {
            if (primaryThemes.has(tag)) {
                allThemes.add(tag);
            }
        });
    });
    
    // Update dropdown (keep "All Themes" option)
    const currentValue = themeFilter.value;
    themeFilter.innerHTML = '<option value="">All Themes</option>';
    Array.from(allThemes).sort().forEach(theme => {
        const option = document.createElement('option');
        option.value = theme;
        option.textContent = theme;
        if (theme === currentValue) {
            option.selected = true;
        }
        themeFilter.appendChild(option);
    });
}

// Phase 2: Calendar View (Priority 6, Phase 2)
class EventCalendar {
    constructor(containerId, events) {
        this.containerId = containerId;
        this.events = events;
        this.calendar = null;
        this.init();
    }
    
    init() {
        const calendarEl = document.getElementById(this.containerId);
        if (!calendarEl) return;
        
        this.calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek'
            },
            events: this.formatEventsForCalendar(this.events),
            eventClick: (info) => {
                this.showEventDetails(info.event);
            },
            eventColor: '#0d7ea8'
        });
        
        this.calendar.render();
    }
    
    formatEventsForCalendar(events) {
        return events.map(event => {
            const date = event.date_time ? new Date(event.date_time) : null;
            return {
                id: event.id,
                title: event.event_name,
                start: date ? date.toISOString() : null,
                url: event.link,
                extendedProps: {
                    firm_name: event.firm_name,
                    description: event.description,
                    location: event.location_city || event.location_text
                }
            };
        }).filter(event => event.start !== null);
    }
    
    updateEvents(events) {
        this.events = events;
        if (this.calendar) {
            this.calendar.removeAllEvents();
            this.calendar.addEventSource(this.formatEventsForCalendar(events));
        }
    }
    
    showEventDetails(event) {
        const details = `Event: ${event.title}\nFirm: ${event.extendedProps.firm_name}\n${event.extendedProps.description ? 'Description: ' + event.extendedProps.description.substring(0, 100) + '...' : ''}`;
        alert(details);
    }
}

function initViewToggle() {
    const listViewBtn = document.getElementById('list-view-btn');
    const calendarViewBtn = document.getElementById('calendar-view-btn');
    
    if (listViewBtn && calendarViewBtn) {
        listViewBtn.addEventListener('click', () => switchToView('list'));
        calendarViewBtn.addEventListener('click', () => switchToView('calendar'));
    }
}

function switchToView(view) {
    currentView = view;
    const listContainer = document.getElementById('events-list');
    const calendarContainer = document.getElementById('calendar-container');
    const listViewBtn = document.getElementById('list-view-btn');
    const calendarViewBtn = document.getElementById('calendar-view-btn');
    
    if (view === 'list') {
        if (listContainer) listContainer.style.display = 'block';
        if (calendarContainer) calendarContainer.style.display = 'none';
        if (listViewBtn) listViewBtn.classList.add('active');
        if (calendarViewBtn) calendarViewBtn.classList.remove('active');
    } else {
        if (listContainer) listContainer.style.display = 'none';
        if (calendarContainer) calendarContainer.style.display = 'block';
        if (calendarViewBtn) calendarViewBtn.classList.add('active');
        if (listViewBtn) listViewBtn.classList.remove('active');
        
        // Initialize calendar if not already done
        if (!calendar && calendarContainer) {
            calendar = new EventCalendar('calendar-container', events);
        } else if (calendar) {
            calendar.updateEvents(events);
        }
    }
}

// Phase 3: Advanced Filters - Tag Filter (Priority 6, Phase 3)
function setupTagFilter() {
    const tagFilterBtn = document.getElementById('tag-filter-btn');
    const tagFilterDropdown = document.getElementById('tag-filter-dropdown');
    const dateStart = document.getElementById('date-start');
    const dateEnd = document.getElementById('date-end');
    
    if (tagFilterBtn && tagFilterDropdown) {
        tagFilterBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isVisible = tagFilterDropdown.style.display !== 'none';
            tagFilterDropdown.style.display = isVisible ? 'none' : 'block';
        });
        
        document.addEventListener('click', (e) => {
            if (!tagFilterDropdown.contains(e.target) && e.target !== tagFilterBtn) {
                tagFilterDropdown.style.display = 'none';
            }
        });
    }
    
    if (dateStart) {
        dateStart.addEventListener('change', () => loadEvents());
    }
    if (dateEnd) {
        dateEnd.addEventListener('change', () => loadEvents());
    }
}

function updateTagFilter() {
    const tagFilterDropdown = document.getElementById('tag-filter-dropdown');
    const tagFilterBtn = document.getElementById('tag-filter-btn');
    if (!tagFilterDropdown || !tagFilterBtn) return;
    
    // Collect all unique tags
    allTags.clear();
    events.forEach(e => {
        const tags = e.tags_json || [];
        tags.forEach(tag => allTags.add(tag));
    });
    
    // Update button text
    if (selectedTags.size === 0) {
        tagFilterBtn.textContent = 'Tags: All';
    } else if (selectedTags.size === 1) {
        tagFilterBtn.textContent = `Tags: ${Array.from(selectedTags)[0]}`;
    } else {
        tagFilterBtn.textContent = `Tags: ${selectedTags.size} selected`;
    }
    
    // Update dropdown
    tagFilterDropdown.innerHTML = '';
    Array.from(allTags).sort().forEach(tag => {
        const item = document.createElement('div');
        item.className = 'tag-filter-item';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = tag;
        checkbox.checked = selectedTags.has(tag);
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                selectedTags.add(tag);
            } else {
                selectedTags.delete(tag);
            }
            updateTagFilter();
            loadEvents();
        });
        item.appendChild(checkbox);
        item.appendChild(document.createTextNode(tag));
        tagFilterDropdown.appendChild(item);
    });
}

// Phase 4: Saved Searches (Priority 6, Phase 4)
function initSavedSearches() {
    const saveSearchBtn = document.getElementById('save-search-btn');
    const savedSearchesList = document.getElementById('saved-searches-list');
    const deleteSearchBtn = document.getElementById('delete-search-btn');
    
    if (saveSearchBtn) {
        saveSearchBtn.addEventListener('click', saveCurrentSearch);
    }
    
    if (savedSearchesList) {
        savedSearchesList.addEventListener('change', (e) => {
            if (e.target.value) {
                loadSavedSearch(e.target.value);
            }
        });
    }
    
    if (deleteSearchBtn) {
        deleteSearchBtn.addEventListener('click', deleteSavedSearch);
    }
    
    updateSavedSearchesList();
}

function saveCurrentSearch() {
    const searchName = prompt('Enter a name for this search:');
    if (!searchName) return;
    
    const filters = getCurrentFilters();
    const savedSearches = getSavedSearches();
    
    savedSearches[searchName] = filters;
    localStorage.setItem('savedSearches', JSON.stringify(savedSearches));
    
    updateSavedSearchesList();
    alert(`Search "${searchName}" saved!`);
}

function getSavedSearches() {
    const stored = localStorage.getItem('savedSearches');
    return stored ? JSON.parse(stored) : {};
}

function loadSavedSearch(searchName) {
    const savedSearches = getSavedSearches();
    const filters = savedSearches[searchName];
    
    if (filters) {
        applySavedFilters(filters);
        loadEvents();
    }
}

function updateSavedSearchesList() {
    const select = document.getElementById('saved-searches-list');
    if (!select) return;
    
    const savedSearches = getSavedSearches();
    
    select.innerHTML = '<option value="">Load saved search...</option>';
    Object.keys(savedSearches).sort().forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
}

function getCurrentFilters() {
    return {
        search: document.getElementById('search-input')?.value || '',
        firms: Array.from(selectedFirms),
        tags: Array.from(selectedTags),
        format: document.getElementById('format-filter')?.value || '',
        date_start: document.getElementById('date-start')?.value || '',
        date_end: document.getElementById('date-end')?.value || '',
        days_ahead: document.getElementById('days-ahead-select')?.value || '365',
        with_date: document.getElementById('with-date-checkbox')?.checked || false
    };
}

function applySavedFilters(filters) {
    if (filters.search) {
        const searchInput = document.getElementById('search-input');
        if (searchInput) searchInput.value = filters.search;
    }
    
    selectedFirms = new Set(filters.firms || []);
    selectedTags = new Set(filters.tags || []);
    
    if (filters.format) {
        const formatFilter = document.getElementById('format-filter');
        if (formatFilter) formatFilter.value = filters.format;
    }
    
    if (filters.date_start) {
        const dateStart = document.getElementById('date-start');
        if (dateStart) dateStart.value = filters.date_start;
    }
    
    if (filters.date_end) {
        const dateEnd = document.getElementById('date-end');
        if (dateEnd) dateEnd.value = filters.date_end;
    }
    
    updateFirmFilterUI();
    updateTagFilter();
}

function deleteSavedSearch() {
    const select = document.getElementById('saved-searches-list');
    if (!select || !select.value) {
        alert('Please select a saved search to delete');
        return;
    }
    
    if (confirm(`Delete saved search "${select.value}"?`)) {
        const savedSearches = getSavedSearches();
        delete savedSearches[select.value];
        localStorage.setItem('savedSearches', JSON.stringify(savedSearches));
        updateSavedSearchesList();
    }
}

// Phase 5: Export Functionality (Priority 6, Phase 5)
function initExportButtons() {
    const exportCsvBtn = document.getElementById('export-csv-btn');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', exportToCSV);
    }
}

function exportToCSV() {
    if (events.length === 0) {
        alert('No events to export');
        return;
    }
    
    // CSV header
    const headers = ['Firm', 'Event Name', 'Date', 'Link', 'Description', 'Location', 'Format', 'Tags'];
    let csv = headers.join(',') + '\n';
    
    // CSV rows
    events.forEach(event => {
        const tags = event.tags_json || [];
        const tagsStr = Array.isArray(tags) ? tags.join('; ') : '';
        const row = [
            escapeCSV(event.firm_name || ''),
            escapeCSV(event.event_name || ''),
            escapeCSV(event.date_time || ''),
            escapeCSV(event.link || ''),
            escapeCSV(event.description || ''),
            escapeCSV(event.location_city || event.location_text || ''),
            escapeCSV(event.format || ''),
            escapeCSV(tagsStr)
        ];
        csv += row.join(',') + '\n';
    });
    
    // Download
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `events_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
}

function escapeCSV(str) {
    if (!str) return '';
    str = String(str).replace(/"/g, '""');
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str}"`;
    }
    return str;
}

// Phase 6: Dark Mode (Priority 6, Phase 6)
function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) return;
    
    const savedTheme = localStorage.getItem('theme') || 'light';
    setTheme(savedTheme);
    
    themeToggle.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        setTheme(newTheme);
    });
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.textContent = theme === 'light' ? '🌙 Dark' : '☀️ Light';
    }
}

// Phase 1: Topic-Based Navigation (Priority 7, Phase 1)
async function loadTopics() {
    try {
        const response = await fetch(apiUrl('/api/topics'));
        topics = await response.json();
        renderTopicNavigation();
    } catch (error) {
        console.error("loadTopics error:", error);
    }
}

function renderTopicNavigation() {
    const select = document.getElementById('topic-filter');
    if (!select) return;
    
    // Clear existing options (keep "All Topics")
    select.innerHTML = '<option value="all">All Topics</option>';
    
    // Add topic options
    topics.forEach(topic => {
        const option = document.createElement('option');
        option.value = topic.slug;
        option.textContent = `${topic.name} (${topic.count})`;
        option.setAttribute('data-topic-name', topic.name);
        select.appendChild(option);
    });
    
    // Set current topic
    if (currentTopic && currentTopic !== 'all') {
        select.value = currentTopic;
    } else {
        select.value = 'all';
    }
    
    // Add change handler (only if not already added)
    const existingHandler = select.getAttribute('data-handler-attached');
    if (!existingHandler) {
        select.addEventListener('change', (e) => {
            const topicSlug = e.target.value;
            switchToTopic(topicSlug);
        });
        select.setAttribute('data-handler-attached', 'true');
    }
}

function switchToTopic(topicSlug) {
    currentTopic = topicSlug;
    
    // Update dropdown value
    const select = document.getElementById('topic-filter');
    if (select) {
        select.value = topicSlug;
    }
    
    // Reload events with topic filter
    loadEvents();
}

// Phase 2: Featured Events & Storylines (Priority 7, Phase 2)
async function loadFeaturedEvents() {
    try {
        const response = await fetch(apiUrl('/api/events/featured?limit=2')); // Phase 2: Reduce to 2
        const featuredEvents = await response.json();
        
        const container = document.getElementById('featured-events');
        const section = document.getElementById('featured-section');
        if (!container || !section) return;
        
        if (featuredEvents.length === 0) {
            section.style.display = 'none';
            return;
        }
        
        section.style.display = 'block';
        // Phase 2: Compact featured cards
        container.innerHTML = featuredEvents.map(event => {
            const dateStr = event.date_time ? formatDate(event.date_time) : '';
            return `
                <article class="featured-card-compact">
                    <span class="featured-badge">Featured</span>
                    <h3 class="featured-title"><a href="${escapeHtml(event.link)}" target="_blank">${escapeHtml(event.event_name)}</a></h3>
                    <div class="featured-meta">
                        <span class="featured-firm">${escapeHtml(event.firm_name)}</span>
                        ${dateStr ? `<span class="featured-date">${dateStr}</span>` : ''}
                    </div>
                    <a href="${escapeHtml(event.link)}" target="_blank" class="featured-link">View →</a>
                </article>
            `;
        }).join('');
    } catch (error) {
        console.error("loadFeaturedEvents error:", error);
    }
}

async function loadStorylines() {
    try {
        const response = await fetch(apiUrl('/api/storylines'));
        const storylines = await response.json();
        
        const container = document.getElementById('storylines-list');
        const section = document.getElementById('storylines-section');
        if (!container || !section) return;
        
        if (storylines.length === 0) {
            section.style.display = 'none';
            return;
        }
        
        section.style.display = 'block';
        container.innerHTML = storylines.slice(0, 6).map(storyline => {
            const eventsHtml = storyline.events.slice(0, 3).map(event => 
                `<li><a href="${escapeHtml(event.link)}" target="_blank">${escapeHtml(event.event_name)}</a></li>`
            ).join('');
            return `
                <article class="storyline-card">
                    <h3>${escapeHtml(storyline.title)}</h3>
                    <p class="storyline-meta">${storyline.event_count} events</p>
                    <ul class="storyline-events-preview">
                        ${eventsHtml}
                        ${storyline.event_count > 3 ? `<li>... and ${storyline.event_count - 3} more</li>` : ''}
                    </ul>
                </article>
            `;
        }).join('');
    } catch (error) {
        console.error("loadStorylines error:", error);
    }
}

// Phase 2: Featured collapse functionality (Priority 8, Phase 2)
function initFeaturedCollapse() {
    const toggle = document.getElementById('featured-toggle');
    const content = document.getElementById('featured-content');
    
    if (toggle && content) {
        // Load saved state
        const savedState = localStorage.getItem('featuredCollapsed');
        const isCollapsed = savedState === 'true';
        
        if (isCollapsed) {
            content.style.display = 'none';
            toggle.textContent = '+';
        }
        
        toggle.addEventListener('click', () => {
            if (content.style.display === 'none') {
                content.style.display = 'block';
                toggle.textContent = '−';
                localStorage.setItem('featuredCollapsed', 'false');
            } else {
                content.style.display = 'none';
                toggle.textContent = '+';
                localStorage.setItem('featuredCollapsed', 'true');
            }
        });
    }
}

// Phase 3: Filter groups collapse/expand (Priority 8, Phase 3)
function initFilterGroups() {
    // Load saved preferences
    const savedState = localStorage.getItem('filterGroupsState');
    const state = savedState ? JSON.parse(savedState) : {
        advanced: false,
        view: false
    };
    
    // Set initial state
    setFilterGroupState('advanced', state.advanced);
    setFilterGroupState('view', state.view);
    
    // Add toggle handlers
    document.querySelectorAll('.filter-group-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            const group = toggle.getAttribute('data-group');
            const currentState = getFilterGroupState(group);
            setFilterGroupState(group, !currentState);
            saveFilterGroupState();
        });
    });
}

function setFilterGroupState(group, isOpen) {
    const content = document.getElementById(`${group}-filters-content`) || 
                    document.getElementById(`${group}-options-content`);
    const toggle = document.querySelector(`[data-group="${group}"]`);
    
    if (content && toggle) {
        content.style.display = isOpen ? 'flex' : 'none';
        const icon = toggle.querySelector('.toggle-icon');
        if (icon) {
            icon.textContent = isOpen ? '▼' : '▶';
        }
    }
}

function getFilterGroupState(group) {
    const content = document.getElementById(`${group}-filters-content`) || 
                    document.getElementById(`${group}-options-content`);
    return content ? content.style.display !== 'none' : false;
}

function saveFilterGroupState() {
    const state = {
        advanced: getFilterGroupState('advanced'),
        view: getFilterGroupState('view')
    };
    localStorage.setItem('filterGroupsState', JSON.stringify(state));
}

// 4-Zone Architecture: Authentication functions
// 4-Zone Architecture: Homepage Preview Loading
async function loadHomepagePreviews() {
    try {
        const url = apiUrl('/api/homepage/preview');
        const response = await fetch(url);
        if (response.ok) {
            const preview = await response.json();
            renderZonePreview('zone1', preview.zone1);
            renderZonePreview('zone2', preview.zone2);
            renderZonePreview('zone3', preview.zone3);
            renderZonePreview('zone4', preview.zone4);
        } else {
            console.error('Failed to load homepage preview, status:', response.status);
            const text = await response.text();
            console.error('Response text:', text);
            // Show error in preview containers
            ['zone1', 'zone2', 'zone3', 'zone4'].forEach(zoneId => {
                const container = document.getElementById(`${zoneId}-preview`);
                if (container) {
                    container.innerHTML = `<p style="color: red;">Error loading preview (HTTP ${response.status})</p>`;
                }
            });
        }
    } catch (error) {
        console.error('Error loading homepage preview:', error);
        // Show error in preview containers
        ['zone1', 'zone2', 'zone3', 'zone4'].forEach(zoneId => {
            const container = document.getElementById(`${zoneId}-preview`);
            if (container) {
                container.innerHTML = `<p style="color: red;">Error: ${error.message}</p>`;
            }
        });
    }
}

function renderZonePreview(zoneId, zoneData) {
    const previewContainer = document.getElementById(`${zoneId}-preview`);
    if (!previewContainer) return;
    
    if (zoneId === 'zone3') {
        // Zone 3: Show topics
        if (zoneData.topics && zoneData.topics.length > 0) {
            const topicsHtml = zoneData.topics.slice(0, 6).map(topic => 
                `<span class="topic-badge">${escapeHtml(topic.name)}</span>`
            ).join('');
            previewContainer.innerHTML = `
                <div class="topics-preview">${topicsHtml}</div>
                ${zoneData.preview_events && zoneData.preview_events.length > 0 ? 
                    `<div class="events-preview">${renderPreviewEvents(zoneData.preview_events.slice(0, 2))}</div>` : 
                    '<p style="color: var(--muted); font-size: 13px;">Select a topic to explore</p>'
                }
            `;
        } else {
            previewContainer.innerHTML = '<p class="loading">Loading topics...</p>';
        }
    } else if (zoneId === 'zone4') {
        // Zone 4: Show total count
        previewContainer.innerHTML = `
            <div class="zone4-preview">
                <div class="total-count">${zoneData.total_count || 0}</div>
                <p>events available</p>
            </div>
        `;
    } else {
        // Zone 1 & 2: Show preview events (3-5 events)
        if (zoneData.preview_events && zoneData.preview_events.length > 0) {
            previewContainer.innerHTML = renderPreviewEvents(zoneData.preview_events.slice(0, 5));
        } else {
            previewContainer.innerHTML = '<p style="color: var(--muted); font-size: 13px;">No events available</p>';
        }
    }
}

function renderPreviewEvents(events) {
    if (!events || events.length === 0) {
        return '<p style="color: var(--muted); font-size: 13px;">No events available</p>';
    }
    return events.map(event => {
        let dateStr = 'Date TBD';
        try {
            if (event.date_time) {
                const date = new Date(event.date_time);
                dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
            }
        } catch (e) {
            dateStr = 'Date TBD';
        }
        const title = (event.event_name || 'Untitled Event').length > 50 ? 
            (event.event_name || 'Untitled Event').substring(0, 50) + '...' : 
            (event.event_name || 'Untitled Event');
        return `
            <div class="preview-event">
                <div class="preview-event-title">${escapeHtml(title)}</div>
                <div class="preview-event-meta">
                    <span class="preview-event-date">${dateStr}</span>
                    ${event.format ? `<span class="preview-event-format">${escapeHtml(event.format)}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// 4-Zone Architecture: Zone initialization
function initZones() {
    // Check if we're on a zone page (has events-list container)
    const isZonePage = document.getElementById('events-list') && 
                      (window.location.pathname.startsWith('/zone') || 
                       window.location.pathname === '/zone1' || 
                       window.location.pathname === '/zone2' || 
                       window.location.pathname === '/zone3' || 
                       window.location.pathname === '/zone4');
    
    // Only run homepage zone loading if on homepage (has zone preview containers)
    if (!isZonePage && document.getElementById('zone1-preview')) {
        // Homepage zone loading (for previews)
        loadZone1Preview();
        loadZone2Preview();
        loadZone3Topics();
    }
    // Zone pages handle their own loading via inline scripts
}

// Rename homepage functions to avoid confusion
function loadZone1Preview() {
    loadZone1();
}

function loadZone2Preview() {
    loadZone2();
}

// 4-Zone Architecture: Zone 1 - Recommended for You (Homepage Preview)
async function loadZone1() {
    const container = document.getElementById('zone1Events');
    if (!container) return;
    
    try {
        container.innerHTML = '<p class="loading">Loading recommendations...</p>';
        const response = await fetch(apiUrl('/api/recommendations?limit=20'));
        if (response.ok) {
            const events = await response.json();
            if (events.length === 0) {
                container.innerHTML = '<p>No recommendations available.</p>';
            } else {
                renderEventsToContainer(events, container);
            }
        } else {
            container.innerHTML = '<p>Error loading recommendations</p>';
        }
    } catch (error) {
        console.error("loadZone1 error:", error);
        container.innerHTML = '<p>Error loading recommendations</p>';
    }
}

// 4-Zone Architecture: Zone 2 - Happening Soon (Homepage Preview)
async function loadZone2() {
    const container = document.getElementById('zone2Events');
    if (!container) return;
    
    try {
        container.innerHTML = '<p class="loading">Loading...</p>';
        const response = await fetch(apiUrl('/api/events/happening-soon?days=14'));
        if (response.ok) {
            const events = await response.json();
            if (events.length === 0) {
                container.innerHTML = '<p>No events happening in the next 14 days</p>';
            } else {
                renderEventsToContainer(events, container);
            }
        } else {
            container.innerHTML = '<p>Error loading events</p>';
        }
    } catch (error) {
        console.error("loadZone2 error:", error);
        container.innerHTML = '<p>Error loading events</p>';
    }
}

// 4-Zone Architecture: Zone 3 - Explore by Interest
async function loadZone3Topics() {
    const container = document.getElementById('topicFilters');
    if (!container) return;
    
    try {
        const response = await fetch(apiUrl('/api/topics'));
        if (response.ok) {
            const topics = await response.json();
            container.innerHTML = topics.slice(0, 10).map(topic => 
                `<button class="topic-filter-btn" data-topic="${escapeHtml(topic.slug)}" data-topic-name="${escapeHtml(topic.name)}">
                    ${escapeHtml(topic.name)} (${topic.count})
                </button>`
            ).join('');
            
            // Add click handlers
            container.querySelectorAll('.topic-filter-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const topicName = btn.getAttribute('data-topic-name');
                    selectedZone3Topic = topicName;
                    loadZone3(topicName);
                    // Update active state
                    container.querySelectorAll('.topic-filter-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                });
            });
        }
    } catch (error) {
        console.error("loadZone3Topics error:", error);
    }
}

async function loadZone3(topic) {
    const container = document.getElementById('zone3Events');
    if (!container) return;
    
    try {
        container.innerHTML = '<p class="loading">Loading...</p>';
        const response = await fetch(apiUrl(`/api/events/by-topic?topic=${encodeURIComponent(topic)}`));
        if (response.ok) {
            const events = await response.json();
            if (events.length === 0) {
                container.innerHTML = `<p>No events found for "${topic}"</p>`;
            } else {
                renderEventsToContainer(events, container);
            }
        } else {
            container.innerHTML = '<p>Error loading events</p>';
        }
    } catch (error) {
        console.error("loadZone3 error:", error);
        container.innerHTML = '<p>Error loading events</p>';
    }
}

// 4-Zone Architecture: Helper function to render events to a container
function renderEventsToContainer(events, container) {
    if (!container || !events || events.length === 0) {
        container.innerHTML = '<p>No events found</p>';
        return;
    }
    
    container.innerHTML = events.map(event => {
        const dateStr = event.date_time ? formatDate(event.date_time) : 'Date TBD';
        return `
            <article class="conversation-card">
                <div class="conversation-header">
                    <span class="firm-badge">${escapeHtml(event.firm_name)}</span>
                    ${dateStr !== 'Date TBD' ? `<span class="date-badge">${dateStr}</span>` : ''}
                </div>
                <h3 class="conversation-title">
                    <a href="${escapeHtml(event.link)}" target="_blank">${escapeHtml(event.event_name)}</a>
                </h3>
                ${event.description ? `<p class="conversation-description">${escapeHtml(event.description.substring(0, 150))}...</p>` : ''}
            </article>
        `;
    }).join('');
}

// 4-Zone Architecture: Advanced view toggle
function setupAdvancedView() {
    const advancedLink = document.getElementById('advanced-link');
    const backBtn = document.getElementById('back-to-zones-btn');
    const homepage = document.getElementById('homepage');
    const advancedView = document.getElementById('advanced-view');
    
    if (advancedLink) {
        advancedLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (homepage) homepage.style.display = 'none';
            if (advancedView) advancedView.style.display = 'block';
            loadEvents(); // Load events in advanced view
        });
    }
    
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            if (homepage) homepage.style.display = 'block';
            if (advancedView) advancedView.style.display = 'none';
        });
    }
}

function sortEvents(events, sortBy) {
    const sorted = [...events];
    
    switch (sortBy) {
        case 'date-asc':
            sorted.sort((a, b) => {
                if (!a.date_time && !b.date_time) return 0;
                if (!a.date_time) return 1;
                if (!b.date_time) return -1;
                return new Date(a.date_time) - new Date(b.date_time);
            });
            break;
        case 'date-desc':
            sorted.sort((a, b) => {
                if (!a.date_time && !b.date_time) return 0;
                if (!a.date_time) return 1;
                if (!b.date_time) return -1;
                return new Date(b.date_time) - new Date(a.date_time);
            });
            break;
        case 'signal-desc':
            sorted.sort((a, b) => {
                const scoreA = a.signal_score || 50;
                const scoreB = b.signal_score || 50;
                return scoreB - scoreA;
            });
            break;
        case 'newest':
            sorted.sort((a, b) => {
                const dateA = a.last_seen ? new Date(a.last_seen) : new Date(0);
                const dateB = b.last_seen ? new Date(b.last_seen) : new Date(0);
                return dateB - dateA;
            });
            break;
    }
    
    return sorted;
}

function renderEvents(container = null, eventsToRender = null) {
    const eventsList = container || document.getElementById('events-list');
    if (!eventsList) return;
    
    // Use provided events or fall back to global events variable
    const eventsToUse = eventsToRender || events;
    
    if (!eventsToUse || eventsToUse.length === 0) {
        eventsList.innerHTML = '<p class="empty">No events found.</p>';
        return;
    }
    
    // Build editorial conversation cards (PHASE 5)
    let html = '<div class="conversation-stream">';
    
    eventsToUse.forEach(event => {
        // Parse date/time
        let dateStr = '';
        let timeStr = '';
        let whenDisplay = '';
        if (event.date_time) {
            try {
                const dt = new Date(event.date_time);
                dateStr = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                timeStr = dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
                whenDisplay = `${dateStr} at ${timeStr}`;
            } catch (e) {
                whenDisplay = formatDate(event.date_time);
            }
        } else if (!event.has_explicit_date) {
            whenDisplay = 'Ongoing discussion';
        }
        
        // Theme tags (primary theme for color coding)
        const tags = event.tags_json || [];
        const primaryThemes = ['Macro', 'Geopolitics', 'Markets', 'Rates', 'FX', 'Credit', 'Equities', 'Commodities'];
        const themeTag = tags.find(t => primaryThemes.includes(t)) || tags[0] || '';
        const themeClass = getThemeClass(themeTag);
        
        // Intel type badge
        const intelType = event.intel_type || 'event';
        const intelLabels = {
            'event': 'EVENT',
            'briefing': 'BRIEFING',
            'outlook': 'OUTLOOK',
            'webinar': 'WEBINAR',
            'note': 'NOTE',
            'invite': 'INVITE',
            'debate': 'DEBATE',
            'signal': 'SIGNAL'
        };
        const typeLabel = intelLabels[intelType] || 'EVENT';
        
        // Description (truncate to 200 chars)
        let descriptionHtml = '';
        if (event.description) {
            const desc = event.description.length > 200 
                ? event.description.substring(0, 200) + '...' 
                : event.description;
            descriptionHtml = `<p class="conversation-description">${escapeHtml(desc)}</p>`;
        }
        
        // Participant roles (PHASE 4)
        let participantsHtml = '';
        if (event.participant_roles_json && typeof event.participant_roles_json === 'object') {
            const roles = event.participant_roles_json.roles || [];
            const affiliations = event.participant_roles_json.affiliations || [];
            if (roles.length > 0 || affiliations.length > 0) {
                const roleLabels = roles.map(r => r.replace('_', ' ')).join(', ');
                participantsHtml = `<div class="conversation-participants">Who: ${escapeHtml(roleLabels)}</div>`;
            }
        }
        
        // Signal score badge (PHASE 6)
        let signalScoreHtml = '';
        if (event.signal_score !== null && event.signal_score !== undefined) {
            const score = event.signal_score;
            const scoreClass = score >= 70 ? 'signal-high' : score >= 60 ? 'signal-medium' : 'signal-low';
            signalScoreHtml = `<span class="signal-badge ${scoreClass}">Signal: ${score}</span>`;
        }
        
        // Phase 1: Expandable event details (Priority 6, Phase 1)
        const eventId = escapeHtml(event.id);
        html += `
            <article class="conversation-card ${themeClass}" data-event-id="${eventId}">
                <div class="conversation-header" onclick="toggleEventDetails('${eventId}')" style="cursor: pointer;">
                    <span class="theme-badge ${themeClass}">${escapeHtml(themeTag || 'General')}</span>
                    <span class="type-badge">${typeLabel}</span>
                    ${signalScoreHtml}
                    <span class="expand-icon" id="expand-${eventId}">▼</span>
                </div>
                <h3 class="conversation-title">
                    <a href="${escapeHtml(event.link)}" target="_blank">${escapeHtml(event.event_name)}</a>
                </h3>
                ${descriptionHtml}
                ${participantsHtml}
                <div class="conversation-meta">
                    <span class="conversation-firm">${escapeHtml(event.firm_name)}</span>
                    ${whenDisplay ? `<span class="conversation-date">When: ${whenDisplay}</span>` : ''}
                </div>
                <div class="event-details" id="details-${eventId}" style="display: none;">
                    ${renderEventDetails(event)}
                </div>
            </article>
        `;
    });
    
    html += '</div>';
    eventsList.innerHTML = html;
}

function getThemeClass(theme) {
    const themeMap = {
        'Macro': 'theme-macro',
        'Geopolitics': 'theme-geopolitics',
        'Markets': 'theme-markets',
        'Rates': 'theme-rates',
        'FX': 'theme-fx',
        'Credit': 'theme-credit',
        'Equities': 'theme-equities',
        'Commodities': 'theme-commodities'
    };
    return themeMap[theme] || 'theme-default';
}

function attachEventListeners() {
    // No action buttons to attach - removed save/note functionality
}

// Phase 1: Event Detail View - Helper functions (Priority 6, Phase 1)
function renderEventDetails(event) {
    let html = '';
    
    // Full description
    if (event.description) {
        html += `<div class="event-description-full"><h4>Description</h4><p>${escapeHtml(event.description)}</p></div>`;
    }
    
    // Speakers
    html += renderSpeakers(event.speakers_json);
    
    // Location
    html += renderLocation(event);
    
    // Registration
    html += renderRegistration(event);
    
    // Tags
    html += renderTags(event.tags_json);
    
    return html;
}

function renderSpeakers(speakersJson) {
    if (!speakersJson) return '';
    
    try {
        const speakers = typeof speakersJson === 'string' ? JSON.parse(speakersJson) : speakersJson;
        if (!Array.isArray(speakers) || speakers.length === 0) return '';
        
        let html = '<div class="speakers-section"><h4>Speakers</h4><ul class="speakers-list">';
        speakers.forEach(speaker => {
            html += `
                <li class="speaker-item">
                    <strong>${escapeHtml(speaker.name || 'Unknown')}</strong>
                    ${speaker.title ? `<span class="speaker-title">${escapeHtml(speaker.title)}</span>` : ''}
                    ${speaker.affiliation ? `<span class="speaker-affiliation">${escapeHtml(speaker.affiliation)}</span>` : ''}
                    ${speaker.role ? `<span class="speaker-role">${escapeHtml(speaker.role)}</span>` : ''}
                </li>
            `;
        });
        html += '</ul></div>';
        return html;
    } catch (e) {
        return '';
    }
}

function renderLocation(event) {
    if (!event.location_city && !event.location_country && !event.format) return '';
    
    let html = '<div class="location-section"><h4>Location</h4><ul>';
    if (event.location_city) html += `<li>City: ${escapeHtml(event.location_city)}</li>`;
    if (event.location_country) html += `<li>Country: ${escapeHtml(event.location_country)}</li>`;
    if (event.format) html += `<li>Format: ${escapeHtml(event.format)}</li>`;
    if (event.location_text) html += `<li>${escapeHtml(event.location_text)}</li>`;
    html += '</ul></div>';
    return html;
}

function renderRegistration(event) {
    if (!event.registration_type && !event.registration_url && !event.registration_deadline) return '';
    
    let html = '<div class="registration-section"><h4>Registration</h4><ul>';
    if (event.registration_type) html += `<li>Type: ${escapeHtml(event.registration_type)}</li>`;
    if (event.registration_deadline) html += `<li>Deadline: ${escapeHtml(event.registration_deadline)}</li>`;
    if (event.registration_fee) html += `<li>Fee: ${escapeHtml(event.registration_fee)}</li>`;
    if (event.registration_url) html += `<li><a href="${escapeHtml(event.registration_url)}" target="_blank">Register</a></li>`;
    html += '</ul></div>';
    return html;
}

function renderTags(tagsJson) {
    if (!tagsJson) return '';
    
    try {
        const tags = typeof tagsJson === 'string' ? JSON.parse(tagsJson) : tagsJson;
        if (!Array.isArray(tags) || tags.length === 0) return '';
        
        let html = '<div class="tags-section"><h4>Tags</h4><div class="tags-list">';
        tags.forEach(tag => {
            html += `<span class="tag">${escapeHtml(tag)}</span>`;
        });
        html += '</div></div>';
        return html;
    } catch (e) {
        return '';
    }
}

function toggleEventDetails(eventId) {
    const detailsDiv = document.getElementById(`details-${eventId}`);
    const expandIcon = document.getElementById(`expand-${eventId}`);
    
    if (detailsDiv && expandIcon) {
        if (detailsDiv.style.display === 'none') {
            detailsDiv.style.display = 'block';
            expandIcon.textContent = '▲';
        } else {
            detailsDiv.style.display = 'none';
            expandIcon.textContent = '▼';
        }
    }
}

// Make function globally accessible
window.toggleEventDetails = toggleEventDetails;


function getFormatClass(format) {
    const formatLower = (format || '').toLowerCase();
    if (formatLower === 'online') return 'format-online';
    if (formatLower === 'in-person') return 'format-inperson';
    if (formatLower === 'hybrid') return 'format-hybrid';
    return 'format-unknown';
}

// Notifications tab
function setupNotificationsTab() {
    const markAllSeenBtn = document.getElementById('mark-all-seen-btn');
    
    markAllSeenBtn.addEventListener('click', async () => {
        const unseenNotifications = notifications.filter(n => !n.seen);
        if (unseenNotifications.length === 0) {
            return;
        }
        
        const notificationIds = unseenNotifications.map(n => n.id);
        
        markAllSeenBtn.disabled = true;
        const originalText = markAllSeenBtn.textContent;
        markAllSeenBtn.textContent = 'Marking...';
        
        try {
            const data = await fetchWithErrorHandling(apiUrl('/api/notifications/mark_seen'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notification_ids: notificationIds })
            });
            
            if (data.success) {
                showMessage(`Marked ${data.marked} notifications as seen`, 'success');
                loadNotifications();
            } else {
                showMessage(`Error: ${data.error || 'Unknown error'}`, 'error');
            }
        } catch (error) {
            showMessage(`Error: ${error.message}`, 'error');
        } finally {
            markAllSeenBtn.disabled = false;
            markAllSeenBtn.textContent = originalText;
        }
    });
}

async function loadNotifications() {
    const notificationsList = document.getElementById('notifications-list');
    
    notificationsList.innerHTML = '<p class="loading">Loading notifications...</p>';
    
    try {
        notifications = await fetchWithErrorHandling(apiUrl('/api/notifications'));
        renderNotifications();
    } catch (error) {
        notificationsList.innerHTML = `<p class="error">Error loading notifications: ${error.message}</p>`;
        notifications = [];
    }
}

function renderNotifications() {
    const notificationsList = document.getElementById('notifications-list');
    
    if (notifications.length === 0) {
        notificationsList.innerHTML = '<p class="empty">No notifications.</p>';
        return;
    }
    
    let html = '';
    
    notifications.forEach(notification => {
        const dateStr = notification.date_time ? formatDate(notification.date_time) : '-';
        const seenClass = notification.seen ? '' : 'unseen';
        
        html += `
            <div class="notification-item ${seenClass}">
                <div class="notification-content">
                    <div class="notification-firm">${escapeHtml(notification.firm_name)}</div>
                    <div class="notification-event">${escapeHtml(notification.event_name)}</div>
                    <div class="notification-date">${dateStr}</div>
                </div>
                <div class="notification-link">
                    <a href="${escapeHtml(notification.link)}" target="_blank">Open</a>
                </div>
            </div>
        `;
    });
    
    notificationsList.innerHTML = html;
}

// Settings tab
function setupSettingsTab() {
    // Settings tab has no interactive elements to set up
    // Settings are loaded when tab is clicked (handled by switchTab)
}

async function loadSettings() {
    const settingsContent = document.getElementById('settings-content');
    
    settingsContent.innerHTML = '<p class="loading">Loading settings...</p>';
    
    try {
        const prefs = await fetchWithErrorHandling(apiUrl('/api/preferences'));
        
        let html = '<div class="settings-section">';
        html += '<h3>Followed Firms</h3>';
        html += '<ul class="settings-list">';
        if (prefs.follow_firms && prefs.follow_firms.length > 0) {
            prefs.follow_firms.forEach(firm => {
                html += `<li>${escapeHtml(firm)}</li>`;
            });
        } else {
            html += '<li><em>None</em></li>';
        }
        html += '</ul></div>';
        
        html += '<div class="settings-section">';
        html += '<h3>Followed Packs</h3>';
        html += '<ul class="settings-list">';
        if (prefs.follow_packs && prefs.follow_packs.length > 0) {
            prefs.follow_packs.forEach(pack => {
                html += `<li>${escapeHtml(pack.display_name)}</li>`;
            });
        } else {
            html += '<li><em>None</em></li>';
        }
        html += '</ul></div>';
        
        html += '<div class="settings-section">';
        html += '<h3>Followed Tags</h3>';
        html += '<ul class="settings-list">';
        if (prefs.follow_tags && prefs.follow_tags.length > 0) {
            prefs.follow_tags.forEach(tag => {
                html += `<li>${escapeHtml(tag)}</li>`;
            });
        } else {
            html += '<li><em>None</em></li>';
        }
        html += '</ul></div>';
        
        html += '<div class="settings-section">';
        html += '<h3>Notification Settings</h3>';
        html += '<ul class="settings-list">';
        html += `<li>Require confirmed events: ${prefs.require_confirmed_for_notifications ? 'Yes' : 'No'}</li>`;
        html += '</ul></div>';
        
        // Load source status
        try {
            const sourceStats = await fetchWithErrorHandling(apiUrl('/api/source_stats'));
            const validationResults = await fetch(apiUrl('/api/new_sources_validation')).catch(() => null);
            
            html += '<div class="settings-section">';
            html += '<h3>Source Status</h3>';
            
            if (validationResults && validationResults.ok) {
                const validation = await validationResults.json();
                html += '<div class="source-status-summary">';
                html += `<p><strong>New Sources Validation:</strong></p>`;
                html += `<ul class="settings-list">`;
                html += `<li>✓ Working: ${validation.summary.working || 0}</li>`;
                html += `<li>⚠ Partial: ${validation.summary.partial || 0}</li>`;
                html += `<li>✗ No events: ${validation.summary.no_events || 0}</li>`;
                html += `<li>✗ Errors: ${validation.summary.errors || 0}</li>`;
                html += `</ul>`;
                
                if (validation.results && validation.results.length > 0) {
                    html += '<div class="source-status-details" style="margin-top: 15px;">';
                    html += '<p><strong>Source Details:</strong></p>';
                    html += '<table class="source-status-table" style="width: 100%; border-collapse: collapse; margin-top: 10px;">';
                    html += '<thead><tr><th style="text-align: left; padding: 8px; border-bottom: 1px solid #ddd;">Source</th><th style="text-align: left; padding: 8px; border-bottom: 1px solid #ddd;">Status</th><th style="text-align: left; padding: 8px; border-bottom: 1px solid #ddd;">Events</th></tr></thead>';
                    html += '<tbody>';
                    
                    // Sort: working first, then by events
                    const sorted = [...validation.results].sort((a, b) => {
                        if (a.status === 'working' && b.status !== 'working') return -1;
                        if (a.status !== 'working' && b.status === 'working') return 1;
                        return b.events_found - a.events_found;
                    });
                    
                    sorted.forEach(result => {
                        const statusClass = result.status === 'working' ? 'status-working' : 
                                          result.status === 'partial' ? 'status-partial' : 'status-failed';
                        const statusIcon = result.status === 'working' ? '✓' : 
                                         result.status === 'partial' ? '⚠' : '✗';
                        const statusText = result.status === 'working' ? 'Working' : 
                                         result.status === 'partial' ? 'Partial' : 'No Events';
                        
                        html += `<tr class="${statusClass}">`;
                        html += `<td style="padding: 8px; border-bottom: 1px solid #eee;">${escapeHtml(result.firm_name)}</td>`;
                        html += `<td style="padding: 8px; border-bottom: 1px solid #eee;">${statusIcon} ${statusText}</td>`;
                        html += `<td style="padding: 8px; border-bottom: 1px solid #eee;">${result.events_found} (${result.future_count} future, ${(result.dated_ratio * 100).toFixed(0)}% dated)</td>`;
                        html += `</tr>`;
                    });
                    
                    html += '</tbody></table>';
                    html += '</div>';
                }
                
                html += '</div>';
            }
            
            if (sourceStats && Object.keys(sourceStats).length > 0) {
                html += '<div class="source-stats-summary" style="margin-top: 20px;">';
                html += `<p><strong>Active Sources:</strong> ${Object.keys(sourceStats).length}</p>`;
                html += '</div>';
            }
            
            html += '</div>';
        } catch (error) {
            console.error('Error loading source status:', error);
        }
        
        settingsContent.innerHTML = html;
    } catch (error) {
        settingsContent.innerHTML = `<p class="error">Error loading settings: ${error.message}</p>`;
    }
}

// Utility functions
function formatDate(isoString) {
    try {
        const date = new Date(isoString);
        // For previews, show shorter format
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
        return isoString;
    }
}

function formatDateFull(isoString) {
    try {
        const date = new Date(isoString);
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
        return isoString;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Error handling utilities
function handleZonePageError(container, error, defaultMessage) {
    console.error('Zone page error:', error);
    const errorMsg = error.message || defaultMessage || 'Unknown error';
    container.innerHTML = `
        <div class="error-message" style="padding: 20px; background: #fee; border: 1px solid #fcc; border-radius: 8px; margin: 20px 0;">
            <p style="font-weight: bold; margin-bottom: 10px;">Error loading events</p>
            <p style="margin-bottom: 15px;">${escapeHtml(errorMsg)}</p>
            <button onclick="location.reload()" class="button" style="padding: 8px 16px; background: var(--accent); color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>
        </div>
    `;
}

function showLoading(container, message = 'Loading events...') {
    if (container) {
        container.innerHTML = `<p class="loading">${message}</p>`;
    }
}

function showEmpty(container, message = 'No events found.') {
    if (container) {
        container.innerHTML = `<p class="empty">${message}</p>`;
    }
}

// Make functions globally available for zone page inline scripts
window.apiUrl = apiUrl;
window.escapeHtml = escapeHtml;
window.renderEvents = renderEvents;
window.renderEventsToContainer = renderEventsToContainer;
window.handleZonePageError = handleZonePageError;
window.showLoading = showLoading;
window.showEmpty = showEmpty;

// Utility function to wait for app.js to load
function waitForAppJS(callback, maxAttempts = 10) {
    if (typeof apiUrl !== 'undefined' && typeof renderEvents !== 'undefined' && typeof escapeHtml !== 'undefined') {
        callback();
    } else if (maxAttempts > 0) {
        setTimeout(() => waitForAppJS(callback, maxAttempts - 1), 100);
    } else {
        console.error('app.js functions not available after 10 attempts');
        const eventsList = document.getElementById('events-list');
        if (eventsList) {
            eventsList.innerHTML = '<p class="error">JavaScript not loaded. Please refresh the page.</p>';
        }
    }
}
window.waitForAppJS = waitForAppJS;

// ============================================================================
// Zone Page Loading Functions - Use /api/events for all events
// ============================================================================

// Zone 1: Load recommended events (high signal score)
async function loadZone1PageEvents() {
    const eventsList = document.getElementById('events-list');
    if (!eventsList) return;
    
    showLoading(eventsList, 'Loading recommendations...');
    
    try {
        // Get filter values
        const signalFilter = document.getElementById('signal-filter')?.value;
        const daysAhead = document.getElementById('days-ahead-select')?.value || '365';
        const formatFilter = document.getElementById('format-filter')?.value;
        const topicFilter = document.getElementById('topic-filter')?.value;
        
        // Build API URL - use /api/events with filters instead of /api/recommendations
        // This ensures we get ALL events, not just limited recommendations
        const params = new URLSearchParams();
        params.append('days_ahead', daysAhead);
        params.append('with_date', '1');
        if (signalFilter) {
            params.append('min_signal_score', signalFilter);
        }
        if (topicFilter && topicFilter !== 'all') {
            params.append('tags', topicFilter);
        }
        
        const response = await fetch(apiUrl(`/api/events?${params}`));
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 100)}`);
        }
        
        let events = await response.json();
        
        // Sort by signal score (descending) by default
        events.sort((a, b) => (b.signal_score || 0) - (a.signal_score || 0));
        
        // Apply client-side format filter
        if (formatFilter) {
            events = events.filter(e => e.format === formatFilter);
        }
        
        // Apply sorting from sort select
        const sortSelect = document.getElementById('sort-select');
        if (sortSelect?.value === 'date-asc') {
            events.sort((a, b) => new Date(a.date_time || 0) - new Date(b.date_time || 0));
        } else if (sortSelect?.value === 'date-desc') {
            events.sort((a, b) => new Date(b.date_time || 0) - new Date(a.date_time || 0));
        }
        // signal-desc is default (already sorted above)
        
        if (events.length === 0) {
            showEmpty(eventsList, 'No recommendations available.');
        } else {
            renderEvents(eventsList, events);
        }
    } catch (error) {
        console.error('Error loading Zone 1 events:', error);
        handleZonePageError(eventsList, error, 'Error loading recommendations');
    }
}

// Zone 2: Load happening soon events
async function loadZone2PageEvents() {
    const eventsList = document.getElementById('events-list');
    if (!eventsList) return;
    
    showLoading(eventsList, 'Loading events...');
    
    try {
        const days = document.getElementById('time-window-select')?.value || '14';
        const formatFilter = document.getElementById('format-filter')?.value;
        const topicFilter = document.getElementById('topic-filter')?.value;
        
        // Use /api/events with date range instead of /api/events/happening-soon
        // This ensures we get ALL events in the time window
        const params = new URLSearchParams();
        params.append('days_ahead', days);
        params.append('with_date', '1');
        if (topicFilter && topicFilter !== 'all') {
            params.append('tags', topicFilter);
        }
        
        const response = await fetch(apiUrl(`/api/events?${params}`));
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 100)}`);
        }
        
        let events = await response.json();
        
        // Sort by date (ascending) by default
        events.sort((a, b) => new Date(a.date_time || 0) - new Date(b.date_time || 0));
        
        // Apply client-side format filter
        if (formatFilter) {
            events = events.filter(e => e.format === formatFilter);
        }
        
        // Apply sorting
        const sortSelect = document.getElementById('sort-select');
        if (sortSelect?.value === 'date-desc') {
            events.sort((a, b) => new Date(b.date_time || 0) - new Date(a.date_time || 0));
        } else if (sortSelect?.value === 'signal-desc') {
            events.sort((a, b) => (b.signal_score || 0) - (a.signal_score || 0));
        }
        // date-asc is default (already sorted above)
        
        if (events.length === 0) {
            showEmpty(eventsList, `No events happening in the next ${days} days`);
        } else {
            renderEvents(eventsList, events);
        }
    } catch (error) {
        console.error('Error loading Zone 2 events:', error);
        handleZonePageError(eventsList, error, 'Error loading events');
    }
}

// Zone 3: Load events by topic
async function loadZone3PageEvents(topic) {
    const eventsList = document.getElementById('events-list');
    if (!eventsList) return;
    
    if (!topic) {
        showEmpty(eventsList, 'Select a topic above to explore events');
        return;
    }
    
    showLoading(eventsList, `Loading events for "${topic}"...`);
    
    try {
        const formatFilter = document.getElementById('format-filter')?.value;
        const signalFilter = document.getElementById('signal-filter')?.value;
        const daysAhead = document.getElementById('days-ahead-select')?.value || '365';
        
        // Use /api/events with tags filter instead of /api/events/by-topic
        // This ensures we get ALL events for the topic
        const params = new URLSearchParams();
        params.append('tags', topic);
        params.append('days_ahead', daysAhead);
        params.append('with_date', '1');
        if (signalFilter) {
            params.append('min_signal_score', signalFilter);
        }
        
        const response = await fetch(apiUrl(`/api/events?${params}`));
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 100)}`);
        }
        
        let events = await response.json();
        
        // Apply client-side format filter
        if (formatFilter) {
            events = events.filter(e => e.format === formatFilter);
        }
        
        // Apply sorting
        const sortSelect = document.getElementById('sort-select');
        if (sortSelect?.value === 'date-desc') {
            events.sort((a, b) => new Date(b.date_time || 0) - new Date(a.date_time || 0));
        } else if (sortSelect?.value === 'signal-desc') {
            events.sort((a, b) => (b.signal_score || 0) - (a.signal_score || 0));
        } else {
            // Default: date ascending
            events.sort((a, b) => new Date(a.date_time || 0) - new Date(b.date_time || 0));
        }
        
        if (events.length === 0) {
            showEmpty(eventsList, `No events found for "${topic}"`);
        } else {
            renderEvents(eventsList, events);
        }
    } catch (error) {
        console.error('Error loading Zone 3 events:', error);
        handleZonePageError(eventsList, error, 'Error loading events');
    }
}

// Populate topic filters dropdown
async function populateTopicFilters(selectElement) {
    if (!selectElement) return;
    
    try {
        const response = await fetch(apiUrl('/api/topics'));
        if (response.ok) {
            const topics = await response.json();
            
            // Clear existing options (except "All Topics")
            selectElement.innerHTML = '<option value="all">All Topics</option>';
            
            // Add topics
            topics.forEach(topic => {
                const option = document.createElement('option');
                option.value = topic.name;
                option.textContent = `${topic.name} (${topic.count})`;
                selectElement.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading topics:', error);
    }
}

// Initialize zone page with all filters and event loading
function initializeZonePage(zoneNumber) {
    // Wait for app.js to be ready
    waitForAppJS(() => {
        // Populate topic filters (except Zone 3 which uses buttons)
        const topicFilter = document.getElementById('topic-filter');
        if (topicFilter && zoneNumber !== 3) {
            populateTopicFilters(topicFilter);
        }
        
        // Setup filter change handlers
        const formatFilter = document.getElementById('format-filter');
        const signalFilter = document.getElementById('signal-filter');
        const sortSelect = document.getElementById('sort-select');
        const daysAheadSelect = document.getElementById('days-ahead-select');
        const timeWindowSelect = document.getElementById('time-window-select');
        
        // Zone-specific filter setup and initial load
        if (zoneNumber === 1) {
            [formatFilter, signalFilter, sortSelect, daysAheadSelect, topicFilter].forEach(el => {
                if (el) el.addEventListener('change', loadZone1PageEvents);
            });
            loadZone1PageEvents();
        } else if (zoneNumber === 2) {
            [formatFilter, sortSelect, timeWindowSelect, topicFilter].forEach(el => {
                if (el) el.addEventListener('change', loadZone2PageEvents);
            });
            loadZone2PageEvents();
        } else if (zoneNumber === 3) {
            // Zone 3 has topic buttons, handled separately in zone3.html inline script
            // Filter change handlers are set up in zone3.html
            // Topics are loaded by loadZone3Topics() in zone3.html
            // Just ensure filters are connected (done in zone3.html)
        } else if (zoneNumber === 4) {
            // Zone 4 uses existing loadEvents() function
            // Ensure setupEventsTab() was called (should be in app.js initialization)
            if (typeof loadEvents === 'function') {
                // Set defaults
                const withDateCheckbox = document.getElementById('with-date-checkbox');
                const daysAheadSelect = document.getElementById('days-ahead-select');
                if (withDateCheckbox) withDateCheckbox.checked = true;
                if (daysAheadSelect) daysAheadSelect.value = '365';
                loadEvents();
            }
        }
        
        // Setup rescrape button (handled by setupEventsTab, but ensure it's called)
        // This should already work if setupEventsTab() was called in app.js initialization
    });
}

// Make functions globally available
window.loadZone1PageEvents = loadZone1PageEvents;
window.loadZone2PageEvents = loadZone2PageEvents;
window.loadZone3PageEvents = loadZone3PageEvents;
window.populateTopicFilters = populateTopicFilters;
window.initializeZonePage = initializeZonePage;

function showMessage(message, type) {
    const eventsList = document.getElementById('events-list');
    const messageDiv = document.createElement('div');
    messageDiv.className = type;
    messageDiv.textContent = message;
    eventsList.insertBefore(messageDiv, eventsList.firstChild);
    
    setTimeout(() => {
        messageDiv.remove();
    }, 5000);
}
