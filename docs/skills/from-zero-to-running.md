# Skill: From Zero to Running

Complete setup guide for creating a new SmallStack project from clone through production deployment. Follow each section in order — every step includes verification commands.

## Phase 1: Clone and Local Setup

### 1.1 Clone the Repository

```bash
git clone https://github.com/emichaud/django-smallstack.git myapp
cd myapp
rm -rf .git    # Detach from upstream (or keep for pull-based updates)
git init
```

### 1.2 Create Environment File

```bash
cp .env.example .env
```

Edit `.env` with project-specific values. Every setting below must be reviewed:

#### Required Settings

| Variable | Default | Action |
|----------|---------|--------|
| `DJANGO_SETTINGS_MODULE` | `config.settings.development` | Keep for local dev. Change to `config.settings.production` in Docker/.kamal/secrets. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Add your domain in production. |

#### Development Superuser

| Variable | Default | Action |
|----------|---------|--------|
| `DEV_SUPERUSER_USERNAME` | `admin` | Change if desired. Used by `make superuser`. |
| `DEV_SUPERUSER_PASSWORD` | `admin` | Change if desired. Local dev only — never used in production. |

#### Docker Superuser (Production)

Uncomment and set these for automatic admin creation on first Docker startup:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

#### Timezone

```bash
TIME_ZONE=America/New_York    # IANA timezone name
TZ=America/New_York           # For Docker: keeps cron in sync with Django
```

See: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

#### Scheduled Tasks

These run automatically in Docker via supercronic — every minute (heartbeat), every 15 minutes (activity pruning), daily at 2 AM (database backup):

```bash
BACKUP_CRON_ENABLED=true              # Disable with false if not needed
# HEARTBEAT_RETENTION_DAYS=7          # Days of raw heartbeat data to keep
# ACTIVITY_MAX_ROWS=10000             # Max activity log rows before pruning
```

#### Auth Feature Flags

```bash
# SMALLSTACK_LOGIN_ENABLED=True       # False hides Login/Sign Up from topbar
# SMALLSTACK_SIGNUP_ENABLED=True      # False hides Sign Up and 404s the URL
```

#### HTTPS (Production Only)

Leave `false` for local dev. Set `true` when behind HTTPS proxy (Kamal with SSL):

```bash
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
```

#### Email (Required for Password Reset and Backup Alerts)

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-password
EMAIL_USE_TLS=true
```

Without email configured, password reset and backup failure notifications won't work. In local dev, email prints to console by default.

### 1.3 Run Setup

```bash
make setup    # installs deps, runs migrations, creates dev superuser
```

**Verify:**
```bash
make run      # starts on http://localhost:8005
```

Log in with `admin` / `admin` (or whatever you set in `.env`). Visit:

| URL | What to Check |
|-----|---------------|
| `http://localhost:8005/` | Home page loads |
| `http://localhost:8005/smallstack/` | Dashboard loads (staff only) |
| `http://localhost:8005/smallstack/explorer/` | Explorer shows registered models |
| `http://localhost:8005/status/` | Public status page |
| `http://localhost:8005/health/` | Returns `{"status": "ok"}` |

---

## Phase 2: Branding and Identity

### 2.1 Update Branding Settings

Edit `config/settings/base.py`:

```python
# Branding — update all of these
BRAND_NAME = "My App"
BRAND_TAGLINE = "Your tagline here"
BRAND_LOGO = "brand/my-logo.svg"            # Light mode logo
BRAND_LOGO_DARK = "brand/my-logo-dark.svg"  # Dark mode logo
BRAND_LOGO_TEXT = "brand/my-logo-text.svg"   # Text-only logo
BRAND_ICON = "brand/my-icon.svg"             # Small icon
BRAND_FAVICON = "brand/my-icon.ico"          # Browser tab icon
BRAND_SOCIAL_IMAGE = "brand/my-social.png"   # OG/social preview (1200x630)

# Site metadata
SITE_NAME = "My App"
SITE_DOMAIN = "myapp.com"

# Legal (set to "" to disable)
BRAND_PRIVACY_URL = "/privacy/"
BRAND_TERMS_URL = "/terms/"
BRAND_COOKIE_BANNER = True
BRAND_SIGNUP_TERMS_NOTICE = True
```

