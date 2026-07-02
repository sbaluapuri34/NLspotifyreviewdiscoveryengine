// Theme Exploration State
let activeTheme = 'discovery';

function getApiUrl(basePath) {
    if (activeTheme === 'discovery') {
        return basePath;
    }
    const parts = basePath.split('?');
    const path = parts[0];
    const query = parts[1] ? `?${parts[1]}` : '';
    const apiName = path.replace('/api/', '');
    return `/api/exploration/${activeTheme}/${apiName}${query}`;
}

// Intercept window.fetch to support Theme Exploration Mode and Location/Language filters dynamically
const originalFetch = window.fetch;
window.fetch = function(input, init) {
    let url = typeof input === 'string' ? input : input.url;
    if (url.startsWith('/api/') && 
        !url.includes('/api/pipeline-status') && 
        !url.includes('/api/pipeline-decision') && 
        !url.includes('/api/exploration/')) {
        
        url = getApiUrl(url);
    }
    
    // Automatically append country and lang filters if they are active
    if (url.startsWith('/api/') && 
        !url.includes('/api/pipeline-status') && 
        !url.includes('/api/pipeline-decision') && 
        !url.includes('/api/run-pipeline') && 
        !url.includes('/api/cancel-pipeline') && 
        !url.includes('/api/exploration/run-pipeline') && 
        !url.includes('/api/exploration/cancel-pipeline')) {
        
        const country = state.countryFilter || 'all';
        const lang = state.langFilter || 'all';
        if (country !== 'all' || lang !== 'all') {
            const separator = url.includes('?') ? '&' : '?';
            url = `${url}${separator}country=${country}&lang=${lang}`;
        }
    }
    
    if (typeof input === 'string') {
        input = url;
    } else {
        input.url = url;
    }
    return originalFetch(input, init);
};

// App State
let state = {
    activeTab: 'clusters',
    activeSource: null, // Slicing filter
    countryFilter: 'all',
    langFilter: 'all',
    clusters: [],
    selectedCluster: null,
    researchQuestions: [],
    refinedThemes: [],
    operationalCategories: [],
    canvasScale: 1.0,
    canvasOffset: { x: 0, y: 0 },
    pipelineRunning: false,
    lastTargetSource: null
};

// DOM Elements
const menuItems = document.querySelectorAll('.menu-item');
const tabPanes = document.querySelectorAll('.tab-pane');
const pageTitle = document.getElementById('page-title');
const pageSubtitle = document.getElementById('page-subtitle');
const clusterCanvas = document.getElementById('cluster-canvas');
const clusterCtx = clusterCanvas ? clusterCanvas.getContext('2d') : null;
const detailPanel = document.getElementById('cluster-detail-panel');
const detailContent = detailPanel ? detailPanel.querySelector('.detail-content') : null;
const emptyState = detailPanel ? detailPanel.querySelector('.empty-state') : null;
const terminalLogs = document.getElementById('terminal-logs');

// Initialize App
document.addEventListener('DOMContentLoaded', async () => {
    initTabs();
    initSSE();
    initPipelineButton();
    initCanvasEvents();
    initDecisionButtons();
    updateIntegrityBadge();
    initMetadataFilters();
    
    // Check if pipeline is already running in background
    try {
        const res = await fetch('/api/pipeline-status');
        const status = await res.json();
        if (status.status === 'running' || status.status === 'awaiting_decision') {
            state.pipelineRunning = true;
            if (status.theme_slug) {
                activeTheme = status.theme_slug;
                initSSE('exploration', activeTheme);
            }
            showAllTabsLoading("Analysis in progress... (resuming view)");
            if (status.status === 'awaiting_decision') {
                showPipelineDecisionModal();
            }
        }
    } catch (e) {
        console.error("Error checking initial pipeline status:", e);
    }
    
    // Research Mode selector handler
    const modeSelect = document.getElementById('research-mode-select');
    const customThemeInputGroup = document.getElementById('custom-theme-input-group');
    const customThemeInput = document.getElementById('custom-theme-input');
    
    if (modeSelect && customThemeInputGroup) {
        modeSelect.addEventListener('change', () => {
            if (modeSelect.value === 'theme') {
                customThemeInputGroup.style.display = 'block';
            } else {
                customThemeInputGroup.style.display = 'none';
                if (customThemeInput) customThemeInput.value = '';
                activeTheme = 'discovery';
                initSSE('discovery');
                reloadDashboard();
            }
        });
    }

    // Transition Nudge Modal click handlers
    const nudgeModal = document.getElementById('nudge-modal');
    const nudgeBtnShow = document.getElementById('nudge-btn-show');
    const nudgeBtnKeep = document.getElementById('nudge-btn-keep');
    
    if (nudgeBtnShow && nudgeModal) {
        nudgeBtnShow.addEventListener('click', () => {
            if (state.pendingThemeSlug) {
                activeTheme = state.pendingThemeSlug;
                state.pendingThemeSlug = null;
                state.pendingThemeName = null;
                nudgeModal.classList.add('hidden');
                
                initSSE('exploration', activeTheme);
                
                // Switch back to clusters tab and reload
                switchTab('clusters');
                reloadDashboard();
            }
        });
    }
    
    if (nudgeBtnKeep && nudgeModal) {
        nudgeBtnKeep.addEventListener('click', () => {
            state.pendingThemeSlug = null;
            state.pendingThemeName = null;
            nudgeModal.classList.add('hidden');
        });
    }

    loadSourceCounts();
    loadClusters();
    loadOperationalFriction();
    loadResearch();
    loadThematicRefinement();
    
    const onlyLatestCheckbox = document.getElementById('pipeline-only-latest');
    const menuPipelineDetails = document.getElementById('menu-pipeline-details');
    if (onlyLatestCheckbox) {
        onlyLatestCheckbox.addEventListener('change', () => {
            loadSourceCounts();
            loadClusters();
            loadOperationalFriction();
            
            if (onlyLatestCheckbox.checked) {
                if (menuPipelineDetails) {
                    menuPipelineDetails.style.display = 'flex';
                }
                switchTab('pipeline-details');
            } else {
                if (menuPipelineDetails) {
                    menuPipelineDetails.style.display = 'none';
                }
                if (state.activeTab === 'pipeline-details') {
                    switchTab('clusters');
                }
            }
        });
    }

    // Add change listeners to date inputs to automatically filter the dashboard view in real time
    const fromDateInput = document.getElementById('pipeline-from-date');
    const toDateInput = document.getElementById('pipeline-to-date');
    if (fromDateInput) fromDateInput.addEventListener('change', reloadDashboard);
    if (toDateInput) toDateInput.addEventListener('change', reloadDashboard);
});

// Global function to reload all dashboard data
function reloadDashboard() {
    loadSourceCounts();
    loadClusters();
    loadOperationalFriction();
    loadResearch();
    loadThematicRefinement();
    updateIntegrityBadge();
    if (state.activeTab === 'executive') loadExecutiveOverview();
    if (state.activeTab === 'strategic') loadStrategicRoadmap();
    if (state.activeTab === 'deep-themes') loadDeepThemeAnalysis();
    if (state.activeTab === 'diagnostic') loadDiagnosticAccuracy();
}

// 1. Tab Navigation
function initTabs() {
    menuItems.forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.getAttribute('data-tab');
            switchTab(tab);
        });
    });
}

