"""Import an app-documentation bundle (ZIP) into a runbook.

    uv run python manage.py import_runbook docs-bundle.zip

Documents are marked managed (``is_generated``, ``source``) and **locked**
(read-only; superuser to change) by default — the bundle is the source of truth.
Use ``--unlock`` on a dev machine to hydrate them for editing, then re-export.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.runbook import bundle


class Command(BaseCommand):
    help = "Import an app-documentation bundle (ZIP) into a runbook."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("path", help="Path to the bundle .zip.")
        parser.add_argument("--slug", default=None, help="Override the runbook slug from the manifest.")
        parser.add_argument("--source", default="app", help="Provenance source label (default 'app').")
        parser.add_argument("--unlock", action="store_true", help="Import unlocked (for authoring/editing).")
        parser.add_argument("--prune", action="store_true", help="Archive managed docs no longer in the bundle.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            with open(options["path"], "rb") as handle:
                data = handle.read()
        except OSError as exc:
            raise CommandError(str(exc))

        result = bundle.import_bundle(
            data,
            slug_override=options["slug"],
            locked=not options["unlock"],
            source=options["source"],
            prune=options["prune"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported into '{result.runbook}': {result.created} created, "
                f"{result.updated} updated, {result.archived} archived."
            )
        )
