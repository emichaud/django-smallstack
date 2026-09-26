# Upgrading SmallStack

Breaking changes and the migration steps for each. Downstream projects (smallstack_web,
opshugger, and any clone) should read the section for any version they cross when pulling
upstream.

Most releases are non-breaking patch/minor bumps and won't appear here. If a release isn't
listed, no downstream migration is required.

---

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
