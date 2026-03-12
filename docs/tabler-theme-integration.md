# Tabler Theme Integration Guide

Technical guide for implementing the Tabler theme as a self-contained Django app that works with SmallStack's new self-contained app architecture.

## Architecture Overview

After the base restructuring, SmallStack uses Django's standard template precedence:

```
1. DIRS (project root /templates/)     <- user overrides (always win)
2. APP_DIRS in INSTALLED_APPS order:
   ├── apps/tabler/templates/          <- theme app (wins over built-in)
   ├── apps/activity/templates/        <- built-in default
   ├── apps/smallstack/templates/      <- built-in default
   └── ...
```

A theme app placed **before** built-in apps in `INSTALLED_APPS` wins template resolution automatically. No custom template loaders or monkey-patching needed.

## Target Structure: `apps/tabler/`

```
apps/tabler/
├── __init__.py
├── apps.py                           # TablerConfig, nav registration
├── templates/
│   ├── tabler/                       # Theme's own namespace
│   │   ├── base.html                 # Tabler base layout
│   │   └── includes/
│   │       ├── navbar.html           # Top navigation bar
│   │       ├── breadcrumbs.html
│   │       ├── messages.html
│   │       └── settings.html         # Theme settings panel
│   ├── smallstack/                   # Overrides for built-in smallstack templates
│   │   ├── base.html                 # Redirect: {% extends "tabler/base.html" %}
│   │   └── includes/
│   │       └── sidebar.html          # Empty or hidden (tabler uses navbar)
│   ├── activity/                     # Tabler-styled built-in pages
│   │   ├── dashboard.html
│   │   ├── requests.html
│   │   └── users.html
│   ├── heartbeat/
│   │   ├── dashboard.html
│   │   ├── status.html
│   │   └── sla.html
│   ├── usermanager/
│   │   ├── user_list.html
│   │   └── timezone_dashboard.html
│   ├── profile/
│   │   ├── profile.html
│   │   ├── profile_detail.html
│   │   └── profile_edit.html
│   ├── help/
│   │   ├── help_index.html
│   │   ├── help_detail.html
│   │   └── help_section_index.html
│   ├── registration/
│   │   ├── login.html
│   │   ├── signup.html
│   │   └── ...
│   └── accounts/
│       └── user_form.html
├── static/
│   └── tabler/
│       ├── css/
│       │   └── tabler_overrides.css
│       └── js/
│           └── tabler_theme.js
└── preview/                          # Optional: component showcase
    └── ...
```

### Key Design Decisions

**`smallstack/base.html` override.** The theme provides `apps/tabler/templates/smallstack/base.html` that simply extends `tabler/base.html`. This means every built-in page that does `{% extends "smallstack/base.html" %}` automatically gets the tabler layout without modifying any built-in template. Only pages that need tabler-specific block changes need individual overrides.

**Sidebar suppression.** Provide an empty `smallstack/includes/sidebar.html` to suppress the default sidebar. Tabler uses a top navbar instead.

**Built-in page overrides.** Pages like `activity/dashboard.html` need tabler-specific markup (Tabler card classes, grid system, etc.), so they get full overrides in the theme app. These extend `tabler/base.html` directly.

---

## Installation (Downstream Project)

### Step 1: Add the app

```python
# config/settings/base.py
INSTALLED_APPS = [
    "apps.tabler",        # Theme — MUST be before built-in apps
    "apps.accounts",
    "apps.smallstack",
    "apps.profile",
    "apps.help",
    "apps.tasks",
    "apps.activity",
    "apps.heartbeat",
    "apps.usermanager",
    "apps.website",
    # django built-ins...
]
```

### Step 2: That's it

No other config changes needed. Django's `APP_DIRS` resolution handles everything:
- `{% extends "smallstack/base.html" %}` finds `apps/tabler/templates/smallstack/base.html` first
- `{% static 'tabler/css/tabler_overrides.css' %}` finds `apps/tabler/static/tabler/css/...`
- Built-in pages that tabler overrides get the tabler version
- Pages tabler doesn't override get the default SmallStack version

