/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Event Editing Modal V2 - Redesigned Interface
 * Preserves all V1 functionality with updated UI interactions
 */

// =========================================================================
// Human Review Components
// =========================================================================

/**
 * ReviewableField - Wraps form fields with accept/reject functionality
 * Shows orange glow for pending fields, accept/reject popover on focus
 */
class ReviewableField {
    constructor(fieldId, fieldName, extractedData, modal) {
        this.fieldId = fieldId;
        this.fieldName = fieldName;
        this.extractedData = extractedData;
        this.modal = modal;
        this.element = document.getElementById(fieldId);
        this.actionsContainer = null;
        this.status = extractedData?.status || 'pending';
        // Store original value for comparison (to determine if user modified it)
        this.originalValue = extractedData?.value ?? '';

        if (this.element) {
            this.init();
        }
    }

    init() {
        // Add review wrapper (doesn't change layout - just adds relative positioning)
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'v2-review-field-wrapper';
        this.element.parentNode.insertBefore(this.wrapper, this.element);
        this.wrapper.appendChild(this.element);

        // Apply initial state
        this.updateVisualState();

        // Bind events
        this.bindEvents();
    }

    bindEvents() {
        // Auto-accept when clicking in the field and select all text
        this.element.addEventListener('click', (e) => {
            if (this.status === 'pending') {
                this.accept();
            }
            // Select all text on click
            this.selectAllText();
        });

        // Also auto-accept on focus (for keyboard navigation / Jump to Next) and select all text
        this.element.addEventListener('focus', () => {
            if (this.status === 'pending') {
                this.accept();
            }
            // Select all text on focus (small delay to ensure element is focused).
            // CRITICAL: guard with document.activeElement === this.element.
            // Rapid Jump-to-Next clicks queue one setTimeout per click; when
            // they fire, .select() on an *unfocused* input refocuses it
            // (Chrome/Firefox behavior), which made the cursor cycle through
            // every field the user just clicked past, in order. The guard
            // means only the field that's still actually focused runs .select().
            setTimeout(() => {
                if (document.activeElement === this.element) {
                    this.selectAllText();
                }
            }, 0);
            // Highlight email source if value matches original and email panel is visible
            this.highlightEmailSource();
        });

        // Clear highlight on blur (only if no other mapped field is focused)
        this.element.addEventListener('blur', () => {
            setTimeout(() => {
                // Don't clear if another field in the form is now focused
                if (!this.modal.isFieldFocused()) {
                    this.modal.clearEmailHighlights();
                }
            }, 150);
        });

        // Keyboard shortcuts
        this.element.addEventListener('keydown', (e) => {
            if (this.status !== 'pending') return;

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.accept();
            }
        });

        // Highlight email source when hovering on wrapper - ONLY for pending review fields
        this.wrapper.addEventListener('mouseenter', (e) => {
            if (this.status === 'pending') {
                this.highlightEmailSource();
            }
        });

        // Clear email highlights when leaving the wrapper (unless field is focused)
        this.wrapper.addEventListener('mouseleave', () => {
            // Don't clear if this field or another mapped field is focused
            if (!this.modal.isFieldFocused()) {
                this.modal.clearEmailHighlights();
            }
        });
    }

    /**
     * Select all text in the field element
     */
    selectAllText() {
        if (!this.element) return;

        // For input and textarea elements, use select()
        if (this.element.tagName === 'INPUT' || this.element.tagName === 'TEXTAREA') {
            this.element.select();
        }
        // For select dropdowns, we can't select text but the element is already focused
    }

    /**
     * Check if current field value matches the original extracted value
     */
    valueMatchesOriginal() {
        if (!this.element) return false;
        const currentValue = this.element.value?.trim() ?? '';
        const originalValue = String(this.originalValue ?? '').trim();
        return currentValue === originalValue;
    }

    /**
     * Check if highlighting should occur (email panel visible and value unchanged)
     */
    shouldHighlight() {
        // Must have valid indices
        if (this.extractedData?.start_index == null ||
            this.extractedData?.end_index == null) {
            return false;
        }
        // Email panel must be visible
        if (!this.modal.isEmailPanelVisible) {
            return false;
        }
        // Value must match original (user hasn't modified it)
        return this.valueMatchesOriginal();
    }

    highlightEmailSource() {
        // Only highlight if conditions are met
        if (this.shouldHighlight()) {
            this.modal.highlightEmailText({
                start_index: this.extractedData.start_index,
                end_index: this.extractedData.end_index,
                text_snippet: this.extractedData.text_snippet
            });
        }
    }

    updateVisualState() {
        // Remove all state classes
        this.wrapper.classList.remove('v2-review-pending', 'v2-review-accepted', 'v2-review-rejected');

        // Add current state class
        this.wrapper.classList.add(`v2-review-${this.status}`);

        // Update field editability
        if (this.status === 'rejected') {
            this.element.disabled = true;
            this.element.value = '';
        } else {
            this.element.disabled = false;
        }
    }

    async accept() {
        this.status = 'accepted';
        this.updateVisualState();

        // Update progress immediately (before API call)
        this.modal.updateReviewProgress();

        // Check if this will complete the review
        const willComplete = this.modal.isReviewComplete();

        // Call API FIRST - this saves the extracted_fields and requires_human_review
        await this.modal.handleFieldReview(this.fieldName, 'accept');

        // THEN update UI after API confirms save
        if (willComplete) {
            this.modal.completeReviewMode();
        }
    }

    async reject() {
        this.status = 'rejected';
        this.updateVisualState();

        // Update progress immediately (before API call)
        this.modal.updateReviewProgress();

        // Check if this will complete the review
        const willComplete = this.modal.isReviewComplete();

        // Call API FIRST - this saves the extracted_fields and requires_human_review
        await this.modal.handleFieldReview(this.fieldName, 'reject');

        // THEN update UI after API confirms save
        if (willComplete) {
            this.modal.completeReviewMode();
        }
    }

    async undoReject() {
        this.status = 'pending';

        // Restore original value
        if (this.extractedData?.value !== undefined) {
            this.element.value = this.extractedData.value;
        }

        this.updateVisualState();

        // Call API - this saves the extracted_fields and requires_human_review
        await this.modal.handleFieldReview(this.fieldName, 'undo_reject');
    }

    destroy() {
        if (this.wrapper && this.element) {
            this.wrapper.parentNode.insertBefore(this.element, this.wrapper);
            this.wrapper.remove();
        }
    }
}

/**
 * ReviewProgressBar - Shows review progress with Jump to Next button
 */
class ReviewProgressBar {
    constructor(modal) {
        this.modal = modal;
        this.element = null;
        this.totalFields = 0;
        this.reviewedFields = 0;

        this.init();
    }

    init() {
        // Remove any existing review bottom rows to prevent duplicates
        document.querySelectorAll('.v2-review-bottom-row').forEach(el => el.remove());

        // Create progress bar container
        this.element = document.createElement('div');
        this.element.className = 'v2-review-bottom-row';
        this.element.innerHTML = `
            <button type="button" class="v2-jump-next-btn">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="5 4 15 12 5 20 5 4"></polygon>
                    <line x1="19" y1="5" x2="19" y2="19"></line>
                </svg>
                Jump to Next
            </button>
            <div class="v2-review-progress-container">
                <div class="v2-progress-track">
                    <div class="v2-progress-fill" style="width: 0%"></div>
                </div>
                <span class="v2-progress-text">0 / 0 fields reviewed</span>
            </div>
            <div class="v2-review-warning">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                Human Review Required
            </div>
        `;

        // Insert before action bar
        const actionBar = document.querySelector('.v2-action-bar');
        if (actionBar) {
            actionBar.parentNode.insertBefore(this.element, actionBar);
        }

        // Bind jump button
        this.element.querySelector('.v2-jump-next-btn').addEventListener('click', () => {
            this.modal.jumpToNextUnreviewedField();
        });
    }

    update(reviewed, total) {
        this.reviewedFields = reviewed;
        this.totalFields = total;

        const percentage = total > 0 ? (reviewed / total) * 100 : 0;

        // Update progress bar
        const fill = this.element.querySelector('.v2-progress-fill');
        if (fill) {
            fill.style.width = `${percentage}%`;
        }

        // Update text
        const text = this.element.querySelector('.v2-progress-text');
        if (text) {
            text.textContent = `${reviewed} / ${total} fields reviewed`;
        }

        // Update jump button state
        const jumpBtn = this.element.querySelector('.v2-jump-next-btn');
        if (jumpBtn) {
            jumpBtn.disabled = reviewed >= total;
            if (reviewed >= total) {
                jumpBtn.textContent = 'Review Complete';
            }
        }

        // Update warning visibility
        const warning = this.element.querySelector('.v2-review-warning');
        if (warning) {
            warning.classList.toggle('hidden', reviewed >= total);
        }
    }

    destroy() {
        if (this.element) {
            this.element.remove();
        }
    }
}

/**
 * ReviewConfirmDialog - Confirmation dialog for incomplete review close
 */
class ReviewConfirmDialog {
    constructor(modal) {
        this.modal = modal;
        this.element = null;
        this.resolveCallback = null;

        this.init();
    }

