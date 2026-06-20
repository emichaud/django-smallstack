"""Search security model — the two per-view knobs that gate cross-model search.

  - ``search_access`` (default SearchAccess.STAFF): the level a caller
    must reach to see hits from this CRUDView. Three levels — STAFF,
    AUTHENTICATED, ANONYMOUS — each a strict superset of the prior.
  - ``search_visibility`` (callable, default None): when access is
    broader than staff, further scope rows per user via
    ``(queryset, user) -> queryset``.

Both apply in :func:`apps.search.registry.search_all` and
:func:`apps.search.registry.get_indexed_sources`. ``user=None`` (trusted
internal call) bypasses both. ``user.is_staff`` bypasses both.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from apps.search.access import SearchAccess
from apps.search.backends import get_backend
from apps.search.registry import (
    all_views,
    get_indexed_sources,
    register,
    search_all,
    unregister,
    view_count,
)
from apps.smallstack.crud import CRUDView


def _make_view_class(
    model,
    *,
    fields=("username",),
    display="username",
    access=SearchAccess.STAFF,
    visibility=None,
    name="TestSecView",
):
    attrs = {
        "model": model,
        "url_base": "sec-test",
        "enable_search": True,
        "search_fields": list(fields),
        "search_display": display,
        "search_access": access,
    }
    if visibility is not None:
        attrs["search_visibility"] = staticmethod(visibility)
    return type(name, (CRUDView,), attrs)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Each test gets a clean registry slate, even when the default
    User opt-in already registered itself at startup."""
    User = get_user_model()
    label = f"{User._meta.app_label}.{User.__name__}"
    unregister(label)
    yield
    unregister(label)


pytestmark = pytest.mark.django_db


def _rebuild_indexes():
    backend = get_backend()
    for view in all_views():
        backend.rebuild(view)


# ────────────────────────────────────────────────────────────────────────────
#  staff gate — the secure default
# ────────────────────────────────────────────────────────────────────────────


def test_default_view_is_staff_only():
    """A view that doesn't set search_access defaults to STAFF."""
    User = get_user_model()
    cls = _make_view_class(User)
    view = register(cls)
    assert view is not None
    assert view.access == SearchAccess.STAFF


def test_non_staff_user_sees_zero_hits_from_staff_only_view():
    """Default = closed. Non-staff users get no hits from staff-only views."""
    User = get_user_model()
    register(_make_view_class(User))  # default access=STAFF
    User.objects.create_user(username="staff-only-needle-zz")
    _rebuild_indexes()

    regular = User.objects.create_user(username="regular_user", password="x")
    hits = search_all("staff-only-needle-zz", user=regular)
    assert hits == []


def test_anonymous_user_sees_zero_hits_from_staff_only_view():
    """Default = closed. Anonymous visitors get no hits from staff-only views."""
    User = get_user_model()
    register(_make_view_class(User))  # default access=STAFF
    User.objects.create_user(username="anon-cannot-see-zz")
    _rebuild_indexes()

    hits = search_all("anon-cannot-see-zz", user=AnonymousUser())
    assert hits == []


def test_staff_user_sees_hits_from_staff_only_view():
    """Staff users skip the gate entirely."""
    User = get_user_model()
    register(_make_view_class(User))  # default access=STAFF
    User.objects.create_user(username="staff-only-needle-zz")
    _rebuild_indexes()

    staff = User.objects.create_user(username="staff_user", password="x", is_staff=True)
    hits = search_all("staff-only-needle-zz", user=staff)
    assert any(h.display == "staff-only-needle-zz" for h in hits)


def test_trusted_internal_caller_sees_hits_when_user_is_none():
    """``user=None`` means trusted internal — bypasses both gates."""
    User = get_user_model()
    register(_make_view_class(User))  # default access=STAFF
    User.objects.create_user(username="internal-needle-zz")
    _rebuild_indexes()

    hits = search_all("internal-needle-zz", user=None)
    assert any(h.display == "internal-needle-zz" for h in hits)


# ────────────────────────────────────────────────────────────────────────────
#  AUTHENTICATED level — opt-in to any-signed-in-user access
# ────────────────────────────────────────────────────────────────────────────


def test_non_staff_sees_hits_when_view_is_authenticated_access():
    """search_access=AUTHENTICATED lets any signed-in user find rows."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED))
    User.objects.create_user(username="authed-needle-zz")
    _rebuild_indexes()

    regular = User.objects.create_user(username="regular2", password="x")
    hits = search_all("authed-needle-zz", user=regular)
    assert any(h.display == "authed-needle-zz" for h in hits)


def test_anonymous_does_not_see_authenticated_access_view():
    """search_access=AUTHENTICATED still gates out signed-out visitors."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED))
    User.objects.create_user(username="not-anon-zz")
    _rebuild_indexes()

    hits = search_all("not-anon-zz", user=AnonymousUser())
    assert hits == []


# ────────────────────────────────────────────────────────────────────────────
#  ANONYMOUS level — opt-in to fully public access
# ────────────────────────────────────────────────────────────────────────────


def test_anonymous_sees_hits_when_view_is_anonymous_access():
    """search_access=ANONYMOUS makes the view visible to signed-out visitors."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.ANONYMOUS))
    User.objects.create_user(username="public-anon-needle-zz")
    _rebuild_indexes()

    hits = search_all("public-anon-needle-zz", user=AnonymousUser())
    assert any(h.display == "public-anon-needle-zz" for h in hits)


def test_authenticated_user_also_sees_anonymous_access_views():
    """ANONYMOUS is a superset of AUTHENTICATED — signed-in users see them too."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.ANONYMOUS))
    User.objects.create_user(username="open-needle-zz")
    _rebuild_indexes()

    regular = User.objects.create_user(username="any_user", password="x")
    hits = search_all("open-needle-zz", user=regular)
    assert any(h.display == "open-needle-zz" for h in hits)