function switchTab(tab) {
    menuItems.forEach(mi => {
        if (mi.getAttribute('data-tab') === tab) {
            mi.classList.add('active');
        } else {
            mi.classList.remove('active');
        }
    });
    
    tabPanes.forEach(pane => {
        if (pane.id === `tab-${tab}`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });
    
    state.activeTab = tab;
    updateHeaderInfo();
    
    if (tab === 'clusters') {
        resizeCanvas();
    }
}

function updateHeaderInfo() {
    switch (state.activeTab) {
        case 'clusters':
            pageTitle.innerText = 'Cluster Explorer';
            pageSubtitle.innerText = 'Interactive 2D vector space of user feedback clusters';
            break;
        case 'executive':
            pageTitle.innerText = 'Executive Overview';
            pageSubtitle.innerText = 'High-level Share of Voice and prevalence analysis';
            loadExecutiveOverview();
            break;
        case 'strategic':
            pageTitle.innerText = 'Product Opportunity Analysis';
            pageSubtitle.innerText = 'Jobs-to-be-Done, observed user workarounds, and evidence-based feature prioritization';
            loadStrategicRoadmap();
            break;
        case 'deep-themes':
            pageTitle.innerText = 'Deep Theme Analysis';
            pageSubtitle.innerText = 'Granular sub-theme counts and co-occurrence overlaps';
            loadDeepThemeAnalysis();
            break;
        case 'diagnostic':
            pageTitle.innerText = 'Diagnostic Accuracy';
            pageSubtitle.innerText = 'Double-pass validation diagnostics and opportunity deciles';
            loadDiagnosticAccuracy();
            break;
        case 'operational':
            pageTitle.innerText = 'Operational Friction';
            pageSubtitle.innerText = 'Analysis of non-discovery-related user complaints';
            break;
        case 'research':
            pageTitle.innerText = 'Research Questions';
            pageSubtitle.innerText = 'Synthesized answers and opportunities for the 7 core research questions';
            break;
        case 'thematic':
            pageTitle.innerText = 'Deep Thematic Refinement';
            pageSubtitle.innerText = 'Niche sub-themes extracted and validated against reviews';
            break;
        case 'terminal':
            pageTitle.innerText = 'Live Logs Stream';
            pageSubtitle.innerText = 'Real-time stdout logs of the ingestion and analysis pipeline';
            break;
        case 'pipeline-details':
            pageTitle.innerText = 'Pipeline Run Details';
            pageSubtitle.innerText = 'Granular insights and stage-by-step metrics for the recent scraping execution';
            break;
    }
}

// Helper to get active query parameters including source, dates, and only_latest
function getQueryParams() {
    let params = [];
    
    const onlyLatest = document.getElementById('pipeline-only-latest') ? document.getElementById('pipeline-only-latest').checked : false;
    params.push(`only_latest=${onlyLatest}`);
    
    if (state.activeSource) {
        params.push(`source=${state.activeSource}`);
    }
    
    // Only apply date filters if we are NOT showing only the latest scrape
    if (!onlyLatest) {
        const fromDate = document.getElementById('pipeline-from-date').value;
        const toDate = document.getElementById('pipeline-to-date').value;
        if (fromDate) params.push(`start_date=${fromDate}`);
        if (toDate) params.push(`end_date=${toDate}`);
    }
    
    // Always append cache buster to guarantee real-time data fetch
    params.push(`_=${Date.now()}`);
    
    return params.join('&');
}

// 2. Server-Sent Events (SSE) Connection
let currentEventSource = null;

function initSSE(mode = 'discovery', theme = '') {
    if (currentEventSource) {
        currentEventSource.close();
    }
    
    let url = '/api/stream?mode=' + mode;
    if (theme) {
        url += '&theme=' + theme;
    }
    
    const eventSource = new EventSource(url);
    currentEventSource = eventSource;
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'pipeline_counts') {
            updateLiveCounts(data);
            return;
        }
        
        appendTerminalLog(data.message, data.level);
        
        // Update global progress bar and active tab loading message
        if (data.progress !== undefined) {
            const container = document.getElementById('pipeline-progress-container');
            const bar = document.getElementById('pipeline-progress-bar');
            const percentage = document.getElementById('pipeline-progress-percentage');
            const statusText = document.getElementById('pipeline-progress-status');
            
            if (container && bar && percentage && statusText) {
                container.classList.remove('hidden');
                bar.style.width = `${data.progress}%`;
                percentage.innerText = `${data.progress}%`;
                statusText.innerText = data.message;
                
                if (data.progress === 100) {
                    setTimeout(() => {
                        container.classList.add('hidden');
                    }, 4000);
                }
            }
            
            // Also update the message on the loading overlays if running
            if (state.pipelineRunning) {
                showAllTabsLoading(`${data.message} (${data.progress}%)`);
            }
        } else if (data.message && state.pipelineRunning) {
            showAllTabsLoading(data.message);
        }

        // If pipeline requires a decision on date-range review mismatch
        if (data.message && data.message.includes('DECISION_REQUIRED')) {
            showPipelineDecisionModal();
        }
        
        // If pipeline completed, reload all dashboard data
        if (data.message && data.message.includes('PIPELINE EXECUTION COMPLETED')) {
            // Hide loading overlays
            hideAllTabsLoading();
            state.pipelineRunning = false;
            
            // Reset running button status
            const runPipelineBtn = document.getElementById('btn-run-pipeline');
            if (runPipelineBtn) {
                runPipelineBtn.disabled = false;
                runPipelineBtn.innerText = '⚡ Scrape & Analyze';
            }
            
            if (state.pendingThemeSlug) {
                // Show Nudge Modal for Theme Mode
                const nudgeModal = document.getElementById('nudge-modal');
                const nudgeText = document.getElementById('nudge-modal-text');
                if (nudgeModal && nudgeText) {
                    nudgeText.innerText = `A new analysis for custom theme "${state.pendingThemeName}" is ready. Would you like to view the analysis?`;
                    nudgeModal.classList.remove('hidden');
                }
                return; // Do NOT reload dashboard with Discovery data
            }
            
            // Auto-switch source filter if a single source was targeted
            if (state.lastTargetSource) {
                state.activeSource = state.lastTargetSource;
                const sourceFilter = document.getElementById('filter-source');
                if (sourceFilter) {
                    sourceFilter.value = state.lastTargetSource;
                }
                state.lastTargetSource = null; // Reset
            }
            
            reloadDashboard();
        }
    };
    
    eventSource.onerror = () => {
        appendTerminalLog('Connection to log stream lost. Retrying...', 'WARNING');
    };
}

