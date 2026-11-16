/* SPDX-License-Identifier: Apache-2.0 */
/**
 * filter-presets.js
 * -----------------------------------------------------------------------------
 * Shared "named filter presets" dropdown used by both the Events (schedule) and
 * Calendar filter sidebars. Presets are stored per-user (not per-office) via
 * /api/user/filter-presets/.
 *
 * The host view supplies an adapter so this module stays UI-agnostic:
 *   adapter.getCsrf()        -> CSRF token string
 *   adapter.getCurrentData() -> canonical preset-data object from current filters
 *   adapter.applyData(data)  -> apply a preset's data object to the view
 *   adapter.showToast(msg)   -> surface a short message to the user
 *
 * Usage:
 *   const mgr = new FilterPresetManager(adapter);
 *   await mgr.load();                       // fetch presets (and detect default)
 *   container.prepend(mgr.render());        // insert dropdown at top of sidebar
 *   const def = mgr.getDefault();           // {id,name,data,is_default} | null
 */
(function (window) {
    'use strict';

    const ENDPOINT = '/api/user/filter-presets/';

    // --- small inline icons (stroke = currentColor) -------------------------
    const ICON = {
        bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>',
        chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
        starOutline: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
        starFilled: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
        trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
        check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
        plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    };

    class FilterPresetManager {
        constructor(adapter) {
            this.adapter = adapter;
            this.presets = [];
            this.activeId = null;
            this.open = false;
            this.root = null;          // .filter-presets element
            this.saveButtonWrap = null;
            this._onDocClick = this._handleDocClick.bind(this);
        }

        // --- data ------------------------------------------------------------
        async load() {
            try {
                const resp = await fetch(ENDPOINT, {
                    headers: { 'X-CSRFToken': this.adapter.getCsrf() },
                });
                if (resp.ok) {
                    this.presets = await resp.json();
                }
            } catch (e) {
                console.error('Failed to load filter presets', e);
            }
            return this.presets;
        }

        getDefault() {
            return this.presets.find(p => p.is_default) || null;
        }

        /** Mark which preset is currently applied (e.g. the default on load). */
        setActive(id) {
            this.activeId = id;
            this._refreshLabel();
            this._refreshList();
        }

        /** Deselect the active preset (resets the trigger label to "Filter presets"). */
        clearActive() {
            this.activeId = null;
            this._refreshLabel();
            this._refreshList();
        }

        // --- rendering -------------------------------------------------------
        render() {
            const root = document.createElement('div');
            root.className = 'filter-presets';
            root.dataset.section = 'presets';
            root.innerHTML = `
                <div class="preset-dropdown">
                    <button type="button" class="preset-dropdown-trigger" aria-haspopup="true" aria-expanded="false">
                        <span class="preset-trigger-icon">${ICON.bookmark}</span>
                        <span class="preset-dropdown-label">Filter presets</span>
                        <span class="preset-chevron">${ICON.chevron}</span>
                    </button>
                    <div class="preset-dropdown-menu" role="menu">
                        <div class="preset-list"></div>
                    </div>
                </div>
            `;
            this.root = root;

            this.trigger = root.querySelector('.preset-dropdown-trigger');
            this.menu = root.querySelector('.preset-dropdown-menu');
            this.listEl = root.querySelector('.preset-list');

            this.trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggle();
            });

            // Close when the mouse leaves the whole control (trigger + menu).
            root.addEventListener('mouseleave', () => {
                if (this.open) this.close();
            });

            this._refreshLabel();
            this._refreshList();
            return root;
        }

        _refreshLabel() {
            if (!this.root) return;
            const label = this.root.querySelector('.preset-dropdown-label');
            const active = this.presets.find(p => p.id === this.activeId);
            label.textContent = active ? active.name : 'Filter presets';
            this.root.classList.toggle('has-active', !!active);
        }

        _refreshList() {
            if (!this.listEl) return;
            this.listEl.innerHTML = '';

            if (!this.presets.length) {
                const empty = document.createElement('div');
                empty.className = 'preset-empty';
                empty.textContent = 'No saved presets yet';
                this.listEl.appendChild(empty);
                return;
            }

            this.presets.forEach((preset) => {
                const row = document.createElement('div');
                row.className = 'preset-item';
                if (preset.id === this.activeId) row.classList.add('active');

                const applyBtn = document.createElement('button');
                applyBtn.type = 'button';
                applyBtn.className = 'preset-item-apply';
                applyBtn.innerHTML = `<span class="preset-item-name"></span>`;
                applyBtn.querySelector('.preset-item-name').textContent = preset.name;
                applyBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.apply(preset.id);
                });

                const starBtn = document.createElement('button');
                starBtn.type = 'button';
                starBtn.className = 'preset-item-default preset-tip' + (preset.is_default ? ' is-default' : '');
                starBtn.setAttribute('data-tooltip', preset.is_default ? 'Unset default' : 'Set as default');
                starBtn.innerHTML = preset.is_default ? ICON.starFilled : ICON.starOutline;
                starBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleDefault(preset.id);
                });

                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'preset-item-delete preset-tip';
                delBtn.setAttribute('data-tooltip', 'Delete');
                delBtn.innerHTML = ICON.trash;
                delBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.remove(preset.id);
                });

                row.appendChild(applyBtn);
                row.appendChild(starBtn);
                row.appendChild(delBtn);
                this.listEl.appendChild(row);
            });
        }

        /**
         * Build the "Save current filters" button (styled like Clear All Filters).
         * Lives in the sidebar above the Clear All button, NOT inside the menu.
         * Clicking it morphs the button into an inline name field.
         */
        renderSaveButton() {
            const wrap = document.createElement('div');
            wrap.className = 'preset-save-button-wrap';
            this.saveButtonWrap = wrap;
            this._renderSaveButtonDefault();
            return wrap;
        }

        _renderSaveButtonDefault() {
            if (!this.saveButtonWrap) return;
            this.saveButtonWrap.innerHTML = '';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'preset-save-btn';
            btn.innerHTML = `<span class="preset-save-icon">${ICON.plus}</span> Save current filters`;
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._renderSaveButtonForm();
            });
            this.saveButtonWrap.appendChild(btn);
        }

        _renderSaveButtonForm() {
            if (!this.saveButtonWrap) return;
            this.saveButtonWrap.innerHTML = '';
            const form = document.createElement('form');
            form.className = 'preset-save-form';
            form.innerHTML = `
                <input type="text" class="preset-name-input" placeholder="Preset name" maxlength="100" autocomplete="off">
                <button type="submit" class="preset-name-confirm preset-tip-top" data-tooltip="Save">${ICON.check}</button>
                <button type="button" class="preset-name-cancel preset-tip-top" data-tooltip="Cancel">${ICON.close}</button>
            `;
            const input = form.querySelector('.preset-name-input');
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                this.save(input.value);
            });
            form.querySelector('.preset-name-cancel').addEventListener('click', (e) => {
                e.stopPropagation();
                this._renderSaveButtonDefault();
            });
            this.saveButtonWrap.appendChild(form);
            input.focus();
        }

        // --- open / close ----------------------------------------------------
        toggle() {
            this.open ? this.close() : this.openMenu();
        }

        openMenu() {
            this.open = true;
            this.root.classList.add('open');
            this.trigger.setAttribute('aria-expanded', 'true');
            document.addEventListener('click', this._onDocClick);
        }

        close() {
            this.open = false;
            this.root.classList.remove('open');
            this.trigger.setAttribute('aria-expanded', 'false');
            document.removeEventListener('click', this._onDocClick);
        }

        _handleDocClick(e) {
            if (this.root && !this.root.contains(e.target)) this.close();
        }

        // --- actions ---------------------------------------------------------
        apply(id) {
            const preset = this.presets.find(p => p.id === id);
            if (!preset) return;
            this.adapter.applyData(preset.data || {});
            this.activeId = id;
            this._refreshLabel();
            this._refreshList();
            this.close();
            this.adapter.showToast(`Applied "${preset.name}"`);
        }

        async save(rawName) {
            const name = (rawName || '').trim();
            if (!name) {
                this.adapter.showToast('Enter a name for the preset');
                return;
            }
            const data = this.adapter.getCurrentData();
            try {
                const resp = await fetch(ENDPOINT, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.adapter.getCsrf(),
                    },
                    body: JSON.stringify({ name, data }),
                });
                if (!resp.ok) throw new Error('save failed');
                const saved = await resp.json();
                // Upsert into local list (server upserts by name)
                const idx = this.presets.findIndex(p => p.id === saved.id);
                if (idx >= 0) this.presets[idx] = saved;
                else this.presets.push(saved);
                this.presets.sort((a, b) => a.name.localeCompare(b.name));
                this.activeId = saved.id;
                this._refreshLabel();
                this._refreshList();
                this._renderSaveButtonDefault();
                this.adapter.showToast(`Saved "${saved.name}"`);
            } catch (e) {
                console.error('Failed to save preset', e);
                this.adapter.showToast('Failed to save preset');
            }
        }

        async toggleDefault(id) {
            const preset = this.presets.find(p => p.id === id);
            if (!preset) return;
            const makeDefault = !preset.is_default;
            try {
                const resp = await fetch(`${ENDPOINT}${id}/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.adapter.getCsrf(),
                    },
                    body: JSON.stringify({ is_default: makeDefault }),
                });
                if (!resp.ok) throw new Error('patch failed');
                // Reflect "one default per user" locally
                this.presets.forEach(p => { p.is_default = (p.id === id) ? makeDefault : false; });
                this._refreshList();
                this.adapter.showToast(
                    makeDefault ? `"${preset.name}" is now the default` : `Cleared default preset`
                );
            } catch (e) {
                console.error('Failed to update default', e);
                this.adapter.showToast('Failed to update default');
            }
        }

        async remove(id) {
            const preset = this.presets.find(p => p.id === id);
            if (!preset) return;
            try {
                const resp = await fetch(`${ENDPOINT}${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.adapter.getCsrf() },
                });
                if (!resp.ok && resp.status !== 204) throw new Error('delete failed');
                this.presets = this.presets.filter(p => p.id !== id);
                if (this.activeId === id) this.activeId = null;
                this._refreshLabel();
                this._refreshList();
                this.adapter.showToast(`Deleted "${preset.name}"`);
            } catch (e) {
                console.error('Failed to delete preset', e);
                this.adapter.showToast('Failed to delete preset');
            }
        }
    }

    window.FilterPresetManager = FilterPresetManager;
})(window);
