/* SPDX-License-Identifier: Apache-2.0 */
/*
 * event-contacts-panel.js
 *
 * Normalized Contacts / Organizations section of the event editing modal
 * ("Involved Parties" tab).
 *
 * Cards:
 *   - VIEW (default): read-only. Contact cards show name + emails + phones +
 *     organization(s); organization cards show just the name. Each has an
 *     "Edit" button and an × (unlink from this event).
 *   - Clicking "Edit" opens the editable form in a POPUP — UNLESS the event is
 *     in human review with extracted contact fields, in which case the form is
 *     shown INLINE (so the review highlight/accept flow stays in place).
 *
 * An "Add Contact" / "Add Organization" button sits BELOW the cards (dashed,
 * like "Add Staff"); it reveals a search (link existing) + a "New …" button.
 *
 * Records are shared: editing a card edits the underlying Contact/Organization
 * everywhere it is linked. The × only unlinks it from THIS event.
 */
(function () {
    'use strict';

    const state = { eventId: null, reviewInline: false, inReview: false };
    const editing = new Set();   // record ids shown inline-edit (review mode)
    const expanded = new Set();  // contact ids whose card is expanded — persists
                                 // across re-renders (e.g. closing an edit popup)
    const popupStack = [];       // close fns for open popups (top of stack = last)

    function pushPopup(closeFn) { popupStack.push(closeFn); }
    function popPopup(closeFn) {
        const i = popupStack.indexOf(closeFn);
        if (i !== -1) popupStack.splice(i, 1);
    }

    const CONFIGS = {
        contact: {
            api: 'contacts', label: 'contact', hasLocation: false,
            listId: 'v2-contact-list', addBtnId: 'v2-contact-add-btn',
            panelId: 'v2-contact-addpanel', searchId: 'v2-contact-search',
            resultsId: 'v2-contact-results', newBtnId: 'v2-contact-new-btn',
            resultLabel: r => `<strong>${escapeHtml(r.name || '(no name)')}</strong>` +
                (r.primary_organization ? ` <span class="ec-result-meta">${escapeHtml(r.primary_organization)}</span>` : '') +
                (r.primary_email ? ` <span class="ec-result-meta">${escapeHtml(r.primary_email)}</span>` : ''),
            linkExtra: { role: 'point_of_contact' },
        },
        org: {
            api: 'organizations', label: 'organization', hasLocation: true,
            listId: 'v2-org-list', addBtnId: 'v2-org-add-btn',
            panelId: 'v2-org-addpanel', searchId: 'v2-org-search',
            resultsId: 'v2-org-results', newBtnId: 'v2-org-new-btn',
            resultLabel: r => `<strong>${escapeHtml(r.name || '(no name)')}</strong>`,
            linkExtra: {},
        },
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
        if (!res.ok) {
            const err = new Error(data.detail || data.emails || data.name || `HTTP ${res.status}`);
            err.payload = data;
            throw err;
        }
        return data;
    }

    function el(tag, cls, html) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    function focusableEls(root) {
        return Array.from(root.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), ' +
            'select:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(el => el.getClientRects().length > 0);
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function debounce(fn, ms) {
        let t;
        return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
    }

    // ----- recently-accessed store (localStorage) --------------------------
    // Tracks the contacts/orgs you've most recently opened/linked so the link
    // popup can show relevant suggestions before you start typing. Stores a
    // small {id, name, primary_email} snapshot per record, most-recent-first.

    const RECENTS_KEY = 'ec_recents_v1';
    const RECENTS_CAP = 50;

    function loadRecents() {
        try { return JSON.parse(localStorage.getItem(RECENTS_KEY)) || {}; }
        catch (e) { return {}; }
    }

    function bumpRecent(kind, rec) {
        // Skip records with no name — they shouldn't surface in recents.
        if (!rec || !rec.id || !(rec.name || '').trim()) return;
        try {
            const all = loadRecents();
            const list = (all[kind] || []).filter(x => x.id !== rec.id);
            list.unshift({ id: rec.id, name: rec.name || '', primary_email: rec.primary_email || '' });
            all[kind] = list.slice(0, RECENTS_CAP);
            localStorage.setItem(RECENTS_KEY, JSON.stringify(all));
        } catch (e) { /* storage unavailable — recents are best-effort */ }
    }

    function getRecents(kind, limit) {
        return (loadRecents()[kind] || [])
            .filter(r => (r.name || '').trim())
            .slice(0, limit || 15);
    }

    // Newly-opened event's contacts/orgs jump to the top of the recents list.
    function bumpEventRecents(data) {
        if (!data) return;
        [...(data.contacts || [])].reverse().forEach(c =>
            bumpRecent('contacts', { id: c.id, name: c.name, primary_email: c.email }));
        [...(data.organizations || [])].reverse().forEach(o =>
            bumpRecent('organizations', { id: o.id, name: o.name, primary_email: '' }));
    }

    function computeReviewInline(data) {
        if (!data || !data.requires_human_review) return false;
        const ef = data.extracted_fields || {};
        return Object.keys(ef).some(k => k === 'group' || k.indexOf('point_of_contact') === 0);
    }

    // ----- view rows -------------------------------------------------------

    function viewRow(label, text) {
        const row = el('div', 'ec-row');
        row.appendChild(el('div', 'ec-row-label', label));
        row.appendChild(el('div', 'ec-view-val', escapeHtml(text || '—')));
        return row;
    }

    function viewRowMulti(label, values) {
        const row = el('div', 'ec-row');
        row.appendChild(el('div', 'ec-row-label', label + (values.length > 1 ? 's' : '')));
        const box = el('div', 'ec-view-vals');
        values.forEach(v => box.appendChild(el('div', 'ec-view-val', escapeHtml(v))));
        row.appendChild(box);
        return row;
    }

    const PENCIL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M12 20h9"></path>' +
        '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg>';
    const STAR_ICON = '<svg viewBox="0 0 24 24" stroke-width="2">' +
        '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>';
    const CONTACT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>';
    // Org symbol: the exact "users" glyph from the contacts directory.
    const ORG_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>' +
        '<circle cx="9" cy="7" r="4"></circle>' +
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>' +
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>';
    const LINK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>' +
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>';
    const CHEVRON_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<polyline points="6 9 12 15 18 9"></polyline></svg>';
    // Expand/maximize glyph — opens the read-only details popup.
    const EXPAND_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M15 3h6v6"></path><path d="M9 21H3v-6"></path>' +
        '<path d="M21 3l-7 7"></path><path d="M3 21l7-7"></path></svg>';

    function starButton(cfg, rec) {
        const btn = el('button', 'ec-star-btn' + (rec.is_primary ? ' ec-star-on' : ''), STAR_ICON);
        btn.type = 'button';
        const label = rec.is_primary
            ? `Primary ${cfg.label}` : `Set as primary ${cfg.label}`;
        btn.setAttribute('aria-label', label);
        btn.setAttribute('data-tooltip', label);
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            // An event must keep a primary: you can move it, not clear it.
            if (!rec.is_primary) setPrimary(cfg, rec, true);
        });
        return btn;
    }

    function cardHead(cfg, rec, title, primaryBtn, onRemove, leading) {
        const head = el('div', 'ec-card-head');
        if (leading) head.appendChild(leading);
        head.appendChild(el('div', 'ec-card-title', escapeHtml(title)));
        const actions = el('div', 'ec-card-actions');
        if (primaryBtn) actions.appendChild(primaryBtn);
        const x = el('button', 'ec-card-x ec-card-icon-btn', '&times;');
        x.type = 'button';
        x.setAttribute('aria-label', 'Remove from this event');
        x.setAttribute('data-tooltip', 'Remove from event');
        x.addEventListener('click', onRemove);
        actions.appendChild(x);
        head.appendChild(actions);
        return head;
    }

    function renderViewCard(cfg, rec) {
        const card = el('div', 'ec-card ec-card-view');
        card.dataset.id = rec.id;

        const expandBtn = el('button', 'ec-card-icon-btn ec-expand-btn', EXPAND_ICON);
        expandBtn.type = 'button';
        expandBtn.setAttribute('aria-label', 'Expand');
        expandBtn.setAttribute('data-tooltip', 'Expand');
        expandBtn.addEventListener('click', () => openDetailsPopup(cfg, rec));
        card.appendChild(cardHead(cfg, rec, rec.name || '(no name)', expandBtn,
            () => unlink(cfg, rec.id), starButton(cfg, rec)));

        if (cfg.hasLocation) {
            // Organization card: a single compact, truncated subline of
            // location · emails · phones · connected people (people last).
            const parts = [];
            if (rec.location) parts.push(rec.location);
            (rec.emails || []).forEach(e => parts.push(e.email));
            (rec.phones || []).forEach(p => parts.push(p.phone));
            (rec.members || []).forEach(m => parts.push(m.name || m.email || ''));
            const text = parts.filter(Boolean).join('  ·  ');
            if (text) {
                const sub = el('div', 'ec-card-subline');
                sub.textContent = text;
                sub.title = text;
                card.appendChild(sub);
            }
        } else {
            // Contact card: full read-only body, collapsible.
            const body = el('div', 'ec-card-body');
            if (rec.position && String(rec.position).trim()) body.appendChild(viewRow('Position', rec.position));
            if (rec.emails && rec.emails.length) body.appendChild(viewRowMulti('Email', rec.emails.map(e => e.email)));
            if (rec.phones && rec.phones.length) body.appendChild(viewRowMulti('Phone', rec.phones.map(p => p.phone)));
            const orgs = (rec.organizations || []).map(o => o.name);
            body.appendChild(viewRow('Organization' + (orgs.length > 1 ? 's' : ''),
                orgs.length ? orgs.join(', ') : '—'));
            // Scheduling notes — shown in the expanded body only when the
            // contact actually has notes.
            if (rec.notes && String(rec.notes).trim()) {
                const nrow = el('div', 'ec-row');
                nrow.appendChild(el('div', 'ec-row-label', 'Scheduling Notes'));
                nrow.appendChild(el('div', 'ec-view-val ec-view-notes', escapeHtml(rec.notes)));
                body.appendChild(nrow);
            }
            card.appendChild(body);

            // Collapsed by default → shows only the name. The expanded state
            // persists across re-renders (e.g. closing an edit popup) via the
            // `expanded` set, so open cards don't snap shut on refresh.
            card.classList.add('ec-collapsible');
            if (!expanded.has(rec.id)) card.classList.add('ec-card-collapsed');
            const head = card.querySelector('.ec-card-head');
            const chev = el('button', 'ec-card-icon-btn ec-collapse-btn', CHEVRON_ICON);
            chev.type = 'button';
            chev.setAttribute('aria-label', 'Show or hide details');
            chev.setAttribute('data-tooltip', 'Show / hide details');
            const toggle = (e) => {
                if (e) e.stopPropagation();
                const collapsed = card.classList.toggle('ec-card-collapsed');
                if (collapsed) expanded.delete(rec.id); else expanded.add(rec.id);
            };
            chev.addEventListener('click', toggle);
            const actions = head.querySelector('.ec-card-actions');
            actions.insertBefore(chev, actions.firstChild);
            const title = head.querySelector('.ec-card-title');
            title.style.cursor = 'pointer';
            title.addEventListener('click', toggle);
        }
        return card;
    }

    // ----- edit form (used inline AND in popup) ----------------------------

    function textField(cls, label, value) {
        const row = el('div', 'ec-row');
        row.appendChild(el('div', 'ec-row-label', label));
        const inp = el('input', 'ec-val ' + cls);
        inp.type = 'text';
        inp.value = value || '';
        row.appendChild(inp);
        return { row, inp };
    }

    function textareaField(cls, label, value) {
        const row = el('div', 'ec-row');
        row.appendChild(el('div', 'ec-row-label', label));
        const ta = el('textarea', 'ec-val ec-textarea ' + cls);
        ta.value = value || '';
        row.appendChild(ta);
        return { row, ta };
    }

    function multiField(cfg, kind, label, items) {
        const row = el('div', 'ec-row');
        row.appendChild(el('div', 'ec-row-label', label));
        const multi = el('div', 'ec-multi');
        multi.dataset.kind = kind;

        const addBtn = el('button', 'ec-multi-add', '+ add ' + kind);
        addBtn.type = 'button';

        const addValueRow = (item) => {
            item = item || {};
            const r = el('div', 'ec-multi-row');
            // Primary star (exclusive within this kind; none primary by default).
            const star = el('button', 'ec-star-btn ec-star-row' + (item.is_primary ? ' ec-star-on' : ''), STAR_ICON);
            star.type = 'button';
            const setStarTip = (on) => {
                const t = on ? 'Primary ' + kind : 'Set as primary ' + kind;
                star.setAttribute('aria-label', t);
                star.setAttribute('data-tooltip', t);
            };
            setStarTip(item.is_primary);
            star.addEventListener('click', () => {
                const on = star.classList.contains('ec-star-on');
                multi.querySelectorAll('.ec-star-row.ec-star-on').forEach(s => {
                    s.classList.remove('ec-star-on');
                    const k = s.getAttribute('data-tooltip') || '';
                    if (k.startsWith('Primary')) s.setAttribute('data-tooltip', 'Set as primary ' + kind);
                });
                if (!on) { star.classList.add('ec-star-on'); setStarTip(true); }
                else setStarTip(false);
                saveCardOf(cfg, multi);
            });
            const inp = el('input', 'ec-val');
            inp.type = kind === 'email' ? 'email' : 'text';
            inp.value = item.email || item.phone || '';
            inp.placeholder = kind === 'email' ? 'email@example.com' : '(555) 123-4567';
            inp.addEventListener('change', (e) => saveCardOf(cfg, e.target));
            const rm = el('button', 'ec-multi-x', '&times;');
            rm.type = 'button';
            rm.title = 'Remove ' + kind;
            rm.addEventListener('click', () => { r.remove(); saveCardOf(cfg, multi); });
            // Only offer the × while the field is empty, so a populated
            // email/phone can't be deleted by an accidental click — clear it
            // first to reveal the ×.
            const syncRm = () => { rm.style.display = inp.value.trim() ? 'none' : ''; };
            inp.addEventListener('input', syncRm);
            syncRm();
            r.appendChild(star);
            r.appendChild(inp);
            r.appendChild(rm);
            multi.insertBefore(r, addBtn);
            return inp;
        };

        addBtn.addEventListener('click', () => { addValueRow({}).focus(); });
        multi.appendChild(addBtn);
        const list = (items && items.length) ? items : [{}];
        list.forEach(it => addValueRow(it));
        row.appendChild(multi);
        return row;
    }

    // A small related-record card: [star] name [edit] [×].
    function relCard(name, opts) {
        const row = el('div', 'ec-relcard');
        const star = el('button', 'ec-star-btn ec-relcard-star' + (opts.starred ? ' ec-star-on' : ''), STAR_ICON);
        star.type = 'button';
        const relTip = opts.starred ? 'Primary' : 'Set as primary';
        star.setAttribute('aria-label', relTip);
        star.setAttribute('data-tooltip', relTip);
        star.addEventListener('click', () => opts.onStar(!opts.starred));
        row.appendChild(star);
        row.appendChild(el('span', 'ec-relcard-name', escapeHtml(name || '(no name)')));
        const actions = el('div', 'ec-relcard-actions');
        const edit = el('button', 'ec-card-icon-btn', PENCIL_ICON);
        edit.type = 'button';
        edit.title = 'Edit';
        edit.addEventListener('click', opts.onEdit);
        const x = el('button', 'ec-card-icon-btn ec-relcard-x', '&times;');
        x.type = 'button';
        x.title = 'Remove';
        x.addEventListener('click', opts.onRemove);
        actions.appendChild(edit);
        actions.appendChild(x);
        row.appendChild(actions);
        return row;
    }

    function contactOrgEditor(rec, card) {
        const row = el('div', 'ec-row ec-orgeditor');
        row.appendChild(el('div', 'ec-row-label', 'Organization(s)'));
        const currentIds = () => (rec.organizations || []).map(z => z.id);

        const list = el('div', 'ec-relcards');
        (rec.organizations || []).forEach(o => {
            list.appendChild(relCard(o.name, {
                starred: rec.primary_organization_id === o.id,
                onStar: (on) => setPrimaryOrg(rec, card, on ? o.id : null),
                onEdit: () => openOrgFromContact(o.id),
                onRemove: () => setContactOrgs(rec, card, currentIds().filter(id => id !== o.id)),
            }));
        });
        if (!(rec.organizations || []).length) list.appendChild(el('div', 'ec-empty', 'None'));
        row.appendChild(list);

        const linkBtn = el('button', 'ec-add-btn ec-orglink-btn', 'Link organization');
        linkBtn.type = 'button';
        linkBtn.addEventListener('click', () => {
            openSearchPopup({
                title: 'Link an organization',
                api: 'organizations',
                recentKind: 'organizations',
                exclude: new Set(currentIds()),
                resultLabel: (o) => `<strong>${escapeHtml(o.name || '(no name)')}</strong>`,
                onPick: (o) => setContactOrgs(rec, card, [...currentIds(), o.id]),
            });
        });
        row.appendChild(linkBtn);
        return row;
    }

    async function setPrimaryOrg(rec, card, orgId) {
        try {
            await api('POST', `/api/contacts/${rec.id}/set_primary_org/`, { organization_id: orgId });
            rec.primary_organization_id = orgId;
            const old = card.querySelector('.ec-orgeditor');
            if (old) old.replaceWith(contactOrgEditor(rec, card));
        } catch (e) { console.error('EventContactsPanel: set primary org failed', e); }
    }

    async function openOrgFromContact(orgId) {
        try {
            const o = await api('GET', `/api/organizations/${orgId}/`);
            openEditPopup(CONFIGS.org, {
                id: o.id, name: o.name, location: o.location,
                emails: o.emails, phones: o.phones, members: o.members,
                primary_contact_id: o.primary_contact_id, notes: o.notes,
            });
        } catch (e) { console.error('EventContactsPanel: open org failed', e); }
    }

    // Connected-people editor inside the EDIT ORGANIZATION popup: lists the
    // org's contacts, with "Add existing" (link a contact) and "Create contact".
    function orgMembersEditor(rec, card) {
        const row = el('div', 'ec-row ec-membereditor');
        row.appendChild(el('div', 'ec-row-label', 'Connected people'));

        const list = el('div', 'ec-relcards');
        (rec.members || []).forEach(m => {
            list.appendChild(relCard(m.name || m.email, {
                starred: rec.primary_contact_id === m.id,
                onStar: (on) => setPrimaryContact(rec, card, on ? m.id : null),
                onEdit: () => openContactFromOrg(m.id, rec, card),
                onRemove: () => removeOrgMember(rec, card, m.id),
            }));
        });
        if (!(rec.members || []).length) list.appendChild(el('div', 'ec-empty', 'None'));
        row.appendChild(list);

        const btns = el('div', 'ec-addbtns');
        const addExisting = el('button', 'ec-add-btn', 'Add existing');
        addExisting.type = 'button';
        addExisting.addEventListener('click', () => {
            const have = new Set((rec.members || []).map(m => m.id));
            openSearchPopup({
                title: 'Add a contact',
                api: 'contacts',
                recentKind: 'contacts',
                exclude: have,
                resultLabel: CONFIGS.contact.resultLabel,
                onPick: (contact) => addOrgMember(rec, card, contact.id),
            });
        });
        const createNew = el('button', 'ec-add-btn ec-add-btn-primary', 'Create contact');
        createNew.type = 'button';
        createNew.addEventListener('click', () => createOrgMember(rec, card));
        btns.appendChild(addExisting);
        btns.appendChild(createNew);
        row.appendChild(btns);
        return row;
    }

    async function refreshOrgMembers(rec, card) {
        try {
            const fresh = await api('GET', `/api/organizations/${rec.id}/`);
            rec.members = fresh.members || [];
            rec.primary_contact_id = fresh.primary_contact_id || null;
            const old = card.querySelector('.ec-membereditor');
            if (old) old.replaceWith(orgMembersEditor(rec, card));
        } catch (e) { console.error('EventContactsPanel: refresh members failed', e); }
    }

    async function addOrgMember(rec, card, contactId) {
        try {
            await api('POST', `/api/organizations/${rec.id}/add_member/`, { contact_id: contactId });
            await refreshOrgMembers(rec, card);
            await refreshReverseList(CONFIGS.org);
        } catch (e) { alert('Could not add contact: ' + e.message); }
    }

    async function removeOrgMember(rec, card, contactId) {
        try {
            await api('POST', `/api/organizations/${rec.id}/remove_member/`, { contact_id: contactId });
            await refreshOrgMembers(rec, card);
            await refreshReverseList(CONFIGS.org);
        } catch (e) { console.error('EventContactsPanel: remove member failed', e); }
    }

    async function setPrimaryContact(rec, card, contactId) {
        try {
            await api('POST', `/api/organizations/${rec.id}/set_primary_contact/`, { contact_id: contactId });
            rec.primary_contact_id = contactId;
            const old = card.querySelector('.ec-membereditor');
            if (old) old.replaceWith(orgMembersEditor(rec, card));
        } catch (e) { console.error('EventContactsPanel: set primary contact failed', e); }
    }

    async function openContactFromOrg(contactId, orgRec, orgCard) {
        try {
            const ct = await api('GET', `/api/contacts/${contactId}/`);
            openEditPopup(CONFIGS.contact, {
                id: ct.id, name: ct.name, position: ct.position, emails: ct.emails, phones: ct.phones,
                organizations: ct.organizations, primary_organization_id: ct.primary_organization_id,
                notes: ct.notes,
            }, { onClose: () => refreshOrgMembers(orgRec, orgCard) });
        } catch (e) { console.error('EventContactsPanel: open contact failed', e); }
    }

    async function createOrgMember(rec, card) {
        try {
            const contact = await api('POST', '/api/contacts/', { name: '' });
            await api('POST', `/api/organizations/${rec.id}/add_member/`, { contact_id: contact.id });
            await refreshOrgMembers(rec, card);
            await refreshReverseList(CONFIGS.org);
            // Open the new contact so its details can be filled; refresh the
            // org's member list again when that popup closes.
            openEditPopup(CONFIGS.contact,
                { id: contact.id, name: '', emails: [], phones: [], organizations: [{ id: rec.id, name: rec.name }] },
                { deleteIfEmpty: true, onClose: () => refreshOrgMembers(rec, card) });
        } catch (e) { alert('Could not create contact: ' + e.message); }
    }

    function fillEditFields(card, cfg, rec) {
        const name = textField('ec-name', 'Name', rec.name);
        name.inp.placeholder = cfg.hasLocation ? 'Organization name' : 'Full name';
        name.inp.addEventListener('change', (e) => saveCardOf(cfg, e.target));
        card.appendChild(name.row);

        // Position (job title) — contacts only; optional like the others.
        if (!cfg.hasLocation) {
            const pos = textField('ec-position', 'Position', rec.position);
            pos.inp.placeholder = 'Job title / position';
            pos.inp.addEventListener('change', (e) => saveCardOf(cfg, e.target));
            card.appendChild(pos.row);
        }

        if (cfg.hasLocation) {
            const loc = textField('ec-location', 'Location', rec.location);
            loc.inp.placeholder = 'City, address…';
            loc.inp.addEventListener('change', (e) => saveCardOf(cfg, e.target));
            card.appendChild(loc.row);
        }

        card.appendChild(multiField(cfg, 'email', 'Email(s)', rec.emails));
        card.appendChild(multiField(cfg, 'phone', 'Phone(s)', rec.phones));

        if (!cfg.hasLocation) {
            card.appendChild(contactOrgEditor(rec, card));
        } else {
            card.appendChild(orgMembersEditor(rec, card));
        }

        // Freeform scheduling notes — the record's `notes` field, surfaced here
        // under a scheduling-specific label.
        const notes = textareaField('ec-notes', 'Scheduling Notes', rec.notes);
        notes.ta.placeholder = 'Scheduling notes…';
        notes.ta.addEventListener('change', (e) => saveCardOf(cfg, e.target));
        card.appendChild(notes.row);
    }

    // INLINE edit card (used only in human-review mode).
    function buildEditForm(cfg, rec, opts) {
        const card = el('div', 'ec-card ec-card-edit');
        card.dataset.id = rec.id;

        const doneBtn = el('button', 'ec-done-btn', 'Done');
        doneBtn.type = 'button';
        doneBtn.addEventListener('click', async () => {
            try { await saveCardNow(cfg, card); } catch (e) { handleSaveError(e); return; }
            opts.onClose();
        });
        card.appendChild(cardHead(cfg, rec, cfg.hasLocation ? 'Edit organization' : 'Edit contact',
            doneBtn, opts.onRemove));
        fillEditFields(card, cfg, rec);
        return card;
    }

    function renderCard(cfg, rec) {
        if (editing.has(rec.id)) {
            return buildEditForm(cfg, rec, {
                onClose: async () => { editing.delete(rec.id); await refresh(); },
                onRemove: () => unlink(cfg, rec.id),
            });
        }
        return renderViewCard(cfg, rec);
    }

    function rerenderCard(cfg, rec) {
        const list = document.getElementById(cfg.listId);
        const old = list && list.querySelector(`.ec-card[data-id="${rec.id}"]`);
        if (old) old.replaceWith(renderCard(cfg, rec));
    }

    function renderList(cfg, records) {
        const list = document.getElementById(cfg.listId);
        if (!list) return;
        list.innerHTML = '';
        if (!records || !records.length) {
            // During human review the extraction cards stand in for this list (and
            // nothing is committed yet), so the "nothing linked" placeholder would
            // just be noise — suppress it.
            if (!state.inReview) {
                list.appendChild(el('div', 'ec-empty', `No ${cfg.label}s linked yet.`));
            }
            return;
        }
        records.forEach(r => list.appendChild(renderCard(cfg, r)));
    }

    // ----- popup -----------------------------------------------------------

    // Popup edit — reuses the modal's existing .v2-approval-popup shell (same
    // backdrop, surface, close button) so it matches the EEM's other popups.
    // Closing on Escape is handled by the modal's central Escape authority via
    // the exposed isPopupOpen()/closePopup() API (see the modal JS).
    const CLOSE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
        '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

    // Delete a just-created record that the user left completely empty (no name,
    // email, phone — and no location for orgs).
    async function deleteIfEmptyRecord(cfg, id) {
        try {
            const r = await api('GET', `/api/${cfg.api}/${id}/`);
            const empty = !(r.name || '').trim()
                && !(r.emails || []).length && !(r.phones || []).length
                && (!cfg.hasLocation || !(r.location || '').trim());
            if (empty) await api('DELETE', `/api/${cfg.api}/${id}/`);
        } catch (e) { /* best-effort cleanup */ }
    }

    function openEditPopup(cfg, rec, opts) {
        const overlay = el('div', 'v2-approval-popup-overlay ec-edit-popup-overlay visible ' +
            (cfg.hasLocation ? 'ec-edit-popup-org' : 'ec-edit-popup-contact'));
        const popup = el('div', 'v2-approval-popup');

        const closeBtn = el('button', 'v2-approval-popup-close', CLOSE_ICON);
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close');

        // Header is the record's name with a pencil icon to the left; it tracks
        // the Name field live.
        const header = el('div', 'v2-approval-popup-header');
        const titleH3 = el('h3', 'ec-popup-title',
            '<span class="ec-popup-title-icon">' + (cfg.hasLocation ? ORG_ICON : CONTACT_ICON) + '</span>' +
            '<span class="ec-popup-title-name"></span>');
        const titleNameEl = titleH3.querySelector('.ec-popup-title-name');
        const setTitle = (v) => {
            const n = (v || '').trim();
            titleNameEl.textContent = n || (cfg.hasLocation ? 'New organization' : 'New contact');
            titleNameEl.classList.toggle('ec-popup-title-empty', !n);
        };
        setTitle(rec.name);
        header.appendChild(titleH3);

        const card = el('div', 'ec-card');
        card.dataset.id = rec.id;
        fillEditFields(card, cfg, rec);
        card.querySelector('.ec-name')?.addEventListener('input', (e) => setTitle(e.target.value));
        const body = el('div', 'v2-approval-popup-body');
        body.appendChild(card);

        const actions = el('div', 'v2-approval-popup-actions');
        // Standalone (e.g. the contacts directory) has no event to remove from.
        const standalone = !!(opts && opts.standalone);
        const removeBtn = el('button', 'v2-btn-secondary', 'Remove from event');
        removeBtn.type = 'button';
        const right = el('div', 'v2-approval-popup-right-actions');
        right.style.marginLeft = 'auto';   // keep Save on the right even with no remove button
        const doneBtn = el('button', 'v2-btn-accent', 'Save');
        doneBtn.type = 'button';
        right.appendChild(doneBtn);
        if (!standalone) actions.appendChild(removeBtn);
        actions.appendChild(right);

        popup.appendChild(closeBtn);
        popup.appendChild(header);
        popup.appendChild(body);
        popup.appendChild(actions);
        overlay.appendChild(popup);

        const close = async () => {
            if (!overlay.parentNode) return;
            // Save typed input first so an empty-check below doesn't discard a
            // name the user entered without blurring the field.
            if (opts && opts.deleteIfEmpty) {
                try { await saveCardNow(cfg, card); } catch (e) { /* dup email — keep record */ }
            }
            overlay.remove();
            popPopup(close);
            if (opts && opts.deleteIfEmpty) await deleteIfEmptyRecord(cfg, rec.id);
            await refresh();
            if (opts && opts.onClose) await opts.onClose();
        };
        pushPopup(close);

        doneBtn.addEventListener('click', async () => {
            try { await saveCardNow(cfg, card); } catch (e) { handleSaveError(e); return; }
            close();
        });
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

        // Trap Tab/Shift+Tab inside the popup so it cycles the popup's own fields
        // — never the page or the EEM behind it. stopPropagation keeps the EEM's
        // modal-level Tab handler from also acting.
        overlay.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            const f = focusableEls(popup);
            if (!f.length) return;
            e.preventDefault();
            e.stopPropagation();
            const n = f.length;
            const idx = f.indexOf(document.activeElement);
            const nextIdx = idx === -1 ? (e.shiftKey ? n - 1 : 0)
                                       : (e.shiftKey ? (idx - 1 + n) % n : (idx + 1) % n);
            f[nextIdx].focus();
        });

        removeBtn.addEventListener('click', async () => {
            overlay.remove();
            popPopup(close);
            await unlink(cfg, rec.id);
        });

        mountPopup(overlay);
        card.querySelector('.ec-name')?.focus();
    }

    // ----- read-only details popup ----------------------------------------

    function cfgFor(apiName) {
        return apiName === 'organizations' ? CONFIGS.org : CONFIGS.contact;
    }

    // Fetch the full record (the slim search result only carries id/name/email).
    async function fetchFull(cfg, id) {
        const r = await api('GET', `/api/${cfg.api}/${id}/`);
        return cfg.hasLocation
            ? { id: r.id, name: r.name, location: r.location, emails: r.emails,
                phones: r.phones, members: r.members, primary_contact_id: r.primary_contact_id,
                notes: r.notes }
            : { id: r.id, name: r.name, position: r.position, emails: r.emails,
                phones: r.phones, organizations: r.organizations,
                primary_organization_id: r.primary_organization_id, notes: r.notes };
    }

    function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve, reject) => {
            try {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                resolve();
            } catch (e) { reject(e); }
        });
    }

    // Floating "Copied" pill at <body> level — the SAME feedback the contacts
    // directory side panel uses (a fixed-positioned `.cdp-float-tip`).
    function flashCopied(el) {
        const rect = el.getBoundingClientRect();
        const tip = document.createElement('div');
        tip.className = 'cdp-float-tip';
        tip.textContent = 'Copied';
        document.body.appendChild(tip);
        const tw = tip.getBoundingClientRect();
        let left = rect.left + rect.width / 2 - tw.width / 2;
        let top = rect.top - tw.height - 8;
        if (top < 4) top = rect.bottom + 8;
        left = Math.max(4, Math.min(left, window.innerWidth - tw.width - 4));
        tip.style.left = left + 'px';
        tip.style.top = top + 'px';
        window.requestAnimationFrame(() => tip.classList.add('visible'));
        setTimeout(() => {
            tip.classList.remove('visible');
            setTimeout(() => { if (tip.parentNode) tip.parentNode.removeChild(tip); }, 200);
        }, 1100);
    }

    // A read-only value that copies its text to the clipboard on click — mirrors
    // the contacts-directory panel's `.cdp-copy` behavior, including the floating
    // "Copied" tooltip.
    function detailCopyVal(text) {
        const v = el('div', 'ec-detail-value ec-detail-copy', escapeHtml(text));
        v.title = 'Click to copy';
        v.addEventListener('click', () => {
            copyText(text).then(() => flashCopied(v)).catch(() => {});
        });
        return v;
    }

    function detailSection(label, count) {
        const s = el('div', 'ec-detail-section');
        const lab = el('div', 'ec-detail-label', escapeHtml(label));
        if (count != null) lab.appendChild(el('span', 'ec-detail-count', String(count)));
        s.appendChild(lab);
        return s;
    }

    // A clickable related-record row (a contact's organizations, an org's
    // people). Opens that record's OWN read-only details popup — the "links".
    function detailRecordItem(otherCfg, relRec, isPrimary, meta) {
        const item = el('div', 'ec-detail-item');
        item.setAttribute('role', 'button');
        item.tabIndex = 0;
        item.appendChild(el('span', 'ec-detail-item-icon',
            otherCfg.hasLocation ? ORG_ICON : CONTACT_ICON));
        item.appendChild(el('span',
            'ec-detail-item-title' + (isPrimary ? ' ec-detail-item-primary' : ''),
            escapeHtml(relRec.name || relRec.email || '(no name)')));
        if (meta) item.appendChild(el('span', 'ec-detail-item-meta', escapeHtml(meta)));
        const open = () => openDetailsPopup(otherCfg, { id: relRec.id, name: relRec.name || relRec.email }, {});
        item.addEventListener('click', open);
        item.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        });
        return item;
    }

    function buildDetailsBody(cfg, rec) {
        const wrap = el('div', 'ec-detail-wrap');

        // Subtitle: position (contact) or location (org), as in the directory panel.
        const sub = cfg.hasLocation ? rec.location : rec.position;
        if (sub && String(sub).trim()) {
            wrap.appendChild(el('div', 'ec-detail-subtitle', escapeHtml(sub)));
        }

        // Email(s) / phone(s) — two columns, click-to-copy.
        const hasEmails = rec.emails && rec.emails.length;
        const hasPhones = rec.phones && rec.phones.length;
        if (hasEmails || hasPhones) {
            const grid = el('div', 'ec-detail-grid');
            if (hasEmails) {
                const s = detailSection('Email' + (rec.emails.length > 1 ? 's' : ''));
                rec.emails.forEach(e => s.appendChild(detailCopyVal(e.email)));
                grid.appendChild(s);
            }
            if (hasPhones) {
                const s = detailSection('Phone' + (rec.phones.length > 1 ? 's' : ''));
                rec.phones.forEach(p => s.appendChild(detailCopyVal(p.phone)));
                grid.appendChild(s);
            }
            wrap.appendChild(grid);
        }

        if (rec.notes && String(rec.notes).trim()) {
            const s = detailSection('Notes');
            s.appendChild(el('div', 'ec-detail-notes', escapeHtml(rec.notes)));
            wrap.appendChild(s);
        }

        // Related records as clickable links.
        if (cfg.hasLocation) {
            const members = rec.members || [];
            const s = detailSection('People', members.length);
            if (members.length) {
                const list = el('div', 'ec-detail-list');
                members.forEach(m => list.appendChild(
                    detailRecordItem(CONFIGS.contact, m, rec.primary_contact_id === m.id, m.primary_email || m.email)));
                s.appendChild(list);
            } else {
                s.appendChild(el('div', 'ec-detail-empty', 'No people linked.'));
            }
            wrap.appendChild(s);
        } else {
            const orgs = rec.organizations || [];
            const s = detailSection('Organization' + (orgs.length === 1 ? '' : 's'), orgs.length);
            if (orgs.length) {
                const list = el('div', 'ec-detail-list');
                orgs.forEach(o => list.appendChild(
                    detailRecordItem(CONFIGS.org, o, rec.primary_organization_id === o.id, o.location)));
                s.appendChild(list);
            } else {
                s.appendChild(el('div', 'ec-detail-empty', 'No organizations linked.'));
            }
            wrap.appendChild(s);
        }

        return wrap;
    }

    // ----- linked events + related emails (same data as the directory) ------
    // These two sections aren't in the slim API; they're rendered server-side in
    // the directory panel fragment. We fetch that fragment and transplant just
    // the "Linked events" and "Related emails" sections so the popup shows the
    // exact same content (and markup) as the nav page.

    function navPanelUrl(cfg, id) {
        return cfg.hasLocation
            ? `/contacts/organizations/${id}/panel/`
            : `/contacts/${id}/panel/`;
    }

    function openEvent(id, href) {
        if (typeof window.openEventEditingModal === 'function') window.openEventEditingModal(id);
        else if (href) window.location.href = href;
    }

    // A related email's full thread — same fragment the directory popup loads,
    // shown in its own overlay (layered below the EEM so opening an event from a
    // thread stacks the EEM on top).
    function openEmailThread(url) {
        const overlay = el('div', 'cdp-email-overlay ec-email-overlay');
        const modal = el('div', 'cdp-email-modal');
        const closeBtn = el('button', 'cdp-email-close', CLOSE_ICON);
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close');
        const bodyEl = el('div', 'cdp-email-modal-body', '<div class="ec-detail-empty">Loading…</div>');
        modal.appendChild(closeBtn);
        modal.appendChild(bodyEl);
        overlay.appendChild(modal);

        const close = () => { if (!overlay.parentNode) return; overlay.remove(); popPopup(close); };
        pushPopup(close);
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

        mountPopup(overlay);
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(r => r.text())
            .then(html => {
                bodyEl.innerHTML = html;
                bodyEl.querySelectorAll('[data-action="open-outlook"]').forEach(b => {
                    b.addEventListener('click', () => {
                        const link = b.getAttribute('data-weblink');
                        if (link) window.open(link, '_blank', 'noopener');
                    });
                });
                bodyEl.querySelectorAll('.cdp-relevents-item[data-event-id]').forEach(it => {
                    it.addEventListener('click', () => {
                        close();
                        openEvent(it.getAttribute('data-event-id'), it.getAttribute('data-href'));
                    });
                });
            })
            .catch(() => { bodyEl.innerHTML = '<div class="ec-detail-empty">Could not load email.</div>'; });
    }

    function wireNavSections(container) {
        container.querySelectorAll('.overlap-item[data-event-id]').forEach(row => {
            const go = () => openEvent(row.getAttribute('data-event-id'), row.getAttribute('data-href'));
            row.addEventListener('click', go);
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
            });
        });
        container.querySelectorAll('.cdp-email-item[data-url]').forEach(row => {
            const go = () => openEmailThread(row.getAttribute('data-url'));
            row.addEventListener('click', go);
            row.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
            });
        });
    }

    async function appendNavSections(cfg, id, container) {
        try {
            const res = await fetch(navPanelUrl(cfg, id),
                { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
            if (!res.ok) return;
            const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
            doc.querySelectorAll('.cdp-section').forEach(sec => {
                const label = (sec.querySelector('.cdp-label') &&
                    sec.querySelector('.cdp-label').textContent || '').toLowerCase();
                if (label.indexOf('linked events') !== -1 || label.indexOf('related emails') !== -1) {
                    container.appendChild(document.importNode(sec, true));
                }
            });
            wireNavSections(container);
        } catch (e) { /* best-effort — the sections just don't appear */ }
    }

    // Read-only details popup modeled on the contacts directory right panel.
    // Shown after a search result is picked (and when drilling into a linked
    // record). Reuses the .v2-approval-popup shell. The Edit button toggles THIS
    // popup into the shared edit form (fillEditFields); Done saves and returns to
    // the read-only view. The confirm action (e.g. "Link") runs opts.onConfirm —
    // omit it for pure view/edit (drilling into a related record).
    function openDetailsPopup(cfg, slimRec, opts) {
        opts = opts || {};
        const overlay = el('div', 'v2-approval-popup-overlay ec-edit-popup-overlay ' +
            'ec-details-popup-overlay visible ' +
            (cfg.hasLocation ? 'ec-edit-popup-org' : 'ec-edit-popup-contact'));
        const popup = el('div', 'v2-approval-popup');

        const closeBtn = el('button', 'v2-approval-popup-close', CLOSE_ICON);
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close');

        const header = el('div', 'v2-approval-popup-header');
        const titleH3 = el('h3', 'ec-popup-title',
            '<span class="ec-popup-title-icon">' + (cfg.hasLocation ? ORG_ICON : CONTACT_ICON) + '</span>' +
            '<span class="ec-popup-title-name"></span>');
        const titleNameEl = titleH3.querySelector('.ec-popup-title-name');
        const setTitle = (v) => {
            const n = (v || '').trim();
            titleNameEl.textContent = n || '(no name)';
            titleNameEl.classList.toggle('ec-popup-title-empty', !n);
        };
        header.appendChild(titleH3);

        const body = el('div', 'v2-approval-popup-body ec-details-body');

        // Actions are right-aligned; Edit/Done is accent-colored (and the confirm
        // action, when present, sits to its right).
        const actions = el('div', 'v2-approval-popup-actions');
        const right = el('div', 'v2-approval-popup-right-actions');
        right.style.marginLeft = 'auto';
        const editBtn = el('button', 'v2-btn-accent ec-details-edit-btn', 'Edit');
        editBtn.type = 'button';
        right.appendChild(editBtn);
        let confirmBtn = null;
        if (opts.onConfirm) {
            confirmBtn = el('button', 'v2-btn-accent', opts.confirmLabel || 'Link');
            confirmBtn.type = 'button';
            right.appendChild(confirmBtn);
        }
        actions.appendChild(right);

        popup.appendChild(closeBtn);
        popup.appendChild(header);
        popup.appendChild(body);
        popup.appendChild(actions);
        overlay.appendChild(popup);

        let rec = slimRec;
        let mode = 'view';

        const close = async () => {
            if (!overlay.parentNode) return;
            overlay.remove();
            popPopup(close);
            if (opts.onClose) await opts.onClose();
        };
        pushPopup(close);
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

        // Trap Tab inside the popup (same as the edit popup).
        overlay.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            const f = focusableEls(popup);
            if (!f.length) return;
            e.preventDefault();
            e.stopPropagation();
            const n = f.length;
            const idx = f.indexOf(document.activeElement);
            const nextIdx = idx === -1 ? (e.shiftKey ? n - 1 : 0)
                                       : (e.shiftKey ? (idx - 1 + n) % n : (idx + 1) % n);
            f[nextIdx].focus();
        });

        const renderView = () => {
            mode = 'view';
            body.innerHTML = '';
            const wrap = buildDetailsBody(cfg, rec);
            body.appendChild(wrap);
            // Linked events + related emails come from the directory fragment
            // (same content as the nav page); appended async when they arrive.
            appendNavSections(cfg, rec.id, wrap);
            editBtn.textContent = 'Edit';
            if (confirmBtn) confirmBtn.style.display = '';
        };

        const renderEdit = () => {
            mode = 'edit';
            body.innerHTML = '';
            const card = el('div', 'ec-card');
            card.dataset.id = rec.id;
            fillEditFields(card, cfg, rec);
            const nameInp = card.querySelector('.ec-name');
            if (nameInp) nameInp.addEventListener('input', (e) => setTitle(e.target.value));
            body.appendChild(card);
            editBtn.textContent = 'Done';
            if (confirmBtn) confirmBtn.style.display = 'none';
            if (nameInp) nameInp.focus();
        };

        editBtn.addEventListener('click', async () => {
            if (mode === 'view') { renderEdit(); return; }
            // Editing → save, re-fetch, and return to the read-only view.
            const card = body.querySelector('.ec-card');
            try { await saveCardNow(cfg, card); } catch (e) { handleSaveError(e); return; }
            try { rec = await fetchFull(cfg, rec.id); } catch (e) { /* keep current rec */ }
            setTitle(rec.name);
            renderView();
        });

        if (confirmBtn) {
            confirmBtn.addEventListener('click', async () => {
                await close();
                try { await opts.onConfirm(rec); } catch (e) { console.error('EventContactsPanel: confirm failed', e); }
            });
        }

        mountPopup(overlay);

        // Load full details, then render the read-only view.
        setTitle(rec.name);
        body.appendChild(el('div', 'ec-detail-empty ec-detail-loading', 'Loading…'));
        fetchFull(cfg, rec.id).then(full => {
            rec = full;
            setTitle(rec.name);
            renderView();
        }).catch(e => {
            body.innerHTML = '';
            body.appendChild(el('div', 'ec-detail-empty', 'Could not load details.'));
            console.error('EventContactsPanel: load details failed', e);
        });
    }

    // Reusable search/link popup — same .v2-approval-popup shell, fixed height,
    // with a search bar and a SCROLLABLE results area. Used to link an existing
    // contact/org to the event, and to link an organization to a contact.
    function openSearchPopup(opts) {
        const overlay = el('div',
            'v2-approval-popup-overlay ec-edit-popup-overlay ec-search-popup-overlay visible');
        const popup = el('div', 'v2-approval-popup');

        const closeBtn = el('button', 'v2-approval-popup-close', CLOSE_ICON);
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'Close');

        const header = el('div', 'v2-approval-popup-header');
        header.appendChild(el('h3', 'ec-popup-title',
            '<span class="ec-popup-title-icon ec-link-icon">' + LINK_ICON + '</span>' +
            '<span>' + escapeHtml(opts.title) + '</span>'));

        const body = el('div', 'v2-approval-popup-body ec-search-body');
        const input = el('input', 'ec-val ec-search-input');
        input.type = 'text';
        input.placeholder = 'Search…';
        input.autocomplete = 'off';
        const results = el('div', 'ec-search-results');
        body.appendChild(input);
        body.appendChild(results);

        popup.appendChild(closeBtn);
        popup.appendChild(header);
        popup.appendChild(body);
        overlay.appendChild(popup);

        const close = () => {
            if (!overlay.parentNode) return;
            overlay.remove();
            popPopup(close);
        };
        pushPopup(close);
        closeBtn.addEventListener('click', close);
        overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

        const exclude = opts.exclude || new Set();
        const pick = async (rec) => {
            bumpRecent(opts.recentKind, rec);
            close();
            // Picking no longer links straight away: open a read-only details
            // popup (with Edit + a confirm action) so the record can be reviewed
            // — and edited — before it is linked.
            openDetailsPopup(cfgFor(opts.api), rec, {
                confirmLabel: opts.confirmLabel || 'Link',
                onConfirm: (full) => opts.onPick(full || rec),
            });
        };

        const addRow = (rec) => {
            const row = el('div', 'ec-result', opts.resultLabel(rec));
            row.setAttribute('role', 'option');
            row.addEventListener('click', () => pick(rec));
            results.appendChild(row);
        };

        // Before searching: the most recently accessed (relevant) records.
        const showRecents = () => {
            results.innerHTML = '';
            const recents = getRecents(opts.recentKind, 15).filter(r => !exclude.has(r.id));
            if (recents.length) {
                results.appendChild(el('div', 'ec-search-section', 'Recent'));
                recents.forEach(addRow);
            } else {
                results.appendChild(el('div', 'ec-search-hint', 'Type to search.'));
            }
        };

        const run = debounce(async () => {
            const q = input.value.trim();
            if (q.length < 2) { showRecents(); return; }
            try {
                const data = await api('GET', `/api/${opts.api}/?search=${encodeURIComponent(q)}`);
                results.innerHTML = '';
                const matches = (data.results || []).filter(r => !exclude.has(r.id)).slice(0, 40);
                matches.forEach(addRow);
                if (!matches.length) results.appendChild(el('div', 'ec-result ec-result-empty', 'No matches.'));
            } catch (e) { console.error('EventContactsPanel: search failed', e); }
        }, 120);
        input.addEventListener('input', run);

        showRecents();
        mountPopup(overlay);
        input.focus();
    }

    // Mount inside the modal's container (same place the approval/routing popups
    // live) so it shares the modal's stacking context and shows above the modal.
    function mountPopup(overlay) {
        const mount = document.getElementById('v2-modal-overlay')?.parentElement || document.body;
        mount.appendChild(overlay);
        injectStyles();
        attachTooltips(overlay);
    }

    // ----- saving / mutations ---------------------------------------------

    function collectCard(cfg, card) {
        const payload = { name: card.querySelector('.ec-name')?.value.trim() || '' };
        if (cfg.hasLocation) {
            payload.location = card.querySelector('.ec-location')?.value.trim() || '';
        }
        const posEl = card.querySelector('.ec-position');
        if (posEl) payload.position = posEl.value.trim();
        const rows = (kind, key) =>
            [...card.querySelectorAll(`.ec-multi[data-kind=${kind}] .ec-multi-row`)]
                .map(r => ({
                    [key]: (r.querySelector('.ec-val')?.value || '').trim(),
                    is_primary: !!r.querySelector('.ec-star-row.ec-star-on'),
                }))
                .filter(x => x[key]);
        payload.emails = rows('email', 'email');
        payload.phones = rows('phone', 'phone');
        const notesEl = card.querySelector('.ec-notes');
        if (notesEl) payload.notes = notesEl.value;
        return payload;
    }

    async function saveCardNow(cfg, card) {
        await api('PATCH', `/api/${cfg.api}/${card.dataset.id}/`, collectCard(cfg, card));
        card.classList.add('ec-card-saved');
        setTimeout(() => card.classList.remove('ec-card-saved'), 900);
    }

    function handleSaveError(e) {
        const dupe = e.payload && e.payload.existing_contact_id;
        alert('Could not save: ' + e.message +
            (dupe ? '\n\nThat email already belongs to another contact.' : ''));
    }

    const saveCardOf = debounce(async function (cfg, node) {
        const card = node.closest('.ec-card');
        if (!card) return;
        try { await saveCardNow(cfg, card); }
        catch (e) { handleSaveError(e); }
    }, 350);

    async function setContactOrgs(rec, card, ids) {
        try {
            await api('PATCH', `/api/contacts/${rec.id}/`, { organization_ids: ids });
            const fresh = await api('GET', `/api/contacts/${rec.id}/`);
            rec.organizations = fresh.organizations || [];
            rec.primary_organization_id = fresh.primary_organization_id || null;
            // Clear a primary org that is no longer linked.
            if (rec.primary_organization_id &&
                !rec.organizations.some(o => o.id === rec.primary_organization_id)) {
                await api('POST', `/api/contacts/${rec.id}/set_primary_org/`, { organization_id: null });
                rec.primary_organization_id = null;
            }
            const oldRow = card.querySelector('.ec-orgeditor');
            if (oldRow) oldRow.replaceWith(contactOrgEditor(rec, card));
            await refreshReverseList(CONFIGS.contact);
        } catch (e) {
            console.error('EventContactsPanel: set orgs failed', e);
            alert('Could not update organizations: ' + e.message);
        }
    }

    async function setPrimary(cfg, rec, makePrimary) {
        if (!state.eventId) return;
        try {
            await api('POST', `/api/${cfg.api}/${rec.id}/set_primary/`,
                { event_id: state.eventId, is_primary: makePrimary });
            await refresh();
        } catch (e) {
            console.error('EventContactsPanel: set primary failed', e);
        }
    }

    // Keep the modal header's organization subheader in sync with the primary org.
    function updateOrgSubheader(data) {
        const btn = document.getElementById('v2-organization');
        if (!btn) return;
        const orgs = (data && data.organizations) || [];
        const primary = orgs.find(o => o.is_primary) || orgs[0];
        const name = primary ? primary.name : '';
        btn.textContent = name || 'Add organization / group';
        btn.classList.toggle('v2-org-jump-empty', !name);
        // Remember the primary org so the jump button targets it (not just the
        // first card in DOM order).
        btn.dataset.primaryOrgId = primary ? primary.id : '';
    }

    async function refresh() {
        if (!state.eventId) return;
        try {
            const data = await api('GET', `/api/events/${state.eventId}/`);
            state.reviewInline = computeReviewInline(data);
            state.inReview = !!(data && data.requires_human_review);
            bumpEventRecents(data);
            renderList(CONFIGS.contact, data.contacts || []);
            renderList(CONFIGS.org, data.organizations || []);
            updateOrgSubheader(data);
            if (window.EventReviewCards) window.EventReviewCards.render(state.eventId, data);
        } catch (e) {
            console.error('EventContactsPanel: refresh failed', e);
        }
    }

    // Contact↔Organization "related" links are a single bidirectional M2M, so a
    // change made from one side already exists on the other in the DB. After
    // such a change, re-render the OTHER side's list so the reverse link shows
    // immediately (the actively-edited side's card is left untouched).
    async function refreshReverseList(cfg) {
        if (!state.eventId) return;
        const other = cfg === CONFIGS.contact ? CONFIGS.org : CONFIGS.contact;
        try {
            const data = await api('GET', `/api/events/${state.eventId}/`);
            renderList(other, (other === CONFIGS.org ? data.organizations : data.contacts) || []);
        } catch (e) {
            console.error('EventContactsPanel: reverse refresh failed', e);
        }
    }

    async function unlink(cfg, id) {
        if (!state.eventId) return;
        try {
            await api('POST', `/api/${cfg.api}/${id}/unlink_event/`, { event_id: state.eventId });
            editing.delete(id);
            await refresh();
        } catch (e) {
            console.error('EventContactsPanel: unlink failed', e);
        }
    }

    async function linkExisting(cfg, id) {
        await api('POST', `/api/${cfg.api}/${id}/link_event/`,
            Object.assign({ event_id: state.eventId }, cfg.linkExtra));
        await refresh();
    }

    async function createBlank(cfg) {
        try {
            const rec = await api('POST', `/api/${cfg.api}/`, { name: '' });
            await api('POST', `/api/${cfg.api}/${rec.id}/link_event/`,
                Object.assign({ event_id: state.eventId }, cfg.linkExtra));
            await refresh();
            // Open the new blank record straight into the editor.
            const fresh = (cfg.hasLocation
                ? { id: rec.id, name: '', location: '', emails: [], phones: [] }
                : { id: rec.id, name: '', emails: [], phones: [], organizations: [] });
            if (state.reviewInline) { editing.add(rec.id); rerenderCard(cfg, fresh); }
            else openEditPopup(cfg, fresh, { deleteIfEmpty: true });
        } catch (e) {
            console.error('EventContactsPanel: create failed', e);
            alert('Could not create ' + cfg.label + ': ' + e.message);
        }
    }

    // ----- add bar ---------------------------------------------------------

    function openLinkExistingPopup(cfg) {
        // Exclude records already linked to this event.
        const linked = new Set(
            [...document.querySelectorAll(`#${cfg.listId} .ec-card`)].map(c => c.dataset.id));
        openSearchPopup({
            title: cfg.hasLocation ? 'Link an organization' : 'Link a contact',
            api: cfg.api,
            recentKind: cfg.api,
            exclude: linked,
            resultLabel: cfg.resultLabel,
            onPick: (rec) => linkExisting(cfg, rec.id),
        });
    }

    function wireAddBar(cfg) {
        const btn = document.getElementById(cfg.addBtnId);
        if (btn && !btn.dataset.ecWired) {
            btn.dataset.ecWired = '1';
            btn.addEventListener('click', () => openLinkExistingPopup(cfg));
        }
        const newBtn = document.getElementById(cfg.newBtnId);
        if (newBtn && !newBtn.dataset.ecWired) {
            newBtn.dataset.ecWired = '1';
            newBtn.addEventListener('click', () => createBlank(cfg));
        }
    }

    function wireOrgJump() {
        const btn = document.getElementById('v2-organization');
        if (!btn || btn.dataset.ecJumpWired) return;
        btn.dataset.ecJumpWired = '1';
        btn.addEventListener('click', () => {
            document.getElementById('v2-involved-parties-tab')?.click();
            setTimeout(() => {
                const list = document.getElementById('v2-org-list');
                // Target the primary org's card; fall back to the first card.
                const primaryId = btn.dataset.primaryOrgId;
                const target = (primaryId && list?.querySelector(`.ec-card[data-id="${primaryId}"]`))
                    || list?.querySelector('.ec-card');
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    target.classList.add('ec-card-flash');
                    setTimeout(() => target.classList.remove('ec-card-flash'), 1100);
                } else {
                    list?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    document.getElementById('v2-org-add-btn')?.focus();
                }
            }, 80);
        });
    }

    // App-style tooltips: delegate hover on a stable root to the modal's
    // floating-tooltip helper (the same one the routing × button uses). Applied
    // to the panel AND each popup overlay so stars/icons there get tooltips too.
    function attachTooltips(rootEl) {
        if (!rootEl || rootEl.dataset.ecTipWired) return;
        rootEl.dataset.ecTipWired = '1';
        rootEl.addEventListener('mouseover', (e) => {
            const btn = e.target.closest('[data-tooltip]');
            const modal = window.eventEditingModalV2;
            if (btn && modal && modal._showFloatingTooltip && !btn.contains(e.relatedTarget)) {
                modal._showFloatingTooltip(btn, btn.getAttribute('data-tooltip'));
            }
        });
        rootEl.addEventListener('mouseout', (e) => {
            const btn = e.target.closest('[data-tooltip]');
            const modal = window.eventEditingModalV2;
            if (btn && modal && modal._hideFloatingTooltip && !btn.contains(e.relatedTarget)) {
                modal._hideFloatingTooltip();
            }
        });
    }

    function wireTooltips() {
        attachTooltips(document.getElementById('v2-involved-parties-panel'));
    }

    function wireAll() {
        wireAddBar(CONFIGS.contact);
        wireAddBar(CONFIGS.org);
        wireOrgJump();
        wireTooltips();
        injectStyles();
    }

    function injectStyles() {
        if (document.getElementById('ec-panel-styles')) return;
        const css = `
        .ec-addbar { margin-top: 10px; }
        .ec-addbtns { display:flex; gap:8px; }
        /* Both add buttons share the dashed ghost shape; left is dark-gray,
           right (create) is the accent blue. */
        .ec-add-btn { flex:1; display:flex; align-items:center; justify-content:center; gap:6px;
            height:30px; padding:0 12px; border:1px dashed #cbd5e1; border-radius:8px; background:#fff;
            color:#475569; font-size:0.82rem; font-weight:500; cursor:pointer; transition:all .15s ease; }
        /* Both add buttons are gray; either turns accent on hover. */
        .ec-add-btn-primary { color:#475569; border-color:#cbd5e1; background:#fff; }
        .ec-add-btn:hover, .ec-add-btn-primary:hover { color:var(--v2-accent, #2563eb);
            border-color:var(--v2-accent, #2563eb); background:var(--v2-accent-light, #f0f6ff); }
        /* Accent (blue) primary button — used for the popup "Done" action. */
        .v2-btn-accent { display:inline-flex; align-items:center; gap:6px; padding:10px 16px;
            background:var(--v2-accent, #2563eb); color:#fff; border:none;
            border-radius:var(--v2-input-radius, 8px); font-size:var(--v2-small-size, 0.85rem);
            font-weight:600; cursor:pointer; transition:all .15s ease; }
        .v2-btn-accent:hover { background:var(--v2-accent-hover, #1d4ed8); }
        /* Search/link popup: fixed search bar on top, scrollable results below. */
        .ec-search-popup-overlay .v2-approval-popup-body { display:flex; flex-direction:column;
            gap:10px; overflow:hidden; }
        .ec-search-input { height:38px; }
        .ec-search-results { flex:1 1 auto; overflow-y:auto; border:1px solid #eef2f7;
            border-radius:8px; }
        .ec-search-hint { color:#94a3b8; font-size:0.82rem; padding:10px 12px; }
        .ec-search-section { font-size:0.68rem; text-transform:uppercase; letter-spacing:0.05em;
            color:#94a3b8; padding:8px 12px 4px; background:#fafbfc; border-bottom:1px solid #f1f5f9;
            position:sticky; top:0; }
        .ec-orglink-btn { flex:0 0 auto; align-self:flex-start; height:32px; padding:0 14px; }
        .ec-result { padding:9px 12px; cursor:pointer; font-size:0.875rem; border-bottom:1px solid #f1f5f9;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ec-result:last-child { border-bottom:none; }
        .ec-result:hover { background:#f1f5f9; }
        .ec-result-meta { color:#64748b; font-size:0.78rem; }
        .ec-result-empty { color:#94a3b8; cursor:default; }
        .ec-cards { display:flex; flex-direction:column; gap:10px; }
        .ec-empty { color:#94a3b8; font-size:0.85rem; padding:2px 0; }
        .ec-card { position:relative; border:1px solid #d1d5db; border-radius:10px;
            background:#fff; padding:12px 14px; }
        .ec-card-saved { border-color:#22c55e; transition:border-color .2s; }
        .ec-card-head { display:flex; align-items:center; gap:8px; }
        .ec-card-view .ec-card-head + .ec-card-body { margin-top:8px; }
        /* Collapsible contact cards: show only the name when collapsed. */
        .ec-card-collapsed .ec-card-body { display:none; }
        .ec-collapsible .ec-card-title { user-select:none; }
        .ec-collapse-btn svg { transition:transform .15s ease; }
        .ec-card-collapsed .ec-collapse-btn svg { transform:rotate(-90deg); }
        .ec-card-title { flex:1; min-width:0; font-weight:600; font-size:0.95rem; color:#1a1a1a;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .ec-card-edit .ec-card-title { font-size:0.72rem; text-transform:uppercase; letter-spacing:0.04em;
            color:#94a3b8; font-weight:600; }
        .ec-card-actions { display:flex; align-items:center; gap:2px; }
        /* Icon buttons (Edit pencil, remove ×) — same shape as the modal's. */
        .ec-card-icon-btn { display:inline-flex; align-items:center; justify-content:center;
            width:26px; height:26px; padding:0; border:none; background:transparent; border-radius:6px;
            color:#94a3b8; cursor:pointer; line-height:1; transition:background .15s ease, color .15s ease; }
        .ec-card-icon-btn svg { width:15px; height:15px; }
        /* Contacts / Organizations subheader: label left, icon add-buttons right. */
        .ec-subheader-row { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:6px; }
        .ec-subheader-row .v2-field-label { margin:0; }
        .ec-addbtns-inline { display:flex; align-items:center; gap:2px; flex-shrink:0; }
        .ec-add-icon-btn svg { width:17px; height:17px; }
        .ec-add-icon-btn:hover { background:#f1f5f9; color:var(--v2-accent, #2563eb); }
        .ec-card-x { font-size:1.15rem; }
        .ec-card-x:hover { background:#f1f5f9; color:#ef4444; }
        .ec-expand-btn:hover { background:#f1f5f9; color:var(--v2-accent, #2563eb); }
        .ec-done-btn { height:26px; padding:0 12px; border:none; border-radius:6px; font-size:0.78rem;
            cursor:pointer; background:var(--v2-accent, #2563eb); color:#fff; }
        /* Primary star — outline when off, filled accent when on. */
        .ec-star-btn { display:inline-flex; align-items:center; justify-content:center; width:24px;
            height:24px; padding:0; border:none; background:transparent; border-radius:6px;
            cursor:pointer; color:#cbd5e1; transition:color .15s ease; }
        .ec-star-btn svg { width:16px; height:16px; fill:none; stroke:currentColor; }
        .ec-star-btn:hover { color:var(--v2-accent, #2563eb); }
        .ec-star-on { color:var(--v2-accent, #2563eb); }
        .ec-star-on svg { fill:var(--v2-accent, #2563eb); stroke:var(--v2-accent, #2563eb); }
        .ec-row { display:flex; flex-direction:column; gap:4px; margin-bottom:8px; }
        .ec-card-edit .ec-row:last-child { margin-bottom:0; }
        .ec-row-label { font-size:0.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;
            color:#64748b; user-select:none; -webkit-user-select:none; }
        .ec-view-val { font-size:0.875rem; color:#1f2937; }
        .ec-view-notes { white-space:pre-wrap; color:#475569; line-height:1.45; }
        .ec-view-vals { display:flex; flex-direction:column; gap:2px; }
        /* Org card: single compact, truncated detail line under the title. */
        .ec-card-subline { margin-top:4px; color:#64748b; font-size:0.82rem;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ec-val { height:34px; border:1px solid #e2e8f0; border-radius:6px; padding:0 10px;
            font-size:0.875rem; width:100%; box-sizing:border-box; background:#fff; }
        .ec-val:focus { outline:none; border-color:#2563eb; }
        .ec-textarea { height:auto; min-height:62px; padding:8px 10px; line-height:1.4;
            font-family:inherit; resize:vertical; }
        .ec-name { font-weight:400; }
        .ec-multi { display:flex; flex-direction:column; gap:4px; }
        .ec-multi-row { display:flex; gap:4px; align-items:center; }
        .ec-star-row { width:24px; height:24px; flex:0 0 auto; }
        .ec-star-row svg { width:15px; height:15px; }
        .ec-multi-x { border:none; background:transparent; color:#cbd5e1; font-size:1.05rem;
            line-height:1; cursor:pointer; padding:0 4px; }
        .ec-multi-x:hover { color:#ef4444; }
        .ec-multi-add { align-self:flex-start; border:none; background:none; color:var(--v2-accent, #2563eb);
            font-size:0.78rem; cursor:pointer; padding:2px 0; }
        .ec-orgchips { display:flex; flex-wrap:wrap; gap:6px; }
        .ec-orgchip { display:inline-flex; align-items:center; gap:4px; padding:3px 8px; border-radius:999px;
            background:#eef2ff; color:#3730a3; font-size:0.8rem; }
        .ec-orgchip-x { border:none; background:transparent; color:#6366f1; cursor:pointer;
            font-size:0.95rem; line-height:1; padding:0; }
        .ec-orgchip-x:hover { color:#ef4444; }
        .ec-card-flash { border-color:var(--v2-accent) !important; box-shadow:0 0 0 3px var(--v2-accent-light); }
        /* Edit popup reuses .v2-approval-popup shell; strip the inner card chrome.
           Fixed height with a scrollbar so the popup never resizes per record. */
        .ec-edit-popup-overlay .v2-approval-popup-body .ec-card { border:none; padding:0; }
        .ec-edit-popup-overlay .v2-approval-popup { max-height:88vh; display:flex; flex-direction:column; }
        .ec-edit-popup-overlay .v2-approval-popup-body { flex:1 1 auto; overflow-y:auto; }
        /* Edit-contact popup: a touch narrower. Edit-org popup: wider (just under
           the EEM's 560px) and shorter, so the popup behind shows when nested. */
        .ec-edit-popup-contact .v2-approval-popup { max-width:460px; height:600px; }
        .ec-edit-popup-org .v2-approval-popup { max-width:540px; height:440px; }
        /* The link/search popup is smaller so it doesn't fully cover the edit popup. */
        .ec-search-popup-overlay .v2-approval-popup { max-width:360px; height:440px; }
        .ec-link-icon { color:var(--v2-accent, #2563eb) !important; }
        /* Edit popup header: pencil icon + the record's (live) name. */
        .ec-popup-title { display:flex; align-items:center; gap:8px; }
        .ec-popup-title-icon { display:inline-flex; color:var(--v2-text-tertiary, #94a3b8); }
        .ec-popup-title-icon svg { width:16px; height:16px; }
        .ec-popup-title-empty { color:var(--v2-text-tertiary, #94a3b8); font-weight:500; }
        /* Read-only details popup — mirrors the contacts directory right panel.
           Taller than the edit-org popup since it also shows events + emails. */
        .ec-details-popup-overlay .v2-approval-popup { height:600px; }
        .ec-details-body .ec-detail-subtitle { color:#64748b; font-size:0.85rem; margin-bottom:14px; }
        .ec-detail-grid { display:flex; gap:24px; flex-wrap:wrap; margin-bottom:14px; }
        .ec-detail-section { margin-bottom:14px; }
        .ec-detail-section:last-child { margin-bottom:0; }
        .ec-detail-grid .ec-detail-section { margin-bottom:0; }
        .ec-detail-label { font-size:0.68rem; text-transform:uppercase; letter-spacing:0.05em;
            color:#94a3b8; font-weight:600; margin-bottom:6px; display:flex; align-items:center; gap:6px; }
        .ec-detail-count { display:inline-flex; align-items:center; justify-content:center; min-width:18px;
            height:18px; padding:0 5px; border-radius:9px; background:#f1f5f9; color:#64748b;
            font-size:0.7rem; font-weight:600; letter-spacing:0; }
        .ec-detail-value { font-size:0.875rem; color:#1f2937; padding:2px 0; }
        .ec-detail-copy { cursor:pointer; border-radius:4px; margin:0 -4px; padding:2px 4px;
            transition:background .12s ease; }
        .ec-detail-copy:hover { background:#f1f5f9; }
        .ec-detail-copied { background:#dcfce7 !important; }
        .ec-detail-notes { white-space:pre-wrap; color:#475569; line-height:1.45; font-size:0.85rem; }
        .ec-detail-list { display:flex; flex-direction:column; border:1px solid #eef2f7;
            border-radius:8px; overflow:hidden; }
        .ec-detail-item { display:flex; align-items:center; gap:8px; padding:8px 10px; cursor:pointer;
            border-bottom:1px solid #f1f5f9; transition:background .12s ease; }
        .ec-detail-item:last-child { border-bottom:none; }
        .ec-detail-item:hover { background:#f1f5f9; }
        .ec-detail-item-icon { display:inline-flex; flex:0 0 auto; color:#94a3b8; }
        .ec-detail-item-icon svg { width:15px; height:15px; }
        .ec-detail-item-title { flex:1; min-width:0; font-size:0.875rem; color:#1f2937;
            overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .ec-detail-item-primary { font-weight:600; }
        .ec-detail-item-meta { color:#64748b; font-size:0.78rem; white-space:nowrap;
            overflow:hidden; text-overflow:ellipsis; max-width:45%; }
        .ec-detail-empty { color:#94a3b8; font-size:0.85rem; }
        .ec-details-edit-btn { display:inline-flex; align-items:center; gap:6px; }
        /* Floating "Copied" pill — same as the contacts directory side panel. */
        .cdp-float-tip { position:fixed; z-index:2147483647; padding:4px 9px;
            background:var(--text-primary, #1e293b); color:var(--bg-primary, #fff);
            border-radius:6px; font-size:11px; font-weight:600; white-space:nowrap;
            box-shadow:0 4px 14px rgba(0,0,0,0.22); pointer-events:none; opacity:0;
            transition:opacity .14s ease; }
        .cdp-float-tip.visible { opacity:1; }
        /* Linked-events + related-emails sections transplanted from the directory
           panel. Most .cdp-* / .overlap-* / status styles are global; these fill
           in the few the popup needs and match the directory spacing. */
        .ec-details-body .cdp-section { margin-bottom:14px; }
        .ec-details-body .cdp-section:last-child { margin-bottom:0; }
        .ec-details-body .cdp-label { display:flex; align-items:center; gap:8px;
            font-size:0.68rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;
            color:#94a3b8; margin-bottom:8px; }
        .ec-details-body .cdp-count { display:inline-flex; align-items:center; justify-content:center;
            min-width:18px; height:18px; padding:0 5px; border-radius:9px; background:#f1f5f9;
            color:#64748b; font-size:0.7rem; font-weight:600; letter-spacing:0; text-transform:none; }
        .ec-details-body .cdp-empty { color:#94a3b8; font-size:0.85rem; }
        .ec-details-body .cdp-list { list-style:none; margin:0; padding:4px; background:#f8fafc;
            border:1px solid #e5e7eb; border-radius:8px; display:flex; flex-direction:column; gap:2px; }
        .ec-details-body .cdp-list-item { display:flex; align-items:center; justify-content:space-between;
            gap:10px; padding:8px 10px; border-radius:6px; }
        .ec-details-body .cdp-list-title { flex:1; min-width:0; font-size:0.875rem; font-weight:600;
            color:#1f2937; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .ec-details-body .cdp-list-meta { flex-shrink:0; font-size:0.72rem; color:#94a3b8; white-space:nowrap; }
        .ec-details-body .cdp-item-icon { flex-shrink:0; display:inline-flex; align-items:center; color:#94a3b8; }
        .ec-details-body .cdp-item-icon svg { width:14px; height:14px; }
        .ec-details-body .cdp-email-item { cursor:pointer; transition:background .12s ease; }
        .ec-details-body .cdp-email-item:hover, .ec-details-body .cdp-email-item:focus-visible {
            background:#fff; outline:none; }
        .ec-details-body .cdp-thread-badge { flex-shrink:0; display:inline-flex; align-items:center; gap:3px;
            padding:1px 7px; border-radius:9999px; background:var(--v2-accent-light, #f0f6ff);
            color:var(--v2-accent, #2563eb); font-size:11px; font-weight:600; }
        .ec-details-body .cdp-thread-badge svg { opacity:0.8; }
        .ec-details-body .cdp-events-divider { display:flex; align-items:center; gap:8px;
            padding:6px 2px 4px; font-size:10px; font-weight:700; text-transform:uppercase;
            letter-spacing:0.05em; color:#94a3b8; user-select:none; }
        .ec-details-body .cdp-events-divider::before, .ec-details-body .cdp-events-divider::after {
            content:''; flex:1; height:1px; background:#e5e7eb; }
        /* Linked-events box: match the related-emails (.cdp-list) box exactly.
           The global .overlap-* / .detail-panel-status rules live in
           schedule-redesign.css, which isn't loaded on every page that opens
           the EEM — so style them here to keep the popup self-contained. */
        .ec-details-body .overlap-list { margin:0; padding:4px; background:#f8fafc;
            border:1px solid #e5e7eb; border-radius:8px; display:flex; flex-direction:column; gap:2px; }
        .ec-details-body .overlap-item { display:flex; align-items:center; gap:10px;
            padding:8px 10px; border-radius:6px; cursor:pointer; transition:background .12s ease; }
        .ec-details-body .overlap-item:hover, .ec-details-body .overlap-item:focus-visible {
            background:#fff; outline:none; }
        .ec-details-body .overlap-title { flex:1; min-width:0; font-size:0.875rem; font-weight:600;
            color:#1f2937; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .ec-details-body .overlap-time { flex-shrink:0; font-size:0.72rem; color:#94a3b8; white-space:nowrap; }
        /* Status badge — base shape + per-status colors (mirrors .detail-panel-status). */
        .ec-details-body .detail-panel-status { flex-shrink:0; display:inline-flex; align-items:center;
            font-size:0.72rem; font-weight:600; padding:3px 8px; border-radius:9999px;
            border:1px solid #9ca3af; background-color:rgba(107,114,128,0.1); color:#475569; white-space:nowrap; }
        .ec-details-body .detail-panel-status.status-received { color:var(--status-received,#2b5ea0); border-color:var(--status-received,#2b5ea0); background-color:var(--status-received-bg,rgba(43,94,160,0.1)); }
        .ec-details-body .detail-panel-status.status-hold { color:var(--status-hold,#f97316); border-color:var(--status-hold,#f97316); background-color:var(--status-hold-bg,rgba(249,115,22,0.1)); }
        .ec-details-body .detail-panel-status.status-referred { color:var(--status-referred,#8b5cf6); border-color:var(--status-referred,#8b5cf6); background-color:var(--status-referred-bg,rgba(139,92,246,0.1)); }
        .ec-details-body .detail-panel-status.status-fyied { color:var(--status-fyied,#14b8a6); border-color:var(--status-fyied,#14b8a6); background-color:var(--status-fyied-bg,rgba(20,184,166,0.1)); }
        .ec-details-body .detail-panel-status.status-scheduling_in_progress { color:var(--status-scheduling_in_progress,#14b8a6); border-color:var(--status-scheduling_in_progress,#14b8a6); background-color:var(--status-scheduling_in_progress-bg,rgba(20,184,166,0.1)); }
        .ec-details-body .detail-panel-status.status-scheduled { color:var(--status-scheduled,#22c55e); border-color:var(--status-scheduled,#22c55e); background-color:var(--status-scheduled-bg,rgba(34,197,94,0.1)); }
        .ec-details-body .detail-panel-status.status-rsvped { color:var(--status-rsvped,#10b981); border-color:var(--status-rsvped,#10b981); background-color:var(--status-rsvped-bg,rgba(16,185,129,0.1)); }
        .ec-details-body .detail-panel-status.status-regrets_sent { color:var(--status-regrets_sent,#ef4444); border-color:var(--status-regrets_sent,#ef4444); background-color:var(--status-regrets_sent-bg,rgba(239,68,68,0.1)); }
        .ec-details-body .detail-panel-status.status-passed { color:var(--status-passed,#6b7280); border-color:var(--status-passed,#6b7280); background-color:var(--status-passed-bg,rgba(107,114,128,0.1)); }
        .ec-details-body .detail-panel-status.status-canceled { color:var(--status-canceled,#ef4444); border-color:var(--status-canceled,#ef4444); background-color:var(--status-canceled-bg,rgba(239,68,68,0.1)); }
        .ec-details-body .detail-panel-status.status-requires_hms_review { color:var(--status-requires_hms_review,#eab308); border-color:var(--status-requires_hms_review,#eab308); background-color:var(--status-requires_hms_review-bg,rgba(245,158,11,0.1)); }
        /* Email-thread overlay (a related email opened from the popup). */
        .cdp-email-overlay { position:fixed; inset:0; z-index:9000; display:flex; align-items:center;
            justify-content:center; padding:24px; background:rgba(15,23,42,0.45);
            -webkit-backdrop-filter:blur(2px); backdrop-filter:blur(2px); }
        .cdp-email-modal { position:relative; display:flex; flex-direction:column; width:min(640px,100%);
            max-height:80vh; background:#fff; border-radius:12px; box-shadow:0 20px 50px rgba(0,0,0,0.3);
            overflow:hidden; }
        .cdp-email-modal-body { overflow-y:auto; padding:20px; }
        .cdp-email-close { position:absolute; top:12px; right:12px; z-index:1; display:flex;
            align-items:center; justify-content:center; width:30px; height:30px; padding:0; border:none;
            border-radius:8px; background:#fff; color:#6b7280; cursor:pointer;
            transition:background .15s ease, color .15s ease; }
        .cdp-email-close svg { width:16px; height:16px; }
        .cdp-email-close:hover { background:#f1f5f9; color:#1f2937; }
        .cdp-email-thread-label { font-size:0.72rem; font-weight:600; text-transform:uppercase;
            letter-spacing:0.04em; color:#94a3b8; margin-bottom:10px; }
        /* Related-events dropdown inside an email (hover to open). */
        .cdp-relevents { position:relative; display:inline-flex; }
        .cdp-relevents-btn { width:auto; gap:3px; padding:0 6px; }
        .cdp-relevents-count { font-size:11px; font-weight:700; }
        .cdp-relevents-menu { display:none; position:absolute; top:calc(100% + 4px); right:0; z-index:5;
            min-width:230px; max-width:320px; padding:4px; background:#fff; border:1px solid #e2e8f0;
            border-radius:8px; box-shadow:0 8px 20px rgba(0,0,0,0.16); }
        .cdp-relevents:hover .cdp-relevents-menu { display:block; }
        .cdp-relevents-menu::before { content:''; position:absolute; left:0; right:0; bottom:100%; height:8px; }
        .cdp-relevents-heading { padding:6px 8px 4px; font-size:11px; font-weight:700; text-transform:uppercase;
            letter-spacing:0.04em; color:#9ca3af; }
        .cdp-relevents-item { display:flex; align-items:center; justify-content:space-between; gap:8px;
            width:100%; padding:7px 8px; border:none; border-radius:6px; background:none; font-family:inherit;
            font-size:0.8rem; color:#1f2937; text-align:left; cursor:pointer; transition:background .12s ease; }
        .cdp-relevents-item:hover { background:#f1f5f9; }
        .cdp-relevents-title { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        /* Related-record mini cards (contact's orgs, org's people). */
        .ec-relcards { display:flex; flex-direction:column; gap:6px; }
        .ec-relcard { display:flex; align-items:center; gap:6px; padding:5px 8px;
            border:1px solid #e2e8f0; border-radius:8px; background:#fff; }
        .ec-relcard-name { flex:1; min-width:0; font-size:0.875rem; overflow:hidden;
            text-overflow:ellipsis; white-space:nowrap; }
        .ec-relcard-actions { display:flex; align-items:center; gap:2px; }
        .ec-relcard .ec-card-icon-btn { width:24px; height:24px; }
        .ec-relcard-x:hover { color:#ef4444; }
        .ec-relcard-star { width:24px; height:24px; flex:0 0 auto; }
        /* Org subheader jump button — matches the header date link (hover bg, no underline). */
        .v2-org-jump { background:transparent; border:none; cursor:pointer; text-align:left;
            padding:2px 4px; margin-left:-4px; border-radius:4px; font:inherit; color:inherit;
            transition:background-color .15s ease; }
        .v2-org-jump:hover { background-color: var(--v2-bg-tertiary, #f1f5f9); }
        .v2-org-jump-empty { color:#94a3b8; font-style:italic; }`;
        const style = el('style', null, css);
        style.id = 'ec-panel-styles';
        document.head.appendChild(style);
    }

    // ----- public API ------------------------------------------------------

    window.EventContactsPanel = {
        // Used by the modal's central Escape authority to close the topmost popup.
        isPopupOpen() { return popupStack.length > 0; },
        closePopup() {
            const top = popupStack[popupStack.length - 1];
            if (top) top();
        },
        // Open the read-only DETAILS popup for a contact/organization by id,
        // outside any event context (used by the global "/" quick search). It
        // shows the record read-only with an Edit toggle and no link/confirm
        // action. opts.name seeds the header before the full record loads;
        // opts.onClose fires after the popup closes.
        openDetails(kind, id, opts) {
            const cfg = kind === 'organization' ? CONFIGS.org : CONFIGS.contact;
            openDetailsPopup(cfg, { id: id, name: (opts && opts.name) || '' },
                { onClose: opts && opts.onClose });
        },
        // Open the shared edit popup for a single contact/organization by id,
        // outside any event context (used by the contacts directory). opts.onClose
        // fires after the popup closes so the caller can refresh its view.
        async openEditor(kind, id, opts) {
            const cfg = kind === 'organization' ? CONFIGS.org : CONFIGS.contact;
            try {
                const r = await api('GET', `/api/${cfg.api}/${id}/`);
                const rec = cfg.hasLocation
                    ? { id: r.id, name: r.name, location: r.location, emails: r.emails,
                        phones: r.phones, members: r.members, primary_contact_id: r.primary_contact_id,
                        notes: r.notes }
                    : { id: r.id, name: r.name, position: r.position, emails: r.emails, phones: r.phones,
                        organizations: r.organizations, primary_organization_id: r.primary_organization_id,
                        notes: r.notes };
                openEditPopup(cfg, rec, { standalone: true, onClose: opts && opts.onClose });
            } catch (e) {
                console.error('EventContactsPanel.openEditor failed', e);
                alert('Could not open editor: ' + e.message);
            }
        },
        render(eventId, eventData) {
            state.eventId = eventId;
            editing.clear();
            expanded.clear();
            state.reviewInline = computeReviewInline(eventData);
            state.inReview = !!(eventData && eventData.requires_human_review);
            bumpEventRecents(eventData);
            wireAll();
            renderList(CONFIGS.contact, (eventData && eventData.contacts) || []);
            renderList(CONFIGS.org, (eventData && eventData.organizations) || []);
            updateOrgSubheader(eventData);
            if (window.EventReviewCards) window.EventReviewCards.render(eventId, eventData);
        },
        init(eventId, attempt) {
            state.eventId = eventId;
            if (!document.getElementById(CONFIGS.contact.listId)) {
                if ((attempt || 0) < 10) {
                    setTimeout(() => this.init(eventId, (attempt || 0) + 1), 60);
                }
                return;
            }
            editing.clear();
            expanded.clear();
            wireAll();
            refresh();
        },
    };
})();