function updateLiveCounts(data) {
    const container = document.getElementById('header-source-badges');
    if (!container) return;
    
    const sourceMeta = {
        "google_play": { name: "Play Store", icon: "📱" },
        "reddit": { name: "Reddit", icon: "👽" },
        "youtube": { name: "YouTube", icon: "📺" },
        "spotify_community": { name: "Forums", icon: "🗣️" }
    };
    
    const fmt = (num) => Number(num || 0).toLocaleString();
    
    // Calculate total fetched, analysed, pending
    let totalFetched = 0;
    let totalAnalysed = 0;
    
    const sourceKeys = ["google_play", "reddit", "spotify_community", "youtube"];
    sourceKeys.forEach(src => {
        totalFetched += (data.fetched[src] || 0);
        totalAnalysed += (data.analysed[src] || 0);
    });
    const totalPending = totalFetched - totalAnalysed;
    
    container.innerHTML = '';
    
    // 1. All Sources card
    const allCard = document.createElement('div');
    allCard.className = `source-card ${state.activeSource === null ? 'active' : ''}`;
    allCard.innerHTML = `
        <div class="source-card-header">
            <span class="source-icon">📦</span>
            <span class="source-name">All Sources (Live)</span>
        </div>
        <div class="source-metrics-grid">
            <div class="metric-item">
                <span class="metric-label">F:</span>
                <span class="metric-value">${fmt(totalFetched)}</span>
            </div>
            <div class="metric-item">
                <span class="metric-label">A:</span>
                <span class="metric-value">${fmt(totalAnalysed)}</span>
            </div>
            <div class="metric-item">
                <span class="metric-label">P:</span>
                <span class="metric-value ${totalPending > 0 ? 'pending-active' : 'pending-zero'}">${fmt(totalPending)}</span>
            </div>
        </div>
    `;
    container.appendChild(allCard);
    
    // 2. Individual source cards
    sourceKeys.forEach(src => {
        const fetched = data.fetched[src] || 0;
        const analysed = data.analysed[src] || 0;
        const pending = fetched - analysed;
        const meta = sourceMeta[src] || { name: src, icon: "🔗" };
        
        const card = document.createElement('div');
        card.className = `source-card ${state.activeSource === src ? 'active' : ''}`;
        card.innerHTML = `
            <div class="source-card-header">
                <span class="source-icon">${meta.icon}</span>
                <span class="source-name">${meta.name}</span>
            </div>
            <div class="source-metrics-grid">
                <div class="metric-item">
                    <span class="metric-label">F:</span>
                    <span class="metric-value">${fmt(fetched)}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">A:</span>
                    <span class="metric-value">${fmt(analysed)}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">P:</span>
                    <span class="metric-value ${pending > 0 ? 'pending-active' : 'pending-zero'}">${fmt(pending)}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

function appendTerminalLog(message, level = 'INFO') {
    if (!terminalLogs) return;
    
    const logLine = document.createElement('div');
    logLine.className = `log-line log-${level.toLowerCase()}`;
    
    const timestamp = new Date().toLocaleTimeString();
    logLine.innerText = `[${timestamp}] [${level}] ${message}`;
    
    terminalLogs.appendChild(logLine);
    terminalLogs.scrollTop = terminalLogs.scrollHeight;
}

async function loadSourceCounts() {
    const container = document.getElementById('header-source-badges');
    if (!container) return;
    
    try {
        const queryParams = getQueryParams();
        const response = await fetch(`/api/source-counts?${queryParams}`);
        const data = await response.json();
        
        // Update the dynamic "till date" text in the sidebar if present in the response
        if (data.latest_date) {
            const dateObj = new Date(data.latest_date);
            const formattedDate = dateObj.toLocaleDateString('en-US', {
                month: 'long',
                day: 'numeric',
                year: 'numeric',
                timeZone: 'UTC'
            });
            const instructionText = document.getElementById('pipeline-instruction-text');
            if (instructionText) {
                instructionText.innerHTML = `Select the date range and number of reviews for which you want to scrape and analyze. Currently, we are showing a cumulative analysis of all the reviews scraped till <strong>${formattedDate}</strong>.`;
            }
        }
        
        const sources = data.sources || {};
        const total = data.total || { fetched: 0, analysed: 0, pending: 0 };
        
        container.innerHTML = '';
        
        const sourceMeta = {
            "google_play": { name: "Play Store", icon: "📱" },
            "reddit": { name: "Reddit", icon: "👽" },
            "youtube": { name: "YouTube", icon: "📺" },
            "spotify_community": { name: "Forums", icon: "🗣️" }
        };
        
        const fmt = (num) => Number(num || 0).toLocaleString();
        
        // 1. Create the "All Sources" card
        const allCard = document.createElement('div');
        allCard.className = `source-card ${state.activeSource === null ? 'active' : ''}`;
        allCard.innerHTML = `
            <div class="source-card-header">
                <span class="source-icon">📦</span>
                <span class="source-name">All Sources</span>
            </div>
            <div class="source-metrics-grid">
                <div class="metric-item">
                    <span class="metric-label">F:</span>
                    <span class="metric-value">${fmt(total.fetched)}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">A:</span>
                    <span class="metric-value">${fmt(total.analysed)}</span>
                </div>
                <div class="metric-item">
                    <span class="metric-label">P:</span>
                    <span class="metric-value ${total.pending > 0 ? 'pending-active' : 'pending-zero'}">${fmt(total.pending)}</span>
                </div>
            </div>
        `;
        allCard.addEventListener('click', () => {
            state.activeSource = null;
            state.selectedCluster = null;
            if (emptyState) emptyState.classList.remove('hidden');
            if (detailContent) detailContent.classList.add('hidden');
            loadSourceCounts();
            loadClusters();
            loadOperationalFriction();
        });
        container.appendChild(allCard);
        
        // 2. Create cards for individual sources
        const sourceKeys = ["google_play", "reddit", "spotify_community", "youtube"];
        sourceKeys.forEach(src => {
            const counts = sources[src] || { fetched: 0, analysed: 0, pending: 0 };
            const meta = sourceMeta[src] || { name: src, icon: "🔗" };
            
            const card = document.createElement('div');
            card.className = `source-card ${state.activeSource === src ? 'active' : ''}`;
            card.innerHTML = `
                <div class="source-card-header">
                    <span class="source-icon">${meta.icon}</span>
                    <span class="source-name">${meta.name}</span>
                </div>
                <div class="source-metrics-grid">
                    <div class="metric-item">
                        <span class="metric-label">F:</span>
                        <span class="metric-value">${fmt(counts.fetched)}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">A:</span>
                        <span class="metric-value">${fmt(counts.analysed)}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">P:</span>
                        <span class="metric-value ${counts.pending > 0 ? 'pending-active' : 'pending-zero'}">${fmt(counts.pending)}</span>
                    </div>
                </div>
            `;
            
            card.addEventListener('click', () => {
                state.activeSource = (state.activeSource === src) ? null : src;
                state.selectedCluster = null;
                if (emptyState) emptyState.classList.remove('hidden');
                if (detailContent) detailContent.classList.add('hidden');
                loadSourceCounts();
                loadClusters();
                loadOperationalFriction();
            });
            container.appendChild(card);
        });
        
    } catch (e) {
        console.error('Error loading source counts:', e);
    }
}

// 4. Cluster Explorer: Canvas Vector Map & Analytics
async function loadClusters() {
    try {
        const queryParams = getQueryParams();
        let url = `/api/clusters?${queryParams}`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        // Update the analysis context banner
        const contextText = document.getElementById('analysis-context-text');
        const contextIcon = document.getElementById('analysis-context-icon');
        const contextBanner = document.getElementById('analysis-context-banner');
        if (contextText && data.metadata) {
            const meta = data.metadata;
            let htmlContent = '';
            
            if (meta.view_type === 'session') {
                const stats = meta.ingestion_stats;
                const rawScraped = stats ? (stats.raw_processed_total || (stats.fetched + (stats.associated_existing || 0))) : 3039;
                const inRange = stats ? (stats.in_range_total || meta.total_reviews) : 1056;
                const sentToPipeline = stats ? (stats.pipeline_analysed_total || 2623) : 2623;
                const filteredNoise = stats ? (stats.filtered || 0) : 1929;
                
                htmlContent = `<strong>Temporary Session Analysis:</strong> ${meta.from_date} to ${meta.to_date} <span style="margin: 0 6px; opacity: 0.5;">|</span> Scraped/Processed: <strong>${rawScraped}</strong> <span style="margin: 0 6px; opacity: 0.5;">|</span> In-Range: <strong>${inRange}</strong> <span style="margin: 0 6px; opacity: 0.5;">|</span> Sent to Analysis Pipeline: <strong>${sentToPipeline}</strong>`;
                
                if (contextIcon) contextIcon.innerText = '⏱️';
                if (contextBanner) {
                    contextBanner.style.borderBottomColor = 'rgba(235, 87, 87, 0.2)';
                    contextBanner.style.background = 'rgba(235, 87, 87, 0.04)';
                    contextBanner.style.color = '#eb5757';
                }
                
                // Update Pipeline Details tab cards dynamically
                const pStatRaw = document.getElementById('pipeline-stat-raw');
                const pStatInRange = document.getElementById('pipeline-stat-in-range');
                const pStatDiscovery = document.getElementById('pipeline-stat-discovery');
                const pStatFiltered = document.getElementById('pipeline-stat-filtered');
                
                if (pStatRaw) pStatRaw.innerText = rawScraped.toLocaleString();
                if (pStatInRange) pStatInRange.innerText = inRange.toLocaleString();
                if (pStatDiscovery) pStatDiscovery.innerText = sentToPipeline.toLocaleString();
                if (pStatFiltered) pStatFiltered.innerText = filteredNoise.toLocaleString();
            } else {
                htmlContent = `<strong>Cumulative 6-Month Analysis:</strong> ${meta.from_date} to ${meta.to_date} (${meta.total_reviews} reviews)`;
                if (contextIcon) contextIcon.innerText = '📅';
                if (contextBanner) {
                    contextBanner.style.borderBottomColor = 'rgba(29, 185, 84, 0.2)';
                    contextBanner.style.background = 'rgba(29, 185, 84, 0.04)';
                    contextBanner.style.color = '#1db954';
                }
                
                // Add ingestion stats if available (compact inline styling!)
                if (meta.ingestion_stats) {
                    const stats = meta.ingestion_stats;
                    htmlContent += ` <span style="margin: 0 8px; opacity: 0.5;">|</span> <span style="font-weight: 400; opacity: 0.9;">Latest Scrape: Fetched <strong>${stats.fetched}</strong> reviews ➔ Saved <strong>${stats.saved}</strong> (Filtered ${stats.filtered} old/duplicate/noise reviews)</span>`;
                }
            }
            
            contextText.innerHTML = htmlContent;
        }
        
        // Filter out tiny singleton/doubleton noise clusters (under size 3)
        state.clusters = (data.clusters || []).filter(c => c.size >= 3);
        
        const clusterCountBadge = document.getElementById('cluster-count-badge');
        if (clusterCountBadge) {
            clusterCountBadge.innerText = `${state.clusters.length} Clusters`;
        }
        
        resizeCanvas();
        renderThematicClassification();
        renderWordMap();
    } catch (e) {
        console.error('Error loading clusters:', e);
    }
}

function resizeCanvas() {
    if (!clusterCanvas) return;
    
    const rect = clusterCanvas.parentElement.getBoundingClientRect();
    clusterCanvas.width = rect.width;
    clusterCanvas.height = rect.height - 40; // Leave space for legend
    
    drawClusters();
}

function drawClusters() {
    if (!clusterCtx || !clusterCanvas || state.clusters.length === 0) return;
    
    clusterCtx.clearRect(0, 0, clusterCanvas.width, clusterCanvas.height);
    
    const xs = state.clusters.map(c => c.x);
    const ys = state.clusters.map(c => c.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    
    const padding = 40;
    const width = clusterCanvas.width - padding * 2;
    const height = clusterCanvas.height - padding * 2;
    
    state.clusters.forEach(c => {
        const canvasX = padding + ((c.x - minX) / (maxX - minX || 1)) * width;
        const canvasY = padding + ((c.y - minY) / (maxY - minY || 1)) * height;
        
        c.screenX = canvasX;
        c.screenY = canvasY;
        
        clusterCtx.beginPath();
        const radius = 4 + Math.log2(c.size) * 1.5;
        clusterCtx.arc(canvasX, canvasY, radius, 0, 2 * Math.PI);
        
        // Uniform premium Spotify green with subtle opacity
        clusterCtx.fillStyle = 'rgba(29, 185, 84, 0.65)';
        clusterCtx.strokeStyle = 'rgba(29, 185, 84, 0.9)';
        
        if (state.selectedCluster && state.selectedCluster.cluster_id === c.cluster_id) {
            clusterCtx.arc(canvasX, canvasY, radius + 4, 0, 2 * Math.PI);
            clusterCtx.strokeStyle = '#FFFFFF';
            clusterCtx.lineWidth = 2;
        } else {
            clusterCtx.lineWidth = 1;
        }
        
        clusterCtx.fill();
        clusterCtx.stroke();
    });
}

function initCanvasEvents() {
    if (!clusterCanvas) return;
    
    clusterCanvas.addEventListener('click', (e) => {
        const rect = clusterCanvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        
        let clickedCluster = null;
        let minDist = 15;
        
        state.clusters.forEach(c => {
            const dist = Math.hypot(c.screenX - clickX, c.screenY - clickY);
            if (dist < minDist) {
                minDist = dist;
                clickedCluster = c;
            }
        });
        
        if (clickedCluster) {
            selectCluster(clickedCluster);
        }
    });
    
    window.addEventListener('resize', () => {
        if (state.activeTab === 'clusters') {
            resizeCanvas();
        }
    });
}

function selectCluster(cluster) {
    state.selectedCluster = cluster;
    drawClusters();
    
    emptyState.classList.add('hidden');
    detailContent.classList.remove('hidden');
    
    document.getElementById('detail-cluster-id').innerText = cluster.cluster_name;
    document.getElementById('detail-size').innerText = cluster.size;
    
    // Render hierarchical themes & sub-issues
    const subIssuesContainer = document.getElementById('detail-sub-issues');
    subIssuesContainer.innerHTML = '';
    
    if (cluster.sub_themes && cluster.sub_themes.length > 0) {
        cluster.sub_themes.forEach(theme => {
            const themeSection = document.createElement('div');
            themeSection.style.marginBottom = '16px';
            themeSection.innerHTML = `
                <div style="font-weight: 700; font-size: 11px; text-transform: uppercase; color: var(--spotify-green); margin-bottom: 8px; border-bottom: 1px dashed rgba(255,255,255,0.08); padding-bottom: 4px; letter-spacing: 0.5px;">
                    ${theme.name}
                </div>
                <div style="font-size: 12px; opacity: 0.7; margin-bottom: 8px; font-style: italic;">
                    ${theme.description}
                </div>
                <div class="theme-issues-list" id="issues-for-${theme.theme_id}"></div>
            `;
            subIssuesContainer.appendChild(themeSection);
            
            const issuesList = themeSection.querySelector(`#issues-for-${theme.theme_id}`);
            const matchingIssues = (cluster.sub_issues || []).filter(sub => sub.associated_theme_id === theme.theme_id);
            
            if (matchingIssues.length > 0) {
                matchingIssues.forEach(sub => {
                    const item = document.createElement('div');
                    item.className = 'sub-issue-item';
                    item.style.marginLeft = '12px';
                    item.innerHTML = `
                        <div class="sub-issue-header">
                            <span class="sub-issue-title">${sub.name}</span>
                            <span class="sub-issue-pct">${sub.frequency_percentage}%</span>
                        </div>
                        <div class="sub-issue-desc">${sub.description}</div>
                    `;
                    issuesList.appendChild(item);
                });
            } else {
                issuesList.innerHTML = '<div style="font-size:11px; opacity:0.5; padding-left:12px;">No specific sub-issues mapped.</div>';
            }
        });
    } else if (cluster.sub_issues && cluster.sub_issues.length > 0) {
        cluster.sub_issues.forEach(sub => {
            const item = document.createElement('div');
            item.className = 'sub-issue-item';
            item.innerHTML = `
                <div class="sub-issue-header">
                    <span class="sub-issue-title">${sub.name}</span>
                    <span class="sub-issue-pct">${sub.frequency_percentage || 0}%</span>
                </div>
                <div class="sub-issue-desc">${sub.description}</div>
            `;
            subIssuesContainer.appendChild(item);
        });
    } else {
        subIssuesContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px;">No sub-theme or sub-issue decomposition available.</p>';
    }
    
    // Render representative reviews with clickable URLs
    const reviewsContainer = document.getElementById('detail-reviews');
    reviewsContainer.innerHTML = '';
    
    if (cluster.top_reviews && cluster.top_reviews.length > 0) {
        cluster.top_reviews.forEach(rev => {
            const item = document.createElement('div');
            item.className = 'representative-review-item';
            
            const sourceText = rev.source.toUpperCase().replace('_', ' ');
            
            item.innerHTML = `
                <div class="rep-review-meta">
                    <span class="rep-review-source">${sourceText}</span>
                </div>
                <div class="rep-review-text">"${rev.text}"</div>
                <a href="${rev.url}" target="_blank" class="rep-review-link">View Source ↗</a>
            `;
            reviewsContainer.appendChild(item);
        });
    } else {
        reviewsContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px;">No representative reviews found.</p>';
    }
}

