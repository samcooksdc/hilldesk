/* SPDX-License-Identifier: Apache-2.0 */
/**
 * ScheduleRedesign - Schedule Tab JavaScript Controller
 * HillDesk Congressional Scheduling Application
 *
 * Provides functionality for:
 * - Filter sidebar with collapsible sections
 * - Search with debouncing
 * - Multiple sort options
 * - Event card rendering with status colors
 * - Inline status change via dropdown
 * - Event editing modal integration
 */

class ScheduleRedesign {
    constructor(config = {}) {
        this.config = {
            apiUrl: config.apiUrl || '/api/events/',
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
                format: [],
                staff: [],
                source: [],
                myEvents: false,
                overlappingOnly: false,
                memberAttending: false
            },
            autoLoadFilters: false,
            search: '',
            // Active tab: 'all' (dated + undated, date-grouped) or 'undated'
            // (only events with no fixed date or a tentative date range).
            activeTab: 'all',
            // Remembers the selected event per tab so swapping back restores it.
            tabSelection: { all: null, undated: null },
            // Caches each tab's loaded events so swapping back is instant
            // (no skeleton/refetch) as long as the filter state is unchanged.
            tabCache: { all: null, undated: null },
            sortBy: 'start_date',
            // Undated tab has its own sort (date-based sorting doesn't apply).
            // Default 'created' (ascending) = oldest-waiting requests first.
            undatedSortBy: 'created',
            showPastEvents: false,
            pastRange: 'all', // 'all', '365days', 'year', '30days', 'month', 'week', '7days'
            page: 1,
            events: [],
            totalCount: 0,
            filteredCount: 0,
            hasMore: false,
            isLoading: false,
            sidebarOpen: false,
            // Detail panel state
            detailPanelEventId: null,
            detailPanelEventData: null,
            // View mode: 'list' or 'spreadsheet'
            viewMode: 'list',
            // Spreadsheet active-cell cursor {row, col} for Excel-style keyboard
            // navigation (null = no active cell). The side panel is never used in
            // spreadsheet mode.
            ssCursor: null,
            // Recently viewed events — loaded from sessionStorage
            recentlyViewed: this._loadRecentlyViewed()
        };

        // Status choices for dropdown
        this.statusChoices = [];