### 2.2 Add Brand Assets

Place logo and icon files in `static/brand/`:

```
static/brand/
├── my-logo.svg           # ~200px wide, light background
├── my-logo-dark.svg      # ~200px wide, dark background
├── my-logo-text.svg      # Text-only version
├── my-icon.svg           # Square icon (sidebar, topbar)
├── my-icon.ico           # Favicon (16x16 or 32x32)
└── my-social.png         # 1200x630 for social sharing
```

### 2.3 Choose Default Color Palette

In `config/settings/base.py`:

```python
SMALLSTACK_COLOR_PALETTE = "django"  # Options: django, high-contrast, dark-blue, orange, purple
```

Users can override this per-profile. To add a custom palette, see `docs/skills/theming-system.md`.

**Verify:** Reload the page. Logo, favicon, and site name should reflect your changes.

---

## Phase 3: Theme Strategy

SmallStack supports three theme scenarios. Choose one before building pages.

### Scenario A: Public Site + Staff Admin (Most Common)

Your public pages use a custom theme (Bootstrap, Tailwind, plain CSS). SmallStack's built-in tools (Explorer, Activity, Backups, etc.) keep their own theme at `/smallstack/`.

**What to create:**

1. **Custom base template** — `templates/mytheme/base.html`
2. **Public pages** — `templates/website/*.html` extending your base
3. **Views** — `apps/website/views.py`
4. **URLs** — `apps/website/urls.py`

