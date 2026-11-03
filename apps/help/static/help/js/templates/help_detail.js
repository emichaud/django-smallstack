// Moved from apps/help/templates/help/help_detail.html (inline <script>) so the CSP needs no 'unsafe-inline'.
function toggleFocusMode() {
    var body = document.body;
    var btn = document.getElementById('focus-toggle');
    var label = document.getElementById('focus-label');
    var icon = document.getElementById('focus-icon');
    body.classList.toggle('help-focus-mode');
    var focused = body.classList.contains('help-focus-mode');
    label.textContent = focused ? 'Expand' : 'Focus';
    icon.innerHTML = focused
        ? '<path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>'
        : '<path d="M3 5v4h2V5h4V3H5c-1.1 0-2 .9-2 2zm2 10H3v4c0 1.1.9 2 2 2h4v-2H5v-4zm14 4h-4v2h4c1.1 0 2-.9 2-2v-4h-2v4zm0-16h-4v2h4v4h2V5c0-1.1-.9-2-2-2z"/>';
    // Focus temporarily collapses the SmallStack side menu; Expand restores it.
    // Guarded so it can't get out of sync: only close a sidebar that's open, and
    // on Expand only re-open the one focus itself closed AND that's still closed
    // (a manual toggle mid-focus wins). Non-persistent; no-ops with no sidebar.
    var sb = window.smallstackSidebar;
    if (focused) {
        btn.style.background = 'color-mix(in srgb, var(--primary) 25%, var(--body-bg))';
        btn.style.borderColor = 'var(--primary)';
        if (sb && sb.getState() === 'open') {
            sb.setState('closed', false);
            body.dataset.focusClosedSidebar = '1';
        }
    } else {
        btn.style.background = 'color-mix(in srgb, var(--primary) 10%, var(--body-bg))';
        btn.style.borderColor = 'color-mix(in srgb, var(--primary) 40%, transparent)';
        if (sb && body.dataset.focusClosedSidebar === '1' && sb.getState() === 'closed') {
            sb.setState('open', false);
        }
        delete body.dataset.focusClosedSidebar;
    }
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { toggleFocusMode: window.toggleFocusMode });
