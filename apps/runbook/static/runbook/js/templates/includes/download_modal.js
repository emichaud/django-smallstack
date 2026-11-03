// Moved from apps/runbook/templates/runbook/includes/download_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function confirmDownload(el) {
    var url = el.getAttribute('data-download-url');
    var desc = el.getAttribute('data-download-desc');
    document.getElementById('download-desc').textContent = desc;
    document.getElementById('download-link').href = url;
    document.getElementById('download-link').onclick = function() {
        setTimeout(downloadModalClose, 300);
    };
    document.getElementById('download-modal').style.display = 'flex';
}

function downloadModalClose() {
    document.getElementById('download-modal').style.display = 'none';
}

document.addEventListener('click', function(e) {
    if (e.target.id === 'download-modal') downloadModalClose();
});
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('download-modal').style.display === 'flex') {
        downloadModalClose();
    }
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { confirmDownload: window.confirmDownload, downloadModalClose: window.downloadModalClose });
