// Moved from apps/runbook/templates/runbook/document_edit_content.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var documentEditContentConfig = document.currentScript.dataset;

var previewActive = false;
var previewBtn = document.getElementById('preview-toggle');

function togglePreview() {
    var editor = document.getElementById('editor-panel');
    var preview = document.getElementById('preview-panel');
    previewActive = !previewActive;

    if (previewActive) {
        editor.style.display = 'none';
        preview.style.display = 'block';
        previewBtn.textContent = 'Edit';
        previewBtn.className = 'btn-primary';
        loadPreview();
    } else {
        editor.style.display = 'block';
        preview.style.display = 'none';
        previewBtn.textContent = 'Preview';
        previewBtn.className = 'btn-secondary';
    }
}

function loadPreview() {
    var content = document.getElementById('editor-textarea').value;
    var target = document.getElementById('preview-content');
    var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    target.innerHTML = '<p style="color: var(--body-quiet-color);">Loading preview...</p>';

    fetch(documentEditContentConfig.documentPreviewUrl, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'content=' + encodeURIComponent(content),
    })
    .then(function(response) { return response.text(); })
    .then(function(html) { target.innerHTML = html; })
    .catch(function() { target.innerHTML = '<p style="color: var(--error-fg, red);">Preview failed.</p>'; });
}

/* -- Editor text-size control (A− / A / A+), persisted to localStorage ---- */
(function() {
    var textarea = document.getElementById('editor-textarea');
    var dec = document.getElementById('rb-font-dec');
    if (!textarea || !dec) { return; }
    var previewContent = document.getElementById('preview-content');
    var KEY = 'rb-editor-font-size';
    var MIN = 0.75, MAX = 1.25, STEP = 0.05, DEFAULT = 0.9;
    var size = parseFloat(localStorage.getItem(KEY));
    if (!size || isNaN(size)) { size = DEFAULT; }

    function apply() {
        size = Math.min(MAX, Math.max(MIN, Math.round(size * 100) / 100));
        textarea.style.fontSize = size + 'rem';
        // Scale the rendered preview proportionally to its natural size.
        if (previewContent) { previewContent.style.fontSize = (size / DEFAULT).toFixed(3) + 'em'; }
        localStorage.setItem(KEY, size);
    }
    dec.addEventListener('click', function() { size -= STEP; apply(); });
    document.getElementById('rb-font-inc').addEventListener('click', function() { size += STEP; apply(); });
    document.getElementById('rb-font-reset').addEventListener('click', function() { size = DEFAULT; apply(); });
    apply();
})();

/* Tab key inserts spaces instead of changing focus */
document.getElementById('editor-textarea').addEventListener('keydown', function(e) {
    if (e.key === 'Tab') {
        e.preventDefault();
        var start = this.selectionStart;
        var end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 4;
    }
});

/* -- Image upload: file picker + clipboard paste -------------------------- */
var rbTextarea = document.getElementById('editor-textarea');
var rbCsrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
var rbUploadUrl = documentEditContentConfig.documentImageUploadUrl;
var rbUploadSeq = 0;

function rbInsertAtCursor(text) {
    var start = rbTextarea.selectionStart;
    var end = rbTextarea.selectionEnd;
    rbTextarea.value = rbTextarea.value.substring(0, start) + text + rbTextarea.value.substring(end);
    rbTextarea.selectionStart = rbTextarea.selectionEnd = start + text.length;
    rbTextarea.focus();
}

function rbUploadImage(file) {
    if (!file) { return; }
    /* Unique placeholder so the async result lands where the upload started. */
    var token = '![uploading…](#rb-upload-' + (rbUploadSeq++) + ')';
    rbInsertAtCursor(token);

    var fd = new FormData();
    fd.append('image', file, file.name || 'pasted-image.png');

    fetch(rbUploadUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': rbCsrf },
        body: fd,
    })
    .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
    .then(function(res) {
        if (res.ok) {
            rbTextarea.value = rbTextarea.value.replace(token, res.data.markdown);
        } else {
            rbTextarea.value = rbTextarea.value.replace(token, '');
            alert('Image upload failed: ' + (res.data.error || 'unknown error'));
        }
    })
    .catch(function() {
        rbTextarea.value = rbTextarea.value.replace(token, '');
        alert('Image upload failed.');
    });
}

var RB_MAX_IMAGES = 10;
function rbUploadFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) { return; }
    if (files.length > RB_MAX_IMAGES) {
        alert('You can upload up to ' + RB_MAX_IMAGES + ' images at once — using the first ' + RB_MAX_IMAGES + '.');
        files = files.slice(0, RB_MAX_IMAGES);
    }
    files.forEach(function(f) { rbUploadImage(f); });
}

var rbFileInput = document.getElementById('image-file-input');
document.getElementById('insert-image-btn').addEventListener('click', function() {
    rbFileInput.click();
});
rbFileInput.addEventListener('change', function() {
    rbUploadFiles(this.files);
    this.value = '';  /* reset so the same file(s) can be picked again */
});

rbTextarea.addEventListener('paste', function(e) {
    var items = (e.clipboardData || window.clipboardData).items;
    if (!items) { return; }
    for (var i = 0; i < items.length; i++) {
        if (items[i].type.indexOf('image') === 0) {
            e.preventDefault();
            rbUploadImage(items[i].getAsFile());
            return;
        }
    }
});
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { togglePreview: window.togglePreview });
