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
    // Accessibility primitive: focus trap
    // ============================================
    // window.SmallStack.trapFocus(container) confines Tab/Shift+Tab focus to
    // `container`, moves focus to its first focusable child, and returns a
    // release() that removes the trap and restores focus to wherever it was.
    // Use it for any modal/dialog/popover. See docs/skills/accessibility.md.
    window.SmallStack = window.SmallStack || {};

    var FOCUSABLE_SELECTOR = [
        'a[href]', 'button:not([disabled])', 'textarea:not([disabled])',
        'input:not([disabled])', 'select:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(', ');

    window.SmallStack.trapFocus = function (container) {
        if (!container) return function () {};
        var previouslyFocused = document.activeElement;

        function focusables() {
            return Array.prototype.slice
                .call(container.querySelectorAll(FOCUSABLE_SELECTOR))
                .filter(function (el) { return el.offsetParent !== null; });
        }

        function onKeydown(e) {
            if (e.key !== 'Tab') return;
            var items = focusables();
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }

        container.addEventListener('keydown', onKeydown);
        var items = focusables();
        if (items.length) items[0].focus();

        return function release() {
            container.removeEventListener('keydown', onKeydown);
            if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
                previouslyFocused.focus();
            }
        };
    };

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
        // Always set data-palette (including for the default "django"
        // palette) so palette-specific CSS rules can target every state.
        // Removing the attribute meant the django palette inherited the
        // base [data-theme="dark"] surfaces (warm-gray) instead of the
        // explicit modern-black override defined for data-palette="django".
        var effective = palette || 'django';
        document.documentElement.setAttribute('data-palette', effective);
        localStorage.setItem(PALETTE_KEY, effective);

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

        function setState(state, persist) {
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

            // Persist to localStorage — unless the server forces the state, we're
            // on mobile, or the caller opts out (persist === false, e.g. a
            // temporary collapse by focus mode that should snap back on reload).
            if (persist !== false && !isForced && !isMobile()) {
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

        // Public handle so features (Help/Runbook focus mode) can collapse the
        // sidebar temporarily and keep dataset/classes/currentState in sync.
        // Only defined when the sidebar is actually present + enabled.
        window.smallstackSidebar = {
            getState: function () { return currentState; },
            setState: setState,   // setState(state, persist) — pass false for a temporary change
        };

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

        initSidebarScroll(sidebar);
    }

    // --- Sidebar scroll position ---
    // Every link is a full page load, so the sidebar would start back at the top each time.
    // Keep its scroll offset for this tab (sessionStorage) and put it back on the next page;
    // with nothing saved (a new tab), bring the active link into view instead.
    const SIDEBAR_SCROLL_KEY = 'smallstack-sidebar-scroll';

    function initSidebarScroll(sidebar) {
        // .sidebar and .sidebar-nav can both overflow, depending on the viewport.
        var panes = [sidebar, sidebar.querySelector('.sidebar-nav')].filter(Boolean);
        var saved = null;
        try { saved = JSON.parse(sessionStorage.getItem(SIDEBAR_SCROLL_KEY)); } catch (e) { /* none */ }

        if (Array.isArray(saved)) {
            panes.forEach(function(pane, i) { pane.scrollTop = saved[i] || 0; });
        }
        // Bring the active link into view by scrolling the sidebar only (scrollIntoView
        // would move the page as well).
        var active = sidebar.querySelector('.nav-link.active');
        if (active) {
            panes.forEach(function(pane) {
                if (pane.scrollHeight <= pane.clientHeight) return;
                var box = pane.getBoundingClientRect(), link = active.getBoundingClientRect();
                if (link.top < box.top) pane.scrollTop -= box.top - link.top + 16;
                else if (link.bottom > box.bottom) pane.scrollTop += link.bottom - box.bottom + 16;
            });
        }

        window.addEventListener('pagehide', function() {
            try {
                sessionStorage.setItem(SIDEBAR_SCROLL_KEY, JSON.stringify(panes.map(function(p) { return p.scrollTop; })));
            } catch (e) { /* storage blocked: start at the top next time */ }
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

    function removeMessage(message) {
        message.style.opacity = '0';
        message.style.transform = 'translateX(100%)';
        setTimeout(() => {
            var container = message.closest('.messages-container');
            message.remove();
            if (container && !container.querySelector('.message')) {
                container.remove();
            }
        }, 300);
    }

    function initMessages() {
        const closeButtons = document.querySelectorAll('.message-close');

        closeButtons.forEach((button) => {
            button.addEventListener('click', () => {
                const message = button.closest('.message');
                if (message) {
                    removeMessage(message);
                }
            });
        });

        // Auto-dismiss messages after 5 seconds
        const messages = document.querySelectorAll('.message');
        messages.forEach((message) => {
            setTimeout(() => {
                if (message.parentNode) {
                    removeMessage(message);
                }
            }, 5000);
        });
    }

    // ============================================
    // Number stepper: − / + buttons on every number field
    // ============================================
    // A browser's own spin buttons are a few pixels wide and drawn in its
    // colours, not the theme's. Every <input type="number"> on the page is
    // wrapped with two theme-drawn buttons instead: as it loads, and whenever
    // one is added later (htmx, a script building a row). Nothing to add in
    // markup. data-no-stepper on the input, or on any element around it, leaves
    // the field alone.
    //
    // The wrapper takes the input's place in the layout, so it's given the
    // input's own width (fitStepper, below): a % or calc() width as written, a
    // fixed one in px. The buttons then follow the room there is (a container
    // query in components.css): − and + side by side, each the height of the
    // field, when the wrapper is 10rem or wider; a slim stacked pair, + over −,
    // when it's narrower. A narrow fixed-width field keeps its width for the
    // value and gets the stacked pair beside it (num-stepper--compact).
    //
    // The buttons step by the input's own step, min and max and fire `input`
    // and `change`, so existing listeners hear them. An empty field starts
    // from its placeholder when that's a number (the default it stands for).
    // Like the native ones they are a mouse and touch convenience, outside the
    // tab order and the accessibility tree: the field's arrow keys still step it.
    // window.SmallStack.numberStepper(input) wraps one by hand and returns the
    // wrapper; it's safe to call twice.
    var STEPPER_ROOM = 10;   // rem: a field at least this wide holds the − / + pair (the CSS says the same)

    // The input's width as the stylesheet computes it ("100%", "calc(100% - 14px)",
    // "105px", "auto") where the browser can say; else what getComputedStyle
    // gives, which is a used px value once the field is rendered.
    function stepperWidth(input, cs) {
        try {
            if (input.computedStyleMap) return String(input.computedStyleMap().get('width'));
        } catch (e) { /* fall through */ }
        return cs.width;
    }

    function fitStepper(wrap, input, parent) {
        var cs = window.getComputedStyle(input);
        var pcs = window.getComputedStyle(parent);
        var width = stepperWidth(input, cs);
        var fluid = width.indexOf('%') >= 0;
        if (!fluid && !input.computedStyleMap && input.offsetWidth) {
            var room = parent.clientWidth - parseFloat(pcs.paddingLeft) - parseFloat(pcs.paddingRight);
            if (room > 0 && input.offsetWidth >= room * 0.9) { fluid = true; width = '100%'; }
        }
        // Stand where the input stood: its margins, and its part in a flex row or a grid.
        var sides = [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft];
        if (sides.some(function (m) { return parseFloat(m); })) wrap.style.margin = sides.join(' ');
        var grows = false;
        if (pcs.display.indexOf('flex') >= 0) {
            grows = parseFloat(cs.flexGrow) > 0;
            wrap.style.flex = cs.flexGrow + ' ' + cs.flexShrink + ' ' + (grows ? cs.flexBasis : 'auto');
        }
        var area = [cs.gridRowStart, cs.gridColumnStart, cs.gridRowEnd, cs.gridColumnEnd];
        if (area.some(function (a) { return a && a !== 'auto'; })) wrap.style.gridArea = area.join(' / ');

        var px = parseFloat(width) || input.offsetWidth;  // "auto": what it measures, if it's drawn
        var rem = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
        if (grows) wrap.style.width = 'auto';
        else if (fluid || !px) wrap.style.width = fluid ? width : '100%';
        else if (px >= STEPPER_ROOM * rem) wrap.style.width = px + 'px';
        else {
            // Too narrow to give anything up: the value keeps its width, the pair goes beside it.
            wrap.classList.add('num-stepper--compact');
            wrap.style.width = 'calc(' + px + 'px + 1.7rem)';
        }
    }

    window.SmallStack.numberStepper = function (input) {
        if (!input || input.type !== 'number') return input;
        var parent = input.parentNode;
        if (parent && parent.classList && parent.classList.contains('num-stepper')) return parent;
        var wrap = document.createElement('span');
        wrap.className = 'num-stepper';
        if (parent && input.isConnected) fitStepper(wrap, input, parent);
        if (parent) parent.insertBefore(wrap, input);
        wrap.appendChild(input);
        var buttons = document.createElement('span');
        buttons.className = 'num-stepper-btns';
        wrap.appendChild(buttons);

        function limit(name) { return input[name] === '' ? null : Number(input[name]); }
        function sync() {
            var value = input.value === '' ? null : Number(input.value);
            var min = limit('min'), max = limit('max');
            down.disabled = value !== null && min !== null && value <= min;
            up.disabled = value !== null && max !== null && value >= max;
        }
        function step(direction) {
            if (input.disabled || input.readOnly) return;
            if (input.value === '' && input.placeholder !== '' && !isNaN(Number(input.placeholder))) {
                input.value = input.placeholder;
            }
            try {
                if (direction > 0) input.stepUp(); else input.stepDown();
            } catch (e) {  // step="any" has no step to take: move by one
                var next = (Number(input.value) || 0) + direction;
                var min = limit('min'), max = limit('max');
                if (min !== null) next = Math.max(min, next);
                if (max !== null) next = Math.min(max, next);
                input.value = String(next);
            }
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            sync();
            input.focus();
        }
        function button(text, direction) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'num-stepper-btn';
            btn.tabIndex = -1;
            btn.setAttribute('aria-hidden', 'true');
            btn.textContent = text;
            btn.addEventListener('click', function () { step(direction); });
            buttons.appendChild(btn);
            return btn;
        }
        var down = button('−', -1), up = button('+', 1);
        input.addEventListener('input', sync);
        input.addEventListener('change', sync);
        sync();
        return wrap;
    };

    function stepNumbersIn(root) {
        if (!root || root.nodeType !== 1) return;
        var found = root.matches('input[type="number"]') ? [root] : root.querySelectorAll('input[type="number"]');
        for (var i = 0; i < found.length; i++) {
            if (!found[i].closest('.num-stepper, [data-no-stepper]')) window.SmallStack.numberStepper(found[i]);
        }
    }

    function initSteppers() {
        stepNumbersIn(document.body);
        if (!window.MutationObserver) return;
        new MutationObserver(function (records) {
            for (var i = 0; i < records.length; i++) {
                if (records[i].type === 'attributes') { stepNumbersIn(records[i].target); continue; }
                for (var j = 0; j < records[i].addedNodes.length; j++) stepNumbersIn(records[i].addedNodes[j]);
            }
        }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['type'] });
    }

    // ============================================
    // Stat-card drill-down modal
    // ============================================
    // The modal markup lives in base.html (included globally). Open it
    // declaratively — no inline handler — and let htmx swap the body:
    //
    //   <button hx-get="/rows/" hx-target="#stat-modal-body" data-stat-modal="Title">
    //   <button data-stat-modal-close>Keep it</button>
    //
    // A click on a [data-stat-modal] element opens the modal with that title
    // (an <a> doesn't navigate); [data-stat-modal-close] and the backdrop close
    // it. openStatModal / closeStatModal stay on window for script callers.

    var _statModalRelease = null;
    var _statModalTrigger = null;

    // `trigger` is the stat-card button that opened the modal (passed as `this`
    // from the inline onclick). We stash it so focus returns to it on close —
    // even if htmx/focus timing means it isn't document.activeElement anymore.
    function openStatModal(title, trigger) {
        var titleEl = document.getElementById('stat-modal-title');
        var modal = document.getElementById('stat-modal');
        if (!modal) return;
        _statModalTrigger = trigger || document.activeElement;
        if (titleEl) titleEl.textContent = title;
        // data-stat-modal-size on the opener: "narrow" is a panel sized for a
        // form rather than a table (width to a comfortable measure, height
        // to its content); "reading" is one for a page of prose (a help
        // bubble): a reading measure wide, most of the window tall.
        var panel = modal.querySelector('.stat-modal-panel');
        var size = trigger && trigger.getAttribute ? trigger.getAttribute('data-stat-modal-size') : null;
        if (panel) {
            panel.classList.toggle('is-narrow', size === 'narrow');
            panel.classList.toggle('is-reading', size === 'reading');
        }
        modal.classList.add('open');
        _statModalRelease = window.SmallStack.trapFocus(
            modal.querySelector('.stat-modal-panel') || modal
        );
    }

    function closeStatModal() {
        var modal = document.getElementById('stat-modal');
        if (modal) modal.classList.remove('open');
        if (_statModalRelease) { _statModalRelease(); _statModalRelease = null; }
        // Restore focus to the invoking stat card (trapFocus also attempts this,
        // but the explicit trigger is the reliable target).
        if (_statModalTrigger && typeof _statModalTrigger.focus === 'function') {
            _statModalTrigger.focus();
        }
        _statModalTrigger = null;
    }

    window.openStatModal = openStatModal;
    window.closeStatModal = closeStatModal;

    document.addEventListener('click', function (e) {
        var opener = e.target.closest && e.target.closest('[data-stat-modal]');
        if (opener) {
            if (opener.tagName === 'A') e.preventDefault();
            openStatModal(opener.getAttribute('data-stat-modal'), opener);
            return;
        }
        var closer = e.target.closest && e.target.closest('[data-stat-modal-close]');
        if (closer || (e.target.id === 'stat-modal')) {  // the close button, or the backdrop
            if (closer) e.preventDefault();
            closeStatModal();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeStatModal();
    });

    // ============================================
    // Declarative behaviours — markup without inline handlers
    // ============================================
    // Templates describe behaviour with data- attributes; these delegated
    // listeners carry it out. No onclick="…" anywhere: the CSP's script-src has
    // no 'unsafe-inline', so the browser wouldn't run one.
    //
    //   <form data-confirm="Delete this?">           confirm before submitting
    //   <a|button data-confirm="Really?">            confirm before following/clicking
    //   <select data-autosubmit>                     submit its form on change
    //   <button data-copy="element-id">              copy that element's value/text
    //   <button data-copy-text="literal">            copy the literal text
    //   <button data-scroll-to="#id">                smooth-scroll to an element
    //   <button data-toggle-class="open"             toggle a class on the closest
    //           data-toggle-on=".panel">               match (or on itself)
    //   <button data-activate-in=".tab-bar">         mark itself .active among the
    //                                                  [data-activate-in] buttons there
    //   <div role="button" tabindex="0" data-keyclick>  Enter/Space click it
    //   <button data-ss-action="openThing"              call a REGISTERED page action
    //           data-ss-args='["x", "$this"]'>     ("$this" = the element,
    //                                                   "$event" = the event)
    //   <div data-ss-action="closeThing" data-ss-self>  …only when the click is
    //                                                   on the element itself (a backdrop)
    //   <a href="/x/delete/" data-ss-action="…" data-ss-prevent>  …and don't follow
    //                                                   the link (it's the no-JS fallback)
    //
    // Page scripts register their actions (an allow-list — markup can only call
    // what a script chose to expose), whenever they run:
    //
    //   window.SmallStack = window.SmallStack || {};
    //   window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { openThing: openThing });

    window.SmallStack.actions = window.SmallStack.actions || {};
    // Built-in: fill the stat modal from a hidden source element (content that's
    // already on the page, no request) — with data-stat-modal on the same trigger.
    window.SmallStack.actions.fillStatModalFrom = function (sourceId) {
        var src = document.getElementById(sourceId);
        var body = document.getElementById('stat-modal-body');
        if (src && body) body.innerHTML = src.innerHTML;
    };

    function runAction(el, ev) {
        var fn = window.SmallStack.actions[el.getAttribute('data-ss-action')];
        if (typeof fn !== 'function') {
            console.warn('SmallStack: no registered action "' + el.getAttribute('data-ss-action') + '"');
            return;
        }
        var args = [];
        var raw = el.getAttribute('data-ss-args');
        if (raw) {
            try { args = JSON.parse(raw); } catch (err) { console.warn('SmallStack: bad data-ss-args', raw); return; }
        }
        args = args.map(function (a) { return a === '$this' ? el : (a === '$event' ? ev : a); });
        return fn.apply(el, args);
    }

    function copyToClipboard(btn, text) {
        if (!navigator.clipboard) return;
        navigator.clipboard.writeText(text).then(function () {
            if (!btn.hasAttribute('data-copy-quiet')) {
                var label = btn.getAttribute('aria-label');
                if (!btn.querySelector('svg')) {
                    var was = btn.textContent;
                    btn.textContent = 'Copied!';
                    setTimeout(function () { btn.textContent = was; }, 1500);
                } else if (label !== null) {
                    btn.setAttribute('aria-label', 'Copied');
                    setTimeout(function () { btn.setAttribute('aria-label', label); }, 1500);
                }
            }
        });
    }

    document.addEventListener('click', function (e) {
        var t = e.target;
        if (!t.closest) return;

        var copyEl = t.closest('[data-copy], [data-copy-text]');
        if (copyEl) {
            var text = copyEl.getAttribute('data-copy-text');
            if (text === null) {
                var src = document.getElementById(copyEl.getAttribute('data-copy'));
                text = src ? ('value' in src && src.value !== undefined ? src.value : src.innerText) : '';
            }
            copyToClipboard(copyEl, text);
        }

        var scrollEl = t.closest('[data-scroll-to]');
        if (scrollEl) {
            var dest = document.querySelector(scrollEl.getAttribute('data-scroll-to'));
            if (dest) dest.scrollIntoView({ behavior: 'smooth' });
        }

        var toggleEl = t.closest('[data-toggle-class]');
        if (toggleEl) {
            var on = toggleEl.getAttribute('data-toggle-on');
            var host = on ? toggleEl.closest(on) : toggleEl;
            if (host) host.classList.toggle(toggleEl.getAttribute('data-toggle-class'));
        }

        var activateEl = t.closest('[data-activate-in]');
        if (activateEl) {
            var group = activateEl.closest(activateEl.getAttribute('data-activate-in'));
            if (group) {
                group.querySelectorAll('[data-activate-in]').forEach(function (b) { b.classList.remove('active'); });
                activateEl.classList.add('active');
            }
        }

        var actionEl = t.closest('[data-ss-action]');
        if (actionEl && (actionEl.getAttribute('data-ss-on') || 'click') === 'click') {
            if (actionEl.hasAttribute('data-ss-self') && t !== actionEl) return;
            if (actionEl.hasAttribute('data-ss-prevent') || (actionEl.tagName === 'A' && actionEl.getAttribute('href') === '#')) e.preventDefault();
            if (runAction(actionEl, e) === false) e.preventDefault();
        }
    });

    // Capture phase: a "no" stops the click before htmx or any element listener sees it.
    document.addEventListener('click', function (e) {
        var confirmEl = e.target.closest && e.target.closest('a[data-confirm], button[data-confirm]');
        if (confirmEl && !window.confirm(confirmEl.getAttribute('data-confirm'))) {
            e.preventDefault();
            e.stopPropagation();
        }
    }, true);

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (form.hasAttribute && form.hasAttribute('data-confirm') && !window.confirm(form.getAttribute('data-confirm'))) {
            e.preventDefault();
            e.stopPropagation();
        }
    }, true);

    document.addEventListener('change', function (e) {
        var t = e.target;
        if (t.hasAttribute && t.hasAttribute('data-autosubmit') && t.form) t.form.submit();
        var actionEl = t.closest && t.closest('[data-ss-action][data-ss-on="change"]');
        if (actionEl) runAction(actionEl, e);
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        var el = e.target.closest && e.target.closest('[data-keyclick]');
        if (el && el === e.target) {
            e.preventDefault();
            el.click();
        }
    });

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
        initSteppers();

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
