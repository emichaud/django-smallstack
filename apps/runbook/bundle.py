"""App-documentation bundles: round-trip a runbook to/from a portable ZIP.

Author docs in a runbook (rich UI), ``export_bundle`` → a self-contained ZIP
that ships in the app repo; ``import_bundle`` re-hydrates it into a runbook
(locked by default — the bundle is the source of truth). The ZIP holds a
``manifest.json`` plus markdown files and content-hashed images, with image URLs
rewritten to relative paths so the bundle is database-independent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import posixpath
import zipfile
from typing import Optional

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import service
from .models import Document, DocumentImage, Runbook, Section

FORMAT = "smallstack-runbook-bundle/1"


@dataclasses.dataclass
class ImportResult:
    runbook: str
    created: int
    updated: int
    archived: int


def _doc_key(doc: Document) -> str:
    return doc.key or doc.slug


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_sha(image: DocumentImage) -> str:
    image.image.open("rb")
    try:
        return _sha(image.image.read())
    finally:
        image.image.close()


def export_bundle(runbook: Runbook) -> bytes:
    """Serialise a runbook (current docs + images) to a portable ZIP bundle."""
    manifest: dict = {
        "format": FORMAT,
        "runbook": {
            "slug": runbook.slug,
            "name": runbook.name,
            "description": runbook.description,
            "icon": runbook.icon,
        },
        "sections": [],
        "documents": [],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sec in runbook.sections.order_by("order", "name"):
            manifest["sections"].append({
                "slug": sec.slug, "name": sec.name, "order": sec.order,
                "description": sec.description, "icon": sec.icon,
            })

        docs = (
            Document.objects.filter(runbook=runbook, is_archived=False)
            .select_related("section")
            .order_by("section__order", "title")
        )
        for doc in docs:
            dir_parts = [doc.section.slug] if doc.section_id else []
            doc_path = posixpath.join(*(dir_parts + [f"{_doc_key(doc)}.md"]))
            content = service.read_head(doc)

            images = []
            for img in doc.images.all():
                serve_url = reverse("runbook:serve_image", kwargs={"pk": img.pk})
                if serve_url not in content:
                    continue
                img.image.open("rb")
                data = img.image.read()
                img.image.close()
                ext = os.path.splitext(img.image.name)[1] or ".png"
                digest = hashlib.sha256(data).hexdigest()[:16]
                rel_ref = f"images/{digest}{ext}"  # relative to the doc's folder
                content = content.replace(serve_url, rel_ref)
                zip_path = posixpath.join(*(dir_parts + [rel_ref]))
                if zip_path not in zf.namelist():
                    zf.writestr(zip_path, data)
                images.append({"ref": rel_ref, "alt": img.alt})

            zf.writestr(doc_path, content)
            manifest["documents"].append({
                "key": _doc_key(doc),
                "title": doc.title,
                "section": doc.section.slug if doc.section_id else None,
                "description": doc.description,
                "doc_type": doc.doc_type,
                "path": doc_path,
                "images": images,
            })

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return buf.getvalue()


@transaction.atomic
def import_bundle(
    data: bytes,
    *,
    slug_override: Optional[str] = None,
    locked: bool = True,
    source: str = "app",
    prune: bool = False,
    actor: Optional[AbstractBaseUser] = None,
) -> ImportResult:
    """Hydrate a bundle into a runbook, upserting docs by key.

    Documents are marked ``is_generated`` + ``source`` and ``locked`` (default),
    since the bundle is the source of truth. With ``prune=True``, managed docs
    (same ``source``) whose keys are absent from the bundle are archived.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(zf.read("manifest.json"))
    rb_meta = manifest.get("runbook", {})
    slug = slug_override or rb_meta["slug"]

    runbook, _ = Runbook.objects.get_or_create(
        slug=slug,
        defaults={
            "name": rb_meta.get("name", slug),
            "description": rb_meta.get("description", ""),
            "icon": rb_meta.get("icon", ""),
        },
    )

    sections: dict[str, Section] = {}
    for spec in manifest.get("sections", []):
        section, _ = Section.objects.get_or_create(
            runbook=runbook, slug=spec["slug"],
            defaults={
                "name": spec.get("name", spec["slug"]),
                "order": spec.get("order", 0),
                "description": spec.get("description", ""),
                "icon": spec.get("icon", ""),
            },
        )
        sections[spec["slug"]] = section

    created = updated = 0
    seen: set[str] = set()

    for spec in manifest.get("documents", []):
        key = spec["key"]
        seen.add(key)
        content = zf.read(spec["path"]).decode("utf-8")
        section = sections.get(spec.get("section"))
        doc_dir = posixpath.dirname(spec["path"])

        doc = Document.objects.filter(runbook=runbook, key=key).first()
        is_new = doc is None
        if is_new:
            doc = Document.objects.create(
                runbook=runbook, key=key, section=section,
                title=spec.get("title", key), description=spec.get("description", ""),
                doc_type=spec.get("doc_type", ""), is_generated=True, source=source,
                locked=locked, via="import", created_by=actor,
            )
            meta_changed = True
        else:
            before = (doc.section_id, doc.title, doc.description, doc.doc_type,
                      doc.is_generated, doc.source, doc.locked)
            doc.section = section
            doc.title = spec.get("title", doc.title)
            doc.description = spec.get("description", doc.description)
            doc.doc_type = spec.get("doc_type", doc.doc_type)
            doc.is_generated = True
            doc.source = source
            doc.locked = locked
            after = (doc.section_id, doc.title, doc.description, doc.doc_type,
                     doc.is_generated, doc.source, doc.locked)
            meta_changed = before != after
            if meta_changed:
                doc.save()

        # The bundle is authoritative for images, but only recreate the pool when
        # the content-hash set actually differs — otherwise reuse the existing
        # rows so an unchanged re-import doesn't churn image pks (or the serve
        # URLs baked into the body) and stays truly idempotent.
        desired = []
        for img in spec.get("images", []):
            rel_ref = img["ref"]
            zip_path = posixpath.join(doc_dir, rel_ref) if doc_dir else rel_ref
            blob = zf.read(zip_path)
            desired.append((rel_ref, img.get("alt", ""), blob, _sha(blob)))

        existing = list(doc.images.all())
        if existing and sorted((_image_sha(di), di.alt) for di in existing) == sorted(
            (digest, alt) for _, alt, _, digest in desired
        ):
            by_digest = {_image_sha(di): di for di in existing}
            for rel_ref, _alt, _blob, digest in desired:
                serve_url = reverse("runbook:serve_image", kwargs={"pk": by_digest[digest].pk})
                content = content.replace(rel_ref, serve_url)
        else:
            for di in existing:
                di.delete()
            for rel_ref, alt, blob, _digest in desired:
                image = DocumentImage.objects.create(
                    document=doc, image=ContentFile(blob, name=posixpath.basename(rel_ref)),
                    alt=alt, uploaded_by=actor,
                )
                serve_url = reverse("runbook:serve_image", kwargs={"pk": image.pk})
                content = content.replace(rel_ref, serve_url)

        content_changed = content != service.read_head(doc)
        if content_changed:
            service.write_version(
                doc, body=content, mode="new_version", source=source, via="import",
                actor=actor, bypass_lock=True,
            )

        if is_new:
            created += 1
        elif meta_changed or content_changed:
            updated += 1

    archived = 0
    if prune:
        stale = Document.objects.filter(
            runbook=runbook, is_archived=False, source=source
        ).exclude(key__in=seen)
        for doc in stale:
            doc.is_archived = True
            doc.archived_at = timezone.now()
            doc.save(update_fields=["is_archived", "archived_at"])
            archived += 1

    return ImportResult(runbook=runbook.slug, created=created, updated=updated, archived=archived)
