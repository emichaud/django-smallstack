# Skill: Theme Integration Scenarios

This skill covers the three ways to integrate a custom theme with SmallStack. Read this before helping a user set up their own CSS framework or decide which approach to take.

## Decision Tree

Ask the user: **Do users log in to your app?**

- **No** → Scenario A (public site, staff-only login)
- **Yes** → Scenario B (public site with user login)
- **Either, but I want to use SmallStack's theme** → Scenario C (build on SmallStack)

## Architecture: How Two Themes Coexist

SmallStack's built-in apps (Dashboard, Explorer, Activity, Backups, Users, Help) all extend `smallstack/base.html`. Custom pages extend a different base template. Both share:

- **Dark mode** — same `localStorage` key (`smallstack-theme`), same `data-theme` attribute on `<html>`
- **Palettes** — same `localStorage` key (`smallstack-palette`), same `data-palette` attribute
- **Authentication** — same Django session
- **`theme.js`** — same script, loaded in both bases

They differ in CSS framework, layout, and navigation.

```
templates/
├── smallstack/base.html          # SmallStack apps use this (DON'T MODIFY)
├── mytheme/base.html             # Custom pages use this (CREATE)
└── website/                      # All custom page templates go here
    ├── home.html                 # {% extends "mytheme/base.html" %}
    └── dashboard.html
```

## Scenario A: Public Site, No User Login

**Goal:** Visitors see your theme. Staff logs in to `/smallstack/` for admin tools.

### Steps

1. **Disable signup:**
   ```bash
   # .env
   SMALLSTACK_SIGNUP_ENABLED=False
   ```

2. **Create custom base template** at `templates/mytheme/base.html` with:
   - Your CSS framework
   - Blocking theme script in `<head>` (reads localStorage, sets `data-theme`)
   - `window.SMALLSTACK` config object before `theme.js`
   - SmallStack's `theme.js` script

3. **Update public pages** to extend `mytheme/base.html` instead of `smallstack/base.html`:
   ```html
   {% extends "mytheme/base.html" %}
   ```

4. **Login redirect** — default `LOGIN_REDIRECT_URL = "/smallstack/"` is correct. Staff logs in and lands on Dashboard.

5. **Optional admin link** in footer:
   ```html
   {% if user.is_staff %}
   <a href="/smallstack/">Admin</a>
   {% endif %}
   ```

### Settings (no changes needed for defaults)

```python
LOGIN_URL = "/smallstack/accounts/login/"
LOGIN_REDIRECT_URL = "/smallstack/"
LOGOUT_REDIRECT_URL = "/"
SMALLSTACK_SIGNUP_ENABLED = False
```

## Scenario B: Public Site with User Login

**Goal:** Users log in and use the app with your theme. Staff accesses SmallStack tools via a link.

### Steps

1. **Create custom base template** — same as Scenario A.

2. **Set login redirect** to your app's start page:
   ```python
   # config/settings/base.py
   LOGIN_REDIRECT_URL = "/dashboard/"    # or wherever your app starts
   ```

3. **Override login template** (optional) to match your theme:
   ```
   templates/registration/login.html → {% extends "mytheme/base.html" %}
   ```
   Django finds this automatically — no URL changes needed.

4. **Build user pages** in `apps/website/`, extending `mytheme/base.html`:
   ```python
   # views.py
   class UserDashboardView(LoginRequiredMixin, TemplateView):
       template_name = "website/dashboard.html"
   ```

5. **Expose admin tools** — add a staff-only link to `/smallstack/` in your nav:
   ```html
   {% if user.is_staff %}
   <a href="/smallstack/">Admin Tools</a>
   {% endif %}
   ```

### Settings

```python
LOGIN_URL = "/smallstack/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"        # CHANGED — your app's start page
LOGOUT_REDIRECT_URL = "/"
```

## Scenario C: Build on SmallStack's Theme

**Goal:** Use SmallStack's built-in theme for everything. No external CSS.

### Steps

1. **Update branding:**
   ```python
   BRAND_NAME = "My App"
   ```

2. **Edit homepage** — `templates/website/home.html` already extends `smallstack/base.html`. Replace the `{% include %}` content with your own.

