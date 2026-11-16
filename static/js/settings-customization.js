/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Settings Customization Manager
 * HillDesk Congressional Scheduling Application
 *
 * Manages the customization interface for event status, type, and format options.
 * Features:
 * - Load/save choices from/to API
 * - Drag-and-drop reordering
 * - Inline label editing
 * - Color picker for status
 * - Add/delete (soft-delete) options
 */

class SettingsCustomization {
    constructor() {
        this.statusChoices = [];
        this.typeChoices = [];
        this.formatChoices = [];
        this.tagsChoices = [];
        this.staffMembers = [];
        this.unlinkedUsers = [];  // Users available for linking
        this.roles = [];           // Office roles (Admin/Scheduler/Staff/custom)
        this.permissionCatalog = []; // Grouped permission catalog for the role builder
        this.permissionDependencies = {}; // key -> [required keys]
        this.canManageRoles = false; // Whether the current user can manage roles
        this.officeInfo = {
            member_name: '',
            district: '',
            dc_office_address: '',
            district_office_address: ''
        };
        this.originalData = {};
        this.hasUnsavedChanges = false;
        this.activeColorPicker = null;
        this.autoSaveTimer = null;
        this.autoSaveDelay = 300; // short debounce so edits save near-instantly
        this.isSaving = false;

        // 16 color palette for status
        this.colorPalette = [
            { name: 'blue', color: '#3b82f6', bg: '#dbeafe' },
            { name: 'indigo', color: '#6366f1', bg: '#e0e7ff' },
            { name: 'purple', color: '#8b5cf6', bg: '#ede9fe' },
            { name: 'pink', color: '#ec4899', bg: '#fce7f3' },
            { name: 'red', color: '#ef4444', bg: '#fee2e2' },
            { name: 'orange', color: '#f97316', bg: '#ffedd5' },
            { name: 'amber', color: '#f59e0b', bg: '#fef3c7' },
            { name: 'yellow', color: '#eab308', bg: '#fef9c3' },
            { name: 'lime', color: '#84cc16', bg: '#ecfccb' },
            { name: 'green', color: '#22c55e', bg: '#dcfce7' },
            { name: 'emerald', color: '#10b981', bg: '#d1fae5' },
            { name: 'teal', color: '#14b8a6', bg: '#ccfbf1' },
            { name: 'cyan', color: '#06b6d4', bg: '#cffafe' },
            { name: 'sky', color: '#0ea5e9', bg: '#e0f2fe' },
            { name: 'slate', color: '#64748b', bg: '#f1f5f9' },
            { name: 'gray', color: '#6b7280', bg: '#f3f4f6' }
        ];

        this.init();
    }

    async init() {
        console.log('SettingsCustomization: Initializing...');
        await this.loadChoices();
        this.renderAll();
        this.bindEvents();
        this.storeOriginalData();
        console.log('SettingsCustomization: Initialization complete');
    }

    async loadChoices() {
        try {
            // Use /api/office/choices/ to get ALL choices including inactive ones (for settings management)
            const response = await fetch('/api/office/choices/');
            if (!response.ok) throw new Error('Failed to load choices');

            const data = await response.json();

            // Normalize choices to ensure they have all required fields
            this.statusChoices = this.normalizeStatusChoices(data.event_status_choices || []);
            this.typeChoices = this.normalizeTypeChoices(data.event_type_choices || []);
            this.formatChoices = this.normalizeTypeChoices(data.event_format_choices || []);
            this.tagsChoices = this.normalizeTagChoices(data.default_tags || []);
            this.staffMembers = data.staff_members || [];
            this.unlinkedUsers = data.unlinked_users || [];
            this.roles = data.roles || [];
            this.permissionCatalog = data.permission_catalog || [];
            this.permissionDependencies = data.permission_dependencies || {};
            this.canManageRoles = data.can_manage_roles || false;

            // Load office info
            this.officeInfo = {
                member_name: data.member_name || '',
                district: data.district || '',
                dc_office_address: data.dc_office_address || '',
                district_office_address: data.district_office_address || ''
            };

            // Ensure the protected "received" status always exists
            this.ensureReceivedStatusExists();

            console.log('Loaded choices:', {
                status: this.statusChoices.length,
                type: this.typeChoices.length,
                format: this.formatChoices.length,
                tags: this.tagsChoices.length,
                staff: this.staffMembers.length,
                unlinkedUsers: this.unlinkedUsers.length
            });
        } catch (error) {
            console.error('Error loading choices:', error);
            // Show error to user
            this.showNotification('Failed to load customization options', 'error');
        }
    }

    normalizeTagChoices(choices) {
        return choices.map((choice, index) => ({
            value: choice.value || '',
            label: choice.label || '',
            color: choice.color || '#3b82f6',
            bg_color: choice.bg_color || '#dbeafe',
            is_active: choice.is_active !== false,
            order: choice.order || index + 1
        }));
    }

    ensureReceivedStatusExists() {
        // Check if "received" status exists
        const receivedExists = this.statusChoices.some(s => s.value?.toLowerCase() === 'received');

        if (!receivedExists) {
            // Add the required "received" status at the beginning
            this.statusChoices.unshift({
                value: 'received',
                label: 'Received',
                color: '#3b82f6',
                bg_color: '#dbeafe',
                is_active: true,
                order: 0
            });
            console.log('Added missing "received" status');
        }
    }

    normalizeStatusChoices(choices) {
        return choices.map((choice, index) => {
            if (Array.isArray(choice)) {
                return {
                    value: choice[0],
                    label: choice[1],
                    color: '#3b82f6',
                    bg_color: '#dbeafe',
                    is_active: true,
                    order: index + 1
                };
            }
            return {
                value: choice.value || '',
                label: choice.label || '',
                color: choice.color || '#3b82f6',
                bg_color: choice.bg_color || '#dbeafe',
                is_active: choice.is_active !== false,
                order: choice.order || index + 1
            };
        });
    }

    normalizeTypeChoices(choices) {
        return choices.map((choice, index) => {
            if (Array.isArray(choice)) {
                return {
                    value: choice[0],
                    label: choice[1],
                    is_active: true,
                    order: index + 1
                };
            }
            return {
                value: choice.value || '',
                label: choice.label || '',
                is_active: choice.is_active !== false,
                order: choice.order || index + 1
            };
        });
    }

    storeOriginalData() {
        this.originalData = {
            statusChoices: JSON.stringify(this.statusChoices),
            typeChoices: JSON.stringify(this.typeChoices),
            formatChoices: JSON.stringify(this.formatChoices),
            tagsChoices: JSON.stringify(this.tagsChoices),
            staffMembers: JSON.stringify(this.staffMembers),
            officeInfo: JSON.stringify(this.officeInfo)
        };
    }

    checkForChanges() {
        const currentData = {
            statusChoices: JSON.stringify(this.statusChoices),
            typeChoices: JSON.stringify(this.typeChoices),
            formatChoices: JSON.stringify(this.formatChoices),
            tagsChoices: JSON.stringify(this.tagsChoices)
        };

        this.hasUnsavedChanges =
            currentData.statusChoices !== this.originalData.statusChoices ||
            currentData.typeChoices !== this.originalData.typeChoices ||
            currentData.formatChoices !== this.originalData.formatChoices ||
            currentData.tagsChoices !== this.originalData.tagsChoices;

        this.updateUnsavedBanner();

        // Trigger auto-save if there are unsaved changes
        if (this.hasUnsavedChanges) {
            this.scheduleAutoSave();
        }
    }

