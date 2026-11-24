"""System checks for SmallStack's own release metadata.

Currently one: the version SmallStack advertises is derived from the *installed
distribution*, not from `pyproject.toml`. That is a build artifact, so it can
silently lag the source of truth — and every surface that reports a version
(`SMALLSTACK_VERSION`, `MCP_SERVER_VERSION`, OpenAPI `info.version`) reads from
the same chain, so all of them can agree with each other while all of them are
wrong. Four witnesses, one source.

The failure is silent by construction: nothing errors, the app serves a
plausible number, and a downstream consumer making a compatibility decision from
`info.version` gets a confident wrong answer. Same shape as the three checks in
`apps/tasks/checks.py` — convert a silent drift into a loud one.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.core.checks import register

DISTRIBUTION = "django-smallstack"


def _pyproject_version() -> str | None:
    """The source-of-truth version, or ``None`` if pyproject.toml isn't readable."""
    try:
        path = Path(settings.BASE_DIR) / "pyproject.toml"
        return str(tomllib.loads(path.read_text())["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError, TypeError, AttributeError):
        return None


@register()
def check_reported_version_is_not_stale(app_configs: Any, **kwargs: Any) -> list[CheckWarning]:
    """Warn when the installed distribution's version has drifted from pyproject.

    Skipped in three cases, each of which makes the comparison meaningless
    rather than clean:

    * the distribution isn't installed — settings then read ``pyproject.toml``
      directly, so no drift is possible;
    * ``pyproject.toml`` isn't readable (a wheel-only deploy) — there is nothing
      to compare against, and asserting drift from an absent file would be a
      guess;
    * ``SMALLSTACK_VERSION`` is explicitly overridden — the reported version is
      then deliberately decoupled from the package, so a stale install is not
      what anyone is serving. Not warning about a deliberate opt-out is the same
      rule as ``tasks.W001``.
    """
    try:
        installed = installed_version(DISTRIBUTION)
    except PackageNotFoundError:
        return []
    declared = _pyproject_version()
    if declared is None or declared == installed:
        return []
    # Its default *is* the installed version, so a difference means an override.
    if getattr(settings, "SMALLSTACK_VERSION", installed) != installed:
        return []
    return [
        CheckWarning(
            f"SmallStack reports version {installed!r}, but pyproject.toml declares {declared!r}. "
            "The installed distribution is stale, so every version surface is reporting the old "
            "number.",
            hint=(
                "Reinstall the package so the metadata catches up — `make setup`, or "
                "`uv sync --extra dev` (a bare `uv sync` installs it but prunes the dev extras, "
                "taking pytest/ruff/mypy with them). This normally means a version bump was "
                "committed without reinstalling: "
                "SMALLSTACK_VERSION, MCP_SERVER_VERSION and the OpenAPI info.version all derive "
                "from the installed distribution, so they will agree with each other and still be "
                "wrong. Set SMALLSTACK_VERSION explicitly if you version your API contract "
                "independently of the package."
            ),
            id="smallstack.W001",
        )
    ]


@register()
def check_api_session_csrf_switch(app_configs: Any, **kwargs: Any) -> list[CheckWarning]:
    """``SMALLSTACK_API_SESSION_CSRF=False`` is a one-release escape hatch."""
    if getattr(settings, "SMALLSTACK_API_SESSION_CSRF", True):
        return []
    return [
        CheckWarning(
            "SMALLSTACK_API_SESSION_CSRF is False: REST API writes on a browser session are accepted without "
            "a CSRF token, so another page can make a signed-in browser write.",
            hint=(
                "Temporary, for the release that introduced the check. Find the callers in the log "
                "(\"allowed because SMALLSTACK_API_SESSION_CSRF=False\"), make them send X-CSRFToken (the "
                "csrftoken cookie) or use an API token, then remove the setting. It is removed in 0.34.0."
            ),
            id="smallstack.W002",
        )
    ]
