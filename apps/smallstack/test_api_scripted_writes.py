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


class SubclassedScopedWidgetForm(ScopedWidgetForm):
    """The shape that actually ships: a subclass that *hides* ``user=``.

    ``apps/blog``'s PostForm, BlogForm and TagForm all override ``__init__``
    with ``(*args, **kwargs)`` for unrelated reasons and forward to the base
    that declares ``user=``. ``inspect.signature(PostForm.__init__)`` therefore
    shows no ``user``, and the first version of ``build_form`` skipped it — so
    three of the four scoped forms stayed unscoped and the cross-tenant write
    was still open on Post while already closed on Issue.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = True


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


class _SubclassScopedWidgetView(CRUDView):
    model = Widget
    url_base = "test/subclass-scoped-widgets"
    form_class = SubclassedScopedWidgetForm
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
def _clear_accepts_user_cache():
    """Drop ``build_form``'s per-class verdict cache between tests.

    Without this the suite cannot witness the MRO defect: the pre-fix cache was
    read with ``getattr``, so a verdict cached on a *base* class leaked to
    subclasses, and whether a subclass got scoped depended on which class the
    process happened to probe first. That order-dependence is itself the bug —
    pinning it makes these tests deterministic witnesses rather than artefacts
    of test ordering.
    """
    for klass in (
        ScopedWidgetForm,
        SubclassedScopedWidgetForm,
        PlainWidgetForm,
    ):
        # delattr only — a class __dict__ is a read-only mappingproxy.
        try:
            delattr(klass, "_accepts_user_kwarg")
        except AttributeError:
            pass
    yield


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


def test_create_scoping_survives_a_subclass_that_hides_the_user_param(alice, bob):
    """Checking only ``form_class.__init__`` fixes one form in four.

    This is the shape ``apps/blog`` ships; see SubclassedScopedWidgetForm.
    Fails against a ``build_form`` that does not walk the MRO.
    """
    view = _make_api_list_view(_SubclassScopedWidgetView)
    response = view(_req("post", alice, {"name": "injected", "owner": bob.pk}))

    assert response.status_code == 400, (
        "a subclass overriding __init__ with **kwargs hid the inherited user= "
        "parameter, so the form was built unscoped"
    )
    assert not Widget.objects.filter(owner=bob).exists()


def test_accepts_user_is_not_cached_across_the_mro(alice):
    """A base's cached verdict must not be inherited by a subclass.

    Caching on the class via ``getattr`` made the answer depend on which class
    was probed first.
    """
    from apps.smallstack.form_bridge import _accepts_user

    assert _accepts_user(ScopedWidgetForm) is True
    assert _accepts_user(SubclassedScopedWidgetForm) is True
    assert _accepts_user(PlainWidgetForm) is False
    # Re-probe in the reverse order: a leaked cache would flip one of these.
    assert _accepts_user(PlainWidgetForm) is False
    assert _accepts_user(SubclassedScopedWidgetForm) is True


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


def test_serialize_output_is_json_primitive_not_merely_jsonresponse_safe():
    """``serialize()`` must survive plain ``json.dumps``, not just JsonResponse.

    JsonResponse encodes with DjangoJSONEncoder (UUID, Decimal, date all fine),
    but apps/webhooks stores the same dict in a JSONField with no ``encoder=``,
    i.e. plain ``json.dumps``. A UUIDField in a CRUDView's detail_fields
    therefore serialized fine over REST and raised on the webhook write —
    inside the caller's atomic() block, which rolled the caller's own INSERT
    back while fan_out's bare except hid it. Round 2 of the blog programme:
    ``service.create_post`` returned a Post with a pk and left no row.

    A stub stands in for a model here on purpose: this is a contract about
    ``serialize``'s output types, and it must hold for every app, not just the
    one that happened to expose it.
    """
    import datetime
    import uuid
    from decimal import Decimal

    class _Stub:
        pk = 7
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        amount = Decimal("19.99")
        span = datetime.timedelta(seconds=90)
        when = datetime.datetime(2026, 10, 12, 3, 0, 0)
        flag = True
        note = "plain"

    data = _serialize(_Stub(), ["uid", "amount", "span", "when", "flag", "note"])

    json.dumps(data)  # the actual failure mode
    assert data["uid"] == "12345678-1234-5678-1234-567812345678"
    assert data["amount"] == "19.99", "Decimal must not become a float"
    assert data["span"] == "0:01:30"
    assert data["when"] == "2026-10-12T03:00:00"
    assert data["flag"] is True
    assert data["note"] == "plain"


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
