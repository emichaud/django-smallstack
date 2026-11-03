// Moved from apps/runbook/templates/runbook/dashboard.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Inject a hidden source form into the shared modal (same pattern as New Page).
function openFormModal(title, sourceId) {
    openStatModal(title);
    document.getElementById('stat-modal-body').innerHTML =
        document.getElementById(sourceId).innerHTML;
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { openFormModal: window.openFormModal });
