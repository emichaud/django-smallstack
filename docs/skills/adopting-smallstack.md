# Skill: Moving an Existing Django Project onto SmallStack

How to bring a working Django project (its apps, templates, users and data) onto SmallStack: start from a
fresh SmallStack clone and migrate your apps into it, one at a time, then adopt SmallStack's tools where they
help.

## Don't install SmallStack into your project

SmallStack is a platform, not a package. Its settings, database configuration and middleware are tuned
together for the SmallStack experience, and the apps rely on that tuning. An existing project has made its
own choices for the same settings, and the two collide:

**Settings.** `config/settings/` is split by environment (`base.py`, `development.py`, `production.py`,
`test.py`, plus `smallstack.py` with about 90 `SMALLSTACK_*` switches), read from `.env` through
python-decouple. Several of its values are platform decisions your project has probably decided differently:

- `AUTH_USER_MODEL = "accounts.User"`. Django lets a project choose this once, before its first migration;
  every app with a user foreign key depends on it.
- `LOGIN_URL` under `/smallstack/accounts/`, `django-axes` lockout as the first authentication backend, and
  SmallStack's password validators.
- A Content Security Policy (`django-csp`) with no inline JavaScript, which most existing templates break.
- `TASKS` on `django-tasks-db` with its own queues, CORS defaults, pinned cookie `SameSite`, `STORAGES` with
  WhiteNoise, `DEFAULT_AUTO_FIELD`, and template context processors for branding, notifications and runbooks.
- `LOGGING`: request-id filters, a JSON formatter in production, and a database log handler the
  `/smallstack/logs/` viewer reads.

**Database configuration.** SQLite is the default, tuned for production: WAL journal mode, `IMMEDIATE`
transactions, a busy timeout and cache pragmas on every connection. Apps add to the database at runtime: the
search app provisions its full-text index (FTS5 on SQLite, a `search_vector` column and GIN index on
PostgreSQL) after each `migrate`, and the datasets app registers a median aggregate on each SQLite
connection. A project with its own database setup (another engine, a router, several databases, connection
pooling) has to reconcile each of these.

**Middleware.** Eighteen middleware classes in a deliberate order. Some must come first (a health check that
answers before host validation, request ids every log line carries); some must follow authentication
(timezone, activity logging, notification read-tracking); others belong to the platform (WhiteNoise, CORS,
htmx and its login redirect, axes, CSP). Merging that list with an existing one, and keeping the order right,
is where adoption attempts break quietly: a request logged without its id, a login redirect returned to an
htmx request as a page.

**And the rest:** the URL layout (`/smallstack/…`, `/api/…`, `/mcp`, `/status/`), the base templates and
theme, and two dozen apps that depend on one another.

Laying all of that over an existing project means reconciling each of those with yours at the same time, in
a repository where you can no longer tell your code from SmallStack's. It also cuts you off from SmallStack's
updates, which arrive as merges into a clone (see `integration-workflow.md`): every setting you changed to fit
the old project conflicts again on the next merge.

The direction that works: **a fresh clone is the new project, and your apps move into it.** Your Django code
keeps working there, because SmallStack is ordinary Django. What changes is around it (settings, URLs,
users), and you deal with that once, per app.

## Before you start: an inventory

Write these down for the old project. Each one is a decision below.

| Question | Why it matters |
|---|---|
| Which apps are yours, and which are third-party? | Yours move; third-party ones become dependencies in `pyproject.toml` |
| Default `auth.User`, or a custom user model? | Decides how users move (step 6) |
| How much data, and which database? | `dumpdata`/`loaddata` for small or medium sets; a database-level copy for large ones |
| Which URLs must keep working? | Public links, API clients and webhooks pointing at you |
| Inline `<script>` or `onclick=` in templates? | SmallStack's Content Security Policy blocks inline JavaScript (step 5) |
| Background work: Celery, cron, management commands on a timer? | SmallStack has `django-tasks-db` and `@scheduled`; keep Celery only if you need it |
| An API: Django REST Framework, Ninja, hand-written views? | They can stay; `CRUDView`'s `enable_api` is an option, not a requirement |

## 1. Clone SmallStack, keeping it as `upstream`

Keep SmallStack's history and point it at a remote of its own, so updates can be merged later. Don't delete
`.git`: a fresh `git init` cuts the project off from SmallStack's releases.

```bash
git clone https://github.com/emichaud/django-smallstack.git myproject
cd myproject
git remote rename origin upstream          # SmallStack, for `git fetch upstream` + merge
git remote add origin git@github.com:yourorg/myproject.git
git push -u origin main
```

## 2. Set it up and make it yours

```bash
cp .env.example .env      # edit project values: SECRET_KEY, BRAND_*, email, database
make setup                # uv sync + migrate + dev superuser (admin/admin)
make run                  # http://localhost:8005
```

