// Moved from apps/runbook/templates/runbook/runbook_form.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var runbookFormConfig = document.currentScript.dataset;

(function () {
    var input = document.getElementById(runbookFormConfig.iconFieldId);
    var preview = document.getElementById("icon-preview");
    if (!input || !preview) return;
    var choices = document.querySelectorAll(".icon-choice");
    function refresh(val) {
        preview.textContent = val || "📘";
        choices.forEach(function (b) { b.classList.toggle("selected", b.dataset.icon === val); });
    }
    choices.forEach(function (btn) {
        btn.addEventListener("click", function () { input.value = btn.dataset.icon; refresh(btn.dataset.icon); });
    });
    input.addEventListener("input", function () { refresh(input.value); });
    refresh(input.value);
})();
