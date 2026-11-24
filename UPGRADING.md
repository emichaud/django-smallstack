# Upgrading SmallStack

Breaking changes and the migration steps for each. Any project built on SmallStack should
read the section for every version it crosses when pulling upstream.

Most releases are non-breaking patch/minor bumps and won't appear here. If a release isn't
listed, no downstream migration is required.

---

## v0.33.0 — access reviews, the evidence pack, directory-managed groups

**Who is affected:** projects that set `SMALLSTACK_PRIVATE_MEDIA_PREFIXES` themselves, projects that
grant `is_superuser` or set `user.groups` from a sign-in backend, and every project (three migrations).

**What changed.** The Access app gains reviews, stored evidence packs and directory identities, and
SmallStack ships a sixth group, *Access attester*.

**Migration.**

1. `make migrate`. This adds the review, review item, evidence bundle and directory identity tables,
   `signed_request_id` on reviews and a `directory_role` on declared groups, and creates the *Access attester* group with no members.
2. If you set `SMALLSTACK_PRIVATE_MEDIA_PREFIXES` in `.env` or settings, add `access/` to it.
   Otherwise stored evidence packs are served by the public `/media/` route.
3. Nothing is scheduled unless you set `SMALLSTACK_ACCESS_REVIEW_CADENCE=quarterly`. If you do, run a
   worker for the scheduler, and `db_worker --queue-name webhooks` for the `access.review.signed`
   deliveries, and set `SITE_URL` so the emailed and webhook links are absolute.
4. **Session writes to the API need the CSRF token.** A browser script that POSTs/PUTs/PATCHes/
   DELETEs to `/smallstack/api/…` (or your own `@api_view` / `authenticate_api_request` views) on the
   signed-in session must now send `X-CSRFToken` (the `csrftoken` cookie's value), or it gets 403.
   Scripts and SPAs that use an API token are unaffected. A hand-written JSON view whose POST is a
   pure dry run may pass `authenticate_api_request(request, check_csrf=False)`.
   **Deprecation path:** if you can't add the header before upgrading, set
   `SMALLSTACK_API_SESSION_CSRF=False` for this release. Session writes without the token are then
   allowed and each is logged (`apps.smallstack.api`, WARNING: method, path, reason; a route with its
   own CSRF check, such as the dashboard picture upload, still refuses), and
   `manage.py check` warns `smallstack.W002`. Grep the log for "allowed because
   SMALLSTACK_API_SESSION_CSRF=False", fix those callers, then remove the setting. The switch is
   removed in 0.34.0.
5. Tests that build a session write with `RequestFactory` and call an API view directly set
   `request._dont_enforce_csrf_checks = True`, as Django's test `Client` does.
6. Staff without `accounts.view_user` no longer see the *Users* card on `/smallstack/` (it shows
   account counts); give a widget of your own that shows account or access data a `visible_to`.
7. If a sign-in backend sets `user.groups` or `is_superuser` from claims, move it to
   `apps.access.directory.sign_in` and declare the groups with `directory_role`
   (`docs/skills/directory-sso.md`, "The migration from 'we already set groups ourselves'").

---

## v0.32.0 — the Access app

**Who is affected:** every downstream project (a new app and a middleware line), and any project
with its own copy of `config/settings/base.py` or `apps/smallstack/site_urls.py`.

**What changed.** `apps/access` records every change to access and provides `/smallstack/access/`.
It needs an app entry, a middleware entry and a migration.

**Migration.**

1. `config/settings/base.py`: add `"apps.access",` to `INSTALLED_APPS` after `"apps.usermanager",`.
2. `config/settings/base.py`: add `"apps.access.context.ActorMiddleware",` to `MIDDLEWARE` right after
   `"django.contrib.auth.middleware.AuthenticationMiddleware",`. Without it, changes made on a page are
   recorded with no actor (as `system`); nothing else breaks.
3. If your `apps/smallstack/site_urls.py` diverged from upstream, add
   `path("access/", include("apps.access.urls")),` beside the User Manager's include.
4. `make migrate`. This creates two tables and SmallStack's five shipped groups (Access reviewer, User
   manager, Log reader, Approver, Token manager), each with its permissions and no members. Their
   creation is itself recorded as the first events.

**Then look at the overview once.** It will likely report findings on day one (more superusers than
needed, dormant accounts, permissions granted directly). Those describe your existing data, not a
regression; the page says what to do about each.

**The User Manager now asks for Django's user permissions.** Creating an account at
`/smallstack/manage/users/` needs `accounts.add_user`, editing one (including the staff and active
flags, a reset link and an unlock) needs `accounts.change_user`, and deleting needs
`accounts.delete_user`; only a superuser may change a superuser's account. Staff without those
permissions still see the pages, read-only. If people on your team managed accounts there with the
staff flag alone, add them to the shipped **User manager** group (`add_user` + `change_user`) — or
give `delete_user` directly to whoever should delete accounts — before you deploy.

**Inviting by email now asks for the same permission.** `/smallstack/accounts/invite/` needs
`accounts.add_user`, and ticking *Grant staff access* there also needs `accounts.change_user`. The
same goes for the *Staff* box on the User Manager's create page and Explorer's user create form: an
`add_user` holder without `change_user` creates non-staff accounts only. Staff
who sent invites with the staff flag alone belong in the **User manager** group.

**Adding someone to a group now needs every permission the group grants.** On the Access pages, REST,
approvals and the CLI, an actor holding `accounts.change_user` may add a member only to a group whose
permissions they hold themselves (superusers: any group). Removal is unchanged.

**Explorer now asks for model permissions on accounts, groups, permissions, API tokens, the change
history and the Access app's models, even with `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` off.** A staff
account that browsed or edited those in Explorer with no permissions now gets a 403 there. Give the
people who should keep that access the shipped group that fits (User manager, Token manager, Log
reader, Access reviewer) or the `view_*` / `change_*` permissions directly. A ModelAdmin's
`explorer_model_permissions = False` no longer turns the check off for these models. Explorer also
follows a ModelAdmin's own `has_*_permission` overrides now, so a ModelAdmin that refuses deletes
refuses them in Explorer too, and an API token's owner is read-only once the token exists.

**Explorer also asks those overrides per row.** For each row's edit and delete (the buttons, the
edit and delete pages, bulk actions, REST and MCP), Explorer calls the ModelAdmin's
`has_change_permission(request, obj)` / `has_delete_permission(request, obj)` with the row, as Django
admin does, whatever `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` says. Check your own ModelAdmins: one
that overrides either method with a rule on `obj` now has it enforced in Explorer, and one that just
returns `super()...` brings Django's model-permission check with it, so staff without
`change_<model>` / `delete_<model>` lose edit or delete on that model in Explorer. If a rule was only
meant for Django admin, check `request.resolver_match.namespace` or move it to `get_readonly_fields()`;
if staff need the access, grant the permission. A method that raises refuses (fails closed).

**Minting an API token for someone else now needs `smallstack.add_apitoken`.** At
`/smallstack/tokens/create/`, staff without it mint only for themselves. With it (the shipped **Token
manager** group), they may pick an active non-superuser holding no permission they lack; only a
superuser mints for a superuser or chooses the `auth` level. If someone on your team minted tokens for
service accounts, put them in Token manager, or have a superuser mint those.

**Revoking someone else's API token now needs `smallstack.change_apitoken`.** (The Access user
page's *Revoke tokens & sign out* also accepts `accounts.change_user`, the User manager's, since that
role can deactivate the account anyway; it can't be used on your own account.) Anyone still revokes
their own; staff who revoked other accounts' tokens with the staff flag alone belong in **Token
manager**, and only a superuser revokes a superuser's token. Every revoke is now a `token_revoked`
access event; if you recorded revocations yourself, you now record them twice.

**The `/api/auth/` account endpoints are bounded by the token's owner.** An auth-level token now needs
an owner who is active staff holding `accounts.change_user` to update, deactivate or reset a password
(and `accounts.add_user` to register); only a superuser's token changes a superuser. A server that
manages accounts with an auth-level token owned by a plain staff account gets 403: put that account in
the shipped **User manager** group. A token's `access_level` can no longer be edited after it is made;
mint a new token instead.

