// Dashboard JavaScript for Source Health Monitoring

async function loadDashboard() {
    try {
        const response = await fetch('/api/dashboard/sources');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const sources = await response.json();
        
        document.getElementById('loading').style.display = 'none';
        document.getElementById('sources-list').style.display = 'grid';
        
        renderSources(sources);
    } catch (error) {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('error').style.display = 'block';
        document.getElementById('error').textContent = `Error loading dashboard: ${error.message}`;
    }
}

function renderSources(sources) {
    const container = document.getElementById('sources-list');
    container.innerHTML = '';
    
    sources.forEach(source => {
        const card = createSourceCard(source);
        container.appendChild(card);
    });
}

function createSourceCard(source) {
    const card = document.createElement('div');
    card.className = 'source-card';
    
    const stats = source.current_stats || {};
    const trend = source.trend || {};
    
    // Status badge
    const statusClass = source.active ? 'status-active' : 'status-inactive';
    const statusText = source.active ? 'Active' : 'Inactive';
    
    // Trend badge
    let trendClass = 'trend-stable';
    let trendText = 'Stable';
    if (trend.trend === 'improving') {
        trendClass = 'trend-improving';
        trendText = 'Improving';
    } else if (trend.trend === 'degrading') {
        trendClass = 'trend-degrading';
        trendText = 'Degrading';
    } else if (trend.trend === 'insufficient_data') {
        trendText = 'Insufficient Data';
    }
    
    card.innerHTML = `
        <div class="source-header">
            <div class="source-name">${source.firm_name || source.id}</div>
            <span class="status-badge ${statusClass}">${statusText}</span>
        </div>
        <div class="stats-row">
            <span class="stats-label">Kept Ratio:</span>
            <span class="stats-value">${(stats.kept_ratio || 0).toFixed(2)}</span>
        </div>
        <div class="stats-row">
            <span class="stats-label">Dated Ratio:</span>
            <span class="stats-value">${(stats.dated_ratio || 0).toFixed(2)}</span>
        </div>
        <div class="stats-row">
            <span class="stats-label">Raw Count:</span>
            <span class="stats-value">${stats.raw_count || 0}</span>
        </div>
        <div class="stats-row">
            <span class="stats-label">Future Events:</span>
            <span class="stats-value">${stats.future_count || 0}</span>
        </div>
        <div class="stats-row">
            <span class="stats-label">History Points:</span>
            <span class="stats-value">${source.history_count || 0}</span>
        </div>
        <div class="trend-badge ${trendClass}">${trendText}</div>
    `;
    
    return card;
}

// Load dashboard on page load
document.addEventListener('DOMContentLoaded', loadDashboard);
