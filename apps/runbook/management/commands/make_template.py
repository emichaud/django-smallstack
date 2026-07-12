"""Turn a runbook into a reusable template by cloning a copy.

    uv run python manage.py make_template <slug> [--name NAME] [--slug SLUG]

The original runbook is left untouched; a separate template runbook is created
(``is_template=True``) with copies of its sections, documents, and images.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.runbook import service
from apps.runbook.models import Runbook


class Command(BaseCommand):
    help = "Clone a runbook into a reusable template runbook."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("slug", help="Slug of the runbook to templatize.")
        parser.add_argument("--name", default=None, help="Name for the new template runbook.")
        parser.add_argument("--slug", dest="new_slug", default=None, help="Slug for the new template runbook.")
        parser.add_argument("--keep-locked", action="store_true", help="Preserve locked state on cloned docs.")

    def handle(self, *args: Any, **options: Any) -> None:
        source = Runbook.objects.filter(slug=options["slug"]).first()
        if source is None:
            raise CommandError(f"No runbook with slug {options['slug']!r}.")

        template = service.clone_runbook(
            source,
            new_slug=options["new_slug"],
            new_name=options["name"] or f"{source.name} Template",
            as_template=True,
            copy_locked=options["keep_locked"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created template '{template.slug}' from '{source.slug}' "
                f"({template.documents.count()} document(s))."
            )
        )
