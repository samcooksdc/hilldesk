/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Interactive Components for HillDesk
 */

// Initialize components when DOM is loaded
function initializeComponents() {
    initializeModals();
    initializeTabs();
    initializeDropdowns();
    initializeTooltips();
    initializePagination();
    initializeDataTables();
    initializeFormComponents();
    initializeSearchComponents();
    initializeCalendarComponents();
    
    console.log('Components initialized');
}

/**
 * Modal Component
 */
function initializeModals() {
    // Modal triggers
    document.addEventListener('click', function(event) {
        const modalTrigger = event.target.closest('[data-modal-target]');
        if (modalTrigger) {
            event.preventDefault();
            const targetId = modalTrigger.getAttribute('data-modal-target');
            const modal = document.getElementById(targetId);
            if (modal) {
                showModal(modal);
            }
        }
        
        // Modal close buttons
        const modalClose = event.target.closest('.modal-close, [data-modal-close]');
        if (modalClose) {
            event.preventDefault();
            const modal = modalClose.closest('.modal-overlay');
            if (modal) {
                hideModal(modal);
            }
        }
        
        // Close modal when clicking overlay
        if (event.target.classList.contains('modal-overlay')) {
            hideModal(event.target);
        }
    });
    
    // Close modal on escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            const openModal = document.querySelector('.modal-overlay.show');
            if (openModal) {
                hideModal(openModal);
            }
        }
    });
}

function showModal(modal) {
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
    
    // Focus first focusable element
    const focusableElements = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusableElements.length > 0) {
        focusableElements[0].focus();
    }
    
    // Prevent body scroll
    document.body.style.overflow = 'hidden';
    
    // Trap focus within modal
    trapFocus(modal);
}

function hideModal(modal) {
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    
    // Restore body scroll
    document.body.style.overflow = '';
    
    // Return focus to trigger element
    const trigger = document.querySelector(`[data-modal-target="${modal.id}"]`);
    if (trigger) {
        trigger.focus();
    }
}

function trapFocus(element) {
    const focusableElements = element.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    
    element.addEventListener('keydown', function(event) {
        if (event.key === 'Tab') {
            if (event.shiftKey) {
                if (document.activeElement === firstElement) {
                    event.preventDefault();
                    lastElement.focus();
                }
            } else {
                if (document.activeElement === lastElement) {
                    event.preventDefault();
                    firstElement.focus();
                }
            }
        }
    });
}

/**
 * Tabs Component
 */
function initializeTabs() {
    const tabLists = document.querySelectorAll('.tab-list');
    
    tabLists.forEach(function(tabList) {
        const tabs = tabList.querySelectorAll('.tab-link');
        const panels = document.querySelectorAll('.tab-panel');
        
        tabs.forEach(function(tab, index) {
            tab.addEventListener('click', function(event) {
                event.preventDefault();
                
                // Remove active class from all tabs and panels
                tabs.forEach(t => t.classList.remove('active'));
                panels.forEach(p => p.classList.remove('active'));
                
                // Add active class to clicked tab
                tab.classList.add('active');
                
                // Show corresponding panel
                const targetId = tab.getAttribute('href').substring(1);
                const targetPanel = document.getElementById(targetId);
                if (targetPanel) {
                    targetPanel.classList.add('active');
                }
                
                // Update ARIA attributes
                tabs.forEach(t => t.setAttribute('aria-selected', 'false'));
                tab.setAttribute('aria-selected', 'true');
            });
            
            // Keyboard navigation
            tab.addEventListener('keydown', function(event) {
                let newIndex = index;
                
                if (event.key === 'ArrowRight') {
                    event.preventDefault();
                    newIndex = (index + 1) % tabs.length;
                } else if (event.key === 'ArrowLeft') {
                    event.preventDefault();
                    newIndex = (index - 1 + tabs.length) % tabs.length;
                } else if (event.key === 'Home') {
                    event.preventDefault();
                    newIndex = 0;
                } else if (event.key === 'End') {
                    event.preventDefault();
                    newIndex = tabs.length - 1;
                }
                
                if (newIndex !== index) {
                    tabs[newIndex].focus();
                    tabs[newIndex].click();
                }
            });
        });
    });
}

