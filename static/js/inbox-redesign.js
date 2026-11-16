/* SPDX-License-Identifier: Apache-2.0 */
/**
 * InboxRedesign - Inbox JavaScript Controller
 * HillDesk Congressional Scheduling Application
 *
 * Shows events requiring attention:
 * - Events needing human review (AI extraction review) - small "Needs Review" badge
 * - Events needing approval routing review - approval flow with status colors
 *
 * Both types are combined in a single view sorted by creation date.
 */

class InboxRedesign {
    constructor(config = {}) {
        this.config = {
            apiUrl: config.apiUrl || '/api/events/',
            approvalApiUrl: config.approvalApiUrl || '/api/events/needs-my-approval/',
            changeSuggestionsUrl: config.changeSuggestionsUrl || '/api/change-suggestions/?origin=email_ingestion&status=pending',
            // Emails the pipeline set aside for a human decision (auth failures,
            // digests, unknown-event cancellations...). Shown as "Needs a decision".
            triageApiUrl: config.triageApiUrl || '/email/api/triage/',
            divertedApiUrl: config.divertedApiUrl || '/email/api/diverted/',
            divertedActionUrl: config.divertedActionUrl || '/email/diverted/',
            triageActionUrl: config.triageActionUrl || '/email/triage/',
            suggestionReviewUrl: config.suggestionReviewUrl || '/api/suggestions/',
            eventChoicesUrl: config.eventChoicesUrl || '/api/event-choices/',
            eventEditingUrl: config.eventEditingUrl || '/event-editing/',
            csrfToken: config.csrfToken || '',
            filterChoices: config.filterChoices || {},
            debounceDelay: 300,
            pageSize: 50
        };

        this.state = {
            filters: {
                status: [],
                type: [],
                format: []
            },
            search: '',
            sortBy: '-created', // Default: newest first
            page: 1,
            events: [],
            totalCount: 0,
            filteredCount: 0,
            hasMore: false,
            isLoading: false,
            sidebarOpen: false,
            showExtractedEvents: true, // Show AI-extracted events by default
            showStaffReview: true, // Show staff review/approval events by default
            showPastItems: false, // Hide resolved/past items by default (incl. dismissed)
            displayLimit: 50, // Number of items currently rendered
            displayInitial: 50, // Initial / post-filter-reset render count
            displayStep: 25, // How many more items each Load More click reveals
            totalResolvedCount: 0, // Track total resolved items
            // IDs resolved in this session (dismissed, fully reviewed, approved,
            // or sent back) — kept visible until the page is reloaded so the user
            // can revisit or undo them without enabling "Show resolved".
            recentlyResolvedIds: new Set(),
            detailPanelOpen: false,
            detailPanelEventId: null,
            detailPanelEventData: null
        };

        this.elements = {};
        this.searchTimeout = null;
        this._clickTimer = null;
        this._clickEventId = null;
        this._CLICK_DELAY = 220;
    }

    /**
     * Initialize the inbox component
     */
    init() {
        console.log('Initializing InboxRedesign...');
        this.cacheElements();
        this.state.view = new URLSearchParams(window.location.search).get('view') === 'diverted'
            ? 'diverted' : 'inbox';
        this.bindEvents();
        this._applyViewChrome();
        this.loadFilterChoices();
        this.fetchEvents();
        this.renderEmptyDetailPanel();
        this._applyUrlFilters();
    }

    _applyUrlFilters() {
        const params = new URLSearchParams(window.location.search);
        const filter = params.get('filter');
        if (!filter) return;

        if (filter === 'pending_approval') {
            this.state.showStaffReview = true;
            this.state.showExtractedEvents = false;
        } else if (filter === 'needs_review') {
            this.state.showExtractedEvents = true;
            this.state.showStaffReview = false;
        }

        this._pendingUrlFilter = filter;
        // Apply the filter silently (sidebar stays closed) and draw the eye to
        // the filter button with a one-shot pulse instead of opening the menu.
        this.updateFiltersButtonState();
        this.pulseFiltersButton();
    }

    /**
     * Briefly pulse the filter button(s) to signal that a filter is active —
     * used when a page is opened via a deep-link that pre-applies a filter.
     * The animation class removes itself once it finishes so the steady
     * has-filters glow remains.
     */
    pulseFiltersButton() {
        [this.elements.filtersToggleBtn, this.elements.filtersToggleBtnInline].forEach((btn) => {
            if (!btn) return;
            btn.classList.remove('filter-pulse');
            // Force reflow so re-adding the class restarts the animation.
            void btn.offsetWidth;
            btn.classList.add('filter-pulse');
            btn.addEventListener('animationend', () => {
                btn.classList.remove('filter-pulse');
            }, { once: true });
        });
    }

    /**
     * Cache DOM elements for performance
     */
    cacheElements() {
        this.elements = {
            // Sidebar
            sidebar: document.getElementById('inbox-filter-sidebar'),
            sidebarOverlay: document.getElementById('inbox-sidebar-overlay'),
            sidebarContent: document.getElementById('filter-sidebar-content'),
            sidebarCloseBtn: document.getElementById('sidebar-close-btn'),
            filtersToggleBtn: document.getElementById('filters-toggle-btn'),
            filtersToggleBtnInline: document.getElementById('filters-toggle-btn-inline'),

            // Header
            searchInput: document.getElementById('inbox-search-input'),
            searchClear: document.getElementById('inbox-search-clear'),
            sortSelect: document.getElementById('inbox-sort-select'),
            showPastItemsCheckbox: document.getElementById('show-past-items'),
            headerSelects: document.querySelectorAll('.schedule-header-select'),

            // Event list
            viewContainer: document.getElementById('inbox-view-container'),
            eventList: document.getElementById('inbox-event-list'),
            loadMore: document.getElementById('inbox-load-more'),
            loadMoreBtn: document.getElementById('load-more-btn'),

            // Detail panel
            detailPanel: document.getElementById('inbox-detail-panel'),
            detailPanelContent: document.getElementById('inbox-detail-panel-content')
        };

    }