Then the decisions that apply to any new SmallStack project (`from-zero-to-running.md` covers them):
branding (`BRAND_*` settings, `static/brand/`), the default palette, and the public site in `apps/website/`.
Delete the demo pages in `apps/showcase/` now, before your apps arrive: remove the directory,
`"apps.showcase"` from `INSTALLED_APPS` in `config/settings/base.py`, and its `include()` in `config/urls.py`.

## 3. Move one app at a time

Move an app, get it to pass `manage.py check` and its tests, commit, then move the next. A project moved in
one go fails in a dozen places at once.

**Copy the code and its templates:**

```bash
cp -r /path/to/old-project/myapp apps/myapp
cp -r /path/to/old-project/templates/myapp templates/myapp   # if templates lived at the project root
```

**Point the AppConfig at its new location, and keep its label.** `name` changes; `label` stays what it was,
so table names (`myapp_order`), content types and permission codenames don't change:

```python
# apps/myapp/apps.py
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.myapp"   # the new location
    label = "myapp"       # what it was: same tables, content types, permissions

    def ready(self) -> None:
        from apps.smallstack.navigation import nav

        nav.register(section="main", label="My App", url_name="myapp:list", order=10)
```

**Fix imports** that named the old location (`from myapp.models` → `from apps.myapp.models`):

```bash
rg -l "(from|import) myapp\b" apps/myapp
```

**Install it and route it:** add `"apps.myapp"` to `INSTALLED_APPS` in `config/settings/base.py`, and
`path("myapp/", include("apps.myapp.urls"))` to `config/urls.py`. If a URL must keep its old address, mount
the app at that prefix. App settings of your own go in `config/settings/base.py`, read from `.env` with
`config(...)` like SmallStack's.

**Dependencies:** `uv add <package>` for each third-party package the app needs. `pyproject.toml` replaces
`requirements.txt`.

## 4. Start the app's migration history fresh

The new project has a new, empty database, so the old migration files have nothing to apply to. Delete them
and make one initial migration from the models as they are now:

```bash
find apps/myapp/migrations -name "0*.py" -delete
uv run python manage.py makemigrations myapp
uv run python manage.py migrate
```

That also drops any migration that named `auth.User` directly. Keep the old history only if you mean to
migrate the old database in place, which this guide doesn't recommend.

Data migrations in the old history that seeded rows (default categories, lookup values) don't survive this:
copy their code into a new `RunPython` migration, or let step 6 bring the rows over with the rest of the data.

## 5. Templates, sign-in and the Content Security Policy

**Templates can keep their own look.** A template doesn't have to extend `smallstack/base.html`: your app's
pages can stay on your existing base template while SmallStack runs the staff side. To move a page onto the
theme, extend `smallstack/base.html` and follow `modern-dark-theme.md` (theme variables, never colour
values). To put SmallStack's cards and dashboards on your own base, see `adding-your-own-theme.md`
(`{% smallstack_assets %}` and `{% smallstack_modal %}`).

**Sign-in goes through SmallStack's accounts:**

| Old | New |
|---|---|
| `@login_required(login_url="/admin/login/")` | `@login_required` (`LOGIN_URL` is `/smallstack/accounts/login/`) |
| `href="/admin/login/"`, `href="/accounts/login/"` | `href="{% url 'login' %}"` |
| `href="/admin/logout/"` | a POST form to `{% url 'logout' %}` |
| `from django.contrib.auth.models import User` | `get_user_model()`, or `settings.AUTH_USER_MODEL` in a `ForeignKey` |
| `ForeignKey("auth.User", …)` | `ForeignKey(settings.AUTH_USER_MODEL, …)` |

**Inline JavaScript is blocked.** The policy's `script-src` is `'self'` with no `'unsafe-inline'`, so a
`<script>…</script>` block or an `onclick="…"` in a template silently doesn't run (the browser console names
each blocked line). Move the script into a file under `static/`, and pass server values as `data-` attributes
or with `json_script`; `templates.md` has the recipe. A script from a CDN needs that origin added to
`script-src` in `CONTENT_SECURITY_POLICY` (`config/settings/base.py`), or the file copied into `static/`.
Inline styles are allowed.

## 6. Move the users, then the data

Migrate the new database first (`make migrate`), so content types and permissions exist. Then users, then
everything that points at them.

### Users from Django's default `auth.User`

`accounts.User` has the same fields (username, email, password hash, names, flags, groups, permissions,
dates), so users move as they are, passwords included: Django's hashers are the same, and people sign in
with the passwords they had.

```bash
# In the old project. Natural keys: users by username, groups by name, permissions by codename.
python manage.py dumpdata auth.group auth.user --natural-foreign --natural-primary --indent 2 > users.json
```

Two changes to the file before loading it:

- the model label: `"auth.user"` becomes `"accounts.user"`;
- empty emails: SmallStack's email is unique and may be null, while `auth.User` stores a missing email as
  `""`, so a second blank email fails the unique check. Turn `""` into `null`.

```bash
python3 - <<'EOF'
import json
rows = json.load(open("users.json"))
for row in rows:
    if row["model"] == "auth.user":
        row["model"] = "accounts.user"
        if not row["fields"].get("email"):
            row["fields"]["email"] = None
json.dump(rows, open("users.json", "w"), indent=2)
EOF
uv run python manage.py loaddata users.json   # in the new project
```