/**
 * Dropdown Component
 */
function initializeDropdowns() {
    document.addEventListener('click', function(event) {
        const dropdownToggle = event.target.closest('.dropdown-toggle');
        
        if (dropdownToggle) {
            event.stopPropagation();
            const dropdown = dropdownToggle.closest('.dropdown');
            const isOpen = dropdown.classList.contains('show');
            
            // Close all other dropdowns
            document.querySelectorAll('.dropdown.show').forEach(function(openDropdown) {
                if (openDropdown !== dropdown) {
                    openDropdown.classList.remove('show');
                    const toggle = openDropdown.querySelector('.dropdown-toggle');
                    if (toggle) {
                        toggle.setAttribute('aria-expanded', 'false');
                    }
                }
            });
            
            // Toggle current dropdown
            dropdown.classList.toggle('show');
            dropdownToggle.setAttribute('aria-expanded', !isOpen);
        } else {
            // Close all dropdowns when clicking outside
            document.querySelectorAll('.dropdown.show').forEach(function(dropdown) {
                dropdown.classList.remove('show');
                const toggle = dropdown.querySelector('.dropdown-toggle');
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'false');
                }
            });
        }
    });
    
    // Keyboard navigation for dropdowns
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            document.querySelectorAll('.dropdown.show').forEach(function(dropdown) {
                dropdown.classList.remove('show');
                const toggle = dropdown.querySelector('.dropdown-toggle');
                if (toggle) {
                    toggle.setAttribute('aria-expanded', 'false');
                    toggle.focus();
                }
            });
        }
    });
}

/**
 * Tooltip Component
 */
function initializeTooltips() {
    const tooltips = document.querySelectorAll('.tooltip');
    
    tooltips.forEach(function(tooltip) {
        const content = tooltip.querySelector('.tooltip-content');
        if (!content) return;
        
        let showTimeout, hideTimeout;
        
        tooltip.addEventListener('mouseenter', function() {
            clearTimeout(hideTimeout);
            showTimeout = setTimeout(() => {
                content.style.opacity = '1';
                content.style.visibility = 'visible';
            }, 500);
        });
        
        tooltip.addEventListener('mouseleave', function() {
            clearTimeout(showTimeout);
            hideTimeout = setTimeout(() => {
                content.style.opacity = '0';
                content.style.visibility = 'hidden';
            }, 100);
        });
        
        // Keyboard support
        tooltip.addEventListener('focus', function() {
            content.style.opacity = '1';
            content.style.visibility = 'visible';
        });
        
        tooltip.addEventListener('blur', function() {
            content.style.opacity = '0';
            content.style.visibility = 'hidden';
        });
    });
}

/**
 * Pagination Component
 */
function initializePagination() {
    const paginationContainers = document.querySelectorAll('.pagination');
    
    paginationContainers.forEach(function(container) {
        const items = container.querySelectorAll('.pagination-item');
        
        items.forEach(function(item) {
            item.addEventListener('click', function(event) {
                if (this.classList.contains('disabled') || this.classList.contains('active')) {
                    event.preventDefault();
                    return;
                }
                
                // Show loading state
                if (window.showLoading) {
                    window.showLoading('Loading page...');
                }
            });
        });
    });
}

/**
 * Data Table Component
 */
