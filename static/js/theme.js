/* SPDX-License-Identifier: Apache-2.0 */
/**
 * Theme System for HillDesk
 */

// Theme management
const ThemeManager = {
    // Default settings
    defaults: {
        theme: 'light',
        accentColor: 'blue'
    },
    
    // Storage keys
    storageKeys: {
        theme: 'capitol-schedule-theme',
        accentColor: 'capitol-schedule-accent'
    },
    
    // Initialize theme system
    init() {
        this.loadSavedPreferences();
        this.createThemeControls();
        this.bindEvents();
        this.detectSystemPreferences();
        
        console.log('Theme system initialized');
    },
    
    // Load saved preferences from localStorage
    loadSavedPreferences() {
        const savedTheme = localStorage.getItem(this.storageKeys.theme);
        const savedAccent = localStorage.getItem(this.storageKeys.accentColor);
        
        if (savedTheme) {
            this.setTheme(savedTheme, false);
        }
        
        if (savedAccent) {
            this.setAccentColor(savedAccent, false);
        }
    },
    
    // Create theme control elements
    createThemeControls() {
        // Only create controls if user is authenticated
        if (!document.querySelector('.user-menu')) return;
        
        // Check if controls already exist to prevent duplicates
        if (document.querySelector('.theme-controls')) return;
        
        // Find or create settings area
        let settingsArea = document.querySelector('.theme-controls');
        if (!settingsArea) {
            settingsArea = this.createSettingsArea();
        }
        
        if (!settingsArea) return; // Exit if we couldn't create the settings area
        
        // Create theme toggle
        const themeToggle = this.createThemeToggle();
        settingsArea.appendChild(themeToggle);
        
        // Create accent color selector
        const accentSelector = this.createAccentSelector();
        settingsArea.appendChild(accentSelector);
    },
    
    // Create settings area in user dropdown
    createSettingsArea() {
        const userDropdown = document.querySelector('.user-dropdown');
        if (!userDropdown) return null;
        
        // Add divider before settings
        const divider = document.createElement('div');
        divider.className = 'dropdown-divider';
        userDropdown.appendChild(divider);
        
        // Create settings area
        const settingsArea = document.createElement('div');
        settingsArea.className = 'theme-controls';
        settingsArea.style.padding = '0.75rem 1rem';
        userDropdown.appendChild(settingsArea);
        
        return settingsArea;
    },
    
    // Create theme toggle button
    createThemeToggle() {
        const container = document.createElement('div');
        container.style.marginBottom = '0.75rem';
        
        const label = document.createElement('label');
        label.textContent = 'Theme';
        label.style.display = 'block';
        label.style.fontSize = 'var(--font-size-xs)';
        label.style.fontWeight = '600';
        label.style.textTransform = 'uppercase';
        label.style.letterSpacing = '0.025em';
        label.style.color = 'var(--text-secondary)';
        label.style.marginBottom = '0.5rem';
        
        const toggle = document.createElement('button');
        toggle.className = 'theme-toggle';
        toggle.setAttribute('aria-label', 'Toggle theme');
        toggle.style.width = '100%';
        toggle.style.justifyContent = 'space-between';
        toggle.style.cursor = 'pointer';
        
        // Add direct click handler to ensure it works
        toggle.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            this.toggleTheme();
        });
        
        this.updateThemeToggle(toggle);
        
        container.appendChild(label);
        container.appendChild(toggle);
        
        return container;
    },
    
    // Create accent color selector
    createAccentSelector() {
        const container = document.createElement('div');
        
        const label = document.createElement('label');
        label.textContent = 'Accent Color';
        label.style.display = 'block';
        label.style.fontSize = 'var(--font-size-xs)';
        label.style.fontWeight = '600';
        label.style.textTransform = 'uppercase';
        label.style.letterSpacing = '0.025em';
        label.style.color = 'var(--text-secondary)';
        label.style.marginBottom = '0.5rem';
        
        const selector = document.createElement('div');
        selector.className = 'accent-selector';
        selector.style.justifyContent = 'space-between';
        
        // Blue option
        const blueOption = this.createAccentOption('blue', 'Blue');
        selector.appendChild(blueOption);
        
        // Red option
        const redOption = this.createAccentOption('red', 'Red');
        selector.appendChild(redOption);
        
        container.appendChild(label);
        container.appendChild(selector);
        
        return container;
    },
    
    // Create individual accent color option
    createAccentOption(color, label) {
        const container = document.createElement('div');
        container.style.display = 'flex';
        container.style.alignItems = 'center';
        container.style.gap = '0.5rem';
        container.style.cursor = 'pointer';
        
        const option = document.createElement('button');
        option.className = `accent-option ${color}`;
        option.setAttribute('data-accent', color);
        option.setAttribute('aria-label', `Set accent color to ${label}`);
        option.style.flexShrink = '0';
        option.style.cursor = 'pointer';
        
        const labelElement = document.createElement('span');
        labelElement.textContent = label;
        labelElement.style.fontSize = 'var(--font-size-sm)';
        labelElement.style.color = 'var(--text-primary)';
        labelElement.style.cursor = 'pointer';
        
        // Update active state
        const currentAccent = this.getCurrentAccentColor();
        if (color === currentAccent) {
            option.classList.add('active');
        }
        
        // Make the entire container clickable
        container.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            this.setAccentColor(color);
        });
        
        // Also add click handler to the button itself as backup
        option.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            this.setAccentColor(color);
        });
        
        container.appendChild(option);
        container.appendChild(labelElement);
        
        return container;
    },
    
    // Bind event listeners
    bindEvents() {
        // Theme toggle - use more specific event delegation
        document.addEventListener('click', (event) => {
            const themeToggle = event.target.closest('.theme-toggle');
            if (themeToggle) {
                event.preventDefault();
                event.stopPropagation();
                this.toggleTheme();
                return;
            }
        });
        
        // Accent color selection - now handled in createAccentOption
        
        // Listen for system theme changes
        if (window.matchMedia) {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            mediaQuery.addEventListener('change', () => {
                if (!localStorage.getItem(this.storageKeys.theme)) {
                    this.detectSystemPreferences();
                }
            });
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (event) => {
            // Ctrl/Cmd + Shift + T to toggle theme
            if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'T') {
                event.preventDefault();
                this.toggleTheme();
            }
        });
    },
    
    // Detect system preferences
    detectSystemPreferences() {
        // Only apply system preferences if user hasn't set a preference
        if (localStorage.getItem(this.storageKeys.theme)) return;
        
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            this.setTheme('dark', false);
        } else {
            this.setTheme('light', false);
        }
    },
    
    // Get current theme
    getCurrentTheme() {
        return document.documentElement.getAttribute('data-theme') || this.defaults.theme;
    },
    
    // Get current accent color
    getCurrentAccentColor() {
        return document.documentElement.getAttribute('data-accent') || this.defaults.accentColor;
    },
    
    // Set theme
    setTheme(theme, save = true) {
        document.documentElement.setAttribute('data-theme', theme);
        
        if (save) {
            localStorage.setItem(this.storageKeys.theme, theme);
            this.syncWithServer({ theme });
        }
        
        // Update theme toggle
        const themeToggle = document.querySelector('.theme-toggle');
        if (themeToggle) {
            this.updateThemeToggle(themeToggle);
        }
        
        // Announce to screen readers
        if (window.CapitolSchedule && window.CapitolSchedule.announceToScreenReader) {
            window.CapitolSchedule.announceToScreenReader(`Theme changed to ${theme} mode`);
        }
        
        // Dispatch custom event
        document.dispatchEvent(new CustomEvent('themeChanged', {
            detail: { theme, accentColor: this.getCurrentAccentColor() }
        }));
    },
    
    // Set accent color
    setAccentColor(color, save = true) {
        document.documentElement.setAttribute('data-accent', color);
        
        if (save) {
            localStorage.setItem(this.storageKeys.accentColor, color);
            this.syncWithServer({ accentColor: color });
        }
        
        // Update accent options
        const accentOptions = document.querySelectorAll('.accent-option');
        accentOptions.forEach(option => {
            option.classList.toggle('active', option.getAttribute('data-accent') === color);
        });
        
        // Announce to screen readers
        if (window.CapitolSchedule && window.CapitolSchedule.announceToScreenReader) {
            const colorName = color === 'blue' ? 'Blue' : 'Red';
            window.CapitolSchedule.announceToScreenReader(`Accent color changed to ${colorName}`);
        }
        
        // Dispatch custom event
        document.dispatchEvent(new CustomEvent('accentColorChanged', {
            detail: { theme: this.getCurrentTheme(), accentColor: color }
        }));
    },
    
    // Toggle theme
    toggleTheme() {
        const currentTheme = this.getCurrentTheme();
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        this.setTheme(newTheme);
    },
    
    // Update theme toggle button
    updateThemeToggle(toggle) {
        const currentTheme = this.getCurrentTheme();
        const isDark = currentTheme === 'dark';
        
        toggle.innerHTML = `
            <span style="display: flex; align-items: center; gap: 0.5rem;">
                <svg class="theme-toggle-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    ${isDark ? this.getMoonIcon() : this.getSunIcon()}
                </svg>
                <span>${isDark ? 'Dark' : 'Light'}</span>
            </span>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M7 10L12 15L17 10" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
            </svg>
        `;
        
        toggle.setAttribute('aria-label', `Switch to ${isDark ? 'light' : 'dark'} theme`);
    },
    
    // Get sun icon SVG
    getSunIcon() {
        return `
            <circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="2"/>
            <line x1="12" y1="1" x2="12" y2="3" stroke="currentColor" stroke-width="2"/>
            <line x1="12" y1="21" x2="12" y2="23" stroke="currentColor" stroke-width="2"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" stroke="currentColor" stroke-width="2"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" stroke="currentColor" stroke-width="2"/>
            <line x1="1" y1="12" x2="3" y2="12" stroke="currentColor" stroke-width="2"/>
            <line x1="21" y1="12" x2="23" y2="12" stroke="currentColor" stroke-width="2"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" stroke="currentColor" stroke-width="2"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" stroke="currentColor" stroke-width="2"/>
        `;
    },
    
    // Get moon icon SVG
    getMoonIcon() {
        return `
            <path d="M21 12.79C20.8427 14.4922 20.2039 16.1144 19.1583 17.4668C18.1127 18.8192 16.7035 19.8458 15.0957 20.4265C13.4879 21.0073 11.7473 21.1181 10.0713 20.746C8.39524 20.3739 6.84947 19.5345 5.62596 18.3109C4.40245 17.0874 3.56305 15.5417 3.19097 13.8656C2.81889 12.1896 2.9297 10.449 3.51042 8.84124C4.09114 7.23345 5.11775 5.82423 6.47017 4.77866C7.82259 3.73308 9.44485 3.09434 11.147 2.93695C9.35969 4.33437 8.25989 6.41663 8.25989 8.74989C8.25989 11.0831 9.35969 13.1654 11.147 14.5628C12.9342 15.9602 15.2166 16.4904 17.4999 15.9999C19.7831 15.5094 21.8654 14.0096 23.2628 12.2224C22.6456 14.1692 21.5458 15.9544 20.0542 17.4460C18.5627 18.9375 16.7775 20.0373 14.8307 20.6545C12.8839 21.2717 10.8496 21.3823 8.84663 20.9744C6.84364 20.5665 5.00125 19.6555 3.51042 18.3265" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
        `;
    },
    
    // Sync preferences with server
    syncWithServer(preferences) {
        if (!window.CapitolSchedule || !window.CapitolSchedule.ajax) return;
        
        // Only sync if user is authenticated
        if (!document.querySelector('.user-menu')) return;
        
        const url = '/auth/preferences/';
        
        window.CapitolSchedule.ajax.post(url, preferences)
            .catch(error => {
                console.warn('Failed to sync theme preferences with server:', error);
            });
    },
    
    // Reset to defaults
    reset() {
        localStorage.removeItem(this.storageKeys.theme);
        localStorage.removeItem(this.storageKeys.accentColor);
        
        this.setTheme(this.defaults.theme, false);
        this.setAccentColor(this.defaults.accentColor, false);
        
        this.detectSystemPreferences();
    },
    
    // Get current preferences
    getPreferences() {
        return {
            theme: this.getCurrentTheme(),
            accentColor: this.getCurrentAccentColor()
        };
    },
    
    // Apply preferences
    applyPreferences(preferences) {
        if (preferences.theme) {
            this.setTheme(preferences.theme, false);
        }
        
        if (preferences.accentColor) {
            this.setAccentColor(preferences.accentColor, false);
        }
    }
};

// Initialize theme system when DOM is loaded
function initializeTheme() {
    ThemeManager.init();
}

// Export for use in other scripts
window.ThemeManager = ThemeManager;

// Auto-initialize if DOM is already loaded
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeTheme);
} else {
    initializeTheme();
}