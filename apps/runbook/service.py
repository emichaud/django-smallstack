"""Transport-agnostic document service — the one write path.

Web, MCP, REST, and CLI all call these functions, so versioning, provenance,
optimistic concurrency, and domain events behave identically everywhere.

Two layers:
  * instance ops (``write_version``, ``attach_image``, ``archive_document`` …)
    work on any ``Document`` — used by the browser UI, including keyless docs.
  * keyed ops (``put_document``, ``get_document`` …) resolve ``(runbook, key)``
    for idempotent programmatic access — used by MCP/REST/CLI.

Writers deal in markdown ``str`` bodies; images are attached separately.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime
from typing import Any, Literal, Optional, Union

from django.contrib.auth.models import AbstractBaseUser
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, QuerySet
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from . import permissions, signals
from .models import Document, DocumentImage, DocumentVersion, Runbook, Section, strip_frontmatter

# -- Types --------------------------------------------------------------------

WriteMode = Literal["new_version", "overwrite", "append", "append_version"]
OnExists = Literal["new_version", "overwrite", "append", "append_version", "fail"]
ChangeType = Literal["created", "new_version", "overwrite", "append", "append_version"]

RunbookRef = Union[Runbook, str]
SectionRef = Union[Section, str, None]
Actor = Optional[AbstractBaseUser]


class DocumentServiceError(Exception):
    """Base class for service-layer errors."""


class RunbookNotFound(DocumentServiceError):
    pass


class SectionNotFound(DocumentServiceError):
    pass


class DocumentNotFound(DocumentServiceError):
    pass


class DocumentAlreadyExists(DocumentServiceError):
    pass


class RunbookAlreadyExists(DocumentServiceError):
    """Raised when creating a runbook whose slug is already taken."""


class VersionConflict(DocumentServiceError):
    """Raised when ``expected_version`` does not match the current head."""


class DocumentLocked(DocumentServiceError):
    """Raised when a write targets a locked document without authorization."""


class NotAuthorized(DocumentServiceError):
    """Raised when an actor lacks ownership/edit rights for a runbook or document."""


@dataclasses.dataclass(frozen=True)
class ImageRef:
    id: int
    url: str
    markdown: str


@dataclasses.dataclass(frozen=True)
class DocumentSummary:
    id: int
    uid: str
    runbook: Optional[str]
    key: Optional[str]
    title: str
    version: int
    url: str
    source: str
    is_generated: bool
    is_archived: bool
    updated_at: datetime

    @classmethod
    def of(cls, doc: Document) -> DocumentSummary:
        return cls(
            id=doc.pk,
            uid=str(doc.uid),
            runbook=doc.runbook.slug if doc.runbook_id else None,
            key=doc.key,
            title=doc.title,
            version=doc.version,
            url=doc.get_absolute_url(),
            source=doc.source,
            is_generated=doc.is_generated,
            is_archived=doc.is_archived,
            updated_at=doc.updated_at,
        )


@dataclasses.dataclass(frozen=True)
class DocumentResult:
    id: int
    uid: str
    runbook: Optional[str]
    key: Optional[str]
    title: str
    version: int
    url: str
    source: str
    via: str
    is_generated: bool
    is_archived: bool
    locked: bool
    updated_at: datetime
    content_markdown: Optional[str] = None

    @classmethod
    def of(cls, doc: Document, *, with_body: bool = False) -> DocumentResult:
        return cls(
            id=doc.pk,
            uid=str(doc.uid),
            runbook=doc.runbook.slug if doc.runbook_id else None,
            key=doc.key,
            title=doc.title,
            version=doc.version,
            url=doc.get_absolute_url(),
            source=doc.source,
            via=doc.via,
            is_generated=doc.is_generated,
            is_archived=doc.is_archived,
            locked=doc.locked,
            updated_at=doc.updated_at,
            content_markdown=read_head(doc) if with_body else None,
        )


# -- Resolution & IO helpers --------------------------------------------------

def _resolve_runbook(runbook: RunbookRef) -> Runbook:
    if isinstance(runbook, Runbook):
        return runbook
    rb = Runbook.objects.filter(slug=runbook).first()
    if rb is None:
        raise RunbookNotFound(f"No runbook with slug {runbook!r}.")
    return rb


def _resolve_section(rb: Runbook, section: SectionRef) -> Optional[Section]:
    if section is None:
        return None
    if isinstance(section, Section):
        if section.runbook_id != rb.pk:
            raise SectionNotFound("Section does not belong to the runbook.")
        return section
    sec = Section.objects.filter(runbook=rb, slug=section).first()
    if sec is None:
        raise SectionNotFound(f"No section {section!r} in runbook {rb.slug!r}.")
    return sec


def _md_file(body: str, doc: Document) -> ContentFile:
    return ContentFile(body.encode("utf-8"), name=f"{doc.key or doc.slug or 'document'}.md")


def read_head(doc: Document) -> str:
    """Return the current version's markdown body ('' if there is none)."""
    if not doc.current_version_id:
        return ""
    handle = doc.current_version.file
    handle.open("rb")
    try:
        return handle.read().decode("utf-8", errors="replace")
    finally:
        handle.close()


