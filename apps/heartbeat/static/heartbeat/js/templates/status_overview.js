// Moved from apps/heartbeat/templates/heartbeat/status_overview.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
    var modal = document.getElementById('add-monitor-modal');
    var body = document.getElementById('add-monitor-body');
    var titleEl = document.getElementById('am-title');
    if (!modal) return;

    // innerHTML doesn't execute <script> tags — re-create them so injected form JS runs.
    function setBody(html) {
        body.innerHTML = html;
        body.querySelectorAll('script').forEach(function (old) {
            var s = document.createElement('script');
            if (old.src) s.src = old.src; else s.textContent = old.textContent;
            old.parentNode.replaceChild(s, old);
        });
    }

    window.openAddMonitorModal = function (url, title) {
        titleEl.textContent = title || 'Add monitor';
        body.innerHTML = '<p class="am-loading">Loading&hellip;</p>';
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.text(); })
            .then(setBody)
            .catch(function () { body.innerHTML = '<p class="am-loading">Couldn’t load the form.</p>'; });
    };

    window.closeAddMonitorModal = function () {
        modal.classList.remove('open');
        document.body.style.overflow = '';
        body.innerHTML = '';
    };

    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('[data-add-monitor]');
        if (trigger) {
            e.preventDefault();
            window.openAddMonitorModal(trigger.getAttribute('href'), trigger.getAttribute('data-title'));
            return;
        }
        if (e.target === modal) { window.closeAddMonitorModal(); return; }
        // Cancel inside the modal closes instead of navigating away.
        if (e.target.closest('#add-monitor-body a.btn-cancel')) { e.preventDefault(); window.closeAddMonitorModal(); }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && modal.classList.contains('open')) window.closeAddMonitorModal();
    });

    // Submit the embedded form via AJAX; a redirect = success (reload to show it).
    body.addEventListener('submit', function (e) {
        var form = e.target.closest('form');
        if (!form) return;
        e.preventDefault();
        var btn = form.querySelector('.btn-save') || form.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            body: new FormData(form),
            credentials: 'same-origin',
        }).then(function (r) {
            if (r.redirected) { location.reload(); return null; }  // created → CreateView redirected
            return r.text();
        }).then(function (html) {
            if (html != null) setBody(html);  // re-render with validation errors
        }).catch(function () {
            if (btn) btn.disabled = false;
        });
    });
})();
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { closeAddMonitorModal: window.closeAddMonitorModal });
