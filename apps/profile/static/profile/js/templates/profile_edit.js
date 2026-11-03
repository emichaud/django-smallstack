// Moved from apps/profile/templates/profile/profile_edit.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Preview uploaded images
document.getElementById('id_profile_photo').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('profile-photo-preview');
            const placeholder = document.getElementById('profile-photo-placeholder');
            preview.src = e.target.result;
            preview.style.display = 'block';
            if (placeholder) placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
    }
});

document.getElementById('id_background_photo').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('cover-photo-preview');
            const placeholder = document.getElementById('cover-photo-placeholder');
            preview.src = e.target.result;
            preview.style.display = 'block';
            if (placeholder) placeholder.style.display = 'none';
        };
        reader.readAsDataURL(file);
    }
});

// Date picker button triggers native date picker
document.getElementById('date-picker-btn').addEventListener('click', function() {
    const dateInput = document.getElementById('id_date_of_birth');
    if (dateInput.showPicker) {
        dateInput.showPicker();
    } else {
        dateInput.focus();
        dateInput.click();
    }
});

// Theme toggle buttons are handled globally by theme.js
// which calls setTheme() and updates the id_theme_preference hidden input automatically.

// Live timezone preview
(function() {
    const tzSelect = document.getElementById('id_timezone');
    const preview = document.getElementById('tz-preview');
    if (!tzSelect || !preview) return;

    function formatTime(date, tz) {
        try {
            return date.toLocaleString('en-US', {
                timeZone: tz,
                month: 'short', day: 'numeric', year: 'numeric',
                hour: 'numeric', minute: '2-digit', second: '2-digit',
                hour12: true, timeZoneName: 'short'
            });
        } catch (e) {
            return null;
        }
    }

    function updatePreview() {
        const tz = tzSelect.value;
        if (!tz) {
            preview.textContent = '';
            return;
        }
        const now = new Date();
        const utcStr = formatTime(now, 'UTC');
        const localStr = formatTime(now, tz);
        if (utcStr && localStr) {
            preview.innerHTML = utcStr + '<br>' + localStr;
        } else {
            preview.textContent = '';
        }
    }

    tzSelect.addEventListener('change', updatePreview);
    updatePreview();
    setInterval(updatePreview, 1000);
})();
