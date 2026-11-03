// Moved from apps/smallstack/templates/smallstack/starter.html (inline <script>) so the CSP needs no 'unsafe-inline'.
{# Tab switching (for .tab-bar / .tab-btn) #}
function switchTab(e, tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    e.currentTarget.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');
}

{# Filter toggle switching (for .filter-toggles) #}
function showFilterTab(tab) {
    document.querySelectorAll('.filter-toggle').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    {# Show/hide corresponding tables or panels by id="tab-{name}" #}
    document.querySelectorAll('[id^="tab-"]').forEach(function(el) {
        el.style.display = el.id === 'tab-' + tab ? '' : 'none';
    });
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { showFilterTab: window.showFilterTab, switchTab: window.switchTab });
