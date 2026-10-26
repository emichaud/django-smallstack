"""Bundled datasets for runbooks: documents and their version history.

Document bodies are not columns; this is the catalogue, not the content.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import Document, DocumentVersion


@framework_dataset(
    "smallstack_runbook_documents",
    label="Runbook documents",
    description=(
        "Every runbook document: runbook, section, key, title, current version, type, provenance, "
        "lifecycle flags and dates."
    ),
    columns=[
        "runbook",
        "section",
        "key",
        "slug",
        "title",
        "version",
        "doc_type",
        "source",
        "via",
        "created_by",
        "is_generated",
        "is_template",
        "is_archived",
        "locked",
        "archived_at",
        "created_at",
        "updated_at",
    ],
    filterable=[
        "runbook",
        "section",
        "doc_type",
        "source",
        "via",
        "created_by",
        "is_generated",
        "is_template",
        "is_archived",
        "locked",
        "created_at",
        "updated_at",
    ],
)
def runbook_documents() -> QuerySet[Document]:
    return Document.objects.select_related("runbook", "section", "created_by")


@framework_dataset(
    "smallstack_runbook_document_versions",
    label="Runbook document versions",
    description=(
        "One row per saved version of a document: which document, the version number, who wrote it, how, and when."
    ),
    columns=["document", "version", "title", "source", "via", "created_by", "created_at"],
    filterable=["document", "source", "via", "created_by", "created_at"],
)
def runbook_document_versions() -> QuerySet[DocumentVersion]:
    return DocumentVersion.objects.select_related("document", "created_by")
