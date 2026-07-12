"""Runbook models — Runbook, Section, and Document."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.core.files import File
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Runbook(models.Model):
    """A collection of sections and documents."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)

    # Ownership + visibility. owner=NULL is a "system" runbook (staff-managed);
    # owner=<user> is a personal runbook that user controls. is_public is the
    # publish flag: private by default (owner + staff only), public means any
    # authenticated user may read it (editing stays owner/staff-only). Sections
    # and Documents inherit these via their runbook — see permissions.py.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runbooks",
    )
    is_public = models.BooleanField(default=False)

    # A template runbook is a reusable blueprint: its documents seed new documents
    # (via the create-from-scratch picker) and the whole thing can be instantiated
    # into a fresh runbook. Template runbooks live in a separate Templates area.
    is_template = models.BooleanField(default=False)

    # Retention defaults for documents in this runbook (null → fall back to the
    # global default keyed by is_generated). Doc-level values override these.
    # This is the downstream lever: e.g. an "ephemeral-status" runbook can set
    # default_ttl_days=7 for everything inside it.
    default_max_versions = models.IntegerField(null=True, blank=True)
    default_max_version_age_days = models.IntegerField(null=True, blank=True)
    default_ttl_days = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("runbook:runbook_detail", kwargs={"slug": self.slug})


class Section(models.Model):
    """Organizational grouping for documents within a runbook."""

    runbook = models.ForeignKey(
        Runbook,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("runbook", "slug")]

    def __str__(self) -> str:
        return self.name

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("runbook:runbook_detail", kwargs={"slug": self.runbook.slug}) + f"#{self.slug}"


ALLOWED_EXTENSIONS: list[str] = ["md"]
FILE_TYPE_CHOICES = [("md", "Markdown")]


