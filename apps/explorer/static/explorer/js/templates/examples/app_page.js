// Moved from apps/explorer/templates/explorer/examples/app_page.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    // Tab switching
    const tabs = document.getElementById('example-tabs');
    const panels = document.querySelectorAll('.example-tab-panel');
    tabs.addEventListener('click', function(e) {
        const btn = e.target.closest('button[data-tab]');
        if (!btn) return;
        tabs.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        panels.forEach(p => p.classList.toggle('active', p.id === 'tab-' + btn.dataset.tab));
    });

    // Copy buttons
    document.querySelectorAll('.example-copy-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const code = this.closest('.example-code-wrap').querySelector('code');
            const text = code.textContent;
            navigator.clipboard.writeText(text).then(() => {
                const orig = this.textContent;
                this.textContent = 'Copied!';
                this.style.color = 'var(--primary)';
                this.style.borderColor = 'var(--primary)';
                setTimeout(() => {
                    this.textContent = orig;
                    this.style.color = '';
                    this.style.borderColor = '';
                }, 1500);
            });
        });
    });
})();
