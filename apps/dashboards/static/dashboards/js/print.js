// The print document: the Print button, and ?auto=1 opening the dialog on arrival.
(function () {
    "use strict";
    document.addEventListener("DOMContentLoaded", function () {
        document.getElementById("doc-print").addEventListener("click", function () { window.print(); });
        if (document.body.hasAttribute("data-auto-print")) window.print();
    });
})();
