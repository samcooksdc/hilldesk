/* SPDX-License-Identifier: Apache-2.0 */
/**
 * EventChangeReview — email change-request review inside the Event Editing
 * Modal.
 *
 * When an email asks to reschedule or cancel an EXISTING event, the ingestion
 * pipeline stores per-field EventChangeSuggestions. This module reviews them
 * in the same design language — and interaction model — as the AI extraction
 * review:
 *
 *  - ONLY the changed fields enter review. Each mapped form field gets the
 *    gold pending treatment (same wrapper classes as ReviewableField) with the
 *    SUGGESTED value pre-filled in the input. The modal layout is untouched.
 *  - Hovering the field shows a POPOVER (the extraction review's popover
 *    styling) that states the change — original → suggested, with the email's
 *    verbatim wording — and carries the Accept / Reject buttons.
 *  - Putting the cursor in the box ACCEPTS the change (mirrors the extraction
 *    review's focus-to-accept). The popover then offers only Revert.
 *  - Ctrl+Z in the field undoes an accepted change (server-side revert: the
 *    event's original value is restored and the suggestion reopens).
 *  - Unmappable fields (a cancellation's status change) render as a compact
 *    review card at the top of the Event Details panel with the same hover
 *    popover.
 *
 * Pluggable-module contract (mirrors window.EventReviewCards): the modal
 * calls counts() / hasPending() / focusNext(); this module calls back into
 * modal.updateReviewProgress() / modal.completeReviewMode().
 */
