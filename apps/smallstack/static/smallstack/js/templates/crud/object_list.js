// Moved from apps/smallstack/templates/smallstack/crud/object_list.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var objectListConfig = document.currentScript.dataset;

(function() {
    var key = 'ss_display_' + objectListConfig.urlBase;
    document.querySelectorAll('.display-palette-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            localStorage.setItem(key, this.dataset.display);
            document.querySelectorAll('.display-palette-btn').forEach(function(b) {
                b.classList.remove('active');
            });
            this.classList.add('active');
        });
    });
    var params = new URLSearchParams(window.location.search);
    if (!params.has('display')) {
        var saved = localStorage.getItem(key);
        if (saved && saved !== objectListConfig.activeDisplay) {
            params.set('display', saved);
            window.location.replace(window.location.pathname + '?' + params.toString());
        }
    }
})();
