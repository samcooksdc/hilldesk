/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Export Template Management for HillDesk Settings Page (Templates tab).
 *
 * Renders one section per export type (always shown, even when empty), each
 * with its own "Upload" button. Uploading opens a small modal that only asks
 * for a name + file — the type comes from whichever section's button was used.
 *
 * Backend endpoints (apps/api/urls.py):
 *   GET    /api/export/templates/
 *   POST   /api/export/templates/upload/         (multipart: file, name, template_type)
 *   DELETE /api/export/templates/<id>/delete/
 *   GET    /api/export/templates/<id>/download/
 */

class ExportTemplateManager {
    constructor() {
        this.templates = [];
        this._initialized = false;
        this._selectedFile = null;
        this._uploadType = null;
    }

    // The canonical export types — each gets its own always-visible section.
    static get TYPE_SECTIONS() {
        return [
            { type: 'daily_briefing', label: 'Daily Briefing' },
            { type: 'weekly_overview', label: 'Weekly Overview' },
            { type: 'event_detail', label: 'Event Detail' },
            { type: 'filtered_list', label: 'Filtered List' },
        ];
    }

    init() {
        if (this._initialized) return;
        this._bindEvents();
        this._initPlaceholderCopy();
        this._initialized = true;

        // Load when the Templates tab becomes visible.
        const tab = document.querySelector('[data-tab="templates"]');
        if (tab) {
            tab.addEventListener('click', () => {
                setTimeout(() => this.loadTemplates(), 100);
            });
        }
    }

