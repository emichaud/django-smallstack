/**
 * Theme JavaScript - SmallStack
 *
 * Handles:
 * - Dark/Light mode toggle with localStorage persistence
 * - Sidebar collapse behavior
 * - User dropdown menu
 * - Message dismissal
 */

(function () {
    'use strict';

    // ============================================
    // Theme Toggle (Dark/Light Mode)
    // ============================================

    const THEME_KEY = 'smallstack-theme';

    // Get config from window object (set in base template)
    const config = window.SMALLSTACK || {};

    function getStoredTheme() {
        return localStorage.getItem(THEME_KEY);
    }

    function setStoredTheme(theme) {
        localStorage.setItem(THEME_KEY, theme);
    }

    function getPreferredTheme() {
        // Priority 1: User's saved profile preference (if logged in)
        if (config.isAuthenticated && config.userTheme) {
            return config.userTheme;
        }

        // Priority 2: localStorage (for session persistence and anonymous users)
        const stored = getStoredTheme();
        if (stored) {
            return stored;
        }

        // Priority 3: Default to dark theme
        return 'dark';
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        setStoredTheme(theme);

        // Update the theme preference hidden input and toggle buttons if on profile edit page
        const themeInput = document.getElementById('id_theme_preference');
        if (themeInput) {
            themeInput.value = theme;
        }

        // Update toggle button states
        document.querySelectorAll('.theme-toggle-btn').forEach(function(btn) {
            if (btn.dataset.theme === theme) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Save theme preference to profile via htmx (if authenticated and htmx available)
        if (config.isAuthenticated && typeof htmx !== 'undefined') {
            htmx.ajax('POST', '/profile/theme/', {
                values: { theme: theme },
                swap: 'none'
            });
        }
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme');
        const newTheme = current === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
    }

    // Initialize theme on page load
    function initTheme() {
        setTheme(getPreferredTheme());

        // Listen for theme toggle button clicks
        const themeToggle = document.getElementById('theme-toggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', toggleTheme);
        }

        // Listen for system theme changes (only if no stored preference)
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!getStoredTheme() && !config.userTheme) {
                setTheme(e.matches ? 'dark' : 'light');
            }
        });

        // Theme toggle buttons (profile edit page and dropdown menu)
        document.querySelectorAll('.theme-toggle-btn').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                setTheme(this.dataset.theme);
            });
        });
    }

    // ============================================
    // Sidebar Toggle
    // ============================================

    function initSidebar() {
        const sidebarToggle = document.getElementById('sidebar-toggle');
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');

        if (!sidebar) return;

        const SIDEBAR_STATE_KEY = 'smallstack-sidebar-closed';

        function isMobile() {
            return window.innerWidth <= 768;
        }

        function openSidebar() {
            sidebar.classList.remove('closed');
            document.body.classList.remove('sidebar-closed');
            if (isMobile() && overlay) overlay.classList.add('show');
            if (!isMobile()) {
                localStorage.setItem(SIDEBAR_STATE_KEY, 'false');
            }
        }

        function closeSidebar() {
            sidebar.classList.add('closed');
            document.body.classList.add('sidebar-closed');
            if (overlay) overlay.classList.remove('show');
            if (!isMobile()) {
                localStorage.setItem(SIDEBAR_STATE_KEY, 'true');
            }
        }

        function toggleSidebar() {
            if (sidebar.classList.contains('closed')) {
                openSidebar();
            } else {
                closeSidebar();
            }
        }

        // Remove the flash-prevention class (CSS takes over from here)
        document.documentElement.classList.remove('sidebar-will-close');

        // On mobile, start closed. On desktop, restore from localStorage
        if (isMobile()) {
            closeSidebar();
        } else if (localStorage.getItem(SIDEBAR_STATE_KEY) === 'true') {
            closeSidebar();
        }

        // Hamburger toggle in topbar
        if (sidebarToggle) {
            sidebarToggle.addEventListener('click', toggleSidebar);
        }

        // Close sidebar when clicking overlay (mobile)
        if (overlay) {
            overlay.addEventListener('click', closeSidebar);
        }

        // Handle resize - close on mobile, restore on desktop
        window.addEventListener('resize', () => {
            if (isMobile()) {
                closeSidebar();
            }
        });
    }

    // ============================================
    // User Dropdown Menu
    // ============================================

    function initUserMenu() {
        const menuToggle = document.getElementById('user-menu-toggle');
        const dropdown = document.getElementById('user-dropdown');

        if (!menuToggle || !dropdown) return;

        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!menuToggle.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });

        // Close dropdown on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                dropdown.classList.remove('show');
            }
        });
    }

    // ============================================
    // Message Dismissal
    // ============================================

    function initMessages() {
        const closeButtons = document.querySelectorAll('.message-close');

        closeButtons.forEach((button) => {
            button.addEventListener('click', () => {
                const message = button.closest('.message');
                if (message) {
                    message.style.opacity = '0';
                    message.style.transform = 'translateX(100%)';
                    setTimeout(() => {
                        message.remove();
                    }, 300);
                }
            });
        });

        // Auto-dismiss messages after 5 seconds
        const messages = document.querySelectorAll('.message');
        messages.forEach((message) => {
            setTimeout(() => {
                if (message.parentNode) {
                    message.style.opacity = '0';
                    message.style.transform = 'translateX(100%)';
                    setTimeout(() => {
                        message.remove();
                    }, 300);
                }
            }, 5000);
        });
    }

    // ============================================
    // Initialize Everything
    // ============================================

    function init() {
        initTheme();
        initSidebar();
        initUserMenu();
        initMessages();

        // Re-initialize message dismissal after htmx swaps new content
        document.addEventListener('htmx:afterSettle', function() {
            initMessages();
        });
    }

    // Run init when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
