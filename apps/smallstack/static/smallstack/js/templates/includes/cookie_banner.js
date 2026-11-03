// Moved from apps/smallstack/templates/smallstack/includes/cookie_banner.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function() {
    if (!localStorage.getItem('cookie_consent')) {
        document.getElementById('cookie-banner').style.display = '';
    }
})();
function acceptCookies() {
    localStorage.setItem('cookie_consent', 'accepted');
    document.cookie = 'cookie_consent=accepted; path=/; max-age=31536000; SameSite=Lax';
    document.getElementById('cookie-banner').remove();
}
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { acceptCookies: window.acceptCookies });
