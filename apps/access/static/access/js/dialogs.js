/*
 * Modal dialogs on the Access pages, on the native <dialog> element (it traps
 * focus, closes on Esc and draws the backdrop):
 *
 *   <button data-dialog-open="new-group">New group</button>
 *   <dialog id="new-group"> … <button data-dialog-close>Cancel</button> … </dialog>
 *
 * A click on the backdrop closes it too. Events are delegated from the
 * document, so a form htmx swaps inside the dialog keeps its close buttons.
 * No inline handlers (the CSP refuses them).
 */
(function () {
    "use strict";

    document.addEventListener("click", function (e) {
        var opener = e.target.closest && e.target.closest("[data-dialog-open]");
        if (opener) {
            var dialog = document.getElementById(opener.getAttribute("data-dialog-open"));
            if (dialog && typeof dialog.showModal === "function") {
                e.preventDefault();
                dialog.showModal();
                var first = dialog.querySelector("[autofocus]");
                if (first) { first.focus(); }
            }
            return;
        }
        var closer = e.target.closest && e.target.closest("[data-dialog-close]");
        if (closer) {
            var open = closer.closest("dialog");
            if (open) { open.close(); }
            return;
        }
        // A click on the dialog element itself is a click on its backdrop.
        if (e.target.tagName === "DIALOG" && e.target.open) {
            e.target.close();
        }
    });

    // After htmx swaps the form back in with an error, put the cursor in the field.
    document.addEventListener("htmx:afterSettle", function (e) {
        var dialog = e.target.closest && e.target.closest("dialog[open]");
        var field = dialog && dialog.querySelector("[aria-invalid=true], [autofocus]");
        if (field) { field.focus(); field.select && field.select(); }
    });
})();
