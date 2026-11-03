// Moved from apps/explorer/templates/explorer/index.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    // ── Sidebar mode toggle ────────────────────────────────────────
    const modeToggle = document.getElementById('sidebar-mode');
    const groupPanel = document.getElementById('sidebar-group');
    const appPanel = document.getElementById('sidebar-app');

    modeToggle.addEventListener('click', function(e) {
        const btn = e.target.closest('button[data-mode]');
        if (!btn) return;
        const mode = btn.dataset.mode;
        modeToggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        groupPanel.style.display = mode === 'group' ? '' : 'none';
        appPanel.style.display = mode === 'app' ? '' : 'none';
        localStorage.setItem('explorer-sidebar-mode', mode);

        // Navigate to "all" for the selected mode
        window.location.href = '?by=' + mode;
    });

    // Restore sidebar mode from localStorage on "all" views
    const params = new URLSearchParams(window.location.search);
    if (!params.has('by')) {
        const saved = localStorage.getItem('explorer-sidebar-mode');
        if (saved === 'app') {
            modeToggle.querySelector('[data-mode="app"]').classList.add('active');
            modeToggle.querySelector('[data-mode="group"]').classList.remove('active');
            groupPanel.style.display = 'none';
            appPanel.style.display = '';
        }
    }

    // ── Sidebar filter ──────────────────────────────────────────────
    const sidebarFilter = document.getElementById('sidebar-filter');
    sidebarFilter.addEventListener('input', function() {
        const q = this.value.toLowerCase();
        document.querySelectorAll('.explorer-sidebar-list li').forEach(li => {
            const text = li.textContent.toLowerCase();
            li.style.display = (!q || text.includes(q)) ? '' : 'none';
        });
    });

    // ── Client-side search ─────────────────────────────────────────
    const searchInput = document.getElementById('explorer-search');
    // Search whichever grid is currently rendered: model cards or widgets
    const items = document.querySelectorAll('.explorer-card, .dashboard-widget');
    const modelCount = document.getElementById('explorer-model-count');
    const recordCount = document.getElementById('explorer-record-count');

    searchInput.addEventListener('input', function() {
        const q = this.value.toLowerCase();
        let visible = 0;
        let records = 0;
        items.forEach(item => {
            const text = (item.dataset.name || '') + ' ' +
                         (item.dataset.app || '') + ' ' +
                         (item.dataset.group || '');
            const match = !q || text.toLowerCase().includes(q);
            item.style.display = match ? '' : 'none';
            if (match) {
                visible++;
                records += parseInt(item.dataset.count || '0', 10);
            }
        });
        // Only update counts that exist on the current page
        if (modelCount) modelCount.textContent = visible;
        if (recordCount) recordCount.textContent = records.toLocaleString();
    });
})();
