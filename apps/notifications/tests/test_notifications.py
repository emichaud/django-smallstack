"""Notifications primitive — services, views, REST, prune.

The contract under test: notify() never raises and never notifies the actor;
read-state is recipient-scoped on every surface; the bell count is what the
context processor renders; retention pruning respects the setting.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.notifications import mark_read, notify, unread_count
from apps.notifications.models import Notification
from apps.notifications.services import prune
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def alice(db):
    return User.objects.create_user("alice", password="p")


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", password="p")


def _client(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


# --- services ---------------------------------------------------------------


def test_notify_creates_one_row_per_recipient(alice, bob):
    assert notify([alice, bob], title="hi", kind="t.x") == 2
    assert Notification.objects.count() == 2


def test_notify_skips_actor_duplicates_and_anonymous(alice, bob):
    from django.contrib.auth.models import AnonymousUser

    created = notify([alice, alice, bob, AnonymousUser(), None], title="hi", actor=bob)
    assert created == 1  # alice once; bob is the actor; anon/None skipped
    assert Notification.objects.get().recipient == alice


def test_notify_never_raises(alice, monkeypatch):
    monkeypatch.setattr(
        "apps.notifications.models.Notification.objects.bulk_create",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    assert notify([alice], title="hi") == 0  # swallowed, logged


def test_notify_noops_when_disabled(alice, settings):
    settings.SMALLSTACK_NOTIFICATIONS_ENABLED = False
    assert notify([alice], title="hi") == 0
    assert Notification.objects.count() == 0


def test_unread_count_and_mark_read_scoping(alice, bob):
    notify([alice], title="a1")
    notify([alice], title="a2")
    notify([bob], title="b1")
    assert unread_count(alice) == 2
    bob_pk = Notification.objects.get(recipient=bob).pk
    # alice cannot mark bob's row read
    assert mark_read(alice, ids=[bob_pk]) == 0
    assert unread_count(bob) == 1
    assert mark_read(alice) == 2
    assert unread_count(alice) == 0


# --- views ------------------------------------------------------------------


def test_inbox_requires_login(client):
    response = client.get(reverse("notifications:inbox"))
    assert response.status_code == 302  # redirected to login


def test_inbox_shows_only_own_rows(alice, bob):
    notify([alice], title="alice-only")
    notify([bob], title="bob-only")
    body = _client(alice).get(reverse("notifications:inbox")).content.decode()
    assert "alice-only" in body
    assert "bob-only" not in body


def test_open_marks_read_and_redirects(alice):
    notify([alice], title="go", url="/smallstack/")
    n = Notification.objects.get()
    response = _client(alice).get(reverse("notifications:open", args=[n.pk]))
    assert response.status_code == 302
    assert response.url == "/smallstack/"
    n.refresh_from_db()
    assert n.is_read


def test_open_rejects_external_and_scheme_relative_urls(alice):
    notify([alice], title="evil", url="https://evil.example/x")
    notify([alice], title="sneaky", url="//evil.example/x")
    for n in Notification.objects.all():
        response = _client(alice).get(reverse("notifications:open", args=[n.pk]))
        assert response.url == reverse("notifications:inbox"), n.title


def test_open_cross_user_is_404(alice, bob):
    notify([bob], title="bobs")
    n = Notification.objects.get()
    assert _client(alice).get(reverse("notifications:open", args=[n.pk])).status_code == 404


def test_mark_all_read_view(alice):
    notify([alice], title="x")
    notify([alice], title="y")
    _client(alice).post(reverse("notifications:mark_all_read"))
    assert unread_count(alice) == 0


def test_bell_context_processor(alice):
    notify([alice], title="ping")
    body = _client(alice).get(reverse("notifications:inbox")).content.decode()
    assert "notif-bell" in body
    assert "notif-bell-badge" in body


# --- REST -------------------------------------------------------------------


def test_api_list_scoped_to_caller(alice, bob):
    notify([alice], title="mine")
    notify([bob], title="theirs")
    _token, raw = APIToken.create_token(
        user=alice, name="n-test", token_type="manual", access_level="auth"
    )
    response = Client().get(
        reverse("notifications:api_list"), HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    data = response.json()
    assert data["count"] == 1
    assert data["notifications"][0]["title"] == "mine"
    assert data["unread_total"] == 1


def test_api_mark_read_ids_and_all(alice):
    notify([alice], title="one")
    notify([alice], title="two")
    client = _client(alice)
    first = Notification.objects.filter(recipient=alice).first()
    response = client.post(
        reverse("notifications:api_mark_read"),
        data={"ids": [first.pk]},
        content_type="application/json",
    )
    assert response.json()["unread_total"] == 1
    response = client.post(
        reverse("notifications:api_mark_read"),
        data={"all": True},
        content_type="application/json",
    )
    assert response.json()["unread_total"] == 0


def test_api_mark_read_validates_payload(alice):
    response = _client(alice).post(
        reverse("notifications:api_mark_read"),
        data={"ids": "nope"},
        content_type="application/json",
    )
    assert response.status_code == 400


def test_api_requires_auth(client):
    assert client.get(reverse("notifications:api_list")).status_code == 401


def test_openapi_schema_advertises_endpoints(alice):
    spec = _client(alice).get(reverse("api-openapi-schema")).json()
    base = reverse("notifications:api_list")
    assert base in spec["paths"]
    assert f"{base}mark-read/" in spec["paths"]


# --- prune ------------------------------------------------------------------


def test_prune_respects_retention(alice, settings):
    settings.SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS = 30
    notify([alice], title="old")
    notify([alice], title="new")
    Notification.objects.filter(title="old").update(
        created_at=timezone.now() - timedelta(days=31)
    )
    assert prune() == 1
    assert list(Notification.objects.values_list("title", flat=True)) == ["new"]


def test_prune_zero_means_keep_forever(alice, settings):
    settings.SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS = 0
    notify([alice], title="ancient")
    Notification.objects.update(created_at=timezone.now() - timedelta(days=999))
    assert prune() == 0
    assert Notification.objects.count() == 1