**Changing another account's password, email or username needs every permission that account holds.**
The User Manager (edit and *Send link*), `/api/auth/users/<id>/password/`, a `PATCH` of `email` on
`/api/auth/users/<id>/`, Django admin's password form and user form, and Explorer's user form now refuse
it (with the missing permissions named) unless the actor holds all of the account's permissions or is a
superuser. A User manager can still edit the name and the staff and active flags of a wider account.
Have a superuser (or someone holding the account's permissions) reset the passwords of privileged
accounts; a server that rotates service-account passwords over the API needs a token owner holding
everything those accounts hold.

**Reading accounts, access and other accounts' tokens now needs a `view` permission, not just staff.**
The Access pages, REST reads and MCP read tools, the User Manager's list and pages (not its Timezones
dashboard, which stays open to staff and shows names and time zones only), `GET /api/auth/users/` and user search hits need `accounts.view_user`; seeing other
accounts' API tokens on the Token Manager needs `smallstack.view_apitoken` (everyone still sees their
own). Superusers are unaffected. **Staff who relied on the staff flag to read these get a 403** (and no
longer see the Access and Users links): put auditors in **Access reviewer**, people who manage accounts
in **User manager**, and people who look after tokens in **Token manager** before you deploy. A script
reading `/smallstack/api/access/` or `/api/auth/users/` needs its token's owner to hold `view_user`. A
custom group that should read these needs those permissions added.

**Reset and invite tokens are redacted from the activity log and the captured logs.** Until now
`RequestLog.path` held every opened password-reset and invite link in full, readable by any staff
account at `/smallstack/activity/`. `make migrate` runs `activity.0005` and `telemetry.0002`, which
replace the token in rows already stored (`/accounts/reset/MQ/***/`); nothing to configure. **The
migration does not invalidate the links themselves.** A reset or invite link issued before the upgrade
stays valid until it is used or expires (`PASSWORD_RESET_TIMEOUT`, one day in SmallStack's settings), and anyone who
read it from the log before the upgrade can still use it. If staff you don't fully trust could read the
activity log, rotate: ask the holders of privileged accounts to change their password (that voids every
outstanding link for the account), or wait out `PASSWORD_RESET_TIMEOUT` before relying on the fix. Copies
of the log outside the database (backups, exported CSVs, a log shipper) are not touched. A URL parameter
of your own that carries a one-time credential should be named `token`, so the request log redacts it.
**If you keep your own `gunicorn.conf`,** add `logger_class = "apps.smallstack.gunicorn_logging.RedactingLogger"`
to it: without it the server's access log (stdout, `kamal app logs`) keeps printing reset links in
full. A proxy in front (kamal-proxy, nginx, a CDN) logs paths itself; limit who reads those logs.

**If your project records access changes itself** (a signal on `user.groups`, a custom audit of the
staff flag), it now does so twice; keep yours only if it records something these events don't.

---

## v0.31.0 — CRUDView pages write their own audit entries

**Who is affected:** a CRUDView that records its web writes itself: `AuditMixin` added through
`view_mixins`, or a `log_action()` call in `on_form_valid` or `on_delete`.

**What changed.** The generated create, edit and delete pages now write the `LogEntry` for each
write, as REST, MCP, `sc` and the bulk views always did. Your own call now duplicates it.

**Migration.** Remove the `AuditMixin` from `view_mixins`, or the `log_action()` call from the hook.
To find them: `grep -rn "AuditMixin\|log_action(" apps/ | grep -v tests`. A hook that logs something the
framework doesn't (a custom message, a related object) can stay.

**Also new, nothing to migrate:** `model_permissions = True` (Django model permissions on every
surface, off by default), `SMALLSTACK_EXPLORER_MODEL_PERMISSIONS` for Explorer (off by default),
`enable_history = True` for a per-row History page (on for Explorer models), and a delete confirmation
that lists what cascades. A custom `object_confirm_delete.html` keeps working; include
`smallstack/crud/includes/delete_summary.html` in it to show the cascade.

---

## v0.30.3 — SmallStack's loggers are named by module

**Who is affected:** anything keyed on SmallStack's logger names: a `LOGGING` entry of your own, a log
alert or saved search, a `grep smallstack.mcp` in a runbook, `TELEMETRY_CAPTURE_LOGGERS`.

**What changed.** The framework apps logged as `smallstack.<app>` (`smallstack.webhooks`,
`smallstack.mcp.views`, …). They now use `logging.getLogger(__name__)`, so the names are module paths:
`apps.webhooks.services`, `apps.mcp.views`, `apps.mcp.oauth_views`. The `apps` logger already configured in
settings covers them all. MCP's own entry (INFO, so it doesn't log every tool it registers) is now
`apps.mcp`. A `smallstack` logger is still configured, for code of your own written to the old convention.

**Migration.**

- In your `LOGGING`, rename a `smallstack.mcp` entry to `apps.mcp`, and any other `smallstack.<app>` entry
  to `apps.<app>`.
- Update log searches and alerts the same way; old records in `/smallstack/logs/` keep their old names.
- Your own code on `getLogger("smallstack.…")` keeps working; `getLogger(__name__)` is the convention.

## v0.30.3 — the design tokens move to `core.css`; embeds on your own theme

**Who is affected:** forks that edited token values in `static/smallstack/css/theme.css`, and projects
whose own base template (not `smallstack/base.html`) shows SmallStack embeds.

**What changed.**

- The `:root` and `[data-theme="dark"]` custom properties and `.sr-only` moved from `theme.css` to a new
  `core.css`, which `theme.css` imports first. The drill-down modal, help-bubble and stat-list rules moved
  to the end of `components.css`. Pages on `smallstack/base.html` load the same CSS as before (computed
  styles checked unchanged).
- New tags in `theme_tags`: `{% smallstack_assets %}` (head) and `{% smallstack_modal %}` (end of body).

**Migration.**

- **Edited tokens in `theme.css`?** The merge conflicts there. Keep upstream's `theme.css` and redo your
  edits in `core.css`, or better, in a palette (`docs/skills/modify-palettes.md`), which upgrades never touch.
- **Embeds on your own base template:** add the two tags (see Step 2 of `adding-your-own-theme.md`). Remove
  any `{% include "smallstack/includes/stat_modal.html" %}` you added by hand; `{% smallstack_modal %}`
  renders it once.

## v0.30.2 — a theme built from the theming guide doesn't save the light/dark choice

**Who is affected:** projects with their own base template (Bootstrap, Tailwind, a bought theme) built
from `adding-your-own-theme.md` or `theme-scenarios.md`. Pages on `smallstack/base.html` are fine.

**Symptom.** A signed-in user toggles to light on one of your pages; the next page load is dark again.
The guide's config left out the URLs `theme.js` saves to, so the toggle changed only the browser's copy,
and the profile's saved theme wins on load.

**Migration.** Copy the two script blocks from the guide's Step 2 into your base template:

- `theme-init.js` in `<head>`, with `data-user-theme` / `data-user-palette` so a new browser paints the
  saved theme first.
- `config.js` with `data-theme-url="{% url 'theme_preference' %}"` and
  `data-palette-url="{% url 'palette_preference' %}"`, then htmx and `theme.js`. Keep
  `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` on `<body>`; the save is a POST.

Either replaces an inline `<script>` theme block, which the CSP refuses anyway unless you kept the
`'unsafe-inline'` stopgap. `grep -rn "window.SMALLSTACK = {" templates apps` finds an old setup.

## v0.30.1 — SmallStack's demo pages move to `apps/showcase`; error pages become app defaults

**Who is affected:** every project, once. This is the merge that stops `apps/website/`, the error
pages and `README.md` conflicting on every later release.

**What changed.**

- The demo pages left `apps/website/` for a new app, **`apps/showcase/`** (namespace `showcase`):
  about, getting started, prompts, both platform pages, the starter pages, `/components/` and the
  public `/search/`. Their URLs are unchanged; their names went from `website:about` to
  `showcase:about` (and so on). Their templates and static moved with them (from
  `templates/website/`, `templates/starter*`, `smallstack/pages/{about,getting_started,starter}_*`
  and `static/website/` + `static/starter/`). `apps/website/` keeps the home page, `base.html` and
  the chart card types (`dashboard_cards.py`).
- The 400/403/404/500 pages moved from `templates/` to `apps/smallstack/templates/`, and
  `errors.css` to `static/smallstack/css/templates/errors.css`. A `templates/404.html` of your own
  now overrides the default without upstream ever shipping that path.
- `README.md` is short and stable; SmallStack's description is `docs/smallstack.md`.

**Migration.**

