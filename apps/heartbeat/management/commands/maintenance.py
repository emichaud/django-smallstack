"""Manage maintenance windows from the CLI.

A maintenance window marks planned downtime so the status page shows "Under
maintenance" (not "Down") and the SLA calculation excludes the span. The most
common use is wrapping a deploy: open a bounded window before the container
swap, close it once the new container is healthy.

Examples::

    # Open a 15-minute window starting now (typical for a deploy)
    python manage.py maintenance open --minutes 15 --title "Deploy v1.2.3"

    # Open a window with explicit bounds
    python manage.py maintenance open --start "2026-07-01 02:00" --end "2026-07-01 03:00" \\
        --title "DB migration"

    # End any active window now
    python manage.py maintenance close

    # Inspect what's scheduled
    python manage.py maintenance list
    python manage.py maintenance list --active --json
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime
from django.utils.timezone import localtime

from apps.heartbeat import maintenance


class Command(BaseCommand):
    help = "Open, close, or list maintenance windows (planned downtime, SLA-excluded)."

    def add_arguments(self, parser):
        parser.add_argument(
            "subcommand",
            choices=["open", "close", "list"],
            help="open a window, close active windows, or list windows.",
        )
        parser.add_argument("--monitor", default="site", help="Monitor key the window applies to (default: site).")
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

        # open
        parser.add_argument("--minutes", type=int, help="open: duration in minutes, starting now.")
        parser.add_argument("--start", help="open: ISO start (e.g. '2026-07-01 02:00'). Use with --end.")
        parser.add_argument("--end", help="open: ISO end. Use with --start.")
        parser.add_argument("--title", default="Maintenance", help="open: window title.")
        parser.add_argument("--note", default="", help="open: optional note.")
        parser.add_argument(
            "--no-sla-exclude",
            action="store_true",
            help="open: record the window WITHOUT excluding it from SLA (informational only).",
        )

        # close
        parser.add_argument(
            "--delete-future",
            action="store_true",
            help="close: also delete windows that haven't started yet.",
        )

        # list
        parser.add_argument("--active", action="store_true", help="list: only windows active right now.")

    def handle(self, *args, **options):
        sub = options["subcommand"]
        if sub == "open":
            self._open(options)
        elif sub == "close":
            self._close(options)
        else:
            self._list(options)

    # -- subcommands -------------------------------------------------------

    def _open(self, options):
        monitor = options["monitor"]
        minutes = options["minutes"]
        start_raw, end_raw = options["start"], options["end"]
        exclude = not options["no_sla_exclude"]

        if minutes is not None and (start_raw or end_raw):
            raise CommandError("Use either --minutes OR --start/--end, not both.")

        try:
            if minutes is not None:
                window = maintenance.open_window_for(
                    minutes,
                    options["title"],
                    monitor_key=monitor,
                    note=options["note"],
                    exclude_from_sla=exclude,
                )
            elif start_raw and end_raw:
                start = _parse(start_raw, "--start")
                end = _parse(end_raw, "--end")
                window = maintenance.open_window(
                    options["title"],
                    start,
                    end,
                    monitor_key=monitor,
                    note=options["note"],
                    exclude_from_sla=exclude,
                )
            else:
                raise CommandError("open requires --minutes, or both --start and --end.")
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if options["json"]:
            self.stdout.write(json.dumps(_window_dict(window)))
            return

        self.stdout.write(self.style.SUCCESS(f"Opened maintenance window #{window.pk} for '{monitor}':"))
        self.stdout.write(f"  {window.title}")
        self.stdout.write(f"  {localtime(window.start):%Y-%m-%d %H:%M} → {localtime(window.end):%Y-%m-%d %H:%M}")
        if not exclude:
            self.stdout.write(self.style.WARNING("  Not excluded from SLA (informational only)."))

    def _close(self, options):
        result = maintenance.close_windows(
            monitor_key=options["monitor"],
            delete_future=options["delete_future"],
        )
        if options["json"]:
            self.stdout.write(json.dumps(result))
            return

        if result["ended"] or result["deleted"]:
            parts = []
            if result["ended"]:
                parts.append(f"ended {result['ended']} active")
            if result["deleted"]:
                parts.append(f"deleted {result['deleted']} future")
            self.stdout.write(self.style.SUCCESS(f"Closed maintenance for '{options['monitor']}': {', '.join(parts)}."))
        else:
            self.stdout.write("No active maintenance windows to close.")

    def _list(self, options):
        windows = maintenance.list_windows(monitor_key=options["monitor"], active_only=options["active"])
        rows = [_window_dict(w) for w in windows]

        if options["json"]:
            self.stdout.write(json.dumps(rows))
            return

        if not rows:
            self.stdout.write("No maintenance windows.")
            return

        for w, data in zip(windows, rows):
            tag = " [active]" if data["active"] else ""
            sla = "" if w.exclude_from_sla else " (not SLA-excluded)"
            self.stdout.write(
                f"#{w.pk} [{w.monitor_key}] {localtime(w.start):%Y-%m-%d %H:%M} → "
                f"{localtime(w.end):%H:%M}  {w.title}{tag}{sla}"
            )


def _parse(raw: str, flag: str):
    dt = parse_datetime(raw)
    if dt is None:
        raise CommandError(f"Could not parse {flag} value {raw!r}. Use ISO format, e.g. '2026-07-01 02:00'.")
    return dt


def _window_dict(window) -> dict:
    from django.utils.timezone import now

    return {
        "id": window.pk,
        "monitor_key": window.monitor_key,
        "title": window.title,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "note": window.note,
        "exclude_from_sla": window.exclude_from_sla,
        "active": window.start <= now() < window.end,
    }