    init() {
        this.element = document.createElement('div');
        this.element.className = 'v2-review-confirm-overlay';
        this.element.innerHTML = `
            <div class="v2-review-confirm-dialog">
                <button type="button" class="v2-review-confirm-close" title="Cancel">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
                <div class="v2-review-confirm-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="13" stroke-width="3"></line>
                        <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"></circle>
                    </svg>
                </div>
                <div class="v2-review-confirm-header">
                    <h3>Review Incomplete</h3>
                </div>
                <div class="v2-review-confirm-body">
                    <p>You haven't reviewed all AI-extracted fields yet.</p>
                    <p class="v2-review-confirm-stats"></p>
                </div>
                <div class="v2-review-confirm-actions">
                    <button type="button" class="v2-review-confirm-cancel">
                        Cancel
                    </button>
                    <button type="button" class="v2-review-confirm-later">
                        Save & Close
                    </button>
                    <button type="button" class="v2-review-confirm-discard">
                        Discard Event
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(this.element);

        // Bind buttons
        this.element.querySelector('.v2-review-confirm-discard').addEventListener('click', () => {
            this.resolve('discard');
        });

        this.element.querySelector('.v2-review-confirm-later').addEventListener('click', () => {
            this.resolve('later');
        });

        // Cancel button - stays in modal
        this.element.querySelector('.v2-review-confirm-cancel').addEventListener('click', () => {
            this.resolve('cancel');
        });

        // X close button - same as cancel
        this.element.querySelector('.v2-review-confirm-close').addEventListener('click', () => {
            this.resolve('cancel');
        });

        // Close on overlay click - cancel
        this.element.addEventListener('click', (e) => {
            if (e.target === this.element) {
                this.resolve('cancel');
            }
        });

        // Escape key - cancel
        this.escapeHandler = (e) => {
            if (e.key === 'Escape' && this.element.classList.contains('visible')) {
                this.resolve('cancel');
            }
        };
        document.addEventListener('keydown', this.escapeHandler);
    }

    show(reviewedCount, totalCount) {
        // Update stats
        const stats = this.element.querySelector('.v2-review-confirm-stats');
        if (stats) {
            stats.textContent = `${reviewedCount} of ${totalCount} fields reviewed.`;
        }

        this.element.classList.add('visible');

        return new Promise((resolve) => {
            this.resolveCallback = resolve;
        });
    }

    resolve(action) {
        this.element.classList.remove('visible');
        if (this.resolveCallback) {
            this.resolveCallback(action);
            this.resolveCallback = null;
        }
    }

    destroy() {
        document.removeEventListener('keydown', this.escapeHandler);
        if (this.element) {
            this.element.remove();
        }
    }
}

// =========================================================================
// Review-Locked Tooltip (singleton, portaled to <body>)
// =========================================================================

/**
 * Mounts a single tooltip <div> on <body> and wires document-level hover
 * delegation for any element carrying [data-review-locked-tooltip].
 *
 * Portaling to <body> + position:fixed is what lets the tooltip render on
 * top of the rest of the page instead of being clipped by the overflow
 * boundaries of the modal panels (.v2-panel-content, .v2-email-toolbar,
 * etc.). Safe to call multiple times — only the first call sets up.
 */
let _reviewLockedTooltipSetup = false;
function setupReviewLockedTooltip() {
    if (_reviewLockedTooltipSetup) return;
    _reviewLockedTooltipSetup = true;

    const tooltip = document.createElement('div');
    tooltip.className = 'v2-review-locked-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    document.body.appendChild(tooltip);

    let currentTarget = null;

    const position = (target) => {
        const rect = target.getBoundingClientRect();
        // Render first so we can measure
        tooltip.classList.add('visible');
        const tipRect = tooltip.getBoundingClientRect();
        // Center horizontally above the target, with an 8px gap for the caret
        const top = rect.top - tipRect.height - 8;
        const left = rect.left + rect.width / 2 - tipRect.width / 2;
        // Clamp inside viewport (4px margin)
        const clampedLeft = Math.max(4, Math.min(left, window.innerWidth - tipRect.width - 4));
        tooltip.style.top = `${Math.max(4, top)}px`;
        tooltip.style.left = `${clampedLeft}px`;
    };

    const show = (target) => {
        if (currentTarget === target) return;
        currentTarget = target;
        tooltip.textContent = target.getAttribute('data-review-locked-tooltip') || '';
        position(target);
    };

    const hide = () => {
        currentTarget = null;
        tooltip.classList.remove('visible');
    };

    // Delegated hover. mouseover/mouseout bubble (mouseenter/leave don't),
    // which lets us catch hover on any current or future locked element.
    document.addEventListener('mouseover', (e) => {
        const target = e.target.closest && e.target.closest('[data-review-locked-tooltip]');
        if (target) show(target);
    });

    document.addEventListener('mouseout', (e) => {
        if (!currentTarget) return;
        // Only hide when the pointer truly leaves the locked element
        // (not when crossing between its descendants).
        const related = e.relatedTarget;
        if (related && currentTarget.contains(related)) return;
        hide();
    });

    // If the locked element scrolls out from under the pointer, drop it.
    document.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
}

// =========================================================================
// Main Modal Class
// =========================================================================

class EventEditingModalV2 {
    constructor(options = {}) {
        this.options = {
            autoSaveDelay: 2000,
            ...options
        };

        // State
        this.autoSaveTimeout = null;
        this.lastSavedData = null;
        this.isSaving = false;
        this.isInitializing = true;  // Flag to prevent auto-save during init
        this.isEmailPanelVisible = false;
        this.activeTab = 'event-details';
        this.isTimeRangeMode = false;

        // Human Review state
        this.isReviewMode = false;
        this.reviewableFields = {};  // fieldName -> ReviewableField instance
        this.extractedFields = {};   // Raw extracted data from server
        this.progressBar = null;
        this.confirmDialog = null;

        // Bound methods for event listener cleanup
        this.boundHandlers = {};

        // Initialize
        this.init();
    }

    init() {
        console.log('EventEditingModalV2: Initializing...');

        this.cacheElements();
        this.bindOverlayEvents();
        this.initializeTabs();
        this.initializeTimeToggle();
        this.initializeRecurrence();
        this.initializeEmailToggle();
        this.initializeAutoSave();
        this.initializeFieldSync();
        this.initializeTags();
        this.initializeStaff();
        this.initializeTimeValidation();
        this.initializeStatusDropdown();
        this.initializeGenericDropdowns();
        this.initializeFieldFocusHighlighting();
        this.initializeMoreMenu();
        this.initializeApprovalRouting();
        this.initializeApprovalPopup();
        this.initializeAttachments();

        // Load approval routing data if we have an event ID
        // This is needed when modal is opened via openEventEditingModal()
        // which loads server-rendered HTML but doesn't call loadEventData().
        // The action bar (incl. the Review button) is already rendered with the
        // correct visibility server-side via can_user_approve, so it loads with
        // the rest of the modal; this fetch only reconciles dynamic changes.
        const eventId = this.form?.dataset?.eventId;
        if (eventId && eventId !== 'new') {
            this.loadApprovalRouting(eventId);
            this.fetchAndRenderOverlaps();
        }

        // Initial render of header meta (datetime / location / type · format)
        this.updateHeaderMeta();
        this.initializeHeaderMetaClick();

        // Size the panel-content to the tallest tab so switching tabs never
        // shrinks the modal and shorter tabs don't expose extra scrollable
        // empty space. Re-measure after a beat to catch async content
        // (approval routing, overlaps) finishing rendering.
        requestAnimationFrame(() => this.seedPanelMinHeightFromAllTabs());
        setTimeout(() => this.seedPanelMinHeightFromAllTabs(), 800);

        // Capture initial state after a short delay
        // Only then allow auto-save to prevent saving incomplete/empty data during init
        setTimeout(() => {
            this.lastSavedData = this.collectFormData();
            this.isInitializing = false;  // Now safe to auto-save
            console.log('EventEditingModalV2: Initial state captured, auto-save enabled');
        }, 500);

        console.log('EventEditingModalV2: Initialization complete');
    }

    // =========================================================================
    // Attachments
    // =========================================================================

    /**
     * Wire up the attachment sections (one per tab — Event Details and
     * Staff & Review). Both show the same list, so uploads/deletes refresh
     * every section. New (unsaved) events show a hint instead of controls,
     * since there's no event id to attach files to yet.
     */
    initializeAttachments() {
        this.attachmentSections = Array.from(document.querySelectorAll('[data-attachments-section]'));
        if (!this.attachmentSections.length) return;

        const eventId = this.form?.dataset?.eventId;
        this.attachmentsEventId = eventId;
        const isNew = !eventId || eventId === 'new';

        this.attachmentSections.forEach((section) => {
            const addBtn = section.querySelector('[data-attachment-add]');
            const uploadInput = section.querySelector('[data-attachment-upload]');
            const replaceInput = section.querySelector('[data-attachment-replace]');
            const list = section.querySelector('[data-attachment-list]');

            if (isNew) {
                if (list) list.innerHTML = '<div class="v2-attachment-empty-hint">Save the event to add attachments.</div>';
                return;
            }

            if (addBtn && uploadInput) {
                addBtn.hidden = false;
                addBtn.addEventListener('click', () => uploadInput.click());
                uploadInput.addEventListener('change', () => {
                    if (uploadInput.files && uploadInput.files[0]) {
                        this._uploadAttachment(uploadInput.files[0]);
                        uploadInput.value = '';
                    }
                });
            }

            if (replaceInput) {
                replaceInput.addEventListener('change', () => {
                    const attachmentId = replaceInput.dataset.attachmentId;
                    if (attachmentId && replaceInput.files && replaceInput.files[0]) {
                        this._replaceAttachment(attachmentId, replaceInput.files[0]);
                        replaceInput.value = '';
                    }
                });
            }

            if (list) {
                list.addEventListener('click', (e) => {
                    const replaceTrigger = e.target.closest('[data-att-replace]');
                    const deleteTrigger = e.target.closest('[data-att-delete]');
                    if (replaceTrigger || deleteTrigger) this._hideFloatingTooltip();
                    if (replaceTrigger && replaceInput) {
                        replaceInput.dataset.attachmentId = replaceTrigger.getAttribute('data-att-replace');
                        replaceInput.click();
                    } else if (deleteTrigger) {
                        const name = deleteTrigger.getAttribute('data-att-name') || 'this file';
                        const attachmentId = deleteTrigger.getAttribute('data-att-delete');
                        // App-styled confirm (same popup as "Remove routing").
                        this._confirmAction(
                            'Delete attachment',
                            `This permanently removes "${name}" and all its versions.`,
                            'Delete',
                            () => this._deleteAttachment(attachmentId)
                        );
                    }
                });

                // App-styled tooltips for the per-file replace/delete buttons,
                // portaled to <body> on the top layer (see _showFloatingTooltip).
                // Delegated on the stable list element so it survives re-renders.
                list.addEventListener('mouseover', (e) => {
                    const btn = e.target.closest('[data-tooltip]');
                    if (btn && !btn.contains(e.relatedTarget)) {
                        this._showFloatingTooltip(btn, btn.getAttribute('data-tooltip'));
                    }
                });
                list.addEventListener('mouseout', (e) => {
                    const btn = e.target.closest('[data-tooltip]');
                    if (btn && !btn.contains(e.relatedTarget)) {
                        this._hideFloatingTooltip();
                    }
                });
            }
        });

        if (!isNew) this._loadAttachments();
    }

    _attachmentCsrf() {
        // Reuse the modal's shared CSRF helper (form input → meta → cookie).
        return this.getCsrfToken();
    }

    /**
     * Turn a failed Response into a user-facing message. DRF reports errors
     * under `detail` (auth/CSRF/throttle) or our views' `error`; non-JSON
     * responses (e.g. a 500 HTML page) fall back to the status code.
     */
    async _attachmentError(resp, fallback) {
        try {
            const data = await resp.json();
            return data.error || data.detail || fallback;
        } catch (e) {
            return `${fallback} (HTTP ${resp.status})`;
        }
    }

    async _loadAttachments() {
        if (!this.attachmentsEventId) return;
        try {
            const resp = await fetch(`/api/events/${this.attachmentsEventId}/attachments/`, {
                headers: { 'Accept': 'application/json', 'X-CSRFToken': this._attachmentCsrf() },
                credentials: 'same-origin',
            });
            if (!resp.ok) return;
            const data = await resp.json();
            this._renderAttachments(data.attachments || []);
        } catch (e) {
            console.error('Failed to load attachments:', e);
        }
    }

    _renderAttachments(attachments) {
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

            rows += `<div class="v2-attachment-row">
                <svg class="v2-attachment-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>
                <div class="v2-attachment-info">
                    ${nameHtml}
                    <span class="v2-attachment-meta">${[sizeText, escapeHtml(att.created_by_name)].filter(Boolean).join(' · ')}</span>
                </div>
                ${versionNote}
                ${badge}
                <div class="v2-attachment-controls">
                    <button type="button" class="v2-attachment-icon-btn" data-att-replace="${att.id}" data-tooltip="Upload new version">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    </button>
                    <button type="button" class="v2-attachment-icon-btn v2-attachment-icon-btn--danger" data-att-delete="${att.id}" data-att-name="${escapeHtml(att.original_filename)}" data-tooltip="Delete">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                </div>
            </div>`;
        });

        const html = rows || '<div class="v2-attachment-empty-hint">No files attached.</div>';
        // Both tabs share the same list — update every section.
        (this.attachmentSections || []).forEach((section) => {
            const list = section.querySelector('[data-attachment-list]');
            if (list) list.innerHTML = html;
        });
    }

    async _uploadAttachment(file) {
        await this._sendAttachment(
            `/api/events/${this.attachmentsEventId}/attachments/`, file, 'Upload failed.'
        );
    }

    async _replaceAttachment(attachmentId, file) {
        await this._sendAttachment(
            `/api/events/${this.attachmentsEventId}/attachments/${attachmentId}/replace/`, file, 'Replace failed.'
        );
    }

    async _sendAttachment(url, file, errLabel) {
        const form = new FormData();
        form.append('file', file);
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': this._attachmentCsrf() },
                credentials: 'same-origin',
                body: form,
            });
            if (!resp.ok) {
                alert(await this._attachmentError(resp, errLabel));
                return;
            }
            await this._loadAttachments();
        } catch (e) {
            console.error(errLabel, e);
            alert(errLabel);
        }
    }

    async _deleteAttachment(attachmentId) {
        try {
            const resp = await fetch(`/api/events/${this.attachmentsEventId}/attachments/${attachmentId}/`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this._attachmentCsrf() },
                credentials: 'same-origin',
            });
            if (!resp.ok) {
                alert(await this._attachmentError(resp, 'Delete failed.'));
                return;
            }
            await this._loadAttachments();
        } catch (e) {
            console.error('Delete failed.', e);
            alert('Delete failed.');
        }
    }

    cacheElements() {
        // Modal elements
        this.overlay = document.getElementById('v2-modal-overlay');
        this.container = document.getElementById('v2-modal-container');
        this.form = document.getElementById('v2-event-form');
        this.closeBtn = document.getElementById('v2-close-btn');

        // Time elements
        this.singleEventBtn = document.getElementById('v2-single-event-btn');
        this.timeRangeBtn = document.getElementById('v2-time-range-btn');
        this.startDateInput = document.getElementById('v2-start-date');
        this.startTimeInput = document.getElementById('v2-start-time');
        this.endDateInput = document.getElementById('v2-end-date');
        this.endTimeInput = document.getElementById('v2-end-time');
        this.longerThanDayCheckbox = document.getElementById('v2-longer-than-day');
        this.longerDayWrapper = document.getElementById('v2-longer-day-wrapper');
        this.repeatsCheckbox = document.getElementById('v2-repeats');
        this.repeatsRow = document.getElementById('v2-repeats-row');
        this.recurrenceSection = document.getElementById('v2-recurrence-section');
        this.recurrenceConfirmBtn = document.getElementById('v2-recurrence-confirm');
        this.recurrenceSummary = document.getElementById('v2-recurrence-summary');
        this.singleEventTimes = document.getElementById('v2-single-event-times');
        this.timeRangeDetails = document.getElementById('v2-time-range-details');
        this.timeRangeText = document.getElementById('v2-time-range-text');
        this.startLabel = document.getElementById('v2-start-label');
        this.endLabel = document.getElementById('v2-end-label');

        // Tab elements
        this.tabButtons = document.querySelectorAll('.v2-tab');
        this.tabPanels = document.querySelectorAll('.v2-tab-panel');

        // Action elements
        this.showEmailBtn = document.getElementById('v2-show-email-btn');
        // Status dropdown elements are cached in initializeStatusDropdown()

        // Tags
        this.tagsContainer = document.getElementById('v2-tags-container');
        this.tagInput = document.getElementById('v2-tag-input');
        this.tagAddBtn = document.getElementById('v2-tag-add-btn');

        // Staff
        this.staffContainer = document.getElementById('v2-staff-container');
        this.addStaffBtn = document.getElementById('v2-add-staff-btn');
        this.wireStaffStars();

        // More menu
        this.moreMenu = document.getElementById('v2-more-menu');
        this.moreBtn = document.getElementById('v2-more-btn');
        this.moreDropdown = document.getElementById('v2-more-dropdown');
        this.deleteBtn = document.getElementById('v2-delete-btn');
        this.printBtn = document.getElementById('v2-print-btn');

        // Review button in action bar
        this.reviewBtnWrapper = document.getElementById('v2-review-btn-wrapper');
        this.reviewBtn = document.getElementById('v2-review-btn');
        this.reviewBtnText = document.getElementById('v2-review-btn-text');

        // Approval popup
        this.approvalPopupOverlay = document.getElementById('v2-approval-popup-overlay');
        this.approvalPopup = document.getElementById('v2-approval-popup');
        this.approvalPopupClose = document.getElementById('v2-approval-popup-close');
        this.approvalPopupTitle = document.getElementById('v2-approval-popup-title');
        this.approvalNotes = document.getElementById('v2-approval-notes');
        this.approvalPopupCancel = document.getElementById('v2-approval-popup-cancel');
        this.approvalPopupSendBack = document.getElementById('v2-approval-popup-send-back');
        this.approvalPopupApprove = document.getElementById('v2-approval-popup-approve');
        this.approvalPopupCancelSection = document.getElementById('v2-approval-popup-cancel-section');
        this.approvalPopupCancelReview = document.getElementById('v2-approval-popup-cancel-review');
    }

    // =========================================================================
    // Modal Open/Close
    // =========================================================================

    bindOverlayEvents() {
        // Close button - MUST show review dialog if review is incomplete
        this.closeBtn?.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            await this.handleCloseRequest();
        });

        // Overlay click (outside modal) - also must check review mode
        this.overlay?.addEventListener('click', async (e) => {
            if (e.target === this.overlay) {
                e.preventDefault();
                await this.handleCloseRequest();
            }
        });

        // Escape key — single authority for the modal. Closes the topmost open
        // popup first; only closes the modal itself when no popup is open.
        //
        // The modal is re-instantiated on every open (see openEventEditingModal),
        // and each instance would otherwise register its own document-level
        // keydown listener that is never removed. Stale listeners accumulate, and
        // because they all resolve the same DOM nodes by id, pressing Escape with
        // a nested popup open caused the *first* listener to close the popup and a
        // *second* stale listener to then fall through and close the whole modal.
        // Keep exactly one live handler: remove any previously-attached one first.
        if (EventEditingModalV2._escapeKeyHandler) {
            document.removeEventListener('keydown', EventEditingModalV2._escapeKeyHandler);
        }
        const escapeKeyHandler = async (e) => {
            if (e.key !== 'Escape' || !this.overlay?.classList.contains('active')) return;

            // 0. An open status / generic dropdown closes first (never the modal).
            const escDropdown = this._openDropdownContext();
            if (escDropdown) {
                e.preventDefault();
                escDropdown.close();
                escDropdown.trigger?.focus();
                return;
            }

            // 1. Remove-routing confirm dialog (portaled to <body>)
            const routingConfirm = document.getElementById('v2-routing-confirm-overlay');
            if (routingConfirm && getComputedStyle(routingConfirm).display !== 'none') {
                e.preventDefault();
                this._closeRoutingConfirm();
                return;
            }

            // 2. Review confirm dialog (dismissed by its own handler)
            if (document.querySelector('.v2-review-confirm-overlay.visible')) {
                return;
            }

            // 3. Email-panel popups (confirm / draft / send-warning / attach picker)
            if (window.emailComposer && window.emailComposer.closeAnyOpenPopup()) {
                e.preventDefault();
                return;
            }

            // 4. Approval review popup
            if (this.approvalPopupOverlay?.classList.contains('visible')) {
                e.preventDefault();
                this.hideApprovalPopup();
                return;
            }

            // 5. Routing builder popup
            if (this.routingPopupOverlay?.classList.contains('visible')) {
                e.preventDefault();
                this.closeRoutingBuilder();
                return;
            }

            // 5b. Contacts / organizations edit popup (portaled to <body>)
            if (window.EventContactsPanel && window.EventContactsPanel.isPopupOpen &&
                window.EventContactsPanel.isPopupOpen()) {
                e.preventDefault();
                window.EventContactsPanel.closePopup();
                return;
            }

            // 6. A field is focused → first Escape just deselects it, returning
            //    focus to the active tab. Only a subsequent Escape (with nothing
            //    selected) closes the modal.
            const ae = document.activeElement;
            const escContainer = this.container || document.getElementById('v2-modal-container');
            const isField = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' ||
                ae.tagName === 'SELECT' || ae.isContentEditable);
            if (isField && escContainer && escContainer.contains(ae)) {
                e.preventDefault();
                ae.blur();
                escContainer.querySelector('.v2-tab.active')?.focus();
                return;
            }

            // 7. Nothing open → close the modal
            e.preventDefault();
            await this.handleCloseRequest();
        };
        EventEditingModalV2._escapeKeyHandler = escapeKeyHandler;
        document.addEventListener('keydown', escapeKeyHandler);

        // Focus trap — keep Tab cycling within the modal so it never reaches the
        // page content behind the overlay or the browser chrome (address bar,
        // back button). Same single-live-handler discipline as the Escape
        // handler above: remove any previously-attached one first.
        if (EventEditingModalV2._focusTrapHandler) {
            document.removeEventListener('keydown', EventEditingModalV2._focusTrapHandler);
        }
        const focusTrapHandler = (e) => {
            if (!this.overlay?.classList.contains('active')) return;
            const container = this.container || document.getElementById('v2-modal-container');
            if (!container) return;

            // An open status / generic dropdown takes the keys first: arrows
            // navigate options, Enter/Space select, Tab closes + advances.
            const openDropdown = this._openDropdownContext();
            if (openDropdown &&
                ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Enter', ' ', 'Tab'].includes(e.key)) {
                this._handleOpenDropdownKeys(e, openDropdown);
                return;
            }

            // If a nested popup is open, Tab cycles WITHIN that popup — never the
            // modal content behind it. Other keys pass through (caret movement in
            // the popup's own fields, etc.).
            const popup = this._activePopupContainer();
            if (popup) {
                if (e.key === 'Tab') this._trapTabWithin(popup, e);
                return;
            }

            // Left/Right cycle the tabs when nothing field-like is selected
            // (focus on a tab, the modal shell, or nothing). After switching,
            // the roving tabindex makes the next Tab land in that tab's panel.
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                const ae = document.activeElement;
                // Only typeable fields (text inputs, selects, textareas,
                // contenteditable) keep the arrows for caret/value movement.
                // Any other focus — a tab, a non-typeable control (button,
                // checkbox…), the modal shell, or nothing — lets the arrows
                // switch tabs.
                if (this._isTypeableField(ae)) return;
                // Leave a nested popup's own controls alone.
                if (this.approvalPopupOverlay?.classList.contains('visible') ||
                    this.routingPopupOverlay?.classList.contains('visible')) return;

                const tabs = Array.from(this.tabButtons || [])
                    .filter(t => !t.classList.contains('v2-tab-disabled'));
                if (tabs.length === 0) return;

                const activeId = `v2-${this.activeTab}-tab`;
                let idx = tabs.findIndex(t => t.id === activeId);
                if (idx === -1) idx = 0;
                const dir = e.key === 'ArrowRight' ? 1 : -1;
                const nextTab = tabs[(idx + dir + tabs.length) % tabs.length];

                e.preventDefault();
                this.switchTab?.(nextTab.id);
                nextTab.focus();
                return;
            }

            if (e.key !== 'Tab') return;

            // In human-review mode, Tab acts like the "Jump to Next" button:
            // advance to the next field still needing review instead of cycling
            // every focusable control.
            if (this.isReviewMode) {
                e.preventDefault();
                this.jumpToNextUnreviewedField();
                return;
            }

            const focusables = this._getFocusableElements(container);
            if (focusables.length === 0) {
                e.preventDefault();
                return;
            }
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            const active = document.activeElement;
            if (!container.contains(active)) {
                // Focus drifted outside the modal — pull it back in.
                e.preventDefault();
                (e.shiftKey ? last : first).focus();
            } else if (e.shiftKey && active === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && active === last) {
                e.preventDefault();
                first.focus();
            }
        };
        EventEditingModalV2._focusTrapHandler = focusTrapHandler;
        document.addEventListener('keydown', focusTrapHandler);
    }

    /**
     * Visible, tabbable elements inside the modal, in DOM order. Hidden tab
     * panels (display:none) and disabled controls are excluded, so Tab only
     * cycles through the fields the user can actually see.
     */
    /**
     * True for fields where Left/Right arrows have a native meaning (moving the
     * caret or changing the value): text-like inputs, number/date/range, select,
     * textarea, and contenteditable. Non-typeable controls (buttons, checkboxes,
     * radios) return false so the arrows can switch tabs instead.
     */
    _isTypeableField(el) {
        if (!el) return false;
        if (el.isContentEditable) return true;
        const tag = el.tagName;
        if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if (tag === 'INPUT') {
            const nonTypeable = ['checkbox', 'radio', 'button', 'submit', 'reset', 'file', 'color', 'image'];
            return !nonTypeable.includes((el.type || 'text').toLowerCase());
        }
        return false;
    }

    _getFocusableElements(container) {
        const selector = [
            'a[href]',
            'button:not([disabled])',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])'
        ].join(',');
        return Array.from(container.querySelectorAll(selector)).filter(el =>
            (el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement) &&
            el.getAttribute('aria-hidden') !== 'true' &&
            el.getAttribute('tabindex') !== '-1'
        );
    }

    /**
     * The innermost open nested popup whose focus should be trapped (review/
     * routing confirm dialogs, the approval popup, the routing builder), or null
     * when none is open.
     */
    _activePopupContainer() {
        const routingConfirm = document.getElementById('v2-routing-confirm-overlay');
        if (routingConfirm && getComputedStyle(routingConfirm).display !== 'none') return routingConfirm;
        const reviewConfirm = document.querySelector('.v2-review-confirm-overlay.visible');
        if (reviewConfirm) return reviewConfirm;
        if (this.approvalPopupOverlay?.classList.contains('visible')) return this.approvalPopupOverlay;
        if (this.routingPopupOverlay?.classList.contains('visible')) return this.routingPopupOverlay;
        return null;
    }

    /**
     * Fully trap Tab/Shift+Tab within `container`: cycle its focusables and pull
     * focus back in if it has drifted out. Always consumes the Tab.
     */
    _trapTabWithin(container, e) {
        const focusables = this._getFocusableElements(container);
        e.preventDefault();
        if (focusables.length === 0) return;
        const active = document.activeElement;
        const idx = focusables.indexOf(active);
        if (idx === -1) {
            focusables[e.shiftKey ? focusables.length - 1 : 0].focus();
            return;
        }
        focusables[(idx + (e.shiftKey ? -1 : 1) + focusables.length) % focusables.length].focus();
    }

    /**
     * If a status / generic dropdown is open, return its { options, trigger,
     * close } so the keyboard handler can drive it; otherwise null.
     */
    _openDropdownContext() {
        if (this.statusWrapper?.classList.contains('open') && this.statusMenu) {
            return {
                options: Array.from(this.statusMenu.querySelectorAll('.v2-status-dropdown-option')),
                trigger: this.statusTrigger,
                close: () => this.closeStatusDropdown()
            };
        }
        const g = (this.genericDropdowns || []).find(d => d.wrapper.classList.contains('open'));
        if (g) {
            return {
                options: Array.from(g.menu.querySelectorAll('.v2-dropdown-option')),
                trigger: g.trigger,
                close: () => this.closeGenericDropdown(g.wrapper, g.menu)
            };
        }
        if (this.staffDropdownVisible && this.activeStaffDropdown) {
            return {
                options: Array.from(this.activeStaffDropdown.querySelectorAll('.v2-staff-dropdown-item:not(.disabled)')),
                trigger: this.activeStaffDropdownSource === 'staff-review' ? this.reviewAddStaffBtn : this.addStaffBtn,
                close: () => this.hideStaffDropdown()
            };
        }
        return null;
    }

    /**
     * Keyboard handling for an open in-modal dropdown — mirrors the page
     * dropdowns: arrows move the highlight, Enter/Space pick it, and Tab /
     * Shift+Tab close the menu unchanged and move to the next / previous
     * focusable control in the modal.
     */
    _handleOpenDropdownKeys(event, ctx) {
        const { options, trigger, close } = ctx;
        if (options.length === 0) return;

        const highlight = (i) => {
            options.forEach((o, j) => o.classList.toggle('kb-active', j === i));
            options[i]?.scrollIntoView({ block: 'nearest' });
        };
        let idx = options.findIndex(o => o.classList.contains('kb-active'));
        if (idx === -1) idx = options.findIndex(o => o.classList.contains('selected'));

        switch (event.key) {
            case 'ArrowDown':
            case 'ArrowRight':
                event.preventDefault();
                highlight(idx < 0 ? 0 : (idx + 1) % options.length);
                break;
            case 'ArrowUp':
            case 'ArrowLeft':
                event.preventDefault();
                highlight(idx < 0 ? options.length - 1 : (idx - 1 + options.length) % options.length);
                break;
            case 'Enter':
            case ' ':
                event.preventDefault();
                if (idx >= 0) {
                    options[idx].click(); // selects + closes the menu
                } else {
                    close();
                }
                trigger?.focus();
                break;
            case 'Tab':
                // Close unchanged, then advance. In human-review mode that means
                // jumping to the next field needing review; otherwise just move
                // to the next / previous focusable.
                event.preventDefault();
                close();
                trigger?.focus();
                if (this.isReviewMode) {
                    this.jumpToNextUnreviewedField();
                } else {
                    this._moveModalFocus(event.shiftKey ? -1 : 1);
                }
                break;
        }
    }

    /** Move focus to the next (1) / previous (-1) focusable in the modal. */
    _moveModalFocus(direction) {
        const container = this.container || document.getElementById('v2-modal-container');
        if (!container) return;
        const focusables = this._getFocusableElements(container);
        const idx = focusables.indexOf(document.activeElement);
        if (idx === -1) return;
        focusables[(idx + direction + focusables.length) % focusables.length]?.focus();
    }

    /**
     * Handle close request - always saves and closes (no confirmation dialogs)
     */
    async handleCloseRequest() {
        // Always save and close - no review confirmation popup
        await this.performModalClose();
    }

    openModal(eventId = null, options = {}) {
        console.log('EventEditingModalV2: Opening modal', eventId ? `for event ${eventId}` : 'for new event', options);

        // Track whether this session changes anything; if not, closing the modal
        // skips the (expensive, flicker-y) list refresh so keyboard users can
        // open → look → Escape → arrow to the next item smoothly.
        this._didMutate = false;

        if (this.form) {
            this.form.dataset.eventId = eventId || 'new';
        }

        // Track if this is a newly created event (for empty check on close)
        // Can be set explicitly via options or inferred
        this.isNewlyCreatedEvent = options.isNewEvent || false;
        if (options.isNewEvent) {
            this.newEventId = eventId;
        }

        if (eventId && eventId !== 'new') {
            this.loadEventData(eventId).then(() => {
                // Auto-focus title if requested (after data loads)
                if (options.autoFocusTitle && this.titleInput) {
                    setTimeout(() => {
                        this.titleInput.focus();
                        this.titleInput.select();
                    }, 100);
                }
            });
        } else {
            this.resetForm();
        }

        this.overlay?.classList.add('active');
        document.body.classList.add('modal-open');

        // Move focus into the modal (so it can't sit on the page behind the
        // overlay): the shell by default — nothing focused — or the Review
        // button for routing review events. See focusModalOnOpen().
        setTimeout(() => this.focusModalOnOpen(), 50);
    }

    /**
     * Create a new event via API and open the modal for editing
     * If the event is still empty when closed, it will be deleted
     */
    async createNewEvent() {
        console.log('EventEditingModalV2: Creating new event...');

        try {
            const csrfToken = this.getCsrfToken();

            // Create a minimal event with default values
            const newEventData = {
                title: '',
                status: 'received',
                type: 'meeting',
                format: 'in_person'
            };

            const response = await fetch('/api/events/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify(newEventData)
            });

            if (!response.ok) {
                const errorText = await response.text();
                console.error('EventEditingModalV2: Failed to create event', response.status, errorText);
                throw new Error(`Failed to create event: ${response.status}`);
            }

            const createdEvent = await response.json();
            console.log('EventEditingModalV2: Event created', createdEvent.id);

            // Mark this as a newly created event for empty check on close
            this.isNewlyCreatedEvent = true;
            this.newEventId = createdEvent.id;

            // Open the modal with the new event
            this.openModal(createdEvent.id);

        } catch (error) {
            console.error('EventEditingModalV2: Error creating event', error);
            // Show error message to user
            if (typeof showMessage === 'function') {
                showMessage('Failed to create event. Please try again.', 'error');
            }
        }
    }

    /**
     * Check if the event is essentially empty (no meaningful data entered)
     */
    isEventEmpty() {
        const data = this.collectFormData();

        // Check if any meaningful fields have been filled in
        // Note: Exclude start_date, start_time, end_time as these are set programmatically
        // when creating events from calendar click-to-create
        const meaningfulFields = [
            data.title,
            data.group,
            data.location,
            data.description,
            data.point_of_contact_name,
            data.point_of_contact_email,
            data.participants?.length > 0,
            data.staff?.length > 0
        ];

        // Event is empty if no meaningful fields have values
        return !meaningfulFields.some(field => {
            if (typeof field === 'string') return field.trim().length > 0;
            if (typeof field === 'boolean') return field;
            return false;
        });
    }

    /**
     * Actually close the modal - saves changes and cleans up all layers
     * Do not call directly - use handleCloseRequest() instead
     */
    async performModalClose() {
        // Prevent re-entrant close (both inner and outer handlers can fire)
        if (this._isClosing) return;
        this._isClosing = true;

        // Check for unsaved changes
        if (this.isSaving) {
            console.log('EventEditingModalV2: Waiting for save to complete...');
            await this.waitForSave();
        }

        // Check if this is a newly created event that's still empty - delete it
        if (this.isNewlyCreatedEvent && this.isEventEmpty()) {
            console.log('EventEditingModalV2: Newly created event is empty, deleting...');
            await this.discardEvent();
            // Reset the flag
            this.isNewlyCreatedEvent = false;
            this.newEventId = null;
            // Refresh calendar to remove the discarded event
            if (window.calendar) {
                window.calendar.fetchEvents().then(() => window.calendar.renderCurrentView());
            } else if (window.calendarRedesign) {
                window.calendarRedesign.fetchEvents().then(() => {
                    window.calendarRedesign.renderCurrentView();
                });
            }
        } else {
            // Normal close - save any changes
            // BUT skip if still initializing (data hasn't fully loaded)
            if (this.isInitializing) {
                console.log('EventEditingModalV2: Skipping close-save (still initializing)');
            } else {
                const currentData = this.collectFormData();
                const hasChanges = this.lastSavedData &&
                    JSON.stringify(currentData) !== JSON.stringify(this.lastSavedData);

                // Safety check: Don't save if title was cleared but had content before
                // This prevents accidentally wiping event data
                const titleCleared = this.lastSavedData?.title && !currentData.title;
                if (titleCleared) {
                    console.warn('EventEditingModalV2: Skipping close-save (title was cleared - possible data loss)');
                } else if (hasChanges) {
                    // Trigger final save
                    await this.performAutoSave();
                }
            }
        }

        // Reset the newly created flag
        this.isNewlyCreatedEvent = false;
        this.newEventId = null;

        // Clean up review mode
        this.cleanupReviewMode();

        this.overlay?.classList.remove('active');
        document.body.classList.remove('modal-open');

        // Clear auto-save timeout
        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
            this.autoSaveTimeout = null;
        }

        // Also clean up the outer AJAX container (used on calendar/schedule/inbox pages)
        const outerContainer = document.getElementById('event-editing-container');
        if (outerContainer && outerContainer.classList.contains('active')) {
            outerContainer.classList.remove('active');
            outerContainer.setAttribute('aria-hidden', 'true');
            outerContainer.innerHTML = '<div class="loading-indicator"><div class="spinner"></div><div>Loading event...</div></div>';
            document.body.style.overflow = '';
        }

        // Refresh the page list ONLY if something actually changed this session.
        // A pure view (open → look → close) leaves the list untouched, so
        // keyboard users can Escape and immediately arrow to the next item with
        // no reload/flicker.
        if (this._didMutate) {
            if (window.calendarRedesign) {
                window.calendarRedesign.fetchEvents().then(() => {
                    window.calendarRedesign.renderCurrentView();
                });
            } else if (window.calendar && typeof window.calendar.fetchEvents === 'function') {
                window.calendar.fetchEvents().then(() => {
                    if (typeof window.calendar.renderCurrentView === 'function') {
                        window.calendar.renderCurrentView();
                    }
                });
            } else if (window.scheduleRedesign) {
                window.scheduleRedesign.refresh();
            } else if (window.inboxRedesign) {
                window.inboxRedesign.refresh();
            } else if (typeof window.dashboardRefresh === 'function') {
                window.dashboardRefresh();
            }
        }

        this._isClosing = false;
        console.log('EventEditingModalV2: Modal closed');
    }

    /**
     * Discard event (delete from server)
     */
    async discardEvent() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        this._didMutate = true; // deletion → list must refresh on close
        try {
            const csrfToken = this.getCsrfToken();
            await fetch(`/api/events/${eventId}/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            console.log('EventEditingModalV2: Event discarded');
        } catch (error) {
            console.error('EventEditingModalV2: Failed to discard event', error);
        }
    }

    waitForSave() {
        return new Promise((resolve) => {
            const checkSaving = () => {
                if (!this.isSaving) {
                    resolve();
                } else {
                    setTimeout(checkSaving, 100);
                }
            };
            checkSaving();
        });
    }

    // =========================================================================
    // Tab Navigation
    // =========================================================================

    initializeTabs() {
        const tabMapping = {
            'v2-event-details-tab': 'v2-event-details-panel',
            'v2-involved-parties-tab': 'v2-involved-parties-panel',
            'v2-staff-review-tab': 'v2-staff-review-panel'
        };

        const switchTab = (tabId) => {
            const panelId = tabMapping[tabId];
            if (!panelId) return;

            // Deactivate all tabs and panels. Roving tabindex: only the active
            // tab stays in the Tab order, so Tab from it lands in the active
            // panel's first field rather than the next tab.
            this.tabButtons.forEach(tab => {
                tab.classList.remove('active');
                tab.setAttribute('aria-selected', 'false');
                tab.setAttribute('tabindex', '-1');
            });

            this.tabPanels.forEach(panel => {
                panel.classList.remove('active');
            });

            // Activate target tab and panel
            const targetTab = document.getElementById(tabId);
            const targetPanel = document.getElementById(panelId);

            if (targetTab) {
                targetTab.classList.add('active');
                targetTab.setAttribute('aria-selected', 'true');
                targetTab.setAttribute('tabindex', '0');
            }

            if (targetPanel) {
                targetPanel.classList.add('active');
            }

            this.activeTab = tabId.replace('v2-', '').replace('-tab', '');
            console.log('EventEditingModalV2: Switched to tab', this.activeTab);

            // Keep the modal stable: after the new tab renders, grow the
            // panel-content's min-height if the new tab is taller than what
            // we've seen so far. Never shrinks — so flipping back and forth
            // stays at the tallest tab and there's no extra scrollable space
            // when the active tab is shorter.
            this.growPanelMinHeight();
        };

        this.tabButtons.forEach(tab => {
            tab.addEventListener('click', (e) => {
                e.preventDefault();
                // Block clicks on tabs locked during review. CSS used to do this
                // via pointer-events: none, but that also blocked hover and
                // prevented the "Complete human review first" tooltip from
                // showing — hover is now allowed and clicks are guarded here.
                if (tab.classList.contains('v2-tab-disabled')) return;
                switchTab(tab.id);
            });

            // Keyboard support
            tab.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (tab.classList.contains('v2-tab-disabled')) return;
                    switchTab(tab.id);
                }
            });
        });

        // Expose for keyboard tab-cycling (Left/Right arrows).
        this.switchTab = switchTab;
        this.tabOrder = Object.keys(tabMapping);

        // Initialize first tab
        switchTab('v2-event-details-tab');
    }

    // =========================================================================
    // Time Toggle (Single Event / Time Range)
    // =========================================================================

    initializeTimeToggle() {
        const handleToggle = (isRange) => {
            console.log('EventEditingModalV2: handleToggle called with isRange:', isRange);
            this.isTimeRangeMode = isRange;

            // Update button states
            this.singleEventBtn?.classList.toggle('active', !isRange);
            this.timeRangeBtn?.classList.toggle('active', isRange);

            // Update labels based on mode
            if (this.startLabel) {
                this.startLabel.textContent = isRange ? 'Range Start' : 'Start Date';
            }
            if (this.endLabel) {
                this.endLabel.textContent = isRange ? 'Range End' : 'End Date';
            }

            // Show/hide Single Event time fields vs Time Range details
            if (this.singleEventTimes) {
                this.singleEventTimes.classList.toggle('hidden', isRange);
            }
            if (this.timeRangeDetails) {
                this.timeRangeDetails.classList.toggle('hidden', !isRange);
            }

            // Show/hide Longer than a day checkbox (only visible for Single Event)
            if (this.longerDayWrapper) {
                this.longerDayWrapper.classList.toggle('hidden', isRange);
            }
            // The Repeats section lives with that checkbox: hidden in Range mode.
            this._updateRecurrenceVisibility();

            // Update end date input based on mode and longer-than-day checkbox
            if (this.endDateInput) {
                if (isRange) {
                    // Time Range mode: end date is always enabled
                    this.endDateInput.disabled = false;
                    this.endDateInput.classList.remove('disabled');
                } else {
                    // Single Event mode: end date depends on "longer than a day"
                    const longerThanDay = this.longerThanDayCheckbox?.checked || false;
                    this.endDateInput.disabled = !longerThanDay;
                    this.endDateInput.classList.toggle('disabled', !longerThanDay);

                    if (!longerThanDay) {
                        // Copy start date to end date when single event without longer-than-day
                        this.endDateInput.value = this.startDateInput?.value || '';
                    }
                }
            }

            this.triggerAutoSave();
        };

        this.singleEventBtn?.addEventListener('click', () => handleToggle(false));
        this.timeRangeBtn?.addEventListener('click', () => handleToggle(true));

        // Longer than a day checkbox (enables end date in Single Event mode)
        this.longerThanDayCheckbox?.addEventListener('change', (e) => {
            // "Longer than a day" and "Repeats" are mutually exclusive.
            if (e.target.checked && this.repeatsCheckbox?.checked) {
                if (!this._setRepeats(false)) {
                    e.target.checked = false; // Repeats couldn't be turned off (locked/active)
                    return;
                }
            }
            if (!this.isTimeRangeMode && this.endDateInput) {
                this.endDateInput.disabled = !e.target.checked;
                this.endDateInput.classList.toggle('disabled', !e.target.checked);

                if (!e.target.checked) {
                    // Copy start date to end date when unchecked
                    this.endDateInput.value = this.startDateInput?.value || '';
                }
            }
            this.triggerAutoSave();
        });

        // Sync start date to end date when not longer than a day
        this.startDateInput?.addEventListener('change', () => {
            if (!this.isTimeRangeMode && !this.longerThanDayCheckbox?.checked) {
                if (this.endDateInput) {
                    this.endDateInput.value = this.startDateInput.value;
                }
            }
            // The earlier `input` event already triggered a header refresh,
            // but it ran before this sync — re-render so the header reflects
            // the just-updated end date.
            this.updateHeaderMeta();
            // Recurrence anchors on the start date (monthly labels, until min).
            this.recurrenceEditor?.refreshForStartDate();
            this._updateRecurrenceFooter();
        });

        // Initialize based on form data
        const isDateRange = this.form?.querySelector('[name="is_date_range"]')?.value === 'true';
        handleToggle(isDateRange);
    }

    // =========================================================================
    // Recurrence ("Repeats" checkbox + section under the time row)
    // =========================================================================
    //
    // Not part of autosave: a series is created/confirmed explicitly via
    // POST /api/events/<id>/series/ (which materializes occurrences), and a
    // pending one is discarded via DELETE. Locked while human review is
    // pending — like the email Respond button — and read-only once active.

    initializeRecurrence() {
        if (!this.repeatsCheckbox || !this.recurrenceSection) return;

        const ds = this.recurrenceSection.dataset;
        this._seriesState = ds.seriesId ? { id: ds.seriesId, active: ds.active === 'true' } : null;
        this._recurrenceLocked = this._reviewLocked ||
            document.getElementById('v2-modal-container')?.dataset.requiresReview === 'true';

        const editorRoot = document.getElementById('v2-recurrence-editor');
        if (window.RecurrenceEditor && editorRoot) {
            this.recurrenceEditor = new window.RecurrenceEditor(editorRoot, {
                seriesInfo: ds.seriesId ? { rrule: ds.rrule, until_date: ds.until, count: ds.count } : null,
                getStartDate: () => this.startDateInput?.value || '',
                onChange: () => this._updateRecurrenceFooter(),
            });
        }

        this.repeatsCheckbox.addEventListener('change', (e) => {
            const wanted = e.target.checked;
            e.target.checked = !wanted; // _setRepeats decides whether it flips
            this._setRepeats(wanted);
        });
        this.recurrenceConfirmBtn?.addEventListener('click', () => this._confirmRecurrence());

        this._applyRecurrenceLock();
        this._updateRecurrenceVisibility();
    }

    /** Turn Repeats on/off. Returns false when it can't change (locked/active). */
    _setRepeats(on) {
        if (!this.repeatsCheckbox) return true;
        if (on === this.repeatsCheckbox.checked) return true;
        if (this._recurrenceLocked || this._seriesState?.active) return false;

        this.repeatsCheckbox.checked = on;
        if (on && this.longerThanDayCheckbox?.checked) {
            // Mutually exclusive with "Longer than a day"; its change handler
            // re-syncs the end date and autosaves.
            this.longerThanDayCheckbox.checked = false;
            this.longerThanDayCheckbox.dispatchEvent(new Event('change'));
        }
        if (!on && this._seriesState && !this._seriesState.active) {
            this._discardPendingSeries();
        }
        this._updateRecurrenceVisibility();
        return true;
    }

    _updateRecurrenceVisibility() {
        if (!this.recurrenceSection) return;
        this.recurrenceSection.hidden = !this.repeatsCheckbox?.checked || this.isTimeRangeMode;
        this._updateRecurrenceFooter();
    }

    _updateRecurrenceFooter(message = null, isError = false) {
        const editor = this.recurrenceEditor;
        if (!editor || !this.recurrenceSummary) return;
        const active = !!this._seriesState?.active;

        this.recurrenceSummary.classList.toggle('is-error', isError);
        this.recurrenceSummary.textContent = message ||
            (active ? `Active series · ${editor.describe()}` : editor.describe());

        const btn = this.recurrenceConfirmBtn;
        if (btn) {
            btn.hidden = active;
            btn.textContent = this._seriesState ? 'Confirm series' : 'Create series';
            const blocked = this._recurrenceLocked || this._recurrenceSaving || !editor.endBound();
            btn.disabled = blocked;
            btn.classList.toggle('v2-btn-disabled', blocked);
        }
    }

    /** Gray out the Repeats option while review is pending (or once active). */
    _applyRecurrenceLock() {
        if (!this.repeatsCheckbox) return;
        const locked = !!this._recurrenceLocked;
        const active = !!this._seriesState?.active;

        this.repeatsCheckbox.disabled = locked || active;
        this.repeatsRow?.classList.toggle('is-disabled', locked || active);
        const tip = locked ? 'Complete human review first'
            : active ? 'Part of an active series' : null;
        if (tip) {
            setupReviewLockedTooltip();
            this.repeatsRow?.setAttribute('data-review-locked-tooltip', tip);
        } else {
            this.repeatsRow?.removeAttribute('data-review-locked-tooltip');
        }
        this.recurrenceEditor?.setDisabled(locked || active);
        this._updateRecurrenceFooter();
    }

    _setRecurrenceLocked(locked) {
        this._recurrenceLocked = locked;
        this._applyRecurrenceLock();
    }

    async _confirmRecurrence() {
        const editor = this.recurrenceEditor;
        const end = editor?.endBound();
        const eventId = this.form?.dataset?.eventId;
        if (!end || this._recurrenceLocked || this._seriesState?.active) return;
        if (!eventId || eventId === 'new') {
            this._updateRecurrenceFooter('Save the event before making it repeat', true);
            return;
        }

        this._recurrenceSaving = true;
        this._updateRecurrenceFooter('Creating series…');
        try {
            // Flush pending edits so the series anchors on the current start date/time.
            if (this.autoSaveTimeout) {
                clearTimeout(this.autoSaveTimeout);
                this.autoSaveTimeout = null;
            }
            for (let i = 0; this.isSaving && i < 50; i++) {
                await new Promise(r => setTimeout(r, 100));
            }
            await this.performAutoSave();

            const response = await fetch(`/api/events/${eventId}/series/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ rrule: editor.buildRrule(), ...end }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

            this._seriesState = { id: data.series_id, active: true };
            this.recurrenceSection.dataset.active = 'true';
            this._didMutate = true; // list/calendar refresh on close
            this._recurrenceSaving = false;
            this._applyRecurrenceLock();
            const n = Number(data.occurrences_created) || 0;
            this._updateRecurrenceFooter(
                `Series created · ${n} more occurrence${n === 1 ? '' : 's'} added to the calendar`);
        } catch (error) {
            console.error('EventEditingModalV2: series save failed', error);
            this._recurrenceSaving = false;
            this._updateRecurrenceFooter(error.message || 'Could not create the series', true);
        }
    }

    async _discardPendingSeries() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || !this._seriesState || this._seriesState.active) return;
        try {
            const response = await fetch(`/api/events/${eventId}/series/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
            this._seriesState = null;
            delete this.recurrenceSection.dataset.seriesId;
            this._didMutate = true;
            this._updateRecurrenceFooter();
        } catch (error) {
            console.error('EventEditingModalV2: discarding series failed', error);
            // Put the checkbox back so the UI matches the server.
            this.repeatsCheckbox.checked = true;
            this._updateRecurrenceVisibility();
            this._updateRecurrenceFooter(error.message || 'Could not remove the series', true);
        }
    }

    // =========================================================================
    // Email Panel Toggle
    // =========================================================================

    initializeEmailToggle() {
        this.showEmailBtn?.addEventListener('click', () => {
            this.isEmailPanelVisible = !this.isEmailPanelVisible;

            if (this.isEmailPanelVisible) {
                // When showing: add transition class first, then add visible class
                this.container?.classList.add('email-transitioning');
                // Use requestAnimationFrame to ensure transition class is applied before visible
                requestAnimationFrame(() => {
                    this.container?.classList.add('email-visible');
                });
            } else {
                // When hiding: remove transition class first (no animation), then remove visible
                this.container?.classList.remove('email-transitioning');
                this.container?.classList.remove('email-visible');
            }

            // Update button text
            const btnText = this.showEmailBtn.querySelector('.v2-btn-text');
            if (btnText) {
                btnText.textContent = this.isEmailPanelVisible ? 'Hide Email' : this.getEmailButtonText();
            }

            // Update button icon
            const btnIcon = this.showEmailBtn.querySelector('.v2-action-btn-icon');
            if (btnIcon) {
                btnIcon.innerHTML = this.isEmailPanelVisible
                    ? '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>'
                    : '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
            }

            // Re-assert the human-review lock on the Respond button now that the
            // email toolbar is visible (it may not have existed at review init).
            if (this.isEmailPanelVisible && this._reviewLocked) {
                setTimeout(() => this._lockRespondButton(true), 0);
            }

            console.log('EventEditingModalV2: Email panel', this.isEmailPanelVisible ? 'shown' : 'hidden');
        });

        // Initialize email button based on email count
        this.initializeEmailButton();
    }

    getEmailButtonText() {
        const emailCount = this.getEmailCount();
        if (emailCount === 0) {
            return 'No Emails';
        } else if (emailCount === 1) {
            return 'Show Email';
        } else {
            return 'Show Emails';
        }
    }

    getEmailCount() {
        // Count email items in the email panel
        const emailItems = document.querySelectorAll('.v2-email-item');
        return emailItems.length;
    }

    initializeEmailButton() {
        const emailCount = this.getEmailCount();
        const btnText = this.showEmailBtn?.querySelector('.v2-btn-text');

        if (emailCount === 0) {
            // Disable button and gray it out
            if (this.showEmailBtn) {
                this.showEmailBtn.disabled = true;
                this.showEmailBtn.classList.add('v2-action-btn-disabled');
            }
            if (btnText) {
                btnText.textContent = 'No Emails';
            }
        } else {
            if (this.showEmailBtn) {
                this.showEmailBtn.disabled = false;
                this.showEmailBtn.classList.remove('v2-action-btn-disabled');
            }
            if (btnText) {
                btnText.textContent = emailCount === 1 ? 'Show Email' : 'Show Emails';
            }
        }
    }

    // =========================================================================
    // Auto-Save System
    // =========================================================================

    initializeAutoSave() {
        const autoSaveFields = [
            'v2-title', 'v2-organization', 'v2-location', 'v2-description', 'v2-event-notes',
            'v2-start-date', 'v2-start-time', 'v2-end-date', 'v2-end-time',
            'v2-timezone', 'v2-time-range-text', 'v2-point-of-contact', 'v2-contact-email', 'v2-contact-phone',
            'v2-expected-attendees',
            // Note: Custom dropdowns (type, format, duration, reminder, status) trigger auto-save via selection
            'v2-parties-notes', 'v2-review-notes', 'v2-tab-organization'
        ];

        autoSaveFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (!field) return;

            const eventType = (field.type === 'checkbox' || field.tagName === 'SELECT')
                ? 'change' : 'input';

            field.addEventListener(eventType, () => this.triggerAutoSave());
        });

        // Also update time display when time fields change
        this.startTimeInput?.addEventListener('change', () => this.updateTimeDisplay());
        this.endTimeInput?.addEventListener('change', () => this.updateTimeDisplay());
    }

    /**
     * Compute the largest min-height we can safely set on the panel-content
     * without pushing the action bar past the modal's max-height: 90vh.
     *
     * Subtlety: during human review the action bar gets `display: none` and
     * the review progress bar appears in its place. We always reserve room
     * for the action bar (cached the first time we see it visible, with a
     * sensible fallback if we never did) so the stored min-height stays
     * safe across the review → post-review transition.
     */
    getMaxSafePanelHeight() {
        const container = document.getElementById('v2-modal-container');
        if (!container) return Infinity;
        const header = container.querySelector('.v2-header');
        const tabs = container.querySelector('.v2-tabs');
        const actionBar = container.querySelector('.v2-action-bar');
        const reviewBar = container.querySelector('.v2-review-bottom-row');
        const h = (el) => (el ? el.offsetHeight : 0);

        const actionH = h(actionBar);
        if (actionH > 0) {
            // Cache the visible height for later when it might be hidden.
            this._actionBarHeight = Math.max(this._actionBarHeight || 0, actionH);
        }
        const actionReserve = Math.max(actionH, this._actionBarHeight || 80);
        const reviewReserve = h(reviewBar);

        const modalCap = window.innerHeight * 0.9; // matches max-height: 90vh
        // Small safety buffer for borders/shadows.
        return Math.max(0, modalCap - h(header) - h(tabs) - actionReserve - reviewReserve - 8);
    }

    /**
     * Grow the panel-content's min-height to the active tab's content height
     * if it's larger than what we've stored. Modal stays stable across tabs
     * — switching to a shorter tab doesn't shrink it, and there's no extra
     * scrollable space beyond the active tab's content. Capped so the action
     * bar stays visible.
     */
    growPanelMinHeight() {
        const pc = document.querySelector('.v2-panel-content');
        if (!pc) return;
        const activePanel = pc.querySelector('.v2-tab-panel.active');
        if (!activePanel) return;
        const padTop = parseFloat(getComputedStyle(pc).paddingTop) || 0;
        const padBot = parseFloat(getComputedStyle(pc).paddingBottom) || 0;
        const needed = Math.min(
            activePanel.scrollHeight + padTop + padBot,
            this.getMaxSafePanelHeight()
        );
        const stored = this._panelMaxHeight || 0;
        if (needed > stored) {
            this._panelMaxHeight = needed;
            pc.style.minHeight = needed + 'px';
        }
    }

    /**
     * Measure all tabs once on init so the modal opens at the tallest tab's
     * size rather than growing on first navigation.
     */
    seedPanelMinHeightFromAllTabs() {
        const pc = document.querySelector('.v2-panel-content');
        const panels = Array.from(document.querySelectorAll('.v2-tab-panel'));
        if (!pc || !panels.length) return;

        const padTop = parseFloat(getComputedStyle(pc).paddingTop) || 0;
        const padBot = parseFloat(getComputedStyle(pc).paddingBottom) || 0;
        const prevPos = pc.style.position;
        pc.style.position = 'relative';

        let maxH = 0;
        panels.forEach(panel => {
            const wasActive = panel.classList.contains('active');
            const orig = {
                display: panel.style.display,
                visibility: panel.style.visibility,
                position: panel.style.position,
                left: panel.style.left,
                right: panel.style.right,
                top: panel.style.top,
            };
            if (!wasActive) {
                panel.style.display = 'block';
                panel.style.visibility = 'hidden';
                panel.style.position = 'absolute';
                panel.style.left = '0';
                panel.style.right = '0';
                panel.style.top = '0';
            }
            const h = panel.scrollHeight;
            if (h > maxH) maxH = h;
            if (!wasActive) {
                panel.style.display = orig.display;
                panel.style.visibility = orig.visibility;
                panel.style.position = orig.position;
                panel.style.left = orig.left;
                panel.style.right = orig.right;
                panel.style.top = orig.top;
            }
        });

        pc.style.position = prevPos;

        const needed = Math.min(maxH + padTop + padBot, this.getMaxSafePanelHeight());
        if (needed > (this._panelMaxHeight || 0)) {
            this._panelMaxHeight = needed;
            pc.style.minHeight = needed + 'px';
        }
    }

    /**
     * Clicking the datetime line in the header jumps to the date/time section
     * inside the Event Details tab.
     */
    initializeHeaderMetaClick() {
        const container = document.getElementById('v2-header-meta');
        if (!container) return;
        container.addEventListener('click', (e) => {
            if (e.target.closest('.v2-header-meta-datetime')) {
                this.switchToTab('event-details');
                const section = document.querySelector('#v2-event-details-panel .v2-time-section');
                section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }

    /**
     * Render the header meta lines (datetime · relative / location / · type · format)
     * underneath the organization input, matching the schedule side-panel style.
     */
    updateHeaderMeta() {
        const container = document.getElementById('v2-header-meta');
        if (!container) return;

        const startDate = this.startDateInput?.value || '';
        const endDate = this.endDateInput?.value || '';
        const startTime = this.startTimeInput?.value || '';
        const endTime = this.endTimeInput?.value || '';

        const escapeHtml = (str) => String(str ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        const formatDate = (dateStr) => {
            if (!dateStr) return '';
            const d = new Date(dateStr + 'T00:00:00');
            if (isNaN(d.getTime())) return '';
            const now = new Date();
            const opts = d.getFullYear() !== now.getFullYear()
                ? { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }
                : { weekday: 'short', month: 'short', day: 'numeric' };
            return d.toLocaleDateString('en-US', opts);
        };

        const formatTime = (timeStr) => {
            if (!timeStr) return '';
            const [h, m] = timeStr.split(':');
            const d = new Date();
            d.setHours(parseInt(h, 10), parseInt(m, 10));
            return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
        };

        const getRelativeTime = () => {
            if (!startDate) return '';
            const now = new Date();
            const eventDate = new Date(startDate + 'T00:00:00');
            if (isNaN(eventDate.getTime())) return '';
            if (startTime) {
                const [h, m] = startTime.split(':');
                eventDate.setHours(parseInt(h, 10), parseInt(m, 10), 0, 0);
            }
            const diffMs = eventDate.getTime() - now.getTime();
            const diffDays = Math.round(diffMs / 86400000);
            const isToday = eventDate.toDateString() === now.toDateString();
            const isTomorrow = new Date(now.getTime() + 86400000).toDateString() === eventDate.toDateString();
            const timeStr = startTime ? formatTime(startTime) : '';

            if (isToday) {
                if (diffMs > 0) {
                    const hrsLeft = Math.floor(diffMs / 3600000);
                    const minsLeft = Math.round((diffMs % 3600000) / 60000);
                    const remaining = hrsLeft > 0 ? `starts in ${hrsLeft}h ${minsLeft}m` : `starts in ${minsLeft}m`;
                    return timeStr ? `Today at ${timeStr} — ${remaining}` : `Today — ${remaining}`;
                }
                return timeStr ? `Today at ${timeStr}` : 'Today';
            }
            if (isTomorrow) return timeStr ? `Tomorrow at ${timeStr}` : 'Tomorrow';
            if (diffDays > 0 && diffDays <= 14) return `In ${diffDays} day${diffDays === 1 ? '' : 's'}`;
            if (diffDays > 14 && diffDays <= 60) { const w = Math.round(diffDays / 7); return `In ${w} week${w === 1 ? '' : 's'}`; }
            if (diffDays < 0 && diffDays >= -60) { const a = Math.abs(diffDays); return `${a} day${a === 1 ? '' : 's'} ago`; }
            return '';
        };

        // Datetime line
        let dateTimeDisplay = '';
        if (startDate) {
            if (endDate && endDate !== startDate) {
                dateTimeDisplay = `${formatDate(startDate)} – ${formatDate(endDate)}`;
            } else {
                dateTimeDisplay = formatDate(startDate);
                if (startTime) {
                    dateTimeDisplay += ` at ${formatTime(startTime)}`;
                    if (endTime) {
                        dateTimeDisplay += ` – ${formatTime(endTime)}`;
                    }
                }
            }
        }
        const relativeTime = getRelativeTime();

        let html = '';
        if (dateTimeDisplay || relativeTime) {
            const datePart = escapeHtml(dateTimeDisplay);
            const relPart = relativeTime
                ? ` <span class="v2-header-meta-relative">· ${escapeHtml(relativeTime)}</span>`
                : '';
            html += `<div class="v2-header-meta-datetime">
                <svg class="v2-header-meta-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
                <span>${datePart}${relPart}</span>
            </div>`;
        }
        container.innerHTML = html;
    }

    triggerAutoSave() {
        // Header meta (date/time/location/type/format) reflects current form
        // state and should update on every change, not after the debounced save.
        this.updateHeaderMeta();

        // Don't auto-save during initialization - form may not be fully populated
        if (this.isInitializing) {
            console.log('EventEditingModalV2: triggerAutoSave skipped (initializing)');
            return;
        }

        console.log('EventEditingModalV2: triggerAutoSave called');
        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
        }

        this.autoSaveTimeout = setTimeout(() => {
            this.performAutoSave();
        }, this.options.autoSaveDelay);
    }

    async performAutoSave() {
        if (this.isSaving) return;

        const currentData = this.collectFormData();

        // Check for changes
        if (this.lastSavedData &&
            JSON.stringify(currentData) === JSON.stringify(this.lastSavedData)) {
            return;
        }

        const eventId = this.form?.dataset?.eventId;

        if (!eventId || eventId === 'new') {
            console.log('EventEditingModalV2: Skipping auto-save for new event');
            return;
        }

        // UUID validation
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
        if (!uuidRegex.test(eventId)) {
            console.warn('EventEditingModalV2: Invalid event ID', eventId);
            return;
        }

        // Safety check: Don't save if title was cleared but had content before
        // This prevents accidentally wiping event data on close/escape
        if (this.lastSavedData?.title && !currentData.title) {
            console.warn('EventEditingModalV2: Skipping auto-save (title cleared - possible data loss)', {
                previousTitle: this.lastSavedData.title,
                currentTitle: currentData.title
            });
            return;
        }

        this.isSaving = true;
        this.showSaveIndicator('saving');

        try {
            const csrfToken = this.getCsrfToken();
            const cleanData = this.cleanDataForAPI(currentData);

            // Debug logging for staff data
            console.log('EventEditingModalV2: Auto-save request data:', {
                eventId,
                staff: cleanData.staff,
                status: cleanData.status,
                title: cleanData.title
            });

            const response = await fetch(`/api/events/${eventId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(cleanData),
                credentials: 'same-origin'
            });

            if (response.ok) {
                const responseData = await response.json();
                this.lastSavedData = currentData;
                this._didMutate = true; // data changed → list refresh on close
                this.showSaveIndicator('saved');
                console.log('EventEditingModalV2: Auto-save successful, response:', {
                    id: responseData.id,
                    staff: responseData.staff,
                    status: responseData.status
                });

                // Refresh calendar if available
                if (window.calendarRedesign) {
                    window.calendarRedesign.fetchEvents().then(() => {
                        window.calendarRedesign.renderCurrentView();
                    });
                }
            } else {
                // Read error response for debugging
                const errorText = await response.text();
                console.error('EventEditingModalV2: Auto-save failed', {
                    status: response.status,
                    statusText: response.statusText,
                    body: errorText
                });
                throw new Error(`HTTP ${response.status}: ${errorText}`);
            }
        } catch (error) {
            console.error('EventEditingModalV2: Auto-save error', error);
            this.showSaveIndicator('error');
        } finally {
            this.isSaving = false;
        }
    }

    getCsrfToken() {
        // Try form input
        const formInput = this.form?.querySelector('[name="csrfmiddlewaretoken"]');
        if (formInput?.value) return formInput.value;

        // Try meta tag
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag?.content) return metaTag.content;

        // Try cookie
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return value;
        }

        return '';
    }

    showSaveIndicator(status) {
        let indicator = document.getElementById('v2-autosave-indicator');

        if (!indicator) {
            indicator = document.createElement('div');
            indicator.id = 'v2-autosave-indicator';
            indicator.className = 'v2-autosave-indicator';
            indicator.innerHTML = `
                <svg class="v2-autosave-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                    <polyline points="17 21 17 13 7 13 7 21"/>
                    <polyline points="7 3 7 8 15 8"/>
                </svg>
                <span class="v2-autosave-text"></span>
            `;
            document.body.appendChild(indicator);
        }

        const textEl = indicator.querySelector('.v2-autosave-text');

        // Remove previous status classes
        indicator.classList.remove('saving', 'saved', 'error');

        switch (status) {
            case 'saving':
                indicator.classList.add('saving', 'visible');
                textEl.textContent = 'Saving...';
                break;
            case 'saved':
                indicator.classList.add('saved', 'visible');
                textEl.textContent = 'Saved';
                setTimeout(() => indicator.classList.remove('visible'), 2000);
                break;
            case 'error':
                indicator.classList.add('error', 'visible');
                textEl.textContent = 'Save failed';
                setTimeout(() => indicator.classList.remove('visible'), 3000);
                break;
        }
    }

    // =========================================================================
    // Field Synchronization
    // =========================================================================

    initializeFieldSync() {
        // Sync organization fields (header <-> tab)
        const headerOrg = document.getElementById('v2-organization');
        const tabOrg = document.getElementById('v2-tab-organization');

        if (headerOrg && tabOrg) {
            headerOrg.addEventListener('input', (e) => {
                tabOrg.value = e.target.value;
                this.triggerAutoSave();
            });

            tabOrg.addEventListener('input', (e) => {
                headerOrg.value = e.target.value;
                this.triggerAutoSave();
            });
        }

        // Sync notes fields across tabs
        const noteFields = [
            document.getElementById('v2-event-notes'),
            document.getElementById('v2-parties-notes'),
            document.getElementById('v2-review-notes')
        ].filter(Boolean);

        noteFields.forEach((field, idx) => {
            field.addEventListener('input', (e) => {
                noteFields.forEach((other, otherIdx) => {
                    if (idx !== otherIdx) {
                        other.value = e.target.value;
                    }
                });
                this.triggerAutoSave();
            });
        });
    }

    // =========================================================================
    // Tags System
    // =========================================================================

    initializeTags() {
        const addTag = (text, isImportant = false) => {
            if (!text.trim() || !this.tagsContainer) return;

            // Check for duplicates
            const existingTags = this.collectTags();
            if (existingTags.includes(text.trim())) return;

            const tag = document.createElement('div');
            const tagClass = isImportant || text.toUpperCase() === 'IMPORTANT'
                ? 'v2-tag-important' : 'v2-tag-default';

            tag.className = `v2-tag ${tagClass}`;
            tag.innerHTML = `
                <span class="v2-tag-text">${this.escapeHtml(text.trim())}</span>
                <button type="button" class="v2-tag-remove" aria-label="Remove tag">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            `;

            tag.querySelector('.v2-tag-remove').addEventListener('click', () => {
                tag.remove();
                this.triggerAutoSave();
            });

            // Insert before input or add button
            const insertBefore = this.tagInput || this.tagAddBtn;
            if (insertBefore) {
                this.tagsContainer.insertBefore(tag, insertBefore);
            } else {
                this.tagsContainer.appendChild(tag);
            }

            this.triggerAutoSave();
        };

        // Enter key to add tag
        this.tagInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addTag(this.tagInput.value);
                this.tagInput.value = '';
            }
        });

        // Focus input when add button clicked
        this.tagAddBtn?.addEventListener('click', () => {
            this.tagInput?.focus();
        });

        // Expose addTag method
        this.addTag = addTag;
    }

    collectTags() {
        const tags = [];
        this.tagsContainer?.querySelectorAll('.v2-tag-text').forEach(span => {
            const text = span.textContent.trim();
            if (text) tags.push(text);
        });
        return tags;
    }

    // =========================================================================
    // Staff Management
    // =========================================================================

    initializeStaff() {
        // Cache office staff (loaded once)
        this.officeStaff = null;
        this.staffDropdownVisible = false;

        // Remove staff pill in Involved Parties tab
        this.staffContainer?.querySelectorAll('.v2-staff-pill-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const staffName = btn.closest('.v2-staff-pill')?.querySelector('.v2-staff-name')?.textContent?.trim();
                btn.closest('.v2-staff-pill')?.remove();
                if (staffName) {
                    this.removeStaffFromEvent(staffName, 'involved-parties');
                }
                this.triggerAutoSave();
            });
        });

        // Add staff button in Involved Parties tab
        this.addStaffBtn?.addEventListener('click', () => {
            this.toggleStaffDropdown('involved-parties');
        });

        // Staff & Review tab elements
        this.reviewStaffList = document.getElementById('v2-review-staff-list');
        this.reviewAddStaffBtn = document.getElementById('v2-review-add-staff-btn');
        this.reviewStaffDropdown = document.getElementById('v2-review-staff-dropdown');

        // Involved Parties tab dropdown
        this.involvedStaffDropdown = document.getElementById('v2-involved-staff-dropdown');

        // Add staff button in Staff & Review tab
        this.reviewAddStaffBtn?.addEventListener('click', () => {
            this.toggleStaffDropdown('staff-review');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (this.staffDropdownVisible) {
                const isDropdownClick = e.target.closest('.v2-staff-dropdown-wrapper');
                if (!isDropdownClick) {
                    this.hideStaffDropdown();
                }
            }
        });

        // Sync existing staff from Involved Parties tab to Staff & Review tab on load
        // (Django template pre-populates Involved Parties but not Staff & Review)
        this.syncStaffToReviewTab();
    }

    /**
     * Load office staff list from API (cached)
     */
    async loadOfficeStaff() {
        if (this.officeStaff) {
            return this.officeStaff;
        }

        try {
            const response = await fetch('/api/office/choices/', {
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            // API returns staff_members array
            this.officeStaff = data.staff_members || data.staff || [];
            return this.officeStaff;
        } catch (error) {
            console.error('EventEditingModalV2: Failed to load office staff', error);
            // Return mock data for development
            this.officeStaff = [
                { id: '1', name: 'John Smith' },
                { id: '2', name: 'Jane Doe' },
                { id: '3', name: 'Mike Johnson' },
                { id: '4', name: 'Sarah Williams' }
            ];
            return this.officeStaff;
        }
    }

    /**
     * Toggle staff dropdown visibility
     */
    async toggleStaffDropdown(source) {
        if (this.staffDropdownVisible) {
            this.hideStaffDropdown();
            return;
        }

        // Load staff if not cached
        const staff = await this.loadOfficeStaff();
        const currentStaff = this.collectStaff();

        // Determine which dropdown to use
        const dropdown = source === 'staff-review'
            ? this.reviewStaffDropdown
            : this.involvedStaffDropdown;

        if (!dropdown) return;

        // Build dropdown content
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

                html += `
                    <div class="v2-staff-dropdown-item${disabledClass}" data-staff-name="${this.escapeHtml(name)}" data-source="${source}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        <span>${this.escapeHtml(name)}</span>
                        ${checkIcon}
                    </div>
                `;
            });
        }

        dropdown.innerHTML = html;

        // Bind click handlers to dropdown items
        dropdown.querySelectorAll('.v2-staff-dropdown-item:not(.disabled)').forEach(item => {
            item.addEventListener('click', () => {
                const staffName = item.dataset.staffName;
                const itemSource = item.dataset.source;
                this.addStaffToEvent(staffName, itemSource);
                this.hideStaffDropdown();
            });
        });

        // Move dropdown to body to escape transform containment (like status dropdown)
        document.body.appendChild(dropdown);

        // Make visible first so it can be measured for flip-up positioning.
        dropdown.classList.add('visible');

        // Position dropdown using fixed positioning
        const button = source === 'staff-review' ? this.reviewAddStaffBtn : this.addStaffBtn;
        if (button) {
            const rect = button.getBoundingClientRect();
            const gap = 4;
            const margin = 8;
            const dropdownHeight = dropdown.offsetHeight;
            const spaceBelow = window.innerHeight - rect.bottom;
            const spaceAbove = rect.top;

            // Flip the dropdown above the button when it would clip off the
            // bottom of the screen and there's more room above than below.
            if (spaceBelow < dropdownHeight + gap + margin && spaceAbove > spaceBelow) {
                dropdown.style.top = `${Math.max(margin, rect.top - dropdownHeight - gap)}px`;
            } else {
                dropdown.style.top = `${rect.bottom + gap}px`;
            }
            dropdown.style.left = `${rect.left}px`;

            // Ensure dropdown doesn't overflow right edge of screen
            const dropdownWidth = 220;
            if (rect.left + dropdownWidth > window.innerWidth) {
                dropdown.style.left = `${window.innerWidth - dropdownWidth - 16}px`;
            }
        }

        this.staffDropdownVisible = true;
        this.activeStaffDropdown = dropdown;
        this.activeStaffDropdownSource = source;
    }

    /**
     * Hide staff dropdown
     */
    hideStaffDropdown() {
        // Move active dropdown back to its wrapper if on body
        if (this.activeStaffDropdown && this.activeStaffDropdown.parentNode === document.body) {
            // Find the original wrapper based on source
            const wrapper = this.activeStaffDropdownSource === 'staff-review'
                ? this.reviewAddStaffBtn?.closest('.v2-staff-dropdown-wrapper')
                : this.addStaffBtn?.closest('.v2-staff-dropdown-wrapper');

            if (wrapper) {
                // Clear inline styles
                this.activeStaffDropdown.style.top = '';
                this.activeStaffDropdown.style.left = '';
                wrapper.appendChild(this.activeStaffDropdown);
            }
        }

        this.reviewStaffDropdown?.classList.remove('visible');
        this.involvedStaffDropdown?.classList.remove('visible');
        this.staffDropdownVisible = false;
        this.activeStaffDropdown = null;
        this.activeStaffDropdownSource = null;
    }

    /**
     * Add staff member to event
     */
    addStaffToEvent(staffName, source) {
        console.log('EventEditingModalV2: Adding staff member:', staffName, 'from', source);

        // Add to Involved Parties tab
        if (this.staffContainer) {
            const existingPills = this.staffContainer.querySelectorAll('.v2-staff-pill');
            const alreadyExists = Array.from(existingPills).some(
                pill => pill.querySelector('.v2-staff-name')?.textContent?.trim() === staffName
            );

            if (!alreadyExists) {
                const pill = document.createElement('div');
                pill.className = 'v2-staff-pill';
                pill.dataset.staffName = staffName;
                pill.innerHTML = `
                    <button type="button" class="v2-staff-star" data-tooltip="Set as primary staffer" aria-label="Set as primary staffer">
                        <svg viewBox="0 0 24 24" stroke-width="2" width="13" height="13"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                    </button>
                    <span class="v2-staff-name">${this.escapeHtml(staffName)}</span>
                    <button type="button" class="v2-staff-pill-remove" aria-label="Remove">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                `;

                // Insert before the dropdown wrapper
                const dropdownWrapper = this.staffContainer.querySelector('.v2-staff-dropdown-wrapper');
                if (dropdownWrapper) {
                    this.staffContainer.insertBefore(pill, dropdownWrapper);
                } else {
                    this.staffContainer.appendChild(pill);
                }

                // Bind remove handler
                pill.querySelector('.v2-staff-pill-remove')?.addEventListener('click', () => {
                    this.removeStaffFromEvent(staffName, 'involved-parties');
                });
            }
        }

        // Sync to Staff & Review tab
        this.syncStaffToReviewTab();
        this.triggerAutoSave();
    }

    /**
     * Remove staff member from event
     */
    removeStaffFromEvent(staffName, source) {
        // If the removed staffer was the primary, clear the primary.
        const psInput = document.getElementById('v2-primary-staff');
        if (psInput && psInput.value === staffName) psInput.value = '';
        // Remove from Involved Parties tab
        if (this.staffContainer) {
            this.staffContainer.querySelectorAll('.v2-staff-pill').forEach(pill => {
                if (pill.querySelector('.v2-staff-name')?.textContent?.trim() === staffName) {
                    pill.remove();
                }
            });
        }

        // Sync to Staff & Review tab
        this.syncStaffToReviewTab();
        this.triggerAutoSave();
    }

    /**
     * Sync staff list to Staff & Review tab
     */
    syncStaffToReviewTab() {
        const staff = this.collectStaff();
        console.log('EventEditingModalV2: syncStaffToReviewTab - collected staff:', staff);
        this.renderReviewStaffList(staff);
    }

    /**
     * Render staff list in Staff & Review tab
     */
    renderReviewStaffList(staffList) {
        console.log('EventEditingModalV2: renderReviewStaffList called with', staffList, 'reviewStaffList element:', this.reviewStaffList);
        if (!this.reviewStaffList) {
            console.warn('EventEditingModalV2: reviewStaffList element not found');
            return;
        }

        if (!staffList || staffList.length === 0) {
            this.reviewStaffList.innerHTML = '';
            return;
        }

        let html = '';
        staffList.forEach(name => {
            html += `
                <div class="v2-staff-pill" data-staff-name="${this.escapeHtml(name)}">
                    <button type="button" class="v2-staff-star" data-tooltip="Set as primary staffer" aria-label="Set as primary staffer">
                        <svg viewBox="0 0 24 24" stroke-width="2" width="13" height="13"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                    </button>
                    <span class="v2-staff-name">${this.escapeHtml(name)}</span>
                    <button type="button" class="v2-staff-pill-remove" aria-label="Remove" data-staff-name="${this.escapeHtml(name)}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
            `;
        });

        this.reviewStaffList.innerHTML = html;

        // Bind remove handlers
        this.reviewStaffList.querySelectorAll('.v2-staff-pill-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const staffName = btn.dataset.staffName;
                this.removeStaffFromEvent(staffName, 'staff-review');
            });
        });
        this.applyStaffStars();
    }

    collectStaff() {
        const staff = [];
        this.staffContainer?.querySelectorAll('.v2-staff-pill').forEach(pill => {
            const nameEl = pill.querySelector('.v2-staff-name');
            if (nameEl?.textContent) {
                const name = nameEl.textContent.trim();
                // Only add valid string names (not empty, not object representations)
                if (name && !name.startsWith('{') && !name.startsWith('[')) {
                    staff.push(name);
                }
            }
        });
        console.log('EventEditingModalV2: collectStaff returned', staff);
        return staff;
    }

    // ----- Primary staffer (optional; one of the assigned staff) -------------

    primaryStaffName() {
        return document.getElementById('v2-primary-staff')?.value || '';
    }

    setPrimaryStaff(name) {
        if (!name) return;
        const input = document.getElementById('v2-primary-staff');
        if (!input) return;
        // Toggle: clicking the current primary clears it (a primary is optional).
        input.value = (input.value === name) ? '' : name;
        this.applyStaffStars();
        this.triggerAutoSave();
    }

    applyStaffStars() {
        const primary = this.primaryStaffName();
        document.querySelectorAll('.v2-staff-pill').forEach(pill => {
            const name = pill.dataset.staffName ||
                pill.querySelector('.v2-staff-name')?.textContent?.trim();
            const star = pill.querySelector('.v2-staff-star');
            if (star) star.classList.toggle('v2-staff-star-on', !!primary && name === primary);
        });
    }

    // Delegated star clicks for both staff lists (involved-parties + review).
    wireStaffStars() {
        ['v2-staff-container', 'v2-review-staff-list'].forEach(id => {
            const c = document.getElementById(id);
            if (!c || c.dataset.starWired) return;
            c.dataset.starWired = '1';
            c.addEventListener('click', (e) => {
                const star = e.target.closest('.v2-staff-star');
                if (!star) return;
                e.preventDefault();
                const pill = star.closest('.v2-staff-pill');
                const name = pill?.dataset.staffName ||
                    pill?.querySelector('.v2-staff-name')?.textContent?.trim();
                this.setPrimaryStaff(name);
            });
        });
        this.applyStaffStars();
    }

    // =========================================================================
    // Time Validation
    // =========================================================================

    initializeTimeValidation() {
        const validateTimes = () => {
            const startDate = this.startDateInput?.value;
            const startTime = this.startTimeInput?.value;
            const endDate = this.endDateInput?.value;
            const endTime = this.endTimeInput?.value;

            if (!startDate || !startTime || !endDate || !endTime) return;

            const start = new Date(`${startDate}T${startTime}`);
            const end = new Date(`${endDate}T${endTime}`);

            if (end <= start && startDate === endDate) {
                // Adjust end time to be 1 hour after start
                const newEnd = new Date(start.getTime() + 60 * 60 * 1000);
                const hours = String(newEnd.getHours()).padStart(2, '0');
                const mins = String(newEnd.getMinutes()).padStart(2, '0');

                if (this.endTimeInput) {
                    this.endTimeInput.value = `${hours}:${mins}`;
                }

                console.log('EventEditingModalV2: Adjusted end time to', this.endTimeInput?.value);
            }

            this.updateTimeDisplay();
        };

        this.startTimeInput?.addEventListener('change', validateTimes);
        this.endTimeInput?.addEventListener('change', validateTimes);
        this.startDateInput?.addEventListener('change', validateTimes);
        this.endDateInput?.addEventListener('change', validateTimes);
    }

    // =========================================================================
    // Status Dropdown (Custom)
    // =========================================================================

    initializeStatusDropdown() {
        this.statusWrapper = document.getElementById('v2-status-dropdown-wrapper');
        this.statusTrigger = document.getElementById('v2-status');
        this.statusMenu = document.getElementById('v2-status-dropdown-menu');
        this.statusValueInput = document.getElementById('v2-status-value');
        this.statusOptions = this.statusMenu?.querySelectorAll('.v2-status-dropdown-option');

        if (!this.statusWrapper || !this.statusTrigger || !this.statusMenu) {
            console.warn('EventEditingModalV2: Status dropdown elements not found');
            return;
        }

        // Toggle dropdown on trigger click
        this.statusTrigger.addEventListener('click', (e) => {
            e.stopPropagation();

            if (this.statusWrapper.classList.contains('open')) {
                this.closeStatusDropdown();
                return;
            }

            this.openStatusDropdown();
        });

        // Keyboard support for trigger. When the menu is open, let the modal's
        // dropdown key handler drive navigation/selection (arrows, Enter, Tab);
        // Escape is owned by the modal Escape authority.
        this.statusTrigger.addEventListener('keydown', (e) => {
            if ((e.key === 'Enter' || e.key === ' ') && !this.statusWrapper.classList.contains('open')) {
                e.preventDefault();
                e.stopPropagation();
                this.openStatusDropdown();
            }
        });

        // Handle option selection
        this.statusOptions?.forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const newStatus = option.dataset.value;
                this.selectStatus(newStatus, option.textContent.trim());
            });
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!this.statusWrapper?.contains(e.target) && !this.statusMenu?.contains(e.target)) {
                this.closeStatusDropdown();
            }
        });

        // Initialize status class on trigger from hidden input
        const currentStatus = this.statusValueInput?.value;
        if (currentStatus) {
            this.statusTrigger.classList.add(`status-${currentStatus}`);
        }
    }

    openStatusDropdown() {
        // Move menu to body to avoid containment issues
        document.body.appendChild(this.statusMenu);

        // Get trigger position
        const triggerRect = this.statusTrigger.getBoundingClientRect();

        // Measure menu
        this.statusMenu.style.visibility = 'hidden';
        this.statusMenu.style.display = 'block';
        const menuWidth = this.statusMenu.offsetWidth;
        const menuHeight = this.statusMenu.offsetHeight;

        const viewportHeight = window.innerHeight;
        const viewportWidth = window.innerWidth;
        const spaceBelow = viewportHeight - triggerRect.bottom;
        const spaceAbove = triggerRect.top;

        // Calculate left position (aligned with trigger left edge)
        let left = triggerRect.left;
        if (left + menuWidth > viewportWidth - 8) {
            left = viewportWidth - menuWidth - 8;
        }

        // Position menu below or above trigger
        let top;
        if (spaceBelow >= menuHeight || spaceBelow >= spaceAbove) {
            top = triggerRect.bottom + 4;
        } else {
            top = triggerRect.top - menuHeight - 4;
        }

        // Clamp to viewport
        if (top + menuHeight > viewportHeight - 8) {
            top = viewportHeight - menuHeight - 8;
        }
        if (top < 8) {
            top = 8;
        }

        // Apply position and show
        this.statusMenu.style.top = top + 'px';
        this.statusMenu.style.left = left + 'px';
        this.statusMenu.style.visibility = '';

        this.statusWrapper.classList.add('open');
    }

    closeStatusDropdown() {
        if (!this.statusWrapper?.classList.contains('open')) return;

        this.statusWrapper.classList.remove('open');
        this.statusMenu?.querySelectorAll('.v2-status-dropdown-option.kb-active')
            .forEach(o => o.classList.remove('kb-active'));

        // Move menu back to wrapper
        if (this.statusMenu?.parentNode === document.body) {
            this.statusMenu.style.display = '';
            this.statusMenu.style.top = '';
            this.statusMenu.style.left = '';
            this.statusMenu.style.visibility = '';
            this.statusWrapper.appendChild(this.statusMenu);
        }
    }

    selectStatus(status, label) {
        // Update hidden input value
        if (this.statusValueInput) {
            this.statusValueInput.value = status;
        }

        // Update trigger text
        const statusText = this.statusTrigger?.querySelector('.v2-status-text');
        if (statusText) {
            statusText.textContent = label;
        }

        // Update trigger styling
        this.statusTrigger.className = 'v2-status-select';
        this.statusTrigger.classList.add(`status-${status}`);

        // Update selected state in menu
        this.statusOptions?.forEach(opt => {
            opt.classList.toggle('selected', opt.dataset.value === status);
        });

        // Close dropdown
        this.closeStatusDropdown();

        // Trigger auto-save
        this.triggerAutoSave();
    }

    // Get current status value (for form collection)
    getStatusValue() {
        return this.statusValueInput?.value || 'received';
    }

    // =========================================================================
    // Generic Dropdowns (Accent Color)
    // =========================================================================

    initializeGenericDropdowns() {
        this.genericDropdowns = [];
        const wrappers = document.querySelectorAll('.v2-dropdown-wrapper');

        wrappers.forEach(wrapper => {
            const dropdownId = wrapper.dataset.dropdownId;
            const trigger = wrapper.querySelector('.v2-dropdown-trigger');
            const menu = wrapper.querySelector('.v2-dropdown-menu');
            const hiddenInput = document.getElementById(`${dropdownId}-value`);
            const options = menu?.querySelectorAll('.v2-dropdown-option');

            if (!trigger || !menu) return;

            // Store reference
            this.genericDropdowns.push({ wrapper, trigger, menu, hiddenInput, options, dropdownId });

            // Toggle dropdown on trigger click
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();

                if (wrapper.classList.contains('open')) {
                    this.closeGenericDropdown(wrapper, menu);
                    return;
                }

                this.openGenericDropdown(wrapper, trigger, menu);
            });

            // Keyboard support. When open, the modal's dropdown key handler
            // drives navigation/selection; Escape is owned by the modal Escape
            // authority.
            trigger.addEventListener('keydown', (e) => {
                if ((e.key === 'Enter' || e.key === ' ') && !wrapper.classList.contains('open')) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.openGenericDropdown(wrapper, trigger, menu);
                }
            });

            // Handle option selection
            options?.forEach(option => {
                option.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const value = option.dataset.value;
                    const label = option.textContent.trim();

                    // Update hidden input
                    if (hiddenInput) {
                        hiddenInput.value = value;
                    }

                    // Update trigger text
                    const triggerText = trigger.querySelector('.v2-dropdown-text');
                    if (triggerText) {
                        triggerText.textContent = label;
                    }

                    // Update selected state
                    options.forEach(opt => opt.classList.remove('selected'));
                    option.classList.add('selected');

                    // Close dropdown
                    this.closeGenericDropdown(wrapper, menu);

                    // Trigger auto-save
                    this.triggerAutoSave();
                });
            });
        });

        // Close all dropdowns when clicking outside
        document.addEventListener('click', (e) => {
            this.genericDropdowns.forEach(({ wrapper, menu }) => {
                if (!wrapper.contains(e.target) && !menu.contains(e.target)) {
                    this.closeGenericDropdown(wrapper, menu);
                }
            });
        });
    }

    openGenericDropdown(wrapper, trigger, menu) {
        // Close all other dropdowns first
        this.closeAllGenericDropdowns();

        // Move menu to body
        document.body.appendChild(menu);

        // Get trigger position
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

        // Match trigger width
        menu.style.minWidth = triggerRect.width + 'px';

        // Position left-aligned with trigger
        let left = triggerRect.left;
        if (left + menuWidth > viewportWidth - 8) {
            left = viewportWidth - menuWidth - 8;
        }

        // Position below or above
        let top;
        if (spaceBelow >= menuHeight || spaceBelow >= spaceAbove) {
            top = triggerRect.bottom + 4;
        } else {
            top = triggerRect.top - menuHeight - 4;
        }

        // Clamp to viewport
        if (top + menuHeight > viewportHeight - 8) {
            top = viewportHeight - menuHeight - 8;
        }
        if (top < 8) {
            top = 8;
        }

        menu.style.top = top + 'px';
        menu.style.left = left + 'px';
        menu.style.visibility = '';

        wrapper.classList.add('open');
        menu._parentWrapper = wrapper;
    }

    closeGenericDropdown(wrapper, menu) {
        if (!wrapper.classList.contains('open')) return;

        wrapper.classList.remove('open');
        menu.querySelectorAll('.v2-dropdown-option.kb-active')
            .forEach(o => o.classList.remove('kb-active'));

        // Move menu back to wrapper
        if (menu.parentNode === document.body) {
            menu.style.display = '';
            menu.style.top = '';
            menu.style.left = '';
            menu.style.minWidth = '';
            menu.style.visibility = '';
            wrapper.appendChild(menu);
            menu._parentWrapper = null;
        }
    }

    closeAllGenericDropdowns() {
        this.genericDropdowns?.forEach(({ wrapper, menu }) => {
            this.closeGenericDropdown(wrapper, menu);
        });

        // Also close status dropdown
        this.closeStatusDropdown();
    }

    // =========================================================================
    // More Menu (Delete / Print)
    // =========================================================================

    initializeMoreMenu() {
        // Toggle dropdown when clicking the more button
        this.moreBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleMoreMenu();
        });

        // Delete button handler
        this.deleteBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeMoreMenu();
            this.handleDeleteEvent();
        });

        // Print button handler (placeholder for now)
        this.printBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.closeMoreMenu();
            console.log('EventEditingModalV2: Print not yet implemented');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (this.moreMenu?.classList.contains('open') &&
                !this.moreMenu.contains(e.target)) {
                this.closeMoreMenu();
            }
        });

        // Close dropdown on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.moreMenu?.classList.contains('open')) {
                this.closeMoreMenu();
            }
        });
    }

    toggleMoreMenu() {
        if (this.moreMenu) {
            this.moreMenu.classList.toggle('open');
        }
    }

    closeMoreMenu() {
        if (this.moreMenu) {
            this.moreMenu.classList.remove('open');
        }
    }

    /**
     * Handle delete event with confirmation
     */
    async handleDeleteEvent() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') {
            console.warn('EventEditingModalV2: Cannot delete - no event ID');
            return;
        }

        this._didMutate = true; // deletion → list must refresh on close
        // Soft delete — the event moves to Deleted Events (Settings) and can be
        // restored, so it's reversible and applied without a confirm prompt.
        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/archive/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (response.ok || response.status === 204) {
                console.log('EventEditingModalV2: Event moved to Deleted Events');

                // Card notification
                if (typeof showMessage === 'function') {
                    showMessage('Moved to Deleted Events', 'success');
                }

                // Close the modal
                this.overlay?.classList.remove('active');
                document.body.classList.remove('modal-open');

                // Clean up review mode if active
                this.cleanupReviewMode();

                // Clear auto-save timeout
                if (this.autoSaveTimeout) {
                    clearTimeout(this.autoSaveTimeout);
                    this.autoSaveTimeout = null;
                }

                // Refresh the page list if available. Also close the detail
                // panel if it's showing the event we just removed, otherwise it
                // re-fetches a now-archived event and 404s.
                const listView = window.inboxRedesign || window.scheduleRedesign;
                if (listView) {
                    if (listView.state?.detailPanelEventId == eventId &&
                        typeof listView.closeDetailPanel === 'function') {
                        listView.closeDetailPanel();
                    }
                    listView.refresh();
                } else if (typeof window.dashboardRefresh === 'function') {
                    window.dashboardRefresh();
                }

                // Call the close modal function if it exists
                if (typeof window.closeEventEditingModal === 'function') {
                    window.closeEventEditingModal();
                }
            } else {
                throw new Error(`HTTP ${response.status}`);
            }
        } catch (error) {
            console.error('EventEditingModalV2: Failed to delete event', error);
            alert('Failed to delete event. Please try again.');
        }
    }

    // =========================================================================
    // Field Focus Highlighting (for non-review mode)
    // =========================================================================

    /**
     * Set up focus-based email highlighting for all mapped fields.
     * When a field is focused and the email panel is open, highlights the source
     * text in the email if the field value hasn't been modified from the original.
     */
    initializeFieldFocusHighlighting() {
        // For each field in the mapping, add focus/blur handlers
        for (const [fieldId, fieldName] of Object.entries(EventEditingModalV2.FIELD_MAPPING)) {
            const element = document.getElementById(fieldId);
            if (!element) continue;

            // Skip if this field already has a ReviewableField wrapper (handled separately)
            if (element.closest('.v2-review-field-wrapper')) continue;

            element.addEventListener('focus', () => {
                this.handleFieldFocusHighlight(fieldName, element);
            });

            element.addEventListener('blur', () => {
                // Small delay to allow click events to process
                setTimeout(() => {
                    // Don't clear if another mapped field is now focused
                    if (!this.isFieldFocused()) {
                        this.clearEmailHighlights();
                    }
                }, 150);
            });
        }
    }

    /**
     * Check if any mapped field is currently focused.
     * Used to prevent clearing highlights when tabbing between fields.
     */
    isFieldFocused() {
        const activeElement = document.activeElement;
        if (!activeElement) return false;

        // Check if active element is one of our mapped fields
        for (const fieldId of Object.keys(EventEditingModalV2.FIELD_MAPPING)) {
            if (activeElement.id === fieldId) return true;
        }

        // Also check if active element is inside a review wrapper
        if (activeElement.closest('.v2-review-field-wrapper')) return true;

        return false;
    }

    /**
     * Handle highlighting when a field gains focus (non-review mode).
     * Only highlights if email panel is visible and value matches original.
     */
    handleFieldFocusHighlight(fieldName, element) {
        // Skip if in review mode - ReviewableField handles highlighting there
        if (this.isReviewMode) return;

        // Must have email panel visible
        if (!this.isEmailPanelVisible) return;

        // Must have extracted field data with indices
        const fieldData = this.extractedFields[fieldName];
        if (!fieldData || fieldData.start_index == null || fieldData.end_index == null) return;

        // Check if current value matches original extracted value
        const currentValue = element.value?.trim() ?? '';
        const originalValue = String(fieldData.value ?? '').trim();
        if (currentValue !== originalValue) return;

        // Highlight the source text
        this.highlightEmailText({
            start_index: fieldData.start_index,
            end_index: fieldData.end_index,
            text_snippet: fieldData.text_snippet
        });
    }

    // =========================================================================
    // Form Data Collection
    // =========================================================================

    collectFormData() {
        return {
            title: document.getElementById('v2-title')?.value?.trim() || '',
            group: document.getElementById('v2-organization')?.value?.trim() || '',
            type: document.getElementById('v2-event-type-value')?.value || '',
            format: document.getElementById('v2-event-format-value')?.value || '',
            location: document.getElementById('v2-location')?.value?.trim() || '',
            description: document.getElementById('v2-description')?.value?.trim() || '',
            notes: document.getElementById('v2-event-notes')?.value?.trim() || '',

            start_date: document.getElementById('v2-start-date')?.value || null,
            start_time: document.getElementById('v2-start-time')?.value || null,
            end_date: document.getElementById('v2-end-date')?.value || null,
            end_time: document.getElementById('v2-end-time')?.value || null,
            timezone: document.getElementById('v2-timezone')?.value || 'America/New_York',

            is_date_range: this.isTimeRangeMode,
            is_longer_than_day: this.longerThanDayCheckbox?.checked || false,
            time_notes: document.getElementById('v2-time-range-text')?.value?.trim() || '',

            // point_of_contact_* / group are normalized and managed via the
            // contacts API (event-contacts-panel.js), not collected here.
            expected_attendees: parseInt(document.getElementById('v2-expected-attendees')?.value) || null,

            tags: this.collectTags(),
            staff: this.collectStaff(),
            primary_staff: this.primaryStaffName(),

            status: document.getElementById('v2-status-value')?.value || 'received',

            legislative_topics: [],
            participants: [],
            approval_routing: {},
            attached_email_ids: [],
            data_classification: 'internal'
        };
    }

    cleanDataForAPI(data) {
        const cleaned = { ...data };

        // Convert nulls to empty strings for text fields
        const textFields = ['title', 'location', 'description', 'notes', 'time_notes'];

        textFields.forEach(field => {
            if (cleaned[field] === null) {
                cleaned[field] = '';
            }
        });

        // Ensure arrays
        ['tags', 'staff', 'legislative_topics', 'participants', 'attached_email_ids'].forEach(field => {
            if (!Array.isArray(cleaned[field])) {
                cleaned[field] = [];
            }
        });

        // IMPORTANT: Remove approval_routing from auto-save data
        // Routing is managed separately through the dedicated routing API endpoint
        // Including it here would overwrite configured routing with empty {}
        delete cleaned.approval_routing;

        console.log('EventEditingModalV2: cleanDataForAPI - approval_routing removed, keys:', Object.keys(cleaned));

        return cleaned;
    }

    // =========================================================================
    // Load Event Data
    // =========================================================================

    async loadEventData(eventId) {
        try {
            const response = await fetch(`/api/events/${eventId}/`, {
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            this.populateForm(data);

            // Capture as initial state
            setTimeout(() => {
                this.lastSavedData = this.collectFormData();
            }, 100);

            // Store extracted fields for focus highlighting (even if review is complete)
            if (data.extracted_fields) {
                this.extractedFields = data.extracted_fields;
            }

            // Check for human review mode
            if (data.requires_human_review && data.extracted_fields) {
                // Check if there are pending fields to review
                const hasPendingFields = Object.values(data.extracted_fields).some(
                    field => field.status === 'pending'
                );

                if (hasPendingFields) {
                    setTimeout(() => {
                        this.initializeReviewMode(data.extracted_fields);
                    }, 200);
                }
            }

            // Load approval routing data
            await this.loadApprovalRouting(eventId);

            console.log('EventEditingModalV2: Event data loaded', eventId);
        } catch (error) {
            console.error('EventEditingModalV2: Failed to load event', error);
        }
    }

    populateForm(data) {
        // Basic fields
        this.setFieldValue('v2-title', data.title);
        // Org subheader is a button that jumps to the Organizations section.
        const orgJumpBtn = document.getElementById('v2-organization');
        if (orgJumpBtn) {
            const orgName = (data.group || '').trim();
            orgJumpBtn.textContent = orgName || 'Add organization / group';
            orgJumpBtn.classList.toggle('v2-org-jump-empty', !orgName);
        }
        this.setDropdownValue('v2-event-type', data.type);
        this.setDropdownValue('v2-event-format', data.format);
        this.setFieldValue('v2-location', data.location);
        this.setFieldValue('v2-description', data.description);

        // Notes (sync across tabs)
        this.setFieldValue('v2-event-notes', data.notes);
        this.setFieldValue('v2-parties-notes', data.notes);
        this.setFieldValue('v2-review-notes', data.notes);

        // Dates/times - set start date/time first
        this.setFieldValue('v2-start-date', data.start_date);
        this.setFieldValue('v2-start-time', data.start_time);
        this.setFieldValue('v2-end-time', data.end_time);
        this.setFieldValue('v2-timezone', data.timezone);

        // Determine if this is a multi-day event BEFORE triggering toggle
        const isLongerThanDay = data.is_longer_than_day ||
            (data.start_date && data.end_date && data.start_date !== data.end_date);

        // Set the longer-than-day checkbox BEFORE the toggle click
        // This prevents the toggle handler from overwriting end_date
        if (this.longerThanDayCheckbox) {
            this.longerThanDayCheckbox.checked = isLongerThanDay;
        }

        // Time toggle - now the checkbox state is correct before this runs
        console.log('EventEditingModalV2: is_date_range from API:', data.is_date_range);
        if (data.is_date_range) {
            console.log('EventEditingModalV2: Clicking Range button');
            this.timeRangeBtn?.click();
        } else {
            console.log('EventEditingModalV2: Clicking Event button');
            this.singleEventBtn?.click();
        }

        // NOW set end_date after the toggle logic has run
        // This ensures the value isn't overwritten
        this.setFieldValue('v2-end-date', data.end_date);

        // Set time notes (for date range events)
        this.setFieldValue('v2-time-range-text', data.time_notes);

        // Enable/disable end date input based on longer-than-day state
        if (this.endDateInput && !data.is_date_range) {
            this.endDateInput.disabled = !isLongerThanDay;
            this.endDateInput.classList.toggle('disabled', !isLongerThanDay);
        }

        // Contacts / organizations are normalized — rendered + managed by the
        // contacts panel (event-contacts-panel.js) via the contacts API.
        this.currentEventId = data.id;
        if (window.EventContactsPanel) {
            window.EventContactsPanel.render(data.id, data);
        }
        this.setFieldValue('v2-expected-attendees', data.expected_attendees);

        // Primary staffer (optional)
        const psInput = document.getElementById('v2-primary-staff');
        if (psInput && data.primary_staff !== undefined) psInput.value = data.primary_staff || '';
        this.applyStaffStars();

        // Status - ensure the current status option exists in the custom dropdown
        if (this.statusMenu && data.status) {
            // Check if the status option exists in the dropdown menu
            const existingOption = this.statusMenu.querySelector(`.v2-status-dropdown-option[data-value="${data.status}"]`);

            // If status doesn't exist (was deleted), add it as a "removed" option
            if (!existingOption) {
                const removedOption = document.createElement('div');
                removedOption.className = `v2-status-dropdown-option status-${data.status} inactive`;
                removedOption.dataset.value = data.status;
                removedOption.textContent = `${data.status} (Removed)`;
                removedOption.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.selectStatus(data.status, removedOption.textContent.trim());
                });
                this.statusMenu.appendChild(removedOption);
                console.log(`EventEditingModalV2: Added missing status option: ${data.status}`);
            }

            // Find the label for this status
            const statusOption = this.statusMenu.querySelector(`.v2-status-dropdown-option[data-value="${data.status}"]`);
            const statusLabel = statusOption?.textContent?.trim() || data.status;

            // Update hidden input
            if (this.statusValueInput) {
                this.statusValueInput.value = data.status;
            }

            // Update trigger text and styling
            if (this.statusTrigger) {
                const statusText = this.statusTrigger.querySelector('.v2-status-text');
                if (statusText) {
                    statusText.textContent = statusLabel;
                }
                this.statusTrigger.className = 'v2-status-select';
                this.statusTrigger.classList.add(`status-${data.status}`);
            }

            // Update selected state in menu
            this.statusMenu.querySelectorAll('.v2-status-dropdown-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === data.status);
            });

            // Store original status for comparison
            this._originalStatus = data.status;
        }
        // Tags
        if (Array.isArray(data.tags)) {
            // Clear existing tags first
            this.tagsContainer?.querySelectorAll('.v2-tag').forEach(tag => tag.remove());
            data.tags.forEach(tag => this.addTag?.(tag));
        }

        // Assigned staff (Staff & Review tab)
        if (Array.isArray(data.staff)) {
            this.renderAssignedStaff(data.staff);
        }

        // Update time display
        this.updateTimeDisplay();
    }

    setFieldValue(fieldId, value) {
        const field = document.getElementById(fieldId);
        if (field && value !== undefined && value !== null) {
            field.value = value;
        }
    }

    setDropdownValue(dropdownId, value) {
        // Set hidden input value
        const hiddenInput = document.getElementById(`${dropdownId}-value`);
        if (hiddenInput) {
            hiddenInput.value = value || '';
        }

        // Find the wrapper and update trigger text
        const wrapper = document.querySelector(`.v2-dropdown-wrapper[data-dropdown-id="${dropdownId}"]`);
        if (!wrapper) return;

        const trigger = wrapper.querySelector('.v2-dropdown-trigger');
        const menu = wrapper.querySelector('.v2-dropdown-menu');
        const triggerText = trigger?.querySelector('.v2-dropdown-text');

        if (!menu || !triggerText) return;

        // Find matching option and get its label
        const options = menu.querySelectorAll('.v2-dropdown-option');
        let selectedLabel = '';

        options.forEach(option => {
            const optionValue = option.dataset.value;
            const isSelected = optionValue === (value || '');
            option.classList.toggle('selected', isSelected);
            if (isSelected) {
                selectedLabel = option.textContent.trim();
            }
        });

        // Update trigger text
        if (selectedLabel) {
            triggerText.textContent = selectedLabel;
        }
    }

    resetForm() {
        this.form?.reset();

        // Clear tags
        this.tagsContainer?.querySelectorAll('.v2-tag').forEach(tag => tag.remove());

        // Reset time toggle
        this.singleEventBtn?.click();

        // Reset status
        if (this.statusTrigger && this.statusValueInput) {
            this.statusValueInput.value = 'received';
            const statusText = this.statusTrigger.querySelector('.v2-status-text');
            if (statusText) {
                statusText.textContent = 'Received';
            }
            this.statusTrigger.className = 'v2-status-select status-received';
            // Reset selected state in menu
            this.statusMenu?.querySelectorAll('.v2-status-dropdown-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.value === 'received');
            });
        }

        // Reset generic dropdowns to first option
        this.setDropdownValue('v2-event-type', '');
        this.setDropdownValue('v2-event-format', '');

        // Clear approval routing
        this.clearApprovalRouting();

        // Clear assigned staff
        this.renderAssignedStaff([]);

        // Switch to first tab
        document.getElementById('v2-event-details-tab')?.click();
    }

    // =========================================================================
    // Utility Methods
    // =========================================================================

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    reinitialize() {
        console.log('EventEditingModalV2: Reinitializing...');

        // Clear timeouts
        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
            this.autoSaveTimeout = null;
        }

        this.isSaving = false;
        this.cacheElements();

        // Recapture initial state
        setTimeout(() => {
            this.lastSavedData = this.collectFormData();
            console.log('EventEditingModalV2: Reinitialized');
        }, 100);
    }

    // =========================================================================
    // Human Review Mode
    // =========================================================================

    /**
     * Field ID to field name mapping for review mode
     */
    static FIELD_MAPPING = {
        'v2-title': 'title',
        'v2-event-type': 'type',
        'v2-event-format': 'format',
        'v2-start-date': 'start_date',
        'v2-start-time': 'start_time',
        'v2-end-date': 'end_date',
        'v2-end-time': 'end_time',
        'v2-location': 'location',
        'v2-description': 'description',
        // group / point_of_contact_* are normalized (managed by the contacts
        // panel), no longer mapped to a text input here.
        'v2-expected-attendees': 'expected_attendees'
    };

    // Contacts/orgs "link existing" + "create new" buttons, locked while the
    // event is in human review (the directory is written only on completion).
    static REVIEW_LOCKED_ADD_BTNS = [
        'v2-contact-add-btn', 'v2-contact-new-btn',
        'v2-org-add-btn', 'v2-org-new-btn',
    ];

    /**
     * Initialize review mode with extracted field data
     * @param {Object} extractedFields - Field data from server
     */
    initializeReviewMode(extractedFields, changeSuggestions = null) {
        const hasChangeSuggestions = Array.isArray(changeSuggestions) && changeSuggestions.length > 0;
        if ((!extractedFields || Object.keys(extractedFields).length === 0) && !hasChangeSuggestions) {
            console.log('EventEditingModalV2: Nothing to review, skipping review mode');
            return;
        }
        extractedFields = extractedFields || {};

        // If already in review mode, clean up first to prevent duplicate UI elements
        if (this.isReviewMode || this.progressBar) {
            console.log('EventEditingModalV2: Review mode already active, cleaning up before re-init');
            this.progressBar?.destroy();
            this.progressBar = null;
        }

        console.log('EventEditingModalV2: Initializing review mode', extractedFields);

        this.isReviewMode = true;
        this.extractedFields = extractedFields;

        // Add review mode class to modal
        this.container?.classList.add('v2-review-mode');

        // Force email panel visible during review
        if (!this.isEmailPanelVisible && this.showEmailBtn) {
            this.showEmailBtn.click();
        }

        // Disable certain features during review
        this.lockFeaturesForReview();

        // Create reviewable field wrappers for each extracted field
        for (const [fieldName, fieldData] of Object.entries(extractedFields)) {
            const fieldId = this.getFieldIdByName(fieldName);
            if (fieldId) {
                this.reviewableFields[fieldName] = new ReviewableField(
                    fieldId,
                    fieldName,
                    fieldData,
                    this
                );
            }
        }

        // Email change-request review rows (same review surface; only the
        // fields the email changed become reviewable). Always reset first —
        // stale rows from a previously opened event must never gate THIS
        // event's completion.
        if (window.EventChangeReview) {
            if (hasChangeSuggestions) {
                window.EventChangeReview.init(this, changeSuggestions);
            } else {
                window.EventChangeReview.destroy();
            }
        }

        // Create progress bar
        this.progressBar = new ReviewProgressBar(this);
        this.updateReviewProgress();

        // Create confirm dialog (lazy, only created once)
        if (!this.confirmDialog) {
            this.confirmDialog = new ReviewConfirmDialog(this);
        }

        // Set up keyboard shortcut for accept all (Ctrl+Shift+A)
        this.boundHandlers.acceptAllShortcut = (e) => {
            if (e.ctrlKey && e.shiftKey && e.key === 'A') {
                e.preventDefault();
                this.acceptAllFields();
            }
        };
        document.addEventListener('keydown', this.boundHandlers.acceptAllShortcut);

        // Don't auto-focus any field - let user click where they want

        console.log('EventEditingModalV2: Review mode initialized');
    }

    /**
     * Get field ID from field name
     */
    getFieldIdByName(fieldName) {
        for (const [fieldId, name] of Object.entries(EventEditingModalV2.FIELD_MAPPING)) {
            if (name === fieldName) {
                return fieldId;
            }
        }
        return null;
    }

    /**
     * Lock features that shouldn't be accessible during review
     */
    lockFeaturesForReview() {
        const lockedTooltip = 'Complete human review first';

        // Mount the singleton tooltip the first time we need it.
        setupReviewLockedTooltip();
        this._reviewLocked = true;

        // Disable Staff & Review tab
        const staffTab = document.getElementById('v2-staff-review-tab');
        if (staffTab) {
            staffTab.classList.add('v2-tab-disabled');
            staffTab.setAttribute('aria-disabled', 'true');
            staffTab.setAttribute('data-review-locked-tooltip', lockedTooltip);
        }

        // Disable respond button in email toolbar (also re-applied whenever the
        // email pane is opened, since its toolbar may not exist yet here).
        this._lockRespondButton(true);

        // Gray out the "Repeats" option (recurrence is confirmed after review).
        this._setRecurrenceLocked(true);

        // Disable "Add Staff" button on Involved Parties tab
        const addStaffBtn = document.getElementById('v2-add-staff-btn');
        if (addStaffBtn) {
            addStaffBtn.disabled = true;
            addStaffBtn.setAttribute('data-review-locked-tooltip', lockedTooltip);
        }

        // Disable the contacts/orgs "link existing" + "create new" buttons —
        // the directory is only written once review completes.
        EventEditingModalV2.REVIEW_LOCKED_ADD_BTNS.forEach((id) => {
            const b = document.getElementById(id);
            if (b) {
                b.disabled = true;
                b.setAttribute('data-review-locked-tooltip', lockedTooltip);
            }
        });

        // Hide normal action bar, show review progress bar instead
        const actionBar = document.querySelector('.v2-action-bar');
        if (actionBar) {
            actionBar.classList.add('v2-hidden-during-review');
        }
    }

    /**
     * Unlock features after review is complete
     */
    unlockFeaturesAfterReview() {
        this._reviewLocked = false;

        // Re-enable Staff & Review tab
        const staffTab = document.getElementById('v2-staff-review-tab');
        if (staffTab) {
            staffTab.classList.remove('v2-tab-disabled');
            staffTab.removeAttribute('aria-disabled');
            staffTab.removeAttribute('data-review-locked-tooltip');
        }

        // Re-enable respond button
        this._lockRespondButton(false);

        // Re-enable the "Repeats" option.
        this._setRecurrenceLocked(false);

        // Re-enable "Add Staff" button on Involved Parties tab
        const addStaffBtn = document.getElementById('v2-add-staff-btn');
        if (addStaffBtn) {
            addStaffBtn.disabled = false;
            addStaffBtn.removeAttribute('data-review-locked-tooltip');
        }

        // Re-enable the contacts/orgs add + create buttons.
        EventEditingModalV2.REVIEW_LOCKED_ADD_BTNS.forEach((id) => {
            const b = document.getElementById(id);
            if (b) {
                b.disabled = false;
                b.removeAttribute('data-review-locked-tooltip');
            }
        });

        // Show action bar again
        const actionBar = document.querySelector('.v2-action-bar');
        if (actionBar) {
            actionBar.classList.remove('v2-hidden-during-review');
        }
    }

    /**
     * Lock/unlock the email-pane Respond button for human review. Grays it out
     * and attaches the same "Complete human review first" tooltip the Staff &
     * Review tab uses. Safe to call repeatedly (the toolbar may render lazily
     * when the email pane is first opened).
     */
    _lockRespondButton(locked) {
        const respondBtn = document.querySelector('.v2-email-respond-btn');
        if (!respondBtn) return;
        if (locked) {
            respondBtn.disabled = true;
            respondBtn.classList.add('v2-btn-disabled');
            respondBtn.setAttribute('data-review-locked-tooltip', 'Complete human review first');
        } else {
            respondBtn.disabled = false;
            respondBtn.classList.remove('v2-btn-disabled');
            respondBtn.removeAttribute('data-review-locked-tooltip');
        }
    }

    /**
     * Handle field review action (accept/reject/undo)
     */
    async handleFieldReview(fieldName, action) {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') {
            console.warn('EventEditingModalV2: Cannot review field without event ID');
            return;
        }

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/review-field/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    field: fieldName,
                    action: action
                }),
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Field review result', result);
            this._didMutate = true; // a field review changed server state → refresh on close

            // Update extracted fields data
            if (this.extractedFields[fieldName]) {
                this.extractedFields[fieldName].status = action === 'undo_reject' ? 'pending' :
                    (action === 'accept' ? 'accepted' : 'rejected');
            }

            // Update progress
            this.updateReviewProgress();

            // Check if review is complete
            if (this.isReviewComplete()) {
                this.completeReviewMode();
            }

        } catch (error) {
            console.error('EventEditingModalV2: Field review error', error);
        }
    }

    /**
     * Accept all remaining pending fields (hidden feature: Ctrl+Shift+A)
     */
    async acceptAllFields() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        console.log('EventEditingModalV2: Accepting all fields');

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/accept-all/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            // Update all pending fields to accepted
            for (const [fieldName, field] of Object.entries(this.reviewableFields)) {
                if (field.status === 'pending') {
                    field.status = 'accepted';
                    field.updateVisualState();
                }
                if (this.extractedFields[fieldName]) {
                    this.extractedFields[fieldName].status = 'accepted';
                }
            }

            this.updateReviewProgress();
            this.completeReviewMode();

        } catch (error) {
            console.error('EventEditingModalV2: Accept all error', error);
        }
    }

    /**
     * Jump to the next unreviewed field (works across tabs and with dropdowns)
     */
    jumpToNextUnreviewedField() {
        // Bail out entirely if review is no longer active.
        if (!this.isReviewMode) return;

        // Field order with their associated tabs
        const fieldConfig = [
            { name: 'title', tab: null }, // Header, no tab switch needed
            { name: 'group', tab: null }, // Header, no tab switch needed
            { name: 'start_date', tab: null }, // Date section, no tab
            { name: 'start_time', tab: null },
            { name: 'end_date', tab: null },
            { name: 'end_time', tab: null },
            { name: 'location', tab: 'event-details' },
            { name: 'type', tab: 'event-details' },
            { name: 'format', tab: 'event-details' },
            { name: 'duration', tab: 'event-details' },
            { name: 'description', tab: 'event-details' },
            // point_of_contact_* are normalized (contacts panel) — not inline fields.
            { name: 'expected_attendees', tab: 'involved-parties' }
        ];

        // Start searching AFTER the current position and wrap around, so the
        // jump always advances in the set order and loops back to the start —
        // no matter which field/tab the user begins on. "Current position" is
        // the focused reviewable field, falling back to the last field we jumped
        // to (the button itself takes focus on click, so activeElement alone
        // isn't enough for repeated button presses).
        const n = fieldConfig.length;
        const active = document.activeElement;
        let currentIndex = fieldConfig.findIndex(c => {
            const f = this.reviewableFields[c.name];
            return f && f.element === active;
        });
        if (currentIndex === -1 && this._lastJumpedFieldName) {
            currentIndex = fieldConfig.findIndex(c => c.name === this._lastJumpedFieldName);
        }

        for (let step = 1; step <= n; step++) {
            const config = fieldConfig[(currentIndex + step + n) % n];
            const field = this.reviewableFields[config.name];
            if (field && field.status === 'pending') {
                // Tab switch + panel activation are both synchronous DOM
                // updates, so the target field is focusable immediately
                // afterwards. We deliberately do NOT setTimeout: that's what
                // was causing rapid clicks to queue racing focus+scroll
                // animations. Doing it inline means each click advances
                // exactly one field, cleanly, even at full clicking speed.
                if (config.tab) {
                    this.switchToTab(config.tab);
                }
                this._lastJumpedFieldName = config.name;

                const el = field.element;
                if (el) {
                    // preventScroll on focus, then do an explicit INSTANT
                    // scroll. The site sets `scroll-behavior: smooth` on
                    // <html> (main.css), so `behavior: 'auto'` would defer
                    // to that and animate. Rapid clicks would stack smooth-
                    // scroll animations and the cursor would appear to
                    // bounce between the last two fields as the animations
                    // compete. 'instant' overrides the CSS so each click
                    // snaps cleanly.
                    try {
                        el.focus({ preventScroll: true });
                    } catch (_) {
                        el.focus();
                    }
                    try {
                        el.scrollIntoView({ behavior: 'instant', block: 'center' });
                    } catch (_) {
                        // Older browsers reject 'instant'; fall back to a
                        // plain scrollIntoView (still beats smooth queueing).
                        el.scrollIntoView({ block: 'center' });
                    }
                }
                return;
            }
        }

        // No pending scalar field left — continue into the contact/organization
        // review cards. They are part of the SAME Jump-to-Next system: the cards
        // module focuses the next pending card (Accept button) or unreviewed card
        // field on the Involved Parties tab.
        if (window.EventReviewCards && typeof window.EventReviewCards.focusNext === 'function') {
            this.switchToTab('involved-parties');
            if (window.EventReviewCards.focusNext()) {
                this._lastJumpedFieldName = null;
                return;
            }
        }

        // Then any email change-request rows (Event Details tab).
        if (window.EventChangeReview && typeof window.EventChangeReview.focusNext === 'function'
                && window.EventChangeReview.hasPending()) {
            this.switchToTab('event-details');
            if (window.EventChangeReview.focusNext()) {
                this._lastJumpedFieldName = null;
                return;
            }
        }

        this._lastJumpedFieldName = null;
        console.log('EventEditingModalV2: No more pending fields');
    }

    /**
     * Switch to a specific tab
     */
    switchToTab(tabName) {
        const tabMap = {
            'event-details': 'v2-event-details-tab',
            'involved-parties': 'v2-involved-parties-tab',
            'staff-review': 'v2-staff-review-tab'
        };

        const tabId = tabMap[tabName];
        if (tabId) {
            const tabButton = document.getElementById(tabId);
            if (tabButton && !tabButton.classList.contains('active')) {
                tabButton.click();
            }
        }
    }

    /**
     * Update the review progress bar
     */
    updateReviewProgress() {
        if (!this.progressBar) return;

        let total = Object.keys(this.reviewableFields).length;
        let reviewed = 0;

        for (const field of Object.values(this.reviewableFields)) {
            if (field.status === 'accepted' || field.status === 'rejected') {
                reviewed++;
            }
        }

        // Contact/organization review cards contribute their units too (each card
        // + each extracted field), so the progress bar covers the whole review.
        if (window.EventReviewCards && typeof window.EventReviewCards.counts === 'function') {
            const c = window.EventReviewCards.counts();
            total += c.total;
            reviewed += c.reviewed;
        }

        // Email change-request rows count toward the same bar.
        if (window.EventChangeReview && typeof window.EventChangeReview.counts === 'function') {
            const cr = window.EventChangeReview.counts();
            total += cr.total;
            reviewed += cr.reviewed;
        }

        this.progressBar.update(reviewed, total);
    }

    /**
     * Check if all fields have been reviewed
     */
    isReviewComplete() {
        for (const field of Object.values(this.reviewableFields)) {
            if (field.status === 'pending') {
                return false;
            }
        }
        // The review is only complete when the contact/org cards are done too.
        if (window.EventReviewCards && typeof window.EventReviewCards.hasPending === 'function'
                && window.EventReviewCards.hasPending()) {
            return false;
        }
        // ...and every email change request has a decision.
        if (window.EventChangeReview && typeof window.EventChangeReview.hasPending === 'function'
                && window.EventChangeReview.hasPending()) {
            return false;
        }
        return true;
    }

    /**
     * Exit review mode after all fields reviewed
     */
    completeReviewMode() {
        console.log('EventEditingModalV2: Review mode complete');

        this._didMutate = true; // review resolved the item → refresh on close
        this.isReviewMode = false;

        // Remove review mode class
        this.container?.classList.remove('v2-review-mode');

        // Unlock features
        this.unlockFeaturesAfterReview();

        // Remove progress bar
        this.progressBar?.destroy();
        this.progressBar = null;

        // Remove keyboard shortcut
        if (this.boundHandlers.acceptAllShortcut) {
            document.removeEventListener('keydown', this.boundHandlers.acceptAllShortcut);
        }

        // Don't destroy reviewable fields - keep visual indicators
        // Note: handleFieldReview API already saves the event with requires_human_review=False
        // so we don't need to call performAutoSave() here
    }

    /**
     * Clean up review mode completely (on modal close)
     */
    cleanupReviewMode() {
        // Destroy all reviewable field wrappers
        for (const field of Object.values(this.reviewableFields)) {
            field.destroy();
        }
        this.reviewableFields = {};
        this.extractedFields = {};

        // Destroy progress bar
        this.progressBar?.destroy();
        this.progressBar = null;

        // Remove review mode class
        this.container?.classList.remove('v2-review-mode');

        // Unlock features
        this.unlockFeaturesAfterReview();

        // Remove keyboard shortcut
        if (this.boundHandlers.acceptAllShortcut) {
            document.removeEventListener('keydown', this.boundHandlers.acceptAllShortcut);
        }

        this.isReviewMode = false;
    }

    /**
     * Get review status counts
     */
    getReviewCounts() {
        let total = 0;
        let reviewed = 0;
        let pending = 0;

        for (const field of Object.values(this.reviewableFields)) {
            total++;
            if (field.status === 'accepted' || field.status === 'rejected') {
                reviewed++;
            } else {
                pending++;
            }
        }

        return { total, reviewed, pending };
    }

    // =========================================================================
    // Email Highlighting
    // =========================================================================

    /**
     * Highlight text in email panel based on source location
     */
    highlightEmailText(sourceData) {
        if (!sourceData) return;

        // Clear existing highlights first
        this.clearEmailHighlights();

        const emailContent = document.querySelector('.v2-email-body-text');
        if (!emailContent) {
            console.warn('EventEditingModalV2: Email content container not found');
            return;
        }

        // Try exact index match first
        if (sourceData.start_index !== undefined && sourceData.end_index !== undefined) {
            const success = this.applyHighlightByIndex(
                emailContent,
                sourceData.start_index,
                sourceData.end_index
            );
            if (success) {
                this.scrollToHighlight();
                return;
            }
        }

        // Fall back to text snippet search
        if (sourceData.text_snippet) {
            const success = this.applyHighlightByText(emailContent, sourceData.text_snippet);
            if (success) {
                this.scrollToHighlight();
                return;
            }
        }

        console.warn('EventEditingModalV2: Could not highlight email text', sourceData);
    }

    /**
     * Apply highlight using character indices
     */
    applyHighlightByIndex(container, startIndex, endIndex) {
        const textContent = container.textContent;
        if (startIndex >= textContent.length || endIndex > textContent.length) {
            return false;
        }

        const targetText = textContent.substring(startIndex, endIndex);
        return this.applyHighlightByText(container, targetText);
    }

    /**
     * Apply highlight by searching for text
     */
    applyHighlightByText(container, searchText) {
        if (!searchText) return false;

        const walker = document.createTreeWalker(
            container,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        let node;
        while ((node = walker.nextNode())) {
            const index = node.textContent.indexOf(searchText);
            if (index !== -1) {
                // Split the text node and wrap the match in a highlight span
                const range = document.createRange();
                range.setStart(node, index);
                range.setEnd(node, index + searchText.length);

                const highlight = document.createElement('mark');
                highlight.className = 'v2-email-highlight';
                range.surroundContents(highlight);

                return true;
            }
        }

        return false;
    }

    /**
     * Scroll email panel to show highlighted text
     */
    scrollToHighlight() {
        const highlight = document.querySelector('.v2-email-highlight');
        const emailPanel = document.querySelector('.v2-email-panel');

        if (highlight && emailPanel) {
            highlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    /**
     * Remove all email highlights
     */
    clearEmailHighlights() {
        document.querySelectorAll('.v2-email-highlight').forEach(el => {
            const parent = el.parentNode;
            while (el.firstChild) {
                parent.insertBefore(el.firstChild, el);
            }
            parent.removeChild(el);
            parent.normalize(); // Merge adjacent text nodes
        });
    }

    // =========================================================================
    // Approval Routing
    // =========================================================================

    /**
     * Initialize approval routing UI elements and event handlers
     */
    initializeApprovalRouting() {
        // Cache approval routing elements
        this.approvalRoutingContainer = document.getElementById('v2-approval-routing');
        this.routingChain = document.getElementById('v2-routing-chain');
        this.noRoutingSection = document.getElementById('v2-no-routing');
        this.approveBtn = document.getElementById('v2-approve-btn');
        this.sendBackBtn = document.getElementById('v2-send-back-btn');
        this.sendBackComment = document.getElementById('v2-send-back-comment');
        this.sendBackReason = document.getElementById('v2-send-back-reason');
        this.cancelSendBackBtn = document.getElementById('v2-cancel-send-back');
        this.confirmSendBackBtn = document.getElementById('v2-confirm-send-back');
        this.configureRoutingBtn = document.getElementById('v2-configure-routing-btn');
        this.assignedStaffList = document.getElementById('v2-assigned-staff-list');

        // Routing builder popup elements
        this.routingPopupOverlay = document.getElementById('v2-routing-popup-overlay');
        this.routingPopupClose = document.getElementById('v2-routing-popup-close');
        this.routingStagesContainer = document.getElementById('v2-routing-stages');
        this.addStageBtn = document.getElementById('v2-add-stage-btn');
        this.routingCancelBtn = document.getElementById('v2-routing-cancel');
        this.routingSaveBtn = document.getElementById('v2-routing-save');
        this.removeRoutingBtn = document.getElementById('v2-remove-routing-btn');
        console.log('EventEditingModalV2: removeRoutingBtn found:', !!this.removeRoutingBtn);

        // Routing preset (saved routes) elements
        this.routingPresetsDropdown = document.getElementById('v2-routing-presets-dropdown');
        this.routingPresetsTrigger = document.getElementById('v2-routing-presets-trigger');
        this.routingPresetsMenu = document.getElementById('v2-routing-presets-menu');
        this.routingPresetsList = document.getElementById('v2-routing-presets-list');
        this.routingPresetsLabel = document.getElementById('v2-routing-presets-label');
        this.routingPresetsSave = document.getElementById('v2-routing-presets-save');

        // Routing builder state
        this.routingStages = [];

        // Routing preset state
        this.routingPresets = [];
        this.activeRoutingPresetId = null;
        this._routingPresetsMenuOpen = false;

        // Bind event handlers
        this.approveBtn?.addEventListener('click', () => this.handleApprove());
        this.sendBackBtn?.addEventListener('click', () => this.showSendBackComment());
        this.cancelSendBackBtn?.addEventListener('click', () => this.hideSendBackComment());
        this.confirmSendBackBtn?.addEventListener('click', () => this.handleSendBack());
        this.configureRoutingBtn?.addEventListener('click', () => this.openRoutingBuilder());

        // Routing builder popup event handlers
        this.addStageBtn?.addEventListener('click', () => this.addRoutingStage());
        this.routingPopupClose?.addEventListener('click', () => this.closeRoutingBuilder());
        this.routingCancelBtn?.addEventListener('click', () => this.closeRoutingBuilder());
        this.routingSaveBtn?.addEventListener('click', () => this.saveRoutingConfig());

        // Saved-routes dropdown toggle
        this.routingPresetsTrigger?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleRoutingPresetsMenu();
        });

        // Close the saved-routes dropdown when the mouse leaves it (mirrors the
        // filter-presets dropdown behavior).
        this.routingPresetsDropdown?.addEventListener('mouseleave', () => {
            if (this._routingPresetsMenuOpen) this.closeRoutingPresetsMenu();
        });

        // Click backdrop to close the routing builder popup. (Escape is handled
        // centrally by the modal's single Escape authority.)
        this.routingPopupOverlay?.addEventListener('click', (e) => {
            if (e.target === this.routingPopupOverlay) {
                this.closeRoutingBuilder();
            }
        });

        // Remove routing button handler (scheduler only)
        if (this.removeRoutingBtn) {
            this.removeRoutingBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('EventEditingModalV2: Remove routing button clicked');
                this.handleRemoveRouting();
            });

            // Portaled hover tooltip — centered above the button and on the top
            // layer, so it never clips against the modal's edges.
            this.removeRoutingBtn.addEventListener('mouseenter', () => {
                this._showFloatingTooltip(
                    this.removeRoutingBtn,
                    this.removeRoutingBtn.getAttribute('data-tooltip') || 'Remove Routing'
                );
            });
            this.removeRoutingBtn.addEventListener('mouseleave', () => this._hideFloatingTooltip());
        }

        // Also use event delegation on the modal container as fallback
        // Only add if not already added (guard against duplicate listeners)
        if (this.container && !this._removeRoutingDelegationAdded) {
            this._removeRoutingDelegationAdded = true;
            console.log('EventEditingModalV2: Adding event delegation for remove routing button');
            this.container.addEventListener('click', (e) => {
                const btn = e.target.closest('#v2-remove-routing-btn');
                if (btn) {
                    e.preventDefault();
                    e.stopPropagation();
                    console.log('EventEditingModalV2: Remove routing button clicked (delegation)');
                    this.handleRemoveRouting();
                }
            });
        }

        // Review button handler
        this.reviewBtn?.addEventListener('click', () => this.handleReviewButtonClick());
    }

    /**
     * Initialize approval popup event handlers
     */
    initializeApprovalPopup() {
        // Re-cache approval popup elements (needed when loaded via AJAX)
        this.recacheApprovalPopupElements();

        // Prevent double-binding event handlers. Bind ONCE per instance.
        if (this._approvalPopupInitialized) {
            console.log('EventEditingModalV2: Approval popup already initialized, skipping event binding');
            return;
        }
        // Only mark initialized + bind once the popup is actually in the DOM.
        // (The constructor may run before/after injection depending on the load
        // path; binding before the elements exist would leave nothing bound and
        // force a rebind later, which is how handlers got attached twice.)
        if (!this.approvalPopupOverlay || !this.approvalPopupApprove) {
            return;
        }
        this._approvalPopupInitialized = true;

        // Close popup
        this.approvalPopupClose?.addEventListener('click', () => this.hideApprovalPopup());
        this.approvalPopupCancel?.addEventListener('click', () => this.hideApprovalPopup());

        // Click outside to close
        this.approvalPopupOverlay?.addEventListener('click', (e) => {
            if (e.target === this.approvalPopupOverlay) {
                this.hideApprovalPopup();
            }
        });

        // (Escape is handled centrally by the modal's single Escape authority.)

        // Approve button
        this.approvalPopupApprove?.addEventListener('click', () => this.submitApprovalFromPopup('approve'));

        // Send Back button
        this.approvalPopupSendBack?.addEventListener('click', () => this.submitApprovalFromPopup('send_back'));

        // Cancel Review button
        this.approvalPopupCancelReview?.addEventListener('click', () => this.handleCancelReview());
    }

    /**
     * Re-cache approval popup elements (call after AJAX load)
     */
    recacheApprovalPopupElements() {
        this.approvalPopupOverlay = document.getElementById('v2-approval-popup-overlay');
        this.approvalPopup = document.getElementById('v2-approval-popup');
        this.approvalPopupClose = document.getElementById('v2-approval-popup-close');
        this.approvalPopupTitle = document.getElementById('v2-approval-popup-title');
        this.approvalNotes = document.getElementById('v2-approval-notes');
        this.approvalPopupCancel = document.getElementById('v2-approval-popup-cancel');
        this.approvalPopupSendBack = document.getElementById('v2-approval-popup-send-back');
        this.approvalPopupApprove = document.getElementById('v2-approval-popup-approve');
        this.approvalPopupCancelSection = document.getElementById('v2-approval-popup-cancel-section');
        this.approvalPopupCancelReview = document.getElementById('v2-approval-popup-cancel-review');

        console.log('EventEditingModalV2: recacheApprovalPopupElements', {
            overlay: !!this.approvalPopupOverlay,
            popup: !!this.approvalPopup,
            approveBtn: !!this.approvalPopupApprove
        });
    }

    /**
     * Handle Review button click in action bar
     * If user can approve, show the approval popup
     * Otherwise, navigate to Staff & Review tab
     */
    handleReviewButtonClick() {
        const data = this.approvalRoutingData;

        // No pending approval for user → jump to Staff & Review tab
        if (!data?.can_user_approve) {
            document.getElementById('v2-staff-review-tab')?.click();
            return;
        }

        // Has pending approval → show the approval popup
        this.showApprovalPopup();
    }

    /**
     * Show the approval review popup
     */
    showApprovalPopup() {
        const data = this.approvalRoutingData;
        const isFirstApprover = data?.is_first_approver || false;

        console.log('EventEditingModalV2: showApprovalPopup', {
            isFirstApprover,
            can_user_approve: data?.can_user_approve,
            approvalRoutingData: data,
            hasOverlay: !!this.approvalPopupOverlay,
            overlayInDOM: !!document.getElementById('v2-approval-popup-overlay')
        });

        // If overlay not cached, try to find it in DOM
        if (!this.approvalPopupOverlay) {
            console.warn('EventEditingModalV2: Approval popup overlay not cached, attempting to find in DOM');
            this.recacheApprovalPopupElements();
        }

        if (!this.approvalPopupOverlay) {
            console.error('EventEditingModalV2: Approval popup overlay not found!');
            return;
        }

        // Clear previous notes
        if (this.approvalNotes) {
            this.approvalNotes.value = '';
        }

        // Always offer Send Back when it's the user's turn. The popup only opens
        // for users who can act on the event, so every reviewer (including the
        // creator after a send-back) gets Approve / Send Back / Cancel.
        if (this.approvalPopupSendBack) {
            this.approvalPopupSendBack.style.display = 'inline-flex';
        }

        // Show/hide cancel review option
        // Creator (first approver) sees this option when it's their turn
        if (this.approvalPopupCancelSection) {
            if (isFirstApprover && data?.can_user_approve) {
                this.approvalPopupCancelSection.style.display = 'block';
            } else {
                this.approvalPopupCancelSection.style.display = 'none';
            }
        }

        // Update title based on context
        if (this.approvalPopupTitle) {
            this.approvalPopupTitle.textContent = 'Review Event';
        }

        // Show popup
        this.approvalPopupOverlay?.classList.add('visible');
    }

    /**
     * Hide the approval popup
     */
    hideApprovalPopup() {
        this.approvalPopupOverlay?.classList.remove('visible');
    }

    /**
     * Submit approval decision from popup
     */
    async submitApprovalFromPopup(action) {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        const comment = this.approvalNotes?.value?.trim() || '';

        // Notes are optional for sending back.

        try {
            // Disable buttons
            if (this.approvalPopupApprove) {
                this.approvalPopupApprove.disabled = true;
            }
            if (this.approvalPopupSendBack) {
                this.approvalPopupSendBack.disabled = true;
            }

            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/approval-routing/approve/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    action: action,
                    comment: comment
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to submit approval');
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Approval submitted from popup', result);
            this._didMutate = true; // approval/send-back resolved the item → refresh on close

            // Hide popup
            this.hideApprovalPopup();

            // Reload approval routing to show updated state
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                const msg = action === 'approve' ? 'Approval submitted successfully' : 'Event sent back for review';
                showMessage(msg, 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to submit approval from popup', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to submit approval', 'error');
            }
        } finally {
            // Re-enable buttons
            if (this.approvalPopupApprove) {
                this.approvalPopupApprove.disabled = false;
            }
            if (this.approvalPopupSendBack) {
                this.approvalPopupSendBack.disabled = false;
            }
        }
    }

    /**
     * Handle cancel review (removes entire routing)
     */
    async handleCancelReview() {
        if (!confirm('Cancel this review? This will remove the entire approval routing.')) {
            return;
        }

        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/approval-routing/cancel/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || errorData.message || 'Failed to cancel review');
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Review cancelled', result);

            // Hide popup
            this.hideApprovalPopup();

            // Reload approval routing to show cleared state
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                showMessage('Review cancelled and routing removed', 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to cancel review', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to cancel review', 'error');
            }
        }
    }

    /**
     * Load approval routing data for the current event
     */
    async loadApprovalRouting(eventId) {
        if (!eventId || eventId === 'new') {
            this.clearApprovalRouting();
            return;
        }

        try {
            const response = await fetch(`/api/events/${eventId}/approval-routing/`, {
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                if (response.status === 404) {
                    // No routing configured
                    this.clearApprovalRouting();
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            console.log('EventEditingModalV2: loadApprovalRouting - raw response:', JSON.stringify(data, null, 2));
            console.log('EventEditingModalV2: has_routing:', data.has_routing, 'stages:', data.stages?.length || 0);
            this.approvalRoutingData = data;
            this.renderApprovalRouting(data);

        } catch (error) {
            console.error('EventEditingModalV2: Failed to load approval routing', error);
            this.clearApprovalRouting();
        }
    }

    /**
     * Clear/reset approval routing UI
     */
    clearApprovalRouting() {
        this.approvalRoutingData = null;

        if (this.noRoutingSection) {
            this.noRoutingSection.style.display = 'flex';
        }
        if (this.routingChain) {
            this.routingChain.style.display = 'none';
            this.routingChain.innerHTML = '';
        }
        // Hide Remove Routing button when no routing exists
        if (this.removeRoutingBtn) {
            this.removeRoutingBtn.style.display = 'none';
        }
        // Update Review button to show "No Routing" state
        this.updateReviewButton({ has_routing: false });
    }

    /**
     * Render the approval routing chain UI
     */
    renderApprovalRouting(data) {
        console.log('EventEditingModalV2: renderApprovalRouting data:', data);

        // Handle both API formats:
        // - Direct format: { has_routing, is_complete, current_stage, stages }
        // - Nested format: { routing: { stages }, is_complete, ... }
        const stages = data?.stages || data?.routing?.stages || [];

        if (!data || !data.has_routing || stages.length === 0) {
            this.clearApprovalRouting();
            return;
        }

        const { current_stage, is_complete } = data;

        // Hide empty state, show routing chain
        if (this.noRoutingSection) {
            this.noRoutingSection.style.display = 'none';
        }
        if (this.routingChain) {
            this.routingChain.style.display = 'block';
        }

        // Build routing chain HTML as a compact table
        let html = '';

        // Build table rows from stages and approvers
        html += `<table class="v2-routing-table">
            <thead>
                <tr>
                    <th class="v2-rt-col-num">#</th>
                    <th class="v2-rt-col-reviewer">Reviewer</th>
                    <th class="v2-rt-col-status">Status</th>
                    <th class="v2-rt-col-comment">Comment</th>
                </tr>
            </thead>
            <tbody>`;

        // Check if current user can approve (to show Review Now button)
        const canUserApprove = data.can_user_approve || false;

        stages.forEach((stage) => {
            const isActive = current_stage === stage.stage_id;
            const approvers = stage.approvers || [];

            approvers.forEach((approver, approverIndex) => {
                const approverStatus = approver.status || 'pending';
                const isCurrentTurn = isActive && approverStatus === 'pending';
                // Check if this approver is the current user (API includes is_current_user flag)
                const isCurrentUser = approver.is_current_user || false;

                // Row class based on status
                let rowClass = 'v2-rt-row';
                if (approverStatus === 'approved') {
                    rowClass += ' v2-rt-approved';
                } else if (approverStatus === 'sent_back') {
                    rowClass += ' v2-rt-sent-back';
                } else if (isCurrentTurn) {
                    rowClass += ' v2-rt-current';
                }

                // Status icon and text
                // First stage (order 0) is the creator - show "Started" instead of "Approved"
                const isFirstStage = stage.order === 0;
                let statusHtml = '';
                if (approverStatus === 'approved') {
                    const statusLabel = isFirstStage ? 'Started' : 'Approved';
                    statusHtml = `<span class="v2-rt-status v2-rt-status-approved">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        ${statusLabel}
                    </span>`;
                } else if (approverStatus === 'sent_back') {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-sent-back">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path></svg>
                        Sent Back
                    </span>`;
                } else if (isCurrentTurn) {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-current">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        Awaiting
                    </span>`;
                } else {
                    statusHtml = `<span class="v2-rt-status v2-rt-status-pending">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle></svg>
                        Pending
                    </span>`;
                }

                // Stage number (only show for first approver in stage, or always for single approvers)
                const stageNum = approverIndex === 0 ? stage.order : '';
                const stageNumClass = approverIndex === 0 ? 'v2-rt-stage-num' : 'v2-rt-stage-num v2-rt-stage-continuation';

                // Comment column - show Review button if it's the current user's turn
                let commentHtml = '';
                if (isCurrentTurn && isCurrentUser && canUserApprove) {
                    commentHtml = `<button type="button" class="v2-rt-review-btn" data-action="review">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="9 11 12 14 22 4"></polyline>
                            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
                        </svg>
                        Review
                    </button>`;
                } else if (approver.comment) {
                    const escapedComment = this.escapeHtml(approver.comment);
                    commentHtml = `<span class="v2-rt-comment-text" title="${escapedComment}">${escapedComment}</span>`;
                }

                html += `
                    <tr class="${rowClass}">
                        <td class="${stageNumClass}">${stageNum}</td>
                        <td class="v2-rt-reviewer">${this.escapeHtml(approver.name)}</td>
                        <td class="v2-rt-status-cell">${statusHtml}</td>
                        <td class="v2-rt-comment">${commentHtml}</td>
                    </tr>
                `;
            });
        });

        html += `</tbody></table>`;

        if (this.routingChain) {
            this.routingChain.innerHTML = html;

            // Bind Review Now button click handler
            const reviewBtn = this.routingChain.querySelector('.v2-rt-review-btn');
            if (reviewBtn) {
                reviewBtn.addEventListener('click', () => this.showApprovalPopup());
            }
        }

        // Also add a "Reconfigure" button if routing exists
        if (this.configureRoutingBtn) {
            this.configureRoutingBtn.textContent = 'Edit Routing';
        }

        // Show Remove Routing button if user can edit routing (scheduler) and routing exists
        if (this.removeRoutingBtn) {
            const canEditRouting = data?.can_edit_routing || false;
            console.log('EventEditingModalV2: renderApprovalRouting - can_edit_routing:', canEditRouting, 'button:', this.removeRoutingBtn);
            this.removeRoutingBtn.style.display = canEditRouting ? 'inline-flex' : 'none';
        } else {
            console.log('EventEditingModalV2: renderApprovalRouting - removeRoutingBtn not found');
        }

        // Update Review button in action bar
        this.updateReviewButton(data);
    }

    /**
     * Update Review button state in action bar
     * Button always says "Review" but style changes based on routing
     */
    updateReviewButton(data) {
        const canUserApprove = data?.can_user_approve || false;

        // Only surface the Review action when it's actually the user's turn to
        // review this event. Otherwise hide the whole group so Show Email and
        // Event status expand to fill the action bar.
        if (this.reviewBtnWrapper) {
            this.reviewBtnWrapper.style.display = canUserApprove ? '' : 'none';
        }

        if (!this.reviewBtn) return;

        const hasRouting = data?.has_routing || false;
        const isComplete = data?.is_complete || false;

        // Button always says "Review"
        if (this.reviewBtnText) {
            this.reviewBtnText.textContent = 'Review';
        }

        // Update style based on state
        if (!hasRouting) {
            // Stay enabled so clicking jumps to the Staff & Review tab where
            // routing can be configured. (handleReviewButtonClick handles it.)
            this.reviewBtn.disabled = false;
            this.reviewBtn.classList.remove('v2-needs-action');
        } else if (canUserApprove && !isComplete) {
            this.reviewBtn.disabled = false;
            this.reviewBtn.classList.add('v2-needs-action');
        } else {
            this.reviewBtn.disabled = false;
            this.reviewBtn.classList.remove('v2-needs-action');
        }
    }

    /**
     * Focus handling when the modal opens. By default nothing is focused: focus
     * lands on the modal shell so it can't sit on a control behind the overlay,
     * but no tab or field is highlighted. For a routing review event — one where
     * it's the user's turn to approve, so the footer Review button is shown —
     * focus moves to that Review button instead. The button's actionable state
     * is set when routing data renders, which can be a beat after open, so we
     * poll a few frames; if the user moves focus first, we bail.
     */
    focusModalOnOpen() {
        const overlayEl = this.overlay || document.getElementById('v2-modal-overlay');
        if (!overlayEl || !overlayEl.classList.contains('active')) return;
        const cont = this.container || document.getElementById('v2-modal-container');
        if (!cont) return;

        if (!cont.hasAttribute('tabindex')) cont.setAttribute('tabindex', '-1');
        cont.focus();

        const wrapper = this.reviewBtnWrapper || document.getElementById('v2-review-btn-wrapper');
        const reviewBtn = this.reviewBtn || document.getElementById('v2-review-btn');
        let tries = 30;
        const tryFocusReview = () => {
            if (!overlayEl.classList.contains('active')) return;
            // Bail if the user already moved focus into a field/control themselves.
            const ae = document.activeElement;
            if (ae && ae !== cont && cont.contains(ae)) return;
            const actionable = wrapper && getComputedStyle(wrapper).display !== 'none' &&
                reviewBtn && !reviewBtn.disabled &&
                (reviewBtn.offsetWidth > 0 || reviewBtn.offsetHeight > 0);
            if (actionable) {
                reviewBtn.focus();
                return;
            }
            if (tries-- > 0) requestAnimationFrame(tryFocusReview);
        };
        requestAnimationFrame(tryFocusReview);
    }

    /**
     * Render assigned staff list (called from populateForm)
     * This populates both the Involved Parties tab and syncs to Staff & Review tab
     */
    renderAssignedStaff(staffList) {
        // Render in Involved Parties tab
        if (this.staffContainer) {
            // Clear existing pills (but not the dropdown wrapper)
            this.staffContainer.querySelectorAll('.v2-staff-pill').forEach(pill => pill.remove());

            if (staffList && staffList.length > 0) {
                const dropdownWrapper = this.staffContainer.querySelector('.v2-staff-dropdown-wrapper');
                staffList.forEach(staff => {
                    const name = staff.name || staff;
                    const pill = document.createElement('div');
                    pill.className = 'v2-staff-pill';
                    pill.innerHTML = `
                        <span class="v2-staff-name">${this.escapeHtml(name)}</span>
                        <button type="button" class="v2-staff-pill-remove" aria-label="Remove">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    `;

                    // Insert before dropdown wrapper
                    if (dropdownWrapper) {
                        this.staffContainer.insertBefore(pill, dropdownWrapper);
                    } else {
                        this.staffContainer.appendChild(pill);
                    }

                    // Bind remove handler
                    pill.querySelector('.v2-staff-pill-remove')?.addEventListener('click', () => {
                        this.removeStaffFromEvent(name, 'involved-parties');
                    });
                });
            }
        }

        // Sync to Staff & Review tab
        const names = staffList ? staffList.map(s => s.name || s) : [];
        this.renderReviewStaffList(names);
    }

    /**
     * Show send back comment textarea
     */
    showSendBackComment() {
        if (this.sendBackComment) {
            this.sendBackComment.style.display = 'block';
            this.sendBackReason?.focus();
        }
    }

    /**
     * Hide send back comment textarea
     */
    hideSendBackComment() {
        if (this.sendBackComment) {
            this.sendBackComment.style.display = 'none';
        }
        if (this.sendBackReason) {
            this.sendBackReason.value = '';
        }
    }

    /**
     * Handle approve button click
     */
    async handleApprove() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        try {
            this.approveBtn.disabled = true;
            this.approveBtn.textContent = 'Approving...';

            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/approval-routing/approve/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ action: 'approve' })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to approve');
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Approval submitted', result);

            // Reload approval routing to show updated state
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                showMessage('Approval submitted successfully', 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to approve', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to submit approval', 'error');
            }
        } finally {
            if (this.approveBtn) {
                this.approveBtn.disabled = false;
                this.approveBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    Approve
                `;
            }
        }
    }

    /**
     * Handle send back button click
     */
    async handleSendBack() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        const comment = this.sendBackReason?.value?.trim() || '';
        // Notes are optional for sending back.

        try {
            this.confirmSendBackBtn.disabled = true;
            this.confirmSendBackBtn.textContent = 'Sending...';

            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/approval-routing/approve/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    action: 'send_back',
                    comment: comment
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to send back');
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Send back submitted', result);

            // Hide comment section and clear
            this.hideSendBackComment();

            // Reload approval routing to show updated state
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                showMessage('Event sent back for review', 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to send back', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to send back', 'error');
            }
        } finally {
            if (this.confirmSendBackBtn) {
                this.confirmSendBackBtn.disabled = false;
                this.confirmSendBackBtn.textContent = 'Confirm Send Back';
            }
        }
    }

    /**
     * Handle Remove Routing button click (scheduler only)
     * Removes the entire approval routing from the event
     */
    handleRemoveRouting() {
        console.log('EventEditingModalV2: handleRemoveRouting called');
        const eventId = this.form?.dataset?.eventId;
        if (!eventId) {
            console.error('EventEditingModalV2: No event ID for remove routing');
            return;
        }

        // App-styled confirm (matches the email tab's "Remove message" warning)
        this._confirmAction(
            'Remove approval routing',
            'This clears all approvals and the routing configuration.',
            'Remove',
            () => this._performRemoveRouting(eventId)
        );
    }

    /**
     * App-styled confirm popup, built lazily on <body> so it survives the
     * AJAX-loaded modal and centers on the viewport (mirrors email-composer's
     * _confirmRemove). Uses the same .v2-plain-popup style.
     */
    _ensureRoutingConfirmOverlay() {
        let overlay = document.getElementById('v2-routing-confirm-overlay');
        if (overlay) return overlay;

        overlay = document.createElement('div');
        overlay.className = 'v2-draft-prompt-overlay';
        overlay.id = 'v2-routing-confirm-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="v2-draft-prompt-popup v2-plain-popup">
                <div class="v2-draft-prompt-header">
                    <h3 id="v2-routing-confirm-title">Remove</h3>
                </div>
                <div class="v2-draft-prompt-body">
                    <p id="v2-routing-confirm-message" style="margin: 0; font-size: 13px; color: var(--v2-text-secondary, #64748b);"></p>
                </div>
                <div class="v2-draft-prompt-actions">
                    <button type="button" class="v2-btn-secondary" id="v2-routing-confirm-cancel">Cancel</button>
                    <button type="button" class="v2-confirm-danger-btn" id="v2-routing-confirm-ok">Remove</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        // The pending callback is stored on the overlay ELEMENT (not on the
        // modal instance). The modal is re-instantiated on every open, but this
        // overlay is created once and persists on <body>; binding these handlers
        // to a specific instance's `this` meant that after a reopen the OK click
        // read a dead instance's pending callback (null) and the action silently
        // did nothing. Reading from the overlay keeps the dialog self-contained.
        const hide = () => { overlay.style.display = 'none'; overlay.__pendingConfirm = null; };
        overlay.querySelector('#v2-routing-confirm-cancel').addEventListener('click', hide);
        overlay.querySelector('#v2-routing-confirm-ok').addEventListener('click', () => {
            const fn = overlay.__pendingConfirm;
            hide();
            if (fn) fn();
        });
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) hide();
        });
        return overlay;
    }

    _confirmAction(title, message, confirmLabel, onConfirm) {
        const overlay = this._ensureRoutingConfirmOverlay();
        const titleEl = overlay.querySelector('#v2-routing-confirm-title');
        const msgEl = overlay.querySelector('#v2-routing-confirm-message');
        const okBtn = overlay.querySelector('#v2-routing-confirm-ok');
        if (titleEl) titleEl.textContent = title;
        if (msgEl) msgEl.textContent = message;
        if (okBtn && confirmLabel) okBtn.textContent = confirmLabel;
        // Store the callback on the overlay element so the (once-bound) OK
        // handler resolves it regardless of which modal instance is current.
        overlay.__pendingConfirm = onConfirm;
        // Centered in the viewport via the shared .v2-draft-prompt-overlay flex.
        overlay.style.display = 'flex';
    }

    _closeRoutingConfirm() {
        const overlay = document.getElementById('v2-routing-confirm-overlay');
        if (overlay) {
            overlay.style.display = 'none';
            overlay.__pendingConfirm = null;
        }
    }

    /**
     * Show a tooltip portaled to <body> (position:fixed, top layer), centered
     * above the anchor element and clamped to the viewport so it can't clip
     * against the modal's overflow edges.
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

    async _performRemoveRouting(eventId) {
        try {
            // Keep the button as a bare X icon; just disable it while removing.
            if (this.removeRoutingBtn) {
                this.removeRoutingBtn.disabled = true;
            }

            const csrfToken = this.getCsrfToken();
            // Use the /cancel/ endpoint which allows both creators and schedulers
            const response = await fetch(`/api/events/${eventId}/approval-routing/cancel/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || result.message || 'Failed to remove routing');
            }

            console.log('EventEditingModalV2: Routing removed via cancel endpoint', result);

            // Reload approval routing to show cleared state
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                showMessage('Approval routing removed', 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to remove routing', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to remove routing', 'error');
            }
        } finally {
            if (this.removeRoutingBtn) {
                this.removeRoutingBtn.disabled = false;
                this.removeRoutingBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" aria-hidden="true">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                `;
            }
        }
    }

    /**
     * Open the routing builder popup.
     *
     * Builder state is a flat list of reviewers. Each entry carries a
     * `connector` describing its relation to the NEXT reviewer:
     *   - 'then' : a step boundary (sequential — next reviewer waits)
     *   - 'and'  : a parallel join (same step — both review at once)
     * Consecutive 'and'-linked reviewers form one parallel group. The group's
     * all-vs-any rule is stored as `rule` ('all' | 'any') on the FIRST member
     * of the group.
     */
    async openRoutingBuilder() {
        console.log('EventEditingModalV2: Opening routing builder');

        // Load office staff (for approver selection) and saved routing presets
        await Promise.all([this.loadOfficeStaff(), this.loadRoutingPresets()]);

        // Initialize builder from existing routing (skipping the creator stage)
        const existing = this.approvalRoutingData?.stages
            || this.approvalRoutingData?.routing?.stages
            || [];
        this._loadBuilderFromStages(existing);
        this.activeRoutingPresetId = null;

        // If this event has no routing yet, pre-load the user's default preset.
        const hasExistingRouting = this.routingStages.some(s => s.approver);
        if (!hasExistingRouting) {
            const def = (this.routingPresets || []).find(p => p.is_default);
            if (def && Array.isArray(def.data?.stages) && def.data.stages.length) {
                this._loadBuilderFromStages(def.data.stages);
                this.activeRoutingPresetId = def.id;
            }
        }

        // Render stages and presets bar
        this.renderRoutingStages();
        this.renderRoutingPresets();

        // Show popup
        this.routingPopupOverlay?.classList.add('visible');
    }

    /**
     * Populate the builder state (this.routingStages) from a stages array
     * (an approval-routing config's `stages`, with the creator stage skipped).
     */
    _loadBuilderFromStages(stages) {
        const reviewerStages = (stages || []).filter(
            s => s.stage_id !== 'stage-creator' && (s.order || 0) !== 0
        );

        this.routingStages = [];
        reviewerStages.forEach(stage => {
            const approvers = stage.approvers || [];
            const rule = stage.all_required === false ? 'any' : 'all';
            approvers.forEach((ap, j) => {
                this.routingStages.push({
                    approver: ap.name || '',
                    staff_id: ap.staff_id || null,
                    user_id: ap.user_id || null,
                    // Within a stage, members are parallel; the last member's
                    // connector bridges to the next stage (sequential).
                    connector: j < approvers.length - 1 ? 'and' : 'then',
                    rule: j === 0 ? rule : 'all'
                });
            });
        });

        if (this.routingStages.length === 0) {
            this.routingStages = [{ approver: '', connector: 'then', rule: 'all' }];
        }
    }

    /**
     * Build an approval-routing `stages` array from the current builder state.
     * Consecutive 'and'-linked reviewers collapse into one parallel stage.
     * (The creator stage is prepended server-side, not here.)
     */
    _buildRoutingStagesConfig() {
        const groups = this._computeRoutingGroups();
        const stages = [];
        let order = 0;
        groups.forEach(group => {
            const approvers = group
                .map(idx => this.routingStages[idx])
                .filter(stage => stage.approver)
                .map(stage => ({
                    name: stage.approver,
                    staff_id: stage.staff_id || null,
                    user_id: stage.user_id || null
                }));
            if (approvers.length === 0) return;

            order += 1;
            const isParallel = approvers.length > 1;
            const rule = this.routingStages[group[0]]?.rule || 'all';
            stages.push({
                stage_id: `stage-${order}`,
                order: order,
                type: isParallel ? 'parallel' : 'sequential',
                all_required: isParallel ? (rule !== 'any') : true,
                approvers: approvers
            });
        });
        return stages;
    }

    // ---- Saved routes (routing presets, user-level) ----------------------

    /** Fetch the current user's saved routing presets. */
    async loadRoutingPresets() {
        try {
            const resp = await fetch('/api/user/routing-presets/', {
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            if (resp.ok) {
                this.routingPresets = await resp.json();
            }
        } catch (e) {
            console.error('EventEditingModalV2: Failed to load routing presets', e);
        }
        return this.routingPresets;
    }

    toggleRoutingPresetsMenu() {
        this._routingPresetsMenuOpen ? this.closeRoutingPresetsMenu() : this.openRoutingPresetsMenu();
    }

    openRoutingPresetsMenu() {
        this._routingPresetsMenuOpen = true;
        this.routingPresetsDropdown?.classList.add('open');
        this.routingPresetsTrigger?.setAttribute('aria-expanded', 'true');
        if (!this._routingPresetsOutsideHandler) {
            this._routingPresetsOutsideHandler = (e) => {
                if (this.routingPresetsDropdown && !this.routingPresetsDropdown.contains(e.target)) {
                    this.closeRoutingPresetsMenu();
                }
            };
        }
        document.addEventListener('click', this._routingPresetsOutsideHandler);
    }

    closeRoutingPresetsMenu() {
        this._routingPresetsMenuOpen = false;
        this.routingPresetsDropdown?.classList.remove('open');
        this.routingPresetsTrigger?.setAttribute('aria-expanded', 'false');
        if (this._routingPresetsOutsideHandler) {
            document.removeEventListener('click', this._routingPresetsOutsideHandler);
        }
    }

    /** Render the saved-routes dropdown list + the save button/form. */
    renderRoutingPresets() {
        const active = this.routingPresets.find(p => p.id === this.activeRoutingPresetId);
        if (this.routingPresetsLabel) {
            this.routingPresetsLabel.textContent = active ? active.name : 'Saved routes';
        }
        this.routingPresetsDropdown?.classList.toggle('has-active', !!active);

        if (this.routingPresetsList) {
            this.routingPresetsList.innerHTML = '';
            if (!this.routingPresets.length) {
                const empty = document.createElement('div');
                empty.className = 'v2-routing-presets-empty';
                empty.textContent = 'No saved routes yet';
                this.routingPresetsList.appendChild(empty);
            } else {
                this.routingPresets.forEach(preset => {
                    const row = document.createElement('div');
                    row.className = 'v2-routing-preset-item';
                    if (preset.id === this.activeRoutingPresetId) row.classList.add('active');

                    const applyBtn = document.createElement('button');
                    applyBtn.type = 'button';
                    applyBtn.className = 'v2-routing-preset-apply';
                    applyBtn.innerHTML = '<span class="v2-routing-preset-name"></span>';
                    applyBtn.querySelector('.v2-routing-preset-name').textContent = preset.name;
                    applyBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.applyRoutingPreset(preset.id);
                    });

                    const starBtn = document.createElement('button');
                    starBtn.type = 'button';
                    starBtn.className = 'v2-routing-preset-default' + (preset.is_default ? ' is-default' : '');
                    starBtn.title = preset.is_default ? 'Unset default' : 'Set as default';
                    starBtn.setAttribute('aria-label', starBtn.title);
                    starBtn.innerHTML = preset.is_default
                        ? '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>'
                        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>';
                    starBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.toggleRoutingPresetDefault(preset.id);
                    });

                    const delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = 'v2-routing-preset-delete';
                    delBtn.title = 'Delete';
                    delBtn.setAttribute('aria-label', 'Delete');
                    delBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>';
                    delBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.deleteRoutingPreset(preset.id);
                    });

                    row.appendChild(applyBtn);
                    row.appendChild(starBtn);
                    row.appendChild(delBtn);
                    this.routingPresetsList.appendChild(row);
                });
            }
        }

        this._renderRoutingPresetSaveDefault();
    }

    _renderRoutingPresetSaveDefault() {
        if (!this.routingPresetsSave) return;
        this.routingPresetsSave.innerHTML = '';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'v2-routing-preset-save-btn';
        btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Save as preset';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._renderRoutingPresetSaveForm();
        });
        this.routingPresetsSave.appendChild(btn);
    }

    _renderRoutingPresetSaveForm() {
        if (!this.routingPresetsSave) return;
        this.routingPresetsSave.innerHTML = '';
        const form = document.createElement('form');
        form.className = 'v2-routing-preset-save-form';
        form.innerHTML = `
            <input type="text" class="v2-routing-preset-name-input" placeholder="Route name" maxlength="100" autocomplete="off">
            <button type="submit" class="v2-routing-preset-name-confirm" aria-label="Save"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></button>
            <button type="button" class="v2-routing-preset-name-cancel" aria-label="Cancel"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
        `;
        const input = form.querySelector('.v2-routing-preset-name-input');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveRoutingPreset(input.value);
        });
        form.querySelector('.v2-routing-preset-name-cancel').addEventListener('click', (e) => {
            e.stopPropagation();
            this._renderRoutingPresetSaveDefault();
        });
        this.routingPresetsSave.appendChild(form);
        input.focus();
    }

    applyRoutingPreset(id) {
        const preset = this.routingPresets.find(p => p.id === id);
        if (!preset) return;
        const stages = Array.isArray(preset.data?.stages) ? preset.data.stages : [];
        this._loadBuilderFromStages(stages);
        this.activeRoutingPresetId = id;
        this.renderRoutingStages();
        this.renderRoutingPresets();
        this.closeRoutingPresetsMenu();
        if (typeof showMessage === 'function') showMessage(`Applied "${preset.name}"`, 'success');
    }

    async saveRoutingPreset(rawName) {
        const name = (rawName || '').trim();
        if (!name) {
            if (typeof showMessage === 'function') showMessage('Enter a name for the route', 'warning');
            return;
        }
        const stages = this._buildRoutingStagesConfig();
        if (stages.length === 0) {
            if (typeof showMessage === 'function') showMessage('Add at least one reviewer before saving', 'warning');
            return;
        }
        try {
            const resp = await fetch('/api/user/routing-presets/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ name, data: { stages } })
            });
            if (!resp.ok) {
                const errText = await resp.text().catch(() => '');
                console.error('EventEditingModalV2: routing preset save failed',
                    resp.status, errText);
                throw new Error('save failed');
            }
            const saved = await resp.json();
            const idx = this.routingPresets.findIndex(p => p.id === saved.id);
            if (idx >= 0) this.routingPresets[idx] = saved;
            else this.routingPresets.push(saved);
            this.routingPresets.sort((a, b) => a.name.localeCompare(b.name));
            this.activeRoutingPresetId = saved.id;
            this.renderRoutingPresets();
            if (typeof showMessage === 'function') showMessage(`Saved "${saved.name}"`, 'success');
        } catch (e) {
            console.error('EventEditingModalV2: Failed to save routing preset', e);
            if (typeof showMessage === 'function') showMessage('Failed to save route', 'error');
        }
    }

    async toggleRoutingPresetDefault(id) {
        const preset = this.routingPresets.find(p => p.id === id);
        if (!preset) return;
        const makeDefault = !preset.is_default;
        try {
            const resp = await fetch(`/api/user/routing-presets/${id}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ is_default: makeDefault })
            });
            if (!resp.ok) throw new Error('patch failed');
            this.routingPresets.forEach(p => { p.is_default = (p.id === id) ? makeDefault : false; });
            this.renderRoutingPresets();
        } catch (e) {
            console.error('EventEditingModalV2: Failed to update default routing preset', e);
            if (typeof showMessage === 'function') showMessage('Failed to update default', 'error');
        }
    }

    async deleteRoutingPreset(id) {
        const preset = this.routingPresets.find(p => p.id === id);
        if (!preset) return;
        try {
            const resp = await fetch(`/api/user/routing-presets/${id}/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin'
            });
            if (!resp.ok && resp.status !== 204) throw new Error('delete failed');
            this.routingPresets = this.routingPresets.filter(p => p.id !== id);
            if (this.activeRoutingPresetId === id) this.activeRoutingPresetId = null;
            this.renderRoutingPresets();
            if (typeof showMessage === 'function') showMessage(`Deleted "${preset.name}"`, 'success');
        } catch (e) {
            console.error('EventEditingModalV2: Failed to delete routing preset', e);
            if (typeof showMessage === 'function') showMessage('Failed to delete route', 'error');
        }
    }

    /**
     * Close the routing builder popup without saving
     */
    closeRoutingBuilder() {
        console.log('EventEditingModalV2: Closing routing builder');

        // Hide popup
        this.routingPopupOverlay?.classList.remove('visible');

        // Close the saved-routes dropdown if open
        this.closeRoutingPresetsMenu();

        // Close any open routing dropdowns and return menus to DOM
        this._closeAllRoutingDropdowns();

        // Clean up routing dropdown outside click handler
        if (this._routingDropdownOutsideHandler) {
            document.removeEventListener('click', this._routingDropdownOutsideHandler);
            this._routingDropdownOutsideHandler = null;
        }

        // Reset stages
        this.routingStages = [];
    }

    /**
     * Add a new reviewer to the end of the chain (its own sequential step)
     */
    addRoutingStage() {
        this.routingStages.push({ approver: '', connector: 'then', rule: 'all' });
        this.renderRoutingStages();
    }

    /**
     * Remove a reviewer from the chain
     */
    removeRoutingStage(index) {
        if (this.routingStages.length <= 1) {
            // Keep at least one reviewer row
            return;
        }

        this.routingStages.splice(index, 1);
        this.renderRoutingStages();
    }

    /**
     * Group reviewer indices into steps. Consecutive 'and'-linked reviewers
     * share a step; a 'then' connector starts a new step.
     * Returns an array of arrays of indices, e.g. [[0], [1, 2], [3]].
     */
    _computeRoutingGroups() {
        const stages = this.routingStages;
        const groups = [];
        if (!stages.length) return groups;

        let cur = [0];
        for (let i = 0; i < stages.length - 1; i++) {
            if (stages[i].connector === 'and') {
                cur.push(i + 1);
            } else {
                groups.push(cur);
                cur = [i + 1];
            }
        }
        groups.push(cur);
        return groups;
    }

    /**
     * Toggle the connector below reviewer `index` between 'then' and 'and'
     */
    toggleRoutingConnector(index) {
        const stage = this.routingStages[index];
        if (!stage) return;
        stage.connector = stage.connector === 'and' ? 'then' : 'and';
        if (stage.connector === 'and' && !stage.rule) {
            stage.rule = 'all';
        }
        this.renderRoutingStages();
    }

    /**
     * Set the all-vs-any rule for the parallel group that begins at `index`
     */
    setRoutingGroupRule(index, rule) {
        const stage = this.routingStages[index];
        if (!stage) return;
        stage.rule = rule;
        this.renderRoutingStages();
    }

    /**
     * Close all open routing stage dropdowns and return menus to their wrappers
     */
    _closeAllRoutingDropdowns() {
        this.routingStagesContainer?.querySelectorAll('.v2-routing-stage-dropdown-wrapper').forEach(w => {
            if (w._detachedMenu && w._detachedMenu.parentNode === document.body) {
                w._detachedMenu.style.display = '';
                w.appendChild(w._detachedMenu);
                w._detachedMenu = null;
            }
            w.classList.remove('open');
        });
        // Also clean up any orphaned menus left on body
        document.querySelectorAll('body > .v2-routing-stage-menu').forEach(m => {
            m.style.display = '';
            m.remove();
        });
    }

    /**
     * Render all routing stages in the builder
     */
    renderRoutingStages() {
        if (!this.routingStagesContainer) return;

        const staff = this.officeStaff || [];
        let html = '';
        let stepNumber = 2; // creator is always step 1

        // Static "then" connector. Parallel ("and") is temporarily disabled, so
        // every reviewer is a sequential step. One sits above each reviewer,
        // including the first (connecting it to the creator stage above).
        const thenConnector = `
            <div class="v2-routing-connector">
                <span class="v2-connector-static">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline></svg>
                    then
                </span>
            </div>
        `;

        this.routingStages.forEach((stage, index) => {
            // Find the currently matched staff member for this stage
            let matchedName = '';
            let matchedValue = '';
            staff.forEach(member => {
                const name = member.name || member;
                const id = member.id || '';
                const linkedUserId = member.linked_user?.id || '';
                const isMatch = (stage.staff_id && stage.staff_id === id) ||
                                (stage.user_id && linkedUserId && stage.user_id === linkedUserId) ||
                                (!stage.staff_id && !stage.user_id && stage.approver === name);
                if (isMatch) {
                    matchedName = name;
                    matchedValue = `${id}|${linkedUserId}|${name}`;
                }
            });

            // Build dropdown options
            let optionsHtml = '';
            staff.forEach(member => {
                const name = member.name || member;
                const id = member.id || '';
                const linkedUserId = member.linked_user?.id || '';
                const value = `${id}|${linkedUserId}|${name}`;
                const isSelected = value === matchedValue;
                optionsHtml += `<div class="v2-routing-stage-option${isSelected ? ' selected' : ''}" data-value="${this.escapeHtml(value)}">${this.escapeHtml(name)}</div>`;
            });

            const triggerText = matchedName || 'Select reviewer...';
            const placeholderClass = matchedName ? '' : ' placeholder';

            // Step numbering: parallel continuation members share the prior
            // step's number and show an unfilled circle.
            const contInPrev = index > 0 && this.routingStages[index - 1].connector === 'and';
            if (index > 0 && !contInPrev) stepNumber++;
            const numContent = contInPrev ? '' : stepNumber;
            const numClass = contInPrev
                ? 'v2-routing-stage-number v2-routing-stage-number-cont'
                : 'v2-routing-stage-number';

            // "then" connector above this reviewer (creator -> first, prev -> this)
            html += thenConnector;

            html += `
                <div class="v2-routing-stage-item" data-stage-index="${index}">
                    <div class="${numClass}">${numContent}</div>
                    <div class="v2-routing-stage-dropdown-wrapper" data-stage-index="${index}">
                        <div class="v2-routing-stage-trigger${placeholderClass}" data-stage-index="${index}">${this.escapeHtml(triggerText)}</div>
                        <div class="v2-routing-stage-menu">
                            ${optionsHtml}
                        </div>
                    </div>
                    <button type="button" class="v2-routing-stage-remove" data-stage-index="${index}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
            `;
        });

        this.routingStagesContainer.innerHTML = html;

        // Bind custom dropdown trigger clicks
        this.routingStagesContainer.querySelectorAll('.v2-routing-stage-trigger').forEach(trigger => {
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                const wrapper = trigger.closest('.v2-routing-stage-dropdown-wrapper');
                const wasOpen = wrapper.classList.contains('open');

                // Close any open routing dropdown
                this._closeAllRoutingDropdowns();

                if (!wasOpen) {
                    // Move menu to body (like status dropdown) to avoid modal transform/overflow clipping
                    const menu = wrapper.querySelector('.v2-routing-stage-menu');
                    document.body.appendChild(menu);
                    wrapper._detachedMenu = menu;

                    // Measure and position
                    const rect = trigger.getBoundingClientRect();
                    menu.style.visibility = 'hidden';
                    menu.style.display = 'block';
                    const menuHeight = menu.offsetHeight;
                    const spaceBelow = window.innerHeight - rect.bottom;

                    let top;
                    if (spaceBelow >= menuHeight || spaceBelow >= rect.top) {
                        top = rect.bottom + 4;
                    } else {
                        top = rect.top - menuHeight - 4;
                    }
                    if (top + menuHeight > window.innerHeight - 8) top = window.innerHeight - menuHeight - 8;
                    if (top < 8) top = 8;

                    menu.style.left = rect.left + 'px';
                    menu.style.top = top + 'px';
                    menu.style.width = rect.width + 'px';
                    menu.style.visibility = '';

                    wrapper.classList.add('open');
                }
            });
        });

        // Bind option clicks
        this.routingStagesContainer.querySelectorAll('.v2-routing-stage-option').forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const menu = option.closest('.v2-routing-stage-menu');
                // Find the wrapper via data attribute since menu may be detached to body
                const stageIndex = menu.closest('.v2-routing-stage-dropdown-wrapper')?.dataset?.stageIndex;
                // If menu is detached, find wrapper by iterating
                let wrapper = null;
                this.routingStagesContainer.querySelectorAll('.v2-routing-stage-dropdown-wrapper').forEach(w => {
                    if (w._detachedMenu === menu || w.contains(menu)) {
                        wrapper = w;
                    }
                });
                if (!wrapper) return;

                const index = parseInt(wrapper.dataset.stageIndex);
                const value = option.dataset.value;

                // Parse "staffId|userId|name" format
                const parts = value.split('|');
                const staffId = parts[0] || '';
                const userId = parts[1] || '';
                const name = parts.slice(2).join('|');

                this.routingStages[index].staff_id = staffId || null;
                this.routingStages[index].user_id = userId || null;
                this.routingStages[index].approver = name || '';

                // Update trigger text
                const trigger = wrapper.querySelector('.v2-routing-stage-trigger');
                trigger.textContent = name;
                trigger.classList.remove('placeholder');

                // Update selected state on all options in the menu
                menu.querySelectorAll('.v2-routing-stage-option').forEach(o => o.classList.remove('selected'));
                option.classList.add('selected');

                // Close dropdown (returns menu to wrapper)
                this._closeAllRoutingDropdowns();
            });
        });

        // Close routing dropdowns on outside click
        if (this._routingDropdownOutsideHandler) {
            document.removeEventListener('click', this._routingDropdownOutsideHandler);
        }
        this._routingDropdownOutsideHandler = (e) => {
            if (!e.target.closest('.v2-routing-stage-dropdown-wrapper') && !e.target.closest('.v2-routing-stage-menu')) {
                this._closeAllRoutingDropdowns();
            }
        };
        document.addEventListener('click', this._routingDropdownOutsideHandler);

        // Bind remove button handlers
        this.routingStagesContainer.querySelectorAll('.v2-routing-stage-remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const index = parseInt(btn.dataset.stageIndex);
                this.removeRoutingStage(index);
            });
        });

        // Bind connector toggle handlers (then <-> and)
        this.routingStagesContainer.querySelectorAll('.v2-connector-toggle').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.stageIndex);
                this.toggleRoutingConnector(index);
            });
        });

        // Bind parallel group rule handlers (all / any)
        this.routingStagesContainer.querySelectorAll('.v2-rule-opt').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const index = parseInt(btn.dataset.stageIndex);
                this.setRoutingGroupRule(index, btn.dataset.rule);
            });
        });
    }

    /**
     * Save routing configuration to API
     */
    async saveRoutingConfig() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') {
            console.warn('EventEditingModalV2: Cannot save routing without event ID');
            return;
        }

        // Group reviewers into steps and build the routing config.
        const stages = this._buildRoutingStagesConfig();
        if (stages.length === 0) {
            if (typeof showMessage === 'function') {
                showMessage('Please select at least one approver', 'warning');
            }
            return;
        }

        try {
            // Disable save button
            if (this.routingSaveBtn) {
                this.routingSaveBtn.disabled = true;
                this.routingSaveBtn.textContent = 'Saving...';
            }

            const csrfToken = this.getCsrfToken();

            // Build routing config
            const routingConfig = { stages: stages };

            console.log('EventEditingModalV2: Saving routing config:', routingConfig);

            const response = await fetch(`/api/events/${eventId}/approval-routing/`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ routing_config: routingConfig })
            });

            if (!response.ok) {
                const errorText = await response.text();
                console.error('EventEditingModalV2: Routing save failed', {
                    status: response.status,
                    statusText: response.statusText,
                    body: errorText
                });
                let errorMessage = 'Failed to save routing';
                try {
                    const errorData = JSON.parse(errorText);
                    errorMessage = errorData.error || errorData.message || errorMessage;
                } catch (e) {
                    // Not JSON, use generic message
                }
                throw new Error(errorMessage);
            }

            const result = await response.json();
            console.log('EventEditingModalV2: Routing saved', result);

            // Close builder
            this.closeRoutingBuilder();

            // Reload routing to show updated chain
            await this.loadApprovalRouting(eventId);

            // Show success message
            if (typeof showMessage === 'function') {
                showMessage('Approval routing saved', 'success');
            }

        } catch (error) {
            console.error('EventEditingModalV2: Failed to save routing', error);
            if (typeof showMessage === 'function') {
                showMessage(error.message || 'Failed to save routing', 'error');
            }
        } finally {
            if (this.routingSaveBtn) {
                this.routingSaveBtn.disabled = false;
                this.routingSaveBtn.textContent = 'Save & Start Review';
            }
        }
    }

    /**
     * Fetch overlapping events for the current event and render in the modal.
     */
    async fetchAndRenderOverlaps() {
        const eventId = this.form?.dataset?.eventId;
        if (!eventId || eventId === 'new') return;

        // Check form fields for complete time data
        const startDate = this.form?.querySelector('[name="start_date"]')?.value;
        const startTime = this.form?.querySelector('[name="start_time"]')?.value;
        const endDate = this.form?.querySelector('[name="end_date"]')?.value;
        const endTime = this.form?.querySelector('[name="end_time"]')?.value;
        if (!startDate || !startTime || !endDate || !endTime) return;

        try {
            const csrfToken = this.getCsrfToken();
            const response = await fetch(`/api/events/${eventId}/overlaps/`, {
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            });
            if (!response.ok) return;
            const overlaps = await response.json();
            if (!overlaps.length) return;

            this.renderOverlapsInModal(overlaps);
        } catch (error) {
            console.error('EventEditingModalV2: Error fetching overlaps:', error);
        }
    }

    /**
     * Render overlap items in the editing modal, below the tags field.
     */
    renderOverlapsInModal(overlaps) {
        // Remove any existing overlap section
        this.form?.querySelector('.v2-overlap-section')?.remove();

        const escapeHtml = (str) => {
            if (!str) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        const statusLabels = {
            'received': 'Received', 'hold': 'Hold', 'referred': 'Referred',
            'fyied': 'FYI\'ed', 'scheduling_in_progress': 'Scheduling',
            'scheduled': 'Scheduled', 'rsvped': 'RSVP\'d',
            'regrets_sent': 'Regrets Sent', 'passed': 'Passed',
            'canceled': 'Canceled', 'requires_hms_review': 'Needs Review'
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
            const label = statusLabels[o.status] || o.status || 'Unknown';
            return `<div class="overlap-item" role="button" tabindex="0" data-event-id="${o.id}" aria-label="Open ${escapeHtml(o.title)}">
                <span class="overlap-title">${escapeHtml(o.title)}</span>
                <span class="overlap-time">${timeStr}</span>
                <span class="detail-panel-status status-${o.status || 'received'}">${escapeHtml(label)}</span>
            </div>`;
        }).join('');

        const countLabel = `${overlaps.length} ${overlaps.length === 1 ? 'event' : 'events'}`;
        const sectionHtml = `<div class="v2-overlap-section">
            <label class="v2-field-label">
                <span class="v2-field-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="13" stroke-width="3"></line>
                        <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"></circle>
                    </svg>
                </span>
                Overlaps with <span class="v2-overlap-count">${countLabel}</span>
            </label>
            <div class="overlap-list">${itemsHtml}</div>
        </div>`;

        // Insert inside the scrollable Event Details tab, just after the
        // (now relocated) time/date section.
        const timeSection = this.form?.querySelector('#v2-event-details-panel .v2-time-section');
        if (timeSection) {
            timeSection.insertAdjacentHTML('afterend', sectionHtml);
        } else {
            const detailsPanel = this.form?.querySelector('#v2-event-details-panel');
            detailsPanel?.insertAdjacentHTML('afterbegin', sectionHtml);
        }

        // Bind click/keyboard handlers on overlap items
        const overlapSection = this.form?.querySelector('.v2-overlap-section');
        overlapSection?.querySelectorAll('.overlap-item').forEach(item => {
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
}

// =========================================================================
// Global Initialization
// =========================================================================

// Create global instance
let eventEditingModalV2 = null;

function initEventEditingModalV2() {
    if (!eventEditingModalV2) {
        eventEditingModalV2 = new EventEditingModalV2();
        window.eventEditingModalV2 = eventEditingModalV2;
    }
    return eventEditingModalV2;
}

/**
 * Global function to create a new event and open the editing modal
 * Called from the "New Event" button in the header
 */
async function createNewEvent() {
    console.log('createNewEvent: Creating new event...');

    try {
        // Get CSRF token
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
            document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1];

        if (!csrfToken) {
            throw new Error('CSRF token not found');
        }

        // Create a minimal event with default values
        const newEventData = {
            title: '',
            status: 'received',
            type: 'meeting',
            format: 'in_person'
        };

        const response = await fetch('/api/events/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify(newEventData)
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('createNewEvent: Failed to create event', response.status, errorText);
            throw new Error(`Failed to create event: ${response.status}`);
        }

        const createdEvent = await response.json();
        console.log('createNewEvent: Event created', createdEvent.id);

        // Now open the event editing modal with the created event
        openEventEditingModal(createdEvent.id, true); // true = newly created

    } catch (error) {
        console.error('createNewEvent: Error', error);
        if (typeof showMessage === 'function') {
            showMessage('Failed to create event. Please try again.', 'error');
        } else {
            alert('Failed to create event. Please try again.');
        }
    }
}

/**
 * Open a read-only view modal for events the user cannot edit
 * Shows a compact, single-panel view with all event details
 * @param {object} eventData - The event data from API
 * @param {HTMLElement} container - The container element
 */
function openReadOnlyEventModal(eventData, container) {
    console.log('openReadOnlyEventModal: Opening read-only view for event', eventData.id);

    // Helper to escape HTML
    const escapeHtml = (str) => {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };

    // Format date for display
    const formatDate = (dateStr) => {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                weekday: 'short',
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            });
        } catch (e) {
            return dateStr;
        }
    };

    // Format time for display
    const formatTime = (timeStr) => {
        if (!timeStr) return '';
        try {
            const [hours, minutes] = timeStr.split(':');
            const date = new Date();
            date.setHours(parseInt(hours), parseInt(minutes));
            return date.toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });
        } catch (e) {
            return timeStr;
        }
    };

    // Build relative time indicator
    const getRelativeTime = () => {
        if (!eventData.start_date) return '';
        try {
            const now = new Date();
            const eventDate = new Date(eventData.start_date);
            if (eventData.start_time) {
                const [h, m] = eventData.start_time.split(':');
                eventDate.setHours(parseInt(h), parseInt(m), 0, 0);
            }
            const diffMs = eventDate.getTime() - now.getTime();
            const diffMins = Math.round(diffMs / 60000);
            const diffHours = Math.round(diffMs / 3600000);
            const diffDays = Math.round(diffMs / 86400000);
            const isToday = eventDate.toDateString() === now.toDateString();
            const isTomorrow = new Date(now.getTime() + 86400000).toDateString() === eventDate.toDateString();
            const timeStr = eventData.start_time ? formatTime(eventData.start_time) : '';

            if (isToday) {
                if (diffMs > 0) {
                    const hrsLeft = Math.floor(diffMs / 3600000);
                    const minsLeft = Math.round((diffMs % 3600000) / 60000);
                    const remaining = hrsLeft > 0
                        ? `starts in ${hrsLeft}h ${minsLeft}m`
                        : `starts in ${minsLeft}m`;
                    return timeStr ? `Today at ${timeStr} \u2014 ${remaining}` : `Today \u2014 ${remaining}`;
                }
                return timeStr ? `Today at ${timeStr}` : 'Today';
            }
            if (isTomorrow) {
                return timeStr ? `Tomorrow at ${timeStr}` : 'Tomorrow';
            }
            if (diffDays > 0 && diffDays <= 14) {
                return `In ${diffDays} day${diffDays === 1 ? '' : 's'}`;
            }
            if (diffDays > 14) {
                const weeks = Math.round(diffDays / 7);
                return `In ${weeks} week${weeks === 1 ? '' : 's'}`;
            }
            if (diffDays < 0) {
                const absDays = Math.abs(diffDays);
                return `${absDays} day${absDays === 1 ? '' : 's'} ago`;
            }
            return '';
        } catch (e) {
            return '';
        }
    };

    // Build date/time display
    let dateTimeDisplay = '';
    if (eventData.start_date) {
        dateTimeDisplay = formatDate(eventData.start_date);
        if (eventData.start_time) {
            dateTimeDisplay += ` at ${formatTime(eventData.start_time)}`;
        }
        if (eventData.end_time && eventData.end_time !== eventData.start_time) {
            dateTimeDisplay += ` \u2013 ${formatTime(eventData.end_time)}`;
        }
        if (eventData.end_date && eventData.end_date !== eventData.start_date) {
            dateTimeDisplay += ` to ${formatDate(eventData.end_date)}`;
        }
    }
    const relativeTime = getRelativeTime();

    // Get status display info
    const statusLabel = eventData.status
        ? eventData.status.charAt(0).toUpperCase() + eventData.status.slice(1).replace(/_/g, ' ')
        : 'Unknown';

    // --- Track missing fields for collapsible summary ---
    const missingFields = [];
    const hasDateTime = !!eventData.start_date;
    const hasLocation = !!eventData.location;
    const hasType = !!eventData.type;
    const hasFormat = !!eventData.format;
    const hasDescription = !!eventData.description;
    const hasTags = eventData.tags && eventData.tags.length > 0;
    const hasPOC = !!eventData.point_of_contact_name;
    const hasParticipants = eventData.participants && eventData.participants.length > 0;
    const hasStaff = eventData.staff && eventData.staff.length > 0;
    const hasNotes = !!eventData.notes;

    if (!hasDateTime) missingFields.push('Date & time');
    if (!hasLocation) missingFields.push('Location');
    if (!hasType) missingFields.push('Type');
    if (!hasFormat) missingFields.push('Format');
    if (!hasDescription) missingFields.push('Description');
    if (!hasTags) missingFields.push('Tags');
    if (!hasPOC) missingFields.push('Point of contact');
    if (!hasParticipants) missingFields.push('Participants');
    if (!hasStaff) missingFields.push('Assigned staff');
    if (!hasNotes) missingFields.push('Notes');

    // --- Build Type · Format tertiary line ---
    let typeFormatHtml = '';
    if (hasType || hasFormat) {
        const parts = [];
        if (hasType) parts.push(escapeHtml(eventData.type));
        if (hasFormat) parts.push(escapeHtml(eventData.format.replace(/_/g, ' ')));
        typeFormatHtml = `
            <div class="v2-readonly-type-format">${parts.join(' \u00b7 ')}</div>
        `;
    }

    // --- Build secondary sections (only if values exist) ---
    let descriptionHtml = '';
    if (hasDescription) {
        descriptionHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Description</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.description)}</span>
            </div>
        `;
    }

    // TODO: Make tags link to filtered event list when tag-based filtering is implemented
    let tagsHtml = '';
    if (hasTags) {
        tagsHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Tags</span>
                <div class="v2-readonly-tags">
                    ${eventData.tags.map(tag =>
                        `<button type="button" class="v2-readonly-tag" data-tag="${escapeHtml(tag)}" tabindex="0">${escapeHtml(tag)}</button>`
                    ).join('')}
                </div>
            </div>
        `;
    }

    let pocHtml = '';
    if (hasPOC) {
        pocHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Point of contact</span>
                <span class="v2-readonly-value">
                    ${escapeHtml(eventData.point_of_contact_name)}${eventData.point_of_contact_email ? ` \u00b7 <a href="mailto:${escapeHtml(eventData.point_of_contact_email)}">${escapeHtml(eventData.point_of_contact_email)}</a>` : ''}${eventData.point_of_contact_phone ? ` \u00b7 ${escapeHtml(eventData.point_of_contact_phone)}` : ''}
                </span>
            </div>
        `;
    }

    let participantsHtml = '';
    if (hasParticipants) {
        participantsHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Participants</span>
                <div class="v2-readonly-participants">
                    ${eventData.participants.map(p => `
                        <div class="v2-readonly-participant">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                                <circle cx="12" cy="7" r="4"></circle>
                            </svg>
                            ${escapeHtml(typeof p === 'object' ? p.name : p)}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    let staffHtml = '';
    if (hasStaff) {
        staffHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Assigned staff</span>
                <div class="v2-readonly-staff-list">
                    ${eventData.staff.map(s => `
                        <span class="v2-readonly-staff-pill">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                                <circle cx="12" cy="7" r="4"></circle>
                            </svg>
                            ${escapeHtml(s.name || s)}
                        </span>
                    `).join('')}
                </div>
            </div>
        `;
    }

    let notesHtml = '';
    if (hasNotes) {
        notesHtml = `
            <div class="v2-readonly-section">
                <span class="v2-readonly-label">Notes</span>
                <span class="v2-readonly-value multiline">${escapeHtml(eventData.notes)}</span>
            </div>
        `;
    }

    // --- Missing fields summary ---
    let missingHtml = '';
    if (missingFields.length > 0) {
        missingHtml = `
            <div class="v2-readonly-missing">
                <button type="button" class="v2-readonly-missing-toggle" id="v2-readonly-missing-toggle" aria-expanded="false" tabindex="0">
                    <span>${missingFields.length} field${missingFields.length === 1 ? '' : 's'} not yet specified</span>
                    <svg class="v2-readonly-missing-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>
                <ul class="v2-readonly-missing-list" id="v2-readonly-missing-list" aria-hidden="true">
                    ${missingFields.map(f => `<li>${f}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    // TODO: Add conflict detection banner when calendar conflict data is available
    // in the event API response. Render as a yellow/amber alert at the top of the
    // content area: "Overlaps with [Event Name] at [time]"

    // Build the modal HTML
    const modalHtml = `
        <div class="v2-readonly-overlay active" id="v2-readonly-overlay" role="dialog" aria-modal="true" aria-label="Event details">
            <div class="v2-readonly-modal">
                <!-- Header -->
                <div class="v2-readonly-header">
                    <div class="v2-readonly-header-content">
                        <h2 class="v2-readonly-title">${escapeHtml(eventData.title) || 'Untitled Event'}</h2>
                        ${eventData.group ? `<div class="v2-readonly-org">${escapeHtml(eventData.group)}</div>` : ''}
                        <span class="v2-readonly-status status-${eventData.status || 'received'}">${statusLabel}</span>
                    </div>
                    <div class="v2-readonly-header-actions">
                        <span class="v2-readonly-viewonly-badge" aria-label="View only" title="View only">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                                <circle cx="12" cy="12" r="3"></circle>
                            </svg>
                        </span>
                        <div class="v2-more-menu" id="v2-readonly-more-menu">
                            <button class="v2-more-btn" type="button" id="v2-readonly-more-btn" aria-label="More options" aria-expanded="false" aria-haspopup="true">
                                <svg viewBox="0 0 24 24" fill="currentColor">
                                    <circle cx="12" cy="5" r="2"></circle>
                                    <circle cx="12" cy="12" r="2"></circle>
                                    <circle cx="12" cy="19" r="2"></circle>
                                </svg>
                            </button>
                            <div class="v2-more-dropdown" id="v2-readonly-more-dropdown">
                                <button type="button" class="v2-more-item" id="v2-readonly-copy-btn">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                        <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path>
                                    </svg>
                                    Copy Details
                                </button>
                            </div>
                        </div>
                        <button type="button" class="v2-readonly-close" id="v2-readonly-close" aria-label="Close">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                </div>

                <!-- Content -->
                <div class="v2-readonly-content">
                    <!-- Primary tier -->
                    <div class="v2-readonly-primary">
                        ${hasDateTime ? `<div class="v2-readonly-datetime">${dateTimeDisplay}</div>` : ''}
                        ${relativeTime ? `<div class="v2-readonly-relative-time">${relativeTime}</div>` : ''}
                        ${hasLocation ? `<div class="v2-readonly-location">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"></path>
                                <circle cx="12" cy="10" r="3"></circle>
                            </svg>
                            ${escapeHtml(eventData.location)}
                        </div>` : ''}
                        ${typeFormatHtml}
                    </div>

                    <!-- Secondary tier -->
                    <div class="v2-readonly-secondary">
                        ${descriptionHtml}
                        ${tagsHtml}
                        ${pocHtml}
                        ${participantsHtml}
                        ${staffHtml}
                        ${notesHtml}
                    </div>

                    <!-- Missing fields summary -->
                    ${missingHtml}
                </div>

                <!-- Footer -->
                <div class="v2-readonly-footer">
                    <button type="button" class="v2-readonly-calendar-btn" id="v2-readonly-calendar-btn">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                        View on Calendar
                    </button>
                </div>
            </div>
        </div>
    `;

    // Insert into container
    container.innerHTML = modalHtml;

    // --- Event listeners ---

    const closeModal = () => {
        const overlay = document.getElementById('v2-readonly-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
        container.classList.remove('active');
        container.setAttribute('aria-hidden', 'true');
        container.innerHTML = '';
        document.body.style.overflow = '';

        // Refresh any active page lists
        if (window.calendar && typeof window.calendar.fetchEvents === 'function') {
            window.calendar.fetchEvents().then(() => {
                if (typeof window.calendar.renderCurrentView === 'function') {
                    window.calendar.renderCurrentView();
                }
            });
        } else if (window.scheduleRedesign && typeof window.scheduleRedesign.refresh === 'function') {
            window.scheduleRedesign.refresh();
        } else if (window.inboxRedesign && typeof window.inboxRedesign.refresh === 'function') {
            window.inboxRedesign.refresh();
        } else if (typeof window.dashboardRefresh === 'function') {
            window.dashboardRefresh();
        }
    };

    // Close button in header
    document.getElementById('v2-readonly-close')?.addEventListener('click', closeModal);

    // More menu toggle in readonly header
    const roMoreMenu = document.getElementById('v2-readonly-more-menu');
    const roMoreBtn = document.getElementById('v2-readonly-more-btn');
    if (roMoreMenu && roMoreBtn) {
        roMoreBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = roMoreMenu.classList.toggle('open');
            roMoreBtn.setAttribute('aria-expanded', String(open));
        });
        document.addEventListener('click', (e) => {
            if (roMoreMenu.classList.contains('open') && !roMoreMenu.contains(e.target)) {
                roMoreMenu.classList.remove('open');
                roMoreBtn.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // Missing fields toggle
    document.getElementById('v2-readonly-missing-toggle')?.addEventListener('click', () => {
        const list = document.getElementById('v2-readonly-missing-list');
        const toggle = document.getElementById('v2-readonly-missing-toggle');
        if (!list || !toggle) return;
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        list.setAttribute('aria-hidden', String(expanded));
        list.classList.toggle('expanded');
        toggle.querySelector('.v2-readonly-missing-chevron')?.classList.toggle('rotated');
    });

    // Missing fields toggle keyboard support
    document.getElementById('v2-readonly-missing-toggle')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            e.target.click();
        }
    });

    // Copy Details button (now in more menu)
    document.getElementById('v2-readonly-copy-btn')?.addEventListener('click', async () => {
        // Close the dropdown
        roMoreMenu?.classList.remove('open');
        roMoreBtn?.setAttribute('aria-expanded', 'false');

        const parts = [];
        if (eventData.title) parts.push(eventData.title);
        if (dateTimeDisplay) parts.push(dateTimeDisplay);
        if (eventData.location) parts.push(eventData.location);
        const text = parts.join('\n');
        try {
            await navigator.clipboard.writeText(text);
            const btn = document.getElementById('v2-readonly-copy-btn');
            if (btn) {
                const original = btn.innerHTML;
                btn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    Copied!
                `;
                setTimeout(() => { btn.innerHTML = original; }, 1500);
            }
        } catch (e) {
            console.warn('Failed to copy to clipboard:', e);
        }
    });

    // View on Calendar button
    document.getElementById('v2-readonly-calendar-btn')?.addEventListener('click', () => {
        const startDate = eventData.start_date;
        const eventId = eventData.id;

        if (startDate && window.calendar) {
            closeModal();
            const date = new Date(startDate);
            window.calendar.state.currentDate = date;
            window.calendar.fetchEvents().then(() => {
                window.calendar.renderCurrentView();
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
            });
        } else if (startDate) {
            window.location.href = `/calendar/?date=${startDate}&event=${eventId}`;
        } else {
            window.location.href = '/calendar/';
        }
    });

    // TODO: Tag click handler — navigate to event list filtered by tag
    // when tag-based filtering is implemented
    container.querySelectorAll('.v2-readonly-tag').forEach(tagBtn => {
        tagBtn.addEventListener('click', () => {
            console.log('Tag clicked:', tagBtn.dataset.tag);
            // Future: window.location.href = `/schedule/?tag=${encodeURIComponent(tagBtn.dataset.tag)}`;
        });
        tagBtn.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                tagBtn.click();
            }
        });
    });

    // Click on overlay to close
    document.getElementById('v2-readonly-overlay')?.addEventListener('click', (e) => {
        if (e.target.id === 'v2-readonly-overlay') {
            closeModal();
        }
    });

    // Escape key
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            closeModal();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

