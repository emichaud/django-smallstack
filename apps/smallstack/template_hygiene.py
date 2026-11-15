"""Template scanners for the inline-code rules the CSP enforces.

SmallStack's ``script-src`` is ``'self'`` with no ``'unsafe-inline'``, so the
browser refuses an inline ``<script>`` block or an ``on…=`` handler in any
template. These scanners find them. ``test_template_hygiene.py`` asserts on
them and ``manage.py template_hygiene`` lists them, so a project moving onto
the policy can see how much work it has.

Scope follows the policy actually in force:

* While ``script-src`` has no ``'unsafe-inline'``, an inline script anywhere is
  dead code, so every template in the project is checked, the project's own
  included.
* With the documented stopgap (``'unsafe-inline'`` added back), a project's own
  inline scripts run, so only the framework's templates are held to the rule.
* Inline ``<style>`` is allowed by ``style-src``. Keeping page CSS in static/
  is a framework convention, so only the framework's templates are checked.

When ``script-src`` carries ``csp.constants.NONCE``, an inline ``<script>``
with a ``nonce=`` attribute runs, so it isn't counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

#: Repo root: apps/smallstack/template_hygiene.py → ../../
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_SKIP_DIRS = {".git", ".venv", "node_modules", "staticfiles", "htmlcov", "site-packages", "__pycache__"}

#: The framework's own apps: everything under apps/ but ``website``, which is the
#: project's to edit. ``showcase`` is SmallStack's demo pages, which a project may
#: delete, but while it's there its templates are SmallStack's. A new app goes here.
FRAMEWORK_APPS = (
    "access",
    "accounts",
    "activity",
    "api",
    "approvals",
    "blog",
    "calendar",
    "dashboards",
    "datasets",
    "explorer",
    "feeds",
    "heartbeat",
    "help",
    "mcp",
    "notifications",
    "profile",
    "runbook",
    "scheduler",
    "search",
    "showcase",
    "smallstack",
    "tasks",
    "telemetry",
    "tokenmgr",
    "usermanager",
    "webhooks",
)

#: Framework templates under the root templates/ directory. templates/website/ is the
#: project's own, and so is any error page there (the defaults are in apps/smallstack).
FRAMEWORK_ROOT_TEMPLATES = ("email", "legal")

#: Inline <style> blocks kept on purpose: the 500 page must render when static files
#: can't be served, and the Swagger page's three lines need the brand logo's URL
#: (that page carries its own CSP for the Swagger UI bundle).
INLINE_STYLE_ALLOWED = {"apps/smallstack/templates/500.html", "apps/smallstack/templates/smallstack/api/swagger.html"}

_NON_EXECUTABLE_TYPES = ("application/json", "application/ld+json", "text/template", "importmap")
_INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*=\s*["']""")
_SCRIPT_BLOCK = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S)
_COMMENT_BLOCK = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)


@dataclass(frozen=True)
class Offender:
    path: str  # relative to the repo root
    line: int
    snippet: str = ""

    def __str__(self) -> str:
        return f"{self.path}:{self.line}" + (f" — {self.snippet}" if self.snippet else "")


def project_templates() -> list[Path]:
    """Every .html file in the project, framework and project-owned alike."""
    return [p for p in REPO_ROOT.rglob("*.html") if not (_SKIP_DIRS & set(p.parts))]


def is_framework_template(path: Path) -> bool:
    parts = path.relative_to(REPO_ROOT).parts
    if len(parts) > 2 and parts[0] == "apps":
        return parts[1] in FRAMEWORK_APPS
    return len(parts) > 1 and parts[0] == "templates" and parts[1] in FRAMEWORK_ROOT_TEMPLATES


def framework_templates() -> list[Path]:
    return [p for p in project_templates() if is_framework_template(p)]


def inline_script_allowed() -> bool:
    """True when the site's ``script-src`` lets inline scripts run (the stopgap)."""
    csp = getattr(settings, "CONTENT_SECURITY_POLICY", None) or {}
    return "'unsafe-inline'" in csp.get("DIRECTIVES", {}).get("script-src", [])


def nonce_allowed() -> bool:
    """True when ``script-src`` carries django-csp's per-request nonce."""
    from csp.constants import NONCE

    csp = getattr(settings, "CONTENT_SECURITY_POLICY", None) or {}
    return NONCE in csp.get("DIRECTIVES", {}).get("script-src", [])


def script_templates() -> list[Path]:
    """The templates the inline-script rules apply to under the policy in force."""
    return framework_templates() if inline_script_allowed() else project_templates()


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _line(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def inline_scripts(paths: list[Path]) -> list[Offender]:
    found = []
    nonce = nonce_allowed()
    for path in paths:
        text = path.read_text(errors="replace")
        for match in _SCRIPT_BLOCK.finditer(text):
            attrs, body = match.group(1), match.group(2)
            if "src=" in attrs or (nonce and "nonce=" in attrs) or any(t in attrs for t in _NON_EXECUTABLE_TYPES):
                continue
            if body.strip():
                found.append(Offender(_rel(path), _line(text, match.start())))
    return found


def inline_handlers(paths: list[Path]) -> list[Offender]:
    found = []
    for path in paths:
        text = path.read_text(errors="replace")
        for match in _INLINE_HANDLER.finditer(text):
            snippet = text[match.start() : match.start() + 60].strip().splitlines()[0]
            found.append(Offender(_rel(path), _line(text, match.start()), snippet))
    return found


def inline_styles(paths: list[Path]) -> list[Offender]:
    found = []
    for path in paths:
        rel = _rel(path)
        # Django templates only (a standalone .html document elsewhere in the repo is its own page)
        if "templates" not in path.parts or rel in INLINE_STYLE_ALLOWED:
            continue
        text = path.read_text(errors="replace")
        comments = [(c.start(), c.end()) for c in _COMMENT_BLOCK.finditer(text)]
        for match in re.finditer(r"<style\b[^>]*>", text):
            if not any(a <= match.start() < b for a, b in comments):
                found.append(Offender(rel, _line(text, match.start())))
    return found
