/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Main JavaScript for HillDesk
 */

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

/**
 * Initialize the application
 */
function initializeApp() {
    initializeSidebar();
    initializeMobileMenu();
    initializeNavigationKeyboard();
    initializeActiveStates();
    initializeMessages();
    initializeLoadingStates();
    initializeAccessibility();
    initializeFormEnhancements();
    initializeComingSoon();
    // Initialize theme system
    if (typeof initializeTheme === 'function') {
        initializeTheme();
    }

    // Initialize components
    if (typeof initializeComponents === 'function') {
        initializeComponents();
    }

    console.log('HillDesk application initialized');
}


/**
 * Sidebar functionality with toggle button expand/collapse
 * State persists across page navigations via localStorage
 */
function initializeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const toggleBtn = document.getElementById('sidebar-toggle-btn');
    const STORAGE_KEY = 'hilldesk-sidebar-collapsed';

    if (!sidebar) return;

    // Helper function to expand sidebar
    function expandSidebar(save = true) {
        sidebar.classList.remove('collapsed');
        document.body.classList.remove('sidebar-collapsed');
        document.documentElement.removeAttribute('data-sidebar-collapsed');
        if (toggleBtn) {
            toggleBtn.setAttribute('aria-label', 'Collapse sidebar');
            toggleBtn.setAttribute('title', 'Collapse sidebar');
        }
        if (save) {
            localStorage.setItem(STORAGE_KEY, 'false');
        }
        announceToScreenReader('Sidebar expanded');
    }

    // Helper function to collapse sidebar
    function collapseSidebar(save = true) {
        sidebar.classList.add('collapsed');
        document.body.classList.add('sidebar-collapsed');
        document.documentElement.setAttribute('data-sidebar-collapsed', 'true');
        if (toggleBtn) {
            toggleBtn.setAttribute('aria-label', 'Expand sidebar');
            toggleBtn.setAttribute('title', 'Expand sidebar');
        }
        if (save) {
            localStorage.setItem(STORAGE_KEY, 'true');
        }
        announceToScreenReader('Sidebar collapsed');
    }

    // Restore sidebar state from localStorage (default: expanded).
    // The user's choice is honored on every page, including the calendar.
    const savedState = localStorage.getItem(STORAGE_KEY);
    if (savedState === 'true') {
        collapseSidebar(false); // Explicitly saved as collapsed, restore
    } else {
        expandSidebar(false); // Default to expanded
    }

    // Toggle button click handler (brand link) - ONLY way to change collapsed state
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const isCollapsed = sidebar.classList.contains('collapsed');

            if (isCollapsed) {
                expandSidebar();
            } else {
                collapseSidebar();
            }
        });
    }

    // Clicking on sidebar does NOT change collapsed state anymore
    // Only the toggle button controls expand/collapse

    // Handle mobile sidebar overlay
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', function() {
            sidebar.classList.remove('mobile-open');
            sidebarOverlay.classList.remove('active');
            document.body.style.overflow = '';
        });
    }

    // Enhanced mobile sidebar toggle (for mobile menu button if needed)
    function toggleMobileSidebar() {
        if (window.innerWidth < 768) {
            const isOpen = sidebar.classList.contains('mobile-open');

            if (isOpen) {
                sidebar.classList.remove('mobile-open');
                if (sidebarOverlay) sidebarOverlay.classList.remove('active');
                document.body.style.overflow = '';
            } else {
                sidebar.classList.add('mobile-open');
                if (sidebarOverlay) sidebarOverlay.classList.add('active');
                document.body.style.overflow = 'hidden';
            }

            // Announce mobile sidebar state
            announceToScreenReader(isOpen ? 'Mobile sidebar closed' : 'Mobile sidebar opened');
        }
    }
    
    // Make mobile toggle available globally if needed
    window.toggleMobileSidebar = toggleMobileSidebar;
    
    // Handle window resize
    window.addEventListener('resize', debounce(function() {
        if (window.innerWidth >= 768) {
            // Close mobile sidebar on desktop
            sidebar.classList.remove('mobile-open');
            if (sidebarOverlay) sidebarOverlay.classList.remove('active');
            document.body.style.overflow = '';
            // Body margin stays static - no adjustment needed
        }
    }, 250));
}

/**
 * Mobile menu functionality
 */