class Document(models.Model):
    """A logical markdown document — stable identity with a chain of versions.

    Addressed by ``(runbook, key)`` for programmatic/idempotent writes. Content
    lives in :class:`DocumentVersion`; the head is ``current_version``. Head
    fields (``title``, ``file_type``, ``content_text``, ``version``) are
    denormalised here for cheap display/search, kept in sync on every write.
    Images attach to the Document and are shared across all versions.

    Retention/lifecycle fields land now but stay dormant until later phases.
    """

    ON_EXPIRE_CHOICES = [("archive", "Archive"), ("delete", "Delete")]

    # -- Identity & placement --
    # uid is the canonical, container-independent address: it survives moves,
    # detaching from a runbook, and having no runbook at all. (runbook, key) is
    # a convenience alias that only means something within a runbook namespace.
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    runbook = models.ForeignKey(
        Runbook,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    key = models.SlugField(max_length=200, null=True, blank=True, help_text="Stable handle, unique per runbook.")
    external_id = models.CharField(max_length=200, blank=True, db_index=True)
    slug = models.SlugField(max_length=200)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # -- Head pointer + denormalised head fields --
    current_version = models.ForeignKey(
        "DocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    version = models.IntegerField(default=1)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, editable=False, blank=True)
    content_text = models.TextField(blank=True, editable=False, help_text="Head plaintext for search.")

    # -- Provenance & classification --
    is_generated = models.BooleanField(default=False)
    # A template page: a reusable starting point offered in the "New Page" dialog.
    # The page stays in its runbook; docs inside a template runbook are templates too.
    is_template = models.BooleanField(default=False)
    doc_type = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=100, blank=True)
    via = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="runbook_documents",
    )

    # -- Lifecycle --
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    # locked = read-only in the UI/API/MCP; only a superuser may change it.
    # Set on app-documentation bundles imported into a runbook; the bundle in
    # the app repo is the source of truth, so the projected doc is read-only.
    locked = models.BooleanField(default=False)

    # -- Retention (dormant until the retention phase) --
    max_versions = models.IntegerField(null=True, blank=True)
    max_version_age_days = models.IntegerField(null=True, blank=True)
    ttl_days = models.IntegerField(null=True, blank=True)
    on_expire = models.CharField(max_length=10, choices=ON_EXPIRE_CHOICES, default="archive")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["runbook", "key"],
                condition=models.Q(key__isnull=False),
                name="uniq_runbook_key",
            ),
        ]
        indexes = [
            models.Index(fields=["is_archived"], name="ss_rb_doc_archived_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} (v{self.version})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("runbook:document_detail", kwargs={"pk": self.pk})

    # -- Compatibility accessors (keep existing views/templates working) --
    @property
    def file(self) -> Optional[File]:
        """The head version's file (read-only). Writers go through versions."""
        return self.current_version.file if self.current_version_id else None

    @property
    def is_markdown(self) -> bool:
        return self.file_type == "md"

    @property
    def is_pdf(self) -> bool:
        return self.file_type == "pdf"

    @property
    def is_docx(self) -> bool:
        return self.file_type in ("docx", "doc")

    @property
    def search_subtitle_text(self) -> str:
        """Composite subtitle for search hits ("Runbook · Section").

        The search engine's ``search_subtitle`` is a single field/attr path, so
        this property joins runbook + section into one string for the hit line.
        """
        parts = []
        if self.runbook_id:
            parts.append(self.runbook.name)
        if self.section_id:
            parts.append(self.section.name)
        return " · ".join(parts)

    # -- Versioning --
    def _sync_head(self, version: DocumentVersion) -> None:
        """Point at ``version`` and refresh denormalised head fields."""
        self.current_version = version
        self.version = version.version
        self.file_type = version.file_type
        self.content_text = version.content_text
        self.save(update_fields=["current_version", "version", "file_type", "content_text", "updated_at"])

    def create_new_version(
        self,
        *,
        file: File,
        created_by: Optional[AbstractBaseUser] = None,
        description: str = "",
        source: str = "",
        via: str = "web",
    ) -> Document:
        """Create the next version from ``file``, advance the head, return ``self``.

        The first call on a fresh document (no ``current_version``) produces v1.
        """
        next_version = (self.current_version.version + 1) if self.current_version_id else 1
        version = DocumentVersion(
            document=self,
            version=next_version,
            file=file,
            title=self.title,
            description=description,
            created_by=created_by,
            source=source,
            via=via,
        )
        version.save()
        self._sync_head(version)
        return self


class DocumentVersion(models.Model):
    """An immutable content snapshot of a :class:`Document`."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.IntegerField()
    file = models.FileField(
        upload_to="runbook/",
        validators=[FileExtensionValidator(allowed_extensions=ALLOWED_EXTENSIONS)],
    )
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, editable=False, blank=True)
    content_text = models.TextField(blank=True, editable=False)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True, help_text="Per-version note / changelog.")
    source = models.CharField(max_length=100, blank=True)
    via = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="runbook_document_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="uniq_document_version"),
        ]

    def __str__(self) -> str:
        return f"{self.title or self.document_id} v{self.version}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.file and not self.file_type:
            self.file_type = self.file.name.rsplit(".", 1)[-1].lower()
        # Extract searchable text on create/upload. Callers writing the file
        # content directly (in-place editor) pass skip_content_extract=True.
        if self.file and not kwargs.pop("skip_content_extract", False):
            self.content_text = self.extract_text()
        super().save(*args, **kwargs)

    def extract_text(self) -> str:
        """Read the markdown file and return plaintext for search indexing."""
        try:
            raw = self.file.read().decode("utf-8")
            self.file.seek(0)
            return strip_frontmatter(raw)
        except Exception:
            return ""

    @property
    def is_current(self) -> bool:
        return self.document.current_version_id == self.pk

    def get_absolute_url(self) -> str:
        return self.document.get_absolute_url()


class DocumentImage(models.Model):
    """An image asset attached to a document, for use in its markdown.

    Images attach to the logical :class:`Document`, so they are shared across
    every version and are never pruned by version retention. Treated as
    immutable/append-only — "replacing" an image means uploading a new one and
    referencing it in a new version, preserving the fidelity of older versions.

    Served only through the access-checked ``serve_image`` view, never the
    public ``MEDIA`` path.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="runbook/images/%Y/%m/")
    alt = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="runbook_images",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.image.name

    def get_absolute_url(self) -> str:
        return reverse("runbook:serve_image", kwargs={"pk": self.pk})


class Subscription(models.Model):
    """A user's subscription to a document's updates.

    Consumed by the ``document_written`` fan-out (see ``subscriptions`` +
    ``receivers``): a demonstration of the extension seam — downstream apps
    build emailers/formatters/etc. the same way, without touching the write path.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    subscriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="runbook_subscriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("document", "subscriber")]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.subscriber} → {self.document}"


_FM_KEYVAL = re.compile(r"[\w.\-]+\s*:\s*.*")
_FM_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block from markdown text.

    Robust to:
      * CRLF / LF line endings and a leading BOM,
      * blank lines or a standalone image before the block — an image
        inserted at the top of a document is a common way the frontmatter
        gets pushed below the first line (and then rendered as body text).

    Only a ``---`` fenced block whose body is entirely ``key: value`` lines
    is treated as frontmatter, so genuine ``---`` thematic breaks with prose
    between them are left untouched.
    """
    if text.startswith("\ufeff"):
        text = text[1:]

    lines = text.splitlines(keepends=True)
    i = 0
    # Skip leading blank lines and standalone images (kept in the output).
    while i < len(lines) and (not lines[i].strip() or _FM_IMAGE.fullmatch(lines[i].strip())):
        i += 1

    if i < len(lines) and lines[i].strip() == "---":
        j = i + 1
        while j < len(lines) and lines[j].strip() != "---":
            j += 1
        if j < len(lines):  # found the closing fence
            body = [ln.strip() for ln in lines[i + 1:j] if ln.strip()]
            if body and all(_FM_KEYVAL.fullmatch(ln) for ln in body):
                kept = lines[:i] + lines[j + 1:]
                return "".join(kept).strip()

    return text.strip()
