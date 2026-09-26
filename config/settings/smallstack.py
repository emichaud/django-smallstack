"""
SmallStack application settings.

All user-customizable SmallStack settings live here. Override any value
via environment variable (python-decouple) or by editing the defaults below.

Infrastructure settings (INSTALLED_APPS, MIDDLEWARE, DATABASES, etc.)
remain in base.py.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from decouple import config

try:
    # Single source of truth: the installed distribution's version (pyproject.toml).
    _PACKAGE_VERSION = _pkg_version("django-smallstack")
except PackageNotFoundError:
    # Running from source without an installed distribution — read the version
    # straight from pyproject.toml so it can never drift from the real one. (A
    # hardcoded string here silently goes stale every release; see the version
    # locations in docs/skills/release-process.md.)
    import tomllib

    try:
        _pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        _PACKAGE_VERSION = tomllib.loads(_pyproject.read_text())["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        _PACKAGE_VERSION = "0.0.0+unknown"

# The version SmallStack advertises across its surfaces (OpenAPI info.version,
# MCP initialize). Derived from the package so it never drifts; override via env
# if you version your API contract independently of the package.
SMALLSTACK_VERSION = config("SMALLSTACK_VERSION", default=_PACKAGE_VERSION)

# Needed by BACKUP_DIR below. Same calculation as base.py — duplicated
# here to avoid circular imports (this file is imported INTO base.py).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Site Identity
# ---------------------------------------------------------------------------
SITE_NAME = config("SITE_NAME", default="SmallStack")
SITE_DOMAIN = config("SITE_DOMAIN", default="localhost:8000")
USE_HTTPS = config("USE_HTTPS", default=False, cast=bool)
TIME_ZONE = config("TIME_ZONE", default="America/New_York")

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------
# These paths are relative to STATIC_URL. Override to customize branding.
BRAND_NAME = config("BRAND_NAME", default="SmallStack")
BRAND_LOGO = config("BRAND_LOGO", default="smallstack/brand/django-smallstack-logo.svg")
BRAND_LOGO_DARK = config("BRAND_LOGO_DARK", default="smallstack/brand/django-smallstack-logo-dark.svg")
BRAND_LOGO_TEXT = config("BRAND_LOGO_TEXT", default="smallstack/brand/django-smallstack-text.svg")
BRAND_ICON = config("BRAND_ICON", default="smallstack/brand/django-smallstack-icon.svg")
BRAND_FAVICON = config("BRAND_FAVICON", default="smallstack/brand/django-smallstack-icon.ico")
BRAND_SOCIAL_IMAGE = config("BRAND_SOCIAL_IMAGE", default="smallstack/brand/django-smallstack-social.png")
BRAND_TAGLINE = config("BRAND_TAGLINE", default="A minimal Django starter stack")

# Legal / Consent
BRAND_PRIVACY_URL = config("BRAND_PRIVACY_URL", default="/privacy/")
BRAND_TERMS_URL = config("BRAND_TERMS_URL", default="/terms/")
BRAND_COOKIE_BANNER = config("BRAND_COOKIE_BANNER", default=True, cast=bool)
BRAND_SIGNUP_TERMS_NOTICE = config("BRAND_SIGNUP_TERMS_NOTICE", default=True, cast=bool)

# ---------------------------------------------------------------------------
# Email Defaults
# ---------------------------------------------------------------------------
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")

# Django 6.1's MAILERS (replaces the deprecated EMAIL_* settings; removed in 7.0).
# Base default is the console backend; production overrides to SMTP. Still
# driven by the same EMAIL_* env vars — see config/settings/_email.py.
from ._email import CONSOLE_BACKEND, build_mailers  # noqa: E402

MAILERS = build_mailers(default_backend=CONSOLE_BACKEND)

# Accent colour used in HTML emails (the branded header band + buttons).
# Emails can't use the live CSS palette, so this is a single re-brandable knob.
# Default is the Django-palette emerald, not the old Django-admin teal.
BRAND_EMAIL_ACCENT = config("BRAND_EMAIL_ACCENT", default="#10b981")

# How long password-reset / set-password / invite links stay valid (seconds).
# Set explicitly so the "expires in 24 hours" email copy is actually true.
PASSWORD_RESET_TIMEOUT = config("PASSWORD_RESET_TIMEOUT", default=86400, cast=int)

# ---------------------------------------------------------------------------
# Feature Flags & UI
# ---------------------------------------------------------------------------
# SmallStack Help Documentation
# Set to False to hide SmallStack reference docs from /help/
SMALLSTACK_DOCS_ENABLED = config("SMALLSTACK_DOCS_ENABLED", default=True, cast=bool)

# SmallStack Color Palette
# System-wide default palette. Users can override in their profile.
# Options: django, high-contrast, dark-blue, orange, purple
SMALLSTACK_COLOR_PALETTE = config("SMALLSTACK_COLOR_PALETTE", default="purple")

# Auth Feature Flags
# Set to False to hide Login/Sign Up buttons from the topbar
SMALLSTACK_LOGIN_ENABLED = config("SMALLSTACK_LOGIN_ENABLED", default=True, cast=bool)
# Set to False to hide Sign Up and 404 the signup URL
SMALLSTACK_SIGNUP_ENABLED = config("SMALLSTACK_SIGNUP_ENABLED", default=True, cast=bool)
# Passwordless ("email me a code") login. When True the login page offers a
# code-based sign-in: enter email -> 6-digit code emailed -> enter code -> in.
SMALLSTACK_PASSWORDLESS_LOGIN = config("SMALLSTACK_PASSWORDLESS_LOGIN", default=False, cast=bool)
# Validity window for a passwordless sign-in code, in seconds (default 10 min).
SMALLSTACK_LOGIN_CODE_TTL = config("SMALLSTACK_LOGIN_CODE_TTL", default=600, cast=int)
# Most passwordless codes one account can be sent per hour (each allows 5 guesses).
SMALLSTACK_LOGIN_CODES_PER_HOUR = config("SMALLSTACK_LOGIN_CODES_PER_HOUR", default=5, cast=int)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
# Set to False to completely remove the sidebar and hamburger toggle
SMALLSTACK_SIDEBAR_ENABLED = config("SMALLSTACK_SIDEBAR_ENABLED", default=True, cast=bool)
# Set to False to start with sidebar closed by default (users can still toggle open)
SMALLSTACK_SIDEBAR_OPEN = config("SMALLSTACK_SIDEBAR_OPEN", default=True, cast=bool)
# Default sidebar state: "open", "closed", or "disabled"
# When set, this takes precedence over SMALLSTACK_SIDEBAR_OPEN.
# Can be overridden per-page via template block or view context.
SMALLSTACK_SIDEBAR_DEFAULT = config("SMALLSTACK_SIDEBAR_DEFAULT", default="open")

# ---------------------------------------------------------------------------
# Topbar Navigation
# ---------------------------------------------------------------------------
# Always show the unified topbar nav (from registry), even when sidebar is open.
# When False (default), topbar nav only appears when sidebar is closed/disabled.
SMALLSTACK_TOPBAR_NAV_ALWAYS = config("SMALLSTACK_TOPBAR_NAV_ALWAYS", default=True, cast=bool)

# Legacy topbar nav (DEPRECATED — use the nav registry instead)
# These settings are kept for backward compatibility and will be removed.
SMALLSTACK_TOPBAR_NAV_ENABLED = config("SMALLSTACK_TOPBAR_NAV_ENABLED", default=False, cast=bool)
SMALLSTACK_TOPBAR_NAV_ITEMS = []

# ---------------------------------------------------------------------------
# Activity Tracking
# ---------------------------------------------------------------------------
ACTIVITY_MAX_ROWS = config("ACTIVITY_MAX_ROWS", default=10000, cast=int)
ACTIVITY_EXCLUDE_PATHS = [
    "/static/",
    "/media/",
    "/favicon.ico",
    "/health/",
    "/heartbeat/ping/",
    "/status/",
    "/smallstack/status/",
    "/admin/jsi18n/",
    "/__debug__/",
    # The logger API reads the log table; without this, a client polling a tail
    # fills that table with its own poll traffic and a search for its own
    # request_id returns its own request. Same feedback shape the
    # DatabaseLogHandler's recursion guard breaks, one level up.
    "/api/logger/",
]

# ---------------------------------------------------------------------------
# Telemetry — database-backed log capture
# ---------------------------------------------------------------------------
# Log lines are written to the telemetry_logrecord table so they can be read
# back from inside the app. This is what makes a deployment debuggable when you
# can't reach the log stream — a locked-down container, a managed platform with
# no shell.
#
# Master switch. Off means the handler is never added to LOGGING, so there is
# no queue, no writer thread, and no rows.
TELEMETRY_LOG_CAPTURE_ENABLED = config("TELEMETRY_LOG_CAPTURE_ENABLED", default=True, cast=bool)

# Baseline level persisted to the database. WARNING keeps the table small and
# the write volume negligible; open a capture window when you need more:
#   manage.py log_capture start --level DEBUG --minutes 15
TELEMETRY_LOG_LEVEL = config("TELEMETRY_LOG_LEVEL", default="WARNING")

# Loggers whose level is lowered while a capture window is open. A record has
# to be created before any handler sees it, so lowering the handler alone would
# capture nothing new. Kept to application code: lowering `django` wholesale
# pulls in django.db.backends, which at DEBUG is one line per SQL query.
TELEMETRY_CAPTURE_LOGGERS = ["apps", "smallstack", "django.request"]

# Upper bound on how long a capture window may run, so an unattended DEBUG
# window can't quietly fill the disk.
TELEMETRY_MAX_CAPTURE_MINUTES = config("TELEMETRY_MAX_CAPTURE_MINUTES", default=120, cast=int)

# Retention — enforced by `manage.py prune_logs`, whichever binds first.
TELEMETRY_LOG_RETENTION_DAYS = config("TELEMETRY_LOG_RETENTION_DAYS", default=7, cast=int)
TELEMETRY_LOG_MAX_ROWS = config("TELEMETRY_LOG_MAX_ROWS", default=20000, cast=int)

# Buffer depth. Overflow drops records and counts the drops (visible in
# `manage.py log_capture status`) rather than blocking the request that logged.
TELEMETRY_LOG_QUEUE_SIZE = config("TELEMETRY_LOG_QUEUE_SIZE", default=1000, cast=int)

# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
BACKUP_DIR = config("BACKUP_DIR", default=str(BASE_DIR / "backups"))
BACKUP_RETENTION = config("BACKUP_RETENTION", default=10, cast=int)
BACKUP_CRON_ENABLED = config("BACKUP_CRON_ENABLED", default=True, cast=bool)
BACKUP_DOWNLOAD_ENABLED = config("BACKUP_DOWNLOAD_ENABLED", default=True, cast=bool)

# ---------------------------------------------------------------------------
# Heartbeat / Uptime Monitoring
# ---------------------------------------------------------------------------
HEARTBEAT_RETENTION_DAYS = config("HEARTBEAT_RETENTION_DAYS", default=7, cast=int)
HEARTBEAT_EXPECTED_INTERVAL = config("HEARTBEAT_EXPECTED_INTERVAL", default=60, cast=int)
# A monitor younger than this shows a "warming up" pill instead of a not-yet-
# representative uptime % on the status overview / public board.
HEARTBEAT_WARMUP_MINUTES = config("HEARTBEAT_WARMUP_MINUTES", default=60, cast=int)

# Master switch for the ANONYMOUS public status surface — the branded /status/
# board, /status/json/, and the public scheduled-maintenance pages. Set False to
# turn it off entirely (those routes return 404 and their links are hidden); the
# staff status tooling under /smallstack/status/ (overview, dashboard, SLA,
# per-monitor) is unaffected. Default on.
SMALLSTACK_PUBLIC_STATUS_ENABLED = config("SMALLSTACK_PUBLIC_STATUS_ENABLED", default=True, cast=bool)

# Public profile pages (/profile/<username>/). On: anyone can view them — which
# also lets an anonymous visitor probe whether a username exists (200 vs 404).
# Off: sign-in required. Default on (historical behaviour).
SMALLSTACK_PUBLIC_PROFILES = config("SMALLSTACK_PUBLIC_PROFILES", default=True, cast=bool)

# ---------------------------------------------------------------------------
# REST API surface
# ---------------------------------------------------------------------------
# Master switch for the whole HTTP API: the OpenAPI schema, Swagger UI / ReDoc,
# the API-auth + dashboard endpoints, and every per-CRUDView REST endpoint
# (``enable_api = True`` becomes a no-op when this is off). Set False to ship with
# no API published — the routes 404, the "API Health" nav + status monitor hide.
# Default on.
SMALLSTACK_API_ENABLED = config("SMALLSTACK_API_ENABLED", default=True, cast=bool)

# Master switch for the datasets surface: the /smallstack/datasets/ REST routes
# and the dataset MCP tools (list_datasets + query_dataset_<key>). Per-dataset
# ``enable_api`` / ``enable_mcp`` become no-ops when this is off. Default on.
SMALLSTACK_DATASETS_ENABLED = config("SMALLSTACK_DATASETS_ENABLED", default=True, cast=bool)
# Largest ?format=csv export (rows). Over it the endpoint returns 400 asking the
# caller to filter or page — the export is built in memory.
SMALLSTACK_DATASET_CSV_MAX_ROWS = config("SMALLSTACK_DATASET_CSV_MAX_ROWS", default=50_000, cast=int)

# ---------------------------------------------------------------------------
# Login Rate Limiting (django-axes)
# ---------------------------------------------------------------------------
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = 0.25  # 15 minutes lockout
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # Lock per username+IP combination
AXES_RESET_ON_SUCCESS = True  # Reset failure count after successful login

# Resolve the client IP the same way everywhere (activity log + axes lockout).
# The callable honors TRUST_PROXY_HEADERS: behind a trusted proxy it reads the
# real client from X-Forwarded-For, otherwise it uses REMOTE_ADDR. Deployments
# behind a proxy set TRUST_PROXY_HEADERS=true (production.py defaults it on for
# the blessed kamal-proxy path). See apps/smallstack/client_ip.py.
TRUST_PROXY_HEADERS = config("TRUST_PROXY_HEADERS", default=False, cast=bool)
AXES_CLIENT_IP_CALLABLE = "apps.smallstack.client_ip.get_client_ip"

# ---------------------------------------------------------------------------
# MCP — Model Context Protocol server for AI clients
# ---------------------------------------------------------------------------

# Master switch for the whole MCP surface: the /mcp JSON-RPC endpoint, OAuth +
# discovery routes, all tool registration (``enable_mcp = True`` becomes a no-op),
# and the MCP nav + dashboard widget + status monitor. Set False to ship without
# MCP — the endpoint 404s and nothing registers. Default on.
SMALLSTACK_MCP_ENABLED = config("SMALLSTACK_MCP_ENABLED", default=True, cast=bool)

# Server name advertised on `initialize` and the friendly GET banner.
MCP_SERVER_NAME = config("MCP_SERVER_NAME", default=BRAND_NAME.lower().replace(" ", "-"))

# Version string advertised on `initialize`. Defaults to the package version so
# MCP clients see the real release, not a hardcoded number.
MCP_SERVER_VERSION = config("MCP_SERVER_VERSION", default=SMALLSTACK_VERSION)

# Base template the OAuth consent page extends. Derived projects with a
# different theme override this in their own smallstack.py.
MCP_BASE_TEMPLATE = config("MCP_BASE_TEMPLATE", default="website/base.html")

# Prefix for APITokens auto-minted by the OAuth flow. Final token name is
# f"{MCP_TOKEN_NAME_PREFIX} — {client_id}".
MCP_TOKEN_NAME_PREFIX = config("MCP_TOKEN_NAME_PREFIX", default="MCP")

# Protocol versions we know how to speak. The dispatcher echoes back the
# client's version if it's in this list; otherwise falls back to the first
# entry. Hardcoding a single version makes Claude.ai silently disconnect
# when its negotiated version isn't matched.
MCP_SUPPORTED_PROTOCOL_VERSIONS = [
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
]

# How long an OAuth authorization code is valid (seconds).
MCP_OAUTH_CODE_TTL_SECONDS = config("MCP_OAUTH_CODE_TTL_SECONDS", default=600, cast=int)

# Disable to ship without OAuth (only direct bearer-token MCP calls).
# Useful for internal-only servers behind a VPN.
MCP_ENABLE_OAUTH = config("MCP_ENABLE_OAUTH", default=True, cast=bool)

# When True, the dispatch logger emits DEBUG body previews (truncated to
# 1 KB each direction). Defaults to False so production stays quiet.
MCP_VERBOSE_LOGGING = config("MCP_VERBOSE_LOGGING", default=False, cast=bool)

# Tool modules imported at app-ready time. Each module's @tool calls
# self-register against the singleton server. Derived projects add their
# own curated cross-cutting tools here.
MCP_TOOL_MODULES: list[str] = []  # e.g. ["apps.mcp_tools.summary"]

# Auto-import every app's views.py + mcp_tools.py at startup so CRUDViews
# defined there register before the factory walks the registry. Mirrors
# Django's admin.autodiscover pattern. Disable if your project hits
# circular imports — but then every app with enable_mcp=True must
# explicitly `from . import views` in its AppConfig.ready().
MCP_AUTODISCOVER = config("MCP_AUTODISCOVER", default=True, cast=bool)


# ---------------------------------------------------------------------------
# Runbook (apps.runbook) — versioned markdown documents
# ---------------------------------------------------------------------------
# The base template every runbook page extends. In SmallStack this is the
# themed shell so runbook pages match the rest of the admin UI.
RUNBOOK_BASE_TEMPLATE = config("RUNBOOK_BASE_TEMPLATE", default="smallstack/base.html")
# Restrict the runbook UI to staff users (True) or allow any signed-in user.
RUNBOOK_STAFF_REQUIRED = config("RUNBOOK_STAFF_REQUIRED", default=True, cast=bool)
# MEDIA_ROOT subtrees the public /media/ route refuses (404). Runbook files are
# served only through access-checked views; list any of your own gated upload
# dirs here too. Profile photos stay public. (See apps/smallstack/media.py.)
SMALLSTACK_PRIVATE_MEDIA_PREFIXES = config(
    "SMALLSTACK_PRIVATE_MEDIA_PREFIXES",
    default="runbook/",
    cast=lambda v: [p.strip() for p in v.split(",") if p.strip()],
)
# Other RUNBOOK_* knobs (version/retention caps) default sensibly in
# apps/runbook/conf.py — override here only if needed.


# ---------------------------------------------------------------------------
# Scheduler (apps.scheduler) — DB-backed recurring jobs over django.tasks
# ---------------------------------------------------------------------------
# Master switch for the scheduler surface: @scheduled autodiscovery/sync, the
# tick, and the nav item + dashboard widget + status monitor. Off ⇒ nothing
# registers and the tick is a no-op. Harmless with zero jobs, so default on.
SMALLSTACK_SCHEDULER_ENABLED = config("SMALLSTACK_SCHEDULER_ENABLED", default=True, cast=bool)

# A previous run still marked unfinished after this many seconds is treated as
# abandoned by the overlap guard, so a dead worker can never permanently wedge
# an allow_overlap=False schedule. Default 24h.
SMALLSTACK_SCHEDULER_STALE_RUN_SECONDS = config("SMALLSTACK_SCHEDULER_STALE_RUN_SECONDS", default=86_400, cast=int)

# An enabled job overdue by more than this trips the scheduler status monitor
# (a proxy for "the tick isn't firing"). Default 5 min.
SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS = config("SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS", default=300, cast=int)

# Minimum runs in the last hour before the status monitor's failure-rate check
# applies — so a single failed run in a quiet hour (1/1) can't trip it DOWN.
SMALLSTACK_SCHEDULER_FAILURE_MIN_SAMPLE = config("SMALLSTACK_SCHEDULER_FAILURE_MIN_SAMPLE", default=5, cast=int)

# Recipients emailed when a scheduled run fails (via send_email_task). Empty ⇒
# no failure emails. Comma-separated in env, e.g. "ops@x.com,oncall@x.com".
SMALLSTACK_SCHEDULER_FAILURE_EMAILS = config(
    "SMALLSTACK_SCHEDULER_FAILURE_EMAILS",
    default="",
    cast=lambda v: [a.strip() for a in v.split(",") if a.strip()],
)

# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
# Master switch for the webhooks surface: the outbound change-signal receiver,
# the delivery/retry tick, inbound receiver endpoints, and the nav item +
# dashboard widget + status monitor. Off ⇒ nothing registers, no model change
# fans out, and /webhooks/in/<slug>/ 404s. Harmless with zero endpoints, so on.
SMALLSTACK_WEBHOOKS_ENABLED = config("SMALLSTACK_WEBHOOKS_ENABLED", default=True, cast=bool)

# Feeds: publish CRUDViews as RSS/Atom (enable_rss) and consume external feeds
# into a model (the collector). Off ⇒ /feed/ 404s and the collector no-ops.
SMALLSTACK_FEEDS_ENABLED = config("SMALLSTACK_FEEDS_ENABLED", default=True, cast=bool)

# Independent toggles for each direction (both gated by the master switch above).
SMALLSTACK_WEBHOOKS_OUTBOUND = config("SMALLSTACK_WEBHOOKS_OUTBOUND", default=True, cast=bool)
SMALLSTACK_WEBHOOKS_INBOUND = config("SMALLSTACK_WEBHOOKS_INBOUND", default=True, cast=bool)

# Delivery attempt ceiling before a WebhookDelivery is marked "dead". Includes
# the first attempt, so 5 ⇒ 1 initial + 4 retries.
SMALLSTACK_WEBHOOK_MAX_ATTEMPTS = config("SMALLSTACK_WEBHOOK_MAX_ATTEMPTS", default=5, cast=int)

# Per-request HTTP timeout (seconds) when POSTing an outbound webhook.
SMALLSTACK_WEBHOOK_TIMEOUT = config("SMALLSTACK_WEBHOOK_TIMEOUT", default=10, cast=int)

# Consecutive delivery failures before an endpoint auto-disables itself (a proxy
# for "this URL is dead"). 0 ⇒ never auto-disable.
SMALLSTACK_WEBHOOK_AUTO_DISABLE_AFTER = config("SMALLSTACK_WEBHOOK_AUTO_DISABLE_AFTER", default=20, cast=int)

# Backoff schedule (seconds) applied per retry attempt. Index = (attempt - 1),
# clamped to the last entry. Comma-separated in env.
SMALLSTACK_WEBHOOK_BACKOFF = config(
    "SMALLSTACK_WEBHOOK_BACKOFF",
    default="60,300,1800,7200,21600",
    cast=lambda v: [int(x) for x in v.split(",") if x.strip()],
)

# Ceiling (seconds) for any single retry wait — clamps a hostile/absurd Retry-After
# header on a 429/503 so a rate-limiter can't push a delivery weeks out.
SMALLSTACK_WEBHOOK_MAX_BACKOFF = config("SMALLSTACK_WEBHOOK_MAX_BACKOFF", default=21600, cast=int)

# This deployment's webhook origin — stamped on every outbound delivery as
# X-SmallStack-Origin so a paired SmallStack can drop self-originated events.
# Blank ⇒ derived from SITE_URL / the hostname at send time.
SMALLSTACK_WEBHOOK_ORIGIN = config("SMALLSTACK_WEBHOOK_ORIGIN", default="")

# SSRF guard. When non-empty, an outbound target URL's host must match one of
# these suffixes (e.g. "example.com,hooks.internal"). Empty ⇒ allow any public
# host; loopback/private ranges are still rejected unless SMALLSTACK_WEBHOOK_
# ALLOW_PRIVATE is on (dev/testing against a local receiver).
SMALLSTACK_WEBHOOK_ALLOWLIST = config(
    "SMALLSTACK_WEBHOOK_ALLOWLIST",
    default="",
    cast=lambda v: [a.strip().lower() for a in v.split(",") if a.strip()],
)
SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = config("SMALLSTACK_WEBHOOK_ALLOW_PRIVATE", default=False, cast=bool)

# Inbound receiver hardening (the /webhooks/in/<slug>/ route is public).
# Bodies above this are refused with 413 before anything is stored.
SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES = config("SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES", default=1_048_576, cast=int)
# Signature-rejected requests recorded per receiver per minute; beyond this the
# 401 is still returned but no receipt row is written.
SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE = config("SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE", default=30, cast=int)
# Receipts older than this are deleted by `manage.py prune_webhook_receipts`.
SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS = config("SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS", default=30, cast=int)

# Recipients emailed when a delivery exhausts its retries (via send_email_task).
# Empty ⇒ no emails. Comma-separated in env.
SMALLSTACK_WEBHOOK_FAILURE_EMAILS = config(
    "SMALLSTACK_WEBHOOK_FAILURE_EMAILS",
    default="",
    cast=lambda v: [a.strip() for a in v.split(",") if a.strip()],
)

# ---------------------------------------------------------------------------
# Notifications — the in-app bell/inbox primitive (apps/notifications)
# ---------------------------------------------------------------------------
# Master switch. Off ⇒ notify() no-ops, the bell and inbox routes vanish, and
# producers (e.g. approvals) silently skip the in-app channel.
SMALLSTACK_NOTIFICATIONS_ENABLED = config("SMALLSTACK_NOTIFICATIONS_ENABLED", default=True, cast=bool)
# Rows older than this are pruned by the daily sweep. 0 = keep forever.
SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS = config(
    "SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS", default=90, cast=int
)

# ---------------------------------------------------------------------------
# Approvals — the side-car human-approval gate (apps/approvals)
# ---------------------------------------------------------------------------
# Master switch. Off ⇒ the URLs are never mounted (console, REST, decide POST),
# no kind autodiscovery, no receivers, no nav/dashboard/monitor, no sweep job,
# and services.request_approval/decide/cancel raise ApprovalsDisabled. It used
# to leave every endpoint live and only kill the fan-out. (F-11.)
SMALLSTACK_APPROVALS_ENABLED = config("SMALLSTACK_APPROVALS_ENABLED", default=True, cast=bool)
# May the requester decide their own request? Off by default — a human gate
# you can wave yourself through isn't a gate.
SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE = config(
    "SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE", default=False, cast=bool
)
# When a request names assignees, may staff still decide it? On by default —
# is_staff is the trust anchor and an assignee-only request must not wedge
# permanently. Flip off for hard assignee exclusivity (four-eyes policies).
SMALLSTACK_APPROVALS_STAFF_OVERRIDE = config(
    "SMALLSTACK_APPROVALS_STAFF_OVERRIDE", default=True, cast=bool
)
# Fallback TTL in minutes when neither the request nor its kind sets one.
# 0 = requests never expire by default.
SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES = config(
    "SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES", default=0, cast=int
)
# Email channel (in-app notifications + webhooks are independent of this).
SMALLSTACK_APPROVALS_EMAILS_ENABLED = config(
    "SMALLSTACK_APPROVALS_EMAILS_ENABLED", default=True, cast=bool
)
# Extra recipients (comma-separated) copied on every request + decision.
SMALLSTACK_APPROVALS_NOTIFY_EMAILS = config(
    "SMALLSTACK_APPROVALS_NOTIFY_EMAILS",
    default="",
    cast=lambda v: [e.strip() for e in str(v).split(",") if e.strip()],
)
# Send approval mail in the request path instead of queueing it on the `email`
# task queue. Defaults to DEBUG: a `make run` demo or a test run delivers with no
# worker, while production keeps the queue (and then NEEDS a db_worker on the
# `email` queue — the approvals status monitor trips if nothing drains it). (F-07.)
# Unset (the default) means "follow DEBUG", resolved at call time in
# apps/approvals/receivers.py — DEBUG isn't defined yet in this module.
_approvals_inline = config("SMALLSTACK_APPROVALS_EMAILS_INLINE", default="")
SMALLSTACK_APPROVALS_EMAILS_INLINE = (
    None
    if str(_approvals_inline) == ""
    else str(_approvals_inline).strip().lower() in {"1", "true", "yes", "on"}
)
# How long a queued approval email may sit unrun before the status monitor
# reports the email channel as down.
SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES = config(
    "SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES", default=15, cast=int
)
# The @scheduled 5-minute expiry sweep (lazy expiry still applies without it).
SMALLSTACK_APPROVALS_SWEEP_ENABLED = config(
    "SMALLSTACK_APPROVALS_SWEEP_ENABLED", default=True, cast=bool
)
# How many overdue rows one interactive page-load may expire itself. Expiring a
# row runs the kind callback + audit + signal + notification + email + webhook,
# so an unbounded backlog made the queue page the slowest in the app. The
# scheduled sweep drains the remainder and a warning is logged when it's behind.
SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT = config(
    "SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT", default=25, cast=int
)
# Cap on a single requester's outstanding pending requests per kind (0 = no cap).
# The abuse model is an agent token in a loop: one identity filed 60 requests and
# generated 600 notification rows unimpeded, which defeats the gate by alert
# fatigue. Exceeding it raises TooManyPending → 429 on REST/MCP. (F-18.)
SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER = config(
    "SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER", default=50, cast=int
)

# ---------------------------------------------------------------------------
# Audit — attribution for writes no human caused
# ---------------------------------------------------------------------------
# django.contrib.admin's LogEntry.user is non-null, so a system transition (an
# expiry sweep, a scheduled job) previously left NO audit row at all. Writes with
# no actor are attributed to this reserved account, created on first use as
# is_active=False with an unusable password — a label, not a credential (nothing
# can authenticate as an inactive user on any surface). Blank ⇒ system writes are
# logged to the application log only. (F-15.)
SMALLSTACK_AUDIT_SYSTEM_USERNAME = config("SMALLSTACK_AUDIT_SYSTEM_USERNAME", default="system")
