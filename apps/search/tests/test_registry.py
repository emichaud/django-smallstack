"""Registry — register/unregister/get_view/search_all."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.search.registry import (
    all_views,
    get_view,
    register,
    search_all,
    unregister,
    view_count,
)
from apps.smallstack.crud import CRUDView


def _make_view_class(model, fields=("username",), display="username"):
    return type(
        "TestRegistryView",
        (CRUDView,),
        {
            "model": model,
            "url_base": "registry-test",
            "enable_search": True,
            "search_fields": list(fields),
            "search_display": display,
        },
    )


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Ensure each test starts with a clean registry slate."""
    User = get_user_model()
    label = f"{User._meta.app_label}.{User.__name__}"
    yield
    unregister(label)


pytestmark = pytest.mark.django_db


def test_register_returns_view():
    User = get_user_model()
    cls = _make_view_class(User)
    view = register(cls)
    assert view is not None
    assert view.model is User


def test_register_idempotent():
    User = get_user_model()
    cls = _make_view_class(User)
    register(cls)
    register(cls)
    assert view_count() == 1


def test_register_skipped_with_no_search_fields():
    User = get_user_model()
    cls = type(
        "NoFieldsView", (CRUDView,),
        {"model": User, "url_base": "x", "enable_search": True, "search_fields": []},
    )
    assert register(cls) is None


def test_get_view_finds_registered_model_instance():
    User = get_user_model()
    register(_make_view_class(User))
    user = User.objects.create_user(username="lookup-target")
    found = get_view(user)
    assert found is not None
    assert found.model is User


def test_get_view_returns_none_for_unregistered_model():
    from django.contrib.contenttypes.models import ContentType
    assert get_view(ContentType) is None


def test_search_all_runs_across_registered_views():
    User = get_user_model()
    register(_make_view_class(User))
    User.objects.create_user(username="searchable-zz-needle")
    # Rebuild the index for this view since signals weren't firing during
    # the test create — call the backend directly.
    from apps.search.backends import get_backend

    backend = get_backend()
    for view in all_views():
        backend.rebuild(view)

    hits = search_all("searchable-zz-needle")
    assert any(h.display == "searchable-zz-needle" for h in hits)
