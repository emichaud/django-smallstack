"""Search captured log records from the shell.

The gap this fills: ``log_capture`` could turn capture up and report *that* it
was on, but there was no way to read the resulting records without a browser
session — the viewer and (now) ``/api/logger/`` were the only readers. On a box
where you already have a shell, opening a browser to read the logs you just
captured is a silly round trip.

    # what went wrong recently
    manage.py logs --level ERROR --limit 20

    # every line a failing request produced (paste the X-Request-ID)
    manage.py logs --request-id req_d09627b8-f8a7-448d-a605-62c6590c2e49

    # find it by exception class — searches tracebacks, not just messages
    manage.py logs --search ValidationError

    # one record with its full traceback
    manage.py logs --id 6183

    # follow, like tail -f
    manage.py logs --follow --level WARNING

Filters are the same names and semantics as ``/api/logger/records/`` and the
``logs_search`` MCP tool, because all three call ``apps.telemetry.queries``.
``--json`` emits the same payload the API returns.
"""

from __future__ import annotations

import json
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.telemetry import queries


class Command(BaseCommand):
    help = "Search captured log records (same filters as /api/logger/records/)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--level", help="This level and above (DEBUG/INFO/WARNING/ERROR/CRITICAL).")
        parser.add_argument("--logger", help="Hierarchy-aware logger prefix, e.g. apps.inventory.")
        parser.add_argument("--request-id", dest="request_id", help="Exact X-Request-ID to correlate.")
        parser.add_argument("--trace-id", dest="trace_id", help="Exact trace id (background work).")
        parser.add_argument("--search", help="Substring of the message OR the traceback.")
        parser.add_argument("--since", help="ISO-8601 lower bound, e.g. 2026-08-17T01:30:00Z.")
        parser.add_argument("--until", help="ISO-8601 upper bound.")
        parser.add_argument("--after-id", dest="after_id", type=int, help="Only records newer than this id.")
        parser.add_argument(
            "--before-id", dest="before_id", type=int, help="Older records: the next page back from this id."
        )
        parser.add_argument("--limit", type=int, help=f"Max {queries.MAX_LIMIT}, default {queries.DEFAULT_LIMIT}.")
        parser.add_argument("--id", type=int, help="Show one record with its full traceback, then exit.")
        parser.add_argument("--json", action="store_true", help="Emit the API's JSON payload.")
        parser.add_argument(
            "--follow",
            action="store_true",
            help="Poll for new records and print them as they arrive (Ctrl-C to stop).",
        )
        parser.add_argument("--interval", type=float, default=2.0, help="Seconds between polls with --follow.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            if options.get("id"):
                self._detail(options["id"], as_json=options["json"])
            elif options.get("follow"):
                self._follow(options)
            else:
                self._search(options)
        except queries.TelemetryQueryError as exc:
            # A bad filter is a usage error, not a traceback. CommandError
            # exits non-zero, which is what a script checks.
            raise CommandError(str(exc)) from None

    # -- helpers ------------------------------------------------------------

    def _filters(self, options: dict[str, Any]) -> dict[str, Any]:
        return {
            name: options[name]
            for name in queries.FILTER_NAMES
            if options.get(name) not in (None, "")
        }

    def _detail(self, record_id: int, *, as_json: bool) -> None:
        record = queries.get_record(record_id)
        if record is None:
            raise CommandError(f"No log record with id {record_id}")
        if as_json:
            self.stdout.write(json.dumps(record, indent=2, default=str))
            return

        for field in ("id", "ts", "level", "logger", "module", "func", "line", "request_id", "trace_id"):
            if record.get(field) not in (None, "", 0):
                self.stdout.write(f"{field + ':':<12} {record[field]}")
        self.stdout.write("")
        self.stdout.write(record["message"])
        if record.get("extra"):
            self.stdout.write("")
            self.stdout.write(f"extra: {json.dumps(record['extra'], default=str)}")
        if record.get("exc_text"):
            self.stdout.write("")
            self.stdout.write(record["exc_text"])

    def _search(self, options: dict[str, Any]) -> None:
        result = queries.search_records(**self._filters(options))
        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return

        records = result["records"]
        if not records:
            self.stdout.write("No matching records.")
            # The most common cause of an empty result by far, and invisible
            # unless you know the baseline: the lines were never stored,
            # because capture sits at WARNING.
            status = queries.capture_status()
            if not status["open"]:
                self.stdout.write(
                    f"  (capture is at its {status['baseline_level']} baseline — lines below that "
                    "were never stored. `manage.py log_capture start --level DEBUG` to change that.)"
                )
            return

        # Oldest first when printing so a terminal reads top-to-bottom like a
        # log file. A page with no cursor or --before-id comes back newest-first
        # and is flipped; an --after-id page is already oldest-first.
        for record in records if "after_id" in result["applied_filters"] else reversed(records):
            self._line(record)

        if result["has_more"]:
            if result["next_before_id"] is not None:
                more = f"--before-id {result['next_before_id']} for the older ones"
            else:
                more = f"--after-id {result['next_after_id']} for the next ones"
            self.stdout.write(
                self.style.WARNING(f"… {result['total_matching'] - len(records)} more match. Use --limit, or {more}.")
            )

    def _line(self, record: dict) -> None:
        stamp = str(record["ts"])[:19].replace("T", " ")
        level = record["level"]
        style = {
            "ERROR": self.style.ERROR,
            "CRITICAL": self.style.ERROR,
            "WARNING": self.style.WARNING,
        }.get(level, lambda text: text)
        suffix = ""
        if record.get("exc_type"):
            suffix = f"  [{record['exc_type']}]"
        message = record["message"].splitlines()[0] if record["message"] else ""
        self.stdout.write(
            f"{record['id']:>7}  {stamp}  {style(f'{level:<8}')} {record['logger']:<28} {message}{suffix}"
        )

    def _follow(self, options: dict[str, Any]) -> None:
        """Tail. Uses the id cursor, not page numbers.

        New rows arrive continuously, so an offset-based loop would re-print
        records it had already shown every time the head moved.
        """
        filters = self._filters(options)
        cursor = filters.pop("after_id", None)
        if cursor is None:
            # Start from the current tail rather than replaying history — the
            # point of --follow is what happens next.
            recent = queries.search_records(**filters, limit=1)
            cursor = recent["records"][0]["id"] if recent["records"] else 0

        self.stdout.write(self.style.SUCCESS(f"Following from id {cursor} (Ctrl-C to stop)…"))
        try:
            while True:
                batch = queries.search_records(**filters, after_id=cursor, limit=queries.MAX_LIMIT)
                for record in batch["records"]:  # already oldest-first when tailing
                    if options["json"]:
                        self.stdout.write(json.dumps(record, default=str))
                    else:
                        self._line(record)
                if batch["records"]:
                    cursor = batch["next_after_id"]
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(f"Stopped at id {cursor}.")
