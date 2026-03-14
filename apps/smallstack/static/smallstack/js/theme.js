/**
 * Theme JavaScript - SmallStack
 *
 * Handles:
 * - Dark/Light mode toggle with localStorage persistence
 * - Sidebar collapse behavior with state control (open/closed/disabled)
 * - Sidebar submenu expand/collapse
 * - User dropdown menu
 * - Topbar navigation submenus
 * - Message dismissal
 */

(function () {
    'use strict';

    // ============================================
    // Theme Toggle (Dark/Light Mode)
    // ============================================

    const THEME_KEY = 'smallstack-theme';
    const PALETTE_KEY = 'smallstack-palette';

    // Get config from window object (set in base template)
    const config = window.SMALLSTACK || {};

    function getStoredTheme() {
        return localStorage.getItem(THEME_KEY);
    }

    function setStoredTheme(theme) {
        localStorage.setItem(THEME_KEY, theme);
        // Sync to Django admin's localStorage key so admin picks up the same theme
        localStorage.setItem('theme', theme);
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
        if (config.isAuthenticated && typeof htmx !== 'undefined' && config.urls && config.urls.themePreference) {
            htmx.ajax('POST', config.urls.themePreference, {
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
    // Color Palette
    // ============================================

    function getPreferredPalette() {
        // Priority 1: User's saved profile preference (if logged in)
        if (config.isAuthenticated && config.userPalette) {
            return config.userPalette;
        }

        // Priority 2: localStorage
        var stored = localStorage.getItem(PALETTE_KEY);
        if (stored) {
            return stored;
        }

        // Priority 3: System default from context
        return config.colorPalette || 'django';
    }

    function setPalette(palette) {
        if (palette && palette !== 'django') {
            document.documentElement.setAttribute('data-palette', palette);
        } else {
            document.documentElement.removeAttribute('data-palette');
        }
        localStorage.setItem(PALETTE_KEY, palette || 'django');

        // Update the hidden input on profile edit page
        var paletteInput = document.getElementById('id_color_palette');
        if (paletteInput) {
            paletteInput.value = palette || '';
        }

        // Update swatch active states
        document.querySelectorAll('.palette-swatch, .palette-swatch-inline').forEach(function(btn) {
            if (btn.dataset.palette === (palette || 'django')) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        // Save palette preference to profile via htmx (if authenticated and htmx available)
        if (config.isAuthenticated && typeof htmx !== 'undefined' && config.urls && config.urls.palettePreference) {
            htmx.ajax('POST', config.urls.palettePreference, {
                values: { palette: palette || '' },
                swap: 'none'
            });
        }
    }

    function initPalette() {
        setPalette(getPreferredPalette());

        // Listen for palette swatch clicks
        document.querySelectorAll('.palette-swatch, .palette-swatch-inline').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                setPalette(this.dataset.palette);
            });
        });
    }

    // ============================================
    // Sidebar Toggle (State-based)
    // ============================================

    const SIDEBAR_STATE_KEY = 'smallstack-sidebar-state';

    function initSidebar() {
        const sidebarToggle = document.getElementById('sidebar-toggle');
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebar-overlay');
        const body = document.body;
        const isForced = body.hasAttribute('data-sidebar-forced');
        var currentState = body.dataset.sidebarState || config.sidebarDefault || 'open';

        function enableTransitions() {
            requestAnimationFrame(function() {
                requestAnimationFrame(function() {
                    document.documentElement.classList.remove('no-sidebar-transition');
                });
            });
        }

        // If sidebar is disabled, apply state and return early
        if (currentState === 'disabled' || !config.sidebarEnabled) {
            body.dataset.sidebarState = 'disabled';
            body.classList.add('sidebar-closed');
            enableTransitions();
            return;
        }

        if (!sidebar) { enableTransitions(); return; }

        function isMobile() {
            return window.innerWidth <= 768;
        }

        function setState(state) {
            currentState = state;
            body.dataset.sidebarState = state;

            if (state === 'open') {
                sidebar.classList.remove('closed');
                body.classList.remove('sidebar-closed');
                if (isMobile() && overlay) overlay.classList.add('show');
            } else {
                sidebar.classList.add('closed');
                body.classList.add('sidebar-closed');
                if (overlay) overlay.classList.remove('show');
            }

            // Persist to localStorage (only if not forced by server)
            if (!isForced && !isMobile()) {
                localStorage.setItem(SIDEBAR_STATE_KEY, state);
            }
        }

        function toggleSidebar() {
            setState(currentState === 'open' ? 'closed' : 'open');
        }

        // Restore from localStorage if not forced by server
        if (!isForced && !isMobile()) {
            var saved = localStorage.getItem(SIDEBAR_STATE_KEY);
            if (saved === 'open' || saved === 'closed') {
                currentState = saved;
            }
        }

        // On mobile, always start closed
        if (isMobile()) {
            currentState = 'closed';
        }

        // Apply initial state (with transitions suppressed via CSS)
        setState(currentState);

        // Re-enable transitions after the browser has painted the correct state
        enableTransitions();

        // Hamburger toggle in topbar
        if (sidebarToggle) {
            sidebarToggle.addEventListener('click', toggleSidebar);
        }

        // Close sidebar when clicking overlay (mobile)
        if (overlay) {
            overlay.addEventListener('click', function() {
                setState('closed');
            });
        }

        // Handle resize - close on mobile
        window.addEventListener('resize', function() {
            if (isMobile()) {
                setState('closed');
            }
        });

        // --- Submenu toggle ---
        document.querySelectorAll('[data-submenu] .nav-parent').forEach(function(btn) {
            btn.addEventListener('click', function() {
                btn.closest('[data-submenu]').classList.toggle('open');
            });
        });

        // Auto-open submenu with active child
        document.querySelectorAll('.nav-submenu .nav-link.active').forEach(function(el) {
            var group = el.closest('[data-submenu]');
            if (group) group.classList.add('open');
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
            // Close apps dropdown if open
            const appsDropdown = document.getElementById('apps-dropdown');
            if (appsDropdown) appsDropdown.classList.remove('show');
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
    // Apps Menu Dropdown
    // ============================================

    function initAppsMenu() {
        const menuToggle = document.getElementById('apps-menu-toggle');
        const dropdown = document.getElementById('apps-dropdown');

        if (!menuToggle || !dropdown) return;

        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            // Close user dropdown if open
            const userDropdown = document.getElementById('user-dropdown');
            if (userDropdown) userDropdown.classList.remove('show');
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
    // Topbar Navigation Submenus
    // ============================================

    function initTopbarNav() {
        // Handle both .topbar-nav and .topbar-nav-auto submenus
        const navItems = document.querySelectorAll('.topbar-nav-item.has-submenu');
        if (!navItems.length) return;

        navItems.forEach(function(item) {
            const btn = item.querySelector('.topbar-nav-link');
            if (!btn) return;

            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const isOpen = item.classList.contains('submenu-open');

                // Close all other open submenus
                navItems.forEach(function(other) {
                    if (other !== item) {
                        other.classList.remove('submenu-open');
                        var otherBtn = other.querySelector('.topbar-nav-link');
                        if (otherBtn) otherBtn.setAttribute('aria-expanded', 'false');
                    }
                });

                // Toggle this submenu
                item.classList.toggle('submenu-open', !isOpen);
                btn.setAttribute('aria-expanded', String(!isOpen));
            });
        });

        // Close all submenus on outside click
        document.addEventListener('click', function() {
            navItems.forEach(function(item) {
                item.classList.remove('submenu-open');
                var btn = item.querySelector('.topbar-nav-link');
                if (btn) btn.setAttribute('aria-expanded', 'false');
            });
        });

        // Close all submenus on Escape
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                navItems.forEach(function(item) {
                    item.classList.remove('submenu-open');
                    var btn = item.querySelector('.topbar-nav-link');
                    if (btn) btn.setAttribute('aria-expanded', 'false');
                });
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
        initPalette();
        initSidebar();
        initUserMenu();
        initAppsMenu();
        initTopbarNav();
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
