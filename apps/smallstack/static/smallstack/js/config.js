// window.SMALLSTACK — the page's settings for theme.js, read from data-
// attributes on this script's own tag (base.html renders them), so the values
// arrive without an inline <script>. Must load before theme.js.
(function () {
    var d = (document.currentScript && document.currentScript.dataset) || {};
    function flag(v) { return v === 'true'; }
    window.SMALLSTACK = {
        userTheme: d.userTheme || null,
        userPalette: d.userPalette || null,
        colorPalette: d.colorPalette || '',
        isAuthenticated: flag(d.authenticated),
        sidebarEnabled: flag(d.sidebarEnabled),
        sidebarDefault: d.sidebarDefault || '',
        topbarNavEnabled: flag(d.topbarNavEnabled),
        urls: {
            themePreference: d.themeUrl || '',
            palettePreference: d.paletteUrl || ''
        }
    };
})();