Two emails that differ only in case are still two accounts; find them in the old database before the move if
that matters to you. A user named `admin` in the file updates `make setup`'s dev superuser instead of
duplicating it. Profiles (`apps.profile`) are created for each loaded user automatically.

### Users from a custom user model

Map its fields onto `accounts.User`'s as above. Fields `accounts.User` doesn't have belong in a model of
your own with a `OneToOneField(settings.AUTH_USER_MODEL)`, not in `apps/accounts/`: that app is SmallStack's,
and changes to it conflict on every upstream merge.

### Your apps' data

```bash
# In the old project. --natural-foreign writes each user reference as a username, not an id.
python manage.py dumpdata myapp --natural-foreign --indent 2 > myapp.json
# In the new project:
uv run python manage.py loaddata myapp.json
```

`loaddata` resets PostgreSQL's id sequences itself. For data too large for JSON, copy the tables at the
database level instead (the kept app label keeps the table names the same), map user ids to the new
`accounts_user` ids, then run `manage.py sqlsequencereset myapp | manage.py dbshell`.

## 7. Adopt SmallStack's tools where they help

Nothing below is required: code that works can stay as it is. Each is worth it when it replaces something
you'd otherwise maintain.

| You have | Consider |
|---|---|
| Django admin pages for staff | Explorer (`explorer.register()` in `apps/myapp/explorer.py`, `explorer.md`) reads your `ModelAdmin` as it is, or a `CRUDView` for full control (`crud-views.md`) |
| Hand-written list/detail/form pages | A `CRUDView`: the pages, plus `enable_api`, `enable_mcp`, `enable_search`, `enable_webhooks` from flags |
| A REST API on DRF or Ninja | Keep it; or move a model's endpoints to `enable_api` to get OpenAPI, tokens and the same permissions as the pages (`api.md`) |
| Celery beat or cron jobs | `@scheduled` on a function (`scheduler.md`) |
| Celery tasks | `django-tasks-db` tasks run by `manage.py db_worker` (`background-tasks.md`) |
| A search page | `enable_search = True` (`search.md`) |
| Reports, charts, CSV exports | A `@dataset`, then metrics, dashboards and reports over it (`datasets.md`, `dashboards.md`) |
| Signals that call other systems | Outbound webhooks (`webhooks.md`) |
| An approval step in a workflow | `@approval_kind` and `request_approval()` (`approvals.md`) |
| Your own audit or log tables | `LogEntry` is written for every `CRUDView` write; logs go to `/smallstack/logs/` (`logging-audit.md`) |

## 8. Verify each app before moving the next

```bash
uv run python manage.py check
make test        # your tests and SmallStack's
make lint        # ruff + mypy + skill index
make run         # click through the app's pages
```

- [ ] The app's pages render, signed in and signed out as appropriate
- [ ] Old URLs that must keep working still answer
- [ ] Users sign in with their old passwords; groups and permissions came across
- [ ] Row counts match the old database for each model you moved
- [ ] The app appears in the sidebar; its models in Explorer, if registered
- [ ] No "Refused to execute inline script" errors in the browser console
- [ ] `/smallstack/` and `/admin/` still load

Your tests move with the app into `apps/myapp/tests/`. SmallStack's own tests should keep passing; one that
fails because of your change (a template, a URL, a setting) usually points at a real conflict, so fix the cause
rather than the test.

## Common issues

**`NoReverseMatch` after moving an app:** a template names a URL by its old name or without its namespace.
SmallStack's own templates don't reference your routes, so fix the reference in your template; don't edit
SmallStack's.

**`loaddata` fails on a user reference:** the data was dumped without `--natural-foreign`, so it carries old
user ids. Dump it again with the flag, after the users are loaded.

**A permission or content type is missing on load:** the app's `label` changed. Keep the old label in its
AppConfig (step 3).

**Explorer doesn't show a model:** check that `apps/myapp/explorer.py` exists and the app is in
`INSTALLED_APPS`, then restart the server: Explorer registers at startup.

**Upstream merges conflict in files you didn't mean to own:** you edited SmallStack's files (its templates,
`apps/smallstack/`, `apps/accounts/`). Move that change into your own app or `apps/website/`;
`integration-workflow.md` has the conflict table.

## With a coding agent

A move like this suits an agent, one app per session:

```text
I'm moving my Django app <myapp> from <path to old project> into this SmallStack project. Read AGENTS.md
and docs/skills/adopting-smallstack.md first, and follow it: copy the app into apps/<myapp>, keep its
app label, fix imports, add it to INSTALLED_APPS and config/urls.py, start its migrations fresh, and move
any inline JavaScript into static files. Don't edit SmallStack's own apps or templates. Run
`manage.py check`, `make test` and `make lint` until they pass, then tell me what still needs a decision from me.
```

Moving the users and data (step 6) is best done by you, against a copy of the production database first.