**Key requirement:** Your custom base must include the SmallStack dark mode contract:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    {# Blocking script — prevents theme flash #}
    <script>
    (function() {
        var t = localStorage.getItem('smallstack-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', t);
        var p = localStorage.getItem('smallstack-palette') || '{{ color_palette }}';
        document.documentElement.setAttribute('data-palette', p);
    })();
    </script>
    <title>{% block title %}{% endblock %} | {{ brand.name }}</title>
    {% block extra_css %}{% endblock %}
</head>
<body>
    {% block content %}{% endblock %}

    {# SmallStack config object — before theme.js #}
    <script>
    window.SMALLSTACK = {
        userTheme: {% if user.is_authenticated %}'{{ user.profile.theme_preference }}'{% else %}null{% endif %},
        userPalette: {% if user.is_authenticated %}'{{ user.profile.color_palette }}'{% else %}null{% endif %},
        colorPalette: '{{ color_palette }}',
        isAuthenticated: {{ user.is_authenticated|yesno:"true,false" }},
        sidebarEnabled: false,
        sidebarOpen: false,
        topbarNavEnabled: false
    };
    </script>
    <script src="{% static 'smallstack/js/theme.js' %}" defer></script>
    {% block extra_js %}{% endblock %}
</body>
</html>
```

**Settings to consider:**

```python
SMALLSTACK_LOGIN_ENABLED = False       # Hide login from SmallStack topbar (your theme has its own)
LOGIN_REDIRECT_URL = "/"               # After login, go to your homepage
LOGOUT_REDIRECT_URL = "/"
```

See `docs/skills/adding-your-own-theme.md` for the full walkthrough.

### Scenario B: Public Site + Authenticated User Area

Same as Scenario A, but users log in and access an authenticated area (dashboard, settings, etc.) using your custom theme.

**Additional settings:**

```python
LOGIN_REDIRECT_URL = "/dashboard/"     # Your app's post-login page
SMALLSTACK_SIGNUP_ENABLED = True       # Allow public registration
```

### Scenario C: Build on SmallStack's Theme (Simplest)

Use SmallStack's built-in theme for everything. All pages extend `smallstack/base.html`. Sidebar, topbar, dark mode, and breadcrumbs work automatically.

**No custom base template needed.** Just create pages:

```html
{% extends "smallstack/base.html" %}
{% load theme_tags static %}

{% block title %}My Page{% endblock %}

{% block breadcrumbs %}
{% breadcrumb "Home" "home" %}
{% breadcrumb "My Page" %}
{% render_breadcrumbs %}
{% endblock %}

{% block content %}
<div class="card">
    <div class="card-header"><h1>My Page</h1></div>
    <div class="card-body">Content here</div>
</div>
{% endblock %}
```

See `docs/skills/theme-scenarios.md` for decision guidance.

---

## Phase 4: Build Your App

### 4.1 Landing Pages and Static Content

All landing pages go in the **website** app. This is the project-specific app that ships with SmallStack:

```
apps/website/
├── views.py      # Add view functions
├── urls.py       # Add routes
└── apps.py       # Register nav items

templates/website/
├── home.html     # Override the home page
├── about.html    # About page
└── pricing.html  # Any static pages
```

**Adding a new page:**

```python
# apps/website/views.py
def pricing_view(request):
    return render(request, "website/pricing.html")

# apps/website/urls.py
urlpatterns = [
    path("", home_view, name="home"),
    path("about/", about_view, name="about"),
    path("pricing/", pricing_view, name="pricing"),
]
```

Register in navigation if desired:

```python
# apps/website/apps.py
from apps.smallstack.navigation import nav

class WebsiteConfig(AppConfig):
    def ready(self):
        nav.register(section="topbar", label="Pricing", url_name="website:pricing", order=5)
```

### 4.2 Creating New Apps (Business Logic)

When adding new functionality (not just pages), create a new app:

```bash
mkdir -p apps/inventory
uv run python manage.py startapp inventory apps/inventory
```

> **Important:** Django's `startapp` generates `name = "inventory"` in `apps.py`, but SmallStack apps live under `apps/` and must use the dotted path `"apps.inventory"`. If you skip this step, Django will fail with an `AppRegistryNotReady` or `ModuleNotFoundError`. This is the most common setup mistake.

Fix the app config immediately after `startapp`:

```python
# apps/inventory/apps.py
class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"       # Must be "apps.<appname>", not just "<appname>"
    verbose_name = "Inventory"
```

Register in `config/settings/base.py`:

```python
INSTALLED_APPS = [
    # ... existing apps ...
    "apps.inventory",
]
```

Create models, then migrate:

```bash
make migrations          # Or: uv run python manage.py makemigrations inventory
make migrate
```

### 4.3 Navigation Registration

Register sidebar/topbar items in `apps.py`:

```python
from apps.smallstack.navigation import nav

class InventoryConfig(AppConfig):
    # ...
    def ready(self):
        nav.register(
            section="main",
            label="Inventory",
            url_name="inventory:list",
            icon_svg='<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="..."/></svg>',
            order=20,
            auth_required=True,
        )
```

**Sections:** `main` (sidebar + topbar), `topbar` (topbar only), `admin` (staff section), `resources` (help/links).

**Submenus:**

```python
nav.register(section="main", label="Inventory", url_name="inventory:list", order=20)
nav.register(section="main", label="Products", url_name="inventory:products", parent="Inventory", order=0)
nav.register(section="main", label="Warehouses", url_name="inventory:warehouses", parent="Inventory", order=1)
```

See `docs/skills/navigation.md` for the full API.

---

## Phase 5: CRUD Pages

SmallStack offers two paths for CRUD interfaces: **Explorer** (fastest) and **CRUDView** (most control).

### 5.1 Explorer — Auto-Generated CRUD (Fastest)

Register any model in Explorer for instant staff-facing CRUD at `/smallstack/explorer/`:

```python
# apps/inventory/explorer.py
from django.contrib import admin
from apps.explorer.registry import explorer
from apps.smallstack.displays import Table2Display, TableDisplay, CardDisplay
from .models import Product

class ProductExplorerAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "price", "in_stock", "created_at")
    explorer_displays = [Table2Display, TableDisplay, CardDisplay(title_field="name", subtitle_field="sku")]
    explorer_paginate_by = 25
    explorer_enable_api = True                  # Adds REST API at /api/...
    explorer_export_formats = ["csv", "json"]   # Enable export

explorer.register(Product, ProductExplorerAdmin, group="Inventory")
```

That's it. Explorer autodiscovers `explorer.py` files on startup. No URL wiring needed.

**Explorer-specific attributes:**

| Attribute | Default | Purpose |
|-----------|---------|---------|
| `explorer_displays` | `[Table2Display]` | List view display classes |
| `explorer_detail_displays` | `[]` | Detail view display classes |
| `explorer_fields` | auto-detected | Override which fields show |
| `explorer_readonly` | auto-detected | Force readonly (list + detail only) |
| `explorer_field_transforms` | `{}` | Field rendering transforms |
| `explorer_paginate_by` | `10` | Items per page |
| `explorer_enable_api` | `False` | Generate REST API endpoints |
| `explorer_export_formats` | `[]` | `["csv", "json"]` for export |

See `docs/skills/explorer.md` and `apps/explorer/content/admin-api.md` for the full API.

### 5.2 CRUDView — Custom CRUD Pages (Most Control)

Use CRUDView when you need custom layouts, public access, or production management pages:

```python
# apps/inventory/views.py
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay
from apps.smallstack.mixins import StaffRequiredMixin
from .models import Product

class ProductCRUDView(CRUDView):
    model = Product
    fields = ["name", "sku", "price", "in_stock", "category"]
    url_base = "inventory/products"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    displays = [TableDisplay]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = ("Inventory", "inventory:list")
    enable_api = True
```

Wire URLs:

```python
# apps/inventory/urls.py
from django.urls import path
from .views import ProductCRUDView

app_name = "inventory"

urlpatterns = [
    *ProductCRUDView.get_urls(),
]
```

Include in `config/urls.py`:

```python
path("", include("apps.inventory.urls")),
```

**This generates:**

| URL | Name | Purpose |
|-----|------|---------|
| `/inventory/products/` | `inventory/products-list` | List view |
| `/inventory/products/new/` | `inventory/products-create` | Create form |
| `/inventory/products/<pk>/edit/` | `inventory/products-update` | Edit form |
| `/inventory/products/<pk>/delete/` | `inventory/products-delete` | Delete confirmation |

**CRUDView key options:**

| Option | Purpose |
|--------|---------|
| `displays` | List view displays (TableDisplay, CardDisplay, Table2Display, or custom) |
| `detail_displays` | Detail view displays (DetailTableDisplay, DetailCardDisplay, or custom) |
| `form_class` | Custom ModelForm (auto-generated from `fields` if not set) |
| `table_class` | django-tables2 Table for sortable columns |
| `queryset` | Base queryset (default: `model.objects.all()`) |
| `search_fields` | Fields for API `?q=` search |
| `filter_fields` | Fields for API query-param filtering |
| `export_formats` | `["csv", "json"]` for API export |
| `field_transforms` | Dict of field rendering transforms |

**Hooks:**

```python
class ProductCRUDView(CRUDView):
    # Filter the list queryset
    @classmethod
    def get_list_queryset(cls, qs, request):
        return qs.filter(is_active=True)

    # Post-save callback
    @classmethod
    def on_form_valid(cls, request, form, obj, is_create):
        if is_create:
            log_activity(request, f"Created {obj}")

    # Per-object permission checks
    @classmethod
    def can_update(cls, obj, request):
        return obj.owner == request.user or request.user.is_staff

    @classmethod
    def can_delete(cls, obj, request):
        return request.user.is_staff
```

See `docs/skills/crud-views.md` for the full reference.

### 5.3 Custom Displays (Charts, Calendars, Cards)

Both Explorer and CRUDView support custom display classes that swap via HTMX:

```python
# apps/inventory/displays.py
from apps.smallstack.displays import ListDisplay, DetailDisplay

class InventoryGridDisplay(ListDisplay):
    name = "grid"
    icon = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="..."/></svg>'
    template_name = "inventory/displays/grid.html"

    def get_context(self, queryset, crud_config, request):
        return {
            "products": queryset.filter(in_stock=True),
            "out_of_stock": queryset.filter(in_stock=False).count(),
        }

class ProductStatsDisplay(DetailDisplay):
    name = "stats"
    icon = '<svg>...</svg>'
    template_name = "inventory/displays/stats.html"

    def get_context(self, obj, crud_config, request):
        return {"sales_30d": obj.sales.filter(date__gte=thirty_days_ago).count()}
```

Display templates are standalone fragments — no `{% extends %}` needed:

```html
{# templates/inventory/displays/grid.html #}
<style>
.inventory-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
</style>
<div class="inventory-grid">
    {% for product in products %}
    <div class="card">
        <div class="card-body">{{ product.name }} — ${{ product.price }}</div>
    </div>
    {% endfor %}
</div>
```

Register on CRUDView or Explorer:

```python
# CRUDView
class ProductCRUDView(CRUDView):
    displays = [TableDisplay, InventoryGridDisplay()]
    detail_displays = [DetailTableDisplay, ProductStatsDisplay()]

# Explorer
class ProductExplorerAdmin(admin.ModelAdmin):
    explorer_displays = [Table2Display, InventoryGridDisplay()]
    explorer_detail_displays = [DetailTableDisplay, ProductStatsDisplay()]
```

When multiple displays are registered, a palette of icon buttons appears. Clicking swaps the display via HTMX. The URL updates with `?display=grid` for bookmarking.

### 5.4 Explorer vs CRUDView — When to Use Which

| | Explorer | CRUDView |
|---|----------|----------|
| **Setup** | `explorer.register()` + ModelAdmin | View class + URL wiring |
| **Location** | All under `/smallstack/explorer/` | Any URL you choose |
| **Access** | Staff only | Any mixin (public, auth, staff) |
| **Customization** | Admin attributes + display classes | Full view/form/template control |
| **Best for** | Data browsing, internal tools, prototyping | Production pages, custom layouts |

**Start with Explorer** for rapid prototyping. **Graduate to CRUDView** when you need custom URLs, public access, or complex layouts.

### 5.5 REST API

Both Explorer and CRUDView can generate REST API endpoints:

```python
# Explorer
explorer_enable_api = True

# CRUDView
enable_api = True
```

This adds JSON endpoints with:
- Bearer token + session authentication
- GET (list with search/filter/pagination/export), POST (create)
- GET (detail), PUT/PATCH (update), DELETE
- Permissions cascade from view mixins

**Getting a token:**

```bash
uv run python manage.py create_api_token <username>
```

**Using the API:**

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8005/api/inventory/products/
```

**CORS for frontend projects:** SmallStack includes `django-cors-headers` — no additional installation needed. If your frontend runs on a different origin (e.g., React on port 3000), set `CORS_ALLOWED_ORIGINS` in `.env`:

```bash
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
```

**Filtering:** Add `filter_fields` to your view for query-parameter filtering (uses `django-filter`, included in dependencies). Date/DateTime fields automatically get range lookups (`__gte`, `__lte`, `__gt`, `__lt`):

```python
filter_fields = ["category", "in_stock", "created_at"]
# GET /api/inventory/products/?category=1&in_stock=true
# GET /api/inventory/products/?created_at__gte=2026-03-01
```

**FK expansion:** Add `api_expand_fields` to inline related object names instead of raw PKs:

```python
api_expand_fields = ["category"]
# Returns: "category": {"id": 3, "name": "Electronics"} instead of "category": 3
```

Clients can also request expansion per-request with `?expand=category,owner`.

**Aggregation:** Add `api_aggregate_fields` for server-side stats (avoids fetching all pages for dashboards):

```python
api_aggregate_fields = ["price"]
# GET /api/inventory/products/?count_by=in_stock → {"counts": {"true": 30, "false": 5}, ...}
# GET /api/inventory/products/?sum=price → {"sum_price": 12450.00, ...}
```

**Programmatic login:** `POST /api/auth/token/` exchanges credentials for a Bearer token (for SPAs and mobile apps).

See `docs/skills/api.md` for full details including CORS setup, pagination, serialization, and all query parameters.

---

## Phase 6: Email and Admin Notifications

### 6.1 SMTP Configuration

In `.env` (or `.kamal/secrets` for production):

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=myapp@gmail.com
EMAIL_HOST_PASSWORD=app-specific-password
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=noreply@myapp.com
```

**Verify locally:**

```python
# In Django shell (make shell)
from django.core.mail import send_mail
send_mail("Test", "Body", None, ["you@example.com"])
```

### 6.2 Admin Error Notifications

In `config/settings/production.py`, uncomment and set:

```python
ADMINS = [("Your Name", "you@example.com")]
SERVER_EMAIL = "server@myapp.com"
```

Django emails `ADMINS` on unhandled 500 errors. Backup failures also notify admins.

### 6.3 Background Email Tasks

Use background tasks for non-blocking email from views:

```python
from apps.tasks.tasks import send_email_task

# Single recipient
send_email_task.enqueue(
    recipient="user@example.com",
    subject="Order Confirmation",
    message="Your order #1234 has been placed."
)

# Multiple recipients (single task, single SMTP call)
send_email_task.enqueue(
    recipient=["owner@example.com", "backup@example.com"],
    subject="New Order",
    message="Order #1234 received."
)
```

The worker must be running to process email tasks:
- **Local dev:** `uv run python manage.py db_worker`
- **Docker/Kamal:** Worker service runs automatically

See `docs/skills/background-tasks.md` for the full task API.

---

## Phase 7: Docker Deployment

### 7.1 Local Docker Test

```bash
cp .env.example .env
# Edit .env: set DJANGO_SUPERUSER_* variables
docker compose up -d --build
```

**Verify:**

| URL | Check |
|-----|-------|
| `http://localhost:8010/` | Home page loads |
| `http://localhost:8010/health/` | Returns `{"status": "ok"}` |
| `http://localhost:8010/smallstack/` | Dashboard works after login |

**Logs:**
```bash
docker compose logs web -f
docker compose logs worker -f
```

### 7.2 Docker Architecture

```
┌─────────────────────────────────────┐
│  web container                      │
│  ├── gunicorn (2 workers, 4 threads)│
│  ├── supercronic (cron daemon)      │
│  │   ├── heartbeat (every 1m)       │
│  │   ├── prune activity (every 15m) │
│  │   └── backup db (daily 2 AM)     │
│  └── port 8000                      │
├─────────────────────────────────────┤
│  worker container                   │
│  └── db_worker (processes tasks)    │
├─────────────────────────────────────┤
│  volumes                            │
│  ├── db_data → /data (SQLite)       │
│  └── media_data → /app/media        │
└─────────────────────────────────────┘
```

---

## Phase 8: Kamal Production Deployment

### 8.1 Prerequisites

- VPS with SSH access (Ubuntu 22.04+ or Debian 12+)
- SSH key authentication configured
- Docker Desktop running locally
- Kamal installed: `brew install kamal` or `gem install kamal`
- Domain pointed to VPS IP (for HTTPS)

### 8.2 Configure Kamal

Edit `config/deploy.yml`:

```yaml
service: myapp                    # Your app name (lowercase, no spaces)
image: myapp

servers:
  web:
    - 123.45.67.89                # Your VPS IP
  worker:
    hosts:
      - 123.45.67.89
    cmd: python manage.py db_worker --queue-name "*"

volumes:
  - /root/myapp_data/media:/app/media
  - /root/myapp_data/db:/app/data

proxy:
  ssl: true                       # Enable Let's Encrypt HTTPS
  app_port: 8000
  hosts:
    - myapp.com
    - www.myapp.com
  healthcheck:
    path: /health/
    interval: 3
    timeout: 5

registry:
  server: localhost:5555          # Local registry (no Docker Hub needed)

builder:
  arch: amd64

deploy_timeout: 90               # Extra time for migrations on small VPS
```

### 8.3 Configure Secrets

Edit `.kamal/secrets`:

```bash
ALLOWED_HOSTS=myapp.com,www.myapp.com,123.45.67.89,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://myapp.com,https://www.myapp.com
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>
DJANGO_SUPERUSER_EMAIL=admin@myapp.com

# Email (for password reset and backup alerts)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=myapp@gmail.com
EMAIL_HOST_PASSWORD=<app-specific-password>
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=noreply@myapp.com

# HTTPS
SECURE_SSL_REDIRECT=true
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
```

### 8.4 Deploy

```bash
kamal setup    # First time: provisions server, installs Docker, deploys
kamal deploy   # Subsequent deploys: zero-downtime rolling update
```

**Verify:**

```bash
kamal app logs                    # Check for errors
curl https://myapp.com/health/    # Should return {"status": "ok"}
```

### 8.5 Common Kamal Commands

```bash
kamal deploy                      # Deploy latest code
kamal rollback                    # Rollback to previous version
kamal app logs                    # View web logs
kamal app logs --role worker      # View worker logs
kamal app exec "python manage.py migrate"       # Run management commands
kamal app exec "python manage.py create_api_token admin"  # Create API token
kamal lock release                # Release stuck deploy lock
```

### 8.6 Small VPS Cautions

- **Never run concurrent deploys** — doubles memory, can OOM a 1GB VPS
- **Never rapid-retry failed deploys** — stacks SSH connections, triggers fail2ban lockout
- **Pre-flight check:** `ssh root@<IP> "echo ok"` before deploying
- **Volume permissions:** Dirs must be owned by uid 1000. Fix with: `ssh root@<IP> "chown -R 1000:1000 /root/myapp_data/*"`

See `docs/skills/kamal-deployment.md` for the full deployment guide.

---

## Phase 9: Content Security Policy

If your custom theme loads external assets (Google Fonts, CDN scripts), update CSP in `config/settings/base.py`:

```python
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "'unsafe-inline'"],
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'", "https://fonts.gstatic.com"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
        "form-action": ["'self'"],
    }
}
```

**Production recommendation:** Vendor fonts and CSS frameworks locally in `static/` to avoid external dependencies and CSP complexity.

---

## Phase 10: Help Documentation

Add project-specific help pages:

1. Create markdown files in `apps/help/content/`:

```markdown
---
title: Getting Started
description: How to use this app
---

# Getting Started

Your content here...
```

2. Register in `apps/help/content/_config.yaml`:

```yaml
sections:
  - slug: ""
    pages:
      - slug: getting-started
        title: "Getting Started"
        description: "How to use this app"
        icon: "rocket"
        category: "Basics"
```

See `docs/skills/help-documentation.md` for the full guide.

---

## Quick Reference: File Placement

| What | Where |
|------|-------|
| Landing pages, static pages | `apps/website/views.py` + `templates/website/` |
| New business logic | New app in `apps/myapp/` |
| Custom theme base | `templates/mytheme/base.html` |
| Brand assets | `static/brand/` |
| Custom CSS | `static/css/` |
| Help documentation | `apps/help/content/` |
| Explorer registration | `apps/myapp/explorer.py` |
| Nav items | `apps/myapp/apps.py` in `ready()` |
| Background tasks | `apps/myapp/tasks.py` with `@task` decorator |
| Custom displays | `apps/myapp/displays.py` |
| Display templates | `apps/myapp/templates/myapp/displays/` |

## Quick Reference: Key URLs

| URL | Purpose | Access |
|-----|---------|--------|
| `/` | Home page | Public |
| `/smallstack/` | Staff dashboard | Staff |
| `/smallstack/explorer/` | Model browser | Staff |
| `/smallstack/accounts/login/` | Login | Public |
| `/accounts/login/` | Login (alias) | Public |
| `/status/` | Public status page | Public |
| `/health/` | Health check (JSON) | Public |
| `/help/` | Documentation | Public |
| `/admin/` | Django admin | Superuser |

## Quick Reference: Common Commands

```bash
# Development
make setup                    # First-time setup
make run                      # Start dev server (port 8005)
make test                     # Run tests
make lint-fix                 # Fix lint issues
make shell                    # Django shell
make migrations               # Create migrations
make migrate                  # Apply migrations
make backup                   # Manual database backup

# Docker
docker compose up -d --build  # Start containers
docker compose logs web -f    # Watch logs
docker compose down           # Stop containers

# Kamal
kamal setup                   # First deploy
kamal deploy                  # Update production
kamal app logs                # View logs
kamal rollback                # Rollback
```
