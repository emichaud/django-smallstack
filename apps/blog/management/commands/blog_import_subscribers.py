"""Import a subscriber list from CSV.

Deliberately demands ``--consent-note``: importing is the one path that can
bypass double opt-in, so the record of why these people may be mailed has to
exist before the first send rather than be reconstructed afterwards.
"""

from __future__ import annotations

import csv
import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.blog import service
from apps.blog.models import Blog


class Command(BaseCommand):
    help = "Import subscribers into a blog's newsletter from a CSV of email,name."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("blog", help="Blog slug.")
        parser.add_argument("csv_path", nargs="?", help="CSV file; omit to read stdin.")
        parser.add_argument(
            "--consent-note",
            required=True,
            help="Where consent came from. Required, and stored on every row.",
        )
        parser.add_argument(
            "--confirmed",
            action="store_true",
            help="Mark rows confirmed (skips double opt-in — only for a list "
            "whose consent you can evidence).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            blog = Blog.objects.get(slug=options["blog"])
        except Blog.DoesNotExist as exc:
            raise CommandError(f"No blog with slug {options['blog']!r}.") from exc

        handle = open(options["csv_path"], newline="") if options["csv_path"] else sys.stdin
        try:
            rows = [
                (row[0], row[1] if len(row) > 1 else "")
                for row in csv.reader(handle)
                if row and row[0].strip() and "@" in row[0]
            ]
        finally:
            if options["csv_path"]:
                handle.close()

        if not rows:
            raise CommandError("No usable rows found.")

        try:
            stats = service.import_subscribers(
                blog,
                rows,
                consent_note=options["consent_note"],
                confirmed=options["confirmed"],
                actor=None,
            )
        except service.BlogServiceError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"{stats['created']} added, {stats['existing']} already present, "
                f"{stats['skipped']} skipped."
            )
        )
        if not options["confirmed"]:
            self.stdout.write(
                "Imported as PENDING — they will not receive anything until they confirm."
            )
