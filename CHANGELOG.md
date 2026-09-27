# Changelog

All notable changes to SmallStack are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Breaking-change migration recipes live in [`UPGRADING.md`](UPGRADING.md).

## [Unreleased]

## [0.21.5] - 2026-09-27

### Fixed
- **The 90-day timeline no longer shows a permanent false red square on the day
  currently crossing the retention boundary.** The pruner advances one minute at
  a time, so a day takes ~24 hours to fold into its summary — throughout, the
  summary holds the already-pruned prefix and raw beats hold the remainder.
  `_daily_uptime_map` *chose* the summary outright, scoring a flawless mid-fold
  day at `prefix/1440` (live downstream evidence: 563/1440 ⇒ 39.097% "down"),
  while `_uptime_over_window` handled the same day correctly — the two public
  surfaces contradicted each other, and exactly one day per monitor is always
  mid-fold. The map now **sums** the two halves (disjoint by construction), with
  the raw half SLA-scoped on *both* terms so excluded-maintenance beats can't
  re-enter the `max(observed, expected)` denominator through the raw side.
  Four regression tests, three of which fail against the previous code.
  (Downstream report; validated live.)

## [0.21.4] - 2026-09-27

### Fixed
- **Heartbeat tests no longer hard-code the brand name or one theme's markup.**
  A rebranded downstream (`BRAND_NAME=Planner`) or one overriding the
  `detail_grid.html` display template inherited three false test failures. The
  public-status assertions now read `settings.BRAND_NAME`, and the boolean-
  rendering test asserts the actual regression invariant (False renders
  differently from True) via a template-agnostic extractor instead of pinning
  upstream's ✓/— glyphs. (Downstream report; verified non-vacuous — simulating
  the original all-booleans-truthy bug still fails the rewritten test.)
