"""Build Django 6.1's ``MAILERS`` setting from the conventional ``EMAIL_*`` env.

Django 6.1 consolidated email config into a single ``MAILERS`` dict (like
``DATABASES``/``CACHES``/``STORAGES``) and deprecated the flat ``EMAIL_BACKEND``
/ ``EMAIL_HOST`` / … *settings* (removed in Django 7.0). We keep reading the
same ``EMAIL_*`` **environment variables** deployments already set — those are
env vars, not the deprecated Django settings, so no warning — and assemble
``MAILERS`` from them.

``OPTIONS`` is backend-aware: only the SMTP backend receives connection options,
so the console/file backends never get kwargs they don't understand (Django 6.1
warns on unknown backend kwargs). ``DEFAULT_FROM_EMAIL`` / ``SERVER_EMAIL`` are
unaffected — they were not deprecated.
"""

from __future__ import annotations

from typing import Any

from decouple import config

CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
FILE_BACKEND = "django.core.mail.backends.filebased.EmailBackend"


def build_mailers(default_backend: str = CONSOLE_BACKEND) -> dict[str, dict[str, Any]]:
    """Return a single-``default`` ``MAILERS`` dict from ``EMAIL_*`` env vars.

    ``EMAIL_BACKEND`` (env) selects the backend; ``default_backend`` is the
    fallback (console for dev, smtp for production). ``send_mail()`` and friends
    use ``MAILERS["default"]`` automatically when no ``using=`` is given.
    """
    backend = config("EMAIL_BACKEND", default=default_backend)
    options: dict[str, Any] = {}

    if backend.endswith("smtp.EmailBackend"):
        options = {
            "host": config("EMAIL_HOST", default="localhost"),
            "port": config("EMAIL_PORT", default=25, cast=int),
            "username": config("EMAIL_HOST_USER", default=""),
            "password": config("EMAIL_HOST_PASSWORD", default=""),
            "use_tls": config("EMAIL_USE_TLS", default=False, cast=bool),
            "use_ssl": config("EMAIL_USE_SSL", default=False, cast=bool),
        }
        # Seconds before a stalled SMTP connect/read gives up. Without one the
        # socket waits forever: a hung mail server held a web thread until
        # gunicorn killed the worker, and held the task worker (which serves
        # every queue) indefinitely. 0 restores "no timeout".
        # An empty value (`EMAIL_TIMEOUT=`) is the default, as it was before this
        # became an int; int("") would stop the app from booting.
        timeout = config("EMAIL_TIMEOUT", default="10", cast=lambda v: int(v) if str(v).strip() else 10)
        if timeout > 0:
            options["timeout"] = timeout
    elif backend.endswith("filebased.EmailBackend"):
        options = {"file_path": config("EMAIL_FILE_PATH", default="")}

    return {"default": {"BACKEND": backend, "OPTIONS": options}}
