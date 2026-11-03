// Moved from apps/activity/templates/activity/includes/tab_bar.html (inline <script>) so the CSP needs no 'unsafe-inline'.
if (!window.ssActivateTab) {
    window.ssActivateTab = function (btn) {
        btn.closest('.tab-bar').querySelectorAll('.tab-btn').forEach(function (b) {
            var on = b === btn;
            b.classList.toggle('active', on);
            b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
    };
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { ssActivateTab: window.ssActivateTab });
