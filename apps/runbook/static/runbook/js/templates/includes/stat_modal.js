// Moved from apps/runbook/templates/runbook/includes/stat_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// openStatModal / closeStatModal (and Escape, the backdrop, focus) are theme.js's:
// this file used to redefine them, which replaced theme.js's on runbook pages.

/* Client-side column sorting for stat drill-down tables (.rb-sortable).
   Delegated on document so it works on htmx-injected content. */
(function() {
    function typed(s) {
        s = s.trim();
        if (/[A-Za-z]{3,}\s+\d{1,2},?\s+\d{4}/.test(s)) {          // "Jul 10, 2026"
            var d = Date.parse(s);
            if (!isNaN(d)) return { t: 'd', v: d };
        }
        var m = s.replace(/,/g, '').match(/-?\d+(\.\d+)?/);          // "v2", "3 images", "12"
        if (m && /^[v#$]?\s*-?\d/.test(s)) return { t: 'n', v: parseFloat(m[0]) };
        return { t: 's', v: s.toLowerCase() };
    }
    document.addEventListener('click', function(e) {
        var th = e.target.closest('.rb-sortable thead th');
        if (!th) return;
        var table = th.closest('table');
        var heads = table.querySelectorAll('thead th');
        var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
        var tbody = table.querySelector('tbody');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        if (rows.length <= 1 && (!rows[0] || rows[0].children.length < heads.length)) return;  // empty msg

        var asc = th.getAttribute('data-sort') !== 'asc';
        heads.forEach(function(h) {
            h.removeAttribute('data-sort');
            var a = h.querySelector('.rb-sort-arrow'); if (a) a.textContent = '';
        });
        th.setAttribute('data-sort', asc ? 'asc' : 'desc');
        var arrow = th.querySelector('.rb-sort-arrow');
        if (arrow) arrow.textContent = asc ? ' ▲' : ' ▼';

        function cell(row) { var td = row.children[idx]; return td ? td.textContent : ''; }
        rows.sort(function(a, b) {
            var A = typed(cell(a)), B = typed(cell(b)), cmp;
            if (A.t === B.t && A.t !== 's') { cmp = A.v < B.v ? -1 : (A.v > B.v ? 1 : 0); }
            else { cmp = cell(a).trim().toLowerCase().localeCompare(cell(b).trim().toLowerCase()); }
            return asc ? cmp : -cmp;
        });
        rows.forEach(function(r) { tbody.appendChild(r); });
    });
})();