function initializeDataTables() {
    const tables = document.querySelectorAll('.data-table');
    
    tables.forEach(function(table) {
        // Initialize sortable headers
        const sortableHeaders = table.querySelectorAll('.sortable');
        
        sortableHeaders.forEach(function(header) {
            header.addEventListener('click', function() {
                const currentSort = this.classList.contains('asc') ? 'asc' : 
                                  this.classList.contains('desc') ? 'desc' : 'none';
                
                // Remove sort classes from all headers
                sortableHeaders.forEach(h => h.classList.remove('asc', 'desc'));
                
                // Apply new sort
                if (currentSort === 'none' || currentSort === 'desc') {
                    this.classList.add('asc');
                } else {
                    this.classList.add('desc');
                }
                
                // Trigger sort (this would typically make an AJAX request)
                const sortField = this.getAttribute('data-sort-field');
                const sortDirection = this.classList.contains('asc') ? 'asc' : 'desc';
                
                if (sortField) {
                    handleTableSort(sortField, sortDirection);
                }
            });
        });
        
        // Initialize row selection
        const selectAllCheckbox = table.querySelector('input[type="checkbox"][data-select-all]');
        const rowCheckboxes = table.querySelectorAll('tbody input[type="checkbox"]');
        
        if (selectAllCheckbox && rowCheckboxes.length > 0) {
            selectAllCheckbox.addEventListener('change', function() {
                rowCheckboxes.forEach(checkbox => {
                    checkbox.checked = this.checked;
                    updateRowSelection(checkbox);
                });
                updateBulkActions();
            });
            
            rowCheckboxes.forEach(function(checkbox) {
                checkbox.addEventListener('change', function() {
                    updateRowSelection(this);
                    updateSelectAllState();
                    updateBulkActions();
                });
            });
        }
    });
}

function handleTableSort(field, direction) {
    // This would typically make an AJAX request to sort the data
    const currentUrl = new URL(window.location);
    currentUrl.searchParams.set('sort_by', direction === 'desc' ? `-${field}` : field);
    
    if (window.showLoading) {
        window.showLoading('Sorting...');
    }
    
    window.location.href = currentUrl.toString();
}

function updateRowSelection(checkbox) {
    const row = checkbox.closest('tr');
    if (row) {
        row.classList.toggle('selected', checkbox.checked);
    }
}

function updateSelectAllState() {
    const table = document.querySelector('.data-table');
    if (!table) return;
    
    const selectAllCheckbox = table.querySelector('input[type="checkbox"][data-select-all]');
    const rowCheckboxes = table.querySelectorAll('tbody input[type="checkbox"]');
    
    if (selectAllCheckbox && rowCheckboxes.length > 0) {
        const checkedCount = Array.from(rowCheckboxes).filter(cb => cb.checked).length;
        
        selectAllCheckbox.checked = checkedCount === rowCheckboxes.length;
        selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < rowCheckboxes.length;
    }
}

function updateBulkActions() {
    const table = document.querySelector('.data-table');
    if (!table) return;
    
    const rowCheckboxes = table.querySelectorAll('tbody input[type="checkbox"]');
    const checkedCount = Array.from(rowCheckboxes).filter(cb => cb.checked).length;
    
    const bulkActions = document.querySelector('.bulk-actions');
    if (bulkActions) {
        bulkActions.style.display = checkedCount > 0 ? 'block' : 'none';
        
        const countDisplay = bulkActions.querySelector('.selected-count');
        if (countDisplay) {
            countDisplay.textContent = `${checkedCount} selected`;
        }
    }
}

/**
 * Form Components
 */
function initializeFormComponents() {
    // Initialize form validation
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(initializeFormValidation);
    
    // Initialize file inputs
    const fileInputs = document.querySelectorAll('input[type="file"]');
    fileInputs.forEach(initializeFileInput);
    
    // Initialize character counters
    const textareas = document.querySelectorAll('textarea[data-max-length]');
    textareas.forEach(initializeCharacterCounter);
    
    // Initialize auto-resize textareas
    const autoResizeTextareas = document.querySelectorAll('textarea[data-auto-resize]');
    autoResizeTextareas.forEach(initializeAutoResize);
}

