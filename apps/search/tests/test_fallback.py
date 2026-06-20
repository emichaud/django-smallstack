"""FallbackBackend — __icontains OR across configured fields."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.search.backends.base import IndexedView
from apps.search.backends.fallback import FallbackBackend

pytestmark = pytest.mark.django_db


@pytest.fixture
def view_factory():
    User = get_user_model()

    def make(fields=("username", "email"), display="username", subtitle="email"):
        return IndexedView(
            view_cls=type("DummyView", (), {}),
            model=User,
            fields=list(fields),
            display_field=display,
            subtitle_field=subtitle,
        )

    return make


def test_empty_query_returns_empty(view_factory):
    backend = FallbackBackend()
    view = view_factory()
    assert backend.query(view, "") == []
    assert backend.query(view, "   ") == []


def test_finds_match_by_substring(view_factory):
    User = get_user_model()
    User.objects.create_user(username="ev-fallback", email="ev@example.com")
    backend = FallbackBackend()
    view = view_factory()
    hits = backend.query(view, "ev-fall")
    assert any(h.display == "ev-fallback" for h in hits)


def test_or_across_fields(view_factory):
    User = get_user_model()
    User.objects.create_user(username="alice", email="someone@unique-tld-xyz123.com")
    backend = FallbackBackend()
    view = view_factory()
    hits = backend.query(view, "unique-tld-xyz123")
    assert any(h.display == "alice" for h in hits)


def test_no_match_returns_empty(view_factory):
    User = get_user_model()
    User.objects.create_user(username="alice")
    backend = FallbackBackend()
    view = view_factory()
    assert backend.query(view, "zzz-non-existent-99") == []


def test_index_methods_are_noops(view_factory):
    """Fallback has no separate index — ensure() / index_object() are no-ops."""
    backend = FallbackBackend()
    view = view_factory()
    backend.ensure_index(view)  # must not raise
    backend.remove_object(view, 1)  # must not raise
    # rebuild() returns current row count
    assert backend.rebuild(view) >= 0
