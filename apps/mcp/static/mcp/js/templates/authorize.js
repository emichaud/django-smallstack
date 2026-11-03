// Moved from apps/mcp/templates/mcp/authorize.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
  // First-click guard with deferred disable: keep the original click's
  // `decision` value but block subsequent rapid clicks. We use a flag on
  // the form rather than disabling the button synchronously, so the
  // browser's form submission still carries the chosen value.
  var form = document.getElementById("mcp-authorize-form");
  var overlay = document.getElementById("mcp-handoff-overlay");
  var clicked = false;
  if (!form) return;
  form.addEventListener("submit", function (e) {
    if (clicked) {
      e.preventDefault();
      return;
    }
    clicked = true;
    // Defer the disable to the next microtask so the FormData still includes
    // the clicked submitter's value.
    setTimeout(function () {
      var buttons = form.querySelectorAll("button");
      buttons.forEach(function (b) { b.disabled = true; });
      if (overlay) overlay.style.display = "flex";
    }, 0);
  });
})();
