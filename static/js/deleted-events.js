/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Deleted Events tab (Settings)
 *
 * Lists soft-deleted (archived) events, and lets the user restore them to the
 * schedule or permanently delete them. Cards are styled to match the event
 * cards on the Schedule tab for visual consistency.
 *
 * Backend:
 *   GET    /api/events/?archived_only=true   -> list deleted events
 *   POST   /api/events/<id>/restore/         -> restore (unarchive)
 *   DELETE /api/events/<id>/?include_archived=1 -> permanent delete
 */
(function () {
    'use strict';

    class DeletedEvents {
        constructor() {
            this.listEl = document.getElementById('deleted-events-list');
            this.searchEl = document.getElementById('deleted-events-search');
            this.tabBtn = document.querySelector('.settings-tab[data-tab="deleted-events"]');
            this.loaded = false;
            this.events = [];
            this.init();
        }

        init() {
            if (!this.listEl) return;

            // Lazy-load the first time the tab is opened.
            if (this.tabBtn) {
                this.tabBtn.addEventListener('click', () => this.ensureLoaded());
            }

            // Deep link: /settings/?tab=deleted-events
            const tabParam = new URLSearchParams(window.location.search).get('tab');
            if (tabParam === 'deleted-events') {
                this.ensureLoaded();
            }

            if (this.searchEl) {
                this.searchEl.addEventListener('input', () => this.render());
            }
        }

        ensureLoaded() {
            if (this.loaded) return;
            this.loaded = true;
            this.load();
        }

        async load() {
            this.listEl.innerHTML = '<div class="deleted-events-placeholder">Loading deleted events…</div>';
            try {
                const events = [];
                let url = '/api/events/?archived_only=true&page_size=100&ordering=-modified';
                // Walk pagination so we get every deleted event, not just the first page.
                while (url) {
                    const resp = await fetch(url, {
                        headers: { 'X-Requested-With': 'XMLHttpRequest' },
                        credentials: 'same-origin'
                    });
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const data = await resp.json();
                    const page = Array.isArray(data) ? data : (data.results || []);
                    events.push(...page);
                    url = (!Array.isArray(data) && data.next) ? data.next : null;
                }
                // Most recently deleted first.
                events.sort((a, b) => new Date(b.archived_date || 0) - new Date(a.archived_date || 0));
                this.events = events;
                this.render();
            } catch (err) {
                console.error('DeletedEvents: failed to load', err);
                this.listEl.innerHTML =
                    '<div class="deleted-events-placeholder deleted-events-error">' +
                    'Could not load deleted events. Please try again.</div>';
            }
        }

        render() {
            const query = (this.searchEl?.value || '').trim().toLowerCase();
            let events = this.events;
            if (query) {
                events = events.filter(e => {
                    const hay = [e.title, e.group, e.location, e.point_of_contact_name]
                        .filter(Boolean).join(' ').toLowerCase();
                    return hay.includes(query);
                });
            }

            if (!this.events.length) {
                this.listEl.innerHTML =
                    '<div class="deleted-events-empty">' +
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">' +
                    '<polyline points="3 6 5 6 21 6"></polyline>' +
                    '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>' +
                    '</svg><p>No deleted events.</p>' +
                    '<span>Events you delete from the schedule will appear here.</span></div>';
                return;
            }

            if (!events.length) {
                this.listEl.innerHTML =
                    '<div class="deleted-events-empty"><p>No deleted events match your search.</p></div>';
                return;
            }

            this.listEl.innerHTML = events.map(e => this.renderCard(e)).join('');
            this.bindCardActions();
        }

        renderCard(event) {
            const statusKey = event.status
                ? event.status.toLowerCase().replace(/\s+/g, '_')
                : '';
            const statusClass = statusKey ? ` status-${statusKey}` : '';

            const title = this.escape(event.title || 'Untitled Event');
            const org = event.group && event.group !== event.title
                ? ` <span class="de-card-org">· ${this.escape(event.group)}</span>`
                : '';

            const metaString = this.buildMeta(event);

            return `
                <div class="de-card${statusClass}" data-event-id="${event.id}">
                    <div class="de-card-status-bar"></div>
                    <div class="de-card-body">
                        <div class="de-card-left">
                            <div class="de-card-title">${title}${org}</div>
                            <div class="de-card-meta-line">${metaString}</div>
                        </div>
                        <div class="de-card-actions">
                            <button type="button" class="de-card-btn de-restore" data-event-id="${event.id}">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M3 12a9 9 0 1 0 9-9 9 9 0 0 0-6.36 2.64L3 8"></path>
                                    <polyline points="3 3 3 8 8 8"></polyline>
                                </svg>
                                Restore
                            </button>
                            <button type="button" class="de-card-btn de-delete" data-event-id="${event.id}">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }

        buildMeta(event) {
            const parts = [];

            // Date (+ optional time), mirroring the Schedule card format.
            if (event.start_date) {
                const start = new Date(event.start_date + 'T00:00:00');
                const opts = start.getFullYear() !== new Date().getFullYear()
                    ? { month: 'short', day: 'numeric', year: 'numeric' }
                    : { month: 'short', day: 'numeric' };
                let datePart = start.toLocaleDateString('en-US', opts);
                if (event.end_date && event.end_date !== event.start_date) {
                    const end = new Date(event.end_date + 'T00:00:00');
                    datePart += ' – ' + end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                }
                parts.push(datePart);
                if (event.start_time) {
                    const t = new Date(`2000-01-01T${event.start_time}`);
                    parts.push(t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }));
                }
            }

            // Deleted-on line.
            if (event.archived_date) {
                const d = new Date(event.archived_date);
                let deleted = 'Deleted ' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                if (event.archived_by) deleted += ' by ' + this.escape(String(event.archived_by));
                parts.push(deleted);
            }

            return parts.map(p => `<span>${p}</span>`).join('<span class="de-card-sep">·</span>');
        }

        bindCardActions() {
            this.listEl.querySelectorAll('.de-restore').forEach(btn => {
                btn.addEventListener('click', () => this.restore(btn.dataset.eventId, btn));
            });
            this.listEl.querySelectorAll('.de-delete').forEach(btn => {
                btn.addEventListener('click', () => this.permanentDelete(btn.dataset.eventId, btn));
            });
        }

        async restore(eventId, btn) {
            this.setRowBusy(btn, true);
            try {
                const resp = await fetch(`/api/events/${eventId}/restore/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.getCsrf(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin'
                });
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                this.removeEvent(eventId);
            } catch (err) {
                console.error('DeletedEvents: restore failed', err);
                this.setRowBusy(btn, false);
                alert('Could not restore this event. Please try again.');
            }
        }

        async permanentDelete(eventId, btn) {
            const ok = confirm('Permanently delete this event? This cannot be undone.');
            if (!ok) return;
            this.setRowBusy(btn, true);
            try {
                // include_archived so the API queryset can find the archived row.
                const resp = await fetch(`/api/events/${eventId}/?include_archived=1`, {
                    method: 'DELETE',
                    headers: {
                        'X-CSRFToken': this.getCsrf(),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin'
                });
                if (!resp.ok && resp.status !== 204) throw new Error(`HTTP ${resp.status}`);
                this.removeEvent(eventId);
            } catch (err) {
                console.error('DeletedEvents: permanent delete failed', err);
                this.setRowBusy(btn, false);
                alert('Could not delete this event. Please try again.');
            }
        }

        removeEvent(eventId) {
            this.events = this.events.filter(e => String(e.id) !== String(eventId));
            this.render();
        }

        setRowBusy(btn, busy) {
            const card = btn.closest('.de-card');
            if (card) card.classList.toggle('de-card-busy', busy);
        }

        getCsrf() {
            const input = document.querySelector('[name=csrfmiddlewaretoken]');
            if (input && input.value) return input.value;
            const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
            return match ? decodeURIComponent(match[1]) : '';
        }

        escape(str) {
            const div = document.createElement('div');
            div.textContent = str == null ? '' : String(str);
            return div.innerHTML;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        window.deletedEvents = new DeletedEvents();
    });
})();