### Step 3 (Optional): Nav registry integration

The theme's `apps.py` can register its own nav items or consume the existing `nav_items` context variable in its navbar template:

```python
# apps/tabler/apps.py
from django.apps import AppConfig

class TablerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tabler"
    verbose_name = "Tabler Theme"
```

The navbar can iterate `nav_items` from the context processor instead of hardcoding links:

```html
{# apps/tabler/templates/tabler/includes/navbar.html #}
{% for group in nav_items %}
    {% for item in group.items %}
    <a class="nav-link {% if item.active %}active{% endif %}" href="{{ item.url }}">
        {{ item.icon_svg|safe }}
        <span class="nav-link-title">{{ item.label }}</span>
    </a>
    {% endfor %}
{% endfor %}
```

This means adding/removing an app from `INSTALLED_APPS` automatically updates the tabler navbar — no template edits needed.

---

## Merge Surface with Upstream

After this architecture, the merge surface between a tabler-themed downstream project and upstream SmallStack is:

| File | Conflict risk | Notes |
|---|---|---|
| `config/settings/base.py` | Low | One line in INSTALLED_APPS |
| `apps/tabler/` (entire dir) | None | Purely additive — doesn't exist upstream |
| `templates/` (project root) | None | Only project-specific files here |
| `static/` (project root) | None | Only project-specific files here |

Everything else merges cleanly because the downstream diff is purely additive.

---

## Migration Path: Current Tabler Project → New Architecture

The current `smallstack-tabler` project has tabler templates scattered across the project root `templates/` directory (every built-in page has a copy at root that extends `tabler/base.html`). Here's how to migrate.

### Should You Re-clone or Migrate In-Place?

**Re-clone from updated upstream is recommended.** Here's why:

| Approach | Pros | Cons |
|---|---|---|
| **Merge upstream** | Preserves git history, existing commits | Massive merge conflicts (every template moved), must untangle root vs app templates |
| **Re-clone + copy tabler** | Clean start, correct structure from day one, fast | Lose project-specific git history, must re-apply non-tabler customizations |

The current tabler project's git history is mostly upstream merges + tabler template additions. The valuable work is:
1. `templates/tabler/` (base.html, includes/) — the theme itself
2. `static/tabler/` (CSS overrides, theme JS)
3. `apps/preview/` — component showcase
4. Individual page overrides (activity, heartbeat, etc.)

All of this can be copied into the new structure in about 30 minutes. A merge would take longer and leave debris.

### Re-clone Procedure

```bash
# 1. Fresh clone of updated base
mkdir smallstack-tabler-new
cd smallstack-tabler-new
git clone https://github.com/emichaud/django-smallstack .

# 2. Create the theme app
mkdir -p apps/tabler/{templates,static}

# 3. Copy theme core from old project
cp -r ../smallstack-tabler/templates/tabler/ apps/tabler/templates/tabler/
cp -r ../smallstack-tabler/static/tabler/ apps/tabler/static/tabler/

# 4. Copy page overrides into the theme app
# These are the pages that currently live at templates/<app>/ in the old project
# and extend tabler/base.html. Move them INTO apps/tabler/templates/<app>/:
for app in activity heartbeat usermanager profile help accounts; do
    if [ -d "../smallstack-tabler/templates/$app" ]; then
        cp -r "../smallstack-tabler/templates/$app" "apps/tabler/templates/$app"
    fi
done
cp -r ../smallstack-tabler/templates/registration apps/tabler/templates/registration

# 5. Create the smallstack/base.html bridge
mkdir -p apps/tabler/templates/smallstack
cat > apps/tabler/templates/smallstack/base.html << 'TMPL'
{% extends "tabler/base.html" %}
TMPL

# 6. Suppress sidebar
mkdir -p apps/tabler/templates/smallstack/includes
touch apps/tabler/templates/smallstack/includes/sidebar.html

# 7. Copy preview app if desired
cp -r ../smallstack-tabler/apps/preview apps/preview/

# 8. Copy project-specific templates to root
cp -r ../smallstack-tabler/templates/website templates/website
# Copy error pages, email, legal if customized

# 9. Create apps.py
cat > apps/tabler/__init__.py << 'EOF'
EOF
cat > apps/tabler/apps.py << 'PYEOF'
from django.apps import AppConfig

class TablerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tabler"
    verbose_name = "Tabler Theme"
PYEOF

# 10. Update INSTALLED_APPS: add "apps.tabler" as the FIRST app
# 11. make setup && make test
```

