"""Tests for the seed_platform_runbook management command.

Verifies idempotency: running the seeder multiple times should not create
duplicates or raise exceptions.
"""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.runbook.models import Document, Runbook

User = get_user_model()


class SeedPlatformRunbookTest(TestCase):
    """Test the seed_platform_runbook command."""

    def setUp(self):
        """Create a superuser so the seeder can run."""
        User.objects.create_superuser("admin", "admin@example.com", "admin")

    def test_seeder_is_idempotent(self):
        """Running the seeder twice should not crash or create duplicates."""
        # First run: should create the runbook and all documents
        call_command("seed_platform_runbook")

        # Verify the Platform Access Guide runbook was created
        runbook = Runbook.objects.filter(name__icontains="Platform Access").first()
        self.assertIsNotNone(runbook, "Platform Access Guide runbook was not created")

        # Count documents in the first run
        docs_after_first_run = Document.objects.filter(
            runbook=runbook, is_archived=False
        ).count()
        self.assertGreater(docs_after_first_run, 0, "No documents were created")

        # Second run: should not crash and should not create duplicates
        call_command("seed_platform_runbook")

        # Verify document count is unchanged
        docs_after_second_run = Document.objects.filter(
            runbook=runbook, is_archived=False
        ).count()
        self.assertEqual(
            docs_after_first_run,
            docs_after_second_run,
            "Document count changed on second run (idempotency broken)",
        )

    def test_seeder_creates_expected_documents(self):
        """Verify the seeder creates the expected documents."""
        call_command("seed_platform_runbook")

        runbook = Runbook.objects.filter(name__icontains="Platform Access").first()
        self.assertIsNotNone(runbook)

        # Expected document titles (must match DOCS in seed_platform_runbook.py)
        expected_titles = [
            "The Four Surfaces",
            "Using the sc CLI",
            "Using the REST API",
            "Using MCP",
            "Searching Models",  # Fixed: was "Using Search", should be "Searching Models"
        ]

        documents = Document.objects.filter(
            runbook=runbook, is_archived=False
        ).values_list("title", flat=True)

        for title in expected_titles:
            self.assertIn(title, documents, f"Document '{title}' was not created")
