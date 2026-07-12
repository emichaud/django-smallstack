"""Backfill content_text for all document versions and resync document heads."""

from typing import Any

from django.core.management.base import BaseCommand

from apps.runbook.models import Document, DocumentVersion


class Command(BaseCommand):
    help = "Extract plaintext from every version's file, then resync each document's head text."

    def handle(self, *args: Any, **options: Any) -> None:
        versions = DocumentVersion.objects.all()
        total = versions.count()
        updated = 0

        for version in versions.iterator():
            text = version.extract_text()
            if text != version.content_text:
                version.content_text = text
                version.save(update_fields=["content_text"], skip_content_extract=True)
                updated += 1

        # Keep each document's denormalised head text in sync.
        for doc in Document.objects.select_related("current_version").iterator():
            head = doc.current_version
            if head and doc.content_text != head.content_text:
                doc.content_text = head.content_text
                doc.save(update_fields=["content_text"])

        self.stdout.write(
            self.style.SUCCESS(f"Reindex complete: {updated} of {total} version(s) changed.")
        )
