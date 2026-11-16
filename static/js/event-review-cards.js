/* SPDX-License-Identifier: Apache-2.0 */
/*
 * event-review-cards.js
 *
 * Extraction-review cards for the Event Editing Modal's "Involved Parties" tab
 * (multi-contact / multi-org overhaul). Distinct from event-contacts-panel.js,
 * which renders the RESOLVED Contact/Organization records linked to the event.
 *
 * Each card represents one extracted party from event.extracted_fields. The
 * resolution action (new / link / link_update) is auto-determined — the reviewer
 * never chooses it. The review is keyboard-driven:
 *
 *   - The card itself is reviewed via Accept / Reject buttons in the header (to
 *     the right of the name). Accept is AI-amber and glows while pending.
 *   - Tab / "Jump to next" lands first on the glowing Accept button.
 *       Enter        -> accept the card, stop the glow, jump to its first field.
 *       Tab          -> move to Reject (does NOT accept).
 *   - On Reject:  Enter -> reject;  Tab -> accept the card + jump to first field
 *     (accept-by-skipping-reject). No fields -> accept and go to the next card.
 *   - Every extracted field (and each addition/replace) is then reviewed
 *     individually: it stays highlighted until visited; Enter/Tab advances to the
 *     next field, then on to the next card.
 *
 * Nothing is written to the contacts tables here — accept only records the
 * decision; the server commits everything once the whole event passes review.
 */
