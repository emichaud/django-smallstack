// Moved from apps/heartbeat/templates/heartbeat/crud/monitoredendpoint_form.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var monitoredendpointFormConfig = document.currentScript.dataset;

(function () {
    var form = document.getElementById('ep-form');
    if (!form) return;
    // Mode toggle → swap field groups.
    form.querySelectorAll('input[name="mode"]').forEach(function (r) {
        r.addEventListener('change', function () { form.setAttribute('data-mode', r.value); });
    });
    // Live "/health/" preview.
    var urlInput = form.querySelector('#' + monitoredendpointFormConfig.urlFieldId);
    var preview = document.getElementById('health-preview');
    function updatePreview() {
        if (!urlInput || !preview) return;
        var v = (urlInput.value || '').trim().replace(/\/+$/, '');
        preview.textContent = v ? v + '/health/' : '<url>/health/';
    }
    if (urlInput) urlInput.addEventListener('input', updatePreview);
    updatePreview();
    // Verify button → probe /health/ (non-blocking).
    var btn = document.getElementById('verify-btn');
    var result = document.getElementById('verify-result');
    if (btn) btn.addEventListener('click', function () {
        var token = form.querySelector('[name=csrfmiddlewaretoken]').value;
        result.innerHTML = '<span style="color:var(--body-quiet-color)">Checking…</span>';
        fetch(monitoredendpointFormConfig.verifySmallstackUrl, {
            method: 'POST',
            headers: { 'X-CSRFToken': token, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'url=' + encodeURIComponent(urlInput.value || '')
        }).then(function (r) { return r.text(); })
          .then(function (html) { result.innerHTML = html; })
          .catch(function () { result.innerHTML = '<span class="verify-bad">Verification request failed.</span>'; });
    });
})();
