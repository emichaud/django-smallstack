// Moved from apps/runbook/templates/runbook/runbook_detail.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Inject a hidden source form into the shared modal (same pattern as the stat cards).
function openFormModal(title, sourceId) {
    openStatModal(title);
    document.getElementById('stat-modal-body').innerHTML =
        document.getElementById(sourceId).innerHTML;
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { openFormModal: window.openFormModal });