def _overwrite_head(doc: Document, body: str, *, source: str, via: str) -> DocumentVersion:
    """Replace the current version's content in place and resync the head."""
    version = doc.current_version
    version.file.open("wb")
    version.file.write(body.encode("utf-8"))
    version.file.close()
    version.content_text = strip_frontmatter(body)
    if source:
        version.source = source
    version.via = via
    version.save(update_fields=["content_text", "source", "via"], skip_content_extract=True)
    doc.content_text = version.content_text
    doc.save(update_fields=["content_text", "updated_at"])
    return version


def _check_writable(doc: Document, actor: Actor, bypass_lock: bool) -> None:
    """Guard a write against ownership *and* the lock.

    Ownership: only the runbook owner or a staff user may edit (see
    ``permissions.can_edit_doc``). Lock: a locked doc additionally requires a
    superuser. Both checks are skipped when the caller is trusted — either
    ``actor is None`` (an internal sync: seed/import/clone) or
    ``bypass_lock=True`` (an authorized sync writing managed content)."""
    trusted = actor is None or bypass_lock
    if not trusted and not permissions.can_edit_doc(actor, doc):
        # Hide existence from a caller who can't even *view* the doc (a private
        # runbook they don't own): raise not-found, exactly as a read would, so
        # the write path can't be used to enumerate private slugs. A caller who
        # *can* view but not edit (e.g. a public doc they don't own) gets 403.
        if not permissions.can_view_doc(actor, doc):
            raise DocumentNotFound("Document not found.")
        raise NotAuthorized(f"You do not have permission to edit document {doc.key or doc.uid}.")
    if doc.locked and not bypass_lock and not getattr(actor, "is_superuser", False):
        raise DocumentLocked(f"Document {doc.key or doc.uid} is locked; superuser required to change it.")


def _emit_written(
    doc: Document,
    change: ChangeType,
    *,
    previous_version: Optional[DocumentVersion],
    actor: Actor,
    source: str,
    via: str,
) -> None:
    def _send() -> None:
        signals.document_written.send(
            sender=Document,
            document=doc,
            version=doc.current_version,
            change_type=change,
            previous_version=previous_version,
            actor=actor,
            source=source,
            via=via,
        )

    transaction.on_commit(_send)


# -- Instance-level write ops (work on any Document) --------------------------

