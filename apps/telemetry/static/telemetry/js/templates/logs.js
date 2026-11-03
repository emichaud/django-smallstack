// Moved from apps/telemetry/templates/telemetry/logs.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function toggleLogDetail(button) {
    var row = document.getElementById(button.getAttribute('aria-controls'));
    if (!row) { return; }
    var expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    row.hidden = expanded;
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { toggleLogDetail: window.toggleLogDetail });
