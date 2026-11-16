/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Event Editing Interface Class - Clean Working Version
 */

console.log('=== JAVASCRIPT FILE LOADING ===');

class EventEditingInterface {
    constructor() {
        console.log('EventEditingInterface constructor called');
        this.init();
    }

    init() {
        console.log('EventEditingInterface init() called');

        // Initialize auto-save properties
        this.autoSaveTimeout = null;
        this.autoSaveDelay = 2000; // 2 second delay after user stops typing
        this.lastSavedData = null;
        this.isSaving = false; // Flag to prevent multiple simultaneous saves

        // Initialize overlay
        this.initializeOverlay();

        // Initialize tabs - CRITICAL FUNCTIONALITY
        setTimeout(() => {
            console.log('About to initialize tabs...');
            this.initializeTabs();
        }, 100);

        // Initialize other features
        this.initializeInteractiveElements();
        this.initializeEventTags();
        this.initializeCheckboxes();
        this.initializeAutoSave();
        this.initializeTimeValidation();
        this.initializeFieldSynchronization();
        this.initializeEmailViewer();
        this.initializeEmailToggle();

        // Set initial saved data to prevent unnecessary saves on load
        setTimeout(() => {
            this.lastSavedData = collectFormData();
            console.log('Initial form data captured for auto-save comparison');
        }, 1000);

        console.log('EventEditingInterface fully initialized');
    }

    // Method to reinitialize the interface (for when modal is reopened)
    reinitialize() {
        console.log('Reinitializing EventEditingInterface...');
        
        // Clear any existing timeouts
        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
            this.autoSaveTimeout = null;
        }

        // Reset saving state
        this.isSaving = false;

        // Force reinitialize all components immediately
        this.initializeTabs();
        this.initializeCheckboxes();
        this.initializeAutoSave();
        this.initializeFieldSynchronization();
        this.initializeEmailViewer();
        this.initializeEmailToggle();
        