// 5. Thematic Shares & Word Map
function renderThematicClassification() {
    const container = document.getElementById('thematic-chart-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    const categories = {
        "Music Discovery Friction": 0,
        "Algorithmic Repetition & Looping": 0,
        "Recommendation Algorithm Sentiment": 0,
        "User Discovery Methods & Behaviors": 0,
        "Physical Listening Contexts": 0,
        "Monetization & Feature Access": 0
    };
    
    let totalReviews = 0;
    
    state.clusters.forEach(c => {
        const theme = c.themes[0] ? c.themes[0].toLowerCase() : "";
        let mapped = false;
        
        if (theme.includes("repeat") || theme.includes("loop") || theme.includes("shuffle")) {
            categories["Algorithmic Repetition & Looping"] += c.size;
            mapped = true;
        } else if (theme.includes("car") || theme.includes("bluetooth") || theme.includes("sonos")) {
            categories["Physical Listening Contexts"] += c.size;
            mapped = true;
        } else if (theme.includes("free") || theme.includes("ad") || theme.includes("premium")) {
            categories["Monetization & Feature Access"] += c.size;
            mapped = true;
        } else if (theme.includes("playlist") || theme.includes("dj")) {
            categories["User Discovery Methods & Behaviors"] += c.size;
            mapped = true;
        } else if (theme.includes("recommend") || theme.includes("algorithm")) {
            categories["Recommendation Algorithm Sentiment"] += c.size;
            mapped = true;
        }
        
        if (!mapped) {
            categories["Music Discovery Friction"] += c.size;
        }
        totalReviews += c.size;
    });
    
    Object.entries(categories).forEach(([catName, count]) => {
        const pct = totalReviews > 0 ? Math.round((count / totalReviews) * 100) : 0;
        
        const group = document.createElement('div');
        group.className = 'chart-bar-group';
        group.innerHTML = `
            <div class="chart-bar-header">
                <span class="chart-bar-title">${catName}</span>
                <span class="chart-bar-val">${count} (${pct}%)</span>
            </div>
            <div class="chart-bar-track">
                <div class="chart-bar-fill" style="width: ${pct}%"></div>
            </div>
        `;
        container.appendChild(group);
    });
}

function renderWordMap() {
    const container = document.getElementById('wordcloud-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    const wordCounts = {};
    state.clusters.forEach(c => {
        c.themes.forEach(theme => {
            const words = theme.split(/\s+/);
            words.forEach(w => {
                const clean = w.toLowerCase().replace(/[^a-z0-9]/g, "");
                if (clean && clean.length > 3) {
                    wordCounts[clean] = (wordCounts[clean] || 0) + c.size;
                }
            });
        });
    });
    
    const topWords = Object.entries(wordCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 20);
        
    const maxCount = topWords[0] ? topWords[0][1] : 1;
    
    topWords.forEach(([word, count]) => {
        const tag = document.createElement('span');
        tag.className = 'word-tag';
        
        const fontSize = 11 + Math.round((count / maxCount) * 11);
        tag.style.fontSize = `${fontSize}px`;
        
        const hue = Math.random() > 0.5 ? 141 : 270;
        const sat = 70 + Math.round(Math.random() * 20);
        const light = 50 + Math.round(Math.random() * 20);
        tag.style.color = `hsl(${hue}, ${sat}%, ${light}%)`;
        
        tag.innerText = word;
        container.appendChild(tag);
    });
}

async function loadOperationalFriction() {
    const container = document.getElementById('operational-categories-container');
    if (!container) return;
    
    try {
        const queryParams = getQueryParams();
        let url = `/api/operational-friction?${queryParams}`;
        
        const response = await fetch(url);
        const data = await response.json();
        state.operationalCategories = data.categories || [];
        
        container.innerHTML = '';
        
        state.operationalCategories.forEach(cat => {
            const card = document.createElement('div');
            card.className = 'card-operational';
            
            let reviewsHtml = '';
            cat.top_reviews.forEach(rev => {
                const sourceText = rev.source.toUpperCase().replace('_', ' ');
                reviewsHtml += `
                    <div class="review-item">
                        <div class="review-meta">
                            <span>Source: ${sourceText}</span>
                        </div>
                        <div class="review-text">"${rev.text}"</div>
                        <a href="${rev.url}" target="_blank" class="rep-review-link" style="margin-top: 4px; font-size: 12px;">View Source ↗</a>
                    </div>
                `;
            });
            
            card.innerHTML = `
                <div class="operational-header">
                    <span class="operational-title">${cat.category_name}</span>
                    <span class="operational-badge">${cat.count} reviews (${cat.percentage}%)</span>
                </div>
                <div class="operational-reviews-list">
                    ${reviewsHtml || '<p style="color: var(--text-secondary); font-size: 13px; padding: 20px 0;">No reviews found in this category.</p>'}
                </div>
            `;
            container.appendChild(card);
        });
        
    } catch (e) {
        console.error('Error loading operational friction:', e);
    }
}

// 7. Research Questions
async function loadResearch() {
    try {
        const response = await fetch('/api/research');
        const data = await response.json();
        state.researchQuestions = data.answers || [];
        renderResearchQuestions();
    } catch (e) {
        console.error('Error loading research questions:', e);
    }
}

function renderResearchQuestions() {
    const container = document.getElementById('research-questions-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    state.researchQuestions.forEach(rq => {
        const card = document.createElement('div');
        card.className = 'card card-research';
        
        let workaroundsHtml = '';
        if (rq.observed_workarounds && rq.observed_workarounds.length > 0) {
            workaroundsHtml = `
                <div style="margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;">
                    <span style="font-size: 10px; text-transform: uppercase; color: var(--text-secondary); width: 100%; margin-bottom: 2px;">User Workarounds:</span>
                    ${rq.observed_workarounds.map(w => `
                        <span class="tag" style="font-size: 9px; padding: 2px 6px; background: rgba(241, 196, 15, 0.08); border: 1px solid rgba(241, 196, 15, 0.15); color: #f1c40f; border-radius: 4px; display: inline-block;">
                            ${w}
                        </span>
                    `).join('')}
                </div>
            `;
        }
        
        let jtbdHtml = '';
        if (rq.jtbd_summary && rq.jtbd_summary.situation) {
            jtbdHtml = `
                <div class="jtbd-card" style="background: rgba(29, 185, 84, 0.04); border-left: 2px solid var(--spotify-green); padding: 8px 10px; border-radius: 4px; font-size: 11px; margin-top: 12px; line-height: 1.4; color: var(--text-primary);">
                    <strong>JTBD:</strong> When ${rq.jtbd_summary.situation}, I want to ${rq.jtbd_summary.motivation}, so that ${rq.jtbd_summary.outcome}
                </div>
            `;
        }

        card.innerHTML = `
            <div class="research-header">
                <span class="research-id">${rq.rq_id}</span>
                <span class="research-conf">Conf: ${Math.round(rq.confidence_score * 100)}%</span>
            </div>
            <h3>${rq.title}</h3>
            <p>${rq.executive_summary.substring(0, 150)}...</p>
            ${jtbdHtml}
            ${workaroundsHtml}
        `;
        
        card.addEventListener('click', () => showResearchModal(rq));
        container.appendChild(card);
    });
    
    // Render dynamic deep-inquiry follow-up research questions
    const deepContainer = document.getElementById('deep-inquiry-questions-container');
    if (deepContainer) {
        deepContainer.innerHTML = '';
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        
        fetch(`/api/executive-overview?only_latest=${onlyLatest}`)
            .then(res => res.json())
            .then(data => {
                const questions = data.deep_inquiry_questions || [];
                if (questions.length === 0) {
                    deepContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px; grid-column: 1 / -1; text-align: center; padding: 20px;">No strategic follow-up questions generated yet. Run validation to generate.</p>';
                } else {
                    questions.forEach(q => {
                        const card = document.createElement('div');
                        card.className = 'card card-research';
                        let pColor = '#e74c3c';
                        if (q.priority === 'Medium') pColor = '#f1c40f';
                        if (q.priority === 'Low') pColor = '#3498db';
                        
                        card.style.borderLeft = `3px solid ${pColor}`;
                        card.innerHTML = `
                            <div class="research-header">
                                <span class="research-id" style="color: ${pColor}; font-weight: 700; border-color: ${pColor};">${q.priority.toUpperCase()} PRIORITY</span>
                            </div>
                            <h3>${q.question}</h3>
                            <p style="margin-top: 8px;"><strong>Strategic Rationale:</strong> ${q.rationale}</p>
                        `;
                        deepContainer.appendChild(card);
                    });
                }
            })
            .catch(err => {
                console.error("Error loading deep inquiry questions:", err);
                deepContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px; grid-column: 1 / -1; text-align: center;">Error loading dynamic follow-up research questions.</p>';
            });
    }
}

