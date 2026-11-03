// Moved from apps/search/templates/search/diagnostics.html (inline <script>) so the CSP needs no 'unsafe-inline'.
  function ssCopyDiag(btn) {
    var text = document.getElementById("ss-diag-report").textContent;
    navigator.clipboard.writeText(text).then(function () {
      var original = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = original; }, 1500);
    });
  }
// Exposed to data-ss-action="…" in the markup (see theme.js: declarative behaviours).
window.SmallStack = window.SmallStack || {};
window.SmallStack.actions = Object.assign(window.SmallStack.actions || {}, { ssCopyDiag: window.ssCopyDiag });
