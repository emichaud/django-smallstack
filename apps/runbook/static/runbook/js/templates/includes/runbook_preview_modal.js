// Moved from apps/runbook/templates/runbook/includes/runbook_preview_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function openRunbookPreview(name) {
    document.getElementById('runbook-preview-title').textContent = name;
    document.getElementById('runbook-preview-modal').classList.add('open');
}
function closeRunbookPreview() {
    document.getElementById('runbook-preview-modal').classList.remove('open');
}
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeRunbookPreview(); }
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { closeRunbookPreview: window.closeRunbookPreview, openRunbookPreview: window.openRunbookPreview });
