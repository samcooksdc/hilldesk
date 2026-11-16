/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Calendar Redesign JavaScript
 * HillDesk Congressional Scheduling Application
 *
 * Provides functionality for the redesigned calendar view:
 * - Four view modes (Day, Week, Month, Schedule)
 * - Filter management with immediate application
 * - Outlook-style side-by-side overlapping events
 * - Integration with existing event editing modal
 */

/**
 * Main Calendar class managing state and rendering
 */
class CalendarRedesign {
    constructor(config = {}) {
        this.config = config;
        this.state = {
            currentView: 'week',  // Always start with week view
            currentDate: new Date(),
            filters: {
                status: [],
                category: [],
                format: [],
                staff: [],
                source: [],
                myEvents: false,
                overlappingOnly: false
            },
            autoLoadFilters: false,
            events: config.events || [],
            filterChoices: config.filterChoices || {},
            isLoading: false,
            allDayCollapsed: false,  // Track collapsed state of all-day section
            detailPanelEventId: null,
            detailPanelEventData: null
        };
        this.csrfToken = config.csrfToken || this.getCsrfToken();
        this.elements = {};

        // Popup state
        this.popup = null;
        this.popupTimeout = null;
        this.hidePopupTimeout = null;
        this.currentHoveredEvent = null;

        // Drag and resize state
        this.dragState = null;  // { type: 'move'|'resize-top'|'resize-bottom', eventEl, eventData, startY, startTop, startHeight, ... }
        this.dragGhost = null;
        this.dragTooltip = null;
        this.boundHandleDragMove = null;
        this.boundHandleMouseUp = null;
        this.wasDragging = false;  // Flag to prevent click after drag

        // Click-to-create state
        this.createState = null;  // { startMinutes, endMinutes, date, column, previewEl, popupEl, isMouseDown }
        this.boundHandleCreateDrag = null;
        this.boundHandleCreateMouseUp = null;
        this.wasCreating = false;  // Flag to prevent new create immediately after hiding popup

        // Mini calendar state
        this.miniCalendarDate = new Date();  // Month being displayed in mini calendar
    }

    /**
     * Initialize the calendar
     */
    init() {
        this.cacheElements();
        this.setScrollbarWidth();
        this.bindEvents();
        this.loadFilterChoices();
        this.renderFilters();
        this.updatePeriodLabel();
        this.startCurrentTimeUpdater();
        this.updateFiltersButtonState();
        this.initPopup();
        this.initTooltip();
        this.initDetailPanel();
        this.initDragAndResize();
        this.initClickToCreate();
        this.initMiniCalPopover();

        // Always start on today's date
        this.state.currentDate = new Date();

        // Hide loading spinners
        this.hideLoading();

        // Show the current view container and toggle buttons without fetching events.
        // The fetch is deferred to _maybeAutoLoadFilters so saved filter presets
        // are applied before the first API call (avoids a race condition).
        this.switchView(this.state.currentView, true);

        // Auto-load saved filters, then fetch events
        this._maybeAutoLoadFilters();
    }

    async _maybeAutoLoadFilters() {
        // Load the user's named presets; auto-apply the one flagged as default.
        try {
            this._ensurePresetManager();
            await this.presetManager.load();
            this._mountPresetDropdown();
            const def = this.presetManager.getDefault();
            if (def) {
                const preset = def.data || {};
                this.state.filters.status = preset.status || [];
                this.state.filters.category = preset.type || [];
                this.state.filters.format = preset.format || [];
                this.state.filters.staff = preset.staff || [];
                this.state.filters.source = preset.source || [];
                this.state.filters.myEvents = preset.myEvents || false;
                this.state.filters.overlappingOnly = preset.overlappingOnly || false;
                this.renderFilters();
                this._syncFilterCheckboxes();
                this.presetManager.setActive(def.id);
                this.updateFiltersButtonState();
            }
        } catch (e) {
            console.error('Error loading filter presets:', e);
        }

        // Fetch events (whether a default preset applied or not) — single initial fetch
        this.fetchEvents().then(() => {
            this.renderCurrentView();
            this.updatePeriodLabel();
            this.syncMiniCalendar();
            this.handleEventHighlightFromUrl();
        }).catch((error) => {
            console.error('Error fetching events:', error);
            // Still render even if fetch fails
            this.renderCurrentView();
            this.updatePeriodLabel();
            this.syncMiniCalendar();
        });
    }

    /**
     * Check URL for event parameter and highlight that event
     */
    handleEventHighlightFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        const eventId = urlParams.get('event');
        const dateParam = urlParams.get('date');

