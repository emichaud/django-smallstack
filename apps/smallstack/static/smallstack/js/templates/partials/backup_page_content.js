// Moved from apps/smallstack/templates/smallstack/partials/backup_page_content.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function switchBackupTab(tab) {
    var tabs = ['activity', 'files', 'config'];
    tabs.forEach(function(t) {
        var panel = document.getElementById('panel-' + t);
        var btn = document.getElementById('tab-' + t);
        if (t === tab) {
            panel.style.display = '';
            btn.classList.add('active');
        } else {
            panel.style.display = 'none';
            btn.classList.remove('active');
        }
    });
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { switchBackupTab: window.switchBackupTab });
