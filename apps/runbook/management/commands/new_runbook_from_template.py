"""Instantiate a fresh runbook from a template runbook.

    uv run python manage.py new_runbook_from_template <template-slug> --name "My Runbook"

Copies the template's sections, documents, and images into a new (non-template)
runbook that you can edit freely. The template is left untouched.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.runbook import service
from apps.runbook.models import Runbook


class Command(BaseCommand):
    help = "Create a new runbook from a template runbook."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("slug", help="Slug of the template runbook.")
        parser.add_argument("--name", required=True, help="Name for the new runbook.")
        parser.add_argument("--slug", dest="new_slug", default=None, help="Slug for the new runbook.")

    def handle(self, *args: Any, **options: Any) -> None:
        template = Runbook.objects.filter(slug=options["slug"], is_template=True).first()
        if template is None:
            raise CommandError(f"No template runbook with slug {options['slug']!r}.")

        runbook = service.clone_runbook(
            template,
            new_name=options["name"],
            new_slug=options["new_slug"],
            as_template=False,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created runbook '{runbook.slug}' from template '{template.slug}' "
                f"({runbook.documents.count()} document(s))."
            )
        )
