# Skill: Adopting SmallStack into an Existing Django Project

How to integrate SmallStack into a pre-existing Django project that has its own apps, templates, and data. Two approaches: overlay into the existing repo (preserves git history) or fresh clone with app migration.

## When to Use This

- You have a working Django project with custom apps and want SmallStack's infrastructure (auth, profiles, help, activity, explorer, backups, theming)
- The existing project uses vanilla Django (default User model, basic settings, pip/requirements.txt)
- You want to keep the existing app's UI/templates while gaining SmallStack's staff-side tools

## Approach A: Overlay into Existing Repo (Recommended)

Preserves git history. Best when the existing project is the "source of truth" repo.

### A1. Prepare the Existing Project

Commit all pending work. Create a clean checkpoint:

```bash
cd /path/to/existing-project
git add -A && git commit -m "Pre-SmallStack integration checkpoint"
```

### A2. Clone SmallStack as a Reference

Clone SmallStack into a temporary directory — do NOT clone into the project:

```bash
git clone https://github.com/emichaud/django-smallstack.git /tmp/smallstack-ref
```

### A3. Back Up the Existing App

Move the existing app(s) out temporarily:

```bash
# If the app lives at the project root (e.g., runbooks/ with models.py, views.py)
mv myapp /tmp/myapp-backup

# If templates are at the project root
mv templates/myapp /tmp/myapp-templates-backup
```

### A4. Copy SmallStack Structure

Copy SmallStack's project structure into the existing project. Key directories:

```bash
# Core SmallStack apps
cp -r /tmp/smallstack-ref/apps/ ./apps/

# Config (settings, urls, wsgi, asgi)
cp -r /tmp/smallstack-ref/config/ ./config/

# Templates (base, error pages, email, etc.)
cp -r /tmp/smallstack-ref/templates/ ./templates/

# Static files (theme CSS, JS, brand assets)
cp -r /tmp/smallstack-ref/static/ ./static/

# Docs and skills
cp -r /tmp/smallstack-ref/docs/ ./docs/

# Build files
cp /tmp/smallstack-ref/Makefile .
cp /tmp/smallstack-ref/pyproject.toml .
cp /tmp/smallstack-ref/.env.example .
cp /tmp/smallstack-ref/.gitignore .
cp /tmp/smallstack-ref/manage.py .
```

### A5. Restore the Existing App

Move the app back into SmallStack's `apps/` directory:

```bash
# Move app into apps/ with SmallStack naming convention
mv /tmp/myapp-backup apps/myapp

# Restore templates
mv /tmp/myapp-templates-backup templates/myapp
```

### A6. Update the App's AppConfig

Change the app's `apps.py` to use the `apps.` prefix and register with SmallStack navigation:

```python
# apps/myapp/apps.py
from django.apps import AppConfig

class MyAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.myapp"          # Must match the new location
    verbose_name = "My App"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="main",
            label="My App",
            url_name="myapp:list",       # Your app's main URL name
            icon_svg='<svg>...</svg>',   # 20x20 SVG icon
            order=5,
        )
```

### A7. Update Internal Imports

If the app used absolute imports based on the old location, update them:

```python
# Old: from myapp.models import MyModel
# New: from apps.myapp.models import MyModel

# Old: from myapp.utils import helper
# New: from apps.myapp.utils import helper
```

Search for all internal imports:
```bash
rg "from myapp\." apps/myapp/ --files-with-matches
rg "import myapp\." apps/myapp/ --files-with-matches
```

### A8. Update Settings

Edit `config/settings/base.py`:

```python
INSTALLED_APPS = [
    # ... SmallStack apps (already present) ...
    "apps.myapp",          # Add your app
    # Add any third-party deps your app needs
    "some_third_party",
]
```

Add any app-specific settings your project needs (API keys, feature flags, etc.).

### A9. Update URLs

Edit `config/urls.py` to include your app's URLs:

```python
urlpatterns = [
    # ... SmallStack URLs (already present) ...
    path("myapp/", include("apps.myapp.urls")),
]
```

### A10. Update Auth References

SmallStack uses its own auth system. Replace any hardcoded auth URLs:

| Old Pattern | New Pattern |
|-------------|-------------|
| `@login_required(login_url='/admin/login/')` | `@login_required` |
| `@staff_member_required(login_url='/admin/login/')` | `@staff_member_required` |
| `href="/admin/login/"` | `href="{% url 'login' %}"` |
| `href="/admin/logout/"` | `href="{% url 'logout' %}"` |

SmallStack's `LOGIN_URL` is set to `/smallstack/accounts/login/` in base settings.

### A11. Convert to UV

Replace pip/requirements.txt with SmallStack's pyproject.toml:

1. Open `pyproject.toml` and add your app's dependencies to `[project.dependencies]`
2. Delete `requirements.txt`
3. Run setup:

```bash
make setup    # uv sync + migrate + create_dev_superuser
```

### A12. Handle the User Model

**Critical**: SmallStack uses a custom User model (`apps.accounts.models.User`). If the existing project used Django's default `auth.User`, you must reset the database:

```bash
rm db.sqlite3
make migrate
make superuser
```

If the existing project had real data, export it first:
```bash
uv run python manage.py dumpdata myapp --indent 2 > myapp_data.json
# After migration:
uv run python manage.py loaddata myapp_data.json
```

**Note**: `loaddata` will fail if any models have ForeignKey to User. In that case, recreate users first, then load data, or write a migration script that maps old user IDs to new ones.

### A13. Register Models in Explorer

Create `apps/myapp/explorer.py` to make models available in SmallStack Explorer:

```python
from django.contrib import admin
from apps.explorer.registry import explorer
from .models import MyModel, AnotherModel

class MyModelExplorerAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "created_at")
    search_fields = ("name",)
    list_filter = ("status",)

class AnotherModelExplorerAdmin(admin.ModelAdmin):
    list_display = ("title", "my_model", "updated_at")
    search_fields = ("title",)

explorer.register(MyModel, MyModelExplorerAdmin, group="My App")
explorer.register(AnotherModel, AnotherModelExplorerAdmin, group="My App")
```

Explorer autodiscovers `explorer.py` files — no URL wiring needed.

### A14. Simplify the Website App

SmallStack includes a `website` app for the homepage. Simplify it to work with your app:

```python
# apps/website/views.py
from django.shortcuts import redirect
from django.urls import reverse

def home_view(request):
    """Homepage — redirect to the main app."""
    return redirect(reverse("myapp:list"))
```

Update `apps/website/apps.py` to only register the Home nav item.

### A15. Fix SmallStack Templates

SmallStack's topbar template may reference URLs that don't exist in your project. Check:

```bash
uv run python manage.py check
```

Common fix: `templates/smallstack/includes/topbar.html` may have `{% url 'website:about' %}` — change to `{% url 'help:index' %}` or another valid URL.

### A16. Update .gitignore

SmallStack's `.gitignore` uses `staticfiles/` for collected static (not `static/`). Ensure your app's static files are tracked:

```gitignore
# SmallStack defaults
staticfiles/     # collectstatic output (not tracked)
# But static/ IS tracked (source static files)
```

### A17. Update Tests

SmallStack ships with tests that assume the default website app. Update or skip tests that reference removed pages:

```python
# apps/website/tests.py
import pytest

@pytest.mark.django_db
class TestWebsiteViews:
    def test_home_redirects(self, client):
        response = client.get("/")
        assert response.status_code == 302
        assert "/myapp/" in response.url
```

For SmallStack base tests that check `/` for template content (topbar, cookie banner), update them to hit a page that renders the SmallStack base template (e.g., `/smallstack/accounts/signup/`), or skip them if your project's public pages use custom templates.

### A18. Verify and Commit

```bash
uv run python manage.py check        # Django system checks
make test                              # Run test suite
uv run ruff check .                   # Lint
make run PORT=8105                    # Start dev server and spot-check
```