/**
 * Global function to open the event editing modal
 * Fetches the modal HTML from the server and displays it
 * First checks if user can edit - if not, shows read-only view instead
 * @param {string} eventId - The event ID to edit
 * @param {boolean|object} isNewlyCreatedOrOptions - Whether this is a newly created event, or options object
 */
/**
 * Initialize EmailComposer from embedded JSON data in the modal DOM.
 * Called after AJAX-loaded modal content is injected into the page.
 */
function _initEmailComposerFromDOM() {
    if (!window.emailComposer) return;

    const dataScript = document.getElementById('email-composer-data');
    if (!dataScript) {
        console.log('openEventEditingModal: No email-composer-data found (no emails attached)');
        return;
    }

    try {
        const data = JSON.parse(dataScript.textContent);
        window.emailComposer.init(data.eventContext || {}, data.emailContext || {});
    } catch (e) {
        console.error('openEventEditingModal: Failed to parse email composer data:', e);
    }
}

/**
 * Skeleton placeholder for the editing modal — renders the real modal chrome
 * (centered card, header with title/org/close, a few field rows, footer
 * buttons) so the fetched interface swaps into an already-present card instead
 * of popping out of an empty backdrop. Reuses the live .v2-modal-overlay /
 * .v2-modal-container classes so size, position, and styling match exactly.
 */