@transaction.atomic
def write_version(
    doc: Document,
    *,
    body: str,
    mode: WriteMode = "new_version",
    description: str = "",
    source: str = "",
    via: str = "web",
    actor: Actor = None,
    bypass_lock: bool = False,
) -> Document:
    """Write ``body`` to ``doc`` per ``mode`` and emit ``document_written``.

    ``new_version`` snapshots a new version; ``overwrite`` replaces the head in
    place; ``append`` concatenates to the head content in place; ``append_version``
    concatenates **and** snapshots a new version (a running, versioned log).
    """
    _check_writable(doc, actor, bypass_lock)
    if mode == "new_version":
        previous_version = doc.current_version
        doc.create_new_version(
            file=_md_file(body, doc), created_by=actor, description=description, source=source, via=via
        )
        change: ChangeType = "new_version"
    elif mode == "overwrite":
        previous_version = None
        _overwrite_head(doc, body, source=source, via=via)
        change = "overwrite"
    elif mode == "append":
        previous_version = None
        combined = (read_head(doc).rstrip() + "\n\n" + body.strip() + "\n").lstrip("\n")
        _overwrite_head(doc, combined, source=source, via=via)
        change = "append"
    elif mode == "append_version":
        # Grow the head like `append`, but snapshot it as a new version like
        # `new_version` — so history keeps every appended entry.
        previous_version = doc.current_version
        combined = (read_head(doc).rstrip() + "\n\n" + body.strip() + "\n").lstrip("\n")
        doc.create_new_version(
            file=_md_file(combined, doc), created_by=actor, description=description, source=source, via=via
        )
        change = "append_version"
    else:  # pragma: no cover - guarded by the WriteMode type
        raise ValueError(f"Unknown write mode {mode!r}")

    _emit_written(doc, change, previous_version=previous_version, actor=actor, source=source, via=via)
    return doc


def create_document(
    runbook: RunbookRef,
    *,
    body: str,
    title: str,
    key: Optional[str] = None,
    section: SectionRef = None,
    description: str = "",
    source: str = "",
    via: str = "web",
    is_generated: bool = True,
    doc_type: str = "",
    locked: bool = False,
    actor: Actor = None,
) -> Document:
    """Create a logical Document + its first version and emit ``document_written``."""
    rb = _resolve_runbook(runbook)
    if actor is not None and not permissions.can_edit(actor, rb):
        # Same existence-hiding rule as _check_writable: a caller who can't view
        # the target runbook gets not-found (never a leak); one who can view but
        # not edit gets 403.
        if not permissions.can_view(actor, rb):
            raise RunbookNotFound(f"No runbook with slug {rb.slug!r}.")
        raise NotAuthorized(f"You do not have permission to add documents to '{rb.slug}'.")
    sec = _resolve_section(rb, section)
    doc = Document.objects.create(
        runbook=rb,
        section=sec,
        key=key,
        title=title,
        description=description,
        source=source,
        via=via,
        is_generated=is_generated,
        doc_type=doc_type,
        locked=locked,
        created_by=actor,
    )
    doc.create_new_version(file=_md_file(body, doc), created_by=actor, source=source, via=via)
    _emit_written(doc, "created", previous_version=None, actor=actor, source=source, via=via)
    return doc


def attach_image(
    *,
    document: Optional[Document] = None,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    data: Optional[bytes] = None,
    file: Optional[File] = None,
    alt: str = "",
    actor: Actor = None,
) -> ImageRef:
    """Attach an image to a document and return the markdown snippet to embed."""
    doc = document if document is not None else _get_doc(runbook, key)
    content = file if file is not None else ContentFile(data or b"", name="image.png")
    image = DocumentImage.objects.create(document=doc, image=content, alt=alt, uploaded_by=actor)

    def _send() -> None:
        signals.document_image_attached.send(sender=Document, document=doc, image=image, actor=actor)

    transaction.on_commit(_send)
    url = reverse("runbook:serve_image", kwargs={"pk": image.pk})
    return ImageRef(id=image.pk, url=url, markdown=f"![{alt}]({url})")


def archive_document(
    *,
    document: Optional[Document] = None,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    actor: Actor = None,
    bypass_lock: bool = False,
) -> DocumentResult:
    """Soft-delete: hide from default listings, keep history. Idempotent."""
    doc = document if document is not None else _get_doc(runbook, key, uid=uid)
    _check_writable(doc, actor, bypass_lock)
    if not doc.is_archived:
        doc.is_archived = True
        doc.archived_at = timezone.now()
        doc.save(update_fields=["is_archived", "archived_at", "updated_at"])

        def _send() -> None:
            signals.document_archived.send(sender=Document, document=doc, actor=actor)

        transaction.on_commit(_send)
    return DocumentResult.of(doc)