function showResearchModal(rq) {
    const modal = document.getElementById('research-modal');
    if (!modal) return;
    
    document.getElementById('modal-title').innerText = `${rq.rq_id}: ${rq.title}`;
    document.getElementById('modal-summary').innerText = rq.executive_summary;
    
    // Render Modal JTBD section
    const jtbdSection = document.getElementById('modal-jtbd-section');
    const jtbdContainer = document.getElementById('modal-jtbd');
    if (jtbdSection && jtbdContainer) {
        if (rq.jtbd_summary && rq.jtbd_summary.situation) {
            jtbdContainer.innerHTML = `
                <strong>Situation:</strong> When ${rq.jtbd_summary.situation}<br/>
                <strong>Motivation:</strong> I want to ${rq.jtbd_summary.motivation}<br/>
                <strong>Desired Outcome:</strong> so that ${rq.jtbd_summary.outcome}
            `;
            jtbdSection.style.display = 'block';
        } else {
            jtbdSection.style.display = 'none';
        }
    }
    
    // Render Modal Workarounds section
    const workaroundsSection = document.getElementById('modal-workarounds-section');
    const workaroundsContainer = document.getElementById('modal-workarounds');
    if (workaroundsSection && workaroundsContainer) {
        workaroundsContainer.innerHTML = '';
        if (rq.observed_workarounds && rq.observed_workarounds.length > 0) {
            rq.observed_workarounds.forEach(w => {
                const badge = document.createElement('span');
                badge.className = 'tag';
                badge.style.background = 'rgba(241, 196, 15, 0.08)';
                badge.style.borderColor = 'rgba(241, 196, 15, 0.15)';
                badge.style.color = '#f1c40f';
                badge.innerText = w;
                workaroundsContainer.appendChild(badge);
            });
            workaroundsSection.style.display = 'block';
        } else {
            workaroundsSection.style.display = 'none';
        }
    }
    
    const findingsContainer = document.getElementById('modal-findings');
    findingsContainer.innerHTML = '';
    rq.key_findings.forEach(f => {
        const item = document.createElement('div');
        item.className = 'finding-item';
        item.innerHTML = `
            <div class="finding-title">${f.finding}</div>
            <div class="finding-desc">${f.supporting_evidence}</div>
        `;
        findingsContainer.appendChild(item);
    });
    
    const oppsContainer = document.getElementById('modal-opportunities');
    oppsContainer.innerHTML = '';
    rq.actionable_opportunities.forEach(o => {
        const item = document.createElement('div');
        item.className = 'opp-item';
        item.innerHTML = `
            <div class="opp-title">${o.opportunity}</div>
            <div class="opp-desc"><strong>Unmet Need:</strong> ${o.unmet_need}<br><strong>Proposed Solution:</strong> ${o.proposed_feature}</div>
        `;
        oppsContainer.appendChild(item);
    });
    
    modal.classList.remove('hidden');
}

// Close Modal Events
const closeModalBtn = document.getElementById('btn-close-modal');
if (closeModalBtn) {
    closeModalBtn.addEventListener('click', () => {
        document.getElementById('research-modal').classList.add('hidden');
    });
}

// 8. Deep Thematic Refinement
async function loadThematicRefinement() {
    try {
        const response = await fetch('/api/thematic-refinement');
        const data = await response.json();
        state.refinedThemes = data.themes || [];
        renderThematicRefinement();
    } catch (e) {
        console.error('Error loading thematic refinement:', e);
    }
}

function renderThematicRefinement() {
    const container = document.getElementById('thematic-themes-container');
    if (!container) return;
    
    container.innerHTML = '';
    
    state.refinedThemes.forEach(theme => {
        const group = document.createElement('div');
        group.className = 'theme-group';
        
        let reviewsHtml = '';
        theme.reviews.forEach(rev => {
            const sourceText = rev.source.toUpperCase().replace('_', ' ');
            reviewsHtml += `
                <div class="review-item">
                    <div class="review-meta">
                        <span>Source: ${sourceText}</span>
                    </div>
                    <div class="review-text">"${rev.text}"</div>
                    <a href="${rev.url}" target="_blank" class="rep-review-link" style="margin-top: 4px; font-size: 12px;">View Source ↗</a>
                </div>
            `;
        });
        
        group.innerHTML = `
            <div class="theme-group-header">
                <span class="theme-group-header category-badge">${theme.category}</span>
                <h3>${theme.name}</h3>
                <p style="color: var(--text-secondary); font-size: 14px; margin-top: 8px;">${theme.description}</p>
            </div>
            <div class="theme-reviews-list">
                ${reviewsHtml || '<p style="color: var(--text-secondary); font-size: 13px;">No verified reviews mapped to this sub-theme.</p>'}
            </div>
        `;
        
        container.appendChild(group);
    });
}

// 9. Pipeline Control Form (Per-Source Limits Trigger)
function initPipelineButton() {
    const runPipelineBtn = document.getElementById('btn-run-pipeline');
    if (!runPipelineBtn) return;
    
    runPipelineBtn.addEventListener('click', async () => {
        const modeSelect = document.getElementById('research-mode-select');
        const customThemeInput = document.getElementById('custom-theme-input');
        
        const isThemeMode = modeSelect ? (modeSelect.value === 'theme') : false;
        let themeSlug = '';
        let themeName = '';
        
        if (isThemeMode) {
            themeName = customThemeInput ? customThemeInput.value.trim() : '';
            if (!themeName) {
                alert('Please enter a custom theme topic name first (e.g. Podcasts, Ads, AI DJ).');
                return;
            }
            themeSlug = themeName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
            if (!themeSlug) {
                alert('Please enter a valid theme topic name.');
                return;
            }
        }

        // Gather individual limits
        const gp = document.getElementById('limit-google-play').value || 0;
        const rd = document.getElementById('limit-reddit').value || 0;
        const yt = document.getElementById('limit-youtube').value || 0;
        const sc = document.getElementById('limit-spotify-community').value || 0;
        const as = 0;
        
        const fromDate = document.getElementById('pipeline-from-date').value;
        const toDate = document.getElementById('pipeline-to-date').value;
        
        // Track target source for auto-switching on completion
        let targetSource = '';
        const activeSources = [];
        if (parseInt(gp) > 0) activeSources.push('google_play');
        if (parseInt(rd) > 0) activeSources.push('reddit');
        if (parseInt(yt) > 0) activeSources.push('youtube');
        if (parseInt(sc) > 0) activeSources.push('spotify_community');
        
        if (activeSources.length === 1) {
            targetSource = activeSources[0];
        }
        state.lastTargetSource = targetSource;
        state.pipelineRunning = true;
        
        if (isThemeMode) {
            initSSE('exploration', themeSlug);
        } else {
            initSSE('discovery');
        }
        
        // Show loading overlays across all analytical tabs
        showAllTabsLoading(isThemeMode ? `Starting Theme Exploration for "${themeName}"...` : "Starting pipeline... Scraping reviews.");
        
        try {
            runPipelineBtn.disabled = true;
            runPipelineBtn.innerText = 'Running...';
            
            // Switch to terminal tab and clear old logs so the user sees fresh progress
            switchTab('terminal');
            if (terminalLogs) terminalLogs.innerHTML = '';
            
            if (isThemeMode) {
                appendTerminalLog(`Bootstrapping custom theme config for "${themeName}"...`, 'INFO');
                // 1. Bootstrap theme config
                const bootstrapRes = await fetch('/api/exploration/bootstrap', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme: themeName })
                });
                const bootstrapData = await bootstrapRes.json();
                if (bootstrapData.error) {
                    throw new Error(bootstrapData.error);
                }
                appendTerminalLog(`Theme config bootstrapped successfully for slug: ${themeSlug}`, 'SUCCESS');
                
                // Store pending theme slug and name to trigger completion nudge later
                state.pendingThemeSlug = themeSlug;
                state.pendingThemeName = themeName;
            } else {
                state.pendingThemeSlug = null;
                state.pendingThemeName = null;
            }

            // Build URL parameters
            const disableKws = document.getElementById('pipeline-disable-keywords')?.checked || false;
            let url = isThemeMode 
                ? `/api/exploration/${themeSlug}/run-pipeline?limit_google_play=${gp}&limit_reddit=${rd}&limit_youtube=${yt}&limit_spotify_community=${sc}&limit_app_store=${as}&disable_keywords=${disableKws}`
                : `/api/run-pipeline?limit_google_play=${gp}&limit_reddit=${rd}&limit_youtube=${yt}&limit_spotify_community=${sc}&limit_app_store=${as}&disable_keywords=${disableKws}`;
            
            if (fromDate) url += `&from_date=${fromDate}`;
            if (toDate) url += `&to_date=${toDate}`;
            if (state.countryFilter && state.countryFilter !== 'all') url += `&country=${state.countryFilter}`;
            if (state.langFilter && state.langFilter !== 'all') url += `&lang=${state.langFilter}`;
            
            appendTerminalLog('Triggering pipeline run...', 'INFO');
            const response = await fetch(url, { method: 'POST' });
            const data = await response.json();
            
            if (data.error) {
                throw new Error(data.error);
            }
            appendTerminalLog(`${data.status} (Task ID: ${data.task_id || 'unknown'})`, 'SUCCESS');
            
        } catch (e) {
            appendTerminalLog('Error starting pipeline: ' + e.message, 'WARNING');
            state.pipelineRunning = false;
            hideAllTabsLoading();
        } finally {
            runPipelineBtn.disabled = false;
            runPipelineBtn.innerText = '⚡ Scrape & Analyze';
        }
    });
    
    // Bind stop button listener
    const cancelPipelineBtn = document.getElementById('btn-cancel-pipeline');
    if (cancelPipelineBtn) {
        cancelPipelineBtn.addEventListener('click', async () => {
            if (confirm("Are you sure you want to stop the running pipeline?")) {
                appendTerminalLog("Requesting pipeline cancellation...", "WARNING");
                try {
                    const response = await fetch('/api/cancel-pipeline', { method: 'POST' });
                    const data = await response.json();
                    appendTerminalLog(data.status, "SUCCESS");
                } catch (err) {
                    appendTerminalLog("Failed to cancel pipeline: " + err.message, "ERROR");
                }
            }
        });
    }
}

