/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Contacts Directory — inbox-style list-detail behaviour.
 *
 * People and Organizations are both rendered into one page; the toggle switches
 * between them client-side (no navigation). Layered behaviour:
 *   - People / Organizations toggle (filters the single list by data-kind)
 *   - "Recent" default sort: the left list shows recently-opened records until a
 *     search is typed, then it falls back to A–Z over the whole set
 *   - instant client-side search over name / email / organization / location
 *   - an inbox-style filter sidebar ("Show only" toggles)
 *   - row selection that fetches the record's detail-panel fragment on click,
 *     an X button that clears the selection, and up/down keyboard navigation
 */
(function () {
    'use strict';

    // Recently-viewed is shared with the event contacts panel (event-contacts-panel.js)
    // so opening a record in either place keeps one cross-app history.
    var SHARED_RECENTS_KEY = 'ec_recents_v1';
    var SHARED_CAP = 50;        // entries persisted per kind
    var RECENT_DISPLAY = 15;    // entries surfaced in the directory list

    function init() {
        var list = document.getElementById('contacts-list');
        var panelContent = document.getElementById('contacts-detail-panel-content');
        var detailPanel = document.getElementById('contacts-detail-panel');
        var wrapper = document.querySelector('.schedule-list-detail-wrapper');
        if (!list || !panelContent) return;

        var searchInput = document.getElementById('contacts-search-input');
        var searchClear = document.getElementById('contacts-search-clear');
        var emptyState = document.getElementById('contacts-empty');
        var sortSelect = document.getElementById('contacts-sort-select');
        var tabs = Array.prototype.slice.call(document.querySelectorAll('.contacts-tab'));

        var filterSidebar = document.getElementById('contacts-filter-sidebar');
        var filtersToggleBtn = document.getElementById('filters-toggle-btn');
        var sidebarCloseBtn = document.getElementById('sidebar-close-btn');
        var clearFiltersBtn = document.getElementById('contacts-clear-filters');
        var filterBoxes = Array.prototype.slice.call(list ? document.querySelectorAll('#contacts-filter-sidebar input[data-filter-attr]') : []);

        var viewContainer = document.getElementById('contacts-view-container');
        var rows = Array.prototype.slice.call(list.querySelectorAll('.contact-card'));

        // ---- skeleton builders (match the app's shimmer + each shape) -------
        function panelSkeletonHtml() {
            function section(n) {
                var r = '';
                for (var i = 0; i < n; i++) {
                    r += '<div class="cdp-sk-row"><div class="skeleton sk-row-title"></div><div class="skeleton sk-row-meta"></div></div>';
                }
                return '<div class="cdp-sk-section"><div class="skeleton sk-label"></div><div class="cdp-sk-box">' + r + '</div></div>';
            }
            return '<div class="detail-panel-skeleton cdp-skeleton" role="status" aria-label="Loading details" aria-hidden="true">'
                + '<div class="detail-panel-header"><div class="detail-panel-header-left">'
                + '<div class="skeleton skeleton-dp-title"></div><div class="skeleton skeleton-dp-subtitle"></div>'
                + '</div><div class="skeleton skeleton-dp-close"></div></div>'
                + '<div class="detail-panel-body cdp-body">'
                + '<div class="cdp-sk-grid">'
                + '<div class="cdp-sk-col"><div class="skeleton sk-label"></div><div class="skeleton sk-line"></div></div>'
                + '<div class="cdp-sk-col"><div class="skeleton sk-label"></div><div class="skeleton sk-line"></div></div>'
                + '</div>' + section(3) + section(2) + '</div></div>';
        }

        function emailSkeletonHtml() {
            return '<div class="cdp-email-skeleton" role="status" aria-label="Loading email" aria-hidden="true">'
                + '<div class="v2-email-item">'
                + '<div class="v2-email-header"><div class="skeleton sk-from"></div><div class="skeleton sk-date"></div></div>'
                + '<div class="skeleton sk-subject"></div>'
                + '<div class="sk-body"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>'
                + '</div></div>';
        }

        var cfg = window.contactsDirectoryConfig || {};
        var kind = cfg.initialTab === 'organizations' ? 'organizations' : 'people';
        var selectedId = null;
        var selectedRow = null;
        // Remembers the last row selected on each tab, so arrow-swapping back to
        // a tab can restore its previous selection instead of jumping to the top.
        var lastSelectedByTab = { people: null, organizations: null };
        var loadToken = 0;

        // Section header shown above the list in "Recent" mode.
        var recentHeader = document.createElement('div');
        recentHeader.className = 'contacts-section-header';
        recentHeader.innerHTML = '<span class="contacts-section-label">Recently viewed</span>';

        // ---- helpers --------------------------------------------------------
        function kindNoun() { return kind === 'organizations' ? 'organizations' : 'contacts'; }

        function num(row, attr) { return parseInt(row.getAttribute(attr) || '0', 10) || 0; }

        // The shared store keys People under 'contacts' (matching the event panel).
        function storeKind() { return kind === 'organizations' ? 'organizations' : 'contacts'; }

        function loadRecentStore() {
            try { return JSON.parse(localStorage.getItem(SHARED_RECENTS_KEY)) || {}; }
            catch (_) { return {}; }
        }
        function loadRecent() {
            // Most-recent-first list of ids for the active kind (display-capped at 15).
            return (loadRecentStore()[storeKind()] || [])
                .filter(function (r) { return r && (r.name || '').trim(); })
                .slice(0, RECENT_DISPLAY)
                .map(function (r) { return r.id; });
        }
        function pushRecent(id, name, email) {
            if (!id || !(name || '').trim()) return;
            try {
                var all = loadRecentStore();
                var list = (all[storeKind()] || []).filter(function (x) { return x.id !== id; });
                list.unshift({ id: id, name: name || '', primary_email: email || '' });
                all[storeKind()] = list.slice(0, SHARED_CAP);
                localStorage.setItem(SHARED_RECENTS_KEY, JSON.stringify(all));
            } catch (_) {}
        }

        function applicableBoxes() {
            return filterBoxes.filter(function (box) {
                var item = box.closest('.filter-checkbox-item');
                var kinds = (item && item.getAttribute('data-kinds') || '').split(/\s+/);
                return kinds.indexOf(kind) !== -1;
            });
        }
        function activeBoxes() {
            return applicableBoxes().filter(function (b) { return b.checked; });
        }
        function passesFilters(row) {
            return activeBoxes().every(function (box) {
                var attr = box.getAttribute('data-filter-attr');
                var val = row.getAttribute(attr);
                if (box.getAttribute('data-filter-type') === 'count') {
                    return (parseInt(val || '0', 10) || 0) > 0;
                }
                return val === '1';
            });
        }

        function matchesRow(row, needle) {
            if (row.getAttribute('data-kind') !== kind) return false;
            if (needle && (row.getAttribute('data-search') || '').indexOf(needle) === -1) return false;
            return passesFilters(row);
        }

        function comparator(value) {
            var parts = (value || 'name-asc').split('-');
            var field = parts[0];
            var dir = parts[1] === 'desc' ? -1 : 1;
            return function (a, b) {
                var cmp;
                if (field === 'events' || field === 'contacts') {
                    cmp = num(a, 'data-' + field) - num(b, 'data-' + field);
                } else {
                    var av = a.getAttribute('data-' + field) || '';
                    var bv = b.getAttribute('data-' + field) || '';
                    if (!av && bv) return 1;
                    if (av && !bv) return -1;
                    cmp = av.localeCompare(bv);
                }
                if (cmp === 0) return (a.getAttribute('data-name') || '').localeCompare(b.getAttribute('data-name') || '');
                return cmp * dir;
            };
        }

        // ---- master render --------------------------------------------------
        function applyView() {
            var needle = (searchInput && searchInput.value || '').trim().toLowerCase();
            var sortValue = sortSelect ? sortSelect.getAttribute('data-value') : 'recent';
            if (searchClear) searchClear.classList.toggle('visible', !!needle);

            var matches = rows.filter(function (r) { return matchesRow(r, needle); });

            var recentMode = sortValue === 'recent' && !needle;
            var ordered;
            var showHeader = false;

            if (recentMode) {
                var byId = {};
                matches.forEach(function (r) { byId[r.getAttribute('data-id')] = r; });
                var recents = loadRecent().map(function (id) { return byId[id]; }).filter(Boolean);
                if (recents.length) {
                    ordered = recents;
                    showHeader = true;
                } else {
                    ordered = matches.slice().sort(comparator('name-asc'));
                }
            } else {
                ordered = matches.slice().sort(comparator(sortValue === 'recent' ? 'name-asc' : sortValue));
            }

            rows.forEach(function (r) { r.hidden = true; });
            ordered.forEach(function (r) { r.hidden = false; list.appendChild(r); });

            recentHeader.remove();
            if (showHeader) list.insertBefore(recentHeader, list.firstChild);

            if (emptyState) {
                emptyState.hidden = ordered.length !== 0;
                if (!ordered.length) {
                    emptyState.textContent = (needle || activeBoxes().length)
                        ? 'No ' + kindNoun() + ' match your search.'
                        : 'No ' + kindNoun() + ' yet.';
                }
            }
        }

        // ---- selection / detail fetch --------------------------------------
        function emptyPanelHtml() {
            var noun = kind === 'organizations' ? 'organization' : 'contact';
            return '<div class="detail-panel-empty">'
                + '<svg class="detail-panel-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">'
                + '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle>'
                + '<path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'
                + '<p class="detail-panel-empty-title">No ' + noun + ' selected</p>'
                + '<p class="detail-panel-empty-subtitle">Select a ' + noun + ' from the list to see its details.</p></div>';
        }

        function deselect() {
            selectedId = null;
            selectedRow = null;
            rows.forEach(function (r) { r.classList.remove('detail-active'); });
            if (detailPanel) detailPanel.classList.remove('has-event');
            panelContent.innerHTML = emptyPanelHtml();
        }

        function selectRow(row, focusEdit) {
            if (!row) return;
            selectedId = row.getAttribute('data-id');
            selectedRow = row;
            var rk = row.getAttribute('data-kind');
            if (lastSelectedByTab.hasOwnProperty(rk)) lastSelectedByTab[rk] = row;
            rows.forEach(function (r) { r.classList.remove('detail-active'); });
            row.classList.add('detail-active');
            if (detailPanel) detailPanel.classList.add('has-event');
            if (wrapper) wrapper.classList.remove('detail-panel-collapsed');
            var verb = row.querySelector('.inbox-row-verb');
            pushRecent(selectedId, verb ? verb.textContent : '', row.getAttribute('data-email') || '');

            var url = row.getAttribute('data-url');
            if (!url) return;
            var token = ++loadToken;
            panelContent.innerHTML = panelSkeletonHtml();

            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
                .then(function (html) {
                    if (token !== loadToken) return;
                    panelContent.innerHTML = html;
                    panelContent.scrollTop = 0;
                    // Keyboard navigation primes the Edit button (focus + ring)
                    // so Enter activates it. The .focus-ring class is the app's
                    // deterministic ring (works even though this focus is async,
                    // where :focus-visible can't be relied on). Mouse selection
                    // passes no flag, so nothing is ringed until Tab is pressed.
                    if (focusEdit) {
                        var editBtn = panelContent.querySelector('[data-action="edit-record"]');
                        if (editBtn) {
                            editBtn.classList.add('focus-ring');
                            editBtn.addEventListener('blur', function () {
                                editBtn.classList.remove('focus-ring');
                            }, { once: true });
                            editBtn.focus();
                        }
                    }
                })
                .catch(function () {
                    if (token !== loadToken) return;
                    panelContent.innerHTML = '<div class="detail-panel-empty">'
                        + '<p class="detail-panel-empty-title">Could not load details</p>'
                        + '<p class="detail-panel-empty-subtitle">Please try again.</p></div>';
                });
        }

        // ---- tab switching --------------------------------------------------
        function setTab(next) {
            if (next === kind) return;
            kind = next;
            tabs.forEach(function (t) {
                var on = t.getAttribute('data-tab') === kind;
                t.classList.toggle('active', on);
                t.setAttribute('aria-selected', on ? 'true' : 'false');
            });

            if (searchInput) {
                searchInput.placeholder = kind === 'organizations'
                    ? 'Search name, location…' : 'Search name, email, organization…';
            }

            // Hide sort options / filter rows that don't apply to this kind.
            if (sortSelect) {
                var options = sortSelect.querySelectorAll('.schedule-header-select-option');
                var selected = sortSelect.getAttribute('data-value');
                var selectedOk = true;
                options.forEach(function (opt) {
                    var kinds = opt.getAttribute('data-kinds');
                    var ok = !kinds || kinds.split(/\s+/).indexOf(kind) !== -1;
                    opt.hidden = !ok;
                    if (!ok && opt.getAttribute('data-value') === selected) selectedOk = false;
                });
                if (!selectedOk) setSort('recent');
            }
            filterBoxes.forEach(function (box) {
                var item = box.closest('.filter-checkbox-item');
                var kinds = (item && item.getAttribute('data-kinds') || '').split(/\s+/);
                if (item) item.hidden = kinds.indexOf(kind) === -1;
            });

            updateFilterButton();
            deselect();
            applyView();
        }

        tabs.forEach(function (t) {
            t.addEventListener('click', function () { setTab(t.getAttribute('data-tab')); });
        });

        // ---- sort dropdown --------------------------------------------------
        function setSort(value) {
            if (!sortSelect) return;
            var options = sortSelect.querySelectorAll('.schedule-header-select-option');
            var label = sortSelect.querySelector('.schedule-header-select-value');
            sortSelect.setAttribute('data-value', value);
            options.forEach(function (o) {
                var on = o.getAttribute('data-value') === value;
                o.classList.toggle('selected', on);
                if (on && label) label.textContent = o.textContent;
            });
        }

        if (sortSelect) {
            var trigger = sortSelect.querySelector('.schedule-header-select-trigger');
            var options = sortSelect.querySelectorAll('.schedule-header-select-option');
            if (trigger) {
                trigger.addEventListener('click', function (e) {
                    e.stopPropagation();
                    sortSelect.classList.toggle('open');
                });
            }
            options.forEach(function (opt) {
                opt.addEventListener('click', function () {
                    setSort(opt.getAttribute('data-value'));
                    sortSelect.classList.remove('open');
                    applyView();
                });
            });
            document.addEventListener('click', function (e) {
                if (!sortSelect.contains(e.target)) sortSelect.classList.remove('open');
            });
        }

        // ---- search ---------------------------------------------------------
        if (searchInput) searchInput.addEventListener('input', applyView);
        // Enter while typing in search opens the currently selected record (so
        // arrow-to-select then Enter works without leaving the search box).
        if (searchInput) {
            searchInput.addEventListener('keydown', function (e) {
                if (e.key !== 'Enter') return;
                if (anyModalOpen()) return;
                if (!selectedRow || selectedRow.hidden) return;
                e.preventDefault();
                openEditorForRow(selectedRow);
            });
        }
        if (searchClear) {
            searchClear.addEventListener('click', function () {
                if (!searchInput) return;
                searchInput.value = '';
                searchInput.focus();
                applyView();
            });
        }

        // First Tab on a fresh page (nothing focused yet) drops the cursor into
        // the search box. Runs once, then bows out to normal tab order.
        var firstTabHandler = function (e) {
            if (e.key === 'Tab' && !e.shiftKey && searchInput
                && (document.activeElement === document.body || !document.activeElement)) {
                e.preventDefault();
                searchInput.focus();
            }
            document.removeEventListener('keydown', firstTabHandler, true);
        };
        document.addEventListener('keydown', firstTabHandler, true);

        // ---- filter sidebar -------------------------------------------------
        function updateFilterButton() {
            if (filtersToggleBtn) filtersToggleBtn.classList.toggle('has-filters', activeBoxes().length > 0);
        }
        if (filtersToggleBtn && filterSidebar) {
            filtersToggleBtn.addEventListener('click', function () {
                filterSidebar.classList.toggle('collapsed');
            });
        }
        if (sidebarCloseBtn && filterSidebar) {
            sidebarCloseBtn.addEventListener('click', function () { filterSidebar.classList.add('collapsed'); });
        }
        var filterToggleHeader = document.querySelector('#contacts-filter-sidebar [data-filter-toggle]');
        if (filterToggleHeader) {
            filterToggleHeader.addEventListener('click', function () {
                filterToggleHeader.closest('.filter-section').classList.toggle('collapsed');
            });
        }
        filterBoxes.forEach(function (box) {
            box.addEventListener('change', function () { updateFilterButton(); applyView(); });
        });
        if (clearFiltersBtn) {
            clearFiltersBtn.addEventListener('click', function () {
                filterBoxes.forEach(function (b) { b.checked = false; });
                updateFilterButton();
                applyView();
            });
        }

        // ---- row + panel events --------------------------------------------
        rows.forEach(function (row) {
            row.addEventListener('click', function () { selectRow(row); });
            // Double-click opens the record for editing (same as Enter / the
            // panel's Edit button).
            row.addEventListener('dblclick', function (e) {
                e.preventDefault();
                if (anyModalOpen()) return;
                if (row !== selectedRow) selectRow(row);
                openEditorForRow(row);
            });
            row.addEventListener('keydown', function (e) {
                if (anyModalOpen()) return;
                if (e.key === 'Enter') {
                    // Enter on the selected/focused row opens it for editing.
                    e.preventDefault();
                    if (row !== selectedRow) selectRow(row);
                    openEditorForRow(row);
                } else if (e.key === ' ') {
                    e.preventDefault();
                    selectRow(row);
                }
            });
        });

        function openEvent(item) {
            var id = item.getAttribute('data-event-id');
            if (id && typeof window.openEventEditingModal === 'function') {
                window.openEventEditingModal(id);
            } else {
                var href = item.getAttribute('data-href');
                if (href) window.location.href = href;
            }
        }

        panelContent.addEventListener('click', function (e) {
            if (e.target.closest('[data-action="deselect"]')) { deselect(); return; }
            var editBtn = e.target.closest('[data-action="edit-record"]');
            if (editBtn) { openRecordEditor(editBtn); return; }
            var copyEl = e.target.closest('[data-copy]');
            if (copyEl) { copyToClipboard(copyEl); return; }
            var recordItem = e.target.closest('.cdp-record-item');
            if (recordItem) { openEditorByKindId(recordItem.getAttribute('data-kind'), recordItem.getAttribute('data-id')); return; }
            var overlap = e.target.closest('.overlap-item');
            if (overlap) { openEvent(overlap); return; }
            var emailItem = e.target.closest('.cdp-email-item');
            if (emailItem) openEmail(emailItem);
        });

        // Enter/Space activates the focused panel item (orgs/people, events, emails).
        panelContent.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            var recordItem = e.target.closest('.cdp-record-item');
            var overlap = e.target.closest('.overlap-item');
            var emailItem = e.target.closest('.cdp-email-item');
            if (recordItem) { e.preventDefault(); openEditorByKindId(recordItem.getAttribute('data-kind'), recordItem.getAttribute('data-id')); }
            else if (overlap) { e.preventDefault(); openEvent(overlap); }
            else if (emailItem) { e.preventDefault(); openEmail(emailItem); }
        });

        // Click a name / email / phone to copy it, flashing a "Copied" tooltip.
        function copyText(text) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                return navigator.clipboard.writeText(text);
            }
            return new Promise(function (resolve, reject) {
                try {
                    var ta = document.createElement('textarea');
                    ta.value = text;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.focus();
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                    resolve();
                } catch (err) { reject(err); }
            });
        }
        // Floating "Copied" pill at <body> level — fixed-positioned so it never
        // clips behind the header or inside a scroll container.
        function flashCopied(el) {
            var rect = el.getBoundingClientRect();
            var tip = document.createElement('div');
            tip.className = 'cdp-float-tip';
            tip.textContent = 'Copied';
            document.body.appendChild(tip);
            var tw = tip.getBoundingClientRect();
            var left = rect.left + rect.width / 2 - tw.width / 2;
            var top = rect.top - tw.height - 8;
            if (top < 4) top = rect.bottom + 8;
            left = Math.max(4, Math.min(left, window.innerWidth - tw.width - 4));
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            requestAnimationFrame(function () { tip.classList.add('visible'); });
            setTimeout(function () {
                tip.classList.remove('visible');
                setTimeout(function () { if (tip.parentNode) tip.parentNode.removeChild(tip); }, 200);
            }, 1100);
        }
        function copyToClipboard(el) {
            var val = el.getAttribute('data-copy');
            if (!val) return;
            copyText(val).then(function () { flashCopied(el); }).catch(function () {});
        }

        // Edit → the shared EEM contact/org edit popup. When it closes, re-fetch
        // the panel so any changes show immediately.
        function openEditorByKindId(kindArg, id) {
            if (!id || !window.EventContactsPanel || typeof window.EventContactsPanel.openEditor !== 'function') return;
            window.EventContactsPanel.openEditor(kindArg, id, {
                onClose: function () { if (selectedRow) selectRow(selectedRow); }
            });
        }
        function openRecordEditor(btn) {
            openEditorByKindId(btn.getAttribute('data-kind'), btn.getAttribute('data-id'));
        }
        function openEditorForRow(row) {
            if (!row) return;
            var k = row.getAttribute('data-kind') === 'organizations' ? 'organization' : 'contact';
            openEditorByKindId(k, row.getAttribute('data-id'));
        }

        // True while any overlay/modal is up — keyboard list nav must stay inert
        // so arrows scroll the modal instead of moving the selection underneath.
        function anyModalOpen() {
            if (emailOverlay && !emailOverlay.hidden) return true;
            if (document.querySelector('.event-editing-container.active')) return true;
            if (document.querySelector('.v2-approval-popup-overlay')) return true;
            if (window.EventContactsPanel && typeof window.EventContactsPanel.isPopupOpen === 'function'
                && window.EventContactsPanel.isPopupOpen()) return true;
            return false;
        }
        panelContent.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            var overlap = e.target.closest('.overlap-item');
            if (overlap) { e.preventDefault(); openEvent(overlap); return; }
            var emailItem = e.target.closest('.cdp-email-item');
            if (emailItem) { e.preventDefault(); openEmail(emailItem); }
        });

        // ---- related-email popup -------------------------------------------
        var emailOverlay = document.getElementById('cdp-email-overlay');
        var emailModalBody = document.getElementById('cdp-email-modal-body');
        var emailToken = 0;

        // Portal the overlay to <body> so position:fixed covers the whole viewport
        // rather than being trapped inside the (sidebar-offset) content area.
        if (emailOverlay && emailOverlay.parentNode !== document.body) {
            document.body.appendChild(emailOverlay);
        }

        function openEmail(item) {
            var url = item && item.getAttribute('data-url');
            if (!url || !emailOverlay || !emailModalBody) return;
            var token = ++emailToken;
            emailModalBody.innerHTML = emailSkeletonHtml();
            emailOverlay.hidden = false;

            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
                .then(function (html) {
                    if (token !== emailToken) return;
                    emailModalBody.innerHTML = html;
                    emailModalBody.scrollTop = 0;
                })
                .catch(function () {
                    if (token !== emailToken) return;
                    emailModalBody.innerHTML = '<div class="v2-email-empty">Could not load this email.</div>';
                });
        }

        function closeEmail() {
            if (!emailOverlay) return;
            emailOverlay.hidden = true;
            if (emailModalBody) emailModalBody.innerHTML = '';
        }

        if (emailOverlay) {
            emailOverlay.addEventListener('click', function (e) {
                if (e.target === emailOverlay || e.target.closest('[data-action="close-email"]')) closeEmail();
            });
            document.addEventListener('keydown', function (e) {
                // Don't close the email popup with Escape while the EEM is open
                // over it — let the EEM handle its own Escape first.
                if (e.key === 'Escape' && !emailOverlay.hidden
                    && !document.querySelector('.event-editing-container.active')) {
                    closeEmail();
                }
            });
        }

        // Per-message controls inside the popup: Open in Outlook + Related events.
        // The events menu itself opens on hover (CSS); here we only act on clicks
        // of an Outlook link or a chosen event.
        if (emailModalBody) {
            emailModalBody.addEventListener('click', function (e) {
                var outlook = e.target.closest('[data-action="open-outlook"]');
                if (outlook) {
                    var weblink = outlook.getAttribute('data-weblink');
                    if (weblink) window.open(weblink, '_blank', 'noopener');
                    return;
                }
                var revItem = e.target.closest('.cdp-relevents-item');
                if (revItem) {
                    var id = revItem.getAttribute('data-event-id');
                    // Leave the email popup open underneath; the EEM opens on top.
                    if (id && typeof window.openEventEditingModal === 'function') {
                        window.openEventEditingModal(id);
                    } else {
                        var href = revItem.getAttribute('data-href');
                        if (href) window.location.href = href;
                    }
                    return;
                }
            });
        }

        // ---- up/down keyboard navigation -----------------------------------
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
            var inSearch = e.target === searchInput;
            var tag = (e.target.tagName || '').toLowerCase();
            // Up/Down still drive the list while typing in the search box;
            // otherwise leave keystrokes to other form fields.
            if (!inSearch && (tag === 'input' || tag === 'textarea' || tag === 'select')) return;
            // While a popup/modal is open, let arrows scroll it — don't move the
            // selection in the list underneath.
            if (anyModalOpen()) return;
            // Traverse in visual (DOM) order — the list is reordered on sort.
            var vis = Array.prototype.slice.call(list.querySelectorAll('.contact-card'))
                .filter(function (r) { return !r.hidden; });
            if (!vis.length) return;
            e.preventDefault();
            var current = document.querySelector('.contact-card.detail-active');
            var idx = current ? vis.indexOf(current) : -1;
            if (e.key === 'ArrowDown') idx = idx < vis.length - 1 ? idx + 1 : 0;
            else idx = idx > 0 ? idx - 1 : vis.length - 1;
            var next = vis[idx];
            // Keyboard nav primes the Edit button (ring + focus) rather than
            // focusing the row, so Enter edits the selected contact — but when
            // navigating from the search box, keep focus there so the user can
            // keep typing.
            selectRow(next, !inSearch);
            next.scrollIntoView({ block: 'nearest' });
        });

        // ---- left/right toggles the People / Organizations tabs -------------
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
            var tag = (e.target.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
            if (e.target.isContentEditable) return;
            // Don't steal arrows from an open popup/modal.
            if (anyModalOpen()) return;
            e.preventDefault();
            // Left = People (left tab), Right = Organizations (right tab).
            var target = e.key === 'ArrowLeft' ? 'people' : 'organizations';
            if (target === kind) return;
            setTab(target);
            // Restore the tab's previous selection if it's still visible;
            // otherwise select the first row of the tab we swapped to.
            var prev = lastSelectedByTab[target];
            var pick = (prev && prev.isConnected && !prev.hidden) ? prev
                : Array.prototype.slice.call(list.querySelectorAll('.contact-card'))
                    .filter(function (r) { return !r.hidden; })[0];
            if (pick) {
                selectRow(pick, true);
                pick.scrollIntoView({ block: 'nearest' });
            }
        });

        // ---- Escape closes the open contact/org edit popup ------------------
        // The shared edit popup normally defers Escape to the EEM's central
        // authority, which isn't present on this page — so handle it here.
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            if (window.EventContactsPanel && typeof window.EventContactsPanel.isPopupOpen === 'function'
                && window.EventContactsPanel.isPopupOpen()) {
                e.preventDefault();
                e.stopPropagation();
                window.EventContactsPanel.closePopup();
            }
        }, true);

        // ---- Tab: trap inside the email popup, else cycle the selected panel -
        function focusableIn(root) {
            return Array.prototype.slice.call(root.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )).filter(function (el) { return el.getClientRects().length > 0; });
        }
        function trapTab(root, e) {
            var f = focusableIn(root);
            if (!f.length) return;
            var first = f[0], last = f[f.length - 1], cur = document.activeElement;
            if (e.shiftKey) {
                if (cur === first || !root.contains(cur)) { e.preventDefault(); last.focus(); }
            } else {
                if (cur === last || !root.contains(cur)) { e.preventDefault(); first.focus(); }
            }
        }
        function panelTabOrder() {
            var order = [];
            var editBtn = panelContent.querySelector('[data-action="edit-record"]');
            if (editBtn) order.push(editBtn);
            // DOM order = related orgs/people, then events, then emails.
            Array.prototype.forEach.call(
                panelContent.querySelectorAll('.cdp-list-item, .overlap-item'),
                function (it) { order.push(it); });
            return order;
        }
        function cyclePanelTab(e) {
            var order = panelTabOrder();
            if (!order.length) return;
            e.preventDefault();
            var n = order.length;
            var idx = order.indexOf(document.activeElement);
            var nextIdx = idx === -1 ? (e.shiftKey ? n - 1 : 0)
                                     : (e.shiftKey ? (idx - 1 + n) % n : (idx + 1) % n);
            order[nextIdx].focus();
        }

        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            // The edit popup manages its own trap (shared with the EEM).
            if (document.querySelector('.v2-approval-popup-overlay')) return;
            if (emailOverlay && !emailOverlay.hidden) { trapTab(emailOverlay, e); return; }
            if (detailPanel && detailPanel.classList.contains('has-event')) {
                var ae = document.activeElement;
                var onRow = ae && ae.classList && ae.classList.contains('contact-card');
                if (panelContent.contains(ae) || onRow) cyclePanelTab(e);
            }
        }, true);

        // ---- initial state --------------------------------------------------
        tabs.forEach(function (t) {
            var on = t.getAttribute('data-tab') === kind;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        if (sortSelect) {
            sortSelect.querySelectorAll('.schedule-header-select-option').forEach(function (opt) {
                var kinds = opt.getAttribute('data-kinds');
                opt.hidden = !(!kinds || kinds.split(/\s+/).indexOf(kind) !== -1);
            });
        }
        filterBoxes.forEach(function (box) {
            var item = box.closest('.filter-checkbox-item');
            var kinds = (item && item.getAttribute('data-kinds') || '').split(/\s+/);
            if (item) item.hidden = kinds.indexOf(kind) === -1;
        });
        applyView();

        // Deep-link: /contacts/?open=<id>&kind=people|organizations opens that
        // record's detail panel on load. Used by the global quick-search palette
        // (keyboard-nav.js) so Enter on a contact/org result lands on the record.
        try {
            var qp = new URLSearchParams(window.location.search);
            var openId = qp.get('open');
            if (openId) {
                var wantKind = qp.get('kind') === 'organizations' ? 'organizations' : 'people';
                if (wantKind !== kind) setTab(wantKind);
                var target = rows.filter(function (r) {
                    return r.getAttribute('data-id') === openId;
                })[0];
                if (target) {
                    target.hidden = false;
                    selectRow(target);
                    if (target.scrollIntoView) target.scrollIntoView({ block: 'nearest' });
                }
            }
        } catch (_) {}

        // Real rows are sorted/filtered now — drop the skeleton and reveal them.
        if (viewContainer) viewContainer.classList.remove('is-loading');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
