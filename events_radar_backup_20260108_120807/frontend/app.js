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

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Check if running in file:// mode
    if (FILE_MODE) {
        showFileModeBanner();
        disableActions();
        return; // Don't initialize normal functionality
    }
    
    setupTabs();
    setupEventsTab();
    setupNotificationsTab();
    setupSettingsTab();
    loadEvents();
    loadNotifications();
});

function showFileModeBanner() {
    const banner = document.createElement('div');
    banner.id = 'file-mode-banner';
    banner.style.cssText = 'background-color: #ff6b6b; color: white; padding: 20px; margin: 0; text-align: center; font-weight: bold;';
    banner.innerHTML = `
        <p style="margin: 0 0 10px 0; font-size: 16px;">
            ⚠️ This page was opened from a file path (file://)
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
    return `${API_BASE}${path}`;
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
}

async function loadEvents() {
    const searchInput = document.getElementById('search-input');
    const withDateCheckbox = document.getElementById('with-date-checkbox');
    const daysAheadSelect = document.getElementById('days-ahead-select');
    const eventsList = document.getElementById('events-list');
    
    eventsList.innerHTML = '<p class="loading">Loading events...</p>';
    
    try {
        const params = new URLSearchParams();
        const q = searchInput.value.trim();
        if (q) {
            params.append('q', q);
        }
        if (withDateCheckbox.checked) {
            params.append('with_date', '1');
        }
        params.append('days_ahead', daysAheadSelect.value);
        
        const url = apiUrl(`/api/events?${params}`);
        events = await fetchWithErrorHandling(url);
        renderEvents();
    } catch (error) {
        console.error("loadEvents error:", error);
        eventsList.innerHTML = `<p class="error">Error loading events: ${error.message}</p>`;
        events = [];
    }
}

function renderEvents() {
    const eventsList = document.getElementById('events-list');
    
    if (events.length === 0) {
        eventsList.innerHTML = '<p class="empty">No events found.</p>';
        return;
    }
    
    // Sorting hint
    let html = '<p class="sort-hint" style="font-size: 12px; color: #666; margin-bottom: 10px;">📅 Sorted by date (upcoming first). Undated items at bottom.</p>';
    html += '<table class="events-table">';
    html += '<thead><tr><th>Firm</th><th>Event</th><th>Date</th><th>Link</th></tr></thead>';
    html += '<tbody>';
    
    events.forEach(event => {
        const dateStr = event.date_time ? formatDate(event.date_time) : '-';
        html += `
            <tr>
                <td>${escapeHtml(event.firm_name)}</td>
                <td>${escapeHtml(event.event_name)}</td>
                <td>${dateStr}</td>
                <td class="link-cell"><a href="${escapeHtml(event.link)}" target="_blank">Open</a></td>
            </tr>
        `;
    });
    
    html += '</tbody></table>';
    eventsList.innerHTML = html;
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
        
        settingsContent.innerHTML = html;
    } catch (error) {
        settingsContent.innerHTML = `<p class="error">Error loading settings: ${error.message}</p>`;
    }
}

// Utility functions
function formatDate(isoString) {
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