    scheduleAutoSave() {
        // Clear any existing timer
        if (this.autoSaveTimer) {
            clearTimeout(this.autoSaveTimer);
        }

        // Show "saving soon" indicator
        this.updateSaveIndicator('pending');

        // Schedule auto-save after debounce delay
        this.autoSaveTimer = setTimeout(() => {
            this.autoSaveChoices();
        }, this.autoSaveDelay);
    }

    async autoSaveChoices() {
        if (this.isSaving || !this.hasUnsavedChanges) return;

        this.isSaving = true;
        this.updateSaveIndicator('saving');

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch('/api/office/choices/', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    event_status_choices: this.statusChoices,
                    event_type_choices: this.typeChoices,
                    event_format_choices: this.formatChoices,
                    default_tags: this.tagsChoices
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save changes');
            }

            this.storeOriginalData();
            this.hasUnsavedChanges = false;
            this.updateUnsavedBanner();
            this.updateSaveIndicator('saved');

            console.log('SettingsCustomization: Auto-saved successfully');

        } catch (error) {
            console.error('Auto-save error:', error);
            this.updateSaveIndicator('error');
            this.showNotification('Auto-save failed: ' + error.message, 'error');
        } finally {
            this.isSaving = false;
        }
    }

    updateSaveIndicator(state) {
        // Update the save button or create a save indicator
        const saveBtn = document.querySelector('.unsaved-changes-actions .settings-save-btn:last-child');
        const banner = document.getElementById('unsaved-banner');

        // Create or update inline save indicator
        let indicator = document.getElementById('auto-save-indicator');
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.id = 'auto-save-indicator';
            indicator.className = 'auto-save-indicator';
            // Insert at the top of the main content area
            const header = document.querySelector('.settings-header-bar');
            if (header) {
                header.style.position = 'relative';
                header.appendChild(indicator);
            }
        }

        switch (state) {
            case 'pending':
                indicator.innerHTML = '';
                indicator.className = 'auto-save-indicator pending';
                break;
            case 'saving':
                indicator.innerHTML = `
                    <svg class="auto-save-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="32"></circle>
                    </svg>
                    <span>Saving...</span>
                `;
                indicator.className = 'auto-save-indicator saving';
                break;
            case 'saved':
                indicator.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <span>Saved</span>
                `;
                indicator.className = 'auto-save-indicator saved';
                // Hide after 2 seconds
                setTimeout(() => {
                    indicator.className = 'auto-save-indicator hidden';
                }, 2000);
                break;
            case 'error':
                indicator.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                    </svg>
                    <span>Save failed</span>
                `;
                indicator.className = 'auto-save-indicator error';
                break;
        }
    }

    updateUnsavedBanner() {
        const banner = document.getElementById('unsaved-banner');
        if (banner) {
            // Hide the banner - we're using auto-save now
            banner.classList.remove('visible');
        }
    }

    renderAll() {
        this.renderStatusList();
        this.renderTypeList();
        this.renderFormatList();
        this.renderTagsList();
        this.renderStaffList();
        this.renderRolesList();
        this.renderOfficeInfo();
    }

    renderStatusList() {
        const container = document.getElementById('status-list');
        if (!container) return;

        container.innerHTML = this.statusChoices
            .sort((a, b) => a.order - b.order)
            .map(choice => this.renderStatusItem(choice))
            .join('');

        this.initDragAndDrop(container, 'status');
    }

    renderTypeList() {
        const container = document.getElementById('type-list');
        if (!container) return;

        container.innerHTML = this.typeChoices
            .sort((a, b) => a.order - b.order)
            .map(choice => this.renderTypeItem(choice, 'type'))
            .join('');

        this.initDragAndDrop(container, 'type');
    }

    renderFormatList() {
        const container = document.getElementById('format-list');
        if (!container) return;

        container.innerHTML = this.formatChoices
            .sort((a, b) => a.order - b.order)
            .map(choice => this.renderTypeItem(choice, 'format'))
            .join('');

        this.initDragAndDrop(container, 'format');
    }

    renderTagsList() {
        const container = document.getElementById('tags-list');
        if (!container) return;

        container.innerHTML = this.tagsChoices
            .sort((a, b) => a.order - b.order)
            .map(choice => this.renderTagItem(choice))
            .join('');

        this.initDragAndDrop(container, 'tags');
    }

    renderTagItem(choice) {
        const inactiveClass = !choice.is_active ? 'inactive' : '';
        return `
            <div class="customization-item ${inactiveClass}" data-value="${choice.value}" draggable="true">
                <div class="customization-drag-handle">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="9" cy="5" r="1"></circle>
                        <circle cx="9" cy="12" r="1"></circle>
                        <circle cx="9" cy="19" r="1"></circle>
                        <circle cx="15" cy="5" r="1"></circle>
                        <circle cx="15" cy="12" r="1"></circle>
                        <circle cx="15" cy="19" r="1"></circle>
                    </svg>
                </div>
                <div class="customization-color-swatch"
                     style="background-color: ${choice.color}; border-color: ${choice.color};"
                     data-value="${choice.value}"
                     data-color="${choice.color}"
                     data-bg="${choice.bg_color}"
                     data-type="tags"
                     aria-label="Click to change color">
                </div>
                <div class="customization-label-container">
                    <input type="text"
                           class="customization-label"
                           value="${this.escapeHtml(choice.label)}"
                           data-value="${choice.value}"
                           data-type="tags">
                </div>
                <div class="customization-actions">
                    ${choice.is_active ? `
                        <button type="button" class="customization-btn delete" data-tooltip="Delete" aria-label="Delete" data-action="deactivate" data-value="${choice.value}" data-type="tags">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    ` : `
                        <button type="button" class="customization-btn restore" data-tooltip="Reactivate" aria-label="Reactivate" data-action="reactivate" data-value="${choice.value}" data-type="tags">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="1 4 1 10 7 10"></polyline>
                                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                            </svg>
                        </button>
                    `}
                </div>
            </div>
        `;
    }

    renderStaffList() {
        const container = document.getElementById('staff-list');
        if (!container) return;

        if (this.staffMembers.length === 0) {
            container.innerHTML = '<div class="staff-empty-state">No staff members added yet.</div>';
            return;
        }

        container.innerHTML = this.staffMembers.map(staff => this.renderStaffItem(staff)).join('');
    }

    renderStaffItem(staff) {
        const areasHtml = staff.legislative_areas && staff.legislative_areas.length > 0
            ? staff.legislative_areas.map(area => `<span class="staff-area-tag">${this.escapeHtml(area)}</span>`).join('')
            : '<span class="staff-no-areas">No areas assigned</span>';

        // Account linking section
        let accountLinkHtml = '';
        if (staff.linked_user) {
            // Staff has a linked account
            accountLinkHtml = `
                <div class="staff-account-link staff-account-linked">
                    <span class="staff-account-label">Linked Account:</span>
                    <span class="staff-account-user">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        ${this.escapeHtml(staff.linked_user.full_name)}
                    </span>
                    <button type="button" class="staff-unlink-btn" data-tooltip="Unlink account" aria-label="Unlink account" data-action="unlink-account" data-id="${staff.id}">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                        Unlink
                    </button>
                </div>
            `;
        } else if (this.unlinkedUsers.length > 0) {
            // Staff has no linked account but there are users to link
            const userOptions = this.unlinkedUsers.map(u =>
                `<option value="${u.id}">${this.escapeHtml(u.full_name)} (${this.escapeHtml(u.email || u.username)})</option>`
            ).join('');
            accountLinkHtml = `
                <div class="staff-account-link staff-account-unlinked">
                    <span class="staff-account-label">Link Account:</span>
                    <select class="staff-link-select" data-staff-id="${staff.id}">
                        <option value="">Select user...</option>
                        ${userOptions}
                    </select>
                    <button type="button" class="staff-link-btn" data-tooltip="Link account" aria-label="Link account" data-action="link-account" data-id="${staff.id}">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
                            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
                        </svg>
                        Link
                    </button>
                </div>
            `;
        } else {
            // No linked account and no users available
            accountLinkHtml = `
                <div class="staff-account-link staff-account-none">
                    <span class="staff-account-label">Account:</span>
                    <span class="staff-no-account">No account linked (no unlinked users available)</span>
                </div>
            `;
        }

        return `
            <div class="staff-item" data-id="${staff.id}">
                <div class="staff-item-main">
                    <div class="staff-item-info">
                        <div class="staff-item-name">${this.escapeHtml(staff.name)}</div>
                        <div class="staff-item-position">${this.escapeHtml(staff.position) || 'No position'}</div>
                        <div class="staff-item-contact">
                            ${staff.email ? `<span class="staff-email">${this.escapeHtml(staff.email)}</span>` : ''}
                            ${staff.phone ? `<span class="staff-phone">${this.escapeHtml(staff.phone)}</span>` : ''}
                        </div>
                    </div>
                    <div class="staff-item-actions">
                        <button type="button" class="customization-btn edit" data-tooltip="Edit" aria-label="Edit" data-action="edit-staff" data-id="${staff.id}">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>
                        <button type="button" class="customization-btn delete" data-tooltip="Remove" aria-label="Remove" data-action="delete-staff" data-id="${staff.id}">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    </div>
                </div>
                ${accountLinkHtml}
                <div class="staff-item-areas">
                    <span class="staff-areas-label">Legislative Areas:</span>
                    <div class="staff-areas-list">${areasHtml}</div>
                </div>
            </div>
        `;
    }

    renderOfficeInfo() {
        // Populate office info fields
        const memberNameInput = document.getElementById('member_name');
        const districtInput = document.getElementById('district');
        const dcAddressInput = document.getElementById('dc_office_address');
        const districtAddressInput = document.getElementById('district_office_address');

        if (memberNameInput) memberNameInput.value = this.officeInfo.member_name || '';
        if (districtInput) districtInput.value = this.officeInfo.district || '';
        if (dcAddressInput) dcAddressInput.value = this.officeInfo.dc_office_address || '';
        if (districtAddressInput) districtAddressInput.value = this.officeInfo.district_office_address || '';
    }

    renderStatusItem(choice) {
        const inactiveClass = !choice.is_active ? 'inactive' : '';
        // "received" is protected and cannot be deleted - check value (case-insensitive)
        const isProtected = choice.value?.toLowerCase() === 'received';
        const isReadOnly = isProtected ? 'readonly' : '';
        const protectedClass = isProtected ? 'protected' : '';

        return `
            <div class="customization-item ${inactiveClass} ${protectedClass}" data-value="${choice.value}" draggable="${!isProtected}">
                <div class="customization-drag-handle" ${isProtected ? 'style="visibility: hidden;"' : ''}>
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="9" cy="5" r="1"></circle>
                        <circle cx="9" cy="12" r="1"></circle>
                        <circle cx="9" cy="19" r="1"></circle>
                        <circle cx="15" cy="5" r="1"></circle>
                        <circle cx="15" cy="12" r="1"></circle>
                        <circle cx="15" cy="19" r="1"></circle>
                    </svg>
                </div>
                <div class="customization-color-swatch"
                     style="background-color: ${choice.color}; border-color: ${choice.color};"
                     data-value="${choice.value}"
                     data-color="${choice.color}"
                     data-bg="${choice.bg_color}"
                     aria-label="Click to change color">
                </div>
                <div class="customization-label-container">
                    <input type="text"
                           class="customization-label"
                           value="${this.escapeHtml(choice.label)}"
                           data-value="${choice.value}"
                           data-type="status"
                           ${isReadOnly}>
                </div>
                <div class="customization-actions">
                    ${isProtected ? `
                        <span class="customization-protected-label" data-tooltip="This status is required and cannot be removed" aria-label="This status is required and cannot be removed">Required</span>
                    ` : choice.is_active ? `
                        <button type="button" class="customization-btn delete" data-tooltip="Delete" aria-label="Delete" data-action="deactivate" data-value="${choice.value}" data-type="status">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    ` : `
                        <button type="button" class="customization-btn restore" data-tooltip="Reactivate" aria-label="Reactivate" data-action="reactivate" data-value="${choice.value}" data-type="status">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="1 4 1 10 7 10"></polyline>
                                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                            </svg>
                        </button>
                    `}
                </div>
            </div>
        `;
    }

    renderTypeItem(choice, choiceType) {
        const inactiveClass = !choice.is_active ? 'inactive' : '';
        return `
            <div class="customization-item ${inactiveClass}" data-value="${choice.value}" draggable="true">
                <div class="customization-drag-handle">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="9" cy="5" r="1"></circle>
                        <circle cx="9" cy="12" r="1"></circle>
                        <circle cx="9" cy="19" r="1"></circle>
                        <circle cx="15" cy="5" r="1"></circle>
                        <circle cx="15" cy="12" r="1"></circle>
                        <circle cx="15" cy="19" r="1"></circle>
                    </svg>
                </div>
                <div class="customization-label-container">
                    <input type="text"
                           class="customization-label"
                           value="${this.escapeHtml(choice.label)}"
                           data-value="${choice.value}"
                           data-type="${choiceType}">
                </div>
                <div class="customization-actions">
                    ${choice.is_active ? `
                        <button type="button" class="customization-btn delete" data-tooltip="Delete" aria-label="Delete" data-action="deactivate" data-value="${choice.value}" data-type="${choiceType}">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    ` : `
                        <button type="button" class="customization-btn restore" data-tooltip="Reactivate" aria-label="Reactivate" data-action="reactivate" data-value="${choice.value}" data-type="${choiceType}">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="1 4 1 10 7 10"></polyline>
                                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                            </svg>
                        </button>
                    `}
                </div>
            </div>
        `;
    }

    bindEvents() {
        // Color swatches
        document.addEventListener('click', (e) => {
            const swatch = e.target.closest('.customization-color-swatch');
            if (swatch) {
                this.openColorPicker(swatch);
                e.stopPropagation();
                return;
            }

            // Color picker option
            const colorOption = e.target.closest('.color-picker-option');
            if (colorOption) {
                this.selectColor(colorOption);
                return;
            }

            // Close color picker when clicking outside
            if (this.activeColorPicker && !e.target.closest('.color-picker-popover')) {
                this.closeColorPicker();
            }

            // Action buttons
            const actionBtn = e.target.closest('.customization-btn');
            if (actionBtn) {
                const action = actionBtn.dataset.action;
                const value = actionBtn.dataset.value;
                const type = actionBtn.dataset.type;
                const id = actionBtn.dataset.id;

                if (action === 'edit-staff') {
                    this.openStaffModal(id);
                } else if (action === 'delete-staff') {
                    this.deleteStaff(id);
                } else if (action === 'edit-role') {
                    this.openRoleModal(id);
                } else if (action === 'delete-role') {
                    this.deleteRole(id);
                } else {
                    this.handleAction(action, value, type);
                }
            }

            // Staff account link button
            const linkBtn = e.target.closest('.staff-link-btn');
            if (linkBtn) {
                const staffId = linkBtn.dataset.id;
                this.linkStaffAccount(staffId);
            }

            // Staff account unlink button
            const unlinkBtn = e.target.closest('.staff-unlink-btn');
            if (unlinkBtn) {
                const staffId = unlinkBtn.dataset.id;
                this.unlinkStaffAccount(staffId);
            }

            // Add buttons
            const addBtn = e.target.closest('.customization-add-btn');
            if (addBtn) {
                this.addNewItem(addBtn.dataset.choiceType);
            }
        });

        // Label input changes
        document.addEventListener('input', (e) => {
            if (e.target.classList.contains('customization-label')) {
                this.handleLabelChange(e.target);
            }
        });

        // Staff account link dropdown - auto-link when user selects an account
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('staff-link-select') && e.target.value) {
                const staffId = e.target.dataset.staffId;
                this.linkStaffAccount(staffId);
            }
            // Role permission checkbox toggled → cascade dependencies.
            if (e.target.matches('#role-modal input[name="permissions"]')) {
                this.handlePermissionToggle(e.target);
            }
        });

        // Add staff button
        const addStaffBtn = document.getElementById('add-staff-btn');
        if (addStaffBtn) {
            addStaffBtn.addEventListener('click', () => this.openStaffModal());
        }

        // Add role button
        const addRoleBtn = document.getElementById('add-role-btn');
        if (addRoleBtn) {
            addRoleBtn.addEventListener('click', () => this.openRoleModal());
        }

        // Custom app-styled dropdowns (e.g. the staff-modal role selector).
        document.addEventListener('click', (e) => {
            const trigger = e.target.closest('.app-select-trigger');
            if (trigger && !trigger.disabled) {
                const dd = trigger.closest('.app-select');
                const menu = dd.querySelector('.app-select-menu');
                const willOpen = menu.hidden;
                this._closeAllAppSelects();
                menu.hidden = !willOpen;
                trigger.setAttribute('aria-expanded', String(willOpen));
                return;
            }
            const option = e.target.closest('.app-select-option');
            if (option) {
                const dd = option.closest('.app-select');
                dd.dataset.value = option.dataset.value;
                dd.querySelector('.app-select-label').textContent = option.textContent;
                dd.querySelectorAll('.app-select-option').forEach(o => {
                    o.classList.remove('is-selected');
                    o.setAttribute('aria-selected', 'false');
                });
                option.classList.add('is-selected');
                option.setAttribute('aria-selected', 'true');
                this._closeAllAppSelects();
                return;
            }
            // Click anywhere else closes any open dropdown.
            if (!e.target.closest('.app-select')) {
                this._closeAllAppSelects();
            }
        });

        // Save office info button (keep for manual save, but also enable auto-save)
        const saveOfficeInfoBtn = document.getElementById('save-office-info-btn');
        if (saveOfficeInfoBtn) {
            saveOfficeInfoBtn.addEventListener('click', () => this.saveOfficeInfo());
        }

        // Auto-save for office info fields
        this.bindOfficeInfoAutoSave();

        // Save changes button in banner
        window.saveAllChanges = () => this.saveAllChanges();
        window.discardChanges = () => this.discardChanges();
    }

    bindOfficeInfoAutoSave() {
        const officeFields = ['member_name', 'district', 'dc_office_address', 'district_office_address'];

        officeFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                field.addEventListener('input', () => {
                    this.scheduleOfficeInfoAutoSave();
                });
            }
        });
    }

    scheduleOfficeInfoAutoSave() {
        // Clear any existing timer
        if (this.officeInfoAutoSaveTimer) {
            clearTimeout(this.officeInfoAutoSaveTimer);
        }

        // Show "saving soon" indicator
        this.updateSaveIndicator('pending');

        // Schedule auto-save after debounce delay
        this.officeInfoAutoSaveTimer = setTimeout(() => {
            this.autoSaveOfficeInfo();
        }, this.autoSaveDelay);
    }

    async autoSaveOfficeInfo() {
        if (this.isSaving) return;

        // Check if there are actual changes
        const memberName = document.getElementById('member_name')?.value || '';
        const district = document.getElementById('district')?.value || '';
        const dcAddress = document.getElementById('dc_office_address')?.value || '';
        const districtAddress = document.getElementById('district_office_address')?.value || '';

        const currentOfficeInfo = JSON.stringify({
            member_name: memberName,
            district: district,
            dc_office_address: dcAddress,
            district_office_address: districtAddress
        });

        if (currentOfficeInfo === this.originalData.officeInfo) {
            this.updateSaveIndicator('saved');
            return; // No changes
        }

        this.isSaving = true;
        this.updateSaveIndicator('saving');

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch('/api/office/choices/', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    member_name: memberName,
                    district: district,
                    dc_office_address: dcAddress,
                    district_office_address: districtAddress
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save office info');
            }

            // Update local state
            this.officeInfo = {
                member_name: memberName,
                district: district,
                dc_office_address: dcAddress,
                district_office_address: districtAddress
            };
            this.originalData.officeInfo = JSON.stringify(this.officeInfo);

            this.updateSaveIndicator('saved');
            console.log('SettingsCustomization: Office info auto-saved successfully');

        } catch (error) {
            console.error('Office info auto-save error:', error);
            this.updateSaveIndicator('error');
            this.showNotification('Auto-save failed: ' + error.message, 'error');
        } finally {
            this.isSaving = false;
        }
    }

    initDragAndDrop(container, choiceType) {
        let draggedItem = null;

        container.querySelectorAll('.customization-item').forEach(item => {
            item.addEventListener('dragstart', (e) => {
                draggedItem = item;
                item.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });

            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
                draggedItem = null;
            });

            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';

                if (draggedItem && draggedItem !== item) {
                    const rect = item.getBoundingClientRect();
                    const midY = rect.top + rect.height / 2;

                    if (e.clientY < midY) {
                        container.insertBefore(draggedItem, item);
                    } else {
                        container.insertBefore(draggedItem, item.nextSibling);
                    }
                }
            });
        });

        container.addEventListener('drop', () => {
            this.updateOrderFromDOM(container, choiceType);
        });
    }

    updateOrderFromDOM(container, choiceType) {
        const items = container.querySelectorAll('.customization-item');
        const choices = this.getChoicesArray(choiceType);

        items.forEach((item, index) => {
            const value = item.dataset.value;
            const choice = choices.find(c => c.value === value);
            if (choice) {
                choice.order = index + 1;
            }
        });

        this.checkForChanges();
    }

    openColorPicker(swatch) {
        const popover = document.getElementById('color-picker-popover');
        if (!popover) return;

        this.activeColorPicker = swatch;
        const currentColor = swatch.dataset.color;

        // Position the popover directly next to the swatch
        const rect = swatch.getBoundingClientRect();

        // Make popover visible temporarily to get its actual size
        popover.style.visibility = 'hidden';
        popover.classList.add('visible');
        const popoverRect = popover.getBoundingClientRect();
        const popoverWidth = popoverRect.width || 180;
        const popoverHeight = popoverRect.height || 220;
        popover.classList.remove('visible');
        popover.style.visibility = '';

        // Start with top aligned to the swatch (slight offset for visual balance)
        let top = rect.top - 8;

        // Prefer to show to the right of the swatch
        let left = rect.right + 12;

        // If would go off right edge, show to the left
        if (left + popoverWidth > window.innerWidth - 20) {
            left = rect.left - popoverWidth - 12;
        }

        // Ensure not off bottom - adjust upward if needed
        if (top + popoverHeight > window.innerHeight - 20) {
            top = window.innerHeight - popoverHeight - 20;
        }

        // Ensure not off top
        if (top < 80) { // Account for header
            top = 80;
        }

        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;

        // Mark current color as selected
        popover.querySelectorAll('.color-picker-option').forEach(option => {
            option.classList.toggle('selected', option.dataset.color === currentColor);
        });

        popover.classList.add('visible');
    }

    closeColorPicker() {
        const popover = document.getElementById('color-picker-popover');
        if (popover) {
            popover.classList.remove('visible');
        }
        this.activeColorPicker = null;
    }

    selectColor(colorOption) {
        if (!this.activeColorPicker) return;

        const color = colorOption.dataset.color;
        const bgColor = colorOption.dataset.bg;
        const value = this.activeColorPicker.dataset.value;
        const type = this.activeColorPicker.dataset.type || 'status';

        // Update the swatch
        this.activeColorPicker.style.backgroundColor = color;
        this.activeColorPicker.style.borderColor = color;
        this.activeColorPicker.dataset.color = color;
        this.activeColorPicker.dataset.bg = bgColor;

        // Update the data based on type
        const choices = type === 'tags' ? this.tagsChoices : this.statusChoices;
        const choice = choices.find(c => c.value === value);
        if (choice) {
            choice.color = color;
            choice.bg_color = bgColor;
        }

        this.closeColorPicker();
        this.checkForChanges();
        // Color changes save immediately. checkForChanges() also scheduled a
        // debounced save as a backup, which no-ops if this one already saved
        // (or catches the change if a prior save was still in flight).
        this.autoSaveChoices();
    }

    handleLabelChange(input) {
        const value = input.dataset.value;
        const type = input.dataset.type;
        const newLabel = input.value;

        const choices = this.getChoicesArray(type);
        const choice = choices.find(c => c.value === value);
        if (choice) {
            choice.label = newLabel;
        }

        this.checkForChanges();
    }

    async handleAction(action, value, type) {
        const choices = this.getChoicesArray(type);
        const choice = choices.find(c => c.value === value);

        if (!choice) return;

        if (action === 'deactivate') {
            // Check minimum option requirement - must have at least 1 active option
            const activeChoices = choices.filter(c => c.is_active && c.value !== value);
            if (activeChoices.length === 0) {
                this.showNotification(
                    `Cannot delete "${choice.label}". You must have at least one ${type} option.`,
                    'error'
                );
                return;
            }

            // Check if option is in use by any events
            try {
                const response = await fetch(`/api/office/check-option-usage/?field=${type}&value=${encodeURIComponent(value)}`);
                if (!response.ok) {
                    throw new Error(`API returned ${response.status}`);
                }
                const data = await response.json();

                console.log(`Check option usage for ${type}=${value}:`, data);

                if (data.in_use) {
                    // Soft delete - option is in use, can't fully remove
                    choice.is_active = false;
                    this.showNotification(
                        `"${choice.label}" is used by ${data.event_count} event(s) and has been deactivated. It will still appear with strikethrough.`,
                        'info'
                    );
                } else {
                    // Hard delete - option is not in use, remove completely
                    const index = choices.indexOf(choice);
                    if (index > -1) {
                        choices.splice(index, 1);
                        this.showNotification(`"${choice.label}" has been removed`, 'success');
                    }
                }
            } catch (error) {
                console.error('Error checking option usage:', error);
                // Fall back to soft delete on error
                choice.is_active = false;
                this.showNotification(`"${choice.label}" has been deactivated`, 'info');
            }
        } else if (action === 'reactivate') {
            choice.is_active = true;
            this.showNotification(`"${choice.label}" has been reactivated`, 'success');
        }

        this.renderAll();
        this.checkForChanges();
    }

    addNewItem(choiceType) {
        const choices = this.getChoicesArray(choiceType);
        const maxOrder = Math.max(...choices.map(c => c.order || 0), 0);

        // Generate a unique value
        const baseValue = `custom_${Date.now()}`;
        const newChoice = {
            value: baseValue,
            label: choiceType === 'tags' ? 'New Tag' : 'New Option',
            is_active: true,
            order: maxOrder + 1
        };

        // Add color for status and tags
        if (choiceType === 'status' || choiceType === 'tags') {
            const randomColor = this.colorPalette[Math.floor(Math.random() * this.colorPalette.length)];
            newChoice.color = randomColor.color;
            newChoice.bg_color = randomColor.bg;
        }

        choices.push(newChoice);
        this.renderAll();
        this.checkForChanges();

        // Focus the new item's label input
        setTimeout(() => {
            const input = document.querySelector(`input[data-value="${baseValue}"]`);
            if (input) {
                input.focus();
                input.select();
            }
        }, 100);
    }

    getChoicesArray(type) {
        switch (type) {
            case 'status': return this.statusChoices;
            case 'type': return this.typeChoices;
            case 'format': return this.formatChoices;
            case 'tags': return this.tagsChoices;
            default: return [];
        }
    }

    async saveAllChanges() {
        try {
            // Get CSRF token
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch('/api/office/choices/', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    event_status_choices: this.statusChoices,
                    event_type_choices: this.typeChoices,
                    event_format_choices: this.formatChoices,
                    default_tags: this.tagsChoices
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save changes');
            }

            this.storeOriginalData();
            this.checkForChanges();
            this.showNotification('Changes saved successfully!', 'success');

        } catch (error) {
            console.error('Error saving changes:', error);
            this.showNotification('Failed to save changes: ' + error.message, 'error');
        }
    }

    async saveOfficeInfo() {
        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const memberName = document.getElementById('member_name')?.value || '';
            const district = document.getElementById('district')?.value || '';
            const dcAddress = document.getElementById('dc_office_address')?.value || '';
            const districtAddress = document.getElementById('district_office_address')?.value || '';

            const response = await fetch('/api/office/choices/', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    member_name: memberName,
                    district: district,
                    dc_office_address: dcAddress,
                    district_office_address: districtAddress
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save office info');
            }

            // Update local state
            this.officeInfo = {
                member_name: memberName,
                district: district,
                dc_office_address: dcAddress,
                district_office_address: districtAddress
            };
            this.originalData.officeInfo = JSON.stringify(this.officeInfo);

            this.showNotification('Office information saved successfully!', 'success');

        } catch (error) {
            console.error('Error saving office info:', error);
            this.showNotification('Failed to save office info: ' + error.message, 'error');
        }
    }

    openStaffModal(staffId = null) {
        // Create or show staff modal
        let modal = document.getElementById('staff-modal');
        if (!modal) {
            modal = this.createStaffModal();
            document.body.appendChild(modal);
        }

        const isEdit = staffId !== null;
        const staff = isEdit ? this.staffMembers.find(s => s.id === staffId) : null;

        // Populate modal
        modal.querySelector('.staff-modal-title').textContent = isEdit ? 'Edit Staff Member' : 'Add Staff Member';
        modal.querySelector('#staff-modal-name').value = staff?.name || '';
        modal.querySelector('#staff-modal-position').value = staff?.position || '';
        modal.querySelector('#staff-modal-email').value = staff?.email || '';
        modal.querySelector('#staff-modal-phone').value = staff?.phone || '';
        modal.querySelector('#staff-modal-areas').value = (staff?.legislative_areas || []).join(', ');
        modal.dataset.staffId = staffId || '';

        // Role & permissions selector — only meaningful for admins editing a staff
        // member that is linked to a user account.
        const roleGroup = modal.querySelector('#staff-modal-role-group');
        const roleHelp = modal.querySelector('#staff-modal-role-help');
        if (this.canManageRoles && roleGroup) {
            roleGroup.style.display = '';
            const linked = staff?.linked_user;
            this._populateRoleDropdown(modal, linked ? (linked.role_id || '') : '', !linked);
            roleHelp.textContent = linked
                ? `Sets the role (and permissions) for ${linked.full_name}.`
                : 'Link a user account below to assign a role.';
        } else if (roleGroup) {
            roleGroup.style.display = 'none';
        }

        modal.classList.add('visible');
    }

    createStaffModal() {
        const modal = document.createElement('div');
        modal.id = 'staff-modal';
        modal.className = 'staff-modal-overlay';
        modal.innerHTML = `
            <div class="staff-modal">
                <div class="staff-modal-header">
                    <h3 class="staff-modal-title">Add Staff Member</h3>
                    <button type="button" class="staff-modal-close" onclick="window.settingsCustomization.closeStaffModal()">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="staff-modal-body">
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="staff-modal-name">Name *</label>
                        <input type="text" class="settings-form-input" id="staff-modal-name" required>
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="staff-modal-position">Position</label>
                        <input type="text" class="settings-form-input" id="staff-modal-position" placeholder="e.g., Legislative Director">
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="staff-modal-email">Email</label>
                        <input type="email" class="settings-form-input" id="staff-modal-email">
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="staff-modal-phone">Phone</label>
                        <input type="text" class="settings-form-input" id="staff-modal-phone">
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="staff-modal-areas">Legislative Areas</label>
                        <input type="text" class="settings-form-input" id="staff-modal-areas" placeholder="Healthcare, Education, Defense (comma-separated)">
                        <p class="settings-form-help">Enter areas separated by commas</p>
                    </div>
                    <div class="settings-form-group" id="staff-modal-role-group">
                        <label class="settings-form-label">Role &amp; Permissions</label>
                        <div class="app-select" id="staff-modal-role" data-value="">
                            <button type="button" class="app-select-trigger" aria-haspopup="listbox" aria-expanded="false">
                                <span class="app-select-label">Select a role…</span>
                                <svg class="app-select-chevron" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="6 9 12 15 18 9"></polyline>
                                </svg>
                            </button>
                            <ul class="app-select-menu" role="listbox" hidden></ul>
                        </div>
                        <p class="settings-form-help" id="staff-modal-role-help"></p>
                    </div>
                </div>
                <div class="staff-modal-footer">
                    <button type="button" class="settings-save-btn" style="background: var(--bg-secondary); color: var(--text-secondary); border: 1px solid var(--border-color);" onclick="window.settingsCustomization.closeStaffModal()">
                        Cancel
                    </button>
                    <button type="button" class="settings-save-btn" onclick="window.settingsCustomization.saveStaff()">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        Save Staff Member
                    </button>
                </div>
            </div>
        `;

        // Save & close on Escape while the modal is open
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('visible')) {
                e.preventDefault();
                this._saveAndCloseStaff();
            }
        });

        return modal;
    }

    /**
     * Escape handler: save the staff member if the form is valid (which also
     * closes the modal on success), otherwise just close without nagging.
     */
    _saveAndCloseStaff() {
        const modal = document.getElementById('staff-modal');
        if (!modal) return;
        const name = modal.querySelector('#staff-modal-name').value.trim();
        if (name) {
            this.saveStaff();
        } else {
            this.closeStaffModal();
        }
    }

    closeStaffModal() {
        const modal = document.getElementById('staff-modal');
        if (modal) {
            modal.classList.remove('visible');
        }
        this._closeAllAppSelects();
    }

    // Fill the custom role dropdown with the office roles, mark the current one,
    // and set its enabled/disabled state.
    _populateRoleDropdown(modal, currentId, disabled) {
        const dd = modal.querySelector('#staff-modal-role');
        if (!dd) return;
        const menu = dd.querySelector('.app-select-menu');
        const label = dd.querySelector('.app-select-label');
        const trigger = dd.querySelector('.app-select-trigger');

        menu.innerHTML = this.roles.map(r => {
            const isSel = r.id === currentId;
            return `<li class="app-select-option${isSel ? ' is-selected' : ''}" role="option"`
                + ` data-value="${r.id}" aria-selected="${isSel}">${this.escapeHtml(r.name)}</li>`;
        }).join('');

        const current = this.roles.find(r => r.id === currentId);
        dd.dataset.value = currentId || '';
        label.textContent = current ? current.name : 'Select a role…';
        dd.classList.toggle('disabled', !!disabled);
        trigger.disabled = !!disabled;
        trigger.setAttribute('aria-expanded', 'false');
        menu.hidden = true;
    }

    _closeAllAppSelects() {
        document.querySelectorAll('.app-select-menu').forEach(m => { m.hidden = true; });
        document.querySelectorAll('.app-select-trigger').forEach(t => t.setAttribute('aria-expanded', 'false'));
    }

    async saveStaff() {
        const modal = document.getElementById('staff-modal');
        if (!modal) return;

        const staffId = modal.dataset.staffId;
        const name = modal.querySelector('#staff-modal-name').value.trim();
        const position = modal.querySelector('#staff-modal-position').value.trim();
        const email = modal.querySelector('#staff-modal-email').value.trim();
        const phone = modal.querySelector('#staff-modal-phone').value.trim();
        const areasInput = modal.querySelector('#staff-modal-areas').value;
        const legislative_areas = areasInput
            .split(',')
            .map(a => a.trim())
            .filter(a => a.length > 0);

        if (!name) {
            this.showNotification('Staff name is required', 'error');
            return;
        }

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const isEdit = staffId && staffId.length > 0;
            const url = isEdit ? `/api/office/staff/${staffId}/` : '/api/office/staff/';
            const method = isEdit ? 'PUT' : 'POST';

            const payload = { name, position, email, phone, legislative_areas };
            // Include the selected role when editing a linked staff member.
            const roleDd = modal.querySelector('#staff-modal-role');
            if (roleDd && !roleDd.classList.contains('disabled') && roleDd.dataset.value) {
                payload.role_id = roleDd.dataset.value;
            }

            const response = await fetch(url, {
                method: method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to save staff');
            }

            const data = await response.json();

            // Update local state
            if (isEdit) {
                const index = this.staffMembers.findIndex(s => s.id === staffId);
                if (index !== -1) {
                    this.staffMembers[index] = data.staff;
                }
            } else {
                this.staffMembers.push(data.staff);
            }

            this.renderStaffList();
            this.closeStaffModal();
            this.showNotification(isEdit ? 'Staff member updated!' : 'Staff member added!', 'success');

        } catch (error) {
            console.error('Error saving staff:', error);
            this.showNotification('Failed to save staff: ' + error.message, 'error');
        }
    }

    async deleteStaff(staffId) {
        const staff = this.staffMembers.find(s => s.id === staffId);
        if (!staff) return;

        if (!confirm(`Are you sure you want to remove ${staff.name}?`)) {
            return;
        }

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch(`/api/office/staff/${staffId}/delete/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to remove staff');
            }

            // Update local state
            this.staffMembers = this.staffMembers.filter(s => s.id !== staffId);
            this.renderStaffList();
            this.showNotification('Staff member removed', 'success');

        } catch (error) {
            console.error('Error removing staff:', error);
            this.showNotification('Failed to remove staff: ' + error.message, 'error');
        }
    }

    async linkStaffAccount(staffId) {
        const staff = this.staffMembers.find(s => s.id === staffId);
        if (!staff) return;

        // Get selected user from dropdown
        const select = document.querySelector(`.staff-link-select[data-staff-id="${staffId}"]`);
        if (!select) return;

        const userId = select.value;
        if (!userId) {
            this.showNotification('Please select a user to link', 'error');
            return;
        }

        const selectedUser = this.unlinkedUsers.find(u => u.id === userId);
        const userName = selectedUser ? selectedUser.full_name : 'user';

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch(`/api/office/staff/${staffId}/link/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ user_id: userId })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to link account');
            }

            const data = await response.json();

            // Update local state
            const staffIndex = this.staffMembers.findIndex(s => s.id === staffId);
            if (staffIndex !== -1) {
                this.staffMembers[staffIndex].linked_user = data.linked_user;
            }

            // Remove user from unlinked list
            this.unlinkedUsers = this.unlinkedUsers.filter(u => u.id !== userId);

            this.renderStaffList();
            this.showNotification(`${userName} linked to ${staff.name}`, 'success');

        } catch (error) {
            console.error('Error linking staff account:', error);
            this.showNotification('Failed to link account: ' + error.message, 'error');
        }
    }

    async unlinkStaffAccount(staffId) {
        const staff = this.staffMembers.find(s => s.id === staffId);
        if (!staff || !staff.linked_user) return;

        const userName = staff.linked_user.full_name;

        if (!confirm(`Unlink ${userName} from ${staff.name}?`)) {
            return;
        }

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');

            const response = await fetch(`/api/office/staff/${staffId}/unlink/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to unlink account');
            }

            // Add the user back to unlinked list
            this.unlinkedUsers.push(staff.linked_user);

            // Update local state
            const staffIndex = this.staffMembers.findIndex(s => s.id === staffId);
            if (staffIndex !== -1) {
                this.staffMembers[staffIndex].linked_user = null;
            }

            this.renderStaffList();
            this.showNotification(`${userName} unlinked from ${staff.name}`, 'success');

        } catch (error) {
            console.error('Error unlinking staff account:', error);
            this.showNotification('Failed to unlink account: ' + error.message, 'error');
        }
    }

    // =====================================================================
    // Roles & Permissions
    // =====================================================================

    permissionLabel(key) {
        for (const group of this.permissionCatalog) {
            const perm = (group.permissions || []).find(p => p.key === key);
            if (perm) return perm.label;
        }
        return key;
    }

    // All permissions a key (transitively) requires.
    _collectRequires(key) {
        const deps = this.permissionDependencies || {};
        const out = new Set();
        const visit = (k) => (deps[k] || []).forEach(req => {
            if (!out.has(req)) { out.add(req); visit(req); }
        });
        visit(key);
        return [...out];
    }

    // All permissions that (transitively) require a key.
    _collectDependents(key) {
        const deps = this.permissionDependencies || {};
        const out = new Set();
        const visit = (k) => Object.keys(deps).forEach(p => {
            if ((deps[p] || []).includes(k) && !out.has(p)) { out.add(p); visit(p); }
        });
        visit(key);
        return [...out];
    }

    // Checking a permission auto-checks its requirements; unchecking a
    // requirement auto-unchecks everything that depends on it.
    handlePermissionToggle(checkbox) {
        const modal = document.getElementById('role-modal');
        if (!modal) return;
        const setChecked = (key, checked) => {
            const el = modal.querySelector(`input[name="permissions"][value="${key}"]`);
            if (el) el.checked = checked;
        };
        if (checkbox.checked) {
            this._collectRequires(checkbox.value).forEach(k => setChecked(k, true));
        } else {
            this._collectDependents(checkbox.value).forEach(k => setChecked(k, false));
        }
    }

    renderRolesList() {
        const container = document.getElementById('roles-list');
        if (!container) return;

        if (this.roles.length === 0) {
            container.innerHTML = '<div class="staff-empty-state">No roles defined.</div>';
            return;
        }
        container.innerHTML = this.roles.map(role => this.renderRoleItem(role)).join('');
    }

    renderRoleItem(role) {
        const chips = role.is_admin
            ? ['All permissions']
            : (role.permissions.length
                ? role.permissions.map(k => this.permissionLabel(k))
                : ['No permissions']);
        const chipsHtml = chips
            .map(label => `<span class="role-perm-chip">${this.escapeHtml(label)}</span>`)
            .join('');

        const badge = role.is_admin ? '<span class="role-tag role-tag-locked">Locked</span>' : '';

        let actions = '';
        if (role.is_editable) {
            actions += `
                <button type="button" class="customization-btn edit" data-tooltip="Edit" aria-label="Edit role" data-action="edit-role" data-id="${role.id}">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>`;
        }
        if (role.is_deletable && role.user_count === 0) {
            actions += `
                <button type="button" class="customization-btn delete" data-tooltip="Delete" aria-label="Delete role" data-action="delete-role" data-id="${role.id}">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>`;
        }

        const userCount = `${role.user_count} user${role.user_count === 1 ? '' : 's'}`;

        return `
            <div class="role-item" data-id="${role.id}">
                <div class="role-item-header">
                    <span class="role-name">${this.escapeHtml(role.name)}</span>
                    ${badge}
                    <span class="role-user-count">${userCount}</span>
                    <div class="role-item-actions">${actions}</div>
                </div>
                ${role.description ? `<div class="role-item-desc">${this.escapeHtml(role.description)}</div>` : ''}
                <div class="role-perm-chips">${chipsHtml}</div>
            </div>
        `;
    }

    openRoleModal(roleId = null) {
        let modal = document.getElementById('role-modal');
        if (!modal) {
            modal = this.createRoleModal();
            document.body.appendChild(modal);
        }

        const isEdit = roleId !== null && roleId !== undefined && roleId !== '';
        const role = isEdit ? this.roles.find(r => r.id === roleId) : null;

        modal.querySelector('.role-modal-title').textContent = isEdit ? 'Edit Role' : 'Create Role';
        modal.querySelector('#role-modal-name').value = role?.name || '';
        modal.querySelector('#role-modal-description').value = role?.description || '';
        modal.dataset.roleId = roleId || '';

        // Reset + check the permission boxes for this role
        const selected = new Set(role?.permissions || []);
        modal.querySelectorAll('input[name="permissions"]').forEach(cb => {
            cb.checked = selected.has(cb.value);
        });

        modal.classList.add('visible');
    }

    createRoleModal() {
        const groupsHtml = this.permissionCatalog.map(group => {
            const opts = group.permissions.map(p => `
                <label class="role-perm-option">
                    <input type="checkbox" name="permissions" value="${p.key}">
                    <span class="role-perm-text">
                        <span class="role-perm-name">${this.escapeHtml(p.label)}</span>
                        <span class="role-perm-help">${this.escapeHtml(p.help)}</span>
                    </span>
                </label>`).join('');
            return `
                <div class="role-perm-group">
                    <div class="role-perm-group-title">${this.escapeHtml(group.label)}</div>
                    ${opts}
                </div>`;
        }).join('');

        const modal = document.createElement('div');
        modal.id = 'role-modal';
        modal.className = 'staff-modal-overlay';
        modal.innerHTML = `
            <div class="staff-modal role-modal-box">
                <div class="staff-modal-header">
                    <h3 class="staff-modal-title role-modal-title">Create Role</h3>
                    <button type="button" class="staff-modal-close" onclick="window.settingsCustomization.closeRoleModal()">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="staff-modal-body">
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="role-modal-name">Role name *</label>
                        <input type="text" class="settings-form-input" id="role-modal-name" placeholder="e.g., Intern, Press Aide" required>
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label" for="role-modal-description">Description</label>
                        <input type="text" class="settings-form-input" id="role-modal-description" placeholder="What is this role for? (optional)">
                    </div>
                    <div class="settings-form-group">
                        <label class="settings-form-label">Permissions</label>
                        <div class="role-perm-groups">${groupsHtml}</div>
                    </div>
                </div>
                <div class="staff-modal-footer">
                    <button type="button" class="settings-save-btn" style="background: var(--bg-secondary); color: var(--text-secondary); border: 1px solid var(--border-color);" onclick="window.settingsCustomization.closeRoleModal()">
                        Cancel
                    </button>
                    <button type="button" class="settings-save-btn" onclick="window.settingsCustomization.saveRole()">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        Save Role
                    </button>
                </div>
            </div>
        `;
        return modal;
    }

    closeRoleModal() {
        const modal = document.getElementById('role-modal');
        if (modal) modal.classList.remove('visible');
    }

    async saveRole() {
        const modal = document.getElementById('role-modal');
        if (!modal) return;

        const roleId = modal.dataset.roleId;
        const name = modal.querySelector('#role-modal-name').value.trim();
        const description = modal.querySelector('#role-modal-description').value.trim();
        const permissions = Array.from(modal.querySelectorAll('input[name="permissions"]:checked'))
            .map(cb => cb.value);

        if (!name) {
            this.showNotification('Role name is required', 'error');
            return;
        }

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');
            const isEdit = roleId && roleId.length > 0;
            const url = isEdit ? `/api/office/roles/${roleId}/` : '/api/office/roles/';
            const method = isEdit ? 'PUT' : 'POST';

            const response = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({ name, description, permissions })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'Failed to save role');
            }

            const data = await response.json();
            if (isEdit) {
                const idx = this.roles.findIndex(r => r.id === roleId);
                if (idx !== -1) this.roles[idx] = data.role;
            } else {
                this.roles.push(data.role);
            }

            this.renderRolesList();
            this.closeRoleModal();
            this.showNotification(isEdit ? 'Role updated!' : 'Role created!', 'success');
        } catch (error) {
            console.error('Error saving role:', error);
            this.showNotification('Failed to save role: ' + error.message, 'error');
        }
    }

    async deleteRole(roleId) {
        const role = this.roles.find(r => r.id === roleId);
        if (!role) return;
        if (!confirm(`Delete the "${role.name}" role?`)) return;

        try {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                              this.getCookie('csrftoken');
            const response = await fetch(`/api/office/roles/${roleId}/delete/`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': csrfToken }
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'Failed to delete role');
            }
            this.roles = this.roles.filter(r => r.id !== roleId);
            this.renderRolesList();
            this.showNotification('Role deleted', 'success');
        } catch (error) {
            console.error('Error deleting role:', error);
            this.showNotification('Failed to delete role: ' + error.message, 'error');
        }
    }

    discardChanges() {
        this.statusChoices = JSON.parse(this.originalData.statusChoices);
        this.typeChoices = JSON.parse(this.originalData.typeChoices);
        this.formatChoices = JSON.parse(this.originalData.formatChoices);
        this.tagsChoices = JSON.parse(this.originalData.tagsChoices);
        this.renderAll();
        this.checkForChanges();
        this.showNotification('Changes discarded', 'info');
    }

    showNotification(message, type = 'info') {
        // Always use fixed-position toast for settings page (don't use global showToast which displaces content)
        // Create toast notification (overlays above page content)
        const toast = document.createElement('div');
        toast.className = `settings-toast settings-toast-${type}`;
        toast.textContent = message;

        // Style the toast
        Object.assign(toast.style, {
            position: 'fixed',
            top: '20px',
            right: '20px',
            padding: '12px 20px',
            borderRadius: '8px',
            fontSize: '14px',
            fontWeight: '500',
            zIndex: '10001',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
            opacity: '0',
            transform: 'translateY(-10px)',
            transition: 'opacity 0.3s ease, transform 0.3s ease',
            maxWidth: '400px'
        });

        // Type-specific colors
        if (type === 'success') {
            toast.style.background = '#dcfce7';
            toast.style.color = '#166534';
            toast.style.border = '1px solid #86efac';
        } else if (type === 'error') {
            toast.style.background = '#fee2e2';
            toast.style.color = '#991b1b';
            toast.style.border = '1px solid #fca5a5';
        } else {
            toast.style.background = '#dbeafe';
            toast.style.color = '#1e40af';
            toast.style.border = '1px solid #93c5fd';
        }

        document.body.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        });

        // Auto-remove after 4 seconds
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