Commit the integration:
```bash
git add -A
git commit -m "Integrate SmallStack backend"
```

---

## Approach B: Fresh Clone with Data Migration

Start from a clean SmallStack clone and copy the app in. Best when you want a clean git history.

### B1. Clone SmallStack

```bash
git clone https://github.com/emichaud/django-smallstack.git myproject
cd myproject
rm -rf .git && git init
```

### B2. Setup SmallStack

```bash
cp .env.example .env
# Edit .env with project-specific values
make setup
```

### B3. Copy the App

```bash
cp -r /path/to/old-project/myapp apps/myapp
cp -r /path/to/old-project/templates/myapp templates/myapp
```

### B4. Follow Steps A6–A18

The remaining steps are identical: update AppConfig, imports, settings, URLs, auth references, Explorer registration, tests, and verify.

### B5. Migrate Data

Export from the old project:
```bash
cd /path/to/old-project
python manage.py dumpdata myapp --indent 2 > /tmp/myapp_data.json
```

Import into the new project:
```bash
cd /path/to/new-project
uv run python manage.py loaddata /tmp/myapp_data.json
```

**User data caveat**: If models reference Django's `auth.User` and SmallStack uses `accounts.User`, you'll need to either:
1. Export users separately and recreate them in SmallStack first
2. Write a data migration script that remaps user foreign keys
3. Accept starting fresh with users (simplest for dev/staging)

### B6. Set Remote

Point the new repo at the desired remote:
```bash
git remote add origin git@github.com:yourorg/myproject.git
git add -A && git commit -m "Initial SmallStack integration"
git push -u origin main
```

---

## Common Issues

### Migration Conflicts

If the existing app has migrations that conflict with SmallStack:

```bash
uv run python manage.py makemigrations --merge --noinput
```

If both sides created the same model, delete the duplicate migration and keep one. Add any missing operations (like `AlterModelOptions`) to the surviving migration.

### AUTH_USER_MODEL Mismatch

SmallStack sets `AUTH_USER_MODEL = "accounts.User"`. If the old project used `auth.User`, any model with `ForeignKey(settings.AUTH_USER_MODEL)` will break. Options:

1. **Dev/staging**: Delete `db.sqlite3` and start fresh
2. **Production with data**: Write a data migration that creates matching users in the new model, then updates all foreign keys

### CDN Resources Blocked by CSP

SmallStack's Content Security Policy may block CDN-loaded CSS/JS (e.g., Bootstrap from CDN). Fix by either:
1. Download the files locally into `static/`
2. Add the CDN domain to CSP settings in `config/settings/base.py`

### Templates Not Extending SmallStack Base

If the existing app has standalone HTML templates (not extending `smallstack/base.html`), they'll work fine — SmallStack doesn't require all pages to use its base template. The app keeps its own look while SmallStack provides the staff-side infrastructure.

### Explorer Not Showing Models

- Verify `explorer.py` exists in your app directory
- Verify the app is in `INSTALLED_APPS`
- Explorer autodiscovers on startup — restart the dev server after creating `explorer.py`

## Verification Checklist

After integration, verify each of these works:

- [ ] `uv run python manage.py check` — no errors
- [ ] `make test` — all tests pass (or known skips documented)
- [ ] Homepage loads (redirect or full page)
- [ ] Your app's main page renders correctly
- [ ] SmallStack dashboard at `/smallstack/` shows widgets
- [ ] Your app appears in SmallStack sidebar navigation
- [ ] Login/logout works through SmallStack auth
- [ ] Explorer at `/smallstack/explorer/` shows your models
- [ ] Django admin at `/admin/` shows your models
- [ ] Static files load (CSS, JS, images)

## Port Conventions

When running the integrated project for testing, use a port that doesn't conflict:

```bash
make run PORT=8105    # Add 100 to your project's normal port
```

Kill the test server when done — don't leave it running.
