/* Studio list/cards toggle.
 *
 * One markup, two layouts: every .studio-list switches between rows and a
 * card grid by class, so the two views can never show different data. The
 * choice is a per-viewer convenience kept in localStorage (never
 * load-bearing); ?view=cards|list overrides it for a single request.
 */
(function () {
    "use strict";
    var KEY = "smallstack.blog.studioView";

    function read() {
        var q = new URLSearchParams(window.location.search).get("view");
        if (q === "cards" || q === "list") { return q; }
        try { return window.localStorage.getItem(KEY) === "cards" ? "cards" : "list"; }
        catch (e) { return "list"; }
    }

    function apply(view) {
        document.querySelectorAll(".studio-list").forEach(function (list) {
            list.classList.toggle("is-cards", view === "cards");
        });
        document.querySelectorAll(".studio-viewswitch-btn").forEach(function (b) {
            b.setAttribute("aria-pressed", b.getAttribute("data-view") === view ? "true" : "false");
        });
    }

    function init() {
        apply(read());
        document.querySelectorAll(".studio-viewswitch-btn").forEach(function (b) {
            b.addEventListener("click", function () {
                var view = b.getAttribute("data-view");
                apply(view);
                try { window.localStorage.setItem(KEY, view); } catch (e) { /* ignore */ }
            });
        });
    }

    if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); }
    else { init(); }
})();
