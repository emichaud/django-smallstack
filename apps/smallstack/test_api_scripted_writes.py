"""The scripted write surfaces (REST, MCP) must behave like the HTML one.

Three framework defects found by the integration harness on 2026-10-11, all in
``apps/smallstack/api.py``, all surfaced by ``apps/blog`` being the first app to
put a user-scoped FK and a ``FileField`` on a generated write surface:

1. **Cross-tenant create.** ``CRUDView`` builds HTML forms through
   ``get_form_kwargs``, the seam a view uses to pass ``request.user`` so the
   form can scope its own ``ModelChoiceField`` querysets. The scripted surfaces
   constructed the form directly with no user, so the queryset stayed unscoped —
   and narrowing that queryset *is* the validation, because the field validates
   the submitted pk against it. A create has no object for
   ``check_object_permission`` to inspect and ``get_list_queryset`` only scopes
   reads, so the form was the sole gate and it was built disarmed. Any
   authenticated account could write a row into another tenant's object.

2. **``FileField`` 500s after committing.** ``_serialize`` had no branch for
   ``FieldFile``, and ``JsonResponse`` has no ``default=`` fallback, so a create
   wrote the row and *then* raised ``TypeError``. A client retrying on 5xx
   duplicated the row every attempt.

3. **``api_expand_fields`` vs ``.only()``.** An expanded FK absent from
   ``list_fields`` was both deferred and traversed, which Django refuses — a 500
   on the list endpoint with no client input, and reachable on demand via
   ``?expand=``.

Each test here fails on the pre-fix code.
"""

from __future__ import annotations

import json

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.mcp.tests.models import Widget
from apps.smallstack.api import (
    _make_api_detail_view,
    _make_api_list_view,
    _serialize,
)
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.form_bridge import build_form

pytestmark = pytest.mark.django_db
User = get_user_model()


# ---------------------------------------------------------------------------
# A CRUDView whose form scopes its FK per user — the shape apps/blog uses.
# ---------------------------------------------------------------------------
class ScopedWidgetForm(forms.ModelForm):
    """Mirrors apps/blog/forms.py: accepts ``user=`` and narrows its own choices."""

    class Meta:
        model = Widget
        fields = ["name", "owner"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields["owner"].queryset = User.objects.filter(pk=user.pk)


class PlainWidgetForm(forms.ModelForm):
    """A form that does NOT accept ``user=`` — must still be constructible."""

    class Meta:
        model = Widget
        fields = ["name", "owner"]


class _ScopedWidgetView(CRUDView):
    model = Widget
    url_base = "test/scoped-widgets"
    form_class = ScopedWidgetForm
    fields = ["name", "owner"]
    list_fields = ["name"]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE]
    enable_api = True

    @classmethod
    def get_list_queryset(cls, qs, request):
        return qs.filter(owner=request.user)


class _ExpandWidgetView(CRUDView):
    """``owner`` is expanded but absent from ``list_fields`` — finding 3."""

    model = Widget
    url_base = "test/expand-widgets"
    fields = ["name", "owner"]
    list_fields = ["name"]
    actions = [Action.LIST]
    enable_api = True
    api_expand_fields = ["owner"]


@pytest.fixture(autouse=True)
def _fresh_content_types():
    """Drop the ContentType cache around every test in this module.

    These are the first tests to drive a *successful* write through the generated
    API against ``Widget``, so they are the first to make ``log_write`` insert a
    ``django_admin_log`` row for it. ``Widget``'s table is created outside
    migration control (see its model docstring), so its ContentType row is
    created inside whichever test transaction first asked for it and then rolled
    back — while ``ContentType.objects.get_for_model``'s process-wide cache keeps
    the now-nonexistent id. The next test's admin-log row then points at it and
    the end-of-test constraint check fails with "invalid foreign key".

    Nothing to do with the behaviour under test; clearing the cache keeps the id
    and the row in the same transaction.
    """
    from django.contrib.contenttypes.models import ContentType

    ContentType.objects.clear_cache()
    yield
    ContentType.objects.clear_cache()


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice-sw", password="x", is_staff=True)


@pytest.fixture
def bob():
    return User.objects.create_user(username="bob-sw", password="x", is_staff=True)


def _req(method, user, payload=None, path="/x/"):
    rf = RequestFactory()
    if payload is None:
        req = getattr(rf, method)(path)
    else:
        req = getattr(rf, method)(path, data=json.dumps(payload), content_type="application/json")
    req.user = user
    return req


