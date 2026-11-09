// Moved from templates/starter/forms.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Tab switching
document.querySelectorAll('[data-tabs]').forEach(function(tabBar) {
    var card = tabBar.closest('.card');
    tabBar.querySelectorAll('.starter-tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            var target = this.dataset.tab;
            // Toggle tab buttons
            tabBar.querySelectorAll('.starter-tab').forEach(function(t) {
                t.classList.toggle('active', t.dataset.tab === target);
            });
            // Toggle panels
            card.querySelectorAll('.starter-tab-panel').forEach(function(p) {
                p.classList.toggle('active', p.dataset.panel === target);
            });
        });
    });
});

// File upload dropzone interactions
document.querySelectorAll('.file-upload-dropzone').forEach(function(zone) {
    var input = zone.querySelector('.file-upload-input');
    var text = zone.querySelector('.dropzone-text');
    var filename = zone.querySelector('.dropzone-filename');

    input.addEventListener('change', function() {
        if (this.files.length > 0) {
            text.style.display = 'none';
            filename.textContent = this.files[0].name;
            filename.style.display = '';
        } else {
            text.style.display = '';
            filename.style.display = 'none';
        }
    });

    zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function() {
        zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function(e) {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            input.files = e.dataTransfer.files;
            input.dispatchEvent(new Event('change'));
        }
    });
});

// Date picker buttons trigger native date picker
document.querySelectorAll('.date-picker-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var input = document.getElementById(this.dataset.target);
        if (input.showPicker) {
            input.showPicker();
        } else {
            input.focus();
            input.click();
        }
    });
});