        // Reset saved data after a short delay
        setTimeout(() => {
            this.lastSavedData = collectFormData();
            console.log('Interface reinitialized successfully');
        }, 100);
    }

    // Initialize field synchronization between tabs
    initializeFieldSynchronization() {
        console.log('Initializing field synchronization...');

        // Synchronize organization fields
        const headerOrg = document.getElementById('header-organization');
        const mainOrg = document.getElementById('organization');

        if (headerOrg && mainOrg) {
            // Remove existing listeners to prevent duplicates
            headerOrg.removeEventListener('input', this.syncOrgFields);
            mainOrg.removeEventListener('input', this.syncOrgFields);

            // Create bound functions for proper removal
            this.syncOrgFromHeader = (e) => {
                mainOrg.value = e.target.value;
                this.triggerAutoSave();
            };
            this.syncOrgFromMain = (e) => {
                headerOrg.value = e.target.value;
                this.triggerAutoSave();
            };

            headerOrg.addEventListener('input', this.syncOrgFromHeader);
            mainOrg.addEventListener('input', this.syncOrgFromMain);
        }

        // Synchronize notes fields across tabs
        const eventNotes = document.getElementById('event-notes');
        const partiesNotes = document.getElementById('parties-notes');
        const reviewNotes = document.getElementById('review-notes');

        const noteFields = [eventNotes, partiesNotes, reviewNotes].filter(field => field);

        noteFields.forEach((field, index) => {
            // Remove existing listeners
            field.removeEventListener('input', this.syncNotesFields);

            // Create sync function
            const syncNotes = (e) => {
                const value = e.target.value;
                noteFields.forEach((otherField, otherIndex) => {
                    if (otherIndex !== index) {
                        otherField.value = value;
                    }
                });
                this.triggerAutoSave();
            };

            field.addEventListener('input', syncNotes);
        });

        console.log('Field synchronization initialized');
    }

    initializeEmailViewer() {
        console.log('Initializing email viewer integration...');
        
        // Initialize EmailHTMLViewer if it's available
        if (window.EmailHTMLViewer && !window.emailHTMLViewer) {
            window.emailHTMLViewer = new EmailHTMLViewer();
        }
        
        // If EmailHTMLViewer is already initialized, reinitialize it
        if (window.emailHTMLViewer && typeof window.emailHTMLViewer.init === 'function') {
            window.emailHTMLViewer.init();
        }
        
        console.log('Email viewer integration initialized');
    }

    // Initialize Hide/Show Email functionality
    initializeEmailToggle() {
        console.log('Initializing email toggle functionality...');
        
        const hideEmailBtn = document.getElementById('hide-email-btn');
        const splitContainer = document.querySelector('.split-panel-container');
        
        if (!hideEmailBtn || !splitContainer) {
            console.warn('Hide email button or split container not found');
            return;
        }
        
        // Set initial state - email is hidden by default
        const isInitiallyHidden = splitContainer.classList.contains('email-hidden');
        const btnText = hideEmailBtn.querySelector('.btn-text');
        
        if (isInitiallyHidden) {
            hideEmailBtn.classList.add('showing-email');
            btnText.textContent = 'Show Email';
            console.log('Email panel initially hidden');
        } else {
            hideEmailBtn.classList.remove('showing-email');
            btnText.textContent = 'Hide Email';
            console.log('Email panel initially shown');
        }
        
        hideEmailBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const isHidden = splitContainer.classList.contains('email-hidden');
            
            if (isHidden) {
                // Show email panel - load content when showing
                splitContainer.classList.remove('email-hidden');
                hideEmailBtn.classList.remove('showing-email');
                btnText.textContent = 'Hide Email';
                
                // Load email content if not already loaded
                this.loadEmailContent();
                
                console.log('Email panel shown');
            } else {
                // Hide email panel
                splitContainer.classList.add('email-hidden');
                hideEmailBtn.classList.add('showing-email');
                btnText.textContent = 'Show Email';
                console.log('Email panel hidden');
            }
        });
        
        console.log('Email toggle functionality initialized');
    }

    // Method to load email content when panel is shown
    loadEmailContent() {
        console.log('Loading email content...');
        const emailDisplay = document.getElementById('email-content-display');
        
        if (emailDisplay && !emailDisplay.dataset.loaded) {
            // Mark as loaded to prevent multiple loads
            emailDisplay.dataset.loaded = 'true';
            
            // Email content is already in the HTML, so just ensure it's visible
            // In a real implementation, you might fetch content via AJAX here
            console.log('Email content loaded');
        }
    }

    triggerAutoSave() {
        // Clear existing timeout
        if (this.autoSaveTimeout) {
            clearTimeout(this.autoSaveTimeout);
        }

        // Set new timeout for auto-save
        this.autoSaveTimeout = setTimeout(() => {
            this.performAutoSave();
        }, this.autoSaveDelay);
    }

    performAutoSave() {
        console.log('Performing auto-save...');

        // Check if already saving
        if (this.isSaving) {
            console.log('Auto-save already in progress, skipping');
            return;
        }

        // Get current form data
        const currentData = collectFormData();

        // Check if data has changed
        if (this.lastSavedData && JSON.stringify(currentData) === JSON.stringify(this.lastSavedData)) {
            console.log('No changes detected, skipping auto-save');
            return;
        }

        // Get event ID
        const form = document.getElementById('eventForm');
        const eventId = form?.dataset?.eventId;

        if (!eventId || eventId === 'new' || eventId === 'undefined') {
            console.log('Cannot auto-save new event or invalid event ID, skipping');
            return;
        }

        // Validate that eventId is a valid UUID format
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
        if (!uuidRegex.test(eventId)) {
            console.log('Invalid event ID format, skipping auto-save:', eventId);
            return;
        }

        // Set saving flag and show indicator
        this.isSaving = true;
        this.showAutoSaveIndicator('saving');

        // Clean data for API submission
        const cleanData = this.cleanDataForAPI(currentData);
        console.log('Sending auto-save data:', cleanData);

        // Get CSRF token
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            console.error('Cannot perform auto-save: CSRF token not found');
            this.showAutoSaveIndicator('error');
            this.isSaving = false;
            return;
        }

        // Perform the save with timeout
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout

        fetch(`/api/events/${eventId}/`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(cleanData),
            credentials: 'same-origin',
            signal: controller.signal
        })
            .then(response => {
                clearTimeout(timeoutId);
                console.log('Auto-save response status:', response.status);

                if (response.ok) {
                    return response.json();
                }

                // Handle different error status codes
                let errorMessage = 'Unknown error';
                if (response.status === 403) {
                    errorMessage = 'Authentication failed - please refresh the page';
                } else if (response.status === 404) {
                    errorMessage = 'Event not found - it may have been deleted';
                } else if (response.status === 400) {
                    errorMessage = 'Invalid data - check form fields';
                } else if (response.status === 500) {
                    errorMessage = 'Server error - please try again';
                }

                return response.text().then(errorText => {
                    console.error('Auto-save error response:', errorText);
                    let errorData;
                    try {
                        errorData = JSON.parse(errorText);
                        if (errorData.detail) errorMessage = errorData.detail;
                        if (errorData.error) errorMessage = errorData.error;
                    } catch (e) {
                        errorData = { error: errorText, status: response.status, message: errorMessage };
                    }
                    throw new Error(JSON.stringify(errorData));
                });
            })
            .then(data => {
                console.log('Auto-save successful:', data);
                this.lastSavedData = currentData;
                this.showAutoSaveIndicator('saved');
            })
            .catch(error => {
                clearTimeout(timeoutId);
                console.error('Auto-save error:', error);
                this.showAutoSaveIndicator('error');

                if (error.name === 'AbortError') {
                    console.error('Auto-save timed out after 10 seconds');
                } else if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
                    console.error('Network error - check internet connection');
                } else {
                    try {
                        const errorData = JSON.parse(error.message);
                        console.error('Detailed auto-save error:', errorData);
                    } catch (e) {
                        console.error('Auto-save failed with message:', error.message);
                    }
                }
            })
            .finally(() => {
                this.isSaving = false;
            });
    }

    cleanDataForAPI(data) {
        // Create a clean copy of the data for API submission
        const cleanData = { ...data };

        // Handle date/time validation and cleanup
        if (cleanData.start_date && cleanData.end_date && cleanData.start_time && cleanData.end_time) {
            const startDateTime = new Date(`${cleanData.start_date}T${cleanData.start_time}`);
            const endDateTime = new Date(`${cleanData.end_date}T${cleanData.end_time}`);

            // If end time is not after start time, adjust it
            if (endDateTime <= startDateTime) {
                console.log('Adjusting end time to be after start time');
                const adjustedEnd = new Date(startDateTime.getTime() + 60 * 60 * 1000); // Add 1 hour
                cleanData.end_date = adjustedEnd.toISOString().split('T')[0];
                cleanData.end_time = adjustedEnd.toTimeString().slice(0, 5);
            }
        }

        // Ensure all string fields are strings, not null
        const stringFields = [
            'title', 'group', 'type', 'format', 'duration', 'location', 
            'description', 'notes', 'point_of_contact_name', 'point_of_contact_email', 
            'point_of_contact_phone', 'timezone', 'time_notes', 'reminder_time', 'status'
        ];

        stringFields.forEach(field => {
            if (cleanData[field] === null || cleanData[field] === undefined) {
                cleanData[field] = '';
            }
        });

        // Ensure arrays are arrays
        const arrayFields = ['tags', 'staff', 'legislative_topics', 'participants', 'attached_email_ids'];
        arrayFields.forEach(field => {
            if (!Array.isArray(cleanData[field])) {
                cleanData[field] = [];
            }
        });

        // Ensure approval_routing is an object
        if (typeof cleanData.approval_routing !== 'object' || cleanData.approval_routing === null) {
            cleanData.approval_routing = {};
        }

        // Handle boolean fields
        cleanData.reminder_enabled = Boolean(cleanData.reminder_enabled);
        cleanData.is_date_range = Boolean(cleanData.is_date_range);
        cleanData.is_longer_than_day = Boolean(cleanData.is_longer_than_day);

        // Set default data classification
        if (!cleanData.data_classification) {
            cleanData.data_classification = 'internal';
        }

        return cleanData;
    }

    showAutoSaveIndicator(status) {
        // Remove existing indicator
        const existingIndicator = document.querySelector('.auto-save-indicator');
        if (existingIndicator) {
            existingIndicator.remove();
        }

        // Create new indicator
        const indicator = document.createElement('div');
        indicator.className = 'auto-save-indicator';

        let message = '';
        let className = '';

        switch (status) {
            case 'saving':
                message = '💾 Saving...';
                className = 'saving';
                break;
            case 'saved':
                message = '✅ Saved';
                className = 'saved';
                break;
            case 'error':
                message = '❌ Save failed';
                className = 'error';
                break;
        }

        indicator.textContent = message;
        indicator.className += ` ${className}`;

        // Style the indicator
        indicator.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10001;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.3s ease;
            pointer-events: none;
        `;

        // Apply status-specific styles
        if (status === 'saving') {
            indicator.style.background = '#fef3c7';
            indicator.style.color = '#92400e';
            indicator.style.border = '1px solid #f59e0b';
        } else if (status === 'saved') {
            indicator.style.background = '#d1fae5';
            indicator.style.color = '#065f46';
            indicator.style.border = '1px solid #10b981';
        } else if (status === 'error') {
            indicator.style.background = '#fee2e2';
            indicator.style.color = '#991b1b';
            indicator.style.border = '1px solid #ef4444';
        }

        document.body.appendChild(indicator);

        // Auto-remove after delay (except for saving status)
        if (status !== 'saving') {
            setTimeout(() => {
                if (indicator.parentNode) {
                    indicator.style.opacity = '0';
                    indicator.style.transform = 'translateY(-10px)';
                    setTimeout(() => {
                        if (indicator.parentNode) {
                            indicator.remove();
                        }
                    }, 300);
                }
            }, 2000);
        }
    }

    initializeOverlay() {
        console.log('Initializing overlay...');
        const overlay = document.getElementById('event-editing-overlay');
        if (overlay) {
            overlay.style.position = 'fixed';
            overlay.style.top = '0';
            overlay.style.left = '0';
            overlay.style.right = '0';
            overlay.style.bottom = '0';
            overlay.style.width = '100vw';
            overlay.style.height = '100vh';
            overlay.style.background = 'rgba(0, 0, 0, 0.5)';
            overlay.style.zIndex = '1000';
            overlay.style.display = 'flex';
            overlay.style.alignItems = 'center';
            overlay.style.justifyContent = 'center';
            overlay.style.opacity = '1';
            overlay.style.visibility = 'visible';

            const container = overlay.querySelector('.split-panel-container');
            if (container) {
                container.style.margin = 'auto';
                container.style.transform = 'scale(1) translateY(0)';
            }

            document.body.style.overflow = 'hidden';
            console.log('Overlay initialized successfully');
        } else {
            console.log('ERROR: Overlay element not found');
        }
    }

    // CRITICAL: Tab functionality
    initializeTabs() {
        console.log('=== INITIALIZING TABS ===');

        // Tab mapping
        const tabMapping = {
            'event-details-tab': 'event-details-panel',
            'involved-parties-tab': 'involved-parties-panel',
            'staff-review-tab': 'staff-review-panel'
        };

        // Function to switch tabs
        const switchTab = (activeTabId) => {
            console.log('Switching to tab:', activeTabId);

            const targetPanelId = tabMapping[activeTabId];
            if (!targetPanelId) {
                console.error('No panel found for tab:', activeTabId);
                return;
            }

            // Hide all panels
            const allPanels = document.querySelectorAll('.tab-panel');
            allPanels.forEach(panel => {
                panel.style.display = 'none';
                panel.classList.remove('active');
            });

            // Deactivate all buttons
            const allButtons = document.querySelectorAll('.tab-button');
            allButtons.forEach(button => {
                button.classList.remove('active');
                button.setAttribute('aria-selected', 'false');
            });

            // Show target panel
            const targetPanel = document.getElementById(targetPanelId);
            if (targetPanel) {
                targetPanel.style.display = 'block';
                targetPanel.classList.add('active');
                console.log('Showed panel:', targetPanelId);
            }

            // Activate target button
            const targetButton = document.getElementById(activeTabId);
            if (targetButton) {
                targetButton.classList.add('active');
                targetButton.setAttribute('aria-selected', 'true');
                console.log('Activated button:', activeTabId);
            }
        };

        // Setup tab buttons
        const setupTabs = () => {
            const tabButtons = document.querySelectorAll('.tab-button');
            console.log('Found tab buttons:', tabButtons.length);

            if (tabButtons.length === 0) {
                console.log('No tab buttons found, retrying...');
                setTimeout(setupTabs, 100);
                return;
            }

            // Add click handlers to each button
            tabButtons.forEach((button) => {
                console.log('Setting up button:', button.id);

                // Ensure the button doesn't have href or form attributes that could cause navigation
                button.removeAttribute('href');
                button.removeAttribute('action');
                button.setAttribute('type', 'button');

                // Remove any existing handlers to prevent duplicates
                button.onclick = null;

                // Add simple, direct click handler
                button.addEventListener('click', (e) => {
                    console.log('Tab button clicked:', button.id);
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Direct tab switch
                    switchTab(button.id);
                    return false;
                });

                // Add keyboard handler
                button.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        console.log('Tab button activated via keyboard:', button.id);
                        switchTab(button.id);
                    }
                });
            });

            // Initialize first tab
            setTimeout(() => {
                console.log('Initializing first tab');
                switchTab('event-details-tab');
            }, 50);

            console.log('=== TABS SETUP COMPLETE ===');
        };

        setupTabs();
    }

    initializeInteractiveElements() {
        console.log('Initializing interactive elements...');

        // Close button functionality
        const closeButton = document.querySelector('.close-button');
        if (closeButton) {
            closeButton.addEventListener('click', (e) => {
                e.stopPropagation();
                console.log('Close button clicked');
                closeModal();
            });
        }

        // Action buttons functionality
        const actionButtons = document.querySelectorAll('.action-btn');
        actionButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.stopPropagation();
                console.log('Action button clicked:', button.textContent.trim());
            });
        });

        // Prevent modal close when clicking inside the panel
        const eventPanel = document.querySelector('.event-editing-panel');
        if (eventPanel) {
            eventPanel.addEventListener('click', (e) => {
                if (!e.target.closest('.tab-button')) {
                    e.stopPropagation();
                }
            });
        }

        // Prevent any form submissions that might cause navigation
        const form = document.getElementById('eventForm');
        if (form) {
            form.addEventListener('submit', (e) => {
                console.log('Form submission prevented - using autosave instead');
                e.preventDefault();
                e.stopPropagation();
                return false;
            });
        }

        // Close modal when clicking overlay background
        const overlay = document.getElementById('event-editing-overlay');
        if (overlay) {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) {
                    console.log('Overlay background clicked - closing modal');
                    closeModal();
                }
            });
        }

        console.log('Interactive elements initialized');
    }

    initializeEventTags() {
        console.log('Initializing event tags...');

        const tagInput = document.querySelector('.tag-input');
        const tagRemoveButtons = document.querySelectorAll('.tag-remove');

        if (tagInput) {
            tagInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && e.target.value.trim()) {
                    e.preventDefault();
                    this.addTag(e.target.value.trim());
                    e.target.value = '';
                }
            });
        }

        tagRemoveButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                button.parentElement.remove();
                console.log('Tag removed');
            });
        });

        console.log('Event tags initialized');
    }

    addTag(tagText) {
        const tagContainer = document.querySelector('.tags-container');
        const tagInput = document.querySelector('.tag-input');

        if (tagContainer && tagInput) {
            const newTag = document.createElement('div');
            newTag.className = 'tag';
            newTag.innerHTML = tagText + '<button type="button" class="tag-remove">×</button>';

            const removeButton = newTag.querySelector('.tag-remove');
            removeButton.addEventListener('click', (e) => {
                e.preventDefault();
                newTag.remove();
            });

            tagContainer.insertBefore(newTag, tagInput);
            console.log('Added tag:', tagText);
        }
    }

    // Checkbox functionality for date/time controls
    initializeCheckboxes() {
        console.log('Initializing checkbox functionality...');

        const dateRangeCheckbox = document.getElementById('date-range-event');
        const longerThanDayCheckbox = document.getElementById('longer-than-day');
        const startDateInput = document.getElementById('start-date');
        const endDateInput = document.getElementById('end-date');
        const startTimeInput = document.getElementById('start-time');
        const endTimeInput = document.getElementById('end-time');
        const timezoneSelect = document.getElementById('timezone');
        const timeNotesContainer = document.getElementById('time-notes-container');
        const timeNotesInput = document.getElementById('time-notes');

        if (!dateRangeCheckbox || !longerThanDayCheckbox) {
            console.log('Checkboxes not found, skipping initialization');
            return;
        }

        // Helper function to show/hide elements
        const toggleElement = (element, show) => {
            if (element) {
                element.style.display = show ? 'block' : 'none';
                if (element.closest('.options-row')) {
                    element.closest('.options-row').style.display = show ? 'flex' : 'none';
                }
            }
        };

        // Helper function to enable/disable inputs
        const toggleInput = (input, enabled) => {
            if (input) {
                input.disabled = !enabled;
                if (enabled) {
                    input.style.background = 'var(--bg-primary, #ffffff)';
                    input.style.color = 'var(--text-primary, #111827)';
                } else {
                    input.style.background = 'var(--bg-tertiary, #f3f4f6)';
                    input.style.color = 'var(--text-tertiary, #9ca3af)';
                }
            }
        };

        // Helper function to check if dates are different
        const datesDiffer = () => {
            if (!startDateInput || !endDateInput) return false;
            return startDateInput.value !== endDateInput.value && endDateInput.value !== '';
        };

        // Date Range checkbox handler
        const handleDateRangeChange = () => {
            const isDateRange = dateRangeCheckbox.checked;
            console.log('Date range checkbox changed:', isDateRange);

            if (isDateRange) {
                // Enable end date
                toggleInput(endDateInput, true);

                // Hide time inputs and show notes field
                toggleElement(startTimeInput?.closest('.form-field'), false);
                toggleElement(endTimeInput?.closest('.form-field'), false);
                toggleElement(timeNotesContainer, true);

                // Hide "longer than a day" checkbox and timezone
                toggleElement(longerThanDayCheckbox?.closest('.options-row'), false);
                toggleElement(timezoneSelect?.closest('.options-row'), false);

                // Focus on notes input
                if (timeNotesInput) {
                    setTimeout(() => timeNotesInput.focus(), 100);
                }
            } else {
                // Show time inputs and hide notes field
                toggleElement(startTimeInput?.closest('.form-field'), true);
                toggleElement(endTimeInput?.closest('.form-field'), true);
                toggleElement(timeNotesContainer, false);

                // Show "longer than a day" checkbox and timezone
                toggleElement(longerThanDayCheckbox?.closest('.options-row'), true);
                toggleElement(timezoneSelect?.closest('.options-row'), true);

                // Check if dates differ and auto-check "longer than a day"
                if (datesDiffer()) {
                    longerThanDayCheckbox.checked = true;
                    toggleInput(endDateInput, true);
                } else {
                    longerThanDayCheckbox.checked = false;
                    toggleInput(endDateInput, false);
                }
            }
        };

        // Longer than a day checkbox handler
        const handleLongerThanDayChange = () => {
            const isLongerThanDay = longerThanDayCheckbox.checked;
            console.log('Longer than a day checkbox changed:', isLongerThanDay);

            // Enable/disable end date input
            toggleInput(endDateInput, isLongerThanDay);

            // If unchecking and end date is different from start date, set end date to match start date
            if (!isLongerThanDay && startDateInput && endDateInput) {
                endDateInput.value = startDateInput.value;
            }
        };

        // Date input change handlers
        const handleDateChange = () => {
            // Only handle this if date range is not checked
            if (!dateRangeCheckbox.checked) {
                if (datesDiffer()) {
                    longerThanDayCheckbox.checked = true;
                    toggleInput(endDateInput, true);
                } else {
                    longerThanDayCheckbox.checked = false;
                    toggleInput(endDateInput, false);
                }
            }
        };

        // Remove existing event listeners to prevent duplicates
        dateRangeCheckbox.removeEventListener('change', handleDateRangeChange);
        longerThanDayCheckbox.removeEventListener('change', handleLongerThanDayChange);
        if (startDateInput) {
            startDateInput.removeEventListener('change', handleDateChange);
        }
        if (endDateInput) {
            endDateInput.removeEventListener('change', handleDateChange);
        }

        // Add event listeners
        dateRangeCheckbox.addEventListener('change', handleDateRangeChange);
        longerThanDayCheckbox.addEventListener('change', handleLongerThanDayChange);

        if (startDateInput) {
            startDateInput.addEventListener('change', handleDateChange);
        }
        if (endDateInput) {
            endDateInput.addEventListener('change', handleDateChange);
        }

        // Initialize state
        console.log('Setting initial checkbox state...');

        // Disable end date by default
        toggleInput(endDateInput, false);

        // Hide time notes by default
        toggleElement(timeNotesContainer, false);

        // If either checkbox is already checked, trigger their handlers
        if (dateRangeCheckbox.checked) {
            handleDateRangeChange();
        } else if (longerThanDayCheckbox.checked) {
            handleLongerThanDayChange();
        }

        console.log('Checkbox functionality initialized successfully');
    }

    initializeAutoSave() {
        console.log('Initializing auto-save functionality...');

        // Store reference to bound function for removal
        if (!this.autoSaveHandler) {
            this.autoSaveHandler = () => this.triggerAutoSave();
        }

        // Get all form inputs that should trigger auto-save
        const autoSaveFields = [
            'event-editing-title', 'header-organization', 'organization', 'event-type',
            'event-format', 'event-duration', 'event-location', 'event-description',
            'event-notes', 'parties-notes', 'review-notes', 'start-date', 'start-time', 
            'end-date', 'end-time', 'timezone', 'time-notes', 'point-of-contact', 
            'contact-info', 'expected-attendees', 'reminder', 'event-status-select'
        ];

        // Add event listeners to all auto-save fields
        autoSaveFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (field) {
                // Remove existing listeners first
                field.removeEventListener('input', this.autoSaveHandler);
                field.removeEventListener('change', this.autoSaveHandler);

                // Add new listeners
                if (field.type === 'checkbox') {
                    field.addEventListener('change', this.autoSaveHandler);
                } else if (field.tagName === 'SELECT') {
                    field.addEventListener('change', this.autoSaveHandler);
                } else {
                    field.addEventListener('input', this.autoSaveHandler);
                    field.addEventListener('change', this.autoSaveHandler);
                }
                console.log(`Auto-save enabled for field: ${fieldId}`);
            }
        });

        // Add listeners for checkboxes
        const checkboxes = ['date-range-event', 'longer-than-day'];
        checkboxes.forEach(checkboxId => {
            const checkbox = document.getElementById(checkboxId);
            if (checkbox) {
                // Remove existing listener first
                checkbox.removeEventListener('change', this.autoSaveHandler);
                // Add new listener
                checkbox.addEventListener('change', this.autoSaveHandler);
                console.log(`Auto-save enabled for checkbox: ${checkboxId}`);
            }
        });

        console.log('Auto-save functionality initialized');
    }

    initializeTimeValidation() {
        console.log('Initializing time validation...');

        const startTimeInput = document.getElementById('start-time');
        const endTimeInput = document.getElementById('end-time');
        const startDateInput = document.getElementById('start-date');
        const endDateInput = document.getElementById('end-date');

        // Function to validate time combination
        const validateDateTime = () => {
            if (!startDateInput?.value || !endDateInput?.value || !startTimeInput?.value || !endTimeInput?.value) {
                return; // Skip validation if any field is empty
            }

            const startDateTime = new Date(`${startDateInput.value}T${startTimeInput.value}`);
            const endDateTime = new Date(`${endDateInput.value}T${endTimeInput.value}`);

            if (endDateTime <= startDateTime) {
                console.warn('End time is not after start time, adjusting...');
                // Set end time to 1 hour after start time
                const adjustedEnd = new Date(startDateTime.getTime() + 60 * 60 * 1000);

                // If the adjusted time is on a different date, update the end date too
                if (adjustedEnd.toDateString() !== startDateTime.toDateString()) {
                    endDateInput.value = adjustedEnd.toISOString().split('T')[0];
                }
                endTimeInput.value = adjustedEnd.toTimeString().slice(0, 5);

                console.log(`Adjusted end time to: ${endDateInput.value} ${endTimeInput.value}`);
            }
        };

        // Add event listeners for time validation
        if (startTimeInput) {
            startTimeInput.addEventListener('change', validateDateTime);
        }
        if (endTimeInput) {
            endTimeInput.addEventListener('change', validateDateTime);
        }

        console.log('Time validation initialized');
    }
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function () {
    console.log('=== DOM READY - STARTING INITIALIZATION ===');

    // Create global instance
    if (typeof EventEditingInterface !== 'undefined') {
        window.eventEditingInterface = new EventEditingInterface();
        console.log('EventEditingInterface initialized successfully');
    } else {
        console.error('EventEditingInterface class not found');
    }
});

// Also initialize if DOM is already loaded
if (document.readyState === 'complete' || document.readyState === 'interactive') {
    console.log('=== DOM ALREADY READY - INITIALIZING IMMEDIATELY ===');
    if (typeof EventEditingInterface !== 'undefined') {
        window.eventEditingInterface = new EventEditingInterface();
        console.log('EventEditingInterface initialized immediately');
    }
}

// Function to open the modal (called from other pages)
function openEventEditingModal(eventId = null) {
    const modal = document.getElementById('event-editing-overlay');
    if (modal) {
        // Replace history state to prevent form resubmission warnings
        window.history.replaceState({}, document.title, window.location.pathname);

        // Set the event ID on the form
        const form = document.getElementById('eventForm');
        if (form) {
            form.dataset.eventId = eventId || 'new';

            // If editing existing event, load the data
            if (eventId && eventId !== 'new') {
                loadEventData(eventId);
            } else {
                // Clear form for new event
                form.reset();
            }
        }

        modal.style.display = 'block';
        document.body.classList.add('modal-open');

        // Reinitialize the interface if it exists
        if (window.eventEditingInterface) {
            console.log('Reinitializing event editing interface...');
            window.eventEditingInterface.reinitialize();
        } else {
            // Create new instance if it doesn't exist
            console.log('Creating new event editing interface instance...');
            setTimeout(() => {
                window.eventEditingInterface = new EventEditingInterface();
            }, 100);
        }
    }
}

// Form submission handling
function closeModal() {
    console.log('Close modal requested');
    
    // Check if there's an active EventEditingInterface instance
    const eventInterface = window.eventEditingInterface;
    
    if (eventInterface) {
        // Check if currently saving
        if (eventInterface.isSaving) {
            console.log('Save in progress, waiting for completion before closing...');
            showCloseWaitingIndicator('Saving in progress...');
            
            // Wait for save to complete
            const checkSaveComplete = () => {
                if (!eventInterface.isSaving) {
                    console.log('Save completed, proceeding with close');
                    hideCloseWaitingIndicator();
                    performModalClose();
                } else {
                    // Check again in 100ms
                    setTimeout(checkSaveComplete, 100);
                }
            };
            
            checkSaveComplete();
            return;
        }
        
        // Check for unsaved changes
        const currentData = collectFormData();
        const hasUnsavedChanges = eventInterface.lastSavedData && 
            JSON.stringify(currentData) !== JSON.stringify(eventInterface.lastSavedData);
        
        if (hasUnsavedChanges) {
            console.log('Unsaved changes detected, triggering save before close...');
            showCloseWaitingIndicator('Saving changes...');
            
            // Trigger auto-save and wait for completion
            eventInterface.performAutoSave();
            
            // Wait for save to complete
            const checkSaveComplete = () => {
                if (!eventInterface.isSaving) {
                    console.log('Auto-save completed, proceeding with close');
                    hideCloseWaitingIndicator();
                    performModalClose();
                } else {
                    // Check again in 100ms
                    setTimeout(checkSaveComplete, 100);
                }
            };
            
            // Start checking after a brief delay to allow save to start
            setTimeout(checkSaveComplete, 200);
            return;
        }
    }
    
    // No unsaved changes and not saving, close immediately
    console.log('No unsaved changes, closing immediately');
    performModalClose();
}

function performModalClose() {
    const modal = document.getElementById('event-editing-overlay');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');

        // Clear any form data and replace history state to prevent resubmission warning
        const form = document.getElementById('eventForm');
        if (form) {
            form.reset();
        }

        // Clear any auto-save timeouts
        if (window.eventEditingInterface && window.eventEditingInterface.autoSaveTimeout) {
            clearTimeout(window.eventEditingInterface.autoSaveTimeout);
            window.eventEditingInterface.autoSaveTimeout = null;
        }

        // Replace the current history state to avoid POST resubmission
        if (window.history.state !== null || window.location.search) {
            window.history.replaceState({}, document.title, window.location.pathname);
        }

        console.log('Modal closed and cleaned up');
    }
}

function showCloseWaitingIndicator(message) {
    // Remove any existing indicator
    hideCloseWaitingIndicator();
    
    const indicator = document.createElement('div');
    indicator.id = 'close-waiting-indicator';
    indicator.className = 'close-waiting-indicator';
    indicator.innerHTML = `
        <div class="waiting-content">
            <div class="waiting-spinner"></div>
            <span class="waiting-text">${message}</span>
        </div>
    `;
    
    // Style the indicator
    indicator.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        z-index: 10002;
        background: rgba(0, 0, 0, 0.8);
        color: white;
        padding: 20px 30px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 12px;
        backdrop-filter: blur(4px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    `;
    
    // Add spinner styles
    const style = document.createElement('style');
    style.textContent = `
        .waiting-content {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .waiting-spinner {
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-top: 2px solid white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    `;
    
    document.head.appendChild(style);
    document.body.appendChild(indicator);
}