function initializeFormValidation(form) {
    form.addEventListener('submit', function(event) {
        const isValid = validateForm(form);
        if (!isValid) {
            event.preventDefault();
        }
    });
    
    // Real-time validation
    const inputs = form.querySelectorAll('input, textarea, select');
    inputs.forEach(function(input) {
        input.addEventListener('blur', function() {
            validateField(input);
        });
        
        input.addEventListener('input', function() {
            clearFieldError(input);
        });
    });
}

function validateForm(form) {
    let isValid = true;
    const inputs = form.querySelectorAll('input, textarea, select');
    
    inputs.forEach(function(input) {
        if (!validateField(input)) {
            isValid = false;
        }
    });
    
    return isValid;
}

function validateField(field) {
    const value = field.value.trim();
    const isRequired = field.hasAttribute('required');
    const type = field.type;
    const pattern = field.pattern;
    
    clearFieldError(field);
    
    // Required validation
    if (isRequired && !value) {
        showFieldError(field, 'This field is required');
        return false;
    }
    
    if (!value) return true; // Skip other validations if field is empty and not required
    
    // Email validation
    if (type === 'email' && !isValidEmail(value)) {
        showFieldError(field, 'Please enter a valid email address');
        return false;
    }
    
    // Pattern validation
    if (pattern && !new RegExp(pattern).test(value)) {
        showFieldError(field, 'Please enter a valid value');
        return false;
    }
    
    // Custom validations
    const customValidation = field.getAttribute('data-validation');
    if (customValidation) {
        const isValid = window[customValidation] ? window[customValidation](value) : true;
        if (!isValid) {
            showFieldError(field, field.getAttribute('data-validation-message') || 'Invalid value');
            return false;
        }
    }
    
    return true;
}

function showFieldError(field, message) {
    field.classList.add('error');
    
    let errorElement = field.parentNode.querySelector('.field-error');
    if (!errorElement) {
        errorElement = document.createElement('div');
        errorElement.className = 'field-error';
        field.parentNode.appendChild(errorElement);
    }
    
    errorElement.textContent = message;
    errorElement.style.display = 'block';
}

function clearFieldError(field) {
    field.classList.remove('error');
    
    const errorElement = field.parentNode.querySelector('.field-error');
    if (errorElement) {
        errorElement.style.display = 'none';
    }
}

function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

function initializeFileInput(input) {
    // Opt-out: custom dropzones (e.g. the export-template uploader) style the
    // file control themselves and don't want the generic "Choose File / No file
    // chosen" wrapper injected next to their own UI.
    if (input.dataset.skipEnhance !== undefined || input.closest('.exp-dropzone')) {
        return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'file-input-wrapper';
    
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary';
    button.textContent = 'Choose File';
    
    const filename = document.createElement('span');
    filename.className = 'filename';
    filename.textContent = 'No file chosen';
    
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(button);
    wrapper.appendChild(filename);
    wrapper.appendChild(input);
    
    input.style.display = 'none';
    
    button.addEventListener('click', () => input.click());
    
    input.addEventListener('change', function() {
        if (this.files.length > 0) {
            filename.textContent = this.files[0].name;
        } else {
            filename.textContent = 'No file chosen';
        }
    });
}

function initializeCharacterCounter(textarea) {
    const maxLength = parseInt(textarea.getAttribute('data-max-length'));
    
    const counter = document.createElement('div');
    counter.className = 'character-counter';
    textarea.parentNode.appendChild(counter);
    
    function updateCounter() {
        const remaining = maxLength - textarea.value.length;
        counter.textContent = `${remaining} characters remaining`;
        counter.classList.toggle('warning', remaining < 50);
        counter.classList.toggle('error', remaining < 0);
    }
    
    textarea.addEventListener('input', updateCounter);
    updateCounter();
}

function initializeAutoResize(textarea) {
    function resize() {
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
    }
    
    textarea.addEventListener('input', resize);
    resize();
}

/**
 * Search Components
 */
function initializeSearchComponents() {
    const searchInputs = document.querySelectorAll('.search-input');
    
    searchInputs.forEach(function(input) {
        let searchTimeout;
        
        input.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                handleSearch(input);
            }, 300);
        });
        
        // Clear search
        const clearButton = input.parentNode.querySelector('.search-clear');
        if (clearButton) {
            clearButton.addEventListener('click', function() {
                input.value = '';
                input.focus();
                handleSearch(input);
            });
        }
    });
    
    // Advanced search toggle
    const advancedToggle = document.querySelector('.advanced-search-toggle');
    const advancedPanel = document.querySelector('.advanced-search-panel');
    
    if (advancedToggle && advancedPanel) {
        advancedToggle.addEventListener('click', function() {
            const isExpanded = advancedPanel.style.display !== 'none';
            advancedPanel.style.display = isExpanded ? 'none' : 'block';
            this.setAttribute('aria-expanded', !isExpanded);
        });
    }
}