- **Conflicts on files you rewrote** (`apps/website/views.py`, `urls.py`, `templates/website/*.html`,
  `templates/40x.html`, `README.md`): keep yours. Upstream deleted or shrank them; nothing you keep
  there is overwritten again.
- **Links to the moved pages:** `grep -rnE "website:(about|getting_started|prompts|platform_|starter|components|search)" apps templates`
  finds any left in your own templates. Point them at `showcase:…`, or use
  `{% url 'showcase:about' as u %}{% if u %}…{% endif %}` so they survive deleting the app.
- **Your own error pages** linking `website/css/templates/errors.css`: point them at
  `smallstack/css/templates/errors.css`.
- **Don't want the demo pages:** delete `apps/showcase/`, `"apps.showcase"` from `INSTALLED_APPS`
  and its `include()` from `config/urls.py`. Keep them out on later merges (the conflict table in
  `docs/skills/integration-workflow.md` says how).

## v0.30.1 — a dataset filter value that won't parse is refused

**Who is affected:** code or links that send a dataset a flat filter it can't read:
`?created_at__gte=2026-13-45`, an unknown `__period` key, a non-number on a numeric column.

**What changed.** Such a value used to be dropped, so the request returned every row. It now
raises `ValueError` from `rows()`/`series()`/`scalar()`/`cells()`, a 400 over REST, and the
dataset browser shows no rows with "These filters can't be applied". A blank value still means no
filter.

**Migration.** Check callers that build filter values themselves; `Dataset.filter_problems(filters)`
lists what a set of filters would refuse without running a query. Each schema filter's `lookups`
names the suffixes it takes.

## v0.30.0 at a glance — what changes a build coming from 0.29

Each line is one thing to check. The sections below have the details.

- **CSP: `script-src` has no `'unsafe-inline'`.** Inline `<script>` blocks and `on…=` handlers in
  your own templates stop running. See *inline scripts are blocked* below.
- **A new app, `apps.dashboards`, is in `INSTALLED_APPS`:** a nav item (on by default), MCP tools,
  14 migrations, and the shipped defaults synced after every migrate. See *dashboards arrive* below.
- **Webhooks get their own queue and worker:** `webhooks` in `TASKS`, `WORKER_WEBHOOKS` in the
  entrypoint, `SMALLSTACK_WEBHOOK_QUEUE`.
- **Invite and sign-in-code emails are queued;** `EMAIL_TIMEOUT` now defaults to 10 seconds.
  `SMALLSTACK_ACCOUNTS_EMAILS_INLINE` keeps the old in-request send.
- **Cards over a dataset carry their own source** (migration `0012_card_sources`), and only
  administrators change a dashboard's address.
- **New settings, all with working defaults:** `SMALLSTACK_DASHBOARDS_ENABLED`,
  `SMALLSTACK_DASHBOARD_DEFAULTS_SYNC`, `SMALLSTACK_ACCOUNTS_EMAILS_INLINE`,
  `SMALLSTACK_WEBHOOK_QUEUE`, `SMALLSTACK_FEEDS_MAX_CONCURRENT_FETCHES`,
  `HEARTBEAT_MAX_CONCURRENT_CHECKS` (8, endpoint checks probed in parallel) and
  `HEARTBEAT_RUN_DEADLINE_SECONDS` (50, a probe still running this long counts as down).

## v0.30.0 — inline scripts are blocked

**Who is affected:** any project whose own templates carry an inline `<script>` block or an
`onclick="…"` (or any `on…=`) handler.

**What changed.** The CSP's `script-src` is `'self'` with no `'unsafe-inline'`, in settings and on
the API docs pages. The browser refuses inline code and logs the blocked line in the console; the
page still renders, so the symptom is a control that does nothing. Every SmallStack template moved
its code to static files. Four tests guard the policy: `test_csp_script_src_allows_no_inline_script`
and the inline script, handler and `<style>` sweeps in `apps/smallstack/test_template_hygiene.py`.

**Migration.**

- **Size it.** From v0.30.1, `manage.py template_hygiene` lists every inline script,
  handler and style block by file and line. On 0.30.0 itself, grep:

  ```bash
  grep -rnE --include='*.html' '<script\b[^>]*>' apps templates \
    | grep -vE 'src=|type="(application/(ld\+)?json|text/template|importmap)"'   # inline blocks
  grep -rnE --include='*.html' " on[a-z]+=[\"']" apps templates                  # handlers
  ```
- **Move them** as `docs/skills/templates.md` describes: scripts to static files with server values on
  data- attributes, handlers to `data-confirm` / `data-autosubmit` / `data-ss-action`.
- **Stopgap:** add `"'unsafe-inline'"` back to `CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]`.
  On 0.30.0 the four tests above then fail, because they sweep your templates too; skip them in your
  `conftest.py` until you take v0.30.1. From v0.30.1 they follow the policy in
  force: with the stopgap, only SmallStack's templates are swept, and the settings test skips.
- **A step between:** django-csp's nonce (`csp.constants.NONCE` in `script-src`,
  `nonce="{{ request.csp_nonce }}"` on a block you can't move yet). A browser that sees a nonce
  ignores `'unsafe-inline'`, and a nonce can't cover an `on…=` handler, so move the handlers first.

## v0.30.0 — dashboards arrive (a new app in `INSTALLED_APPS`)

**Who is affected:** every project, since `apps.dashboards` is in the bundled `INSTALLED_APPS`.

**What changed.** The app (label `smallstack_dashboards`) adds metrics, dashboards, reports, goal
lists and playlists at `/smallstack/dashboards/`, a nav item, MCP tools, and 14 migrations. After
every migrate it creates and updates the defaults apps ship (`dashboard_defaults.py`), never
overwriting an edited one. With it installed, the `/smallstack/` page is an editable dashboard.

**Migration.**

- Merging your own `INSTALLED_APPS`: keep `"apps.dashboards"` and run `make migrate`.
- Don't want it yet: set `SMALLSTACK_DASHBOARDS_ENABLED=False`. The nav item, routes and MCP tools go
  away, while the app stays installed so turning it on later needs no schema change.
- Don't want the defaults synced on migrate (a deploy that migrates on boot, say): set
  `SMALLSTACK_DASHBOARD_DEFAULTS_SYNC=False` and run `manage.py dashboard_defaults` when you choose.

## v0.30.0 — webhooks get a queue and a worker of their own

**Who is affected:** deployments using the bundled `docker-entrypoint.sh`, and
projects that override `TASKS`.

**What changed.** Outbound webhook deliveries run on a new `webhooks` task
queue when `TASKS` lists it (the bundled `base.py` does). The entrypoint now
starts one extra inline worker for that queue (`WORKER_WEBHOOKS`, default 1),
and the main worker skips it. That is one more Python process in the web
container, roughly 60 to 80 MB.

**Migration.**

- Your own `TASKS` setting without `webhooks`: nothing breaks, deliveries stay
  on `default`. Add `"webhooks"` to `QUEUES` to get the isolation.
- Tight on memory: set `WORKER_WEBHOOKS=0` to run everything on one worker,
  as before.
- A separate worker role or container with `--queue-name "*"` still delivers
  webhooks. To isolate them there, see the commented examples in
  `config/deploy.yml` and `docker-compose.yml`.

## v0.30.0 — invite and sign-in-code emails are queued; SMTP times out

**Who is affected:** production deployments that send staff invites or use
passwordless sign-in (`SMALLSTACK_PASSWORDLESS_LOGIN`) and run **no task
worker** — `WORKER_INLINE=false` with no separate worker role.

**What changed.** These two emails used to be sent inside the request, so a
slow mail server held a web thread while the user waited. They are now queued
on the `email` task queue, like the welcome, runbook and approval emails. With
no worker they are never sent. Separately, `EMAIL_TIMEOUT` now defaults to 10
seconds; unset used to mean no timeout at all.

**Migration.**

- Run a worker that drains `email` (the default container already does), or
  set `SMALLSTACK_ACCOUNTS_EMAILS_INLINE=True` to keep sending in the request.
- If your mail server legitimately needs longer than 10 seconds, set
  `EMAIL_TIMEOUT`; `0` restores the old no-timeout behaviour.
- `send_invite_email(request, user, inviter)` keeps its signature.
  `send_login_code_email(request, user, code)` still sends immediately; the
  passwordless view now calls `send_login_code(request, login_code)` instead.

## v0.30.0 — a chart filters a dataset of its own; a metric goes on a single stat