def unarchive_document(
    *,
    document: Optional[Document] = None,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    actor: Actor = None,
    bypass_lock: bool = False,
) -> DocumentResult:
    """Reverse :func:`archive_document`: return a soft-deleted doc to active
    listings. Idempotent. The save re-emits the search index write (post_save),
    so the doc reappears in search as well as ``ls``."""
    doc = document if document is not None else _get_doc(runbook, key, uid=uid)
    _check_writable(doc, actor, bypass_lock)
    if doc.is_archived:
        doc.is_archived = False
        doc.archived_at = None
        doc.save(update_fields=["is_archived", "archived_at", "updated_at"])
    return DocumentResult.of(doc)


def restore_version(
    document: Optional[Document] = None,
    *,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    version: int,
    actor: Actor = None,
    via: str = "web",
    bypass_lock: bool = False,
) -> Document:
    """Roll a document back to an earlier ``version`` by snapshotting that
    version's content as a new head version (history is never rewritten). Mirrors
    the web UI's Restore action so every transport agrees. Address the document by
    a ``document`` instance or by ``runbook``/``key``/``uid``; edit rights are
    enforced by the underlying ``write_version``."""
    doc = document if document is not None else _get_doc(runbook, key, uid=uid)
    old = doc.versions.filter(version=version).first()
    if old is None:
        raise DocumentNotFound(f"Document has no version {version}.")
    old.file.open("rb")
    try:
        body = old.file.read().decode("utf-8", errors="replace")
    finally:
        old.file.close()
    return write_version(
        doc, body=body, mode="new_version",
        description=f"Restored from version {version}",
        actor=actor, via=via, bypass_lock=bypass_lock,
    )


def delete_document(
    *,
    document: Optional[Document] = None,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    force: bool = False,
    actor: Actor = None,
    bypass_lock: bool = False,
) -> None:
    """Archive by default (recoverable); ``force=True`` hard-deletes."""
    doc = document if document is not None else _get_doc(runbook, key, uid=uid)
    _check_writable(doc, actor, bypass_lock)
    if not force:
        archive_document(document=doc, actor=actor, bypass_lock=bypass_lock)
        return
    doc.delete()


# -- Keyed ops (idempotent programmatic access) -------------------------------

def _get_doc(
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    *,
    id: Optional[int] = None,
    uid: Optional[str] = None,
    viewer: Actor = None,
) -> Document:
    """Resolve a document by uid (canonical), id, or (runbook, key).

    When ``viewer`` is set (an interactive caller), a document the viewer may not
    see raises ``DocumentNotFound`` — hidden, never a permission leak. ``viewer``
    of None means a trusted/internal caller and skips the visibility check.
    """
    if uid is not None:
        doc = Document.objects.filter(uid=uid).first()
    elif id is not None:
        doc = Document.objects.filter(pk=id).first()
    elif runbook is not None and key is not None:
        doc = Document.objects.filter(runbook=_resolve_runbook(runbook), key=key).first()
    else:
        raise DocumentNotFound("Provide uid, id, or (runbook, key).")
    if doc is None:
        raise DocumentNotFound("Document not found.")
    if viewer is not None and not permissions.can_view_doc(viewer, doc):
        raise DocumentNotFound("Document not found.")
    return doc


