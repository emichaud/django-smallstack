// Moved from apps/smallstack/templates/smallstack/crud/includes/field_preview_modal.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function(){
    var modal = document.getElementById('fieldPreviewModal');
    if (!modal) return;
    var contentEl = document.getElementById('field-preview-content');
    var copyBtn = document.getElementById('fieldPreviewCopy');
    var tabs = modal.querySelectorAll('.field-preview-tab');

    window.closeFieldPreview = function() {
        modal.classList.remove('open');
        contentEl.innerHTML = '<p style="color: var(--body-quiet-color); text-align: center; padding: 2rem;">Loading&hellip;</p>';
    };

    /* Open modal when HTMX trigger is clicked */
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('.field-preview-trigger[hx-get]');
        if (trigger) {
            modal.classList.add('open');
        }
    });

    /* After HTMX swaps content, activate the detected format tab */
    document.addEventListener('htmx:afterSwap', function(e) {
        if (e.detail.target === contentEl) {
            var activeTab = contentEl.querySelector('.field-preview-tab-content:not([style*="display:none"])');
            if (activeTab) {
                var fmt = activeTab.dataset.format;
                tabs.forEach(function(t) {
                    t.classList.toggle('active', t.dataset.format === fmt);
                });
            }
            /* Reset copy button */
            copyBtn.classList.remove('copied');
            copyBtn.querySelector('span').textContent = 'Copy';
        }
    });

    /* Tab switching — show/hide pre-rendered content */
    tabs.forEach(function(tab) {
        tab.addEventListener('click', function() {
            var fmt = this.dataset.format;
            var panels = contentEl.querySelectorAll('.field-preview-tab-content');
            panels.forEach(function(p) {
                p.style.display = p.dataset.format === fmt ? '' : 'none';
            });
            tabs.forEach(function(t) {
                t.classList.toggle('active', t.dataset.format === fmt);
            });
            /* Reset copy button */
            copyBtn.classList.remove('copied');
            copyBtn.querySelector('span').textContent = 'Copy';
        });
    });

    /* Copy button — reads raw text from <template> tag */
    copyBtn.addEventListener('click', function() {
        var tpl = contentEl.querySelector('#field-preview-raw');
        var text = tpl ? tpl.content.textContent : '';
        navigator.clipboard.writeText(text).then(function() {
            copyBtn.classList.add('copied');
            copyBtn.querySelector('span').textContent = 'Copied';
            setTimeout(function() {
                copyBtn.classList.remove('copied');
                copyBtn.querySelector('span').textContent = 'Copy';
            }, 2000);
        });
    });

    /* Escape key */
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('open')) closeFieldPreview();
    });
})();
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { closeFieldPreview: window.closeFieldPreview });