- **Daily uptime summaries prorate their expected-checks denominator.** Three
  spans nobody agreed to monitor were read as downtime by the flat
  `86400 // interval` denominator: the epoch's first partial day (~6% "down"
  even with every check green), a monitor added mid-day (same shape — its epoch
  is its first beat), and SLA-excluded maintenance (a 4h excluded window capped
  an honest day at 83%, defeating `exclude_from_sla=True`). The summary writer
  now computes `expected_intervals_for_day` (epoch row → day-in-progress →
  excluded windows) **and** moves beats recorded inside excluded windows out of
  `ok_count`/`fail_count` into `maintenance_count` — mirroring the raw span's
  `_uptime_over_window` semantics; shrinking the denominator alone would have
  left `max(recorded, expected)` resurrecting the excluded time. The 90-day
  timeline's raw branch uses the same math, so a day's uptime no longer changes
  when it crosses the retention boundary. Missing beats inside the monitored
  span still count as downtime (deliberately: for a self-pinged monitor, "cron
  didn't run" and "host was down" are the same event). A fully excluded day
  writes `expected_count=0` and renders "No data". New
  `manage.py heartbeat --reprorate` backfills existing summaries — expected
  depends only on the date, the epoch row, and the maintenance windows, so
  unlike `--repair-summaries` it fixes history (run repair first).
- **One host setting now satisfies both email links and webhooks.** Emails built
  outside a request (approval notifications, welcome mail) read `SITE_DOMAIN`,
  while webhooks read `SITE_URL` — so a deployment that configured its host the
  way `webhook_doctor` instructs still sent dead `localhost:8000` email links,
  and the Approvals status monitor stayed DOWN telling it to set a *second*
  variable. `site_base_url()` (in `apps/accounts/emails.py`) now resolves
  `SITE_DOMAIN`+`USE_HTTPS` → a URL-shaped `SITE_URL`/`SMALLSTACK_SITE_URL`/
  `BASE_URL` → the localhost default, and every consumer (branded emails, the
  welcome task, the `ApprovalsFanoutMonitor` link check) shares it. The monitor
  message now names both knobs, and `.env.example` finally documents
  `SITE_DOMAIN`/`USE_HTTPS`/`SITE_URL` (it mentioned none of them).

## [0.21.3] - 2026-09-26

### Fixed
- **Public status pages no longer paint all history "down" at 0.07% on long-running
  sites.** The heartbeat pruner runs every minute (the ping view calls it), so one
  calendar day is pruned across ~1440 tiny batches — but `_write_daily_summaries`
  *overwrote* the day's `HeartbeatDaily` row with only the current batch, so every
  fully-summarized day converged to its final single beat: 1/1440 ⇒ `uptime_pct =
  0.069%` ⇒ "down" (while the raw-retention window stayed green — the "only ~7 days
  survive" symptom). Summaries now **accumulate** across batches (counts merge,
  response times weighted-average), the aggregate-then-delete pair runs in one
  transaction, and the timeline/calendar/SLA maths are unchanged. Deployments that
  ran the buggy pruner: `manage.py heartbeat --repair-summaries` deletes the
  corrupted rows (recorded beats < 5% of expected — the bug's fingerprint; genuine
  full days and recorded outages are kept), after which those days honestly render
  "No data". The true counts are unrecoverable.

### Added
- **User-facing help pages for the scheduler** (`/smallstack/help/smallstack/scheduler/`)
  — the control console, `@scheduled` cadences, tick triggers, and the run lifecycle
  finally have a human-readable page (the skill doc existed; Help had nothing).
- **Webhooks help covers the v0.19 event picker** — the annotated checkbox event
  list, the Advanced custom-pattern disclosure, and every-surface pattern validation.
- **Background Tasks help no longer steers cron work to Celery** — the comparison
  table predated the `@scheduled` scheduler; it now says scheduling is built in and
  links to the scheduler page.

### Documentation
- **The palette count is corrected in the three files the v0.21.1 sweep missed.**
  `README.md` (four claims), `CLAUDE.md` and `apps/smallstack/docs/tldr.md` still said
  **five** palettes; there are **six** (`django`, `dark-blue`, `purple`, `orange`,
  `high-contrast`, `gold`). `CLAUDE.md` also named the palettes by label rather than id,
  omitted `gold`, and left the default unstated — it is `purple`
  (`SMALLSTACK_COLOR_PALETTE`). These are the read-first files for a new contributor and
  for an agent onboarding to the repo, so they were contradicting
  `docs/skills/modern-dark-theme.md`, which v0.21.1 had already fixed.

## [0.21.2] - 2026-09-26

### Removed
- **The approvals scenario test-harness apps no longer ship in the base template.**
  `apps/demo_purchasing`, `apps/demo_agentops` and `apps/demo_access` — plus
  `manage.py approval_scenario` and `manage.py seed_approval_scenarios` — were the QA
  workspace's test vehicle for the v0.21.x approvals work. They drove the findings but
  were never meant to land in the starter template: a fresh clone got three extra apps,
  six extra migrations, and 29 routes under `/demo/` without opting in. The apps, their
  conditional `INSTALLED_APPS` registration, and the `/demo/` URL mounting are all
  removed; the framework itself never referenced them, so no framework behavior changes.
  If you cloned at v0.21.0/v0.21.1 and migrated, see "Scenario demo apps" in
  `UPGRADING.md` for what the leftovers are (inert) and how to drop them.

## [0.21.1] - 2026-09-26

Fixes for findings from the 2026-09-26 test rounds. Each carries a regression test that
fails against the old code.

### Fixed
- **Turning the approval email channel off no longer holds the status page down.**
  `SMALLSTACK_APPROVALS_EMAILS_ENABLED=False` still enqueued a `notify_*` task per request —
  the gate lived only at *send* time — so with no worker those rows sat READY forever and
  `ApprovalsFanoutMonitor` counted exactly them. A **core-category** service card sat
  permanently DOWN telling the operator to start a mail worker they had deliberately chosen
  not to run, and `UPGRADING.md` recommended that very setting as the remedy for the
  symptom. Nothing to send now means nothing to queue, and the monitor ignores a backlog
  while the channel is off, so rows left from before the switch don't hold it down either.
- **The approvals monitor no longer reports "email queue drained" while mail is queued.** It
  now distinguishes *stale* from *queued-but-young* and says which it found — the note
  described the opposite of the situation on the one channel that fails silently.
- **The approvals monitor reports every fault in one check.** The `SITE_DOMAIN` branch
  returned before the backlog was looked at, so an install with both faults learned about
  the second only after fixing the first.
- **The notifications inbox has an `<h1>`** — its page heading was an `<h2>`, leaving the
  page with no `h1` at all and breaking the document outline and heading-jump navigation.
- **Unread notifications are announced to screen readers.** Unread state was carried only by
  an `aria-hidden` dot and bold weight, so the state the screen exists to convey was
  sighted-only (WCAG 1.3.1 / 1.4.1). A visually-hidden "Unread." marker now precedes the row.
- **The sidebar no longer claims you are on the Dashboard when you are not.** The dashboard
  lives at `/smallstack/`, which prefixes every admin route, so any page without its own nav
  entry — the notifications inbox, reached from the topbar bell — lit it up. Nav items gain
  `active_exact`, set on the dashboard root.

### Changed
- `nav.register(...)` accepts `active_exact=True`: the item goes active only on an exact path
  match, never on a prefix. For a section root that is the difference between "you are here"
  and "you are somewhere below here".

### Documentation
- **`docs/skills/modern-dark-theme.md` was wrong about the palettes it is the read-first
  authority for**: it claimed **five**, named a `dark-purple` that does not exist (the id is
  `purple`), omitted `gold`, and said the default was `django` when it is `purple`. Corrected,
  with a pointer to `UserProfile.color_palette.choices` + `palettes.css` as the authoritative
  list. The same claims are fixed in seven other docs.
- **`UPGRADING.md` under-counted the migrations**: it said "Four", which is what the
  approvals/notifications *review* added. Coming from v0.20.1 — the only previously released
  version — you apply **thirteen**. Now stated with the breakdown.
- **The bundled scenario demo apps are documented.** `apps/demo_purchasing`, `demo_agentops`
  and `demo_access` ship as of v0.21.0 and register themselves when present, so a fresh clone
  gets three extra apps, six extra migrations and 29 routes under `/demo/`. `UPGRADING.md`
  now says so and gives the one-line opt-out; `config/settings/base.py`'s comment no longer
  claims they are "deliberately not tracked".

## [0.21.0] - 2026-09-26

Fixes from the 2026-09-13 base-framework audit (v0.20.1). Each carries a
regression test that fails against the old code.

### Security
- **MCP now checks the *user's* staff flag, not just the token's label.** Any
  tool at `requires_access="staff"` (or `"auth"`) also requires
  `token.user.is_staff`, matching REST. Previously a staff-level token held by a
  non-staff user — flag cleared after minting, or minted for them by another
  staffer — kept full staff read/write over MCP (26 of 40 tools, incl.
  `create_webhook`). The token form also refuses to mint staff/auth-level
  tokens for non-staff users. (C1)
- **`/media/` no longer serves access-controlled files.** Runbook bodies were
  reachable anonymously at `/media/runbook/<key>.md`. The media route now 404s
  prefixes listed in the new `SMALLSTACK_PRIVATE_MEDIA_PREFIXES` (default
  `runbook/`, env-overridable, comma-separated); profile photos stay public.
  The gate compares the resolved file path the server would open — not URL
  strings — so `..` tricks (`/media/%2e%2e/media/runbook/x.md`) and symlinks
  can't slip past it. (C2)
- **API tokens no longer leak into logs.** An `HttpRequest` in a log record's
  `extra` (every `django.request` 4xx/5xx) is reduced to method + path, so a
  feed's `?token=` never reaches JSON log lines or `LogRecord.extra`. Gunicorn's
  access log format drops the query string too. (C3)
- **Webhook delivery can't be redirected into the private network.** 3xx
  responses are recorded as failures, never followed, and the connected
  socket's peer address is re-checked before any byte is sent — closing the
  DNS-rebinding window as well. (C4)
- **REST detail/update/delete and bulk endpoints honour `get_list_queryset`**,
  as REST list and all MCP verbs already did. A fork scoping rows per owner
  leaked other tenants' rows at `/api/<base>/<pk>/`. (C5)
- **Inbound webhook receiver hardened**: bodies over
  `SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES` (1 MB) get 413 before anything is
  stored; signature-rejected receipts keep a 1 KB excerpt + SHA-256 and stop
  being recorded past `SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE` (30); new
  `prune_webhook_receipts` command (in the shipped crontab). (C6)
- **Runbook images get server-generated names and a pinned content type.**
  Only png/jpg/gif/webp are accepted by the form; any other stored name
  (service/bundle paths, pre-fix uploads) is served as an
  `application/octet-stream` download, never rendered. (C7)
- **OAuth consent POST requires a CSRF token** (`AuthorizeView` is no longer
  `csrf_exempt`), and `SESSION_COOKIE_SAMESITE`/`CSRF_COOKIE_SAMESITE` are
  pinned to `"Lax"`. The consent page's CSP override regains `base-uri`,
  `object-src`, `font-src`, `connect-src`. (C8, H5)
- **Abandoned OAuth codes are scrubbed**: past their TTL the plaintext key is
  cleared and the never-delivered token deactivated. (C9b)
- **Passwordless login**: attempts are spent atomically before the code check
  (parallel guesses bypassed the 5-attempt limit) and codes per account are
  capped by `SMALLSTACK_LOGIN_CODES_PER_HOUR` (5). (H3)
- **`.dockerignore` excludes `backups/`, `data/`, `.secret_key`, `.kamal/` and
  nested `*.sqlite3`** — `COPY . .` was baking DB snapshots into images. (H1)
- `SMALLSTACK_PUBLIC_STATUS_ENABLED=False` now also closes the per-monitor
  detail page to anonymous visitors (C9a). New `SMALLSTACK_PUBLIC_PROFILES`
  flag (default on) lets a deployment require sign-in for `/profile/<username>/`,
  which otherwise answers "does this account exist" (C9d).

### Fixed
- **The telemetry `after_id` cursor skipped records.** It filtered by pk but
  ordered by ts, so batch-inserted records captured earlier than their pk
  suggests were never returned — with `has_more=False`. Cursor mode now pages
  in pk order. Affects `/api/logger/records/`, MCP `logs_search`, and
  `logs --follow`. (D1)
- **A scheduler fire that failed to enqueue was lost silently.** Any enqueue
  exception now records a FAILED run and `last_status="failed"`; an unknown
  `queue_name` is rejected by `ScheduledJob.clean()`. (D2)
- **The shipped crontab now drives the webhook retry tick** (`POST
  /webhooks/tick/` every minute) — failed deliveries were never retried or
  dead-lettered — **and nightly `run_retention`**, the only driver of runbook
  document TTL expiry. (D3, D4)
- `api_doctor` and the OpenAPI validity tests validate the spec actually
  served (custom endpoints included: 68 operations, not 42), via the new
  `build_served_spec()`. (D5)
- A log-capture window that would capture nothing extra (a typo, or a level at
  or above the baseline) is refused with a clear message on every channel
  instead of being audited and reported as active. (D6)
- Dynamic status monitors: a DB error is logged instead of silently dropping
  every endpoint/surface monitor from the tick; one bad row no longer drops
  the rest. (D7)
- Bulk deletes log at WARNING, so the v0.20.0 summary line actually reaches
  the log viewer at the default baseline. (D8)
- Smaller: heartbeat log uses `attach_display_helpers` (D9); the log viewer
  gains a CRITICAL filter and flags unknown levels (D10a); write give-ups count
  toward `dropped` (D10b); `reset_schedule` reports a failed re-sync (D10c);
  bulk-delete and help-search failures are logged (D10d); the api/mcp/webhook
  doctors report a missing schema instead of a traceback (D10f); CRUD lists
  fall back to pk order when the queryset is unordered — fixes
  `UnorderedObjectListWarning` on the user list (D10g).
- Dataset CSV export is capped by `SMALLSTACK_DATASET_CSV_MAX_ROWS` (50,000);
  over the cap is a 400 asking the caller to filter or page. (C9c)

### Added — approvals + notifications

The two primitives themselves, which had no changelog entry: ~19 *fixes* to them
were documented below before this section said they existed. (F-56 #10)

- **`apps/approvals` — a side-car human-in-the-loop approval gate.** An app (or
  an AI agent) files an `ApprovalRequest`, a human decides it in the staff queue
  and decision console at `/smallstack/approvals/requests/`, and the app reacts
  through a per-kind callback. What "approved" *means* stays app-owned:
  approvals never write your models. State machine
  `pending → approved | rejected | canceled | expired`, every transition
  race-safe (conditional UPDATE, single winner) and audited.
  - `@approval_kind` registry, autodiscovered from `<app>/approvals.py`, with
    `default_expires_in`, a `can_decide` eligibility hook that *narrows only*,
    `assignable` allowlisting, `notify` extra recipients, and a context card
    template per kind.
  - One eligibility implementation (`permissions.can_decide`) shared by web,
    REST and MCP: staff by default, self-approval blocked, assignees narrow.
  - Surfaces: the console, `{% approval_card %}` for non-staff assignees,
    `POST …/requests/create/` + `{id}/decide/` REST, `request_approval` /
    `decide_approval` MCP tools, `approval_requested` / `approval_decided`
    signals, `.created` / `.updated` webhooks carrying `data.status`, a
    dashboard widget, and a 5-minute expiry sweep plus lazy expiry so
    correctness never depends on the worker.
- **`apps/notifications` — an in-app notification primitive.** A never-raising
  `notify()` service, topbar bell with unread badge, a LoginRequired inbox at
  `/smallstack/notifications/` (deliberately *not* staff-only), per-user REST
  (`api/` + `api/mark-read/`), and a daily retention prune.
- **New public notifications API** beyond `notify()`: `services.resolve(subject_key,
  kind="")` retires every unread row about a subject, `notify(..., subject_key=…)`
  tags a row with a producer-owned handle, and `Notification.subject_key` (indexed)
  stores it. This is what lets a decision retire the other approvers' now-stale
  "Approval needed" bells instead of leaving a badge that means nothing. (F-56 #3)
- **New middleware** — `apps.notifications.middleware.NotificationReadOnArrivalMiddleware`
  is added to `MIDDLEWARE` in `config/settings/base.py`. It marks a notification
  read only on a 2xx arrival, so a click that dead-ends cannot silently consume
  the badge. **A fork that pins its own `MIDDLEWARE` list must add this entry**
  or it loses read-on-arrival. (F-56 #1)
- **Nine settings**: `SMALLSTACK_APPROVALS_ENABLED`,
  `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE`, `SMALLSTACK_APPROVALS_STAFF_OVERRIDE`,
  `SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES`, `SMALLSTACK_APPROVALS_EMAILS_ENABLED`,
  `SMALLSTACK_APPROVALS_NOTIFY_EMAILS`, `SMALLSTACK_APPROVALS_SWEEP_ENABLED`,
  `SMALLSTACK_NOTIFICATIONS_ENABLED`, `SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS`
  — plus the five added by the review, listed under Changed.

### Changed — approvals/notifications review (2026-09-25)

Behaviour changes an operator or a fork will notice. Recipes for the ones with a
remedy are in [`UPGRADING.md`](UPGRADING.md).

- **API tokens held by deactivated accounts stop working.** `APIToken` now
  refuses a token whose user is `is_active=False` on *every* surface (REST, MCP,
  feeds, OAuth), and approvals eligibility requires an active user too.
  Previously an offboarded account's un-revoked token kept reading the queue and
  **approving/rejecting**, recorded under their name. This changes behaviour at
  every offboarding: deactivating a user is now sufficient to cut their tokens,
  where before revocation was also required. (F-10, F-56 #4)
- **The master switches now un-mount their app's URLs**, following the
  `SMALLSTACK_MCP_ENABLED` precedent. With `SMALLSTACK_APPROVALS_ENABLED=False`
  or `SMALLSTACK_NOTIFICATIONS_ENABLED=False`, the routes cease to exist rather
  than staying live while only the fan-out died. **Consequence:** a template or
  `reverse()` referencing e.g. `notifications:inbox` under a disabled switch now
  raises `NoReverseMatch` (a 500) instead of rendering a dead link — guard such
  references with the switch. (F-11, F-56 #2)
- **New `WebhookReceiver.signature_header` default:** `"X-Signature"` →
  `"X-SmallStack-Signature"`, matching what outbound signs, with migration
  `webhooks/0004`. Existing receivers keep their stored value; **receivers
  created after the upgrade expect the new spelling**, so a third-party sender
  configured for `X-Signature` will 401 unless the field is set explicitly.
  (F-06, F-56 #8)
- **System-initiated audit entries create one inactive `User` row.** The first
  write with no human actor (expiry sweep, scheduler retirement) creates an
  `is_active=False`, non-staff account named by the new
  `SMALLSTACK_AUDIT_SYSTEM_USERNAME` (default `"system"`), so those entries have
  an author instead of being invisible. Expect one unfamiliar row in the user
  list; it cannot log in. (F-15, F-56 #7)
- **Filing an approval can now return 429.** `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER`
  (default 50) caps one requester's open requests **per kind**; over it, REST and MCP return
  `too_many_pending`. An agent in a retry loop could previously fill the queue
  unbounded. (F-18, F-56 #5)
- **Four more new settings** (F-56 #6):
  - `SMALLSTACK_APPROVALS_EMAILS_INLINE` — defaults to `DEBUG`. Sending falls
    back to inline only when set; **in production this means approval email
    requires a `db_worker` draining the `email` queue.** The new
    `approvals-fanout` monitor goes DOWN when it isn't.
  - `SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES` (15) — how stale the email
    queue may get before that monitor complains.
  - `SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT` (25) — rows lazily expired per
    request, bounding what had been an unbounded synchronous sweep inside a GET.
  - `SMALLSTACK_AUDIT_SYSTEM_USERNAME` (`"system"`) — see above.
- **Generated MCP tool refusals carry a machine-readable `code`** —
  `invalid_argument` · `not_found` · `not_permitted` · `validation_error` ·
  `unsupported` — where they previously returned a bare English sentence. A
  rejected create also now sets the protocol-level `isError` flag (it returned
  `{"errors": …}` with no top-level `error` key, so a model reading the flag saw
  success). Clients string-matching the old prose must switch to `error.code`.
  (F-53)
- **REST exposes `target_ref` and `assignee_usernames` on approval requests**,
  so the API shows the target it accepts (`"app_label.model:pk"`) instead of
  serializing it to `null`. (F-35)
- **Four new framework migrations**: `notifications/0002` (+`subject_key` and its
  index), `notifications/0003` (backfill — see `UPGRADING.md`), `scheduler/0003`
  (+`auto_retired`), `webhooks/0004` (the header default above).

### Security — approvals/notifications review (2026-09-25)

- **Per-object authorization now covers every single-object CRUD surface.** New
  `CRUDView.check_object_permission(obj, request)` hook, applied by the base to
  detail, edit, delete, field-preview, related-tab, the REST detail/update/delete
  handlers, the bulk-action view and the generated MCP `get_*`/`update_*`/`delete_*`
  tools. Previously a view that expressed ownership by overriding one generated
  base's `get_object` protected only that base: `/smallstack/tokens/<pk>/related/request_logs/`
  returned **200** with another user's API-token request log — which endpoints
  that token calls and when — to any logged-in non-staff account, while the
  detail page beside it correctly answered 403. `tokenmgr` now uses the hook.
  (F-27)
- **Deactivating an account no longer widens an approval's audience.** A request
  routed to one named assignee used to become a broadcast to every active staff
  user the moment that assignee was offboarded (1 recipient → 6 recipients, 1
  bell → 10), silently. The fallback remains — the request must not go unseen —
  but it logs a warning naming the deactivated assignees and both the email
  subject and the bell title carry `(assignee deactivated)`. (F-32)
- **The MCP tier ladder is no longer inverted.** It ranked
  `readonly < staff < auth`, so `requires_access="auth"` — documented as "gate to
  any authenticated caller" — could be satisfied by *no* login token, and staff
  were strictly less capable than non-staff on that tier. The ladder is now
  `readonly < auth < staff`, and only the `staff` tier implies the staff flag.
  Latent before this (nothing shipped declares `"auth"`, though a dataset author's
  `mcp_access="auth"` reaches it). (F-26)
- **An inbound webhook verifier that raises is logged.** The bare
  `except Exception` around the verifier swallowed everything, so a verifier
  raising on a *correct* signature was indistinguishable from a forged one with
  nothing in the log. Still fails closed. (F-37)

### Fixed — approvals/notifications review (2026-09-25)

- **Multi-line `{# … #}` comments no longer render as page text.** Django's `{# #}`
  is single-line only; three multi-line ones were being emitted verbatim — on the
  approvals decision console and in *every* CRUDView's no-match empty state. Swept
  tree-wide (12 more in `smallstack/starter.html`, which ships as "copy this
  file"). Guarded by `apps/smallstack/test_template_hygiene.py`, which reads every
  template in the tree and also asserts that rendered CRUD pages contain no `{#`,
  `{%` or `{{`. (F-45)
- **The empty state branches on filters, not on "any query param".** It tested
  `request.GET.urlencode`, which is truthy for pagination, ordering, the display
  toggle and the `?_notification=` marker the notification bell appends — so a
  user who sorted an empty list or arrived from a bell row was told to "clear
  their filters" and lost the create-the-first-one link. New
  `has_active_filters` context flag; the four divergent copies of the empty state
  converge on one include. (F-44)
- **`?status=pending` on the approvals queue now agrees with its own Pending stat
  card.** Expiry is lazy, so an overdue row's stored `status` still reads
  `pending`; the filter matched the column while the card counted `actionable()`,
  and the page contradicted itself by 900 rows. Both now evaluate
  `ApprovalRequestQuerySet.for_effective_status`, on HTML, REST and MCP, and
  `?status=expired` includes overdue-but-unswept rows. New generic
  `CRUDView.apply_filter(qs, field_name, value, request)` hook. (F-29)
- **`SMALLSTACK_APPROVALS_SWEEP_ENABLED` is a two-way switch again.** Retiring a
  code-declared scheduled job whose spec disappeared had no reverse, so turning
  the flag back on never restored the job. New `ScheduledJob.auto_retired` marks
  automatic retirements and they are undone when the spec returns; a job an
  operator disabled by hand stays off (and now says so in the log). A relative
  safety valve also refuses to retire more than half the known code jobs in one
  sync, which is the signature of a *partial* autodiscovery failure. (F-30)
- **A verifier that mutates its headers dict works again.** The case-insensitivity
  fix had narrowed the argument from `dict[str, str]` to Django's immutable
  `CaseInsensitiveMapping`, so a third-party verifier doing
  `headers.pop("X-Smallstack-Signature", "")` began returning 401 on correct
  credentials. The argument is now `webhooks.hooks.CaseInsensitiveDict` — a real
  mutable `dict` subclass with case-insensitive lookups. (F-37)
- **A failing status monitor no longer renders as a green tick.** The core tier of
  `/smallstack/status/overview/` built each service row from `Monitor.inventory()`,
  whose base implementation returns `{"ok": True}`, so `approvals-fanout` ("191
  approval email tasks queued and unrun") and `scheduler-tick` ("2 jobs overdue")
  both showed "on" while recorded as FAILING. The row now needs `inventory()` **and**
  the recorded state to be good, and carries the monitor's actionable note.
  Not-yet-recorded still reads as fine. (F-28, F-07)
- **Generated MCP `get_*`/`update_*`/`delete_*` tools accept `id`.** `serialize()`
  emits the row identity as `id` and three hand-written tools accept `id`, but the
  generated ones required `pk` — so an agent passing the id it had just been
  handed got `{"error": "pk is required"}` on its first call, which is exactly
  what `request_approval`'s own description told it to do. `pk` remains a
  permanent alias; schemas declare both with `anyOf`; descriptions name the
  parameter. (F-25)
- **A feature's master switch degrades to 503, not 500.** New
  `apps.smallstack.exceptions.FeatureDisabled`, translated by `api_view` for every
  endpoint in the project. `ApprovalsDisabled` is one, so a *downstream* app's
  endpoint that files an approval with approvals switched off returns a 503
  envelope naming the setting instead of an unhandled 500. Approvals' own dead 503
  handlers and OpenAPI entries are removed — those routes are unmounted whenever
  the exception can be raised. `PermissionDenied` gets the same treatment (403).
  (F-31)
- **Approval emails warn when they would link to `localhost`.** Approvals mail is
  sent without a request, so its absolute console link comes from `SITE_DOMAIN`
  (default `localhost:8000`) — dead on every unconfigured install, including the
  headline "non-staff assignees decide via the emailed link" story. The approvals
  monitor now reports it. Skipped under `DEBUG` and when the email channel is off.
  (F-33)
- **Global search finds a non-staff assignee's own approvals.** Search was the one
  read surface the eligibility scoper never reached (`search_access` defaults to
  STAFF), so a user who could open and decide a request could not find it.
  (F-43)
- **A non-staff approver has a nav entry to the console.** The console is
  LoginRequired + eligibility-scoped, but its only nav registration sat in the
  staff-only ADMIN section. New `nav.register(visible=<predicate>)` for rules the
  `auth_required`/`staff_required` flags cannot express. (F-46)
- **Stale "Approval needed" bells created before the `subject_key` migration can
  be retired.** New data migration backfills `subject_key` from the row's URL and
  marks read any bell whose request is already terminal. Without it the
  retirement feature reached only rows filed after the upgrade — 105 of 105 unread
  rows on the reference install were unaddressable. Idempotent. (F-42)
- The decision-email recipient rule is documented correctly at last: the set is
  **the approvers — including the decider** — plus the requester. The bell differs
  from the email by exactly one person (it skips the actor), and that asymmetry is
  now stated in `emails.py` and both `.md` files. (F-04)

## [0.20.1] - 2026-08-29

### Changed
- **`make lint` now runs ruff *and* mypy** — one command, the full static gate.
  `make typecheck` existed as a deliberately separate target wired only into
  the pre-commit hook, so *commits* were type-checked but a by-hand
  `make test && make lint` gave no type check and no signal one existed. A
  hand-run lint now enforces exactly what the hook enforces; the hook drops
  its duplicate mypy step, and `make typecheck` remains for running mypy alone.
- **CLAUDE.md gains a Types convention**: prefer strongly typed code where
  practical, annotate signatures on new and edited code — under this mypy
  config (`check_untyped_defs = false`) annotating a function is what opts its
  body into checking — and keep `make lint` green before reporting work done.
  CLI reference docs synced (`cli-reference.md`, `cli-tools.md`).

## [0.20.0] - 2026-08-16

### Added
- **`/api/logger/` — the telemetry surface a machine can drive.** The staff
  viewer answered "an operator needs to read the logs without shell access";
  this answers the same question for a CI job, a frontend dev panel, or an AI
  agent. Staff-only, Bearer or session auth, advertised in the OpenAPI schema:

  | Endpoint | |
  |---|---|
  | `GET /api/logger/` | Capability document — filters, limits, capture state |
  | `GET /api/logger/records/` | Search, with the viewer's filters |
  | `GET /api/logger/records/<id>/` | One record, full untruncated traceback |
  | `GET|POST|DELETE /api/logger/capture/` | Read, open, or close a capture window |
  | `GET /api/logger/config/` | Effective settings + live handler stats (read-only) |
  | `GET /api/logger/loggers/` | Logger names with counts, for discovery |

  Shaped for its consumer rather than copying the UI. **Unknown query parameters
  are a 400**, not silently ignored: a human eventually notices a result set
  looks wrong, but `?sevrity=ERROR` returning the *unfiltered* table reads to a
  script as a successful query, and everything concluded afterwards is built on
  it. **`?after_id=` is a cursor, not a page number** — new rows arrive at the
  top, so page 2 of a live tail re-reads what page 1 already returned.
  **`applied_filters` is echoed back**, so a caller can check the server
  understood the query it thinks it sent. List responses truncate tracebacks and
  flag `exc_truncated`; the detail endpoint serves the full text.

  `POST /api/logger/capture/` requires a `note` (the CLI leaves it optional — a
  human running a command is present and accountable in the moment, an
  unattended caller is neither). Duration is clamped with `clamped: true`
  reported rather than silently running for a different period than asked for.
  `DELETE` is idempotent, so a cleanup step in a `finally` is safe. Both are
  audited. A **read-only token can read everything here but cannot open a
  window** — the right credential for CI.

  `GET /api/logger/config/` is deliberately read-only. Persistent configuration
  belongs in settings/env where a deploy reproduces it; an API that rewrote
  baseline logging config would be a drift generator. The capture window is the
  one runtime knob, and it expires.

- **Five MCP tools** — `logs_search`, `logs_get`, `logs_status`,
  `logs_capture_start`, `logs_capture_stop` — so an agent can run a whole
  debugging session: turn capture up, reproduce, correlate an `X-Request-ID` to
  the lines that explain it, turn capture back down. Five rather than eight
  because every tool costs room in an agent's tool list, and "what's the state
  of logging here" is one question: `logs_status` answers capture state,
  effective config, and the busiest loggers together.

- **`manage.py logs`** — search captured records from the shell, which
  previously required a browser. `--level`, `--logger`, `--request-id`,
  `--trace-id`, `--search`, `--since`/`--until`, `--after-id`, plus `--id` for
  one record with its full traceback and `--follow` for a cursor-based tail. An
  empty result says whether capture was simply at its baseline, which is the
  usual cause.

- **`--json` on `log_capture` and `prune_logs`.** The human output of
  `log_capture status` printed a *Python dict repr* — single quotes, `False` not
  `false` — so anything consuming it was screen-scraping something that was
  never JSON.

- **`apps/telemetry/queries.py`** — one implementation of the filters,
  validation, serialization, and capture verbs, with the REST API, the MCP
  tools, and the CLI as thin adapters over it. Two bugs fixed in this same
  release line were one rule written twice and drifting apart; three transports
  made that risk structural, so the shared core removes it. Tests assert the
  three surfaces return identical results for identical queries.

### Fixed
- **Read-only API tokens could write through any hand-rolled `@api_view`
  endpoint** (security). CRUDView-generated endpoints have always enforced the
  read-only rule via `_check_api_permissions`, but that is only reached from the
  generated views — the `api_view` decorator every *custom* endpoint uses never
  called it. `apps/runbook/api.py` was unaffected only because it independently
  re-implemented the same rule in a private helper; anything else was exempt,
  and a new endpoint had no way to know it needed the check. Verified with a
  synthetic endpoint: a read-only token returned 200 **and ran its side
  effect**. Now enforced in `api_view` itself, so the rule is structural rather
  than remembered. Login tokens (`access_level=""`) are unaffected; only tokens
  explicitly minted read-only change behaviour, which is the point of minting
  them.

- **Django's own 4xx access-log lines carried no `request_id`.** `get_response()`
  calls `log_response(..., request=request)` *after* the middleware chain
  returns — i.e. after `RequestIDMiddleware`'s `finally` reset — so the
  `Unauthorized:`/`Not Found:` line documenting a failure was invisible to a
  search by the very ID the client was told to quote. 500s were fine, which made
  it easy to miss. `RequestContextFilter` now falls back to `record.request.id`,
  defensively enough that a missing or broken `request` can never take the line
  down.

- **`X-Request-ID` was not exposed to cross-origin JavaScript.** The header was
  on the wire but absent from `Access-Control-Expose-Headers`, so `fetch()` read
  `null` — the correlation story was unreachable from exactly the browser
  clients it was written for. `CORS_EXPOSE_HEADERS` now lists it.

- **A freshly-started process ignored an already-open capture window** until it
  happened to log at or above the baseline level. `Logger.callHandlers` compares
  `record.levelno` against the handler's level *before* invoking the handler, so
  nothing inside `emit()` can run for a below-baseline record — meaning the
  writer/poller thread that picks up capture windows never started. A worker
  whose early lines are all INFO could sit outside an open DEBUG window
  indefinitely. `TelemetryConfig.ready()` now starts the poller eagerly.
  (`_ensure_worker()` also gated on `django_apps.ready`, which `Apps.populate()`
  only sets *after* every `ready()` returns — always false at that call site.)

- **The log viewer's `?logger=` filter matched sibling names.** It was a raw
  `startswith`, so `apps.telemetry` also matched `apps.telemetry_report` — the
  bug class the capture handler's own exclusion check had already been fixed
  for. Both now share `logger_match.prefix_q`.

- **A non-serializable `extra` value rendered with `str()` while the docs
  promised `repr()`** — which loses exactly the type information you want when
  reading a log. Now `repr()`, bounded to 2000 characters. An `extra` value whose
  `__repr__()` *raises* no longer drops the whole line either: the DB handler's
  fallback used to re-touch the poisoned value and fail again, losing the
  message and every healthy field with it.

- **`log_capture start` always claimed the duration was clamped**, because it
  compared two independently-generated `timezone.now()` values.

- **CRUDView bulk delete/update left no trace.** A 500-row bulk delete was
  invisible in both the log viewer and the audit trail. Now one summary log line
  per call (not one per row — that is the unbounded-growth failure mode the
  handler's own docstring warns about) plus per-row `LogEntry` audit entries
  written in a single `bulk_create`, because "who deleted row X" has to stay
  answerable per row.

- **`bind_trace_id()` was documented but unused**, and unreachable in the
  viewer. Background tasks and scheduler jobs now bind a trace ID
  automatically, and the viewer gained a `trace_id` filter. The task hook
  subscribes to **both** identically-named signal pairs — `django_tasks.signals`
  (sent by `django_tasks_db`'s worker) and `django.tasks.signals` (sent by
  Django's own backends, including the `ImmediateBackend` the test settings
  use). Subscribing to one meant trace binding silently stopped the moment
  `TASKS["default"]["BACKEND"]` changed; it also meant the real
  `enqueue()`-to-execution path had no test coverage, since the suite runs on
  the namespace the hook wasn't listening to.

- **`django.server` is no longer captured to the database.** The dev server's
  per-request access log wrote one INFO record per request, so anything polling
  the log table filled it with its own poll traffic — the viewer's five-second
  live mode included. Measured: ten polls of the logger API produced eleven new
  records; zero after the fix. It does not exist in production (gunicorn writes
  its own access log), and `RequestLog` already stores the same information
  properly, with a user and a request ID attached.

The telemetry subsystem itself — the staff log viewer, database-backed capture,
and real JSON logging — landed after v0.19.0 and ships here too. Its notes
follow.

### Added — telemetry subsystem
- **`/smallstack/logs/` — a staff log viewer, so the whole loop works without
  shell access.** Newest-first, one line per record, with a colour rail down the
  left edge carrying severity: level is the attribute you scan for, and a rail
  finds it without reading while costing no row height (a badge would have made
  every row taller for information the rail already carries). Filters for level
  (each showing the count you'd get), logger, time range, and a search that
  covers tracebacks as well as messages — the exception class is what you
  remember, and it lives in the traceback.

  Rows expand in place for the full message, traceback, `extra` fields and
  source location; tracebacks load on demand, since one can be 20 KB and fifty
  inlined would dominate the page. A live mode polls every five seconds.

  **The capture control sits in the page header**, because "nothing here, turn
  it up" is the first move when the baseline level missed your bug. Opening a
  window from the UI is audited via `log_action`.

  **Request correlation is now round-trip**: expanding a record links to every
  line its request produced, and `/smallstack/activity/requests/` gained a
  `logs` link per request going the other way.

  Verified across the django / orange / dark-blue / high-contrast palettes, in
  light and dark, and down to a 420px viewport (the logger column drops, the
  rails hold).

- **`apps/telemetry` — log records are written to the database, so a deployment
  is debuggable from inside the app.** Console and file logging both assume you
  can reach the output; a container platform with no shell means the log is
  written perfectly and you can't see a line of it. Records now also land in
  `telemetry_logrecord`, browsable at `/admin/telemetry/logrecord/` and through
  Explorer, each carrying the `request_id` that produced it — so an
  `X-Request-ID` from a bug report pulls every line that request emitted.

- **Time-boxed capture windows.** Baseline capture is WARNING so the table
  stays small. `manage.py log_capture start --level DEBUG --minutes 15` turns it
  up and it closes itself — nothing is left switched on because someone got
  distracted. The window lives in the database, not one process's memory, so
  every worker and container picks it up within a poll interval (5s), and each
  row records who opened it and why.

  Both the handler *and* the logger levels move. A record has to be created
  before any handler is consulted, so lowering the handler alone would capture
  nothing new — this is the usual reason "I turned on DEBUG and saw nothing".
  `TELEMETRY_CAPTURE_LOGGERS` controls which loggers are lowered;
  `django.db.backends` is pinned at WARNING regardless, because at DEBUG it
  emits one line per SQL query.

- **`DatabaseLogHandler`, built so logging can never break a request.** Four
  guards, each for a specific failure mode of writing logs to the database you
  are serving from:
  - *recursion* — writing a row runs a query, the query logs, the record comes
    back to the handler. A thread-local guard plus logger-hierarchy exclusion
    breaks the cycle.
  - *raising* — every path swallows; a failed write costs log lines, not a 500.
  - *latency* — nothing is written on the request path; records go to a bounded
    queue and a background thread batches them out.
  - *load* — an incident floods ERROR lines exactly when the database can least
    absorb them, so the queue drops on overflow and counts the drops instead of
    blocking the caller. `log_capture status` reports them.

- **`manage.py prune_logs`** — retention by age (`TELEMETRY_LOG_RETENTION_DAYS`,
  default 7) *and* a hard row cap (`TELEMETRY_LOG_MAX_ROWS`, default 20000),
  whichever binds first; wired into the container cron every 15 minutes. Age
  alone wouldn't survive an incident logging a million lines in ten minutes; a
  cap alone would keep stale rows forever on a quiet site.

- **`manage.py log_capture start|stop|status`** — control surface for the
  window, plus queue health (written / dropped / errors / worker liveness).

- 51 tests in `apps/telemetry/tests/`. Two bugs they caught during development:
  logger exclusion used a raw string prefix, which also swallowed unrelated apps
  like `apps.telemetry_report`; and the row-cap prune cut on `pk`, copied from
  `prune_activity` where pk order tracks timestamp order — it doesn't here,
  because records are queued and batched, so concurrent workers interleave.
  It now cuts on `ts`.

- `TELEMETRY_LOG_CAPTURE_ENABLED=false` switches the whole subsystem off: no
  handler, no queue, no thread, no rows.

### Fixed — telemetry subsystem
- **Production log output is now actually JSON.** The `json` formatter was a
  `%`-style string template (`'{"message": "%(message)s"}'`) that only looked
  like JSON. It emitted malformed lines in three routine cases, all of which
  silently corrupted anything downstream that tried to parse them:

  - **Any quote, backslash, or newline in a message** broke the line — nothing
    escaped `%(message)s`. A single `logger.info('Ticket "42" closed')` was
    enough.
  - **`logger.exception()` was unparseable by construction.** Python appends the
    traceback *after* the formatted string, so the JSON object was followed by
    20-odd raw `Traceback` lines. The most important events were the ones a
    collector could never read.
  - **`extra={...}` was silently discarded.** The format string had no
    placeholder for it, so existing structured call sites in `apps/api/threats.py`
    and `apps/help/search.py` were logging fields that went nowhere.

  Formatting now runs through `json.dumps` (`apps.smallstack.logging.JSONFormatter`):
  messages are escaped, tracebacks land in an `exc` field (with `exc_type`
  alongside) *inside* the object, `stack_info` lands in `stack`, and `extra`
  fields are preserved under an `extra` key. Non-serializable values fall back to
  `repr()` instead of taking the line down, and the formatter cannot raise — a
  serialization failure degrades to a minimal object carrying the message.

### Added — telemetry subsystem (correlation)
- **Log lines carry the request ID that produced them.** `RequestIDMiddleware`
  binds the request ID to a `contextvar`; a new `RequestContextFilter` on each
  handler copies it onto every record as `request_id`. The docs already promised
  you could correlate a user-reported `X-Request-ID` to log entries — now you
  actually can, across both the log stream and the `RequestLog` table, with no
  changes at any call site.
- **`bind_trace_id()` / `reset_trace_id()`** in `apps.smallstack.logging`, for
  stitching together work that isn't a single HTTP request — scheduled jobs,
  webhook delivery chains, multi-step agent runs. Every log line emitted inside
  the binding carries a shared `trace_id`.
- **`apps/smallstack/test_logging.py`** — 33 tests pinning JSON validity
  (quotes, backslashes, newlines, unicode, nested JSON), traceback containment,
  `extra` preservation, context binding and reset-on-exception, and a check that
  the `development.py` / `production.py` `LOGGING` dicts configure cleanly. The
  test settings override `LOGGING`, so nothing else in the suite exercised them.

### Changed — telemetry subsystem
- **Production log timestamps are ISO-8601 UTC** (`2026-03-04T14:23:01.123Z`)
  instead of local-time `%(asctime)s`, so lines from different hosts sort
  correctly. JSON output is ASCII-escaped by default so it can never raise
  `UnicodeEncodeError` on a stream with a non-UTF-8 encoding; parsers decode the
  escapes back to the original text. Pass `ensure_ascii=False` to `JSONFormatter`
  if you read raw container logs by eye.
- **Development console lines show `request_id=…`** when emitted during a
  request, appended at the end of the line so the left edge stays scannable.

## [0.19.0] - 2026-08-16

### Changed
- **The "Connect a SmallStack" pairing panel picks events instead of asking for
  raw JSON.** The "Events (JSON)" text field is replaced by the same
  `EventFilterWidget` picker the endpoint form uses — checkboxes built from
  `available_events()`, with `*` pre-checked reproducing the old `["*"]`
  default. Both surfaces now share one picker, upgraded together:

  - **Plain-English annotations** on every option (`*.created — any record is
    created`; model patterns resolve verbose names: *"a Ticket is created"*).
  - **A help popup** on the custom-pattern box explaining the
    `app.model.action` grammar with examples — built on a new reusable
    `.help-pop` component (`<details>`-based, no JS, keyboard-operable,
    palette-correct), documented in `admin-page-styling.md`.
  - **Progressive disclosure**: the custom-pattern box collapses to a quiet
    "advanced" line when empty and auto-expands with a count badge whenever
    patterns exist — expansion is round-trip safety, since patterns usually
    arrive via REST/MCP/CLI and a UI save with the textarea absent would
    silently strip them.

  The scripted contract is unchanged: raw `events` JSON is still accepted by
  the pairing action, and REST/MCP/CLI post `event_filter` exactly as before.

### Fixed
- **Malformed event patterns are now rejected instead of silently matching
  nothing.** A typo is still valid JSON, so `"support ticket created"` or a
  pasted `["*"]` sailed through every surface and produced an endpoint that
  simply never fires, with no error anywhere. `validate_event_patterns()`
  shape-checks patterns on the endpoint form — HTML, REST, MCP, and CLI all
  validate through it — and in the pairing view. Well-formed patterns that
  match nothing this instance currently emits are still accepted (they may
  target future events); the pairing flow warns about them, staying silent on
  instances with no concrete events where the warning would be noise. Pairing
  with an empty selection is rejected rather than creating a link that
  forwards nothing.
- **The event picker's border used the undefined `--border-color` variable**,
  falling back to a hard-coded `#333` on light themes (the v0.15.2 bug class).
  Now `var(--card-border)`.

## [0.18.0] - 2026-08-15

### Changed
- **The scheduler job edit page is redesigned as a control console.** It was a
  1,830px single-column form with **Run now** buried at the bottom as a
  tertiary outline button; it is now 1,040px with Run now leading the page.

  An **identity strip** replaces both the generic "Edit Scheduled job" card
  header and the read-only "What it runs" section: status dot, job name as the
  title, task path / queue / args in the monospace ops voice, a status line,
  and Run now as a solid-accent button top right. The body becomes two rails —
  cadence editor left, behavior toggles + the Next-5-runs preview right — so
  the fire-time feedback is visible *while* the cadence is edited. Collapses
  to one column under 940px; on mobile Run now stays above the fold.

  The strip also surfaces a state the old page hid: a `next_run_at` in the
  past (stalled worker) used to display as a future-looking "next fire" — it
  now reads **"fire overdue since <date> — is the worker running?"** in
  warning color.

  Delivered as `scheduler/crud/scheduledjob_edit.html` via the CRUDView
  template chain — no framework changes, all cadence-builder JS and htmx
  endpoints untouched. Theme-variable-only, verified across palettes.

### Fixed
- **"Run now" returns to the job page.** `scheduler_run_now` honors a
  same-origin-validated `next` param (the control page posts its own path);
  offsite values fall back to the dashboard, so it cannot become an open
  redirect. Callers that don't pass `next` see the old behavior.

## [0.17.0] - 2026-08-15

### Changed
- **The admin sidebar section is listed A–Z instead of by hand-assigned
  `order`.** It reads: Activity, API Health, API Tokens, Backups, Dashboard,
  Explorer, MCP, Scheduler, Search, Status, Users, Webhooks.

  That section is a tool drawer — a dozen unrelated utilities contributed by
  whichever apps are installed, with no workflow sequence to preserve. It was
  hand-numbered across twelve `apps.py` files, so every new app had to pick a
  number, the numbers collided (`Status` and `Explorer` both sat at `20`, making
  their relative position a function of `INSTALLED_APPS` ordering rather than
  intent), and the list drifted out of alphabetical whenever anything was added
  or relabelled. Sorting in the registry keeps it A–Z permanently, including for
  apps a downstream project adds — which renumbering upstream could never fix.

  Sorting is case-insensitive, so "API Health" files next to "Activity" rather
  than ahead of every lowercase label.

  **`order` is now inert for the admin section** (documented on `register()`).
  A downstream project that deliberately ordered its own admin nav items will
  see them alphabetised instead. Existing `order=` values are harmless and were
  left in place. Every other section still honours `order` exactly as before.

  **"Admin Panel" is unaffected** — it isn't a registry item, but a hardcoded
  link at the end of `sidebar.html` out to Django's own admin, so it stays
  pinned last rather than filing under A.

## [0.16.2] - 2026-08-15

### Fixed
- **Empty states rendered raw template source into the page.** Django's
  tokenizer matches tags with `{%.*?%}` and **no `DOTALL`**, so a `{% %}` tag
  split across lines is never parsed — it is emitted as literal text. Four
  empty-state includes were wrapped for readability and shipped that way, so a
  visitor saw:

  ```
  {% include "smallstack/includes/empty_state.html" with
     no_card=True
     title="No matches"
     body="No "|add:object_verbose_name_plural|add:" matched your search…" %}
  ```

  This hit **every CRUDView on the default templates whenever its list was
  empty** — a no-match search or a fresh install with nothing added yet — on
  both the plain page load and the HTMX toolbar swap, plus the dashboard
  "no widgets available" state and the MCP tools admin.

  The pattern spread because `empty_state.html`'s own usage example was written
  wrapped and every caller copied it; that example is now a single line carrying
  an explicit warning. A whole-tree sweep test now fails the build on any
  multi-line tag — the defect is invisible in review, since the template reads
  perfectly well.
- **A missing `object_verbose_name_plural` raised instead of degrading.** With
  the tag parsing again, `body="No "|add:object_verbose_name_plural` makes that
  variable a filter *argument*, and an unresolved filter argument raises
  `VariableDoesNotExist` rather than rendering empty the way `{{ missing }}`
  does. `_CRUDContextMixin` always supplies it, but this partial is also
  included by hand-written list templates (`usermanager` does, and downstream
  projects do) — it now resolves through `{% with %}` with a default noun.

### Added
- **The related-tab partial is overridable like every other CRUD surface.**
  `_CRUDRelatedTabBase` hardcoded its template while every sibling — including
  `_CRUDFieldPreviewBase` directly above it — resolves through
  `_get_template_names(suffix)`, so it was the one CRUD surface a project could
  not override per model or per app. It now offers the same instance → app →
  default chain. The shipped partial lives at
  `crud/includes/related_tab_content.html`, which doesn't fit the
  `crud/object_{suffix}` default convention, so that path is appended as the
  final fallback — the loader takes the first template that exists, so behavior
  is unchanged when no override is present.

## [0.16.1] - 2026-08-14

### Fixed
- **`CalendarDisplay` compared `DateTimeField`s against naive month boundaries.**
  Filtering used plain `date` bounds, so under `USE_TZ` Django built a naive
  midnight, emitted "received a naive datetime while time zone support is
  active", then coerced it with the **default** timezone — while the bucketing
  side used `localtime()`, the **current** one. Two halves of the same display
  deciding "is this in the month?" through different clocks. Boundaries are now
  coerced to the type each field expects (aware midnight for datetimes, the
  plain date for `DateField`s), resolved independently for the start and end
  fields.

  **No events move.** Verified against rows straddling both month edges,
  including exact midnights: old and new code select identically. The two
  timezones coincide because nothing activates a per-request timezone (the
  profile timezone is applied by a template filter), so the drift this prevents
  is latent — it would only appear if timezone-activating middleware were added.
  Removes 24 warnings from the test suite.
- **`api_doctor` detected opt-ins by regex while `mcp_doctor` used AST.** The
  line-anchored regex matched `enable_api = True` on any line with only
  whitespace before it — i.e. exactly how a code example is indented inside a
  docstring, which is how this codebase documents its own flags (8 in-scope
  modules already mention `enable_api` in prose). Nothing was misreported: of
  two regex/AST disagreements repo-wide, both sat outside the scan's scope. That
  was the problem — the check was correct only because a directory exclusion
  happened to cover the one offending file.

  Both doctors now share `has_enable_classvar(source, marker)` in
  `apps/smallstack/autodiscover.py`, so they agree on what an opt-in is. With
  AST the `management/` exclusion is unnecessary, so `api_doctor` scans that
  directory again — closing the opposite gap, where a genuine opt-in defined in
  a management command was invisible to it but visible to `mcp_doctor`.

## [0.16.0] - 2026-08-14

### Changed
- **`CalendarDisplay` caps events rendered per day (`max_per_day`, default 5).**
  The calendar rendered one chip — plus a hover-tooltip subtree — for every
  record in the visible month, so a high-volume site produced tens of thousands
  of DOM nodes and a calendar that took seconds to paint, or never usefully did.
  Cells now render at most 5 events followed by a **"+N more"** link that
  expands that single day in full (`?day=YYYY-MM-DD`). Overflow events are
  counted, not materialised.

  The point isn't the constant factor — it's that rendered chips are now bounded
  by `max_per_day × days_in_month` **regardless of record count**. Measured on
  200 seeded records: 201 chips / 171 KB before, 26 chips / 73 KB after.

  Capping is a *rendering* limit only: the header total and every "+N more"
  badge still report exact counts. **This changes what existing calendars
  display** — pass `max_per_day=None` to restore the previous behavior.

### Fixed
- **Related tabs 500'd when the related view had no DETAIL action.**
  `_CRUDRelatedTabBase` hardcoded `crud_actions = [Action.DETAIL]`, so
  `{% crud_table %}` reversed `<url_base>-detail` for a view that never
  generates that route (`get_urls` only registers it when `actions` include
  DETAIL). Because related tabs load lazily over HTMX, the NoReverseMatch
  surfaced as a tab with a count badge and an empty body rather than a visible
  error. The tab now forwards what the related view actually routes — DETAIL,
  else UPDATE, else unlinked — matching `crud_table`'s documented fallback.
  DELETE is never forwarded, and exactly one action is passed so a tab whose
  target routes both doesn't grow an Edit column it never had.
- **Related tabs rendered child rows through the parent's hooks.**
  `crud_config` stayed the parent CRUDView's, and `{% crud_table %}` reads
  `row_link_url()`, `row_actions()` and `column_widths` off it — so a parent
  that redirects its row links silently pointed a child row at an unrelated
  record that happened to share its pk. Fails silently, so worth re-checking any
  related tab under a CRUDView that overrides those hooks.
- **`api_doctor` / `mcp_doctor` reported test fixtures as unregistered opt-ins.**
  Both excluded test code by directory (`tests/`), missing the flat `test_*.py`
  convention `apps/smallstack` uses — so `smallstack/test_bulk_ops.py` was
  flagged as an orphan on every run and on the `/smallstack/api/` and
  `/smallstack/mcp/` pages. A CRUDView declared in a test is meant to stay out
  of the registry; the advertised fix (importing it from `AppConfig.ready()`)
  would have published a test view as a live REST endpoint and MCP tool. The
  shared `is_test_module()` helper now lives in
  `apps/smallstack/autodiscover.py` and covers both layouts.

## [0.15.2] - 2026-08-12

### Fixed
- **Invisible "Copy" button on the token-reveal page (gold + high contrast).**
  The button set a background but no `color`, so it inherited `--button-fg` —
  the foreground meant to pair with a *solid* `--primary` fill. On the only two
  palettes with a dark `--button-fg` (gold `#1a1a1a`, high-contrast `#000000`)
  that painted dark text on a dark card and the label disappeared. It now uses
  the existing `.btn-outline` class.
- **Unreadable MCP consent page (`/mcp/oauth/authorize`) on dark themes.** The
  template referenced `--border`, `--muted-fg` and `--code-bg`, none of which
  were defined anywhere, so each always resolved to its hard-coded *light*
  fallback: gray borders on dark cards, and `#f4f4f4` chips whose inherited text
  was also light. That made the client id and the **redirect host** — the one
  field a user must read before granting access — invisible. Its Allow button
  also hard-coded `color: #fff` over `var(--primary)`, i.e. white-on-white on
  the high-contrast palette.
- **Links ignored the selected palette in light mode.** Every dark palette block
  set `--link-fg`, but the gold / orange / purple / dark-blue *light* blocks set
  only `--link-color`. SmallStack's own CSS reads `--link-color`, while Django
  admin's `a:link, a:visited` rule reads `--link-fg` — so every plain anchor
  stayed on admin's `#417893` teal. All light blocks now set both.
- **The default `django` palette had no light block at all**, so light mode fell
  through to Django admin's colors (`--primary: #79aec8`) instead of
  SmallStack's. `admin/css/base.css` declares its variables under
  `html[data-theme="light"], :root`; that first branch scores (0,1,1) and the
  theme JS always writes an explicit `data-theme`, so it outranks theme.css's
  plain `:root` (0,1,0) no matter which file loads last. Adds a django light
  block built on emerald-700 `#047857` (5.5:1 on white — the dark palette's
  `#10b981` is only 2.5:1 and unusable for accent text).

### Added
- **`--border`, `--muted-fg` and `--code-bg`** are now defined in `theme.css`.
  They were referenced by templates but declared nowhere, which is what let the
  bugs above degrade silently. Defined as derived aliases (`var(--card-border)`,
  `var(--text-muted)`, and a `color-mix` recipe) so they track the active theme
  and palette with no per-palette overrides. Prefer the specific token in new
  code.
- **`apps/smallstack/test_palette_css.py`** — parses `palettes.css` against
  `UserProfile.COLOR_PALETTE_CHOICES` and fails if any palette is missing a
  light or dark block, or omits `--link-fg` / `--link-color`.

## [0.15.1] - 2026-08-09

### Internal
- **Test coverage backfill (codebase-review F4).** No behavior change — new
  tests only. `postgres_fts.py` 0% → 83% (a Postgres-gated suite that runs under
  `TEST_DB=postgres` and skips on SQLite); `api.py` 75% → 88% (the auth endpoints
  — register / password change / admin reset — and the REST bulk-update
  endpoint); `mcp/factory.py` 76% → 92% (the update/delete MCP tool handlers);
  `crud.py` 78% → 84% (the HTML bulk-action + bulk-update-form views);
  `audit.py` 57% → 80% (the `log_write` never-raises discipline).

## [0.15.0] - 2026-08-09

### Changed
- **BREAKING — CRUDViews require login by default.** `CRUDView.mixins` now
  defaults to `None`, which the framework resolves to `[LoginRequiredMixin]`;
  previously the default was `[]` (anonymous). A CRUDView that *omitted* `mixins`
  silently shipped public HTML **and** REST endpoints — now it requires login.
  Opt into anonymous access with the new **`public = True`** flag (or an explicit
  `mixins = []`); an explicit `mixins` list always wins. A public view that
  exposes write actions with `enable_api=True` now emits a warning. All bundled
  framework views set `mixins` explicitly and are unaffected. See
  [`UPGRADING.md`](UPGRADING.md). (Codebase-review F6.)

### Added
- **`make typecheck`** — mypy + django-stubs, configured leniently and scoped to
  the type-clean apps (starts at `apps/feeds`; widen app-by-app as each reaches
  green). A local / pre-commit guard, no CI lane. (Codebase-review F3.)

### Removed
- **django-debug-toolbar** — removed from the project entirely (dependency, the
  dev-settings toggle, the `__debug__/` URL, and the bundled help page). It was
  off-by-default dev tooling; dropping it slims the dependency surface.

## [0.14.3] - 2026-08-09

Fixes from a full codebase review (two security fixes + a Django 6.1 deploy-check
regression). All backward-compatible.

### Fixed
- **Security — stored XSS on public search snippets.** Dropped `|safe` on the
  website search result snippet (`templates/website/search.html`); the value is
  raw model text and the view is anonymous, so it's now auto-escaped.
- **Security — PKCE code-challenge compared in constant time.** `verify_pkce`
  (`apps/mcp/oauth.py`) now uses `hmac.compare_digest` instead of `==`.
- **Fresh-clone `manage.py check --deploy` passes again.** Django 6.1's
  `mail.E001` deploy check errored on dev's console email backend; it's now
  silenced in development settings (dev isn't a deploy target — production/SMTP
  is unaffected and still validated). Regression from the v0.14.2 / Django 6.1
  MAILERS migration.

### Removed
- **Dead search abstraction layer** — `apps/search/{api,orchestration,cache,serializers}.py`
  (813 lines with no runtime importers; runtime search goes through
  `get_backend()` directly). Removing it also eliminates a latent
  `SearchAPI.search()` access-gate bypass.

### Internal
- Test integrity + coverage: replaced hollow `api_doctor` tests with a real
  fail-case assertion, restored the SearchBuilder-example + search-admin tests,
  and added audit-logging failure-path tests (`audit.py` 57% → 80%). Documented
  the help-renderer trust boundary.

## [0.14.2] - 2026-08-09

### Fixed
- **Absolute URLs are `https://` behind kamal-proxy.** The base `production.py`
  shipped without `SECURE_PROXY_SSL_HEADER`, so behind the TLS-terminating proxy
  (which forwards over HTTP) `request.is_secure()` was False and Django built
  `http://` absolute URLs — feed self-links, sitemaps, and the links in
  password-reset / invite emails all went out as http. Now sets
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`, **gated on the
  existing `TRUST_PROXY_HEADERS` flag** (default-on in production). Safe by
  default for non-proxy deployments: a directly-exposed instance
  (`TRUST_PROXY_HEADERS=false`) never trusts a client-supplied `X-Forwarded-Proto`.

## [0.14.1] - 2026-08-09

Two upstream bug fixes surfaced by a downstream deploy.

### Fixed
- **Docker builds install from the frozen `uv.lock`.** The `Dockerfile` copied
  `uv.lock` but installed with `uv pip install -e .`, which re-resolves the
  `pyproject.toml` ranges (`django>=6.1`, …) against the index at build time and
  ignores the lock — so images could silently drift onto newer, untested
  dependency releases (a routine deploy pulling a future Django and breaking on
  an incompatible transitive dep, with nothing changed in the repo). Now exports
  the frozen lock and installs that exact set, then the project with `--no-deps`.
  Builds are reproducible (prod == local == CI) and fail loudly if `uv.lock`
  drifts from `pyproject.toml`. Verified via an image build.
- **`mcp_doctor` no longer false-positives on `enable_mcp = True` in strings.**
  The unregistered-opt-in scan was a naive substring match that fired on the
  marker inside docstrings/seed content (the runbook seed command embeds a
  teaching example), turning `mcp_doctor` and the dashboard MCP card yellow over
  a non-issue. It now uses AST detection — the marker counts only as a real
  `ClassDef`-body assignment. `mcp_doctor` goes 6✓/1⚠ → 7✓/0⚠.

## [0.14.0] - 2026-08-08

Django 6.1 + the email `MAILERS` migration. Minor bump because the email change
is **breaking for downstream projects that set `EMAIL_BACKEND`** in their own
settings (see UPGRADING). Also the first published release to carry the
accessibility foundation and the RSS/Atom feeds surface from v0.13.13.

### Changed
- **Django 6.0 → 6.1** (latest stable). `manage.py check` clean and the full
  suite passes; every third-party dependency (axes, csp, filter, htmx,
  tasks-db, cors-headers, debug-toolbar, extensions, whitenoise, mcp) is
  compatible unchanged.
- **Email migrated to Django 6.1's `MAILERS`.** The framework now ships a
  `MAILERS` dict (assembled from the same `EMAIL_*` **environment variables**
  via `config/settings/_email.py`) instead of the deprecated flat `EMAIL_*`
  *settings*, and drops the deprecated `fail_silently` argument across all mail
  calls. This clears every `RemovedInDjango70Warning`. `DEFAULT_FROM_EMAIL` /
  `SERVER_EMAIL` and `send_mail` / `EmailMultiAlternatives` / `mail_admins` are
  unchanged. **Breaking:** Django 6.1 raises `ImproperlyConfigured` if a
  deprecated `EMAIL_*` setting coexists with `MAILERS` — downstream projects
  that define `EMAIL_BACKEND` must migrate (UPGRADING.md).

### Fixed
- Accessibility WCAG 2.1 AA follow-ups across the theme, CRUD tables, and the
  feeds surfaces (sortable headers became real `<button>`s with `aria-sort`,
  focus and labelling polish).
- Feeds: enforce the `SMALLSTACK_FEEDS_ENABLED` master switch on the request
  surface, Django-6 enclosure handling, and consume-side auth headers.
- Test suite: silenced pre-existing naive-datetime and unclosed-file
  `ResourceWarning` noise (no behavior change).

## [0.13.13] - 2026-08-08

Two new surfaces — first-party RSS/Atom feeds and an accessibility foundation —
both built as reusable, documented primitives with the "fix once in the
framework, every project benefits" model.

### Added
- **RSS/Atom feeds (`apps.feeds`)** — a symmetric publish + consume surface,
  mirroring the webhooks philosophy. **Publish**: ``enable_rss = True`` on a
  CRUDView exposes it at ``/feed/<slug>.rss`` (+ ``.atom``), deriving items from
  the existing ``search_display``/``search_subtitle``/timestamp/detail-route
  declarations; curated feeds subclass ``Feed`` + ``register_feed``. Access is
  gated by ``SearchAccess`` (anonymous/authenticated/staff; token via Bearer or
  ``?token=``). The ``rss_item_extra(obj)`` seam attaches enclosures/iTunes tags
  so media/podcast feeds are a downstream add-on, not core. **Consume**:
  ``register_feed_source(name, url, model=, map=, dedupe=)`` + a dependency-free
  RSS 2.0/Atom parser + a collector that runs as ``manage.py collect_feeds`` and
  a ``@scheduled`` poll job (idempotent, deduped), landing in a bundled
  ``CollectedItem`` model or your own. The public status page publishes an
  incidents-plus-maintenance feed at ``/feed/status.rss`` as the reference.
  Skill: ``docs/skills/rss.md``.
- **Accessibility primitives** — reusable building blocks: ``.sr-only``,
  ``.skip-link``, a global ``:focus-visible`` ring, and
  ``window.SmallStack.trapFocus(el)`` (used by the stat modal + omnibar). Skill:
  ``docs/skills/accessibility.md`` (primitives, rules, pre-"done" checklist),
  wired into the read-first guides so agents build accessibly by default.

### Fixed
- **Accessibility (WCAG 2.1 AA) gaps across the theme** — keyboard focus rings
  on form inputs (previously ``outline: none`` with no ``:focus-visible``
  replacement, a 2.4.7 blocker); a skip-to-content link; form errors announced
  via ``role="alert"``; ``<th scope>`` + ``aria-sort`` on CRUD tables; modal
  ``role="dialog"``/``aria-modal``/labelled close + focus trap; and
  ``aria-hidden`` on the decorative SVGs in the shared topbar/sidebar/user-menu.

## [0.13.12] - 2026-08-08

Postgres out-of-the-box hardening for search, upstreamed from a downstream
post-mortem (search worked in dev SQLite, then broke and crawled on prod
Postgres). SQLite masks each of these, so the fix is making the Postgres path
good by default. All backward-compatible; verified on SQLite and a real
Postgres 16.

### Added
- **`reindex_instances(model, objects=None)`** (`apps.search`) — reindex rows
  written by `bulk_create` / `bulk_update` / `QuerySet.update()`, which fire no
  signals and were otherwise left **silently un-indexed** (the most common
  importer/data-migration footgun).
- **Search diagnostics** — `manage.py search_diagnose [query]` and a staff page
  at `/smallstack/search/diagnostics/` share one core: per-table health (est.
  rows, GIN present, un-indexed backlog), app-level timing, and a live
  `EXPLAIN` verdict (Seq Scan vs GIN Bitmap Index Scan, size-aware so it doesn't
  cry wolf on small tables). Answers "is search fast, and if not, where's the
  time" when you can't reach `psql`.
- **`analyze_search_index` management command** — refreshes Postgres planner
  stats for every searchable table (cheap, fast, safe on every deploy; wired
  into the container entrypoint). No-op on SQLite.
- **Help full-text search on Postgres** — both the article index (omnibar /
  `search_help`) and the passage-level RAG index behind the `search_help_docs`
  MCP tool now build a `tsvector`+GIN index on Postgres instead of falling back
  to a Python scan (which returned **empty** for the RAG tool on prod).
- **`digits_search()`** (`apps.search`) — recipe/helper for indexing opaque
  identifiers (phone numbers, SKUs) that the `english` FTS tokenizer won't
  match on partial/formatted input.

### Changed
- **Postgres `rebuild_search_index` is now set-based** — one
  `UPDATE … setweight(to_tsvector(…)) || …` for views whose `search_fields` are
  all local columns (seconds instead of O(rows) per-row UPDATEs); per-row
  fallback retained for property/`__`-related fields. Runs `ANALYZE` afterward.
- **GIN indexes are created `CONCURRENTLY`** on Postgres (autocommit-guarded) so
  provisioning never locks a live table; provisioning failures are surfaced
  rather than only logged.
- **Search-hub row counts use the planner's `reltuples` estimate** on Postgres
  instead of `COUNT(*)` per model (instant catalog lookup vs full scan).

### Fixed
- **Help docs were re-parsed from disk on every request.** `build_search_index()`
  is now memoized (`@lru_cache`); on Postgres, where help search fell back to a
  scan, this took the hot path from ~4.5 s to ~15 ms (~300×).
- **Search results are clickable without `get_absolute_url`.** Hits fall back to
  the registering CRUDView's `{url_base}-detail` route.
- **Changing `search_fields` no longer breaks SQLite search.** FTS5 bakes one
  column per field at create time; the table is now detected as drifted and
  recreated (previously `rebuild_search_index` failed with "table … has no
  column named …").
- **`api_view` no longer force-parses multipart/form bodies as JSON.** File
  uploads to custom API endpoints returned 400 "Invalid JSON" because the
  decorator read `request.body` and demanded JSON for every write method.
  Multipart and form-encoded content types now skip JSON parsing
  (`request.json` is `None`; use `request.POST`/`request.FILES` as usual).
- **Bare-button hover styling no longer outranks custom button classes.** The
  base `button` / `input[type=submit|button]` rules put only the wrapper inside
  `:where()`, so `button:hover` still carried (0,1,1) specificity — enough to
  beat a downstream single-class button (0,1,0) on hover and slide the
  `--primary-hover` background under its custom text color (low-contrast
  accent-on-accent hovers). The entire selector now sits inside `:where()`
  (true zero specificity, all states), matching the rule's stated intent.
  Downstream apps that added defensive per-state `background` declarations can
  keep or drop them; they are now redundant.

## [0.13.11] - 2026-07-29

### Added
- **Datasets — bucketed grouping + drilldown** (R8, the final datasets-feedback
  item). `series()` now accepts a **dict** dimension for bucketed grouping:
  numeric bands (`{lo, hi}`, half-open), categorical (`{value}` / `{values}`),
  an honest `{other: true}` complement, and **auto** top-N value buckets keyed
  `v:<value>` (+ `other`) derived from the unnarrowed scope so keys stay stable
  under filters. Count-only (`[{key, label, value, lo, hi}]`). A `rows(dimension=,
  bucket=)` **drilldown** re-applies the same bucket condition, so the rows behind
  a bucket reconcile with its count by construction. Exposed over REST (JSON
  `buckets` / `auto` params, `bucket=` drilldown) and MCP (`buckets` array, `auto`,
  `bucket`). The bucket grammar (`apps/datasets/buckets.py`) is lifted verbatim
  from the downstream reporter so call_stats can swap to it.

## [0.13.10] - 2026-07-29

### Added
- **Datasets hardening** (from downstream feedback):
  - `@dataset(filterable=…)` replaces `filters=` for the *declaration* of which
    columns may be filtered; the old `filters=` decorator kwarg is a deprecated
    alias (warns). Runtime `rows()/series()/scalar()(filters=…)` is unchanged.
  - Public **`ds.queryset(request, filters)`** seam so a higher layer (a BI/report
    layer) can compose on a dataset's filtered queryset without touching internals.
  - **Pagination**: `rows(limit, offset)` (+ `limit=None` for the whole set) and
    `ds.count()`; the REST rows route returns an envelope `{count, total, offset,
    results}` and CSV exports the whole filtered set.
  - **Declared ratio measures**: `@dataset(measures=[(name, num, denom, fmt)])`
    computes `sum(num)/sum(denom)` in-DB per group (`×100` for percent), returning
    `None` for an empty denominator — never the average of per-row ratios. Surfaced
    in `schema()` (`computed: true`) and the MCP tool.
  - **Explicit date ranges**: `<col>__gte` / `<col>__lt` half-open bounds on any
    date/datetime column, everywhere filters are accepted (explicit wins over a
    preset); `schema()` advertises `"range": true`.
- Datasets app **label namespaced** to `smallstack_datasets` (avoids an
  `INSTALLED_APPS` clash with a downstream app named `datasets`).
- Docs: naming guidance + the flat-filter invariant documented in `datasets.md`.

## [0.13.9] - 2026-07-29

### Added
- **Datasets (`apps/datasets/`)** — the `@dataset` primitive: register a filtered
  queryset as a named, typed source of rows/columns for dashboard/report/chart
  UIs. `schema()` introspects it into dimensions/measures + filter widgets;
  `rows()` returns tabular data (FK columns are a bare pk by default, `id`+`name`
  on expand), `series()` aggregates a measure over a dimension (resolving FK
  dimension labels to name), and a **scalar** mode returns a single aggregate
  (count / sum) when no dimension is given. Opt-in REST + MCP: a `query_dataset`
  tool (series + scalar, honoring filters) and JSON endpoints (anonymous → 401).
  Unknown dimension/measure raise a clear `ValueError`. See `docs/skills/datasets.md`.
- **Help RAG** — a lexical passage index over the bundled help docs plus a
  `search_help_docs` MCP tool, so AI clients can retrieve relevant doc passages.

## [0.13.8] - 2026-07-26

### Added
- **Webhooks (`apps/webhooks/`)** — outbound event delivery and inbound receivers,
  built on the CRUDView pipeline. A model opts into **outbound** with
  `enable_webhooks = True` (like `enable_search`); a global `post_save`/`post_delete`
  observer fans every change — across HTML, REST, MCP, `sc`, and raw ORM — out to
  matching `WebhookEndpoint`s as an HMAC-SHA256-signed POST, delivered through the
  `django.tasks` queue with exponential backoff, **`Retry-After`** support,
  auto-disable, a dead-letter state, and **bulk replay**. **Inbound**: a
  `WebhookReceiver` + a `@webhook_handler` verify the signature (constant-time) and
  dispatch. Ships an SSRF guard, staff-only secret reveal/rotate, a
  `/smallstack/webhooks/` dashboard, a status monitor, `webhook_doctor`, `sc webhook`
  ops, and MCP tools.
- **Webhook extension seams** — four named-registry hooks (`@webhook_transform`,
  `@webhook_auth`, `@webhook_verifier`, `@webhook_challenge`), autodiscovered from an
  app's `webhook_*.py` and each defaulting to the built-in behavior, so a specific
  integration (Slack payloads, Stripe/GitHub/SNS signatures, SAS/OIDC auth, Event Grid
  validation) is a small plug-in rather than a core change. A complete **Azure Event
  Grid** reference adapter (`apps/webhooks/contrib/eventgrid.py`) is built purely on
  the seams with zero core edits.
- **SmallStack↔SmallStack pairing** — `sc webhook pair` stands up a loop-safe two-way
  link in one command (paired endpoint + receiver with per-direction secrets, a
  `suppress_webhooks()` loop guard, and an `X-SmallStack-Origin` header so write-backs
  can't run away). A stable `X-SmallStack-Event-Id` lets consumers dedupe across
  retries and operator replay.

## [0.13.7] - 2026-07-25

### Fixed
- **CRUD list "N Records" count** — the record count lives in the toolbar, outside
  the `#crud-list-content` htmx swap target, so a search/filter left it showing the
  stale pre-filter total. The list-content response now emits an out-of-band copy
  of the count span (`hx-swap-oob`) so it refreshes alongside the list — no extra
  request, no JS. Guarded by `request.htmx` so a full-page load (which includes the
  partial in-page) doesn't render a duplicate. The `tokenmgr` app, which overrides
  the generic list-content partial, gets the same out-of-band refresh.

## [0.13.6] - 2026-07-21

### Added
- **Scheduler (`apps/scheduler/`)** — recurring background jobs over `django.tasks`
  (no Celery/Redis). Ships the `@scheduled` decorator (cron / interval / once,
  with calendar-aware intervals and anchors), DB-backed `ScheduledJob` schedules
  with idempotent code-sync, and a `run_due_jobs` tick with an **atomic claim**
  so concurrent triggers can't double-fire. Overlap guard (with a stale-run
  timeout so a dead worker can't wedge a schedule), catch-up policy, and run
  history linked to the task engine's `DBTaskResult`.
- **Scheduler surfaces** — themed `/smallstack/scheduler/` dashboard (stat cards,
  24h run timeline, upcoming + recent runs, per-job Run-now), a `ScheduledJob`
  CRUDView with REST (`enable_api`) + MCP (`list_schedules` … `delete_schedule`)
  + search, a dashboard widget, a `/status/` core monitor, and Explorer browsing.
- **Scheduler control UI** — the jobs list gains a table⇄calendar toggle (upcoming
  runs by next fire) plus a read-only **run-history** view with its own
  table⇄calendar coloured by outcome. Code-owned jobs render as a **read-only
  control page**: the definition is locked to code; operators override only the
  schedule + enable/pause + Run-now. UI schedule overrides survive code-sync
  (`schedule_overridden`), with a "reset to code default".
- **Triggers** — `POST /smallstack/scheduler/tick/` (localhost-only, runs inside
  gunicorn), `manage.py run_due_tasks`, `manage.py scheduler_beat`; plus
  `manage.py prune_job_runs` history retention. Cron lines added to
  `scripts/smallstack-cron`.
- **Focus mode** on Help & Docs and Runbook now also collapses the SmallStack side
  menu for an immersive read (non-persistent; restored on Expand). `theme.js`
  exposes `window.smallstackSidebar` (get/set state with a persist opt-out).
- Settings: `SMALLSTACK_SCHEDULER_ENABLED`, `_STALE_RUN_SECONDS`,
  `_OVERDUE_GRACE_SECONDS`, `_FAILURE_EMAILS`. New dependency: `croniter`.
- Docs: `docs/skills/scheduler.md`; `@scheduled` flipped from "coming soon" to
  shipped in `CLAUDE.md`, `README.md`, `background-tasks.md`, `skills/README.md`.

### Changed
- **Runbook markdown** now renders with the same recipe as Help & Docs (roomier
  18px/1.8 prose, heading rules, neutral non-accent-tinted code inset into the
  card) — fixes the long-standing readability gap between the two surfaces.
- **Orange palette** retuned to a warm-ground "quiet luxury" look (vivid accent,
  warm-biased surfaces); the elegance levers are documented in `modify-palettes.md`.
- User-menu **"Admin"** now opens the SmallStack dashboard (`/smallstack/`) rather
  than raw Django admin (still reachable from the sidebar "Admin Panel").

### Fixed
- Scheduler hardening: timezone dev/prod parity (Linux/Docker), recompute + monitor
  sample-floor tuning, and agent-hostile input hardening.

## [0.13.5] - 2026-07-19

### Fixed
- **SQLiteFTSBackend.rebuild() deadlock** — Fixed "database is locked" error on models with >500 rows. 
  Root cause: iterator(chunk_size=500) kept read cursor open during writes. Solution: materialize pk list, 
  batch with explicit transactions. Approximately 50x faster; tested with 25,713+ rows.
- **SearchBuilder.transform_hit() call convention** — Fixed silent failure where custom variants returned 
  empty extra payload. Root cause: instance method called unbound on class (TypeError swallowed). 
  Solution: instantiate view before calling, matching pattern elsewhere. Enhanced error logging to 
  document contract.
- **PostgresFTSBackend.rebuild()** — Applied same deadlock fix as SQLite (consistent batching pattern).

### Documentation
- Added fixes/DOWNSTREAM-ISSUES.md documenting both bugs, root causes, and fixes.
- Clarified that filter_searchable_queryset and get_ranking_weights are dead code in v0.13.4; 
  use search_weight and post-filtering instead.

### Backward Compatible
- No API changes
- All fixes are transparent to downstream apps
- Required for any model with >500 rows + enable_search, or custom SearchBuilder.transform_hit()


## [0.13.4] - 2026-07-18

### Added
- **SearchBuilder — programmable search customization** (Phases 1-2, ~3,500 LOC): Optional SearchBuilder protocol 
  enables models to define custom search variants (admin, public, api, mcp, etc.) with computed fields, custom 
  display logic, cross-model orchestration, and automatic MCP tool generation per variant. Native dict serialization 
  (no DRF dependency). Full type hints and comprehensive testing.
- **Native search serialization** — 4 pure-Python dict functions (`serialize_search_hit`, `serialize_search_results`, 
  `serialize_search_config`, `serialize_all_search_configs`) for JSON-safe output. Supports variant-specific extra fields 
  with transparent flattening.
- **Search introspection API** — `SearchAPI` class with 5 methods (get_config, list_variants, search, search_and_filter, 
  get_output_schema) for high-level orchestration; `SearchOrchestrator` for multi-stage workflows and cross-model search.
- **Search variant caching** — In-memory config cache with 1-hour TTL and cache invalidation on view registration.
- **Per-variant MCP tools** — Auto-generated MCP tools for each search variant (search_model, search_model_summary, 
  search_model_admin, etc.) for agent orchestration.

### Fixed
- **F1 (BLOCKER)** — Instance method call on class; fixed by instantiating view_cls before calling get_search_variants().
- **F2 (MAJOR)** — Removed djangorestframework dependency; replaced with 4 native dict serialization functions.
- **F4 (MAJOR)** — Guarded 3 unguarded date_joined references in search examples; added missing email field to admin variant.
- **F5 (MAJOR)** — Fixed 252 ruff lint errors (226 W293 whitespace, 16 F401 unused imports, 9 I001 unsorted, 1 E501 line length).
- **F6 (MAJOR)** — Replaced broken DRF serializer tests with real native serializer tests; removed false pytest.skip guards.
- **F7 (OBSERVATION)** — Documented extra field flattening behavior and collision risk in serialize_search_hit() docstring.

### Technical Details
- All new code is fully typed (Python 3.10+ syntax: dict[str, Any], QuerySet, return types)
- 119 integration tests covering all variants, orchestration, caching, and admin integration
- Comprehensive documentation: RUNBOOK.md, TUTORIAL.md, ORCHESTRATION-GUIDE.md, and 2 AI skills
- Backward compatible: all SearchBuilder methods optional; existing search works unchanged
- No breaking changes to SearchBackend protocol or query() signature


## [0.13.3] - 2026-07-16

### Fixed
- **Runbook dark-mode CSS** — enhanced styling now correctly scoped to app theme (`html[data-theme="dark"]`) 
  instead of OS setting (`@media prefers-color-scheme`), ensuring enhancements apply on default dark mode 
  regardless of OS theme setting.
- **Seeder idempotency** — `seed_platform_runbook` command now properly assigns section before guard check, 
  preventing `IntegrityError` crashes on re-run; added comprehensive idempotency test.

## [0.13.2] - 2026-07-12

### Added
- **`sc` — a framework CLI** (`manage.py sc` / the `sc` console script): a fifth thin skin over the
  CRUDView registry, the same operations as web/REST/MCP. Resource verbs — `ls` (registered models +
  rows, with `-q`/`--filter`/`--order`/`--limit`), `get`, `describe`, `search`, and writes `new`/`set`/
  `rm` through the model's `form_class` validation + `log_write` audit (staff-gated like the MCP tools).
  Operational verbs — `doctor`/`backup`/`token`/`status`/`index` (thin fronts over the framework's
  management commands) plus `sc commands` discovery. `--json` on every read. Explorer-synthesized views
  mean it reaches every admin-registered model, not just hand-written CRUDViews. See
  `docs/skills/sc-cli.md`.

### Fixed
- **Bundled JS client** (`clients/js` v0.3.1): SSR-safe `localStorage` access — the client guards
  `localStorage` so it's safe to import in a server-side-rendering context.

## [0.13.1] - 2026-07-12

### Added
- **Bundled API clients** under `clients/`: a TypeScript/JavaScript SDK (`clients/js`, with built
  `dist/`) and a single-file Python client (`clients/python/smallstack_client.py`) for talking to the
  REST API from external apps. See `clients/README.md`.

## [0.13.0] - 2026-07-12

### Added
- **Runbook — a first-class dynamic-documents app** (`apps/runbook/`): versioned markdown documents
  with images, sections, keyword + full-text search, retention, subscriptions, and portable ZIP
  bundles — readable and writable from the web UI, a transport-agnostic service layer, REST, MCP,
  and a unix-style CLI. (Previously the standalone `smallstack-runbook` package; now permanent core.
  The `smallstack_runbook` DB label is preserved, so existing tables/migrations reuse as-is.)
- **Runbook CLI** (`manage.py runbook` / the `rb` console script): `ls`, `toc`, `find` (BM25-ranked
  search), `cat` (`<ref>@N` reads an earlier version), `write` (stdin), `cp`, `rm`, `restore`, `mv`,
  `revert`, `log`, `stat`, `mkdir`, `sections`, `publish`/`unpublish`. Every verb takes `--json`.
- **Runbook REST API**: full document lifecycle (`api/documents/…`, incl. `append`/`move`/`archive`/
  `unarchive`/`revert`/`copy`) plus an `api/runbooks/…` container resource (list/create, detail +
  table of contents, sections, publish/unpublish). All registered in the OpenAPI schema (Swagger/
  ReDoc) and ownership-scoped. `GET api/documents/?q=` is BM25-ranked (substring fallback).
- **Runbook MCP tools** + search-engine registration (`search_runbook_documents`, global omnibar).
- **Runbook dashboard widget** on the central `/smallstack/` dashboard (runbook + document counts).
- `api_doctor` now lists hand-registered (`register_api_path`) custom endpoints, so its inventory
  matches the OpenAPI schema (and warns on any `url_name` that no longer reverses).

### Changed
- Client-IP resolution is now proxy-aware and shared by the activity log and the django-axes login
  lockout. Behind a trusted reverse proxy (`TRUST_PROXY_HEADERS`, defaulted on in production for
  kamal-proxy) the real client is read from the rightmost, proxy-appended `X-Forwarded-For` entry
  (spoof-resistant); otherwise the unspoofable `REMOTE_ADDR` is used. One helper
  (`apps/smallstack/client_ip.py`) is the single source of truth.
- The markdown hardening from the CRUD field-preview is extracted into a reusable
  `harden_markdown_renderer()` and shared with the runbook renderer.

### Fixed
- **Stored XSS in runbook document rendering** — user- and AI-authored document bodies could inject
  `<script>` / `<img onerror>` / `javascript:` links that executed in a viewer's session. The
  renderer now escapes raw HTML and blanks dangerous URL schemes, and drops the unsafe `md_in_html`
  and `attr_list` extensions. Regression-tested.
- Runbook ZIP export silently omitted section-less ("loose") documents attached straight to a
  runbook — they are now included (loose docs at the archive root).
- Runbook CLI N+1 queries in `ls`, `toc`, and `sections`.
- MCP activity page: the filter `Apply`/`Reset` buttons now align with the control row.
- Silenced the django-axes INFO startup banner in development (it polluted piped CLI output).

### Security
- django-axes now resolves the real client IP behind kamal-proxy, so per-IP brute-force lockout is
  effective in production (previously every request keyed to the proxy's address, neutering it).

## [0.12.4] - 2026-07-11

### Security
- **Dependencies:** bumped Django (→6.0.7), Pillow (→12.3.0), starlette, pydantic-settings, pygments,
  and pytest to their fix releases — `pip-audit` goes from 13 known vulnerabilities to 0.
- Fixed stored-XSS in the CRUD field-preview markdown renderer — arbitrary field content can no
  longer inject script. Raw HTML is neutralized (rendered as escaped text), dangerous link/image
  URL schemes (`javascript:`, `data:`, …) are blanked via a URL allowlist, and the extension set
  is restricted to `fenced_code`/`tables` (no `md_in_html` / `attr_list`). Regression-tested.
- Fixed stored-XSS in search-result snippets — the plain-text snippet is no longer rendered `|safe`.
- CSP: added `base-uri 'self'` and `object-src 'none'` directives (no inline-script trade-off).

### Added
- `register_api_path` — let custom `@api_view` endpoints join the OpenAPI schema.
- Maintenance-window tooling for heartbeat/status: `manage.py maintenance` command and
  `apps/heartbeat/maintenance.py` (open a maintenance window / SLA-exclude a deploy).
- Per-app `README.md` files, plus `SECURITY.md` and this `CHANGELOG.md`.

### Fixed
- Ordering by a computed/non-DB column no longer 500s — a misconfigured `ordering_fields` (or a
  hand-crafted `?ordering=`) degrades to no-sort instead of raising `FieldError`.
- Search: a model registered *after* the search app's `ready()` (from a later app in
  `INSTALLED_APPS`) now gets its per-model `search_<plural>` MCP tool — registration is now
  independent of app order.
- OpenAPI `info.version` and `MCP_SERVER_VERSION` derive from the package version (new
  `SMALLSTACK_VERSION` setting) instead of a hardcoded `1.0.0`.
- Dev `SECRET_KEY` is persisted to a gitignored `.secret_key` so all local processes share one key —
  `screenshot_auth` sessions are no longer silently rejected on a fresh clone.

### Changed
- API-layer dedup: `json.loads` bodies via `_load_json_body`; the three HTML-pagination sites via
  `attach_display_helpers`; `_api_list` and the OpenAPI path builders slimmed via extracted helpers.
- Heartbeat: six function-based views moved to a shared `staff_required` decorator.
- Type hints completed on `apps/activity`, `apps/tasks`, `apps/profile`, and `apps/smallstack/displays.py`;
  narrowed/logged several broad `except` handlers.
- Standardized test layout (`accounts`/`heartbeat` → `tests/` packages); `apps/tasks` coverage 0% → 99%.
- Docs: unified "Coming soon" framing for `@scheduled` + vector search; completed the CLI reference.

## [0.12.3] - 2026

### Fixed
- Invisible status calendar/timeline cells on standalone status pages.

## [0.12.2] - 2026

### Changed
- Maintenance-aware status: uptime/SLA calculations exclude scheduled maintenance windows.

### Fixed
- Test-suite robustness improvements.

## [0.12.1] - 2026

### Added
- `merge-0.12.0` upgrade skill documenting the v0.12.0 migration path.

## [0.12.0] - 2026

### Added
- **Pluggable status monitoring system** — register a Service + Monitor to track a
  subsystem's uptime/health on `/smallstack/status/`; add status visualizations.
  See `docs/skills/status-monitors.md`.

### Changed
- MCP and Search are decoupled from the status system (independent enable flags).
- Daily-timeline "today" coloring and doctor-command flag-awareness fixes.

### Removed
- **django-tables2** and the public `apps.smallstack.tables` / `table_class` surface.
  Downstream projects importing these must migrate — see `UPGRADING.md`.

## [0.11.x] - 2026

Condensed highlights of the v0.11 series (see git history for per-patch detail):

### Added
- Account invites by email + passwordless code login with branded emails (`apps/accounts`).
- Username-or-email login (`EmailOrUsernameBackend`).
- `usermanager`: password-on-create, edit actions, and guardrails.
- Consolidated dashboard stat cards into one `{% stat_card %}` standard with drill-down modals.
- API endpoints admin page; clickable list rows; table pagination.
- Editorial "Getting Started" redesign; apps-dropdown redesign; Search section on Home.

### Fixed
- **v0.11.14** — pinned test settings to `config.settings.test` (`--ds` in `addopts`) so the
  suite no longer silently ran under dev settings; hermetic dev-superuser test; v0.12 upgrade note.
- **v0.11.13** — platform re-audit hardening: security fixes (OAuth scope→role capping, token
  scope, backups, allowed hosts), Postgres fixes, **GitHub Actions CI** (SQLite + Postgres matrix
  + ruff), and the django-tables2 removal groundwork.
- Django-6 `log_action` breakage that broke programmatic API/MCP write audit logging.
- Explorer detail grid rendering every boolean as ✓ regardless of value.

## Earlier releases (0.8.x – 0.10.x)

See the git tag history (`git tag`) and `ai_cowork/audit_history/` for the full record of the
v0.8–v0.10 API-server, modern-dark-theme, search, MCP, and Postgres eras.

[Unreleased]: https://github.com/emichaud/django-smallstack/compare/v0.21.5...HEAD
[0.21.5]: https://github.com/emichaud/django-smallstack/compare/v0.21.4...v0.21.5
[0.21.4]: https://github.com/emichaud/django-smallstack/compare/v0.21.3...v0.21.4
[0.21.3]: https://github.com/emichaud/django-smallstack/compare/v0.21.2...v0.21.3
[0.21.2]: https://github.com/emichaud/django-smallstack/compare/v0.21.1...v0.21.2
[0.21.1]: https://github.com/emichaud/django-smallstack/compare/v0.21.0...v0.21.1
[0.21.0]: https://github.com/emichaud/django-smallstack/compare/v0.20.1...v0.21.0
[0.20.1]: https://github.com/emichaud/django-smallstack/compare/v0.20.0...v0.20.1
[0.20.0]: https://github.com/emichaud/django-smallstack/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/emichaud/django-smallstack/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/emichaud/django-smallstack/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/emichaud/django-smallstack/compare/v0.16.2...v0.17.0
[0.16.2]: https://github.com/emichaud/django-smallstack/compare/v0.16.1...v0.16.2
[0.16.1]: https://github.com/emichaud/django-smallstack/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/emichaud/django-smallstack/compare/v0.15.2...v0.16.0
[0.15.2]: https://github.com/emichaud/django-smallstack/compare/v0.15.1...v0.15.2
[0.15.1]: https://github.com/emichaud/django-smallstack/compare/v0.15.0...v0.15.1
[0.15.0]: https://github.com/emichaud/django-smallstack/compare/v0.14.3...v0.15.0
[0.14.3]: https://github.com/emichaud/django-smallstack/compare/v0.14.2...v0.14.3
[0.14.2]: https://github.com/emichaud/django-smallstack/compare/v0.14.1...v0.14.2
[0.14.1]: https://github.com/emichaud/django-smallstack/compare/v0.14.0...v0.14.1
[0.14.0]: https://github.com/emichaud/django-smallstack/compare/v0.13.13...v0.14.0
[0.13.13]: https://github.com/emichaud/django-smallstack/compare/v0.13.12...v0.13.13
[0.13.12]: https://github.com/emichaud/django-smallstack/compare/v0.13.11...v0.13.12
[0.13.8]: https://github.com/emichaud/django-smallstack/compare/v0.13.7...v0.13.8
[0.13.7]: https://github.com/emichaud/django-smallstack/compare/v0.13.6...v0.13.7
[0.13.6]: https://github.com/emichaud/django-smallstack/compare/v0.13.5...v0.13.6
[0.13.5]: https://github.com/emichaud/django-smallstack/compare/v0.13.4...v0.13.5
[0.13.4]: https://github.com/emichaud/django-smallstack/compare/v0.13.3...v0.13.4
[0.13.3]: https://github.com/emichaud/django-smallstack/compare/v0.13.2...v0.13.3
[0.13.2]: https://github.com/emichaud/django-smallstack/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/emichaud/django-smallstack/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/emichaud/django-smallstack/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/emichaud/django-smallstack/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/emichaud/django-smallstack/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/emichaud/django-smallstack/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/emichaud/django-smallstack/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/emichaud/django-smallstack/compare/v0.11.19...v0.12.0