(function () {
    'use strict';

    const REVIEW_URL = (id) => `/api/suggestions/${id}/review/`;

    // DOM id for each suggestable field (subset of the modal's FIELD_MAPPING).
    const FIELD_TO_ID = {
        title: 'v2-title',
        type: 'v2-event-type',
        format: 'v2-event-format',
        start_date: 'v2-start-date',
        start_time: 'v2-start-time',
        end_date: 'v2-end-date',
        end_time: 'v2-end-time',
        location: 'v2-location',
        description: 'v2-description',
    };

    const FIELD_LABELS = {
        title: 'Title', start_date: 'Date', start_time: 'Time',
        end_date: 'End date', end_time: 'End time', location: 'Location',
        status: 'Status', type: 'Type', format: 'Format',
        description: 'Description',
    };

    let modal = null;
    let rows = [];          // [{ suggestion, popover, input, wrapper }]
    let initialized = false;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function getCsrf() {
        return (modal && modal.csrfToken)
            || document.querySelector('[name=csrfmiddlewaretoken]')?.value
            || document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
    }

    function ensureStyles() {
        if (document.getElementById('ecr-styles')) return;
        const style = document.createElement('style');
        style.id = 'ecr-styles';
        // Popover cloned from the extraction review's .v2-review-popover /
        // .v2-review-tooltip (event-editing-modal-v2.css §15): same surface,
        // shadow, hover reveal, and dark green/red action buttons. Gold #eab308
        // is the shared "needs review" color.
        style.textContent = `
.ecr-popover { position:absolute; top:100%; left:0; min-width:220px; max-width:340px;
    margin-top:6px; background:var(--v2-bg-primary, #fff);
    border:1px solid rgba(234,179,8,.6); border-radius:8px;
    box-shadow:0 0 0 3px rgba(234,179,8,.25), 0 4px 14px rgba(0,0,0,.18);
    z-index:120; padding:8px 12px;
    opacity:0; visibility:hidden; pointer-events:none;
    /* Instant hide (no fade-out); fade applies on reveal only. */
    transition:none; }
/* Invisible hover bridge over the gap between the field and the popup, so
   the popup only hides once the mouse truly leaves field+popup. */
.ecr-popover::before { content:''; position:absolute; top:-10px; left:0;
    right:0; height:10px; }
.ecr-wrapper:hover > .ecr-popover, .ecr-card:hover > .ecr-popover,
.ecr-wrapper:focus-within > .ecr-popover, .ecr-popover:hover {
    opacity:1; visibility:visible; pointer-events:auto;
    transition:opacity .15s ease; }
.ecr-popover [hidden] { display:none !important; }
.ecr-pop-change { display:flex; align-items:baseline; gap:6px; flex-wrap:wrap;
    font-size:13px; margin-bottom:8px; }
.ecr-old { color:var(--v2-text-tertiary, #9ca3af); font-weight:400; }
.ecr-arrow { color:#a16207; font-weight:700; }
.ecr-new { font-weight:700; }
.ecr-pop-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.ecr-accept-btn, .ecr-reject-btn, .ecr-revert-btn { display:flex; align-items:center;
    justify-content:center; gap:4px; padding:6px 12px; border:none; border-radius:6px;
    font-size:12px; font-weight:500; cursor:pointer; transition:all .15s ease;
    white-space:nowrap; }
.ecr-accept-btn { background:#166534; color:#fff; border:1px solid #14532d; }
.ecr-accept-btn:hover { background:#14532d; }
.ecr-reject-btn { background:#991b1b; color:#fff; border:1px solid #7f1d1d; }
.ecr-reject-btn:hover { background:#7f1d1d; }
.ecr-revert-btn { background:transparent; color:var(--v2-text-secondary, #4b5563);
    border:1px solid var(--v2-border-color, #d1d5db); }
.ecr-revert-btn:hover { background:rgba(156,163,175,.15); }
.ecr-pop-actions button:disabled { opacity:.5; cursor:default; }
.ecr-pop-state { display:inline-block; padding:1px 10px; border-radius:10px;
    font-size:11px; line-height:18px; font-weight:700; }
.ecr-pop-state.ecr-state-applied { background:rgba(34,197,94,.16); color:#15803d; }
.ecr-pop-state.ecr-state-rejected { background:rgba(153,27,27,.12); color:#991b1b; }
/* While the cursor is in the box: only the change + a full-width Revert. */
.ecr-wrapper:focus-within .ecr-pop-state { display:none !important; }
.ecr-wrapper:focus-within .ecr-revert-btn { width:100%; flex:1 1 100%; }
.ecr-card { position:relative; border:1px solid rgba(234,179,8,.5);
    border-left:3px solid #eab308; border-radius:6px; padding:8px 12px;
    margin:0 0 12px; background:rgba(234,179,8,.05); font-size:12.5px; }
.ecr-card.ecr-card-resolved { border-color:var(--v2-border-color, #d1d5db);
    border-left-color:var(--v2-border-color, #9ca3af); background:transparent;
    opacity:.85; }
.ecr-card-title { font-weight:700; margin-right:6px; color:#a16207; }
`;
        document.head.appendChild(style);
    }

    // ------------------------------------------------------------------
    // Popover
    // ------------------------------------------------------------------

    function verbatimFor(suggestion) {
        const v = suggestion.verbatim || {};
        if (suggestion.field_name.indexOf('date') !== -1) return v.date_text || '';
        if (suggestion.field_name.indexOf('time') !== -1) return v.time_text || '';
        return '';
    }

    function inputValueFor(suggestion) {
        // <input type="time"> wants HH:MM; the API may serialize HH:MM:SS.
        if (suggestion.field_name.indexOf('time') !== -1) {
            return String(suggestion.suggested_value || '').slice(0, 5);
        }
        return suggestion.suggested_value || '';
    }

    function originalValueFor(suggestion) {
        let original = suggestion.current_value || '';
        if (suggestion.field_name.indexOf('time') !== -1) {
            original = original.slice(0, 5);
        }
        return original;
    }

    function sourceSnippet(suggestion) {
        // Verbatim wording from the email when the model recorded it; for a
        // cancellation (no verbatim on a status change) fall back to the word
        // that carries the intent so SOMETHING lights up in the email pane.
        const verbatim = verbatimFor(suggestion);
        if (verbatim) return verbatim;
        if (suggestion.intent === 'CANCELLATION') return 'cancel';
        return suggestion.suggested_value || '';
    }

    function highlightSource(suggestion) {
        const snippet = sourceSnippet(suggestion);
        if (snippet && modal && typeof modal.highlightEmailText === 'function') {
            modal.highlightEmailText({ text_snippet: String(snippet) });
        }
    }

    function clearSourceHighlight() {
        if (modal && typeof modal.clearEmailHighlights === 'function') {
            modal.clearEmailHighlights();
        }
    }

    function displayValue(suggestion, raw) {
        if (raw == null || raw === '') return '(not set)';
        if (suggestion.field_name.indexOf('time') !== -1) {
            const parts = String(raw).slice(0, 5).split(':');
            const hour = parseInt(parts[0], 10);
            if (!isNaN(hour) && parts[1] !== undefined) {
                const ampm = hour >= 12 ? 'PM' : 'AM';
                const h12 = hour % 12 || 12;
                return `${h12}:${parts[1]} ${ampm}`;
            }
        }
        return String(raw);
    }

    function popoverHtml(suggestion) {
        const original = displayValue(suggestion, suggestion.current_value);
        const proposed = displayValue(suggestion, suggestion.suggested_value);
        return `
            <div class="ecr-pop-change">
                <span class="ecr-old">${esc(original)}</span>
                <span class="ecr-arrow">&rarr;</span>
                <span class="ecr-new">${esc(proposed)}</span>
            </div>
            <div class="ecr-pop-actions">
                <button type="button" class="ecr-accept-btn">&#10003; Accept</button>
                <button type="button" class="ecr-reject-btn">&#10007; Reject</button>
                <button type="button" class="ecr-revert-btn" hidden
                        title="Undo (Ctrl+Z)">&#8630; Revert</button>
                <span class="ecr-pop-state" hidden></span>
            </div>
        `;
    }

    function refreshPopover(row) {
        const status = row.suggestion.status;
        const q = (sel) => row.popover.querySelector(sel);
        const pending = status === 'pending';
        q('.ecr-accept-btn').hidden = !pending;
        q('.ecr-reject-btn').hidden = !pending;
        q('.ecr-revert-btn').hidden = pending;
        const stateEl = q('.ecr-pop-state');
        stateEl.hidden = pending;
        stateEl.textContent = status === 'approved' ? 'Applied'
            : status === 'rejected' ? 'Rejected' : '';
        stateEl.classList.toggle('ecr-state-applied', status === 'approved');
        stateEl.classList.toggle('ecr-state-rejected', status === 'rejected');
        if (row.wrapper && row.input) {
            row.wrapper.classList.toggle('v2-review-pending', pending);
        }
        if (row.card) {
            row.card.classList.toggle('ecr-card-resolved', !pending);
        }
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------

    async function review(row, action) {
        const body = { action };
        if (action === 'approve' && row.input) {
            body.value = row.input.value;   // whatever is in the box applies
        }
        const resp = await fetch(REVIEW_URL(row.suggestion.id), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrf(),
            },
            body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data.success === false) {
            throw new Error(data.message || data.error || 'Review action failed');
        }
        return data;
    }

    function afterStateChange(row, status) {
        row.suggestion.status = status;
        if (row.input) {
            if (status === 'rejected') {
                row.input.value = originalValueFor(row.suggestion);
            } else if (status === 'pending') {
                row.input.value = inputValueFor(row.suggestion);
            }
        }
        refreshPopover(row);
        if (modal) {
            modal._didMutate = true;
            modal.updateReviewProgress();
            if (!hasPending() && typeof modal.isReviewComplete === 'function'
                    && modal.isReviewComplete()) {
                modal.completeReviewMode();
            }
        }
    }

    async function act(row, action, nextStatus) {
        if (row._busy) return;
        row._busy = true;
        const buttons = row.popover.querySelectorAll('button');
        buttons.forEach((b) => { b.disabled = true; });
        try {
            await review(row, action);
            afterStateChange(row, nextStatus);
        } catch (e) {
            alert(e.message);
        } finally {
            row._busy = false;
            buttons.forEach((b) => { b.disabled = false; });
        }
    }

    function bindPopover(row) {
        row.popover.querySelector('.ecr-accept-btn')
            .addEventListener('click', () => act(row, 'approve', 'approved'));
        row.popover.querySelector('.ecr-reject-btn')
            .addEventListener('click', () => act(row, 'reject', 'rejected'));
        row.popover.querySelector('.ecr-revert-btn')
            .addEventListener('click', () => act(row, 'revert', 'pending'));
    }

    // ------------------------------------------------------------------
    // Row construction
    // ------------------------------------------------------------------

    function buildFieldRow(suggestion) {
        const fieldId = FIELD_TO_ID[suggestion.field_name];
        const input = fieldId ? document.getElementById(fieldId) : null;
        if (!input) return buildCardRow(suggestion);   // unmappable → details-panel card

        // Same wrapper classes as ReviewableField: the gold pending glow and
        // hover treatment come from the existing review CSS; the layout of the
        // modal is untouched (the popover is absolutely positioned).
        let wrapper = input.closest('.v2-review-field-wrapper');
        if (!wrapper) {
            wrapper = document.createElement('div');
            wrapper.className = 'v2-review-field-wrapper';
            input.parentNode.insertBefore(wrapper, input);
            wrapper.appendChild(input);
        }
        wrapper.classList.add('ecr-wrapper');

        if (suggestion.status === 'pending') {
            // "The new suggestion in the box" — editable before accepting.
            input.value = inputValueFor(suggestion);
        }

        const popover = document.createElement('div');
        popover.className = 'ecr-popover';
        popover.innerHTML = popoverHtml(suggestion);
        wrapper.appendChild(popover);

        const row = { suggestion, popover, input, wrapper, card: null, _busy: false };
        bindPopover(row);
        refreshPopover(row);

        // Hovering the field highlights the email's source wording in the
        // email pane (same behavior as the extraction review's fields).
        wrapper.addEventListener('mouseenter', () => highlightSource(suggestion));
        wrapper.addEventListener('mouseleave', () => {
            if (document.activeElement !== input) clearSourceHighlight();
        });

        // Cursor in the box = accept (the extraction review's focus-to-accept),
        // applying whatever value is in the box at that moment.
        input.addEventListener('focus', () => {
            if (row.suggestion.status === 'pending' && !row._busy) {
                act(row, 'approve', 'approved');
            }
            highlightSource(suggestion);
        });
        input.addEventListener('blur', () => clearSourceHighlight());
        // Ctrl+Z in the field undoes an accepted change (server-side revert).
        input.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z'
                    && row.suggestion.status === 'approved') {
                e.preventDefault();
                act(row, 'revert', 'pending');
            }
        });
        return row;
    }

    function buildCardRow(suggestion) {
        // Fields without a form control (e.g. a cancellation's status change)
        // render as a compact review card at the top of the details panel,
        // with the same hover popover carrying the actions.
        const panel = document.getElementById('v2-event-details-panel');
        if (!panel) return null;
        const card = document.createElement('div');
        card.className = 'ecr-card';
        const intentLabel = suggestion.intent === 'CANCELLATION'
            ? 'Cancellation requested' : 'Change requested';
        card.innerHTML = `
            <span class="ecr-card-title">${esc(intentLabel)}</span>
            <span class="ecr-old">${esc(suggestion.current_value || '(not set)')}</span>
            <span class="ecr-arrow">&rarr;</span>
            <span class="ecr-new">${esc(suggestion.suggested_value)}</span>
        `;
        const popover = document.createElement('div');
        popover.className = 'ecr-popover';
        popover.innerHTML = popoverHtml(suggestion);
        card.appendChild(popover);
        panel.insertBefore(card, panel.firstChild);

        card.addEventListener('mouseenter', () => highlightSource(suggestion));
        card.addEventListener('mouseleave', () => clearSourceHighlight());

        const row = { suggestion, popover, input: null, wrapper: null, card, _busy: false };
        bindPopover(row);
        refreshPopover(row);
        return row;
    }

    // ------------------------------------------------------------------
    // Module contract (mirrors window.EventReviewCards)
    // ------------------------------------------------------------------

    function init(modalInstance, suggestions) {
        destroy();
        modal = modalInstance;
        if (!suggestions || !suggestions.length) return;
        ensureStyles();
        rows = suggestions.map(buildFieldRow).filter(Boolean);
        initialized = true;
    }

    function liveRows() {
        // Prune rows whose DOM is gone — the modal re-rendered for another
        // event, so those suggestions are no longer part of THIS review.
        rows = rows.filter((r) => r.popover && r.popover.isConnected);
        if (!rows.length) initialized = false;
        return rows;
    }

    function counts() {
        if (!initialized) return { total: 0, reviewed: 0 };
        const live = liveRows();
        const total = live.length;
        const reviewed = live.filter((r) => r.suggestion.status !== 'pending').length;
        return { total, reviewed };
    }

    function hasPending() {
        return initialized && liveRows().some((r) => r.suggestion.status === 'pending');
    }

    function focusNext() {
        const next = liveRows().find((r) => r.suggestion.status === 'pending');
        if (!next) return false;
        const target = next.input || next.card;
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (next.input) {
            // Cursor lands in the box — which accepts the change, the same
            // way the extraction review's jump/focus flow accepts fields.
            next.input.focus({ preventScroll: true });
        }
        return true;
    }

    function destroy() {
        rows = [];
        initialized = false;
        modal = null;
    }

    window.EventChangeReview = { init, counts, hasPending, focusNext, destroy };
})();