def put_document(
    runbook: RunbookRef,
    key: str,
    *,
    body: str,
    title: Optional[str] = None,
    section: SectionRef = None,
    on_exists: OnExists = "new_version",
    expected_version: Optional[int] = None,
    source: str = "",
    via: str = "api",
    is_generated: bool = True,
    doc_type: str = "",
    locked: Optional[bool] = None,
    actor: Actor = None,
    bypass_lock: bool = False,
) -> DocumentResult:
    """Idempotent upsert of the document addressed by ``(runbook, key)``.

    Creates it if missing; otherwise applies ``on_exists``
    (``new_version`` | ``overwrite`` | ``append`` | ``append_version`` | ``fail``).
    ``append_version`` grows the head *and* snapshots a version. ``expected_version``
    is an optional optimistic lock against the current head.

    ``locked`` is a tri-state on update: ``None`` (the default) leaves the flag
    untouched, so a content-only write never silently clears a managed doc's
    lock. Pass an explicit bool to change it. On create, ``None`` means unlocked.
    """
    rb = _resolve_runbook(runbook)
    with transaction.atomic():
        doc = Document.objects.select_for_update().filter(runbook=rb, key=key).first()

        if doc is None:
            doc = create_document(
                rb,
                body=body,
                title=title or key,
                key=key,
                section=section,
                source=source,
                via=via,
                is_generated=is_generated,
                doc_type=doc_type,
                locked=bool(locked),
                actor=actor,
            )
            return DocumentResult.of(doc)

        _check_writable(doc, actor, bypass_lock)
        if on_exists == "fail":
            raise DocumentAlreadyExists(f"Document ({rb.slug!r}, {key!r}) already exists.")
        if expected_version is not None and doc.version != expected_version:
            raise VersionConflict(f"Expected version {expected_version}, head is {doc.version}.")

        meta_fields: list[str] = []
        if title is not None and title != doc.title:
            doc.title = title
            meta_fields.append("title")
        if section is not None:
            doc.section = _resolve_section(rb, section)
            meta_fields.append("section")
        if locked is not None and locked != doc.locked:
            doc.locked = locked
            meta_fields.append("locked")
        if meta_fields:
            doc.save(update_fields=[*meta_fields, "updated_at"])

        mode: WriteMode = "new_version" if on_exists == "new_version" else on_exists
        write_version(doc, body=body, mode=mode, source=source, via=via, actor=actor, bypass_lock=bypass_lock)
        return DocumentResult.of(doc)


def append_to_document(
    runbook: RunbookRef, key: str, *, body: str, **kwargs: Any
) -> DocumentResult:
    """Convenience wrapper: ``put_document(..., on_exists="append")``.

    Grows the head content in place; the version is unchanged. Use
    :func:`append_version` instead if each append should also be a new version.
    """
    return put_document(runbook, key, body=body, on_exists="append", **kwargs)


def append_version(
    runbook: RunbookRef, key: str, *, body: str, **kwargs: Any
) -> DocumentResult:
    """Append ``body`` to the head **and** snapshot a new version, in one call.

    The primitive a recurring job wants for a running, versioned log (e.g. an
    hourly status snapshot): unlike :func:`append_to_document` (grows the head,
    version unchanged) or ``on_exists="new_version"`` (snapshots but *replaces*
    the head), this both concatenates and records a version, so history keeps
    every entry. Creates the document on the first call.
    """
    return put_document(runbook, key, body=body, on_exists="append_version", **kwargs)


def get_document(
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    *,
    id: Optional[int] = None,
    uid: Optional[str] = None,
    with_body: bool = False,
    viewer: Actor = None,
) -> DocumentResult:
    return DocumentResult.of(_get_doc(runbook, key, id=id, uid=uid, viewer=viewer), with_body=with_body)


def move_document(
    *,
    document: Optional[Document] = None,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    to_runbook: Optional[RunbookRef] = None,
    to_section: SectionRef = None,
    actor: Actor = None,
    bypass_lock: bool = False,
) -> DocumentResult:
    """Re-place a document (identity via uid is unchanged).

    ``to_runbook=None`` detaches it to a standalone, uid-only document (the
    key, being namespace-scoped, is cleared). Otherwise it moves into the target
    runbook/section, guarding against a key collision there.
    """
    doc = document if document is not None else _get_doc(runbook, key, uid=uid)
    _check_writable(doc, actor, bypass_lock)
    from_runbook = doc.runbook

    if to_runbook is None:
        doc.runbook = None
        doc.section = None
        doc.key = None
    else:
        target_rb = _resolve_runbook(to_runbook)
        if actor is not None and not bypass_lock and not permissions.can_edit(actor, target_rb):
            if not permissions.can_view(actor, target_rb):
                raise RunbookNotFound(f"No runbook with slug {target_rb.slug!r}.")
            raise NotAuthorized(f"You do not have permission to move documents into '{target_rb.slug}'.")
        target_sec = _resolve_section(target_rb, to_section)
        if doc.key and Document.objects.filter(runbook=target_rb, key=doc.key).exclude(pk=doc.pk).exists():
            raise DocumentAlreadyExists(f"Key {doc.key!r} already exists in runbook {target_rb.slug!r}.")
        doc.runbook = target_rb
        doc.section = target_sec

    doc.save(update_fields=["runbook", "section", "key", "updated_at"])

    def _send() -> None:
        signals.document_moved.send(
            sender=Document, document=doc, from_runbook=from_runbook, to_runbook=doc.runbook, actor=actor
        )

    transaction.on_commit(_send)
    return DocumentResult.of(doc)


