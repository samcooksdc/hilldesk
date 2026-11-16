/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Email Composer Module for HillDesk Event Editing Modal.
 *
 * Manages the inline email response composer that appears below the email
 * thread inside the scrollable area:
 * 1. Email thread display with sent response history
 * 2. AI + Template toolbar for draft generation
 * 3. Rich-text composer with variable auto-population
 */

class EmailComposer {
    constructor() {
        this.isComposerVisible = false;
        this.templates = [];
        this.eventData = {};
        this.emailData = {};
        this.sessionCount = 0;
        this.maxRegenerations = 3;
        this.currentDraft = '';
        this._initialized = false;
        // The email/thread the composer is currently replying to. Set when a
        // per-thread (or standalone) Reply button is clicked; falls back to the
        // first email in the panel when replying via the global Respond button.
        this.activeReplyEmailId = null;
        this.activeReplySender = '';
        // Ctrl+F-style search state
        this._searchMatches = [];
        this._searchIndex = -1;
        this._tooltipBound = false;
    }

    /**
     * The id of the email a reply will be sent against (in_reply_to target).
     * Prefers the thread the user explicitly chose to reply to, then the first
     * email in the panel, then the init-time email context.
     */
    _getActiveReplyEmailId() {
        if (this.activeReplyEmailId) return this.activeReplyEmailId;
        const firstItem = document.querySelector('.v2-email-item[data-email-id]');
        return firstItem ? firstItem.dataset.emailId : this.emailData.id;
    }

    /**
     * Initialize the composer with event and email context.
     * @param {Object} eventData - Event form data (title, date, time, etc.)
     * @param {Object} emailData - Email data (id, sender, subject, etc.)
     */
    init(eventData, emailData) {
        this.eventData = eventData || {};
        this.emailData = emailData || {};
        this.sessionCount = 0;
        this.isComposerVisible = false;

        // Always re-bind events since the modal DOM is replaced on each open
        this._initialized = false;
        this._bindEvents();
        this._initialized = true;

        this._initTooltips();

        this._loadSignature();
        this._loadResponseHistory();
        this._restoreDraft();

        console.log('EmailComposer: initialized with', {
            emailId: this.emailData.id,
            sender: this.emailData.sender_name,
            staffer: this.eventData.staffer_name
        });
    }

    // =========================================================================
    // Event Binding
    // =========================================================================

