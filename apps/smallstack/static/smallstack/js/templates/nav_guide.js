// Moved from apps/smallstack/templates/smallstack/nav_guide.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    // Generic tab switching for all tab groups
    document.querySelectorAll('.guide-tabs').forEach(function(tabBar) {
        var group = tabBar.dataset.tabgroup;
        tabBar.addEventListener('click', function(e) {
            var btn = e.target.closest('button[data-tab]');
            if (!btn) return;
            tabBar.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            document.querySelectorAll('.guide-tab-panel[data-group="' + group + '"]').forEach(function(p) {
                p.classList.toggle('active', p.dataset.panel === btn.dataset.tab);
            });
        });
    });

    // Copy button handler
    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.g-copy-btn');
        if (!btn) return;
        var code = btn.closest('.g-code-wrap').querySelector('code');
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