3. **Add pages** using the standard pattern:
   - View in `apps/website/views.py`
   - URL in `apps/website/urls.py`
   - Template extending `smallstack/base.html`
   - Optional nav item via `nav.register()` in `apps/website/apps.py`

4. **Use built-in CSS classes:** `card`, `card-header`, `card-body`, `btn`, `grid-row`, `grid-col-*`, `vTextField`.

5. **Use CSS variables** for custom styling: `var(--primary)`, `var(--card-bg)`, `var(--body-fg)`, etc.

### No settings changes needed — everything works out of the box.

## Required Pieces in Custom Base Template

When creating `templates/mytheme/base.html`, these three pieces are **mandatory**:

### 1. Blocking Theme Script (in `<head>`, before CSS)

```html
<script>
(function() {
    var theme = localStorage.getItem('smallstack-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    var palette = localStorage.getItem('smallstack-palette') || '{{ color_palette }}';
    if (palette && palette !== 'django') {
        document.documentElement.setAttribute('data-palette', palette);
    }
})();
</script>
```

### 2. SMALLSTACK Config Object (before theme.js)

```html
<script>
window.SMALLSTACK = {
    userTheme: {% if user.is_authenticated and user.profile %}'{{ user.profile.theme_preference }}'{% else %}null{% endif %},
    userPalette: {% if user.is_authenticated and user.profile %}'{{ user.profile.color_palette }}'{% else %}null{% endif %},
    colorPalette: '{{ color_palette }}',
    isAuthenticated: {% if user.is_authenticated %}true{% else %}false{% endif %},
    sidebarEnabled: false,
    sidebarOpen: false,
    topbarNavEnabled: false
};
</script>
```

### 3. SmallStack theme.js

```html
<script src="{% static 'smallstack/js/theme.js' %}"></script>
```

### Optional but recommended

- `{% static 'smallstack/css/palettes.css' %}` — gives you palette color variables
- `{% include "smallstack/includes/messages.html" %}` — flash messages
- `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` on `<body>` — if using htmx

## File Placement Rules

| What | Where |
|------|-------|
| Custom base template | `templates/mytheme/base.html` |
| Custom navbar/partials | `templates/mytheme/includes/` |
| All custom page templates | `templates/website/` |
| Custom CSS overrides | `static/css/mytheme.css` |
| Vendored framework files | `static/mytheme/css/`, `static/mytheme/js/` |
| Views | `apps/website/views.py` |
| URLs | `apps/website/urls.py` |
| Nav registration | `apps/website/apps.py` |

**Never modify** files under `templates/smallstack/` or `static/smallstack/`.

## SmallStack App URLs for Admin Links

| App | URL | Access |
|-----|-----|--------|
| Dashboard | `/smallstack/` | Staff |
| Explorer | `/smallstack/explorer/` | Staff |
| Activity | `/smallstack/activity/` | Staff |
| Backups | `/smallstack/backups/` | Staff |
| Users | `/smallstack/manage/users/` | Staff |
| Help | `/smallstack/help/` | All |
| Profile | `/smallstack/profile/` | Authenticated |
| Django Admin | `/admin/` | Staff |

## Common Mistakes

- **Don't override SmallStack app templates** — they're upstream and will conflict on updates
- **Don't reimplement dark mode** — use SmallStack's `theme.js`, remove any competing dark mode JS from purchased themes
- **Don't put pages in other apps** — custom pages go in `apps/website/`
- **Don't forget the blocking theme script** — without it, users see a flash of the wrong theme on page load
- **Don't hardcode colors** — use `var(--primary)`, `var(--card-bg)`, etc. so palettes and dark mode work

## Related Skills

- [adding-your-own-theme.md](adding-your-own-theme.md) — Full Bootstrap walkthrough with CSS override examples
- [theming-system.md](theming-system.md) — CSS variables, palettes, dark mode internals
- [templates.md](templates.md) — Template inheritance, blocks, includes
- [authentication.md](authentication.md) — Auth views, LoginRequiredMixin, protecting views
- [settings.md](settings.md) — Split settings, environment variables