function handleSearch(input) {
    const query = input.value.trim();
    const form = input.closest('form');
    
    if (form) {
        // Update URL with search parameters
        const formData = new FormData(form);
        const params = new URLSearchParams();
        
        for (const [key, value] of formData.entries()) {
            if (value) {
                params.append(key, value);
            }
        }
        
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        
        if (window.showLoading) {
            window.showLoading('Searching...');
        }
        
        window.location.href = newUrl;
    }
}

/**
 * Calendar Components
 */
function initializeCalendarComponents() {
    const calendarViews = document.querySelectorAll('.calendar-view');
    
    calendarViews.forEach(function(calendar) {
        // View switcher
        const viewButtons = calendar.querySelectorAll('.view-button');
        viewButtons.forEach(function(button) {
            button.addEventListener('click', function() {
                const view = this.getAttribute('data-view');
                switchCalendarView(calendar, view);
                
                // Update active state
                viewButtons.forEach(btn => btn.classList.remove('active'));
                this.classList.add('active');
            });
        });
        
        // Navigation
        const prevButton = calendar.querySelector('.calendar-prev');
        const nextButton = calendar.querySelector('.calendar-next');
        
        if (prevButton) {
            prevButton.addEventListener('click', function() {
                navigateCalendar(calendar, -1);
            });
        }
        
        if (nextButton) {
            nextButton.addEventListener('click', function() {
                navigateCalendar(calendar, 1);
            });
        }
        
        // Event creation
        const calendarCells = calendar.querySelectorAll('.calendar-cell');
        calendarCells.forEach(function(cell) {
            cell.addEventListener('click', function() {
                const date = this.getAttribute('data-date');
                if (date) {
                    handleCalendarCellClick(date);
                }
            });
        });
    });
}

function switchCalendarView(calendar, view) {
    // This would switch between month, week, and day views
    calendar.setAttribute('data-view', view);
    
    // Update URL
    const url = new URL(window.location);
    url.searchParams.set('view', view);
    window.history.pushState({}, '', url);
    
    // Reload calendar data
    if (window.showLoading) {
        window.showLoading('Loading calendar...');
    }
    
    // This would typically make an AJAX request to get new data
    setTimeout(() => {
        if (window.hideLoading) {
            window.hideLoading();
        }
    }, 1000);
}

function navigateCalendar(calendar, direction) {
    const currentDate = calendar.getAttribute('data-current-date') || new Date().toISOString().split('T')[0];
    const view = calendar.getAttribute('data-view') || 'month';
    
    // Calculate new date based on view and direction
    const date = new Date(currentDate);
    
    if (view === 'month') {
        date.setMonth(date.getMonth() + direction);
    } else if (view === 'week') {
        date.setDate(date.getDate() + (direction * 7));
    } else if (view === 'day') {
        date.setDate(date.getDate() + direction);
    }
    
    // Update URL and reload
    const url = new URL(window.location);
    url.searchParams.set('date', date.toISOString().split('T')[0]);
    
    if (window.showLoading) {
        window.showLoading('Loading calendar...');
    }
    
    window.location.href = url.toString();
}