**Who is affected:** any project with dashboard cards, and any app that
registers a `ComponentType` of its own (a chart) or writes cards over REST or
MCP.

**What changed.** A card that draws data has one of two sources. **A dataset
it filters itself:** `dataset` + `filter_tree` + `agg`/`measure` +
`period_field`, the definition a metric holds, kept on the card (new
`Component` fields, and the same keys on a dashboard cell). **A saved
metric:** `metric`, now only on a design whose `single_value` is true (the
single stat): a metric is a filtered result rolled up to one number, for
goals and thresholds, and a chart needs the rows. A metric with no dataset to
filter (entered by hand, a rate) may still be charted as it is. Saving a
grouped stat, a pie, ranked bars or a trend over a dataset metric is refused
on every surface, with the fields to give it instead.

`smallstack_dashboards.0012_card_sources` copies each metric's definition into
every chart and grouped card that was bound to one (saved cards and dashboard
cells), with the metric's format, unit and colour rules as the card's own
`options.style` / `options.thresholds` where the card had none. **Those cards
keep drawing the same thing, and no longer follow later edits to the metric.**
Deleting the metric no longer removes them.

**Migration.**

- A custom card type's `build` already received `ctx.metric`; it now receives
  the card's source as a `Metric` either way (an unsaved one for a card's own
  source, `components.is_inline`). Nothing to change for evaluation.
- Any rows link a `build` draws must come from `components.rows_url(ctx, …)`
  (or `ctx.rows_url`), not `reverse("dashboards_metric_rows", key=…)`: a
  card's own source has no metric page, so its rows open by its place on the
  dashboard (`d/<slug>/cards/<cell_id>/rows/`) or, unsaved, through
  `dashboards/preview-rows/`.
- Agents and REST clients that create charts or grouped cards send `dataset`,
  `filter_tree`, `agg`, `measure` and `period_field` instead of `metric`
  (`card_preview` says so). Reading a dashboard's values, a card with its own
  source answers `dataset` where it answered `metric`.
- **Add to goals** needs a single stat over a metric; a stat with its own
  filter is saved as a metric first.

## v0.30.0 — only administrators change an address

**Who is affected:** staff (or their API tokens and agents) who change a dashboard's, report's,
playlist's or goal list's `slug`.

**What changed:** only a superuser or a member of the `admin` group may change an existing
address. Anyone else's change is refused on every surface (the settings page, REST and MCP) with a
validation error. Plain staff used to be able to.

**Migration:** add those people to an `admin` group, or have a superuser make the change. A
changed address doesn't redirect, so links and embeds by the old slug stop working either way.

## v0.28.0 — `can_update` / `can_delete` now gate writes, not just buttons

**Who is affected:** any CRUDView that overrides `can_update(obj, request)` or
`can_delete(obj, request)` *and* relies on the default `check_object_permission`.
If you never override those hooks, nothing changes.

**What changed.** Those hooks used to decide only which buttons render on the
detail and list pages; REST, MCP and the bulk views consulted them, but the
HTML edit and delete views did not, so a CRUDView that implemented `can_update`
and stopped there still accepted a non-owner's POST to `…/edit/`. The default
`check_object_permission` now calls `enforce_write_hooks(obj, request)`, which
raises `PermissionDenied` (403) on the edit and delete routes for any method,
and on every non-GET request, unless the matching hook returns True.

**Migration.**

- If a hook returned False **only to hide a button** while the write was meant
  to stay allowed, that write is now refused. Either let the hook return True
  and hide the button in the template, or move the cosmetic rule out of the
  hook — the hook's name always promised the stricter meaning.
- If you override `check_object_permission` for a read-side rule (ownership,
  tenancy) and want the new write gate too, call
  `cls.enforce_write_hooks(obj, request)` at the end of your override. An override
  that does not call it keeps the old behaviour.
- The calendar's `EventCRUDView` is the upstream example: `can_update` says
  "author or staff" and the framework default now enforces it on every surface.

---

## v0.25.1 — `enable_rss` removed; feeds are a publishing surface

**Who is affected:** any CRUDView that set `enable_rss = True`, any `rss_*`
attribute, or overrode `rss_item_extra()`. Nothing in upstream did; the blog
and the status page were already curated feeds. If you never touched these,
nothing to do.

**What changed.** The one-flag model feed (`apps/feeds/model_feed.py`) built
its items from `model.objects.all()` and never applied `get_list_queryset` or
`search_visibility`, so a single flag could syndicate drafts and other
tenants' rows to an anonymous URL. Rather than keep a seam that is unsafe on
exactly the models people want to syndicate, it is gone. Setting `enable_rss`,
any `rss_*` attribute or `rss_item_extra` on a CRUDView now raises
`ImproperlyConfigured` at import, so a stale copy fails loudly at startup
instead of quietly serving an unscoped feed.

The engine is unchanged: `Feed`, `FeedItem`, `register_feed`, `render_feed`,
the `/feed/<slug>.rss|atom` routes, access tiers, token auth, the collector.

**Migration** (10–20 lines per feed):

```python
# before
class ReleaseView(CRUDView):
    model = Release
    enable_rss = True
    rss_slug = "releases"
    rss_access = SearchAccess.ANONYMOUS
    search_display = "title"
    search_subtitle = "summary"
    def rss_item_extra(self, obj):
        return {"enclosures": [...]}

# after — apps/<app>/feeds.py
from apps.feeds import Feed, FeedItem, register_feed

class ReleasesFeed(Feed):
    slug = "releases"                        # same slug → same URL, subscribers notice nothing
    title = "Releases"
    access = SearchAccess.ANONYMOUS

    def items(self, request):
        qs = Release.objects.filter(published=True).order_by("-published_at", "-id")[:50]
        for obj in qs:                        # ← scope it; this is the step the flag never did
            yield FeedItem(
                title=obj.title, link=obj.get_absolute_url(),
                unique_id=f"app.Release:{obj.pk}",   # keep the old GUID scheme
                description=obj.summary, pubdate=obj.published_at,
                extra_kwargs={"enclosures": [...]},
            )

# apps/<app>/apps.py  ready():
register_feed(ReleasesFeed())
```

Attribute map: `rss_slug`→`slug`; `rss_feed_title`/`rss_feed_description`→
`title`/`description`; `rss_access`→`access`; `rss_limit`/`rss_ordering`→ the
slice and `order_by` in `items()`; `rss_title_field`/`rss_description_field`/
`rss_date_field`/`rss_author_field`→ the `FeedItem` kwargs;
`rss_item_extra()`→`extra_kwargs=`. The full recipe, including per-runtime-object
feeds rendered from your own view, is in `docs/skills/rss.md`.

**Positioning.** Feeds moved from the "integration hub" story to "publishing"
across the README, the shipped site and the skills: feeds are for readers,
podcast apps and the tools that subscribe on their own terms; integrations you
own use webhooks, the REST API and MCP. The collector (`register_feed_source`)
stays, filed under integrations as the way to pull in sources that only speak
RSS.

---

## v0.23.0 — task reliability: lost-task reaper + retries

Run `make migrate`. It applies **five** migrations.

This note deliberately does **not** name the release you are coming from. A version is only a
proxy for "which migrations you already have", and the proxy goes stale every time `main`
releases — it has already gone stale twice in this document while the feature was in review.
Migration ids don't drift. So the state these five assume is:

- `apps/tasks` has **no** migrations applied — it had none at all before this feature; and
- `scheduler` is at **`0003_scheduledjob_auto_retired`**.

That is every release before this one. Confirm with
`manage.py showmigrations tasks scheduler`; if it matches, the list below is what you get.

| Migration | What it does |
|---|---|
| `tasks.0001_initial` | The first models in `apps/tasks`: `WorkerHeartbeat`, `TaskAttempt` |
| `tasks.0002_worker_incarnation` | Keys worker liveness to a process, not to `--worker-id`. **Not additive — see below** |
| `tasks.0003_late_completion_marker` | Records a chain that executed more than once. Additive |
| `tasks.0004_widen_worker_id` | Widens `worker_id` to 128 so a worker identity cannot be silently truncated. Additive |
| `scheduler.0004_max_retries_live` | `ScheduledJob.max_retries` help text + validator. No DDL |

