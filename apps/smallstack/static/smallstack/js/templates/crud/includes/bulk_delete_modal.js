// Moved from apps/smallstack/templates/smallstack/crud/includes/bulk_delete_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var bulkDeleteModalConfig = document.currentScript.dataset;

function bulkDeletePrompt() {
    var ids = window.bulkGetSelectedIds();
    if (!ids.length) return;
    document.getElementById('bulk-delete-count').textContent = ids.length;
    document.getElementById('bulk-delete-title').textContent = 'Confirm Bulk Delete';
    var resultEl = document.getElementById('bulk-delete-result');
    resultEl.style.display = 'none';
    resultEl.innerHTML = '';
    var btn = document.getElementById('bulk-delete-confirm');
    btn.style.display = '';
    btn.disabled = false;
    btn.textContent = 'Delete All';
    document.querySelector('#bulk-delete-modal .crud-modal-btn-cancel').textContent = 'Cancel';
    document.getElementById('bulk-delete-modal').style.display = 'flex';
}

function bulkDeleteModalClose() {
    document.getElementById('bulk-delete-modal').style.display = 'none';
}

function bulkDeleteConfirm() {
    var ids = window.bulkGetSelectedIds();
    if (!ids.length) return;
    var btn = document.getElementById('bulk-delete-confirm');
    btn.disabled = true;
    btn.textContent = 'Deleting\u2026';

    fetch(bulkDeleteModalConfig.bulkUrl, {
        method: 'POST',
        headers: {
            'X-CSRFToken': bulkDeleteModalConfig.csrfToken,
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ action: 'delete', ids: ids }),
    }).then(function(resp) {
        return resp.json();
    }).then(function(data) {
        var resultEl = document.getElementById('bulk-delete-result');
        if (data.error) {
            resultEl.innerHTML = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">' + data.error + '</div>';
            resultEl.style.display = 'block';
            btn.disabled = false;
            btn.textContent = 'Delete All';
            return;
        }

        var deletedIds = data.deleted || [];
        var errors = data.errors || {};
        var errorKeys = Object.keys(errors);

        // Remove deleted IDs from selection
        window.bulkRemoveIds(deletedIds);

        if (errorKeys.length === 0) {
            // Complete success — reload to reflect updated list/pagination
            bulkDeleteModalClose();
            window.location.reload();
            return;
        } else {
            // Partial failure
            var html = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">';
            html += '<strong>' + data.message + '</strong>';
            html += '<ul style="margin: 0.5rem 0 0; padding-left: 1.2rem; font-size: 0.82rem;">';
            errorKeys.forEach(function(pk) {
                html += '<li>ID ' + pk + ': ' + errors[pk] + '</li>';
            });
            html += '</ul></div>';
            resultEl.innerHTML = html;
            resultEl.style.display = 'block';
            btn.style.display = 'none';
            document.querySelector('#bulk-delete-modal .crud-modal-btn-cancel').textContent = 'Close';
        }
    }).catch(function() {
        var resultEl = document.getElementById('bulk-delete-result');
        resultEl.innerHTML = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">Network error \u2014 please try again.</div>';
        resultEl.style.display = 'block';
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = 'Delete All';
    });
}

// Close on overlay click
document.addEventListener('click', function(e) {
    if (e.target.id === 'bulk-delete-modal') bulkDeleteModalClose();
});
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('bulk-delete-modal').style.display !== 'none') {
        bulkDeleteModalClose();
    }
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { bulkDeletePrompt: window.bulkDeletePrompt, bulkDeleteConfirm: window.bulkDeleteConfirm, bulkDeleteModalClose: window.bulkDeleteModalClose });