function hideCloseWaitingIndicator() {
    const indicator = document.getElementById('close-waiting-indicator');
    if (indicator) {
        indicator.remove();
    }
}

function loadEventData(eventId) {
    fetch(`/api/events/${eventId}/`)
        .then(response => response.json())
        .then(event => {
            // Populate form fields with event data
            if (document.getElementById('event-editing-title')) {
                document.getElementById('event-editing-title').value = event.title || '';
            }
            if (document.getElementById('header-organization')) {
                document.getElementById('header-organization').value = event.group || '';
            }
            if (document.getElementById('organization')) {
                document.getElementById('organization').value = event.group || '';
            }
            if (document.getElementById('event-type')) {
                document.getElementById('event-type').value = event.type || '';
            }
            if (document.getElementById('event-format')) {
                document.getElementById('event-format').value = event.format || '';
            }
            if (document.getElementById('event-duration')) {
                document.getElementById('event-duration').value = event.duration || '';
            }
            if (document.getElementById('event-location')) {
                document.getElementById('event-location').value = event.location || '';
            }
            if (document.getElementById('event-description')) {
                document.getElementById('event-description').value = event.description || '';
            }
            if (document.getElementById('event-notes')) {
                document.getElementById('event-notes').value = event.notes || '';
            }
            // Sync notes to other tabs
            if (document.getElementById('parties-notes')) {
                document.getElementById('parties-notes').value = event.notes || '';
            }
            if (document.getElementById('review-notes')) {
                document.getElementById('review-notes').value = event.notes || '';
            }
            if (document.getElementById('start-date')) {
                document.getElementById('start-date').value = event.start_date || '';
            }
            if (document.getElementById('start-time')) {
                document.getElementById('start-time').value = event.start_time || '';
            }
            if (document.getElementById('end-date')) {
                document.getElementById('end-date').value = event.end_date || '';
            }
            if (document.getElementById('end-time')) {
                document.getElementById('end-time').value = event.end_time || '';
            }
            if (document.getElementById('timezone')) {
                document.getElementById('timezone').value = event.timezone || 'America/Denver';
            }
            if (document.getElementById('time-notes')) {
                document.getElementById('time-notes').value = event.time_notes || '';
            }
            if (document.getElementById('date-range-event')) {
                document.getElementById('date-range-event').checked = event.is_date_range || false;
            }
            if (document.getElementById('longer-than-day')) {
                document.getElementById('longer-than-day').checked = event.is_longer_than_day || false;
            }
            if (document.getElementById('point-of-contact')) {
                document.getElementById('point-of-contact').value = event.point_of_contact_name || '';
            }
            if (document.getElementById('contact-info')) {
                document.getElementById('contact-info').value = event.point_of_contact_email || '';
            }
            if (document.getElementById('expected-attendees')) {
                document.getElementById('expected-attendees').value = event.expected_attendees || '';
            }
            if (document.getElementById('reminder')) {
                document.getElementById('reminder').value = event.reminder_time || '';
            }
            if (document.getElementById('event-status-select')) {
                document.getElementById('event-status-select').value = event.status || 'received';
            }

            // Update checkboxes and trigger their handlers
            if (window.eventEditingInterface) {
                // Trigger checkbox handlers to update UI
                const dateRangeCheckbox = document.getElementById('date-range-event');
                const longerThanDayCheckbox = document.getElementById('longer-than-day');
                if (dateRangeCheckbox && dateRangeCheckbox.checked) {
                    dateRangeCheckbox.dispatchEvent(new Event('change'));
                }
                if (longerThanDayCheckbox && longerThanDayCheckbox.checked) {
                    longerThanDayCheckbox.dispatchEvent(new Event('change'));
                }
            }
        })
        .catch(error => {
            console.error('Error loading event data:', error);
        });
}

