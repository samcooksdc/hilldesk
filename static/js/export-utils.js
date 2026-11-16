/* SPDX-License-Identifier: Apache-2.0 */
/**
 * HillDesk Export Utilities
 * Shared export/download functionality for schedule and calendar views.
 */
const HillDeskExport = {

    /**
     * Get CSRF token from cookie, global config, or meta tag.
     */
    getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return value;
        }
        if (window.scheduleConfig?.csrfToken) return window.scheduleConfig.csrfToken;
        if (window.calendarConfig?.csrfToken) return window.calendarConfig.csrfToken;
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag?.content) return metaTag.content;
        return '';
    },

    /**
     * Download a single event as Word document (event_detail template).
     * @param {string} eventId - Event UUID
     * @param {string} eventTitle - Event title for filename
     * @param {string} [csrfToken] - Optional CSRF token override
     * @returns {Promise<void>}
     */
    async downloadEventDocx(eventId, eventTitle, csrfToken) {
        csrfToken = csrfToken || this.getCsrfToken();
        const response = await fetch('/api/events/export/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({
                template_type: 'event_detail',
                event_ids: [eventId],
            }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || `Export failed (${response.status})`);
        }
        const blob = await response.blob();
        const safeName = (eventTitle || 'event').replace(/[^a-zA-Z0-9\-_ ]/g, '').trim().replace(/\s+/g, '_');
        this._downloadBlob(blob, `${safeName}_detail.docx`);
    },

    /**
     * Download a bulk export as Word document.
     * @param {string} templateType - daily_briefing | weekly_overview | filtered_list
     * @param {Object} options - Filter/date options
     * @param {string} [csrfToken] - Optional CSRF token override
     * @returns {Promise<{async: boolean, taskId?: string}>}
     */
    async downloadBulkDocx(templateType, options = {}, csrfToken) {
        csrfToken = csrfToken || this.getCsrfToken();
        const body = { template_type: templateType };
        if (options.date) body.date = options.date;
        if (options.status_filter) body.status_filter = options.status_filter;
        if (options.type_filter) body.type_filter = options.type_filter;
        if (options.search) body.search = options.search;
        if (options.active_filters) body.active_filters = options.active_filters;
        if (options.event_ids) body.event_ids = options.event_ids;

        const response = await fetch('/api/events/export/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(body),
        });

        // Check for async (202) response
        if (response.status === 202) {
            const data = await response.json();
            return { async: true, taskId: data.task_id };
        }

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.error || `Export failed (${response.status})`);
        }

        const blob = await response.blob();
        const dateStr = new Date().toISOString().slice(0, 10);
        this._downloadBlob(blob, `${templateType}_${dateStr}.docx`);
        return { async: false };
    },

    /**
     * Download CSV export of events.
     * @param {Object} filters - Query param filters
     * @returns {Promise<void>}
     */
    async downloadCsv(filters = {}) {
        const params = new URLSearchParams();
        if (filters.status) params.set('status', Array.isArray(filters.status) ? filters.status.join(',') : filters.status);
        if (filters.type) params.set('type', Array.isArray(filters.type) ? filters.type.join(',') : filters.type);
        if (filters.search) params.set('search', filters.search);
        if (filters.start_date) params.set('start_date', filters.start_date);
        if (filters.end_date) params.set('end_date', filters.end_date);

        const qs = params.toString();
        const url = `/api/events/export/csv/${qs ? '?' + qs : ''}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`CSV export failed (${response.status})`);

        const blob = await response.blob();
        const dateStr = new Date().toISOString().slice(0, 10);
        this._downloadBlob(blob, `events_${dateStr}.csv`);
    },

    /**
     * Trigger browser download from a Blob.
     */
    _downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    },

    /**
     * Format today's date as ISO string.
     */
    todayISO() {
        return new Date().toISOString().slice(0, 10);
    },

    /**
     * Get Monday of the current week as ISO string.
     */
    weekStartISO(date) {
        const d = date ? new Date(date) : new Date();
        const day = d.getDay();
        const diff = d.getDate() - day + (day === 0 ? -6 : 1);
        d.setDate(diff);
        return d.toISOString().slice(0, 10);
    },

    /**
     * Build the export dropdown HTML for page headers.
     * @param {string} idPrefix - 'schedule' or 'calendar' for unique IDs
     * @returns {string} HTML string
     */
    buildExportDropdownHTML(idPrefix) {
        return `
            <div class="export-dropdown-wrapper" id="${idPrefix}-export-wrapper">
                <button class="export-btn" id="${idPrefix}-export-btn" title="Export events">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                    <span class="export-btn-label">Export</span>
                </button>
                <div class="export-dropdown-menu" id="${idPrefix}-export-menu">
                    <button class="export-dropdown-item" data-export="daily_briefing">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                        Daily Briefing
                    </button>
                    <button class="export-dropdown-item" data-export="weekly_overview">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z"></path><path d="M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"></path></svg>
                        Weekly Overview
                    </button>
                    <button class="export-dropdown-item" data-export="filtered_list">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>
                        Filtered List
                    </button>
                    <div class="export-dropdown-divider"></div>
                    <button class="export-dropdown-item" data-export="csv">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                        CSV Spreadsheet
                    </button>
                </div>
            </div>`;
    },

    /**
     * Bind export dropdown toggle and item click handlers.
     * @param {string} idPrefix - 'schedule' or 'calendar'
     * @param {Function} getExportOptions - Returns {date, filters, activeFilters} for the current view
     * @param {string} [csrfToken] - Optional CSRF token override
     */
    bindExportDropdown(idPrefix, getExportOptions, csrfToken) {
        const btn = document.getElementById(`${idPrefix}-export-btn`);
        const menu = document.getElementById(`${idPrefix}-export-menu`);
        if (!btn || !menu) return;

        // Toggle dropdown
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.toggle('visible');
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (menu.classList.contains('visible') && !e.target.closest(`#${idPrefix}-export-wrapper`)) {
                menu.classList.remove('visible');
            }
        });

        // Item click handlers
        menu.querySelectorAll('.export-dropdown-item').forEach(item => {
            item.addEventListener('click', async (e) => {
                e.stopPropagation();
                menu.classList.remove('visible');

                const exportType = item.dataset.export;
                const opts = getExportOptions();
                const originalHTML = item.innerHTML;

                // Loading state
                item.innerHTML = `<svg class="export-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" opacity="0.25"></circle><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"></path></svg> Exporting...`;
                item.disabled = true;

                try {
                    if (exportType === 'csv') {
                        await HillDeskExport.downloadCsv(opts.filters || {});
                    } else {
                        await HillDeskExport.downloadBulkDocx(exportType, {
                            date: opts.date || HillDeskExport.todayISO(),
                            status_filter: opts.filters?.status?.[0],
                            type_filter: opts.filters?.category?.[0],
                            search: opts.filters?.search,
                            active_filters: opts.activeFilters,
                        }, csrfToken);
                    }
                    // Success feedback
                    item.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg> Downloaded!`;
                    setTimeout(() => { item.innerHTML = originalHTML; item.disabled = false; }, 1500);
                } catch (err) {
                    console.error('Export failed:', err);
                    item.innerHTML = originalHTML;
                    item.disabled = false;
                    // Surface the server's message (e.g. "Upload a template for
                    // this export type first.") when present.
                    HillDeskExport._showExportToast(err.message || 'Export failed. Please try again.', 'error');
                }
            });
        });
    },

    /**
     * Show a brief toast notification.
     */
    _showExportToast(message, type = 'info') {
        const existing = document.querySelector('.export-toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = `export-toast export-toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('visible'));
        setTimeout(() => {
            toast.classList.remove('visible');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    },

    /**
     * Bind the detail panel export button for a single event.
     * @param {string} btnId - Button element ID
     * @param {string} menuId - More menu ID to close on click
     * @param {Object} eventData - Event data with id and title
     * @param {string} [csrfToken] - CSRF token
     */
    bindDetailPanelExport(btnId, menuId, eventData, csrfToken) {
        const btn = document.getElementById(btnId);
        if (!btn) return;

        btn.addEventListener('click', async () => {
            // Close more menu
            document.getElementById(menuId)?.classList.remove('visible');

            const originalHTML = btn.innerHTML;
            btn.innerHTML = `<svg class="export-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" opacity="0.25"></circle><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"></path></svg> Exporting...`;

            try {
                await HillDeskExport.downloadEventDocx(eventData.id, eventData.title, csrfToken);
                btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg> Downloaded!`;
                setTimeout(() => { btn.innerHTML = originalHTML; }, 1500);
            } catch (err) {
                console.error('Export failed:', err);
                btn.innerHTML = originalHTML;
                HillDeskExport._showExportToast(err.message || 'Export failed. Please try again.', 'error');
            }
        });
    }
};