    _bindEvents() {
        // Move the modal overlay to <body> so position:fixed is resolved against
        // the viewport, not the sidebar-offset content container.
        const overlay = document.getElementById('exp-upload-modal');
        if (overlay && overlay.parentElement !== document.body) {
            document.body.appendChild(overlay);
        }

        const saveBtn = document.getElementById('exp-save-btn');
        if (saveBtn) saveBtn.addEventListener('click', () => this.upload());

        const closeBtn = document.getElementById('exp-cancel-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => this.closeUpload());

        const cancelBtn = document.getElementById('exp-cancel-btn-footer');
        if (cancelBtn) cancelBtn.addEventListener('click', () => this.closeUpload());

        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) this.closeUpload();
            });
        }
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay && overlay.classList.contains('visible')) {
                this.closeUpload();
            }
        });

        // File selection + drag-and-drop on the dropzone.
        const fileInput = document.getElementById('exp-file-input');
        if (fileInput) {
            fileInput.addEventListener('change', () => {
                this._setFile(fileInput.files && fileInput.files[0]);
            });
        }
        const dropzone = document.getElementById('exp-dropzone');
        if (dropzone) {
            ['dragenter', 'dragover'].forEach(evt => {
                dropzone.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dropzone.classList.add('exp-dropzone-active');
                });
            });
            ['dragleave', 'drop'].forEach(evt => {
                dropzone.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dropzone.classList.remove('exp-dropzone-active');
                });
            });
            dropzone.addEventListener('drop', (e) => {
                const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
                this._setFile(file);
            });
        }
    }

    // =========================================================================
    // Load & render
    // =========================================================================

    async loadTemplates() {
        const listEl = document.getElementById('exp-template-list');
        if (!listEl) return;

        listEl.innerHTML = '<div class="et-loading">Loading export templates...</div>';
        try {
            const response = await fetch('/api/export/templates/', {
                headers: { 'X-CSRFToken': this._getCSRFToken() }
            });
            const data = await response.json();
            this.templates = data.templates || [];
            this._render(this.templates);
        } catch (err) {
            console.error('Failed to load export templates:', err);
            listEl.innerHTML = '<div class="et-loading" style="color: #ef4444;">Failed to load export templates</div>';
        }
    }

    _render(templates) {
        const listEl = document.getElementById('exp-template-list');
        if (!listEl) return;

        const html = ExportTemplateManager.TYPE_SECTIONS
            .map(section => this._groupHtml(section.label, section.type, this._effectiveFor(section.type, templates)))
            .join('');

        listEl.innerHTML = html;
        this._wireListEvents(listEl);
    }

    // One template per type: prefer the office upload, else the built-in default.
    _effectiveFor(type, templates) {
        const ofType = templates.filter(t => t.template_type === type);
        return ofType.find(t => !t.is_default) || ofType.find(t => t.is_default) || null;
    }

    _groupHtml(label, type, t) {
        const slot = t ? this._slotHtml(t, label, type) : this._emptySlotHtml(label, type);
        return `<div class="exp-group">
            <div class="exp-group-header">
                <span class="et-category-badge">${this._escapeHtml(label)}</span>
            </div>
            ${slot}
        </div>`;
    }

    _slotHtml(t, label, type) {
        const builtIn = t.is_default;
        const badge = builtIn
            ? '<span class="exp-builtin-badge">Built-in</span>'
            : '<span class="exp-custom-badge">Custom</span>';

        return `<div class="exp-slot" data-id="${t.id}">
            <div class="exp-slot-info">
                <span class="exp-slot-name">${this._escapeHtml(t.name)}</span>
                ${badge}
            </div>
            <div class="exp-slot-actions">
                <button type="button" class="exp-icon-btn exp-download-btn" data-id="${t.id}" data-tooltip="Download" aria-label="Download">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                </button>
                <button type="button" class="exp-icon-btn exp-replace-btn" data-upload-type="${type}" data-upload-label="${this._escapeHtml(label)}" data-tooltip="Upload a replacement" aria-label="Upload a replacement">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="17 8 12 3 7 8"></polyline>
                        <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                </button>
                <button type="button" class="exp-icon-btn exp-delete-btn" data-id="${t.id}" data-name="${this._escapeHtml(t.name)}" data-builtin="${builtIn ? '1' : ''}" data-tooltip="Delete" aria-label="Delete">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        </div>`;
    }

    _emptySlotHtml(label, type) {
        return `<div class="exp-slot exp-slot--empty">
            <span class="exp-slot-empty-text">No template</span>
            <button type="button" class="exp-group-upload exp-replace-btn" data-upload-type="${type}" data-upload-label="${this._escapeHtml(label)}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                Upload
            </button>
        </div>`;
    }

    _wireListEvents(listEl) {
        listEl.querySelectorAll('.exp-replace-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openUpload(btn.dataset.uploadType, btn.dataset.uploadLabel);
            });
        });
        listEl.querySelectorAll('.exp-download-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                window.location.href = `/api/export/templates/${btn.dataset.id}/download/`;
            });
        });
        listEl.querySelectorAll('.exp-delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteTemplate(btn.dataset.id, btn.dataset.name, btn.dataset.builtin === '1');
            });
        });
    }

    // =========================================================================
    // Upload
    // =========================================================================

    openUpload(type, label) {
        const overlay = document.getElementById('exp-upload-modal');
        if (!overlay) return;
        this._uploadType = type;

        const title = document.getElementById('exp-upload-title');
        if (title) title.textContent = `Upload ${label} template`;

        const nameInput = document.getElementById('exp-name');
        nameInput.value = '';
        this._setFile(null);
        this._showError(null);
        overlay.classList.add('visible');
        nameInput.focus({ preventScroll: true });
    }

    closeUpload() {
        const overlay = document.getElementById('exp-upload-modal');
        if (overlay) overlay.classList.remove('visible');
    }

    _setFile(file) {
        const textEl = document.getElementById('exp-dropzone-text');
        const nameEl = document.getElementById('exp-name');
        const defaultText = 'Choose a file or drag it here';
        if (file && !file.name.toLowerCase().endsWith('.docx')) {
            this._showError('Only .docx files are accepted.');
            this._selectedFile = null;
            if (textEl) textEl.textContent = defaultText;
            return;
        }
        this._selectedFile = file || null;
        this._showError(null);
        if (textEl) textEl.textContent = file ? file.name : defaultText;
        // Default the name to the filename (minus extension) if empty.
        if (file && nameEl && !nameEl.value.trim()) {
            nameEl.value = file.name.replace(/\.docx$/i, '');
        }
    }

    async upload() {
        const name = document.getElementById('exp-name').value.trim();
        const templateType = this._uploadType;
        const file = this._selectedFile;

        if (!templateType) { this._showError('Something went wrong — reopen the upload dialog.'); return; }
        if (!file) { this._showError('Choose a .docx file to upload.'); return; }
        if (!name) { this._showError('Give the template a name.'); return; }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('name', name);
        formData.append('template_type', templateType);

        const saveBtn = document.getElementById('exp-save-btn');
        if (saveBtn) saveBtn.disabled = true;
        this._showError(null);

        try {
            const response = await fetch('/api/export/templates/upload/', {
                method: 'POST',
                headers: { 'X-CSRFToken': this._getCSRFToken() },
                body: formData,
            });
            if (response.ok) {
                this.closeUpload();
                this.loadTemplates();
            } else {
                const data = await response.json().catch(() => ({}));
                let msg = data.error || 'Upload failed.';
                if (Array.isArray(data.details) && data.details.length) {
                    msg += ' ' + data.details.join(' ');
                }
                this._showError(msg);
            }
        } catch (err) {
            console.error('Export template upload failed:', err);
            this._showError('Upload failed. Please try again.');
        } finally {
            if (saveBtn) saveBtn.disabled = false;
        }
    }

    async deleteTemplate(templateId, templateName, isBuiltIn) {
        const message = isBuiltIn
            ? `Delete the built-in template "${templateName}"? Until you upload a replacement, exports of this type will ask for a template first. This cannot be undone.`
            : `Delete export template "${templateName}"? This cannot be undone.`;
        if (!confirm(message)) return;
        try {
            const response = await fetch(`/api/export/templates/${templateId}/delete/`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this._getCSRFToken() },
            });
            if (response.ok) {
                this.loadTemplates();
            } else {
                const data = await response.json().catch(() => ({}));
                alert(data.error || 'Failed to delete template');
            }
        } catch (err) {
            console.error('Failed to delete export template:', err);
            alert('Failed to delete template');
        }
    }

    // =========================================================================
    // Placeholder reference — click any row to copy the token
    // =========================================================================

    _initPlaceholderCopy() {
        const container = document.getElementById('exp-ph-groups');
        if (!container) return;
        container.addEventListener('click', (e) => {
            const item = e.target.closest('.exp-ph-item');
            if (!item) return;
            const code = item.querySelector('code');
            const token = code ? code.textContent.trim() : '';
            if (token) this._copyText(token, code);
        });
    }

    _copyText(text, anchorEl) {
        const done = () => this._showCopied(anchorEl);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(() => this._fallbackCopy(text, done));
        } else {
            this._fallbackCopy(text, done);
        }
    }

    _fallbackCopy(text, done) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (e) { /* no-op */ }
        document.body.removeChild(ta);
        done();
    }

    _showCopied(anchorEl) {
        if (!anchorEl) return;
        let tip = document.getElementById('exp-copy-tooltip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'exp-copy-tooltip';
            tip.className = 'exp-copy-tooltip';
            document.body.appendChild(tip);
        }
        tip.textContent = 'Placeholder copied';
        tip.style.display = 'block';

        // Center above the clicked token; flip below if there's no room.
        const a = anchorEl.getBoundingClientRect();
        const t = tip.getBoundingClientRect();
        let left = a.left + a.width / 2 - t.width / 2;
        let top = a.top - t.height - 8;
        left = Math.max(4, Math.min(left, window.innerWidth - t.width - 4));
        if (top < 4) top = a.bottom + 8;
        tip.style.left = `${left}px`;
        tip.style.top = `${top}px`;

        // Force reflow so the fade runs again on rapid repeat clicks.
        void tip.offsetWidth;
        tip.classList.add('visible');

        clearTimeout(this._copyTooltipTimer);
        this._copyTooltipTimer = setTimeout(() => {
            tip.classList.remove('visible');
        }, 1100);
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    _showError(message) {
        const el = document.getElementById('exp-upload-error');
        if (!el) return;
        if (message) {
            el.textContent = message;
            el.hidden = false;
        } else {
            el.textContent = '';
            el.hidden = true;
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
        div.textContent = text || '';
        return div.innerHTML;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const manager = new ExportTemplateManager();
    manager.init();

    // Auto-load if the Templates tab is already active on page load.
    const activeTab = document.querySelector('.settings-tab.active');
    if (activeTab && activeTab.dataset.tab === 'templates') {
        manager.loadTemplates();
    }

    window.exportTemplateManager = manager;
});
