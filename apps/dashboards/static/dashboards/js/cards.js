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

    // -- choice widgets: a "choice" option with widget: "segmented" (pills in a
    // row, an icon for an alignment) or "swatches" (colour dots, each the
    // theme token its class names in dashboards.css). Both builders use this
    // in place of a select. Returns the group, or null for a plain choice.
    var ALIGN_ICONS = {
        start: "M3 5h18v2H3zm0 4h12v2H3zm0 4h18v2H3zm0 4h12v2H3z",
        center: "M3 5h18v2H3zm3 4h12v2H6zm-3 4h18v2H3zm3 4h12v2H6z",
        end: "M3 5h18v2H3zm6 4h12v2H9zm-6 4h18v2H3zm6 4h12v2H9z",
    };
    function choiceWidget(spec, current, onChange, idBase) {
        if (spec.widget !== "segmented" && spec.widget !== "swatches") return null;
        var swatches = spec.widget === "swatches";
        var group = document.createElement("div");
        group.className = swatches ? "cb-swatches" : "cb-seg";
        group.setAttribute("role", "radiogroup");
        group.setAttribute("aria-label", spec.label || spec.name);
        (spec.choices || []).forEach(function (c) {
            var pair = Array.isArray(c) ? c : [c, c];
            var value = String(pair[0]), label = String(pair[1]);
            var id = idBase + "-" + (value || "none");
            var input = document.createElement("input");
            input.type = "radio"; input.name = idBase; input.value = value; input.id = id;
            input.className = "sr-only cb-choice-radio";
            input.checked = value === String(current == null ? "" : current);
            input.addEventListener("change", function () { if (input.checked) onChange(value); });
            var lab = document.createElement("label");
            lab.setAttribute("for", id);
            lab.title = label;
            if (swatches) {
                lab.className = "cb-swatch cb-swatch--" + spec.name + "-" + (value || "none");
                var sr = document.createElement("span"); sr.className = "sr-only"; sr.textContent = label;
                lab.appendChild(sr);
            } else {
                lab.className = "cb-seg-item";
                var icon = spec.name === "align" ? ALIGN_ICONS[value] : null;
                if (icon) {
                    lab.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + icon + '"/></svg>';  // our own paths
                    var text = document.createElement("span"); text.className = "sr-only"; text.textContent = label;
                    lab.appendChild(text);
                } else lab.textContent = label;
            }
            group.appendChild(input);
            group.appendChild(lab);
        });
        return group;
    }

    window.SmallStackDashboards = window.SmallStackDashboards || {};
    window.SmallStackDashboards.cardDrawn = drawn;
    window.SmallStackDashboards.choiceWidget = choiceWidget;
    // Option editors a project registers for its own option types (see the
    // component builder): optionEditors[type] = function ({spec, value, set, columns}) → element.
    window.SmallStackDashboards.optionEditors = window.SmallStackDashboards.optionEditors || {};
})();