function initializeMobileMenu() {
    const mobileToggle = document.querySelector('.mobile-menu-toggle');
    const navbar = document.querySelector('.navbar-nav');
    
    if (!mobileToggle || !navbar) return;
    
    mobileToggle.addEventListener('click', function() {
        const isExpanded = this.getAttribute('aria-expanded') === 'true';
        
        // Toggle aria-expanded
        this.setAttribute('aria-expanded', !isExpanded);
        
        // Toggle menu visibility
        navbar.classList.toggle('show');
        
        // Toggle hamburger animation
        this.classList.toggle('active');
        
        // Prevent body scroll when menu is open on mobile
        if (window.innerWidth < 768) {
            document.body.style.overflow = navbar.classList.contains('show') ? 'hidden' : '';
        }
    });
    
    // Close mobile menu when clicking outside
    document.addEventListener('click', function(event) {
        if (!mobileToggle.contains(event.target) && !navbar.contains(event.target)) {
            navbar.classList.remove('show');
            mobileToggle.setAttribute('aria-expanded', 'false');
            mobileToggle.classList.remove('active');
            document.body.style.overflow = '';
        }
    });
    
    // Close mobile menu on window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth >= 768) {
            navbar.classList.remove('show');
            mobileToggle.setAttribute('aria-expanded', 'false');
            mobileToggle.classList.remove('active');
            document.body.style.overflow = '';
        }
    });
}

/**
 * Enhanced navigation keyboard support
 */
function initializeNavigationKeyboard() {
    const navItems = document.querySelectorAll('.nav-item');
    
    navItems.forEach((item, index) => {
        item.addEventListener('keydown', function(event) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                const nextItem = navItems[index + 1] || navItems[0];
                nextItem.focus();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                const prevItem = navItems[index - 1] || navItems[navItems.length - 1];
                prevItem.focus();
            }
        });
    });
}

/**
 * Enhanced active state management
 */
function initializeActiveStates() {
    // Update active states based on current page
    const currentPath = window.location.pathname;
    const navItems = document.querySelectorAll('.nav-item');
    
    // Remove all active states first
    navItems.forEach(item => {
        item.classList.remove('active');
        item.setAttribute('aria-current', 'false');
    });
    
    // Find the best matching nav item
    let bestMatch = null;
    let bestMatchLength = 0;
    
    navItems.forEach(item => {
        const href = item.getAttribute('href');
        if (href && href !== '#' && currentPath.startsWith(href)) {
            // Prefer longer matches (more specific routes)
            if (href.length > bestMatchLength) {
                bestMatch = item;
                bestMatchLength = href.length;
            }
        }
    });
    
    // If no specific match found, check for dashboard as default
    if (!bestMatch && (currentPath === '/' || currentPath === '/dashboard/' || currentPath.endsWith('/dashboard'))) {
        bestMatch = document.querySelector('.nav-item[href*="dashboard"]');
    }
    
    // Apply active state to best match
    if (bestMatch) {
        bestMatch.classList.add('active');
        bestMatch.setAttribute('aria-current', 'page');
        announceToScreenReader(`Current page: ${bestMatch.textContent.trim()}`);
    }
}

/**
 * Message handling functionality
 */
function initializeMessages() {
    const messages = document.querySelectorAll('.message');
    
    messages.forEach(function(message) {
        const closeButton = message.querySelector('.message-close');
        
        if (closeButton) {
            closeButton.addEventListener('click', function() {
                message.style.opacity = '0';
                message.style.transform = 'translateY(-10px)';
                
                setTimeout(function() {
                    message.remove();
                }, 300);
            });
        }
        
        // Auto-dismiss success messages after 5 seconds
        if (message.classList.contains('message-success')) {
            setTimeout(function() {
                if (message.parentNode) {
                    message.style.opacity = '0';
                    message.style.transform = 'translateY(-10px)';
                    
                    setTimeout(function() {
                        message.remove();
                    }, 300);
                }
            }, 5000);
        }
    });
}

/**
 * Loading states functionality
 */
function initializeLoadingStates() {
    const loadingOverlay = document.getElementById('loading-overlay');
    
    // Show loading overlay
    window.showLoading = function(message = 'Loading...') {
        if (loadingOverlay) {
            const loadingText = loadingOverlay.querySelector('.loading-text');
            if (loadingText) {
                loadingText.textContent = message;
            }
            loadingOverlay.classList.add('show');
            loadingOverlay.setAttribute('aria-hidden', 'false');
        }
    };
    
    // Hide loading overlay
    window.hideLoading = function() {
        if (loadingOverlay) {
            loadingOverlay.classList.remove('show');
            loadingOverlay.setAttribute('aria-hidden', 'true');
        }
    };
    
    // Show loading on form submissions
    const forms = document.querySelectorAll('form');
    forms.forEach(function(form) {
        form.addEventListener('submit', function() {
            showLoading('Saving...');
        });
    });
    
    // Show loading on navigation links (except external links)
    const navLinks = document.querySelectorAll('a[href^="/"], a[href^="' + window.location.origin + '"]');
    navLinks.forEach(function(link) {
        link.addEventListener('click', function(event) {
            // Don't show loading for hash links or if prevented
            if (this.getAttribute('href').startsWith('#') || event.defaultPrevented) {
                return;
            }
            
            showLoading('Loading page...');
        });
    });
}

