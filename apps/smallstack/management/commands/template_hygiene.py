"""List the inline scripts, event handlers and style blocks in the project's templates.

Usage:
    uv run python manage.py template_hygiene              # every offender, by file
    uv run python manage.py template_hygiene --summary    # counts per file
    uv run python manage.py template_hygiene --framework  # the framework's templates only
    uv run python manage.py template_hygiene --check      # exit 1 if a script or handler is found

The CSP's ``script-src`` has no ``'unsafe-inline'``, so the browser refuses an
inline ``<script>`` block or ``on…=`` handler. Run this to size the move to
static files, or to see what the ``'unsafe-inline'`` stopgap is still covering.
The rules and their scope are in ``apps/smallstack/template_hygiene.py``; the
recipe for moving each kind is in ``docs/skills/templates.md``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.smallstack import template_hygiene as hygiene


class Command(BaseCommand):
    help = "List inline <script> blocks, on…= handlers and <style> blocks in templates"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--framework", action="store_true", help="Only the framework's own templates")
        parser.add_argument("--summary", action="store_true", help="Counts per file instead of every line")
        parser.add_argument("--check", action="store_true", help="Exit 1 if any inline script or handler is found")

    def handle(self, *args: Any, **options: Any) -> None:
        paths = hygiene.framework_templates() if options["framework"] else hygiene.project_templates()
        kinds = {
            "inline <script>": hygiene.inline_scripts(paths),
            "on…= handler": hygiene.inline_handlers(paths),
            # Not blocked (style-src allows inline); listed so they can move with the rest.
            "inline <style>": hygiene.inline_styles(paths),
        }
        for kind, offenders in kinds.items():
            if not offenders:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"{kind} ({len(offenders)})"))
            if options["summary"]:
                for path, n in sorted(Counter(o.path for o in offenders).items()):
                    self.stdout.write(f"  {n:4d}  {path}")
            else:
                for offender in offenders:
                    self.stdout.write(f"  {offender}")

        scripts = len(kinds["inline <script>"]) + len(kinds["on…= handler"])
        files = len({o.path for o in kinds["inline <script>"] + kinds["on…= handler"]})
        policy = (
            "script-src allows 'unsafe-inline' (the stopgap): these run today"
            if hygiene.inline_script_allowed()
            else "script-src has no 'unsafe-inline': the browser blocks these"
        )
        self.stdout.write(
            f"\n{scripts} inline scripts and handlers in {files} files, "
            f"{len(kinds['inline <style>'])} style blocks; {policy}."
        )
        if options["check"] and scripts:
            raise CommandError(f"{scripts} inline scripts and handlers — see docs/skills/templates.md")