def list_documents(
    *,
    runbook: Optional[RunbookRef] = None,
    section: SectionRef = None,
    source: Optional[str] = None,
    doc_type: Optional[str] = None,
    query: Optional[str] = None,
    include_archived: bool = False,
    viewer: Actor = None,
) -> list[DocumentSummary]:
    qs = Document.objects.select_related("runbook", "section")
    if viewer is not None:
        qs = permissions.viewable_documents(viewer, qs)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    if runbook is not None:
        qs = qs.filter(runbook=_resolve_runbook(runbook))
    if section is not None:
        qs = qs.filter(section__slug=section) if isinstance(section, str) else qs.filter(section=section)
    if source:
        qs = qs.filter(source=source)
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(content_text__icontains=query))
    return [DocumentSummary.of(doc) for doc in qs]


def search_documents(
    query: str,
    *,
    viewer: Actor = None,
    runbook: Optional[RunbookRef] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> Optional[list[DocumentSummary]]:
    """Ranked full-text search (BM25 via ``apps.search``) scoped to what
    ``viewer`` may see, ordered by relevance. Returns ``None`` when the search
    engine isn't installed / ``Document`` isn't registered, so callers can fall
    back to the substring path in :func:`list_documents`.

    Unlike ``list_documents(query=…)`` (a substring ``icontains`` scan), this
    uses the shared engine's tokenized ranking — the same retrieval the omnibar
    and the ``search_runbook_documents`` MCP tool use."""
    try:
        from apps.search import registry
        from apps.search.backends import get_backend
    except ImportError:
        return None
    view = registry.get_view(Document)
    if view is None:
        return None

    hits = get_backend().query(view, query, limit=limit)
    qs = Document.objects.filter(pk__in=[h.object_id for h in hits], is_archived=False)
    if viewer is not None:
        qs = permissions.viewable_documents(viewer, qs)
    if runbook is not None:
        qs = qs.filter(runbook=_resolve_runbook(runbook))
    if source:
        qs = qs.filter(source=source)
    by_id = {d.pk: d for d in qs.select_related("runbook", "section")}
    # Preserve the engine's relevance order; drop hits filtered out by scope.
    return [DocumentSummary.of(by_id[h.object_id]) for h in hits if h.object_id in by_id]


# -- Runbook & section operations ---------------------------------------------

def create_runbook(
    slug: str,
    *,
    name: Optional[str] = None,
    description: str = "",
    owner: Actor = None,
    is_public: bool = False,
) -> Runbook:
    """Create a new runbook owned by ``owner`` (None → a staff-managed *system*
    runbook). Any authenticated caller may create one they own. Raises
    ``RunbookAlreadyExists`` if the (globally unique) slug is taken."""
    slug = slugify(slug)
    if not slug:
        raise DocumentServiceError("A runbook slug is required.")
    if Runbook.objects.filter(slug=slug).exists():
        raise RunbookAlreadyExists(f"A runbook with slug {slug!r} already exists.")
    return Runbook.objects.create(
        slug=slug, name=name or slug, description=description, owner=owner, is_public=is_public,
    )


def create_section(
    runbook: RunbookRef,
    slug: str,
    *,
    name: Optional[str] = None,
    order: int = 0,
    actor: Actor = None,
) -> Section:
    """Add a section to a runbook (idempotent by slug). Requires edit rights on
    the runbook; a caller who can't even view it gets not-found (never a leak)."""
    rb = _resolve_runbook(runbook)
    if actor is not None and not permissions.can_edit(actor, rb):
        if not permissions.can_view(actor, rb):
            raise RunbookNotFound(f"No runbook with slug {rb.slug!r}.")
        raise NotAuthorized(f"You do not have permission to modify '{rb.slug}'.")
    slug = slugify(slug)
    if not slug:
        raise DocumentServiceError("A section slug is required.")
    section, _ = Section.objects.get_or_create(
        runbook=rb, slug=slug, defaults={"name": name or slug, "order": order},
    )
    return section


def set_runbook_public(runbook: RunbookRef, *, public: bool, actor: Actor = None) -> Runbook:
    """Publish (``public=True``) or unpublish a runbook. Requires edit rights.
    Public = any signed-in user may read; editing stays owner/staff-only."""
    rb = _resolve_runbook(runbook)
    if actor is not None and not permissions.can_edit(actor, rb):
        if not permissions.can_view(actor, rb):
            raise RunbookNotFound(f"No runbook with slug {rb.slug!r}.")
        raise NotAuthorized(f"You do not have permission to modify '{rb.slug}'.")
    if rb.is_public != public:
        rb.is_public = public
        rb.save(update_fields=["is_public"])
    return rb


# -- Cloning (templates) ------------------------------------------------------

def _unique_slug(base: str) -> str:
    """A runbook slug based on ``base`` that isn't taken yet (``base``, ``base-2``…)."""
    base = base or "runbook"
    slug = base
    counter = 2
    while Runbook.objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def clone_referenced_images(body: str, source_doc: Document, target_doc: Document, actor: Actor = None) -> str:
    """Copy each image referenced in ``body`` from ``source_doc`` to ``target_doc``
    and rewrite the serve URLs, so the copy owns its own images. Returns the
    rewritten body. Only images whose serve URL appears in the body are copied
    (the same rule as ``bundle.export_bundle``), so orphans are dropped.
    """
    for image in source_doc.images.all():
        serve_url = reverse("runbook:serve_image", kwargs={"pk": image.pk})
        if serve_url not in body:
            continue
        image.image.open("rb")
        try:
            data = image.image.read()
        finally:
            image.image.close()
        name = os.path.basename(image.image.name) or "image.png"
        new_image = DocumentImage.objects.create(
            document=target_doc, image=ContentFile(data, name=name), alt=image.alt, uploaded_by=actor
        )
        new_serve_url = reverse("runbook:serve_image", kwargs={"pk": new_image.pk})
        body = body.replace(serve_url, new_serve_url)
    return body


def list_template_documents(viewer: Actor = None) -> QuerySet[Document]:
    """Documents usable as page templates: explicitly flagged (``is_template``) or
    living in a template runbook. Archived docs excluded; ordered by runbook, title.

    When ``viewer`` is set, only templates that viewer may see are offered."""
    qs = (
        Document.objects.filter(Q(is_template=True) | Q(runbook__is_template=True), is_archived=False)
        .select_related("runbook")
        .order_by("runbook__name", "title")
    )
    if viewer is not None:
        qs = permissions.viewable_documents(viewer, qs)
    return qs


def create_from_template(
    runbook: RunbookRef,
    *,
    title: str,
    template: Document,
    section: SectionRef = None,
    description: str = "",
    actor: Actor = None,
) -> Document:
    """Create a new page in ``runbook`` seeded from ``template``'s current content.

    The new page gets its **own** copies of any images the template referenced, so
    it's independent of the template. ``description`` sets the new page's one-line
    summary (the template's body is the content). Returns the new Document.
    """
    rb = _resolve_runbook(runbook)
    body = read_head(template) or f"# {title}\n\n"
    doc = create_document(
        rb, body=body, title=title, section=section, description=description,
        doc_type=template.doc_type, is_generated=False, via="web", actor=actor,
    )
    rewritten = clone_referenced_images(body, template, doc, actor)
    if rewritten != body:
        write_version(doc, body=rewritten, mode="overwrite", via="web", actor=actor)
    return doc


def copy_document(
    source: Optional[Document] = None,
    *,
    runbook: Optional[RunbookRef] = None,
    key: Optional[str] = None,
    uid: Optional[str] = None,
    viewer: Actor = None,
    to_runbook: RunbookRef,
    to_key: str,
    title: Optional[str] = None,
    section: SectionRef = None,
    on_exists: OnExists = "fail",
    via: str = "api",
    actor: Actor = None,
) -> DocumentResult:
    """Copy the source's current content into ``(to_runbook, to_key)`` as an
    independent document. Address the source by a ``source`` instance or by
    ``runbook``/``key``/``uid``; pass ``viewer`` to require the caller can see the
    source (a hidden source raises ``DocumentNotFound``, never a leak). The copy
    gets its **own** copies of any images the source referenced, so the two never
    share storage. ``on_exists`` defaults to ``fail`` (never clobber silently).
    Authorization on the *target* runbook is enforced by :func:`put_document`."""
    src = source if source is not None else _get_doc(runbook, key, uid=uid, viewer=viewer)
    rb = _resolve_runbook(to_runbook)
    body = read_head(src)
    result = put_document(
        rb.slug, to_key, body=body, title=title or src.title,
        section=section, on_exists=on_exists, doc_type=src.doc_type,
        source=src.source, via=via, actor=actor,
    )
    target = Document.objects.get(uid=result.uid)
    rewritten = clone_referenced_images(body, src, target, actor)
    if rewritten != body:
        write_version(target, body=rewritten, mode="overwrite", via=via, actor=actor)
        result = DocumentResult.of(target)
    return result


@transaction.atomic
def clone_runbook(
    source: RunbookRef,
    *,
    new_slug: Optional[str] = None,
    new_name: Optional[str] = None,
    as_template: bool = False,
    copy_locked: bool = False,
    actor: Actor = None,
    owner: Actor = None,
) -> Runbook:
    """Deep-copy a runbook (sections + non-archived docs + their images) into a
    fresh runbook, leaving the source untouched.

    Powers "make template" (``as_template=True``) and "new runbook from template"
    (``as_template=False``). Each doc is copied by snapshotting its current head
    content, and gets its **own** image rows so nothing is shared with the source.
    No document events are emitted (this is a bulk copy). Because the target is a
    brand-new empty runbook, reusing each doc's ``key`` can never collide.
    """
    src = _resolve_runbook(source)
    target = Runbook.objects.create(
        name=new_name or src.name,
        slug=new_slug or _unique_slug(slugify(new_name) if new_name else src.slug),
        description=src.description,
        icon=src.icon,
        owner=owner,
        is_template=as_template,
        default_max_versions=src.default_max_versions,
        default_max_version_age_days=src.default_max_version_age_days,
        default_ttl_days=src.default_ttl_days,
    )

    section_map: dict[int, Section] = {}
    for sec in src.sections.order_by("order", "name"):
        section_map[sec.pk] = Section.objects.create(
            runbook=target, name=sec.name, slug=sec.slug,
            description=sec.description, icon=sec.icon, order=sec.order,
        )

    docs = (
        Document.objects.filter(runbook=src, is_archived=False)
        .select_related("section")
        .prefetch_related("images")
        .order_by("pk")
    )
    for doc in docs:
        new_doc = Document.objects.create(
            runbook=target,
            section=section_map.get(doc.section_id),
            key=doc.key,
            title=doc.title,
            slug=doc.slug,
            description=doc.description,
            doc_type=doc.doc_type,
            is_generated=doc.is_generated,
            source=doc.source,
            via="clone",
            locked=doc.locked and copy_locked,
            created_by=actor,
        )
        body = clone_referenced_images(read_head(doc), doc, new_doc, actor)
        new_doc.create_new_version(file=_md_file(body, new_doc), created_by=actor, source=doc.source, via="clone")

    return target
