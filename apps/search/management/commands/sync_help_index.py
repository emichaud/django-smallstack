"""Rebuild the help-article search index from filesystem markdown.

Run after editing or adding any apps/smallstack/docs/*.md file. Also
called automatically at app startup via apps.help.apps.HelpConfig.ready()
so a fresh clone has searchable docs from the first request.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync the help-article search index from filesystem markdown."

    def handle(self, *args, **options):
        from apps.help.search import sync_help_index

        count = sync_help_index()
        if count == 0:
            self.stdout.write(self.style.WARNING(
                "Sync skipped — non-SQLite database or zero articles."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f"Indexed {count} help articles."))
