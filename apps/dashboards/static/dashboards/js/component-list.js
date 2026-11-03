// The components list: hovering or focusing a row shows the card itself in a floating
// preview. Listens on the document, because the list is swapped in place when it sorts.
(function () {
    "use strict";
    if (window.SmallStackComponentPeek) return;
    window.SmallStackComponentPeek = true;

    var DELAY = 220, GAP = 6, MARGIN = 16;
    var timer = null, shown = null;

    function peek() { return document.getElementById("cl-peek"); }
    function hide() {
        clearTimeout(timer);
        shown = null;
        var box = peek();
        if (box) { box.hidden = true; box.innerHTML = ""; }
    }
    function place(box, row) {
        var rect = row.getBoundingClientRect();
        var name = row.querySelector(".cl-name") || row;
        var left = Math.min(name.getBoundingClientRect().left, window.innerWidth - box.offsetWidth - MARGIN);
        var below = rect.bottom + GAP + box.offsetHeight <= window.innerHeight;
        box.style.left = Math.max(MARGIN, left) + "px";
        box.style.top = (below ? rect.bottom + GAP : Math.max(MARGIN, rect.top - GAP - box.offsetHeight)) + "px";
    }
    function show(row) {
        var box = peek();
        if (!box || !window.htmx || row === shown) return;
        shown = row;
        box.innerHTML = '<span class="cc-loading">Loading…</span>';
        box.hidden = false;
        place(box, row);
        window.htmx.ajax("GET", row.getAttribute("data-preview-url"), { target: box, swap: "innerHTML" });
    }
    function soon(row) {
        clearTimeout(timer);
        timer = setTimeout(function () { show(row); }, DELAY);
    }
    document.addEventListener("pointerover", function (ev) {
        if (ev.pointerType !== "mouse" || !ev.target.closest) return;
        var row = ev.target.closest("tr[data-preview-url]");
        if (row) { if (row !== shown) soon(row); }
        else hide();
    });
    document.addEventListener("focusin", function (ev) {
        var row = ev.target.closest && ev.target.closest("tr[data-preview-url]");
        if (row) soon(row); else if (shown) hide();
    });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") hide(); });
    document.addEventListener("scroll", hide, { passive: true, capture: true });
    document.body.addEventListener("htmx:beforeSwap", function (ev) {
        if (ev.detail.target && ev.detail.target.id === "crud-list-content") hide();
    });
})();