    _bindEvents() {
        // Respond button
        const respondBtn = document.getElementById('v2-email-respond-btn');
        if (respondBtn) {
            respondBtn.addEventListener('click', () => this.toggleComposer());
        }

        // Floating respond button (bottom-right of the email pane)
        const respondFab = document.getElementById('v2-email-respond-fab');
        if (respondFab) {
            respondFab.addEventListener('click', () => this.toggleComposer());
        }

        // Email list interactions are DELEGATED on the persistent #v2-email-content
        // node so they keep working after the list is refreshed in place (the
        // inner #v2-email-list is replaced without re-running _bindEvents).
        const emailContent = document.getElementById('v2-email-content');
        if (emailContent) {
            emailContent.addEventListener('click', (e) => {
                // Per-thread / standalone Reply — composer is moved below the row.
                const replyBtn = e.target.closest('.v2-thread-reply-btn');
                if (replyBtn) {
                    const anchor = replyBtn.closest('.v2-thread-reply-row') || replyBtn;
                    this.replyToThread(
                        replyBtn.dataset.replyEmailId || null,
                        replyBtn.dataset.replySender || '',
                        replyBtn.dataset.replySubject || '',
                        anchor
                    );
                    return;
                }
                // Detach thread / remove email / exclude message.
                const actionBtn = e.target.closest('[data-action]');
                if (actionBtn) this._handleEmailLinkAction(actionBtn);
            });
        }

        // Attach controls
        const attachBtn = document.getElementById('v2-email-attach-btn');
        if (attachBtn) {
            attachBtn.addEventListener('click', () => this._toggleAttachPicker());
        }
        const attachPicker = document.getElementById('v2-attach-picker');
        if (attachPicker) {
            // Close when the pointer leaves the picker (no explicit close button).
            attachPicker.addEventListener('mouseleave', () => this._closeAttachPicker());
        }
        const attachSearch = document.getElementById('v2-attach-search-input');
        if (attachSearch) {
            let debounce;
            attachSearch.addEventListener('input', () => {
                clearTimeout(debounce);
                debounce = setTimeout(() => this._searchAttachable(attachSearch.value.trim()), 250);
            });
        }
        // Attach result actions (delegated)
        const attachResults = document.getElementById('v2-attach-results');
        if (attachResults) {
            attachResults.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-attach-action]');
                if (btn) this._handleAttachAction(btn);
            });
        }

        // Email search box — Ctrl+F-style: highlight all matches, Enter steps
        // through them (Shift+Enter goes back), and the counter is click-through.
        const searchInput = document.querySelector('.v2-email-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                this._searchHighlight(searchInput.value.trim().toLowerCase());
            });
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this._gotoMatch(this._searchIndex + (e.shiftKey ? -1 : 1));
                }
            });
        }
        const searchCounter = document.getElementById('v2-search-counter');
        if (searchCounter) {
            searchCounter.addEventListener('click', () => {
                if (this._searchMatches.length) this._gotoMatch(this._searchIndex + 1);
            });
        }
        const searchPrev = document.getElementById('v2-search-prev');
        if (searchPrev) {
            searchPrev.addEventListener('click', () => {
                if (this._searchMatches.length) this._gotoMatch(this._searchIndex - 1);
            });
        }
        const searchNext = document.getElementById('v2-search-next');
        if (searchNext) {
            searchNext.addEventListener('click', () => {
                if (this._searchMatches.length) this._gotoMatch(this._searchIndex + 1);
            });
        }

        // Template selection (custom dropdown)
        const templateSelect = document.getElementById('v2-template-select');
        if (templateSelect) {
            const trigger = templateSelect.querySelector('.v2-template-select-trigger');
            if (trigger) {
                trigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    templateSelect.classList.toggle('open');
                });
            }
            // Close on outside click
            document.addEventListener('click', () => {
                templateSelect.classList.remove('open');
            });
        }

        // AI Generate Draft button — opens prompt popup
        const suggestBtn = document.getElementById('v2-ai-suggest-btn');
        if (suggestBtn) {
            suggestBtn.addEventListener('click', () => this._openDraftPrompt());
        }

        // Draft prompt popup — Generate button
        const draftGenerateBtn = document.getElementById('v2-draft-prompt-generate');
        if (draftGenerateBtn) {
            draftGenerateBtn.addEventListener('click', () => {
                const input = document.getElementById('v2-draft-prompt-input');
                const userPrompt = input ? input.value.trim() : '';
                this._closeDraftPrompt();
                this._suggestDraft(null, userPrompt);
            });
        }

        // Draft prompt popup — Cancel button
        const draftCancelBtn = document.getElementById('v2-draft-prompt-cancel');
        if (draftCancelBtn) {
            draftCancelBtn.addEventListener('click', () => this._closeDraftPrompt());
        }

        // Draft prompt popup — close on overlay click
        const draftOverlay = document.getElementById('v2-draft-prompt-overlay');
        if (draftOverlay) {
            draftOverlay.addEventListener('click', (e) => {
                if (e.target === draftOverlay) this._closeDraftPrompt();
            });
        }

        // Refinement chips
        document.querySelectorAll('.v2-refinement-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                const refinement = chip.dataset.refinement;
                this._suggestDraft(refinement);
            });
        });

        // Formatting bar
        document.querySelectorAll('.v2-format-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const command = btn.dataset.command;
                if (command === 'createLink') {
                    const url = prompt('Enter URL:');
                    if (url) document.execCommand('createLink', false, url);
                } else {
                    document.execCommand(command, false, null);
                }
            });
        });

        // CC/BCC toggle
        const ccBtn = document.getElementById('v2-composer-cc-btn');
        if (ccBtn) {
            ccBtn.addEventListener('click', () => {
                const fields = document.getElementById('v2-composer-cc-fields');
                if (fields) {
                    fields.style.display = fields.style.display === 'none' ? 'block' : 'none';
                }
            });
        }

        // Send button
        const sendBtn = document.getElementById('v2-composer-send');
        if (sendBtn) {
            sendBtn.addEventListener('click', () => this._sendResponse());
        }

        // Send-warning popup (unfilled variables)
        const sendWarnCancel = document.getElementById('v2-send-warning-cancel');
        if (sendWarnCancel) {
            sendWarnCancel.addEventListener('click', () => this._closeSendWarning());
        }
        const sendWarnConfirm = document.getElementById('v2-send-warning-confirm');
        if (sendWarnConfirm) {
            sendWarnConfirm.addEventListener('click', () => {
                this._closeSendWarning();
                this._performSend();
            });
        }
        const sendWarnOverlay = document.getElementById('v2-send-warning-overlay');
        if (sendWarnOverlay) {
            sendWarnOverlay.addEventListener('click', (e) => {
                if (e.target === sendWarnOverlay) this._closeSendWarning();
            });
        }

        // Save Draft button
        const saveDraftBtn = document.getElementById('v2-composer-save-draft');
        if (saveDraftBtn) {
            saveDraftBtn.addEventListener('click', () => this._saveDraft());
        }

        // Cancel button
        const cancelBtn = document.getElementById('v2-composer-cancel');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => this.hideComposer());
        }

        // Track changes in composer body for variable warning
        const body = document.getElementById('v2-composer-body');
        if (body) {
            body.addEventListener('input', () => this._checkUnfilledVars());
            // Tab / bullet indentation handling
            body.addEventListener('keydown', (e) => this._handleComposerKeydown(e));
        }
    }

    // =========================================================================
    // Rich-text editing: Tab indentation & bullet lists
    // =========================================================================

    _handleComposerKeydown(e) {
        if (e.key !== 'Tab') return;
        e.preventDefault();
        const body = document.getElementById('v2-composer-body');
        if (this._isInList(body)) {
            // Inside a bullet list: Tab nests, Shift+Tab un-nests
            document.execCommand(e.shiftKey ? 'outdent' : 'indent', false, null);
        } else if (!e.shiftKey) {
            // Plain text: insert a soft tab (4 spaces)
            document.execCommand('insertText', false, '    ');
        }
    }

    _isInList(container) {
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) return false;
        let node = sel.anchorNode;
        while (node && node !== container) {
            const name = node.nodeName;
            if (name === 'LI' || name === 'UL' || name === 'OL') return true;
            node = node.parentNode;
        }
        return false;
    }

    // =========================================================================
    // Composer Toggle
    // =========================================================================

    toggleComposer() {
        if (this.isComposerVisible) {
            this.hideComposer();
        } else {
            // Global Respond button: reply on the default (first) thread and
            // return the composer to its home position at the bottom.
            this.activeReplyEmailId = null;
            this.activeReplySender = '';
            const wrapper = document.getElementById('v2-inline-composer-wrapper');
            const content = document.getElementById('v2-email-content');
            if (wrapper && content) content.appendChild(wrapper);
            this.showComposer();
        }
    }

    /**
     * Open the composer to reply on a specific thread (or standalone email).
     * All subsequent send / draft / recipient resolution uses this target, and
     * the composer is moved to sit directly below the replied-to thread.
     * @param {string} emailId  - id of the email to reply against (in_reply_to)
     * @param {string} sender   - display recipient for the To: field
     * @param {string} subject  - thread subject, prefixed with "Re:"
     * @param {Element} anchorEl - element to place the composer after
     */
    replyToThread(emailId, sender, subject, anchorEl) {
        this.activeReplyEmailId = emailId;
        this.activeReplySender = sender || '';

        // Relocate the composer to directly below the thread being replied to.
        const wrapper = document.getElementById('v2-inline-composer-wrapper');
        if (wrapper && anchorEl && anchorEl.parentNode) {
            anchorEl.insertAdjacentElement('afterend', wrapper);
        }

        this.showComposer();
        const subjectInput = document.getElementById('v2-composer-subject');
        if (subjectInput && subject) {
            subjectInput.value = /^re:/i.test(subject.trim()) ? subject : `Re: ${subject}`;
        }
    }

    showComposer() {
        const wrapper = document.getElementById('v2-inline-composer-wrapper');
        const respondBtn = document.getElementById('v2-email-respond-btn');
        const respondFab = document.getElementById('v2-email-respond-fab');

        if (wrapper) wrapper.style.display = 'block';

        // Hide the floating button while the composer is open
        if (respondFab) respondFab.style.display = 'none';

        // Update Respond button text
        if (respondBtn) {
            respondBtn.innerHTML = `
                <svg class="v2-action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
                Close Compose
            `;
        }

        this.isComposerVisible = true;

        // Load templates
        this._loadTemplates();

        // Set To: from email sender
        this._setRecipient();

        // Scroll the composer into view within the email content area
        if (wrapper) {
            setTimeout(() => {
                wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 50);
        }
    }

    hideComposer() {
        const wrapper = document.getElementById('v2-inline-composer-wrapper');
        const respondBtn = document.getElementById('v2-email-respond-btn');
        const respondFab = document.getElementById('v2-email-respond-fab');
        const refinementRow = document.getElementById('v2-ai-refinement-row');

        if (wrapper) wrapper.style.display = 'none';
        if (refinementRow) refinementRow.style.display = 'none';

        // Restore the floating button when the composer is closed
        if (respondFab) respondFab.style.display = '';

        // Reset Respond button text
        if (respondBtn) {
            respondBtn.innerHTML = `
                <svg class="v2-action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M9 17l-5-5 5-5"></path>
                    <path d="M20 18v-2a4 4 0 0 0-4-4H4"></path>
                </svg>
                Respond
            `;
        }

        this.isComposerVisible = false;
    }

    // =========================================================================
    // Attach / remove emails & threads
    // =========================================================================

    _eventId() {
        const form = document.getElementById('v2-event-form');
        return form ? form.dataset.eventId : null;
    }

    _toggleAttachPicker() {
        const picker = document.getElementById('v2-attach-picker');
        if (!picker) return;
        if (picker.style.display === 'none' || !picker.style.display) {
            picker.style.display = 'block';
            const input = document.getElementById('v2-attach-search-input');
            if (input) { input.value = ''; input.focus(); }
            this._searchAttachable('');  // load recent candidates
        } else {
            this._closeAttachPicker();
        }
    }

    _closeAttachPicker() {
        const picker = document.getElementById('v2-attach-picker');
        if (picker) picker.style.display = 'none';
    }

    async _searchAttachable(query) {
        const eventId = this._eventId();
        const container = document.getElementById('v2-attach-results');
        if (!eventId || !container) return;
        try {
            const url = `/api/events/${eventId}/attachable_emails/?q=${encodeURIComponent(query || '')}`;
            const resp = await fetch(url, { headers: { 'X-CSRFToken': this._getCSRFToken() } });
            const data = await resp.json();
            this._renderAttachResults(data.emails || []);
        } catch (err) {
            console.error('Failed to search attachable emails:', err);
            container.innerHTML = '<div class="v2-attach-empty">Search failed.</div>';
        }
    }

    _renderAttachResults(emails) {
        const container = document.getElementById('v2-attach-results');
        if (!container) return;
        if (!emails.length) {
            container.innerHTML = '<div class="v2-attach-empty">No matching emails found.</div>';
            return;
        }
        container.innerHTML = emails.map(e => {
            const who = this._escapeHtml(e.sender_name || e.sender || 'Unknown');
            const threadNote = (e.thread && e.thread.message_count > 1)
                ? ` &middot; thread of ${e.thread.message_count}` : '';
            const threadBtn = e.thread
                ? `<button type="button" class="v2-attach-action-btn" data-attach-action="thread" data-thread-id="${e.thread.id}">Attach thread</button>`
                : '';
            return `<div class="v2-attach-result">
                <div class="v2-attach-result-info">
                    <div class="v2-attach-result-subject">${this._escapeHtml(e.subject || 'No subject')}</div>
                    <div class="v2-attach-result-meta">${who}${threadNote}</div>
                </div>
                <div class="v2-attach-result-actions">
                    <button type="button" class="v2-attach-action-btn" data-attach-action="email" data-email-id="${e.id}">Attach email</button>
                    ${threadBtn}
                </div>
            </div>`;
        }).join('');
    }

    _handleAttachAction(btn) {
        const action = btn.dataset.attachAction;
        this._closeAttachPicker();  // close the picker as soon as a choice is made
        if (action === 'email') {
            this._postLink('attach_email_link', { email_id: btn.dataset.emailId });
        } else if (action === 'thread') {
            this._postLink('attach_thread_link', { thread_id: btn.dataset.threadId });
        }
    }

    _handleEmailLinkAction(btn) {
        const action = btn.dataset.action;
        if (action === 'open-outlook') {
            const url = btn.dataset.weblink;
            if (url) window.open(url, '_blank', 'noopener');
            return;
        }
        if (action === 'detach-thread') {
            this._confirmRemove(
                'Remove conversation',
                'Detach this whole conversation from the event?',
                () => this._postLink('detach_thread_link', { thread_id: btn.dataset.threadId })
            );
        } else if (action === 'detach-email') {
            this._confirmRemove(
                'Remove email',
                'Remove this email from the event?',
                () => this._postLink('detach_email_link', { email_id: btn.dataset.emailId })
            );
        } else if (action === 'exclude-email') {
            this._confirmRemove(
                'Remove message',
                'Remove just this message from the event?',
                () => this._postLink('exclude_email_link', { email_id: btn.dataset.emailId })
            );
        }
    }

    /**
     * Lazily build the app-styled confirm popup on <body>. Building it here
     * (rather than in the template) guarantees it exists in the AJAX-loaded
     * modal — which only re-appends a fixed set of sibling overlays — and keeps
     * it out of any transformed ancestor so it centers on the viewport.
     */
    _ensureConfirmOverlay() {
        let overlay = document.getElementById('v2-confirm-overlay');
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.className = 'v2-draft-prompt-overlay';
        overlay.id = 'v2-confirm-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="v2-draft-prompt-popup v2-plain-popup">
                <div class="v2-draft-prompt-header">
                    <h3 id="v2-confirm-title">Remove from event</h3>
                </div>
                <div class="v2-draft-prompt-body">
                    <p id="v2-confirm-message" style="margin: 0; font-size: 13px; color: var(--v2-text-secondary, #64748b);"></p>
                </div>
                <div class="v2-draft-prompt-actions">
                    <button type="button" class="v2-btn-secondary" id="v2-confirm-cancel">Cancel</button>
                    <button type="button" class="v2-confirm-danger-btn" id="v2-confirm-ok">Remove</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        overlay.querySelector('#v2-confirm-cancel').addEventListener('click', () => this._closeConfirm());
        overlay.querySelector('#v2-confirm-ok').addEventListener('click', () => {
            const fn = this._pendingConfirm;
            this._closeConfirm();
            if (fn) fn();
        });
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this._closeConfirm();
        });
        return overlay;
    }

    _confirmRemove(title, message, onConfirm) {
        const overlay = this._ensureConfirmOverlay();
        const titleEl = overlay.querySelector('#v2-confirm-title');
        const msgEl = overlay.querySelector('#v2-confirm-message');
        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = message;
        this._pendingConfirm = onConfirm;
        overlay.style.display = 'flex';
    }

    _closeConfirm() {
        const overlay = document.getElementById('v2-confirm-overlay');
        if (overlay) overlay.style.display = 'none';
        this._pendingConfirm = null;
    }

    /**
     * Close the topmost open email-panel popup, if any. Returns true if one was
     * closed. Used by the modal's Escape handler so Escape dismisses a popup
     * before it falls through to closing the whole modal.
     */
    closeAnyOpenPopup() {
        const isOpen = (el) => el && getComputedStyle(el).display !== 'none';

        const confirmOverlay = document.getElementById('v2-confirm-overlay');
        if (isOpen(confirmOverlay)) { this._closeConfirm(); return true; }

        const sendWarning = document.getElementById('v2-send-warning-overlay');
        if (isOpen(sendWarning)) { sendWarning.style.display = 'none'; return true; }

        const draftPrompt = document.getElementById('v2-draft-prompt-overlay');
        if (isOpen(draftPrompt)) { this._closeDraftPrompt(); return true; }

        const attachPicker = document.getElementById('v2-attach-picker');
        if (isOpen(attachPicker)) { this._closeAttachPicker(); return true; }

        return false;
    }

    /**
     * Ctrl+F-style search: wrap every match in the email list in <mark>, track
     * them, and jump to the first. Nothing is hidden — matches are highlighted
     * and stepped through.
     */
    _searchHighlight(query) {
        this._clearHighlights();
        const counter = document.getElementById('v2-search-counter');
        const nav = document.getElementById('v2-search-nav');
        const list = document.getElementById('v2-email-list');
        if (!list) return;
        if (!query) {
            if (counter) counter.textContent = '';
            if (nav) nav.style.display = 'none';
            return;
        }

        // Collect matching text nodes (skip buttons/icons).
        const walker = document.createTreeWalker(list, NodeFilter.SHOW_TEXT, {
            acceptNode: (node) => {
                if (!node.nodeValue || !node.nodeValue.toLowerCase().includes(query)) {
                    return NodeFilter.FILTER_REJECT;
                }
                if (node.parentElement && node.parentElement.closest('button, svg')) {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            }
        });
        const textNodes = [];
        let node;
        while ((node = walker.nextNode())) textNodes.push(node);

        const matches = [];
        textNodes.forEach(textNode => {
            const text = textNode.nodeValue;
            const lower = text.toLowerCase();
            const frag = document.createDocumentFragment();
            let i = 0, idx;
            while ((idx = lower.indexOf(query, i)) !== -1) {
                if (idx > i) frag.appendChild(document.createTextNode(text.slice(i, idx)));
                const mark = document.createElement('mark');
                mark.className = 'v2-search-highlight';
                mark.textContent = text.slice(idx, idx + query.length);
                frag.appendChild(mark);
                matches.push(mark);
                i = idx + query.length;
            }
            if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)));
            if (textNode.parentNode) textNode.parentNode.replaceChild(frag, textNode);
        });

        this._searchMatches = matches;
        this._searchIndex = -1;
        if (nav) nav.style.display = 'flex';
        if (counter) counter.textContent = matches.length ? `${matches.length} found` : 'No matches';
        if (matches.length) this._gotoMatch(0);
    }

    _clearHighlights() {
        const list = document.getElementById('v2-email-list');
        if (list) {
            list.querySelectorAll('mark.v2-search-highlight').forEach(m => {
                const parent = m.parentNode;
                if (!parent) return;
                parent.replaceChild(document.createTextNode(m.textContent), m);
                parent.normalize();
            });
        }
        this._searchMatches = [];
        this._searchIndex = -1;
    }

    _gotoMatch(idx) {
        const matches = this._searchMatches || [];
        if (!matches.length) return;
        idx = ((idx % matches.length) + matches.length) % matches.length;
        matches.forEach(m => m.classList.remove('v2-search-highlight-current'));
        const current = matches[idx];
        current.classList.add('v2-search-highlight-current');
        current.scrollIntoView({ block: 'center', behavior: 'smooth' });
        this._searchIndex = idx;
        const counter = document.getElementById('v2-search-counter');
        if (counter) counter.textContent = `${idx + 1}/${matches.length}`;
    }

    /**
     * One body-level tooltip element, positioned with fixed coords on hover of
     * the email-panel icon/reply buttons — so it is never clipped by the
     * scrollable email panel. Bound once globally.
     */
    _initTooltips() {
        if (this._tooltipBound) return;
        this._tooltipBound = true;

        const tip = document.createElement('div');
        tip.className = 'v2-hover-tooltip';
        tip.style.display = 'none';
        document.body.appendChild(tip);

        const SEL = '.v2-thread-icon-btn[data-tooltip], .v2-thread-reply-btn[data-tooltip]';
        let showTimer = null;

        const positionAndShow = (el) => {
            const text = el.getAttribute('data-tooltip');
            if (!text) return;
            tip.textContent = text;
            tip.style.visibility = 'hidden';
            tip.style.display = 'block';
            const r = el.getBoundingClientRect();
            const tr = tip.getBoundingClientRect();
            let left = r.left + r.width / 2 - tr.width / 2;
            left = Math.max(6, Math.min(left, window.innerWidth - tr.width - 6));
            let top = r.top - tr.height - 8;
            if (top < 6) top = r.bottom + 8;  // flip below if no room above
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
            tip.style.visibility = 'visible';
        };

        const hideTip = () => {
            if (showTimer) { clearTimeout(showTimer); showTimer = null; }
            tip.style.display = 'none';
        };

        document.addEventListener('mouseover', (e) => {
            const el = e.target.closest && e.target.closest(SEL);
            if (!el) return;
            if (showTimer) { clearTimeout(showTimer); showTimer = null; }
            // The reply button waits 1s before its tooltip shows; the small icon
            // buttons (Outlook / remove) still show instantly.
            if (el.classList.contains('v2-thread-reply-btn')) {
                showTimer = setTimeout(() => { showTimer = null; positionAndShow(el); }, 1000);
            } else {
                positionAndShow(el);
            }
        });
        document.addEventListener('mouseout', (e) => {
            const el = e.target && e.target.closest && e.target.closest(SEL);
            if (el) hideTip();
        });
        // Hide on any scroll (fixed position would otherwise go stale).
        document.addEventListener('scroll', hideTip, true);
    }

    async _postLink(action, body) {
        const eventId = this._eventId();
        if (!eventId) return;
        try {
            const resp = await fetch(`/api/events/${eventId}/${action}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCSRFToken(),
                },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                alert(data.error || 'Action failed');
                return;
            }
            await this._refreshEmailPanel();
        } catch (err) {
            console.error('Link action failed:', err);
            alert('Action failed. Please try again.');
        }
    }

    /**
     * Re-render just the email list in place after an attach/detach, without
     * reloading the whole modal (which would collapse the Show Email pane).
     * Fetches the editing interface, swaps in the fresh #v2-email-list, and
     * relies on the delegated listeners on #v2-email-content (which persists).
     */
    async _refreshEmailPanel() {
        const eventId = this._eventId();
        const content = document.getElementById('v2-email-content');
        const list = document.getElementById('v2-email-list');
        if (!eventId || !content || !list) return;

        // Park the composer outside the list so it survives the swap.
        const wrapper = document.getElementById('v2-inline-composer-wrapper');
        if (wrapper) content.appendChild(wrapper);
        this.hideComposer();

        try {
            const resp = await fetch(`/event-editing/${eventId}/`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin',
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const html = await resp.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const freshList = doc.getElementById('v2-email-list');
            if (freshList) list.innerHTML = freshList.innerHTML;
            // The old highlight <mark>s are gone with the replaced HTML; re-apply.
            this._searchMatches = [];
            this._searchIndex = -1;
            const searchInput = document.querySelector('.v2-email-search-input');
            const q = searchInput ? searchInput.value.trim().toLowerCase() : '';
            if (q) this._searchHighlight(q);
        } catch (err) {
            console.error('Failed to refresh email panel:', err);
        }
    }

    // =========================================================================
    // Template Loading & Selection
    // =========================================================================

    async _loadTemplates() {
        const wrapper = document.getElementById('v2-template-select');
        const menu = document.getElementById('v2-template-select-menu');
        if (!wrapper || !menu) return;
        if (menu.children.length > 0) return; // Already loaded

        try {
            const response = await fetch('/api/email/templates/', {
                headers: {
                    'X-CSRFToken': this._getCSRFToken(),
                }
            });
            const data = await response.json();

            // Clear and rebuild
            menu.innerHTML = '';

            if (data.grouped) {
                data.grouped.forEach(group => {
                    // Category header
                    const groupLabel = document.createElement('div');
                    groupLabel.className = 'v2-template-select-group-label';
                    groupLabel.textContent = group.category_display;
                    menu.appendChild(groupLabel);

                    group.templates.forEach(t => {
                        const option = document.createElement('div');
                        option.className = 'v2-template-select-option';
                        option.dataset.value = t.id;
                        option.dataset.subject = t.subject;
                        option.dataset.body = t.body;
                        option.dataset.variables = JSON.stringify(t.variables || []);
                        option.textContent = t.name;

                        option.addEventListener('click', (e) => {
                            e.stopPropagation();
                            // Update selected state
                            menu.querySelectorAll('.v2-template-select-option').forEach(o => o.classList.remove('selected'));
                            option.classList.add('selected');
                            // Update trigger text
                            const valueSpan = wrapper.querySelector('.v2-template-select-value');
                            if (valueSpan) valueSpan.textContent = t.name;
                            wrapper.dataset.value = t.id;
                            wrapper.classList.remove('open');
                            // Fire template selection
                            this._onTemplateSelect(t.id);
                        });

                        menu.appendChild(option);
                    });
                });
            }

            this.templates = data.templates || [];
        } catch (err) {
            console.error('Failed to load email templates:', err);
        }
    }

    _onTemplateSelect(templateId) {
        if (!templateId) return;

        const menu = document.getElementById('v2-template-select-menu');
        const option = menu ? menu.querySelector(`.v2-template-select-option[data-value="${templateId}"]`) : null;
        if (!option) return;

        let subject = option.dataset.subject || '';
        let body = option.dataset.body || '';

        // Auto-populate variables from event data
        const vars = this._getVariableValues();
        subject = this._replaceVariables(subject, vars);
        body = this._replaceVariables(body, vars);

        // Set subject
        const subjectInput = document.getElementById('v2-composer-subject');
        if (subjectInput) subjectInput.value = subject;

        // Set body with unfilled variable highlighting. Templates may be rich
        // HTML (from the template editor) or legacy plain text.
        const bodyEl = document.getElementById('v2-composer-body');
        if (bodyEl) {
            const looksHtml = /<[a-z][\s\S]*>/i.test(body);
            let html = looksHtml
                ? body
                : body.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
            html = html.replace(/\{[^{}]+\}/g, '<span class="v2-template-var-unfilled">$&</span>');
            bodyEl.innerHTML = html;
        }

        this._checkUnfilledVars();
    }

    // =========================================================================
    // Variable Handling
    // =========================================================================

    _getVariableValues() {
        const vars = {};

        // Only register a variable when its source value is non-empty. Variables
        // whose event field is blank are intentionally left out so they remain
        // visible as unfilled {placeholders} (and get flagged).
        const fieldVal = (id) => {
            const el = document.getElementById(id);
            return el && el.value ? el.value.trim() : '';
        };
        const add = (key, value) => { if (value) vars[key] = value; };

        add('event_title', fieldVal('v2-title'));

        const startDate = fieldVal('v2-start-date');
        if (startDate) add('event_date', this._formatDate(startDate));
        const endDate = fieldVal('v2-end-date');
        if (endDate) add('event_end_date', this._formatDate(endDate));

        add('event_time', this._formatTime(fieldVal('v2-start-time')));
        add('event_end_time', this._formatTime(fieldVal('v2-end-time')));

        add('event_location', fieldVal('v2-location'));
        add('event_description', fieldVal('v2-description'));
        add('organization', fieldVal('v2-organization') || fieldVal('v2-tab-organization'));
        add('contact_name', fieldVal('v2-point-of-contact'));
        add('contact_email', fieldVal('v2-contact-email'));
        add('contact_phone', fieldVal('v2-contact-phone'));

        // Status: use the visible label from the custom dropdown
        const statusText = document.querySelector('#v2-status .v2-status-text');
        add('event_status', statusText ? statusText.textContent.trim() : '');

        // From email data
        add('sender_name', this.emailData.sender_name || this.emailData.sender);

        // From user context (set by modal init)
        add('staffer_name', this.eventData.staffer_name);
        add('member_name', this.eventData.member_name);
        add('sender_title', this.eventData.staffer_title);

        return vars;
    }

    _formatDate(value) {
        const d = new Date(value + 'T00:00:00');
        return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    }

    _formatTime(value) {
        if (!value) return '';
        const [h, m] = value.split(':');
        const hour = parseInt(h, 10);
        const ampm = hour >= 12 ? 'PM' : 'AM';
        const displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
        return `${displayHour}:${m} ${ampm}`;
    }

    _replaceVariables(text, vars) {
        return text.replace(/\{(\w+)\}/g, (match, varName) => {
            return vars[varName] !== undefined ? vars[varName] : match;
        });
    }

    _highlightUnfilledVars(text) {
        // Convert plain text to HTML-safe, then highlight any unfilled
        // {placeholders} — both {word} tokens and the custom { PLACEHOLDER }.
        const escaped = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n/g, '<br>');

        return escaped.replace(
            /\{[^{}]+\}/g,
            '<span class="v2-template-var-unfilled">$&</span>'
        );
    }

    _checkUnfilledVars() {
        const bodyEl = document.getElementById('v2-composer-body');
        const warning = document.getElementById('v2-composer-var-warning');
        if (!bodyEl || !warning) return;

        const hasUnfilled = bodyEl.querySelector('.v2-template-var-unfilled') !== null;
        warning.style.display = hasUnfilled ? 'flex' : 'none';
    }

    // =========================================================================
    // Draft Prompt Popup
    // =========================================================================

    _openDraftPrompt() {
        const overlay = document.getElementById('v2-draft-prompt-overlay');
        const input = document.getElementById('v2-draft-prompt-input');
        if (overlay) overlay.style.display = 'flex';
        if (input) {
            input.value = '';
            input.focus();
        }
    }

    _closeDraftPrompt() {
        const overlay = document.getElementById('v2-draft-prompt-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    // =========================================================================
    // AI Draft Generation
    // =========================================================================

    async _suggestDraft(refinement, userPrompt) {
        if (this.sessionCount >= this.maxRegenerations) {
            console.warn('Draft regeneration limit reached');
            return;
        }

        // If composer has content and not a refinement, confirm replacement
        const bodyEl = document.getElementById('v2-composer-body');
        if (bodyEl && bodyEl.textContent.trim() && !refinement) {
            if (!confirm('Replace current draft with AI suggestion?')) return;
        }

        const loading = document.getElementById('v2-composer-loading');
        const suggestBtn = document.getElementById('v2-ai-suggest-btn');
        if (loading) loading.style.display = 'flex';
        if (suggestBtn) suggestBtn.disabled = true;

        // The email this draft is a reply to (the active thread's target).
        const emailId = this._getActiveReplyEmailId();
        const eventForm = document.getElementById('v2-event-form');
        const eventId = eventForm ? eventForm.dataset.eventId : null;

        const templateSelect = document.getElementById('v2-template-select');
        const templateId = templateSelect ? (templateSelect.dataset.value || null) : null;

        try {
            const response = await fetch('/api/email/generate-draft/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCSRFToken(),
                },
                body: JSON.stringify({
                    email_id: emailId,
                    event_id: eventId !== 'new' ? eventId : null,
                    template_id: templateId || null,
                    refinement: refinement || null,
                    user_prompt: userPrompt || null,
                    previous_draft: refinement ? this.currentDraft : null,
                    session_count: this.sessionCount,
                    stream: true,
                }),
            });

            if (response.headers.get('Content-Type')?.includes('text/event-stream')) {
                // SSE streaming
                if (bodyEl) bodyEl.innerHTML = '';
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.text && bodyEl) {
                                    bodyEl.innerHTML += data.text
                                        .replace(/&/g, '&amp;')
                                        .replace(/</g, '&lt;')
                                        .replace(/>/g, '&gt;')
                                        .replace(/\n/g, '<br>');
                                }
                                if (data.done) break;
                                if (data.error) {
                                    console.error('Draft generation error:', data.error);
                                    if (bodyEl) bodyEl.innerHTML += `<br><em style="color: var(--v2-important);">${data.error}</em>`;
                                }
                            } catch (e) {
                                // Skip malformed JSON
                            }
                        }
                    }
                }
            } else {
                // Non-streaming fallback
                const data = await response.json();
                if (data.draft_text && bodyEl) {
                    bodyEl.innerHTML = data.draft_text
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                        .replace(/\n/g, '<br>');
                }
                if (data.error) {
                    console.error('Draft generation error:', data.error);
                }
            }

            this.currentDraft = bodyEl ? bodyEl.textContent : '';
            this.sessionCount++;
            this._updateRefinementUI();

        } catch (err) {
            console.error('Failed to generate draft:', err);
        } finally {
            if (loading) loading.style.display = 'none';
            if (suggestBtn) suggestBtn.disabled = false;
        }
    }

    _updateRefinementUI() {
        const row = document.getElementById('v2-ai-refinement-row');
        const remaining = document.getElementById('v2-ai-remaining');

        if (row) row.style.display = 'flex';

        const left = this.maxRegenerations - this.sessionCount;
        if (remaining) remaining.textContent = `${left} remaining`;

        if (left <= 0) {
            document.querySelectorAll('.v2-refinement-chip').forEach(chip => {
                chip.disabled = true;
                chip.title = 'Draft limit reached for this session';
            });
            const suggestBtn = document.getElementById('v2-ai-suggest-btn');
            if (suggestBtn) suggestBtn.disabled = true;
        }
    }

    // =========================================================================
    // Send Response
    // =========================================================================

    /**
     * Entry point for the Send button. Validates content, then — if the draft
     * still contains unfilled {placeholders} — prompts a warning before sending.
     */
    _sendResponse() {
        const bodyEl = document.getElementById('v2-composer-body');
        if (!bodyEl || !bodyEl.textContent.trim()) {
            alert('Please write a response before sending.');
            return;
        }

        const unfilled = this._getUnfilledTokens();
        if (unfilled.length > 0) {
            this._showSendWarning(unfilled);
            return;
        }

        this._performSend();
    }

    _getUnfilledTokens() {
        const bodyEl = document.getElementById('v2-composer-body');
        const subjectEl = document.getElementById('v2-composer-subject');
        const text = (bodyEl ? bodyEl.textContent : '') + ' ' + (subjectEl ? subjectEl.value : '');
        const matches = text.match(/\{[^{}]+\}/g) || [];
        return [...new Set(matches.map(t => t.trim()))];
    }

    _showSendWarning(tokens) {
        const overlay = document.getElementById('v2-send-warning-overlay');
        const list = document.getElementById('v2-send-warning-list');
        if (list) {
            list.innerHTML = tokens
                .map(t => `<span class="v2-template-var-unfilled">${this._escapeHtml(t)}</span>`)
                .join('');
        }
        if (overlay) overlay.style.display = 'flex';
    }

    _closeSendWarning() {
        const overlay = document.getElementById('v2-send-warning-overlay');
        if (overlay) overlay.style.display = 'none';
    }

    async _performSend() {
        const bodyEl = document.getElementById('v2-composer-body');
        const subjectEl = document.getElementById('v2-composer-subject');
        const ccEl = document.getElementById('v2-composer-cc');
        const bccEl = document.getElementById('v2-composer-bcc');
        const sendBtn = document.getElementById('v2-composer-send');

        if (!bodyEl || !bodyEl.textContent.trim()) {
            alert('Please write a response before sending.');
            return;
        }

        if (sendBtn) sendBtn.disabled = true;

        const emailId = this._getActiveReplyEmailId();

        const templateSelect = document.getElementById('v2-template-select');

        try {
            const response = await fetch('/api/email/send-response/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCSRFToken(),
                },
                body: JSON.stringify({
                    email_id: emailId,
                    subject: subjectEl ? subjectEl.value : '',
                    body: bodyEl.innerHTML,
                    is_html: true,
                    template_id: templateSelect ? (templateSelect.dataset.value || null) : null,
                    cc_recipients: ccEl && ccEl.value ? ccEl.value.split(',').map(e => e.trim()) : [],
                    bcc_recipients: bccEl && bccEl.value ? bccEl.value.split(',').map(e => e.trim()) : [],
                }),
            });

            const data = await response.json();

            if (response.ok) {
                // Append sent response to thread
                this._appendSentResponse({
                    subject: subjectEl ? subjectEl.value : '',
                    body: bodyEl.innerHTML,
                    sent_at: new Date().toISOString(),
                    status: data.status || 'sent',
                });

                // Clear composer
                if (bodyEl) bodyEl.innerHTML = '';
                if (subjectEl) subjectEl.value = '';
                this._clearSavedDraft();

                // Hide composer
                this.hideComposer();

                // Update respond button to "Send Another"
                const respondBtn = document.getElementById('v2-email-respond-btn');
                if (respondBtn) {
                    respondBtn.innerHTML = `
                        <svg class="v2-action-btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M9 17l-5-5 5-5"></path>
                            <path d="M20 18v-2a4 4 0 0 0-4-4H4"></path>
                        </svg>
                        Send Another
                    `;
                }
            } else {
                alert(data.error || 'Failed to send response');
            }
        } catch (err) {
            console.error('Failed to send response:', err);
            alert('Failed to send response. Please try again.');
        } finally {
            if (sendBtn) sendBtn.disabled = false;
        }
    }

    // =========================================================================
    // Response History
    // =========================================================================

    async _loadResponseHistory() {
        const emailId = this._getActiveReplyEmailId();
        if (!emailId) return;

        try {
            const response = await fetch(`/api/email/${emailId}/responses/`, {
                headers: { 'X-CSRFToken': this._getCSRFToken() }
            });
            const data = await response.json();

            if (data.responses && data.responses.length > 0) {
                data.responses.forEach(resp => this._appendSentResponse(resp));
            }
        } catch (err) {
            console.error('Failed to load response history:', err);
        }
    }

    _appendSentResponse(resp) {
        const container = document.getElementById('v2-sent-responses-container');
        if (!container) return;

        const sentDate = resp.sent_at ? new Date(resp.sent_at).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'
        }) : 'Pending';

        const div = document.createElement('div');
        div.className = 'v2-email-item v2-email-sent';
        div.innerHTML = `
            <div class="v2-email-header">
                <span class="v2-email-from">
                    <span class="v2-sent-badge">Sent</span>
                    You
                </span>
                <span class="v2-email-date">${sentDate}</span>
            </div>
            <div class="v2-email-subject">${this._escapeHtml(resp.subject || '')}</div>
            <div class="v2-email-body">${resp.is_html ? resp.body : this._escapeHtml(resp.body || '')}</div>
        `;
        container.appendChild(div);
    }

    // =========================================================================
    // Draft Persistence (localStorage)
    // =========================================================================

    _saveDraft() {
        const bodyEl = document.getElementById('v2-composer-body');
        const subjectEl = document.getElementById('v2-composer-subject');
        const emailId = this._getActiveReplyEmailId();

        if (!emailId || !bodyEl) return;

        const draft = {
            subject: subjectEl ? subjectEl.value : '',
            body: bodyEl.innerHTML,
            savedAt: new Date().toISOString(),
        };

        try {
            localStorage.setItem(`hilldesk_draft_${emailId}`, JSON.stringify(draft));
            console.log('Draft saved to localStorage');
            // Brief visual feedback
            const saveBtn = document.getElementById('v2-composer-save-draft');
            if (saveBtn) {
                const origText = saveBtn.textContent;
                saveBtn.textContent = 'Saved!';
                setTimeout(() => { saveBtn.textContent = origText; }, 1500);
            }
        } catch (e) {
            console.warn('Failed to save draft:', e);
        }
    }

    _restoreDraft() {
        const emailId = this._getActiveReplyEmailId();
        if (!emailId) return;

        try {
            const saved = localStorage.getItem(`hilldesk_draft_${emailId}`);
            if (saved) {
                const draft = JSON.parse(saved);
                const bodyEl = document.getElementById('v2-composer-body');
                const subjectEl = document.getElementById('v2-composer-subject');
                if (bodyEl && draft.body) bodyEl.innerHTML = draft.body;
                if (subjectEl && draft.subject) subjectEl.value = draft.subject;
            }
        } catch (e) {
            console.warn('Failed to restore draft:', e);
        }
    }

    _clearSavedDraft() {
        const emailId = this._getActiveReplyEmailId();
        if (emailId) {
            try { localStorage.removeItem(`hilldesk_draft_${emailId}`); } catch (e) { /* ignore */ }
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    _setRecipient() {
        const toEl = document.getElementById('v2-composer-to');
        if (!toEl) return;

        // When replying to a specific thread, use that thread's sender.
        if (this.activeReplySender) {
            toEl.value = this.activeReplySender;
            return;
        }

        // Otherwise fall back to the first email in the panel.
        const emailItem = document.querySelector('.v2-email-item:not(.v2-email-sent)');
        if (emailItem) {
            const fromEl = emailItem.querySelector('.v2-email-from');
            toEl.value = fromEl ? fromEl.textContent.trim() : (this.emailData.sender || '');
        } else {
            toEl.value = this.emailData.sender || '';
        }
    }

    _loadSignature() {
        const sigEl = document.getElementById('v2-composer-signature');
        if (sigEl) {
            const name = this.eventData.staffer_name || '';
            const title = this.eventData.staffer_title || '';
            if (name) {
                sigEl.innerHTML = `<div class="v2-signature-line">${this._escapeHtml(name)}</div>` +
                    (title ? `<div class="v2-signature-line">${this._escapeHtml(title)}</div>` : '');
                sigEl.style.display = 'block';
            } else {
                sigEl.style.display = 'none';
            }
        }
    }

    _getCSRFToken() {
        const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        if (cookie) return cookie.split('=')[1];
        const hidden = document.querySelector('[name=csrfmiddlewaretoken]');
        return hidden ? hidden.value : '';
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Global singleton
window.emailComposer = new EmailComposer();