function renderEventEditingSkeleton() {
    const field = (labelW, withSplit) => `
        <div class="v2-skel-field${withSplit ? ' v2-skel-field-split' : ''}">
            <div class="skeleton v2-skel-label" style="width:${labelW}"></div>
            ${withSplit
                ? '<div class="v2-skel-input-row"><div class="skeleton v2-skel-input"></div><div class="skeleton v2-skel-input"></div></div>'
                : '<div class="skeleton v2-skel-input"></div>'}
        </div>`;
    return `
        <div class="v2-modal-overlay active v2-skeleton-overlay" aria-hidden="true">
            <div class="v2-modal-container" role="status" aria-label="Loading event">
                <div class="v2-main-panel v2-skeleton-panel">
                    <div class="v2-skel-header">
                        <div class="v2-skel-header-content">
                            <div class="skeleton v2-skel-title"></div>
                            <div class="skeleton v2-skel-org"></div>
                        </div>
                        <div class="skeleton v2-skel-close"></div>
                    </div>
                    <div class="v2-skel-body">
                        ${field('64px', true)}
                        ${field('88px', true)}
                        ${field('72px', false)}
                        ${field('96px', false)}
                        ${field('80px', false)}
                        ${field('60px', true)}
                        ${field('92px', false)}
                        ${field('76px', false)}
                    </div>
                    <div class="v2-skel-footer">
                        <div class="skeleton v2-skel-btn"></div>
                        <div class="skeleton v2-skel-btn v2-skel-btn-primary"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

async function openEventEditingModal(eventId, isNewlyCreatedOrOptions = false) {
    console.log('openEventEditingModal: Opening modal for event', eventId);

    // Handle both old signature (boolean) and new signature (options object)
    let isNewlyCreated = false;
    let options = {};
    if (typeof isNewlyCreatedOrOptions === 'boolean') {
        isNewlyCreated = isNewlyCreatedOrOptions;
    } else if (typeof isNewlyCreatedOrOptions === 'object') {
        options = isNewlyCreatedOrOptions;
        isNewlyCreated = options.isNewEvent || false;
    }
    let showEmailPane = options.showEmailPane || false;

    const container = document.getElementById('event-editing-container');
    if (!container) {
        console.error('openEventEditingModal: Container not found');
        // Fallback to page navigation
        window.location.href = `/event-editing/${eventId}/`;
        return;
    }

    // Clean up previous interface instance to prevent duplicate UI elements
    if (window.eventEditingInterface) {
        try {
            window.eventEditingInterface.cleanupReviewMode();
        } catch (e) {
            console.warn('openEventEditingModal: cleanup of previous instance failed', e);
        }
        window.eventEditingInterface = null;
    }

    // Show skeleton placeholder (modal chrome) while the interface loads
    container.innerHTML = renderEventEditingSkeleton();
    container.classList.add('active');
    container.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    // Skip permission check for newly created events — always open in edit mode
    if (!isNewlyCreated) {
    // First, check if user can edit this event
    try {
        const eventResponse = await fetch(`/api/events/${eventId}/`, {
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!eventResponse.ok) {
            throw new Error(`HTTP ${eventResponse.status}`);
        }

        const eventData = await eventResponse.json();

        // Debug: Log permission info
        console.log('openEventEditingModal: Permission check -', {
            eventId: eventId,
            can_edit: eventData.can_edit,
            staff: eventData.staff,
            title: eventData.title
        });

        // If user cannot edit, show read-only modal instead
        if (eventData.can_edit === false) {
            console.log('openEventEditingModal: User cannot edit, showing read-only view');
            openReadOnlyEventModal(eventData, container);
            return;
        }
    } catch (error) {
        console.warn('openEventEditingModal: Could not check edit permission, proceeding with full modal', error);
        // Continue with full modal - permission check will happen server-side
    }
    } // end if (!isNewlyCreated)

    // Fetch the event editing interface content
    fetch(`/event-editing/${eventId}/`)
        .then(response => {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.text();
        })
        .then(html => {
            // Parse the HTML to extract just the content block
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');

            // Find the modal overlay element from the fetched page
            let overlay = doc.getElementById('v2-modal-overlay') || doc.getElementById('event-editing-overlay');
            let modalContainer = doc.querySelector('.v2-modal-container') || doc.querySelector('.split-panel-container');

            // Extract review mode data from fetched HTML
            const fetchedModalContainer = doc.querySelector('.v2-modal-container');
            let extractedFields = null;
            let requiresReview = false;

            if (fetchedModalContainer && fetchedModalContainer.dataset.requiresReview === 'true') {
                requiresReview = true;
            }

            // Get extracted fields from script tag
            const extractedFieldsScript = doc.getElementById('extracted-fields-data');
            if (extractedFieldsScript) {
                try {
                    extractedFields = JSON.parse(extractedFieldsScript.textContent);
                } catch (e) {
                    console.error('Failed to parse extracted fields:', e);
                }
            }

            // Email change-request suggestions (EventChangeReview module)
            let changeSuggestions = null;
            const changeSuggestionsScript = doc.getElementById('change-suggestions-data');
            if (changeSuggestionsScript) {
                try {
                    changeSuggestions = JSON.parse(changeSuggestionsScript.textContent);
                } catch (e) {
                    console.error('Failed to parse change suggestions:', e);
                }
            }

            if (overlay) {
                container.innerHTML = '';
                container.appendChild(overlay);

                // Also extract and append sibling overlays (outside the modal container)
                const approvalPopup = doc.getElementById('v2-approval-popup-overlay');
                if (approvalPopup) {
                    container.appendChild(approvalPopup);
                }
                const routingPopup = doc.getElementById('v2-routing-popup-overlay');
                if (routingPopup) {
                    container.appendChild(routingPopup);
                }
                const draftPrompt = doc.getElementById('v2-draft-prompt-overlay');
                if (draftPrompt) {
                    container.appendChild(draftPrompt);
                }

                // Initialize the normalized contacts/organizations panel. This
                // server-rendered flow doesn't call populateForm(), so kick the
                // panel off here (it fetches the event's contacts/orgs itself).
                if (window.EventContactsPanel) {
                    window.EventContactsPanel.init(eventId);
                }

                if (typeof EventEditingModalV2 !== 'undefined') {
                    window.eventEditingInterface = new EventEditingModalV2();
                    // Also update the global eventEditingModalV2 reference
                    // so onclick handlers and other code use the correct instance
                    window.eventEditingModalV2 = window.eventEditingInterface;
                    eventEditingModalV2 = window.eventEditingInterface;
                    // Track if newly created for empty check on close
                    window.eventEditingInterface.isNewlyCreatedEvent = isNewlyCreated;
                    if (options.isNewEvent) {
                        window.eventEditingInterface.newEventId = eventId;
                    }

                    // Auto-focus title if requested
                    if (options.autoFocusTitle) {
                        setTimeout(() => {
                            const titleInput = document.getElementById('event-title');
                            if (titleInput) {
                                titleInput.focus();
                                titleInput.select();
                            }
                        }, 100);
                    } else {
                        // Otherwise move focus INTO the modal: the shell by
                        // default — nothing focused — or the Review button for
                        // routing review events. focusModalOnOpen() also keeps
                        // focus off controls behind the overlay (e.g. the inbox
                        // Review button that just launched this).
                        setTimeout(() => window.eventEditingInterface?.focusModalOnOpen?.(), 80);
                    }

                    // Auto-open email pane if requested
                    if (showEmailPane) {
                        setTimeout(() => {
                            if (window.eventEditingInterface &&
                                window.eventEditingInterface.showEmailBtn &&
                                !window.eventEditingInterface.isEmailPanelVisible) {
                                window.eventEditingInterface.showEmailBtn.click();
                            }
                        }, 200);
                    }

                    // Open a specific tab if requested (e.g. spreadsheet contact/org
                    // cell → Involved Parties). Runs after the default tab is set.
                    if (options.initialTab) {
                        setTimeout(() => {
                            window.eventEditingInterface?.switchToTab?.(options.initialTab);
                        }, 220);
                    }

                    // Re-initialize approval popup after AJAX load
                    // Elements need to be re-cached since they may not have been in DOM during constructor
                    setTimeout(() => {
                        if (window.eventEditingInterface) {
                            // Re-cache elements + bind once (idempotent — will not
                            // rebind if the constructor already bound them).
                            window.eventEditingInterface.initializeApprovalPopup();
                            console.log('openEventEditingModal: Approval popup reinitialized');
                        }
                    }, 100);

                    // Initialize Email Composer from embedded context data
                    setTimeout(() => {
                        _initEmailComposerFromDOM();
                    }, 150);

                    const hasPendingFields = requiresReview && extractedFields
                        && Object.keys(extractedFields).length > 0
                        && Object.values(extractedFields).some(
                            field => field && field.status === 'pending'
                        );
                    // Email change requests enter the SAME review mode — only
                    // the changed fields are reviewable (EventChangeReview).
                    const hasPendingChanges = Array.isArray(changeSuggestions)
                        && changeSuggestions.some(s => s && s.status === 'pending');
                    if (hasPendingFields || hasPendingChanges) {
                        setTimeout(() => {
                            if (window.eventEditingInterface && window.eventEditingInterface.initializeReviewMode) {
                                window.eventEditingInterface.initializeReviewMode(
                                    hasPendingFields ? extractedFields : {},
                                    changeSuggestions
                                );
                            }
                        }, 300);
                    }
                }

                setupEventEditingClose(container);
            } else if (modalContainer) {
                const wrapper = document.createElement('div');
                wrapper.className = 'v2-modal-overlay active';
                wrapper.id = 'v2-modal-overlay';
                wrapper.appendChild(modalContainer);

                container.innerHTML = '';
                container.appendChild(wrapper);

                // Also extract and append sibling overlays (outside the modal container)
                const approvalPopup = doc.getElementById('v2-approval-popup-overlay');
                if (approvalPopup) {
                    container.appendChild(approvalPopup);
                }
                const routingPopup2 = doc.getElementById('v2-routing-popup-overlay');
                if (routingPopup2) {
                    container.appendChild(routingPopup2);
                }
                const draftPrompt2 = doc.getElementById('v2-draft-prompt-overlay');
                if (draftPrompt2) {
                    container.appendChild(draftPrompt2);
                }

                if (typeof EventEditingModalV2 !== 'undefined') {
                    window.eventEditingInterface = new EventEditingModalV2();
                    // Also update the global eventEditingModalV2 reference
                    // so onclick handlers and other code use the correct instance
                    window.eventEditingModalV2 = window.eventEditingInterface;
                    eventEditingModalV2 = window.eventEditingInterface;
                    // Track if newly created for empty check on close
                    window.eventEditingInterface.isNewlyCreatedEvent = isNewlyCreated;
                    if (options.isNewEvent) {
                        window.eventEditingInterface.newEventId = eventId;
                    }

                    // Auto-focus title if requested
                    if (options.autoFocusTitle) {
                        setTimeout(() => {
                            const titleInput = document.getElementById('event-title');
                            if (titleInput) {
                                titleInput.focus();
                                titleInput.select();
                            }
                        }, 100);
                    } else {
                        // Otherwise move focus INTO the modal: the shell by
                        // default — nothing focused — or the Review button for
                        // routing review events. focusModalOnOpen() also keeps
                        // focus off controls behind the overlay (e.g. the inbox
                        // Review button that just launched this).
                        setTimeout(() => window.eventEditingInterface?.focusModalOnOpen?.(), 80);
                    }

                    // Auto-open email pane if requested
                    if (showEmailPane) {
                        setTimeout(() => {
                            if (window.eventEditingInterface &&
                                window.eventEditingInterface.showEmailBtn &&
                                !window.eventEditingInterface.isEmailPanelVisible) {
                                window.eventEditingInterface.showEmailBtn.click();
                            }
                        }, 200);
                    }

                    // Open a specific tab if requested (e.g. spreadsheet contact/org
                    // cell → Involved Parties). Runs after the default tab is set.
                    if (options.initialTab) {
                        setTimeout(() => {
                            window.eventEditingInterface?.switchToTab?.(options.initialTab);
                        }, 220);
                    }

                    // Re-initialize approval popup after AJAX load
                    // Elements need to be re-cached since they may not have been in DOM during constructor
                    setTimeout(() => {
                        if (window.eventEditingInterface) {
                            // Reset the initialization flag to allow re-binding
                            window.eventEditingInterface._approvalPopupInitialized = false;
                            window.eventEditingInterface.initializeApprovalPopup();
                            console.log('openEventEditingModal: Approval popup reinitialized (modalContainer path)');
                        }
                    }, 100);

                    // Initialize Email Composer from embedded context data
                    setTimeout(() => {
                        _initEmailComposerFromDOM();
                    }, 150);

                    if (requiresReview && extractedFields && Object.keys(extractedFields).length > 0) {
                        const hasPendingFields = Object.values(extractedFields).some(
                            field => field && field.status === 'pending'
                        );
                        if (hasPendingFields) {
                            setTimeout(() => {
                                if (window.eventEditingInterface && window.eventEditingInterface.initializeReviewMode) {
                                    window.eventEditingInterface.initializeReviewMode(extractedFields);
                                }
                            }, 300);
                        }
                    }
                }

                setupEventEditingClose(container);
            } else {
                throw new Error('Could not find event editing interface in response');
            }
        })
        .catch(error => {
            console.error('Error loading event editing interface:', error);
            container.innerHTML = `
                <div class="v2-modal-overlay active" id="v2-modal-overlay">
                    <div style="background: var(--bg-primary); padding: 2rem; border-radius: var(--radius-xl); max-width: 500px; margin: auto;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                            <h3 style="margin: 0;">Error Loading Event</h3>
                            <button onclick="closeEventEditingModal()" style="background: none; border: none; font-size: 24px; cursor: pointer;">&times;</button>
                        </div>
                        <p style="color: var(--text-secondary);">Failed to load event details. Please try again.</p>
                        <div style="margin-top: 1rem;">
                            <button onclick="closeEventEditingModal()" class="btn btn-secondary">Close</button>
                        </div>
                    </div>
                </div>
            `;
        });
}

/**
 * Set up close handler for the event editing modal
 */
function setupEventEditingClose(container) {
    // Handle clicks outside the modal
    container.addEventListener('click', function(e) {
        if (e.target === container || e.target.classList.contains('v2-modal-overlay')) {
            closeEventEditingModal();
        }
    });

    // Handle escape key.
    //
    // The EventEditingModalV2 instance registers the single *authoritative*
    // Escape handler (see bindOverlayEvents): it closes the topmost open popup
    // first — approval review, routing builder, email-panel popups, confirm
    // dialogs — and only closes the modal itself once nothing is layered on top.
    // Defer to it whenever it's active; otherwise this fallback handler would
    // ALSO fire on the same keypress and close the entire modal out from under
    // an open popup (the reported "Escape closes the whole modal" bug).
    const escHandler = function(e) {
        if (e.key !== 'Escape') return;
        const v2 = window.eventEditingInterface;
        if (v2 && v2.overlay && v2.overlay.classList.contains('active')) {
            return; // the modal's own handler owns Escape while it's open
        }
        closeEventEditingModal();
        document.removeEventListener('keydown', escHandler);
    };
    document.addEventListener('keydown', escHandler);

    // Provide closeModal alias for compatibility with event-editing-interface.js
    window.closeModal = closeEventEditingModal;
}

/**
 * Close the event editing modal
 */
async function closeEventEditingModal() {
    // If there's an active modal interface, let it handle save + close (it handles both layers)
    if (window.eventEditingInterface && typeof window.eventEditingInterface.handleCloseRequest === 'function') {
        await window.eventEditingInterface.handleCloseRequest();
        return;
    }

    // Fallback: no interface instance, just clean up the container
    const container = document.getElementById('event-editing-container');
    if (!container) return;

    container.classList.remove('active');
    container.setAttribute('aria-hidden', 'true');
    container.innerHTML = '<div class="loading-indicator"><div class="spinner"></div><div>Loading event...</div></div>';
    document.body.style.overflow = '';
}

// Expose globally
window.createNewEvent = createNewEvent;
window.openEventEditingModal = openEventEditingModal;
window.openReadOnlyEventModal = openReadOnlyEventModal;
window.closeEventEditingModal = closeEventEditingModal;
window.showEventDetails = openEventEditingModal;
window.showEventEditingInterface = openEventEditingModal;

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEventEditingModalV2);
} else {
    initEventEditingModalV2();
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EventEditingModalV2, initEventEditingModalV2, createNewEvent };
}
