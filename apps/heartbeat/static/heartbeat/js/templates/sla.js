// Moved from apps/heartbeat/templates/heartbeat/sla.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function slaModalOpen() {
    document.getElementById('sla-confirm-modal').style.display = 'flex';
}
function slaModalClose() {
    document.getElementById('sla-confirm-modal').style.display = 'none';
}
function slaModalConfirm() {
    slaModalClose();
    document.querySelector('.sla-config-form form').submit();
}
document.addEventListener('click', function(e) {
    if (e.target.id === 'sla-confirm-modal') slaModalClose();
});
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') slaModalClose();
});

// SLA / How It Works tabs
document.querySelectorAll('.sla-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
        var card = tab.closest('.sla-tab-card');
        card.querySelectorAll('.sla-tab').forEach(function (t) {
            var on = t === tab;
            t.classList.toggle('active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        card.querySelectorAll('.sla-tab-panel').forEach(function (p) {
            p.hidden = p.dataset.panel !== tab.dataset.tab;
        });
    });
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { slaModalClose: window.slaModalClose, slaModalConfirm: window.slaModalConfirm, slaModalOpen: window.slaModalOpen });
