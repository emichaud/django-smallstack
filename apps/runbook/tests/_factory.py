"""Test helpers for building Model B documents (logical Document + version)."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.text import slugify

from apps.runbook.models import Document, Runbook


def make_runbook(*, name="RB", slug=None, owner=None, is_public=False, is_template=False) -> Runbook:
    """Create a Runbook with ownership/visibility for permission tests."""
    return Runbook.objects.create(
        name=name,
        slug=slug or slugify(name),
        owner=owner,
        is_public=is_public,
        is_template=is_template,
    )


def make_document(
    *,
    title="Doc",
    body: bytes | str = b"# Doc",
    section=None,
    runbook=None,
    created_by=None,
    key=None,
    slug=None,
    description="",
) -> Document:
    """Create a logical Document with its first DocumentVersion."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    slug = slug or slugify(title)
    doc = Document.objects.create(
        title=title,
        slug=slug,
        section=section,
        runbook=runbook or (section.runbook if section is not None else None),
        key=key,
        description=description,
        created_by=created_by,
    )
    doc.create_new_version(
        file=SimpleUploadedFile(f"{slug or 'doc'}.md", body),
        created_by=created_by,
    )
    return doc
