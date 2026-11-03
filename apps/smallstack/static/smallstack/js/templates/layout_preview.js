// Moved from apps/smallstack/templates/smallstack/layout_preview.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    var layouts = {
        'full':         { sidebar: 'open',     topbar: 'auto',   name: 'Full Layout' },
        'topbar-only':  { sidebar: 'disabled', topbar: 'always', name: 'Topbar Only' },
        'dual':         { sidebar: 'open',     topbar: 'always', name: 'Dual Navigation' },
        'collapsed':    { sidebar: 'closed',   topbar: 'always', name: 'Sidebar Collapsed' },
        'minimal':      { sidebar: 'closed',   topbar: 'auto',   name: 'Minimal' },
        'sidebar-only': { sidebar: 'open',     topbar: 'hidden', name: 'Sidebar Only' },
    };

    var initialSidebar = document.body.dataset.sidebarState;
    var initialTopbar = document.body.dataset.topbarNav;

    function detectActive() {
        for (var key in layouts) {
            var l = layouts[key];
            if (l.sidebar === initialSidebar && l.topbar === initialTopbar) return key;
        }
        return null;
    }

    var activeLayout = detectActive();
    if (activeLayout) {
        var el = document.getElementById('card-' + activeLayout);
        if (el) el.classList.add('active');
    }

    window.applyLayout = function(key) {
        var layout = layouts[key];
        if (!layout) return;

        var body = document.body;
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebar-overlay');

        body.dataset.sidebarState = layout.sidebar;
        body.setAttribute('data-sidebar-forced', '');

        if (layout.sidebar === 'open' && sidebar) {
            sidebar.classList.remove('closed');
            body.classList.remove('sidebar-closed');
        } else if (layout.sidebar === 'closed' && sidebar) {
            sidebar.classList.add('closed');
            body.classList.add('sidebar-closed');
        } else if (layout.sidebar === 'disabled') {
            body.classList.add('sidebar-closed');
            if (sidebar) sidebar.classList.add('closed');
        }

        if (overlay) overlay.classList.remove('show');
        body.dataset.topbarNav = layout.topbar;

        var toggle = document.getElementById('sidebar-toggle');
        if (toggle) {
            toggle.style.display = layout.sidebar === 'disabled' ? 'none' : '';
        }

        document.querySelectorAll('.layout-card').forEach(function(card) {
            card.classList.remove('active');
        });
        var card = document.getElementById('card-' + key);
        if (card) card.classList.add('active');

        var actions = document.getElementById('header-actions');
        var nameEl = document.getElementById('preview-name');
        if (actions && nameEl) {
            nameEl.textContent = layout.name;
            actions.style.display = '';
        }
    };

    window.resetLayout = function() {
        window.location.reload();
    };

    // Page-level tab switching
    document.getElementById('page-tabs').addEventListener('click', function(e) {
        var btn = e.target.closest('button[data-pagetab]');
        if (!btn) return;
        this.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        document.querySelectorAll('.page-tab-panel').forEach(function(p) {
            p.classList.toggle('active', p.id === 'pagetab-' + btn.dataset.pagetab);
        });
    });

    // Copy button handler
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.lp-copy-btn');
        if (!btn) return;
        var code = btn.closest('.lp-code-wrap').querySelector('code');
        navigator.clipboard.writeText(code.textContent).then(function() {
            var orig = btn.textContent;
            btn.textContent = 'Copied!';
            btn.style.color = 'var(--primary)';
            btn.style.borderColor = 'var(--primary)';
            setTimeout(function() {
                btn.textContent = orig;
                btn.style.color = '';
                btn.style.borderColor = '';
            }, 1500);
        });
    });
})();
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { applyLayout: window.applyLayout, resetLayout: window.resetLayout });
