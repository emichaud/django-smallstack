// Moved from apps/showcase/templates/showcase/prompts.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var pre = btn.closest('.pf-prompt').querySelector('pre');
      var text = pre.innerText;
      var done = function () {
        btn.textContent = 'Copied'; btn.classList.add('is-done');
        setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('is-done'); }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done);
      } else {
        var range = document.createRange(); range.selectNodeContents(pre);
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
        try { document.execCommand('copy'); done(); } catch (e) {}
        sel.removeAllRanges();
      }
    });
  });
})();