        if (eventId) {
            const highlightEvent = () => {
                // Open the event in the side detail panel, focusing its first
                // action silently so Tab can cycle the panel's controls.
                this.openDetailPanel(eventId, { focusAction: true, silentFocus: true });
                // Clean up URL so a refresh doesn't re-open the panel
                const newUrl = window.location.pathname;
                window.history.replaceState({}, '', newUrl);

                setTimeout(() => {
                    const eventEl = document.querySelector(
                        `.event-block[data-event-id="${eventId}"], ` +
                        `.event-chip[data-event-id="${eventId}"], ` +
                        `.schedule-event-row[data-event-id="${eventId}"], ` +
                        `.allday-event-bar[data-event-id="${eventId}"]`
                    );
                    if (eventEl) {
                        eventEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        eventEl.classList.add('calendar-event-highlight');
                        setTimeout(() => {
                            eventEl.classList.remove('calendar-event-highlight');
                        }, 2000);
                    }
                }, 300);
            };

            // If date parameter exists, navigate to that date and re-fetch events
            if (dateParam) {
                const date = new Date(dateParam);
                if (!isNaN(date.getTime())) {
                    this.state.currentDate = date;
                    this.fetchEvents().then(() => {
                        this.renderCurrentView();
                        highlightEvent();
                    });
                    return;
                }
            }

            // No date change needed — highlight in already-rendered view
            highlightEvent();
        }
    }

    /**
     * Calculate and set the scrollbar width as a CSS variable
     */
    setScrollbarWidth() {
        // Create a temporary element to measure scrollbar width
        const outer = document.createElement('div');
        outer.style.visibility = 'hidden';
        outer.style.overflow = 'scroll';
        outer.style.width = '100px';
        outer.style.height = '100px';
        document.body.appendChild(outer);

        const inner = document.createElement('div');
        inner.style.width = '100%';
        inner.style.height = '100%';
        outer.appendChild(inner);

        const scrollbarWidth = outer.offsetWidth - inner.offsetWidth;
        document.body.removeChild(outer);

        // Set as CSS variable
        document.documentElement.style.setProperty('--scrollbar-width', `${scrollbarWidth}px`);
    }

    /**
     * Cache DOM elements for performance
     */
    cacheElements() {
        this.elements = {
            container: document.querySelector('.calendar-redesign-container'),
            sidebar: document.querySelector('.calendar-filter-sidebar'),
            sidebarContent: document.querySelector('.sidebar-content'),
            sidebarToggle: document.querySelector('.sidebar-toggle'),
            mainArea: document.querySelector('.calendar-main-area'),
            headerBar: document.querySelector('.calendar-header-bar'),
            periodLabel: document.querySelector('.period-label'),
            viewContainer: document.querySelector('.calendar-view-container'),
            viewToggleBtns: document.querySelectorAll('.view-toggle-btn'),
            navBtns: {
                prev: document.querySelector('.nav-btn.prev'),
                today: document.querySelector('.nav-btn.today'),
                next: document.querySelector('.nav-btn.next')
            },
            clearAllBtn: document.querySelector('.clear-all-btn'),
            mobileToggle: document.querySelector('.mobile-sidebar-toggle'),
            filtersToggleBtn: document.getElementById('filters-toggle-btn'),
            sidebarOverlay: document.querySelector('.sidebar-overlay'),
            views: {
                day: document.getElementById('dayView'),
                week: document.getElementById('weekView'),
                month: document.getElementById('monthView'),
                schedule: document.getElementById('scheduleView')
            }
        };
    }

    /**
     * Bind event listeners
     */
    bindEvents() {
        // View toggle
        this.elements.viewToggleBtns.forEach(btn => {
            btn.addEventListener('click', (e) => this.switchView(e.target.dataset.view));
        });

        // Navigation
        this.elements.navBtns.prev?.addEventListener('click', () => this.navigatePrevious());
        this.elements.navBtns.today?.addEventListener('click', () => this.navigateToday());
        this.elements.navBtns.next?.addEventListener('click', () => this.navigateNext());

        // Clear all filters
        this.elements.clearAllBtn?.addEventListener('click', () => this.clearAllFilters());

        // Sidebar toggle (X button in sidebar header)
        this.elements.sidebarToggle?.addEventListener('click', () => this.toggleSidebar());

        // Mobile sidebar toggle
        this.elements.mobileToggle?.addEventListener('click', () => this.toggleSidebar());
        this.elements.sidebarOverlay?.addEventListener('click', () => this.closeSidebar());

        // Filters toggle button (toggles filter sidebar)
        this.elements.filtersToggleBtn?.addEventListener('click', () => this.toggleSidebar());

        // Keyboard navigation
        document.addEventListener('keydown', (e) => this.handleKeyboard(e));
    }

    /**
     * Toggle sidebar visibility (compresses calendar on desktop)
     */
    toggleSidebar() {
        const isOpen = this.elements.sidebar?.classList.contains('open');
        if (isOpen) {
            this.closeSidebar();
        } else {
            this.openSidebar();
        }
    }

    /**
     * Close sidebar
     */
    closeSidebar() {
        this.elements.sidebar?.classList.remove('open');
        this.elements.sidebar?.classList.add('collapsed');
        // Only show overlay on mobile
        if (window.innerWidth <= 1024) {
            this.elements.sidebarOverlay?.classList.remove('visible');
        }
    }

    /**
     * Open sidebar
     */
    openSidebar() {
        this.elements.sidebar?.classList.add('open');
        this.elements.sidebar?.classList.remove('collapsed');
        // Only show overlay on mobile
        if (window.innerWidth <= 1024) {
            this.elements.sidebarOverlay?.classList.add('visible');
        }
    }

    /**
     * Get CSRF token from various sources
     */
    getCsrfToken() {
        let csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (!csrfToken) {
            csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
        }
        if (!csrfToken) {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                const [name, value] = cookie.trim().split('=');
                if (name === 'csrftoken') {
                    csrfToken = value;
                    break;
                }
            }
        }
        return csrfToken;
    }

    // =========================================================================
    // View Management
    // =========================================================================

    /**
     * Switch to a different view mode
     * @param {string} viewName - The view to switch to
     * @param {boolean} skipFetch - If true, only update UI without fetching events (used during init)
     */
    switchView(viewName, skipFetch = false) {
        if (!['day', 'week', 'month', 'schedule'].includes(viewName)) return;

        this.state.currentView = viewName;
        localStorage.setItem('calendarView', viewName);

        // Update toggle button states
        this.elements.viewToggleBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });

        // Hide all views and show the selected one
        Object.entries(this.elements.views).forEach(([name, el]) => {
            if (el) {
                el.classList.toggle('hidden', name !== viewName);
            }
        });

        if (skipFetch) return;

        // Fetch events and render the view - always render even if fetch fails
        this.fetchEvents()
            .then(() => {
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            })
            .catch((error) => {
                console.error('Error fetching events during view switch:', error);
                // Still render the view even if fetch fails
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            });
    }

    /**
     * Render the currently active view
     */
    renderCurrentView() {
        // Always hide loading indicators before rendering
        this.hideLoading();

        switch (this.state.currentView) {
            case 'day':
                this.renderDayView();
                break;
            case 'week':
                this.renderWeekView();
                break;
            case 'month':
                this.renderMonthView();
                break;
            case 'schedule':
                this.renderScheduleView();
                break;
        }
    }

    /**
     * Render the current view but preserve scroll position
     * Used after drag/resize operations to avoid jumping to top
     */
    renderCurrentViewPreserveScroll(savedScrollTop) {
        // Always hide loading indicators before rendering
        this.hideLoading();

        // Render without auto-scroll
        switch (this.state.currentView) {
            case 'day':
                this.renderDayViewNoAutoScroll();
                break;
            case 'week':
                this.renderWeekViewNoAutoScroll();
                break;
            case 'month':
                this.renderMonthView();
                break;
            case 'schedule':
                this.renderScheduleView();
                break;
        }

        // Restore scroll position
        if (savedScrollTop !== undefined) {
            const scrollContainer = this.state.currentView === 'week'
                ? this.elements.views.week?.querySelector('.week-view-body')
                : this.elements.views.day?.querySelector('.day-view-body');

            if (scrollContainer) {
                scrollContainer.scrollTop = savedScrollTop;
            }
        }
    }

    // =========================================================================
    // Navigation
    // =========================================================================

    /**
     * Navigate to the previous period
     */
    navigatePrevious() {
        const date = new Date(this.state.currentDate);
        switch (this.state.currentView) {
            case 'day':
                date.setDate(date.getDate() - 1);
                break;
            case 'week':
                date.setDate(date.getDate() - 7);
                break;
            case 'month':
            case 'schedule':
                date.setMonth(date.getMonth() - 1);
                break;
        }
        this.state.currentDate = date;
        this.fetchEvents()
            .then(() => {
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            })
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            });
    }

    /**
     * Navigate to the next period
     */
    navigateNext() {
        const date = new Date(this.state.currentDate);
        switch (this.state.currentView) {
            case 'day':
                date.setDate(date.getDate() + 1);
                break;
            case 'week':
                date.setDate(date.getDate() + 7);
                break;
            case 'month':
            case 'schedule':
                date.setMonth(date.getMonth() + 1);
                break;
        }
        this.state.currentDate = date;
        this.fetchEvents()
            .then(() => {
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            })
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            });
    }

    /**
     * Navigate to today
     */
    navigateToday() {
        this.state.currentDate = new Date();
        this.fetchEvents()
            .then(() => {
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            })
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            });
    }

    /**
     * Update the period label based on current view and date
     */
    updatePeriodLabel() {
        const date = this.state.currentDate;
        const options = { month: 'long', year: 'numeric' };
        let label = '';

        switch (this.state.currentView) {
            case 'day':
                label = date.toLocaleDateString('en-US', {
                    weekday: 'long',
                    month: 'long',
                    day: 'numeric',
                    year: 'numeric'
                });
                break;
            case 'week':
                const weekStart = this.getWeekStart(date);
                const weekEnd = new Date(weekStart);
                weekEnd.setDate(weekEnd.getDate() + 6);
                if (weekStart.getMonth() === weekEnd.getMonth()) {
                    label = `${weekStart.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} - ${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;
                } else {
                    label = `${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
                }
                break;
            case 'month':
            case 'schedule':
                label = date.toLocaleDateString('en-US', options);
                break;
        }

        if (this.elements.periodLabel) {
            // Update only the text node, preserving child elements (e.g., chevron SVG)
            const firstTextNode = Array.from(this.elements.periodLabel.childNodes)
                .find(n => n.nodeType === Node.TEXT_NODE);
            if (firstTextNode) {
                firstTextNode.textContent = label;
            } else {
                // Insert text before any child elements
                this.elements.periodLabel.insertBefore(
                    document.createTextNode(label),
                    this.elements.periodLabel.firstChild
                );
            }
        }
    }

    /**
     * Handle keyboard navigation
     */
    handleKeyboard(e) {
        // While the Event Editing Modal is open it owns the keyboard — the
        // calendar behind it must not react to arrows/shortcuts.
        const eem = document.getElementById('event-editing-container');
        if (eem && eem.classList.contains('active')) return;

        // Ignore if typing in input/textarea or if modifier keys are pressed
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        switch (e.key) {
            case 'ArrowLeft':
                this.navigatePrevious();
                break;
            case 'ArrowRight':
                this.navigateNext();
                break;
            case 't':
            case 'T':
                this.navigateToday();
                break;
            case 'd':
            case 'D':
                this.switchView('day');
                break;
            case 'w':
            case 'W':
                this.switchView('week');
                break;
            case 'm':
            case 'M':
                this.switchView('month');
                break;
            case 'a':
            case 'A':
                this.switchView('schedule');
                break;
            case 'ArrowDown':
                // Up/Down cycle through events in the detail panel, just like the
                // events page. With nothing selected they jump to the first event
                // happening now or later.
                e.preventDefault();
                this.navigateEvents(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.navigateEvents(-1);
                break;
            case 'Tab':
                // Tab cycles the detail panel's controls, just like the events
                // page. With nothing selected it jumps into the event queue.
                this.handlePanelTab(e);
                break;
        }
    }

    /**
     * Start-of-event timestamp (ms). All-day events sort at 00:00 of their date.
     */
    _eventStartMs(event) {
        if (!event || !event.start_date) return Infinity;
        const [y, mo, d] = event.start_date.split('-').map(Number);
        let h = 0, mi = 0;
        if (event.start_time) {
            [h, mi] = event.start_time.split(':').map(Number);
        }
        return new Date(y, mo - 1, d, h || 0, mi || 0).getTime();
    }

    /**
     * End-of-event timestamp (ms) — used to decide whether an event is still
     * "going on right now". All-day or untimed events run to end of their day.
     */
    _eventEndMs(event) {
        if (!event || !event.start_date) return Infinity;
        const dateStr = event.end_date || event.start_date;
        const [y, mo, d] = dateStr.split('-').map(Number);
        const timeStr = event.end_time || event.start_time;
        if (!timeStr) {
            return new Date(y, mo - 1, d, 23, 59, 59).getTime();
        }
        const [h, mi] = timeStr.split(':').map(Number);
        return new Date(y, mo - 1, d, h || 0, mi || 0).getTime();
    }

    /**
     * Loaded events sorted chronologically by start time (all-day first).
     */
    _getSortedEvents() {
        return [...(this.state.events || [])].sort(
            (a, b) => this._eventStartMs(a) - this._eventStartMs(b)
        );
    }

    /**
     * Cycle the detail panel through events in chronological order. Mirrors the
     * events page: Down = next, Up = previous, stopping at the ends. When nothing
     * is selected yet, both directions open the first event happening now or after
     * the current time (falling back to the most recent event if all are past).
     */
    navigateEvents(direction) {
        if (document.body.classList.contains('modal-open')) return;

        const sorted = this._getSortedEvents();
        if (sorted.length === 0) return;

        const currentIndex = this.state.detailPanelEventId != null
            ? sorted.findIndex(ev => String(ev.id) === String(this.state.detailPanelEventId))
            : -1;

        let nextIndex;
        if (currentIndex === -1) {
            // Nothing selected: start on the first event going on now or later.
            const now = Date.now();
            nextIndex = sorted.findIndex(ev => this._eventEndMs(ev) >= now);
            if (nextIndex === -1) nextIndex = sorted.length - 1; // all in the past
        } else {
            nextIndex = currentIndex + direction;
            if (nextIndex < 0 || nextIndex >= sorted.length) return; // at an edge
        }

        const nextId = sorted[nextIndex].id;
        if (nextId == null) return;
        // Keyboard selection drops focus onto the first action button (ring
        // shown), so Tab walks the rest of the panel's controls.
        this.openDetailPanel(nextId, { focusAction: true });

        // Bring the matching block into view if it's rendered in the current grid.
        const eventEl = document.querySelector(
            `.event-block[data-event-id="${nextId}"], ` +
            `.event-chip[data-event-id="${nextId}"], ` +
            `.schedule-event-row[data-event-id="${nextId}"], ` +
            `.allday-event-bar[data-event-id="${nextId}"]`
        );
        if (eventEl) eventEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    /**
     * The detail panel's focusable controls in Tab order when an event is
     * selected: Edit → Show Email → status badge → more (…) → close (X). Mirrors
     * the events page (the calendar panel has no overlapping-event rows). With
     * nothing selected there's nothing to cycle.
     */
    getPanelTabOrder() {
        if (!this.state.detailPanelEventId) return [];
        const byId = id => document.getElementById(id);
        const ordered = [
            byId('cal-detail-btn-edit'),
            byId('cal-detail-btn-email'),
            byId('cal-detail-status-badge'),
            byId('cal-detail-more-btn'),
            byId('cal-detail-close-btn')
        ];
        return ordered.filter(el => el && !el.disabled &&
            (el.offsetWidth > 0 || el.offsetHeight > 0) &&
            (el.tagName === 'BUTTON' || el.tabIndex >= 0));
    }

    /**
     * Give exactly one panel control the visible keyboard focus ring
     * (.focus-ring) and focus it. The ring is cleared when the control blurs.
     */
    _focusPanelControl(el) {
        if (!el) return;
        this.getPanelTabOrder().forEach(c => c.classList.remove('focus-ring'));
        el.classList.add('focus-ring');
        el.addEventListener('blur', () => el.classList.remove('focus-ring'), { once: true });
        el.focus();
    }

    /**
     * Focus the first panel control. A silent (click) focus omits the ring — the
     * control is still focused so Enter activates it — until the user presses Tab
     * or an arrow; keyboard selection shows the ring immediately. The panel
     * content can need a frame to lay out after the API resolves, so retry across
     * a few frames until the first control exists.
     */
    focusFirstPanelAction(opts = {}) {
        const apply = (tries) => {
            // If the editing modal opened while the panel was still loading, stop
            // — never steal focus back to a control sitting behind the modal.
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
        const nextIdx = idx === -1
            ? (direction > 0 ? 0 : order.length - 1)
            : (idx + direction + order.length) % order.length;
        this._focusPanelControl(order[nextIdx]);
        return true;
    }

    /**
     * Tab handling, mirroring the events page. With nothing selected, Tab jumps
     * into the event queue (Shift+Tab the previous direction). With an event
     * selected and focus inside the panel, Tab/Shift+Tab cycle its controls; any
     * open status/more menu is closed first so it never traps focus.
     */
    handlePanelTab(event) {
        if (!this.state.detailPanelEventId) {
            event.preventDefault();
            this.navigateEvents(event.shiftKey ? -1 : 1);
            return;
        }

        // Close any open panel menu so Tab resumes cycling the controls.
        const statusWrapper = document.getElementById('cal-detail-status-wrapper');
        if (statusWrapper && statusWrapper.classList.contains('open')) {
            this._closeCalDetailStatusDropdown(statusWrapper, document.getElementById('cal-detail-dropdown-menu'));
        }
        const moreMenu = document.getElementById('cal-detail-more-menu');
        if (moreMenu && moreMenu.classList.contains('visible')) {
            moreMenu.classList.remove('visible');
        }

        const panel = document.getElementById('calendar-detail-panel');
        if (!panel || !panel.contains(document.activeElement)) return;
        if (this.cyclePanelFocus(event.shiftKey ? -1 : 1)) {
            event.preventDefault();
        }
    }

    // =========================================================================
    // Filter Management
    // =========================================================================

    /**
     * Load filter choices from config or API
     */
    async loadFilterChoices() {
        if (Object.keys(this.state.filterChoices).length > 0) {
            return; // Already loaded from config
        }

        try {
            const response = await fetch('/api/event-choices/');
            if (response.ok) {
                const data = await response.json();
                this.state.filterChoices = data;
            }
        } catch (error) {
            console.error('Error loading filter choices:', error);
        }
    }

    /**
     * Render filter sections in the sidebar
     */
    renderFilters() {
        const container = this.elements.sidebarContent;
        if (!container) return;

        container.innerHTML = '';

        // Quick Filters section (open by default)
        this.renderQuickFiltersSection(container);

        // Status filter
        this.renderFilterSection(container, 'status', 'Status',
            this.state.filterChoices.event_statuses || [], 'checkbox');

        // Category filter
        this.renderFilterSection(container, 'category', 'Category',
            this.state.filterChoices.event_types || [], 'checkbox');

        // Format filter (uses office-specific choices if available)
        const formatChoices = this.state.filterChoices.event_formats || [
            {value: 'in-person', label: 'In Person'},
            {value: 'virtual', label: 'Virtual'},
            {value: 'hybrid', label: 'Hybrid'}
        ];
        this.renderFilterSection(container, 'format', 'Format',
            formatChoices, 'checkbox');

        // Staff filter
        const staffNames = (this._staffList || []).map(s => s.name);
        const staffChoices = staffNames.map(name => ({value: name, label: name}));
        this.renderFilterSection(container, 'staff', 'Staff',
            staffChoices.length > 0 ? staffChoices : this.state.filterChoices.staff || [], 'checkbox');

        // Source filter (checkbox, not radio)
        const sourceChoices = [
            {value: 'email', label: 'Email'},
            {value: 'manual', label: 'Manual'}
        ];
        this.renderFilterSection(container, 'source', 'Source',
            sourceChoices, 'checkbox');

        // Clear All Filters button
        const clearBtn = document.createElement('button');
        clearBtn.className = 'clear-all-btn';
        clearBtn.textContent = 'Clear All Filters';
        clearBtn.addEventListener('click', () => this.clearAllFilters());
        container.appendChild(clearBtn);

        // Named filter presets dropdown — pinned to the top of the filters tab.
        this._mountPresetDropdown();

        // Fetch staff list if not already loaded
        if (!this._staffList) {
            this._fetchStaffList();
        }
    }

    /** Lazily create the shared preset manager (without mounting its DOM). */
    _ensurePresetManager() {
        if (this.presetManager) return;
        this.presetManager = new FilterPresetManager({
            getCsrf: () => this.csrfToken,
            getCurrentData: () => this._getPresetData(),
            applyData: (data) => this._applyPresetData(data || {}),
            showToast: (msg) => this._showFilterToast(msg),
        });
    }

    /**
     * (Re)mount the filter-preset dropdown at the top of the filter sidebar.
     * Called on every renderFilters() because that rebuilds the sidebar.
     */
    _mountPresetDropdown() {
        const container = this.elements.sidebarContent;
        if (!container) return;
        this._ensurePresetManager();
        const existing = container.querySelector('.filter-presets');
        if (existing) existing.remove();
        container.prepend(this.presetManager.render());

        // "Save current filters" button, placed just above Clear All Filters.
        const existingSave = container.querySelector('.preset-save-button-wrap');
        if (existingSave) existingSave.remove();
        const clearBtn = container.querySelector('.clear-all-btn');
        const saveBtn = this.presetManager.renderSaveButton();
        if (clearBtn) clearBtn.parentNode.insertBefore(saveBtn, clearBtn);
        else container.appendChild(saveBtn);
    }

    /** Canonical preset-data object captured from the current filter state. */
    _getPresetData() {
        return {
            status: this.state.filters.status,
            type: this.state.filters.category,
            format: this.state.filters.format,
            staff: this.state.filters.staff,
            source: this.state.filters.source,
            myEvents: this.state.filters.myEvents,
            overlappingOnly: this.state.filters.overlappingOnly,
        };
    }

    /** Apply a preset-data object to the calendar filters and refresh results. */
    _applyPresetData(preset) {
        this.state.filters.status = preset.status || [];
        this.state.filters.category = preset.type || [];
        this.state.filters.format = preset.format || [];
        this.state.filters.staff = preset.staff || [];
        this.state.filters.source = preset.source || [];
        this.state.filters.myEvents = preset.myEvents || false;
        this.state.filters.overlappingOnly = preset.overlappingOnly || false;

        this.renderFilters();
        this._syncFilterCheckboxes();
        this.updateFiltersButtonState();

        this.fetchEvents()
            .then(() => this.renderCurrentView())
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
            });
    }

    renderQuickFiltersSection(container) {
        const section = document.createElement('div');
        section.className = 'filter-section';  // Not collapsed by default
        section.dataset.section = 'quick';

        const header = document.createElement('div');
        header.className = 'filter-header';
        header.innerHTML = `<span>Quick Filters</span><span class="chevron">&#9660;</span>`;
        header.addEventListener('click', () => section.classList.toggle('collapsed'));

        const content = document.createElement('div');
        content.className = 'filter-content';
        const group = document.createElement('div');
        group.className = 'filter-checkbox-group';

        // My Events
        const myItem = document.createElement('div');
        myItem.className = 'filter-checkbox-item';
        myItem.innerHTML = `
            <input type="checkbox" id="cal-filter-my-events" ${this.state.filters.myEvents ? 'checked' : ''}>
            <label for="cal-filter-my-events">My Events</label>
        `;
        group.appendChild(myItem);

        // Overlapping Events
        const overlapItem = document.createElement('div');
        overlapItem.className = 'filter-checkbox-item';
        overlapItem.innerHTML = `
            <input type="checkbox" id="cal-filter-overlapping" ${this.state.filters.overlappingOnly ? 'checked' : ''}>
            <label for="cal-filter-overlapping">Overlapping Events</label>
        `;
        group.appendChild(overlapItem);

        content.appendChild(group);
        section.appendChild(header);
        section.appendChild(content);
        container.appendChild(section);

        // Bind events after appending
        document.getElementById('cal-filter-my-events')?.addEventListener('change', (e) => this.handleToggleFilter('myEvents', e.target.checked));
        document.getElementById('cal-filter-overlapping')?.addEventListener('change', (e) => this.handleToggleFilter('overlappingOnly', e.target.checked));
    }

    /**
     * Render a single filter section
     */
    renderFilterSection(container, id, label, choices, type = 'checkbox', disabled = false) {
        const section = document.createElement('div');
        // Start collapsed by default
        section.className = `filter-section collapsed${disabled ? ' disabled' : ''}`;
        section.dataset.section = id;

        const header = document.createElement('div');
        header.className = 'filter-header';
        header.innerHTML = `
            <span>${label}</span>
            <span class="chevron">▼</span>
        `;
        header.addEventListener('click', () => {
            section.classList.toggle('collapsed');
        });

        const content = document.createElement('div');
        content.className = 'filter-content';

        if (disabled) {
            content.innerHTML = '<span class="coming-soon">Coming soon</span>';
        } else if (choices.length === 0) {
            content.innerHTML = '<span class="coming-soon">No options available</span>';
        } else {
            const group = document.createElement('div');
            group.className = 'filter-checkbox-group';

            // Add "Select All" option for checkbox filters (not radio)
            if (type === 'checkbox' && choices.length > 1) {
                const selectAllItem = document.createElement('div');
                selectAllItem.className = 'filter-checkbox-item select-all-item';

                const selectAllInput = document.createElement('input');
                selectAllInput.type = 'checkbox';
                selectAllInput.name = `filter-${id}-select-all`;
                selectAllInput.id = `filter-${id}-select-all`;
                selectAllInput.className = 'select-all-checkbox';

                selectAllInput.addEventListener('change', () => {
                    this.handleSelectAll(id, selectAllInput.checked, group);
                });

                const selectAllLabel = document.createElement('label');
                selectAllLabel.htmlFor = selectAllInput.id;
                selectAllLabel.textContent = '(Select All)';

                selectAllItem.appendChild(selectAllInput);
                selectAllItem.appendChild(selectAllLabel);
                group.appendChild(selectAllItem);
            }

            choices.forEach((choice) => {
                // Handle both array format [value, label] and object format {value, label}
                const value = Array.isArray(choice) ? choice[0] : choice.value;
                const displayLabel = Array.isArray(choice) ? choice[1] : choice.label;

                const item = document.createElement('div');
                item.className = 'filter-checkbox-item';

                const input = document.createElement('input');
                input.type = type;
                input.name = `filter-${id}`;
                input.id = `filter-${id}-${value}`;
                input.value = value;

                input.addEventListener('change', () => {
                    this.handleFilterChange(id, value, input.checked);
                    // Update Select All checkbox state
                    this.updateSelectAllState(id, group);
                });

                const inputLabel = document.createElement('label');
                inputLabel.htmlFor = input.id;
                inputLabel.textContent = displayLabel;

                item.appendChild(input);
                item.appendChild(inputLabel);
                group.appendChild(item);
            });

            content.appendChild(group);
        }

        section.appendChild(header);
        section.appendChild(content);
        container.appendChild(section);
    }

    /**
     * Handle Select All checkbox change
     */
    handleSelectAll(filterType, checked, group) {
        const checkboxes = group.querySelectorAll(`input[name="filter-${filterType}"]`);

        // Update filter array directly (batch update, no individual fetches)
        if (checked) {
            // Add all values to the filter
            this.state.filters[filterType] = Array.from(checkboxes).map(cb => cb.value);
        } else {
            // Clear the filter array - empty means "show all" (no filtering)
            this.state.filters[filterType] = [];
        }

        // Update checkbox UI
        checkboxes.forEach(checkbox => {
            checkbox.checked = checked;
        });

        // Update filter button visual state
        this.updateFiltersButtonState();

        // Single fetch and re-render
        this.fetchEvents()
            .then(() => this.renderCurrentView())
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
            });
    }

    /**
     * Update Select All checkbox state based on individual checkboxes
     */
    updateSelectAllState(filterType, group) {
        const selectAllCheckbox = group.querySelector('.select-all-checkbox');
        if (!selectAllCheckbox) return;

        const checkboxes = group.querySelectorAll(`input[name="filter-${filterType}"]`);
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);
        const someChecked = Array.from(checkboxes).some(cb => cb.checked);

        selectAllCheckbox.checked = allChecked;
        selectAllCheckbox.indeterminate = someChecked && !allChecked;
    }

    /**
     * Handle filter checkbox/radio change
     */
    handleFilterChange(filterType, value, checked) {
        const filterArray = this.state.filters[filterType];
        if (checked) {
            if (!filterArray.includes(value)) {
                filterArray.push(value);
            }
        } else {
            const index = filterArray.indexOf(value);
            if (index > -1) {
                filterArray.splice(index, 1);
            }
        }

        // Update filter button visual state
        this.updateFiltersButtonState();

        // Immediately fetch and re-render
        this.fetchEvents()
            .then(() => this.renderCurrentView())
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
            });
    }

    handleToggleFilter(filterName, checked) {
        this.state.filters[filterName] = checked;
        this.updateFiltersButtonState();
        this.fetchEvents()
            .then(() => this.renderCurrentView())
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
            });
    }

    /**
     * Clear all filters
     */
    clearAllFilters() {
        this.state.filters = {
            status: [],
            category: [],
            format: [],
            staff: [],
            source: [],
            myEvents: false,
            overlappingOnly: false
        };

        // Deselect any active saved preset (resets trigger to "Filter presets").
        if (this.presetManager) this.presetManager.clearActive();

        // Re-render filters to reset all checkboxes
        this.renderFilters();

        // Update filter button visual state
        this.updateFiltersButtonState();

        this.fetchEvents()
            .then(() => this.renderCurrentView())
            .catch((error) => {
                console.error('Error fetching events:', error);
                this.renderCurrentView();
            });
    }

    // =========================================================================
    // Data Fetching
    // =========================================================================

    /**
     * Fetch events from the API
     */
    async fetchEvents() {
        this.state.isLoading = true;
        this.showLoading();

        const params = new URLSearchParams();
        params.set('view_type', this.state.currentView);
        params.set('year', this.state.currentDate.getFullYear());
        params.set('month', this.state.currentDate.getMonth() + 1);
        params.set('day', this.state.currentDate.getDate());

        // Add status filters
        this.state.filters.status.forEach(s => params.append('status', s));

        // Add type/category filters
        this.state.filters.category.forEach(t => params.append('type', t));

        // Add staff filters
        this.state.filters.staff.forEach(s => params.append('staff', s));

        // Add source filters
        this.state.filters.source.forEach(s => params.append('source', s));

        // Toggle filters
        if (this.state.filters.myEvents) {
            params.append('my_events', 'true');
        }
        if (this.state.filters.overlappingOnly) {
            params.append('overlapping_only', 'true');
        }

        try {
            const response = await fetch(`/api/calendar/events/?${params}`);
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    // Extract events from calendar_data structure
                    const events = this.extractEventsFromCalendarData(data.calendar_data);
                    this.state.events = this.processEvents(events);
                }
            }
        } catch (error) {
            console.error('Error fetching events:', error);
        } finally {
            this.state.isLoading = false;
            this.hideLoading();
        }
    }

    /**
     * Extract events from the calendar_data structure returned by the API
     */
    extractEventsFromCalendarData(calendarData) {
        const events = [];
        const seenIds = new Set();

        if (!calendarData) return events;

        // Handle week view structure: { days: [...] }
        if (calendarData.days) {
            calendarData.days.forEach(day => {
                if (day.events) {
                    day.events.forEach(event => {
                        if (!seenIds.has(event.id)) {
                            seenIds.add(event.id);
                            // Add start_date and start_time from the day context if not present
                            if (!event.start_date && day.date) {
                                event.start_date = day.date;
                            }
                            events.push(event);
                        }
                    });
                }
            });
        }

        // Handle month view structure: { weeks: [[day, ...], ...] }
        if (calendarData.weeks) {
            calendarData.weeks.forEach(week => {
                week.forEach(day => {
                    if (day.events) {
                        day.events.forEach(event => {
                            if (!seenIds.has(event.id)) {
                                seenIds.add(event.id);
                                if (!event.start_date && day.date) {
                                    event.start_date = day.date;
                                }
                                events.push(event);
                            }
                        });
                    }
                });
            });
        }

        // Handle day view structure: { events: [...] }
        if (calendarData.events && Array.isArray(calendarData.events)) {
            calendarData.events.forEach(event => {
                if (!seenIds.has(event.id)) {
                    seenIds.add(event.id);
                    events.push(event);
                }
            });
        }

        return events;
    }

    /**
     * Process events data and apply client-side filters
     */
    processEvents(events) {
        let filtered = events;
        const beforeCount = events.length;

        // Filter out events that require human review
        const beforeReviewFilter = filtered.length;
        filtered = filtered.filter(event => !event.requires_human_review);
        if (filtered.length < beforeReviewFilter) {
            console.log('CalendarRedesign: Filtered out', beforeReviewFilter - filtered.length, 'events requiring human review');
        }

        // Apply format filter
        if (this.state.filters.format.length > 0) {
            const beforeFormat = filtered.length;
            filtered = filtered.filter(e =>
                this.state.filters.format.includes(e.format)
            );
            if (filtered.length < beforeFormat) {
                console.log('CalendarRedesign: Format filter removed', beforeFormat - filtered.length, 'events');
            }
        }

        // Apply staff filter - normalize staff names for comparison
        if (this.state.filters.staff.length > 0) {
            const beforeStaff = filtered.length;
            filtered = filtered.filter(e => {
                const eventStaff = (e.staff || []).map(s => typeof s === 'object' ? s.name : s);
                return this.state.filters.staff.some(s => eventStaff.includes(s));
            });
            if (filtered.length < beforeStaff) {
                console.log('CalendarRedesign: Staff filter removed', beforeStaff - filtered.length, 'events');
            }
        }

        // Apply source filter (array-based: ['email'], ['manual'], or both/empty = all)
        if (this.state.filters.source.length > 0 && this.state.filters.source.length < 2) {
            const beforeSource = filtered.length;
            filtered = filtered.filter(e => {
                const hasEmails = (e.attached_email_ids?.length || 0) > 0;
                return this.state.filters.source.includes('email') ? hasEmails : !hasEmails;
            });
            if (filtered.length < beforeSource) {
                console.log('CalendarRedesign: Source filter removed', beforeSource - filtered.length, 'events');
            }
        }

        if (filtered.length < beforeCount) {
            console.log('CalendarRedesign: processEvents filtered', beforeCount, '->', filtered.length, 'events');
        }

        return filtered;
    }

    /**
     * Show loading indicator
     */
    showLoading() {
        // Show skeleton inside the currently-visible view (replacing any prior render).
        // renderCurrentView will overwrite this with real content when fetch completes.
        const activeView = this.elements.views?.[this.state.currentView];
        if (!activeView) return;
        activeView.innerHTML = `<div class="calendar-loading" role="status" aria-label="Loading calendar">${this.renderCalendarSkeleton()}</div>`;
        // Scroll body to working-hours area so the shimmer events sit in view.
        const body = activeView.querySelector('.week-view-body, .day-view-body');
        if (body) body.scrollTop = 480;
    }

    renderCalendarSkeleton() {
        const view = this.state.currentView;
        if (view === 'month') return this.renderMonthSkeleton();
        if (view === 'day') return this.renderDaySkeleton();
        return this.renderWeekSkeleton();
    }

    _hourLabel(hour) {
        if (hour === 0) return '12 AM';
        if (hour < 12) return `${hour} AM`;
        if (hour === 12) return '12 PM';
        return `${hour - 12} PM`;
    }

    renderWeekSkeleton() {
        const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

        let header = '<div class="week-header-row"><div class="time-gutter-header"></div>';
        for (let i = 0; i < 7; i++) {
            header += `<div class="day-column-header"><span class="day-name">${dayNames[i]}</span><span class="day-number"><span class="skeleton skeleton-day-num"></span></span></div>`;
        }
        header += '</div>';

        let grid = '<div class="week-view-body"><div class="week-grid">';
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            grid += `<div class="time-gutter">${this._hourLabel(hour)}</div>`;
            for (let i = 0; i < 7; i++) grid += '<div class="hour-cell"></div>';
        }
        grid += '</div>';

        let events = '<div class="week-events-layer">';
        for (let i = 0; i < 7; i++) {
            events += '<div class="day-events-column"><div class="skeleton skeleton-cal-event"></div><div class="skeleton skeleton-cal-event"></div></div>';
        }
        events += '</div>';

        return header + grid + events + '</div>';
    }

    renderDaySkeleton() {
        let header = `<div class="day-header-row"><div class="time-gutter-header"></div><div class="day-column-header"><span class="day-name">Today</span><span class="day-number"><span class="skeleton skeleton-day-num"></span></span></div></div>`;

        let grid = '<div class="day-view-body"><div class="day-grid">';
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            grid += `<div class="time-gutter">${this._hourLabel(hour)}</div><div class="hour-cell"></div>`;
        }
        grid += '</div>';

        let events = '<div class="day-events-layer"><div class="day-events-column"><div class="skeleton skeleton-cal-event"></div><div class="skeleton skeleton-cal-event"></div><div class="skeleton skeleton-cal-event"></div></div></div>';

        return header + grid + events + '</div>';
    }

    renderMonthSkeleton() {
        const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        let html = '<div class="month-view-grid">';
        dayNames.forEach(day => { html += `<div class="month-header-cell">${day}</div>`; });
        for (let i = 0; i < 42; i++) {
            html += '<div class="month-day-cell"><div class="day-number"><span class="skeleton skeleton-day-num"></span></div><div class="month-day-events"><div class="skeleton skeleton-cal-event"></div><div class="skeleton skeleton-cal-event"></div></div></div>';
        }
        html += '</div>';
        return html;
    }

    /**
     * Hide loading indicator
     */
    hideLoading() {
        // Hide all loading indicators in all views
        const loaders = this.elements.viewContainer?.querySelectorAll('.calendar-loading');
        loaders?.forEach(loader => {
            loader.style.display = 'none';
        });
    }

    // =========================================================================
    // Week View
    // =========================================================================

    /**
     * Render the week view
     */
    renderWeekView(skipAutoScroll = false) {
        const container = this.elements.views.week;
        if (!container) return;

        const weekStart = this.getWeekStart(this.state.currentDate);
        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Build sticky header row with time gutter space
        let headerHtml = `
            <div class="week-header-row">
                <div class="time-gutter-header"></div>
        `;

        for (let i = 0; i < 7; i++) {
            const dayDate = new Date(weekStart);
            dayDate.setDate(dayDate.getDate() + i);
            const isToday = dayDate.getTime() === today.getTime();
            headerHtml += `
                <div class="day-column-header${isToday ? ' today' : ''}">
                    <span class="day-name">${dayDate.toLocaleDateString('en-US', { weekday: 'short' })}</span>
                    <span class="day-number">${dayDate.getDate()}</span>
                </div>
            `;
        }
        headerHtml += `</div>`;

        // Build all-day section for multi-day events
        const allDayHtml = this.renderAllDaySection(weekStart, weekEnd, today);

        // Expand tab shown when all-day section is collapsed (placed between header and body)
        const expandTabHtml = allDayHtml ? `<div class="allday-expand-tab" title="Show all-day events">▼</div>` : '';

        // Build scrollable body using CSS grid
        let bodyHtml = `<div class="week-view-body"><div class="week-grid">`;

        // Generate rows for each hour
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            const timeLabel = hour === 0 ? '12 AM' :
                             hour < 12 ? `${hour} AM` :
                             hour === 12 ? '12 PM' :
                             `${hour - 12} PM`;

            // Time gutter cell
            bodyHtml += `<div class="time-gutter">${timeLabel}</div>`;

            // Day cells for this hour
            for (let i = 0; i < 7; i++) {
                const dayDate = new Date(weekStart);
                dayDate.setDate(dayDate.getDate() + i);
                const isToday = dayDate.getTime() === today.getTime();
                bodyHtml += `<div class="hour-cell${isToday ? ' today' : ''}" data-hour="${hour}" data-day="${i}"></div>`;
            }
        }

        bodyHtml += `</div>`;

        // Events layer - positioned absolutely over the grid (only timed events)
        bodyHtml += `<div class="week-events-layer">`;
        let weekHasEvents = false;
        for (let i = 0; i < 7; i++) {
            const dayDate = new Date(weekStart);
            dayDate.setDate(dayDate.getDate() + i);
            const isToday = dayDate.getTime() === today.getTime();
            const dayEvents = this.getTimedEventsForDate(dayDate);
            if (dayEvents.length > 0) weekHasEvents = true;

            bodyHtml += `
                <div class="day-events-column${isToday ? ' today' : ''}" data-date="${this.formatDate(dayDate)}">
                    ${this.renderDayEvents(dayEvents, isToday)}
                </div>
            `;
        }

        bodyHtml += `</div>`;

        // Check if there are any all-day events too
        const hasAllDayEvents = this.getMultiDayEventsForWeek(weekStart, weekEnd).length > 0;

        // Empty state message if no events
        if (!weekHasEvents && !hasAllDayEvents) {
            bodyHtml += `<div class="calendar-empty-state">No events this week</div>`;
        }

        bodyHtml += `</div>`;

        container.innerHTML = headerHtml + allDayHtml + expandTabHtml + bodyHtml;

        // Add class to header row when all-day section is present (moves shadow to all-day section)
        const headerRow = container.querySelector('.week-header-row');
        if (headerRow && allDayHtml) {
            headerRow.classList.add('has-allday-section');
        }

        this.bindEventClicks(container);
        this.bindDragEvents(container);
        this.bindClickToCreate(container);
        this.bindScrollToHidePopup(container.querySelector('.week-view-body'));
        this.bindDateHeaderClicks(container);
        this.bindAllDayEventClicks(container);

        // Restore collapsed state of all-day section if it was previously collapsed
        if (this.state.allDayCollapsed && allDayHtml) {
            const allDaySection = container.querySelector('.week-allday-section');
            if (allDaySection) {
                allDaySection.classList.add('collapsed');
                container.classList.add('allday-collapsed');
                if (headerRow) {
                    headerRow.classList.remove('has-allday-section');
                }
            }
        }

        // Ensure text contrast on event blocks
        container.querySelectorAll('.event-block').forEach(el => this.ensureTextContrast(el));

        // Collapse blocks too narrow to show their text (measured post-layout)
        this.applyCompactEventBlocks(container);

        // Auto-scroll to first event or middle (unless skipped)
        if (!skipAutoScroll) {
            this.autoScrollToContent(container.querySelector('.week-view-body'));
        }
    }

    /**
     * Render week view without auto-scroll (for preserving scroll position)
     */
    renderWeekViewNoAutoScroll() {
        this.renderWeekView(true);
    }

    /**
     * Auto-scroll to the first event or middle of the scrollable area
     */
    autoScrollToContent(scrollContainer) {
        if (!scrollContainer) return;

        // Use setTimeout to ensure DOM is fully rendered
        setTimeout(() => {
            // Find all event blocks and get the one with the smallest top value
            const eventBlocks = scrollContainer.querySelectorAll('.event-block');
            let earliestTop = Infinity;

            eventBlocks.forEach(event => {
                const eventTop = parseInt(event.style.top) || 0;
                if (eventTop < earliestTop) {
                    earliestTop = eventTop;
                }
            });

            if (earliestTop !== Infinity) {
                // Scroll to show the earliest event with some padding above
                const padding = 20; // pixels of padding above the event
                scrollContainer.scrollTop = Math.max(0, earliestTop - padding);
            }// else {
                // No events - scroll to middle of the scrollable area
             //   const scrollHeight = scrollContainer.scrollHeight;
            //    const clientHeight = scrollContainer.clientHeight;
           //     const middleScroll = (scrollHeight - clientHeight) / 2;
           //     scrollContainer.scrollTop = middleScroll;
          //  }
        }, 50);
    }

    /**
     * Starting hour for the calendar day view (12 AM = midnight)
     */
    get startHour() {
        return 0;
    }

    /**
     * Ending hour for the calendar day view (11 PM)
     */
    get endHour() {
        return 23;
    }

    /**
     * Render time labels for week/day views (with header for day view)
     */
    renderTimeLabels() {
        let html = '';
        // Add empty header cell to align with day headers
        html += `<div class="time-column-header"></div>`;
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            const label = hour === 0 ? '12 AM' :
                         hour < 12 ? `${hour} AM` :
                         hour === 12 ? '12 PM' :
                         `${hour - 12} PM`;
            html += `<div class="time-slot-label">${label}</div>`;
        }
        return html;
    }

    /**
     * Render time slot labels only (for week view scrollable body)
     */
    renderTimeSlotLabels() {
        let html = '';
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            const label = hour === 0 ? '12 AM' :
                         hour < 12 ? `${hour} AM` :
                         hour === 12 ? '12 PM' :
                         `${hour - 12} PM`;
            html += `<div class="time-slot-label">${label}</div>`;
        }
        return html;
    }

    /**
     * Render hour slot grid lines
     */
    renderHourSlots() {
        let html = '';
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            html += `<div class="hour-slot" data-hour="${hour}"></div>`;
        }
        return html;
    }

    /**
     * Render events for a single day with overlap handling
     */
    renderDayEvents(events, isToday = false) {
        if (!events.length) return '';

        // Calculate positions for overlapping events
        const positionedEvents = this.calculateEventPositions(events);

        let html = '';

        // Current time line
        if (isToday) {
            const now = new Date();
            const currentHour = now.getHours();
            // Only show current time line if within visible hours
            if (currentHour >= this.startHour && currentHour <= this.endHour) {
                const minutes = (currentHour - this.startHour) * 60 + now.getMinutes();
                const top = (minutes / 60) * 60; // 60px per hour
                html += `<div class="current-time-line" style="top: ${top}px;"></div>`;
            }
        }

        // Render events
        positionedEvents.forEach(event => {
            const startMinutes = this.getEventStartMinutes(event);
            const endMinutes = this.getEventEndMinutes(event);
            const duration = endMinutes - startMinutes;
            const top = ((startMinutes - this.startHour * 60) / 60) * 60; // Offset by start hour
            const height = Math.max((duration / 60) * 60, 24);

            const statusClass = `status-${event.status?.replace(/_/g, '_') || 'received'}`;
            const needsReview = event.status === 'requires_hms_review';
            const hasEmail = (event.attached_email_ids?.length || 0) > 0;

            // Calculate width with 12px right margin for create-event click area
            const adjustedWidth = `calc(${event.width}% - ${(event.width / 100) * 12}px)`;

            html += `
                <div class="event-block ${statusClass}"
                     data-event-id="${event.id}"
                     data-start-minutes="${startMinutes}"
                     data-end-minutes="${endMinutes}"
                     data-column="${event.column}"
                     data-total-columns="${event.totalColumns || 1}"
                     style="top: ${top}px; height: ${height}px; left: ${event.left}%; width: ${adjustedWidth};">
                    <div class="resize-handle resize-handle-top"></div>
                    <div class="event-block-content">
                        <div class="event-block-header">
                            ${needsReview ? '<span class="needs-review-badge">Review</span>' : ''}
                            ${hasEmail ? '<span class="email-indicator"></span>' : ''}
                        </div>
                        <div class="event-block-title">${this.escapeHtml(event.title || 'Untitled')}</div>
                        <div class="event-block-time">${this.formatEventTime(event)}</div>
                        ${event.location ? `<div class="event-block-location">${this.escapeHtml(event.location)}</div>` : ''}
                    </div>
                    <div class="resize-handle resize-handle-bottom"></div>
                </div>
            `;
        });

        return html;
    }

    /**
     * Min-width floor: after blocks are in the DOM, measure each one's real
     * pixel width and tag the ones too narrow to show their text. Compact
     * blocks drop the time/location lines and shrink the title; the full title
     * is exposed as a native hover tooltip and remains in the detail panel.
     *
     * Equal-width columns can get arbitrarily thin when many events run at the
     * same instant, and Phase 4 expansion can't help a genuinely simultaneous
     * set — there's nothing empty to expand into. This keeps those blocks
     * legible instead of mid-word-wrapping a title into a 40px column.
     */
    applyCompactEventBlocks(container) {
        const COMPACT_THRESHOLD = 70; // px
        container.querySelectorAll('.event-block').forEach(el => {
            const width = el.getBoundingClientRect().width;
            const compact = width > 0 && width < COMPACT_THRESHOLD;
            el.classList.toggle('event-block-compact', compact);
            if (compact) {
                const titleEl = el.querySelector('.event-block-title');
                if (titleEl) el.title = titleEl.textContent;
            } else if (el.hasAttribute('title')) {
                el.removeAttribute('title');
            }
        });
    }

    /**
     * Calculate positions for overlapping events (Outlook-style side-by-side)
     */
    calculateEventPositions(events) {
        if (!events.length) return [];

        // Sort by start time, then by end time (longer events first)
        const sorted = [...events].sort((a, b) => {
            const startDiff = this.getEventStartMinutes(a) - this.getEventStartMinutes(b);
            if (startDiff !== 0) return startDiff;
            return this.getEventEndMinutes(b) - this.getEventEndMinutes(a);
        });

        // Helper to check if two events overlap
        const eventsOverlap = (e1, e2) => {
            const start1 = this.getEventStartMinutes(e1);
            const end1 = this.getEventEndMinutes(e1);
            const start2 = this.getEventStartMinutes(e2);
            const end2 = this.getEventEndMinutes(e2);
            return start1 < end2 && start2 < end1;
        };

        // Find overlap groups - events that overlap directly or transitively
        const groups = [];
        const eventToGroup = new Map();

        sorted.forEach(event => {
            // Find all groups this event overlaps with
            const overlappingGroups = new Set();

            for (let i = 0; i < groups.length; i++) {
                for (const groupEvent of groups[i]) {
                    if (eventsOverlap(event, groupEvent)) {
                        overlappingGroups.add(i);
                        break;
                    }
                }
            }

            if (overlappingGroups.size === 0) {
                // No overlaps - create new group
                const newGroup = [event];
                eventToGroup.set(event, groups.length);
                groups.push(newGroup);
            } else if (overlappingGroups.size === 1) {
                // Overlaps with one group - add to it
                const groupIndex = [...overlappingGroups][0];
                groups[groupIndex].push(event);
                eventToGroup.set(event, groupIndex);
            } else {
                // Overlaps with multiple groups - merge them
                const groupIndices = [...overlappingGroups].sort((a, b) => a - b);
                const targetGroup = groups[groupIndices[0]];

                // Merge all overlapping groups into the first one
                for (let i = groupIndices.length - 1; i > 0; i--) {
                    const mergeIndex = groupIndices[i];
                    for (const e of groups[mergeIndex]) {
                        targetGroup.push(e);
                        eventToGroup.set(e, groupIndices[0]);
                    }
                    groups.splice(mergeIndex, 1);
                }

                // Add current event
                targetGroup.push(event);
                eventToGroup.set(event, groupIndices[0]);

                // Update group indices after merge
                for (let i = 0; i < groups.length; i++) {
                    for (const e of groups[i]) {
                        eventToGroup.set(e, i);
                    }
                }
            }
        });

        // Calculate positions within each group
        groups.forEach(group => {
            if (group.length === 1) {
                // Single event - full width
                group[0].column = 0;
                group[0].totalColumns = 1;
                group[0].width = 100;
                group[0].left = 0;
                return;
            }

            // Sort group by start time
            group.sort((a, b) => this.getEventStartMinutes(a) - this.getEventStartMinutes(b));

            // Assign columns within this group
            const columns = [];
            group.forEach(event => {
                const startMin = this.getEventStartMinutes(event);

                // Find first column where event doesn't overlap
                let placed = false;
                for (let col = 0; col < columns.length; col++) {
                    const lastEvent = columns[col][columns[col].length - 1];
                    const lastEnd = this.getEventEndMinutes(lastEvent);

                    if (startMin >= lastEnd) {
                        columns[col].push(event);
                        event.column = col;
                        placed = true;
                        break;
                    }
                }

                if (!placed) {
                    columns.push([event]);
                    event.column = columns.length - 1;
                }
            });

            // Calculate width and left position for this group.
            // Phase 4 (expansion): each event stretches into empty columns to
            // its right, reclaiming space until it hits a column holding an
            // event that overlaps its own time span. This is the Google
            // Calendar behavior — the last events in a group widen back out
            // once their neighbors have ended instead of staying uniformly thin.
            const totalColumns = columns.length;
            const colWidth = 100 / totalColumns;
            group.forEach(event => {
                const evStart = this.getEventStartMinutes(event);
                const evEnd = this.getEventEndMinutes(event);
                let span = 1;
                for (let col = event.column + 1; col < totalColumns; col++) {
                    // Same strict overlap test used everywhere else.
                    const blocked = columns[col].some(other => {
                        const oStart = this.getEventStartMinutes(other);
                        const oEnd = this.getEventEndMinutes(other);
                        return oStart < evEnd && oEnd > evStart;
                    });
                    if (blocked) break;
                    span++;
                }
                event.left = event.column * colWidth;
                event.width = span * colWidth - 1; // keep a 1% gutter on the right
                event.totalColumns = totalColumns;
            });
        });

        return sorted;
    }

    // =========================================================================
    // Day View
    // =========================================================================

    /**
     * Render the day view
     */
    renderDayView(skipAutoScroll = false) {
        const container = this.elements.views.day;
        if (!container) return;

        const date = this.state.currentDate;
        const timedEvents = this.getTimedEventsForDate(date);
        const allDayEvents = this.getAllDayEventsForDate(date);

        // Build all-day section for multi-day events
        const allDayHtml = this.renderDayAllDaySection(date);

        // Expand tab shown when all-day section is collapsed
        const expandTabHtml = allDayHtml ? `<div class="allday-expand-tab" title="Show all-day events">▼</div>` : '';

        // Build scrollable body using CSS grid (no header row - date shown in main header)
        let bodyHtml = `<div class="day-view-body"><div class="day-grid">`;

        // Generate rows for each hour
        for (let hour = this.startHour; hour <= this.endHour; hour++) {
            const timeLabel = hour === 0 ? '12 AM' :
                             hour < 12 ? `${hour} AM` :
                             hour === 12 ? '12 PM' :
                             `${hour - 12} PM`;

            // Time gutter cell
            bodyHtml += `<div class="time-gutter">${timeLabel}</div>`;
            // Day cell for this hour (no today highlighting in day view)
            bodyHtml += `<div class="hour-cell" data-hour="${hour}"></div>`;
        }

        bodyHtml += `</div>`;

        // Events layer (only timed events)
        bodyHtml += `
            <div class="day-events-layer">
                <div class="day-events-column" data-date="${this.formatDate(date)}">
                    ${this.renderDayEvents(timedEvents, false)}
                </div>
            </div>`;

        // Empty state message if no events
        if (timedEvents.length === 0 && allDayEvents.length === 0) {
            bodyHtml += `<div class="calendar-empty-state">No events on this day</div>`;
        }

        bodyHtml += `</div>`;

        container.innerHTML = allDayHtml + expandTabHtml + bodyHtml;
        this.bindEventClicks(container);
        this.bindDragEvents(container);
        this.bindClickToCreate(container);
        this.bindScrollToHidePopup(container.querySelector('.day-view-body'));
        this.bindAllDayEventClicks(container);

        // Restore collapsed state of all-day section if it was previously collapsed
        if (this.state.allDayCollapsed && allDayHtml) {
            const allDaySection = container.querySelector('.day-allday-section');
            if (allDaySection) {
                allDaySection.classList.add('collapsed');
                container.classList.add('allday-collapsed');
            }
        }

        // Ensure text contrast on event blocks
        container.querySelectorAll('.event-block').forEach(el => this.ensureTextContrast(el));

        // Collapse blocks too narrow to show their text (measured post-layout)
        this.applyCompactEventBlocks(container);

        // Auto-scroll to first event or middle (unless skipped)
        if (!skipAutoScroll) {
            this.autoScrollToContent(container.querySelector('.day-view-body'));
        }
    }

    /**
     * Render day view without auto-scroll (for preserving scroll position)
     */
    renderDayViewNoAutoScroll() {
        this.renderDayView(true);
    }

    // =========================================================================
    // Month View
    // =========================================================================

    /**
     * Render the month view
     */
    renderMonthView() {
        const container = this.elements.views.month;
        if (!container) return;

        const year = this.state.currentDate.getFullYear();
        const month = this.state.currentDate.getMonth();
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const startDay = new Date(firstDay);
        startDay.setDate(startDay.getDate() - firstDay.getDay()); // Start from Sunday

        let html = `<div class="month-view-grid">`;

        // Header row
        const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        dayNames.forEach(day => {
            html += `<div class="month-header-cell">${day}</div>`;
        });

        // Day cells (6 weeks)
        const current = new Date(startDay);
        let monthHasEvents = false;
        for (let i = 0; i < 42; i++) {
            const isCurrentMonth = current.getMonth() === month;
            const isToday = current.getTime() === today.getTime();
            const dateStr = this.formatDate(current);
            const dayEvents = this.getEventsForDate(current);
            if (isCurrentMonth && dayEvents.length > 0) monthHasEvents = true;

            html += `
                <div class="month-day-cell${!isCurrentMonth ? ' other-month' : ''}${isToday ? ' today' : ''}"
                     data-date="${dateStr}">
                    <div class="day-number">${current.getDate()}</div>
                    <div class="month-day-events">
                        ${this.renderMonthDayEvents(dayEvents)}
                    </div>
                </div>
            `;

            current.setDate(current.getDate() + 1);
        }

        html += `</div>`;

        // Empty state message if no events in this month
        if (!monthHasEvents) {
            html += `<div class="calendar-empty-state">No events this month</div>`;
        }

        container.innerHTML = html;

        // Bind click events
        container.querySelectorAll('.month-day-cell').forEach(cell => {
            cell.addEventListener('click', (e) => {
                if (e.target.closest('.event-chip') || e.target.closest('.more-events')) return;
                const date = cell.dataset.date;
                this.state.currentDate = new Date(date);
                this.switchView('day');
            });
        });

        this.bindEventClicks(container);
    }

    /**
     * Render event chips for a month day cell
     */
    renderMonthDayEvents(events) {
        const maxVisible = 3;
        let html = '';

        events.slice(0, maxVisible).forEach(event => {
            const statusClass = `status-${event.status?.replace(/_/g, '_') || 'received'}`;
            html += `
                <div class="event-chip" data-event-id="${event.id}">
                    <span class="status-dot ${statusClass}"></span>
                    <span class="event-title">${this.escapeHtml(event.title || 'Untitled')}</span>
                </div>
            `;
        });

        if (events.length > maxVisible) {
            html += `<div class="more-events">+${events.length - maxVisible} more</div>`;
        }

        return html;
    }

    // =========================================================================
    // Schedule View
    // =========================================================================

    /**
     * Render the schedule view - shows current week starting from Sunday
     */
    renderScheduleView() {
        const container = this.elements.views.schedule;
        if (!container) return;

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        // Get the start of the current week (Sunday)
        const weekStart = this.getWeekStart(this.state.currentDate);
        const weekEnd = new Date(weekStart);
        weekEnd.setDate(weekEnd.getDate() + 6);
        weekEnd.setHours(23, 59, 59, 999);

        // Group events by date
        const eventsByDate = this.groupEventsByDate();

        // Generate all 7 days of the week (Sunday to Saturday)
        const weekDays = [];
        for (let i = 0; i < 7; i++) {
            const day = new Date(weekStart);
            day.setDate(weekStart.getDate() + i);
            weekDays.push(day);
        }

        let html = '<div class="schedule-view">';

        // Add week header
        html += `
            <div class="schedule-week-header">
                <span class="week-range">
                    ${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} -
                    ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                </span>
            </div>
        `;

        // Render each day of the week
        weekDays.forEach(date => {
            const dateStr = this.formatDate(date);
            const isToday = date.getTime() === today.getTime();
            const events = eventsByDate[dateStr] || [];

            html += `
                <div class="schedule-day-group${events.length === 0 ? ' empty' : ''}">
                    <div class="schedule-day-header${isToday ? ' today' : ''}">
                        <span class="date-label">${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                        <span class="day-label">${date.toLocaleDateString('en-US', { weekday: 'long' })}</span>
                    </div>
                    <div class="schedule-event-list">
                        ${events.length > 0
                            ? events.map(event => this.renderScheduleEvent(event)).join('')
                            : '<div class="schedule-no-events">No events</div>'
                        }
                    </div>
                </div>
            `;
        });

        html += '</div>';

        container.innerHTML = html;
        this.bindEventClicks(container);
    }

    /**
     * Render a single schedule event row
     */
    renderScheduleEvent(event) {
        const statusClass = `status-${event.status?.replace(/_/g, '_') || 'received'}`;
        const needsReview = event.status === 'requires_hms_review';
        const hasEmail = (event.attached_email_ids?.length || 0) > 0;

        return `
            <div class="schedule-event-row ${statusClass}" data-event-id="${event.id}">
                <div class="schedule-event-time">${this.formatEventTime(event)}</div>
                <div class="schedule-event-content">
                    <div class="schedule-event-title">
                        ${hasEmail ? '<span class="email-indicator"></span>' : ''}
                        ${this.escapeHtml(event.title || 'Untitled')}
                    </div>
                    ${event.location ? `<div class="schedule-event-location">${this.escapeHtml(event.location)}</div>` : ''}
                </div>
                <div class="schedule-event-status">
                    ${needsReview ? '<span class="needs-review-badge">Review</span>' : ''}
                    <span class="status-badge ${statusClass}">${this.formatStatus(event.status)}</span>
                </div>
            </div>
        `;
    }

    // =========================================================================
    // Event Interaction
    // =========================================================================

    /**
     * Bind click events to event elements
     */
    bindEventClicks(container) {
        container.querySelectorAll('[data-event-id]').forEach(el => {
            // Click to show popup (desktop only)
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                // Don't open panel if we just finished dragging
                if (this.wasDragging) {
                    this.wasDragging = false;
                    return;
                }
                // Hide any create preview/popup first
                if (this.createState) {
                    this.hideCreatePreview();
                }
                // Hide tooltip on click
                this.hideTooltip();
                // Open detail panel directly. Focus the first action silently
                // (no ring) so Enter opens it and Tab cycles the panel controls.
                const eventId = el.dataset.eventId;
                this.openDetailPanel(eventId, { focusAction: true, silentFocus: true });
            });

            // Double-click to open event editing modal
            el.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                e.preventDefault();
                // Hide any visible popup or tooltip
                this.hidePopup(true);
                this.hideTooltip();
                // Open the event editing modal
                const eventId = el.dataset.eventId;
                if (eventId && typeof openEventEditingModal === 'function') {
                    openEventEditingModal(eventId);
                } else if (eventId) {
                    // Fallback: navigate to event editing page
                    window.location.href = `/event-editing/${eventId}/`;
                }
            });

            // Hover to show tooltip
            el.addEventListener('mouseenter', (e) => {
                // Don't show during drag/create operations
                if (this.dragState || (this.createState && this.createState.isMouseDown) || this.wasDragging) return;
                // Don't show if popup is visible
                if (this.popup && this.popup.classList.contains('visible')) return;

                const eventId = el.dataset.eventId;
                const eventData = this.state.events.find(ev => String(ev.id) === String(eventId));
                if (!eventData || !eventData.title) return;

                // Format tooltip text - special format for all-day events
                let tooltipText = eventData.title;
                if (el.classList.contains('allday-event-bar')) {
                    const startDate = new Date(eventData.start_date || eventData.date);
                    const endDate = new Date(eventData.end_date || eventData.start_date || eventData.date);
                    const formatDate = (d) => `${d.getMonth() + 1}/${d.getDate()}`;

                    if (this.isDateRangeEvent(eventData)) {
                        // Format: "[Range] TITLE: MM/DD - MM/DD: [TIME NOTES]"
                        const timeNotes = eventData.time_notes ? `: ${eventData.time_notes}` : '';
                        tooltipText = `[Range] ${eventData.title}: ${formatDate(startDate)} - ${formatDate(endDate)}${timeNotes}`;
                    } else {
                        // Format: "TITLE: MM/DD - MM/DD"
                        tooltipText = `${eventData.title}: ${formatDate(startDate)} - ${formatDate(endDate)}`;
                    }
                }

                this.showTooltip(tooltipText, e.clientX, e.clientY);
            });

            el.addEventListener('mousemove', (e) => {
                // Update tooltip position as mouse moves
                if (this.tooltip && this.tooltip.classList.contains('visible')) {
                    this.updateTooltipPosition(e.clientX, e.clientY);
                }
            });

            el.addEventListener('mouseleave', () => {
                this.hideTooltip();
            });
        });
    }

    /**
     * Bind click events to all-day event bars
     * Note: Basic click/hover handling is already done by bindEventClicks via [data-event-id]
     * This method only adds collapse/expand behavior, NOT click-to-show-popup
     */
    bindAllDayEventClicks(container) {
        // NOTE: Click handlers for showing popup are already bound by bindEventClicks()
        // Do NOT add duplicate click handlers here - it causes popup to toggle on then immediately off

        // Bind collapse button
        const collapseBtn = container.querySelector('.allday-collapse-btn');
        if (collapseBtn) {
            collapseBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAllDaySection(container);
            });
        }

        // Bind click on entire gutter area to collapse/expand
        const allDayGutter = container.querySelector('.allday-gutter');
        if (allDayGutter) {
            allDayGutter.style.cursor = 'pointer';
            allDayGutter.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAllDaySection(container);
            });

            // Show tooltip on hover
            allDayGutter.addEventListener('mouseenter', (e) => {
                this.showTooltip('Hide all-day events', e.clientX, e.clientY);
            });
            allDayGutter.addEventListener('mousemove', (e) => {
                if (this.tooltip && this.tooltip.classList.contains('visible')) {
                    this.updateTooltipPosition(e.clientX, e.clientY);
                }
            });
            allDayGutter.addEventListener('mouseleave', () => {
                this.hideTooltip();
            });
        }

        // Bind expand tab (shows when collapsed)
        const expandTab = container.querySelector('.allday-expand-tab');
        if (expandTab) {
            expandTab.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleAllDaySection(container);
            });

            // Show tooltip on hover
            expandTab.addEventListener('mouseenter', (e) => {
                this.showTooltip('Show all-day events', e.clientX, e.clientY);
            });
            expandTab.addEventListener('mousemove', (e) => {
                if (this.tooltip && this.tooltip.classList.contains('visible')) {
                    this.updateTooltipPosition(e.clientX, e.clientY);
                }
            });
            expandTab.addEventListener('mouseleave', () => {
                this.hideTooltip();
            });
        }

        // Position the expand tab at the bottom of the header/all-day section
        this.positionExpandTab(container);
    }

    /**
     * Handle click on all-day event bar - show popup
     */
    handleAllDayEventClick(e, bar) {
        const eventId = bar.dataset.eventId;
        if (!eventId) return;

        // Open detail panel directly
        this.openDetailPanel(eventId);
    }

    /**
     * Toggle collapse state of all-day section
     */
    toggleAllDaySection(container) {
        const allDaySection = container.querySelector('.week-allday-section, .day-allday-section');
        const headerRow = container.querySelector('.week-header-row');

        if (!allDaySection) return;

        const isCollapsed = allDaySection.classList.toggle('collapsed');

        // Save collapsed state to persist across re-renders
        this.state.allDayCollapsed = isCollapsed;

        // Add/remove class on container for CSS selector (expand tab visibility)
        container.classList.toggle('allday-collapsed', isCollapsed);

        // Toggle shadow between header and all-day section
        if (headerRow) {
            headerRow.classList.toggle('has-allday-section', !isCollapsed);
        }

        // Reposition the expand tab
        this.positionExpandTab(container);
    }

    /**
     * Position the expand tab at the bottom of the dates header (always)
     */
    positionExpandTab(container) {
        const expandTab = container.querySelector('.allday-expand-tab');
        if (!expandTab) return;

        // Always position at bottom of header row
        const headerRow = container.querySelector('.week-header-row, .day-header-row');

        let topPosition = 0;

        if (headerRow) {
            topPosition = headerRow.offsetHeight;
        }

        expandTab.style.top = `${topPosition}px`;
    }

    /**
     * NOTE: startAllDayDrag and startAllDayResize are kept for reference but disabled.
     * All-day event drag and resize is currently disabled.
     */
    handleAllDayMouseDown_DISABLED(e, bar, container) {
        // Drag/resize functionality disabled
    }

    /**
     * Start dragging an all-day event
     */
    startAllDayDrag(e, bar, container) {
        const eventId = bar.dataset.eventId;
        const startX = e.clientX;
        const startY = e.clientY;
        let isDragging = false;
        let hasMoved = false;
        let currentDayOffset = 0;
        const threshold = 5; // pixels before considering it a drag

        // Get the header day columns to determine day boundaries
        const headerDays = container.querySelectorAll('.week-header-row .day-column-header');
        if (headerDays.length !== 7) return;

        // Build array of day column boundaries
        const dayBounds = [];
        headerDays.forEach((day, i) => {
            const rect = day.getBoundingClientRect();
            dayBounds.push({ left: rect.left, right: rect.right, center: rect.left + rect.width / 2 });
        });

        // Calculate average day width for movement calculation
        const dayWidth = (dayBounds[6].right - dayBounds[0].left) / 7;

        // Get event data
        const event = this.state.events.find(ev => ev.id === eventId);
        if (!event) return;

        // Parse dates without timezone issues
        const [startYear, startMonth, startDay] = event.start_date.split('-').map(Number);
        const [endYear, endMonth, endDay] = (event.end_date || event.start_date).split('-').map(Number);
        const originalStartDate = new Date(startYear, startMonth - 1, startDay);
        const originalEndDate = new Date(endYear, endMonth - 1, endDay);
        const eventDuration = Math.round((originalEndDate - originalStartDate) / (1000 * 60 * 60 * 24));

        const weekStart = this.getWeekStart(this.state.currentDate);

        // Calculate the original day column of the event
        const originalDayCol = Math.round((originalStartDate - weekStart) / (1000 * 60 * 60 * 24));

        // Store original bar position
        const originalGridColumn = bar.style.gridColumn;

        const handleMouseMove = (moveEvent) => {
            const deltaX = moveEvent.clientX - startX;
            const deltaY = moveEvent.clientY - startY;

            // Check if we've moved enough to start dragging
            if (!isDragging && (Math.abs(deltaX) > threshold || Math.abs(deltaY) > threshold)) {
                isDragging = true;
                bar.classList.add('allday-dragging');
                // Hide popup and tooltip when drag starts
                this.hidePopup(true);
                this.hideTooltip();
            }

            if (isDragging) {
                hasMoved = true;

                // Calculate day offset based on pixel movement
                currentDayOffset = Math.round(deltaX / dayWidth);

                // Calculate where the event would land
                const newDayCol = originalDayCol + currentDayOffset;

                // Visual feedback: show where it will land within the visible week
                if (newDayCol < 0) {
                    bar.style.gridColumn = `1 / span 1`;
                    bar.classList.add('dragging-prev-week');
                    bar.classList.remove('dragging-next-week');
                } else if (newDayCol > 6) {
                    bar.style.gridColumn = `7 / span 1`;
                    bar.classList.add('dragging-next-week');
                    bar.classList.remove('dragging-prev-week');
                } else {
                    const spanCols = Math.min(eventDuration + 1, 7 - newDayCol);
                    bar.style.gridColumn = `${newDayCol + 1} / span ${Math.max(1, spanCols)}`;
                    bar.classList.remove('dragging-prev-week', 'dragging-next-week');
                }
            }
        };

        const handleMouseUp = async (upEvent) => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);

            bar.classList.remove('allday-dragging', 'dragging-prev-week', 'dragging-next-week');

            if (isDragging && hasMoved && currentDayOffset !== 0) {
                // Calculate new dates by adding the day offset
                const newStartDate = new Date(originalStartDate);
                newStartDate.setDate(newStartDate.getDate() + currentDayOffset);
                const newEndDate = new Date(originalEndDate);
                newEndDate.setDate(newEndDate.getDate() + currentDayOffset);

                // Format dates as YYYY-MM-DD strings
                const formatDate = (d) => {
                    const year = d.getFullYear();
                    const month = String(d.getMonth() + 1).padStart(2, '0');
                    const day = String(d.getDate()).padStart(2, '0');
                    return `${year}-${month}-${day}`;
                };

                const newStartStr = formatDate(newStartDate);
                const newEndStr = formatDate(newEndDate);

                // Check if we need to navigate to a different week
                const newDayCol = originalDayCol + currentDayOffset;
                const needsNavigation = newDayCol < 0 || newDayCol > 6;

                // Update event via API and navigate if needed
                await this.updateAllDayEventDates(eventId, newStartStr, newEndStr, needsNavigation ? newStartDate : null);
            } else if (!hasMoved) {
                // It was a click, not a drag - open the event modal
                if (typeof openEventEditingModal === 'function') {
                    openEventEditingModal(eventId);
                }
            } else {
                // Drag happened but no offset change - restore original position
                bar.style.gridColumn = originalGridColumn;
            }
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }

    /**
     * Start resizing an all-day event
     */
    startAllDayResize(e, bar, resizeType, container) {
        const eventId = bar.dataset.eventId;
        const startX = e.clientX;

        // Get the header day columns to determine day width
        const headerDays = container.querySelectorAll('.week-header-row .day-column-header');
        if (headerDays.length !== 7) return;
        const firstRect = headerDays[0].getBoundingClientRect();
        const lastRect = headerDays[6].getBoundingClientRect();
        const dayWidth = (lastRect.right - firstRect.left) / 7;

        // Get event data
        const event = this.state.events.find(ev => ev.id === eventId);
        if (!event) return;

        // Parse dates without timezone issues
        const [startYear, startMonth, startDay] = event.start_date.split('-').map(Number);
        const [endYear, endMonth, endDay] = (event.end_date || event.start_date).split('-').map(Number);
        const originalStartDate = new Date(startYear, startMonth - 1, startDay);
        const originalEndDate = new Date(endYear, endMonth - 1, endDay);

        bar.classList.add('allday-resizing');
        // Hide popup and tooltip when resizing starts
        this.hidePopup(true);
        this.hideTooltip();

        const formatDate = (d) => {
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        };

        const handleMouseMove = (moveEvent) => {
            const deltaX = moveEvent.clientX - startX;
            const dayOffset = Math.round(deltaX / dayWidth);

            // Calculate new dates based on resize type
            let newStartDate = new Date(originalStartDate);
            let newEndDate = new Date(originalEndDate);

            if (resizeType === 'start') {
                newStartDate.setDate(newStartDate.getDate() + dayOffset);
                // Don't allow start date to go past end date
                if (newStartDate > newEndDate) {
                    newStartDate = new Date(newEndDate);
                }
            } else {
                newEndDate.setDate(newEndDate.getDate() + dayOffset);
                // Don't allow end date to go before start date
                if (newEndDate < newStartDate) {
                    newEndDate = new Date(newStartDate);
                }
            }

            // Update visual width
            const weekStart = this.getWeekStart(this.state.currentDate);
            const weekStartTime = weekStart.getTime();
            const weekEndTime = weekStartTime + 6 * 24 * 60 * 60 * 1000;

            // Clamp dates to visible week
            const visibleStart = new Date(Math.max(newStartDate.getTime(), weekStartTime));
            const visibleEnd = new Date(Math.min(newEndDate.getTime(), weekEndTime));

            const startCol = Math.round((visibleStart.getTime() - weekStartTime) / (1000 * 60 * 60 * 24));
            const endCol = Math.round((visibleEnd.getTime() - weekStartTime) / (1000 * 60 * 60 * 24));
            const spanCols = endCol - startCol + 1;

            bar.style.gridColumn = `${startCol + 1} / span ${Math.max(1, spanCols)}`;
        };

        const handleMouseUp = async (upEvent) => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);

            bar.classList.remove('allday-resizing');

            const deltaX = upEvent.clientX - startX;
            const dayOffset = Math.round(deltaX / dayWidth);

            if (dayOffset !== 0) {
                // Calculate final dates
                let newStartDate = new Date(originalStartDate);
                let newEndDate = new Date(originalEndDate);

                if (resizeType === 'start') {
                    newStartDate.setDate(newStartDate.getDate() + dayOffset);
                    if (newStartDate > newEndDate) {
                        newStartDate = new Date(newEndDate);
                    }
                } else {
                    newEndDate.setDate(newEndDate.getDate() + dayOffset);
                    if (newEndDate < newStartDate) {
                        newEndDate = new Date(newStartDate);
                    }
                }

                // Update event via API
                await this.updateAllDayEventDates(eventId, formatDate(newStartDate), formatDate(newEndDate));
            }
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }

    /**
     * Update all-day event dates via API
     * @param {string} eventId - The event ID
     * @param {string} newStartDate - The new start date as YYYY-MM-DD string
     * @param {string} newEndDate - The new end date as YYYY-MM-DD string
     * @param {Date|null} navigateToDate - If provided, navigate to the week containing this date after update
     */
    async updateAllDayEventDates(eventId, newStartDate, newEndDate, navigateToDate = null) {
        try {
            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    start_date: newStartDate,
                    end_date: newEndDate
                })
            });

            if (response.ok) {
                // Navigate to the new week if the event moved outside current week
                if (navigateToDate) {
                    this.state.currentDate = new Date(navigateToDate);
                }
                // Refresh events to get updated data
                await this.fetchEvents();
                this.renderCurrentView();
                this.updatePeriodLabel();
                this.syncMiniCalendar();
            } else {
                console.error('Failed to update event dates:', await response.text());
                // Re-render to reset visual state
                this.renderCurrentView();
            }
        } catch (error) {
            console.error('Error updating event dates:', error);
            this.renderCurrentView();
        }
    }


    /**
     * Initialize the event title tooltip
     */
    initTooltip() {
        // Create tooltip element
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'calendar-tooltip';
        document.body.appendChild(this.tooltip);
    }

    /**
     * Show tooltip above the mouse cursor
     */
    showTooltip(text, mouseX, mouseY) {
        if (!this.tooltip) return;

        // Set content
        this.tooltip.textContent = text;
        this.tooltip.classList.add('visible');

        // Position above mouse
        this.updateTooltipPosition(mouseX, mouseY);
    }

    /**
     * Update tooltip position to be right and below the mouse cursor
     */
    updateTooltipPosition(mouseX, mouseY) {
        if (!this.tooltip) return;

        const tooltipRect = this.tooltip.getBoundingClientRect();
        const offset = 12;

        // Position to the right and below the cursor
        let left = mouseX + offset;
        let top = mouseY + offset;

        // If tooltip would go off right edge, show to the left of cursor
        if (left + tooltipRect.width > window.innerWidth - 10) {
            left = mouseX - tooltipRect.width - offset;
        }

        // If tooltip would go off bottom, show above cursor
        if (top + tooltipRect.height > window.innerHeight - 10) {
            top = mouseY - tooltipRect.height - offset;
        }

        // Keep within bounds
        left = Math.max(10, left);
        top = Math.max(10, top);

        this.tooltip.style.left = `${left}px`;
        this.tooltip.style.top = `${top}px`;
    }

    /**
     * Hide the tooltip
     */
    hideTooltip() {
        if (this.tooltip) {
            this.tooltip.classList.remove('visible');
        }
    }

    /**
     * Bind scroll event to hide popup and tooltip
     */
    bindScrollToHidePopup(scrollContainer) {
        if (!scrollContainer) return;

        scrollContainer.addEventListener('scroll', () => {
            // Hide popup and tooltip when scrolling
            this.hidePopup(true);
            this.hideTooltip();
            // Also hide create preview if active
            if (this.createState) {
                this.hideCreatePreview();
            }
        });
    }

    /**
     * Bind click events on date headers to open day view
     */
    bindDateHeaderClicks(container) {
        const headerRow = container.querySelector('.week-header-row');
        if (!headerRow) return;

        headerRow.querySelectorAll('.day-column-header').forEach((header, index) => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', () => {
                // Calculate the date for this column
                const weekStart = this.getWeekStart(this.state.currentDate);
                const clickedDate = new Date(weekStart);
                clickedDate.setDate(clickedDate.getDate() + index);

                // Set the current date and switch to day view
                this.state.currentDate = clickedDate;
                this.switchView('day');
            });
        });
    }

    /**
     * Handle event click - open the existing editing modal
     */
    handleEventClick(eventId) {
        // Track in recently viewed (shared across pages via sessionStorage)
        const eventData = this.state.events.find(e => String(e.id) === String(eventId));
        if (eventData) {
            this._addToRecentlyViewed(eventData);
        }

        // Open the overlay detail panel
        this.openDetailPanel(eventId);
    }

    /**
     * Add an event to the cross-page recently viewed list in sessionStorage
     */
    _addToRecentlyViewed(eventData) {
        try {
            let recent = JSON.parse(sessionStorage.getItem('hilldesk_recently_viewed') || '[]');
            recent = recent.filter(e => e.id != eventData.id);
            let shortDate = '';
            if (eventData.start_date || eventData.date) {
                try {
                    const dateStr = eventData.start_date || eventData.date;
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

    // =========================================================================
    // Utility Methods
    // =========================================================================

    /**
     * Get the start of the week (Sunday)
     */
    getWeekStart(date) {
        const d = new Date(date);
        const day = d.getDay();
        d.setDate(d.getDate() - day);
        d.setHours(0, 0, 0, 0);
        return d;
    }

    /**
     * Format date as YYYY-MM-DD
     */
    formatDate(date) {
        return date.toISOString().split('T')[0];
    }

    /**
     * Get events for a specific date (includes multi-day events spanning this date)
     */
    getEventsForDate(date) {
        const dateStr = this.formatDate(date);
        return this.state.events.filter(event => {
            const startDate = event.start_date;
            const endDate = event.end_date || event.start_date;
            // Check if date falls within the event's date range
            return dateStr >= startDate && dateStr <= endDate;
        });
    }

    /**
     * Check if an event is a multi-day event
     */
    isMultiDayEvent(event) {
        if (!event.start_date || !event.end_date) return false;
        return event.start_date !== event.end_date;
    }

    /**
     * Check if an event is an all-day event (no time specified or is_longer_than_day flag)
     */
    isAllDayEvent(event) {
        // No start time specified = all-day
        if (!event.start_time) return true;
        // Flag from backend
        if (event.is_longer_than_day === true) return true;
        // Date range events are shown in the all-day section
        if (event.is_date_range === true) return true;
        // Multi-day events are treated as all-day for display purposes
        if (this.isMultiDayEvent(event)) return true;
        return false;
    }

    /**
     * Check if an event is a date range event (uses is_date_range field from model)
     */
    isDateRangeEvent(event) {
        return event.is_date_range === true;
    }

    /**
     * Get multi-day/all-day events for the week view
     */
    getMultiDayEventsForWeek(weekStart, weekEnd) {
        const startStr = this.formatDate(weekStart);
        const endStr = this.formatDate(weekEnd);

        // First, filter to all-day events that overlap with this week
        const allDayEvents = this.state.events.filter(event => {
            if (!this.isAllDayEvent(event)) return false;
            // Use original_start_date if this is a continuation, otherwise use start_date
            const eventStart = event.original_start_date || event.start_date;
            const eventEnd = event.end_date || event.start_date;
            // Event overlaps with week
            return eventStart <= endStr && eventEnd >= startStr;
        });

        // Deduplicate by event ID (keep the one with the earliest start_date or original_start_date)
        const eventMap = new Map();
        allDayEvents.forEach(event => {
            const id = event.id;
            if (!eventMap.has(id)) {
                // For continuations, use original dates for proper span calculation
                if (event.is_continuation && event.original_start_date) {
                    eventMap.set(id, {
                        ...event,
                        start_date: event.original_start_date,
                        title: event.title.replace(' (cont.)', '')  // Remove cont. suffix
                    });
                } else {
                    eventMap.set(id, event);
                }
            }
        });

        return Array.from(eventMap.values());
    }

    /**
     * Get timed (non-all-day) events for a specific date
     */
    getTimedEventsForDate(date) {
        const dateStr = this.formatDate(date);
        return this.state.events.filter(event => {
            const startDate = event.start_date;
            const endDate = event.end_date || event.start_date;
            const isInRange = dateStr >= startDate && dateStr <= endDate;

            // Exclude multi-day and all-day events
            if (this.isAllDayEvent(event)) {
                return false;
            }
            return isInRange;
        });
    }

    /**
     * Get all-day events for a specific date (for day view)
     */
    getAllDayEventsForDate(date) {
        const dateStr = this.formatDate(date);
        return this.state.events.filter(event => {
            if (!this.isAllDayEvent(event)) return false;
            const startDate = event.start_date;
            const endDate = event.end_date || event.start_date;
            return dateStr >= startDate && dateStr <= endDate;
        });
    }

    /**
     * Get the column span information for an event in the week
     */
    getEventSpanInfo(event, weekStart) {
        // Parse dates without timezone issues by extracting components directly
        const [startYear, startMonth, startDay] = event.start_date.split('-').map(Number);
        const eventStartDate = new Date(startYear, startMonth - 1, startDay);

        const endDateStr = event.end_date || event.start_date;
        const [endYear, endMonth, endDay] = endDateStr.split('-').map(Number);
        const eventEndDate = new Date(endYear, endMonth - 1, endDay);

        // Normalize weekStart to midnight (it should already be, but ensure consistency)
        const weekStartNorm = new Date(weekStart);
        weekStartNorm.setHours(0, 0, 0, 0);
        const weekStartTime = weekStartNorm.getTime();

        // Calculate day differences using rounded division to avoid timezone edge cases
        const msPerDay = 24 * 60 * 60 * 1000;
        const startDayDiff = Math.round((eventStartDate.getTime() - weekStartTime) / msPerDay);
        const startCol = Math.max(0, startDayDiff);

        // Calculate end column
        const endDayDiff = Math.round((eventEndDate.getTime() - weekStartTime) / msPerDay);
        const endCol = Math.min(6, endDayDiff);

        // Span count
        const spanCols = endCol - startCol + 1;

        // Check if event extends beyond visible week
        const continuesLeft = startDayDiff < 0;
        const continuesRight = endDayDiff > 6;

        return { startCol, endCol, spanCols, continuesLeft, continuesRight };
    }

    /**
     * Get event duration in days
     */
    getEventDurationDays(event) {
        if (!event.end_date) return 1;
        // Parse dates without timezone issues
        const [startYear, startMonth, startDay] = event.start_date.split('-').map(Number);
        const [endYear, endMonth, endDay] = event.end_date.split('-').map(Number);
        const start = new Date(startYear, startMonth - 1, startDay);
        const end = new Date(endYear, endMonth - 1, endDay);
        return Math.round((end - start) / (1000 * 60 * 60 * 24)) + 1;
    }

    /**
     * Calculate which row each multi-day event should occupy (prevents overlapping bars)
     */
    calculateAllDayEventRows(events, weekStart) {
        const rows = [];

        // Sort events by start date, then by duration (longer first)
        const sorted = [...events].sort((a, b) => {
            const startDiff = a.start_date.localeCompare(b.start_date);
            if (startDiff !== 0) return startDiff;
            // Longer events first
            const aDuration = this.getEventDurationDays(a);
            const bDuration = this.getEventDurationDays(b);
            return bDuration - aDuration;
        });

        sorted.forEach(event => {
            const { startCol, endCol } = this.getEventSpanInfo(event, weekStart);

            // Find first row where this event fits
            let placed = false;
            for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                const row = rows[rowIndex];
                const hasConflict = row.some(existing => {
                    const existingInfo = this.getEventSpanInfo(existing, weekStart);
                    return !(endCol < existingInfo.startCol || startCol > existingInfo.endCol);
                });

                if (!hasConflict) {
                    row.push(event);
                    placed = true;
                    break;
                }
            }

            if (!placed) {
                rows.push([event]);
            }
        });

        return rows;
    }

    /**
     * Render the all-day/multi-day events section for week view
     */
    renderAllDaySection(weekStart, weekEnd, today) {
        const multiDayEvents = this.getMultiDayEventsForWeek(weekStart, weekEnd);

        if (multiDayEvents.length === 0) {
            return ''; // No all-day section if no multi-day events
        }

        // Calculate spanning layout
        const rows = this.calculateAllDayEventRows(multiDayEvents, weekStart);
        const rowHeight = 26; // pixels per event row
        const sectionHeight = Math.max(rows.length * rowHeight + 8, 34); // minimum height

        // Check if section should be compact (single row - hide label)
        const isCompact = rows.length === 1;

        // Build background cells for each day (to highlight today)
        let dayCellsHtml = '<div class="allday-day-backgrounds">';
        for (let i = 0; i < 7; i++) {
            const dayDate = new Date(weekStart);
            dayDate.setDate(dayDate.getDate() + i);
            const isToday = this.formatDate(dayDate) === this.formatDate(today);
            dayCellsHtml += `<div class="allday-day-cell${isToday ? ' today' : ''}"></div>`;
        }
        dayCellsHtml += '</div>';

        let html = `
            <div class="week-allday-section${isCompact ? ' compact' : ''}" style="height: ${sectionHeight}px;">
                <div class="allday-gutter">
                    <span class="allday-label">All day</span>
                    <button class="allday-collapse-btn" title="Hide all-day events">▲</button>
                </div>
                <div class="allday-events-grid">
                    ${dayCellsHtml}
                    <div class="allday-grid-dividers">
                        <div class="allday-divider"></div>
                        <div class="allday-divider"></div>
                        <div class="allday-divider"></div>
                        <div class="allday-divider"></div>
                        <div class="allday-divider"></div>
                        <div class="allday-divider"></div>
                    </div>`;

        // Render each row of spanning events (no resize handles - drag/resize disabled)
        rows.forEach((row, rowIndex) => {
            row.forEach(event => {
                const { startCol, spanCols, continuesLeft, continuesRight } = this.getEventSpanInfo(event, weekStart);
                const statusClass = `status-${(event.status || 'received').replace(/_/g, '_')}`;
                const continuesClasses = `${continuesLeft ? ' continues-left' : ''}${continuesRight ? ' continues-right' : ''}`;
                const dateRangeClass = this.isDateRangeEvent(event) ? ' date-range' : '';
                const titleSuffix = continuesLeft ? ' (cont.)' : '';

                html += `
                    <div class="allday-event-bar ${statusClass}${continuesClasses}${dateRangeClass}"
                         data-event-id="${event.id}"
                         data-start-date="${event.start_date}"
                         data-end-date="${event.end_date || event.start_date}"
                         style="
                             grid-column: ${startCol + 1} / span ${spanCols};
                             grid-row: ${rowIndex + 1};
                         ">
                        <span class="allday-event-title">${this.escapeHtml(event.title || event.group || 'Untitled')}${titleSuffix}</span>
                    </div>`;
            });
        });

        html += `</div></div>`;
        return html;
    }

    /**
     * Render all-day section for day view
     */
    renderDayAllDaySection(date) {
        const allDayEvents = this.getAllDayEventsForDate(date);

        if (allDayEvents.length === 0) {
            return '';
        }

        const rowHeight = 26;
        const sectionHeight = Math.max(allDayEvents.length * rowHeight + 8, 34);

        let html = `
            <div class="day-allday-section" style="height: ${sectionHeight}px;">
                <div class="allday-gutter">
                    <span class="allday-label">All day</span>
                    <button class="allday-collapse-btn" title="Hide all-day events">▲</button>
                </div>
                <div class="allday-events-list">`;

        allDayEvents.forEach(event => {
            const statusClass = `status-${(event.status || 'received').replace(/_/g, '_')}`;
            const dateRangeClass = this.isDateRangeEvent(event) ? ' date-range' : '';
            html += `
                <div class="allday-event-bar ${statusClass}${dateRangeClass}" data-event-id="${event.id}">
                    <span class="allday-event-title">${this.escapeHtml(event.title || event.group || 'Untitled')}</span>
                </div>`;
        });

        html += `</div></div>`;
        return html;
    }

    /**
     * Group events by date
     */
    groupEventsByDate() {
        const groups = {};
        this.state.events.forEach(event => {
            const date = event.start_date;
            if (!groups[date]) {
                groups[date] = [];
            }
            groups[date].push(event);
        });
        return groups;
    }

    /**
     * Get event start time in minutes since midnight
     */
    getEventStartMinutes(event) {
        if (!event.start_time) return 9 * 60; // Default to 9 AM
        const [hours, minutes] = event.start_time.split(':').map(Number);
        return hours * 60 + minutes;
    }

    /**
     * Get event end time in minutes since midnight
     */
    getEventEndMinutes(event) {
        if (!event.end_time) {
            return this.getEventStartMinutes(event) + 60; // Default 1 hour
        }
        const [hours, minutes] = event.end_time.split(':').map(Number);
        return hours * 60 + minutes;
    }

    /**
     * Format event time for display
     */
    formatEventTime(event) {
        if (!event.start_time) return '';

        const formatTime = (timeStr) => {
            const [hours, minutes] = timeStr.split(':').map(Number);
            const period = hours >= 12 ? 'PM' : 'AM';
            const displayHours = hours % 12 || 12;
            return minutes === 0 ? `${displayHours} ${period}` : `${displayHours}:${String(minutes).padStart(2, '0')} ${period}`;
        };

        const start = formatTime(event.start_time);
        if (event.end_time) {
            const end = formatTime(event.end_time);
            return `${start} - ${end}`;
        }
        return start;
    }

    /**
     * Format status for display
     */
    formatStatus(status) {
        if (!status) return 'Received';
        return status
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Start updating current time line
     */
    startCurrentTimeUpdater() {
        setInterval(() => {
            if (this.state.currentView === 'week' || this.state.currentView === 'day') {
                this.updateCurrentTimeLine();
            }
        }, 60000); // Update every minute
    }

    /**
     * Update the current time line position
     */
    updateCurrentTimeLine() {
        const lines = document.querySelectorAll('.current-time-line');
        const now = new Date();
        const minutes = (now.getHours() - 5) * 60 + now.getMinutes();
        const top = (minutes / 60) * 60;

        lines.forEach(line => {
            line.style.top = `${top}px`;
        });
    }

    /**
     * Check if any filters are actively filtering (not showing all)
     */
    hasActiveFilters() {
        return this.state.filters.status.length > 0 ||
               this.state.filters.category.length > 0 ||
               this.state.filters.format.length > 0 ||
               this.state.filters.staff.length > 0 ||
               this.state.filters.source.length > 0 ||
               this.state.filters.myEvents ||
               this.state.filters.overlappingOnly;
    }

    /**
     * Update the Filters button visual state based on active filters
     */
    updateFiltersButtonState() {
        if (this.elements.filtersToggleBtn) {
            if (this.hasActiveFilters()) {
                this.elements.filtersToggleBtn.classList.add('has-filters');
            } else {
                this.elements.filtersToggleBtn.classList.remove('has-filters');
            }
        }
    }

    // =========================================================================
    // Event Hover Popup
    // =========================================================================

    /**
     * Initialize the popup element and bind its events
     */
    initPopup() {
        this.popup = document.getElementById('event-hover-popup');
        if (!this.popup) return;

        // Move popup to body to avoid transform containment issues
        // (ancestors with transform or will-change:transform create new containing blocks for fixed elements)
        document.body.appendChild(this.popup);

        // Prevent clicks inside popup from closing it
        this.popup.addEventListener('click', (e) => e.stopPropagation());

        // "View Details" button opens the detail panel overlay
        const viewDetailsBtn = this.popup.querySelector('.popup-view-details');
        if (viewDetailsBtn) {
            viewDetailsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const popupContent = this.popup.querySelector('.popup-content');
                const eventId = popupContent?.dataset.eventId;
                if (eventId) {
                    this.hidePopup(true);
                    this.openDetailPanel(eventId);
                }
            });
        }

        // Status dropdown change handler
        const statusSelect = this.popup.querySelector('.popup-status-select');
        if (statusSelect) {
            statusSelect.addEventListener('click', (e) => e.stopPropagation());
            statusSelect.addEventListener('change', (e) => this.handlePopupStatusChange(e));
        }

        // Click outside popup to close it
        document.addEventListener('click', (e) => {
            if (this.popup.classList.contains('visible') && !this.popup.contains(e.target)) {
                this.hidePopup(true);
            }
        });

        // Escape key to close popup
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.popup.classList.contains('visible')) {
                this.hidePopup(true);
            }
        });
    }

    /**
     * Show the popup for a clicked event element
     */
    showPopup(eventEl, mouseEvent) {
        if (!this.popup) return;

        // If popup is already visible for this event, hide it (toggle behavior)
        if (this.popup.classList.contains('visible') &&
            this.currentHoveredEvent?.element === eventEl) {
            this.hidePopup(true);
            return;
        }

        // Get event data
        const eventId = eventEl.dataset.eventId;
        const eventData = this.state.events.find(e => String(e.id) === String(eventId));

        if (!eventData) return;

        // Store reference
        this.currentHoveredEvent = { element: eventEl, data: eventData };

        // Populate popup content
        this.populatePopup(eventData);

        // Position popup at mouse cursor and show immediately
        this.positionPopupAtCursor(mouseEvent);
        this.popup.classList.add('visible');
    }

    /**
     * Hide the popup
     */
    hidePopup(immediate = false) {
        if (!this.popup) return;
        this.popup.classList.remove('visible');
        this.currentHoveredEvent = null;
        this.popupMouseOrigin = null;
        this.stopMouseDistanceMonitor();
    }

    /**
     * Position the popup above the mouse cursor, centered horizontally
     */
    positionPopupAtCursor(mouseEvent) {
        if (!this.popup || !mouseEvent) return;

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const gap = 12;

        // Temporarily show popup off-screen to measure it
        this.popup.style.visibility = 'hidden';
        this.popup.style.left = '-9999px';
        this.popup.style.top = '-9999px';
        this.popup.classList.add('visible');

        // Force reflow to get accurate dimensions
        const popupWidth = this.popup.offsetWidth;
        const popupHeight = this.popup.offsetHeight;

        // Get mouse position
        const mouseX = mouseEvent.clientX;
        const mouseY = mouseEvent.clientY;

        // Store mouse position for distance checking
        this.popupMouseOrigin = { x: mouseX, y: mouseY };

        // Calculate position - prefer above mouse, centered horizontally
        let left = mouseX - (popupWidth / 2);
        let top = mouseY - popupHeight - gap;

        // If popup would go off top edge, position below cursor instead
        if (top < gap) {
            top = mouseY + gap;
        }

        // Ensure popup stays within horizontal viewport bounds
        left = Math.max(gap, Math.min(left, viewportWidth - popupWidth - gap));

        // Ensure popup stays within vertical viewport bounds
        top = Math.max(gap, Math.min(top, viewportHeight - popupHeight - gap));

        // Apply final position and make visible
        this.popup.style.left = `${left}px`;
        this.popup.style.top = `${top}px`;
        this.popup.style.visibility = 'visible';

        // Start monitoring mouse distance
        this.startMouseDistanceMonitor();
    }

    /**
     * Start monitoring mouse distance from popup to auto-close
     */
    startMouseDistanceMonitor() {
        // Remove any existing listener
        this.stopMouseDistanceMonitor();

        this.mouseDistanceHandler = (e) => {
            if (!this.popup || !this.popup.classList.contains('visible')) {
                this.stopMouseDistanceMonitor();
                return;
            }

            // Get popup bounds
            const popupRect = this.popup.getBoundingClientRect();
            const mouseX = e.clientX;
            const mouseY = e.clientY;

            // Calculate distance from popup edges (negative means inside)
            const distanceX = mouseX < popupRect.left ? popupRect.left - mouseX :
                             mouseX > popupRect.right ? mouseX - popupRect.right : 0;
            const distanceY = mouseY < popupRect.top ? popupRect.top - mouseY :
                             mouseY > popupRect.bottom ? mouseY - popupRect.bottom : 0;

            // Calculate total distance from popup
            const distance = Math.sqrt(distanceX * distanceX + distanceY * distanceY);

            // Close popup if mouse is more than 100px away from popup edges
            if (distance > 100) {
                this.hidePopup(true);
                this.stopMouseDistanceMonitor();
            }
        };

        document.addEventListener('mousemove', this.mouseDistanceHandler);
    }

    /**
     * Stop monitoring mouse distance
     */
    stopMouseDistanceMonitor() {
        if (this.mouseDistanceHandler) {
            document.removeEventListener('mousemove', this.mouseDistanceHandler);
            this.mouseDistanceHandler = null;
        }
    }

    /**
     * Populate the popup with event data
     */
    populatePopup(eventData) {
        const popupContent = this.popup.querySelector('.popup-content');
        if (!popupContent) return;

        popupContent.dataset.eventId = eventData.id;

        // Apply status class to popup for colored border
        this.popup.className = this.popup.className.replace(/status-\S+/g, '').trim();
        if (eventData.status) {
            this.popup.classList.add(`status-${eventData.status}`);
        }

        // Title
        const titleEl = this.popup.querySelector('.popup-title');
        if (titleEl) {
            titleEl.textContent = eventData.title || 'Untitled Event';
        }

        // Date/time
        const datetimeEl = this.popup.querySelector('.popup-datetime');
        const datetimeTextEl = this.popup.querySelector('.popup-datetime-text');
        if (datetimeEl && datetimeTextEl) {
            let dateTimeStr = '';
            if (eventData.start_date) {
                const date = new Date(eventData.start_date + 'T00:00:00');
                dateTimeStr = date.toLocaleDateString('en-US', {
                    weekday: 'short',
                    month: 'short',
                    day: 'numeric'
                });
            }
            if (eventData.start_time) {
                dateTimeStr += ' ' + this.formatEventTime(eventData);
            }
            datetimeTextEl.textContent = dateTimeStr;
            datetimeEl.style.display = dateTimeStr ? 'flex' : 'none';
        }

        // Location
        const locationEl = this.popup.querySelector('.popup-location');
        const locationTextEl = this.popup.querySelector('.popup-location-text');
        if (locationEl && locationTextEl) {
            const location = eventData.location || '';
            locationTextEl.textContent = location;
            locationEl.style.display = location ? 'flex' : 'none';
        }

        // Description preview (first two lines)
        const descriptionEl = this.popup.querySelector('.popup-description');
        const descriptionTextEl = this.popup.querySelector('.popup-description-text');
        if (descriptionEl && descriptionTextEl) {
            const description = eventData.description || eventData.notes || '';
            if (description) {
                // Get first two lines (split by newline, take first 2, rejoin)
                const lines = description.split(/\r?\n/).filter(line => line.trim());
                const preview = lines.slice(0, 2).join(' ');
                // Truncate if too long (max ~100 chars)
                descriptionTextEl.textContent = preview.length > 100
                    ? preview.substring(0, 100) + '...'
                    : preview;
                descriptionEl.style.display = 'flex';
            } else {
                descriptionTextEl.textContent = '';
                descriptionEl.style.display = 'none';
            }
        }

        // Status dropdown
        this.populateStatusDropdown(eventData.status);
    }

    /**
     * Populate the status dropdown with options
     */
    populateStatusDropdown(currentStatus) {
        const select = this.popup.querySelector('.popup-status-select');
        if (!select) return;

        select.innerHTML = '';

        // Get status options from filter choices
        const statusOptions = this.state.filterChoices.event_statuses || [];

        if (statusOptions.length === 0) {
            // Fallback defaults
            const defaults = [
                ['received', 'Received'],
                ['hold', 'Hold'],
                ['scheduling_in_progress', 'Scheduling in Progress'],
                ['scheduled', 'Scheduled'],
                ['rsvped', 'RSVPed'],
                ['regrets_sent', 'Regrets Sent'],
                ['passed', 'Passed'],
                ['canceled', 'Canceled']
            ];
            defaults.forEach(([value, label]) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                if (value === currentStatus) option.selected = true;
                select.appendChild(option);
            });
        } else {
            statusOptions.forEach(opt => {
                const value = opt.value || opt[0];
                const label = opt.label || opt[1];
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                if (value === currentStatus) option.selected = true;
                select.appendChild(option);
            });
        }

        // Apply status color to dropdown
        this.updateDropdownStatusColor(select, currentStatus);
    }

    /**
     * Update the dropdown's appearance to match the current status color
     */
    updateDropdownStatusColor(select, status) {
        if (!select || !status) return;

        // Remove any existing status classes
        select.className = select.className.replace(/status-\S+/g, '').trim();
        select.classList.add('popup-status-select');
        select.classList.add(`status-${status.replace(/_/g, '_')}`);
    }

    /**
     * Handle status change from popup dropdown
     */
    async handlePopupStatusChange(e) {
        const select = e.target;
        const newStatus = select.value;
        const eventId = this.popup.querySelector('.popup-content')?.dataset.eventId;

        if (!eventId || !newStatus) return;

        const oldStatus = this.currentHoveredEvent?.data?.status;

        try {
            const response = await fetch(`/api/events/${eventId}/update_fields/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    fields: {
                        status: newStatus
                    }
                })
            });

            if (response.ok) {
                const data = await response.json();
                // API returns { message: '...', updated_fields: [...], event: {...} }
                if (data.message || data.updated_fields) {
                    // Update local event data
                    const event = this.state.events.find(e => String(e.id) === String(eventId));
                    if (event) {
                        event.status = newStatus;
                    }

                    // Update the event element's status class
                    if (this.currentHoveredEvent?.element) {
                        const el = this.currentHoveredEvent.element;
                        // Remove old status class
                        el.className = el.className.replace(/status-\S+/g, '');
                        // Add new status class
                        el.classList.add(`status-${newStatus.replace(/_/g, '_')}`);
                    }

                    // Update dropdown color to match new status
                    this.updateDropdownStatusColor(select, newStatus);

                    // Update popup border color to match new status
                    this.popup.className = this.popup.className.replace(/status-\S+/g, '').trim();
                    this.popup.classList.add(`status-${newStatus}`);

                    // Show success toast
                    this.showToast('Status updated', 'success');
                } else {
                    throw new Error(data.error || 'Failed to update status');
                }
            } else {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || 'Request failed');
            }
        } catch (error) {
            console.error('Error updating status:', error);
            // Revert dropdown and color
            if (oldStatus) {
                select.value = oldStatus;
                this.updateDropdownStatusColor(select, oldStatus);
            }
            this.showToast('Failed to update status', 'error');
        }
    }

    /**
     * Show a toast notification
     */
    showToast(message, type = 'info') {
        // Check if there's already a toast container
        let toastContainer = document.querySelector('.calendar-toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.className = 'calendar-toast-container';
            toastContainer.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 1000;
                display: flex;
                flex-direction: column;
                gap: 8px;
            `;
            document.body.appendChild(toastContainer);
        }

        const toast = document.createElement('div');
        toast.className = `calendar-toast calendar-toast-${type}`;
        toast.style.cssText = `
            padding: 12px 16px;
            border-radius: 8px;
            background: ${type === 'error' ? '#fef2f2' : '#f0fdf4'};
            color: ${type === 'error' ? '#dc2626' : '#16a34a'};
            border: 1px solid ${type === 'error' ? '#fecaca' : '#bbf7d0'};
            font-size: 14px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            animation: slideIn 0.2s ease;
        `;
        toast.textContent = message;

        toastContainer.appendChild(toast);

        // Remove after 3 seconds
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.2s ease';
            setTimeout(() => toast.remove(), 200);
        }, 3000);
    }

    // =========================================================================
    // Drag and Drop / Resize Functionality
    // =========================================================================

    /**
     * Initialize drag and drop / resize functionality
     */
    initDragAndResize() {
        // Create drag time tooltip element
        this.dragTooltip = document.createElement('div');
        this.dragTooltip.className = 'drag-time-tooltip';
        this.dragTooltip.style.display = 'none';
        document.body.appendChild(this.dragTooltip);

        // Bind global mouseup to end drag
        this.boundHandleMouseUp = this.endDrag.bind(this);
        document.addEventListener('mouseup', this.boundHandleMouseUp);

        // Bind mousemove handler (will be used during drag)
        this.boundHandleDragMove = this.handleDragMove.bind(this);

        // Cancel drag when mouse leaves the calendar area
        this.boundCancelDragOnLeave = this.cancelDragOnLeave.bind(this);
    }

    /**
     * Cancel drag operation when mouse leaves the calendar area
     */
    cancelDragOnLeave(e) {
        if (!this.dragState) return;

        // Check if the mouse has actually left the calendar container
        const calendarContainer = this.elements.viewContainer;
        if (!calendarContainer) return;

        const rect = calendarContainer.getBoundingClientRect();
        const isOutside = e.clientX < rect.left || e.clientX > rect.right ||
                          e.clientY < rect.top || e.clientY > rect.bottom;

        if (isOutside) {
            this.cancelDrag();
        }
    }

    /**
     * Cancel the current drag operation without saving changes
     */
    cancelDrag() {
        if (!this.dragState) return;

        const { eventEl, eventsColumn, targetColumn } = this.dragState;

        // Remove event listeners
        document.removeEventListener('mousemove', this.boundHandleDragMove);
        document.removeEventListener('mousemove', this.boundCancelDragOnLeave);

        // Remove dragging classes
        eventEl.classList.remove('dragging');
        this.elements.viewContainer?.classList.remove('dragging');

        // Remove ghost
        if (this.dragGhost) {
            this.dragGhost.remove();
            this.dragGhost = null;
        }

        // Hide tooltip
        if (this.dragTooltip) {
            this.dragTooltip.style.display = 'none';
        }

        // Reset event positions in affected columns
        this.resetEventPositionsInColumn(eventsColumn);
        if (targetColumn && targetColumn !== eventsColumn) {
            this.resetEventPositionsInColumn(targetColumn);
        }

        // Clear drag state
        this.dragState = null;
    }

    /**
     * Bind drag and resize events to event blocks in a container
     */
    bindDragEvents(container) {
        container.querySelectorAll('.event-block').forEach(eventEl => {
            // Resize top handle
            const topHandle = eventEl.querySelector('.resize-handle-top');
            if (topHandle) {
                topHandle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.startDrag(e, eventEl, 'resize-top');
                });
            }

            // Resize bottom handle
            const bottomHandle = eventEl.querySelector('.resize-handle-bottom');
            if (bottomHandle) {
                bottomHandle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.startDrag(e, eventEl, 'resize-bottom');
                });
            }

            // Move drag (on the event body, not on handles)
            eventEl.addEventListener('mousedown', (e) => {
                // Don't start move if clicking on resize handles
                if (e.target.classList.contains('resize-handle') ||
                    e.target.classList.contains('resize-handle-top') ||
                    e.target.classList.contains('resize-handle-bottom')) {
                    return;
                }
                e.preventDefault();
                this.startDrag(e, eventEl, 'move');
            });
        });
    }

    /**
     * Start a drag operation
     */
    startDrag(e, eventEl, type) {
        // Get event data
        const eventId = eventEl.dataset.eventId;
        const eventData = this.state.events.find(ev => String(ev.id) === String(eventId));
        if (!eventData) return;

        // Get the events column this event is in
        const eventsColumn = eventEl.closest('.day-events-column');
        if (!eventsColumn) return;

        // Get the scroll container for offset calculation
        const scrollContainer = eventEl.closest('.week-view-body, .day-view-body');
        const scrollTop = scrollContainer ? scrollContainer.scrollTop : 0;

        // Calculate initial positions
        const eventRect = eventEl.getBoundingClientRect();
        const columnRect = eventsColumn.getBoundingClientRect();

        // Store the initial state
        this.dragState = {
            type: type,
            eventEl: eventEl,
            eventData: eventData,
            eventId: eventId,
            startY: e.clientY,
            startX: e.clientX,
            startTop: parseInt(eventEl.style.top) || 0,
            startHeight: parseInt(eventEl.style.height) || 60,
            startMinutes: parseInt(eventEl.dataset.startMinutes) || this.getEventStartMinutes(eventData),
            endMinutes: parseInt(eventEl.dataset.endMinutes) || this.getEventEndMinutes(eventData),
            originalStartDate: eventData.start_date,
            originalLeft: eventEl.style.left,   // Store original horizontal position
            originalWidth: eventEl.style.width, // Store original width
            eventsColumn: eventsColumn,
            columnRect: columnRect,
            scrollContainer: scrollContainer,
            initialScrollTop: scrollTop
        };

        // Add dragging class
        eventEl.classList.add('dragging');
        this.elements.viewContainer?.classList.add('dragging');

        // Create ghost element
        this.createDragGhost(eventEl, eventsColumn);

        // Hide popup if visible
        this.hidePopup(true);

        // Bind mousemove for drag and for cancel detection
        document.addEventListener('mousemove', this.boundHandleDragMove);
        document.addEventListener('mousemove', this.boundCancelDragOnLeave);
    }

    /**
     * Create a ghost element to show the preview position
     */
    createDragGhost(eventEl, eventsColumn) {
        this.dragGhost = document.createElement('div');
        this.dragGhost.className = 'event-drag-ghost';
        this.dragGhost.style.top = eventEl.style.top;
        this.dragGhost.style.height = eventEl.style.height;

        // Calculate proper width based on overlapping events
        const startMinutes = parseInt(eventEl.dataset.startMinutes);
        const endMinutes = parseInt(eventEl.dataset.endMinutes);
        const eventId = eventEl.dataset.eventId;
        const date = eventsColumn.dataset.date;

        this.updateGhostPosition(startMinutes, endMinutes, eventId, date, eventsColumn);

        eventsColumn.appendChild(this.dragGhost);
    }

    /**
     * Calculate and update ghost position based on overlapping events.
     * In the original column: ghost fits into existing layout without affecting other events.
     * In other columns: recalculates all positions so events react to the ghost.
     */
    updateGhostPosition(startMinutes, endMinutes, draggedEventId, date, targetColumn) {
        if (!this.dragGhost) return;

        // Check if we're in the original column
        const isOriginalColumn = this.dragState && date === this.dragState.originalStartDate;

        // Get all events for this date, excluding the one being dragged
        const dayEvents = this.getEventsForDate(new Date(date + 'T00:00:00'))
            .filter(ev => String(ev.id) !== String(draggedEventId));

        if (isOriginalColumn) {
            // In original column: ghost maintains the original event's horizontal position
            // Use the stored original position from when drag started
            if (this.dragState.originalLeft !== undefined && this.dragState.originalWidth !== undefined) {
                this.dragGhost.style.left = this.dragState.originalLeft;
                this.dragGhost.style.width = this.dragState.originalWidth;
                this.dragGhost.style.right = 'auto';
            }
        } else {
            // In a different column: recalculate all positions including ghost
            const ghostEvent = {
                id: '__ghost__',
                _startMinutes: startMinutes,
                _endMinutes: endMinutes,
                isGhost: true
            };

            const allEvents = [...dayEvents, ghostEvent];
            const positionedEvents = this.calculateEventPositionsWithGhost(allEvents);

            // Update ghost position (with 12px right margin for create-event click area)
            const ghostPos = positionedEvents.find(ev => ev.id === '__ghost__');
            if (ghostPos) {
                this.dragGhost.style.left = `${ghostPos.left}%`;
                this.dragGhost.style.width = `calc(${ghostPos.width}% - ${(ghostPos.width / 100) * 12}px)`;
                this.dragGhost.style.right = 'auto';
            }

            // Update positions of other events in this column to react to the ghost
            const eventBlocks = targetColumn.querySelectorAll('.event-block:not(.dragging)');
            eventBlocks.forEach(block => {
                const blockId = block.dataset.eventId;
                const pos = positionedEvents.find(ev => String(ev.id) === String(blockId));
                if (pos) {
                    block.style.left = `${pos.left}%`;
                    block.style.width = `calc(${pos.width}% - ${(pos.width / 100) * 12}px)`;
                }
            });
        }
    }

    /**
     * Calculate positions for events including a ghost event.
     * Similar to calculateEventPositions but handles the ghost's custom time range.
     */
    calculateEventPositionsWithGhost(events) {
        if (!events.length) return [];

        // Helper to get start/end minutes (handles ghost's custom properties)
        const getStart = (e) => e._startMinutes !== undefined ? e._startMinutes : this.getEventStartMinutes(e);
        const getEnd = (e) => e._endMinutes !== undefined ? e._endMinutes : this.getEventEndMinutes(e);

        // Sort by start time, then by end time (longer events first)
        const sorted = [...events].sort((a, b) => {
            const startDiff = getStart(a) - getStart(b);
            if (startDiff !== 0) return startDiff;
            return getEnd(b) - getEnd(a);
        });

        // Helper to check if two events overlap
        const eventsOverlap = (e1, e2) => {
            const start1 = getStart(e1);
            const end1 = getEnd(e1);
            const start2 = getStart(e2);
            const end2 = getEnd(e2);
            return start1 < end2 && start2 < end1;
        };

        // Find overlap groups - events that overlap directly or transitively
        const groups = [];
        const eventToGroup = new Map();

        sorted.forEach(event => {
            // Find all groups this event overlaps with
            const overlappingGroups = new Set();

            for (let i = 0; i < groups.length; i++) {
                for (const groupEvent of groups[i]) {
                    if (eventsOverlap(event, groupEvent)) {
                        overlappingGroups.add(i);
                        break;
                    }
                }
            }

            if (overlappingGroups.size === 0) {
                // No overlaps - create new group
                const newGroup = [event];
                eventToGroup.set(event, groups.length);
                groups.push(newGroup);
            } else if (overlappingGroups.size === 1) {
                // Overlaps with one group - add to it
                const groupIndex = [...overlappingGroups][0];
                groups[groupIndex].push(event);
                eventToGroup.set(event, groupIndex);
            } else {
                // Overlaps with multiple groups - merge them
                const groupIndices = [...overlappingGroups].sort((a, b) => a - b);
                const targetGroup = groups[groupIndices[0]];

                // Merge all overlapping groups into the first one
                for (let i = groupIndices.length - 1; i > 0; i--) {
                    const mergeIndex = groupIndices[i];
                    for (const e of groups[mergeIndex]) {
                        targetGroup.push(e);
                        eventToGroup.set(e, groupIndices[0]);
                    }
                    groups.splice(mergeIndex, 1);
                }

                // Add current event
                targetGroup.push(event);
                eventToGroup.set(event, groupIndices[0]);

                // Update group indices after merge
                for (let i = 0; i < groups.length; i++) {
                    for (const e of groups[i]) {
                        eventToGroup.set(e, i);
                    }
                }
            }
        });

        // Calculate positions within each group
        groups.forEach(group => {
            if (group.length === 1) {
                // Single event - full width
                group[0].column = 0;
                group[0].totalColumns = 1;
                group[0].width = 100;
                group[0].left = 0;
                return;
            }

            // Sort group by start time
            group.sort((a, b) => getStart(a) - getStart(b));

            // Assign columns within this group
            const columns = [];
            group.forEach(event => {
                const startMin = getStart(event);

                // Find first column where event doesn't overlap
                let placed = false;
                for (let col = 0; col < columns.length; col++) {
                    const lastEvent = columns[col][columns[col].length - 1];
                    const lastEnd = getEnd(lastEvent);

                    if (startMin >= lastEnd) {
                        columns[col].push(event);
                        event.column = col;
                        placed = true;
                        break;
                    }
                }

                if (!placed) {
                    columns.push([event]);
                    event.column = columns.length - 1;
                }
            });

            // Calculate width and left position for this group.
            // Phase 4 (expansion): mirror calculateEventPositions so the layout
            // doesn't jump between drag-preview and rest. Each event stretches
            // into empty columns to its right until blocked by a time-overlap.
            const totalColumns = columns.length;
            const colWidth = 100 / totalColumns;
            group.forEach(event => {
                const evStart = getStart(event);
                const evEnd = getEnd(event);
                let span = 1;
                for (let col = event.column + 1; col < totalColumns; col++) {
                    const blocked = columns[col].some(other =>
                        getStart(other) < evEnd && getEnd(other) > evStart);
                    if (blocked) break;
                    span++;
                }
                event.left = event.column * colWidth;
                event.width = span * colWidth - 1; // keep a 1% gutter on the right
                event.totalColumns = totalColumns;
            });
        });

        return sorted;
    }

    /**
     * Handle mouse move during drag
     */
    handleDragMove(e) {
        if (!this.dragState) return;

        const { type, eventEl, startY, startTop, startHeight, startMinutes, endMinutes, eventsColumn, scrollContainer, initialScrollTop } = this.dragState;

        // Calculate current scroll offset
        const currentScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;
        const scrollDelta = currentScrollTop - initialScrollTop;

        // Calculate delta Y (in pixels)
        const deltaY = e.clientY - startY + scrollDelta;

        // Snap to 15-minute intervals (15px = 15 minutes at 60px/hour)
        const snappedDelta = this.snapToInterval(deltaY, 15);

        // Calculate new positions based on drag type
        let newTop, newHeight, newStartMinutes, newEndMinutes;

        if (type === 'move') {
            // Moving the event
            newTop = Math.max(0, startTop + snappedDelta);
            newHeight = startHeight;
            newStartMinutes = startMinutes + (snappedDelta / 15) * 15;
            newEndMinutes = endMinutes + (snappedDelta / 15) * 15;

            // Constrain to grid bounds (0-23 hours = 0-1440 minutes)
            const maxTop = (24 * 60) - startHeight; // Max top based on event height
            newTop = Math.min(newTop, maxTop);
            if (newStartMinutes < 0) {
                newStartMinutes = 0;
                newEndMinutes = endMinutes - startMinutes;
                newTop = 0;
            }
            if (newEndMinutes > 24 * 60) {
                newEndMinutes = 24 * 60;
                newStartMinutes = 24 * 60 - (endMinutes - startMinutes);
                newTop = (24 * 60) - startHeight;
            }

            // Update ghost position and width
            if (this.dragGhost) {
                this.dragGhost.style.top = `${newTop}px`;

                // Recalculate width based on overlapping events at new position
                const targetColumn = this.dragState.targetColumn || eventsColumn;
                const targetDate = targetColumn.dataset.date || this.dragState.originalStartDate;
                this.updateGhostPosition(newStartMinutes, newEndMinutes, this.dragState.eventId, targetDate, targetColumn);
            }

            // Handle horizontal drag for week view (change date)
            this.handleWeekViewDayChange(e, eventsColumn);

        } else if (type === 'resize-top') {
            // Resizing from top (changes start time)
            newTop = startTop + snappedDelta;
            newHeight = startHeight - snappedDelta;

            // Minimum height of 15px (15 minutes)
            if (newHeight < 15) {
                newHeight = 15;
                newTop = startTop + startHeight - 15;
            }

            // Don't go above the grid
            if (newTop < 0) {
                newHeight = startHeight + startTop;
                newTop = 0;
            }

            newStartMinutes = startMinutes + (snappedDelta / 15) * 15;
            newEndMinutes = endMinutes;

            // Update ghost position and width (time range changed, so overlaps may differ)
            if (this.dragGhost) {
                this.dragGhost.style.top = `${newTop}px`;
                this.dragGhost.style.height = `${newHeight}px`;

                const targetColumn = this.dragState.targetColumn || eventsColumn;
                const targetDate = targetColumn.dataset.date || this.dragState.originalStartDate;
                this.updateGhostPosition(newStartMinutes, newEndMinutes, this.dragState.eventId, targetDate, targetColumn);
            }

        } else if (type === 'resize-bottom') {
            // Resizing from bottom (changes end time)
            newTop = startTop;
            newHeight = startHeight + snappedDelta;

            // Minimum height of 15px (15 minutes)
            newHeight = Math.max(15, newHeight);

            // Don't go below the grid (24 hours = 1440px)
            const maxHeight = (24 * 60) - startTop;
            newHeight = Math.min(newHeight, maxHeight);

            newStartMinutes = startMinutes;
            newEndMinutes = endMinutes + ((newHeight - startHeight) / 15) * 15;

            // Update ghost position and width (time range changed, so overlaps may differ)
            if (this.dragGhost) {
                this.dragGhost.style.height = `${newHeight}px`;

                const targetColumn = this.dragState.targetColumn || eventsColumn;
                const targetDate = targetColumn.dataset.date || this.dragState.originalStartDate;
                this.updateGhostPosition(newStartMinutes, newEndMinutes, this.dragState.eventId, targetDate, targetColumn);
            }
        }

        // Store calculated values
        this.dragState.newTop = newTop;
        this.dragState.newHeight = newHeight;
        this.dragState.newStartMinutes = newStartMinutes;
        this.dragState.newEndMinutes = newEndMinutes;

        // Update tooltip
        this.updateDragTooltip(e, newStartMinutes, newEndMinutes);
    }

    /**
     * Handle week view horizontal drag to change day
     */
    handleWeekViewDayChange(e, currentColumn) {
        if (this.state.currentView !== 'week') return;

        const eventsLayer = currentColumn.closest('.week-events-layer');
        if (!eventsLayer) return;

        const columns = eventsLayer.querySelectorAll('.day-events-column');
        const columnRects = Array.from(columns).map(col => ({
            column: col,
            rect: col.getBoundingClientRect()
        }));

        // Find which column the mouse is over
        for (const { column, rect } of columnRects) {
            if (e.clientX >= rect.left && e.clientX <= rect.right) {
                const previousColumn = this.dragGhost ? this.dragGhost.parentElement : null;
                const columnChanged = previousColumn && previousColumn !== column;

                // Move ghost to the column the mouse is over
                if (columnChanged) {
                    // Reset positions in the old column before moving ghost
                    this.resetEventPositionsInColumn(previousColumn);
                    column.appendChild(this.dragGhost);
                }
                this.dragState.targetColumn = column;

                // Set newDate to the column's date, or undefined if it's the original column
                const columnDate = column.dataset.date;
                if (columnDate === this.dragState.originalStartDate) {
                    // Back to original column - clear newDate so no date change is saved
                    this.dragState.newDate = undefined;
                } else {
                    this.dragState.newDate = columnDate;
                }

                // Recalculate ghost width when column changes (different day = different overlapping events)
                if (columnChanged && this.dragState.newStartMinutes !== undefined) {
                    this.updateGhostPosition(
                        this.dragState.newStartMinutes,
                        this.dragState.newEndMinutes,
                        this.dragState.eventId,
                        columnDate,
                        column
                    );
                }
                break;
            }
        }
    }

    /**
     * Update the drag tooltip with current time
     */
    updateDragTooltip(e, startMinutes, endMinutes) {
        if (!this.dragTooltip) return;

        // Format times
        const startTime = this.minutesToTimeString(startMinutes);
        const endTime = this.minutesToTimeString(endMinutes);
        const duration = endMinutes - startMinutes;
        const durationStr = duration >= 60
            ? `${Math.floor(duration / 60)}h ${duration % 60 > 0 ? (duration % 60) + 'm' : ''}`
            : `${duration}m`;

        this.dragTooltip.textContent = `${this.formatTimeForDisplay(startTime)} - ${this.formatTimeForDisplay(endTime)} (${durationStr.trim()})`;
        this.dragTooltip.style.display = 'block';
        this.dragTooltip.style.left = `${e.clientX + 15}px`;
        this.dragTooltip.style.top = `${e.clientY + 15}px`;
    }

    /**
     * End a drag operation
     */
    async endDrag(e) {
        if (!this.dragState) return;

        const { type, eventEl, eventId, eventData, startTop, startHeight, newTop, newHeight, newStartMinutes, newEndMinutes, newDate, originalStartDate, scrollContainer } = this.dragState;

        // Remove event listeners
        document.removeEventListener('mousemove', this.boundHandleDragMove);
        document.removeEventListener('mousemove', this.boundCancelDragOnLeave);

        // Remove dragging classes
        eventEl.classList.remove('dragging');
        this.elements.viewContainer?.classList.remove('dragging');

        // Remove ghost
        if (this.dragGhost) {
            this.dragGhost.remove();
            this.dragGhost = null;
        }

        // Hide tooltip
        if (this.dragTooltip) {
            this.dragTooltip.style.display = 'none';
        }

        // Check if position actually changed
        const positionChanged = (newTop !== undefined && newTop !== startTop) ||
                                (newHeight !== undefined && newHeight !== startHeight) ||
                                (newDate !== undefined && newDate !== originalStartDate);

        // Set flag to prevent click event from firing after drag
        if (positionChanged) {
            this.wasDragging = true;
        }

        if (positionChanged && newStartMinutes !== undefined && newEndMinutes !== undefined) {
            // Convert minutes to time strings
            const newStartTime = this.minutesToTimeString(newStartMinutes);
            const newEndTime = this.minutesToTimeString(newEndMinutes);
            const targetDate = newDate || originalStartDate;

            // Save scroll position before re-rendering
            const savedScrollTop = scrollContainer ? scrollContainer.scrollTop : 0;

            // Save to API
            try {
                // Build update fields - include end_date if date changed
                const updateFields = {
                    start_date: targetDate,
                    start_time: newStartTime,
                    end_time: newEndTime
                };

                // If the date changed, also update end_date to match
                // (most events are same-day, so end_date should match start_date)
                if (newDate && newDate !== originalStartDate) {
                    updateFields.end_date = targetDate;
                }

                const response = await fetch(`/api/events/${eventId}/update_fields/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken
                    },
                    body: JSON.stringify({
                        fields: updateFields
                    })
                });

                if (response.ok) {
                    // Update local event data
                    eventData.start_date = targetDate;
                    eventData.start_time = newStartTime;
                    eventData.end_time = newEndTime;
                    if (updateFields.end_date) {
                        eventData.end_date = updateFields.end_date;
                    }

                    // Re-render the view without auto-scrolling
                    this.renderCurrentViewPreserveScroll(savedScrollTop);
                    this.showToast('Event updated', 'success');
                } else {
                    const errorData = await response.json().catch(() => ({}));
                    console.error('Event update failed:', response.status, errorData);
                    throw new Error(errorData.error || `Failed to update event (${response.status})`);
                }
            } catch (error) {
                console.error('Error updating event:', error);
                this.showToast('Failed to update event', 'error');
                // Re-render to reset visual state
                this.renderCurrentViewPreserveScroll(savedScrollTop);
            }
        } else {
            // Position didn't change - reset event positions in the column
            this.resetEventPositionsInColumn(this.dragState.eventsColumn);
            if (this.dragState.targetColumn && this.dragState.targetColumn !== this.dragState.eventsColumn) {
                this.resetEventPositionsInColumn(this.dragState.targetColumn);
            }
        }

        // Clear drag state
        this.dragState = null;
    }

    /**
     * Reset event positions in a column to their natural calculated positions
     */
    resetEventPositionsInColumn(column) {
        if (!column) return;

        const date = column.dataset.date;
        if (!date) return;

        // Get events for this date
        const dayEvents = this.getEventsForDate(new Date(date + 'T00:00:00'));

        // Calculate their natural positions
        const positionedEvents = this.calculateEventPositions(dayEvents);

        // Update DOM elements (with 12px right margin for create-event click area)
        const eventBlocks = column.querySelectorAll('.event-block');
        eventBlocks.forEach(block => {
            const blockId = block.dataset.eventId;
            const pos = positionedEvents.find(ev => String(ev.id) === String(blockId));
            if (pos) {
                block.style.left = `${pos.left}%`;
                block.style.width = `calc(${pos.width}% - ${(pos.width / 100) * 12}px)`;
            }
        });
    }

    /**
     * Snap a pixel value to an interval
     */
    snapToInterval(pixels, intervalPx = 15) {
        return Math.round(pixels / intervalPx) * intervalPx;
    }

    /**
     * Convert minutes since midnight to HH:MM time string
     */
    minutesToTimeString(minutes) {
        // Clamp to valid range
        minutes = Math.max(0, Math.min(minutes, 24 * 60 - 1));

        const hours = Math.floor(minutes / 60);
        const mins = Math.round(minutes % 60);

        return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
    }

    /**
     * Format time string (HH:MM) for display (e.g., "2:30 PM")
     */
    formatTimeForDisplay(timeStr) {
        const [hours, minutes] = timeStr.split(':').map(Number);
        const period = hours >= 12 ? 'PM' : 'AM';
        const displayHours = hours % 12 || 12;
        return minutes === 0
            ? `${displayHours} ${period}`
            : `${displayHours}:${String(minutes).padStart(2, '0')} ${period}`;
    }

    // =========================================================================
    // Click-to-Create Event Functionality
    // =========================================================================

    /**
     * Initialize click-to-create functionality
     */
    initClickToCreate() {
        // Bind handlers
        this.boundHandleCreateDrag = this.handleCreateDrag.bind(this);
        this.boundHandleCreateMouseUp = this.handleCreateMouseUp.bind(this);

        // Close preview on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.createState) {
                this.hideCreatePreview();
            }
        });

        // Close preview on mousedown anywhere except the popup or preview
        // Using mousedown instead of click to avoid timing issues
        document.addEventListener('mousedown', (e) => {
            if (this.createState && this.createState.popupEl) {
                const popup = this.createState.popupEl;
                const preview = this.createState.previewEl;
                // If clicking outside the popup and preview, hide everything
                if (!popup.contains(e.target) && (!preview || !preview.contains(e.target))) {
                    // Check if clicking on the column (which would start a new preview)
                    const column = e.target.closest('.day-events-column');
                    if (column && !e.target.closest('.event-block')) {
                        // Let the new preview creation happen, it will hide the old one
                        return;
                    }
                    this.hideCreatePreview();
                }
            }
        });

        // Use event delegation on the view container for click-to-create
        // This avoids adding multiple listeners when views are re-rendered
        if (this.elements.viewContainer) {
            this.elements.viewContainer.addEventListener('mousedown', (e) => {
                // Don't start create if clicking on an event, resize handle, or any event-related element
                const eventBlock = e.target.closest('.event-block');
                const resizeHandle = e.target.closest('.resize-handle');
                const eventContent = e.target.closest('.event-block-content');
                const eventBlockAny = e.target.closest('[data-event-id]');

                if (eventBlock || resizeHandle || eventContent || eventBlockAny) {
                    return;
                }

                // Find the day column
                const column = e.target.closest('.day-events-column');
                if (!column) return;

                // Don't interfere with drag operations
                if (this.dragState) {
                    return;
                }

                // Don't start new preview if already creating (either dragging or popup shown)
                if (this.createState) {
                    // If popup is shown, hide it first and don't start new create
                    if (this.createState.popupEl) {
                        this.hideCreatePreview();
                        return;
                    }
                    // If still dragging, don't start new
                    if (this.createState.isMouseDown) {
                        return;
                    }
                }

                // Don't start new create if we just closed a popup (flag resets after event cycle)
                if (this.wasCreating) {
                    return;
                }

                this.handleEmptySpaceMouseDown(e, column);
            });
        }
    }

    /**
     * Bind click-to-create events to day columns
     * Note: Now uses event delegation in initClickToCreate(), this is kept for compatibility
     */
    bindClickToCreate(container) {
        // Event delegation is now handled in initClickToCreate()
        // This method is kept as a no-op for compatibility
    }

    /**
     * Handle mousedown on empty space to start creating event
     */
    handleEmptySpaceMouseDown(e, column) {
        e.preventDefault();

        // Hide any existing preview
        this.hideCreatePreview();

        // Get the date from the column
        const date = column.dataset.date;
        if (!date) return;

        // Calculate the clicked position in minutes
        // getBoundingClientRect().top already accounts for scroll position
        // since it returns viewport-relative coordinates
        const columnRect = column.getBoundingClientRect();
        const clickY = e.clientY - columnRect.top;
        const scrollContainer = column.closest('.week-view-body, .day-view-body');

        // Convert pixels to minutes (60px = 60 minutes, so 1px = 1 minute)
        const clickedMinutes = clickY;
        // Snap to 15-minute interval
        const startMinutes = this.snapToInterval(clickedMinutes, 15);
        const endMinutes = Math.min(startMinutes + 60, 24 * 60); // Default 1 hour, cap at midnight

        // Create preview element
        const previewEl = document.createElement('div');
        previewEl.className = 'event-create-preview';
        previewEl.style.top = `${startMinutes}px`;
        previewEl.style.height = `${endMinutes - startMinutes}px`;
        column.appendChild(previewEl);

        // Store create state
        this.createState = {
            startMinutes: startMinutes,
            endMinutes: endMinutes,
            initialStartMinutes: startMinutes,
            initialClickY: clickY,
            date: date,
            column: column,
            columnRect: columnRect,
            previewEl: previewEl,
            popupEl: null,
            isMouseDown: true,
            startY: e.clientY
        };

        // Set preview to full column width
        previewEl.style.left = '0';
        previewEl.style.width = '100%';

        // Add creating class to container
        this.elements.viewContainer?.classList.add('creating');

        // Bind drag and mouseup handlers
        document.addEventListener('mousemove', this.boundHandleCreateDrag);
        document.addEventListener('mouseup', this.boundHandleCreateMouseUp);
    }

    /**
     * Handle mouse move while creating event (drag to resize)
     */
    handleCreateDrag(e) {
        if (!this.createState || !this.createState.isMouseDown) return;

        const { initialStartMinutes, startY, previewEl } = this.createState;

        // Calculate delta Y from start position
        const deltaY = e.clientY - startY;
        const snappedDelta = this.snapToInterval(deltaY, 15);

        let newStartMinutes, newEndMinutes;

        if (snappedDelta >= 0) {
            // Dragging down - extend end time
            newStartMinutes = initialStartMinutes;
            newEndMinutes = initialStartMinutes + 60 + snappedDelta;
        } else {
            // Dragging up - move start time earlier
            newStartMinutes = Math.max(0, initialStartMinutes + snappedDelta);
            newEndMinutes = initialStartMinutes + 60;
        }

        // Ensure minimum 15-minute duration
        if (newEndMinutes - newStartMinutes < 15) {
            newEndMinutes = newStartMinutes + 15;
        }

        // Constrain to grid bounds (0 to 24 hours)
        newStartMinutes = Math.max(0, newStartMinutes);
        newEndMinutes = Math.min(24 * 60, newEndMinutes);

        // Update state
        this.createState.startMinutes = newStartMinutes;
        this.createState.endMinutes = newEndMinutes;

        // Update preview position (top and height)
        previewEl.style.top = `${newStartMinutes}px`;
        previewEl.style.height = `${newEndMinutes - newStartMinutes}px`;

        // Show time tooltip while dragging
        this.updateDragTooltip(e, newStartMinutes, newEndMinutes);
    }

    /**
     * Handle mouseup to finalize create preview and show popup
     */
    handleCreateMouseUp(e) {
        if (!this.createState) return;

        // Remove drag handlers
        document.removeEventListener('mousemove', this.boundHandleCreateDrag);
        document.removeEventListener('mouseup', this.boundHandleCreateMouseUp);

        this.createState.isMouseDown = false;

        // Hide the drag tooltip
        if (this.dragTooltip) {
            this.dragTooltip.style.display = 'none';
        }

        // Remove creating class
        this.elements.viewContainer?.classList.remove('creating');

        // Show the create popup
        this.showCreatePopup(e.clientX, e.clientY);
    }

    /**
     * Show the create event popup near the cursor
     */
    showCreatePopup(x, y) {
        if (!this.createState) return;

        const { startMinutes, endMinutes, date } = this.createState;
        const startTime = this.minutesToTimeString(startMinutes);
        const endTime = this.minutesToTimeString(endMinutes);
        const timeLabel = `${this.formatTimeForDisplay(startTime)} - ${this.formatTimeForDisplay(endTime)}`;

        // Format the date for display (e.g., "Mon, Jan 20")
        let dateLabel = '';
        if (date) {
            const dateObj = new Date(date + 'T00:00:00');
            dateLabel = dateObj.toLocaleDateString('en-US', {
                weekday: 'short',
                month: 'short',
                day: 'numeric'
            });
        }

        // Create popup element
        const popup = document.createElement('div');
        popup.className = 'event-create-popup';
        popup.innerHTML = `
            <div class="create-date-label">${dateLabel}</div>
            <div class="create-time-label">${timeLabel}</div>
            <button class="create-event-btn" type="button">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                Create Event
            </button>
        `;

        document.body.appendChild(popup);

        // Position popup near cursor, but keep it on screen
        const popupRect = popup.getBoundingClientRect();
        let popupX = x + 10;
        let popupY = y + 10;

        // Adjust if going off right edge
        if (popupX + popupRect.width > window.innerWidth - 10) {
            popupX = x - popupRect.width - 10;
        }
        // Adjust if going off bottom edge
        if (popupY + popupRect.height > window.innerHeight - 10) {
            popupY = y - popupRect.height - 10;
        }

        popup.style.left = `${popupX}px`;
        popup.style.top = `${popupY}px`;

        // Store popup reference and position
        this.createState.popupEl = popup;
        this.createState.popupX = popupX;
        this.createState.popupY = popupY;

        // Bind create button click
        popup.querySelector('.create-event-btn').addEventListener('click', () => {
            this.createEventFromPreview();
        });

        // Track mouse distance - hide if too far from popup/preview
        const handleMouseMove = (e) => {
            if (!this.createState || !this.createState.popupEl) {
                document.removeEventListener('mousemove', handleMouseMove);
                return;
            }

            const popup = this.createState.popupEl;
            const preview = this.createState.previewEl;
            const popupRect = popup.getBoundingClientRect();
            const mouseX = e.clientX;
            const mouseY = e.clientY;

            // Check distance from popup
            const padding = 100;
            const inPopupZone = mouseX >= popupRect.left - padding &&
                               mouseX <= popupRect.right + padding &&
                               mouseY >= popupRect.top - padding &&
                               mouseY <= popupRect.bottom + padding;

            // Check distance from preview
            let inPreviewZone = false;
            if (preview) {
                const previewRect = preview.getBoundingClientRect();
                inPreviewZone = mouseX >= previewRect.left - padding &&
                               mouseX <= previewRect.right + padding &&
                               mouseY >= previewRect.top - padding &&
                               mouseY <= previewRect.bottom + padding;
            }

            if (!inPopupZone && !inPreviewZone) {
                document.removeEventListener('mousemove', handleMouseMove);
                this.hideCreatePreview();
            }
        };

        // Store reference to remove later if needed
        this.createState.mouseMoveHandler = handleMouseMove;
        document.addEventListener('mousemove', handleMouseMove);
    }

    /**
     * Hide and clean up create preview and popup
     */
    hideCreatePreview() {
        if (!this.createState) return;

        // Set flag to prevent immediate re-creation (reset after current event cycle)
        this.wasCreating = true;
        setTimeout(() => { this.wasCreating = false; }, 0);

        // Remove preview element
        if (this.createState.previewEl) {
            this.createState.previewEl.remove();
        }

        // Remove popup element
        if (this.createState.popupEl) {
            this.createState.popupEl.remove();
        }

        // Hide drag tooltip if visible
        if (this.dragTooltip) {
            this.dragTooltip.style.display = 'none';
        }

        // Remove event listeners
        document.removeEventListener('mousemove', this.boundHandleCreateDrag);
        document.removeEventListener('mouseup', this.boundHandleCreateMouseUp);
        if (this.createState.mouseMoveHandler) {
            document.removeEventListener('mousemove', this.createState.mouseMoveHandler);
        }

        // Remove creating class
        this.elements.viewContainer?.classList.remove('creating');

        // Clear state
        this.createState = null;
    }

    /**
     * Create event from the preview selection
     */
    async createEventFromPreview() {
        if (!this.createState) return;

        const { startMinutes, endMinutes, date } = this.createState;
        const startTime = this.minutesToTimeString(startMinutes);
        const endTime = this.minutesToTimeString(endMinutes);

        // Hide preview first
        this.hideCreatePreview();

        try {
            // Create event via API
            const response = await fetch('/api/events/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                body: JSON.stringify({
                    title: '',
                    start_date: date,
                    start_time: startTime,
                    end_time: endTime,
                    status: 'received'
                })
            });

            if (response.ok) {
                const newEvent = await response.json();

                // Add to local state
                this.state.events.push(newEvent);

                // Re-render the view
                this.renderCurrentView();

                // Open the event editing modal with auto-focus on title
                if (typeof openEventEditingModal === 'function') {
                    openEventEditingModal(newEvent.id, {
                        autoFocusTitle: true,
                        isNewEvent: true
                    });
                }
            } else {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || 'Failed to create event');
            }
        } catch (error) {
            console.error('Error creating event:', error);
            this.showToast('Failed to create event', 'error');
        }
    }

    // =========================================================================
    // Left Info Pane (Mini Calendar + Activity Feed)
    // =========================================================================

    /**
     * Initialize the mini calendar popover (anchored to period label in header)
     */
    initMiniCalPopover() {
        this.miniCalPopover = document.getElementById('mini-cal-popover');
        this.periodLabelBtn = document.getElementById('period-label-btn');

        this.renderMiniCalendar();
        this.bindMiniCalendarEvents();

        if (!this.miniCalPopover || !this.periodLabelBtn) return;

        // Toggle popover on period label click
        this.periodLabelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = this.miniCalPopover.classList.contains('visible');
            if (isOpen) {
                this._closeMiniCalPopover();
            } else {
                this._openMiniCalPopover();
            }
        });

        // Also support Enter/Space on the period label
        this.periodLabelBtn.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.periodLabelBtn.click();
            }
        });

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (!this.miniCalPopover.classList.contains('visible')) return;
            if (this.miniCalPopover.contains(e.target) || this.periodLabelBtn.contains(e.target)) return;
            this._closeMiniCalPopover();
        });

        // Close on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.miniCalPopover.classList.contains('visible')) {
                this._closeMiniCalPopover();
            }
        });
    }

    _openMiniCalPopover() {
        if (!this.miniCalPopover || !this.periodLabelBtn) return;
        // Position popover directly below the period-label dropdown button
        const mainArea = document.querySelector('.calendar-main-area');
        const mainRect = mainArea ? mainArea.getBoundingClientRect() : { top: 0, left: 0 };
        const btnRect = this.periodLabelBtn.getBoundingClientRect();
        this.miniCalPopover.style.top = (btnRect.bottom - mainRect.top + 4) + 'px';
        this.miniCalPopover.style.left = (btnRect.left - mainRect.left) + 'px';
        this.miniCalPopover.classList.add('visible');
        this.periodLabelBtn.classList.add('popover-open');
    }

    _closeMiniCalPopover() {
        if (!this.miniCalPopover || !this.periodLabelBtn) return;
        this.miniCalPopover.classList.remove('visible');
        this.periodLabelBtn.classList.remove('popover-open');
    }

    /**
     * Render the mini month calendar
     */
    renderMiniCalendar() {
        const container = document.querySelector('.mini-calendar-grid');
        if (!container) return;

        const year = this.miniCalendarDate.getFullYear();
        const month = this.miniCalendarDate.getMonth();

        // Update header label
        const label = document.querySelector('.mini-cal-month-label');
        if (label) {
            label.textContent = this.miniCalendarDate.toLocaleDateString('en-US', {
                month: 'long', year: 'numeric'
            });
        }

        // Day headers
        const dayNames = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
        let html = dayNames.map(d => `<div class="mini-cal-day-header">${d}</div>`).join('');

        // Get first day of month and total days
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const startDayOfWeek = firstDay.getDay();
        const totalDays = lastDay.getDate();

        // Calculate selected week range (for week view highlighting)
        const isWeekView = this.state.currentView === 'week';
        let weekStart = null;
        let weekEnd = null;
        if (isWeekView) {
            weekStart = this.getWeekStart(this.state.currentDate);
            weekEnd = new Date(weekStart);
            weekEnd.setDate(weekEnd.getDate() + 6);
        }

        // Helper to check if a date is in the selected week
        const isInSelectedWeek = (date) => {
            if (!isWeekView || !weekStart || !weekEnd) return false;
            const dateTime = date.getTime();
            return dateTime >= weekStart.getTime() && dateTime <= weekEnd.getTime();
        };

        // Previous month days
        const prevMonthLast = new Date(year, month, 0).getDate();
        for (let i = startDayOfWeek - 1; i >= 0; i--) {
            const day = prevMonthLast - i;
            const prevMonth = month === 0 ? 11 : month - 1;
            const prevYear = month === 0 ? year - 1 : year;
            const dateStr = `${prevYear}-${String(prevMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const date = new Date(prevYear, prevMonth, day);
            const inWeek = isInSelectedWeek(date);
            html += `<div class="mini-cal-day other-month${inWeek ? ' in-selected-week' : ''}" data-date="${dateStr}">${day}</div>`;
        }

        // Current month days
        const today = new Date();
        const selectedDate = this.state.currentDate;

        for (let day = 1; day <= totalDays; day++) {
            const date = new Date(year, month, day);
            const isToday = this.isSameDay(date, today);
            const isSelected = this.isSameDay(date, selectedDate);
            const inWeek = isInSelectedWeek(date);
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

            let classes = 'mini-cal-day';
            if (isToday) classes += ' today';
            if (isSelected) classes += ' selected';
            if (inWeek) classes += ' in-selected-week';

            html += `<div class="${classes}" data-date="${dateStr}">${day}</div>`;
        }

        // Next month days to fill grid (6 rows x 7 days = 42 cells)
        const totalCells = startDayOfWeek + totalDays;
        const remainingCells = (totalCells <= 35 ? 35 : 42) - totalCells;
        for (let day = 1; day <= remainingCells; day++) {
            const nextMonth = month === 11 ? 0 : month + 1;
            const nextYear = month === 11 ? year + 1 : year;
            const dateStr = `${nextYear}-${String(nextMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const date = new Date(nextYear, nextMonth, day);
            const inWeek = isInSelectedWeek(date);
            html += `<div class="mini-cal-day other-month${inWeek ? ' in-selected-week' : ''}" data-date="${dateStr}">${day}</div>`;
        }

        container.innerHTML = html;
    }

    /**
     * Check if two dates are the same day
     */
    isSameDay(date1, date2) {
        return date1.getFullYear() === date2.getFullYear() &&
               date1.getMonth() === date2.getMonth() &&
               date1.getDate() === date2.getDate();
    }

    /**
     * Bind events for mini calendar navigation and day selection
     */
    bindMiniCalendarEvents() {
        // Month navigation - previous
        document.querySelector('.mini-cal-nav.prev')?.addEventListener('click', () => {
            this.miniCalendarDate.setMonth(this.miniCalendarDate.getMonth() - 1);
            this.renderMiniCalendar();
        });

        // Month navigation - next
        document.querySelector('.mini-cal-nav.next')?.addEventListener('click', () => {
            this.miniCalendarDate.setMonth(this.miniCalendarDate.getMonth() + 1);
            this.renderMiniCalendar();
        });

        // Day selection - use event delegation
        // Single click: jump to date in current view
        // Double click: open day view
        const miniCalGrid = document.querySelector('.mini-calendar-grid');
        if (miniCalGrid) {
            let clickTimeout = null;

            miniCalGrid.addEventListener('click', (e) => {
                const dayEl = e.target.closest('.mini-cal-day');
                if (!dayEl || dayEl.classList.contains('mini-cal-day-header')) return;

                const dateStr = dayEl.dataset.date;
                if (!dateStr) return;

                // Clear any pending single-click action
                if (clickTimeout) {
                    clearTimeout(clickTimeout);
                    clickTimeout = null;
                }

                // Delay single-click action to allow double-click detection
                clickTimeout = setTimeout(() => {
                    // Single click: jump to date but keep current view
                    const [year, month, day] = dateStr.split('-').map(Number);
                    this.state.currentDate = new Date(year, month - 1, day);

                    // Sync mini calendar month if needed
                    if (this.state.currentDate.getMonth() !== this.miniCalendarDate.getMonth() ||
                        this.state.currentDate.getFullYear() !== this.miniCalendarDate.getFullYear()) {
                        this.miniCalendarDate = new Date(this.state.currentDate);
                    }

                    // Close the popover after selection
                    this._closeMiniCalPopover();

                    // Re-render current view with new date (don't switch views)
                    this.fetchEvents().then(() => {
                        this.renderCurrentView();
                        this.updatePeriodLabel();
                        this.renderMiniCalendar();
                    });
                }, 200);
            });

            miniCalGrid.addEventListener('dblclick', (e) => {
                const dayEl = e.target.closest('.mini-cal-day');
                if (!dayEl || dayEl.classList.contains('mini-cal-day-header')) return;

                const dateStr = dayEl.dataset.date;
                if (!dateStr) return;

                // Clear single-click timeout
                if (clickTimeout) {
                    clearTimeout(clickTimeout);
                    clickTimeout = null;
                }

                // Double click: open day view
                const [year, month, day] = dateStr.split('-').map(Number);
                this.state.currentDate = new Date(year, month - 1, day);

                // Sync mini calendar month if needed
                if (this.state.currentDate.getMonth() !== this.miniCalendarDate.getMonth() ||
                    this.state.currentDate.getFullYear() !== this.miniCalendarDate.getFullYear()) {
                    this.miniCalendarDate = new Date(this.state.currentDate);
                }

                // Close the popover after selection
                this._closeMiniCalPopover();

                // Switch to day view
                this.switchView('day');
                this.renderMiniCalendar();
            });
        }
    }

    /**
     * Sync mini calendar with main calendar when date changes
     */
    syncMiniCalendar() {
        // Update mini calendar month if main calendar date is in a different month
        if (this.state.currentDate.getMonth() !== this.miniCalendarDate.getMonth() ||
            this.state.currentDate.getFullYear() !== this.miniCalendarDate.getFullYear()) {
            this.miniCalendarDate = new Date(this.state.currentDate);
        }
        this.renderMiniCalendar();
    }

    /**
     * Render status legend in the info pane using filter choices
     */
    renderStatusLegend() {
        const container = document.getElementById('status-legend');
        if (!container) return;

        const statuses = this.state.filterChoices.status || [];
        if (!statuses.length) {
            container.innerHTML = '<div style="font-size: var(--font-size-xs); color: var(--text-tertiary); font-style: italic;">No statuses configured</div>';
            return;
        }

        const html = statuses.map(s => {
            const value = s.value || s;
            const label = s.label || s.display_name || value;
            return `<div class="status-legend-item">
                <span class="status-legend-dot" style="background: var(--status-${value}, #6b7280);"></span>
                <span>${this.escapeHtml(label)}</span>
            </div>`;
        }).join('');

        container.innerHTML = html;
    }

    /**
     * Ensure text contrast on event blocks — switches text color if contrast is insufficient
     */
    ensureTextContrast(element) {
        const style = getComputedStyle(element);
        const bg = style.backgroundColor;

        // Parse rgb(a) values
        const match = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (!match) return;

        const r = parseInt(match[1]) / 255;
        const g = parseInt(match[2]) / 255;
        const b = parseInt(match[3]) / 255;

        // Relative luminance (WCAG formula)
        const luminance = 0.2126 * (r <= 0.03928 ? r / 12.92 : Math.pow((r + 0.055) / 1.055, 2.4))
                        + 0.7152 * (g <= 0.03928 ? g / 12.92 : Math.pow((g + 0.055) / 1.055, 2.4))
                        + 0.0722 * (b <= 0.03928 ? b / 12.92 : Math.pow((b + 0.055) / 1.055, 2.4));

        // If background is light, use dark text; if dark, use light text
        element.style.color = luminance > 0.4 ? '#1f2937' : '#ffffff';
    }

    // =========================================================================
    // Detail Panel (inline sidebar, compresses calendar content)
    // =========================================================================

    initDetailPanel() {
        this.detailPanel = document.getElementById('calendar-detail-panel');
        this.detailPanelContent = document.getElementById('calendar-detail-panel-content');

        if (!this.detailPanel) return;

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.detailPanel.classList.contains('open')) {
                this.closeDetailPanel();
            }
        });
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

    async openDetailPanel(eventId, options = {}) {
        if (!this.detailPanel || !this.detailPanelContent) return;

        this.state.detailPanelEventId = eventId;

        this.detailPanel.classList.add('open');

        // Mark the selected event on the calendar
        document.querySelectorAll('.event-block.calendar-event-active, .event-chip.calendar-event-active, .allday-event-bar.calendar-event-active, .schedule-event-row.calendar-event-active')
            .forEach(el => el.classList.remove('calendar-event-active'));
        document.querySelectorAll(`[data-event-id="${eventId}"]`)
            .forEach(el => el.classList.add('calendar-event-active'));

        // Show skeleton placeholder while the event loads — mirrors the real
        // panel layout so the swap-in is seamless (no content-shaped spinner).
        this.detailPanelContent.innerHTML = this.renderDetailPanelSkeleton();

        // Fetch event data
        try {
            const response = await fetch(`/api/events/${eventId}/`, {
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': this.csrfToken
                }
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const eventData = await response.json();

            // Guard: if user clicked another event during fetch, abort render
            if (this.state.detailPanelEventId != eventId) return;

            this.state.detailPanelEventData = eventData;

            // Add to recently viewed
            this._addToRecentlyViewed(eventData);

            this.renderCalendarDetailPanel(eventData);

            // Selection asked for focus on the first action — silently for a
            // click (no ring), with the ring for keyboard navigation. This puts
            // focus inside the panel so Tab cycles its controls.
            if (options.focusAction && this.state.detailPanelEventId == eventId) {
                this.focusFirstPanelAction({ silent: options.silentFocus });
            }
        } catch (error) {
            console.error('Error fetching event for detail panel:', error);
            if (this.state.detailPanelEventId == eventId) {
                this.detailPanelContent.innerHTML = `
                    <div class="detail-panel-header">
                        <div class="detail-panel-header-left">
                            <div class="detail-panel-title">Error</div>
                        </div>
                        <div class="detail-panel-header-actions">
                            <button class="detail-panel-close" id="cal-detail-close-btn" aria-label="Close" title="Close">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="18" y1="6" x2="6" y2="18"></line>
                                    <line x1="6" y1="6" x2="18" y2="18"></line>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="detail-panel-body" style="display:flex;align-items:center;justify-content:center;color:var(--text-secondary);">
                        Failed to load event details.
                    </div>`;
                document.getElementById('cal-detail-close-btn')?.addEventListener('click', () => this.closeDetailPanel());
            }
        }
    }

    renderCalendarDetailPanel(eventData) {
        const content = this.detailPanelContent;
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

        // Status
        const statusSlug = (eventData.status || 'received').toLowerCase().replace(/\s+/g, '_');
        const statusClass = `status-${statusSlug}`;
        const statusMap = {
            'received': 'Received', 'hold': 'Hold', 'referred': 'Referred',
            'fyied': 'FYI\'ed', 'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled', 'rsvped': 'RSVP\'d',
            'regrets_sent': 'Regrets Sent', 'passed': 'Passed',
            'canceled': 'Canceled', 'requires_hms_review': 'Needs Review'
        };
        const statusLabel = statusMap[statusSlug] || eventData.status || 'Unknown';

        // Location text
        let locationText = '';
        if (eventData.location) locationText = eventData.location;
        else {
            const parts = [eventData.location_room, eventData.location_building].filter(Boolean);
            locationText = parts.join(', ');
        }

        // Type + format line
        const typeFormatParts = [];
        if (eventData.type) {
            const typeMap = { 'event': 'Event', 'meeting': 'Meeting', 'speaking_engagement': 'Speaking', 'ceremony': 'Ceremony', 'tour': 'Tour', 'phone_call': 'Phone Call', 'other': 'Other' };
            typeFormatParts.push(typeMap[eventData.type] || eventData.type);
        }
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
                    <button type="button" class="v2-add-staff-btn" id="cal-detail-add-staff">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Add Staff
                    </button>
                    <div class="v2-staff-dropdown" id="cal-detail-staff-dropdown"></div>
                </div>`
            : '';
        if (eventData.staff && eventData.staff.length > 0) {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>Assigned staff</span>
                <div class="v2-readonly-staff-list" id="cal-detail-staff-list">
                    ${eventData.staff.map(s => `<span class="v2-readonly-staff-pill">${escapeHtml(s)}</span>`).join('')}
                    ${addStaffBtn}
                </div>
            </div>`;
        } else {
            secondaryHtml += `<div class="v2-readonly-section">
                <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>Assigned staff</span>
                <div class="v2-readonly-staff-list" id="cal-detail-staff-list">
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

        // Review routing
        let reviewHtml = '';
        if (eventData.approval_routing && eventData.approval_routing.stages && eventData.approval_routing.stages.length > 0) {
            reviewHtml = this._buildCalendarReviewTableHtml(eventData, escapeHtml);
        }

        // Footer buttons
        let footerHtml = '';
        if (eventData.can_edit !== false) {
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-edit" id="cal-detail-btn-edit">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                <span class="btn-label">Edit</span>
            </button>`;
        }
        // Show Email button (only if has emails)
        const hasEmails = eventData.has_original_email || (eventData.attached_emails_data && eventData.attached_emails_data.length > 0);
        if (eventData.can_edit !== false && hasEmails) {
            footerHtml += `<button class="detail-panel-btn detail-panel-btn-email" id="cal-detail-btn-email" title="Show email">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                <span class="btn-label">Show Email</span>
            </button>`;
        }
        // (Copy moved to more menu)

        // Build status dropdown options if user can edit
        const statusChoicesMap = {
            'received': 'Received', 'hold': 'Hold', 'referred': 'Referred',
            'fyied': 'FYI\'ed', 'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled', 'rsvped': 'RSVP\'d',
            'regrets_sent': 'Regrets Sent', 'passed': 'Passed',
            'canceled': 'Canceled', 'requires_hms_review': 'Needs Review'
        };
        const statusDropdownOptions = Object.entries(statusChoicesMap).map(([value, label]) => {
            const selectedClass = value === statusSlug ? 'selected' : '';
            const optionStatusClass = `status-${value}`;
            return `<div class="schedule-dropdown-option ${selectedClass} ${optionStatusClass}" data-value="${value}">${label}</div>`;
        }).join('');

        content.innerHTML = `
            <div class="detail-panel-header">
                <div class="detail-panel-header-left">
                    <div class="detail-panel-title">${escapeHtml(eventData.title) || 'Untitled Event'}</div>
                    <div class="detail-panel-org-status">
                        ${eventData.group ? `<span class="detail-panel-org">${escapeHtml(eventData.group)}</span>` : ''}
                        ${eventData.can_edit !== false ? `
                        <div class="detail-panel-status-dropdown-wrapper" id="cal-detail-status-wrapper" data-event-id="${eventData.id}">
                            <div class="detail-panel-status ${statusClass}" id="cal-detail-status-badge" tabindex="0" role="button">
                                <span class="detail-panel-status-text">${statusLabel}</span>
                            </div>
                            <div class="detail-panel-dropdown-menu" id="cal-detail-dropdown-menu">
                                ${statusDropdownOptions}
                            </div>
                        </div>` : `
                        <span class="detail-panel-status ${statusClass}" id="cal-detail-status-badge">${statusLabel}</span>`}
                    </div>
                </div>
                <div class="detail-panel-header-actions">
                    <div class="detail-panel-more-wrapper">
                        <button class="detail-panel-more-btn" id="cal-detail-more-btn" aria-label="More options" title="More options">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="12" cy="5" r="1"></circle>
                                <circle cx="12" cy="12" r="1"></circle>
                                <circle cx="12" cy="19" r="1"></circle>
                            </svg>
                        </button>
                        <div class="detail-panel-more-menu" id="cal-detail-more-menu">
                            <button class="detail-panel-more-menu-item" id="cal-detail-btn-copy">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                Copy Details
                            </button>
                            <button class="detail-panel-more-menu-item" id="cal-detail-btn-export">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                                Export Word
                            </button>
                            ${eventData.can_edit !== false ? `
                            <button class="detail-panel-more-menu-item detail-panel-more-menu-item-danger" id="cal-detail-btn-delete">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                                Delete
                            </button>` : ''}
                        </div>
                    </div>
                    <button class="detail-panel-close" id="cal-detail-close-btn" aria-label="Close" title="Close">
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
                </div>
                ${reviewHtml}
                ${missingHtml}
            </div>
            <div class="detail-panel-footer">
                ${footerHtml}
            </div>
        `;

        this._bindCalendarDetailPanelEvents(eventData);
    }

    _buildCalendarReviewTableHtml(eventData, escapeHtml) {
        try {
            const routing = eventData.approval_routing;
            if (!routing || !routing.stages || routing.stages.length === 0) return '';

            const approvals = eventData.approvals || [];
            let rows = '';

            for (const stage of routing.stages) {
                for (const approver of (stage.approvers || [])) {
                    const name = approver.name || 'Unknown';
                    const approval = approvals.find(a =>
                        a.stage_id === stage.stage_id &&
                        String(a.approver_id || a.approver) === String(approver.user_id)
                    );

                    let statusText = 'Pending';
                    let statusClass = 'review-status-pending';
                    if (approval) {
                        if (approval.status === 'approved') {
                            statusText = 'Approved';
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

    _bindCalendarDetailPanelEvents(eventData) {
        // Close button
        document.getElementById('cal-detail-close-btn')?.addEventListener('click', () => this.closeDetailPanel());

        // Status dropdown
        const statusWrapper = document.getElementById('cal-detail-status-wrapper');
        const statusBadge = document.getElementById('cal-detail-status-badge');
        const statusMenu = document.getElementById('cal-detail-dropdown-menu');
        if (statusWrapper && statusBadge && statusMenu) {
            statusBadge.addEventListener('click', (e) => {
                e.stopPropagation();
                if (statusWrapper.classList.contains('open')) {
                    this._closeCalDetailStatusDropdown(statusWrapper, statusMenu);
                    return;
                }
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
                let top = (viewportHeight - rect.bottom >= menuHeight) ? rect.bottom : rect.top - menuHeight;
                if (top + menuHeight > viewportHeight - 8) top = viewportHeight - menuHeight - 8;
                if (top < 8) top = 8;
                statusMenu.style.top = top + 'px';
                statusMenu.style.left = left + 'px';
                statusMenu.style.visibility = '';
                statusWrapper.classList.add('open');
            });
            statusBadge.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); statusBadge.click(); }
            });
            statusMenu.querySelectorAll('.schedule-dropdown-option').forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const newStatus = option.dataset.value;
                    const newStatusClass = `status-${newStatus.toLowerCase().replace(/\s+/g, '_')}`;
                    statusBadge.className = `detail-panel-status ${newStatusClass}`;
                    statusBadge.querySelector('.detail-panel-status-text').textContent = option.textContent.trim();
                    statusMenu.querySelectorAll('.schedule-dropdown-option').forEach(o => o.classList.remove('selected'));
                    option.classList.add('selected');
                    this._closeCalDetailStatusDropdown(statusWrapper, statusMenu);
                    this._calDetailStatusChange(eventData.id, newStatus);
                });
            });
            document.addEventListener('click', (e) => {
                if (statusWrapper.classList.contains('open') && !e.target.closest('#cal-detail-status-wrapper')) {
                    this._closeCalDetailStatusDropdown(statusWrapper, statusMenu);
                }
            });
        }

        // More menu toggle
        const moreBtn = document.getElementById('cal-detail-more-btn');
        const moreMenu = document.getElementById('cal-detail-more-menu');
        if (moreBtn && moreMenu) {
            moreBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                moreMenu.classList.toggle('visible');
            });
            document.addEventListener('click', (e) => {
                if (moreMenu.classList.contains('visible') && !e.target.closest('.detail-panel-more-wrapper')) {
                    moreMenu.classList.remove('visible');
                }
            });
            const moreWrapper = moreBtn.closest('.detail-panel-more-wrapper');
            if (moreWrapper) {
                moreWrapper.addEventListener('mouseleave', () => {
                    moreMenu.classList.remove('visible');
                });
            }
        }

        // Missing fields toggle
        document.getElementById('cal-detail-missing-toggle')?.addEventListener('click', () => {
            const list = document.getElementById('cal-detail-missing-list');
            const toggle = document.getElementById('cal-detail-missing-toggle');
            if (list && toggle) {
                const expanded = toggle.getAttribute('aria-expanded') === 'true';
                toggle.setAttribute('aria-expanded', !expanded);
                list.classList.toggle('visible');
                list.setAttribute('aria-hidden', expanded);
                toggle.querySelector('.v2-readonly-missing-chevron')?.classList.toggle('rotated');
            }
        });

        // Copy Details (in more menu)
        document.getElementById('cal-detail-btn-copy')?.addEventListener('click', async () => {
            document.getElementById('cal-detail-more-menu')?.classList.remove('visible');
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
                const btn = document.getElementById('cal-detail-btn-copy');
                if (btn) {
                    const originalHTML = btn.innerHTML;
                    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied!`;
                    setTimeout(() => { btn.innerHTML = originalHTML; }, 1500);
                }
            } catch (e) {
                console.error('Copy failed:', e);
            }
        });

        // Export Word button (detail panel more menu)
        if (typeof HillDeskExport !== 'undefined') {
            HillDeskExport.bindDetailPanelExport(
                'cal-detail-btn-export',
                'cal-detail-more-menu',
                eventData,
                this.csrfToken
            );
        }

        // Edit button
        document.getElementById('cal-detail-btn-edit')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id);
            } else {
                window.location.href = `/event-editing/${eventData.id}/`;
            }
        });

        // Delete button (in more menu)
        document.getElementById('cal-detail-btn-delete')?.addEventListener('click', () => {
            document.getElementById('cal-detail-more-menu')?.classList.remove('visible');
            this.deleteEventFromPanel(eventData);
        });

        // Show Email button
        document.getElementById('cal-detail-btn-email')?.addEventListener('click', () => {
            if (typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(eventData.id, { showEmailPane: true });
            }
        });

        // Add Staff button with dropdown
        const addStaffBtnEl = document.getElementById('cal-detail-add-staff');
        const staffDropdown = document.getElementById('cal-detail-staff-dropdown');
        if (addStaffBtnEl && staffDropdown) {
            addStaffBtnEl.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (staffDropdown.classList.contains('visible')) {
                    this._hideCalDetailStaffDropdown(staffDropdown);
                    return;
                }
                await this._showCalDetailStaffDropdown(eventData, addStaffBtnEl, staffDropdown);
            });
            document.addEventListener('click', (e) => {
                if (staffDropdown.classList.contains('visible') && !e.target.closest('.v2-staff-dropdown-wrapper')) {
                    this._hideCalDetailStaffDropdown(staffDropdown);
                }
            });
        }

        // Fetch and render overlaps
        this._fetchCalDetailOverlaps(eventData);
    }

    _closeCalDetailStatusDropdown(wrapper, menu) {
        wrapper.classList.remove('open');
        if (menu.parentNode === document.body) {
            menu.style.display = '';
            menu.style.top = '';
            menu.style.left = '';
            menu.style.visibility = '';
            wrapper.appendChild(menu);
        }
    }

    async _calDetailStatusChange(eventId, newStatus) {
        try {
            await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ status: newStatus }),
                credentials: 'same-origin'
            });
            if (this.state.detailPanelEventData) this.state.detailPanelEventData.status = newStatus;
            // Re-render calendar to reflect new status
            this.renderCurrentView();
        } catch (error) {
            console.error('Failed to update status:', error);
        }
    }

    async _showCalDetailStaffDropdown(eventData, button, dropdown) {
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
        dropdown.querySelectorAll('.v2-staff-dropdown-item:not(.disabled)').forEach(item => {
            item.addEventListener('click', async () => {
                const staffName = item.dataset.staffName;
                this._hideCalDetailStaffDropdown(dropdown);
                await this._addStaffCalDetail(eventData, staffName);
            });
        });
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

    _hideCalDetailStaffDropdown(dropdown) {
        dropdown.classList.remove('visible');
        if (dropdown.parentNode === document.body) {
            const wrapper = document.getElementById('cal-detail-add-staff')?.closest('.v2-staff-dropdown-wrapper');
            if (wrapper) {
                dropdown.style.top = '';
                dropdown.style.left = '';
                wrapper.appendChild(dropdown);
            }
        }
    }

    async _addStaffCalDetail(eventData, staffName) {
        const newStaff = [...(eventData.staff || []), staffName];
        try {
            const resp = await fetch(`/api/events/${eventData.id}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': this.csrfToken
                },
                credentials: 'same-origin',
                body: JSON.stringify({ staff: newStaff })
            });
            if (resp.ok) {
                eventData.staff = newStaff;
                const staffList = document.getElementById('cal-detail-staff-list');
                const wrapper = staffList?.querySelector('.v2-staff-dropdown-wrapper');
                if (staffList && wrapper) {
                    const pill = document.createElement('span');
                    pill.className = 'v2-readonly-staff-pill';
                    pill.textContent = staffName;
                    staffList.insertBefore(pill, wrapper);
                }
                this.renderCurrentView();
            }
        } catch (e) {
            console.error('Failed to add staff:', e);
        }
    }

    async _fetchCalDetailOverlaps(eventData) {
        if (!eventData.start_date || !eventData.start_time || !eventData.end_date || !eventData.end_time) return;
        try {
            const resp = await fetch(`/api/events/${eventData.id}/overlaps/`, {
                headers: { 'Accept': 'application/json', 'X-CSRFToken': this.csrfToken }
            });
            if (!resp.ok) return;
            const overlaps = await resp.json();
            if (!overlaps.length || this.state.detailPanelEventId != eventData.id) return;
            this._renderCalDetailOverlaps(eventData, overlaps);
        } catch (e) {
            console.warn('Failed to fetch overlaps:', e);
        }
    }

    _renderCalDetailOverlaps(eventData, overlaps) {
        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };
        const formatTime = (timeStr) => {
            if (!timeStr) return '';
            try {
                const [h, m] = timeStr.split(':');
                const d = new Date(); d.setHours(parseInt(h), parseInt(m));
                return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
            } catch (e) { return timeStr; }
        };
        const statusMap = {
            'received': 'Received', 'hold': 'Hold', 'referred': 'Referred',
            'fyied': 'FYI\'ed', 'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled', 'rsvped': 'RSVP\'d',
            'regrets_sent': 'Regrets Sent', 'passed': 'Passed',
            'canceled': 'Canceled', 'requires_hms_review': 'Needs Review'
        };

        const itemsHtml = overlaps.map(o => {
            const timeStr = o.start_time ? formatTime(o.start_time) + (o.end_time ? ' \u2013 ' + formatTime(o.end_time) : '') : '';
            const slug = (o.status || 'received').toLowerCase().replace(/\s+/g, '_');
            return `<div class="overlap-item" role="button" tabindex="0" data-event-id="${o.id}" aria-label="Open ${escapeHtml(o.title)}">
                <span class="overlap-title">${escapeHtml(o.title)}</span>
                <span class="overlap-time">${timeStr}</span>
                <span class="detail-panel-status status-${slug}">${escapeHtml(statusMap[slug] || o.status)}</span>
            </div>`;
        }).join('');

        const sectionHtml = `<div class="v2-readonly-section overlap-section">
            <span class="v2-readonly-label"><svg class="v2-label-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="13" stroke-width="3"></line><circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"></circle></svg>Overlaps with</span>
            <div class="overlap-list">${itemsHtml}</div>
        </div>`;

        const secondary = this.detailPanelContent?.querySelector('.v2-readonly-secondary');
        if (!secondary) return;

        const temp = document.createElement('div');
        temp.innerHTML = sectionHtml;
        const overlapEl = temp.firstElementChild;
        secondary.prepend(overlapEl);

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
                    'X-CSRFToken': this.csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            if (!response.ok && response.status !== 204) {
                throw new Error(`HTTP ${response.status}`);
            }
            this.closeDetailPanel();
            this.fetchEvents();
            if (typeof window.showMessage === 'function') {
                window.showMessage('Moved to Deleted Events', 'success');
            }
        } catch (error) {
            console.error('calendarRedesign: Failed to delete event', error);
            if (typeof window.showMessage === 'function') {
                window.showMessage('Failed to delete event', 'error');
            }
        }
    }

    closeDetailPanel() {
        this.state.detailPanelEventId = null;
        this.state.detailPanelEventData = null;

        if (this.detailPanel) this.detailPanel.classList.remove('open');

        // Remove selected state from all calendar events
        document.querySelectorAll('.event-block.calendar-event-active, .event-chip.calendar-event-active, .allday-event-bar.calendar-event-active, .schedule-event-row.calendar-event-active')
            .forEach(el => el.classList.remove('calendar-event-active'));
    }

    // =========================================================================
    // Favorite Filters
    // =========================================================================

    async _fetchStaffList() {
        try {
            const resp = await fetch('/api/office/choices/', {
                headers: { 'X-CSRFToken': this.csrfToken }
            });
            if (!resp.ok) return;
            const data = await resp.json();
            this._staffList = (data.staff_members || []).map(s => ({
                name: s.name,
                id: s.id
            }));
            this.renderFilters();
            this._syncFilterCheckboxes();
        } catch (e) {
            console.error('Error fetching staff list:', e);
        }
    }

    _syncFilterCheckboxes() {
        ['status', 'category', 'format', 'staff', 'source'].forEach(filterType => {
            const activeFilters = this.state.filters[filterType];
            const section = this.elements.sidebarContent?.querySelector(`[data-section="${filterType}"]`);
            if (!section) return;
            const checkboxes = section.querySelectorAll('input[type="checkbox"]:not([id$="-select-all"])');
            const selectAll = section.querySelector('[id$="-select-all"]');

            if (activeFilters.length === 0) {
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
        const myEvtsCb = document.getElementById('cal-filter-my-events');
        const overlapCb = document.getElementById('cal-filter-overlapping');
        if (myEvtsCb) myEvtsCb.checked = this.state.filters.myEvents;
        if (overlapCb) overlapCb.checked = this.state.filters.overlappingOnly;
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
}

// Export for use
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CalendarRedesign;
}