> **`tasks.0002_worker_incarnation` deletes rows.** It is the only destructive operation in
> this release. Its `RunPython` empties `tasks_workerheartbeat`, because pre-upgrade rows are
> keyed on the operator's `--worker-id` label and would match a pre-upgrade task's recorded
> claimant *exactly* — so a row that happened to carry `stopped_at` would cause that task to be
> failed as `WorkerLost` the instant the migration landed, even if it were still running.
> Emptying the table sends every pre-upgrade claim down the conservative
> `SMALLSTACK_TASKS_ORPHAN_SECONDS` path instead. Nothing of value is lost: the table is
> ephemeral liveness state that the reaper already prunes on a timer, any worker running during
> a migration is being restarted anyway, and the next heartbeat writes a fresh row. **Stop your
> workers before migrating** if you want the transition to be boring.

You don't need to change any code. Check the table if one of these applies to you.

| If you… | What changes | What to do |
|---|---|---|
| Run `manage.py db_worker` anywhere | It's now SmallStack's `db_worker`, which replaces django-tasks-db's. It takes the same arguments and adds a worker heartbeat plus a reaper for tasks whose worker died | Nothing. To opt out, set `SMALLSTACK_TASKS_HEARTBEAT_ENABLED=False`. |
| Have your **own** `db_worker` command in an app | Django uses the first app in `INSTALLED_APPS` that defines it | If your app comes before `apps.tasks`, yours wins and you get no heartbeat. Subclass `apps.tasks.management.commands.db_worker.Command` instead. |
| Replaced or edited `apps/tasks/tasks.py` | Upstream's email tasks now carry `@retry_policy(max_attempts=3, retry_on=(OSError,))` | When you merge, keep the decorators if you want SMTP errors retried. Keep `send_email_task` itself, because the scheduler and approvals import it. |
| See tasks go `FAILED` with `apps.tasks.exceptions.WorkerLost` | Their worker died mid-run. Before this change they would have stayed `RUNNING` forever | Expected. Add `@retry_policy` to tasks that are safe to repeat if you want them re-run. |
| Poll a task's first result id to learn its outcome | With retries, a later attempt is a **new** result | Use `apps.tasks.reliability.chain_outcome(result_id)` to follow the chain. |
| Pass `--worker-id` to `db_worker` | It is now an operator **label**, not the worker's identity. Each process appends its own token, so `DBTaskResult.worker_ids` holds `<label>#<token>` and `WorkerHeartbeat` has one row per process | Nothing. A stable `--worker-id` is now safe and is the recommended way to label a worker — previously it made a restarting worker hide the task its predecessor abandoned. |
| Parse `DBTaskResult.worker_ids` yourself | Entries are now `<label>#<token>` rather than the bare `--worker-id` | Match on the `WorkerHeartbeat.label` column, or split on the last `#`. |
| Run `manage.py check` in CI | Four new warnings can fire: `tasks.W001` (another app's `db_worker` shadows ours), `W002`/`W003` (`LOST_AFTER_SECONDS` under three heartbeats), `W004` (`USE_TZ = False` stops the reaper) | None fire on shipped defaults. Each names the misconfiguration and what it costs. |
| Care whether a task ever runs twice | A worker paused past `SMALLSTACK_TASKS_LOST_AFTER_SECONDS` mid-task is reaped and replaced, then may finish anyway. The late result wins, and the double execution is **recorded** (`TaskAttempt.parent_completed_at`, the run message, a WARNING) rather than prevented | Make such tasks idempotent. This is not new behaviour in the engine — it is newly *visible*. |
| Alert on ERROR-level log lines | With django-tasks-db 0.13, Django logs every `FAILED` attempt to `django.tasks` at ERROR, including attempts that `@retry_policy` will retry | Alert on a chain's final outcome (the scheduler's failure email, or `chain_outcome(...)`), not on per-attempt ERRORs. |
| Set `ScheduledJob.max_retries` on a task with no `@retry_policy` | It retries what the task **raises**, but will not re-run an attempt whose worker died | Add `@retry_policy(retry_lost=True)` to the task if repeating it after a worker death is genuinely safe. |

---

## v0.22.0 — the `mcp` SDK is no longer a dependency (check your own imports)

SmallStack **implements the Model Context Protocol itself** — the JSON-RPC
envelope, `initialize` / `tools/list` / `tools/call` dispatch, and OAuth are
plain Django in `apps/mcp/views.py`, served by gunicorn like every other route.
The `mcp` PyPI package was a declared dependency for exactly one thing: a
singleton `mcp.server.lowlevel.Server` in `apps/mcp/server.py` that nothing
ever read. It has been removed.

**Nothing about the MCP surface changes.** Your tools, `@tool`, `TOOL_REGISTRY`,
`current_context()`, `/mcp`, the OAuth flow, `mcp_doctor` and Claude Desktop /
Connectors all behave exactly as before. `MCP_SERVER_NAME` is still honoured
(it's reported in the `initialize` response).

| If you… | What happens | What to do |
|---|---|---|
| Only use SmallStack's `@tool` / CRUDView `enable_mcp` | Nothing | Nothing. You get a smaller install: **20 packages** drop out, including `pydantic`, `starlette`, `uvicorn`, `sse-starlette`, `httpx2`, `jsonschema`, `pyjwt[crypto]`, `opentelemetry-api`, `anyio` and `cryptography` — several of which are ASGI machinery SmallStack never runs. |
| `import mcp` anywhere in **your** code | It kept working only because SmallStack installed the SDK for you. After this upgrade a **clean install** no longer has it | Declare it yourself: add `mcp>=2.3` to your own `pyproject.toml` dependencies and re-lock. |
| Imported `mcp_server` from `apps.mcp.server` | That name is gone | Nothing to migrate — the object was never wired to anything. Delete the import. |
| Script against `mcp_doctor --json` | The `"mcp package"` row is gone | Drop it from any parsing. The checks that describe the live surface — `Settings`, `Server registry`, `URL conf`, `Tokens`, and the end-to-end self-test — are unchanged. The removed row only verified that its own dependency was importable. |

The catch worth knowing: a stray `import mcp` in your code will keep working in
any existing virtualenv that still has the package lying around, and fail only
when someone does a clean install. If you're unsure, check with
`grep -rn "^import mcp\|^from mcp" your_app/` before deploying.

## v0.21.0 — 2026-09-13 audit fixes (behaviour tightened, no code changes required)

These are security/correctness fixes. Most projects need to do nothing; check the list only if
you see one of the symptoms.

| Symptom after pulling | Cause | What to do |
|---|---|---|
| A REST `GET/PATCH/DELETE /api/<base>/<pk>/` (or bulk endpoint) now 404s | Those endpoints now apply your CRUDView's `get_list_queryset`, like the list endpoint and MCP already did | Nothing, if the row really shouldn't be visible to that user. If `get_list_queryset` holds list-only filtering (e.g. "hide inactive by default"), move that into the list view. |
| An MCP client gets `staff_required` | Staff-level tools now require the token's **user** to be staff, as REST does | Mark the user staff, or mint the token for a staff user. |
| A file under `/media/runbook/...` 404s | Runbook files are served only through their access-checked views | Use the runbook's own links. For your own gated uploads, add their folder to `SMALLSTACK_PRIVATE_MEDIA_PREFIXES`. |
| A webhook endpoint that answers with a redirect now fails | Redirects are no longer followed (SSRF protection) | Point the endpoint at the final URL. |
| A dataset `?format=csv` export returns 400 | Exports are capped at `SMALLSTACK_DATASET_CSV_MAX_ROWS` (50,000) | Filter or page with `limit`/`offset`, or raise the setting. |
| Starting a log capture at WARNING/ERROR is refused | Such a window captures nothing beyond the baseline | Pick a lower level (DEBUG/INFO). |
| Gunicorn access-log lines no longer show query strings | Tokens can ride in query strings | Nothing; revert `access_log_format` in `gunicorn.conf` if you need them. |

If you deploy with your own crontab instead of `scripts/smallstack-cron`, add the three new
entries from it: the webhook tick (`POST /webhooks/tick/`), `run_retention`, and
`prune_webhook_receipts`. Run `make migrate` (one new runbook migration).

---

## v0.21.0 — approvals/notifications review (2026-09-25 → 09-26)

Mostly tightening, but **five changes are visible to an operator on the upgrade itself**.
Read those five before you deploy; the rest of the table is symptom-driven.

Run `make migrate`. Coming from **v0.20.1** — the only previously released version — you apply
**thirteen** migrations. Four of them touch data you already have:
`smallstack_notifications.0002_notification_subject_key_and_more` (schema),
`smallstack_notifications.0003_backfill_approvals_subject_key` (**data** — see hazard 4),
`scheduler.0003_scheduledjob_auto_retired` (schema), and
`webhooks.0004_alter_webhookreceiver_signature_header` (schema — see hazard 5).

The other nine create new tables and need no attention: `smallstack_approvals.0001_initial`,
`smallstack_notifications.0001_initial`, `smallstack_runbook.0011_document_image_server_named`, and
two each for the three scenario demos that shipped in v0.21.0–v0.21.1 only (see *Scenario demo
apps* below).

### Scenario demo apps (shipped in v0.21.0–v0.21.1; removed in v0.21.2)

v0.21.0 and v0.21.1 bundled the approvals **test vehicle**: `apps/demo_purchasing`,
`apps/demo_agentops` and `apps/demo_access`, plus `manage.py seed_approval_scenarios` and
`manage.py approval_scenario`. **v0.21.2 removes all three apps and their conditional
registration** — the base template ships framework only; the scenario harness lives in the QA
workspace where it came from.

If you cloned at v0.21.0/v0.21.1 and migrated, the demo tables and their `django_migrations`
rows are inert leftovers once you upgrade — drop them or ignore them. If you deleted the
directories yourself on those versions, v0.21.2 changes nothing for you. Skipping straight from
v0.20.x to v0.21.2 means the demos never touch your install at all.

### The five upgrade hazards

**1. A scheduled job may be disabled — on `migrate` *or* on any scheduler tick.**
`sync_code_jobs()` now reconciles in both directions: a `source=CODE` job whose
`@scheduled` spec is no longer registered is **disabled** (not deleted — run history stays
readable).

> **Where to look.** `sync_code_jobs()` does not run only during `migrate`. It also runs on
> the first scheduler tick of every process (`apps/scheduler/services.py`) and from the
> scheduler admin view — and the tick is the case that matters more, because a *worker* with
> a partially-failed import is exactly where the safety valves below earn their keep. If a
> job goes quiet, grep the **worker/tick** logs as well as the deploy log.

You will see a log line like:

```
scheduler: disabled 'Approvals: expire overdue requests' — no @scheduled spec declares it
  any more (will re-enable automatically if the spec returns)
```

*Why it fires:* the spec genuinely vanished — the feature was removed, or a registration
guard like `SMALLSTACK_APPROVALS_SWEEP_ENABLED=False` turned it off. Before this, such a flag
worked on a fresh database and did nothing on an existing install.

*What to do:* usually nothing. It is now **reversible**: the row is marked `auto_retired`, so
putting the spec back re-enables *and* reschedules it on the next sync. A job **you** disabled
by hand is never re-enabled (it carries no marker) — and now logs
`… is declared in code but disabled by an operator — leaving it off`, so "why isn't my job
running" is a one-line diagnosis. If a *partial* autodiscovery failure (an app's `tasks.py`
raising on import, an app temporarily out of `INSTALLED_APPS`, `migrate` run against a shared
database with a different settings module) would retire more than half your known code jobs,
the sync **refuses** and logs `scheduler: refusing to retire N code job(s) …` instead.
`source=UI` jobs are never touched.

