"""Export a runbook to a portable app-documentation bundle (ZIP).

    uv run python manage.py export_runbook <slug> --out docs-bundle.zip

The bundle ships in your app repo; import it on install with ``import_runbook``.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.runbook import bundle
from apps.runbook.models import Runbook


class Command(BaseCommand):
    help = "Export a runbook to a portable app-documentation bundle (ZIP)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("slug", help="Runbook slug to export.")
        parser.add_argument("--out", required=True, help="Output .zip path.")

    def handle(self, *args: Any, **options: Any) -> None:
        runbook = Runbook.objects.filter(slug=options["slug"]).first()
        if runbook is None:
            raise CommandError(f"No runbook with slug {options['slug']!r}.")

        data = bundle.export_bundle(runbook)
        with open(options["out"], "wb") as handle:
            handle.write(data)

        doc_count = runbook.documents.filter(is_archived=False).count()
        self.stdout.write(
            self.style.SUCCESS(f"Exported '{runbook.slug}' ({doc_count} document(s)) → {options['out']}.")
        )