    /**
     * Bind event handlers
     */
    bindEvents() {
        // Sidebar toggle
        if (this.elements.filtersToggleBtn) {
            this.elements.filtersToggleBtn.addEventListener('click', () => this.toggleSidebar());
        }
        if (this.elements.filtersToggleBtnInline) {
            this.elements.filtersToggleBtnInline.addEventListener('click', () => this.toggleSidebar());
        }
        if (this.elements.sidebarCloseBtn) {
            this.elements.sidebarCloseBtn.addEventListener('click', () => this.closeSidebar());
        }
        if (this.elements.sidebarOverlay) {
            this.elements.sidebarOverlay.addEventListener('click', () => this.closeSidebar());
        }

        // Search
        if (this.elements.searchInput) {
            this.elements.searchInput.addEventListener('input', (e) => this.handleSearchInput(e));
            this.elements.searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    this.clearSearch();
                }
            });
        }
        if (this.elements.searchClear) {
            this.elements.searchClear.addEventListener('click', () => this.clearSearch());
        }

        // Custom header selects (sort)
        this._bindHeaderSelects();

        // Inbox / Diverted segmented toggle (same control as Contacts)
        document.querySelectorAll('.contacts-tab[data-view]').forEach(tab => {
            tab.addEventListener('click', () => this.switchView(tab.dataset.view));
        });

        // Show resolved items checkbox
        if (this.elements.showPastItemsCheckbox) {
            this.elements.showPastItemsCheckbox.addEventListener('change', (e) => {
                this.state.showPastItems = e.target.checked;
                this.state.displayLimit = this.state.displayInitial; // Reset pagination when toggling
                this.renderEvents(); // Re-render without fetching
            });
        }

        // Load more
        if (this.elements.loadMoreBtn) {
            this.elements.loadMoreBtn.addEventListener('click', () => this.loadMoreEvents());
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyboardShortcuts(e));
    }

    // =========================================================================
    // Sidebar Methods
    // =========================================================================

    openSidebar() {
        if (this.elements.sidebar) {
            this.elements.sidebar.classList.remove('collapsed');
            this.elements.sidebar.classList.add('open');
            this.state.sidebarOpen = true;
        }
        if (this.elements.sidebarOverlay && window.innerWidth <= 1024) {
            this.elements.sidebarOverlay.classList.add('visible');
        }
    }

    closeSidebar() {
        if (this.elements.sidebar) {
            this.elements.sidebar.classList.add('collapsed');
            this.elements.sidebar.classList.remove('open');
            this.state.sidebarOpen = false;
        }
        if (this.elements.sidebarOverlay) {
            this.elements.sidebarOverlay.classList.remove('visible');
        }
    }

    toggleSidebar() {
        if (this.state.sidebarOpen) {
            this.closeSidebar();
        } else {
            this.openSidebar();
        }
    }

    // =========================================================================
    // Filter Methods
    // =========================================================================

    async loadFilterChoices() {
        try {
            const response = await fetch(this.config.eventChoicesUrl);
            if (!response.ok) throw new Error('Failed to load filter choices');

            const data = await response.json();
            this.config.filterChoices = data;
            this.renderFilters();
        } catch (error) {
            console.error('Error loading filter choices:', error);
            this.renderFilters();
        }
    }

    renderFilters() {
        if (!this.elements.sidebarContent) return;

        const rawStatuses = this.config.filterChoices.event_statuses || [];
        const rawTypes = this.config.filterChoices.event_types || [];

        // Normalise: API may return [{value, label}] objects or [value, label] tuples
        const normalise = (item) => {
            if (Array.isArray(item)) return { value: item[0], label: item[1] };
            return { value: item.value, label: item.label };
        };
        const event_statuses = rawStatuses.map(normalise);
        const event_types = rawTypes.map(normalise);

        const html = `
            <!-- Inbox Source Filter -->
            <div class="filter-section" data-filter="inbox-source">
                <div class="filter-header" onclick="inboxRedesign.toggleFilterSection('inbox-source')">
                    <span>Source</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="filter-extracted-events" checked
                                   onchange="inboxRedesign.handleSourceFilter()">
                            <label for="filter-extracted-events">Extracted Events</label>
                        </div>
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="filter-staff-review" checked
                                   onchange="inboxRedesign.handleSourceFilter()">
                            <label for="filter-staff-review">Staff Review</label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Status Filter -->
            <div class="filter-section collapsed" data-filter="status">
                <div class="filter-header" onclick="inboxRedesign.toggleFilterSection('status')">
                    <span>Status</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="status-select-all" checked onchange="inboxRedesign.handleSelectAll('status', this.checked)">
                            <label for="status-select-all">Select All</label>
                        </div>
                        ${event_statuses.map(s => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="status-${s.value}" value="${s.value}" checked
                                       onchange="inboxRedesign.handleFilterChange('status', '${s.value}', this.checked)">
                                <label for="status-${s.value}">${s.label}</label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Type Filter -->
            <div class="filter-section collapsed" data-filter="type">
                <div class="filter-header" onclick="inboxRedesign.toggleFilterSection('type')">
                    <span>Type</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="type-select-all" checked onchange="inboxRedesign.handleSelectAll('type', this.checked)">
                            <label for="type-select-all">Select All</label>
                        </div>
                        ${event_types.map(t => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="type-${t.value}" value="${t.value}" checked
                                       onchange="inboxRedesign.handleFilterChange('type', '${t.value}', this.checked)">
                                <label for="type-${t.value}">${t.label}</label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Clear All Filters Button -->
            <button class="clear-all-btn" onclick="inboxRedesign.clearAllFilters()">Clear All Filters</button>
        `;

        this.elements.sidebarContent.innerHTML = html;

        if (this._pendingUrlFilter) {
            const extractedCb = document.getElementById('filter-extracted-events');
            const staffReviewCb = document.getElementById('filter-staff-review');
            if (extractedCb) extractedCb.checked = this.state.showExtractedEvents;
            if (staffReviewCb) staffReviewCb.checked = this.state.showStaffReview;
            this._pendingUrlFilter = null;
            this.updateFiltersButtonState();
            this.renderEvents();
        }
    }

    toggleFilterSection(filterType) {
        const section = this.elements.sidebarContent.querySelector(`[data-filter="${filterType}"]`);
        if (section) {
            section.classList.toggle('collapsed');
        }
    }

    handleSourceFilter() {
        const extractedCb = document.getElementById('filter-extracted-events');
        const staffReviewCb = document.getElementById('filter-staff-review');
        this.state.showExtractedEvents = extractedCb ? extractedCb.checked : true;
        this.state.showStaffReview = staffReviewCb ? staffReviewCb.checked : true;
        this.updateFiltersButtonState();
        this.renderEvents();
    }

    handleSelectAll(filterType, checked) {
        const checkboxes = this.elements.sidebarContent.querySelectorAll(
            `[data-filter="${filterType}"] input[type="checkbox"]:not([id$="-select-all"])`
        );

        if (checked) {
            this.state.filters[filterType] = [];
            checkboxes.forEach(cb => cb.checked = true);
        } else {
            checkboxes.forEach(cb => cb.checked = false);
            this.state.filters[filterType] = [];
        }

        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    handleFilterChange(filterType, value, checked) {
        const selectAllCheckbox = document.getElementById(`${filterType}-select-all`);
        const checkboxes = this.elements.sidebarContent.querySelectorAll(
            `[data-filter="${filterType}"] input[type="checkbox"]:not([id$="-select-all"])`
        );

        if (checked) {
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);
            if (allChecked) {
                this.state.filters[filterType] = [];
                if (selectAllCheckbox) selectAllCheckbox.checked = true;
            } else {
                this.state.filters[filterType] = Array.from(checkboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                if (selectAllCheckbox) selectAllCheckbox.checked = false;
            }
        } else {
            const noneChecked = Array.from(checkboxes).every(cb => !cb.checked);
            if (noneChecked) {
                this.state.filters[filterType] = [];
                if (selectAllCheckbox) selectAllCheckbox.checked = true;
                checkboxes.forEach(cb => cb.checked = true);
            } else {
                this.state.filters[filterType] = Array.from(checkboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                if (selectAllCheckbox) selectAllCheckbox.checked = false;
            }
        }

        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    clearAllFilters() {
        this.state.filters = {
            status: [],
            type: [],
            format: []
        };
        this.state.showExtractedEvents = true;
        this.state.showStaffReview = true;

        const allCheckboxes = this.elements.sidebarContent.querySelectorAll('input[type="checkbox"]');
        allCheckboxes.forEach(cb => cb.checked = true);

        this.clearSearch();

        this.state.sortBy = '-created';
        if (this.elements.sortSelect) {
            this._setHeaderSelectValue(this.elements.sortSelect, '-created');
        }

        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    // =========================================================================
    // Search Methods
    // =========================================================================

    handleSearchInput(event) {
        const query = event.target.value;

        if (this.elements.searchClear) {
            this.elements.searchClear.classList.toggle('visible', query.length > 0);
        }

        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        this.searchTimeout = setTimeout(() => {
            this.state.search = query;
            this.state.page = 1;
            this.fetchEvents();
        }, this.config.debounceDelay);
    }

    clearSearch() {
        if (this.elements.searchInput) {
            this.elements.searchInput.value = '';
        }
        if (this.elements.searchClear) {
            this.elements.searchClear.classList.remove('visible');
        }

        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        this.state.search = '';
        this.state.page = 1;
        this.fetchEvents();
    }

    // =========================================================================
    // Custom Header Selects
    // =========================================================================

    _bindHeaderSelects() {
        this.elements.headerSelects.forEach(select => {
            const trigger = select.querySelector('.schedule-header-select-trigger');
            const options = select.querySelectorAll('.schedule-header-select-option');

            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                const wasOpen = select.classList.contains('open');
                this.elements.headerSelects.forEach(s => s.classList.remove('open'));
                if (!wasOpen) select.classList.add('open');
            });

            options.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const value = option.dataset.value;
                    this._setHeaderSelectValue(select, value);
                    select.classList.remove('open');

                    if (select.id === 'inbox-sort-select') {
                        this.handleSortChange({ target: { value } });
                    }
                });
            });
        });

        document.addEventListener('click', () => {
            this.elements.headerSelects.forEach(s => s.classList.remove('open'));
        });
    }

    _setHeaderSelectValue(selectEl, value) {
        selectEl.dataset.value = value;
        const valueSpan = selectEl.querySelector('.schedule-header-select-value');
        const options = selectEl.querySelectorAll('.schedule-header-select-option');
        options.forEach(opt => {
            const isSelected = opt.dataset.value === value;
            opt.classList.toggle('selected', isSelected);
            if (isSelected && valueSpan) {
                valueSpan.textContent = opt.textContent;
            }
        });
    }

    // =========================================================================
    // Sort Methods
    // =========================================================================

    handleSortChange(event) {
        this.state.sortBy = event.target.value;
        this.state.page = 1;
        this.fetchEvents();
    }

    // =========================================================================
    // Data Fetching
    // =========================================================================

    /**
     * Switch between the inbox and the Diverted view (emails the ingestion
     * funnel filtered out). Same list, headers, search and detail panel.
     */
    switchView(view) {
        view = view === 'diverted' ? 'diverted' : 'inbox';
        if (view === this.state.view) return;
        this.state.view = view;
        this.state.events = [];
        this.closeDetailPanel();
        this._applyViewChrome();
        const url = new URL(window.location.href);
        if (view === 'diverted') url.searchParams.set('view', 'diverted');
        else url.searchParams.delete('view');
        window.history.replaceState(null, '', url);
        if (this.elements.eventList) this.elements.eventList.innerHTML = '';
        this.fetchEvents();
    }

    _applyViewChrome() {
        const diverted = this.state.view === 'diverted';
        document.querySelector('.inbox-container')?.classList.toggle('view-diverted', diverted);
        document.querySelectorAll('.contacts-tab[data-view]').forEach(tab => {
            const active = tab.dataset.view === this.state.view;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const title = document.querySelector('.schedule-page-title');
        if (title) title.textContent = diverted ? 'Diverted' : 'Inbox';
        if (this.elements.searchInput) {
            this.elements.searchInput.placeholder = diverted
                ? 'Search subject, or an exact sender address...'
                : 'Search inbox...';
        }
        this.renderEmptyDetailPanel();
    }

    async fetchDiverted() {
        const params = new URLSearchParams();
        if (this.state.search) params.append('search', this.state.search);
        const response = await fetch(`${this.config.divertedApiUrl}?${params.toString()}`, {
            headers: { 'Accept': 'application/json', 'X-CSRFToken': this.config.csrfToken }
        });
        if (!response.ok) throw new Error(`Diverted feed failed: ${response.status}`);
        const data = await response.json();
        const items = (data.results || []).map(item => ({
            id: `diverted:${item.id}`,
            title: item.subject,
            created: item.received_at,
            _inboxDate: item.received_at,
            _inboxType: 'diverted',
            _diverted: item,
            is_resolved: false
        }));
        items.sort((a, b) => {
            const dateA = new Date(a.created || 0);
            const dateB = new Date(b.created || 0);
            return this.state.sortBy === '-created' ? dateB - dateA : dateA - dateB;
        });
        if (this.state.view !== 'diverted') return;
        this.state.events = items;
        this.state.totalCount = items.length;
        this.renderEventList();
    }

    async fetchEvents(append = false) {
        if (this.state.isLoading) {
            // A view switch mid-fetch: refetch for the new view when this one ends.
            this._refetchAfterLoad = true;
            return;
        }
        const fetchView = this.state.view;

        // A fresh fetch (filter/search/sort change) collapses pagination back
        // to the first page so the user starts at the top of the new view.
        if (!append) {
            this.state.displayLimit = this.state.displayInitial;
        }

        this.state.isLoading = true;
        this.showLoading(append);

        try {
            if (this.state.view === 'diverted') {
                await this.fetchDiverted();
                return;
            }
            // Fetch all four inbox feeds in parallel: human review events,
            // approval routing events, email-ingestion change requests, and
            // emails set aside for a human decision.
            const [reviewResponse, approvalResponse, changeRequestResponse, triageResponse] = await Promise.all([
                fetch(this.buildApiUrl(), {
                    headers: {
                        'Accept': 'application/json',
                        'X-CSRFToken': this.config.csrfToken
                    }
                }),
                fetch(this.config.approvalApiUrl, {
                    headers: {
                        'Accept': 'application/json',
                        'X-CSRFToken': this.config.csrfToken
                    }
                }),
                fetch(this.config.changeSuggestionsUrl, {
                    headers: {
                        'Accept': 'application/json',
                        'X-CSRFToken': this.config.csrfToken
                    }
                }),
                fetch(this.config.triageApiUrl, {
                    headers: {
                        'Accept': 'application/json',
                        'X-CSRFToken': this.config.csrfToken
                    }
                })
            ]);

            let reviewEvents = [];
            let approvalEvents = [];
            let changeRequests = [];
            let decisionItems = [];

            // Process human review events
            if (reviewResponse.ok) {
                const reviewData = await reviewResponse.json();
                console.log('Human review events received:', reviewData);
                reviewEvents = (reviewData.results || []).map(event => {
                    // Determine if this is a resolved human review event
                    const isResolved = event.requires_human_review === false;

                    // The server's review_decision is authoritative when set
                    // (currently only 'dismissed'). Otherwise infer approved vs
                    // rejected from the extracted_fields statuses.
                    const isDismissed = event.review_decision === 'dismissed';
                    let reviewDecision = event.review_decision || '';
                    if (!reviewDecision && isResolved && event.extracted_fields) {
                        // Check if any field was rejected (meaning event was rejected)
                        const fields = Object.values(event.extracted_fields || {});
                        const hasRejected = fields.some(f => f && f.status === 'rejected');
                        reviewDecision = hasRejected ? 'rejected' : 'approved';
                    }

                    return {
                        ...event,
                        _inboxType: 'human_review',
                        is_resolved: isResolved,
                        is_dismissed: isDismissed,
                        review_decision: reviewDecision
                    };
                });
            }

            // Process approval events
            if (approvalResponse.ok) {
                const approvalData = await approvalResponse.json();
                console.log('Approval events received:', JSON.stringify(approvalData, null, 2));
                const rawApprovalEvents = approvalData.events || (Array.isArray(approvalData) ? approvalData : []);
                approvalEvents = rawApprovalEvents.map(event => {
                    console.log('Inbox: Approval event data:',
                        `id=${event.id}, title="${event.title}", group="${event.group}", type="${event.type}"`
                    );
                    return {
                        ...event,
                        _inboxType: 'needs_approval' // Mark as approval event
                    };
                });
            }

            // Process email-ingestion change requests (third feed): each group
            // is one card carrying a field-level diff against its target event.
            if (changeRequestResponse.ok) {
                const crData = await changeRequestResponse.json();
                changeRequests = (crData.results || []).map(group => ({
                    // The row gets its own id: the target event may also have
                    // its own review row, and two rows sharing an id break
                    // selection and Up/Down navigation. The panel loads the
                    // TARGET event (_targetEventId).
                    id: `cr:${group.candidate_id || group.event.id}`,
                    _targetEventId: group.event.id,
                    title: group.event.title,
                    status: group.event.status,
                    start_date: group.event.start_date,
                    start_time: group.event.start_time,
                    created: group.created_at,
                    _inboxType: 'change_request',
                    _changeGroup: group,
                    is_resolved: false
                }));
            }

            // Process emails awaiting a decision (fourth feed). The id is
            // prefixed so it can never collide with an event id; these rows
            // open their own panel and never open the event editor.
            if (triageResponse.ok) {
                const triageData = await triageResponse.json();
                decisionItems = (triageData.results || []).map(item => ({
                    id: `triage:${item.id}`,
                    title: item.subject,
                    created: item.received_at,
                    _inboxType: 'decision',
                    _triage: item,
                    is_resolved: false
                }));
            }

            // Combine and deduplicate (approval events might overlap with review events)
            const combinedEvents = [...reviewEvents];
            // Use String() to ensure consistent comparison even if IDs have different types
            const reviewEventIds = new Set(reviewEvents.map(e => String(e.id)));

            console.log('Inbox: Deduplicating events', {
                reviewCount: reviewEvents.length,
                approvalCount: approvalEvents.length,
                reviewIds: Array.from(reviewEventIds)
            });

            for (const approvalEvent of approvalEvents) {
                const approvalId = String(approvalEvent.id);
                if (!reviewEventIds.has(approvalId)) {
                    combinedEvents.push(approvalEvent);
                } else {
                    // Event exists in both - mark it as both and merge approval data
                    const existingEvent = combinedEvents.find(e => String(e.id) === approvalId);
                    if (existingEvent) {
                        existingEvent._inboxType = 'both';
                        existingEvent._approvalData = {
                            stage_id: approvalEvent.stage_id,
                            stage_order: approvalEvent.stage_order
                        };
                        existingEvent.needs_approval = true;
                        // If the approval is still pending, override resolved status
                        if (!approvalEvent.is_resolved) {
                            existingEvent.is_resolved = false;
                        }
                        // Carry over approval-specific display fields
                        existingEvent.sent_by_name = approvalEvent.sent_by_name;
                        existingEvent.current_approver_name = approvalEvent.current_approver_name;
                        existingEvent.next_approver_name = approvalEvent.next_approver_name;
                        existingEvent.is_final_approver = approvalEvent.is_final_approver;
                        existingEvent.user_approval_status = approvalEvent.user_approval_status;
                        // Save approval's created date for inbox sorting
                        // (approval API sets created = approval.created_at)
                        existingEvent._approvalCreated = approvalEvent.created;
                    }
                }
            }

            // Change-request cards are their own rows even when the target
            // event also appears in another feed — reviewing the event and
            // applying a requested change are different actions.
            combinedEvents.push(...changeRequests);
            combinedEvents.push(...decisionItems);

            console.log('Inbox: Combined events count:', combinedEvents.length);

            // Compute _inboxDate for each event:
            // - Approval-only events: created is already set to approval.created_at by the API
            // - Both (review + approval): use the more recent of event.created and approval date
            // - Review-only events: use event.created
            for (const evt of combinedEvents) {
                if (evt._inboxType === 'both' && evt._approvalCreated) {
                    const evtDate = new Date(evt.created || 0);
                    const approvalDate = new Date(evt._approvalCreated || 0);
                    evt._inboxDate = (approvalDate > evtDate ? evt._approvalCreated : evt.created);
                } else {
                    evt._inboxDate = evt.created;
                }
            }

            // Sort by inbox date (newest first by default)
            combinedEvents.sort((a, b) => {
                const dateA = new Date(a._inboxDate || a.created || 0);
                const dateB = new Date(b._inboxDate || b.created || 0);
                return this.state.sortBy === '-created' ? dateB - dateA : dateA - dateB;
            });

            if (this.state.view !== fetchView) return; // stale: view changed mid-fetch
            if (append) {
                this.state.events = [...this.state.events, ...combinedEvents];
            } else {
                this.state.events = combinedEvents;
            }

            if (this.state.view !== fetchView) return; // stale: view changed mid-fetch
            this.state.totalCount = this.state.events.length;
            // hasMore is computed in filterEventsClientSide based on displayLimit.

            this.renderEventList();

        } catch (error) {
            console.error('Error fetching events:', error);
            this.showError('Failed to load inbox. Please try again.');
        } finally {
            this.state.isLoading = false;
            this.hideLoading();
            if (this._refetchAfterLoad || this.state.view !== fetchView) {
                this._refetchAfterLoad = false;
                this.fetchEvents();
            }
        }
    }

    buildApiUrl() {
        const params = new URLSearchParams();

        // Always filter to events requiring human review
        params.append('requires_human_review', 'true');

        // Include resolved/past reviews
        params.append('include_resolved_reviews', 'true');

        // Search
        if (this.state.search) {
            params.append('search', this.state.search);
        }

        // Filters
        this.state.filters.status.forEach(s => params.append('status', s));
        this.state.filters.type.forEach(t => params.append('type', t));

        // Sort
        if (this.state.sortBy) {
            params.append('ordering', this.state.sortBy);
        }

        // Pagination
        params.append('page', this.state.page);
        params.append('page_size', this.config.pageSize);

        // Don't include archived
        params.append('include_archived', 'false');

        return `${this.config.apiUrl}?${params.toString()}`;
    }

    /**
     * Filter events client-side (mostly handled by API, but double-check)
     */
    filterEventsClientSide(events) {
        if (this.state.view === 'diverted') {
            this.state.hasMore = events.length > this.state.displayLimit;
            return events.slice(0, this.state.displayLimit);
        }
        // Filter by inbox type checkboxes
        let filtered = events.filter(event => {
            const inboxType = event._inboxType || 'human_review';
            const isExtracted = inboxType === 'human_review' || inboxType === 'both';
            const isStaffReview = inboxType === 'needs_approval' || inboxType === 'both';

            if (isExtracted && !isStaffReview && !this.state.showExtractedEvents) return false;
            if (isStaffReview && !isExtracted && !this.state.showStaffReview) return false;
            // "both" type: show if either filter is on
            if (isExtracted && isStaffReview) {
                if (!this.state.showExtractedEvents && !this.state.showStaffReview) return false;
            }
            return true;
        });

        // Filter based on showPastItems checkbox. Dismissed (false-positive)
        // items are resolved too, so the same "Show resolved" toggle reveals
        // them — they are not a separate filter. Exception: anything resolved
        // in this session (dismissed, fully reviewed, approved, or sent back)
        // stays visible until the page is reloaded, so the user can revisit or
        // undo it without turning on "Show resolved".
        if (!this.state.showPastItems) {
            filtered = filtered.filter(event =>
                !event.is_resolved || this.state.recentlyResolvedIds.has(String(event.id))
            );
        }

        // Resolved items keep their natural date-sorted position rather than
        // sinking to the bottom of their day group.
        const ordered = filtered;

        this.state.totalResolvedCount = filtered.filter(
            event => event.is_resolved && !event.is_dismissed
        ).length;

        // Uniform Load More pagination: render up to displayLimit items and
        // surface a Load More button when more exist.
        const visible = ordered.slice(0, this.state.displayLimit);
        this.state.hasMore = ordered.length > visible.length;

        return visible;
    }

    /**
     * Re-render events without fetching (for checkbox/source-filter toggles).
     * Resets the Load More cursor so the user sees the top of the new view.
     */
    renderEvents() {
        this.state.displayLimit = this.state.displayInitial;
        this.renderEventList();
    }

    loadMoreEvents() {
        // Bump the client-side display limit and re-render. fetchEvents()
        // already loads the entire combined inbox into state.events; Load More
        // just reveals the next slice.
        this.state.displayLimit += this.state.displayStep;
        this.renderEventList();
    }

    // =========================================================================
    // Rendering
    // =========================================================================

    renderEventList() {
        if (!this.elements.eventList) return;

        // Initial fetch still in flight: filter choices can resolve before the
        // events request, calling renderEvents() while state.events is still
        // empty. Keep the skeleton up rather than flashing the empty state.
        if (this.state.isLoading && this.state.events.length === 0) {
            return;
        }

        // Apply client-side filtering
        const filteredEvents = this.filterEventsClientSide(this.state.events);

        this.state.filteredCount = filteredEvents.length;

        if (filteredEvents.length === 0) {
            this.elements.eventList.innerHTML = this.renderEmptyState();
            this.hideLoadMore();
            return;
        }

        // Render events grouped by received date (created timestamp)
        const html = this.renderEventsWithReceivedHeaders(filteredEvents);

        this.elements.eventList.innerHTML = html;

        // Bind event click handlers
        this.bindEventClicks();

        // Show/hide load more button
        if (this.state.hasMore) {
            this.showLoadMore();
        } else {
            this.hideLoadMore();
        }
    }

    /**
     * Render events grouped by received date with headers
     * - "Today" for events received today
     * - "Yesterday" for events received yesterday
     * - Specific dates for older events
     * Respects sort order (newest first vs oldest first)
     */
    renderEventsWithReceivedHeaders(events) {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        // Check sort direction: -created = newest first, created = oldest first
        const isNewestFirst = this.state.sortBy === '-created';

        // Group events by received date (created field)
        const groups = new Map();
        const receivedToday = [];
        const receivedYesterday = [];

        for (const event of events) {
            // Use _inboxDate (approval routing date) if available, fall back to created
            const receivedDateStr = event._inboxDate || event.created;
            if (!receivedDateStr) {
                // Events without created date go to a special group
                if (!groups.has('unknown')) {
                    groups.set('unknown', []);
                }
                groups.get('unknown').push(event);
                continue;
            }

            const createdDate = new Date(receivedDateStr);
            const dateOnly = new Date(createdDate.getFullYear(), createdDate.getMonth(), createdDate.getDate());

            if (dateOnly.getTime() === today.getTime()) {
                receivedToday.push(event);
            } else if (dateOnly.getTime() === yesterday.getTime()) {
                receivedYesterday.push(event);
            } else {
                const dateKey = dateOnly.toISOString();
                if (!groups.has(dateKey)) {
                    groups.set(dateKey, []);
                }
                groups.get(dateKey).push(event);
            }
        }

        let html = '<div class="inbox-cards-container with-date-headers">';

        // Sort date keys based on sort direction
        const sortedDateKeys = Array.from(groups.keys())
            .filter(key => key !== 'unknown')
            .sort((a, b) => isNewestFirst
                ? new Date(b) - new Date(a)  // Newest first
                : new Date(a) - new Date(b)  // Oldest first
            );

        if (isNewestFirst) {
            // Newest first: Today -> Yesterday -> Older dates -> Unknown

            // Render "Today" section
            if (receivedToday.length > 0) {
                html += this.renderReceivedDateHeader('Today', today, true);
                for (const event of receivedToday) {
                    html += this.renderEventCard(event);
                }
            }

            // Render "Yesterday" section
            if (receivedYesterday.length > 0) {
                html += this.renderReceivedDateHeader('Yesterday', yesterday, false);
                for (const event of receivedYesterday) {
                    html += this.renderEventCard(event);
                }
            }

            // Render older dates
            for (const dateKey of sortedDateKeys) {
                const dateObj = new Date(dateKey);
                html += this.renderReceivedDateHeader(null, dateObj, false);
                for (const event of groups.get(dateKey)) {
                    html += this.renderEventCard(event);
                }
            }

            // Render unknown date events at the end
            if (groups.has('unknown') && groups.get('unknown').length > 0) {
                html += this.renderSectionHeader('Unknown Date');
                for (const event of groups.get('unknown')) {
                    html += this.renderEventCard(event);
                }
            }
        } else {
            // Oldest first: Unknown -> Older dates -> Yesterday -> Today

            // Render unknown date events first
            if (groups.has('unknown') && groups.get('unknown').length > 0) {
                html += this.renderSectionHeader('Unknown Date');
                for (const event of groups.get('unknown')) {
                    html += this.renderEventCard(event);
                }
            }

            // Render older dates (oldest first)
            for (const dateKey of sortedDateKeys) {
                const dateObj = new Date(dateKey);
                html += this.renderReceivedDateHeader(null, dateObj, false);
                for (const event of groups.get(dateKey)) {
                    html += this.renderEventCard(event);
                }
            }

            // Render "Yesterday" section
            if (receivedYesterday.length > 0) {
                html += this.renderReceivedDateHeader('Yesterday', yesterday, false);
                for (const event of receivedYesterday) {
                    html += this.renderEventCard(event);
                }
            }

            // Render "Today" section
            if (receivedToday.length > 0) {
                html += this.renderReceivedDateHeader('Today', today, true);
                for (const event of receivedToday) {
                    html += this.renderEventCard(event);
                }
            }
        }

        html += '</div>';
        return html;
    }

    /**
     * Render a date header for received date
     */
    renderReceivedDateHeader(label, date, isToday = false) {
        const currentYear = new Date().getFullYear();
        const eventYear = date.getFullYear();

        // Format the full date
        const dateOptions = eventYear !== currentYear
            ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }
            : { weekday: 'long', month: 'long', day: 'numeric' };
        const fullDateLabel = date.toLocaleDateString('en-US', dateOptions);

        if (label) {
            // "Today" or "Yesterday" with special styling
            const cssClass = isToday ? 'inbox-date-header today' : 'inbox-date-header yesterday';
            return `
                <div class="${cssClass}">
                    <span class="date-label">${label}</span>
                    <span class="day-label">${fullDateLabel}</span>
                </div>
            `;
        }

        // Regular date header
        const dateOnlyOptions = eventYear !== currentYear
            ? { month: 'long', day: 'numeric', year: 'numeric' }
            : { month: 'long', day: 'numeric' };
        const dateLabel = date.toLocaleDateString('en-US', dateOnlyOptions);
        const dayName = date.toLocaleDateString('en-US', { weekday: 'long' });

        return `
            <div class="inbox-date-header">
                <span class="date-label">${dateLabel}</span>
                <span class="day-label">${dayName}</span>
            </div>
        `;
    }

    /**
     * Render a section header (for "Unknown Date", etc.)
     */
    renderSectionHeader(title) {
        return `
            <div class="inbox-section-header">
                <span class="section-label">${title}</span>
            </div>
        `;
    }

    renderEventCard(event) {
        if (event._inboxType === 'change_request') {
            return this.renderChangeRequestCard(event);
        }
        if (event._inboxType === 'diverted') {
            return this.renderDivertedCard(event);
        }
        if (event._inboxType === 'decision') {
            return this.renderDecisionCard(event);
        }
        const typeLabel = this.getTypeLabel(event.type);
        const inboxType = event._inboxType || 'human_review';
        const isHumanReview = inboxType === 'human_review' || inboxType === 'both';
        const needsApproval = inboxType === 'needs_approval' || inboxType === 'both';

        // Check if this item is resolved (past item)
        const isResolved = event.is_resolved || false;
        const userApprovalStatus = event.user_approval_status || 'pending';
        const reviewDecision = event.review_decision || '';  // For human review items

        // Format date and time
        let dateTimeDisplay = '';
        if (event.start_date) {
            const startDate = new Date(event.start_date);

            if (event.end_date && event.end_date !== event.start_date) {
                const endDate = new Date(event.end_date);
                const startFormatted = startDate.toLocaleDateString('en-US', {
                    month: '2-digit', day: '2-digit', year: '2-digit'
                });
                const endFormatted = endDate.toLocaleDateString('en-US', {
                    month: '2-digit', day: '2-digit', year: '2-digit'
                });
                dateTimeDisplay = `Range between ${startFormatted} and ${endFormatted}`;
            } else {
                const currentYear = new Date().getFullYear();
                const eventYear = startDate.getFullYear();
                const dateOptions = eventYear !== currentYear
                    ? { month: 'long', day: 'numeric', year: 'numeric' }
                    : { month: 'long', day: 'numeric' };
                dateTimeDisplay = startDate.toLocaleDateString('en-US', dateOptions);
                if (event.start_time) {
                    const time = new Date(`2000-01-01T${event.start_time}`);
                    dateTimeDisplay += ' • ' + time.toLocaleTimeString('en-US', {
                        hour: 'numeric', minute: '2-digit', hour12: true
                    });
                    if (event.end_time) {
                        const endTime = new Date(`2000-01-01T${event.end_time}`);
                        dateTimeDisplay += ' - ' + endTime.toLocaleTimeString('en-US', {
                            hour: 'numeric', minute: '2-digit', hour12: true
                        });
                    }
                }
            }
        } else {
            dateTimeDisplay = 'No date set';
        }

        // Organization name (shown in title line)
        const orgName = event.organization || event.group || '';

        // For approval events: show date in description area, show approval flow on right
        const senderName = event.sent_by_name || event.previous_approver_name ||
                          (event._approvalData && event._approvalData.sent_by_name) ||
                          (event._approvalData && event._approvalData.previous_approver_name) || '';
        // For sent_back events: who you sent it back to
        const sentBackToName = event.sent_back_to_name || senderName;
        const nextApproverName = event.next_approver_name ||
                                (event._approvalData && event._approvalData.next_approver_name) || '';
        const isFinalApprover = event.is_final_approver !== undefined ? event.is_final_approver :
                               (event._approvalData && event._approvalData.is_final_approver) || false;

        // Approval context (compact) — folded into the tertiary meta line instead
        // of a full "Sender → YOU" flow, so each row carries exactly one badge.
        const isReReview = event.is_re_review || false;
        const sentBackByName = event.sent_back_by_name || '';
        let approvalContext = '';
        if (needsApproval && !isResolved) {
            const stageInfo = event.stage_order || (event._approvalData && event._approvalData.stage_order);
            if (userApprovalStatus === 'sent_back' && sentBackToName) {
                approvalContext = `Sent back to ${this.escapeHtml(sentBackToName)}`;
            } else if (isReReview && sentBackByName) {
                approvalContext = `Sent back by ${this.escapeHtml(sentBackByName)}`;
            } else if (senderName) {
                approvalContext = `From ${this.escapeHtml(senderName)}`;
            }
            if (stageInfo) {
                approvalContext += (approvalContext ? ' · ' : '') + `Stage ${stageInfo}`;
            }
            if (isFinalApprover) {
                approvalContext += (approvalContext ? ' · ' : '') + 'Final approver';
            }
        }

        // Email-ingestion meta chips (additive; ingestion spec §10.3): intent,
        // possible-duplicate warning, channel, and pending-series indicator.
        let ingestionChips = '';
        const efMeta = event.extracted_fields && event.extracted_fields.meta;
        if (isHumanReview && efMeta && efMeta.origin === 'email_ingestion' && !isResolved) {
            const chips = [];
            if (efMeta.channel && String(efMeta.channel).indexOf('ics') !== -1) {
                chips.push('<span class="ingestion-chip ingestion-chip-channel" title="Parsed from a calendar invite">📅 Invite</span>');
            }
            if (efMeta.recurrence && efMeta.recurrence.rrule) {
                const needsEnd = efMeta.recurrence.needs_end;
                chips.push(`<span class="ingestion-chip ingestion-chip-recurring" title="${this.escapeHtml(efMeta.recurrence.rrule)}">↻ Recurring${needsEnd ? ' — needs end date' : ''}</span>`);
            }
            if (efMeta.duplicate_of) {
                chips.push(`<span class="ingestion-chip ingestion-chip-duplicate" title="Possible duplicate of: ${this.escapeHtml(efMeta.duplicate_of.title || '')}">⚠ Possible duplicate</span>`);
            }
            if (typeof efMeta.confidence === 'number') {
                const pct = Math.round(efMeta.confidence * 100);
                chips.push(`<span class="ingestion-chip" title="Extraction confidence">${pct}%</span>`);
            }
            ingestionChips = chips.join(' ');
        }

        // Build meta line (received · from-who · date · time) — tertiary.
        // Received time and sender lead; the event's own date/time trails.
        const metaParts = [];
        if (event.created) {
            const d = new Date(event.created);
            const received = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            metaParts.push(`<span class="inbox-card-received-inline">Received ${received}</span>`);
        }
        if (approvalContext) {
            metaParts.push(`<span class="inbox-row-context">${approvalContext}</span>`);
        }
        metaParts.push(dateTimeDisplay);
        if (ingestionChips) {
            metaParts.push(ingestionChips);
        }
        const metaLine = metaParts.join(' · ');

        // Determine row class — the left accent carries state.
        let cardClass = 'inbox-card';

        // Add status class for color coding on ALL rows
        if (event.status) {
            cardClass += ` status-${event.status.toLowerCase().replace(/\s+/g, '-')}`;
        }

        if (isResolved) {
            // Grey accent + muted look via .resolved.
            cardClass += ' resolved approval-card';
        } else if (isHumanReview) {
            // Gold left accent — the deliberate "needs human review" signifier.
            cardClass += ' human-review-card';
        } else {
            // Status-colored left accent for routing/approval rows.
            cardClass += ' approval-card';
        }

        // Action verb leads the row as bold primary text. Resolved rows use past
        // tense; the right-aligned badge carries the specific outcome.
        let verb;
        if (event.is_dismissed) {
            verb = 'Dismissed extracted event';
        } else if (isResolved) {
            verb = (isHumanReview && !needsApproval) ? 'Reviewed extracted event' : 'Reviewed routed event';
        } else if (isHumanReview) {
            verb = 'Review extracted event';
        } else {
            verb = 'Approve routed event';
        }

        // Single right-aligned status badge per row.
        let badgeHtml = '';
        if (event.is_dismissed) {
            badgeHtml = `<span class="detail-panel-status" style="color:#6b7280;background:rgba(156,163,175,0.1);">Dismissed</span>`;
        } else if (isResolved) {
            if (isHumanReview && !needsApproval) {
                if (reviewDecision === 'rejected' || reviewDecision === 'not_event') {
                    badgeHtml = `<span class="detail-panel-status" style="color:#6b7280;background:rgba(156,163,175,0.1);">Event Rejected</span>`;
                } else {
                    badgeHtml = `<span class="detail-panel-status" style="color:#6b7280;background:rgba(156,163,175,0.1);">Review Resolved</span>`;
                }
            } else {
                let badgeText = 'Review Resolved';
                let badgeClass = 'inbox-resolved-badge';
                let badgeIcon = `<path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>`;
                if (userApprovalStatus === 'approved') {
                    badgeText = 'Accepted';
                    badgeClass = 'inbox-resolved-badge inbox-accepted-badge';
                } else if (userApprovalStatus === 'sent_back') {
                    badgeText = 'Sent Back';
                    badgeClass = 'inbox-resolved-badge inbox-sent-back-badge';
                    badgeIcon = `<polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>`;
                } else if (userApprovalStatus === 'cancelled') {
                    badgeText = 'Stopped Review';
                    badgeClass = 'inbox-resolved-badge inbox-cancelled-badge';
                    badgeIcon = `<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>`;
                }
                badgeHtml = `
                    <div class="${badgeClass}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${badgeIcon}</svg>
                        ${badgeText}
                    </div>
                `;
            }
        } else if (isHumanReview) {
            badgeHtml = `<span class="detail-panel-status status-extraction">Needs Human Review</span>`;
        } else {
            badgeHtml = `
                <div class="inbox-requires-review-badge">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M9 11l3 3L22 4"></path>
                        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
                    </svg>
                    Requires Your Approval
                </div>
            `;
        }

        // Subject: event name (secondary) + organization (lighter tertiary),
        // following the verb on the same headline.
        const eventTitle = this.escapeHtml(event.title || event.group || 'Untitled Event');
        const orgSuffix = orgName ? `<span class="inbox-row-org"> · ${this.escapeHtml(orgName)}</span>` : '';

        // Flat, action-led row: verb + subject on the headline, meta beneath,
        // one badge right-aligned. The card shape lives on the Events page only.
        return `
            <div class="${cardClass}" data-event-id="${event.id || event.event_id}">
                <div class="inbox-row-content">
                    <div class="inbox-row-headline">
                        <span class="inbox-row-verb">${verb}</span>
                        <span class="inbox-row-subject">${eventTitle}${orgSuffix}</span>
                    </div>
                    <div class="inbox-row-meta">${metaLine}</div>
                </div>
                <div class="inbox-row-badge">${badgeHtml}</div>
            </div>
        `;
    }

    renderChangeRequestCard(event) {
        const group = event._changeGroup || {};
        const isCancellation = group.intent === 'CANCELLATION';
        const intentLabel = isCancellation ? 'Cancellation' : 'Reschedule';
        const eventTitle = this.escapeHtml(event.title || 'Untitled Event');

        // Field-level diff rows: old → proposed, with the verbatim source
        // string as a tooltip on date/time rows.
        const verbatim = group.verbatim || {};
        const fieldLabels = {
            start_date: 'Date', start_time: 'Time', end_date: 'End date',
            end_time: 'End time', location: 'Location', status: 'Status'
        };
        const diffRows = (group.suggestions || []).map(s => {
            const label = fieldLabels[s.field_name] || s.field_name;
            const isDateField = s.field_name.indexOf('date') !== -1;
            const isTimeField = s.field_name.indexOf('time') !== -1;
            const source = isDateField ? verbatim.date_text
                         : isTimeField ? verbatim.time_text : '';
            const titleAttr = source ? ` title="From email: ${this.escapeHtml(source)}"` : '';
            return `<span class="cr-diff-row"${titleAttr}>` +
                   `<span class="cr-diff-field">${this.escapeHtml(label)}:</span> ` +
                   `<span class="cr-diff-old">${this.escapeHtml(s.current_value || '—')}</span>` +
                   `<span class="cr-diff-arrow">→</span>` +
                   `<span class="cr-diff-new">${this.escapeHtml(s.suggested_value)}</span>` +
                   `</span>`;
        }).join(' ');

        const received = event.created
            ? new Date(event.created).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : '';

        return `
            <div class="inbox-card change-request-card" data-event-id="${event.id}"
                 data-candidate-id="${group.candidate_id || ''}">
                <div class="inbox-row-content">
                    <div class="inbox-row-headline">
                        <span class="inbox-row-verb">${isCancellation ? 'Cancellation requested' : 'Reschedule requested'}</span>
                        <span class="inbox-row-subject">${eventTitle}</span>
                    </div>
                    <div class="inbox-row-meta">
                        ${received ? `<span class="inbox-card-received-inline">Received ${received}</span> · ` : ''}
                        ${diffRows || this.escapeHtml(group.reason || '')}
                    </div>
                </div>
                <div class="inbox-row-badge">
                    <span class="detail-panel-status status-change-request">${intentLabel}</span>
                </div>
            </div>
        `;
    }

    /**
     * "Needs a decision" card: an email the pipeline deliberately did not act
     * on (failed sender authentication, digest, unknown-event cancellation,
     * burst). Same row structure as the change-request card; red accent.
     * There is no one-click approve: the panel offers Extract anyway / Divert.
     */
    renderDecisionCard(event) {
        const item = event._triage || {};
        const subject = this.escapeHtml(item.subject || '(no subject)');
        const sender = this.escapeHtml(item.sender_name || item.sender || '');
        const received = event.created
            ? new Date(event.created).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : '';
        const metaParts = [];
        if (received) metaParts.push(`<span class="inbox-card-received-inline">Received ${received}</span>`);
        if (sender) metaParts.push(`From ${sender}`);
        metaParts.push(this.escapeHtml(item.reason_label || 'Needs a decision'));

        return `
            <div class="inbox-card decision-card" data-event-id="${event.id}">
                <div class="inbox-row-content">
                    <div class="inbox-row-headline">
                        <span class="inbox-row-verb">Needs a decision</span>
                        <span class="inbox-row-subject">${subject}</span>
                    </div>
                    <div class="inbox-row-meta">${metaParts.join(' · ')}</div>
                </div>
                <div class="inbox-row-badge">
                    <span class="detail-panel-status status-needs-decision">Needs Decision</span>
                </div>
            </div>
        `;
    }

    /**
     * Diverted row: an email the ingestion funnel filtered out before AI
     * reading. Same row structure as the other inbox cards; neutral pill.
     */
    renderDivertedCard(event) {
        const item = event._diverted || {};
        const subject = this.escapeHtml(item.subject || '(no subject)');
        const sender = this.escapeHtml(item.sender_name || item.sender || '');
        const received = event.created
            ? new Date(event.created).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : '';
        const metaParts = [];
        if (received) metaParts.push(`<span class="inbox-card-received-inline">Received ${received}</span>`);
        if (sender) metaParts.push(`From ${sender}`);

        return `
            <div class="inbox-card divert-card" data-event-id="${event.id}">
                <div class="inbox-row-content">
                    <div class="inbox-row-headline">
                        <span class="inbox-row-verb">Diverted</span>
                        <span class="inbox-row-subject">${subject}</span>
                    </div>
                    <div class="inbox-row-meta">${metaParts.join(' · ')}</div>
                </div>
                <div class="inbox-row-badge">
                    <span class="detail-panel-status status-diverted">${this.escapeHtml(item.reason_label || 'Diverted')}</span>
                </div>
            </div>
        `;
    }

    getStatusLabel(status) {
        const statusMap = {
            'received': 'Received',
            'hold': 'Hold',
            'referred': 'Referred',
            'fyied': "FYI'd",
            'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled',
            'rsvped': "RSVP'd",
            'regrets_sent': 'Regrets Sent',
            'passed': 'Passed',
            'canceled': 'Canceled',
            'requires_hms_review': 'Needs Review'
        };
        return statusMap[status] || status || '';
    }

    renderEmptyState() {
        const message = this.state.view === 'diverted'
            ? (this.state.search ? 'No diverted email matches this search' : 'No diverted email')
            : 'No items to review';
        return `
            <div class="inbox-empty-message">
                ${message}
            </div>
        `;
    }

    // =========================================================================
    // Event Handling
    // =========================================================================

    bindEventClicks() {
        // Decision rows: "Decide" opens the detail panel (there is no event to
        // edit yet, so the editing modal is never involved).
        this.elements.eventList.querySelectorAll('.decision-review-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const card = btn.closest('.inbox-card');
                if (card && card.dataset.eventId) {
                    this.openDetailPanel(card.dataset.eventId, { focusAction: true });
                }
            });
        });

        const eventCards = this.elements.eventList.querySelectorAll('.inbox-card');
        eventCards.forEach(card => {
            // Single click with disambiguation timer
            card.addEventListener('click', (e) => {
                const eventId = card.dataset.eventId;
                if (!eventId) return;

                // If timer is pending for a different card, cancel and start fresh
                if (this._clickTimer && this._clickEventId !== eventId) {
                    clearTimeout(this._clickTimer);
                    this._clickTimer = null;
                    this._clickEventId = null;
                }

                // If timer already pending for this card → second click (dblclick)
                if (this._clickTimer && this._clickEventId === eventId) {
                    clearTimeout(this._clickTimer);
                    this._clickTimer = null;
                    this._clickEventId = null;
                    this.handleEventDoubleClick(eventId);
                    return;
                }

                // First click: start timer
                this._clickEventId = eventId;
                this._clickTimer = setTimeout(() => {
                    this._clickTimer = null;
                    this._clickEventId = null;
                    this.handleEventSingleClick(eventId);
                }, this._CLICK_DELAY);
            });

            // Safety net: native dblclick event
            card.addEventListener('dblclick', (e) => {
                const eventId = card.dataset.eventId;
                if (!eventId) return;

                if (this._clickTimer) {
                    clearTimeout(this._clickTimer);
                    this._clickTimer = null;
                    this._clickEventId = null;
                }
                this.handleEventDoubleClick(eventId);
            });
        });

        // Re-apply detail-active highlight after re-render
        if (this.state.detailPanelOpen && this.state.detailPanelEventId) {
            this.updateActiveCard(this.state.detailPanelEventId);
        }
    }

    handleEventSingleClick(eventId) {
        // A click focuses the first action (so Enter opens it) but *silently* —
        // no visible focus ring until the user presses Tab or an arrow.
        if (this.state.detailPanelOpen && this.state.detailPanelEventId == eventId) {
            this.focusFirstPanelAction({ silent: true });
            return;
        }
        this.openDetailPanel(eventId, { focusAction: true, silentFocus: true });
    }

    handleEventDoubleClick(eventId) {
        if (String(eventId).startsWith('cr:')) {
            const row = this.state.events.find(e => String(e.id) === String(eventId));
            if (row && typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(row._targetEventId);
            }
            return;
        }
        if (String(eventId).startsWith('triage:') || String(eventId).startsWith('diverted:')) {
            this.openDetailPanel(eventId, { focusAction: true });
            return;
        }
        // Open full editing modal
        console.log('Opening event modal for review:', eventId);
        if (typeof window.openEventEditingModal === 'function') {
            window.openEventEditingModal(eventId);
        } else {
            window.location.href = `${this.config.eventEditingUrl}${eventId}/`;
        }
    }

    // =========================================================================
    // Detail Panel Methods
    // =========================================================================

    async openDetailPanel(eventId, options = {}) {
        const panel = this.elements.detailPanel;
        const content = this.elements.detailPanelContent;
        if (!panel || !content) return;

        // Update state
        this.state.detailPanelEventId = eventId;
        this.state.detailPanelOpen = true;

        // Mark panel as having an event selected (for responsive styles)
        panel.classList.add('has-event');

        // Highlight the card
        this.updateActiveCard(eventId);

        // Show skeleton placeholder while the event loads
        content.innerHTML = this.renderDetailPanelSkeleton();

        // On narrow screens, auto-close filter sidebar
        if (window.innerWidth < 1280 && this.state.sidebarOpen) {
            this.closeSidebar();
        }

        // Look up event in local state to get _inboxType and approval metadata
        const localEvent = this.state.events.find(e => String(e.id || e.event_id) === String(eventId));

        // Diverted emails aren't events either: render from the feed.
        if (localEvent && localEvent._inboxType === 'diverted') {
            this.state.detailPanelEventData = localEvent;
            this.renderDivertedPanel(localEvent);
            if (options.focusAction) this.focusFirstPanelAction({ silent: options.silentFocus });
            return;
        }

        // Emails awaiting a decision aren't events: render from the feed.
        if (localEvent && localEvent._inboxType === 'decision') {
            this.state.detailPanelEventData = localEvent;
            this.renderDecisionPanel(localEvent);
            if (options.focusAction) this.focusFirstPanelAction({ silent: options.silentFocus });
            return;
        }

        // Fetch full event data from API
        try {
            const fetchId = (localEvent && localEvent._targetEventId) || eventId;
            const response = await fetch(`${this.config.apiUrl}${fetchId}/`, {
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                }
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const eventData = await response.json();
            // Derive the client-side dismissed flag from the authoritative
            // server decision so the footer renders Dismiss vs Restore correctly.
            eventData.is_dismissed = eventData.review_decision === 'dismissed';

            // Guard: if user clicked another event during fetch, abort render
            if (this.state.detailPanelEventId != eventId) return;

            // Merge inbox metadata from local state
            if (localEvent) {
                eventData._inboxType = localEvent._inboxType;
                eventData._approvalData = localEvent._approvalData;
                eventData.needs_approval = localEvent.needs_approval;
                eventData.is_resolved = localEvent.is_resolved;
                eventData.sent_by_name = localEvent.sent_by_name;
                eventData.previous_approver_name = localEvent.previous_approver_name;
                eventData.next_approver_name = localEvent.next_approver_name;
                eventData.is_final_approver = localEvent.is_final_approver;
                eventData.stage_order = localEvent.stage_order;
                eventData.is_re_review = localEvent.is_re_review;
                eventData.sent_back_by_name = localEvent.sent_back_by_name;
                eventData.user_approval_status = localEvent.user_approval_status;
                eventData._changeGroup = localEvent._changeGroup;
            }

            // For approval-routing events, fetch the full routing chain so the
            // detail panel can render the same table as the editing modal.
            const inboxType = eventData._inboxType || 'human_review';
            if (inboxType === 'needs_approval' || inboxType === 'both' || eventData.needs_approval) {
                try {
                    const rResp = await fetch(`/api/events/${eventData.id}/approval-routing/`, {
                        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                        credentials: 'same-origin'
                    });
                    if (rResp.ok) eventData._approvalRouting = await rResp.json();
                } catch (e) { /* non-fatal — fall back to the simple flow */ }
                // Re-check the user hasn't switched events during the fetch.
                if (this.state.detailPanelEventId != eventId) return;
            }

            this.state.detailPanelEventData = eventData;
            // Track in recently viewed (shared across pages via sessionStorage)
            this._addToRecentlyViewed(eventData);
            this.renderDetailPanel(eventData);

            // Selection asked for focus on the first action — silently for a
            // click (no ring), with the ring for keyboard navigation.
            if (options.focusAction && this.state.detailPanelEventId == eventId) {
                this.focusFirstPanelAction({ silent: options.silentFocus });
            }
        } catch (error) {
            // A 404 means the event was deleted (moved to Deleted Events) — close
            // the stale panel quietly instead of showing an error.
            if (String(error.message).includes('404')) {
                if (this.state.detailPanelEventId == eventId) {
                    this.closeDetailPanel();
                }
                return;
            }
            console.error('Error fetching event for detail panel:', error);
            if (this.state.detailPanelEventId == eventId) {
                content.innerHTML = `
                    <div class="detail-panel-header">
                        <div class="detail-panel-header-left">
                            <div class="detail-panel-title">Error</div>
                        </div>
                        <button class="detail-panel-close" id="detail-panel-close-btn" aria-label="Close">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="detail-panel-body" style="display:flex;align-items:center;justify-content:center;color:var(--text-secondary);">
                        Failed to load event details.
                    </div>`;
                document.getElementById('detail-panel-close-btn')?.addEventListener('click', () => this.closeDetailPanel());
            }
        }
    }

    /**
     * Build the approval-routing table HTML — mirrors the editing modal's
     * renderApprovalRouting() (columns: #, Reviewer, Status, Comment). Returns
     * '' when there's no routing data so callers can fall back to a simple flow.
     * Read-only here: the inbox panel's footer Review button opens the modal.
     */
    _buildRoutingTableHtml(data) {
        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        const stages = data?.stages || data?.routing?.stages || [];
        if (!data || !data.has_routing || stages.length === 0) return '';

        const currentStage = data.current_stage;
        let rows = '';

        stages.forEach((stage) => {
            const isActive = currentStage === stage.stage_id;
            const approvers = stage.approvers || [];
            approvers.forEach((approver, approverIndex) => {
                const approverStatus = approver.status || 'pending';
                const isCurrentTurn = isActive && approverStatus === 'pending';

                let rowClass = 'v2-rt-row';
                if (approverStatus === 'approved') rowClass += ' v2-rt-approved';
                else if (approverStatus === 'sent_back') rowClass += ' v2-rt-sent-back';
                else if (isCurrentTurn) rowClass += ' v2-rt-current';

                const isFirstStage = stage.order === 0;
                let statusHtml = '';
                if (approverStatus === 'approved') {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-approved"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>${isFirstStage ? 'Started' : 'Approved'}</span>`;
                } else if (approverStatus === 'sent_back') {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-sent-back"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path></svg>Sent Back</span>`;
                } else if (isCurrentTurn) {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-current"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>Awaiting</span>`;
                } else {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-pending"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle></svg>Pending</span>`;
                }

                const stageNum = approverIndex === 0 ? stage.order : '';
                const stageNumClass = approverIndex === 0 ? 'v2-rt-stage-num' : 'v2-rt-stage-num v2-rt-stage-continuation';

                let commentHtml = '';
                if (approver.comment) {
                    const c = escapeHtml(approver.comment);
                    commentHtml = `<span class="v2-rt-comment-text" title="${c}">${c}</span>`;
                }

                rows += `<tr class="${rowClass}"><td class="${stageNumClass}">${stageNum}</td><td class="v2-rt-reviewer">${escapeHtml(approver.name)}</td><td class="v2-rt-status-cell">${statusHtml}</td><td class="v2-rt-comment">${commentHtml}</td></tr>`;
            });
        });

        if (!rows) return '';

        return `<table class="v2-routing-table">
            <thead><tr>
                <th class="v2-rt-col-num">#</th>
                <th class="v2-rt-col-reviewer">Reviewer</th>
                <th class="v2-rt-col-status">Status</th>
                <th class="v2-rt-col-comment">Comment</th>
            </tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    }

    renderDetailPanel(eventData) {
        const content = this.elements.detailPanelContent;
        if (!content) return;

        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        const formatDate = (dateStr) => {
            if (!dateStr) return '';
            try {
                const d = new Date(dateStr + 'T00:00:00');
                const now = new Date();
                const opts = d.getFullYear() !== now.getFullYear()
                    ? { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }
                    : { weekday: 'short', month: 'short', day: 'numeric' };
                return d.toLocaleDateString('en-US', opts);
            } catch (e) { return dateStr; }
        };

        const formatTime = (timeStr) => {
            if (!timeStr) return '';
            try {
                const [h, m] = timeStr.split(':');
                const d = new Date();
                d.setHours(parseInt(h), parseInt(m));
                return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
            } catch (e) { return timeStr; }
        };

        // Relative time
        const getRelativeTime = () => {
            if (!eventData.start_date) return '';
            try {
                const now = new Date();
                const eventDate = new Date(eventData.start_date + 'T00:00:00');
                if (eventData.start_time) {
                    const [h, m] = eventData.start_time.split(':');
                    eventDate.setHours(parseInt(h), parseInt(m), 0, 0);
                }
                const diffMs = eventDate.getTime() - now.getTime();
                const diffDays = Math.round(diffMs / 86400000);
                const isToday = eventDate.toDateString() === now.toDateString();
                const isTomorrow = new Date(now.getTime() + 86400000).toDateString() === eventDate.toDateString();
                const timeStr = eventData.start_time ? formatTime(eventData.start_time) : '';

                if (isToday) {
                    if (diffMs > 0) {
                        const hrsLeft = Math.floor(diffMs / 3600000);
                        const minsLeft = Math.round((diffMs % 3600000) / 60000);
                        const remaining = hrsLeft > 0 ? `starts in ${hrsLeft}h ${minsLeft}m` : `starts in ${minsLeft}m`;
                        return timeStr ? `Today at ${timeStr} — ${remaining}` : `Today — ${remaining}`;
                    }
                    return timeStr ? `Today at ${timeStr}` : 'Today';
                }
                if (isTomorrow) return timeStr ? `Tomorrow at ${timeStr}` : 'Tomorrow';
                if (diffDays > 0 && diffDays <= 14) return `In ${diffDays} day${diffDays === 1 ? '' : 's'}`;
                if (diffDays > 14) { const w = Math.round(diffDays / 7); return `In ${w} week${w === 1 ? '' : 's'}`; }
                if (diffDays < 0) { const a = Math.abs(diffDays); return `${a} day${a === 1 ? '' : 's'} ago`; }
                return '';
            } catch (e) { return ''; }
        };

        // --- Header ---
        const statusLabel = this.getStatusLabel(eventData.status);
        const statusClass = eventData.status ? `detail-panel-status status-${eventData.status.toLowerCase().replace(/\s+/g, '-')}` : 'detail-panel-status';

        // --- Routing section ---
        const inboxType = eventData._inboxType || 'human_review';
        const isHumanReview = inboxType === 'human_review' || inboxType === 'both';
        const needsApproval = inboxType === 'needs_approval' || inboxType === 'both';
        const isReviewEvent = isHumanReview || needsApproval;

        let routingHtml = '';

        // Full routing chain table (same as the editing modal), shown as a
        // "Review" section in the body for approval-routing events.
        const routingTableHtml = needsApproval ? this._buildRoutingTableHtml(eventData._approvalRouting) : '';

        // Top bar: compact sender → YOU → next flow with pills and arrows.
        // Always shown for routing events, above the detail body.
        if (needsApproval) {
            const senderName = eventData.sent_by_name || eventData.previous_approver_name ||
                              (eventData._approvalData && eventData._approvalData.sent_by_name) ||
                              (eventData._approvalData && eventData._approvalData.previous_approver_name) || '';
            const nextApproverName = eventData.next_approver_name ||
                                    (eventData._approvalData && eventData._approvalData.next_approver_name) || '';
            const isFinalApprover = eventData.is_final_approver !== undefined ? eventData.is_final_approver :
                                   (eventData._approvalData && eventData._approvalData.is_final_approver) || false;

            let flowNodes = '';
            if (senderName) {
                flowNodes += `<span class="routing-node">${escapeHtml(senderName)}</span>`;
                flowNodes += '<span class="routing-arrow">&rarr;</span>';
            }
            flowNodes += `<span class="routing-node routing-you">YOU${isFinalApprover ? ' (Final)' : ''}</span>`;
            if (nextApproverName && !isFinalApprover) {
                flowNodes += '<span class="routing-arrow">&rarr;</span>';
                flowNodes += `<span class="routing-node">${escapeHtml(nextApproverName)}</span>`;
            } else {
                // YOU is the last stop — terminal vertical line (sits where the
                // arrow would be if there were a next approver).
                flowNodes += '<span class="routing-end"></span>';
            }

            routingHtml += `
                <div class="inbox-detail-routing">
                    <div class="routing-flow">${flowNodes}</div>
                </div>
            `;
        }

        // --- Body: date/time, location, description, etc. ---
        const hasDateTime = eventData.start_date || eventData.start_time;
        let dateTimeDisplay = '';
        if (eventData.start_date) {
            dateTimeDisplay = formatDate(eventData.start_date);
            if (eventData.end_date && eventData.end_date !== eventData.start_date) {
                dateTimeDisplay += ' — ' + formatDate(eventData.end_date);
            }
        }
        if (eventData.start_time) {
            dateTimeDisplay += (dateTimeDisplay ? ', ' : '') + formatTime(eventData.start_time);
            if (eventData.end_time) {
                dateTimeDisplay += ' – ' + formatTime(eventData.end_time);
            }
        }
        const relativeTime = getRelativeTime();

        const locationText = eventData.location || '';
        const hasLocation = !!locationText;
        const typeLabel = this.getTypeLabel(eventData.type);
        const formatLabel = eventData.format || '';
        // Type/format ("· Meeting · in-person") is omitted on review panels
        // (both human-review extractions and approval-routing events).
        const typeFormatParts = isReviewEvent ? [] : [typeLabel, formatLabel].filter(Boolean);

        // Secondary sections
        let secondaryHtml = '';

        // Description belongs to the normal sidebar (approval-routing and other
        // events). Human-review events get the source-email preview instead, so
        // description is omitted there.
        if (!isHumanReview && eventData.description) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Description</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.description)}</span>
            </div>`;
        }

        if (eventData.tags && eventData.tags.length > 0) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Tags</span>
                <div class="v2-readonly-tags">
                    ${eventData.tags.map(t => `<span class="v2-readonly-tag">${escapeHtml(t)}</span>`).join('')}
                </div>
            </div>`;
        }

        // Contact details come from the normalized Contact model, surfaced by
        // the API as point_of_contact_* (legacy poc_* kept as a fallback).
        const pocName = eventData.poc_name || eventData.point_of_contact_name;
        const pocEmail = eventData.poc_email || eventData.point_of_contact_email;
        const pocPhone = eventData.poc_phone || eventData.point_of_contact_phone;
        if (pocName || pocEmail || pocPhone) {
            const pocParts = [pocName, pocEmail, pocPhone].filter(Boolean);
            secondaryHtml += `<div class="v2-readonly-section inline-section">
                <span class="v2-readonly-label">Contact:</span>
                <span class="v2-readonly-value">${escapeHtml(pocParts.join(' · '))}</span>
            </div>`;
        }

        if (eventData.participants && eventData.participants.length > 0) {
            const participantNames = eventData.participants.map(p => typeof p === 'string' ? p : (p.name || p.title || '')).filter(Boolean);
            if (participantNames.length <= 3) {
                secondaryHtml += `<div class="v2-readonly-section inline-section">
                    <span class="v2-readonly-label">Participants:</span>
                    <span class="v2-readonly-value">${escapeHtml(participantNames.join(', '))}</span>
                </div>`;
            } else {
                secondaryHtml += `<div class="v2-readonly-section">
                    <span class="v2-readonly-label">Participants</span>
                    <div class="v2-readonly-participants">
                        ${participantNames.map(n => `<div class="v2-readonly-participant">${escapeHtml(n)}</div>`).join('')}
                    </div>
                </div>`;
            }
        }

        if (eventData.staff && eventData.staff.length > 0) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Assigned staff</span>
                <div class="v2-readonly-staff-list">
                    ${eventData.staff.map(s => `<span class="v2-readonly-staff-pill">${escapeHtml(s)}</span>`).join('')}
                </div>
            </div>`;
        }

        if (eventData.notes) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Notes</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.notes)}</span>
            </div>`;
        }

        // Approval routing chain — full table (matches the editing modal).
        if (routingTableHtml) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Review</span>
                ${routingTableHtml}
            </div>`;
        }

        // Source email section.
        // complete_email_data is a standardized dict: sender lives under
        // `from: {name, email, display_name}`, the timestamp under
        // `received`/`date_received`, and the body is an object
        // `{text, html, preview}` — NOT flat `sender`/`received_date`/`body`
        // strings. Pull the right fields so the body doesn't stringify to
        // "[object Object]".
        // The source-email preview is exclusive to human-review (AI-extracted)
        // events. Approval-routing events use the normal sidebar instead.
        let sourceEmailHtml = '';
        if (isHumanReview && eventData.attached_emails_data && eventData.attached_emails_data.length > 0) {
            const email = eventData.attached_emails_data[0];

            const from = email.from || {};
            const senderText = from.display_name || from.email || from.name || email.sender || '';

            const rawDate = email.received || email.date_received || email.date_sent || email.received_date || '';
            let dateText = '';
            if (rawDate) {
                try {
                    const d = new Date(rawDate);
                    dateText = isNaN(d) ? String(rawDate) : d.toLocaleString('en-US', {
                        weekday: 'short', month: 'short', day: 'numeric',
                        hour: 'numeric', minute: '2-digit', hour12: true,
                    });
                } catch (e) { dateText = String(rawDate); }
            }

            let bodyText = '';
            if (email.body && typeof email.body === 'object') {
                bodyText = email.body.text || email.body.preview || '';
            } else if (typeof email.body === 'string') {
                bodyText = email.body;
            }
            if (!bodyText) bodyText = email.body_preview || '';

            // Sender + received date share one line, separated by a dot.
            const metaParts = [];
            if (senderText) metaParts.push(`From: ${escapeHtml(senderText)}`);
            if (dateText) metaParts.push(escapeHtml(dateText));
            const metaHtml = metaParts.length
                ? `<div class="source-email-meta">${metaParts.join(' &middot; ')}</div>` : '';

            sourceEmailHtml = `<div class="v2-readonly-section source-email-section">
                <span class="v2-readonly-label">Source email</span>
                <div class="source-email-content">
                    ${email.subject || metaHtml ? `<div class="source-email-header">
                        ${email.subject ? `<div class="source-email-subject">${escapeHtml(email.subject)}</div>` : ''}
                        ${metaHtml}
                    </div>` : ''}
                    ${bodyText ? `<div class="source-email-body">${this._highlightExtractionSources(bodyText, eventData)}</div>` : ''}
                </div>
            </div>`;
        }

        // Missing-fields dropdown removed per design — the editing modal
        // surfaces empty fields when the user actually starts reviewing.
        const missingHtml = '';

        // --- Footer ---
        let footerHtml = '';
        const isChangeRequest = inboxType === 'change_request';
        if (isChangeRequest) {
            // Requested changes listed above the footer; one primary action.
            const group = eventData._changeGroup || {};
            const fieldLabels = {
                start_date: 'Date', start_time: 'Time', end_date: 'End date',
                end_time: 'End time', location: 'Location', status: 'Status'
            };
            const rows = (group.suggestions || []).map(sg =>
                `<span class="v2-readonly-value">${escapeHtml(fieldLabels[sg.field_name] || sg.field_name)}: ` +
                `${escapeHtml(sg.current_value || '—')} → <strong>${escapeHtml(sg.suggested_value)}</strong></span>`
            ).join('');
            sourceEmailHtml = `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Requested changes</span>
                ${rows || `<span class="v2-readonly-value multiline">${escapeHtml(group.reason || '')}</span>`}
            </div>` + sourceEmailHtml;
            footerHtml = `<button class="detail-panel-btn detail-panel-btn-review" id="detail-panel-btn-review">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
                <span class="btn-label">Review changes</span>
            </button>`;
        } else if (isReviewEvent) {
            if (isHumanReview && eventData.is_dismissed) {
                // Dismissed (false-positive) items show only a single white,
                // bold "Restore" button — nothing to review until it's restored.
                footerHtml = `<button class="detail-panel-btn detail-panel-btn-ghost detail-panel-btn-bold" id="detail-panel-btn-dismiss" data-dismissed="true">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="1 4 1 10 7 10"></polyline>
                        <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                    </svg>
                    <span class="btn-label">Restore</span>
                </button>`;
            } else {
                // Human-review or approval events → single full-width "Review" button.
                // Human-review (extraction) events get the same warning-orange used
                // by the Jump to Next button so the call-to-action is consistent.
                const reviewVariant = (isHumanReview && !eventData.is_resolved) ? ' detail-panel-btn-review--extraction' : '';
                footerHtml = `<button class="detail-panel-btn detail-panel-btn-review${reviewVariant}" id="detail-panel-btn-review">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                    <span class="btn-label">Review</span>
                </button>`;
                // Human-review events get a second "Dismiss" button that marks the
                // item as a false positive and removes it from the review queue.
                if (isHumanReview) {
                    footerHtml += `<button class="detail-panel-btn detail-panel-btn-ghost detail-panel-btn-bold" id="detail-panel-btn-dismiss" data-dismissed="false">
                        <span class="btn-label">Dismiss</span>
                    </button>`;
                }
            }
        } else {
            // Normal events → Calendar, Edit, Copy (fallback)
            if (eventData.start_date) {
                footerHtml += `<button class="detail-panel-btn detail-panel-btn-primary" id="detail-panel-btn-calendar">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                    <span class="btn-label">Calendar</span>
                </button>`;
            }
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-edit" id="detail-panel-btn-edit">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                <span class="btn-label">Edit</span>
            </button>`;
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-ghost icon-only" id="detail-panel-btn-copy" title="Copy details">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
            </button>`;
        }

        // --- Assemble ---
        const orgText = eventData.organization || eventData.group || '';
        const aiExtractedBadge = isHumanReview && !eventData.is_resolved ? `<span class="detail-panel-status status-extraction">AI Extracted</span>` : '';
        // Review panels lead with a prompt heading and show the event title
        // beneath it. Human-review (extraction) vs approval-routing differ.
        const reviewHeading = isChangeRequest
                                ? ((eventData._changeGroup || {}).intent === 'CANCELLATION'
                                    ? 'Cancellation requested' : 'Reschedule requested')
                            : isHumanReview ? 'Extracted event requires human review'
                            : needsApproval ? 'Routed event requires your approval'
                            : '';
        // The whole panel body scrolls (everything below the header/routing
        // line); the source-email preview sits at its natural height rather than
        // shrinking into its own scroll box.
        const bodyFillClass = '';

        content.innerHTML = `
            <div class="detail-panel-header">
                <div class="detail-panel-header-left">
                    ${reviewHeading ? `
                        <div class="detail-panel-title">${reviewHeading}</div>
                        <div class="detail-panel-subtitle">
                            <span class="detail-panel-subtitle-title">${escapeHtml(eventData.title) || 'Untitled Event'}</span>${orgText ? ` &middot; <span class="detail-panel-subtitle-org">${escapeHtml(orgText)}</span>` : ''}
                        </div>
                    ` : `
                        <div class="detail-panel-title">${escapeHtml(eventData.title) || 'Untitled Event'}</div>
                        <div class="detail-panel-org-status">
                            ${orgText ? `<span class="detail-panel-org">${escapeHtml(orgText)}</span>` : ''}
                            ${aiExtractedBadge}
                        </div>
                    `}
                </div>
                <button class="detail-panel-close" id="detail-panel-close-btn" aria-label="Close">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            ${routingHtml}
            <div class="detail-panel-body${bodyFillClass}">
                <div class="v2-readonly-primary">
                    ${hasDateTime ? `<div class="v2-readonly-datetime">${dateTimeDisplay}${relativeTime ? ` <span class="v2-readonly-relative-time-inline">&middot; ${relativeTime}</span>` : ''}</div>` : (relativeTime ? `<div class="v2-readonly-datetime"><span class="v2-readonly-relative-time-inline">${relativeTime}</span></div>` : '')}
                    ${hasLocation ? `<div class="v2-readonly-location">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                            <circle cx="12" cy="10" r="3"></circle>
                        </svg>
                        ${escapeHtml(locationText)}${typeFormatParts.length > 0 ? ` <span class="v2-readonly-type-format-inline">&middot; ${typeFormatParts.join(' &middot; ')}</span>` : ''}
                    </div>` : (typeFormatParts.length > 0 ? `<div class="v2-readonly-type-format">${typeFormatParts.join(' &middot; ')}</div>` : '')}
                </div>
                <div class="v2-readonly-secondary">
                    ${secondaryHtml}
                    ${sourceEmailHtml}
                </div>
                ${missingHtml}
            </div>
            <div class="detail-panel-footer">
                ${footerHtml}
            </div>
        `;

        this.bindDetailPanelEvents(eventData);
    }

    /**
     * Collect the phrases that the AI used as extraction sources for this
     * event, ordered longest-first so longer matches win over substrings.
     *
     * Sources, in priority order:
     *   1. `text_snippet` recorded per field in `extracted_fields` — the exact
     *      slice of the email the extractor matched (most accurate).
     *   2. The extracted field values themselves (title, org, location, POC,
     *      participants, topics…) for events where snippets weren't stored.
     *
     * Normalized values that don't appear verbatim in the email (e.g. an ISO
     * date) simply won't match and are skipped — no false highlight.
     */
    _collectExtractionPhrases(eventData) {
        const phrases = [];
        const push = (v) => {
            if (v == null) return;
            const s = String(v).trim();
            if (s.length >= 3) phrases.push(s);
        };

        // 1. Per-field source snippets / values recorded at extraction time.
        const ef = eventData.extracted_fields;
        if (ef && typeof ef === 'object') {
            for (const key of Object.keys(ef)) {
                const f = ef[key];
                if (f && typeof f === 'object') {
                    push(f.text_snippet || f.value);
                } else {
                    push(f);
                }
            }
        }

        // 2. The event's own extracted values (covers events without snippets).
        push(eventData.title);
        push(eventData.group || eventData.organization);
        push(eventData.location);
        push(eventData.location_room);
        push(eventData.location_building);
        push(eventData.description);
        push(eventData.poc_name || eventData.point_of_contact_name);
        push(eventData.poc_email || eventData.point_of_contact_email);
        push(eventData.poc_phone || eventData.point_of_contact_phone);
        (eventData.participants || []).forEach(p =>
            push(typeof p === 'string' ? p : (p && (p.name || p.title))));
        (eventData.legislative_topics || eventData.tags || []).forEach(push);

        // De-dupe (case-insensitive), then longest-first.
        const seen = new Set();
        return phrases
            .filter(s => {
                const k = s.toLowerCase();
                if (seen.has(k)) return false;
                seen.add(k);
                return true;
            })
            .sort((a, b) => b.length - a.length);
    }

    /**
     * Escape `bodyText` and wrap every occurrence of an extraction-source
     * phrase in a <mark> so reviewers can see exactly which parts of the email
     * the AI drew from. Match ranges are merged so overlapping phrases don't
     * produce nested marks.
     */
    _highlightExtractionSources(bodyText, eventData) {
        const escapeHtml = (str) => String(str ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

        if (!bodyText) return '';
        const phrases = this._collectExtractionPhrases(eventData);
        if (!phrases.length) return escapeHtml(bodyText);

        // Find all (case-insensitive) match ranges across the body. Needles
        // that start/end on an alphanumeric must land on a word boundary so a
        // short value like "event" doesn't highlight inside "prevent".
        const lower = bodyText.toLowerCase();
        const isWord = (c) => c !== undefined && /[a-z0-9]/i.test(c);
        const ranges = [];
        for (const phrase of phrases) {
            const needle = phrase.toLowerCase();
            if (needle.length < 3) continue;
            const guardStart = isWord(needle[0]);
            const guardEnd = isWord(needle[needle.length - 1]);
            let from = 0, idx;
            while ((idx = lower.indexOf(needle, from)) !== -1) {
                const end = idx + needle.length;
                const okStart = !guardStart || !isWord(lower[idx - 1]);
                const okEnd = !guardEnd || !isWord(lower[end]);
                if (okStart && okEnd) ranges.push([idx, end]);
                from = end;
            }
        }
        if (!ranges.length) return escapeHtml(bodyText);

        // Sort and merge overlapping/adjacent ranges into flat spans.
        ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
        const merged = [];
        for (const [s, e] of ranges) {
            const last = merged[merged.length - 1];
            if (last && s <= last[1]) last[1] = Math.max(last[1], e);
            else merged.push([s, e]);
        }

        // Rebuild the body, escaping each segment and marking matched spans.
        let out = '', cursor = 0;
        for (const [s, e] of merged) {
            out += escapeHtml(bodyText.slice(cursor, s));
            out += `<mark class="extraction-source">${escapeHtml(bodyText.slice(s, e))}</mark>`;
            cursor = e;
        }
        out += escapeHtml(bodyText.slice(cursor));
        return out;
    }


    bindDetailPanelEvents(eventData) {
        // Close button
        document.getElementById('detail-panel-close-btn')?.addEventListener('click', () => this.closeDetailPanel());

        // Missing fields toggle
        document.getElementById('detail-panel-missing-toggle')?.addEventListener('click', () => {
            const list = document.getElementById('detail-panel-missing-list');
            const toggle = document.getElementById('detail-panel-missing-toggle');
            if (list && toggle) {
                const expanded = toggle.getAttribute('aria-expanded') === 'true';
                toggle.setAttribute('aria-expanded', !expanded);
                list.classList.toggle('visible');
                list.setAttribute('aria-hidden', expanded);
                toggle.querySelector('.v2-readonly-missing-chevron')?.classList.toggle('rotated');
            }
        });

        // Review button → opens editing modal
        document.getElementById('detail-panel-btn-review')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id);
            }
        });

        // Dismiss / Restore button → marks the event as a false positive, or
        // restores a dismissed event back to the active review queue.
        document.getElementById('detail-panel-btn-dismiss')?.addEventListener('click', (e) => {
            const btn = e.currentTarget;
            const isDismissed = btn.dataset.dismissed === 'true';
            this.dismissEvent(eventData.id, isDismissed ? 'undo_dismiss' : 'dismiss', btn);
        });

        // Calendar button
        document.getElementById('detail-panel-btn-calendar')?.addEventListener('click', () => {
            if (eventData.start_date) {
                window.location.href = `/calendar/?date=${eventData.start_date}&event=${eventData.id}`;
            }
        });

        // Edit button
        document.getElementById('detail-panel-btn-edit')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id);
            }
        });

        // Copy Details
        document.getElementById('detail-panel-btn-copy')?.addEventListener('click', async () => {
            const parts = [eventData.title || 'Untitled Event'];
            if (eventData.start_date) {
                const d = new Date(eventData.start_date + 'T00:00:00');
                parts.push(d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }));
                if (eventData.start_time) {
                    const [h, m] = eventData.start_time.split(':');
                    const t = new Date(); t.setHours(parseInt(h), parseInt(m));
                    parts.push(t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }));
                }
            }
            if (eventData.location) parts.push(eventData.location);
            try {
                await navigator.clipboard.writeText(parts.join('\n'));
                const btn = document.getElementById('detail-panel-btn-copy');
                if (btn) {
                    const originalHTML = btn.innerHTML;
                    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
                    setTimeout(() => { btn.innerHTML = originalHTML; }, 1500);
                }
            } catch (e) {
                console.error('Copy failed:', e);
            }
        });
    }

    /**
     * Detail panel for a "Needs a decision" email. Uses the same header,
     * read-only sections, source-email block and footer buttons as the
     * extraction review panel. Body text is shown escaped, never as HTML.
     */
    renderDecisionPanel(event) {
        const content = this.elements.detailPanelContent;
        if (!content) return;
        const item = event._triage || {};
        const esc = (str) => this.escapeHtml(str || '');

        let dateText = '';
        if (item.received_at) {
            try {
                dateText = new Date(item.received_at).toLocaleString('en-US', {
                    weekday: 'short', month: 'short', day: 'numeric',
                    hour: 'numeric', minute: '2-digit', hour12: true,
                });
            } catch (e) { dateText = ''; }
        }
        const senderText = item.sender_name ? `${item.sender_name} <${item.sender}>` : (item.sender || '');
        const metaParts = [];
        if (senderText) metaParts.push(`From: ${esc(senderText)}`);
        if (dateText) metaParts.push(esc(dateText));

        content.innerHTML = `
            <div class="detail-panel-header">
                <div class="detail-panel-header-left">
                    <div class="detail-panel-title">Email needs a decision</div>
                    <div class="detail-panel-subtitle">
                        <span class="detail-panel-subtitle-title">${esc(item.subject) || '(no subject)'}</span>
                    </div>
                </div>
                <button class="detail-panel-close" id="detail-panel-close-btn" aria-label="Close">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            <div class="detail-panel-body">
                <div class="v2-readonly-primary">
                    <div class="v2-readonly-datetime">${esc(item.reason_label) || 'Needs a decision'}</div>
                </div>
                <div class="v2-readonly-secondary">
                    <div class="v2-readonly-section">
                        <span class="v2-readonly-label">Why it was set aside</span>
                        <span class="v2-readonly-value multiline">${esc(item.explanation)}</span>
                        <span class="v2-readonly-value multiline">Extract anyway reads it as a scheduling request. Divert moves it to the Diverted tab, where it stays searchable.</span>
                    </div>
                    ${item.detail && item.detail.trim().toLowerCase() !== (item.subject || '').trim().toLowerCase() ? `<div class="v2-readonly-section">
                        <span class="v2-readonly-label">Mentioned</span>
                        <span class="v2-readonly-value multiline">${esc(item.detail)}</span>
                    </div>` : ''}
                    <div class="v2-readonly-section source-email-section">
                        <span class="v2-readonly-label">Source email</span>
                        <div class="source-email-content">
                            <div class="source-email-header">
                                <div class="source-email-subject">${esc(item.subject) || '(no subject)'}</div>
                                ${metaParts.length ? `<div class="source-email-meta">${metaParts.join(' &middot; ')}</div>` : ''}
                            </div>
                            ${item.body_text ? `<div class="source-email-body">${esc(item.body_text)}</div>` : ''}
                        </div>
                    </div>
                </div>
            </div>
            <div class="detail-panel-footer">
                <button class="detail-panel-btn detail-panel-btn-review" id="detail-panel-btn-extract">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                    <span class="btn-label">Extract anyway</span>
                </button>
                <button class="detail-panel-btn detail-panel-btn-ghost detail-panel-btn-bold" id="detail-panel-btn-divert">
                    <span class="btn-label">Divert</span>
                </button>
            </div>
        `;

        document.getElementById('detail-panel-close-btn')?.addEventListener('click', () => this.closeDetailPanel());
        document.getElementById('detail-panel-btn-extract')?.addEventListener('click', (e) => {
            this.resolveDecision(event, 'extract', e.currentTarget);
        });
        document.getElementById('detail-panel-btn-divert')?.addEventListener('click', (e) => {
            this.resolveDecision(event, 'divert', e.currentTarget);
        });
    }

    /**
     * Act on a "Needs a decision" email: 'extract' runs it through extraction
     * (it then shows up as a normal review card); 'divert' sets it aside in the
     * divert store, where it stays searchable.
     */
    async resolveDecision(event, action, btnEl) {
        const item = event._triage || {};
        if (btnEl) btnEl.disabled = true;
        try {
            const response = await fetch(`${this.config.triageActionUrl}${item.id}/${action}/`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                }
            });
            if (!response.ok) {
                this.showError(action === 'extract'
                    ? 'Could not send the email for extraction.'
                    : 'Could not divert the email.');
                return;
            }
            this.state.events = this.state.events.filter(e => String(e.id) !== String(event.id));
            this.closeDetailPanel();
            if (typeof window.updateInboxBadge === 'function') window.updateInboxBadge();
            // Extraction can create a new review card; refresh all feeds.
            this.fetchEvents();
        } catch (err) {
            console.error('Error resolving decision item:', err);
            this.showError('Something went wrong. Please try again.');
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    /**
     * Detail panel for a diverted email: why the funnel filtered it out, the
     * source email (escaped, never HTML) and one action, Promote to extraction.
     */
    renderDivertedPanel(event) {
        const content = this.elements.detailPanelContent;
        if (!content) return;
        const item = event._diverted || {};
        const esc = (str) => this.escapeHtml(str || '');

        let dateText = '';
        if (item.received_at) {
            try {
                dateText = new Date(item.received_at).toLocaleString('en-US', {
                    weekday: 'short', month: 'short', day: 'numeric',
                    hour: 'numeric', minute: '2-digit', hour12: true,
                });
            } catch (e) { dateText = ''; }
        }
        const senderText = item.sender_name ? `${item.sender_name} <${item.sender}>` : (item.sender || '');
        const metaParts = [];
        if (senderText) metaParts.push(`From: ${esc(senderText)}`);
        if (dateText) metaParts.push(esc(dateText));

        content.innerHTML = `
            <div class="detail-panel-header">
                <div class="detail-panel-header-left">
                    <div class="detail-panel-title">Diverted email</div>
                    <div class="detail-panel-subtitle">
                        <span class="detail-panel-subtitle-title">${esc(item.subject) || '(no subject)'}</span>
                    </div>
                </div>
                <button class="detail-panel-close" id="detail-panel-close-btn" aria-label="Close">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            <div class="detail-panel-body">
                <div class="v2-readonly-primary">
                    <div class="v2-readonly-datetime">${esc(item.reason_label) || 'Diverted'}</div>
                </div>
                <div class="v2-readonly-secondary">
                    <div class="v2-readonly-section">
                        <span class="v2-readonly-label">Why it was diverted</span>
                        <span class="v2-readonly-value multiline">${esc(item.explanation)}</span>
                        <span class="v2-readonly-value multiline">If this is a real scheduling request, promote it: HillDesk reads it and adds a draft to the inbox for review.</span>
                    </div>
                    <div class="v2-readonly-section source-email-section">
                        <span class="v2-readonly-label">Source email</span>
                        <div class="source-email-content">
                            <div class="source-email-header">
                                <div class="source-email-subject">${esc(item.subject) || '(no subject)'}</div>
                                ${metaParts.length ? `<div class="source-email-meta">${metaParts.join(' &middot; ')}</div>` : ''}
                            </div>
                            ${item.body_text ? `<div class="source-email-body">${esc(item.body_text)}</div>` : ''}
                        </div>
                    </div>
                </div>
            </div>
            <div class="detail-panel-footer">
                <button class="detail-panel-btn detail-panel-btn-review" id="detail-panel-btn-promote">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                    <span class="btn-label">Promote to extraction</span>
                </button>
            </div>
        `;

        document.getElementById('detail-panel-close-btn')?.addEventListener('click', () => this.closeDetailPanel());
        document.getElementById('detail-panel-btn-promote')?.addEventListener('click', (e) => {
            this.promoteDiverted(event, e.currentTarget);
        });
    }

    async promoteDiverted(event, btnEl) {
        const item = event._diverted || {};
        if (btnEl) btnEl.disabled = true;
        try {
            const response = await fetch(`${this.config.divertedActionUrl}${item.id}/promote/`, {
                method: 'POST',
                headers: { 'Accept': 'application/json', 'X-CSRFToken': this.config.csrfToken }
            });
            if (!response.ok) {
                this.showError('Could not send the email for extraction.');
                return;
            }
            this.state.events = this.state.events.filter(e => String(e.id) !== String(event.id));
            this.closeDetailPanel();
            this.renderEventList();
            if (typeof window.updateInboxBadge === 'function') window.updateInboxBadge();
        } catch (err) {
            console.error('Error promoting diverted email:', err);
            this.showError('Something went wrong. Please try again.');
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    /**
     * Add an event to the cross-page recently viewed list in sessionStorage
     */
    _addToRecentlyViewed(eventData) {
        try {
            let recent = JSON.parse(sessionStorage.getItem('hilldesk_recently_viewed') || '[]');
            recent = recent.filter(e => e.id != eventData.id);
            let shortDate = '';
            if (eventData.start_date) {
                try {
                    const dateStr = eventData.start_date;
                    const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
                    shortDate = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                } catch (_) {}
            }
            recent.unshift({
                id: eventData.id,
                title: eventData.title || 'Untitled Event',
                group: eventData.group || '',
                date: shortDate
            });
            if (recent.length > 10) recent = recent.slice(0, 10);
            sessionStorage.setItem('hilldesk_recently_viewed', JSON.stringify(recent));
        } catch (_) {}
    }

    renderEmptyDetailPanel() {
        const content = this.elements.detailPanelContent;
        if (!content) return;

        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        content.innerHTML = `
            <div class="detail-panel-empty">
                <svg class="detail-panel-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline>
                    <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>
                </svg>
                <div class="detail-panel-empty-title">${this.state.view === 'diverted' ? 'Select an email' : 'Select an item'}</div>
                <p class="detail-panel-empty-subtitle">${this.state.view === 'diverted'
                    ? 'Click a diverted email to see why it was filtered out'
                    : 'Click an inbox item to view its details here'}</p>
            </div>`;
    }

    closeDetailPanel() {
        this.state.detailPanelOpen = false;
        this.state.detailPanelEventId = null;
        this.state.detailPanelEventData = null;

        // Mark panel as empty (for responsive styles)
        this.elements.detailPanel?.classList.remove('has-event');

        // Remove active highlight from all cards
        this.elements.eventList?.querySelectorAll('.inbox-card.detail-active').forEach(card => {
            card.classList.remove('detail-active');
        });

        // Show empty state instead of hiding
        this.renderEmptyDetailPanel();
    }

    /**
     * Dismiss an event as a false positive, or restore a dismissed one.
     * @param {string} eventId
     * @param {'dismiss'|'undo_dismiss'} action
     * @param {HTMLElement} [btnEl] the button to disable during the request
     */
    async dismissEvent(eventId, action, btnEl) {
        if (btnEl) btnEl.disabled = true;
        try {
            const response = await fetch(`${this.config.apiUrl}${eventId}/dismiss/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                },
                body: JSON.stringify({ action })
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                this.showError(data.message || data.error || 'Failed to update item.');
                return;
            }

            const data = await response.json();
            const dismissed = data.review_decision === 'dismissed';

            // Update local state so the list reflects the change without a refetch.
            const localEvent = this.state.events.find(
                e => String(e.id || e.event_id) === String(eventId)
            );
            if (localEvent) {
                localEvent.is_dismissed = dismissed;
                localEvent.review_decision = data.review_decision || '';
                localEvent.requires_human_review = !dismissed;
                localEvent.is_resolved = dismissed;
            }

            // Keep a just-dismissed row visible until reload so it can be undone
            // without enabling "Show resolved"; drop it from the sticky set on undo.
            if (dismissed) {
                this.state.recentlyResolvedIds.add(String(eventId));
            } else {
                this.state.recentlyResolvedIds.delete(String(eventId));
            }

            // Re-open the panel and focus its first footer action so a single
            // Enter targets it, not "open event": after dismiss → Restore;
            // after restore → Review.
            this.openDetailPanel(eventId, { focusAction: true });
            this.renderEventList();
        } catch (err) {
            console.error('Error updating dismissal for event:', err);
            this.showError('Failed to update item. Please try again.');
        } finally {
            if (btnEl) btnEl.disabled = false;
        }
    }

    updateActiveCard(eventId) {
        // Remove highlight from all cards
        this.elements.eventList?.querySelectorAll('.inbox-card.detail-active').forEach(card => {
            card.classList.remove('detail-active');
        });
        // Add highlight to the selected card
        const card = this.elements.eventList?.querySelector(`.inbox-card[data-event-id="${eventId}"]`);
        if (card) {
            card.classList.add('detail-active');
        }
    }

    // =========================================================================
    // UI Helpers
    // =========================================================================

    showLoading(append = false) {
        if (append) return;
        if (this.elements.eventList) {
            this.elements.eventList.innerHTML = this.renderSkeletonList();
        }
    }

    hideLoading() {
        // No-op: renderEventList / showError will overwrite the skeleton markup.
    }

    renderSkeletonList() {
        const card = `
            <div class="skeleton-inbox-card" aria-hidden="true">
                <div class="skeleton-card-left">
                    <div class="skeleton skeleton-line-title"></div>
                    <div class="skeleton skeleton-line-meta"></div>
                </div>
                <div class="skeleton skeleton-badge"></div>
            </div>
        `;
        const dateHeader = `
            <div class="skeleton-inbox-date-header" aria-hidden="true">
                <div class="skeleton skeleton-date-label"></div>
                <div class="skeleton skeleton-day-label"></div>
            </div>
        `;
        // Runs of rows separated by date-divider placeholders, mirroring the
        // real list (Today / Yesterday / older dates) so the layout fills the
        // area and doesn't shift when real content swaps in.
        const groups = [4, 4, 4];
        const sections = groups.map(n => dateHeader + card.repeat(n)).join('');
        return `<div class="skeleton-inbox-list" role="status" aria-label="Loading inbox">${sections}</div>`;
    }

    /**
     * Skeleton placeholder for the detail panel — mirrors the real layout
     * (header title + status, primary date/location lines, a couple of
     * readonly sections, and footer buttons) so the swap-in is seamless.
     */
    renderDetailPanelSkeleton() {
        return `
            <div class="detail-panel-skeleton" role="status" aria-label="Loading details" aria-hidden="true">
                <div class="detail-panel-header">
                    <div class="detail-panel-header-left">
                        <div class="skeleton skeleton-dp-title"></div>
                        <div class="skeleton skeleton-dp-status"></div>
                    </div>
                    <div class="skeleton skeleton-dp-close"></div>
                </div>
                <div class="detail-panel-body">
                    <div class="skeleton-dp-primary">
                        <div class="skeleton skeleton-dp-line lg"></div>
                        <div class="skeleton skeleton-dp-line sm"></div>
                    </div>
                    <div class="skeleton-dp-section">
                        <div class="skeleton skeleton-dp-label"></div>
                        <div class="skeleton skeleton-dp-line"></div>
                        <div class="skeleton skeleton-dp-line short"></div>
                    </div>
                    <div class="skeleton-dp-section">
                        <div class="skeleton skeleton-dp-label"></div>
                        <div class="skeleton-dp-pills">
                            <div class="skeleton skeleton-dp-pill"></div>
                            <div class="skeleton skeleton-dp-pill"></div>
                            <div class="skeleton skeleton-dp-pill"></div>
                        </div>
                    </div>
                    <div class="skeleton-dp-section">
                        <div class="skeleton skeleton-dp-label"></div>
                        <div class="skeleton skeleton-dp-line"></div>
                    </div>
                </div>
                <div class="detail-panel-footer">
                    <div class="skeleton skeleton-dp-btn"></div>
                    <div class="skeleton skeleton-dp-btn"></div>
                </div>
            </div>
        `;
    }

    showLoadMore() {
        if (this.elements.loadMore) {
            this.elements.loadMore.style.display = 'flex';
        }
    }

    hideLoadMore() {
        if (this.elements.loadMore) {
            this.elements.loadMore.style.display = 'none';
        }
    }

    showError(message) {
        if (this.elements.eventList) {
            this.elements.eventList.innerHTML = `
                <div class="inbox-empty-state">
                    <div class="icon">&#9888;</div>
                    <div class="message">${message}</div>
                    <div class="hint">Please refresh the page or try again later</div>
                </div>
            `;
        }
    }

    // =========================================================================
    // Utility Methods
    // =========================================================================

    hasActiveFilters() {
        // The Source filter is active whenever it's narrowed from its default
        // (both Extracted + Staff Review shown) — this is what the dashboard /
        // Ctrl-K "Extractions" and "Routed to you" deep-links toggle.
        const sourceNarrowed = !(this.state.showExtractedEvents && this.state.showStaffReview);
        return sourceNarrowed ||
               this.state.filters.status.length > 0 ||
               this.state.filters.type.length > 0 ||
               this.state.filters.format.length > 0;
    }

    updateFiltersButtonState() {
        const active = this.hasActiveFilters();
        // Glow both the header filter button and the inline one when any
        // status/type/format filter is active.
        [this.elements.filtersToggleBtn, this.elements.filtersToggleBtnInline].forEach((btn) => {
            if (btn) {
                btn.classList.toggle('has-filters', active);
            }
        });
    }

    getTypeLabel(type) {
        const typeMap = {
            'event': 'Event',
            'meeting': 'Meeting',
            'speaking_engagement': 'Speaking',
            'ceremony': 'Ceremony',
            'tour': 'Tour',
            'phone_call': 'Phone Call',
            'other': 'Other'
        };
        return typeMap[type] || type || '';
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    handleKeyboardShortcuts(event) {
        // While typing in a field, leave the keyboard to the input — except in
        // the search box, where Up/Down/Enter should still drive the inbox list
        // (the list navigates without stealing focus, so typing can continue).
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
            const inSearch = event.target === this.elements.searchInput;
            const isNavKey = event.key === 'ArrowDown' || event.key === 'ArrowUp' ||
                event.key === 'Enter';
            if (!inSearch || !isNavKey) {
                return;
            }
        }

        // Ignore shortcuts while the event editing modal (or its skeleton) is
        // open — the modal owns the keyboard then. Still swallow the arrow keys
        // so they don't scroll the page content behind the modal.
        if (document.body.classList.contains('modal-open') ||
            document.querySelector('.v2-modal-overlay.active')) {
            if (event.key.startsWith('Arrow')) {
                event.preventDefault();
            }
            return;
        }

        if (event.shiftKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight') &&
            event.target !== this.elements.searchInput) {
            event.preventDefault();
            this.switchView(event.key === 'ArrowRight' ? 'diverted' : 'inbox');
            return;
        }

        switch (event.key) {
            case 'f':
                event.preventDefault();
                if (this.elements.searchInput) {
                    this.elements.searchInput.focus();
                }
                break;
            case 'ArrowDown':
                // Up/Down move between inbox rows. When driven from the search
                // box, keep focus there so the user can keep typing.
                event.preventDefault();
                this.navigateItems(1, event.target === this.elements.searchInput);
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.navigateItems(-1, event.target === this.elements.searchInput);
                break;
            case 'ArrowRight':
                // Left/Right cycle the panel's controls, like Tab / Shift+Tab.
                if (this.cyclePanelFocus(1)) event.preventDefault();
                break;
            case 'ArrowLeft':
                if (this.cyclePanelFocus(-1)) event.preventDefault();
                break;
            case 'Tab':
                // Inside the panel, Tab cycles its controls; with nothing
                // selected it selects the first row in the queue.
                this.handlePanelTab(event);
                break;
            case 'Enter': {
                // Enter reviews/opens the selected event. If a focusable panel
                // control is focused (e.g. tabbed to Dismiss or X, or the Review
                // button), let it handle Enter natively; otherwise this is the
                // default action — so it works even before the Review button has
                // loaded/focused.
                if (!this.state.detailPanelOpen || this.state.detailPanelEventId == null) break;
                const ae = document.activeElement;
                const panel = this.elements.detailPanel;
                const onControl = ae && panel && panel.contains(ae) && ae !== panel &&
                    (ae.tagName === 'BUTTON' || ae.tabIndex >= 0);
                if (!onControl) {
                    event.preventDefault();
                    this.handleEventDoubleClick(this.state.detailPanelEventId);
                }
                break;
            }
            case 'Escape':
                // Close detail panel first, then sidebar
                if (this.state.detailPanelOpen) {
                    this.closeDetailPanel();
                } else if (this.state.sidebarOpen) {
                    this.closeSidebar();
                }
                break;
        }
    }

    /**
     * Move the selection up (direction = -1) or down (direction = +1) through
     * the visible inbox rows, opening the detail panel for the new row. With
     * nothing selected yet, Down picks the first row and Up the last.
     */
    navigateItems(direction, keepFocus = false) {
        const cards = Array.from(
            this.elements.eventList?.querySelectorAll('.inbox-card[data-event-id]') || []
        );
        if (cards.length === 0) return;

        // Locate the currently selected row.
        let currentIndex = cards.findIndex(c => c.classList.contains('detail-active'));
        if (currentIndex === -1 && this.state.detailPanelEventId != null) {
            currentIndex = cards.findIndex(
                c => String(c.dataset.eventId) === String(this.state.detailPanelEventId)
            );
        }

        let nextIndex;
        if (currentIndex === -1) {
            if (this.state.navAnchorIndex != null) {
                // The selected row was just removed (resolved/deleted). Resume
                // from its old slot: Down lands on the row that shifted into it
                // (the "next"), Up on the one before it.
                const a = this.state.navAnchorIndex;
                nextIndex = direction > 0 ? Math.min(a, cards.length - 1) : Math.max(a - 1, 0);
            } else {
                // Nothing selected yet (e.g. fresh page load): both Up and Down
                // select the top row.
                nextIndex = 0;
            }
        } else {
            nextIndex = currentIndex + direction;
            if (nextIndex < 0 || nextIndex >= cards.length) return; // at an edge
        }
        this.state.navAnchorIndex = null; // consumed / normal navigation

        const nextId = cards[nextIndex].dataset.eventId;
        if (!nextId) return;
        // Keyboard row navigation: focus the first action (the Review button) and
        // show its accent ring, so the user can see where focus landed. (A mouse
        // click focuses silently — no ring — via handleEventSingleClick.)
        // When navigating from the search box, keep focus in the input instead
        // so the user can keep typing while the selection moves.
        this.openDetailPanel(nextId, keepFocus ? {} : { focusAction: true });
        if (nextIndex === 0 && this.elements.viewContainer) {
            // At the top row, scroll fully up so the date header ("Today") and
            // the heading padding above it show — not just the card itself.
            this.elements.viewContainer.scrollTo({ top: 0 });
        } else {
            cards[nextIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    /**
     * The detail panel's focusable controls, in Tab order: the footer action
     * buttons (Review / Dismiss, or Calendar / Edit / Copy) followed by the
     * close (X). The collapse button is excluded.
     */
    getPanelTabOrder() {
        if (!this.state.detailPanelOpen || !this.state.detailPanelEventId) return [];
        const panel = this.elements.detailPanel;
        if (!panel) return [];
        const footerBtns = Array.from(panel.querySelectorAll('.detail-panel-footer .detail-panel-btn'));
        const closeBtn = panel.querySelector('#detail-panel-close-btn');
        const order = footerBtns.slice();
        if (closeBtn) order.push(closeBtn);
        return order.filter(el => el && !el.disabled &&
            (el.offsetWidth > 0 || el.offsetHeight > 0));
    }

    /**
     * Give exactly one panel control the visible keyboard focus ring
     * (.focus-ring) and focus it; the ring clears when it loses focus.
     */
    _focusPanelControl(el) {
        if (!el) return;
        this.getPanelTabOrder().forEach(c => c.classList.remove('focus-ring'));
        el.classList.add('focus-ring');
        el.addEventListener('blur', () => el.classList.remove('focus-ring'), { once: true });
        el.focus();
    }

    /**
     * Focus the first panel control. Keyboard selection shows the ring; a silent
     * (click) focus omits it — focused so Enter activates it, but no ring until
     * the user presses Tab or an arrow.
     */
    focusFirstPanelAction(opts = {}) {
        // The panel content (incl. the footer Review button) can need a frame to
        // lay out after the API resolves, so the first control may not be present
        // on the first try — retry across a few frames until it is.
        const apply = (tries) => {
            // If the editing modal opened (e.g. a fast Enter launched it while
            // this panel was still loading), stop — never steal focus back to a
            // control sitting behind the modal.
            if (document.body.classList.contains('modal-open') ||
                document.querySelector('.v2-modal-overlay.active')) return;
            const el = this.getPanelTabOrder()[0];
            if (el) {
                if (opts.silent) {
                    this.getPanelTabOrder().forEach(c => c.classList.remove('focus-ring'));
                    el.focus();
                } else {
                    this._focusPanelControl(el);
                }
                if (document.activeElement === el) return; // focus stuck
            }
            if (tries > 0) requestAnimationFrame(() => apply(tries - 1));
        };
        apply(60); // poll up to ~1s in case the panel content is still loading
    }

    /**
     * Move focus to the next (1) / previous (-1) panel control, wrapping. The
     * first press moves directly off the silently-focused control (no "reveal
     * the ring in place" stop). Returns false when empty.
     */
    cyclePanelFocus(direction) {
        const order = this.getPanelTabOrder();
        if (order.length === 0) return false;
        const active = document.activeElement;
        const idx = order.indexOf(active);
        let nextIdx;
        if (idx === -1) {
            nextIdx = direction > 0 ? 0 : order.length - 1;
        } else {
            nextIdx = (idx + direction + order.length) % order.length;
        }
        this._focusPanelControl(order[nextIdx]);
        return true;
    }

    handlePanelTab(event) {
        // With nothing selected (e.g. just after X / Escape), Tab jumps into the
        // queue and selects the first row (Shift+Tab the last).
        if (!this.state.detailPanelOpen || !this.state.detailPanelEventId) {
            event.preventDefault();
            this.navigateItems(event.shiftKey ? -1 : 1);
            return;
        }
        const panel = this.elements.detailPanel;
        if (!panel || !panel.contains(document.activeElement)) return;
        if (this.cyclePanelFocus(event.shiftKey ? -1 : 1)) {
            event.preventDefault();
        }
    }

    /**
     * Refresh the inbox list (called after the editing modal closes).
     * If the user just finished with the selected event — finished human
     * review or took their part of routing approval — it becomes resolved.
     * Rather than dropping it from view, we keep it in place (sticky) until the
     * page is reloaded so the user can revisit or undo it, and leave the panel
     * open. Only events that vanish from the payload detach the panel.
     */
    async refresh() {
        this.state.page = 1;
        const prevSelectedId = this.state.detailPanelEventId;
        const panelWasOpen = this.state.detailPanelOpen;
        // Capture the selected row's slot before re-render so that, if it's gone,
        // the next Up/Down/Tab can resume from the adjacent row.
        const cards = Array.from(this.elements.eventList?.querySelectorAll('.inbox-card[data-event-id]') || []);
        const prevIndex = prevSelectedId != null
            ? cards.findIndex(c => String(c.dataset.eventId) === String(prevSelectedId))
            : -1;

        await this.fetchEvents();

        if (!prevSelectedId || !panelWasOpen) return;

        const updated = this.state.events.find(
            e => String(e.id) === String(prevSelectedId)
        );

        // If the user just resolved the selected event, keep it visible until
        // reload so it can be revisited/undone, then re-render now that it's
        // sticky (fetchEvents already rendered once, before this was marked).
        if (updated && updated.is_resolved) {
            this.state.recentlyResolvedIds.add(String(prevSelectedId));
            this.renderEventList();
        }

        // Only a fully vanished event (gone from the payload) detaches the panel.
        if (!updated) {
            this.state.navAnchorIndex = prevIndex >= 0 ? prevIndex : null;
            this.closeDetailPanel();
        } else {
            this.state.navAnchorIndex = null;
            this.openDetailPanel(prevSelectedId);
        }
    }
}

// Export for global access
window.InboxRedesign = InboxRedesign;
