// Moved from apps/explorer/templates/explorer/examples/classic_index.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    const body = document.getElementById('explorer-body');

    // ── View toggle ──
    const viewButtons = document.querySelectorAll('.explorer-view-toggle button');
    const viewKey = 'explorer-view';
    const savedView = localStorage.getItem(viewKey) || 'grid';

    function setView(view) {
        body.setAttribute('data-explorer-view', view);
        viewButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.view === view));
        localStorage.setItem(viewKey, view);
    }
    viewButtons.forEach(btn => btn.addEventListener('click', () => setView(btn.dataset.view)));
    setView(savedView);

    // ── Shared group-by + search logic ──
    function setupPanel(panelId, container, itemSelector, headerTag, colSpan) {
        const groupKey = 'explorer-groupby-' + panelId;
        const savedGroup = localStorage.getItem(groupKey) || 'none';
        const toggle = document.querySelector('.explorer-groupby-toggle[data-target="' + panelId + '"]');
        const searchInput = document.querySelector('input[data-search="' + panelId + '"]');
        const originalItems = Array.from(container.querySelectorAll(itemSelector));

        function clearHeaders() {
            container.querySelectorAll('.explorer-section-title').forEach(el => el.remove());
        }

        function buildGrouped(attr) {
            const groups = {};
            originalItems.forEach(item => {
                const key = item.getAttribute(attr);
                if (!groups[key]) groups[key] = [];
                groups[key].push(item);
            });
            const sorted = Object.keys(groups).sort((a, b) => a.localeCompare(b));
            sorted.forEach(key => {
                let header;
                if (headerTag === 'div') {
                    header = document.createElement('div');
                    header.className = 'explorer-section-title';
                    header.textContent = key;
                } else {
                    header = document.createElement('tr');
                    header.className = 'explorer-section-title';
                    const td = document.createElement('td');
                    td.colSpan = colSpan;
                    td.textContent = key;
                    header.appendChild(td);
                }
                container.appendChild(header);
                groups[key].forEach(item => container.appendChild(item));
            });
        }

        function applyGroupBy(mode) {
            if (toggle) {
                toggle.querySelectorAll('button').forEach(btn =>
                    btn.classList.toggle('active', btn.dataset.groupby === mode)
                );
            }
            localStorage.setItem(groupKey, mode);
            clearHeaders();
            if (mode === 'none') {
                originalItems.forEach(item => container.appendChild(item));
            } else {
                buildGrouped(mode === 'app' ? 'data-app' : 'data-group');
            }
            if (searchInput && searchInput.value) {
                applySearch(searchInput.value);
            }
        }

        function applySearch(query) {
            const q = query.toLowerCase();
            originalItems.forEach(item => {
                const text = (item.getAttribute('data-name') || '') + ' ' +
                             (item.getAttribute('data-app') || '') + ' ' +
                             (item.getAttribute('data-group') || '');
                item.style.display = text.toLowerCase().includes(q) ? '' : 'none';
            });
            container.querySelectorAll('.explorer-section-title').forEach(header => {
                let next = header.nextElementSibling;
                let hasVisible = false;
                while (next && !next.classList.contains('explorer-section-title')) {
                    if (next.style.display !== 'none') hasVisible = true;
                    next = next.nextElementSibling;
                }
                header.style.display = hasVisible ? '' : 'none';
            });
        }

        if (toggle) {
            toggle.querySelectorAll('button').forEach(btn =>
                btn.addEventListener('click', () => applyGroupBy(btn.dataset.groupby))
            );
        }
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                applySearch(this.value);
            });
        }
        applyGroupBy(savedGroup);
    }

    // Grid view (cards)
    const grid = document.getElementById('explorer-grid');
    if (grid) {
        setupPanel('grid', grid, '.explorer-card', 'div', 0);
    }

    // List view client-side search (filters the hand-rolled table rows)
    const listSearch = document.getElementById('explorer-list-search');
    if (listSearch) {
        listSearch.addEventListener('input', function() {
            const q = this.value.toLowerCase();
            document.querySelectorAll('.explorer-list-wrap .crud-table tbody tr').forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
        });
    }
})();