**2. Inbound webhook verifiers: a contract narrowing has been undone.** The argument a
`@webhook_verifier` receives is now `apps.webhooks.hooks.CaseInsensitiveDict` — a real,
**mutable** `dict` subclass whose lookups ignore header-name casing.

All the ordinary `dict` mutations work and stay case-insensitive: `headers["x-foo"] = …`,
`headers.update({"x-foo": …})`, `setdefault`, `pop`, `del`. A differently-cased key replaces
the existing entry rather than shadowing it, and the original wire spelling is preserved.

*If — and only if — you pulled the intermediate working tree between these two fixes:* that
state passed Django's immutable `CaseInsensitiveMapping`, so a verifier doing the ordinary
`headers.pop("X-Smallstack-Signature", "")` raised inside the verifier, was swallowed, and
returned a bare `401 invalid signature` **on a correct credential**. It was never released, so
anyone upgrading from a tagged version never saw it; if you worked around it by rewriting your
verifier not to mutate, that workaround is now unnecessary but harmless.

*In all cases:* a verifier that raises still fails **closed**, but is now logged with a
traceback (`webhooks: verifier 'x' raised for receiver 'y' — treating the delivery as
UNVERIFIED`). If you were relying on that silence, expect ERROR lines — they are telling you
a verifier is broken.

**3. API-token prefixes no longer start with `-`.** `_generate_raw_key()` re-rolls on a
leading dash (no entropy cost), because ≈1.6 % of prefixes — 1 in 64, the base64url alphabet —
were being read by argparse as an option flag: `sc token revoke -AbC1234` →
`error: the following arguments are required: prefix`.

*What to do:* nothing for new tokens. **Existing tokens are not rewritten** — a `prefix` is
derived from a raw key nobody stores, so it cannot be re-rolled after the fact. If you hold a
pre-upgrade token whose prefix starts with `-`, revoke it with an explicit end-of-options
marker:

```
manage.py sc token revoke -- -AbC1234
```

Check your exposure with
`APIToken.objects.filter(prefix__startswith="-").count()`.

**4. The notification backfill changes your unread badge count.**
`smallstack_notifications.0003` is a **data** migration. It backfills `subject_key` on
`approvals.*` notifications created before `0002` (deriving the request pk from the row's
`url`), then **marks read** every unread "Approval needed" bell whose request has already
reached a terminal state.

