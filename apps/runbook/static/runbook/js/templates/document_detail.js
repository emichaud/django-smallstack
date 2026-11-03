// Moved from apps/runbook/templates/runbook/document_detail.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var documentDetailConfig = document.currentScript.dataset;

// Inject a hidden source form into the shared modal (same pattern as the New Page dialog).
function openFormModal(title, sourceId) {
    openStatModal(title);
    document.getElementById('stat-modal-body').innerHTML =
        document.getElementById(sourceId).innerHTML;
}

function toggleFocusMode() {
    var body = document.body;
    var btn = document.getElementById('focus-toggle');
    var label = document.getElementById('focus-label');
    var icon = document.getElementById('focus-icon');
    body.classList.toggle('runbook-focus-mode');
    var focused = body.classList.contains('runbook-focus-mode');
    label.textContent = focused ? 'Expand' : 'Focus';
    icon.innerHTML = focused
        ? '<path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>'
        : '<path d="M3 5v4h2V5h4V3H5c-1.1 0-2 .9-2 2zm2 10H3v4c0 1.1.9 2 2 2h4v-2H5v-4zm14 4h-4v2h4c1.1 0 2-.9 2-2v-4h-2v4zm0-16h-4v2h4v4h2V5c0-1.1-.9-2-2-2z"/>';
    // Focus temporarily collapses the SmallStack side menu; Expand restores it.
    // Guarded so it can't get out of sync: only close a sidebar that's open,
    // and on Expand only re-open the one focus itself closed AND that's still
    // closed (a manual toggle mid-focus wins). Non-persistent (persist=false),
    // and no-ops if there's no sidebar (custom theme / disabled).
    var sb = window.smallstackSidebar;
    if (focused) {
        if (sb && sb.getState() === 'open') {
            sb.setState('closed', false);
            body.dataset.focusClosedSidebar = '1';
        }
    } else {
        if (sb && body.dataset.focusClosedSidebar === '1' && sb.getState() === 'closed') {
            sb.setState('open', false);
        }
        delete body.dataset.focusClosedSidebar;
    }
}

/* -- Images panel: upload + copy markdown -------------------------------- */
(function() {
    var btn = document.getElementById('rb-img-upload-btn');
    if (!btn) { return; }
    var input = document.getElementById('rb-img-input');
    var grid = document.getElementById('rb-img-grid');
    var uploadUrl = documentDetailConfig.documentImageUploadUrl;
    var csrf = documentDetailConfig.csrfToken;

    var MAX_IMAGES = 10;
    var pending = 0;
    function setBusy(delta) {
        pending = Math.max(0, pending + delta);
        btn.disabled = pending > 0;
        btn.textContent = pending > 0 ? 'Uploading…' : 'Upload image';
    }

    btn.addEventListener('click', function() { input.click(); });
    input.addEventListener('change', function() {
        var files = Array.prototype.slice.call(this.files || []);
        if (files.length > MAX_IMAGES) {
            alert('You can upload up to ' + MAX_IMAGES + ' images at once — using the first ' + MAX_IMAGES + '.');
            files = files.slice(0, MAX_IMAGES);
        }
        files.forEach(uploadImage);
        this.value = '';
    });

    function uploadImage(file) {
        var fd = new FormData();
        fd.append('image', file, file.name || 'pasted-image.png');
        setBusy(1);
        fetch(uploadUrl, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd })
            .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
            .then(function(res) {
                setBusy(-1);
                if (!res.ok) { alert('Upload failed: ' + (res.data.error || 'unknown error')); return; }
                addTile(res.data);
            })
            .catch(function() {
                setBusy(-1);
                alert('Upload failed.');
            });
    }

    var ALIGN_OPTIONS =
        '<option value="">Inline</option>' +
        '<option value=".rb-img-center">Center</option>' +
        '<option value=".rb-img-left">Left</option>' +
        '<option value=".rb-img-right">Right</option>';
    var WIDTH_OPTIONS =
        '<option value="">Auto</option>' +
        '<option value=".rb-img-w-25">25%</option>' +
        '<option value=".rb-img-w-50">50%</option>' +
        '<option value=".rb-img-w-75">75%</option>' +
        '<option value=".rb-img-sm">Small (200px)</option>' +
        '<option value=".rb-img-md">Medium (400px)</option>' +
        '<option value=".rb-img-lg">Large (800px)</option>';

    function labeledSelect(label, cls, options) {
        return '<label style="flex:1;font-size:0.65rem;color:var(--body-quiet-color);">' + label +
            '<select class="' + cls + ' vTextField" style="width:100%;font-size:0.7rem;padding:2px 4px;">' +
            options + '</select></label>';
    }

    function addTile(d) {
        var empty = document.getElementById('rb-img-empty');
        if (empty) { empty.remove(); }
        var fig = document.createElement('figure');
        fig.className = 'rb-img-tile';
        fig.style.margin = '0';
        fig.setAttribute('data-url', d.url);
        fig.setAttribute('data-alt', '');
        fig.innerHTML =
            '<a href="' + d.url + '" target="_blank" rel="noopener">' +
            '<img src="' + d.url + '" style="width:100%;height:100px;object-fit:cover;' +
            'border-radius:var(--radius-sm);border:1px solid var(--card-border);"></a>' +
            '<div style="display:flex;gap:4px;margin-top:6px;">' +
            labeledSelect('Align', 'rb-img-align', ALIGN_OPTIONS) +
            labeledSelect('Size', 'rb-img-width', WIDTH_OPTIONS) +
            '</div>' +
            '<button type="button" class="btn-outline rb-img-copy" ' +
            'style="width:100%;margin-top:6px;font-size:0.75rem;">Copy Markdown</button>';
        grid.appendChild(fig);
    }

    function buildMarkdown(tile) {
        var url = tile.getAttribute('data-url');
        var alt = tile.getAttribute('data-alt') || '';
        var alignSel = tile.querySelector('.rb-img-align');
        var widthSel = tile.querySelector('.rb-img-width');
        // Both selects emit CSS class tokens (e.g. ".rb-img-center .rb-img-w-50").
        var classes = [];
        if (alignSel && alignSel.value) { classes.push(alignSel.value); }
        if (widthSel && widthSel.value) { classes.push(widthSel.value); }
        var suffix = classes.length ? '{: ' + classes.join(' ') + ' }' : '';
        return '![' + alt + '](' + url + ')' + suffix;
    }

    grid.addEventListener('click', function(e) {
        var b = e.target.closest('.rb-img-copy');
        if (!b) { return; }
        var tile = b.closest('.rb-img-tile');
        navigator.clipboard.writeText(buildMarkdown(tile)).then(function() {
            var old = b.textContent;
            b.textContent = 'Copied!';
            setTimeout(function() { b.textContent = old; }, 1200);
        });
    });
})();
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { toggleFocusMode: window.toggleFocusMode, openFormModal: window.openFormModal });