        this.elements = {};
        this.searchTimeout = null;
    }

    /**
     * Initialize the schedule component
     */
    init() {
        console.log('Initializing ScheduleRedesign...');
        this.cacheElements();
        this.bindEvents();
        this.loadFilterChoices();
        this._maybeAutoLoadFilters();
        // Show empty state in detail panel on load
        this.renderEmptyDetailPanel();
    }

    async _maybeAutoLoadFilters() {
        // Check URL params first (takes priority over saved presets)
        const params = new URLSearchParams(window.location.search);
        const filter = params.get('filter');
        if (filter === 'this_week') {
            this.openSidebar();
            this.fetchEvents();
            return;
        }
        if (filter === 'undated') {
            // Came in from the command palette "Undated events" shortcut —
            // open straight onto the Undated tab.
            this.state.activeTab = 'undated';
            this._updateTabUI();
            this.fetchEvents();
            return;
        }
        if (filter === 'my_events') {
            // Came in from the dashboard "Assigned to You" card.
            this.state.filters.myEvents = true;
            this.openSidebar();
            // renderFilters() may run before or after this (loadFilterChoices
            // is in flight); the checkbox reads state.filters.myEvents at
            // render time and _syncFilterCheckboxes covers the late case.
            this._syncFilterCheckboxes();
            this.updateFiltersButtonState();
            this.fetchEvents();
            return;
        }

        // Load the user's named presets; auto-apply the one flagged as default.
        try {
            this._ensurePresetManager();
            await this.presetManager.load();
            this._mountPresetDropdown();
            const def = this.presetManager.getDefault();
            if (def) {
                // _applyPresetData re-renders filters (and re-mounts the dropdown),
                // then fetches events itself.
                this._applyPresetData(def.data || {});
                this.presetManager.setActive(def.id);
                this.updateFiltersButtonState();
            } else {
                this.fetchEvents();
            }
        } catch (e) {
            console.error('Error loading filter presets:', e);
            this.fetchEvents();
        }
    }

    /** Lazily create the shared preset manager (without mounting its DOM). */
    _ensurePresetManager() {
        if (this.presetManager) return;
        this.presetManager = new FilterPresetManager({
            getCsrf: () => this.config.csrfToken,
            getCurrentData: () => this._getPresetData(),
            applyData: (data) => this._applyPresetData(data || {}),
            showToast: (msg) => this._showFilterToast(msg),
        });
    }

    /**
     * Cache DOM elements for performance
     */
    cacheElements() {
        this.elements = {
            // Sidebar
            sidebar: document.getElementById('schedule-filter-sidebar'),
            sidebarOverlay: document.getElementById('schedule-sidebar-overlay'),
            sidebarContent: document.getElementById('filter-sidebar-content'),
            sidebarCloseBtn: document.getElementById('sidebar-close-btn'),
            filtersToggleBtn: document.getElementById('filters-toggle-btn'),
            filtersToggleBtnInline: document.getElementById('filters-toggle-btn-inline'),
            clearAllFiltersBtn: document.getElementById('clear-all-filters-btn'),

            // Header
            searchInput: document.getElementById('schedule-search-input'),
            searchClear: document.getElementById('schedule-search-clear'),
            sortSelect: document.getElementById('schedule-sort-select'),
            undatedSortSelect: document.getElementById('schedule-undated-sort-select'),
            pastRangeSelect: document.getElementById('schedule-past-range-select'),
            headerSelects: document.querySelectorAll('.schedule-header-select'),
            tabs: document.getElementById('schedule-tabs'),

            // Event list
            viewContainer: document.getElementById('schedule-view-container'),
            eventList: document.getElementById('schedule-event-list'),
            loadMore: document.getElementById('schedule-load-more'),
            loadMoreBtn: document.getElementById('load-more-btn'),

            // Detail panel
            detailPanel: document.getElementById('schedule-detail-panel'),
            detailPanelContent: document.getElementById('detail-panel-content'),

            // View toggle
            viewToggle: document.getElementById('schedule-view-toggle'),
            listDetailWrapper: document.querySelector('.schedule-list-detail-wrapper')
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

        // Tabs (All Events / Undated)
        if (this.elements.tabs) {
            this.elements.tabs.querySelectorAll('.schedule-tab').forEach(btn => {
                btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
            });
        }

        // Custom header selects (sort + past range)
        this.bindHeaderSelects();

        // Clear all filters
        if (this.elements.clearAllFiltersBtn) {
            this.elements.clearAllFiltersBtn.addEventListener('click', () => this.clearAllFilters());
        }

        // Load more
        if (this.elements.loadMoreBtn) {
            this.elements.loadMoreBtn.addEventListener('click', () => this.loadMoreEvents());
        }

        // Infinite scroll — auto-load more when nearing the bottom. Capture phase
        // so it also catches scrolling on the inner spreadsheet wrapper, which
        // scrolls independently of the view container in spreadsheet mode.
        if (this.elements.viewContainer) {
            this.elements.viewContainer.addEventListener(
                'scroll',
                (e) => this.handleInfiniteScroll(e.target),
                true
            );
        }

        // View toggle (list / spreadsheet) — clicking either button always
        // swaps to the opposite view, so the toggle acts as a single switch
        // even when you click the already-active half.
        if (this.elements.viewToggle) {
            this.elements.viewToggle.querySelectorAll('.schedule-view-toggle-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const next = this.state.viewMode === 'spreadsheet' ? 'list' : 'spreadsheet';
                    this.handleViewToggle(next);
                });
            });
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyboardShortcuts(e));
    }

    // =========================================================================
    // Custom Header Selects (Sort, Past Range)
    // =========================================================================

    bindHeaderSelects() {
        this.elements.headerSelects.forEach(select => {
            const trigger = select.querySelector('.schedule-header-select-trigger');
            const options = select.querySelectorAll('.schedule-header-select-option');

            // Toggle open/close on trigger click
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                const wasOpen = select.classList.contains('open');
                // Close all other header selects first
                this.elements.headerSelects.forEach(s => s.classList.remove('open'));
                if (!wasOpen) select.classList.add('open');
            });

            // Option selection
            options.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const value = option.dataset.value;
                    this._setHeaderSelectValue(select, value);
                    select.classList.remove('open');

                    // Fire the correct handler
                    if (select.id === 'schedule-sort-select') {
                        this.handleSortChange({ target: { value } });
                    } else if (select.id === 'schedule-undated-sort-select') {
                        this.handleUndatedSortChange({ target: { value } });
                    } else if (select.id === 'schedule-past-range-select') {
                        this.handlePastRangeChange({ target: { value } });
                    }
                });
            });
        });

        // Close on outside click
        document.addEventListener('click', () => {
            this.elements.headerSelects.forEach(s => s.classList.remove('open'));
        });
    }

    _setHeaderSelectValue(selectEl, value) {
        selectEl.dataset.value = value;
        // Update displayed value text
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
    // Sidebar Methods
    // =========================================================================

    openSidebar() {
        if (this.elements.sidebar) {
            this.elements.sidebar.classList.remove('collapsed');
            this.elements.sidebar.classList.add('open');
            this.state.sidebarOpen = true;
        }
        // Only show overlay on mobile
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
            this.statusChoices = data.event_statuses || [];
            this.renderFilters();
        } catch (error) {
            console.error('Error loading filter choices:', error);
            // Use default choices from config
            this.statusChoices = this.config.filterChoices.event_statuses || [];
            this.renderFilters();
        }
    }

    /**
     * Normalize choice item to get value, label, and is_active
     * Handles both array format [value, label] and object format {value, label, is_active}
     */
    normalizeChoice(choice) {
        if (Array.isArray(choice)) {
            return { value: choice[0], label: choice[1], is_active: true };
        }
        return {
            value: choice.value,
            label: choice.label,
            is_active: choice.is_active !== false
        };
    }

    renderFilters() {
        if (!this.elements.sidebarContent) return;

        const { event_statuses = [], event_types = [], event_formats = [] } = this.config.filterChoices;

        // Normalize all choices to {value, label} format
        const statuses = event_statuses.map(c => this.normalizeChoice(c));
        const types = event_types.map(c => this.normalizeChoice(c));
        const formats = event_formats.map(c => this.normalizeChoice(c));

        // Build staff list from office choices (cached after first fetch)
        const staffNames = (this._staffList || []).map(s => s.name);

        const html = `
            <!-- Quick Filters -->
            <div class="filter-section" data-filter="quick">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('quick')">
                    <span>Quick Filters</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="filter-member-attending"
                                   ${this.state.filters.memberAttending ? 'checked' : ''}
                                   onchange="scheduleRedesign.handleToggleFilter('memberAttending', this.checked)">
                            <label for="filter-member-attending">Member Attending</label>
                        </div>
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="filter-my-events"
                                   ${this.state.filters.myEvents ? 'checked' : ''}
                                   onchange="scheduleRedesign.handleToggleFilter('myEvents', this.checked)">
                            <label for="filter-my-events">My Events</label>
                        </div>
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="filter-overlapping"
                                   ${this.state.filters.overlappingOnly ? 'checked' : ''}
                                   onchange="scheduleRedesign.handleToggleFilter('overlappingOnly', this.checked)">
                            <label for="filter-overlapping">Overlapping Events</label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Status Filter -->
            <div class="filter-section collapsed" data-filter="status">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('status')">
                    <span>Status</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="status-select-all" checked onchange="scheduleRedesign.handleSelectAll('status', this.checked)">
                            <label for="status-select-all">Select All</label>
                        </div>
                        ${statuses.map(({value, label}) => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="status-${value}" value="${value}" checked
                                       onchange="scheduleRedesign.handleFilterChange('status', '${value}', this.checked)">
                                <label for="status-${value}">${label}</label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Type Filter -->
            <div class="filter-section collapsed" data-filter="type">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('type')">
                    <span>Type</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="type-select-all" checked onchange="scheduleRedesign.handleSelectAll('type', this.checked)">
                            <label for="type-select-all">Select All</label>
                        </div>
                        ${types.map(({value, label}) => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="type-${value}" value="${value}" checked
                                       onchange="scheduleRedesign.handleFilterChange('type', '${value}', this.checked)">
                                <label for="type-${value}">${label}</label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Format Filter -->
            <div class="filter-section collapsed" data-filter="format">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('format')">
                    <span>Format</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="format-select-all" checked onchange="scheduleRedesign.handleSelectAll('format', this.checked)">
                            <label for="format-select-all">Select All</label>
                        </div>
                        ${formats.map(({value, label}) => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="format-${value}" value="${value}" checked
                                       onchange="scheduleRedesign.handleFilterChange('format', '${value}', this.checked)">
                                <label for="format-${value}">${label}</label>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>

            <!-- Staff Filter -->
            <div class="filter-section collapsed" data-filter="staff">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('staff')">
                    <span>Staff</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="staff-select-all" checked onchange="scheduleRedesign.handleSelectAll('staff', this.checked)">
                            <label for="staff-select-all">Select All</label>
                        </div>
                        ${staffNames.length > 0 ? staffNames.map(name => `
                            <div class="filter-checkbox-item">
                                <input type="checkbox" id="staff-${this.escapeHtml(name)}" value="${this.escapeHtml(name)}" checked
                                       onchange="scheduleRedesign.handleFilterChange('staff', '${this.escapeHtml(name).replace(/'/g, "\\'")}', this.checked)">
                                <label for="staff-${this.escapeHtml(name)}">${this.escapeHtml(name)}</label>
                            </div>
                        `).join('') : '<div class="filter-checkbox-item coming-soon">No staff configured</div>'}
                    </div>
                </div>
            </div>

            <!-- Source Filter -->
            <div class="filter-section collapsed" data-filter="source">
                <div class="filter-header" onclick="scheduleRedesign.toggleFilterSection('source')">
                    <span>Source</span>
                    <span class="chevron">&#9660;</span>
                </div>
                <div class="filter-content">
                    <div class="filter-checkbox-group">
                        <div class="filter-checkbox-item select-all-item">
                            <input type="checkbox" id="source-select-all" checked onchange="scheduleRedesign.handleSelectAll('source', this.checked)">
                            <label for="source-select-all">Select All</label>
                        </div>
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="source-email" value="email" checked
                                   onchange="scheduleRedesign.handleFilterChange('source', 'email', this.checked)">
                            <label for="source-email">Email</label>
                        </div>
                        <div class="filter-checkbox-item">
                            <input type="checkbox" id="source-manual" value="manual" checked
                                   onchange="scheduleRedesign.handleFilterChange('source', 'manual', this.checked)">
                            <label for="source-manual">Manual</label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Clear All Filters Button -->
            <button class="clear-all-btn" id="clear-all-filters-btn-inner" onclick="scheduleRedesign.clearAllFilters()">Clear All Filters</button>
        `;

        this.elements.sidebarContent.innerHTML = html;

        // Named filter presets dropdown — pinned to the top of the filters tab.
        this._mountPresetDropdown();

        // Fetch staff list if not already loaded
        if (!this._staffList) {
            this._fetchStaffList();
        }
    }

    /**
     * Create (once) the shared filter-preset manager and (re)mount its dropdown
     * at the top of the filter sidebar. Called on every renderFilters() because
     * that rebuilds the sidebar's innerHTML.
     */
    _mountPresetDropdown() {
        if (!this.elements.sidebarContent) return;
        this._ensurePresetManager();
        // Remove any stale dropdown, then prepend a fresh one reflecting state.
        const existing = this.elements.sidebarContent.querySelector('.filter-presets');
        if (existing) existing.remove();
        this.elements.sidebarContent.prepend(this.presetManager.render());

        // "Save current filters" button, placed just above Clear All Filters.
        const existingSave = this.elements.sidebarContent.querySelector('.preset-save-button-wrap');
        if (existingSave) existingSave.remove();
        const clearBtn = this.elements.sidebarContent.querySelector('.clear-all-btn');
        const saveBtn = this.presetManager.renderSaveButton();
        if (clearBtn) clearBtn.parentNode.insertBefore(saveBtn, clearBtn);
        else this.elements.sidebarContent.appendChild(saveBtn);
    }

    /** Canonical preset-data object captured from the current filter state. */
    _getPresetData() {
        return {
            status: this.state.filters.status,
            type: this.state.filters.type,
            format: this.state.filters.format,
            staff: this.state.filters.staff,
            source: this.state.filters.source,
            myEvents: this.state.filters.myEvents,
            overlappingOnly: this.state.filters.overlappingOnly,
            memberAttending: this.state.filters.memberAttending,
            sortBy: this.state.sortBy,
            showPastEvents: this.state.showPastEvents,
            pastRange: this.state.pastRange,
        };
    }

    /** Apply a preset-data object to the schedule filters and refresh results. */
    _applyPresetData(preset) {
        this.state.filters.status = preset.status || [];
        this.state.filters.type = preset.type || [];
        this.state.filters.format = preset.format || [];
        this.state.filters.staff = preset.staff || [];
        this.state.filters.source = preset.source || [];
        this.state.filters.myEvents = preset.myEvents || false;
        this.state.filters.overlappingOnly = preset.overlappingOnly || false;
        this.state.filters.memberAttending = preset.memberAttending || false;
        if (preset.sortBy) this.state.sortBy = preset.sortBy;
        if (preset.showPastEvents !== undefined) this.state.showPastEvents = preset.showPastEvents;
        if (preset.pastRange) this.state.pastRange = preset.pastRange;

        this.renderFilters();
        this._syncFilterCheckboxes();
        if (this.elements.sortSelect) {
            this._setHeaderSelectValue(this.elements.sortSelect, this.state.sortBy);
        }
        if (this.elements.pastRangeSelect) {
            const pastVal = this.state.showPastEvents ? this.state.pastRange : 'none';
            this._setHeaderSelectValue(this.elements.pastRangeSelect, pastVal);
        }
        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    async _fetchStaffList() {
        try {
            const resp = await fetch('/api/office/choices/', {
                headers: { 'X-CSRFToken': this.config.csrfToken }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            this._staffList = (data.staff_members || []).map(s => ({
                name: s.name,
                id: s.id
            }));
            // Re-render filters now that staff list is available
            this.renderFilters();
            this._syncFilterCheckboxes();
        } catch (e) {
            console.error('Error fetching staff list:', e);
        }
    }

    toggleFilterSection(filterType) {
        const section = this.elements.sidebarContent.querySelector(`[data-filter="${filterType}"]`);
        if (section) {
            section.classList.toggle('collapsed');
        }
    }

    handleToggleFilter(filterName, checked) {
        this.state.filters[filterName] = checked;
        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    handleSelectAll(filterType, checked) {
        // Get all individual checkboxes for this filter
        const checkboxes = this.elements.sidebarContent.querySelectorAll(
            `[data-filter="${filterType}"] input[type="checkbox"]:not([id$="-select-all"])`
        );

        if (checked) {
            // "Select All" checked = check all individuals, clear filter (show all)
            this.state.filters[filterType] = [];
            checkboxes.forEach(cb => cb.checked = true);
        } else {
            // "Select All" unchecked = uncheck all individuals, but since filter is empty,
            // this would still show all. To show nothing, we'd need to add all to filter then show none.
            // Instead, just uncheck all and keep filter empty (still shows all)
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
            // Check if all are now checked
            const allChecked = Array.from(checkboxes).every(cb => cb.checked);

            if (allChecked) {
                // All checked = "Select All" state = clear filter
                this.state.filters[filterType] = [];
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = true;
                }
            } else {
                // Not all checked = build filter from checked items
                this.state.filters[filterType] = Array.from(checkboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = false;
                }
            }
        } else {
            // Unchecking an item
            // Check if all are now unchecked
            const noneChecked = Array.from(checkboxes).every(cb => !cb.checked);

            if (noneChecked) {
                // None checked = show all (clear filter), check "Select All"
                this.state.filters[filterType] = [];
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = true;
                }
                // Also re-check all items
                checkboxes.forEach(cb => cb.checked = true);
            } else {
                // Some still checked = build filter from checked items
                this.state.filters[filterType] = Array.from(checkboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = false;
                }
            }
        }

        this.state.page = 1;
        this.updateFiltersButtonState();
        this.fetchEvents();
    }

    clearAllFilters() {
        // Reset all filters
        this.state.filters = {
            status: [],
            type: [],
            format: [],
            staff: [],
            source: [],
            myEvents: false,
            overlappingOnly: false,
            memberAttending: false
        };

        // Deselect any active saved preset (resets trigger to "Filter presets").
        if (this.presetManager) this.presetManager.clearActive();

        // Reset checkboxes - check all filter-section checkboxes, uncheck toggles
        const sectionCheckboxes = this.elements.sidebarContent.querySelectorAll('.filter-section input[type="checkbox"]');
        sectionCheckboxes.forEach(cb => { cb.checked = true; });
        const myEvtsCb = document.getElementById('filter-my-events');
        const overlapCb = document.getElementById('filter-overlapping');
        if (myEvtsCb) myEvtsCb.checked = false;
        if (overlapCb) overlapCb.checked = false;

        // Clear search
        this.clearSearch();

        // Reset sort
        this.state.sortBy = 'start_date';
        if (this.elements.sortSelect) {
            this._setHeaderSelectValue(this.elements.sortSelect, 'start_date');
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

        // Show/hide clear button
        if (this.elements.searchClear) {
            this.elements.searchClear.classList.toggle('visible', query.length > 0);
        }

        // Debounce search
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
    // Sort Methods
    // =========================================================================

    handleSortChange(event) {
        this.state.sortBy = event.target.value;
        this.state.page = 1;
        this.fetchEvents();
    }

    handleUndatedSortChange(event) {
        this.state.undatedSortBy = event.target.value;
        this.state.page = 1;
        this.fetchEvents();
    }

    handlePastRangeChange(event) {
        const value = event.target.value;
        this.state.pastRange = value === 'none' ? 'all' : value;
        this.state.showPastEvents = value !== 'none';
        this.state.page = 1;
        this.fetchEvents();
    }

    // =========================================================================
    // Tabs (All Events / Undated)
    // =========================================================================

    /**
     * Switch between the "all" and "undated" tabs. The Undated tab surfaces
     * events that have no fixed date yet (null start_date) or that span a
     * tentative date range — scheduling clients often log these long before a
     * firm date is set, so they need a dedicated place to live.
     */
    async switchTab(tab) {
        if (!tab || tab === this.state.activeTab) return;
        const fromTab = this.state.activeTab;

        // Remember which event was open on the tab we're leaving, and snapshot
        // its loaded events, so swapping back and forth restores the selection
        // and renders instantly (no skeleton/refetch) when filters are unchanged.
        // Don't cache while a load is still in flight — its events aren't final
        // yet, and caching the half-loaded (often empty) list would make a
        // swap-back show nothing. Leave it null so swapping back refetches.
        this.state.tabSelection[fromTab] = this.state.detailPanelEventId;
        this.state.tabCache[fromTab] = this.state.isLoading ? null : {
            sig: this._filterSignature(),
            events: this.state.events,
            hasMore: this.state.hasMore,
            totalCount: this.state.totalCount,
            page: this.state.page,
        };

        this.state.activeTab = tab;
        this._updateTabUI();

        const cached = this.state.tabCache[tab];
        if (cached && cached.sig === this._filterSignature()) {
            // Restore from cache — render directly, no skeleton, no refetch.
            this.state.events = cached.events;
            this.state.hasMore = cached.hasMore;
            this.state.totalCount = cached.totalCount;
            this.state.page = cached.page;
            this.renderEventList();
            this.updateResultsCount();
        } else {
            // No usable cache (first visit, or filters changed) — fetch fresh.
            this.state.page = 1;
            await this.fetchEvents();
        }

        // If another tab switch superseded this one while we awaited the fetch,
        // let that newer switch own the selection restore.
        if (this.state.activeTab !== tab) return;

        // Restore the event previously selected on the tab we just entered —
        // but only if it's actually visible in this tab's (filtered) list.
        const restoreId = this.state.tabSelection[tab];
        const visible = this.filterEventsClientSide(this.state.events);
        const present = restoreId != null &&
            visible.some(e => String(e.id) === String(restoreId));
        if (present) {
            this.openDetailPanel(restoreId, { focusAction: true, silentFocus: true });
        } else if (this.state.detailPanelEventId != null) {
            // The departing tab's selection has no home here — clear the panel.
            this.closeDetailPanel();
        }
    }

    /**
     * A signature of the filter/search/sort state that determines an API
     * result set. Used to decide whether a tab's cached events are still valid.
     */
    _filterSignature() {
        const f = this.state.filters;
        return JSON.stringify([
            f.status, f.type, f.format, f.staff, f.source,
            f.myEvents, f.overlappingOnly, f.memberAttending,
            this.state.search, this.state.sortBy, this.state.undatedSortBy,
            this.state.showPastEvents, this.state.pastRange,
        ]);
    }

    /**
     * Reflect the active tab in the UI: highlight the selected tab button and
     * hide the Sort / Past-events controls on the Undated tab (date ordering and
     * past-date windows are meaningless for undated events).
     */
    _updateTabUI() {
        if (this.elements.tabs) {
            this.elements.tabs.querySelectorAll('.schedule-tab').forEach(btn => {
                const isActive = btn.dataset.tab === this.state.activeTab;
                btn.classList.toggle('active', isActive);
                btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
            });
        }
        const hideForUndated = this.state.activeTab === 'undated';
        if (this.elements.sortSelect) {
            this.elements.sortSelect.style.display = hideForUndated ? 'none' : '';
        }
        if (this.elements.pastRangeSelect) {
            this.elements.pastRangeSelect.style.display = hideForUndated ? 'none' : '';
        }
        // The Undated tab swaps the date-based Sort for its own sort dropdown.
        if (this.elements.undatedSortSelect) {
            this.elements.undatedSortSelect.style.display = hideForUndated ? '' : 'none';
        }
    }

    // =========================================================================
    // Data Fetching
    // =========================================================================

    async fetchEvents(append = false) {
        // Appends (infinite scroll) must not stack on an in-flight load. A
        // fresh load (tab/filter/search change), however, supersedes whatever
        // is in flight — we abort it and ignore its late response below so a
        // tab swap mid-load can't leave the list empty.
        if (append && this.state.isLoading) return;

        if (this._eventsAbort) this._eventsAbort.abort();
        const controller = new AbortController();
        this._eventsAbort = controller;
        const seq = (this._fetchSeq = (this._fetchSeq || 0) + 1);

        this.state.isLoading = true;
        this.showLoading(append);
        if (append) this.showLoadMore();

        try {
            const url = this.buildApiUrl();
            console.log('Fetching events from:', url);

            const response = await fetch(url, {
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                },
                signal: controller.signal
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            console.log('Events received:', data);

            // A newer fetch started while this one was in flight — drop this
            // stale response so it can't clobber the current tab's data.
            if (seq !== this._fetchSeq) return;

            if (append) {
                this.state.events = [...this.state.events, ...data.results];
            } else {
                this.state.events = data.results || [];
            }

            this.state.totalCount = data.count || this.state.events.length;
            this.state.hasMore = !!data.next;

            this.renderEventList();
            this.updateResultsCount();

        } catch (error) {
            // An aborted/superseded request is expected — ignore it quietly.
            if (error.name === 'AbortError' || seq !== this._fetchSeq) return;
            console.error('Error fetching events:', error);
            this.showError('Failed to load events. Please try again.');
        } finally {
            // Only the latest fetch owns the loading UI; a superseded one leaves
            // it to the newer request that replaced it.
            if (seq === this._fetchSeq) {
                this.state.isLoading = false;
                this.hideLoading();
                this.hideLoadMore();
            }
        }
    }

    buildApiUrl() {
        const params = new URLSearchParams();

        // Search
        if (this.state.search) {
            params.append('search', this.state.search);
        }

        // Filters
        this.state.filters.status.forEach(s => params.append('status', s));
        this.state.filters.type.forEach(t => params.append('type', t));
        this.state.filters.staff.forEach(s => params.append('staff', s));
        this.state.filters.source.forEach(s => params.append('source', s));

        // Toggle filters
        if (this.state.filters.myEvents) {
            params.append('my_events', 'true');
        }
        if (this.state.filters.overlappingOnly) {
            params.append('overlapping_only', 'true');
        }
        if (this.state.filters.memberAttending) {
            params.append('member_attending', 'true');
        }

        // On the Undated tab, ignore the date-window controls and use the
        // dedicated undated sort, pulling all undated/date-range events (past
        // included). The API's start_date filter is a >= comparison that would
        // drop NULL start_dates, so we must NOT send it here.
        // 'tentative' is a special server ordering: range events by their window
        // (ascending), with truly-dateless events sorted to the end.
        if (this.state.activeTab === 'undated') {
            params.append('undated_only', 'true');
            params.append('ordering', this.state.undatedSortBy || 'created');
            params.append('page', this.state.page);
            params.append('page_size', this.config.pageSize);
            params.append('include_archived', 'false');
            return `${this.config.apiUrl}?${params.toString()}`;
        }

        // Sort - handle special "not_dated" option
        if (this.state.sortBy && this.state.sortBy !== 'not_dated') {
            params.append('ordering', this.state.sortBy);
        } else if (this.state.sortBy === 'not_dated') {
            // For "not_dated", sort by recently created
            params.append('ordering', '-created');
        }

        // For "Date" sort, filter at the API level
        // - If NOT showing past events: include today + all future events
        //   (today's events show even if their start_time has already passed)
        // - If showing past events: filter to the selected range (unless "All Time")
        // The API uses 'start_date' param which filters for start_date >= value.
        // We use the LOCAL date — toISOString() converts to UTC and can shift the
        // date forward for negative-offset timezones in the evening, excluding
        // today's events.
        const localDateStr = (d) =>
            `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

        if (this.state.sortBy === 'start_date') {
            if (!this.state.showPastEvents) {
                // Today + future events (today's start_date passes start_date >= today)
                params.append('start_date', localDateStr(new Date()));
            } else {
                // Apply the selected range filter at API level
                const cutoffDate = this.getPastRangeCutoffDate();
                if (cutoffDate) {
                    params.append('start_date', localDateStr(cutoffDate));
                }
            }
        }

        // Pagination
        params.append('page', this.state.page);
        params.append('page_size', this.config.pageSize);

        // Don't include archived
        params.append('include_archived', 'false');

        return `${this.config.apiUrl}?${params.toString()}`;
    }

    /**
     * Calculate the cutoff date for past events based on the selected range
     */
    getPastRangeCutoffDate() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        switch (this.state.pastRange) {
            case '7days':
                // Past 7 days from today
                const sevenDaysAgo = new Date(today);
                sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
                return sevenDaysAgo;
            case 'week':
                // This week (from Sunday)
                const thisWeekStart = new Date(today);
                thisWeekStart.setDate(thisWeekStart.getDate() - thisWeekStart.getDay());
                return thisWeekStart;
            case '30days':
                // Past 30 days from today
                const thirtyDaysAgo = new Date(today);
                thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
                return thirtyDaysAgo;
            case 'month':
                // This month (from 1st)
                const thisMonthStart = new Date(today.getFullYear(), today.getMonth(), 1);
                return thisMonthStart;
            case '365days':
                // Past 365 days from today
                const yearAgo = new Date(today);
                yearAgo.setDate(yearAgo.getDate() - 365);
                return yearAgo;
            case 'year':
                // This year (from Jan 1)
                const thisYearStart = new Date(today.getFullYear(), 0, 1);
                return thisYearStart;
            case 'all':
            default:
                return null; // No cutoff
        }
    }

    /**
     * Filter events client-side based on current options
     */
    filterEventsClientSide(events) {
        let filtered = events;
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Filter out events that require human review
        filtered = filtered.filter(event => !event.requires_human_review);

        // Undated tab: keep only events with no fixed date or a tentative date
        // range. No past/future filtering — undated events are timeless, and a
        // range event stays relevant until its date firms up.
        if (this.state.activeTab === 'undated') {
            return filtered.filter(event => {
                // No start date = undated.
                if (!event.start_date) return true;
                // end_date different from start_date = a date range, not a fixed day.
                if (event.end_date && event.end_date !== event.start_date) return true;
                return false;
            });
        }

        const isDateSort = this.state.sortBy === 'start_date' || this.state.sortBy === '-start_date';

        // If showing past events, apply the range filter
        if (this.state.showPastEvents) {
            const cutoffDate = this.getPastRangeCutoffDate();
            if (cutoffDate) {
                filtered = filtered.filter(event => {
                    // Keep undated events
                    if (!event.start_date) return true;
                    // Filter out events older than the cutoff
                    const eventDate = new Date(event.start_date + 'T00:00:00');
                    return eventDate >= cutoffDate;
                });
            }
        }

        // Filter for "Not dated" sort - show only undated or date-range events
        if (this.state.sortBy === 'not_dated') {
            filtered = filtered.filter(event => {
                // No start date = undated
                if (!event.start_date) return true;
                // Has end_date different from start_date = date range
                if (event.end_date && event.end_date !== event.start_date) return true;
                return false;
            });
        }

        // For "Date" sort - show dated events + undated events at the end
        // Filter out past events UNLESS "Show past events" is checked
        if (this.state.sortBy === 'start_date') {
            filtered = filtered.filter(event => {
                // Allow undated events (they'll be shown at the end)
                if (!event.start_date) return true;
                // Filter out date ranges (they go to "Not Dated" sort)
                if (event.end_date && event.end_date !== event.start_date) return false;
                return true;
            });

            // Filter past events unless showPastEvents is checked
            if (!this.state.showPastEvents) {
                filtered = filtered.filter(event => {
                    // Keep undated events
                    if (!event.start_date) return true;
                    // Use 'T00:00:00' to ensure local timezone interpretation
                    const eventDate = new Date(event.start_date + 'T00:00:00');
                    return eventDate >= today;
                });
            }
        }

        // For "Date (Latest)" sort - show dated events + undated events at the end
        if (this.state.sortBy === '-start_date') {
            filtered = filtered.filter(event => {
                // Allow undated events (they'll be shown at the end)
                if (!event.start_date) return true;
                // Filter out date ranges (they go to "Not Dated" sort)
                if (event.end_date && event.end_date !== event.start_date) return false;
                return true;
            });

            // Filter past events unless showPastEvents is checked (only for dated events)
            if (!this.state.showPastEvents) {
                filtered = filtered.filter(event => {
                    // Keep undated events
                    if (!event.start_date) return true;
                    // Use 'T00:00:00' to ensure local timezone interpretation
                    const eventDate = new Date(event.start_date + 'T00:00:00');
                    return eventDate >= today;
                });
            }
        }

        // Filter past events for non-date sorts (unless showPastEvents is checked)
        if (!this.state.showPastEvents && !isDateSort) {
            filtered = filtered.filter(event => {
                // Keep undated events
                if (!event.start_date) return true;

                // For date ranges, check if end_date is today or later
                if (event.end_date && event.end_date !== event.start_date) {
                    // Use 'T00:00:00' to ensure local timezone interpretation
                    const endDate = new Date(event.end_date + 'T00:00:00');
                    return endDate >= today;
                }

                // For single dates, check if start_date is today or later
                // Use 'T00:00:00' to ensure local timezone interpretation
                const eventDate = new Date(event.start_date + 'T00:00:00');
                return eventDate >= today;
            });
        }

        // For date sorts, sort properly by full date (including year)
        // Undated events go to the end
        if (isDateSort) {
            const ascending = this.state.sortBy === 'start_date';
            filtered.sort((a, b) => {
                // Undated events go to the end
                if (!a.start_date && !b.start_date) return 0;
                if (!a.start_date) return 1; // a goes after b
                if (!b.start_date) return -1; // b goes after a

                // Use 'T00:00:00' to ensure local timezone interpretation
                const dateA = new Date(a.start_date + 'T00:00:00');
                const dateB = new Date(b.start_date + 'T00:00:00');
                return ascending ? dateA - dateB : dateB - dateA;
            });
        }

        return filtered;
    }

    loadMoreEvents() {
        this.state.page += 1;
        this.fetchEvents(true);
    }

    /**
     * Auto-load the next page when the user scrolls near the bottom.
     * @param {Element} scroller - the element that fired the scroll event
     */
    handleInfiniteScroll(scroller) {
        if (!scroller || !scroller.scrollHeight) return;
        if (!this.state.hasMore || this.state.isLoading) return;

        const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
        if (remaining <= 300) {
            this.loadMoreEvents();
        }
    }

    // =========================================================================
    // View Toggle
    // =========================================================================

    handleViewToggle(viewMode) {
        if (viewMode === this.state.viewMode) return;
        this.state.viewMode = viewMode;

        // Update toggle button active states
        if (this.elements.viewToggle) {
            this.elements.viewToggle.querySelectorAll('.schedule-view-toggle-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.view === viewMode);
            });
        }

        // Toggle class on the view container and list-detail wrapper (for panel resize)
        if (this.elements.viewContainer) {
            this.elements.viewContainer.classList.toggle('spreadsheet-mode', viewMode === 'spreadsheet');
        }
        if (this.elements.listDetailWrapper) {
            this.elements.listDetailWrapper.classList.toggle('spreadsheet-mode', viewMode === 'spreadsheet');
        }

        // The spreadsheet uses Excel-style cell navigation instead of the side
        // panel: close the panel when entering it, drop the cell cursor on exit.
        if (viewMode === 'spreadsheet') {
            this.closeDetailPanel();
        } else {
            this._clearSsCursor();
        }

        // Re-render (no re-fetch)
        this.renderEventList();
    }

    // =========================================================================
    // Rendering - Card List with Optional Date Grouping
    // =========================================================================

    renderEventList() {
        if (!this.elements.eventList) return;

        // Apply client-side filtering
        const filteredEvents = this.filterEventsClientSide(this.state.events);

        // Store filtered count for results display
        this.state.filteredCount = filteredEvents.length;

        if (filteredEvents.length === 0) {
            this.elements.eventList.innerHTML = this.renderEmptyState();
            this.hideLoadMore();
            this.updateResultsCount();
            return;
        }

        // Branch on view mode
        if (this.state.viewMode === 'spreadsheet') {
            this.elements.eventList.innerHTML = this.renderSpreadsheetView(filteredEvents);
            this.bindSpreadsheetClicks();
            this.bindStatusDropdowns();
            this.bindCellDropdowns();
        } else {
            let html = '<div class="schedule-cards-container">';

            // Determine if search or filters are active
            const hasActiveSearch = this.state.search && this.state.search.trim().length > 0;
            const hasActiveFilters = this.hasActiveFilters();
            const isSearchingOrFiltering = hasActiveSearch || hasActiveFilters;

            // Undated tab: events have no date to group by — flat card list.
            if (this.state.activeTab === 'undated') {
                for (const event of filteredEvents) {
                    html += this.renderEventCard(event);
                }
                html += '</div>';
            }
            // Show date headers for Date (Soonest) and Date (Latest) - ALWAYS (even with search/filters)
            else if (this.state.sortBy === 'start_date' || this.state.sortBy === '-start_date') {
                const ascending = this.state.sortBy === 'start_date';
                html = this.renderEventsWithDateHeaders(filteredEvents, ascending);
            }
            // Show modified headers for Recently Modified - only when NOT searching/filtering
            else if (this.state.sortBy === '-modified' && !isSearchingOrFiltering) {
                html = this.renderEventsWithModifiedHeaders(filteredEvents);
            }
            // Show created headers for Recently Created - only when NOT searching/filtering
            else if (this.state.sortBy === '-created' && !isSearchingOrFiltering) {
                html = this.renderEventsWithCreatedHeaders(filteredEvents);
            }
            else {
                // Render flat list of cards (no headers)
                for (const event of filteredEvents) {
                    html += this.renderEventCard(event);
                }
                html += '</div>';
            }

            this.elements.eventList.innerHTML = html;

            // Bind event click handlers
            this.bindEventClicks();

            // Compute and render overlap indicators on cards
            this.renderOverlapIndicators();

            // Bind body-level tooltips for staff/tags with 2+ items
            this.renderStaffTagTooltips();

            // Bind status dropdown change handlers
            this.bindStatusDropdowns();
        }

        // The load-more indicator is a transient spinner shown only during an
        // append fetch (driven by fetchEvents); nothing to toggle here.
    }

    /**
     * Render events grouped by date with date headers
     * - When showing past events: all events in chronological order (oldest to newest for "Date", newest to oldest for "Date (Reversed)")
     * - When not showing past: future events with date headers, then undated
     * - Undated events always go at the end with "No Date Set" header
     * @param {Array} events - List of events to render
     * @param {boolean} ascending - If true, sort dates ascending (oldest first); if false, descending (newest first)
     */
    renderEventsWithDateHeaders(events, ascending = true) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Group events by date
        const dateGroups = new Map(); // date string -> events
        const undatedEvents = [];

        for (const event of events) {
            // Collect undated events separately
            if (!event.start_date) {
                undatedEvents.push(event);
                continue;
            }

            const dateKey = event.start_date; // YYYY-MM-DD format
            if (!dateGroups.has(dateKey)) {
                dateGroups.set(dateKey, []);
            }
            dateGroups.get(dateKey).push(event);
        }

        // Sort date keys chronologically (ascending or descending based on sort mode)
        const sortedDates = Array.from(dateGroups.keys()).sort((a, b) => {
            const dateA = new Date(a + 'T00:00:00');
            const dateB = new Date(b + 'T00:00:00');
            return ascending ? dateA - dateB : dateB - dateA;
        });

        let html = '<div class="schedule-cards-container with-date-headers">';

        // Render events grouped by date
        for (const dateKey of sortedDates) {
            const eventsForDate = dateGroups.get(dateKey);
            const dateObj = new Date(dateKey + 'T00:00:00'); // Ensure local timezone
            const isToday = dateObj.getTime() === today.getTime();

            html += this.renderDateHeader(dateObj, isToday);

            for (const event of eventsForDate) {
                html += this.renderEventCard(event);
            }
        }

        // Render undated events at the end with "No Date Set" header
        // Only show undated events when all pages have been loaded (no more to load)
        if (undatedEvents.length > 0 && !this.state.hasMore) {
            html += this.renderSectionHeader('No Date Set');
            for (const event of undatedEvents) {
                html += this.renderEventCard(event);
            }
        }

        html += '</div>';
        return html;
    }

    /**
     * Render a date header for a specific date
     */
    renderDateHeader(date, isToday = false) {
        const now = new Date();
        const currentYear = now.getFullYear();
        const eventYear = date.getFullYear();
        const dayName = date.toLocaleDateString('en-US', { weekday: 'long' });

        // Check if tomorrow
        const tomorrow = new Date(now);
        tomorrow.setDate(tomorrow.getDate() + 1);
        tomorrow.setHours(0, 0, 0, 0);
        const isTomorrow = date.getTime() === tomorrow.getTime();

        // Include year if it's not the current year
        const dateOptions = eventYear !== currentYear
            ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }
            : { weekday: 'long', month: 'long', day: 'numeric' };
        const fullDateLabel = date.toLocaleDateString('en-US', dateOptions);

        // For today and tomorrow, show special labels
        if (isToday) {
            return `
                <div class="schedule-date-header today">
                    <span class="date-label">Today</span>
                    <span class="day-label">${fullDateLabel}</span>
                </div>
            `;
        }

        if (isTomorrow) {
            return `
                <div class="schedule-date-header tomorrow">
                    <span class="date-label">Tomorrow</span>
                    <span class="day-label">${fullDateLabel}</span>
                </div>
            `;
        }

        // Regular date header
        const dateOnlyOptions = eventYear !== currentYear
            ? { month: 'long', day: 'numeric', year: 'numeric' }
            : { month: 'long', day: 'numeric' };
        const dateLabel = date.toLocaleDateString('en-US', dateOnlyOptions);

        return `
            <div class="schedule-date-header">
                <span class="date-label">${dateLabel}</span>
                <span class="day-label">${dayName}</span>
            </div>
        `;
    }

    /**
     * Render a section header (for "No Date Set", "Earlier", etc.)
     */
    renderSectionHeader(title) {
        return `
            <div class="schedule-section-header">
                <span class="section-label">${title}</span>
            </div>
        `;
    }

    /**
     * Render events grouped by modification time with headers
     * - "Modified today"
     * - "Yesterday"
     * - "This week"
     * - "Earlier"
     */
    renderEventsWithModifiedHeaders(events) {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        // Calculate start of this week (Sunday)
        const thisWeekStart = new Date(today);
        thisWeekStart.setDate(thisWeekStart.getDate() - thisWeekStart.getDay());

        // Group events by modification period
        const modifiedToday = [];
        const modifiedYesterday = [];
        const modifiedThisWeek = [];
        const modifiedEarlier = [];

        for (const event of events) {
            // Use modified_at or modified field (API returns modified_at)
            const modifiedStr = event.modified_at || event.modified;
            if (!modifiedStr) {
                modifiedEarlier.push(event);
                continue;
            }

            const modifiedDate = new Date(modifiedStr);
            const modifiedDay = new Date(modifiedDate.getFullYear(), modifiedDate.getMonth(), modifiedDate.getDate());

            if (modifiedDay.getTime() === today.getTime()) {
                modifiedToday.push(event);
            } else if (modifiedDay.getTime() === yesterday.getTime()) {
                modifiedYesterday.push(event);
            } else if (modifiedDay >= thisWeekStart) {
                modifiedThisWeek.push(event);
            } else {
                modifiedEarlier.push(event);
            }
        }

        let html = '<div class="schedule-cards-container with-date-headers">';

        // Render each group with its header
        if (modifiedToday.length > 0) {
            html += this.renderSectionHeader('Modified Today');
            for (const event of modifiedToday) {
                html += this.renderEventCard(event);
            }
        }

        if (modifiedYesterday.length > 0) {
            html += this.renderSectionHeader('Modified Yesterday');
            for (const event of modifiedYesterday) {
                html += this.renderEventCard(event);
            }
        }

        if (modifiedThisWeek.length > 0) {
            html += this.renderSectionHeader('Modified This Week');
            for (const event of modifiedThisWeek) {
                html += this.renderEventCard(event);
            }
        }

        if (modifiedEarlier.length > 0) {
            html += this.renderSectionHeader('Modified Earlier');
            for (const event of modifiedEarlier) {
                html += this.renderEventCard(event);
            }
        }

        html += '</div>';
        return html;
    }

    /**
     * Render events grouped by creation time with headers
     * - "Created Today"
     * - "Created Yesterday"
     * - "Created This Week"
     * - "Created Earlier"
     */
    renderEventsWithCreatedHeaders(events) {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        // Calculate start of this week (Sunday)
        const thisWeekStart = new Date(today);
        thisWeekStart.setDate(thisWeekStart.getDate() - thisWeekStart.getDay());

        // Group events by creation period
        const createdToday = [];
        const createdYesterday = [];
        const createdThisWeek = [];
        const createdEarlier = [];

        for (const event of events) {
            // Use created_at or created field (API returns created_at)
            const createdStr = event.created_at || event.created;
            if (!createdStr) {
                createdEarlier.push(event);
                continue;
            }

            const createdDate = new Date(createdStr);
            const createdDay = new Date(createdDate.getFullYear(), createdDate.getMonth(), createdDate.getDate());

            if (createdDay.getTime() === today.getTime()) {
                createdToday.push(event);
            } else if (createdDay.getTime() === yesterday.getTime()) {
                createdYesterday.push(event);
            } else if (createdDay >= thisWeekStart) {
                createdThisWeek.push(event);
            } else {
                createdEarlier.push(event);
            }
        }

        let html = '<div class="schedule-cards-container with-date-headers">';

        // Render each group with its header
        if (createdToday.length > 0) {
            html += this.renderSectionHeader('Created Today');
            for (const event of createdToday) {
                html += this.renderEventCard(event);
            }
        }

        if (createdYesterday.length > 0) {
            html += this.renderSectionHeader('Created Yesterday');
            for (const event of createdYesterday) {
                html += this.renderEventCard(event);
            }
        }

        if (createdThisWeek.length > 0) {
            html += this.renderSectionHeader('Created This Week');
            for (const event of createdThisWeek) {
                html += this.renderEventCard(event);
            }
        }

        if (createdEarlier.length > 0) {
            html += this.renderSectionHeader('Created Earlier');
            for (const event of createdEarlier) {
                html += this.renderEventCard(event);
            }
        }

        html += '</div>';
        return html;
    }

    /**
     * Compute overlaps client-side from loaded events and fill in card indicators.
     */
    renderOverlapIndicators() {
        const events = this.state.events;
        if (!events || events.length < 2) return;

        // Build datetime pairs for events that have full time ranges
        const timed = [];
        for (const e of events) {
            if (!e.start_date || !e.start_time || !e.end_date || !e.end_time) continue;
            if (e.is_archived) continue;
            const start = new Date(`${e.start_date}T${e.start_time}`);
            const end = new Date(`${e.end_date}T${e.end_time}`);
            if (isNaN(start) || isNaN(end)) continue;
            timed.push({ id: String(e.id), title: e.title || e.group || 'Untitled Event', start, end });
        }

        // For each timed event, find overlapping peers
        const overlapMap = new Map(); // eventId -> [{title}]
        for (let i = 0; i < timed.length; i++) {
            for (let j = i + 1; j < timed.length; j++) {
                const a = timed[i], b = timed[j];
                if (a.start < b.end && b.start < a.end) {
                    if (!overlapMap.has(a.id)) overlapMap.set(a.id, []);
                    if (!overlapMap.has(b.id)) overlapMap.set(b.id, []);
                    overlapMap.get(a.id).push(b.title);
                    overlapMap.get(b.id).push(a.title);
                }
            }
        }

        // Fill in placeholder indicators
        const indicators = this.elements.eventList?.querySelectorAll('.overlap-indicator');
        if (!indicators) return;
        for (const el of indicators) {
            const eventId = el.dataset.eventId;
            const titles = overlapMap.get(eventId);
            if (!titles || titles.length === 0) continue;

            const tooltipLines = titles.map(t => this.escapeHtml(t));
            const countHtml = titles.length > 1 ? `<span class="indicator-count">${titles.length}</span>` : '';
            el.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="13" stroke-width="3"></line>
                    <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"></circle>
                </svg>
                ${countHtml}
            `;
            el.style.display = '';

            // Show tooltip on body-level element (card transforms create
            // containing blocks that trap position:fixed children)
            el.addEventListener('mouseenter', () => {
                this.showBodyTooltip(el, 'Overlaps with:', tooltipLines);
            });
            el.addEventListener('mouseleave', () => {
                this.hideBodyTooltip();
            });
        }
    }

    /**
     * Show a body-level tooltip anchored above the given element.
     */
    showBodyTooltip(anchorEl, header, lines) {
        let tip = document.getElementById('card-body-tooltip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'card-body-tooltip';
            tip.className = 'card-body-tooltip';
            document.body.appendChild(tip);
        }
        const listItems = lines.map(l => `<li>${l}</li>`).join('');
        const headerHtml = header ? `<div class="card-tooltip-header">${this.escapeHtml(header)}</div>` : '';
        tip.innerHTML = `${headerHtml}<ul>${listItems}</ul>`;
        const rect = anchorEl.getBoundingClientRect();
        tip.style.top = (rect.top - 8) + 'px';
        // Remove any previous positioning
        tip.style.right = '';
        tip.style.left = '';
        // Temporarily show to measure width
        tip.style.visibility = 'hidden';
        tip.classList.add('visible');
        const tipWidth = tip.offsetWidth;
        // Center tooltip on anchor, arrow points to center of icon
        const anchorCenter = rect.left + rect.width / 2;
        let left = anchorCenter - tipWidth / 2;
        // Keep within viewport
        if (left < 8) left = 8;
        if (left + tipWidth > window.innerWidth - 8) left = window.innerWidth - tipWidth - 8;
        tip.style.left = left + 'px';
        tip.style.transform = 'translateY(-100%)';
        // Position the arrow to point at anchor center
        const arrowOffset = anchorCenter - left;
        tip.style.setProperty('--arrow-offset', arrowOffset + 'px');
        tip.style.visibility = '';
        tip.classList.add('visible');
    }

    hideBodyTooltip() {
        const tip = document.getElementById('card-body-tooltip');
        if (tip) tip.classList.remove('visible');
    }

    /**
     * Bind body-level tooltips for staff (2+) and tags (2+) indicators.
     */
    renderStaffTagTooltips() {
        const events = this.state.events;
        if (!events) return;
        const eventMap = new Map();
        for (const e of events) eventMap.set(String(e.id), e);

        // Staff tooltips
        const staffEls = this.elements.eventList?.querySelectorAll('.staff-body-tip');
        if (staffEls) {
            for (const el of staffEls) {
                const ev = eventMap.get(el.dataset.eventId);
                if (!ev || !ev.staff || ev.staff.length < 2) continue;
                const lines = ev.staff.map(s => this.escapeHtml(s));
                el.addEventListener('mouseenter', () => this.showBodyTooltip(el, null, lines));
                el.addEventListener('mouseleave', () => this.hideBodyTooltip());
            }
        }

        // Tags tooltips
        const tagEls = this.elements.eventList?.querySelectorAll('.tags-body-tip');
        if (tagEls) {
            for (const el of tagEls) {
                const ev = eventMap.get(el.dataset.eventId);
                if (!ev || !ev.tags || ev.tags.length < 2) continue;
                const lines = ev.tags.map(t => this.escapeHtml(t));
                el.addEventListener('mouseenter', () => this.showBodyTooltip(el, null, lines));
                el.addEventListener('mouseleave', () => this.hideBodyTooltip());
            }
        }
    }

    renderEventCard(event) {
        const statusClass = event.status ? `status-${event.status.toLowerCase().replace(/\s+/g, '_')}` : '';

        // Format date portion (short: "Feb 9")
        let datePart = '';
        let timePart = '';
        if (event.start_date) {
            const startDate = new Date(event.start_date);
            if (event.end_date && event.end_date !== event.start_date) {
                const endDate = new Date(event.end_date);
                const startFmt = startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                const endFmt = endDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                datePart = `${startFmt} – ${endFmt}`;
            } else {
                const currentYear = new Date().getFullYear();
                const eventYear = startDate.getFullYear();
                const dateOpts = eventYear !== currentYear
                    ? { month: 'short', day: 'numeric', year: 'numeric' }
                    : { month: 'short', day: 'numeric' };
                datePart = startDate.toLocaleDateString('en-US', dateOpts);
            }
            if (event.start_time) {
                const time = new Date(`2000-01-01T${event.start_time}`);
                timePart = time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
                if (event.end_time) {
                    const endTime = new Date(`2000-01-01T${event.end_time}`);
                    timePart += ' – ' + endTime.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
                }
            }
        } else {
            datePart = 'No date set';
        }

        // Build second-line metadata string: "Date · Time"
        const orgName = event.organization || event.group || '';
        const metaParts = [];
        if (datePart) metaParts.push(datePart);
        if (timePart) metaParts.push(timePart);
        const metaString = metaParts.join(' · ');

        // Member of Congress indicator — podium icon, shown only when the
        // office's Member is assigned to this event. Sits left of the staff icon.
        let mocHtml = '';
        if (event.member_of_congress) {
            const mocTooltip = 'Member attending';
            mocHtml = `
                <span class="schedule-card-indicator">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="4.5" r="2.5"></circle>
                        <path d="M8.5 10a3.5 3.5 0 0 1 7 0"></path>
                        <path d="M6 11.5h12v2H6z"></path>
                        <path d="M12 13.5v6"></path>
                        <path d="M9 19.5h6"></path>
                    </svg>
                    <span class="indicator-tooltip">${mocTooltip}</span>
                </span>
            `;
        }

        // Build compact staff indicator
        let staffHtml = '';
        if (event.staff && Array.isArray(event.staff) && event.staff.length > 0) {
            if (event.staff.length === 1) {
                const staffTooltip = this.escapeHtml(event.staff[0]);
                staffHtml = `
                    <span class="schedule-card-indicator">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        <span class="indicator-count">${event.staff.length}</span>
                        <span class="indicator-tooltip">${staffTooltip}</span>
                    </span>
                `;
            } else {
                staffHtml = `
                    <span class="schedule-card-indicator staff-body-tip" data-event-id="${event.id}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        <span class="indicator-count">${event.staff.length}</span>
                    </span>
                `;
            }
        }

        // Build compact tag indicator
        let tagsHtml = '';
        if (event.tags && Array.isArray(event.tags) && event.tags.length > 0) {
            if (event.tags.length === 1) {
                const tagsTooltip = this.escapeHtml(event.tags[0]);
                tagsHtml = `
                    <span class="schedule-card-indicator">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                            <line x1="7" y1="7" x2="7.01" y2="7"></line>
                        </svg>
                        <span class="indicator-count">${event.tags.length}</span>
                        <span class="indicator-tooltip">${tagsTooltip}</span>
                    </span>
                `;
            } else {
                tagsHtml = `
                    <span class="schedule-card-indicator tags-body-tip" data-event-id="${event.id}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                            <line x1="7" y1="7" x2="7.01" y2="7"></line>
                        </svg>
                        <span class="indicator-count">${event.tags.length}</span>
                    </span>
                `;
            }
        }

        // Permission check: can_edit = can edit this event (and change its status from the card)
        const canEdit = event.can_edit === true;

        // Build edit/view icon — show edit pencil only if user can edit, otherwise eye icon
        const editIconSvg = canEdit
            ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>`
            : `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
        const editTooltip = canEdit ? 'Edit event' : 'Read only';
        const editBtnHtml = `
            <button type="button" class="schedule-card-edit-btn" data-event-id="${event.id}" title="${editTooltip}">
                ${editIconSvg}
                <span class="indicator-tooltip">${editTooltip}</span>
            </button>
        `;

        // Overlap indicator placeholder — filled after render by renderOverlapIndicators()
        const overlapPlaceholder = `<span class="schedule-card-indicator overlap-indicator" data-event-id="${event.id}" style="display:none"></span>`;

        const indicatorsHtml = `<div class="schedule-card-indicators">${mocHtml}${staffHtml}${tagsHtml}${overlapPlaceholder}${editBtnHtml}</div>`;

        // Build custom dropdown options
        const dropdownOptions = this.statusChoices.map(choice => {
            const { value, label, is_active } = this.normalizeChoice(choice);
            const selectedClass = value === event.status ? 'selected' : '';
            const inactiveClass = !is_active ? 'inactive' : '';
            const optionStatusClass = `status-${value.toLowerCase().replace(/\s+/g, '_')}`;
            const displayLabel = !is_active ? `${label} (Inactive)` : label;
            return `<div class="schedule-dropdown-option ${selectedClass} ${inactiveClass} ${optionStatusClass}" data-value="${value}">${displayLabel}</div>`;
        }).join('');

        // Get current status label
        const currentStatusChoice = this.statusChoices.find(choice => {
            const { value } = this.normalizeChoice(choice);
            return value === event.status;
        });
        const currentStatusLabel = currentStatusChoice
            ? this.normalizeChoice(currentStatusChoice).label
            : (event.status || 'Select Status');

        const readOnlyClass = canEdit ? '' : ' read-only';
        let titleHtml = this.escapeHtml(event.title || 'Untitled Event');
        if (orgName && orgName !== event.title) {
            titleHtml += ` <span class="schedule-card-org">· ${this.escapeHtml(orgName)}</span>`;
        }

        return `
            <div class="schedule-card ${statusClass}${readOnlyClass}" data-event-id="${event.id}">
                <div class="schedule-card-status-bar"></div>
                <div class="schedule-card-body">
                    <div class="schedule-card-left">
                        <div class="schedule-card-title">${titleHtml}</div>
                        <div class="schedule-card-meta-line">${metaString}</div>
                    </div>
                    <div class="schedule-card-right-col">
                        <div class="schedule-status-dropdown-wrapper" data-event-id="${event.id}">
                            <div class="schedule-card-status-select" tabindex="${canEdit ? '0' : '-1'}">
                                <span class="schedule-status-text">${currentStatusLabel}</span>
                            </div>
                            <div class="schedule-dropdown-menu">
                                ${dropdownOptions}
                            </div>
                        </div>
                        ${indicatorsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    renderEmptyState() {
        if (this.state.activeTab === 'undated') {
            return `<div class="schedule-empty-state">No undated events. Events with no fixed date or a tentative date range will appear here.</div>`;
        }
        return `<div class="schedule-empty-state">No events found.</div>`;
    }

    // =========================================================================
    // Spreadsheet View
    // =========================================================================

    getSpreadsheetColumns() {
        return [
            { key: 'status_bar', header: '' },
            { key: 'title', header: 'Title' },
            { key: 'status', header: 'Status' },
            { key: 'start_date', header: 'Start Date' },
            { key: 'start_time', header: 'Start Time' },
            { key: 'end_date', header: 'End Date' },
            { key: 'end_time', header: 'End Time' },
            { key: 'timezone', header: 'Timezone' },
            { key: 'primary_org', header: 'Primary Org' },
            { key: 'other_orgs', header: 'Other Organizations' },
            { key: 'primary_contact', header: 'Primary Contact' },
            { key: 'other_contacts', header: 'Other Contacts' },
            { key: 'type', header: 'Type' },
            { key: 'format', header: 'Format' },
            { key: 'location', header: 'Location' },
            { key: 'staff', header: 'Staff' },
            { key: 'tags', header: 'Tags' },
            { key: 'description', header: 'Description' },
            { key: 'created', header: 'Created' },
            { key: 'modified', header: 'Modified' }
        ];
    }

    // Wrap plain-text cell content so it can truncate AND spill into empty
    // neighbouring cells (see _applySpreadsheetSpill).
    _cellText(text) {
        return `<span class="ss-cell-content">${this.escapeHtml(text || '')}</span>`;
    }

    // Map an IANA timezone value to its short (3-4 letter) US abbreviation.
    _tzAbbrev(value) {
        const map = {
            'America/New_York': 'EST',
            'America/Chicago': 'CST',
            'America/Denver': 'MST',
            'America/Los_Angeles': 'PST',
            'America/Anchorage': 'AKST',
            'Pacific/Honolulu': 'HST',
            'UTC': 'UTC',
        };
        return map[value] || value || '';
    }

    // Choices for an editable spreadsheet choice-cell, normalized to {value,label}.
    _choicesFor(field) {
        const fc = this.config.filterChoices || {};
        if (field === 'timezone') {
            // Show short abbreviations (EST, CST, …) rather than full names.
            return (fc.timezones || []).map(c => {
                const { value } = this.normalizeChoice(c);
                return { value, label: this._tzAbbrev(value), is_active: true };
            });
        }
        const raw = field === 'type' ? (fc.event_types || [])
            : field === 'format' ? (fc.event_formats || [])
            : [];
        return raw.map(c => this.normalizeChoice(c));
    }

    // Display label for a choice value. Prefers the office-configured choice label
    // (so it matches the dropdown options), then the type map, then the raw value.
    _choiceLabel(field, value) {
        if (!value) return '';
        const match = this._choicesFor(field).find(c => c.value === value);
        if (match) return match.label;
        if (field === 'type') return this.getTypeLabel(value);
        return value;
    }

    // A clickable chip for a linked contact/organization. Opens the READ-ONLY
    // details popup (not the editor). Returns '' when the record is missing.
    _renderRecordChip(kind, rec) {
        if (!rec || !rec.id) return '';
        const attr = kind === 'organization' ? 'data-org-id' : 'data-contact-id';
        const name = rec.name || '(unnamed)';
        return `<span class="ss-record-link" ${attr}="${this.escapeHtml(String(rec.id))}" `
            + `role="button" tabindex="0" title="View ${kind}">${this.escapeHtml(name)}</span>`;
    }

    // Comma-separated clickable chips for a list of linked records.
    _renderRecordChips(kind, list) {
        if (!Array.isArray(list) || !list.length) return '';
        return list.map(r => this._renderRecordChip(kind, r))
            .join('<span class="ss-record-sep">, </span>');
    }

    // Split a linked contact/org list into its primary record and the rest. The
    // primary is the is_primary one (or the first); it never repeats in "others".
    _splitPrimary(list) {
        const arr = Array.isArray(list) ? list : [];
        const primary = arr.find(r => r.is_primary) || arr[0] || null;
        const others = primary ? arr.filter(r => r.id !== primary.id) : [];
        return { primary, others };
    }

    // An editable choice cell (type/format/timezone) — a dropdown that mirrors the
    // status dropdown and PATCHes the field inline. Read-only when can_edit is false.
    _renderChoiceCell(event, field) {
        const canEdit = event.can_edit === true;
        const readOnlyClass = canEdit ? '' : ' read-only';
        // Timezone defaults to Eastern (EST) when an event has none set.
        const current = event[field] || (field === 'timezone' ? 'America/New_York' : '');
        const options = this._choicesFor(field).map(c => {
            const selectedClass = c.value === current ? 'selected' : '';
            const inactiveClass = c.is_active ? '' : 'inactive';
            const label = c.is_active ? c.label : `${c.label} (Inactive)`;
            return `<div class="schedule-dropdown-option ${selectedClass} ${inactiveClass}" `
                + `data-value="${this.escapeHtml(c.value)}">${this.escapeHtml(label)}</div>`;
        }).join('');
        const currentLabel = this._choiceLabel(field, current) || '—';
        return `<td class="col-choice">
            <div class="schedule-cell-dropdown-wrapper${readOnlyClass}" data-event-id="${event.id}" data-field="${field}">
                <div class="schedule-cell-dropdown-select" tabindex="${canEdit ? '0' : '-1'}">
                    <span class="schedule-cell-dropdown-text">${this.escapeHtml(currentLabel)}</span>
                </div>
                <div class="schedule-dropdown-menu">${options}</div>
            </div>
        </td>`;
    }

    renderSpreadsheetView(events) {
        const columns = this.getSpreadsheetColumns();

        let html = '<div class="schedule-spreadsheet-wrapper"><table class="schedule-spreadsheet">';

        // Header row
        html += '<thead><tr>';
        for (const col of columns) {
            const cssClass = col.key === 'status_bar' ? ' class="col-status-bar"' : '';
            html += `<th${cssClass}>${this.escapeHtml(col.header)}</th>`;
        }
        html += '</tr></thead>';

        // Body rows
        html += '<tbody>';
        for (const event of events) {
            const statusClass = event.status ? `status-${event.status.toLowerCase().replace(/\s+/g, '_')}` : '';
            const activeClass = this.state.detailPanelEventId == event.id ? ' detail-active' : '';
            html += `<tr data-event-id="${event.id}" class="${statusClass}${activeClass}">`;
            for (const col of columns) {
                html += this.renderSpreadsheetCell(event, col.key);
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';

        return html;
    }

    renderSpreadsheetCell(event, columnKey) {
        switch (columnKey) {
            case 'status_bar':
                return '<td class="col-status-bar"></td>';

            case 'title':
                return `<td class="col-title" data-edit-field="title">${this._cellText(event.title || 'Untitled Event')}</td>`;

            case 'primary_org': {
                const { primary } = this._splitPrimary(event.organizations);
                return `<td class="col-record"><span class="ss-cell-content">${this._renderRecordChip('organization', primary)}</span></td>`;
            }

            case 'other_orgs': {
                const { others } = this._splitPrimary(event.organizations);
                return `<td class="col-record col-record-multi">${this._renderRecordChips('organization', others)}</td>`;
            }

            case 'primary_contact': {
                const { primary } = this._splitPrimary(event.contacts);
                // Fall back to the denormalized POC name when no linked contact exists.
                const inner = (!primary && event.point_of_contact_name)
                    ? this.escapeHtml(event.point_of_contact_name)
                    : this._renderRecordChip('contact', primary);
                return `<td class="col-record"><span class="ss-cell-content">${inner}</span></td>`;
            }

            case 'other_contacts': {
                const { others } = this._splitPrimary(event.contacts);
                return `<td class="col-record col-record-multi">${this._renderRecordChips('contact', others)}</td>`;
            }

            case 'type':
                return this._renderChoiceCell(event, 'type');

            case 'format':
                return this._renderChoiceCell(event, 'format');

            case 'timezone':
                return this._renderChoiceCell(event, 'timezone');

            case 'status': {
                const canEdit = event.can_edit === true;
                const readOnlyClass = canEdit ? '' : ' read-only';
                const dropdownOptions = this.statusChoices.map(choice => {
                    const { value, label, is_active } = this.normalizeChoice(choice);
                    const selectedClass = value === event.status ? 'selected' : '';
                    const inactiveClass = !is_active ? 'inactive' : '';
                    const optionStatusClass = `status-${value.toLowerCase().replace(/\s+/g, '_')}`;
                    const displayLabel = !is_active ? `${label} (Inactive)` : label;
                    return `<div class="schedule-dropdown-option ${selectedClass} ${inactiveClass} ${optionStatusClass}" data-value="${value}">${displayLabel}</div>`;
                }).join('');

                const currentStatusChoice = this.statusChoices.find(choice => {
                    const { value } = this.normalizeChoice(choice);
                    return value === event.status;
                });
                const currentStatusLabel = currentStatusChoice
                    ? this.normalizeChoice(currentStatusChoice).label
                    : (event.status || 'Select Status');

                return `<td class="col-status">
                    <div class="schedule-status-dropdown-wrapper${readOnlyClass}" data-event-id="${event.id}">
                        <div class="schedule-card-status-select" tabindex="${canEdit ? '0' : '-1'}">
                            <span class="schedule-status-text">${currentStatusLabel}</span>
                        </div>
                        <div class="schedule-dropdown-menu">
                            ${dropdownOptions}
                        </div>
                    </div>
                </td>`;
            }

            case 'start_date':
                return `<td class="col-text">${this._cellText(event.start_date ? this._formatDateShort(event.start_date) : '')}</td>`;

            case 'start_time':
                return `<td class="col-text">${this._cellText(event.start_time ? this._formatTime(event.start_time) : '')}</td>`;

            case 'end_date':
                return `<td class="col-text">${this._cellText(event.end_date ? this._formatDateShort(event.end_date) : '')}</td>`;

            case 'end_time':
                return `<td class="col-text">${this._cellText(event.end_time ? this._formatTime(event.end_time) : '')}</td>`;

            case 'location':
                return `<td class="col-text" data-edit-field="location">${this._cellText(event.location || '')}</td>`;

            case 'staff': {
                const staff = Array.isArray(event.staff) ? event.staff : [];
                const primary = (event.primary_staff && staff.includes(event.primary_staff))
                    ? event.primary_staff : null;
                // Primary staffer first and bold, then the rest.
                const ordered = primary ? [primary, ...staff.filter(s => s !== primary)] : staff;
                const html = ordered.map(s => s === primary
                    ? `<strong>${this.escapeHtml(s)}</strong>`
                    : this.escapeHtml(s)).join(', ');
                return `<td class="col-text" data-open-tab="staff-review"><span class="ss-cell-content">${html}</span></td>`;
            }

            case 'tags': {
                const tagsStr = (event.tags && Array.isArray(event.tags)) ? event.tags.join(', ') : '';
                return `<td class="col-text">${this._cellText(tagsStr)}</td>`;
            }

            case 'description':
                return `<td class="col-description" data-edit-field="description">${this._cellText(event.description || '')}</td>`;

            case 'created':
                return `<td class="col-text">${this._cellText(event.created ? this._formatDateShort(event.created) : '')}</td>`;

            case 'modified':
                return `<td class="col-text">${this._cellText(event.modified ? this._formatDateShort(event.modified) : '')}</td>`;

            default:
                return '<td></td>';
        }
    }

    _formatDateShort(dateStr) {
        try {
            const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        } catch (_) {
            return dateStr;
        }
    }

    _formatTime(timeStr) {
        try {
            const t = new Date(`2000-01-01T${timeStr}`);
            return t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
        } catch (_) {
            return timeStr;
        }
    }

    bindSpreadsheetClicks() {
        // Interactive cells (status/choice dropdowns, record links) handle their
        // own clicks — a click inside them must NOT select/open the row.
        const isInteractive = (e) =>
            e.target.closest('.schedule-status-dropdown-wrapper') ||
            e.target.closest('.schedule-cell-dropdown-wrapper') ||
            e.target.closest('.ss-record-link');

        const rows = this.elements.eventList.querySelectorAll('.schedule-spreadsheet tbody tr[data-event-id]');
        rows.forEach(row => {
            // Single click = move the active cell (no side panel in this view).
            row.addEventListener('click', (e) => {
                if (isInteractive(e)) return;
                const td = e.target.closest('td');
                if (!td) return;
                const colIndex = Array.from(row.children).indexOf(td);
                const rowIndex = this._ssRows().indexOf(row);
                if (rowIndex >= 0) this._setSsCursor(rowIndex, colIndex);
            });

            // Double click: edit an editable text cell in place; otherwise open
            // the full editing modal.
            row.addEventListener('dblclick', (e) => {
                if (isInteractive(e)) return;
                const td = e.target.closest('td');
                if (td && td.dataset.editField) {
                    const colIndex = Array.from(row.children).indexOf(td);
                    const rowIndex = this._ssRows().indexOf(row);
                    if (rowIndex >= 0) {
                        this._setSsCursor(rowIndex, colIndex);
                        if (this._cursorEditableField()) { this._beginCellEdit(); return; }
                    }
                }
                const eventId = row.dataset.eventId;
                if (eventId) this.handleEventDoubleClick(eventId);
            });
        });

        // Clickable contact/org chips → read-only details popup.
        this.elements.eventList.querySelectorAll('.ss-record-link').forEach(link => {
            const open = (e) => {
                e.stopPropagation();
                if (!window.EventContactsPanel ||
                    typeof window.EventContactsPanel.openDetails !== 'function') return;
                const orgId = link.getAttribute('data-org-id');
                const contactId = link.getAttribute('data-contact-id');
                const name = link.textContent;
                if (orgId) window.EventContactsPanel.openDetails('organization', orgId, { name });
                else if (contactId) window.EventContactsPanel.openDetails('contact', contactId, { name });
            };
            link.addEventListener('click', open);
            link.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(e); }
            });
        });

        // Re-apply the active cell cursor after a re-render (clamped to bounds).
        this._applySsCursorHighlight();
        // Let long text spill into empty cells to its left.
        this._applySpreadsheetSpill();
    }

    // ----- Spreadsheet cell cursor (Excel-style keyboard navigation) ---------

    _ssRows() {
        return Array.from(this.elements.eventList?.querySelectorAll(
            '.schedule-spreadsheet tbody tr[data-event-id]') || []);
    }

    // Navigable column range: every column except the 4px status bar (index 0).
    _ssColBounds() {
        return { min: 1, max: this.getSpreadsheetColumns().length - 1 };
    }

    _ssCursorEventId() {
        if (!this.state.ssCursor) return null;
        const row = this._ssRows()[this.state.ssCursor.row];
        return row ? row.dataset.eventId : null;
    }

    _clearSsCursor() {
        this.state.ssCursor = null;
        this.elements.eventList?.querySelectorAll('.ss-cell-active')
            .forEach(td => td.classList.remove('ss-cell-active'));
    }

    // Paint the cursor cell (clamping to the current grid; clears if empty).
    _applySsCursorHighlight() {
        this.elements.eventList?.querySelectorAll('.ss-cell-active')
            .forEach(td => td.classList.remove('ss-cell-active'));
        if (!this.state.ssCursor) return;
        const rows = this._ssRows();
        if (!rows.length) { this.state.ssCursor = null; return; }
        const { min, max } = this._ssColBounds();
        const row = Math.max(0, Math.min(this.state.ssCursor.row, rows.length - 1));
        const col = Math.max(min, Math.min(this.state.ssCursor.col, max));
        this.state.ssCursor = { row, col };
        const td = rows[row].children[col];
        if (td) td.classList.add('ss-cell-active');
    }

    _setSsCursor(row, col) {
        const { min, max } = this._ssColBounds();
        this.state.ssCursor = {
            row,
            col: Math.max(min, Math.min(col, max)),
        };
        this._applySsCursorHighlight();
        this._scrollSsCellIntoView();
    }

    // Scroll the active cell into view, accounting for the sticky header. The
    // top/bottom rows scroll the container fully to its top/bottom so the header
    // (or last row) is flush, rather than leaving the cell tucked under the
    // sticky header.
    _scrollSsCellIntoView() {
        const active = this.elements.eventList?.querySelector('.ss-cell-active');
        if (!active) return;
        const wrapper = active.closest('.schedule-spreadsheet-wrapper');
        if (!wrapper) { active.scrollIntoView({ block: 'nearest', inline: 'nearest' }); return; }

        const rows = this._ssRows();
        const idx = rows.indexOf(active.parentElement);
        const thead = wrapper.querySelector('thead');
        const headH = thead ? thead.offsetHeight : 0;

        // Vertical
        if (idx === 0) {
            wrapper.scrollTop = 0;
        } else if (idx === rows.length - 1) {
            wrapper.scrollTop = wrapper.scrollHeight;
        } else {
            const w = wrapper.getBoundingClientRect();
            const c = active.getBoundingClientRect();
            if (c.top < w.top + headH) wrapper.scrollTop -= (w.top + headH - c.top);
            else if (c.bottom > w.bottom) wrapper.scrollTop += (c.bottom - w.bottom);
        }

        // Horizontal
        const w2 = wrapper.getBoundingClientRect();
        const c2 = active.getBoundingClientRect();
        if (c2.left < w2.left) wrapper.scrollLeft -= (w2.left - c2.left);
        else if (c2.right > w2.right) wrapper.scrollLeft += (c2.right - w2.right);
    }

    // Move the cursor by (dRow, dCol). toEdge (Shift) jumps to the first/last
    // row or column in that direction, like Ctrl/Shift+Arrow in Excel.
    _moveSsCursor(dRow, dCol, toEdge) {
        const rows = this._ssRows();
        if (!rows.length) return;
        const { min, max } = this._ssColBounds();
        if (!this.state.ssCursor) { this._setSsCursor(0, min); return; }
        let { row, col } = this.state.ssCursor;
        if (toEdge) {
            if (dRow < 0) row = 0; else if (dRow > 0) row = rows.length - 1;
            if (dCol < 0) col = min; else if (dCol > 0) col = max;
        } else {
            row += dRow; col += dCol;
        }
        row = Math.max(0, Math.min(row, rows.length - 1));
        col = Math.max(min, Math.min(col, max));
        this._setSsCursor(row, col);
    }

    _cursorCell() {
        if (!this.state.ssCursor) return null;
        const row = this._ssRows()[this.state.ssCursor.row];
        return row ? row.children[this.state.ssCursor.col] : null;
    }

    // The editable text field of the cursor cell (or null). Respects can_edit.
    _cursorEditableField() {
        const cell = this._cursorCell();
        if (!cell || !cell.dataset.editField) return null;
        const ev = this.state.events.find(e => e.id == this._ssCursorEventId());
        if (ev && ev.can_edit === false) return null;
        return cell.dataset.editField;
    }

    // The portaled menu belonging to an open dropdown wrapper.
    _openMenuFor(wrapper) {
        return Array.from(document.querySelectorAll('.schedule-dropdown-menu'))
            .find(m => m._originalParent === wrapper) || wrapper.querySelector('.schedule-dropdown-menu');
    }

    // Keyboard control for an OPEN inline/status dropdown: arrows move the
    // highlight, Enter picks (which PATCHes + closes), Escape closes.
    _dropdownMenuKeys(event, wrapper) {
        const menu = this._openMenuFor(wrapper);
        const opts = menu ? Array.from(menu.querySelectorAll('.schedule-dropdown-option')) : [];
        const key = event.key;
        if (key === 'Escape') { event.preventDefault(); this.closeAllDropdowns(); return true; }
        if (!opts.length) return false;
        let idx = opts.findIndex(o => o.classList.contains('kb-active'));
        if (idx === -1) idx = opts.findIndex(o => o.classList.contains('selected'));
        if (key === 'ArrowDown' || key === 'ArrowUp') {
            event.preventDefault();
            if (idx >= 0) opts[idx].classList.remove('kb-active');
            idx = idx === -1 ? 0
                : (key === 'ArrowDown' ? Math.min(idx + 1, opts.length - 1) : Math.max(idx - 1, 0));
            opts[idx].classList.add('kb-active');
            opts[idx].scrollIntoView({ block: 'nearest' });
            return true;
        }
        if (key === 'Enter') {
            event.preventDefault();
            (opts[idx === -1 ? 0 : idx]).click(); // selects + PATCHes + closes
            return true;
        }
        return false;
    }

    // Handle a key in spreadsheet view. Returns true if it was consumed.
    _handleSpreadsheetKeys(event) {
        const key = event.key;
        const t = event.target;
        // While the floating editor is open, its own listeners own the keys.
        if (t.classList && t.classList.contains('ss-cell-editor')) return false;
        // Don't hijack text editing elsewhere (search box still drives the grid).
        if ((t.tagName === 'INPUT' || t.tagName === 'TEXTAREA') && t !== this.elements.searchInput) {
            return false;
        }

        // Ctrl/Cmd+Z — undo the last inline text edit.
        if ((event.ctrlKey || event.metaKey) && (key === 'z' || key === 'Z') && !event.shiftKey) {
            event.preventDefault();
            this._undoSpreadsheetEdit();
            return true;
        }

        // An open dropdown owns the keyboard (arrow to move, Enter to pick).
        const openDd = document.querySelector(
            '.schedule-cell-dropdown-wrapper.open, .schedule-status-dropdown-wrapper.open');
        if (openDd) return this._dropdownMenuKeys(event, openDd);

        // Typing a printable character starts editing an editable text cell.
        if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
            if (this._cursorEditableField()) {
                event.preventDefault();
                this._beginCellEdit(key);
                return true;
            }
            return false; // let single-key shortcuts (e.g. 'f') run
        }

        switch (key) {
            case 'ArrowUp':
            case 'ArrowDown':
            case 'ArrowLeft':
            case 'ArrowRight': {
                const dRow = key === 'ArrowDown' ? 1 : key === 'ArrowUp' ? -1 : 0;
                const dCol = key === 'ArrowRight' ? 1 : key === 'ArrowLeft' ? -1 : 0;
                // Shift + Left/Right swaps the All Events / Undated tabs.
                if (event.shiftKey && dCol !== 0) {
                    event.preventDefault();
                    this.switchTab(this.state.activeTab === 'all' ? 'undated' : 'all');
                    return true;
                }
                // Ctrl/Cmd + Arrow jumps to the edge (Excel-style); plain Arrow
                // moves one cell.
                event.preventDefault();
                this._moveSsCursor(dRow, dCol, event.ctrlKey || event.metaKey);
                return true;
            }
            case 'Enter': return this._handleSpreadsheetEnter(event);
            case 'Escape':
                if (this.state.ssCursor) { this._clearSsCursor(); event.preventDefault(); return true; }
                return false;
        }
        return false;
    }

    // Enter is context-sensitive on the active cell: contact/org cells open the
    // editing modal to Involved Parties; dropdown cells open for keyboard pick;
    // editable text cells start editing; anything else opens the editing modal.
    _handleSpreadsheetEnter(event) {
        const cell = this._cursorCell();
        const id = this._ssCursorEventId();
        if (!cell || !id) return false;

        // Contact/org cells → Involved Parties; staff cell → Staff & Review.
        if (cell.classList.contains('col-record')) {
            event.preventDefault();
            this._openEventToTab(id, 'involved-parties');
            return true;
        }
        if (cell.dataset.openTab) {
            event.preventDefault();
            this._openEventToTab(id, cell.dataset.openTab);
            return true;
        }

        const dd = cell.querySelector(
            '.schedule-cell-dropdown-wrapper:not(.read-only), .schedule-status-dropdown-wrapper:not(.read-only)');
        if (dd) {
            event.preventDefault();
            const trigger = dd.querySelector('.schedule-cell-dropdown-select, .schedule-card-status-select');
            trigger?.click(); // opens + portals the menu
            const menu = this._openMenuFor(dd);
            const sel = menu && (menu.querySelector('.schedule-dropdown-option.selected')
                || menu.querySelector('.schedule-dropdown-option'));
            if (sel) sel.classList.add('kb-active');
            return true;
        }

        if (this._cursorEditableField()) {
            event.preventDefault();
            this._beginCellEdit();
            return true;
        }

        event.preventDefault();
        this.handleEventDoubleClick(id);
        return true;
    }

    // Open the editing modal straight to a given tab ('involved-parties',
    // 'staff-review', 'event-details').
    _openEventToTab(eventId, tab) {
        if (typeof window.openEventEditingModal === 'function') {
            window.openEventEditingModal(eventId, { initialTab: tab });
        } else {
            this.handleEventDoubleClick(eventId);
        }
    }

    // ----- Inline text-cell editing (Excel-style) ----------------------------

    _beginCellEdit(initialChar = null) {
        const cell = this._cursorCell();
        const field = this._cursorEditableField();
        if (!cell || !field) return;
        if (this._ssEditing) this._commitCellEdit();
        const eventId = this._ssCursorEventId();
        const ev = this.state.events.find(e => e.id == eventId);
        const currentVal = ev ? (ev[field] || '') : '';

        // A floating editor that opens OVER the cell (and grows) so the whole
        // value is visible — not clipped to the cell width.
        const editor = document.createElement('textarea');
        editor.className = 'ss-cell-editor';
        editor.value = initialChar != null ? initialChar : currentVal;
        document.body.appendChild(editor);
        cell.classList.add('ss-editing');

        const rect = cell.getBoundingClientRect();
        const width = Math.min(Math.max(rect.width, 360), 560);
        let left = rect.left;
        if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - 8 - width);
        editor.style.left = `${left}px`;
        editor.style.top = `${rect.top}px`;
        editor.style.width = `${width}px`;
        editor.style.minHeight = `${rect.height}px`;
        const autosize = () => {
            editor.style.height = 'auto';
            editor.style.height = `${Math.min(editor.scrollHeight + 2, 300)}px`;
            editor.style.overflowY = editor.scrollHeight > 300 ? 'auto' : 'hidden';
        };
        autosize();
        editor.focus();
        if (initialChar != null) editor.setSelectionRange(editor.value.length, editor.value.length);
        else editor.select();

        this._ssEditing = { cell, field, eventId, originalValue: currentVal, editor };
        editor.addEventListener('input', autosize);
        editor.addEventListener('keydown', (e) => {
            e.stopPropagation();
            // Enter commits; Shift+Enter inserts a newline (for long descriptions).
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._commitCellEdit('down'); }
            else if (e.key === 'Escape') { e.preventDefault(); this._cancelCellEdit(); }
            else if (e.key === 'Tab') { e.preventDefault(); this._commitCellEdit(e.shiftKey ? 'left' : 'right'); }
        });
        editor.addEventListener('blur', () => {
            if (this._ssEditing && this._ssEditing.editor === editor) this._commitCellEdit();
        });
    }

    _commitCellEdit(moveDir = null) {
        const editing = this._ssEditing;
        if (!editing) return;
        this._ssEditing = null;
        const newVal = editing.editor ? editing.editor.value : editing.originalValue;
        if (editing.editor && editing.editor.parentNode) editing.editor.remove();
        editing.cell.classList.remove('ss-editing');
        editing.cell.innerHTML = this._cellText(newVal);

        if (newVal !== editing.originalValue) {
            const idx = this.state.events.findIndex(e => e.id == editing.eventId);
            if (idx !== -1) this.state.events[idx][editing.field] = newVal;
            this._pushUndo({ eventId: editing.eventId, field: editing.field, oldValue: editing.originalValue });
            this._patchField(editing.eventId, editing.field, newVal, editing.originalValue, editing.cell);
        }
        this._applySsCursorHighlight();
        this._applySpreadsheetSpill();
        if (moveDir === 'down') this._moveSsCursor(1, 0, false);
        else if (moveDir === 'right') this._moveSsCursor(0, 1, false);
        else if (moveDir === 'left') this._moveSsCursor(0, -1, false);
    }

    _cancelCellEdit() {
        const editing = this._ssEditing;
        if (!editing) return;
        this._ssEditing = null;
        if (editing.editor && editing.editor.parentNode) editing.editor.remove();
        editing.cell.classList.remove('ss-editing');
        this._applySsCursorHighlight();
    }

    async _patchField(eventId, field, value, oldValue, cell) {
        try {
            const r = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ [field]: value }),
                credentials: 'same-origin'
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
        } catch (e) {
            console.error(`Failed to update ${field}:`, e);
            const idx = this.state.events.findIndex(ev => ev.id == eventId);
            if (idx !== -1) this.state.events[idx][field] = oldValue;
            if (cell) cell.innerHTML = this._cellText(oldValue);
            this._applySpreadsheetSpill();
        }
    }

    _pushUndo(entry) {
        if (!this._ssUndo) this._ssUndo = [];
        this._ssUndo.push(entry);
        if (this._ssUndo.length > 50) this._ssUndo.shift();
    }

    _undoSpreadsheetEdit() {
        if (!this._ssUndo || !this._ssUndo.length) return;
        const { eventId, field, oldValue } = this._ssUndo.pop();
        const idx = this.state.events.findIndex(e => e.id == eventId);
        const newer = idx !== -1 ? this.state.events[idx][field] : null;
        if (idx !== -1) this.state.events[idx][field] = oldValue;
        const row = this._ssRows().find(r => r.dataset.eventId == eventId);
        const cell = row && row.querySelector(`td[data-edit-field="${field}"]`);
        if (cell) cell.innerHTML = this._cellText(oldValue);
        this._patchField(eventId, field, oldValue, newer, cell);
        this._applySpreadsheetSpill();
    }

    // ----- Truncated text spilling into empty right-neighbour cells ----------

    _applySpreadsheetSpill() {
        try {
            // Batched in three phases (reset → measure → apply) so we don't
            // thrash layout reading scrollWidth between per-cell style writes.
            const cells = [];
            for (const row of this._ssRows()) {
                const tds = Array.from(row.children);
                tds.forEach((td, i) => {
                    const span = td.querySelector(':scope > .ss-cell-content');
                    if (!span) return;
                    td.classList.remove('ss-spill');     // reset (write)
                    span.style.maxWidth = '';
                    cells.push({ td, span, tds, i });
                });
            }
            const toSpill = [];
            for (const c of cells) {                       // measure (reads)
                const own = c.span.clientWidth;
                if (c.span.scrollWidth <= own + 1) continue; // not truncated
                // Sum the widths of consecutive empty cells to the right; the
                // text may extend across them but no further (so it never
                // overlaps a neighbour that has content).
                let extra = 0;
                for (let j = c.i + 1; j < c.tds.length; j++) {
                    const right = c.tds[j];
                    // "Empty" = no visible text. (A cell may wrap an empty
                    // .ss-cell-content span, so test text, not child elements.)
                    if (right.textContent.trim() !== '') break;
                    extra += right.getBoundingClientRect().width;
                }
                if (extra > 2) toSpill.push({ td: c.td, span: c.span, max: own + extra });
            }
            for (const s of toSpill) {                     // apply (writes)
                s.td.classList.add('ss-spill');
                s.span.style.maxWidth = `${Math.round(s.max)}px`;
            }
        } catch (e) { /* spill is purely cosmetic */ }
    }

    // Bind the editable choice dropdowns (type/format/timezone) in the spreadsheet.
    // Mirrors the status dropdown: portaled menu, inline PATCH, optimistic update.
    bindCellDropdowns() {
        const wrappers = this.elements.eventList.querySelectorAll('.schedule-cell-dropdown-wrapper');
        wrappers.forEach(wrapper => {
            const trigger = wrapper.querySelector('.schedule-cell-dropdown-select');
            const menu = wrapper.querySelector('.schedule-dropdown-menu');
            const options = wrapper.querySelectorAll('.schedule-dropdown-option');
            if (!trigger || !menu) return;

            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                if (wrapper.classList.contains('read-only')) return;
                if (wrapper.classList.contains('open')) { this.closeDropdown(wrapper); return; }
                this.closeAllDropdowns();
                this._openPortaledMenu(wrapper, trigger, menu);
            });

            options.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const value = option.dataset.value;
                    const field = wrapper.dataset.field;
                    const eventId = wrapper.dataset.eventId;
                    const textEl = wrapper.querySelector('.schedule-cell-dropdown-text');
                    if (textEl) textEl.textContent = option.textContent;
                    options.forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');
                    this.closeDropdown(wrapper);
                    this.handleFieldChangeFromDropdown(eventId, field, value, wrapper);
                });
            });
        });
    }

    // Portal a dropdown menu to <body> and position it relative to its trigger.
    // Shared by the spreadsheet choice dropdowns (status keeps its own copy).
    _openPortaledMenu(wrapper, trigger, menu) {
        document.body.appendChild(menu);
        const triggerRect = trigger.getBoundingClientRect();
        menu.style.visibility = 'hidden';
        menu.style.display = 'block';
        const menuWidth = menu.offsetWidth;
        const menuHeight = menu.offsetHeight;
        const vh = window.innerHeight, vw = window.innerWidth;
        const spaceBelow = vh - triggerRect.bottom, spaceAbove = triggerRect.top;
        let left = triggerRect.left + (triggerRect.width / 2) - (menuWidth / 2);
        if (left < 8) left = 8;
        if (left + menuWidth > vw - 8) left = vw - menuWidth - 8;
        let top = (spaceBelow >= menuHeight || spaceBelow >= spaceAbove)
            ? triggerRect.bottom : triggerRect.top - menuHeight;
        if (top + menuHeight > vh - 8) top = vh - menuHeight - 8;
        if (top < 8) top = 8;
        menu.style.top = top + 'px';
        menu.style.left = left + 'px';
        menu.style.visibility = '';
        menu._originalParent = wrapper;
        wrapper.classList.add('open');
    }

    // PATCH an event choice field (type/format/timezone) from the spreadsheet,
    // optimistically updating local state and rolling back on failure.
    async handleFieldChangeFromDropdown(eventId, field, value, wrapper) {
        const idx = this.state.events.findIndex(e => e.id == eventId);
        const prev = idx !== -1 ? this.state.events[idx][field] : undefined;
        if (idx !== -1) this.state.events[idx][field] = value;
        if (this.state.detailPanelEventData && this.state.detailPanelEventId == eventId) {
            this.state.detailPanelEventData[field] = value;
        }

        try {
            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ [field]: value }),
                credentials: 'same-origin'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
        } catch (error) {
            console.error(`Error updating ${field}:`, error);
            // Rollback local state + cell UI.
            if (idx !== -1) this.state.events[idx][field] = prev;
            const textEl = wrapper.querySelector('.schedule-cell-dropdown-text');
            if (textEl) textEl.textContent = this._choiceLabel(field, prev) || '—';
            wrapper.querySelectorAll('.schedule-dropdown-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === prev);
            });
        }
    }

    // =========================================================================
    // Event Handling
    // =========================================================================

    bindEventClicks() {
        // Bind edit/view buttons — these open the modal immediately, bypassing click delay
        const editBtns = this.elements.eventList.querySelectorAll('.schedule-card-edit-btn');
        editBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const eventId = btn.dataset.eventId;
                if (!eventId) return;
                this.handleEventDoubleClick(eventId);
            });
        });

        const eventCards = this.elements.eventList.querySelectorAll('.schedule-card');
        eventCards.forEach(card => {
            // Single click — immediately select event in detail panel
            card.addEventListener('click', (e) => {
                // Don't trigger if clicking on status dropdown or edit button
                if (e.target.closest('.schedule-status-dropdown-wrapper') || e.target.closest('.schedule-card-status-select') || e.target.closest('.schedule-card-edit-btn')) {
                    return;
                }
                const eventId = card.dataset.eventId;
                if (!eventId) return;
                this.handleEventSingleClick(eventId);
            });

            // Double click — open edit modal
            card.addEventListener('dblclick', (e) => {
                if (e.target.closest('.schedule-status-dropdown-wrapper') || e.target.closest('.schedule-card-status-select') || e.target.closest('.schedule-card-edit-btn')) {
                    return;
                }
                const eventId = card.dataset.eventId;
                if (!eventId) return;
                this.handleEventDoubleClick(eventId);
            });
        });

        // Re-apply active card highlight after re-render
        if (this.state.detailPanelEventId) {
            this.updateActiveCard(this.state.detailPanelEventId);
        }
    }

    bindStatusDropdowns() {
        const wrappers = this.elements.eventList.querySelectorAll('.schedule-status-dropdown-wrapper');
        wrappers.forEach(wrapper => {
            const trigger = wrapper.querySelector('.schedule-card-status-select');
            const menu = wrapper.querySelector('.schedule-dropdown-menu');
            const options = wrapper.querySelectorAll('.schedule-dropdown-option');

            // Toggle dropdown on trigger click
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();

                // Don't open dropdown on read-only cards or read-only spreadsheet wrappers
                if (wrapper.closest('.schedule-card.read-only') || wrapper.classList.contains('read-only')) {
                    return;
                }

                // If already open, just close
                if (wrapper.classList.contains('open')) {
                    this.closeDropdown(wrapper);
                    return;
                }

                // Close all other dropdowns first
                this.closeAllDropdowns();

                // Move menu to body to avoid transform containment issues
                document.body.appendChild(menu);

                // Get trigger position in viewport
                const triggerRect = trigger.getBoundingClientRect();

                // Measure menu
                menu.style.visibility = 'hidden';
                menu.style.display = 'block';
                const menuWidth = menu.offsetWidth;
                const menuHeight = menu.offsetHeight;

                const viewportHeight = window.innerHeight;
                const viewportWidth = window.innerWidth;
                const spaceBelow = viewportHeight - triggerRect.bottom;
                const spaceAbove = triggerRect.top;

                // Calculate left position (centered on trigger)
                let left = triggerRect.left + (triggerRect.width / 2) - (menuWidth / 2);
                // Keep within viewport
                if (left < 8) left = 8;
                if (left + menuWidth > viewportWidth - 8) left = viewportWidth - menuWidth - 8;

                // Position menu directly below trigger (no gap) by default
                let top;
                if (spaceBelow >= menuHeight || spaceBelow >= spaceAbove) {
                    // Show below - menu top touches trigger bottom
                    top = triggerRect.bottom;
                } else {
                    // Show above - menu bottom touches trigger top
                    top = triggerRect.top - menuHeight;
                }

                // Clamp to viewport
                if (top + menuHeight > viewportHeight - 8) {
                    top = viewportHeight - menuHeight - 8;
                }
                if (top < 8) {
                    top = 8;
                }

                // Apply position and show
                menu.style.top = top + 'px';
                menu.style.left = left + 'px';
                menu.style.visibility = '';

                // Store reference to parent for closing
                menu._originalParent = wrapper;

                wrapper.classList.add('open');
            });

            // Handle option selection
            options.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const newStatus = option.dataset.value;
                    const eventId = wrapper.dataset.eventId;

                    // Update trigger text
                    const triggerText = wrapper.querySelector('.schedule-status-text');
                    triggerText.textContent = option.textContent;

                    // Update selected state
                    options.forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');

                    // Close dropdown properly (moves menu back)
                    this.closeDropdown(wrapper);

                    // Handle status change
                    this.handleStatusChangeFromDropdown(eventId, newStatus, wrapper);
                });
            });
        });

        // Close dropdowns when clicking outside
        document.addEventListener('click', () => {
            this.closeAllDropdowns();
        });
    }

    /**
     * Close a single dropdown and move menu back to its parent
     */
    closeDropdown(wrapper) {
        wrapper.classList.remove('open');
        // Find the menu that belongs to this dropdown (might be in body)
        const allMenus = document.querySelectorAll('.schedule-dropdown-menu');
        allMenus.forEach(menu => {
            if (menu._originalParent === wrapper) {
                menu.style.display = '';
                menu.style.top = '';
                menu.style.left = '';
                menu.style.visibility = '';
                wrapper.appendChild(menu);
                menu._originalParent = null;
            }
        });
    }

    /**
     * Close all open dropdowns
     */
    closeAllDropdowns() {
        const openWrappers = document.querySelectorAll(
            '.schedule-status-dropdown-wrapper.open, .schedule-cell-dropdown-wrapper.open');
        openWrappers.forEach(wrapper => {
            this.closeDropdown(wrapper);
        });
        // Also close any orphaned menus in the body
        const bodyMenus = document.querySelectorAll('body > .schedule-dropdown-menu');
        bodyMenus.forEach(menu => {
            if (menu._originalParent) {
                menu.style.display = '';
                menu.style.top = '';
                menu.style.left = '';
                menu.style.visibility = '';
                menu._originalParent.appendChild(menu);
                menu._originalParent.classList.remove('open');
                menu._originalParent = null;
            }
        });
    }

    /**
     * Close the detail panel status dropdown and move menu back
     */
    closeDetailStatusDropdown(wrapper, menu) {
        wrapper.classList.remove('open');
        if (menu.parentNode === document.body) {
            menu.style.display = '';
            menu.style.top = '';
            menu.style.left = '';
            menu.style.visibility = '';
            wrapper.appendChild(menu);
        }
    }

    /**
     * Handle status change from detail panel dropdown
     */
    async handleDetailPanelStatusChange(eventId, newStatus) {
        const newStatusClass = `status-${newStatus.toLowerCase().replace(/\s+/g, '_')}`;

        // Update the card in the event list
        const card = this.elements.eventList?.querySelector(`.schedule-card[data-event-id="${eventId}"]`);
        if (card) {
            card.classList.forEach(cls => { if (cls.startsWith('status-')) card.classList.remove(cls); });
            card.classList.add(newStatusClass);
            const cardText = card.querySelector('.schedule-status-text');
            if (cardText) cardText.textContent = this.getStatusLabel(newStatus);
        }

        // Update local state
        const eventIndex = this.state.events.findIndex(e => e.id == eventId);
        if (eventIndex !== -1) this.state.events[eventIndex].status = newStatus;
        if (this.state.detailPanelEventData) this.state.detailPanelEventData.status = newStatus;

        // PATCH API
        try {
            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ status: newStatus }),
                credentials: 'same-origin'
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            if (this.state.sortBy === '-modified') {
                setTimeout(() => { this.state.page = 1; this.fetchEvents(); }, 300);
            }
        } catch (error) {
            console.error('Failed to update status from detail panel:', error);
        }
    }

    /**
     * Handle status change from custom dropdown menu
     */
    async handleStatusChangeFromDropdown(eventId, newStatus, wrapperElement) {
        console.log('Changing status for event:', eventId, 'to:', newStatus);

        // Get the card element (or spreadsheet row)
        const card = wrapperElement.closest('.schedule-card') || wrapperElement.closest('tr[data-event-id]');

        // Store old status for rollback
        const oldStatusClass = Array.from(card.classList).find(c => c.startsWith('status-'));
        const oldStatus = this.state.events.find(e => e.id == eventId)?.status;

        // Optimistically update UI
        // Remove old status class from card
        card.classList.forEach(cls => {
            if (cls.startsWith('status-')) {
                card.classList.remove(cls);
            }
        });
        // Add new status class to card
        const newStatusClass = `status-${newStatus.toLowerCase().replace(/\s+/g, '_')}`;
        card.classList.add(newStatusClass);

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ status: newStatus }),
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            console.log('Status updated successfully');

            // Update the event in our local state
            const eventIndex = this.state.events.findIndex(e => e.id == eventId);
            if (eventIndex !== -1) {
                this.state.events[eventIndex].status = newStatus;
            }

            // Update detail panel status badge if showing this event
            if (this.state.detailPanelEventId == eventId) {
                const badge = document.getElementById('detail-panel-status-badge');
                if (badge) {
                    badge.className = `detail-panel-status ${newStatusClass}`;
                    const textEl = badge.querySelector('.detail-panel-status-text');
                    if (textEl) {
                        textEl.textContent = this.getStatusLabel(newStatus);
                    } else {
                        badge.textContent = this.getStatusLabel(newStatus);
                    }
                }
                if (this.state.detailPanelEventData) {
                    this.state.detailPanelEventData.status = newStatus;
                }
            }

            // If sorting by "Recently Modified", re-fetch to get correct order
            if (this.state.sortBy === '-modified') {
                setTimeout(() => {
                    this.state.page = 1;
                    this.fetchEvents();
                }, 300);
            }

        } catch (error) {
            console.error('Error updating status:', error);

            // Rollback UI on error
            card.classList.remove(newStatusClass);
            if (oldStatusClass) {
                card.classList.add(oldStatusClass);
            }

            // Reset trigger text to previous value
            if (oldStatus) {
                const triggerText = wrapperElement.querySelector('.schedule-status-text');
                const oldChoice = this.statusChoices.find(c => this.normalizeChoice(c).value === oldStatus);
                if (triggerText && oldChoice) {
                    triggerText.textContent = this.normalizeChoice(oldChoice).label;
                }
                // Reset selected state in menu
                wrapperElement.querySelectorAll('.schedule-dropdown-option').forEach(opt => {
                    opt.classList.toggle('selected', opt.dataset.value === oldStatus);
                });
            }

            // Show error to user
            alert('Failed to update status. Please try again.');
        }
    }

    // =========================================================================
    // Single / Double Click Handlers + Detail Panel
    // =========================================================================

    handleEventSingleClick(eventId) {
        // A click focuses the first action button (so Enter opens the event) but
        // *silently* — no visible focus ring until the user presses Tab or an
        // arrow. Keyboard navigation focuses it with the ring shown.
        if (this.state.detailPanelEventId == eventId) {
            this.focusFirstPanelAction({ silent: true });
            return;
        }
        this.openDetailPanel(eventId, { focusAction: true, silentFocus: true });
    }

    handleEventDoubleClick(eventId) {
        // If we have cached data for this event and user cannot edit, fall back to panel
        if (this.state.detailPanelEventData &&
            this.state.detailPanelEventData.id == eventId &&
            this.state.detailPanelEventData.can_edit === false) {
            this.openDetailPanel(eventId);
            return;
        }

        // Open full editing modal
        if (typeof window.openEventEditingModal === 'function') {
            window.openEventEditingModal(eventId);
        } else {
            console.warn('openEventEditingModal not available, navigating to page');
            window.location.href = `${this.config.eventEditingUrl}${eventId}/`;
        }
    }

    async openDetailPanel(eventId, options = {}) {
        // The spreadsheet view never opens the side panel — it uses Excel-style
        // cell navigation. Guard here so programmatic callers (tab restore,
        // refresh) can't pop it open behind the grid.
        if (this.state.viewMode === 'spreadsheet') return;
        const content = this.elements.detailPanelContent;
        if (!content) return;

        // Update state
        this.state.detailPanelEventId = eventId;

        // Mark panel as having an event selected (for responsive styles)
        this.elements.detailPanel?.classList.add('has-event');

        // Highlight the card
        this.updateActiveCard(eventId);

        // If we've loaded this event before, render it immediately from cache
        // (no skeleton flash) and refresh in the background. Otherwise show the
        // skeleton placeholder while the event loads.
        const cachedData = this._detailCache && this._detailCache[eventId];
        if (cachedData) {
            this.state.detailPanelEventData = cachedData;
            this.renderDetailPanel(cachedData);
            if (options.focusAction) {
                this.focusFirstPanelAction({ silent: options.silentFocus });
            }
        } else {
            content.innerHTML = this.renderDetailPanelSkeleton();
        }

        // On narrow screens, auto-close filter sidebar
        if (window.innerWidth < 1280 && this.state.sidebarOpen) {
            this.closeSidebar();
        }

        // Abort any in-flight overlap request
        if (this._overlapAbortController) {
            this._overlapAbortController.abort();
        }
        this._overlapAbortController = new AbortController();

        // Fetch event data and overlaps in parallel to reduce latency
        const headers = { 'Accept': 'application/json', 'X-CSRFToken': this.config.csrfToken };
        const overlapPromise = fetch(`${this.config.apiUrl}${eventId}/overlaps/`, {
            headers,
            signal: this._overlapAbortController.signal
        }).then(r => r.ok ? r.json() : []).catch(() => []);

        try {
            const response = await fetch(`${this.config.apiUrl}${eventId}/`, { headers });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const eventData = await response.json();

            // Cache the loaded event so re-selecting it later (e.g. swapping
            // tabs back and forth) renders instantly without a skeleton.
            (this._detailCache || (this._detailCache = {}))[eventId] = eventData;

            // Guard: if user clicked another event during fetch, abort render
            if (this.state.detailPanelEventId != eventId) return;

            this.state.detailPanelEventData = eventData;

            // Add to recently viewed (session only)
            this.addToRecentlyViewed(eventData);

            this.renderDetailPanel(eventData);

            // Selection asked for focus on the first action — silently for a
            // click (no ring), with the ring for keyboard navigation.
            if (options.focusAction && this.state.detailPanelEventId == eventId) {
                this.focusFirstPanelAction({ silent: options.silentFocus });
            }

            // Overlap data likely already resolved — render immediately
            const overlaps = await overlapPromise;
            if (overlaps.length && this.state.detailPanelEventId == eventId) {
                this.renderOverlapSection(eventData, overlaps);
            }
        } catch (error) {
            // A 404 means the event no longer exists in the active set (it was
            // deleted / moved to Deleted Events). Close the panel quietly rather
            // than showing a scary error for a stale selection.
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
                    </div>
                    <div class="detail-panel-body" style="display:flex;align-items:center;justify-content:center;color:var(--text-secondary);">
                        Failed to load event details.
                    </div>`;
            }
        }
    }

    renderDetailPanel(eventData) {
        const content = this.elements.detailPanelContent;
        if (!content) return;

        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        // Format date
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

        // Format time
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
                        return timeStr ? `Today at ${timeStr} \u2014 ${remaining}` : `Today \u2014 ${remaining}`;
                    }
                    return timeStr ? `Today at ${timeStr}` : 'Today';
                }
                if (isTomorrow) return timeStr ? `Tomorrow at ${timeStr}` : 'Tomorrow';
                if (diffDays > 0 && diffDays <= 14) return `In ${diffDays} day${diffDays === 1 ? '' : 's'}`;
                if (diffDays > 14 && diffDays <= 60) { const w = Math.round(diffDays / 7); return `In ${w} week${w === 1 ? '' : 's'}`; }
                if (diffDays < 0 && diffDays >= -60) { const a = Math.abs(diffDays); return `${a} day${a === 1 ? '' : 's'} ago`; }
                return '';
            } catch (e) { return ''; }
        };

        // Build date/time display
        let dateTimeDisplay = '';
        if (eventData.start_date) {
            if (eventData.end_date && eventData.end_date !== eventData.start_date) {
                dateTimeDisplay = `${formatDate(eventData.start_date)} \u2013 ${formatDate(eventData.end_date)}`;
            } else {
                dateTimeDisplay = formatDate(eventData.start_date);
                if (eventData.start_time) {
                    dateTimeDisplay += ` at ${formatTime(eventData.start_time)}`;
                    if (eventData.end_time) {
                        dateTimeDisplay += ` \u2013 ${formatTime(eventData.end_time)}`;
                    }
                }
            }
        }

        const hasDateTime = !!dateTimeDisplay;
        const relativeTime = getRelativeTime();
        const hasLocation = !!(eventData.location || eventData.location_room || eventData.location_building);
        const statusClass = `status-${(eventData.status || 'received').toLowerCase().replace(/\s+/g, '_')}`;
        const statusLabel = this.getStatusLabel(eventData.status);

        // Location text
        let locationText = '';
        if (eventData.location) locationText = eventData.location;
        else {
            const parts = [eventData.location_room, eventData.location_building].filter(Boolean);
            locationText = parts.join(', ');
        }

        // Type + format line
        const typeFormatParts = [];
        if (eventData.type) typeFormatParts.push(this.getTypeLabel(eventData.type));
        if (eventData.format) {
            const formatMap = { 'in_person': 'In-Person', 'virtual': 'Virtual', 'hybrid': 'Hybrid' };
            typeFormatParts.push(formatMap[eventData.format] || eventData.format);
        }

        // Build secondary sections
        let secondaryHtml = '';

        if (eventData.description) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Description</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.description)}</span>
            </div>`;
        }

        // Assigned staff (with add button matching modal style)
        const addStaffBtn = eventData.can_edit !== false
            ? `<div class="v2-staff-dropdown-wrapper">
                    <button type="button" class="v2-add-staff-btn" id="detail-panel-add-staff">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Add Staff
                    </button>
                    <div class="v2-staff-dropdown" id="detail-panel-staff-dropdown"></div>
                </div>`
            : '';
        if (eventData.staff && eventData.staff.length > 0) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>Assigned staff</span>
                <div class="v2-readonly-staff-list" id="detail-panel-staff-list">
                    ${eventData.staff.map(s => `<span class="v2-readonly-staff-pill">${escapeHtml(s)}</span>`).join('')}
                    ${addStaffBtn}
                </div>
            </div>`;
        } else {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>Assigned staff</span>
                <div class="v2-readonly-staff-list" id="detail-panel-staff-list">
                    ${addStaffBtn}
                </div>
            </div>`;
        }

        if (eventData.tags && eventData.tags.length > 0) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>Tags</span>
                <div class="v2-readonly-tags">
                    ${eventData.tags.map(t => `<span class="v2-readonly-tag">${escapeHtml(t)}</span>`).join('')}
                </div>
            </div>`;
        }

        if (eventData.poc_name || eventData.poc_email || eventData.poc_phone) {
            const pocParts = [eventData.poc_name, eventData.poc_email, eventData.poc_phone].filter(Boolean);
            secondaryHtml += `<div class="v2-readonly-section inline-section">
                <span class="v2-readonly-label">Contact</span>
                <span class="v2-readonly-value">${escapeHtml(pocParts.join(' \u00b7 '))}</span>
            </div>`;
        }

        if (eventData.participants && eventData.participants.length > 0) {
            const participantNames = eventData.participants.map(p => typeof p === 'string' ? p : (p.name || p.title || '')).filter(Boolean);
            if (participantNames.length <= 3) {
                // Inline for ≤3 participants
                secondaryHtml += `<div class="v2-readonly-section inline-section">
                    <span class="v2-readonly-label">Participants</span>
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

        if (eventData.notes) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Notes</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.notes)}</span>
            </div>`;
        }

        // Missing-fields dropdown removed per design — the editing modal
        // surfaces empty fields when the user actually starts editing.
        const missingHtml = '';

        // Review routing section (read-only table in body)
        let reviewHtml = '';
        if (eventData.approval_routing && eventData.approval_routing.stages && eventData.approval_routing.stages.length > 0) {
            reviewHtml = this._buildReviewTableHtml(eventData);
        }

        // Footer buttons — Edit (gray), Calendar/Copy/Email (white), all stretch to fill
        let footerHtml = '';
        // Edit first (only if can_edit)
        if (eventData.can_edit !== false) {
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-edit" id="detail-panel-btn-edit">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                <span class="btn-label">Edit</span>
            </button>`;
        }
        // Calendar (white)
        if (eventData.start_date) {
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-primary" id="detail-panel-btn-calendar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                <span class="btn-label">Calendar</span>
            </button>`;
        }
        // Email (white, only if can_edit AND has emails)
        const hasEmails = eventData.has_original_email || (eventData.attached_emails_data && eventData.attached_emails_data.length > 0);
        if (eventData.can_edit !== false && hasEmails) {
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-email" id="detail-panel-btn-email" title="Show email">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                <span class="btn-label">Show Email</span>
            </button>`;
        }
        // (Copy moved to more menu)

        content.innerHTML = `
            <div class="detail-panel-header">
                <div class="detail-panel-header-left">
                    <div class="detail-panel-title">${escapeHtml(eventData.title) || 'Untitled Event'}</div>
                    <div class="detail-panel-org-status">
                        ${eventData.group ? (() => {
                            const primaryOrg = (eventData.organizations || []).find(o => o.is_primary) || (eventData.organizations || [])[0] || null;
                            const orgId = primaryOrg ? primaryOrg.id : '';
                            return orgId
                                ? `<span class="detail-panel-org detail-panel-org-link" data-org-id="${orgId}" role="button" tabindex="0" title="View organization">${escapeHtml(eventData.group)}</span>`
                                : `<span class="detail-panel-org">${escapeHtml(eventData.group)}</span>`;
                        })() : ''}
                        ${eventData.can_edit !== false ? `
                        <div class="detail-panel-status-dropdown-wrapper" id="detail-panel-status-wrapper" data-event-id="${eventData.id}">
                            <div class="detail-panel-status ${statusClass}" id="detail-panel-status-badge" tabindex="0" role="button">
                                <span class="detail-panel-status-text">${statusLabel}</span>
                            </div>
                            <div class="detail-panel-dropdown-menu" id="detail-panel-dropdown-menu">
                                ${this.statusChoices.map(choice => {
                                    const { value, label, is_active } = this.normalizeChoice(choice);
                                    const selectedClass = value === eventData.status ? 'selected' : '';
                                    const inactiveClass = !is_active ? 'inactive' : '';
                                    const optionStatusClass = `status-${value.toLowerCase().replace(/\s+/g, '_')}`;
                                    const displayLabel = !is_active ? `${label} (Inactive)` : label;
                                    return `<div class="schedule-dropdown-option ${selectedClass} ${inactiveClass} ${optionStatusClass}" data-value="${value}">${displayLabel}</div>`;
                                }).join('')}
                            </div>
                        </div>` : `
                        <span class="detail-panel-status ${statusClass}" id="detail-panel-status-badge">${statusLabel}</span>`}
                    </div>
                </div>
                <div class="detail-panel-header-actions">
                    <div class="detail-panel-more-wrapper">
                        <button class="detail-panel-more-btn" id="detail-panel-more-btn" aria-label="More options" title="More options">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="5" r="1"></circle>
                                <circle cx="12" cy="12" r="1"></circle>
                                <circle cx="12" cy="19" r="1"></circle>
                            </svg>
                        </button>
                        <div class="detail-panel-more-menu" id="detail-panel-more-menu">
                            <button class="detail-panel-more-menu-item" id="detail-panel-btn-copy">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                Copy Details
                            </button>
                            <button class="detail-panel-more-menu-item" id="detail-panel-btn-export">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                                Export Word
                            </button>
                            ${eventData.can_edit !== false ? `
                            <button class="detail-panel-more-menu-item detail-panel-more-menu-item-danger" id="detail-panel-btn-delete">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                                Delete
                            </button>` : ''}
                        </div>
                    </div>
                    <button class="detail-panel-close" id="detail-panel-close-btn" aria-label="Deselect" title="Deselect event">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="detail-panel-body">
                <div class="v2-readonly-primary">
                    ${hasDateTime ? `<div class="v2-readonly-datetime">${dateTimeDisplay}${relativeTime ? ` <span class="v2-readonly-relative-time-inline">\u00b7 ${relativeTime}</span>` : ''}</div>` : (relativeTime ? `<div class="v2-readonly-datetime"><span class="v2-readonly-relative-time-inline">${relativeTime}</span></div>` : '')}
                    ${hasLocation ? `<div class="v2-readonly-location">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                            <circle cx="12" cy="10" r="3"></circle>
                        </svg>
                        ${escapeHtml(locationText)}${typeFormatParts.length > 0 ? ` <span class="v2-readonly-type-format-inline">\u00b7 ${typeFormatParts.join(' \u00b7 ')}</span>` : ''}
                    </div>` : (typeFormatParts.length > 0 ? `<div class="v2-readonly-type-format">${typeFormatParts.join(' \u00b7 ')}</div>` : '')}
                </div>
                <div class="v2-readonly-secondary">
                    ${secondaryHtml}
                    ${this._buildAttachmentsHtml(eventData)}
                </div>
                ${reviewHtml}
                ${missingHtml}
            </div>
            <div class="detail-panel-footer">
                ${footerHtml}
            </div>
        `;

        this.bindDetailPanelEvents(eventData);
    }

    /**
     * Build the attachments section HTML for the Events-page detail panel.
     *
     * Shows the files attached to the event (each a streamed, auth-checked
     * download) plus per-file replace/delete controls when the user can edit.
     * Files are added via the event editing modal, so there's no "Add file"
     * affordance here. Returns '' when the event has no attachments.
     */
    _buildAttachmentsHtml(eventData) {
        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };
        const formatSize = (bytes) => {
            if (!bytes) return '';
            if (bytes < 1024) return `${bytes} B`;
            if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
            return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        };

        const attachments = eventData.attachments || [];
        const canEdit = !!eventData.can_edit;
        if (attachments.length === 0) return '';

        let rows = '';
        attachments.forEach((att) => {
            const v = att.current_version;
            if (!v) return;
            const downloadable = v.scan_status === 'clean' || v.scan_status === 'skipped';
            let badge = '';
            if (v.scan_status === 'pending') {
                badge = `<span class="v2-attachment-badge v2-attachment-badge--scanning">Scanning…</span>`;
            } else if (v.scan_status === 'infected') {
                badge = `<span class="v2-attachment-badge v2-attachment-badge--infected">Blocked</span>`;
            }
            const versionNote = v.version_number > 1
                ? `<span class="v2-attachment-version" title="Uploaded by ${escapeHtml(v.uploaded_by_name)}">v${v.version_number}</span>` : '';
            const sizeText = formatSize(v.file_size);
            const nameHtml = downloadable
                ? `<a class="v2-attachment-name" href="${escapeHtml(v.download_url)}" download>${escapeHtml(att.original_filename)}</a>`
                : `<span class="v2-attachment-name v2-attachment-name--disabled">${escapeHtml(att.original_filename)}</span>`;

            let controls = '';
            if (canEdit) {
                controls = `<div class="v2-attachment-controls">
                    <button class="v2-attachment-btn" data-attachment-replace="${att.id}" data-tooltip="Upload new version">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    </button>
                    <button class="v2-attachment-btn v2-attachment-btn--danger" data-attachment-delete="${att.id}" data-attachment-name="${escapeHtml(att.original_filename)}" data-tooltip="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                </div>`;
            }

            rows += `<div class="v2-attachment-row">
                <svg class="v2-attachment-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                <div class="v2-attachment-info">
                    ${nameHtml}
                    <span class="v2-attachment-meta">${[sizeText, escapeHtml(att.created_by_name)].filter(Boolean).join(' · ')}</span>
                </div>
                ${versionNote}
                ${badge}
                ${controls}
            </div>`;
        });

        const replaceInputHtml = canEdit
            ? `<input type="file" id="detail-panel-attachment-replace-input" class="v2-attachment-file-input" hidden>`
            : '';

        return `<div class="v2-readonly-section">
            <span class="v2-readonly-label">Attachments</span>
            <div class="v2-attachment-list">
                ${rows}
            </div>
            ${replaceInputHtml}
        </div>`;
    }

    /** Turn a failed attachment Response into a user-facing message. */
    async _attachmentError(resp, fallback) {
        try {
            const data = await resp.json();
            return data.error || data.detail || fallback;
        } catch (e) {
            return `${fallback} (HTTP ${resp.status})`;
        }
    }

    /** Re-fetch the event's attachment list and re-render the detail panel. */
    async _refreshAttachments(eventData) {
        try {
            const resp = await fetch(`/api/events/${eventData.id}/attachments/`, {
                headers: { 'Accept': 'application/json', 'X-CSRFToken': this.config.csrfToken },
                credentials: 'same-origin',
            });
            if (resp.ok) {
                const data = await resp.json();
                eventData.attachments = data.attachments;
                if (this.state.detailPanelEventId == eventData.id) {
                    this.renderDetailPanel(eventData);
                }
            }
        } catch (e) {
            console.error('Failed to refresh attachments:', e);
        }
    }

    async _replaceAttachment(eventData, attachmentId, file) {
        const form = new FormData();
        form.append('file', file);
        try {
            const resp = await fetch(`/api/events/${eventData.id}/attachments/${attachmentId}/replace/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': this.config.csrfToken },
                credentials: 'same-origin',
                body: form,
            });
            if (!resp.ok) {
                alert(await this._attachmentError(resp, 'Replace failed.'));
                return;
            }
            await this._refreshAttachments(eventData);
        } catch (e) {
            console.error('Attachment replace failed:', e);
            alert('Replace failed.');
        }
    }

    async _deleteAttachment(eventData, attachmentId) {
        try {
            const resp = await fetch(`/api/events/${eventData.id}/attachments/${attachmentId}/`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this.config.csrfToken },
                credentials: 'same-origin',
            });
            if (!resp.ok) {
                alert(await this._attachmentError(resp, 'Delete failed.'));
                return;
            }
            await this._refreshAttachments(eventData);
        } catch (e) {
            console.error('Attachment delete failed:', e);
            alert('Delete failed.');
        }
    }

    /**
     * Show a tooltip portaled to <body> (position:fixed, top layer, pointer-
     * events:none) so it renders above all page content and never intercepts
     * clicks. Centered above the anchor and clamped to the viewport. Reuses the
     * .v2-floating-tooltip styles (loaded globally via base.html).
     */
    _showFloatingTooltip(anchorEl, text) {
        if (!anchorEl || !text) return;
        let tip = document.getElementById('v2-floating-tooltip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'v2-floating-tooltip';
            tip.className = 'v2-floating-tooltip';
            document.body.appendChild(tip);
        }
        this._floatingTooltipEl = tip;
        tip.textContent = text;
        tip.style.display = 'block';
        const a = anchorEl.getBoundingClientRect();
        const t = tip.getBoundingClientRect();
        let left = a.left + a.width / 2 - t.width / 2;
        let top = a.top - t.height - 8;
        left = Math.max(4, Math.min(left, window.innerWidth - t.width - 4));
        if (top < 4) top = a.bottom + 8; // flip below if there's no room above
        tip.style.left = `${left}px`;
        tip.style.top = `${top}px`;
        tip.classList.add('visible');
    }

    _hideFloatingTooltip() {
        const tip = this._floatingTooltipEl;
        if (tip) {
            tip.classList.remove('visible');
            tip.style.display = 'none';
        }
    }

    /**
     * Render pre-fetched overlapping events into the detail panel.
     */
    renderOverlapSection(eventData, overlaps) {
        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        const formatTime = (t) => {
            if (!t) return '';
            const [h, m] = t.split(':');
            const hour = parseInt(h, 10);
            const suffix = hour >= 12 ? ' PM' : ' AM';
            const h12 = hour % 12 || 12;
            return `${h12}:${m}${suffix}`;
        };

        const itemsHtml = overlaps.map(o => {
            const timeStr = o.start_time ? formatTime(o.start_time) + (o.end_time ? ' \u2013 ' + formatTime(o.end_time) : '') : '';
            return `<div class="overlap-item" role="button" tabindex="0" data-event-id="${o.id}" aria-label="Open ${escapeHtml(o.title)}">
                <span class="overlap-title">${escapeHtml(o.title)}</span>
                <span class="overlap-time">${timeStr}</span>
                <span class="detail-panel-status status-${o.status || 'received'}">${escapeHtml(this.getStatusLabel(o.status))}</span>
            </div>`;
        }).join('');

        const sectionHtml = `<div class="v2-readonly-section overlap-section">
            <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="13" stroke-width="3"></line><circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"></circle></svg>Overlaps with</span>
            <div class="overlap-list">${itemsHtml}</div>
        </div>`;

        // Inject into DOM: before everything in secondary (above description)
        const secondary = this.elements.detailPanelContent?.querySelector('.v2-readonly-secondary');
        if (!secondary) return;

        const temp = document.createElement('div');
        temp.innerHTML = sectionHtml;
        const overlapEl = temp.firstElementChild;

        secondary.prepend(overlapEl);

        // Bind click/keyboard handlers
        overlapEl.querySelectorAll('.overlap-item').forEach(item => {
            const handler = () => {
                const targetId = item.dataset.eventId;
                if (typeof window.openEventEditingModal === 'function') {
                    window.openEventEditingModal(targetId);
                }
            };
            item.addEventListener('click', handler);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
            });
        });
    }

    /**
     * Build review routing table HTML (read-only) from approval_routing data
     */
    _buildReviewTableHtml(eventData) {
        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        try {
            const routing = eventData.approval_routing;
            if (!routing || !routing.stages || routing.stages.length === 0) return '';

            const approvals = eventData.approvals || [];
            let rows = '';

            for (const stage of routing.stages) {
                for (const approver of (stage.approvers || [])) {
                    const approval = approvals.find(a =>
                        a.stage_id === stage.stage_id &&
                        String(a.approver_id || a.approver) === String(approver.user_id)
                    );

                    // Use current name from approval record if available, fall back to routing JSON name
                    const name = (approval && approval.approver_name) || approver.name || 'Unknown';

                    let statusText = 'Pending';
                    let statusClass = 'review-status-pending';
                    const isFirstStage = stage.order === 0;
                    if (approval) {
                        if (approval.status === 'approved') {
                            statusText = isFirstStage ? 'Started' : 'Approved';
                            statusClass = 'review-status-approved';
                        } else if (approval.status === 'sent_back') {
                            statusText = 'Sent back';
                            statusClass = 'review-status-sent-back';
                        }
                    }

                    rows += `<tr>
                        <td class="review-name">${escapeHtml(name)}</td>
                        <td class="review-status ${statusClass}">${statusText}</td>
                    </tr>`;
                }
            }

            if (!rows) return '';
            return `<div class="v2-readonly-section">
                <span class="v2-readonly-label">Review</span>
                <table class="detail-panel-review-table"><tbody>${rows}</tbody></table>
            </div>`;
        } catch (e) {
            return '';
        }
    }

    bindDetailPanelEvents(eventData) {
        // Close button (X) — same as Escape: deselect. Afterwards, Tab selects
        // the first event in the queue (see handlePanelTab).
        document.getElementById('detail-panel-close-btn')?.addEventListener('click', () => this.closeDetailPanel());

        // --- Attachments (replace / delete per file; files are added via the
        // event editing modal, so there's no upload affordance here) ---
        const attachmentReplaceInput = document.getElementById('detail-panel-attachment-replace-input');
        document.querySelectorAll('[data-attachment-replace]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this._hideFloatingTooltip();
                if (!attachmentReplaceInput) return;
                attachmentReplaceInput.dataset.attachmentId = btn.getAttribute('data-attachment-replace');
                attachmentReplaceInput.click();
            });
        });
        if (attachmentReplaceInput) {
            attachmentReplaceInput.addEventListener('change', () => {
                const attachmentId = attachmentReplaceInput.dataset.attachmentId;
                if (attachmentId && attachmentReplaceInput.files && attachmentReplaceInput.files[0]) {
                    this._replaceAttachment(eventData, attachmentId, attachmentReplaceInput.files[0]);
                }
            });
        }
        document.querySelectorAll('[data-attachment-delete]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this._hideFloatingTooltip();
                const attachmentId = btn.getAttribute('data-attachment-delete');
                const name = btn.getAttribute('data-attachment-name') || 'this file';
                if (window.confirm(`Delete "${name}"? This cannot be undone.`)) {
                    this._deleteAttachment(eventData, attachmentId);
                }
            });
        });

        // App-styled tooltips for the replace/delete buttons — portaled to
        // <body> on the top layer (pointer-events:none, so they never intercept
        // clicks or interact with page content).
        document.querySelectorAll('[data-attachment-replace], [data-attachment-delete]').forEach((btn) => {
            btn.addEventListener('mouseenter', () => this._showFloatingTooltip(btn, btn.getAttribute('data-tooltip')));
            btn.addEventListener('mouseleave', () => this._hideFloatingTooltip());
        });

        // Organization name → open that org's read-only details popup.
        const orgLink = document.querySelector('.detail-panel-org-link');
        if (orgLink && window.EventContactsPanel && typeof window.EventContactsPanel.openDetails === 'function') {
            const openOrg = () => {
                const orgId = orgLink.getAttribute('data-org-id');
                if (orgId) window.EventContactsPanel.openDetails('organization', orgId, { name: orgLink.textContent });
            };
            orgLink.addEventListener('click', openOrg);
            orgLink.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openOrg(); }
            });
        }

        // Status dropdown in detail panel header
        const statusWrapper = document.getElementById('detail-panel-status-wrapper');
        const statusBadge = document.getElementById('detail-panel-status-badge');
        const statusMenu = document.getElementById('detail-panel-dropdown-menu');
        if (statusWrapper && statusBadge && statusMenu) {
            statusBadge.addEventListener('click', (e) => {
                e.stopPropagation();
                if (statusWrapper.classList.contains('open')) {
                    this.closeDetailStatusDropdown(statusWrapper, statusMenu);
                    return;
                }
                // Close any card dropdowns
                this.closeAllDropdowns();

                // Move menu to body for positioning
                document.body.appendChild(statusMenu);
                const rect = statusBadge.getBoundingClientRect();
                statusMenu.style.visibility = 'hidden';
                statusMenu.style.display = 'block';
                const menuWidth = statusMenu.offsetWidth;
                const menuHeight = statusMenu.offsetHeight;
                const viewportHeight = window.innerHeight;
                const viewportWidth = window.innerWidth;

                let left = rect.left + (rect.width / 2) - (menuWidth / 2);
                if (left < 8) left = 8;
                if (left + menuWidth > viewportWidth - 8) left = viewportWidth - menuWidth - 8;

                let top;
                if (viewportHeight - rect.bottom >= menuHeight) {
                    top = rect.bottom;
                } else {
                    top = rect.top - menuHeight;
                }
                if (top + menuHeight > viewportHeight - 8) top = viewportHeight - menuHeight - 8;
                if (top < 8) top = 8;

                statusMenu.style.top = top + 'px';
                statusMenu.style.left = left + 'px';
                statusMenu.style.visibility = '';
                statusWrapper.classList.add('open');
            });

            statusBadge.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                // When the menu is already open, let the global handler drive
                // selection/navigation — intercepting here would just toggle it
                // shut without picking the highlighted option.
                if (statusWrapper.classList.contains('open')) return;
                e.preventDefault();
                e.stopPropagation();
                statusBadge.click();
                // Opened via keyboard → highlight an option so arrows move it.
                if (statusWrapper.classList.contains('open')) {
                    const opts = Array.from(statusMenu.querySelectorAll('.schedule-dropdown-option'));
                    opts.forEach(o => o.classList.remove('kb-active'));
                    const sel = statusMenu.querySelector('.schedule-dropdown-option.selected') || opts[0];
                    sel?.classList.add('kb-active');
                    sel?.scrollIntoView({ block: 'nearest' });
                }
            });

            // Option selection
            statusMenu.querySelectorAll('.schedule-dropdown-option').forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const newStatus = option.dataset.value;
                    const eventId = eventData.id;

                    // Update badge text and class
                    const newStatusClass = `status-${newStatus.toLowerCase().replace(/\s+/g, '_')}`;
                    statusBadge.className = `detail-panel-status ${newStatusClass}`;
                    statusBadge.querySelector('.detail-panel-status-text').textContent = option.textContent.trim();

                    // Update selected state
                    statusMenu.querySelectorAll('.schedule-dropdown-option').forEach(o => o.classList.remove('selected'));
                    option.classList.add('selected');

                    this.closeDetailStatusDropdown(statusWrapper, statusMenu);

                    // PATCH and sync card + local state
                    this.handleDetailPanelStatusChange(eventId, newStatus);
                });
            });

            // Close on outside click
            document.addEventListener('click', (e) => {
                if (statusWrapper.classList.contains('open') && !e.target.closest('#detail-panel-status-wrapper')) {
                    this.closeDetailStatusDropdown(statusWrapper, statusMenu);
                }
            });
        }

        // Three-dot more menu toggle
        const moreBtn = document.getElementById('detail-panel-more-btn');
        const moreMenu = document.getElementById('detail-panel-more-menu');
        if (moreBtn && moreMenu) {
            moreBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                moreMenu.classList.toggle('visible');
            });
            // Keyboard open: Enter/Space opens the menu and highlights the first
            // item so arrows/Tab can move it. When already open, let the global
            // handler drive selection/navigation.
            moreBtn.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                if (moreMenu.classList.contains('visible')) return;
                e.preventDefault();
                e.stopPropagation();
                moreMenu.classList.add('visible');
                const items = Array.from(moreMenu.querySelectorAll('.detail-panel-more-menu-item'));
                items.forEach(it => it.classList.remove('kb-active'));
                items[0]?.classList.add('kb-active');
            });
            // Close menu when clicking outside
            document.addEventListener('click', (e) => {
                if (moreMenu.classList.contains('visible') && !e.target.closest('.detail-panel-more-wrapper')) {
                    moreMenu.classList.remove('visible');
                }
            });
            // Close menu when mouse leaves the wrapper area
            const moreWrapper = moreBtn.closest('.detail-panel-more-wrapper');
            if (moreWrapper) {
                moreWrapper.addEventListener('mouseleave', () => {
                    moreMenu.classList.remove('visible');
                });
            }
        }

        // Export Word button (detail panel more menu)
        if (typeof HillDeskExport !== 'undefined') {
            HillDeskExport.bindDetailPanelExport(
                'detail-panel-btn-export',
                'detail-panel-more-menu',
                eventData,
                this.config.csrfToken
            );
        }



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

        // View on Calendar
        document.getElementById('detail-panel-btn-calendar')?.addEventListener('click', () => {
            if (eventData.start_date) {
                window.location.href = `/calendar/?date=${eventData.start_date}&event=${eventData.id}`;
            }
        });

        // Copy Details (in more menu)
        document.getElementById('detail-panel-btn-copy')?.addEventListener('click', async () => {
            document.getElementById('detail-panel-more-menu')?.classList.remove('open');
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
                    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied!`;
                    setTimeout(() => { btn.innerHTML = originalHTML; }, 1500);
                }
            } catch (e) {
                console.error('Copy failed:', e);
            }
        });

        // Delete button (in more menu)
        document.getElementById('detail-panel-btn-delete')?.addEventListener('click', () => {
            document.getElementById('detail-panel-more-menu')?.classList.remove('visible');
            this.deleteEventFromPanel(eventData);
        });

        // Edit button
        document.getElementById('detail-panel-btn-edit')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id);
            }
        });

        // Show Email button
        document.getElementById('detail-panel-btn-email')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id, { showEmailPane: true });
            }
        });

        // Add Staff button — opens dropdown matching modal style
        const addStaffBtnEl = document.getElementById('detail-panel-add-staff');
        const staffDropdown = document.getElementById('detail-panel-staff-dropdown');
        if (addStaffBtnEl && staffDropdown) {
            addStaffBtnEl.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (staffDropdown.classList.contains('visible')) {
                    this.hideDetailStaffDropdown(staffDropdown);
                    return;
                }
                await this.showDetailStaffDropdown(eventData, addStaffBtnEl, staffDropdown);
            });
            document.addEventListener('click', (e) => {
                if (staffDropdown.classList.contains('visible') && !e.target.closest('.v2-staff-dropdown-wrapper')) {
                    this.hideDetailStaffDropdown(staffDropdown);
                }
            });
        }
    }

    async showDetailStaffDropdown(eventData, button, dropdown) {
        // Load office staff
        let staff = [];
        try {
            const resp = await fetch('/api/office/choices/', {
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });
            if (resp.ok) {
                const data = await resp.json();
                staff = data.staff_members || data.staff || [];
            }
        } catch (e) {
            console.warn('Failed to load office staff:', e);
        }

        const currentStaff = eventData.staff || [];
        let html = '<div class="v2-staff-dropdown-header">Office Staff</div>';
        if (staff.length === 0) {
            html += '<div class="v2-staff-dropdown-empty">No staff members found</div>';
        } else {
            staff.forEach(member => {
                const name = member.name || member;
                const isAssigned = currentStaff.includes(name);
                const disabledClass = isAssigned ? ' disabled' : '';
                const checkIcon = isAssigned
                    ? '<svg class="v2-staff-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>'
                    : '';
                html += `<div class="v2-staff-dropdown-item${disabledClass}" data-staff-name="${this.escapeHtml(name)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                        <circle cx="12" cy="7" r="4"></circle>
                    </svg>
                    <span>${this.escapeHtml(name)}</span>
                    ${checkIcon}
                </div>`;
            });
        }
        dropdown.innerHTML = html;

        // Bind click handlers
        dropdown.querySelectorAll('.v2-staff-dropdown-item:not(.disabled)').forEach(item => {
            item.addEventListener('click', async () => {
                const staffName = item.dataset.staffName;
                this.hideDetailStaffDropdown(dropdown);
                await this.addStaffToDetailPanel(eventData, staffName);
            });
        });

        // Position dropdown on body to escape transforms
        document.body.appendChild(dropdown);
        const rect = button.getBoundingClientRect();
        dropdown.style.top = `${rect.bottom + 4}px`;
        dropdown.style.left = `${rect.left}px`;
        const dropdownWidth = 220;
        if (rect.left + dropdownWidth > window.innerWidth) {
            dropdown.style.left = `${window.innerWidth - dropdownWidth - 16}px`;
        }
        dropdown.classList.add('visible');
    }

    hideDetailStaffDropdown(dropdown) {
        dropdown.classList.remove('visible');
        // Move back to wrapper if on body
        if (dropdown.parentNode === document.body) {
            const wrapper = document.getElementById('detail-panel-add-staff')?.closest('.v2-staff-dropdown-wrapper');
            if (wrapper) {
                dropdown.style.top = '';
                dropdown.style.left = '';
                wrapper.appendChild(dropdown);
            }
        }
    }

    async addStaffToDetailPanel(eventData, staffName) {
        // PATCH the event to add the staff member
        const newStaff = [...(eventData.staff || []), staffName];
        try {
            const resp = await fetch(`${this.config.apiUrl}${eventData.id}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': this.config.csrfToken
                },
                credentials: 'same-origin',
                body: JSON.stringify({ staff: newStaff })
            });
            if (resp.ok) {
                // Update cached data and re-render
                eventData.staff = newStaff;
                // Add pill to DOM
                const staffList = document.getElementById('detail-panel-staff-list');
                const wrapper = staffList?.querySelector('.v2-staff-dropdown-wrapper');
                if (staffList && wrapper) {
                    const pill = document.createElement('span');
                    pill.className = 'v2-readonly-staff-pill';
                    pill.textContent = staffName;
                    staffList.insertBefore(pill, wrapper);
                }
                // Refresh event list to update card indicators
                this.refresh();
            }
        } catch (e) {
            console.error('Failed to add staff:', e);
        }
    }

    /**
     * Soft-delete (archive) an event from the detail panel. Moves it to Deleted
     * Events (restorable), mirroring the editor modal's delete action.
     */
    async deleteEventFromPanel(eventData) {
        const eventId = eventData?.id;
        if (!eventId) return;
        // Soft delete (restorable) — applied without a confirm prompt.
        try {
            const response = await fetch(`/api/events/${eventId}/archive/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.config.csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            if (!response.ok && response.status !== 204) {
                throw new Error(`HTTP ${response.status}`);
            }
            this.closeDetailPanel();
            this.refresh();
            if (typeof window.showMessage === 'function') {
                window.showMessage('Moved to Deleted Events', 'success');
            }
        } catch (error) {
            console.error('scheduleRedesign: Failed to delete event', error);
            if (typeof window.showMessage === 'function') {
                window.showMessage('Failed to delete event', 'error');
            }
        }
    }

    closeDetailPanel() {
        this.state.detailPanelEventId = null;
        this.state.detailPanelEventData = null;

        // Mark panel as empty (for responsive styles)
        this.elements.detailPanel?.classList.remove('has-event');

        // Remove active highlight from all cards and spreadsheet rows
        this.elements.eventList?.querySelectorAll('.schedule-card.detail-active, .schedule-spreadsheet tr.detail-active').forEach(el => {
            el.classList.remove('detail-active');
        });

        // Show empty state
        this.renderEmptyDetailPanel();
    }

    updateActiveCard(eventId) {
        // Remove highlight from all cards and spreadsheet rows
        this.elements.eventList?.querySelectorAll('.schedule-card.detail-active, .schedule-spreadsheet tr.detail-active').forEach(el => {
            el.classList.remove('detail-active');
        });
        // Add highlight to the selected card or spreadsheet row
        const card = this.elements.eventList?.querySelector(`.schedule-card[data-event-id="${eventId}"], .schedule-spreadsheet tr[data-event-id="${eventId}"]`);
        if (card) {
            card.classList.add('detail-active');
        }
    }

    addToRecentlyViewed(eventData) {
        // Remove if already in list
        this.state.recentlyViewed = this.state.recentlyViewed.filter(e => e.id != eventData.id);
        // Format a short date for display
        let shortDate = '';
        if (eventData.start_date) {
            try {
                const d = new Date(eventData.start_date + 'T00:00:00');
                shortDate = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            } catch (_) {}
        }
        // Add to front
        this.state.recentlyViewed.unshift({
            id: eventData.id,
            title: eventData.title || 'Untitled Event',
            group: eventData.group || '',
            date: shortDate
        });
        // Keep max 10
        if (this.state.recentlyViewed.length > 10) {
            this.state.recentlyViewed = this.state.recentlyViewed.slice(0, 10);
        }
        // Persist to sessionStorage
        this._saveRecentlyViewed();
    }

    _loadRecentlyViewed() {
        try {
            const data = sessionStorage.getItem('hilldesk_recently_viewed');
            return data ? JSON.parse(data) : [];
        } catch (_) {
            return [];
        }
    }

    _saveRecentlyViewed() {
        try {
            sessionStorage.setItem('hilldesk_recently_viewed', JSON.stringify(this.state.recentlyViewed));
        } catch (_) {}
    }

    renderEmptyDetailPanel() {
        const content = this.elements.detailPanelContent;
        if (!content) return;

        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        let recentHtml = '';
        if (this.state.recentlyViewed.length > 0) {
            const items = this.state.recentlyViewed.map(e => {
                const datePart = e.date ? `<span class="detail-panel-recent-date">${escapeHtml(e.date)}</span>` : '';
                return `<li class="detail-panel-recent-item" data-event-id="${e.id}"><span class="detail-panel-recent-item-title">${escapeHtml(e.title)}</span>${datePart}</li>`;
            }).join('');
            recentHtml = `
                <div class="detail-panel-recent">
                    <div class="detail-panel-recent-title">Recently viewed</div>
                    <ul class="detail-panel-recent-list">${items}</ul>
                </div>`;
        }

        content.innerHTML = `
            <div class="detail-panel-empty">
                <svg class="detail-panel-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
                <div class="detail-panel-empty-title">Select an event</div>
                <p class="detail-panel-empty-subtitle">Click an event to view its details here</p>
                ${recentHtml}
            </div>`;

        // Bind clicks on recently viewed items
        content.querySelectorAll('.detail-panel-recent-item').forEach(item => {
            item.addEventListener('click', () => {
                const eventId = item.dataset.eventId;
                if (eventId) this.openDetailPanel(eventId, { focusAction: true, silentFocus: true });
            });
        });
    }

    async handleStatusChange(eventId, newStatus, selectElement) {
        console.log('Changing status for event:', eventId, 'to:', newStatus);

        // Get the card element
        const card = selectElement.closest('.schedule-card');

        // Store old status for rollback
        const oldStatusClass = Array.from(card.classList).find(c => c.startsWith('status-'));

        // Optimistically update UI
        // Remove old status class
        card.classList.forEach(cls => {
            if (cls.startsWith('status-')) {
                card.classList.remove(cls);
            }
        });
        // Add new status class
        const newStatusClass = `status-${newStatus.toLowerCase().replace(/\s+/g, '_')}`;
        card.classList.add(newStatusClass);

        // Update select styling
        selectElement.classList.forEach(cls => {
            if (cls.startsWith('status-')) {
                selectElement.classList.remove(cls);
            }
        });
        selectElement.classList.add(newStatusClass);

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ status: newStatus }),
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            console.log('Status updated successfully');

            // Update the event in our local state
            const eventIndex = this.state.events.findIndex(e => e.id == eventId);
            if (eventIndex !== -1) {
                this.state.events[eventIndex].status = newStatus;
            }

            // If sorting by "Recently Modified", re-fetch to get correct order
            if (this.state.sortBy === '-modified') {
                // Small delay to let backend update the modified timestamp
                setTimeout(() => {
                    this.state.page = 1;
                    this.fetchEvents();
                }, 300);
            }

        } catch (error) {
            console.error('Error updating status:', error);

            // Rollback UI on error
            card.classList.remove(newStatusClass);
            if (oldStatusClass) {
                card.classList.add(oldStatusClass);
            }
            selectElement.classList.remove(newStatusClass);
            if (oldStatusClass) {
                selectElement.classList.add(oldStatusClass);
            }

            // Reset select to previous value
            const oldStatus = this.state.events.find(e => e.id === eventId)?.status;
            if (oldStatus) {
                selectElement.value = oldStatus;
            }

            // Show error to user
            alert('Failed to update status. Please try again.');
        }
    }

    getCsrfToken() {
        // Try cookie
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return value;
        }

        // Try config
        if (this.config.csrfToken) {
            return this.config.csrfToken;
        }

        // Try meta tag
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag?.content) return metaTag.content;

        return '';
    }

    // =========================================================================
    // UI Helpers
    // =========================================================================

    showLoading(append = false) {
        // Append (Load More) leaves the existing list untouched.
        if (append) return;
        if (!this.elements.eventList) return;
        if (this.state.viewMode === 'spreadsheet') {
            this.elements.eventList.innerHTML = this.renderSkeletonSpreadsheet(6);
        } else {
            this.elements.eventList.innerHTML = this.renderSkeletonList();
        }
    }

    hideLoading() {
        // No-op: renderEventList / showError will overwrite the skeleton markup.
    }

    renderSkeletonList() {
        const header = `
            <div class="skeleton-date-header" aria-hidden="true">
                <div class="skeleton skeleton-date-label"></div>
                <div class="skeleton skeleton-day-label"></div>
            </div>
        `;
        const card = `
            <div class="skeleton-schedule-card" aria-hidden="true">
                <div class="skeleton-status-bar"></div>
                <div class="skeleton-card-body">
                    <div class="skeleton-card-left">
                        <div class="skeleton skeleton-line-title"></div>
                        <div class="skeleton skeleton-line-meta"></div>
                    </div>
                    <div class="skeleton skeleton-pill"></div>
                </div>
            </div>
        `;

        // Build date-grouped skeletons (a date break + a few cards per group)
        // until they fill the visible scroll area, so the placeholder mirrors
        // the real grouped layout and covers the whole page on first load.
        const containerH = this.elements.viewContainer?.clientHeight || 800;
        const fillTarget = containerH + 80; // slight overfill so no gap shows
        const HEADER_H = 40;  // ~ .skeleton-date-header total vertical space
        const CARD_H = 50;    // ~ .skeleton-schedule-card height
        const groupSizes = [4, 3, 5, 3, 4]; // vary group sizes so it looks natural

        let html = '<div class="skeleton-schedule-list" role="status" aria-label="Loading events">';
        let used = 0;
        let g = 0;
        while (used < fillTarget) {
            html += header;
            used += HEADER_H;
            const size = groupSizes[g % groupSizes.length];
            for (let i = 0; i < size && used < fillTarget; i++) {
                html += card;
                used += CARD_H;
            }
            g += 1;
        }
        html += '</div>';
        return html;
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

    renderSkeletonSpreadsheet(count = 6) {
        const columns = this.getSpreadsheetColumns();
        // Real header row so column widths match the loaded table — headers don't shimmer.
        let head = '<thead><tr>';
        for (const col of columns) {
            const cssClass = col.key === 'status_bar' ? ' class="col-status-bar"' : '';
            head += `<th${cssClass}>${this.escapeHtml(col.header)}</th>`;
        }
        head += '</tr></thead>';

        const cells = columns.map(col => {
            if (col.key === 'status_bar') return '<td class="col-status-bar"></td>';
            return '<td><div class="skeleton skeleton-line-cell"></div></td>';
        }).join('');
        const row = `<tr aria-hidden="true">${cells}</tr>`;

        return `<div class="schedule-spreadsheet-wrapper" role="status" aria-label="Loading events">
            <table class="schedule-spreadsheet skeleton-spreadsheet">${head}<tbody>${row.repeat(count)}</tbody></table>
        </div>`;
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

    updateResultsCount() {
        // Results count row removed from UI
    }

    showError(message) {
        if (this.elements.eventList) {
            this.elements.eventList.innerHTML = `
                <div class="schedule-empty-state">
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
        return this.state.filters.status.length > 0 ||
               this.state.filters.type.length > 0 ||
               this.state.filters.format.length > 0 ||
               this.state.filters.staff.length > 0 ||
               this.state.filters.source.length > 0 ||
               this.state.filters.myEvents ||
               this.state.filters.overlappingOnly ||
               this.state.filters.memberAttending;
    }

    /**
     * Update the Filters button visual state based on active filters
     */
    updateFiltersButtonState() {
        const active = this.hasActiveFilters();
        if (this.elements.filtersToggleBtnInline) {
            this.elements.filtersToggleBtnInline.classList.toggle('has-filters', active);
        }
        if (this.elements.filtersToggleBtn) {
            this.elements.filtersToggleBtn.classList.toggle('has-filters', active);
        }
    }

    _syncFilterCheckboxes() {
        // Sync status/type/format/staff/source checkboxes with state
        ['status', 'type', 'format', 'staff', 'source'].forEach(filterType => {
            const activeFilters = this.state.filters[filterType];
            const checkboxes = this.elements.sidebarContent.querySelectorAll(
                `[data-filter="${filterType}"] input[type="checkbox"]:not([id$="-select-all"])`
            );
            const selectAll = document.getElementById(`${filterType}-select-all`);

            if (activeFilters.length === 0) {
                // No filter = all checked
                checkboxes.forEach(cb => { cb.checked = true; });
                if (selectAll) selectAll.checked = true;
            } else {
                checkboxes.forEach(cb => {
                    cb.checked = activeFilters.includes(cb.value);
                });
                if (selectAll) selectAll.checked = false;
            }
        });

        // Sync toggle filters
        const myEvtsCb = document.getElementById('filter-my-events');
        const overlapCb = document.getElementById('filter-overlapping');
        const memberCb = document.getElementById('filter-member-attending');
        if (myEvtsCb) myEvtsCb.checked = this.state.filters.myEvents;
        if (overlapCb) overlapCb.checked = this.state.filters.overlappingOnly;
        if (memberCb) memberCb.checked = this.state.filters.memberAttending;
    }

    _showFilterToast(message) {
        let toast = document.getElementById('filter-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'filter-toast';
            toast.className = 'filter-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('visible');
        setTimeout(() => toast.classList.remove('visible'), 2000);
    }

    getStatusLabel(status) {
        const statusMap = {
            'received': 'Received',
            'hold': 'Hold',
            'referred': 'Referred',
            'fyied': 'FYI\'ed',
            'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled',
            'rsvped': 'RSVP\'d',
            'regrets_sent': 'Regrets Sent',
            'passed': 'Passed',
            'canceled': 'Canceled',
            'requires_hms_review': 'Needs Review'
        };
        return statusMap[status] || status || 'Unknown';
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
        // the search box, where Up/Down/Enter should still drive the event list
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

        // When the detail-panel status dropdown is open, the keys drive that
        // menu (arrows to move, Enter/Space to pick, Esc to close).
        const openStatusWrapper = document.getElementById('detail-panel-status-wrapper');
        if (openStatusWrapper && openStatusWrapper.classList.contains('open')) {
            this.handleStatusMenuKeys(event, openStatusWrapper);
            return;
        }

        // Same for the "…" (more) menu.
        const openMoreMenu = document.getElementById('detail-panel-more-menu');
        if (openMoreMenu && openMoreMenu.classList.contains('visible')) {
            this.handleMoreMenuKeys(openMoreMenu, event);
            return;
        }

        // Spreadsheet view: arrows move the active cell, Ctrl+arrow jumps to the
        // edge, Shift+Left/Right swaps tabs, Enter acts on the cell.
        if (this.state.viewMode === 'spreadsheet' && this._handleSpreadsheetKeys(event)) {
            return;
        }

        switch (event.key) {
            case 'f':
                // Focus search
                event.preventDefault();
                if (this.elements.searchInput) {
                    this.elements.searchInput.focus();
                }
                break;
            case 'ArrowDown':
                // Up/Down move between events. When driven from the search box,
                // keep focus there so the user can keep typing.
                event.preventDefault();
                this.navigateItems(1, event.target === this.elements.searchInput);
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.navigateItems(-1, event.target === this.elements.searchInput);
                break;
            case 'ArrowRight':
                // Shift+Left/Right toggle between the two tabs (either key swaps
                // to the other tab), restoring each tab's previously selected
                // event (see switchTab). With no event selected there are no
                // panel controls to cycle, so plain Left/Right toggle tabs too.
                // Otherwise plain Left/Right cycle the panel's controls, like
                // Tab / Shift+Tab.
                if (event.shiftKey || this.state.detailPanelEventId == null) {
                    event.preventDefault();
                    this.switchTab(this.state.activeTab === 'all' ? 'undated' : 'all');
                } else if (this.cyclePanelFocus(1)) {
                    event.preventDefault();
                }
                break;
            case 'ArrowLeft':
                if (event.shiftKey || this.state.detailPanelEventId == null) {
                    event.preventDefault();
                    this.switchTab(this.state.activeTab === 'all' ? 'undated' : 'all');
                } else if (this.cyclePanelFocus(-1)) {
                    event.preventDefault();
                }
                break;
            case 'Tab':
                // Inside the panel, Tab cycles its controls (action buttons →
                // status → more → close), skipping collapse; on the empty panel
                // it cycles the recently-viewed list.
                this.handlePanelTab(event);
                break;
            case 'Enter': {
                // Enter opens the selected event. If a focusable panel control is
                // focused, let it handle Enter natively; otherwise this is the
                // default action — works even before the panel has loaded/focused.
                if (this.state.detailPanelEventId == null) break;
                const ae = document.activeElement;
                const panel = document.getElementById('schedule-detail-panel');
                const onControl = ae && panel && panel.contains(ae) && ae !== panel &&
                    (ae.tagName === 'BUTTON' || ae.tabIndex >= 0);
                if (!onControl) {
                    event.preventDefault();
                    this.handleEventDoubleClick(this.state.detailPanelEventId);
                }
                break;
            }
            case 'Escape':
                // Deselect event first, then close sidebar
                if (this.state.detailPanelEventId) {
                    this.closeDetailPanel();
                } else if (this.state.sidebarOpen) {
                    this.closeSidebar();
                }
                break;
        }
    }

    /**
     * The panel's focusable items in Tab order. When an event is selected:
     * action buttons (Edit / Calendar / Show Email) → status → any
     * overlapping-event items → more (…) → close (X), excluding the collapse
     * button. When nothing is selected, the empty panel's recently-viewed list.
     */
    getPanelTabOrder() {
        const panel = document.getElementById('schedule-detail-panel');
        if (this.state.detailPanelEventId) {
            const byId = id => document.getElementById(id);
            const ordered = [
                byId('detail-panel-btn-edit'),
                byId('detail-panel-btn-calendar'),
                byId('detail-panel-btn-email'),
                byId('detail-panel-status-badge'),
                // Overlapping events are navigable rows in the body — include
                // each in the cycle (Enter opens it).
                ...(panel ? Array.from(panel.querySelectorAll('.overlap-item')) : []),
                byId('detail-panel-more-btn'),
                byId('detail-panel-close-btn')
            ];
            return ordered.filter(el => el && !el.disabled &&
                (el.offsetWidth > 0 || el.offsetHeight > 0) &&
                (el.tagName === 'BUTTON' || el.tabIndex >= 0));
        }
        return panel ? Array.from(panel.querySelectorAll('.detail-panel-recent-item')) : [];
    }

    /**
     * Give exactly one panel control the visible keyboard focus ring (.focus-ring)
     * and focus it. The ring is cleared when the control loses focus.
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
     * (click) focus omits it — the control is still focused so Enter activates
     * it, but no ring appears until the user presses Tab or an arrow.
     */
    focusFirstPanelAction(opts = {}) {
        // The panel content can need a frame to lay out after the API resolves,
        // so the first control may not be present on the first try — retry across
        // a few frames until it is.
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
     * Move focus to the next (direction = 1) / previous (-1) panel control,
     * wrapping. If focus sits on a control that has no ring yet (a silent
     * click-focus), the first press just reveals the ring without moving.
     * Returns false if there's nothing to cycle.
     */
    cyclePanelFocus(direction) {
        const order = this.getPanelTabOrder();
        if (order.length === 0) return false;
        const active = document.activeElement;
        if (order.indexOf(active) !== -1 && !active.classList.contains('focus-ring')) {
            this._focusPanelControl(active); // reveal the ring, don't move
            return true;
        }
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
        // The spreadsheet has no side panel — leave Tab to the browser so focus
        // moves normally between page controls.
        if (this.state.viewMode === 'spreadsheet') return;
        // With nothing selected (e.g. just after X / Escape), Tab jumps into the
        // queue and selects the first event (Shift+Tab the last).
        if (!this.state.detailPanelEventId) {
            event.preventDefault();
            this.navigateItems(event.shiftKey ? -1 : 1);
            return;
        }
        const panel = document.getElementById('schedule-detail-panel');
        if (!panel || !panel.contains(document.activeElement)) return;
        if (this.cyclePanelFocus(event.shiftKey ? -1 : 1)) {
            event.preventDefault();
        }
    }

    /**
     * Keyboard handling while the detail-panel status dropdown is open: arrows
     * move the highlight between options, Enter/Space picks the highlighted one,
     * and Escape/Tab close the menu — returning focus to the status badge.
     */
    handleStatusMenuKeys(event, statusWrapper) {
        const menu = document.getElementById('detail-panel-dropdown-menu');
        const statusBadge = document.getElementById('detail-panel-status-badge');
        if (!menu) return;
        const options = Array.from(menu.querySelectorAll('.schedule-dropdown-option'));
        if (options.length === 0) return;

        const highlight = (i) => {
            options.forEach((o, j) => o.classList.toggle('kb-active', j === i));
            options[i]?.scrollIntoView({ block: 'nearest' });
        };
        // Current target: the highlighted option, else the selected one.
        let idx = options.findIndex(o => o.classList.contains('kb-active'));
        if (idx === -1) idx = options.findIndex(o => o.classList.contains('selected'));

        const next = () => highlight(idx < 0 ? 0 : (idx + 1) % options.length);
        const prev = () => highlight(idx < 0 ? options.length - 1 : (idx - 1 + options.length) % options.length);

        switch (event.key) {
            case 'ArrowDown':
            case 'ArrowRight':
                event.preventDefault();
                next();
                break;
            case 'ArrowUp':
            case 'ArrowLeft':
                event.preventDefault();
                prev();
                break;
            case 'Tab':
                // Tab / Shift+Tab close the menu unchanged and move to the next
                // / previous control in the panel cycle.
                event.preventDefault();
                this.closeDetailStatusDropdown(statusWrapper, menu);
                this._focusPanelControl(statusBadge);
                this.cyclePanelFocus(event.shiftKey ? -1 : 1);
                break;
            case 'Enter':
            case ' ':
                event.preventDefault();
                if (idx >= 0) {
                    options[idx].click(); // selects + closes the menu
                } else {
                    this.closeDetailStatusDropdown(statusWrapper, menu);
                }
                this._focusPanelControl(statusBadge);
                break;
            case 'Escape':
                event.preventDefault();
                this.closeDetailStatusDropdown(statusWrapper, menu);
                this._focusPanelControl(statusBadge);
                break;
        }
    }

    /**
     * Keyboard handling while the "…" (more) menu is open — mirrors the status
     * dropdown: arrows / Tab / Shift+Tab loop the items, Enter/Space activate
     * the highlighted one, Escape closes. Closing returns focus to the … button
     * (and never closes the panel).
     */
    handleMoreMenuKeys(menu, event) {
        const moreBtn = document.getElementById('detail-panel-more-btn');
        const items = Array.from(menu.querySelectorAll('.detail-panel-more-menu-item'));
        if (items.length === 0) return;

        const highlight = (i) => {
            items.forEach((it, j) => it.classList.toggle('kb-active', j === i));
            items[i]?.scrollIntoView({ block: 'nearest' });
        };
        const idx = items.findIndex(it => it.classList.contains('kb-active'));
        const next = () => highlight(idx < 0 ? 0 : (idx + 1) % items.length);
        const prev = () => highlight(idx < 0 ? items.length - 1 : (idx - 1 + items.length) % items.length);

        const close = () => {
            menu.classList.remove('visible');
            items.forEach(it => it.classList.remove('kb-active'));
            this._focusPanelControl(moreBtn);
        };

        switch (event.key) {
            case 'ArrowDown':
            case 'ArrowRight':
                event.preventDefault();
                next();
                break;
            case 'ArrowUp':
            case 'ArrowLeft':
                event.preventDefault();
                prev();
                break;
            case 'Tab':
                // Tab / Shift+Tab close the menu unchanged and move to the next
                // / previous control in the panel cycle.
                event.preventDefault();
                close();
                this.cyclePanelFocus(event.shiftKey ? -1 : 1);
                break;
            case 'Enter':
            case ' ':
                event.preventDefault();
                if (idx >= 0) {
                    items[idx].click(); // runs the item's action
                }
                close();
                break;
            case 'Escape':
                event.preventDefault();
                close();
                break;
        }
    }

    /**
     * Move the selection up (direction = -1) or down (direction = +1) through
     * the visible events — works for both the card list and the spreadsheet
     * view — opening the detail panel for the new row. With nothing selected,
     * Down picks the first item and Up the last.
     */
    navigateItems(direction, keepFocus = false) {
        const items = Array.from(
            this.elements.eventList?.querySelectorAll(
                '.schedule-card[data-event-id], .schedule-spreadsheet tbody tr[data-event-id]'
            ) || []
        );
        if (items.length === 0) return;

        // Locate the currently selected item.
        let currentIndex = items.findIndex(el => el.classList.contains('detail-active'));
        if (currentIndex === -1 && this.state.detailPanelEventId != null) {
            currentIndex = items.findIndex(
                el => String(el.dataset.eventId) === String(this.state.detailPanelEventId)
            );
        }

        let nextIndex;
        if (currentIndex === -1) {
            if (this.state.navAnchorIndex != null) {
                // The selected event was just removed (deleted/resolved). Resume
                // from its old slot: Down lands on the item that shifted into it
                // (the "next"), Up on the one before it.
                const a = this.state.navAnchorIndex;
                nextIndex = direction > 0 ? Math.min(a, items.length - 1) : Math.max(a - 1, 0);
            } else {
                // Nothing selected yet (e.g. fresh page load): both Up and Down
                // select the top item.
                nextIndex = 0;
            }
        } else {
            nextIndex = currentIndex + direction;
            if (nextIndex < 0 || nextIndex >= items.length) return; // at an edge
        }
        this.state.navAnchorIndex = null; // consumed / normal navigation

        const nextId = items[nextIndex].dataset.eventId;
        if (!nextId) return;
        // Keyboard selection normally drops focus onto the first action button,
        // so Enter opens the event and Tab walks the rest of the row's controls.
        // When navigating from the search box, keep focus in the input instead
        // so the user can keep typing while the selection moves.
        this.openDetailPanel(nextId, keepFocus ? {} : { focusAction: true });
        if (nextIndex === 0) {
            // At the top item, scroll the list fully up so the date header and
            // heading padding show — not just the item. Walk to the nearest
            // scrollable ancestor so this works in card and spreadsheet views.
            let scroller = items[0].parentElement;
            while (scroller) {
                const oy = getComputedStyle(scroller).overflowY;
                if ((oy === 'auto' || oy === 'scroll') && scroller.scrollHeight > scroller.clientHeight) break;
                scroller = scroller.parentElement;
            }
            (scroller || this.elements.viewContainer)?.scrollTo({ top: 0 });
        } else {
            items[nextIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    /**
     * Refresh the event list (called after modal close when something changed).
     * If the selected event vanished (deleted/resolved/filtered out), remember
     * its slot so the next Up/Down/Tab lands on the adjacent item.
     */
    async refresh() {
        this.state.page = 1;
        // Data may have changed (edit/delete/status), and an event can even move
        // between tabs — drop the cross-tab caches so the other tab refetches.
        this.state.tabCache = { all: null, undated: null };
        this._detailCache = {};
        const prevId = this.state.detailPanelEventId;
        const items = Array.from(this.elements.eventList?.querySelectorAll(
            '.schedule-card[data-event-id], .schedule-spreadsheet tbody tr[data-event-id]') || []);
        const prevIndex = prevId != null
            ? items.findIndex(el => String(el.dataset.eventId) === String(prevId))
            : -1;

        await this.fetchEvents();

        if (prevId == null) return;
        const stillVisible = this.elements.eventList?.querySelector(
            `.schedule-card[data-event-id="${prevId}"], .schedule-spreadsheet tr[data-event-id="${prevId}"]`);
        if (stillVisible) {
            this.state.navAnchorIndex = null;
            this.openDetailPanel(prevId);
        } else {
            this.state.navAnchorIndex = prevIndex >= 0 ? prevIndex : null;
            this.closeDetailPanel();
        }
    }
}

// Export for global access
window.ScheduleRedesign = ScheduleRedesign;
