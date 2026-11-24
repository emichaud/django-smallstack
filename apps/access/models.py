"""Access control records: the audit trail of who may do what, and the groups
an app declares in code.

Django's Groups and Permissions stay the source of truth for access. This app
adds the two things they lack: a durable, typed record of every change to
them (``AccessEvent``), and a way for an app to ship a group with its
permissions and keep it in step (``ManagedGroup``, declared with
``register_group``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class AccessEvent(models.Model):
    """One change to someone's access, from whatever surface made it.

    Written by the signal receivers in :mod:`apps.access.signals`, so a change
    made in Django admin, the Access pages, the User Manager, a shell or a
    directory sync is recorded the same way. Names are stored as text beside
    the foreign keys so the record outlives a deleted user or group.
    """

    class Kind(models.TextChoices):
        GROUP_ADDED = "group_added", "Added to group"
        GROUP_REMOVED = "group_removed", "Removed from group"
        PERMISSION_ADDED = "permission_added", "Permission granted directly"
        PERMISSION_REMOVED = "permission_removed", "Direct permission removed"
        GROUP_PERMISSION_ADDED = "group_permission_added", "Permission added to group"
        GROUP_PERMISSION_REMOVED = "group_permission_removed", "Permission removed from group"
        STAFF_ON = "staff_on", "Made staff"
        STAFF_OFF = "staff_off", "Staff removed"
        SUPERUSER_ON = "superuser_on", "Made superuser"
        SUPERUSER_OFF = "superuser_off", "Superuser removed"
        ACTIVATED = "activated", "Account activated"
        DEACTIVATED = "deactivated", "Account deactivated"
        TOKEN_REVOKED = "token_revoked", "API token revoked"
        SESSIONS_ENDED = "sessions_ended", "Sessions ended"
        GROUP_CREATED = "group_created", "Group created"
        GROUP_DELETED = "group_deleted", "Group deleted"
        GROUP_RENAMED = "group_renamed", "Group renamed"
        USER_CREATED = "user_created", "Account created"
        USER_DELETED = "user_deleted", "Account deleted"
        REVIEW_SIGNED = "review_signed", "Access review signed"
        DIRECTORY_ROLE_SET = "directory_role_set", "Directory role set"

    #: Kinds that widen access. They log at WARNING and head the review list.
    GRANTS = frozenset(
        {
            Kind.GROUP_ADDED,
            Kind.PERMISSION_ADDED,
            Kind.GROUP_PERMISSION_ADDED,
            Kind.STAFF_ON,
            Kind.SUPERUSER_ON,
            Kind.ACTIVATED,
        }
    )

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_changes_made",
    )
    actor_label = models.CharField(max_length=150, blank=True)
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_events",
    )
    subject_label = models.CharField(max_length=150, blank=True, db_index=True)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_events")
    group_label = models.CharField(max_length=150, blank=True, db_index=True)
    #: ``app_label.codename`` for permission events.
    permission = models.CharField(max_length=200, blank=True, db_index=True)
    #: Where the change came from: ``web:<path>``, ``shell``, ``migrate``,
    #: ``directory:<provider>``, ``system``.
    source = models.CharField(max_length=200, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-pk"]
        verbose_name = "access event"
        verbose_name_plural = "access events"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.subject_label or self.group_label}"

    @property
    def is_grant(self) -> bool:
        return self.kind in self.GRANTS

    @property
    def object_label(self) -> str:
        """What the event is about: the group, the permission, or the account."""
        if self.permission:
            return self.permission
        if self.group_label and self.subject_label:
            return self.group_label
        return self.group_label or self.subject_label


class ManagedGroup(models.Model):
    """A group whose definition lives somewhere other than its own rows: one an
    app declares in code with ``register_group`` (``source="code"``), or one
    made on the Access pages and marked directory-managed there
    (``source="page"``, the page's equivalent of ``directory_role=``).

    ``declared_permissions`` is what the declaration said at the last sync, so
    the next sync can tell a permission the code dropped (removed from the
    group) from one an administrator added by hand (kept). A page group has
    no declaration: its permissions are whatever the page set, never drift.
    """

    class Source(models.TextChoices):
        CODE = "code", "Declared in code"
        PAGE = "page", "Set on the Access pages"

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="managed")
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.CODE)
    description = models.CharField(max_length=300, blank=True)
    #: The app whose ``groups.py`` declared it.
    app_label = models.CharField(max_length=100, blank=True)
    declared_permissions = models.JSONField(default=list, blank=True)
    #: The key the directory sends for this group (an Entra app-role value, an
    #: Okta group name): membership is then set at sign-in by
    #: :func:`apps.access.directory.sync_roles` and refused here. ``None`` for
    #: a group managed locally (NULL, not "", so the unique constraint holds
    #: on every database).
    directory_role = models.CharField(max_length=100, null=True, blank=True)
    #: Members are staff: the directory sync sets ``is_staff`` when it adds one.
    grants_staff = models.BooleanField(default=False)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["group__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["directory_role"],
                condition=models.Q(directory_role__isnull=False),
                name="access_managedgroup_directory_role_uniq",
            )
        ]

    def __str__(self) -> str:
        return self.group.name

    @property
    def directory_managed(self) -> bool:
        return bool(self.directory_role)

    @property
    def from_code(self) -> bool:
        return self.source == self.Source.CODE

    def drift(self) -> dict[str, list[str]]:
        """Permissions on the group that differ from the declaration:
        ``{"added": [...], "missing": [...]}`` as ``app_label.codename``.
        Empty for a page group: it has no declaration to differ from."""
        if not self.from_code:
            return {"added": [], "missing": []}
        current = {
            f"{p.content_type.app_label}.{p.codename}" for p in self.group.permissions.select_related("content_type")
        }
        declared = set(self.declared_permissions or [])
        return {"added": sorted(current - declared), "missing": sorted(declared - current)}

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group.name,
            "source": self.source,
            "app_label": self.app_label,
            "description": self.description,
            "declared_permissions": list(self.declared_permissions or []),
            "directory_role": self.directory_role or "",
            "grants_staff": self.grants_staff,
        }


class DirectoryIdentity(models.Model):
    """Who an account is to an identity provider: the provider's stable subject
    (Entra ``oid``, an OIDC ``sub``), never the email, which can be renamed or
    reissued to someone else. Written by :func:`apps.access.directory.resolve_identity`
    at sign-in; ``last_roles`` is what the provider said that time, kept so the
    review can show a role value no group matches and an account the directory
    hasn't vouched for in a while.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="directory_identities")
    #: ``entra``, ``okta``, ``google``…: the ``<provider>`` in ``directory:<provider>``.
    provider = models.CharField(max_length=50)
    subject = models.CharField(max_length=255)
    email = models.CharField(max_length=254, blank=True)
    display_name = models.CharField(max_length=150, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(db_index=True)
    #: The role values the provider sent at the last sync (after the alias map).
    last_roles = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["provider", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="access_directoryidentity_subject_uniq")
        ]
        verbose_name = "directory identity"
        verbose_name_plural = "directory identities"

    def __str__(self) -> str:
        return f"{self.provider}:{self.subject}"


class ReviewLocked(Exception):
    """A signed review, or an item of one, is evidence: it can't be changed or deleted."""


class _ReviewQuerySet(models.QuerySet):
    """``update()`` / ``delete()`` refuse when the rows include a signed review
    (T3-1): the per-object lock alone left the bulk paths open. A migration or
    a test that must rewrite history uses ``AccessReview._base_manager``."""

    def _signed(self) -> models.QuerySet:
        return self.filter(status="signed")

    def update(self, **kwargs: Any) -> int:
        if self._signed().exists():
            raise ReviewLocked("A signed review can't be changed.")
        self._guard_status(kwargs)
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        if self._signed().exists():
            raise ReviewLocked("A signed review can't be deleted.")
        return super().delete()

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        objs = list(objs)
        if kwargs.get("update_conflicts") or any(getattr(o, "status", "") == "signed" for o in objs):
            raise ReviewLocked("Reviews are opened and signed through apps.access.reviews, not in bulk.")
        return super().bulk_create(objs, *args, **kwargs)

    def bulk_update(self, objs: Any, fields: Any, *args: Any, **kwargs: Any) -> Any:
        objs = list(objs)
        if "status" in fields or any(getattr(o, "status", "") == "signed" for o in objs):
            # Opening and signing are apps.access.reviews' acts (G5-3).
            raise ReviewLocked("A review's status changes through apps.access.reviews, not bulk_update().")
        if self.filter(pk__in=[o.pk for o in objs], status="signed").exists():
            raise ReviewLocked("A signed review can't be changed.")
        return super().bulk_update(objs, fields, *args, **kwargs)

    def _guard_status(self, kwargs: dict[str, Any]) -> None:
        # A signature is reviews.sign()'s act (it records who, when, what was
        # typed and the counts); a bulk status flip would fake one (G4-2).
        if kwargs.get("status") == "signed":
            raise ReviewLocked("A review is signed through apps.access.reviews.sign, not by update().")


class _ReviewItemQuerySet(models.QuerySet):
    """The same for the items of a signed review."""

    def _signed(self) -> models.QuerySet:
        return self.filter(review__status="signed")

    def update(self, **kwargs: Any) -> int:
        if self._signed().exists():
            raise ReviewLocked("Items of a signed review can't be changed.")
        return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        if self._signed().exists():
            raise ReviewLocked("Items of a signed review can't be deleted.")
        return super().delete()

    def bulk_create(self, objs: Any, *args: Any, **kwargs: Any) -> Any:
        objs = list(objs)
        review_ids = {o.review_id for o in objs if getattr(o, "review_id", None)}
        if kwargs.get("update_conflicts") or AccessReview.objects.filter(pk__in=review_ids, status="signed").exists():
            raise ReviewLocked("Items can't be added to, or rewritten on, a signed review (G4-2).")
        return super().bulk_create(objs, *args, **kwargs)


class AccessReview(models.Model):
    """One periodic access review (attestation): a frozen roster of who held
    access when it was opened, a named reviewer's decision on each row, and a
    signature. Writes go through :mod:`apps.access.reviews`; once signed the
    review and its items refuse every change (:class:`ReviewLocked`).
    """

    class Scope(models.TextChoices):
        PRIVILEGED = "privileged", "Privileged accounts"
        ALL = "all", "All active accounts"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SIGNED = "signed", "Signed"

    class Via(models.TextChoices):
        WEB = "web", "the Reviews page"
        CLI = "cli", "the command line"
        SCHEDULE = "schedule", "the schedule"

    period_start = models.DateField()
    period_end = models.DateField()
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.PRIVILEGED)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN, db_index=True)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_reviews_opened"
    )
    opened_by_label = models.CharField(max_length=150, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    opened_via = models.CharField(max_length=10, choices=Via.choices, default=Via.WEB)
    #: What the cadence (:mod:`apps.access.cadence`) has done about an open
    #: review: when the attesters were last reminded, how often, and when it
    #: was escalated as overdue. Nothing here once signed.
    reminded_at = models.DateTimeField(null=True, blank=True)
    reminders = models.PositiveSmallIntegerField(default=0)
    escalated_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_reviews_signed"
    )
    signed_by_label = models.CharField(max_length=150, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    #: The name the signer typed, as they typed it.
    signed_name = models.CharField(max_length=150, blank=True)
    signed_from = models.CharField(max_length=64, blank=True)
    note = models.TextField(blank=True)
    #: The request that opened the review (``signed_request_id`` is the signing's).
    request_id = models.CharField(max_length=64, blank=True)
    signed_request_id = models.CharField(max_length=64, blank=True)

    objects = _ReviewQuerySet.as_manager()
    #: Counts at signing (``items``, ``confirmed``, ``remove``, ``flagged``) and
    #: the delta against the previous signed review (``new``, ``gone``).
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-period_end", "-pk"]
        permissions = [("sign_accessreview", "Can decide and sign an access review")]
        verbose_name = "access review"
        verbose_name_plural = "access reviews"

    def __str__(self) -> str:
        return f"Access review {self.period_start:%b %d, %Y} – {self.period_end:%b %d, %Y} ({self.get_scope_display()})"

    @property
    def is_signed(self) -> bool:
        return self.status == self.Status.SIGNED

    @property
    def period_label(self) -> str:
        return f"{self.period_start:%b %d, %Y} – {self.period_end:%b %d, %Y}"

    def _locked(self) -> bool:
        if self.pk is None:
            return False
        return AccessReview.objects.filter(pk=self.pk, status=self.Status.SIGNED).exists()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._locked():
            raise ReviewLocked(f"{self} is signed and can't be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self._locked():
            raise ReviewLocked(f"{self} is signed and can't be deleted.")
        return super().delete(*args, **kwargs)


class AccessReviewItem(models.Model):
    """One account on a review's roster, and what the reviewer decided."""

    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        REMOVE = "remove", "Remove"
        FLAGGED = "flagged", "Flagged"

    review = models.ForeignKey(AccessReview, on_delete=models.CASCADE, related_name="items")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="access_review_items"
    )
    user_label = models.CharField(max_length=150, db_index=True)
    #: The account as it was when the review opened: flags, groups, direct
    #: permissions, counts, last sign-in, tokens, directory sightings, grants
    #: in the period.
    facts = models.JSONField(default=dict, blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING, db_index=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by_label = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    #: What a *remove* decision set in motion: ``approval:<id>``.
    follow_up = models.CharField(max_length=100, blank=True)

    objects = _ReviewItemQuerySet.as_manager()

    class Meta:
        ordering = ["user_label"]
        constraints = [models.UniqueConstraint(fields=["review", "user_label"], name="access_reviewitem_user_uniq")]

    def __str__(self) -> str:
        return f"{self.user_label}: {self.get_decision_display()}"

    @property
    def is_decided(self) -> bool:
        return self.decision != self.Decision.PENDING

    def _locked(self) -> bool:
        return bool(self.review_id) and (
            AccessReview.objects.filter(pk=self.review_id, status=AccessReview.Status.SIGNED).exists()
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._locked():
            raise ReviewLocked(f"{self.review} is signed; its items can't be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self._locked():
            raise ReviewLocked(f"{self.review} is signed; its items can't be deleted.")
        return super().delete(*args, **kwargs)


def _bundle_path(instance: EvidenceBundle, filename: str) -> str:
    # Under a private media prefix (SMALLSTACK_PRIVATE_MEDIA_PREFIXES): the
    # public /media/ route refuses it; the download view checks access.
    return f"access/evidence/{filename}"


class EvidenceBundle(models.Model):
    """A stored evidence pack: the ZIP :func:`apps.access.evidence.bundle_zip`
    built for a period, kept with its SHA-256 so a copy handed to an auditor
    can be checked against what the system produced. Built by the schedule
    when a quarter closes and when a review is signed, or on request; never
    edited; removed only by retention (:func:`apps.access.cadence.prune_bundles`).
    """

    class Reason(models.TextChoices):
        PERIOD_CLOSED = "period_closed", "Period closed"
        REVIEW_SIGNED = "review_signed", "Review signed"
        MANUAL = "manual", "On request"

    period_start = models.DateField()
    period_end = models.DateField()
    scope = models.CharField(max_length=16, choices=AccessReview.Scope.choices, default=AccessReview.Scope.PRIVILEGED)
    reason = models.CharField(max_length=16, choices=Reason.choices, default=Reason.MANUAL)
    review = models.ForeignKey(AccessReview, null=True, blank=True, on_delete=models.SET_NULL, related_name="bundles")
    built_at = models.DateTimeField(auto_now_add=True, db_index=True)
    built_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    built_by_label = models.CharField(max_length=150, blank=True)
    file = models.FileField(upload_to=_bundle_path)
    size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    #: Row counts per sheet at build time (``{"roster": 7, ...}``).
    counts = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-built_at", "-pk"]
        verbose_name = "evidence bundle"
        verbose_name_plural = "evidence bundles"

    def __str__(self) -> str:
        return f"Evidence {self.period_label} ({self.scope}, {self.built_at:%Y-%m-%d})"

    @property
    def period_label(self) -> str:
        return f"{self.period_start:%b %d, %Y} – {self.period_end:%b %d, %Y}"

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        storage, name = self.file.storage, self.file.name
        result = super().delete(*args, **kwargs)
        if name:
            storage.delete(name)
        return result
