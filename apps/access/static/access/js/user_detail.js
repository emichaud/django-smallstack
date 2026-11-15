// The user's Access page: filter the permission list as you type.
// Rows carry their searchable text in data-text; an app section hides when
// none of its rows match; the header count says how many are showing.
(function () {
    var input = document.querySelector("[data-perm-filter]");
    var list = document.querySelector("[data-perm-list]");
    if (!input || !list) return;
    var rows = Array.prototype.slice.call(list.querySelectorAll("[data-perm-row]"));
    var apps = Array.prototype.slice.call(list.querySelectorAll("[data-perm-app]"));
    var count = document.querySelector("[data-perm-count]");
    var none = list.querySelector("[data-perm-none]");
    var total = rows.length;
    var totalLabel = count ? count.textContent : "";

    function apply() {
        var terms = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        var shown = 0;
        rows.forEach(function (row) {
            var text = row.getAttribute("data-text") || "";
            var hit = terms.every(function (t) { return text.indexOf(t) !== -1; });
            row.hidden = !hit;
            if (hit) shown += 1;
        });
        apps.forEach(function (app) {
            var visible = app.querySelectorAll("[data-perm-row]:not([hidden])").length;
            app.hidden = visible === 0;
            var c = app.querySelector("[data-perm-app-count]");
            if (c) c.textContent = String(visible);
        });
        if (none) none.hidden = shown !== 0;
        if (count) count.textContent = terms.length ? shown + " of " + total + " shown" : totalLabel;
    }

    input.addEventListener("input", apply);
    // A link to #permissions?q= style deep links isn't needed; ?perm= is the check box.
})();
