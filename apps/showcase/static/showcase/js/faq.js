// The FAQ page: a link to one question (/faq/#crm) opens that question.
// Without this the page scrolls to a closed <details> and the answer stays hidden.
(function () {
    function openTarget() {
        var id = decodeURIComponent(window.location.hash.slice(1));
        if (!id) return;
        var el = document.getElementById(id);
        if (!el || el.tagName !== "DETAILS") return;
        document.querySelectorAll(".faq.is-target").forEach(function (d) { d.classList.remove("is-target"); });
        el.open = true;
        el.classList.add("is-target");
        el.scrollIntoView({ block: "start" });
    }
    window.addEventListener("hashchange", openTarget);
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", openTarget);
    } else {
        openTarget();
    }
})();
