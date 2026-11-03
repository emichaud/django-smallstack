/* The "Add to goals" form — in the global modal (it loads this script with
 * itself) or on its own page: a "between" rule shows its second number, and
 * the section suggestions follow the chosen goal list. Listeners are on the
 * document, attached once, so a form swapped in later works too. */
(function () {
    "use strict";
    if (window.__smallstackGoalAddJs) {
        if (window.__smallstackGoalRules) window.__smallstackGoalRules(document);
        return;
    }
    window.__smallstackGoalAddJs = true;

    function goalRules(root) {
        (root || document).querySelectorAll("[data-gl-between]").forEach(function (fs) {
            var op = fs.querySelector("select");
            var between = !!op && op.value === "between";
            fs.querySelectorAll("[data-gl-second]").forEach(function (n) { n.hidden = !between; });
        });
    }
    window.__smallstackGoalRules = goalRules;

    document.addEventListener("change", function (ev) {
        var t = ev.target;
        if (!t || !t.closest) return;
        if (t.tagName === "SELECT" && t.closest("[data-gl-between]")) goalRules(t.closest("form"));
        if (t.matches("[data-gl-sections]")) {
            var list = document.getElementById(t.getAttribute("data-gl-sections"));
            var chosen = t.options[t.selectedIndex];
            if (!list || !chosen) return;
            list.replaceChildren();
            (chosen.getAttribute("data-sections") || "").split("|").forEach(function (title) {
                if (!title) return;
                var o = document.createElement("option");
                o.value = title;
                list.appendChild(o);
            });
        }
    });
    document.addEventListener("htmx:afterSettle", function () { goalRules(document); });
    goalRules(document);
})();