function handleCalendarCellClick(date) {
    // This would typically open a modal to create a new event
    const modal = document.getElementById('create-event-modal');
    if (modal) {
        const dateInput = modal.querySelector('input[name="start_date"]');
        if (dateInput) {
            dateInput.value = date;
        }
        showModal(modal);
    }
}

/**
 * Utility Functions
 */
function debounce(func, wait, immediate) {
    let timeout;
    return function executedFunction() {
        const context = this;
        const args = arguments;
        
        const later = function() {
            timeout = null;
            if (!immediate) func.apply(context, args);
        };
        
        const callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        
        if (callNow) func.apply(context, args);
    };
}

// Export functions for global use
window.ComponentManager = {
    showModal,
    hideModal,
    handleTableSort,
    updateBulkActions,
    validateForm,
    handleSearch,
    switchCalendarView,
    navigateCalendar
};

// Auto-initialize if DOM is already loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeComponents);
} else {
    initializeComponents();
}

// Event Card Status Dropdown Functionality
function toggleStatusDropdown(eventId) {
    const dropdown = document.getElementById(`status-dropdown-${eventId}`);
    const button = dropdown.previousElementSibling;
    
    // Close all other dropdowns
    document.querySelectorAll('.status-dropdown-menu.show').forEach(menu => {
        if (menu.id !== `status-dropdown-${eventId}`) {
            menu.classList.remove('show');
            menu.previousElementSibling.classList.remove('open');
        }
    });
    
    // Toggle current dropdown
    dropdown.classList.toggle('show');
    button.classList.toggle('open');
}

// Update event status
async function updateEventStatus(eventId, newStatus) {
    const dropdown = document.getElementById(`status-dropdown-${eventId}`);
    const button = dropdown.previousElementSibling;
    
    try {
        // Show loading state
        button.disabled = true;
        button.innerHTML = `
            <span>Updating...</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z"/>
                <path d="M12 6V12L16 14"/>
            </svg>
        `;
        
        // Make API call to update status
        const response = await fetch(`/events/${eventId}/update-status/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ status: newStatus })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Update button appearance
            button.className = `status-button status-${newStatus}`;
            button.innerHTML = `
                ${data.status_display}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="6,9 12,15 18,9"/>
                </svg>
            `;
            
            // Show success message
            showNotification('Status updated successfully', 'success');
        } else {
            throw new Error('Failed to update status');
        }
    } catch (error) {
        console.error('Error updating status:', error);
        showNotification('Failed to update status', 'error');
        
        // Reset button
        button.innerHTML = `
            ${button.textContent.split('Updating...')[0]}
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="6,9 12,15 18,9"/>
            </svg>
        `;
    } finally {
        button.disabled = false;
        dropdown.classList.remove('show');
        button.classList.remove('open');
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', function(event) {
    if (!event.target.closest('.status-dropdown')) {
        document.querySelectorAll('.status-dropdown-menu.show').forEach(menu => {
            menu.classList.remove('show');
            menu.previousElementSibling.classList.remove('open');
        });
    }
});

// Show notification helper
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-message">${message}</span>
            <button class="notification-close" onclick="this.parentElement.parentElement.remove()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
            </button>
        </div>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 3000);
}

// Get CSRF token helper
function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }
    return '';
}

// Show notification helper
function showNotification(message, type) {
    type = type || 'info';
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-message">${message}</span>
            <button class="notification-close" onclick="this.parentElement.parentElement.remove()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        </div>
    `;
    
    // Add to page
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            max-width: 400px;
        `;
        document.body.appendChild(container);
    }
    
    container.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}