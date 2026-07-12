"""Ownership + visibility authorization — the single source of truth.

A runbook has an ``owner`` (NULL = a staff-managed "system" runbook) and an
``is_public`` flag (the publish toggle; private by default). Sections and
Documents inherit these via their runbook. The rules, applied uniformly to
system and personal runbooks:

- **view** = staff, OR the runbook is public, OR you are the owner
- **edit** = staff, OR you are the owner  (owner-NULL/system + detached docs ⇒ staff-only)

These are pure functions (no request objects) so the service layer, views,
REST, and MCP can all share them. Reads that a viewer may not see are hidden
from their querysets and 404 on direct access — never leak existence.
"""

from __future__ import annotations

from typing import Any, Optional

from django.db.models import Q, QuerySet

from .models import Document, Runbook


def _uid(user: Any) -> Optional[int]:
    """The user's pk, or None for AnonymousUser / None."""
    return getattr(user, "id", None)


def is_staff(user: Any) -> bool:
    return bool(getattr(user, "is_staff", False))


# -- Object-level checks ------------------------------------------------------


def can_view(user: Any, runbook: Optional[Runbook]) -> bool:
    """May ``user`` read this runbook (and everything inheriting from it)?

    "Public" means readable by any *signed-in* user — anonymous callers get
    nothing (the runbook surface is login-gated anyway). Keeps this layer
    consistent with ``DocumentSearchConfig.search_access = "authenticated"`` and
    the ``Runbook.is_public`` model docstring.
    """
    if runbook is None:  # detached document's runbook — staff-only
        return is_staff(user)
    if is_staff(user):
        return True
    if _uid(user) is None:  # anonymous — public is signed-in-only
        return False
    if runbook.is_public:
        return True
    return runbook.owner_id is not None and runbook.owner_id == _uid(user)


def can_edit(user: Any, runbook: Optional[Runbook]) -> bool:
    """May ``user`` create/change/delete within this runbook?"""
    if runbook is None:  # detached doc / no runbook — staff-only
        return is_staff(user)
    if is_staff(user):
        return True
    return runbook.owner_id is not None and runbook.owner_id == _uid(user)


def runbook_of(doc: Document) -> Optional[Runbook]:
    """Resolve a document's governing runbook (directly, or via its section).

    Mirrors ``DocumentUpdateView._runbook()`` so section-only-attached docs
    resolve correctly.
    """
    if doc.runbook_id:
        return doc.runbook
    if doc.section_id:
        return doc.section.runbook
    return None


def can_view_doc(user: Any, doc: Document) -> bool:
    return can_view(user, runbook_of(doc))


def can_edit_doc(user: Any, doc: Document) -> bool:
    return can_edit(user, runbook_of(doc))


# -- Queryset scopers ---------------------------------------------------------


def viewable_runbooks(user: Any, qs: Optional[QuerySet[Runbook]] = None) -> QuerySet[Runbook]:
    """Restrict a Runbook queryset to what ``user`` may view."""
    qs = Runbook.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    if _uid(user) is None:  # anonymous — public is signed-in-only, so nothing
        return qs.none()
    return qs.filter(Q(is_public=True) | Q(owner_id=user.id))


def viewable_documents(user: Any, qs: Optional[QuerySet[Document]] = None) -> QuerySet[Document]:
    """Restrict a Document queryset to what ``user`` may view.

    Non-staff scoping goes through ``runbook__*``, which naturally excludes
    detached documents (``runbook_id IS NULL``) — those stay staff-only.
    """
    qs = Document.objects.all() if qs is None else qs
    if is_staff(user):
        return qs
    if _uid(user) is None:  # anonymous — public is signed-in-only, so nothing
        return qs.none()
    return qs.filter(Q(runbook__is_public=True) | Q(runbook__owner_id=user.id))