(function () {
    'use strict';

    const state = { eventId: null };

    // Role starts blank (a deliberate "choose one" default).
    const ROLE_OPTIONS = [
        ['', 'Select a role'],
        ['point_of_contact', 'Point of contact'],
        ['attendee', 'Attendee'],
        ['host_speaker', 'Host / speaker'],
    ];
    const CONTACT_FIELDS = ['name', 'email', 'phone', 'position', 'organization'];
    const ORG_FIELDS = ['name', 'location', 'email', 'phone'];
    const FIELD_LABEL = {
        name: 'Name', email: 'Email', phone: 'Phone', position: 'Position',
        organization: 'Organization', location: 'Location',
    };

    // ----- helpers ---------------------------------------------------------

    function csrfToken() {
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input && input.value) return input.value;
        const meta = document.querySelector('meta[name=csrf-token]');
        if (meta && meta.content) return meta.content;
        const m = document.cookie.split(';').map(c => c.trim())
            .find(c => c.startsWith('csrftoken='));
        return m ? m.split('=')[1] : '';
    }

    async function api(method, url, body) {
        const opts = {
            method,
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken() },
            credentials: 'same-origin',
        };
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const res = await fetch(url, opts);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
        return data;
    }

    function el(tag, cls, html) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function cellValue(fields, key) {
        const cell = fields && fields[key];
        return cell && typeof cell === 'object' ? (cell.value || '') : (cell || '');
    }

    function cellSource(fields, key) {
        const cell = fields && fields[key];
        return cell && Array.isArray(cell.source) ? cell.source : null;
    }

    function highlight(source) {
        const modal = window.eventEditingModalV2;
        if (modal && typeof modal.highlightEmailText === 'function' && Array.isArray(source)) {
            modal.highlightEmailText({ start_index: source[0], end_index: source[1] });
        }
    }

    function clearHighlight() {
        const modal = window.eventEditingModalV2;
        if (modal && typeof modal.clearEmailHighlights === 'function') {
            modal.clearEmailHighlights();
        }
    }

    // After a hover ends, fall back to the highlight of whatever field still has
    // focus (so leaving a hovered field doesn't wipe the focused field's source);
    // clear only when no card field is focused. Mirrors the scalar review fields.
    function restoreFocusHighlight() {
        const a = document.activeElement;
        if (a && a.classList && a.classList.contains('rc-input')
                && a.classList.contains('rc-reviewable') && a._rcSource) {
            highlight(a._rcSource);
        } else {
            clearHighlight();
        }
    }

    // ----- navigation primitives ------------------------------------------

    function panelEl() { return document.getElementById('v2-involved-parties-panel'); }

    // Cards live in two per-section hosts (contacts + organizations); navigation
    // spans both, in DOM order (contacts first).
    function allCards() {
        const p = panelEl();
        return p ? Array.from(p.querySelectorAll('.rc-card')) : [];
    }

    function nextCardAfter(node) {
        const cards = allCards();
        const i = cards.indexOf(node);
        for (let j = i + 1; j < cards.length; j++) {
            if (cards[j].dataset.status === 'pending') return cards[j];
        }
        // Otherwise the next card with unreviewed fields, else the very next card.
        for (let j = i + 1; j < cards.length; j++) return cards[j];
        return null;
    }

    function focusCardStart(node) {
        if (!node) return;
        node.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const accept = node.querySelector('.rc-accept');
        if (accept) { accept.focus(); return; }            // link card: confirm button
        const field = firstUnreviewedStop(node) || node.querySelector('.rc-reviewable');
        if (field) { field.focus(); return; }
        const fr = node.querySelector('.rc-reject-final');  // no fields -> the reject stop
        if (fr) fr.focus();
    }

    function stopsOf(node) {
        return Array.from(node.querySelectorAll('.rc-reviewable'));
    }

    function firstUnreviewedStop(node) {
        return stopsOf(node).find(s => s.dataset.reviewed !== '1') || null;
    }

    function advanceFromStop(node, stop) {
        const stops = stopsOf(node);
        const i = stops.indexOf(stop);
        if (i !== -1 && i + 1 < stops.length) { stops[i + 1].focus(); return; }
        // Past the last field -> the card's final reject stop, then the next card.
        const finalReject = node.querySelector('.rc-reject-final');
        if (finalReject && stop !== finalReject) { finalReject.focus(); return; }
        const next = nextCardAfter(node);
        if (next) focusCardStart(next);
        else if (stop.blur) stop.blur();
    }

    function markStopReviewed(stop) {
        stop.dataset.reviewed = '1';
        const wrap = stop.closest('.rc-field, .rc-reviewable-wrap');
        if (wrap) wrap.classList.add('rc-reviewed');
    }

    // ----- server calls ----------------------------------------------------

    // All review writes mutate the same event.extracted_fields JSON, so they must
    // not race (an overlapping accept + field-review can clobber each other's
    // save, leaving the server "not complete" while the client shows 100%). Run
    // them strictly one-at-a-time through this queue.
    let writeChain = Promise.resolve();
    function queued(task) {
        const run = () => task();
        const next = writeChain.then(run, run);
        writeChain = next.catch(() => {});
        return next;
    }

    function postReview(kind, ref, action, payload) {
        const url = kind === 'organizations'
            ? `/api/events/${state.eventId}/review-organization/`
            : `/api/events/${state.eventId}/review-contact/`;
        return queued(() => api('POST', url, payload || { ref, action }));
    }

    function buildAcceptPayload(cardState, isContact) {
        const confirmed = (cardState.updates || []).filter(u => u.state === 'confirmed');
        const payload = {
            ref: cardState.ref,
            action: 'accept',
            field_edits: cardState.edits,
            additions: confirmed.filter(u => u.type === 'addition').map(u => ({ kind: u.kind, value: u.value })),
            replaces: confirmed.filter(u => u.type === 'replace').map(u => ({
                kind: u.kind, old: u.old, new: u.new, confirmed: true,
            })),
        };
        if (isContact) {
            payload.role = cardState.role || '';
            payload.is_primary = cardState.role === 'point_of_contact';
        }
        return payload;
    }

    async function refreshAll() {
        try {
            const data = await api('GET', `/api/events/${state.eventId}/`);
            if (window.EventContactsPanel && window.EventContactsPanel.render) {
                window.EventContactsPanel.render(state.eventId, data);
            } else {
                render(state.eventId, data);
            }
        } catch (e) { /* best-effort */ }
    }

    // Keep the modal's existing review progress bar / completion in sync after a
    // card action. On full completion, let the modal exit review mode + refresh.
    function handleResult(r) {
        const modal = window.eventEditingModalV2;
        if (r && r.review_complete) {
            if (modal && modal.completeReviewMode) { try { modal.completeReviewMode(); } catch (e) {} }
            refreshAll();
        } else if (modal && modal.updateReviewProgress) {
            try { modal.updateReviewProgress(); } catch (e) {}
        }
    }

    // Send the current accept decision without re-rendering (keeps the card's
    // in-progress field-review state and focus intact). Full refresh only when
    // the whole event review just completed.
    async function syncAccept(node, kind, cardState, isContact) {
        try {
            handleResult(await postReview(kind, cardState.ref, 'accept', buildAcceptPayload(cardState, isContact)));
        } catch (e) { /* keep UI; will retry on next change */ }
    }

    const debounce = (fn, ms) => {
        let t;
        return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
    };

    // ----- card building ---------------------------------------------------

    function buildCard(kind, card) {
        const isContact = kind === 'contacts';
        const fields = card.fields || {};
        const res = card.resolution || {};

        const cardState = {
            ref: card.ref,
            kind,
            matchedId: res.matched_id || null,
            matchedBy: res.matched_by || null,
            role: '',                       // blank default — reviewer selects
            edits: {},
            reviewedFields: new Set(card.reviewed_fields || []),
            updates: []
                .concat((res.pending_additions || []).map(a => ({
                    type: 'addition', kind: a.kind, value: a.value, state: 'pending',
                })))
                .concat((res.pending_replaces || []).map(r => ({
                    type: 'replace', kind: r.kind, old: r.old, new: r.new, state: 'pending',
                }))),
        };
        cardState.sources = {};
        (isContact ? CONTACT_FIELDS : ORG_FIELDS).forEach(k => {
            cardState.edits[k] = cellValue(fields, k);
            cardState.sources[k] = cellSource(fields, k);
        });

        const node = el('div', 'rc-card rc-card-' + (card.status || 'pending'));
        node.dataset.ref = card.ref;
        node.dataset.kind = kind;
        node.dataset.status = card.status || 'pending';
        node._rc = cardState;
        renderCard(node, card, cardState);
        return node;
    }

    // 'new'    = no existing match (a new record will be created)
    // 'update' = matched an existing record AND has additions/replaces to confirm
    // 'link'   = matched an existing record with no changes (just confirm)
    function cardMode(cardState) {
        if (!cardState.matchedId) return 'new';
        return (cardState.updates && cardState.updates.length) ? 'update' : 'link';
    }

    function renderCard(node, card, cardState) {
        const isContact = cardState.kind === 'contacts';
        const status = node.dataset.status;
        const mode = cardMode(cardState);
        node.innerHTML = '';
        node.classList.remove('rc-card-pending', 'rc-card-accepted', 'rc-card-rejected');
        node.classList.add('rc-card-' + status);

        // --- header: "New/Update Contact:" prefix (bold) + name, then actions ---
        const head = el('div', 'rc-head');
        const noun = isContact ? 'Contact' : 'Organization';
        const name = cardState.edits.name || `(unnamed ${noun.toLowerCase()})`;
        let prefix = '';
        if (mode === 'new') prefix = `New ${noun}: `;
        else if (mode === 'update') prefix = `Update ${noun}: `;
        head.appendChild(el('div', 'rc-title',
            (prefix ? `<strong>${escapeHtml(prefix)}</strong>` : '') + escapeHtml(name)));

        const actions = el('div', 'rc-head-actions');
        if (status === 'rejected' || (status === 'accepted' && mode === 'link')) {
            // Resolved binary states keep a status badge + Undo in the header.
            actions.appendChild(el('span', 'rc-badge rc-badge-' + status,
                status === 'accepted' ? 'Accepted' : 'Rejected'));
            const undo = el('button', 'rc-hbtn rc-undo', 'Undo');
            undo.type = 'button';
            undo.addEventListener('click', () => undoCard(node, cardState));
            actions.appendChild(undo);
        } else if (status === 'pending' && mode === 'link') {
            // No-change exact match: a pure accept/reject confirm, both in the header.
            const accept = el('button', 'rc-hbtn rc-accept', 'Accept');
            accept.type = 'button';
            const reject = el('button', 'rc-hbtn rc-reject', 'Reject');
            reject.type = 'button';
            wireAccept(accept, node, cardState, isContact);
            wireReject(reject, node, cardState);
            actions.appendChild(accept);    // Accept first (left of Reject)
            actions.appendChild(reject);
        }
        // New / update cards carry NO header buttons. Their only control is the
        // "Reject …" button at the END of the card (after every field), so it
        // falls last in the tab rotation. Acceptance is implicit: a card is
        // accepted automatically once all of its extracted fields are reviewed.
        head.appendChild(actions);
        node.appendChild(head);

        if (status === 'rejected') {
            node.appendChild(el('div', 'rc-sub', 'This party was discarded. Nothing will be saved for it.'));
            return;
        }

        // A no-change exact match is just a confirm: only the accept/reject button.
        if (mode === 'link') {
            return;
        }

        // Gray subtext under the name (no box).
        node.appendChild(matchBanner(cardState, mode, noun));

        // --- reviewable fields (each must be reviewed individually) ---
        const body = el('div', 'rc-body');
        (isContact ? CONTACT_FIELDS : ORG_FIELDS).forEach(k => {
            if (!cardState.edits[k]) return;       // only extracted fields
            body.appendChild(fieldRow(node, cardState, k, cardState.sources[k]));
        });
        if (isContact) body.appendChild(roleRow(node, cardState));
        node.appendChild(body);

        // --- updates (additions / replaces) as reviewable items ---
        (cardState.updates || []).forEach((u, idx) => node.appendChild(updateRow(node, cardState, u, idx)));

        // --- final tab stop: the lone button on a new/update card ---
        node.appendChild(finalRejectRow(node, cardState, mode));
    }

    // The only control on a new/update card: a reject that discards the whole
    // suggestion. Rendered after every field so the tab rotation reaches it last.
    function finalRejectRow(node, cardState, mode) {
        const wrap = el('div', 'rc-final');
        const btn = el('button', 'rc-hbtn rc-reject rc-reject-final',
            mode === 'update' ? 'Reject all updates' : 'Reject suggestion');
        btn.type = 'button';
        btn.addEventListener('click', () => rejectCard(node, cardState));
        wrap.appendChild(btn);
        return wrap;
    }

    // Extracted-field keys that count toward this card's review (mirrors the
    // server's _card_field_keys: every non-empty field except role).
    function fieldKeysOf(cardState) {
        return Object.keys(cardState.edits).filter(k => cardState.edits[k]);
    }

    // New/update cards have no Accept button — they accept themselves once every
    // extracted field has been reviewed. Drops the amber glow and commits the
    // decision without re-rendering (so the in-progress focus/scroll is kept).
    function maybeAutoAccept(node, cardState) {
        if (node.dataset.status !== 'pending') return;
        if (cardMode(cardState) === 'link') return;     // link still needs a click
        if (!fieldKeysOf(cardState).every(k => cardState.reviewedFields.has(k))) return;
        node.dataset.status = 'accepted';
        node.classList.remove('rc-card-pending');
        node.classList.add('rc-card-accepted');
        syncAccept(node, cardState.kind, cardState, cardState.kind === 'contacts');
    }

    function matchBanner(cardState, mode, noun) {
        const lower = noun.toLowerCase();
        if (mode === 'new') {
            return el('div', 'rc-sub', `No existing ${lower} matched this record, so a new ${lower} will be created.`);
        }
        const by = ({ email: 'email', name_phone: 'name and phone number',
                     name_org: 'name and organization' })[cardState.matchedBy] || 'a match';
        return el('div', 'rc-sub', `This matches an existing ${lower} by ${escapeHtml(by)}. Confirm the updates below.`);
    }

    function fieldRow(node, cardState, key, source) {
        const reviewed = cardState.reviewedFields.has(key);
        const wrap = el('div', 'rc-field' + (reviewed ? ' rc-reviewed' : ''));
        wrap.appendChild(el('label', 'rc-field-label', FIELD_LABEL[key] || key));
        const inp = el('input', 'rc-input rc-reviewable');
        inp.type = 'text';
        inp.value = cardState.edits[key] || '';
        inp.dataset.reviewed = reviewed ? '1' : '0';
        inp._rcSource = source || null;
        inp.addEventListener('input', () => {
            cardState.edits[key] = inp.value;
            scheduleSync(node, cardState);
        });
        inp.addEventListener('focus', () => {
            if (inp.dataset.reviewed !== '1') {
                markStopReviewed(inp);
                cardState.reviewedFields.add(key);
                sendFieldReviewed(cardState, key);
                maybeAutoAccept(node, cardState);   // last field reviewed -> accept
            }
            if (source) highlight(source);
        });
        inp.addEventListener('blur', clearHighlight);
        // Hover highlights the source span too (same as the scalar review fields).
        inp.addEventListener('mouseenter', () => { if (source) highlight(source); });
        inp.addEventListener('mouseleave', restoreFocusHighlight);
        wrap.appendChild(inp);
        return wrap;
    }

    // Role is staff-assigned, not AI-extracted — it is NOT a glowing review unit
    // and does not count toward completion. Plain editable select.
    function roleRow(node, cardState) {
        const wrap = el('div', 'rc-field');
        wrap.appendChild(el('label', 'rc-field-label', 'Role (optional)'));
        const sel = el('select', 'rc-input rc-select');
        ROLE_OPTIONS.forEach(([val, label]) => {
            const o = el('option', null, label);
            o.value = val;
            if (val === cardState.role) o.selected = true;
            sel.appendChild(o);
        });
        sel.addEventListener('change', () => {
            cardState.role = sel.value;
            scheduleSync(node, cardState);
        });
        wrap.appendChild(sel);
        return wrap;
    }

    async function sendFieldReviewed(cardState, field) {
        try {
            handleResult(await postReview(cardState.kind, cardState.ref, 'review_field',
                { ref: cardState.ref, action: 'review_field', field }));
        } catch (e) { /* best-effort */ }
    }

    function updateRow(node, cardState, u, idx) {
        const wrap = el('div', 'rc-reviewable-wrap rc-update rc-update-' + u.state);
        const text = u.type === 'addition'
            ? `Add ${escapeHtml(u.kind)}: <span class="rc-new">${escapeHtml(u.value)}</span>`
            : `Replace ${escapeHtml(u.kind)}: <span class="rc-old">${escapeHtml(u.old || 'none')}</span>` +
              ` <span class="rc-arrow">→</span> <span class="rc-new">${escapeHtml(u.new)}</span>`;
        const row = el('div', 'rc-update-line');
        row.appendChild(el('span', 'rc-update-text', text));

        const btn = el('button', 'rc-mini-btn rc-mini-accent rc-reviewable',
            u.type === 'addition' ? 'Add' : 'Replace');
        btn.type = 'button';
        btn.dataset.reviewed = u.state === 'pending' ? '0' : '1';
        const skip = el('button', 'rc-mini-btn', 'Skip');
        skip.type = 'button';

        const apply = () => { u.state = 'confirmed'; markStopReviewed(btn); scheduleSync(node, cardState); refreshUpdateRow(wrap, u); };
        const doSkip = () => { u.state = 'skipped'; markStopReviewed(btn); scheduleSync(node, cardState); refreshUpdateRow(wrap, u); };
        btn.addEventListener('click', apply);
        skip.addEventListener('click', doSkip);
        const btns = el('div', 'rc-update-btns');
        btns.appendChild(skip);
        btns.appendChild(btn);
        row.appendChild(btns);
        wrap.appendChild(row);
        return wrap;
    }

    function refreshUpdateRow(wrap, u) {
        wrap.classList.remove('rc-update-pending', 'rc-update-confirmed', 'rc-update-skipped');
        wrap.classList.add('rc-update-' + u.state);
    }

    // ----- keyboard wiring -------------------------------------------------
    //
    // A single CAPTURE-phase keydown authority on the host owns Tab/Enter while
    // focus is inside a review card. Capture runs BEFORE the focused control's
    // own listeners and before the modal's / global nav's document-level (bubble)
    // handlers, so the in-card flow can never be hijacked or get stuck:
    //   Accept:  Enter accepts (then walks the fields); Tab moves to Reject.
    //   Reject:  Enter rejects; Tab accepts the card (then walks the fields).
    //   Field:   Enter / Tab advance to the next field, then on to the next card.

    function isFieldStop(elm) {
        return elm.classList.contains('rc-input') && elm.classList.contains('rc-reviewable');
    }
    function isUpdateStop(elm) {
        return elm.classList.contains('rc-mini-btn') && elm.classList.contains('rc-reviewable');
    }

    function hostKeyHandler(e) {
        if (e.key !== 'Tab' && e.key !== 'Enter') return;
        const active = document.activeElement;
        const p = panelEl();
        if (!active || !p || !p.contains(active)) return;
        const node = active.closest('.rc-card');
        if (!node) return;
        const cs = node._rc;
        const isContact = node.dataset.kind === 'contacts';
        const halt = () => { e.preventDefault(); e.stopPropagation(); };

        if (e.key === 'Enter') {
            if (active.classList.contains('rc-accept')) { halt(); acceptThenWalk(node, cs, isContact); }
            else if (active.classList.contains('rc-reject')) { halt(); rejectCard(node, cs); }
            else if (isUpdateStop(active)) { halt(); active.click(); advanceFromStop(node, active); }
            else if (isFieldStop(active)) { halt(); advanceFromStop(node, active); }
            return;
        }

        // Tab
        if (e.shiftKey) {
            if (active.classList.contains('rc-reject-final')) {
                halt();
                const stops = stopsOf(node);
                if (stops.length) stops[stops.length - 1].focus();
                return;
            }
            if (active.classList.contains('rc-reject')) {
                halt();
                const a = node.querySelector('.rc-accept');
                if (a) a.focus();
            }
            return;   // other shift+Tab cases fall back to default
        }
        if (active.classList.contains('rc-reject-final')) {
            halt();
            const next = nextCardAfter(node);   // the lone end button -> next card
            if (next) focusCardStart(next);
        } else if (active.classList.contains('rc-accept')) {
            halt();
            const r = node.querySelector('.rc-reject');
            if (r) r.focus();
        } else if (active.classList.contains('rc-reject')) {
            halt();
            acceptThenWalk(node, cs, isContact);   // accept-by-skipping-reject (link card)
        } else if (isUpdateStop(active) || isFieldStop(active)) {
            halt();
            advanceFromStop(node, active);
        }
    }

    function wireAccept(btn, node, cardState, isContact) {
        btn.addEventListener('click', () => acceptThenWalk(node, cardState, isContact));
    }

    function wireReject(btn, node, cardState) {
        btn.addEventListener('click', () => rejectCard(node, cardState));
    }

    // ----- card actions ----------------------------------------------------

    const scheduleSync = debounce((node, cardState) => {
        if (node.dataset.status === 'accepted') {
            syncAccept(node, cardState.kind, cardState, cardState.kind === 'contacts');
        }
    }, 400);

    function acceptThenWalk(node, cardState, isContact) {
        node.dataset.status = 'accepted';
        const card = { fields: fieldsFromState(cardState, isContact), status: 'accepted', resolution: { matched_id: cardState.matchedId, matched_by: cardState.matchedBy, pending_additions: [], pending_replaces: [] } };
        // Re-render the card in place (header now shows Accepted + Undo; body stays
        // for field review). Then jump to the first field — or the next card.
        renderCard(node, card, cardState);
        syncAccept(node, cardState.kind, cardState, isContact);
        const first = node.querySelector('.rc-reviewable');
        if (first) first.focus();
        else { const n = nextCardAfter(node); if (n) focusCardStart(n); }
    }

    function fieldsFromState(cardState, isContact) {
        // Reconstruct a minimal fields map so renderCard shows the edited values.
        const keys = isContact ? CONTACT_FIELDS : ORG_FIELDS;
        const out = {};
        keys.forEach(k => { if (cardState.edits[k]) out[k] = { value: cardState.edits[k], source: null }; });
        return out;
    }

    async function rejectCard(node, cardState) {
        node.dataset.status = 'rejected';
        renderCard(node, { fields: {}, status: 'rejected', resolution: {} }, cardState);
        let complete = false;
        try {
            const r = await postReview(cardState.kind, cardState.ref, 'reject');
            complete = !!(r && r.review_complete);
            handleResult(r);
        } catch (e) { /* keep UI */ }
        if (complete) return;
        const n = nextCardAfter(node);
        if (n) focusCardStart(n);
    }

    async function undoCard(node, cardState) {
        node.dataset.status = 'pending';
        cardState.updates.forEach(u => { u.state = 'pending'; });
        cardState.reviewedFields.clear();   // server 'undo' re-opens every field too
        const card = { fields: fieldsFromState(cardState, cardState.kind === 'contacts'),
                       status: 'pending',
                       resolution: { matched_id: cardState.matchedId, matched_by: cardState.matchedBy,
                                     pending_additions: cardState.updates.filter(u => u.type === 'addition').map(u => ({ kind: u.kind, value: u.value })),
                                     pending_replaces: cardState.updates.filter(u => u.type === 'replace').map(u => ({ kind: u.kind, old: u.old, new: u.new })) } };
        renderCard(node, card, cardState);
        try { handleResult(await postReview(cardState.kind, cardState.ref, 'undo')); } catch (e) { /* keep UI */ }
        focusCardStart(node);   // link -> Accept; new/update -> first field again
    }

    // ----- integration with the modal's existing Jump-to-Next / progress -----

    function scrollFocus(elm) {
        if (!elm) return;
        const card = elm.closest('.rc-card');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        try { elm.focus({ preventScroll: true }); } catch (_) { elm.focus(); }
    }

    // Advance the in-card flow from whatever control currently has focus, so the
    // modal's Jump-to-Next / Tab moves FORWARD (Accept -> Reject -> accept the
    // card + first field -> field -> field -> next card) instead of sticking on
    // the Accept button.
    function advanceWithinCard(active) {
        const node = active.closest('.rc-card');
        if (!node || !panelEl() || !panelEl().contains(node)) return false;
        if (active.classList.contains('rc-reject-final')) {
            const next = nextCardAfter(node);
            if (next) focusCardStart(next);
            return true;
        }
        if (active.classList.contains('rc-accept')) {
            const reject = node.querySelector('.rc-reject');
            if (reject) { reject.focus(); return true; }
        }
        if (active.classList.contains('rc-reject')) {
            acceptThenWalk(node, node._rc, node.dataset.kind === 'contacts');
            return true;
        }
        if (active.classList.contains('rc-reviewable')) {
            advanceFromStop(node, active);
            return true;
        }
        focusCardStart(node);
        return true;
    }

    // Focus the next card stop that blocks completion: a pending card's Accept
    // button, or an accepted card's first unreviewed field. Returns true if it
    // moved focus. Called by the modal's jumpToNextUnreviewedField / Tab.
    function focusNext() {
        const active = document.activeElement;
        if (active && active.closest && active.closest('.rc-card')
                && panelEl() && panelEl().contains(active)) {
            return advanceWithinCard(active);
        }
        for (const node of allCards()) {
            if (node.dataset.status === 'rejected') continue;
            const accept = node.querySelector('.rc-accept');   // link card: needs a click
            if (accept) { scrollFocus(accept); return true; }
            const f = node.querySelector('.rc-input.rc-reviewable[data-reviewed="0"]');
            if (f) { scrollFocus(f); return true; }            // next unreviewed field
        }
        return false;
    }

    function hasPending() {
        for (const node of allCards()) {
            if (node.dataset.status === 'pending') return true;
            if (node.dataset.status === 'accepted' &&
                node.querySelector('.rc-input.rc-reviewable[data-reviewed="0"]')) return true;
        }
        return false;
    }

    // (total, reviewed) review units for the modal's progress bar — mirrors the
    // server: each card = 1 unit + 1 per extracted field (role excluded).
    function counts() {
        let total = 0, reviewed = 0;
        for (const node of allCards()) {
            const cs = node._rc;
            if (!cs) continue;
            // A no-change exact match (matched, no updates) has no field units.
            const isLink = cs.matchedId && !(cs.updates && cs.updates.length);
            const fkeys = isLink ? [] : Object.keys(cs.edits).filter(k => cs.edits[k]);
            total += 1 + fkeys.length;
            const status = node.dataset.status;
            if (status === 'rejected') {
                reviewed += 1 + fkeys.length;
            } else {
                reviewed += (status !== 'pending' ? 1 : 0);
                reviewed += fkeys.filter(k => cs.reviewedFields.has(k)).length;
            }
        }
        return { total, reviewed };
    }

    // ----- render ----------------------------------------------------------

    // Ensure a per-section review-cards host exists immediately above the given
    // linked-records list (#v2-contact-list / #v2-org-list), so the cards appear
    // inside the Contacts / Organizations section rather than in a place of their
    // own above everything.
    function ensureHost(hostId, listId) {
        let h = document.getElementById(hostId);
        if (!h) {
            const list = document.getElementById(listId);
            if (!list || !list.parentNode) return null;
            h = el('div', 'rc-host');
            h.id = hostId;
            list.parentNode.insertBefore(h, list);
        }
        return h;
    }

    function render(eventId, data) {
        state.eventId = eventId;
        const panel = panelEl();
        if (!panel) return;

        // One capture-phase Tab/Enter authority for both card hosts (see
        // hostKeyHandler); attached to the shared panel, once.
        if (!panel.dataset.rcKeysWired) {
            panel.dataset.rcKeysWired = '1';
            panel.addEventListener('keydown', hostKeyHandler, true);
        }

        const ef = (data && data.extracted_fields) || {};
        const contacts = Array.isArray(ef.contacts) ? ef.contacts : [];
        const orgs = Array.isArray(ef.organizations) ? ef.organizations : [];

        const inReview = !!(data && data.requires_human_review);
        const cHost = document.getElementById('v2-contact-review-cards');
        const oHost = document.getElementById('v2-org-review-cards');
        if (!inReview || !contacts.length) { if (cHost) cHost.remove(); }
        if (!inReview || !orgs.length) { if (oHost) oHost.remove(); }
        if (!inReview || (!contacts.length && !orgs.length)) return;

        injectStyles();

        if (contacts.length) {
            const h = ensureHost('v2-contact-review-cards', 'v2-contact-list');
            if (h) { h.innerHTML = ''; contacts.forEach(c => h.appendChild(buildCard('contacts', c))); }
        }
        if (orgs.length) {
            const h = ensureHost('v2-org-review-cards', 'v2-org-list');
            if (h) { h.innerHTML = ''; orgs.forEach(o => h.appendChild(buildCard('organizations', o))); }
        }

        // A new/update card with no reviewable fields (nothing to walk) has no
        // focus event to trigger acceptance — settle those immediately so they
        // never silently block review completion.
        allCards().forEach(node => { if (node._rc) maybeAutoAccept(node, node._rc); });
    }

    // ----- styles ----------------------------------------------------------

    function injectStyles() {
        if (document.getElementById('rc-styles')) return;
        const css = `
        .rc-host { margin-bottom: 10px; }
        .rc-card { position:relative; border:1px solid #e2e8f0; border-radius:10px; background:#fff;
            padding:12px 14px; margin-bottom:10px; }
        .rc-card-pending { border-color:#f59e0b; box-shadow:0 0 0 2px rgba(245,158,11,0.12); }
        /* Accepted cards return to the neutral resting style — no green wash, and
           no lingering amber glow (the card is no longer .rc-card-pending). */
        .rc-card-accepted { border-color:#e2e8f0; background:#fff; }
        .rc-card-rejected { border-color:#e5e7eb; background:#f8fafc; opacity:0.8; }
        .rc-head { display:flex; align-items:center; gap:10px; }
        .rc-title { flex:1; min-width:0; font-weight:400; font-size:0.95rem; color:#1a1a1a;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .rc-title strong { font-weight:700; }
        /* Gray subtext under the name (no box). */
        .rc-sub { font-size:0.78rem; color:#94a3b8; margin:4px 0 10px; }
        .rc-head-actions { display:flex; align-items:center; gap:6px; flex:0 0 auto; }
        .rc-hbtn { height:28px; padding:0 13px; border-radius:7px; font-size:0.8rem; font-weight:600;
            cursor:pointer; border:1px solid transparent; }
        /* Accept = the inbox "needs human review" badge color, with a steady glow. */
        .rc-accept { background:rgba(180,83,9,0.12); color:#92400e; border-color:rgba(180,83,9,0.6);
            box-shadow:0 0 8px 1px rgba(234,179,8,0.5); }
        .rc-accept:hover { background:rgba(180,83,9,0.2); }
        .rc-accept:focus { outline:none; box-shadow:0 0 0 3px rgba(234,179,8,0.6); }
        .rc-reject { background:#fff; border-color:#e2e8f0; color:#64748b; }
        .rc-reject:hover { border-color:#ef4444; color:#ef4444; }
        .rc-reject:focus { outline:none; box-shadow:0 0 0 3px rgba(239,68,68,0.35); }
        /* The lone end-of-card reject on new/update cards (last tab stop). */
        .rc-final { display:flex; margin-top:12px; }
        .rc-reject-final { margin-left:auto; }
        .rc-undo { background:#fff; border-color:#e2e8f0; color:#475569; }
        .rc-undo:hover { background:#f1f5f9; }
        .rc-badge { font-size:0.68rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;
            padding:3px 9px; border-radius:9999px; }
        .rc-badge-accepted { background:rgba(34,197,94,0.16); color:#15803d; }
        .rc-badge-rejected { background:#f1f5f9; color:#64748b; }
        .rc-body { display:flex; flex-direction:column; gap:12px; }
        /* Extracted fields are a plain label + input (like the rest of the event
           form): no box around the field, the INPUT itself is highlighted yellow
           until the field has been reviewed. */
        .rc-field { display:flex; flex-direction:column; gap:5px; }
        .rc-field-label { font-size:0.7rem; font-weight:600; text-transform:uppercase;
            letter-spacing:0.04em; color:#64748b; }
        .rc-input { height:34px; border:1px solid #e2e8f0; border-radius:6px; padding:0 10px;
            font-size:0.875rem; width:100%; box-sizing:border-box; background:#fff; }
        .rc-input:focus { outline:none; border-color:#2563eb; box-shadow:0 0 0 2px rgba(37,99,235,0.12); }
        .rc-select { height:34px; }
        .rc-field:not(.rc-reviewed) .rc-input.rc-reviewable {
            border-color:#eab308; box-shadow:0 0 0 3px rgba(234,179,8,0.25);
            background-color:rgba(234,179,8,0.08); font-style:italic; }
        .rc-field:not(.rc-reviewed) .rc-input.rc-reviewable:focus {
            box-shadow:0 0 0 3px rgba(234,179,8,0.4); }
        .rc-field.rc-reviewed .rc-input { font-style:normal; }
        /* Updates (additions / replaces) keep their own boxed rows. */
        .rc-reviewable-wrap { display:flex; flex-direction:column; gap:3px; padding:6px 8px;
            border:1px solid #fcd34d; background:#fffbeb; border-radius:7px;
            box-shadow:0 0 0 2px rgba(245,158,11,0.08); }
        .rc-reviewable-wrap.rc-update-confirmed,
        .rc-reviewable-wrap.rc-update-skipped { border-color:#e2e8f0; background:#fff; box-shadow:none; }
        .rc-update { margin-top:2px; }
        .rc-update-confirmed { border-color:#bbf7d0; background:#f0fdf4; box-shadow:none; }
        .rc-update-skipped { border-color:#e5e7eb; background:#f8fafc; box-shadow:none; opacity:0.75; }
        .rc-update-line { display:flex; align-items:center; gap:8px; }
        .rc-update-text { flex:1; min-width:0; font-size:0.8rem; color:#475569; }
        .rc-update-skipped .rc-update-text { text-decoration:line-through; }
        .rc-old { text-decoration:line-through; color:#b45309; }
        .rc-arrow { color:#94a3b8; }
        .rc-new { font-weight:600; color:#15803d; }
        .rc-update-btns { flex:0 0 auto; display:flex; gap:6px; }
        .rc-mini-btn { height:26px; padding:0 10px; border:1px solid #cbd5e1; border-radius:6px;
            background:#fff; color:#475569; font-size:0.76rem; font-weight:600; cursor:pointer; }
        .rc-mini-accent { border-color:#2563eb; color:#2563eb; }
        .rc-mini-btn:hover { background:#f1f5f9; }
`;
        const style = el('style', null, css);
        style.id = 'rc-styles';
        document.head.appendChild(style);
    }

    window.EventReviewCards = { render, focusNext, hasPending, counts };
})();
