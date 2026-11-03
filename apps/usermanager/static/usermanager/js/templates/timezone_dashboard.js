// Moved from apps/usermanager/templates/usermanager/timezone_dashboard.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag; the rows as a JSON block.
var timezoneDashboardConfig = document.currentScript.dataset;

// Live clocks
function ampm(date, tz) {
    var opts = {hour: 'numeric', minute: '2-digit', hour12: true};
    if (tz) opts.timeZone = tz;
    return date.toLocaleTimeString('en-US', opts);
}
function tzAbbr(date, tz) {
    // Get timezone abbreviation like "EDT", "CET", "UTC"
    var opts = {timeZoneName: 'short'};
    if (tz) opts.timeZone = tz;
    var parts = date.toLocaleTimeString('en-US', opts).split(' ');
    return parts[parts.length - 1]; // Last part is the abbreviation
}
function updateClocks() {
    var now = new Date();
    var dateOpts = {weekday: 'long', year: 'numeric', month: 'short', day: 'numeric'};

    // Local clock
    document.getElementById('clock-local').textContent = now.toLocaleTimeString('en-US', {hour12: false});
    document.getElementById('clock-local-ampm').textContent = ampm(now) + ' ' + tzAbbr(now);
    document.getElementById('clock-local-date').textContent = now.toLocaleDateString('en-US', dateOpts);
    document.getElementById('clock-local-tz').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;

    // UTC clock
    document.getElementById('clock-utc').textContent = now.toLocaleTimeString('en-US', {hour12: false, timeZone: 'UTC'});
    document.getElementById('clock-utc-ampm').textContent = ampm(now, 'UTC') + ' UTC';
    document.getElementById('clock-utc-date').textContent = now.toLocaleDateString('en-US', Object.assign({timeZone: 'UTC'}, dateOpts));

    // Server clock
    var serverTz = timezoneDashboardConfig.serverTz;
    try {
        document.getElementById('clock-server').textContent = now.toLocaleTimeString('en-US', {hour12: false, timeZone: serverTz});
        document.getElementById('clock-server-ampm').textContent = ampm(now, serverTz) + ' ' + tzAbbr(now, serverTz);
        document.getElementById('clock-server-date').textContent = now.toLocaleDateString('en-US', Object.assign({timeZone: serverTz}, dateOpts));
    } catch(e) {}
}
updateClocks();
setInterval(updateClocks, 1000);

// Filters — uses data attributes on table rows
(function() {
    // Stamp data attributes on table rows for filtering + live time updates
    var rows = document.querySelectorAll('#tz-table-wrapper .crud-table tbody tr');
    // Data matches table order (sorted by offset, then username in the view)
    var sortedData = JSON.parse(document.getElementById('tz-rows').textContent);

    rows.forEach(function(row, i) {
        if (sortedData[i]) {
            row.dataset.workday = sortedData[i].workday;
            row.dataset.staff = sortedData[i].staff;
            row.dataset.region = sortedData[i].region;
            row.dataset.tz = sortedData[i].tz;
        }
    });

    // Live-update local time cells in the table
    function updateTableTimes() {
        var now = new Date();
        rows.forEach(function(row) {
            var tz = row.dataset.tz;
            if (!tz) return;
            // Find the "Local Time" cell (3rd column, index 2)
            var cell = row.cells[2];
            if (!cell) return;
            try {
                var timeStr = now.toLocaleTimeString('en-US', {
                    hour: 'numeric', minute: '2-digit', hour12: true, timeZone: tz
                });
                var abbrStr = tzAbbr(now, tz);
                cell.innerHTML = '<span style="font-weight:600;font-variant-numeric:tabular-nums;">' +
                    timeStr + ' ' + abbrStr + '</span>';
            } catch(e) {}
        });
    }
    updateTableTimes();
    setInterval(updateTableTimes, 1000);

    document.querySelectorAll('.tz-filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.tz-filter-btn').forEach(function(b) { b.classList.remove('active'); });
            this.classList.add('active');
            var filter = this.dataset.filter;

            rows.forEach(function(row) {
                var show = true;
                if (filter === 'working') show = row.dataset.workday === 'true';
                else if (filter === 'off') show = row.dataset.workday === 'false';
                else if (filter === 'staff') show = row.dataset.staff === 'true';
                else if (filter.startsWith('region-')) show = row.dataset.region === filter.replace('region-', '');
                row.style.display = show ? '' : 'none';
            });
        });
    });
})();
