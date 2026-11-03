// Moved from apps/blog/templates/blog/studio/post_form.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
  var form = document.getElementById('studio-editor');
  var action = document.getElementById('studio-action');
  if (!form || !action) { return; }
  form.querySelectorAll('button[data-action]').forEach(function (b) {
    b.addEventListener('click', function () { action.value = b.getAttribute('data-action'); });
  });
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault(); action.value = 'save'; form.requestSubmit();
    }
  });
  form.querySelectorAll('[data-picker-for]').forEach(function (b) {
    b.addEventListener('click', function () {
      var input = document.getElementById(b.getAttribute('data-picker-for'));
      if (!input) { return; }
      if (input.showPicker) { try { input.showPicker(); return; } catch (e) { /* fall through */ } }
      input.focus(); input.click();
    });
  });
  form.querySelectorAll('[data-cover-input]').forEach(function (box) {
    var file = box.querySelector('[data-cover-file]');
    var img = box.querySelector('[data-cover-preview]');
    var frame = box.querySelector('.studio-cover-frame');
    var name = box.querySelector('[data-cover-filename]');
    var clear = box.querySelector('[data-cover-clear]');
    var label = box.querySelector('[data-cover-pick-label]');
    if (file) {
      file.addEventListener('change', function () {
        var f = file.files && file.files[0];
        if (!f) { return; }
        if (img.src && img.src.indexOf('blob:') === 0) { URL.revokeObjectURL(img.src); }
        img.src = URL.createObjectURL(f);
        frame.classList.remove('is-empty', 'is-removing');
        if (clear) { clear.checked = false; }
        if (name) { name.textContent = f.name; }
        if (label) { label.textContent = 'Replace'; }
      });
    }
    if (clear) {
      clear.addEventListener('change', function () {
        frame.classList.toggle('is-removing', clear.checked);
      });
    }
  });
  var body = form.querySelector('textarea[name="body_markdown"]');
  var count = document.getElementById('studio-words');
  if (body && count) {
    var update = function () {
      var t = body.value.trim(); count.textContent = t ? t.split(/\s+/).length : 0;
    };
    body.addEventListener('input', update); update();
  }
})();