> Read that scope precisely: pass 2 filters on the *requests* pass 1 touched, not on the
> individual rows it rewrote. So an unread bell created **after** `0002` — a second approver on
> one of those same decided requests — is marked read as well. That is the intended outcome (a
> decided request's bell is stale whenever it was written), but it is wider than "only rows the
> backfill rewrote".

*Why:* `resolve()` addresses rows *by* `subject_key`, so before this the stale-bell retirement
could only ever reach requests filed **after** the upgrade. On the reference install that left
105 of 105 unread `approvals.requested` rows permanently un-retirable, several of them
pointing at requests decided weeks earlier.

*What you will observe:* unread counts **drop** — that is the fix, not data loss. Nothing is
deleted; only `subject_key` and `read_at` are written, and only on
`kind__startswith="approvals."` rows with a parseable URL. Bells for **still-pending**
requests are left unread. The migration is idempotent, so it is safe to re-run as a one-off.
If you need the old unread state for an audit, snapshot the table before migrating.

**5. New webhook receivers expect a different signature header.**
`WebhookReceiver.signature_header` now defaults to **`X-SmallStack-Signature`** (was
`X-Signature`), via `webhooks.0004`. The old default never matched what SmallStack's own
outbound side signs, so a SmallStack↔SmallStack pairing rejected every delivery.

*What the migration does:* changes the **field default only**. Every existing receiver keeps
its stored value, so nothing you have configured changes behaviour.

*What to watch:* receivers created **after** the upgrade get the new spelling. If a
third-party sender signs `X-Signature`, set that receiver's `signature_header` explicitly
(staff UI, or `sc set webhookreceiver <pk> signature_header=X-Signature`). Check with
`WebhookReceiver.objects.values_list("name", "signature_header")`.

### Everything else — symptom-driven

| Symptom after pulling | Cause | What to do |
|---|---|---|
| A bookmarked or logged URL for a **UUID-pk** record now 404s | HTML detail/edit/delete routes are registered with typed converters (`<int:pk>` / `<uuid:pk>` / `<str:pk>`) so a non-matching segment 404s instead of reaching the ORM and raising `ValueError: Field 'id' expected a number` — a 500 for every CRUDView. Django's `uuid` converter accepts only the **canonical** dashed lowercase form, so `…/735E9A94-…/` (uppercase) and `…/735e9a94071b…/` (dashless) now 404 where they used to resolve | Rewrite such links to the canonical form (`str(uuid.UUID(value))`). Integer pks are unaffected — `/4/` and `/04/` both still resolve. Bulk-action `ids` are *not* affected: they are coerced via the model's own pk field, so all three UUID spellings are accepted there. |
| **An API token stops working the moment you deactivate its user** | `APIToken` now refuses a token whose user is `is_active=False`, on every surface (REST, MCP, feeds, OAuth), and approvals eligibility requires an active user too. Previously an offboarded account's un-revoked token kept reading the queue and **approving/rejecting**, recorded under their name | Nothing — this is the fix, and deactivating a user is now sufficient to cut their access. If you deactivate accounts as a *temporary* state and relied on their automation continuing, mint the token under a service account instead. |
| `NoReverseMatch` for `notifications:inbox` / an approvals URL after setting a master switch off | `SMALLSTACK_APPROVALS_ENABLED=False` / `SMALLSTACK_NOTIFICATIONS_ENABLED=False` now **un-mount** the app's URLs (the `SMALLSTACK_MCP_ENABLED` precedent), instead of leaving every endpoint live — including the decide POST — while killing only the fan-out | Guard your own `reverse()`/`{% url %}` references with the same switch. SmallStack's own templates and nav already are. |
| An unfamiliar inactive user named `system` appears in the user list | System-initiated audit entries (expiry sweep, scheduler retirement) need an author. The first such write creates one `is_active=False`, non-staff account named by `SMALLSTACK_AUDIT_SYSTEM_USERNAME` (default `system`) | Nothing. It cannot log in. Rename it with that setting before first use if `system` collides with a real account in your directory. |
| Filing an approval returns **429** `too_many_pending` | New `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER` (default 50) caps one requester's open requests **per kind**, so an agent in a retry loop can't fill the queue | Raise the setting, or have the client decide/cancel its open requests. `0` disables the cap. |
| No approval emails arrive in production, and the Approvals monitor is down | `SMALLSTACK_APPROVALS_EMAILS_INLINE` defaults to `DEBUG`, so **production requires a `db_worker` draining the `email` queue**. The previous "inline fallback" never actually fired: with the shipped `DatabaseBackend`, `enqueue()` does not raise, so mail queued silently and forever | Run a worker on the `email` queue, or set `SMALLSTACK_APPROVALS_EMAILS_INLINE=true` to send in-request (simple installs), or `SMALLSTACK_APPROVALS_EMAILS_ENABLED=False` if you don't use email. `SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES` (15) tunes when the monitor complains. |
| A queue page load expires fewer overdue rows than you expected | Lazy expiry is now capped at `SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT` (25) per request, oldest first, and runs once per request rather than three times per page. One GET with 200 overdue rows previously ran 4,017 queries and fired 200 notifications plus 200 webhook deliveries synchronously | Nothing — the 5-minute sweep drains the rest. Raise the cap if you have no worker and want the page to do more of the work. |
| An MCP client's error handling stopped matching | Generated tool refusals now return `{"error": {"code", "message"}}` — `invalid_argument`, `not_found`, `not_permitted`, `validation_error`, `unsupported` — instead of a bare sentence, and a rejected create now sets the protocol `isError` flag (it previously returned `{"errors": …}` and read as success) | Branch on `error.code` instead of matching prose. Field-level detail moved to `error.fields`. |
| A fork that pins its own `MIDDLEWARE` loses notification read-on-arrival | New `apps.notifications.middleware.NotificationReadOnArrivalMiddleware` marks a row read only on a 2xx arrival, so a dead-end click can't silently eat the badge | Add the entry to your `MIDDLEWARE`. |
| A CRUDView's related-tab or field-preview route now returns 403/404 where it returned 200 | New `CRUDView.check_object_permission(obj, request)` is applied by the base to **all five** single-object surfaces (detail, edit, delete, field preview, related tab) plus REST detail/update/delete, the HTML and REST bulk actions, and the generated MCP tools | Nothing, if the row really shouldn't be reachable by that user — this closed a live cross-user leak. If you enforced ownership by overriding one generated base's `get_object`, move that check into `check_object_permission` so it covers all five. |
| `?status=pending` on the approvals queue returns fewer rows than before | The filter now selects the **effective** status (`actionable()` — pending minus overdue) so it agrees with the page's own "Pending" stat card, which was disagreeing by hundreds of rows | Nothing. Overdue-but-unswept rows are now found under `?status=expired`. |
| Your own CRUDView wants a filter whose stored column isn't the value the page reasons about | New `CRUDView.apply_filter(qs, field_name, value, request)` hook, honoured by the HTML list, the REST list and the generated MCP `list_*` tool | Optional. Return a queryset to take over one `filter_fields` entry, or `NotImplemented` for the default. |
| An MCP `get_*`/`update_*`/`delete_*` call that sent `pk` still works, and `id` now works too | Generated single-object tools accept `id` (the key `serialize()` actually emits) with `pk` as a permanent alias | Nothing. `delete_*` now returns both `id` and `pk`. |
| An MCP tool declared `requires_access="auth"` now admits callers it used to refuse | The tier ladder was inverted (`readonly < staff < auth`), so `"auth"` — documented as "any authenticated caller" — could be satisfied by no login token at all, and staff were *less* capable than non-staff on it. It is now `readonly < auth < staff` | Nothing, if `"auth"` meant what the docs say. If you were using `"auth"` as a *higher* tier than `"staff"`, change it to `"staff"`. Nothing in the shipped tree declares `"auth"`, so most projects are unaffected. |
| An endpoint that calls a disabled feature returns 503 instead of 500 | New `apps.smallstack.exceptions.FeatureDisabled`, translated by `api_view` for every endpoint. `ApprovalsDisabled` is one | Nothing — this is the fix. Subclass `FeatureDisabled` in your own feature's exception hierarchy to get the same treatment. |
| An `@api_view` endpoint that raised `PermissionDenied` now returns a JSON 403 instead of Django's HTML 403 | `api_view` translates it into the standard envelope, alongside the existing `Http404` branch | Nothing. |
| The Approvals card on `/smallstack/status/overview/` is **down** and it wasn't before | Core-service rows now need the monitor's live `inventory()` **and** its recorded state to be good. Previously a monitor recording FAIL still rendered a green "on", because the base `inventory()` returns `{"ok": True}` | Read the note now shown on the card — it names the action. Common causes: no worker on the `email` queue, the expiry sweep not running, or `SITE_DOMAIN` still at its `localhost:8000` default (see below). `scheduler-tick` had the identical bug and is fixed by the same change. |
| The Approvals monitor reports `approval emails link to localhost:8000` | Approvals mail is sent from a signal receiver or a task, so it has no request to derive a host from and builds its absolute console link from `SITE_DOMAIN` | **Set `SITE_DOMAIN`** to this install's real host — otherwise the console link in every approval email is dead, which breaks the "non-staff assignees decide via the emailed link" story. Or set `SMALLSTACK_APPROVALS_EMAILS_ENABLED=False` if you don't use the email channel. Skipped under `DEBUG`. |
| An approval email subject or bell title now reads `(assignee deactivated) …` | Every named assignee on that request is deactivated, so it fell back to broadcasting to all active staff. Previously silent | Re-assign the request. The fallback is deliberate (an approval must not go unseen) but it should not be invisible. |
| Decision emails reach more people than you expected, including the decider | Documented behaviour, previously documented **backwards** in both directions: the decision email goes to the requester **and the approvers, including the one who decided**. The in-app bell differs by exactly one person — it skips the actor | Nothing. `SMALLSTACK_APPROVALS_EMAILS_ENABLED=False` and per-kind `notify` are unchanged escape hatches. `apps/approvals/emails.py`'s module docstring is the authority. |
| A non-staff user sees an "Approvals" entry in the sidebar, or finds approvals in global search | The console has been LoginRequired + eligibility-scoped since the previous change, but had no nav entry outside the staff-only ADMIN section, and `search_access` still defaulted to STAFF | Nothing — rows are scoped by the same eligibility scoper every other read surface uses. Staff still see exactly one entry, in ADMIN. |
| Your own nav item needs a rule `auth_required`/`staff_required` can't express | New `nav.register(visible=<callable(request) -> bool>)`. A predicate that raises hides the item and logs; it never 500s the page | Optional. |
| A CRUD list's empty state says "There are no … yet. Create the first one." where it used to say "Nothing matches these filters" | The branch now keys off real search/filter params instead of `request.GET.urlencode`, which was truthy for pagination, ordering, the display toggle and the notification-bell marker | Nothing — this is the fix. If you overrode `object_list.html`, note the new `has_active_filters` context flag and the shared `crud/includes/empty_state.html`. |
| A custom template of yours shows raw `{# … #}` text | Django's `{# #}` is **single-line only**; a multi-line one is emitted verbatim as body text | Use `{% comment %}…{% endcomment %}`. `apps/smallstack/test_template_hygiene.py` now fails the build on any multi-line `{# … #}` anywhere in the tree, so your own templates are covered too. |

---

## v0.15.0 — CRUDViews require login by default (BREAKING)

**Who is affected:** any CRUDView that relied on the old empty-`mixins` default to be
**anonymous/public**. Views that set `mixins` explicitly — e.g. `[StaffRequiredMixin]`, which
every bundled framework view does — are unaffected.

**What changed:** `CRUDView.mixins` now defaults to `None` (secure), which the framework resolves
to `[LoginRequiredMixin]`. Previously the default was `[]` (no auth), so a CRUDView that *omitted*
`mixins` silently shipped anonymous HTML **and** REST endpoints. Now such a view requires login.

**Symptom on upgrade:** a page/endpoint that used to be public now redirects to the login page
(HTML) or returns `401` (REST) for anonymous visitors.

**Find affected views:**
```bash
# CRUDViews that set NO mixins (they inherit the new secure default):
grep -rLn "mixins =" $(grep -rln "CRUDView)" apps/)
```

**Migration — make public access explicit:**
```python
from apps.smallstack.crud import CRUDView, Action

# Opt into anonymous access with the readable flag (recommended):
class ProductCatalogView(CRUDView):
    model = Product
    public = True
    actions = [Action.LIST, Action.DETAIL]   # read-only — public writes are almost never intended

# …or the low-level equivalent:
class ProductCatalogView(CRUDView):
    mixins = []
```
Nothing to do if your CRUDViews already set `mixins` (login/staff) explicitly — an explicit list
always wins over the default and over `public`.

**New guard:** a CRUDView that is public (no auth mixins) **and** exposes write actions
(create/update/delete) with `enable_api=True` now emits a warning — restrict `actions` to
`LIST`/`DETAIL` for public views, or gate it. Note the REST API still requires authentication for
every request regardless (token or session), so a `public=True` view is public over HTML but its
API stays auth-gated.

## v0.14.0 — Django 6.1 + email `MAILERS` (breaking **only** if you set `EMAIL_BACKEND`)

**Who is affected:** downstream projects that define **`EMAIL_BACKEND`** (or any `EMAIL_HOST` /
`EMAIL_PORT` / `EMAIL_USE_TLS` / … *setting*) in their own `config/settings/*.py`. If you only set
these via **environment variables**, you're fine — nothing to do.

**Why:** SmallStack upgraded to **Django 6.1**, which consolidates email config into a single
[`MAILERS`](https://docs.djangoproject.com/en/6.1/topics/email/) dict (like `DATABASES`/`CACHES`) and
deprecates the flat `EMAIL_*` settings (removed in Django 7.0). The base settings now ship `MAILERS`.
Django 6.1 **raises `ImproperlyConfigured` if both `MAILERS` and a deprecated `EMAIL_*` setting are
defined** — so a downstream that still sets `EMAIL_BACKEND` in a settings module will fail to boot with:

> `Deprecated email settings are not allowed when MAILERS is defined: EMAIL_BACKEND.`

**Migration — replace the `EMAIL_*` settings with a `MAILERS` override:**

```python
# before (in your settings module)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.example.com"
EMAIL_USE_TLS = True

# after
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {"host": "smtp.example.com", "use_tls": True},
    },
}
```

Or drop your override entirely and set the `EMAIL_*` **env vars** — SmallStack's
`config/settings/_email.py:build_mailers()` reads them into `MAILERS` for you (dev defaults to the
console backend, production to SMTP). `DEFAULT_FROM_EMAIL` / `SERVER_EMAIL` are unchanged (not
deprecated). `send_mail()`, `EmailMultiAlternatives`, and `mail_admins()` work exactly as before.

**Also removed upstream:** the deprecated `fail_silently=` argument on all framework mail calls (it's
removed in Django 7.0). If your own code passes `fail_silently=True`, wrap the send in `try/except`
instead; `fail_silently=False` is the default, so just drop it.

## v0.13.0 — Runbook app (additive, non-breaking)

**Who is affected:** everyone upgrading from v0.12.x. No manual steps are required — this entry is
informational.

**What's new:** the runbook dynamic-document system ships as a new `smallstack_runbook` app (documents
with immutable versioning, retention, subscriptions, and web / REST / MCP / CLI surfaces over one
service layer).

**Migrations:** `make migrate` applies ten new migrations automatically
(`smallstack_runbook.0001_initial` … `0010_runbook_is_public_runbook_owner`). This was verified with an
upgrade test — cloned v0.12.4, seeded data, merged v0.13.0, and migrated forward on the populated DB:
migrations applied cleanly, **no data loss**, `manage.py check` passed.

**New settings (all optional, safe defaults — no action needed):**

- `RUNBOOK_BASE_TEMPLATE`, `RUNBOOK_STAFF_REQUIRED` (default `True`), and the
  `RUNBOOK_GENERATED_*` retention caps — see `config/settings/smallstack.py`.
- `TRUST_PROXY_HEADERS` (default `False`) — only enable behind a trusted proxy that sets
  `X-Forwarded-For` (kamal-proxy does).

---

## v0.12.0 — `django-tables2` removed (BREAKING)

**Who is affected:** any downstream project that defined its own `tables.Table` subclass and
wired it to a CRUDView with `table_class = MyTable`, or imported from `apps.smallstack.tables`
(`ActionsColumn`, `BooleanColumn`, `DetailLinkColumn`).

**Symptom on merge/upgrade:** after `uv sync` drops `django_tables2`, the project fails to
import before any test runs:

```
ModuleNotFoundError: No module named 'django_tables2'
# and / or
ImportError: cannot import name 'ActionsColumn' from 'apps.smallstack.tables'
```

`apps/smallstack/tables.py` has been deleted; framework apps (usermanager, heartbeat,
explorer) moved to the `TableDisplay` / `{% crud_table %}` flow in the same release, so the
base stays green — the breakage only surfaces in *your* app's imports.

**Find affected sites:**

```bash
grep -rn "django_tables2\|apps.smallstack.tables\|table_class" apps/
```

**Migration:** replace the `Table` class with declarative attributes on the CRUDView.

```python
# BEFORE — apps/<app>/tables.py + views.py
class PortfolioTable(tables.Table):
    title = DetailLinkColumn(url_base="manage/portfolio", link_view="update")
    is_published = BooleanColumn()
    updated_at = tables.DateTimeColumn(format="M d, Y")
    actions = ActionsColumn(url_base="manage/portfolio")

class PortfolioCRUDView(CRUDView):
    table_class = PortfolioTable

# AFTER — views.py only (delete tables.py)
def _render_solution_type(value, obj):
    return format_html('<span class="badge">{}</span>', obj.get_solution_type_display())

class PortfolioCRUDView(CRUDView):
    list_fields = ["title", "solution_type", "is_published", "display_order", "updated_at"]
    link_field = "title"   # clickable -> detail (needs Action.DETAIL in actions)
    field_transforms = {"solution_type": _render_solution_type}
```

`TableDisplay` now handles automatically — no column class needed:

| Old column class | Now done by |
|---|---|
| choice display (`get_FOO_display()`) | automatic for choice fields |
| `BooleanColumn` | automatic ✓ / — for booleans |
| `DateTimeColumn(format=...)` | automatic localized datetime with tooltip |
| `ActionsColumn` | derived from the CRUDView's `actions` |
| `ActionsColumn` subclass (per-row filtering) | override `CRUDView.row_actions(cls, obj, request, default_actions)` |
| custom cell HTML | a `field_transforms` entry — a registered transform name, or a `(value, obj) -> str \| mark_safe` callable |

After migrating, remove `django-tables2` from your own `pyproject.toml` if you pinned it, and
delete the now-unused `apps/<app>/tables.py`.

### Also in v0.12.0 (additive): the status-monitoring subsystem

v0.12.0 also ships the pluggable status-monitoring system — `/smallstack/status/`, the
branded public `/status/` board, Site/External monitors, per-monitor SLA, and three
site-level **surface toggles** (`SMALLSTACK_PUBLIC_STATUS_ENABLED` /
`SMALLSTACK_API_ENABLED` / `SMALLSTACK_MCP_ENABLED`). It's **additive** — no breaking
change — but it touches shared config (`config/urls.py`, `config/settings/smallstack.py`)
and moves the CRUDView `views` autodiscover into `SmallStackConfig.ready()`. For the
merge integration points and the one gotcha (keep that autodiscover call or Search goes
empty), see **`docs/skills/merge-0.12.0.md`**.
