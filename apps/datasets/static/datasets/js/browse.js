/* Dataset browser — live filters, and the shared filter-tree editor under
 * "More conditions".
 *
 * The form is a plain GET: the tree travels as ?filter_tree=<json>, the same
 * parameter REST takes, so the address stays shareable and the CSV link can
 * carry it. The dataset's schema() is on the page as json_script (the page is
 * staff-only; no fetch). An empty tree is left out of the address.
 *
 * The filters apply as they change. The form's own selects and date boxes
 * fire `change`, which htmx listens for (see the hx-trigger in browse.html).
 * This script raises `ds-change` on the form for the three things that don't
 * bubble to it: an edit in the tree editor, typing in a search box (after a
 * pause), and the roll-up selects, which sit outside the form element and
 * are attached with form="ds-form".
 */
(function () {
    "use strict";

    var PAUSE = 400;

    // "Start from a metric": picking one loads its conditions and roll-up (the
    // option's data-url); the blank option starts over.
    document.addEventListener("change", function (e) {
        var select = e.target;
        if (!select || !select.matches || !select.matches("[data-ds-start-select]")) return;
        var option = select.options[select.selectedIndex];
        if (option && option.dataset.url) window.location.assign(option.dataset.url);
    });

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("ds-form");
        var mount = document.getElementById("ds-tree");
        var input = form && form.querySelector('[name="filter_tree"]');
        if (!form || !mount || !input || !window.SmallStackFilterTree) return;

        var timer = null;
        function changed() {
            clearTimeout(timer);
            timer = setTimeout(function () {
                form.dispatchEvent(new CustomEvent("ds-change", { bubbles: true }));
            }, PAUSE);
        }

        // The editor writes readable JSON; the address gets the compact form,
        // and nothing at all when there are no conditions (a disabled input
        // isn't sent, by htmx or by a plain submit).
        function syncTree(editor) {
            var tree = editor.value();
            var empty = !tree || (typeof tree === "object" && !Object.keys(tree).length);
            input.disabled = empty;
            if (!empty) input.value = JSON.stringify(tree);
            return empty;
        }

        var schema = null;
        try { schema = JSON.parse(document.getElementById("ds-schema").textContent); } catch (e) { schema = null; }
        var editor = window.SmallStackFilterTree.create({
            mount: mount,
            input: input,
            placeholder: "This dataset has no filterable columns.",
            onChange: function () {
                syncTree(editor);
                changed();
            },
        });
        editor.setSchema(schema);
        syncTree(editor);
        form.addEventListener("submit", function () { syncTree(editor); });

        // The address htmx pushes is the request's: leave the blank filters
        // out of it, as the Clear link does, so it stays readable to share.
        form.addEventListener("htmx:configRequest", function (e) {
            var p = e.detail.parameters;
            if (!p || typeof p.keys !== "function") return;
            Array.from(p.keys()).forEach(function (k) {
                var v = p.getAll ? p.getAll(k) : [p.get(k)];
                if (v.every(function (x) { return x === ""; })) p.delete(k);
            });
        });

        // Typing in a search box: after a pause, not on every key.
        form.querySelectorAll('input[type="search"]').forEach(function (box) {
            box.addEventListener("input", changed);
        });

        // The roll-up's selects live in the next card (form="ds-form"); their
        // change events don't reach the form, so relay them.
        document.addEventListener("change", function (e) {
            var el = e.target;
            if (el && el.getAttribute && el.getAttribute("form") === "ds-form" && !form.contains(el)) {
                form.dispatchEvent(new CustomEvent("ds-change", { bubbles: true }));
            }
        });
    });
})();
