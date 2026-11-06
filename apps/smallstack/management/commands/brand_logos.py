"""Write the SmallStack logo as SVG files, one set for each palette.

Usage:
    uv run python manage.py brand_logos            # write them
    uv run python manage.py brand_logos --check    # exit 1 if any is out of date

Run it after adding or retuning a palette. See ``apps/smallstack/brand_logos.py``.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.smallstack import brand_logos


class Command(BaseCommand):
    help = "Write the SmallStack logo (logo + icon, dark + light) as SVG files for every palette"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--check", action="store_true", help="Change nothing; fail if a file is out of date")

    def handle(self, *args: Any, **options: Any) -> None:
        where = brand_logos.OUT_DIR.relative_to(brand_logos.APP.parent.parent)
        if options["check"]:
            stale = brand_logos.stale()
            if stale:
                raise CommandError(f"{len(stale)} logo file(s) out of date in {where}: run `manage.py brand_logos`")
            self.stdout.write(f"Logo files in sync ({len(brand_logos.build())} in {where}).")
            return
        changed = brand_logos.write()
        total = len(brand_logos.build())
        self.stdout.write(f"Wrote {total} logo files to {where} ({len(changed)} changed).")
