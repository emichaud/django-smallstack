/**
 * Where a card's HTML lands, the page says so.
 *
 * A card type that draws with a script (a chart library) needs to mount on
 * every surface that shows cards, and those arrive in different ways: a
 * dashboard's cells and the components gallery over htmx, an embed eagerly
 * in the page, the builder's live preview and the Edit card dialog by hand.
 * This script, written by {% component_media %} ahead of every card type's
 * own files, turns all of them into one event:
 *
 *     document.addEventListener("dashboards:card-drawn", function (ev) {
 *         mountCharts(ev.target);   // the element that now holds the card's HTML
 *     });
 *
 * The event bubbles, fires once per drawn card, and never fires for a cell
 * that is still loading. SmallStackDashboards.cardDrawn(el) fires it for
 * HTML a script put somewhere itself.
 */
(function () {
    "use strict";
    var HOLDERS = ".dash-cell-body, .cc-preview, .cl-peek, #cb-preview";
    var PENDING = ".dash-cell-loading, .cc-ghost, .cc-loading";

    function drawn(el) {
        if (!el || !el.children.length || el.querySelector(PENDING)) return;
        el.dispatchEvent(new CustomEvent("dashboards:card-drawn", { bubbles: true }));
    }
    function drawnIn(root) {
        if (!root) return;
        if (root.matches && root.matches(HOLDERS)) { drawn(root); return; }
        if (!root.querySelectorAll) return;
        root.querySelectorAll(HOLDERS).forEach(drawn);
    }

    document.addEventListener("htmx:afterSettle", function (ev) {
        drawnIn((ev.detail && ev.detail.target) || ev.target);
    });
    function ready() { drawnIn(document); }   // cards already in the page (an eager embed)
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
    else ready();

    window.SmallStackDashboards = window.SmallStackDashboards || {};
    window.SmallStackDashboards.cardDrawn = drawn;
    // Option editors a project registers for its own option types (see the
    // component builder): optionEditors[type] = function ({spec, value, set, columns}) → element.
    window.SmallStackDashboards.optionEditors = window.SmallStackDashboards.optionEditors || {};
})();