/**
 * Accessibility enhancements
 */
function initializeAccessibility() {
    // Add focus-visible polyfill behavior
    document.addEventListener('keydown', function() {
        document.body.classList.add('using-keyboard');
    });
    
    document.addEventListener('mousedown', function() {
        document.body.classList.remove('using-keyboard');
    });
    
    // Announce page changes to screen readers
    const pageTitle = document.title;
    if (pageTitle) {
        announceToScreenReader(`Page loaded: ${pageTitle}`);
    }
    
    // Skip link functionality
    const skipLink = document.querySelector('.skip-link');
    if (skipLink) {
        skipLink.addEventListener('click', function(event) {
            event.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.focus();
                target.scrollIntoView();
            }
        });
    }
    
    // Improve table accessibility
    const tables = document.querySelectorAll('table');
    tables.forEach(function(table) {
        if (!table.querySelector('caption')) {
            const caption = document.createElement('caption');
            caption.textContent = 'Data table';
            caption.className = 'sr-only';
            table.insertBefore(caption, table.firstChild);
        }
    });
}

/**
 * Form enhancements
 */
function initializeFormEnhancements() {
    // Add floating labels
    const formControls = document.querySelectorAll('.form-control');
    formControls.forEach(function(control) {
        const label = document.querySelector(`label[for="${control.id}"]`);
        if (label && control.value) {
            control.classList.add('has-value');
        }
        
        control.addEventListener('input', function() {
            if (this.value) {
                this.classList.add('has-value');
            } else {
                this.classList.remove('has-value');
            }
        });
        
        control.addEventListener('focus', function() {
            this.classList.add('focused');
        });
        
        control.addEventListener('blur', function() {
            this.classList.remove('focused');
        });
    });
    
    // Form validation feedback
    const forms = document.querySelectorAll('form');
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            // Skip validation for forms with novalidate attribute
            if (form.hasAttribute('novalidate')) {
                return;
            }
            
            const invalidFields = form.querySelectorAll(':invalid');
            if (invalidFields.length > 0) {
                event.preventDefault();
                invalidFields[0].focus();
                announceToScreenReader('Please correct the errors in the form');
            }
        });
    });
}

/**
 * "Coming Soon" toast for placeholder nav items (Contacts, Analytics)
 */
function initializeComingSoon() {
    document.querySelectorAll('.nav-coming-soon').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            // Remove any existing toast
            const old = document.getElementById('coming-soon-toast');
            if (old) old.remove();
            // Create toast
            const toast = document.createElement('div');
            toast.id = 'coming-soon-toast';
            toast.className = 'coming-soon-toast';
            toast.textContent = 'Coming soon';
            document.body.appendChild(toast);
            // Trigger animation
            requestAnimationFrame(() => toast.classList.add('visible'));
            // Auto-remove
            setTimeout(() => {
                toast.classList.remove('visible');
                setTimeout(() => toast.remove(), 300);
            }, 2000);
        });
    });
}

/**
 * Utility function to announce messages to screen readers
 */
function announceToScreenReader(message) {
    const announcement = document.createElement('div');
    announcement.setAttribute('aria-live', 'polite');
    announcement.setAttribute('aria-atomic', 'true');
    announcement.className = 'sr-only';
    announcement.textContent = message;
    
    document.body.appendChild(announcement);
    
    setTimeout(function() {
        document.body.removeChild(announcement);
    }, 1000);
}

/**
 * Utility function to debounce function calls
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

/**
 * Utility function to throttle function calls
 */
function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * AJAX utility functions
 */
