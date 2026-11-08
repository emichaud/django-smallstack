"""Apply the dashboard defaults apps ship (``dashboard_defaults.py``), or show
what applying them would do.

    uv run python manage.py dashboard_defaults               # every app (also runs after migrate)
    uv run python manage.py dashboard_defaults --dry-run     # what it would do
    uv run python manage.py dashboard_defaults --app support # one app (also one registered with auto=False)
    uv run python manage.py dashboard_defaults --app support --restore   # bring back deleted ones too
    uv run python manage.py dashboard_defaults --app support --adopt     # take over same-named rows made here

A default someone changed is never overwritten here: the run says a newer one is
available, and **Reset to default** on its page applies it.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...defaults import registered_defaults, sync_defaults

#: How each outcome reads, in the order the summary lists them.
WORDS = {
    "created": "created",
    "updated": "updated to the app's new definition",
    "restored": "back from parking (its app returned)",
    "current": "already current",
    "customised": "changed by someone (kept)",
    "removed": "deleted by someone (left deleted)",
    "parked": "archived: its app is turned off",
    "adopted": "taken over: the existing row now matches the default",
    "conflict": "not created: the name is taken (--adopt takes it over)",
    "error": "not applied",
}


class Command(BaseCommand):
    help = "Apply the dashboard defaults apps ship, or show what that would do (--dry-run)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--app", action="append", default=None, help="Only this app's defaults (repeatable).")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
        parser.add_argument(
            "--restore", action="store_true", help="Also bring back defaults someone deleted (with --app)."
        )
        parser.add_argument(
            "--adopt",
            action="store_true",
            help="Take over rows made here that have a default's name, and make them match it (with --app).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apps = options["app"]
        if (options["restore"] or options["adopt"]) and not apps:
            raise CommandError("--restore and --adopt need --app: say whose defaults.")
        unknown = [a for a in apps or [] if a not in registered_defaults()]
        if unknown:
            raise CommandError(f"No defaults registered for: {', '.join(unknown)}")
        report = sync_defaults(apps, dry_run=options["dry_run"], restore=options["restore"], adopt=options["adopt"])
        if not report.lines:
            opt_in = sorted(app for app, bundle in registered_defaults().items() if not bundle.auto)
            if opt_in:
                self.stdout.write(f"Nothing to apply automatically. Opt-in defaults (--app): {', '.join(opt_in)}.")
            else:
                self.stdout.write("No app ships dashboard defaults.")
            return
        for app, kind, key, outcome, detail in report.lines:
            if outcome == "current":
                continue
            style = self.style.ERROR if outcome in ("error", "conflict") else self.style.SUCCESS
            text = f"{app} {kind} {key}: {WORDS.get(outcome, outcome)}"
            self.stdout.write(style(text) + (f" — {detail}" if detail else ""))
        summary = ", ".join(f"{report.count(o)} {w}" for o, w in WORDS.items() if report.count(o))
        prefix = "Would be: " if options["dry_run"] else ""
        self.stdout.write(prefix + summary + ".")
