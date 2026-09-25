"""Open, close, and inspect the log capture window.

The reason this exists: production captures WARNING and above so the table
stays small, but the moment you actually need to debug a live deployment you
want DEBUG — and you want it to turn itself off again.

    # see what's being captured right now
    uv run python manage.py log_capture status

    # capture DEBUG for the next 15 minutes, then reproduce the bug
    uv run python manage.py log_capture start --level DEBUG --minutes 15

    # close it early
    uv run python manage.py log_capture stop

Every worker and container picks the change up within one poll interval
(default 5s) — the window lives in the database, not in one process's memory.

``--json`` on any action prints one machine-readable object instead of prose,
for scripts and agents driving this from a shell. Worth having because the
human output was never parseable: the handler line printed a *Python dict
repr* (single quotes, ``False`` not ``false``), so anything consuming it was
already screen-scraping something that isn't JSON.
"""

from __future__ import annotations

import getpass
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.telemetry import capture, queries
from apps.telemetry.handlers import get_handlers
from apps.telemetry.models import LogRecord


class Command(BaseCommand):
    help = "Control the database log capture window (start / stop / status)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["start", "stop", "status"], help="What to do.")
        parser.add_argument(
            "--level",
            default="DEBUG",
            choices=["DEBUG", "INFO", "WARNING", "ERROR"],
            help="Level to capture while the window is open (start only).",
        )
        parser.add_argument("--minutes", type=int, default=15, help="How long to capture for (start only).")
        parser.add_argument("--note", default="", help="Why the window was opened — shown in the audit list.")
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print one JSON object instead of human-readable output (for scripts and agents).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        if options.get("json"):
            self._emit_json(action, options)
        elif action == "start":
            self._start(options)
        elif action == "stop":
            self._stop()
        else:
            self._status()

    def _emit_json(self, action: str, options: dict[str, Any]) -> None:
        """Machine-readable output, sharing the REST/MCP payload shapes.

        Same dicts the API returns (``apps.telemetry.queries``), so a script
        that moves between the CLI and HTTP doesn't meet two different
        vocabularies for one thing.
        """
        import json

        try:
            if action == "start":
                try:
                    actor = getpass.getuser()
                except Exception:
                    actor = ""
                # note stays optional on the CLI, unlike the API: a human
                # running this is present and accountable in the moment,
                # whereas an unattended caller is neither.
                payload = queries.open_capture(
                    level=options["level"],
                    minutes=options["minutes"],
                    note=options["note"] or f"opened via CLI by {actor or 'unknown'}",
                    actor_name=actor,
                )
            elif action == "stop":
                payload = queries.close_capture()
            else:
                payload = queries.capture_status()
                payload["stored_records"] = LogRecord.objects.count()
        except queries.TelemetryQueryError as exc:
            self.stdout.write(json.dumps({"error": str(exc)}))
            raise SystemExit(1) from None

        self.stdout.write(json.dumps(payload, indent=2, default=str))

    def _start(self, options: dict[str, Any]) -> None:
        try:
            actor = getpass.getuser()
        except Exception:
            actor = ""

        try:
            queries.parse_capture_level(options["level"])
        except queries.TelemetryQueryError as exc:
            raise CommandError(str(exc)) from None

        requested = options["minutes"]
        window = capture.start(
            level=options["level"],
            minutes=requested,
            actor=actor,
            note=options["note"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Capturing {window.level} until {window.expires_at:%Y-%m-%d %H:%M:%S %Z} "
                f"({(window.expires_at - window.started_at).total_seconds() / 60:.0f} min)."
            )
        )
        # Compare the requested value directly against the same cap start()
        # enforces — not two independently-generated timezone.now() calls
        # (expires_at is set in capture.start(); started_at is set moments
        # later by auto_now_add=True at .save() time), which are never
        # exactly equal and used to make this message fire unconditionally.
        if requested < 1 or requested > capture.max_capture_minutes():
            self.stdout.write("  (duration was clamped to TELEMETRY_MAX_CAPTURE_MINUTES)")
        self.stdout.write("  Running processes pick this up within one poll interval.")

    def _stop(self) -> None:
        closed = capture.stop()
        if closed:
            self.stdout.write(self.style.SUCCESS(f"Closed {closed} capture window(s)."))
        else:
            self.stdout.write("No open capture window.")

    def _status(self) -> None:
        window = capture.active_window()
        baseline = capture.baseline_level()

        if window:
            remaining = (window.expires_at - window.started_at).total_seconds()
            self.stdout.write(
                self.style.WARNING(
                    f"Capture window OPEN: {window.level} until "
                    f"{window.expires_at:%Y-%m-%d %H:%M:%S %Z} ({remaining / 60:.0f} min total)"
                )
            )
            if window.started_by or window.note:
                self.stdout.write(f"  opened by {window.started_by or '?'}{': ' + window.note if window.note else ''}")
        else:
            import logging

            self.stdout.write(f"No capture window. Baseline level: {logging.getLevelName(baseline)}")

        self.stdout.write(f"Stored records: {LogRecord.objects.count()}")

        handlers = get_handlers()
        if not handlers:
            # Expected: this is a separate process from the server, and the
            # handler is only installed where LOGGING configured it.
            self.stdout.write("No database log handler in THIS process (normal for a one-off command).")
        for handler in handlers:
            self.stdout.write(f"Handler: {handler.stats()}")