### What Goes Where

| Content | Location | Why |
|---|---|---|
| `tabler/base.html`, `tabler/includes/*` | `apps/tabler/templates/tabler/` | Theme's own namespace |
| `smallstack/base.html` (bridge) | `apps/tabler/templates/smallstack/` | Redirects all `{% extends "smallstack/base.html" %}` to tabler |
| `activity/dashboard.html` etc. | `apps/tabler/templates/activity/` | Theme wins via INSTALLED_APPS order |
| `tabler_overrides.css`, `tabler_theme.js` | `apps/tabler/static/tabler/` | Theme's static namespace |
| `website/home.html` etc. | `templates/website/` (project root) | Project-specific, not part of theme |
| `preview/` pages | `apps/preview/templates/preview/` or `apps/tabler/templates/preview/` | Showcase app |

### Files That Should NOT Be in `apps/tabler/`

- `templates/website/` — project-specific, stays at root
- `templates/400.html` etc. — error pages, stays at root
- `templates/email/` — project-specific
- `templates/legal/` — project-specific
- `static/brand/` — project branding, stays at root
- `config/` — project config, not theme

---

## Using the Nav Registry

The current tabler navbar (`navbar.html`) hardcodes links to Activity, Status, Backups, Users, SLA, Admin. The nav registry makes this dynamic.

### Current (hardcoded):
```html
<a href="{% url 'activity:dashboard' %}" class="dropdown-apps-item">
    <span class="dropdown-apps-icon bg-blue-lt"><!-- svg --></span>
    <span class="dropdown-apps-label">Activity</span>
</a>
<!-- repeated for each link -->
```

### New (registry-driven):
```html
{% for group in nav_items %}
{% if group.section == "admin" %}
{% for item in group.items %}
<a href="{{ item.url }}" class="dropdown-apps-item {% if item.active %}active{% endif %}">
    <span class="dropdown-apps-icon">{{ item.icon_svg|safe }}</span>
    <span class="dropdown-apps-label">{{ item.label }}</span>
</a>
{% endfor %}
{% endif %}
{% endfor %}
```

Benefits: adding/removing apps automatically updates the navbar. No template edits needed when a new built-in app is added upstream.

The tabler navbar can also use its own SVG icons by overriding them in `apps/tabler/apps.py`:

```python
def ready(self):
    from apps.smallstack.navigation import nav
    # Override icon styles for tabler's Feather icon set if desired
```

---

## CSP Considerations

Tabler loads CSS/JS from CDN (`cdn.jsdelivr.net`) and fonts from Google Fonts. Update CSP in settings:

```python
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net"],
        "style-src": ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "fonts.googleapis.com"],
        "font-src": ["'self'", "fonts.gstatic.com"],
        "img-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
    }
}
```

---

## Future: Installable Package

Once the theme is stable, it can become a pip-installable package:

```
pip install django-smallstack-tabler
```

```python
INSTALLED_APPS = [
    "smallstack_tabler",    # pip package, before built-in apps
    "apps.accounts",
    ...
]
```

The `INSTALLED_APPS` line is the only config change. No file-level conflicts with upstream at all.
