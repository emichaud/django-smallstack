"""Fetch registered RSS/Atom feed sources and store new items.

    manage.py collect_feeds            # all enabled sources
    manage.py collect_feeds <name>     # just one

Same core as the ``@scheduled`` ``poll_feed_sources`` job — run it by hand to
backfill or debug a source.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser


class Command(BaseCommand):
    help = "Fetch registered RSS/Atom feed sources and store new items."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("name", nargs="?", help="Only this source (default: all enabled).")

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.feeds.collector import collect_all, collect_source
        from apps.feeds.sources import all_sources

        if not all_sources():
            self.stdout.write(self.style.WARNING(
                "No feed sources registered. Declare them with "
                "apps.feeds.register_feed_source(name, url) in a feed_sources.py "
                "or your app's ready()."
            ))
            return

        name = options.get("name")
        results = [collect_source(name)] if name else collect_all()

        total_new = 0
        for r in results:
            if r.get("error"):
                self.stdout.write(self.style.ERROR(f"  {r['name']}: {r['error']}"))
                continue
            total_new += r["created"]
            self.stdout.write(
                f"  {r['name']}: {r['created']} new, {r['skipped']} seen "
                f"({r['fetched']} in feed)"
            )
        self.stdout.write(self.style.SUCCESS(f"Done — {total_new} new item(s)."))
