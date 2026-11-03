// Moved from apps/smallstack/templates/smallstack/crud/includes/delete_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var deleteModalConfig = document.currentScript.dataset;

let _crudDeleteRow = null;
let _crudDeleteUrl = null;

function crudDeleteModal(el, name) {
    var errorEl = document.getElementById('crud-delete-error');
    var btn = document.getElementById('crud-delete-confirm');
    var cancelBtn = document.querySelector('.crud-modal-btn-cancel');
    document.getElementById('crud-delete-title').textContent = 'Confirm Delete';
    document.getElementById('crud-delete-name').textContent = name;
    errorEl.style.display = 'none';
    errorEl.textContent = '';
    btn.style.display = '';
    btn.disabled = false;
    btn.textContent = 'Delete';
    cancelBtn.textContent = 'Cancel';
    _crudDeleteUrl = el.getAttribute('data-delete-url');
    _crudDeleteRow = el.closest('tr');
    document.getElementById('crud-delete-modal').style.display = 'flex';
}

function crudDeleteModalClose() {
    document.getElementById('crud-delete-modal').style.display = 'none';
    _crudDeleteRow = null;
    _crudDeleteUrl = null;
}

function crudDeleteConfirm() {
    if (!_crudDeleteUrl) return;
    var btn = document.getElementById('crud-delete-confirm');
    btn.disabled = true;
    btn.textContent = 'Deleting…';

    fetch(_crudDeleteUrl, {
        method: 'POST',
        headers: {
            'X-CSRFToken': deleteModalConfig.csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
        },
        redirect: 'manual',
    }).then(function(resp) {
        if (resp.ok || resp.type === 'opaqueredirect') {
            // Success — remove row or reload
            if (_crudDeleteRow) {
                // Hold the row: crudDeleteModalClose() below clears _crudDeleteRow
                // before the fade finishes.
                var row = _crudDeleteRow;
                row.style.transition = 'opacity 0.3s';
                row.style.opacity = '0';
                setTimeout(function() { row.remove(); }, 300);
                crudDeleteModalClose();
            } else {
                var listUrl = document.querySelector('[data-list-url]');
                window.location.href = listUrl
                    ? listUrl.getAttribute('data-list-url')
                    : window.location.pathname.replace(/[^/]+\/$/, '');
            }
        } else {
            // Error — show message, hide delete button, change cancel to close
            return resp.text().then(function(msg) {
                var errorEl = document.getElementById('crud-delete-error');
                document.getElementById('crud-delete-title').textContent = 'Cannot Delete';
                errorEl.textContent = msg || 'Delete failed.';
                errorEl.style.display = 'block';
                btn.style.display = 'none';
                document.querySelector('.crud-modal-btn-cancel').textContent = 'Close';
            });
        }
    }).catch(function() {
        var errorEl = document.getElementById('crud-delete-error');
        errorEl.textContent = 'Network error — please try again.';
        errorEl.style.display = 'block';
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = 'Delete';
    });
}

// Close modal on overlay click
document.addEventListener('click', function(e) {
    if (e.target.id === 'crud-delete-modal') crudDeleteModalClose();
});

// Close on Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') crudDeleteModalClose();
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { crudDeleteConfirm: window.crudDeleteConfirm, crudDeleteModalClose: window.crudDeleteModalClose, crudDeleteModal: window.crudDeleteModal });