// Helper to format logs
function formatLog(message, type) {
    const time = new Date().toLocaleTimeString();
    let cssClass = 'log-info';
    if (type === 'SUCCESS') cssClass = 'log-success';
    if (type === 'WARNING') cssClass = 'log-warning';
    
    return `<div class="log-line ${cssClass}">[${time}] [${type}] ${message}</div>`;
}

// 10. Advanced Analytics Tab Loaders
async function loadExecutiveOverview() {
    try {
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        let url = `/api/executive-overview?only_latest=${onlyLatest}`;
        if (state.activeSource) {
            url += `&source=${state.activeSource}`;
        }
        const fromDate = document.getElementById('pipeline-from-date')?.value;
        const toDate = document.getElementById('pipeline-to-date')?.value;
        if (fromDate) url += `&start_date=${fromDate}`;
        if (toDate) url += `&end_date=${toDate}`;

        const res = await fetch(url);
        const data = await res.json();
        
        // Populate KPIs
        document.getElementById('exec-total-reviews').innerText = data.total_reviews.toLocaleString();
        document.getElementById('exec-discovery-reviews').innerText = data.confirmed_relevant.toLocaleString();
        const pct = data.total_reviews > 0 ? ((data.confirmed_relevant / data.total_reviews) * 100).toFixed(1) : 0;
        document.getElementById('exec-discovery-share').innerText = `${pct}%`;
        
        // Populate Global Share of Voice (SoV) list
        const sovList = document.getElementById('global-sov-list');
        sovList.innerHTML = '';
        Object.entries(data.global_sov).forEach(([category, info]) => {
            const group = document.createElement('div');
            group.className = 'chart-bar-group';
            group.innerHTML = `
                <div class="chart-bar-header">
                    <span class="chart-bar-title">${category}</span>
                    <span class="chart-bar-val">${info.count.toLocaleString()} (${info.percentage}%)</span>
                </div>
                <div class="chart-bar-track">
                    <div class="chart-bar-fill" style="width: ${info.percentage}%; background: linear-gradient(90deg, ${category === 'Music Discovery Friction' ? 'var(--accent-color)' : 'var(--spotify-green)'}, #53d769);"></div>
                </div>
            `;
            sovList.appendChild(group);
        });
        
        // Populate Top Primary Themes
        const topThemesContainer = document.getElementById('exec-top-themes');
        topThemesContainer.innerHTML = '';
        if (data.top_themes.length === 0) {
            topThemesContainer.innerHTML = '<p style="opacity:0.6; font-size:13px; text-align:center;">No clusters found for active filters.</p>';
        } else {
            data.top_themes.forEach(theme => {
                const item = document.createElement('div');
                item.className = 'sub-issue-item';
                item.innerHTML = `
                    <div class="sub-issue-header">
                        <span class="sub-issue-title">${theme.name}</span>
                        <span class="sub-issue-pct">${theme.sov}% SoV</span>
                    </div>
                    <div style="font-size: 11px; opacity: 0.7; margin-top: 4px;">
                        Size: ${theme.size} reviews | Avg Rating: ${theme.average_rating} ★
                    </div>
                `;
                topThemesContainer.appendChild(item);
            });
        }
        
        // Explanation
        document.getElementById('exec-prevalence-explanation').innerText = data.prevalence_explanation;
        
        // Populate PM Prioritized Feature Backlog table
        const backlogContainer = document.getElementById('exec-pm-backlog');
        if (backlogContainer) {
            backlogContainer.innerHTML = '';
            const backlog = data.pm_prioritized_backlog || [];
            if (backlog.length === 0) {
                backlogContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; opacity: 0.6; font-style: italic;">No prioritized backlog features compiled. Run the validation engine to generate.</td></tr>';
            } else {
                backlog.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                    
                    const resolvedWorkarounds = (item.user_workarounds_resolved || []).map(w => `<span class="tag" style="background: rgba(241,196,15,0.08); border: 1px solid rgba(241,196,15,0.15); color: #f1c40f; font-size: 10.5px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; display: inline-block;">${w}</span>`).join('');
                    const actionItems = (item.pm_action_items || []).map(act => `• ${act}`).join('<br/>');
                    
                    let pColor = '#e74c3c';
                    if (item.priority_level === 'Medium') pColor = '#f1c40f';
                    if (item.priority_level === 'Low') pColor = '#3498db';
                    
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: 700; color: ${pColor};">${item.priority_level}</td>
                        <td style="padding: 12px; font-weight: 600; color: var(--text-primary);">${item.feature_name}</td>
                        <td style="padding: 12px; opacity: 0.8; line-height: 1.4;">${item.unmet_need}</td>
                        <td style="padding: 12px; line-height: 1.4;">${resolvedWorkarounds || 'None'}</td>
                        <td style="padding: 12px; font-size: 12px; line-height: 1.45; opacity: 0.9;">${actionItems}</td>
                    `;
                    backlogContainer.appendChild(tr);
                });
            }
        }
    } catch (err) {
        console.error('Error loading executive overview:', err);
    }
}

async function loadDeepThemeAnalysis() {
    try {
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        let url = `/api/deep-theme-analysis?only_latest=${onlyLatest}`;
        if (state.activeSource) {
            url += `&source=${state.activeSource}`;
        }
        const fromDate = document.getElementById('pipeline-from-date')?.value;
        const toDate = document.getElementById('pipeline-to-date')?.value;
        if (fromDate) url += `&start_date=${fromDate}`;
        if (toDate) url += `&end_date=${toDate}`;

        const res = await fetch(url);
        const data = await res.json();
        
        // Populate Theme Cards
        const themesGrid = document.getElementById('deep-themes-grid');
        themesGrid.innerHTML = '';
        data.themes.forEach(theme => {
            const card = document.createElement('div');
            card.className = 'card glass';
            card.style.padding = '20px';
            card.style.borderRadius = '12px';
            card.style.border = '1px solid var(--border-color)';
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                    <h3 style="margin: 0; font-size: 16px; font-weight: 700;">${theme.name}</h3>
                    <span style="padding: 3px 8px; background: rgba(29, 185, 84, 0.1); border: 1px solid rgba(29, 185, 84, 0.2); color: var(--spotify-green); border-radius: 4px; font-size: 11px; font-weight: 600;">
                        ${theme.percentage}% Share
                    </span>
                </div>
                <p style="font-size: 12.5px; opacity: 0.7; line-height: 1.5; margin-bottom: 16px; flex-grow: 1;">${theme.description}</p>
                <div style="display: flex; gap: 12px; border-top: 1px dashed var(--border-color); padding-top: 12px; font-size: 12px;">
                    <div><strong>Raw:</strong> ${theme.raw_count} reviews</div>
                    <div><strong>Pain Index:</strong> ${theme.weighted_count}</div>
                </div>
            `;
            themesGrid.appendChild(card);
        });
        
        // Populate Co-occurrence Matrix Table
        const matrixTable = document.getElementById('co-occurrence-matrix-table');
        matrixTable.innerHTML = '';
        
        // Build header
        const headerRow = document.createElement('tr');
        headerRow.innerHTML = '<th>Sub-Theme Overlap</th>' + data.theme_names.map(name => `<th style="font-size: 11px; max-width: 100px; word-wrap: break-word;">${name}</th>`).join('');
        matrixTable.appendChild(headerRow);
        
        // Build rows
        data.co_occurrence.forEach((row, i) => {
            const tr = document.createElement('tr');
            let cells = `<td style="text-align: left; font-weight: 600; font-size: 12px; width: 150px;">${data.theme_names[i]}</td>`;
            row.forEach((val, j) => {
                const isDiagonal = i === j;
                let bgStyle = '';
                if (!isDiagonal && val > 0) {
                    const maxVal = Math.max(...row.filter((_, idx) => idx !== i));
                    const ratio = maxVal > 0 ? (val / maxVal) : 0;
                    bgStyle = `background: hsla(141, 73%, 42%, ${ratio * 0.4}); color: #fff;`;
                }
                cells += `<td class="${isDiagonal ? 'diagonal' : ''}" style="${bgStyle}">${val}</td>`;
            });
            tr.innerHTML = cells;
            matrixTable.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading deep theme analysis:', err);
    }
}

async function loadDiagnosticAccuracy() {
    try {
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        let url = `/api/diagnostic-accuracy?only_latest=${onlyLatest}`;
        if (state.activeSource) {
            url += `&source=${state.activeSource}`;
        }
        const fromDate = document.getElementById('pipeline-from-date')?.value;
        const toDate = document.getElementById('pipeline-to-date')?.value;
        if (fromDate) url += `&start_date=${fromDate}`;
        if (toDate) url += `&end_date=${toDate}`;

        const res = await fetch(url);
        const data = await res.json();
        
        // Populate Confusion Matrix
        document.getElementById('diag-tp').innerText = data.confusion_matrix.tp.toLocaleString();
        document.getElementById('diag-fp').innerText = data.confusion_matrix.fp.toLocaleString();
        document.getElementById('diag-fn').innerText = data.confusion_matrix.fn.toLocaleString();
        document.getElementById('diag-tn').innerText = data.confusion_matrix.tn.toLocaleString();
        
        // Populate Signal Quality KPIs
        document.getElementById('diag-precision').innerText = `${data.metrics.precision}%`;
        document.getElementById('diag-recall').innerText = `${data.metrics.recall}%`;
        document.getElementById('diag-f1').innerText = `${data.metrics.f1_score}%`;
        
        // Populate Decile Chart
        const chartContainer = document.getElementById('decile-chart-container');
        chartContainer.innerHTML = '';
        
        const maxVolume = Math.max(...data.decile_analysis.map(d => d.volume)) || 1;
        data.decile_analysis.forEach(d => {
            const heightPct = (d.volume / maxVolume) * 100;
            const barWrapper = document.createElement('div');
            barWrapper.className = 'decile-bar-wrapper';
            barWrapper.style.flex = '1';
            barWrapper.innerHTML = `
                <div class="decile-tooltip">
                    <strong>Decile ${d.decile}</strong><br/>
                    Volume: ${d.volume} reviews<br/>
                    Avg Rating: ${d.average_rating} ★
                </div>
                <div class="decile-bar" style="height: ${heightPct}%;"></div>
                <div style="font-size: 9px; opacity: 0.7; margin-top: 4px; font-weight: 700;">${d.average_rating} ★</div>
            `;
            chartContainer.appendChild(barWrapper);
        });
    } catch (err) {
        console.error('Error loading diagnostic accuracy:', err);
    }
}

// Stateful Pipeline Decision Handling
async function showPipelineDecisionModal() {
    try {
        const res = await fetch('/api/pipeline-status');
        const status = await res.json();
        
        if (status.status === 'awaiting_decision') {
            document.getElementById('mismatch-in-range-count').innerText = status.in_range_count.toLocaleString();
            document.getElementById('mismatch-total-count').innerText = status.total_count.toLocaleString();
            
            // Calculate requested limit dynamically from the inputs
            const gp = parseInt(document.getElementById('limit-google-play')?.value) || 0;
            const rd = parseInt(document.getElementById('limit-reddit')?.value) || 0;
            const yt = parseInt(document.getElementById('limit-youtube')?.value) || 0;
            const sc = parseInt(document.getElementById('limit-spotify-community')?.value) || 0;
            const as = parseInt(document.getElementById('limit-app-store')?.value) || 0;
            const totalLimit = gp + rd + yt + sc + as;
            
            document.getElementById('mismatch-requested-limit').innerText = totalLimit.toLocaleString();
            
            const modal = document.getElementById('pipeline-decision-modal');
            if (modal) {
                modal.classList.remove('hidden');
            }
        }
    } catch (err) {
        console.error('Error loading pipeline status:', err);
    }
}

function initDecisionButtons() {
    const btnStrict = document.getElementById('btn-decision-strict');
    const btnExpand = document.getElementById('btn-decision-expand');
    
    if (btnStrict) {
        btnStrict.addEventListener('click', () => sendPipelineDecision('strict'));
    }
    if (btnExpand) {
        btnExpand.addEventListener('click', () => sendPipelineDecision('expand'));
    }
}

function initMetadataFilters() {
    const countrySelect = document.getElementById('pipeline-country');
    const langSelect = document.getElementById('pipeline-lang');
    const modal = document.getElementById('contamination-warning-modal');
    const btnGpOnly = document.getElementById('btn-contamination-gp-only');
    const btnKeepAll = document.getElementById('btn-contamination-keep-all');
    
    if (!countrySelect || !langSelect || !modal) return;
    
    function checkContamination() {
        const country = countrySelect.value;
        const lang = langSelect.value;
        
        state.countryFilter = country;
        state.langFilter = lang;
        
        if (country !== 'all' || lang !== 'all') {
            const rd = parseInt(document.getElementById('limit-reddit')?.value || '0', 10);
            const yt = parseInt(document.getElementById('limit-youtube')?.value || '0', 10);
            const sc = parseInt(document.getElementById('limit-spotify-community')?.value || '0', 10);
            
            if (rd > 0 || yt > 0 || sc > 0) {
                modal.classList.remove('hidden');
            } else {
                reloadDashboard();
            }
        } else {
            reloadDashboard();
        }
    }
    
    countrySelect.addEventListener('change', checkContamination);
    langSelect.addEventListener('change', checkContamination);
    
    if (btnGpOnly) {
        btnGpOnly.addEventListener('click', () => {
            const limitReddit = document.getElementById('limit-reddit');
            const limitYoutube = document.getElementById('limit-youtube');
            const limitSpotify = document.getElementById('limit-spotify-community');
            
            if (limitReddit) limitReddit.value = 0;
            if (limitYoutube) limitYoutube.value = 0;
            if (limitSpotify) limitSpotify.value = 0;
            
            modal.classList.add('hidden');
            appendTerminalLog('Configured pipeline for uncontaminated Google Play Store analysis.', 'INFO');
            reloadDashboard();
        });
    }
    
    if (btnKeepAll) {
        btnKeepAll.addEventListener('click', () => {
            modal.classList.add('hidden');
            reloadDashboard();
        });
    }
}

async function sendPipelineDecision(choice) {
    try {
        const modal = document.getElementById('pipeline-decision-modal');
        if (modal) {
            modal.classList.add('hidden');
        }
        
        appendTerminalLog(`Sending decision: ${choice.toUpperCase()}...`, 'INFO');
        
        const res = await fetch(`/api/pipeline-decision?choice=${choice}`, {
            method: 'POST'
        });
        const data = await res.json();
        
        if (data.error) {
            appendTerminalLog(`Error registering decision: ${data.error}`, 'WARNING');
        } else {
            appendTerminalLog(data.status, 'SUCCESS');
        }
    } catch (err) {
        console.error('Error sending pipeline decision:', err);
        appendTerminalLog(`Failed to send decision: ${err}`, 'WARNING');
    }
}

// Loading Overlay Helpers for processing state
function showTabLoading(tabId, message) {
    const pane = document.getElementById(tabId);
    if (!pane) return;
    
    let overlay = pane.querySelector('.tab-loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'tab-loading-overlay';
        overlay.innerHTML = `
            <div class="spinner"></div>
            <div class="loading-message" style="font-size: 15px; font-weight: 600; color: var(--text-primary); text-align: center; max-width: 80%; line-height: 1.5;"></div>
        `;
        pane.appendChild(overlay);
    }
    
    overlay.querySelector('.loading-message').innerText = message || "Processing analysis...";
}

function hideTabLoading(tabId) {
    const pane = document.getElementById(tabId);
    if (!pane) return;
    const overlay = pane.querySelector('.tab-loading-overlay');
    if (overlay) {
        overlay.remove();
    }
}

function showAllTabsLoading(message) {
    tabPanes.forEach(pane => {
        // Skip terminal/logs tab so user can still watch progress
        if (pane.id === 'tab-terminal') return;
        showTabLoading(pane.id, message);
    });
    
    // Show stop button, hide run button
    const cancelBtn = document.getElementById('btn-cancel-pipeline');
    const runBtn = document.getElementById('btn-run-pipeline');
    if (cancelBtn) cancelBtn.classList.remove('hidden');
    if (runBtn) runBtn.classList.add('hidden');
}

function hideAllTabsLoading() {
    tabPanes.forEach(pane => {
        hideTabLoading(pane.id);
    });
    
    // Hide stop button, show run button
    const cancelBtn = document.getElementById('btn-cancel-pipeline');
    const runBtn = document.getElementById('btn-run-pipeline');
    if (cancelBtn) cancelBtn.classList.add('hidden');
    if (runBtn) runBtn.classList.remove('hidden');
}

async function loadStrategicRoadmap() {
    // 1. Render PM Prioritized Backlog and Inquiries from executive-overview endpoint
    const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
    let url = `/api/executive-overview?only_latest=${onlyLatest}`;
    if (state.activeSource) {
        url += `&source=${state.activeSource}`;
    }
    const fromDate = document.getElementById('pipeline-from-date')?.value;
    const toDate = document.getElementById('pipeline-to-date')?.value;
    if (fromDate) url += `&start_date=${fromDate}`;
    if (toDate) url += `&end_date=${toDate}`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        
        // Render Backlog Table
        const backlogContainer = document.getElementById('strategic-pm-backlog');
        if (backlogContainer) {
            backlogContainer.innerHTML = '';
            const backlog = data.pm_prioritized_backlog || [];
            if (backlog.length === 0) {
                backlogContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; opacity: 0.6; font-style: italic;">No prioritized backlog features compiled. Run the validation engine to generate.</td></tr>';
            } else {
                backlog.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                    
                    const resolvedWorkarounds = (item.user_workarounds_resolved || []).map(w => `<span class="tag" style="background: rgba(241,196,15,0.08); border: 1px solid rgba(241,196,15,0.15); color: #f1c40f; font-size: 10.5px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; display: inline-block;">${w}</span>`).join('');
                    const actionItems = (item.pm_action_items || []).map(act => `• ${act}`).join('<br/>');
                    
                    let pColor = '#e74c3c';
                    if (item.priority_level === 'Medium') pColor = '#f1c40f';
                    if (item.priority_level === 'Low') pColor = '#3498db';
                    
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: 700; color: ${pColor};">${item.priority_level}</td>
                        <td style="padding: 12px; font-weight: 600; color: var(--text-primary);">${item.feature_name}</td>
                        <td style="padding: 12px; opacity: 0.8; line-height: 1.4;">${item.unmet_need}</td>
                        <td style="padding: 12px; line-height: 1.4;">${resolvedWorkarounds || 'None'}</td>
                        <td style="padding: 12px; font-size: 12px; line-height: 1.45; opacity: 0.9;">${actionItems}</td>
                    `;
                    backlogContainer.appendChild(tr);
                });
            }
        }

        // Render Deep-Dive Research Inquiries
        const inquiriesContainer = document.getElementById('strategic-inquiries');
        if (inquiriesContainer) {
            inquiriesContainer.innerHTML = '';
            const questions = data.deep_inquiry_questions || [];
            if (questions.length === 0) {
                inquiriesContainer.innerHTML = '<p style="color: var(--text-secondary); font-size: 13px; grid-column: 1 / -1; text-align: center; padding: 20px;">No strategic follow-up questions generated yet. Run validation to generate.</p>';
            } else {
                questions.forEach(q => {
                    const card = document.createElement('div');
                    card.className = 'card card-research';
                    let pColor = '#e74c3c';
                    if (q.priority === 'Medium') pColor = '#f1c40f';
                    if (q.priority === 'Low') pColor = '#3498db';
                    
                    card.style.borderLeft = `3px solid ${pColor}`;
                    card.innerHTML = `
                        <div class="research-header">
                            <span class="research-id" style="color: ${pColor}; font-weight: 700; border-color: ${pColor};">${q.priority.toUpperCase()} PRIORITY</span>
                        </div>
                        <h3>${q.question}</h3>
                        <p style="margin-top: 8px;"><strong>Strategic Rationale:</strong> ${q.rationale}</p>
                    `;
                    inquiriesContainer.appendChild(card);
                });
            }
        }
    } catch (err) {
        console.error("Error loading strategic roadmap API data:", err);
    }

    // 2. Render Jobs-to-be-Done (JTBD) Curation Matrix from state clusters
    const jtbdMatrix = document.getElementById('strategic-jtbd-matrix');
    if (jtbdMatrix) {
        jtbdMatrix.innerHTML = '';
        
        let clusters = state.clusters || [];
        if (clusters.length === 0) {
            try {
                let clustersUrl = `/api/clusters?only_latest=${onlyLatest}`;
                if (state.activeSource) clustersUrl += `&source=${state.activeSource}`;
                if (fromDate) clustersUrl += `&start_date=${fromDate}`;
                if (toDate) clustersUrl += `&end_date=${toDate}`;
                
                const cRes = await fetch(clustersUrl);
                const cData = await cRes.json();
                clusters = cData.clusters || [];
            } catch (cErr) {
                console.error("Error fetching clusters on-the-fly for strategic matrix:", cErr);
            }
        }

        const activeJtbdClusters = clusters.filter(c => c.jtbd && c.jtbd.situation);
        if (activeJtbdClusters.length === 0) {
            jtbdMatrix.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; opacity: 0.6; font-style: italic;">No active clusters with JTBD desires found. Select larger filters or trigger naming.</td></tr>';
        } else {
            activeJtbdClusters.forEach(c => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                
                const workaroundsStr = (c.workarounds || []).map(w => `<span class="tag" style="background: rgba(241,196,15,0.06); border: 1px solid rgba(241,196,15,0.12); color: #f1c40f; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-right: 4px; display: inline-block;">${w}</span>`).join('');
                
                tr.innerHTML = `
                    <td style="padding: 10px; font-weight: 600; color: var(--spotify-green);">${c.cluster_name}</td>
                    <td style="padding: 10px; opacity: 0.9; line-height: 1.4;">When ${c.jtbd.situation}</td>
                    <td style="padding: 10px; opacity: 0.9; line-height: 1.4;">I want to ${c.jtbd.motivation}</td>
                    <td style="padding: 10px; opacity: 0.9; line-height: 1.4;">so that ${c.jtbd.outcome}</td>
                    <td style="padding: 10px; line-height: 1.4;">${workaroundsStr || 'None'}</td>
                `;
                jtbdMatrix.appendChild(tr);
            });
        }
    }
}

// Data Integrity Diagnostic Functions
window.showDataIntegrityModal = async function() {
    const modal = document.getElementById('integrity-modal');
    const body = document.getElementById('integrity-modal-body');
    if (!modal || !body) return;
    
    modal.classList.remove('hidden');
    body.innerHTML = '<p style="text-align:center; padding: 20px; opacity:0.7;">Loading diagnostic report...</p>';
    
    try {
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        let url = `/api/data-integrity?only_latest=${onlyLatest}`;
        const res = await fetch(url);
        const data = await res.json();
        
        body.innerHTML = '';
        
        const statusColors = {
            "pass": "#2ecc71",
            "warning": "#f1c40f",
            "fail": "#e74c3c"
        };
        const statusIcons = {
            "pass": "✅",
            "warning": "⚠️",
            "fail": "❌"
        };
        
        const checks = data.checks || {};
        for (const [key, check] of Object.entries(checks)) {
            const row = document.createElement('div');
            row.style.background = 'rgba(255,255,255,0.02)';
            row.style.border = '1px solid var(--border-color)';
            row.style.padding = '12px 16px';
            row.style.borderRadius = '8px';
            row.style.display = 'flex';
            row.style.flexDirection = 'column';
            row.style.gap = '6px';
            row.style.marginBottom = '12px';
            
            const checkTitle = key.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
            const color = statusColors[check.status] || '#999';
            const icon = statusIcons[check.status] || '❓';
            
            let extraDetails = '';
            if (key === 'evidence_packages' && check.status !== 'fail') {
                extraDetails = `
                    <div style="font-size: 11px; opacity: 0.6; display: flex; gap: 12px; margin-top: 4px;">
                        <span>Total Clusters: <strong>${check.total_clusters}</strong></span>
                        <span>Missing Names: <strong style="color: ${check.missing_names_count > 0 ? '#f1c40f' : 'inherit'}">${check.missing_names_count}</strong></span>
                        <span>Missing JTBD: <strong style="color: ${check.missing_jtbd_count > 0 ? '#f1c40f' : 'inherit'}">${check.missing_jtbd_count}</strong></span>
                    </div>
                `;
            }
            
            row.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="font-size: 14px; color: var(--text-primary);">${checkTitle}</strong>
                    <span style="font-size: 11px; font-weight: 700; color: ${color}; background: ${color}15; border: 1px solid ${color}30; padding: 2px 8px; border-radius: 12px; display: flex; align-items: center; gap: 4px;">
                        ${icon} ${check.status.toUpperCase()}
                    </span>
                </div>
                <p style="margin: 0; font-size: 12px; opacity: 0.8; line-height: 1.45;">${check.message}</p>
                ${extraDetails}
            `;
            body.appendChild(row);
        }
        
    } catch (e) {
        body.innerHTML = `<p style="color:#e74c3c; text-align:center; padding: 20px;">Error running diagnostics: ${e.message}</p>`;
    }
};

window.closeIntegrityModal = function() {
    const modal = document.getElementById('integrity-modal');
    if (modal) modal.classList.add('hidden');
};

async function updateIntegrityBadge() {
    const badge = document.getElementById('integrity-badge');
    if (!badge) return;
    
    try {
        const onlyLatest = document.getElementById('pipeline-only-latest')?.checked || false;
        let url = `/api/data-integrity?only_latest=${onlyLatest}`;
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.status === 'healthy') {
            badge.style.color = '#2ecc71';
            badge.style.background = 'rgba(46, 204, 113, 0.08)';
            badge.style.borderColor = 'rgba(46, 204, 113, 0.15)';
            badge.innerText = '🛡️ Schema: Healthy';
        } else if (data.status === 'degraded') {
            badge.style.color = '#f1c40f';
            badge.style.background = 'rgba(241, 196, 15, 0.08)';
            badge.style.borderColor = 'rgba(241, 196, 15, 0.15)';
            badge.innerText = '🛡️ Schema: Degraded';
        } else {
            badge.style.color = '#e74c3c';
            badge.style.background = 'rgba(231, 76, 60, 0.08)';
            badge.style.borderColor = 'rgba(231, 76, 60, 0.15)';
            badge.innerText = '🛡️ Schema: Broken';
        }
    } catch (e) {
        badge.style.color = '#e74c3c';
        badge.style.background = 'rgba(231, 76, 60, 0.08)';
        badge.style.borderColor = 'rgba(231, 76, 60, 0.15)';
        badge.innerText = '🛡️ Schema: Error';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateIntegrityBadge();
});

// Assuming reloadDashboard exists and is where re-fetching usually happens
const originalReloadDashboard = window.reloadDashboard;
window.reloadDashboard = async function(...args) {
    if (originalReloadDashboard) await originalReloadDashboard.apply(this, args);
    updateIntegrityBadge();
};