# ---------------------------------------------------------------------------
# 1. Cross-tenant create / update
# ---------------------------------------------------------------------------
def test_create_cannot_point_a_scoped_fk_at_another_user(alice, bob):
    """The BLOCKER: a scoped FK queryset must be the validation on create too."""
    view = _make_api_list_view(_ScopedWidgetView)
    response = view(_req("post", alice, {"name": "injected", "owner": bob.pk}))

    assert response.status_code == 400, (
        "create accepted a pk outside the form's scoped queryset — "
        "the form was built without user=, so it never narrowed"
    )
    assert not Widget.objects.filter(owner=bob).exists()


def test_create_still_works_for_a_pk_inside_the_scope(alice):
    view = _make_api_list_view(_ScopedWidgetView)
    response = view(_req("post", alice, {"name": "mine", "owner": alice.pk}))
    assert response.status_code == 201
    assert Widget.objects.filter(owner=alice, name="mine").exists()


def test_update_cannot_repoint_a_scoped_fk_at_another_user(alice, bob):
    mine = Widget.objects.create(name="mine", owner=alice)
    view = _make_api_detail_view(_ScopedWidgetView)
    response = view(_req("patch", alice, {"owner": bob.pk}), pk=mine.pk)

    assert response.status_code == 400
    mine.refresh_from_db()
    assert mine.owner_id == alice.pk


def test_update_leaving_the_scoped_fk_alone_still_succeeds(alice):
    """Guards the fix against over-correcting: a normal edit must not 400."""
    mine = Widget.objects.create(name="mine", owner=alice)
    view = _make_api_detail_view(_ScopedWidgetView)
    response = view(_req("patch", alice, {"name": "renamed"}), pk=mine.pk)

    assert response.status_code == 200
    mine.refresh_from_db()
    assert mine.name == "renamed"
    assert mine.owner_id == alice.pk


# ---------------------------------------------------------------------------
# build_form itself
# ---------------------------------------------------------------------------
def test_build_form_passes_user_only_to_forms_that_declare_it(alice):
    """A form forwarding ``**kwargs`` to ModelForm must not be handed ``user``.

    Treating a VAR_KEYWORD parameter as consent would raise TypeError on the
    majority of ModelForms, which declare ``__init__(self, *args, **kwargs)``.
    """
    scoped = build_form(ScopedWidgetForm, user=alice)
    assert scoped.user is alice
    assert list(scoped.fields["owner"].queryset) == [alice]

    plain = build_form(PlainWidgetForm, user=alice)  # must not raise
    assert "user" not in getattr(plain, "__dict__", {})
    # Unscoped, as that form asked for: every user is a valid choice.
    assert plain.fields["owner"].queryset.count() == User.objects.count()


def test_build_form_without_a_user_is_the_old_behaviour(alice):
    """``user=None`` means a trusted internal caller (shell, task, CLI)."""
    form = build_form(ScopedWidgetForm, user=None)
    assert form.user is None
    assert form.fields["owner"].queryset.count() == User.objects.count()


# ---------------------------------------------------------------------------
# 2. FileField serialization
# ---------------------------------------------------------------------------
def test_serialize_renders_an_empty_filefield_as_none(alice):
    """Pre-fix this returned the ImageFieldFile, which JsonResponse cannot encode."""
    profile = alice.profile
    data = _serialize(profile, ["profile_photo"])

    assert data["profile_photo"] is None
    json.dumps(data)  # the actual failure mode: must be encodable


def test_serialize_renders_a_populated_filefield_as_its_url(alice):
    profile = alice.profile
    profile.profile_photo.name = "profile_photos/x.png"

    data = _serialize(profile, ["profile_photo"])

    assert isinstance(data["profile_photo"], str)
    assert data["profile_photo"].endswith("profile_photos/x.png")
    json.dumps(data)


# ---------------------------------------------------------------------------
# 3. api_expand_fields vs .only()
# ---------------------------------------------------------------------------
def test_list_survives_an_expanded_fk_absent_from_list_fields(alice):
    """Pre-fix: FieldError — 'cannot be both deferred and traversed'."""
    Widget.objects.create(name="w", owner=alice)
    view = _make_api_list_view(_ExpandWidgetView)
    response = view(_req("get", alice))

    assert response.status_code == 200, "select_related + .only() raised FieldError"
    # `owner` is deliberately absent from the body: expanding a field changes how
    # it renders when it IS serialized, it does not add it to `list_fields`. The
    # regression is the 500, not the payload.
    row = json.loads(response.content)["results"][0]
    assert row["name"] == "w"


def test_client_supplied_expand_cannot_break_the_list(alice):
    """``?expand=`` merges into the expand set, so it hit the same error."""
    Widget.objects.create(name="w", owner=alice)
    view = _make_api_list_view(_ScopedWidgetView)  # list_fields = ["name"] only
    response = view(_req("get", alice, path="/x/?expand=owner"))

    assert response.status_code == 200, "a client-supplied ?expand= could 500 the endpoint"
    assert json.loads(response.content)["results"][0]["name"] == "w"