window.ajax = {
    get: function(url, options = {}) {
        return fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                ...options.headers
            },
            ...options
        }).then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
    },
    
    post: function(url, data, options = {}) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken,
                ...options.headers
            },
            body: JSON.stringify(data),
            ...options
        }).then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
    },
    
    put: function(url, data, options = {}) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        
        return fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken,
                ...options.headers
            },
            body: JSON.stringify(data),
            ...options
        }).then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
    },
    
    delete: function(url, options = {}) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        
        return fetch(url, {
            method: 'DELETE',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': csrfToken,
                ...options.headers
            },
            ...options
        }).then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
    }
};

/**
 * Show toast notification
 */
window.showToast = function(message, type = 'info', duration = 5000) {
    const toast = document.createElement('div');
    toast.className = `message message-${type}`;
    toast.innerHTML = `
        <div class="message-content">
            <svg class="message-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                ${getMessageIcon(type)}
            </svg>
            <span class="message-text">${message}</span>
        </div>
        <button class="message-close" aria-label="Close message">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2"/>
                <line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2"/>
            </svg>
        </button>
    `;
    
    // Add to messages container or create one
    let messagesContainer = document.querySelector('.messages');
    if (!messagesContainer) {
        messagesContainer = document.createElement('div');
        messagesContainer.className = 'messages';
        messagesContainer.setAttribute('role', 'alert');
        messagesContainer.setAttribute('aria-live', 'polite');
        
        const mainContent = document.querySelector('.main-content');
        if (mainContent) {
            mainContent.insertBefore(messagesContainer, mainContent.firstChild);
        }
    }
    
    messagesContainer.appendChild(toast);
    
    // Add close functionality
    const closeButton = toast.querySelector('.message-close');
    closeButton.addEventListener('click', function() {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-10px)';
        setTimeout(() => toast.remove(), 300);
    });
    
    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.opacity = '0';
                toast.style.transform = 'translateY(-10px)';
                setTimeout(() => toast.remove(), 300);
            }
        }, duration);
    }
};

/**
 * Get SVG icon for message type
 */
function getMessageIcon(type) {
    const icons = {
        success: '<path d="M22 11.08V12C21.9988 14.1564 21.3005 16.2547 20.0093 17.9818C18.7182 19.7088 16.9033 20.9725 14.8354 21.5839C12.7674 22.1953 10.5573 22.1219 8.53447 21.3746C6.51168 20.6273 4.78465 19.2461 3.61096 17.4371C2.43727 15.628 1.87979 13.4905 2.02168 11.3363C2.16356 9.18203 2.99721 7.13214 4.39828 5.49883C5.79935 3.86553 7.69279 2.72636 9.79619 2.24223C11.8996 1.75809 14.1003 1.95185 16.07 2.79999" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><polyline points="22,4 12,14.01 9,11.01" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
        error: '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><line x1="15" y1="9" x2="9" y2="15" stroke="currentColor" stroke-width="2"/><line x1="9" y1="9" x2="15" y2="15" stroke="currentColor" stroke-width="2"/>',
        warning: '<path d="M10.29 3.86L1.82 18C1.64571 18.3024 1.55974 18.6453 1.57361 18.9928C1.58747 19.3403 1.70078 19.6763 1.90313 19.9644C2.10549 20.2525 2.38746 20.4804 2.71361 20.6219C3.03976 20.7634 3.39516 20.8131 3.74 20.77H20.26C20.6048 20.8131 20.9602 20.7634 21.2864 20.6219C21.6125 20.4804 21.8945 20.2525 22.0969 19.9644C22.2992 19.6763 22.4125 19.3403 22.4264 18.9928C22.4403 18.6453 22.3543 18.3024 22.18 18L13.71 3.86C13.5317 3.56611 13.2807 3.32312 12.9812 3.15448C12.6817 2.98585 12.3438 2.89725 12 2.89725C11.6562 2.89725 11.3183 2.98585 11.0188 3.15448C10.7193 3.32312 10.4683 3.56611 10.29 3.86V3.86Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" stroke-width="2"/><line x1="12" y1="17" x2="12.01" y2="17" stroke="currentColor" stroke-width="2"/>',
        info: '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><path d="M12 16V12" stroke="currentColor" stroke-width="2"/><path d="M12 8H12.01" stroke="currentColor" stroke-width="2"/>'
    };
    
    return icons[type] || icons.info;
}

// Export functions for use in other scripts
window.CapitolSchedule = {
    showLoading: window.showLoading,
    hideLoading: window.hideLoading,
    showToast: window.showToast,
    announceToScreenReader: window.announceToScreenReader,
    debounce: debounce,
    throttle: throttle,
    ajax: ajax
};/**
 * 
Show message utility function
 */
window.showMessage = function(message, type = 'info') {
    showToast(message, type);
};