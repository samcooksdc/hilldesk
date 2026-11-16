/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Email Template Management for HillDesk Settings Page.
 * Handles CRUD operations for email response templates.
 */

class EmailTemplateManager {
    constructor() {
        this.templates = [];
        this.editingTemplateId = null;
        this._initialized = false;
    }

    init() {
        if (this._initialized) return;
        this._bindEvents();
        this._initialized = true;

        // Load templates when the tab becomes visible
        const tab = document.querySelector('[data-tab="templates"]');
        if (tab) {
            tab.addEventListener('click', () => {
                setTimeout(() => this.loadTemplates(), 100);
            });
        }
    }

    _bindEvents() {
        // Relocate the overlay to <body> so position:fixed is resolved against
        // the viewport, not the sidebar-offset content container (which would
        // otherwise double-count the sidebar width).
        const overlayEl = document.getElementById('et-editor-modal');
        if (overlayEl && overlayEl.parentElement !== document.body) {
            document.body.appendChild(overlayEl);
        }

        // New template button
        const newBtn = document.getElementById('et-new-template-btn');
        if (newBtn) {
            newBtn.addEventListener('click', () => this.openEditor());
        }

        // Save button
        const saveBtn = document.getElementById('et-save-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this.saveTemplate());
        }

        // Header close (×) — save and close, like clicking out
        const closeBtn = document.getElementById('et-cancel-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this._saveAndClose());

        // Footer "Cancel" — discard and close
        const cancelBtn = document.getElementById('et-cancel-btn-footer');
        if (cancelBtn) cancelBtn.addEventListener('click', () => this.closeEditor());

        // Click outside the modal — save and close
        const overlay = document.getElementById('et-editor-modal');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) this._saveAndClose();
            });
        }

        // Escape — save and close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay && overlay.classList.contains('visible')) {
                this._saveAndClose();
            }
        });

        // Track which field (subject or body) last had focus so the
        // "Insert variable" menu inserts into whichever one was being edited.
        // On blur, re-style {placeholders} in a monospace font.
        this._activeField = document.getElementById('et-body');
        ['et-subject', 'et-body'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('focus', () => { this._activeField = el; });
            el.addEventListener('blur', () => this._highlightPlaceholders(el));
            // While typing, drop the monospace styling from any placeholder
            // that's been broken (e.g. by backspacing a brace).
            el.addEventListener('input', () => this._cleanupPlaceholders(el));
        });

        // Keep the subject a single line
        const subjectEl = document.getElementById('et-subject');
        if (subjectEl) {
            subjectEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') e.preventDefault();
            });
        }

        // Build the "Insert variable" menu
        this._renderVariableMenu();

        // "Insert variable" menu: open on hover/click, close on select,
        // outside click, or when the pointer moves too far away.
        const insertBtn = document.getElementById('et-insert-var-btn');
        const menu = document.getElementById('et-var-menu');
        const menuWrap = document.getElementById('et-var-menu-wrap');
        if (insertBtn && menu) {
            insertBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.toggle('visible');
            });
            if (menuWrap) {
                menuWrap.addEventListener('mouseenter', () => menu.classList.add('visible'));
            }
            // Close when clicking elsewhere
            document.addEventListener('click', () => menu.classList.remove('visible'));
            // Close when the pointer drifts too far from the open menu
            document.addEventListener('mousemove', (e) => {
                if (!menu.classList.contains('visible')) return;
                const r = menu.getBoundingClientRect();
                const margin = 60;
                if (e.clientX < r.left - margin || e.clientX > r.right + margin ||
                    e.clientY < r.top - margin || e.clientY > r.bottom + margin) {
                    menu.classList.remove('visible');
                }
            });
        }

        // Rich-text formatting bar (bold / italic / link / bullet list)
        document.querySelectorAll('.et-format-btn').forEach(btn => {
            // Keep the body's selection while clicking a format button
            btn.addEventListener('mousedown', (e) => e.preventDefault());
            btn.addEventListener('click', () => {
                const command = btn.dataset.command;
                const body = this._bodyEl();
                if (body) body.focus();
                if (command === 'createLink') {
                    const url = prompt('Enter URL:');
                    if (url) document.execCommand('createLink', false, url);
                } else {
                    document.execCommand(command, false, null);
                }
            });
        });

        // Tab / bullet indentation handling in the body
        const bodyEl = this._bodyEl();
        if (bodyEl) {
            bodyEl.addEventListener('keydown', (e) => this._handleBodyKeydown(e));
        }
    }

    // =========================================================================
    // Rich-text body helpers
    // =========================================================================

    _bodyEl() {
        return document.getElementById('et-body');
    }

    _getBodyHtml() {
        const el = this._bodyEl();
        if (!el) return '';
        // Strip the display-only placeholder-highlight spans before saving
        const clone = el.cloneNode(true);
        clone.querySelectorAll('span.et-ph').forEach(s => s.replaceWith(document.createTextNode(s.textContent)));
        clone.normalize();
        return clone.innerHTML;
    }

    _getBodyText() {
        const el = this._bodyEl();
        return el ? el.textContent : '';
    }

    _setBody(value) {
        const el = this._bodyEl();
        if (!el) return;
        // New rich templates are stored as HTML; legacy templates are plain
        // text — convert their newlines to <br> so line breaks are preserved.
        const looksHtml = /<[a-z][\s\S]*>/i.test(value || '');
        el.innerHTML = looksHtml ? (value || '') : this._escapeHtml(value || '').replace(/\n/g, '<br>');
        this._highlightPlaceholders(el);
    }

    _getSubjectText() {
        const el = document.getElementById('et-subject');
        return el ? el.textContent : '';
    }

    _setSubject(text) {
        const el = document.getElementById('et-subject');
        if (!el) return;
        el.textContent = text || '';
        this._highlightPlaceholders(el);
    }

    /**
     * Remove the monospace styling from any placeholder span that is no longer
     * a complete {token} (e.g. after backspacing a brace) or is empty, so the
     * formatting doesn't linger. Preserves the caret if it's inside the span.
     */
    _cleanupPlaceholders(el) {
        if (!el) return;
        const sel = window.getSelection();
        el.querySelectorAll('span.et-ph').forEach(span => {
            if (/^\{[^{}]+\}$/.test(span.textContent)) return; // still valid
            let caretOffset = null;
            if (sel && sel.rangeCount && span.contains(sel.anchorNode)) {
                caretOffset = sel.anchorOffset;
            }
            const textNode = document.createTextNode(span.textContent);
            span.replaceWith(textNode);
            if (caretOffset != null) {
                const range = document.createRange();
                range.setStart(textNode, Math.min(caretOffset, textNode.length));
                range.collapse(true);
                sel.removeAllRanges();
                sel.addRange(range);
            }
        });
    }

    /**
     * Wrap {placeholders} in a monospace span so they stand out from prose.
     * Operates on text nodes only, preserving any rich formatting, and is
     * idempotent (unwraps existing spans first). Spans are display-only.
     */
    _highlightPlaceholders(el) {
        if (!el) return;
        el.querySelectorAll('span.et-ph').forEach(span => {
            span.replaceWith(document.createTextNode(span.textContent));
        });
        el.normalize();

        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
        const targets = [];
        let node;
        while ((node = walker.nextNode())) {
            if (/\{[^{}]+\}/.test(node.nodeValue)) targets.push(node);
        }
        targets.forEach(textNode => {
            const frag = document.createDocumentFragment();
            textNode.nodeValue.split(/(\{[^{}]+\})/g).forEach(part => {
                if (!part) return;
                if (/^\{[^{}]+\}$/.test(part)) {
                    const span = document.createElement('span');
                    span.className = 'et-ph';
                    span.textContent = part;
                    frag.appendChild(span);
                } else {
                    frag.appendChild(document.createTextNode(part));
                }
            });
            textNode.replaceWith(frag);
        });
    }

    _handleBodyKeydown(e) {
        if (e.key !== 'Tab') return;
        e.preventDefault();
        const body = this._bodyEl();
        if (this._isInList(body)) {
            document.execCommand(e.shiftKey ? 'outdent' : 'indent', false, null);
        } else if (!e.shiftKey) {
            document.execCommand('insertText', false, '    ');
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

    /**
     * Variables available to templates. Tokens map to the context built in
     * draft_generation_service.build_context().
     */
    static get VARIABLES() {
        return [
            { label: 'Member name', token: '{member_name}' },
            { label: 'Staffer name', token: '{staffer_name}' },
            { label: 'Sender name', token: '{sender_name}' },
            { label: 'Event title', token: '{event_title}' },
            { label: 'Event date', token: '{event_date}' },
            { label: 'Event time', token: '{event_time}' },
            { label: 'Event end date', token: '{event_end_date}' },
            { label: 'Event end time', token: '{event_end_time}' },
            { label: 'Location', token: '{event_location}' },
            { label: 'Description', token: '{event_description}' },
            { label: 'Status', token: '{event_status}' },
            { label: 'Organization', token: '{organization}' },
            { label: 'Contact name', token: '{contact_name}' },
            { label: 'Contact email', token: '{contact_email}' },
            { label: 'Contact phone', token: '{contact_phone}' },
            { label: 'Custom', token: '{ PLACEHOLDER }' },
        ];
    }

    _renderVariableMenu() {
        const menu = document.getElementById('et-var-menu');
        if (!menu) return;
        menu.innerHTML = EmailTemplateManager.VARIABLES.map(v => `
            <button type="button" class="et-var-item" data-insert="${this._escapeHtml(v.token)}" role="menuitem">
                <span class="et-var-item-label">${this._escapeHtml(v.label)}</span>
                <span class="et-var-item-token">${this._escapeHtml(v.token)}</span>
            </button>`).join('');

        menu.querySelectorAll('.et-var-item').forEach(item => {
            // Use mousedown so the field doesn't lose focus before we read it
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this._insertVariable(item.dataset.insert);
                menu.classList.remove('visible');
            });
        });
    }

    _insertVariable(token) {
        const field = this._activeField || this._bodyEl();
        if (!field) return;
        if (field.isContentEditable) {
            // Insert a styled (monospace) placeholder at the caret
            field.focus();
            document.execCommand('insertHTML', false, `<span class="et-ph">${this._escapeHtml(token)}</span>`);
        } else {
            // Plain input (subject)
            const start = field.selectionStart ?? field.value.length;
            const end = field.selectionEnd ?? field.value.length;
            field.value = field.value.slice(0, start) + token + field.value.slice(end);
            const pos = start + token.length;
            field.focus();
            field.setSelectionRange(pos, pos);
        }
        this._activeField = field;
    }

    // =========================================================================
    // Load & Render Templates
    // =========================================================================

    async loadTemplates() {
        const listEl = document.getElementById('et-template-list');
        if (!listEl) return;

        listEl.innerHTML = '<div class="et-loading">Loading templates...</div>';

        try {
            const response = await fetch('/api/email/templates/?include_inactive=true', {
                headers: { 'X-CSRFToken': this._getCSRFToken() }
            });
            const data = await response.json();
            this.templates = data.templates || [];
            this._renderTemplateList(data.grouped || []);
        } catch (err) {
            console.error('Failed to load templates:', err);
            listEl.innerHTML = '<div class="et-loading" style="color: #ef4444;">Failed to load templates</div>';
        }
    }

    _renderTemplateList(grouped) {
        const listEl = document.getElementById('et-template-list');
        if (!listEl) return;

        if (!grouped.length) {
            listEl.innerHTML = '<div class="et-loading">No templates found</div>';
            return;
        }

        let html = '';
        grouped.forEach(group => {
            html += `<div class="et-category-group">
                <div class="et-category-header">
                    <span class="et-category-badge et-category-${group.category}">${this._escapeHtml(group.category_display)}</span>
                    <span class="et-category-count">${group.templates.length} template${group.templates.length !== 1 ? 's' : ''}</span>
                </div>`;

            group.templates.forEach(t => {
                const activeClass = t.is_active ? '' : ' et-template-inactive';
                const activeToggle = t.is_active
                    ? '<span class="et-active-indicator">Active</span>'
                    : '<span class="et-inactive-indicator">Inactive</span>';

                html += `<div class="et-template-card${activeClass}" data-id="${t.id}">
                    <div class="et-template-card-header">
                        <div class="et-template-card-title">
                            <span>${this._escapeHtml(t.name)}</span>
                        </div>
                        <div class="et-template-card-actions">
                            ${activeToggle}
                            <button type="button" class="et-delete-btn" data-id="${t.id}" data-name="${this._escapeHtml(t.name)}" data-tooltip="Delete" aria-label="Delete">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="et-template-card-subject">${this._escapeHtml(t.subject)}</div>
                </div>`;
            });

            html += '</div>';
        });

        listEl.innerHTML = html;

        // Whole card opens the editor
        listEl.querySelectorAll('.et-template-card').forEach(card => {
            card.addEventListener('click', () => this.openEditor(card.dataset.id));
        });

        // Delete button (don't let the click bubble to the card)
        listEl.querySelectorAll('.et-delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteTemplate(btn.dataset.id, btn.dataset.name);
            });
        });
    }

    // =========================================================================
    // Editor
    // =========================================================================

    openEditor(templateId) {
        const overlay = document.getElementById('et-editor-modal');
        const title = document.getElementById('et-editor-title');
        if (!overlay) return;

        this.editingTemplateId = templateId || null;

        if (templateId) {
            // Edit existing
            const template = this.templates.find(t => t.id === templateId);
            if (!template) return;

            title.textContent = 'Edit Template';
            document.getElementById('et-name').value = template.name;
            document.getElementById('et-category').value = template.category;
            this._setSubject(template.subject);
            this._setBody(template.body);
            document.getElementById('et-is-active').checked = template.is_active;
        } else {
            // New template
            title.textContent = 'New Template';
            document.getElementById('et-name').value = '';
            document.getElementById('et-category').value = 'custom';
            this._setSubject('');
            this._setBody('');
            document.getElementById('et-is-active').checked = true;
        }

        // Show modal, scrolled at the top, focusing the first field
        overlay.classList.add('visible');
        const body = overlay.querySelector('.staff-modal-body');
        if (body) body.scrollTop = 0;
        document.getElementById('et-name').focus({ preventScroll: true });
    }

    closeEditor() {
        const overlay = document.getElementById('et-editor-modal');
        if (overlay) overlay.classList.remove('visible');
        this.editingTemplateId = null;
    }

    // =========================================================================
    // Save & Delete
    // =========================================================================

    /**
     * Save and close. Used when clicking out / pressing Escape / the × button.
     * Auto-saves only when the form is complete; otherwise closes without nagging.
     */
    async _saveAndClose() {
        const name = document.getElementById('et-name').value.trim();
        const subject = this._getSubjectText().trim();
        const bodyText = this._getBodyText().trim();
        if (name && subject && bodyText) {
            await this.saveTemplate({ silent: true });
        } else {
            this.closeEditor();
        }
    }

    async saveTemplate({ silent = false } = {}) {
        const name = document.getElementById('et-name').value.trim();
        const category = document.getElementById('et-category').value;
        const subject = this._getSubjectText().trim();
        const body = this._getBodyHtml().trim();
        const bodyText = this._getBodyText().trim();
        const isActive = document.getElementById('et-is-active').checked;

        if (!name || !subject || !bodyText) {
            if (silent) { this.closeEditor(); return; }
            alert('Please fill in name, subject, and body.');
            return;
        }

        // Detect variables used in subject + body
        const varMatches = new Set();
        const combined = subject + ' ' + bodyText;
        const regex = /\{(\w+)\}/g;
        let match;
        while ((match = regex.exec(combined)) !== null) {
            varMatches.add(match[1]);
        }

        const payload = {
            name,
            category,
            subject,
            body,
            variables: Array.from(varMatches),
            is_active: isActive,
        };

        const saveBtn = document.getElementById('et-save-btn');
        if (saveBtn) saveBtn.disabled = true;

        try {
            let url, method;
            if (this.editingTemplateId) {
                url = `/api/email/templates/${this.editingTemplateId}/`;
                method = 'PUT';
            } else {
                url = '/api/email/templates/create/';
                method = 'POST';
            }

            const response = await fetch(url, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCSRFToken(),
                },
                body: JSON.stringify(payload),
            });

            if (response.ok) {
                this.closeEditor();
                this.loadTemplates();
            } else {
                const data = await response.json().catch(() => ({}));
                if (!silent) alert(data.error || 'Failed to save template');
                else this.closeEditor();
            }
        } catch (err) {
            console.error('Failed to save template:', err);
            if (!silent) alert('Failed to save template');
            else this.closeEditor();
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async deleteTemplate(templateId, templateName) {
        if (!confirm(`Delete template "${templateName}"? This cannot be undone.`)) return;

        try {
            const response = await fetch(`/api/email/templates/${templateId}/delete/`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this._getCSRFToken() },
            });

            if (response.ok) {
                this.loadTemplates();
            } else {
                const data = await response.json();
                alert(data.error || 'Failed to delete template');
            }
        } catch (err) {
            console.error('Failed to delete template:', err);
            alert('Failed to delete template');
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    _getCSRFToken() {
        const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        if (cookie) return cookie.split('=')[1];
        const hidden = document.querySelector('[name=csrfmiddlewaretoken]');
        return hidden ? hidden.value : '';
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const manager = new EmailTemplateManager();
    manager.init();

    // Auto-load templates if the tab is already visible
    const activeTab = document.querySelector('.settings-tab.active');
    if (activeTab && activeTab.dataset.tab === 'templates') {
        manager.loadTemplates();
    }

    window.emailTemplateManager = manager;
});
