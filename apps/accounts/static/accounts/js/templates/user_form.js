// Moved from apps/accounts/templates/accounts/user_form.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Tab switching
document.querySelectorAll('.user-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
        var target = this.dataset.tab;
        // Update tab buttons
        document.querySelectorAll('.user-tab').forEach(function(t) { t.classList.remove('active'); });
        this.classList.add('active');
        // Update panels
        document.querySelectorAll('.tab-panel').forEach(function(p) { p.classList.remove('active'); });
        document.querySelectorAll('[data-tab="' + target + '"]').forEach(function(p) {
            if (!p.classList.contains('user-tab')) p.classList.add('active');
        });
        // Show/hide form actions (hide on activity tab)
        var actions = document.getElementById('form-actions');
        if (actions) {
            actions.style.display = (target === 'activity' || target === 'access') ? 'none' : 'flex';
        }
    });
});

// Sparkline bar heights
(function() {
    var bars = document.querySelectorAll('.sparkline-bar');
    if (!bars.length) return;
    var max = 0;
    bars.forEach(function(b) {
        var c = parseInt(b.dataset.count, 10) || 0;
        if (c > max) max = c;
    });
    bars.forEach(function(b) {
        var c = parseInt(b.dataset.count, 10) || 0;
        var pct = max > 0 ? Math.max((c / max) * 100, 4) : 4;
        b.style.height = pct + '%';
    });
})();

// Photo upload preview
function setupPhotoPreview(inputId, imgId, placeholderId, nameId) {
    var input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener('change', function(e) {
        var file = e.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function(ev) {
            var img = document.getElementById(imgId);
            var placeholder = document.getElementById(placeholderId);
            if (img) {
                img.src = ev.target.result;
                img.style.display = 'block';
            }
            if (placeholder) placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
        var nameEl = document.getElementById(nameId);
        if (nameEl) nameEl.textContent = file.name;
    });
}
setupPhotoPreview('id_profile-profile_photo', 'profile-photo-img', 'profile-photo-placeholder', 'profile-photo-name');
setupPhotoPreview('id_profile-background_photo', 'bg-photo-img', 'bg-photo-placeholder', 'bg-photo-name');