// Close modal when clicking outside
window.addEventListener('click', function (event) {
    const modal = document.getElementById('event-editing-overlay');
    if (event.target === modal) {
        closeModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        // The v2 event editing modal manages its own Escape handling (closing
        // popups in priority order first, then saving + closing the modal).
        // Defer to it entirely while it's open so we don't bypass that order.
        const v2 = window.eventEditingInterface;
        if (v2 && v2.overlay && v2.overlay.classList.contains('active')) {
            return;
        }
        closeModal();
    }
});

function getCsrfToken() {
    // Try multiple ways to get the CSRF token
    let csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;

    if (!csrfToken) {
        // Try getting from meta tag
        csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
    }

    if (!csrfToken) {
        // Try getting from cookie
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                csrfToken = value;
                break;
            }
        }
    }

    if (!csrfToken) {
        console.error('CSRF token not found in form, meta tag, or cookies');
    } else {
        console.log('CSRF token found:', csrfToken.substring(0, 10) + '...');
    }

    return csrfToken;
}

function collectFormData() {
    // Collect all form data from the interface
    const formData = {};

    // Basic event information
    formData.title = document.getElementById('event-editing-title')?.value?.trim() || '';
    
    // Get group from either header or main organization field (they should be synced)
    const headerOrg = document.getElementById('header-organization')?.value?.trim() || '';
    const mainOrg = document.getElementById('organization')?.value?.trim() || '';
    formData.group = headerOrg || mainOrg;
    
    formData.type = document.getElementById('event-type')?.value || '';
    formData.format = document.getElementById('event-format')?.value || '';
    formData.duration = document.getElementById('event-duration')?.value || '';
    formData.location = document.getElementById('event-location')?.value?.trim() || '';
    formData.description = document.getElementById('event-description')?.value?.trim() || '';
    
    // Get notes from any of the synchronized fields (they should all have the same value)
    const eventNotes = document.getElementById('event-notes')?.value?.trim() || '';
    const partiesNotes = document.getElementById('parties-notes')?.value?.trim() || '';
    const reviewNotes = document.getElementById('review-notes')?.value?.trim() || '';
    formData.notes = eventNotes || partiesNotes || reviewNotes;

    // Date and time information
    const startDate = document.getElementById('start-date')?.value;
    const startTime = document.getElementById('start-time')?.value;
    const endDate = document.getElementById('end-date')?.value;
    const endTime = document.getElementById('end-time')?.value;

    formData.start_date = startDate && startDate !== '' ? startDate : null;
    formData.start_time = startTime && startTime !== '' ? startTime : null;
    formData.end_date = endDate && endDate !== '' ? endDate : null;
    formData.end_time = endTime && endTime !== '' ? endTime : null;
    formData.timezone = document.getElementById('timezone')?.value || 'America/Denver';
    formData.time_notes = document.getElementById('time-notes')?.value?.trim() || '';
    
    // Checkbox states
    formData.is_date_range = document.getElementById('date-range-event')?.checked || false;
    formData.is_longer_than_day = document.getElementById('longer-than-day')?.checked || false;

    // Contact information
    formData.point_of_contact_name = document.getElementById('point-of-contact')?.value?.trim() || '';
    formData.point_of_contact_email = document.getElementById('contact-info')?.value?.trim() || '';
    formData.point_of_contact_phone = ''; // Always empty string for now
    
    // Expected attendees - handle as number or null
    const expectedAttendeesValue = document.getElementById('expected-attendees')?.value;
    formData.expected_attendees = expectedAttendeesValue && !isNaN(parseInt(expectedAttendeesValue)) ? parseInt(expectedAttendeesValue) : null;

    // Collect tags from the tags container
    const tags = [];
    document.querySelectorAll('.tags-container .tag').forEach(tag => {
        const tagText = tag.textContent.replace('×', '').trim();
        if (tagText && tagText !== 'Add tag...') {
            tags.push(tagText);
        }
    });
    formData.tags = tags;

    // Collect staff assignments from staff pills
    const staff = [];
    document.querySelectorAll('.staff-container .staff-pill, .staff-grid .staff-pill').forEach(pill => {
        const staffText = pill.textContent.replace('×', '').trim();
        if (staffText && staffText !== '+ Add Staff') {
            staff.push(staffText);
        }
    });
    formData.staff = staff;

    // Reminder settings
    const reminderSelect = document.getElementById('reminder');
    const reminderValue = reminderSelect?.value || '';
    formData.reminder_enabled = reminderValue !== '';
    formData.reminder_time = reminderValue;

    // Initialize empty arrays for complex fields that might be populated later
    formData.legislative_topics = [];
    formData.participants = [];
    formData.approval_routing = {};
    formData.attached_email_ids = [];

    // Status and classification - look for status select or default
    formData.status = document.getElementById('event-status-select')?.value || 'received';
    formData.data_classification = 'internal';

    console.log('Collected form data:', formData);
    return formData;
}

// Manual save function for testing - call from console with manualSave()
window.manualSave = function () {
    const form = document.getElementById('eventForm');
    const eventId = form?.dataset?.eventId;

    if (!eventId) {
        console.error('No event ID found');
        return;
    }

    const formData = collectFormData();
    const csrfToken = getCsrfToken();
    console.log('Manual save with form data:', formData);

    fetch(`/api/events/${eventId}/`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(formData),
        credentials: 'same-origin'
    })
        .then(response => {
            console.log('Manual save response:', response.status, response.statusText);
            if (response.ok) {
                return response.json();
            } else {
                return response.text();
            }
        })
        .then(data => {
            console.log('✅ Manual save successful:', data);
            alert('Save successful!');
        })
        .catch(error => {
            console.error('❌ Manual save error:', error);
            alert('Save failed: ' + error.message);
        });
};

console.log('Manual save function available: call manualSave() from console to test saving');
console.log('=== JAVASCRIPT FILE LOADED COMPLETELY ===');