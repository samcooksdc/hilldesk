/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Keyboard navigation — three keys, three non-overlapping jobs.
 *
 *   Cmd/Ctrl-K  command palette over the FIXED set: the six pages + a few
 *               commands. Does not search objects... except as a fall-through:
 *               when a query matches no command/page, object results are shown
 *               below so the palette is never a silent dead end.
 *   /           quick object search over the UNBOUNDED set: events + contacts +
 *               organizations. Ranked-fuzzy, one merged list (slight event
 *               bias), each row badged with its type icon. The lowest-friction
 *               bare key because it is the highest-frequency retrieval action.
 *   g <key>     jump to a sidebar destination (power-user accelerant).
 *   ?           open the shortcut cheat sheet.
 *
 * The fixed list and the unbounded list are different search problems (short
 * static list vs. ranked fuzzy over thousands of records), so they stay as
 * separate modes of one palette rather than a merged engine.
 */
(function () {
    'use strict';

    // ---- destinations + commands (the fixed Cmd-K set) ---------------------
    // hrefs are resolved from the rendered sidebar so we never hardcode a URL
    // that Django might namespace differently; gKey drives the g-prefix jumps.
    var PAGES = [
        { id: 'dashboard', label: 'Dashboard', match: 'dashboard home', gKey: 'd', sel: 'dashboard' },
        { id: 'inbox',     label: 'Inbox',     match: 'inbox email review', gKey: 'i', sel: 'inbox' },
        { id: 'calendar',  label: 'Calendar',  match: 'calendar schedule', gKey: 'c', sel: 'calendar' },
        { id: 'events',    label: 'Events',    match: 'events schedule list', gKey: 'e', sel: 'events' },
        { id: 'contacts',  label: 'Contacts',  match: 'contacts people organizations directory', gKey: 'p', sel: 'contacts' },
        { id: 'settings',  label: 'Settings',  match: 'settings preferences', gKey: 's', sel: 'settings' }
    ];

    var ICONS = {
        page: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>',
        command: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
        event: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
        contact: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
        // Matches the org avatar glyph on the contacts directory (a group of
        // people), so the palette and the directory read as the same thing.
        org: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>',
        search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>',
        slash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="16" y1="4" x2="8" y2="20"></line></svg>',
        close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
        plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
        // Quick-filter shortcuts that mirror the dashboard stat cards.
        undated: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"></circle><polyline points="12 9 12 13 15 14"></polyline><line x1="9" y1="2" x2="15" y2="2"></line></svg>',
        extraction: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 4.9 4.9 1.8-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8z"></path><path d="M18.5 14l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z"></path></svg>',
        approval: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
    };

    // Icons for the Settings sub-tabs — same glyphs the settings page uses
    // (settings_redesign.html), keyed by tab id, so the palette matches.
    var SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';
    var SETTINGS_ICONS = {
        customization: SVG_OPEN + '<circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>',
        templates: SVG_OPEN + '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>',
        profile: SVG_OPEN + '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
        notifications: SVG_OPEN + '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>',
        security: SVG_OPEN + '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
        'deleted-events': SVG_OPEN + '<polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>'
    };

    // Resolve hrefs AND icons from the live sidebar so the palette's page rows
    // use the exact same icon as the nav (single source of truth).
    function resolvePageHrefs() {
        var items = document.querySelectorAll('.sidebar-nav .nav-item');
        PAGES.forEach(function (p) {
            if (p.href && p.icon) return;
            for (var i = 0; i < items.length; i++) {
                var href = items[i].getAttribute('href') || '';
                var text = (items[i].textContent || '').trim().toLowerCase();
                if (text.indexOf(p.label.toLowerCase()) !== -1 && href && href !== '#') {
                    if (!p.href) p.href = href;
                    var svg = items[i].querySelector('svg');
                    if (svg && !p.icon) {
                        var clone = svg.cloneNode(true);
                        clone.removeAttribute('class');   // size via .kbd-row-icon svg
                        p.icon = clone.outerHTML;
                    }
                    break;
                }
            }
        });
    }

    // Settings sub-tabs the user can reach (perm-gated server-side, no DEMO).
    function settingsTabs() {
        var el = document.getElementById('kbd-settings-tabs');
        if (!el) return [];
        try { return JSON.parse(el.textContent) || []; } catch (_) { return []; }
    }

    // ---- event status badges ----------------------------------------------
    // The office's status palette (value → label / color / bg_color), injected
    // once via json_script. Used to badge event rows on the right.
    var STATUS_MAP = null;
    function statusInfo(value) {
        if (STATUS_MAP === null) {
            STATUS_MAP = {};
            var el = document.getElementById('kbd-status-choices');
            if (el) {
                try {
                    (JSON.parse(el.textContent) || []).forEach(function (s) {
                        if (s && s.value) STATUS_MAP[s.value] = s;
                    });
                } catch (_) {}
            }
        }
        return STATUS_MAP[value] || null;
    }

    function statusBadge(value) {
        if (!value) return '';
        var info = statusInfo(value);
        var label = info ? info.label : value;
        var style = '';
        if (info && info.color) {
            style = ' style="color:' + info.color + ';background:' + (info.bg_color || 'transparent') + '"';
        }
        return '<span class="kbd-row-status"' + style + '>' + escapeHtml(label) + '</span>';
    }

    // ---- fuzzy ranking -----------------------------------------------------
    // Subsequence match with scoring: exact substring and word-boundary /
    // initials hits rank above scattered mid-word matches. Returns -Infinity
    // when the query is not even a subsequence of the text.
    function score(query, text) {
        if (!query) return 0;
        var q = query.toLowerCase();
        var t = (text || '').toLowerCase();
        if (!t) return -Infinity;

        var idx = t.indexOf(q);
        if (idx !== -1) {
            // Contiguous match: strong. Bonus for start-of-string / word start.
            var base = 100 - idx;
            if (idx === 0) base += 40;
            else if (/\s|[-_.,]/.test(t.charAt(idx - 1))) base += 25;
            return base;
        }

        // Initials: "sst" matches "Senior Staff Team".
        var initials = t.split(/[\s\-_.,]+/).map(function (w) { return w.charAt(0); }).join('');
        if (initials.indexOf(q) !== -1) return 70;

        // Subsequence fallback with a small per-gap penalty.
        var ti = 0, qi = 0, hits = 0, lastHit = -1, gaps = 0;
        for (; ti < t.length && qi < q.length; ti++) {
            if (t.charAt(ti) === q.charAt(qi)) {
                if (lastHit !== -1) gaps += (ti - lastHit - 1);
                lastHit = ti;
                qi++;
                hits++;
            }
        }
        if (qi < q.length) return -Infinity;
        return 40 + hits - Math.min(gaps, 30);
    }

    // ---- recently-accessed objects ----------------------------------------
    // Last 15 objects opened through the palette (events, contacts, orgs),
    // surfaced when / is pressed before a query is typed. Persisted locally so
    // it survives reloads.
    var RECENTS_KEY = 'hd_recent_objects_v1';
    var RECENTS_CAP = 15;

    function loadRecents() {
        try {
            var v = JSON.parse(localStorage.getItem(RECENTS_KEY));
            return Array.isArray(v) ? v : [];
        } catch (_) { return []; }
    }

    function pushRecent(rec) {
        if (!rec || !rec.id || !rec.kind) return;
        try {
            var list = loadRecents().filter(function (r) {
                return !(r.kind === rec.kind && r.id === rec.id);
            });
            list.unshift({ kind: rec.kind, id: rec.id, title: rec.title || '', sub: rec.sub || '', status: rec.status || '' });
            localStorage.setItem(RECENTS_KEY, JSON.stringify(list.slice(0, RECENTS_CAP)));
        } catch (_) {}
    }

    // Rebuild a renderable row (icon, type, open action) from a stored recent.
    function recentToItem(r) {
        var meta = {
            event:   { icon: ICONS.event,   typeLabel: 'Event',        iconClass: 'is-event',
                       statusBadge: statusBadge(r.status), status: r.status,
                       run: function () { openEvent(r.id); } },
            contact: { icon: ICONS.contact, typeLabel: 'Contact',      iconClass: 'is-contact',
                       run: function () { openRecord(r.id, 'people', r.title); } },
            org:     { icon: ICONS.org,     typeLabel: 'Organization', iconClass: 'is-org',
                       run: function () { openRecord(r.id, 'organizations', r.title); } }
        }[r.kind];
        if (!meta) return null;
        return {
            kind: r.kind, id: r.id, title: r.title || '(untitled)', sub: r.sub || '',
            icon: meta.icon, typeLabel: meta.typeLabel, iconClass: meta.iconClass,
            statusBadge: meta.statusBadge, status: meta.status, run: meta.run
        };
    }

    // ---- DOM ---------------------------------------------------------------
    var overlay, panel, input, resultsEl;
    var mode = null;          // 'command' | 'object'
    var rows = [];            // [{ item, el }]
    var activeIndex = -1;
    var searchToken = 0;
    var debounceTimer = null;
    var highlightQuery = '';  // query whose matched chars get accent-highlighted

    function buildPalette() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.className = 'kbd-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.hidden = true;
        overlay.innerHTML =
            '<div class="kbd-backdrop" data-kbd-close></div>' +
            '<div class="kbd-panel" role="document">' +
              '<div class="kbd-input-row">' +
                '<span class="kbd-input-icon">' + ICONS.search + '</span>' +
                '<input class="kbd-input" type="text" autocomplete="off" autocorrect="off" ' +
                  'autocapitalize="off" spellcheck="false" aria-label="Search">' +
              '</div>' +
              '<ul class="kbd-results" role="listbox"></ul>' +
              '<div class="kbd-footer">' +
                '<span class="kbd-foot-item"><kbd class="kbd-key">&#8593;</kbd>' +
                  '<kbd class="kbd-key">&#8595;</kbd> Navigate</span>' +
                '<span class="kbd-foot-item"><kbd class="kbd-key">&#8629;</kbd> Open</span>' +
                '<span class="kbd-foot-item"><kbd class="kbd-key">esc</kbd> Close</span>' +
              '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        panel = overlay.querySelector('.kbd-panel');
        input = overlay.querySelector('.kbd-input');
        resultsEl = overlay.querySelector('.kbd-results');

        overlay.addEventListener('mousedown', function (e) {
            if (e.target.hasAttribute('data-kbd-close')) { closePalette(); return; }
            // Clicking anywhere on the panel (rows, padding) must NOT blur the
            // search box — otherwise the blur-to-close below would fire before a
            // row click registers. Keep focus on the input; let the click happen.
            if (e.target !== input) e.preventDefault();
        });
        input.addEventListener('input', onInput);
        input.addEventListener('keydown', onInputKeydown);
        // Losing focus closes the palette (e.g. clicking outside, tabbing away).
        input.addEventListener('blur', function () {
            if (paletteOpen()) closePalette();
        });
    }

    function openPalette(nextMode) {
        buildPalette();
        if (cheatOpen) closeCheatSheet();
        resolvePageHrefs();
        mode = nextMode;
        activeIndex = -1;
        overlay.hidden = false;
        overlay.classList.add('open');     // shown instantly (no transition)
        input.value = '';
        // Both modes use the magnifier — the "/" search reads as a search box.
        var iconEl = overlay.querySelector('.kbd-input-icon');
        if (iconEl) iconEl.innerHTML = ICONS.search;
        input.placeholder = mode === 'command'
            ? 'Jump to a page or run a command…'
            : 'Search events, contacts, organizations…';
        // Focus the search box so the user can type immediately. Focus now, and
        // again on the next frame as a guard against focus being stolen.
        input.focus();
        window.requestAnimationFrame(function () { if (paletteOpen()) input.focus(); });
        render();
    }

    function closePalette() {
        if (!overlay || overlay.hidden) return;
        overlay.classList.remove('open');
        overlay.hidden = true;
        mode = null;
        searchToken++;            // invalidate any in-flight object search
        clearTimeout(debounceTimer);
    }

    function paletteOpen() { return overlay && !overlay.hidden && mode; }

    // ---- rendering ---------------------------------------------------------
    function onInput() {
        if (mode === 'object') {
            scheduleObjectSearch();
        } else {
            render();
        }
    }

    function pageItem(p, q) {
        return {
            kind: 'page', id: p.id, title: p.label, sub: '', icon: p.icon || ICONS.page,
            shortcut: ['g', p.gKey], _s: q ? score(q, p.label + ' ' + p.match) : 0,
            run: function () { if (p.href) window.location.href = p.href; }
        };
    }

    function settingsRoot() {
        return PAGES.filter(function (p) { return p.id === 'settings'; })[0];
    }

    function pageHref(id, fallback) {
        var p = PAGES.filter(function (x) { return x.id === id; })[0];
        return (p && p.href) || fallback;
    }

    // Build the fixed Cmd-K pool in display order:
    //   Dashboard, Inbox, Calendar, Events, Contacts,
    //   Create new event (+),  Undated events / Extractions / Routed to you,
    //   Settings,  <settings sub-tabs…>,  Keyboard shortcuts
    function commandMatches(q) {
        var settings = settingsRoot();
        var settingsHref = (settings && settings.href) || '/settings/';
        var eventsHref = pageHref('events', '/events/');
        var inboxHref = pageHref('inbox', '/inbox/');
        var pool = [];

        PAGES.forEach(function (p) {
            if (p.id !== 'settings') pool.push(pageItem(p, q));
        });

        pool.push({
            kind: 'command', id: 'create-event', title: 'Create new event', icon: ICONS.plus,
            shortcut: ['c'], _s: q ? score(q, 'create new event add') : 0,
            run: function () { if (typeof window.createNewEvent === 'function') window.createNewEvent(); }
        });

        // Quick filters mirroring the dashboard stat cards.
        pool.push({
            kind: 'command', id: 'undated-events', title: 'Undated events', icon: ICONS.undated,
            _s: q ? score(q, 'undated events no date tentative tbd') : 0,
            run: function () { window.location.href = eventsHref + '?filter=undated'; }
        });
        pool.push({
            kind: 'command', id: 'extractions', title: 'Extractions', icon: ICONS.extraction,
            _s: q ? score(q, 'extractions new extracted human review') : 0,
            run: function () { window.location.href = inboxHref + '?filter=needs_review'; }
        });
        pool.push({
            kind: 'command', id: 'routed-to-you', title: 'Routed to you', icon: ICONS.approval,
            _s: q ? score(q, 'routed to you needs approval pending') : 0,
            run: function () { window.location.href = inboxHref + '?filter=pending_approval'; }
        });

        if (settings) pool.push(pageItem(settings, q));

        settingsTabs().forEach(function (t) {
            pool.push({
                kind: 'settings-tab', id: 'settings-' + t.tab, title: t.label,
                titleSuffix: ' · Settings', sub: '', icon: SETTINGS_ICONS[t.tab] || ICONS.command,
                _s: q ? score(q, t.label + ' settings') : 0,
                run: function () { window.location.href = settingsHref + '?tab=' + encodeURIComponent(t.tab); }
            });
        });

        pool.push({
            kind: 'command', id: 'shortcuts', title: 'Keyboard shortcuts', icon: ICONS.command,
            _s: q ? score(q, 'keyboard shortcuts help cheat sheet') : 0,
            run: function () { openCheatSheet(); }
        });

        if (q) pool = pool.filter(function (r) { return r._s > -Infinity; })
                          .sort(function (a, b) { return b._s - a._s; });
        return pool;
    }

    function render() {
        var q = input.value.trim();
        highlightQuery = q;

        if (mode === 'command') {
            var cmds = commandMatches(q);
            if (cmds.length) {
                paint([{ label: 'Pages & commands', items: cmds }]);
                return;
            }
            // Fall through to objects so Cmd-K is never a dead end.
            if (q) {
                resultsEl.innerHTML = '<li class="kbd-loading">Searching events & contacts…</li>';
                rows = [];
                runObjectSearch(q, true);
            } else {
                paint([{ label: 'Pages & commands', items: commandMatches('') }]);
            }
            return;
        }

        // object mode handled by scheduleObjectSearch
        scheduleObjectSearch();
    }

    function scheduleObjectSearch() {
        var q = input.value.trim();
        clearTimeout(debounceTimer);
        if (q.length < 2) {
            // Before a real query, show the recently-opened objects (unhighlighted).
            highlightQuery = '';
            var recents = loadRecents().map(recentToItem).filter(Boolean);
            if (recents.length) {
                paint([{ label: 'Recent', items: recents }]);
            } else {
                rows = [];
                resultsEl.innerHTML = '<li class="kbd-empty">' +
                    '<p class="kbd-empty-hint">Search events, contacts &amp; organizations. ' +
                    'Type at least 2 characters.</p></li>';
            }
            return;
        }
        resultsEl.innerHTML = '<li class="kbd-loading">Searching…</li>';
        debounceTimer = window.setTimeout(function () { runObjectSearch(q, false); }, 180);
    }

    // ---- object search (events + contacts + organizations) -----------------
    function fetchJson(url) {
        return fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .catch(function () { return null; });
    }

    function listOf(payload) {
        if (!payload) return [];
        return Array.isArray(payload) ? payload : (payload.results || []);
    }

    // Today as YYYY-MM-DD so we can compare against event start_date strings
    // lexicographically (the API returns ISO dates, which sort chronologically).
    function todayStr() {
        var d = new Date();
        var m = d.getMonth() + 1, day = d.getDate();
        return d.getFullYear() + '-' + (m < 10 ? '0' + m : m) + '-' + (day < 10 ? '0' + day : day);
    }

    // Ranking bias for an event by its date: a strong nudge for upcoming and
    // undated events (the ones a scheduler is usually reaching for), a much
    // weaker one for past events so they still appear but sink below live work.
    function eventBias(startDate) {
        if (!startDate) return 18;                       // undated → treat as live
        return String(startDate) >= todayStr() ? 18 : 4; // upcoming vs. past
    }

    function fmtDate(dateStr) {
        if (!dateStr) return '';
        var parts = String(dateStr).split('-');
        if (parts.length !== 3) return dateStr;
        var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        var m = months[parseInt(parts[1], 10) - 1] || '';
        return m + ' ' + parseInt(parts[2], 10) + ', ' + parts[0];
    }

    function runObjectSearch(q, fromCommandFallthrough) {
        highlightQuery = q;
        var token = ++searchToken;
        var enc = encodeURIComponent(q);
        Promise.all([
            // Global search shows reviewed records only: no AI drafts still
            // awaiting review, and no contacts/orgs known only from such drafts.
            fetchJson('/api/events/?search=' + enc + '&page_size=8&requires_human_review=false'),
            fetchJson('/api/contacts/?search=' + enc + '&page_size=8&exclude_in_review=true'),
            fetchJson('/api/organizations/?search=' + enc + '&page_size=8&exclude_in_review=true')
        ]).then(function (res) {
            if (token !== searchToken) return;   // a newer query superseded this

            var items = [];

            listOf(res[0]).forEach(function (e) {
                var sub = [fmtDate(e.start_date), e.location || e.group || ''].filter(Boolean).join(' · ');
                items.push({
                    kind: 'event', id: e.id, title: e.title || '(untitled event)', sub: sub,
                    icon: ICONS.event, typeLabel: 'Event', iconClass: 'is-event',
                    status: e.status, statusBadge: statusBadge(e.status),
                    // Bias events over same-strength people/orgs, weighted by date:
                    // upcoming/undated strongly, past events only slightly.
                    _s: score(q, e.title || '') + eventBias(e.start_date),
                    run: function () { openEvent(e.id); }
                });
            });

            listOf(res[1]).forEach(function (c) {
                var sub = c.primary_organization || c.primary_email || '';
                items.push({
                    kind: 'contact', id: c.id, title: c.name || '(unnamed)', sub: sub,
                    icon: ICONS.contact, typeLabel: 'Contact', iconClass: 'is-contact',
                    _s: score(q, c.name || ''),
                    run: function () { openRecord(c.id, 'people', c.name); }
                });
            });

            listOf(res[2]).forEach(function (o) {
                items.push({
                    kind: 'org', id: o.id, title: o.name || '(unnamed)', sub: o.primary_email || '',
                    icon: ICONS.org, typeLabel: 'Organization', iconClass: 'is-org',
                    _s: score(q, o.name || ''),
                    run: function () { openRecord(o.id, 'organizations', o.name); }
                });
            });

            items.sort(function (a, b) { return b._s - a._s; });
            items = items.slice(0, 12);

            if (!items.length) {
                rows = [];
                resultsEl.innerHTML = '<li class="kbd-empty">' +
                    '<p class="kbd-empty-title">No results for "' + escapeHtml(q) + '"</p>' +
                    '<p class="kbd-empty-hint">No events, contacts, or organizations matched.</p></li>';
                return;
            }

            var sections = [];
            if (fromCommandFallthrough) sections.push({ label: 'No pages or commands — showing objects', items: items });
            else sections.push({ items: items });
            paint(sections);
        });
    }

    // ---- paint a flat/sectioned list and wire selection --------------------
    function paint(sections) {
        resultsEl.innerHTML = '';
        rows = [];
        sections.forEach(function (sec) {
            if (sec.label) {
                var lab = document.createElement('li');
                lab.className = 'kbd-section-label';
                lab.textContent = sec.label;
                resultsEl.appendChild(lab);
            }
            sec.items.forEach(function (item) {
                var li = document.createElement('li');
                li.className = 'kbd-row';
                li.setAttribute('role', 'option');

                var iconWrap = '<span class="kbd-row-icon' + (item.iconClass ? ' ' + item.iconClass : '') +
                    '">' + item.icon + '</span>';
                var body = '<span class="kbd-row-body"><span class="kbd-row-title">' +
                    highlight(item.title, highlightQuery) +
                    (item.titleSuffix ? '<span class="kbd-title-suffix">' + escapeHtml(item.titleSuffix) + '</span>' : '') +
                    '</span>' +
                    (item.sub ? '<span class="kbd-row-sub">' + escapeHtml(item.sub) + '</span>' : '') +
                    '</span>';
                var trailing = '';
                if (item.statusBadge) trailing = item.statusBadge;
                else if (item.typeLabel) trailing = '<span class="kbd-row-type">' + item.typeLabel + '</span>';
                else if (item.shortcut) {
                    trailing = '<span class="kbd-row-shortcut">' + item.shortcut.map(function (k) {
                        return '<kbd class="kbd-key">' + k + '</kbd>';
                    }).join('') + '</span>';
                }
                li.innerHTML = iconWrap + body + trailing;

                var rowObj = { item: item, el: li };
                var myIndex = rows.length;
                li.addEventListener('mousemove', function () { setActive(myIndex); });
                li.addEventListener('click', function () { activate(item); });
                resultsEl.appendChild(li);
                rows.push(rowObj);
            });
        });
        activeIndex = rows.length ? 0 : -1;
        paintActive();
    }

    function paintActive() {
        rows.forEach(function (r, i) {
            var on = i === activeIndex;
            r.el.classList.toggle('active', on);
            if (on) r.el.setAttribute('aria-selected', 'true');
            else r.el.removeAttribute('aria-selected');
        });
        if (activeIndex >= 0 && rows[activeIndex]) {
            var el = rows[activeIndex].el;
            if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
        }
    }

    function setActive(i) {
        if (i < 0 || i >= rows.length || i === activeIndex) return;
        activeIndex = i;
        paintActive();
    }

    function activate(item) {
        if (!item) return;
        // Remember opened objects (events/contacts/orgs) for the / recents list.
        if (item.kind === 'event' || item.kind === 'contact' || item.kind === 'org') {
            pushRecent({ kind: item.kind, id: item.id, title: item.title, sub: item.sub, status: item.status });
        }
        closePalette();
        try { item.run(); } catch (err) { /* navigation target may be missing */ }
    }

    // ---- open targets ------------------------------------------------------
    function openEvent(id) {
        if (typeof window.openEventEditingModal === 'function') {
            window.openEventEditingModal(id);
        } else {
            window.location.href = '/events/';
        }
    }

    function openRecord(id, kind, title) {
        // Prefer the in-page read-only details popup so picking a contact/org
        // previews it (read-only, with an Edit toggle) instead of navigating to
        // the directory. The popup component is loaded globally via base.html.
        var panel = window.EventContactsPanel;
        if (panel && typeof panel.openDetails === 'function') {
            panel.openDetails(kind === 'organizations' ? 'organization' : 'contact', id, { name: title });
            return;
        }
        // Fallback: the directory honors ?open=<id>&kind=… on load (contacts-directory.js).
        window.location.href = '/contacts/?open=' + encodeURIComponent(id) +
            '&kind=' + encodeURIComponent(kind);
    }

    // ---- palette keyboard --------------------------------------------------
    function onInputKeydown(e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (rows.length) setActive((activeIndex + 1) % rows.length);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (rows.length) setActive((activeIndex - 1 + rows.length) % rows.length);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeIndex >= 0 && rows[activeIndex]) activate(rows[activeIndex].item);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closePalette();
        } else if (e.key === 'Tab') {
            // Keep focus trapped on the input; arrows are the only navigation.
            e.preventDefault();
        }
    }

    // ---- cheat sheet -------------------------------------------------------
    var cheatOverlay = null, cheatOpen = false;

    var CHEAT_GROUPS = [
        { label: 'Global', rows: [
            { desc: 'Command palette (pages & commands)', keys: ['Ctrl', 'K'] },
            { desc: 'Search events, contacts & orgs', keys: ['/'] },
            { desc: 'Create new event', keys: ['c'] },
            { desc: 'Show this cheat sheet', keys: ['?'] },
            { desc: 'Close / back out', keys: ['Esc'] }
        ] },
        { label: 'Go to (press g, then…)', rows: [
            { desc: 'Dashboard', keys: ['g', 'd'] },
            { desc: 'Inbox', keys: ['g', 'i'] },
            { desc: 'Calendar', keys: ['g', 'c'] },
            { desc: 'Events', keys: ['g', 'e'] },
            { desc: 'Contacts', keys: ['g', 'p'] },
            { desc: 'Settings', keys: ['g', 's'] }
        ] }
    ];

    function buildCheatSheet() {
        if (cheatOverlay) return;
        cheatOverlay = document.createElement('div');
        cheatOverlay.className = 'kbd-overlay';
        cheatOverlay.setAttribute('role', 'dialog');
        cheatOverlay.setAttribute('aria-modal', 'true');
        cheatOverlay.hidden = true;

        var groupsHtml = CHEAT_GROUPS.map(function (g) {
            var rowsHtml = g.rows.map(function (r) {
                var keys = r.keys.map(function (k, i) {
                    var sep = i > 0 ? '<span class="kbd-then">then</span>' : '';
                    // Within a chord like Ctrl+K we want a + ; g-prefix uses "then".
                    if (i > 0 && (r.keys[0] === 'Ctrl' || r.keys[0] === 'Cmd')) sep = '<span class="kbd-then">+</span>';
                    return sep + '<kbd class="kbd-key">' + k + '</kbd>';
                }).join('');
                return '<div class="kbd-cheat-row"><span class="kbd-cheat-desc">' +
                    r.desc + '</span><span class="kbd-cheat-keys">' + keys + '</span></div>';
            }).join('');
            return '<div class="kbd-cheat-group-label">' + g.label + '</div>' + rowsHtml;
        }).join('');

        cheatOverlay.innerHTML =
            '<div class="kbd-backdrop" data-kbd-close></div>' +
            '<div class="kbd-cheatsheet">' +
              '<div class="kbd-cheat-header">' +
                '<h2 class="kbd-cheat-title">Keyboard shortcuts</h2>' +
                '<button type="button" class="kbd-icon-btn" data-kbd-close aria-label="Close">' + ICONS.close + '</button>' +
              '</div>' +
              '<div class="kbd-cheat-body">' + groupsHtml + '</div>' +
            '</div>';
        document.body.appendChild(cheatOverlay);
        cheatOverlay.addEventListener('mousedown', function (e) {
            if (e.target.closest('[data-kbd-close]')) closeCheatSheet();
        });
    }

    function openCheatSheet() {
        buildCheatSheet();
        if (paletteOpen()) closePalette();
        cheatOverlay.hidden = false;
        cheatOverlay.classList.add('open');
        cheatOpen = true;
    }

    function closeCheatSheet() {
        if (!cheatOverlay || !cheatOpen) return;
        cheatOverlay.classList.remove('open');
        cheatOverlay.hidden = true;
        cheatOpen = false;
    }

    // ---- global hotkeys ----------------------------------------------------
    function isEditable(el) {
        if (!el) return false;
        var tag = el.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if (el.isContentEditable) return true;
        return false;
    }

    // A genuinely-blocking modal is open elsewhere (event editor, etc.). We
    // still allow Cmd-K, but suppress the bare-key shortcuts so we don't fight
    // another overlay's own keyboard handling.
    function otherModalOpen() {
        var ev = document.getElementById('event-editing-container');
        if (ev && ev.classList.contains('active')) return true;
        if (document.querySelector('.v2-modal-overlay.active')) return true;
        return false;
    }

    var pendingG = false, gTimer = null;

    function clearPendingG() {
        pendingG = false;
        if (gTimer) { clearTimeout(gTimer); gTimer = null; }
    }

    document.addEventListener('keydown', function (e) {
        // Cmd/Ctrl-K — works everywhere; the modifier disambiguates from typing.
        if ((e.metaKey || e.ctrlKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            if (paletteOpen() && mode === 'command') closePalette();
            else openPalette('command');
            return;
        }

        // Escape closes our surfaces (the palette input handles its own Escape).
        if (e.key === 'Escape') {
            if (cheatOpen) { closeCheatSheet(); return; }
            // Close a standalone contact/org details/edit popup opened via "/".
            // When the event modal is open it runs its own Escape authority, so
            // defer to it. stopImmediatePropagation prevents a page-level handler
            // (e.g. the contacts directory's) from closing a second stacked popup.
            if (!otherModalOpen() && window.EventContactsPanel &&
                typeof window.EventContactsPanel.isPopupOpen === 'function' &&
                window.EventContactsPanel.isPopupOpen()) {
                e.preventDefault();
                e.stopImmediatePropagation();
                window.EventContactsPanel.closePopup();
            }
            return;
        }

        // Everything below is a BARE key — never fire while typing or while the
        // palette/cheat sheet is already capturing input.
        if (e.metaKey || e.ctrlKey || e.altKey) { clearPendingG(); return; }
        if (paletteOpen() || cheatOpen) return;
        if (isEditable(document.activeElement)) { clearPendingG(); return; }

        // g-prefix jumps: g, then a destination mnemonic.
        if (pendingG) {
            var dest = PAGES.filter(function (p) { return p.gKey === e.key.toLowerCase(); })[0];
            clearPendingG();
            if (dest) {
                e.preventDefault();
                resolvePageHrefs();
                if (dest.href) window.location.href = dest.href;
            }
            return;
        }

        if (otherModalOpen()) return;

        if (e.key === '/') {
            e.preventDefault();
            openPalette('object');
        } else if (e.key === '?') {        // shift+/ on most layouts
            e.preventDefault();
            openCheatSheet();
        } else if (e.key === 'c' || e.key === 'C') {
            // Quick-create a new event (g-prefixed 'c' is Calendar; bare 'c' creates).
            e.preventDefault();
            if (typeof window.createNewEvent === 'function') window.createNewEvent();
        } else if (e.key === 'g' || e.key === 'G') {
            pendingG = true;
            gTimer = window.setTimeout(clearPendingG, 1200);
        }
    });

    // ---- util --------------------------------------------------------------
    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Wrap the characters of `text` that match `query` in <mark class="kbd-hl">.
    // Prefers a contiguous substring run ("das" → "[Das]hboard"); otherwise
    // falls back to highlighting the subsequence characters.
    function highlight(text, query) {
        text = String(text == null ? '' : text);
        var q = (query || '').trim().toLowerCase();
        if (!q) return escapeHtml(text);
        var lower = text.toLowerCase();

        var idx = lower.indexOf(q);
        if (idx !== -1) {
            return escapeHtml(text.slice(0, idx)) +
                '<mark class="kbd-hl">' + escapeHtml(text.slice(idx, idx + q.length)) + '</mark>' +
                escapeHtml(text.slice(idx + q.length));
        }

        var out = '', qi = 0;
        for (var i = 0; i < text.length; i++) {
            if (qi < q.length && lower.charAt(i) === q.charAt(qi)) {
                out += '<mark class="kbd-hl">' + escapeHtml(text.charAt(i)) + '</mark>';
                qi++;
            } else {
                out += escapeHtml(text.charAt(i));
            }
        }
        return qi === q.length ? out : escapeHtml(text);  // no full match → plain
    }

    // Expose a tiny API so other code (or the cheat-sheet command) can open it.
    window.HillDeskPalette = {
        openCommand: function () { openPalette('command'); },
        openSearch: function () { openPalette('object'); },
        openShortcuts: openCheatSheet
    };
})();
