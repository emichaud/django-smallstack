// Moved from apps/heartbeat/templates/heartbeat/dashboard.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function switchView(viewName, btn) {
    document.querySelectorAll('.view-panel').forEach(function(p) { p.classList.remove('active'); });
    document.querySelectorAll('.view-btn').forEach(function(b) { b.classList.remove('active'); });
    document.getElementById('view-' + viewName).classList.add('active');
    btn.classList.add('active');
}
function setActiveTab(btn) {
    document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
}
function copyJson() {
    var text = document.getElementById('json-content').textContent;
    navigator.clipboard.writeText(text);
    var btn = document.getElementById('copy-json-btn');
    btn.textContent = 'Copied!';
    setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { copyJson: window.copyJson, setActiveTab: window.setActiveTab, switchView: window.switchView });
