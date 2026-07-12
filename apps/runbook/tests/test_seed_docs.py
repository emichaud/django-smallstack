"""Tests for the dogfood docs seed command + search over the seeded docs."""

import pytest
from django.core.management import call_command

from apps.runbook import service
from apps.runbook.models import Document, Runbook


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.mark.django_db
class TestSeedRunbookDocs:
    def test_seed_creates_locked_managed_runbook(self):
        call_command("seed_runbook_docs")
        runbook = Runbook.objects.get(slug="runbook-guide")
        docs = Document.objects.filter(runbook=runbook)
        assert docs.count() == 8
        assert all(d.locked and d.is_generated and d.source == "runbook-docs" for d in docs)
        assert set(runbook.sections.values_list("slug", flat=True)) == {
            "user-guide", "admin-guide", "developer-guide",
        }

    def test_seed_is_idempotent_without_version_churn(self):
        call_command("seed_runbook_docs")
        call_command("seed_runbook_docs")
        docs = Document.objects.filter(runbook__slug="runbook-guide")
        assert docs.count() == 8
        assert all(d.version == 1 for d in docs)  # overwrite in place, not new_version

    def test_unlock_flag_seeds_editable(self):
        call_command("seed_runbook_docs", "--unlock")
        assert not Document.objects.filter(runbook__slug="runbook-guide").first().locked


@pytest.mark.django_db
class TestSearchOverSeededDocs:
    def test_search_matches_body_only_term(self):
        # "retention" is not in any title — only in document bodies.
        call_command("seed_runbook_docs")
        titles = {d.title for d in service.list_documents(runbook="runbook-guide", query="retention")}
        assert "Versions & Retention" in titles

    def test_search_matches_deep_table_cell_term(self):
        # "optimistic" lives in a table cell of the service doc's body.
        call_command("seed_runbook_docs")
        hits = service.list_documents(query="optimistic")
        assert any("Service" in d.title for d in hits)

    def test_search_matches_title(self):
        call_command("seed_runbook_docs")
        hits = service.list_documents(query="bundles")
        assert any(d.title == "Shipping App Documentation as Bundles" for d in hits)

    def test_search_scoped_to_runbook(self):
        call_command("seed_runbook_docs")
        # Every hit scoped to the guide runbook belongs to it.
        hits = service.list_documents(runbook="runbook-guide", query="document")
        assert hits and all(d.runbook == "runbook-guide" for d in hits)
