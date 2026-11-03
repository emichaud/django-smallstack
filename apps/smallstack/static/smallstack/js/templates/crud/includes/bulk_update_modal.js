// Moved from apps/smallstack/templates/smallstack/crud/includes/bulk_update_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var bulkUpdateModalConfig = document.currentScript.dataset;

function bulkUpdatePrompt() {
    var ids = window.bulkGetSelectedIds();
    if (!ids.length) return;
    document.getElementById('bulk-update-count').textContent = ids.length;
    document.getElementById('bulk-update-title').textContent = 'Bulk Update';
    var resultEl = document.getElementById('bulk-update-result');
    resultEl.style.display = 'none';
    resultEl.innerHTML = '';
    var btn = document.getElementById('bulk-update-confirm');
    btn.style.display = '';
    btn.disabled = false;
    btn.textContent = 'Update All';
    document.querySelector('#bulk-update-modal .crud-modal-btn-cancel').textContent = 'Cancel';

    // Fetch the bulk update form
    fetch(bulkUpdateModalConfig.bulkUrl + 'update-form/', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function(resp) {
        if (!resp.ok) {
            document.getElementById('bulk-update-fields').innerHTML = '<p style="color: #dc3545;">Failed to load update form.</p>';
            return;
        }
        return resp.text();
    }).then(function(html) {
        if (html) document.getElementById('bulk-update-fields').innerHTML = html;
    });

    document.getElementById('bulk-update-modal').style.display = 'flex';
}

function bulkUpdateModalClose() {
    document.getElementById('bulk-update-modal').style.display = 'none';
}

function bulkUpdateConfirm() {
    var ids = window.bulkGetSelectedIds();
    if (!ids.length) return;

    // Collect checked fields and their values
    var fields = {};
    document.querySelectorAll('#bulk-update-fields .bulk-field-toggle').forEach(function(cb) {
        if (cb.checked) {
            var fieldName = cb.getAttribute('data-field');
            var input = document.querySelector('#bulk-update-fields [name="bulk_' + fieldName + '"]');
            if (input) {
                if (input.type === 'checkbox') {
                    fields[fieldName] = input.checked ? 'true' : 'false';
                } else {
                    fields[fieldName] = input.value;
                }
            }
        }
    });

    if (Object.keys(fields).length === 0) {
        var resultEl = document.getElementById('bulk-update-result');
        resultEl.innerHTML = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #f0ad4e 12%, var(--body-bg)); color: #f0ad4e;">Select at least one field to update.</div>';
        resultEl.style.display = 'block';
        return;
    }

    var btn = document.getElementById('bulk-update-confirm');
    btn.disabled = true;
    btn.textContent = 'Updating\u2026';

    fetch(bulkUpdateModalConfig.bulkUrl, {
        method: 'POST',
        headers: {
            'X-CSRFToken': bulkUpdateModalConfig.csrfToken,
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ action: 'update', ids: ids, fields: fields }),
    }).then(function(resp) {
        return resp.json();
    }).then(function(data) {
        var resultEl = document.getElementById('bulk-update-result');
        if (data.error) {
            resultEl.innerHTML = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">' + data.error + '</div>';
            resultEl.style.display = 'block';
            btn.disabled = false;
            btn.textContent = 'Update All';
            return;
        }

        var updatedIds = data.updated || [];
        var errors = data.errors || {};
        var errorKeys = Object.keys(errors);

        if (errorKeys.length === 0) {
            // Complete success — reload the list
            bulkUpdateModalClose();
            window.bulkClearAll();
            // Refresh list content
            var listContent = document.getElementById('crud-list-content');
            if (listContent && window.htmx) {
                htmx.trigger(listContent, 'htmx:load');
                location.reload();
            } else {
                location.reload();
            }
        } else {
            var html = '';
            if (updatedIds.length > 0) {
                html += '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #28a745 12%, var(--body-bg)); color: #28a745; margin-bottom: 0.5rem;"><strong>' + data.message + '</strong></div>';
            }
            html += '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">';
            html += '<ul style="margin: 0; padding-left: 1.2rem; font-size: 0.82rem;">';
            errorKeys.forEach(function(pk) {
                var err = errors[pk];
                if (typeof err === 'object') {
                    var msgs = [];
                    Object.keys(err).forEach(function(f) { msgs.push(f + ': ' + err[f].join(', ')); });
                    html += '<li>ID ' + pk + ': ' + msgs.join('; ') + '</li>';
                } else {
                    html += '<li>ID ' + pk + ': ' + err + '</li>';
                }
            });
            html += '</ul></div>';
            resultEl.innerHTML = html;
            resultEl.style.display = 'block';
            if (updatedIds.length > 0) {
                btn.style.display = 'none';
                document.querySelector('#bulk-update-modal .crud-modal-btn-cancel').textContent = 'Close';
            } else {
                btn.disabled = false;
                btn.textContent = 'Update All';
            }
        }
    }).catch(function() {
        var resultEl = document.getElementById('bulk-update-result');
        resultEl.innerHTML = '<div style="padding: 0.6rem 0.9rem; border-radius: 4px; background: color-mix(in srgb, #dc3545 12%, var(--body-bg)); color: #dc3545;">Network error \u2014 please try again.</div>';
        resultEl.style.display = 'block';
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = 'Update All';
    });
}

// Close on overlay click
document.addEventListener('click', function(e) {
    if (e.target.id === 'bulk-update-modal') bulkUpdateModalClose();
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { bulkUpdatePrompt: window.bulkUpdatePrompt, bulkUpdateConfirm: window.bulkUpdateConfirm, bulkUpdateModalClose: window.bulkUpdateModalClose });

// Ticking a field's "update this" box reveals its input. Delegated, because the
// field list arrives later (fetched into #bulk-update-fields with innerHTML).
document.addEventListener('change', function (e) {
    var cb = e.target;
    if (!cb.classList || !cb.classList.contains('bulk-field-toggle') || !cb.closest('#bulk-update-fields')) return;
    var row = cb.closest('.bulk-field-row');
    var widget = row && row.querySelector('.bulk-field-widget');
    if (widget) widget.style.display = cb.checked ? 'block' : 'none';
});
