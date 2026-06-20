"""
SmallStack application settings.

All user-customizable SmallStack settings live here. Override any value
via environment variable (python-decouple) or by editing the defaults below.

Infrastructure settings (INSTALLED_APPS, MIDDLEWARE, DATABASES, etc.)
remain in base.py.
"""

from pathlib import Path

from decouple import config

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
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

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
]

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

# ---------------------------------------------------------------------------
# Login Rate Limiting (django-axes)
# ---------------------------------------------------------------------------
AXES_FAILURE_LIMIT = config("AXES_FAILURE_LIMIT", default=5, cast=int)
AXES_COOLOFF_TIME = 0.25  # 15 minutes lockout
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # Lock per username+IP combination
AXES_RESET_ON_SUCCESS = True  # Reset failure count after successful login

# ---------------------------------------------------------------------------
# MCP — Model Context Protocol server for AI clients
# ---------------------------------------------------------------------------

# Server name advertised on `initialize` and the friendly GET banner.
MCP_SERVER_NAME = config("MCP_SERVER_NAME", default=BRAND_NAME.lower().replace(" ", "-"))

# Version string advertised on `initialize`.
MCP_SERVER_VERSION = config("MCP_SERVER_VERSION", default="1.0.0")

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
