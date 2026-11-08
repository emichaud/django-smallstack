/* What a metric means: hovering (or focusing) a name that carries data-about shows
 * that text in one hover box, under the name and kept on screen. The box is fixed
 * to the viewport, so a scrolling table can't clip it. Delegated, so rows htmx
 * swaps in work without re-binding. */
(function () {
    "use strict";

    var GAP = 6;
    var MARGIN = 8;
    var tip = null;
    var owner = null;

    function show(el) {
        if (!tip) {
            tip = document.createElement("div");
            tip.className = "about-tip";
            tip.id = "about-tip";
            tip.setAttribute("role", "tooltip");
            tip.hidden = true;
            document.body.appendChild(tip);
        }
        owner = el;
        tip.textContent = el.getAttribute("data-about");
        tip.hidden = false;
        el.setAttribute("aria-describedby", "about-tip");
        var r = el.getBoundingClientRect();
        var w = tip.offsetWidth;
        var h = tip.offsetHeight;
        var left = Math.max(MARGIN, Math.min(r.left, window.innerWidth - w - MARGIN));
        var top = r.bottom + GAP;
        if (top + h > window.innerHeight - MARGIN) top = Math.max(MARGIN, r.top - GAP - h);
        tip.style.left = left + "px";
        tip.style.top = top + "px";
    }

    function hide() {
        if (owner) owner.removeAttribute("aria-describedby");
        owner = null;
        if (tip) tip.hidden = true;
    }

    function about(e) {
        return e.target.closest ? e.target.closest("[data-about]") : null;
    }

    document.addEventListener("mouseover", function (e) {
        var el = about(e);
        if (el && el !== owner) show(el);
    });
    document.addEventListener("mouseout", function (e) {
        var el = about(e);
        if (el && el === owner && !(e.relatedTarget && el.contains(e.relatedTarget))) hide();
    });
    document.addEventListener("focusin", function (e) {
        var el = about(e);
        if (el) show(el);
    });
    document.addEventListener("focusout", function (e) {
        if (about(e) === owner) hide();
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && owner) hide();
    });
    window.addEventListener("scroll", hide, { passive: true, capture: true });
})();