# ────────────────────────────────────────────────────────────────────────────
#  Invalid search_access value falls back to STAFF
# ────────────────────────────────────────────────────────────────────────────


def test_invalid_search_access_falls_back_to_staff():
    """A typo'd or unknown search_access value is treated as STAFF (safe)."""
    User = get_user_model()
    cls = _make_view_class(User)
    cls.search_access = "publik"  # typo'd value
    view = register(cls)
    assert view is not None
    assert view.access == SearchAccess.STAFF


# ────────────────────────────────────────────────────────────────────────────
#  visibility filter — per-user row scoping
# ────────────────────────────────────────────────────────────────────────────


def test_visibility_filter_scopes_rows_per_user():
    """search_visibility callable narrows the queryset to what user can see."""
    User = get_user_model()

    # Each user can only "see" themselves via the visibility filter.
    def only_self(qs, user):
        return qs.filter(pk=user.pk)

    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED, visibility=only_self))

    alice = User.objects.create_user(username="alice-needle-zz", password="x")
    User.objects.create_user(username="bob-needle-zz", password="x")
    _rebuild_indexes()

    # Alice searches for the shared "needle" — sees only herself.
    hits = search_all("needle-zz", user=alice)
    displays = {h.display for h in hits}
    assert "alice-needle-zz" in displays
    assert "bob-needle-zz" not in displays


def test_visibility_filter_does_not_apply_to_staff():
    """Staff users skip both gates — visibility filter is irrelevant for them."""
    User = get_user_model()

    def only_self(qs, user):
        return qs.filter(pk=user.pk)

    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED, visibility=only_self))

    User.objects.create_user(username="alice-needle-zz", password="x")
    User.objects.create_user(username="bob-needle-zz", password="x")
    _rebuild_indexes()

    staff = User.objects.create_user(username="staff_x", password="x", is_staff=True)
    hits = search_all("needle-zz", user=staff)
    displays = {h.display for h in hits}
    # Staff sees BOTH alice and bob despite the per-user filter on the view.
    assert "alice-needle-zz" in displays
    assert "bob-needle-zz" in displays


def test_visibility_filter_fails_safe_when_callback_raises():
    """A broken visibility callback drops all hits for that view rather
    than leaking unfiltered rows."""
    User = get_user_model()

    def broken(qs, user):
        raise RuntimeError("boom")

    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED, visibility=broken))
    User.objects.create_user(username="protected-needle-zz")
    _rebuild_indexes()

    regular = User.objects.create_user(username="regular3", password="x")
    hits = search_all("protected-needle-zz", user=regular)
    # No leaks — view's broken visibility means zero hits.
    assert all(h.model_label != f"{User._meta.app_label}.{User.__name__}" for h in hits)


def test_visibility_filter_runs_for_anonymous_access_view():
    """When access=ANONYMOUS, the visibility callback still scopes rows.
    Receives AnonymousUser as the user argument."""
    User = get_user_model()
    seen_users: list = []

    def only_active(qs, user):
        seen_users.append(user)
        return qs.filter(is_active=True)

    register(_make_view_class(User, access=SearchAccess.ANONYMOUS, visibility=only_active))
    User.objects.create_user(username="active-anon-needle-zz", is_active=True)
    User.objects.create_user(username="inactive-anon-needle-zz", is_active=False)
    _rebuild_indexes()

    hits = search_all("anon-needle-zz", user=AnonymousUser())
    displays = {h.display for h in hits}
    assert "active-anon-needle-zz" in displays
    assert "inactive-anon-needle-zz" not in displays
    # The callback was invoked with the anonymous identity.
    assert seen_users and seen_users[0].is_anonymous


# ────────────────────────────────────────────────────────────────────────────
#  get_indexed_sources — applies the same access gate
# ────────────────────────────────────────────────────────────────────────────


def test_indexed_sources_hides_staff_only_views_from_non_staff():
    """get_indexed_sources applies the same gate as search_all — non-staff
    users don't see staff-only views even in the 'what's indexed' panel."""
    User = get_user_model()
    register(_make_view_class(User))  # default access=STAFF

    regular = User.objects.create_user(username="regular4", password="x")
    sources = get_indexed_sources(user=regular)
    model_sources = [s for s in sources if s["kind"] == "model"]
    assert model_sources == []


def test_indexed_sources_hides_authenticated_views_from_anonymous():
    """An AUTHENTICATED-level view is hidden from anonymous visitors in the panel."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.AUTHENTICATED))

    sources = get_indexed_sources(user=AnonymousUser())
    model_sources = [s for s in sources if s["kind"] == "model"]
    assert model_sources == []


def test_indexed_sources_shows_anonymous_views_to_anonymous():
    """An ANONYMOUS-level view IS listed for signed-out visitors."""
    User = get_user_model()
    register(_make_view_class(User, access=SearchAccess.ANONYMOUS))

    sources = get_indexed_sources(user=AnonymousUser())
    assert any(s["kind"] == "model" for s in sources)


def test_indexed_sources_shows_all_to_staff():
    """Staff see every registered source regardless of level."""
    User = get_user_model()
    register(_make_view_class(User))

    staff = User.objects.create_user(username="staff_y", password="x", is_staff=True)
    sources = get_indexed_sources(user=staff)
    assert view_count() >= 1
    assert any(s["kind"] == "model" for s in sources)


def test_indexed_sources_user_none_is_trusted():
    """user=None bypasses the gate (used by MCP-style internal callers)."""
    User = get_user_model()
    register(_make_view_class(User))

    sources = get_indexed_sources(user=None)
    assert any(s["kind"] == "model" for s in sources)
