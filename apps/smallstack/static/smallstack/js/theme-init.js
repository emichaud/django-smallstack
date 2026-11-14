// Sets the theme and palette before first paint — load it as a plain, blocking
// <script src> in <head>, ahead of the stylesheets' first render. One file for
// every page shell (the admin base, public pages, auth, error pages), so the
// CSP needs no 'unsafe-inline'. Configured by data- attributes on its tag:
//
//   data-user-theme="…"                  the signed-in user's saved theme (empty when signed out)
//   data-user-palette="…"                the signed-in user's saved palette (empty when signed out)
//   data-palette="{{ color_palette }}"   the site's palette (a stored choice wins)
//   data-default-palette="django"        the fallback when neither is set
//   data-sidebar-no-transition           suppress the sidebar's open/close animation on load
//
// The order is theme.js's: the profile's choice, then this browser's, then the
// default. Reading the profile here too means a new browser opens in the saved
// theme even on a shell that loads theme.js late.
//
// Storage can be unavailable (private mode, blocked site data); the page then
// opens in the profile's theme, else dark, with the site's palette.
(function () {
    var root = document.documentElement;
    var cfg = (document.currentScript && document.currentScript.dataset) || {};
    var theme = null;
    var palette = null;
    try {
        theme = localStorage.getItem('smallstack-theme');
        palette = localStorage.getItem('smallstack-palette');
    } catch (e) { /* storage unavailable */ }
    root.setAttribute('data-theme', cfg.userTheme || theme || 'dark');
    palette = cfg.userPalette || palette || cfg.palette || cfg.defaultPalette;
    if (palette) root.setAttribute('data-palette', palette);
    if ('sidebarNoTransition' in cfg) root.classList.add('no-sidebar-transition');
})();
