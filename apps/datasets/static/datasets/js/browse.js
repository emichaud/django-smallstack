/* Dataset browser — mounts the shared filter-tree editor under "More conditions".
 *
 * The form is a plain GET: the tree travels as ?filter_tree=<json>, the same
 * parameter REST takes, so the address stays shareable and the CSV link can
 * carry it. The dataset's schema() is on the page as json_script (the page is
 * staff-only; no fetch). An empty tree is left out of the address.
 */
(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("ds-form");
        var mount = document.getElementById("ds-tree");
        var input = form && form.querySelector('[name="filter_tree"]');
        if (!form || !mount || !input || !window.SmallStackFilterTree) return;
        var schema = null;
        try { schema = JSON.parse(document.getElementById("ds-schema").textContent); } catch (e) { schema = null; }
        var editor = window.SmallStackFilterTree.create({
            mount: mount,
            input: input,
            placeholder: "This dataset has no filterable columns.",
        });
        editor.setSchema(schema);
        // The editor writes readable JSON; the address gets the compact form,
        // and nothing at all when there are no conditions.
        form.addEventListener("submit", function () {
            var tree = editor.value();
            var empty = !tree || (typeof tree === "object" && !Object.keys(tree).length);
            input.disabled = empty;
            if (!empty) input.value = JSON.stringify(tree);
        });
    });
})();
