/*
 * Multi-select pickers on the Access pages (people, permissions, groups).
 *
 *   <form data-picker>
 *     <input type="search" data-picker-filter>              narrows the list as you type
 *     <input type="checkbox" data-picker-all>                selects every item shown
 *     <section data-picker-group> … </section>               hidden when nothing in it matches
 *     <label data-picker-item data-text="…"><input type="checkbox" name="…" value="…"></label>
 *     <button type="submit" data-picker-submit>Add <span data-picker-count>0</span></button>
 *   </form>
 *
 * Events are delegated from the document, so a picker inside a card that htmx
 * swaps keeps working without re-initialising. No inline handlers (the CSP
 * refuses them); the form still submits without JS, just unfiltered.
 */
(function () {
    "use strict";

    function picker(el) {
        return el && el.closest ? el.closest("[data-picker]") : null;
    }

    function shownItems(root) {
        return Array.prototype.filter.call(root.querySelectorAll("[data-picker-item]"), function (item) {
            return !item.hidden;
        });
    }

    function update(root) {
        var boxes = root.querySelectorAll("[data-picker-item] input[type=checkbox]");
        var chosen = Array.prototype.filter.call(boxes, function (b) { return b.checked; }).length;
        root.querySelectorAll("[data-picker-count]").forEach(function (c) { c.textContent = String(chosen); });
        root.querySelectorAll("[data-picker-submit]").forEach(function (b) { b.disabled = chosen === 0; });
        var all = root.querySelector("[data-picker-all]");
        if (all) {
            var shown = shownItems(root);
            var shownChecked = shown.filter(function (i) { return i.querySelector("input").checked; }).length;
            all.checked = shown.length > 0 && shownChecked === shown.length;
            all.indeterminate = shownChecked > 0 && shownChecked < shown.length;
        }
    }

    function filter(root, text) {
        var q = (text || "").trim().toLowerCase();
        root.querySelectorAll("[data-picker-item]").forEach(function (item) {
            var hay = (item.getAttribute("data-text") || item.textContent || "").toLowerCase();
            item.hidden = q !== "" && hay.indexOf(q) === -1;
        });
        root.querySelectorAll("[data-picker-group]").forEach(function (group) {
            group.hidden = group.querySelectorAll("[data-picker-item]:not([hidden])").length === 0;
        });
        var none = root.querySelector("[data-picker-none]");
        if (none) { none.hidden = shownItems(root).length > 0; }
        update(root);
    }

    document.addEventListener("input", function (e) {
        if (e.target.matches && e.target.matches("[data-picker-filter]")) {
            filter(picker(e.target), e.target.value);
        }
    });

    document.addEventListener("change", function (e) {
        var root = picker(e.target);
        if (!root) { return; }
        if (e.target.matches("[data-picker-all]")) {
            shownItems(root).forEach(function (item) { item.querySelector("input").checked = e.target.checked; });
        }
        update(root);
    });

    // Enter in the filter narrows; it must not submit the picker.
    document.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && e.target.matches && e.target.matches("[data-picker-filter]")) {
            e.preventDefault();
        }
    });

    function initAll(scope) {
        (scope || document).querySelectorAll("[data-picker]").forEach(update);
    }
    document.addEventListener("DOMContentLoaded", function () { initAll(); });
    document.body && document.body.addEventListener("htmx:afterSettle", function (e) { initAll(e.target); });
})();
