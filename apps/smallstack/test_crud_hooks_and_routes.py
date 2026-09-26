"""Two base-wide CRUDView regressions found while testing approvals (2026-09-25).

* **F-05** — ``on_form_valid`` was documented as "callback after successful
  create/update" with no caveat, but fired only from REST, MCP and bulk update.
  The primary (web) path skipped it, so every CRUDView using it to stamp an
  owner / denormalise / file an approval had a data-integrity hole reachable
  from the UI.
* **F-22** — detail routes were registered with a bare ``<pk>`` (the ``str``
  converter), so any non-numeric segment reached the ORM and raised
  ``ValueError: Field 'id' expected a number``: a 500 in error monitoring for
  every CRUDView, triggerable by a crawler or a typo.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.webhooks.models import WebhookReceiver
from apps.webhooks.views import WebhookReceiverCRUDView

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff():
    return User.objects.create_user("crud-hooks-staff", password="p", is_staff=True)


# --- F-05 -------------------------------------------------------------------


def test_on_form_valid_fires_from_the_html_create_view(client, staff, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        WebhookReceiverCRUDView,
        "on_form_valid",
        classmethod(lambda cls, request, form, obj, is_create=False: calls.append(
            (obj.pk, is_create)
        )),
    )
    client.force_login(staff)
    resp = client.post(
        reverse("webhooks/receivers-create"),
        {
            "name": "hook via html",
            "slug": "hook-via-html",
            "signature_header": "X-Signature",
            "require_signature": "on",
            "verifier": "hmac",
            "enabled": "on",
        },
    )
    assert resp.status_code == 302, resp.content
    obj = WebhookReceiver.objects.get(slug="hook-via-html")
    assert calls == [(obj.pk, True)]


def test_on_form_valid_fires_from_the_html_update_view(client, staff, monkeypatch):
    receiver = WebhookReceiver.objects.create(name="edit me", slug="edit-me")
    calls: list = []
    monkeypatch.setattr(
        WebhookReceiverCRUDView,
        "on_form_valid",
        classmethod(lambda cls, request, form, obj, is_create=False: calls.append(
            (obj.pk, is_create)
        )),
    )
    client.force_login(staff)
    resp = client.post(
        reverse("webhooks/receivers-update", kwargs={"pk": receiver.pk}),
        {
            "name": "edited",
            "slug": "edit-me",
            "signature_header": "X-Signature",
            "require_signature": "on",
            "verifier": "hmac",
            "enabled": "on",
        },
    )
    assert resp.status_code == 302, resp.content
    assert calls == [(receiver.pk, False)]


# --- F-22 -------------------------------------------------------------------


def test_integer_pk_models_get_the_int_converter():
    assert WebhookReceiverCRUDView._pk_converter() == "int:"


def test_non_numeric_pk_404s_on_every_html_detail_route(client, staff):
    client.force_login(staff)
    base = reverse("webhooks/receivers-list")
    for suffix in ("search/", "abc/", "abc/edit/", "abc/delete/"):
        resp = client.get(base + suffix)
        assert resp.status_code == 404, (suffix, resp.status_code)


def test_numeric_pk_still_resolves(client, staff):
    receiver = WebhookReceiver.objects.create(name="live", slug="live")
    client.force_login(staff)
    url = reverse("webhooks/receivers-detail", kwargs={"pk": receiver.pk})
    assert client.get(url).status_code == 200
    # ...and a numeric pk that doesn't exist is still a 404, not a 500.
    assert client.get(url.replace(f"/{receiver.pk}/", "/9999999/")).status_code == 404


# --- F-44 -------------------------------------------------------------------
# The empty-state branch must key off *filters*, not off "any query param".
# `request.GET.urlencode` is truthy for pagination, ordering, the display
# toggle and the ?_notification= marker the notification bell appends, so a
# user who sorted an empty list or arrived from the bell was told to "clear
# your filters" and lost the create-the-first-one CTA.

_FILTERED = "Nothing matches these filters"
_UNFILTERED = "There are no"


@pytest.mark.parametrize(
    "query,expect_filtered",
    [
        ("", False),
        ("?page=1", False),
        ("?ordering=name", False),
        ("?display=cards", False),
        ("?_notification=99", False),  # the bell click-through marker
        ("?q=", False),  # an empty search box is not a filter
        ("?q=zzzznomatch", True),
        ("?enabled=1", True),  # a declared filter_field
    ],
)
def test_empty_state_branches_on_filters_not_on_any_query_param(
    client, staff, query, expect_filtered
):
    client.force_login(staff)
    body = client.get(reverse("webhooks/receivers-list") + query).content.decode()
    if expect_filtered:
        assert _FILTERED in body, f"{query!r} should take the filtered branch"
    else:
        assert _FILTERED not in body, f"{query!r} must NOT take the filtered branch"
        assert _UNFILTERED in body, f"{query!r} should take the unfiltered branch"


def test_every_bundled_display_uses_the_same_empty_state_copy():
    """A 4-file edit previously produced three different strings + a stale CTA."""
    from pathlib import Path

    root = Path(__file__).resolve().parent / "templates" / "smallstack" / "crud"
    include = "smallstack/crud/includes/empty_state.html"
    for rel in (
        "object_list.html",
        "object_list_partial.html",
        "displays/table.html",
        "displays/cards.html",
    ):
        text = (root / rel).read_text()
        assert include in text, f"{rel} does not include the shared empty state"
        assert "to show." not in text, f"{rel} still has the old divergent copy"
        assert "Create one now?" not in text, f"{rel} still has the stale CTA"


# --- F-50: the per-object hook must cover the bulk paths too -----------------
#
# `check_object_permission` was documented as covering "detail, edit, delete,
# field-preview, related-tab, the REST detail/update/delete handlers, the
# bulk-action view and the generated MCP tools". It was not called from any bulk
# path — those applied only `get_detail_queryset`. Not exploitable in the shipped
# tree (the one view that opts out of the read scoper declares no bulk actions),
# but it is the same false-docstring failure mode as the leak it was written to
# fix: it tells the next author "express ownership here, nothing can bypass it".
#
# No shipped CRUDView declares bulk_actions, and the bulk routes are registered
# at import time from that attribute — so the view classes are built here the
# same way crud.py builds them, and driven through as_view().


def _bulk_view_for(view_cls):
    from apps.smallstack.crud import _CRUDBulkActionView

    return type(
        f"{view_cls.model.__name__}BulkActionForTest",
        (_CRUDBulkActionView,),
        {"crud_config": view_cls},
    ).as_view()


@pytest.fixture
def bulk_receivers(staff):
    a = WebhookReceiver.objects.create(name="bulk-allowed", slug="bulk-allowed")
    b = WebhookReceiver.objects.create(name="bulk-denied", slug="bulk-denied")
    return a, b


@pytest.mark.parametrize("action", ["delete", "update"])
def test_bulk_actions_honour_check_object_permission(
    rf, staff, bulk_receivers, monkeypatch, action
):
    from django.core.exceptions import PermissionDenied

    from apps.smallstack.crud import BulkAction

    allowed, denied = bulk_receivers

    class Guarded(WebhookReceiverCRUDView):
        bulk_actions = [BulkAction.DELETE, BulkAction.UPDATE]

        @classmethod
        def check_object_permission(cls, obj, request):
            if obj.pk == denied.pk:
                raise PermissionDenied("not yours")

    payload = {"action": action, "ids": [allowed.pk, denied.pk]}
    if action == "update":
        payload["fields"] = {"enabled": False}
    monkeypatch.setattr(Guarded, "can_bulk_update_fields", classmethod(lambda cls: ["enabled"]))

    import json

    request = rf.post("/x/bulk/", data=json.dumps(payload), content_type="application/json")
    request.user = staff
    response = _bulk_view_for(Guarded)(request)
    body = json.loads(response.content)

    assert body["errors"].get(str(denied.pk)) == "Permission denied", (
        f"bulk {action} bypassed check_object_permission: {body}"
    )
    touched = body.get("deleted") or body.get("updated") or []
    assert denied.pk not in touched, f"bulk {action} acted on a refused row: {body}"
    assert allowed.pk in touched, f"bulk {action} refused a permitted row: {body}"
    if action == "delete":
        assert WebhookReceiver.objects.filter(pk=denied.pk).exists(), "refused row was deleted"
