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

from apps.notifications import mark_read, notify, services, unread_count
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


def test_open_redirects_and_marks_read_on_arrival(alice):
    """Read is an OUTCOME, not an intention.

    The redirect carries a one-shot marker and
    ``NotificationReadOnArrivalMiddleware`` retires the row only when the target
    answers 2xx — so a click that lands on a 403 doesn't silently consume the
    badge and lose the only pointer the user had. (F-01, secondary.)
    """
    alice.is_staff = True  # /smallstack/ is staff-only; make the arrival succeed
    alice.save()
    notify([alice], title="go", url="/smallstack/")
    n = Notification.objects.get()
    response = _client(alice).get(reverse("notifications:open", args=[n.pk]))
    assert response.status_code == 302
    assert response.url == f"/smallstack/?_notification={n.pk}"
    n.refresh_from_db()
    assert not n.is_read  # not yet — nothing has arrived

    assert _client(alice).get(response.url).status_code == 200
    n.refresh_from_db()
    assert n.is_read


def test_open_leaves_the_row_unread_when_the_target_is_unreachable(alice):
    """alice is NOT staff, so /smallstack/ 403s — the badge must survive."""
    notify([alice], title="go", url="/smallstack/")
    n = Notification.objects.get()
    response = _client(alice).get(reverse("notifications:open", args=[n.pk]))
    assert _client(alice).get(response.url).status_code in (302, 403)
    n.refresh_from_db()
    assert not n.is_read


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
    # F-16: not a bare 200 — the response shape and the error codes are declared,
    # so a generated client doesn't treat 400/401 as protocol errors.
    get_op = spec["paths"][base]["get"]
    assert "application/json" in get_op["responses"]["200"]["content"]
    assert {"400", "401"} <= set(get_op["responses"])
    post_op = spec["paths"][f"{base}mark-read/"]["post"]
    assert "application/json" in post_op["responses"]["200"]["content"]
    assert {"400", "401", "403"} <= set(post_op["responses"])


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


# --- F-13: a producer can retire its own rows --------------------------------


def test_resolve_retires_unread_rows_for_one_subject(alice, bob):
    """`notify()` was fire-and-forget with no handle back, so no producer could
    ever retire its own rows when they stopped being actionable."""
    notify([alice, bob], title="Approval needed", kind="approvals.requested",
           subject_key="approvals.request:7")
    notify([alice], title="Something else", kind="approvals.requested",
           subject_key="approvals.request:8")
    assert Notification.objects.filter(read_at__isnull=True).count() == 3

    assert services.resolve("approvals.request:7") == 2
    assert Notification.objects.filter(read_at__isnull=True).count() == 1
    assert Notification.objects.get(read_at__isnull=True).subject_key == "approvals.request:8"

    # Idempotent, and a blank key is a no-op (never a mass update).
    assert services.resolve("approvals.request:7") == 0
    assert services.resolve("") == 0
    assert Notification.objects.filter(read_at__isnull=True).count() == 1


def test_resolve_can_narrow_by_kind(alice):
    notify([alice], title="needed", kind="approvals.requested",
           subject_key="approvals.request:9")
    notify([alice], title="decided", kind="approvals.decided",
           subject_key="approvals.request:9")
    assert services.resolve("approvals.request:9", kind="approvals.requested") == 1
    unread = Notification.objects.filter(read_at__isnull=True)
    assert [n.kind for n in unread] == ["approvals.decided"]


# --- F-42: the retirement feature has to reach rows that predate it ------------
#
# Migration 0002 added `subject_key` and left existing rows at ''. resolve()
# addresses rows BY subject_key, so the "Approval needed" bells already sitting
# unread when the upgrade landed could never be retired — on the reference
# install that was 105 of 105, several pointing at already-decided requests. The
# fix was verified for new rows and invisible for old ones, so "stale bells are
# retired" would have been wrong for every upgrader.


def _load_backfill():
    """The 0003 data migration's ``backfill``.

    ``importlib`` rather than an ``import`` statement: a module name cannot start
    with a digit in import syntax, and Django's migration filenames all do.
    """
    import importlib

    module = importlib.import_module(
        "apps.notifications.migrations.0003_backfill_approvals_subject_key"
    )
    return module.backfill


@pytest.mark.django_db
def test_backfill_addresses_pre_migration_approvals_rows(django_user_model):
    """The 105-of-105 case: rows created before 0002 must become addressable."""
    from django.apps import apps as django_apps

    alice = django_user_model.objects.create_user("f42-alice", password="p")
    bob = django_user_model.objects.create_user("f42-bob", password="p")

    # Two "Approval needed" bells as migration 0002 left them: no subject_key, so
    # resolve() cannot see them at all.
    for user in (alice, bob):
        notify(
            [user],
            title="Approval needed: laptop order",
            kind="approvals.requested",
            url="/smallstack/approvals/requests/248/",
        )
    Notification.objects.filter(kind="approvals.requested").update(subject_key="")

    stale = Notification.objects.filter(kind="approvals.requested")
    assert stale.count() == 2
    assert all(n.subject_key == "" for n in stale)
    # The defect, reproduced: the feature cannot reach them.
    assert services.resolve("approvals.request:248", kind="approvals.requested") == 0
    assert stale.filter(read_at__isnull=True).count() == 2

    _load_backfill()(django_apps, None)

    assert set(
        Notification.objects.filter(kind="approvals.requested").values_list(
            "subject_key", flat=True
        )
    ) == {"approvals.request:248"}
    # …and now retirement works on exactly the rows that could not be retired.
    assert services.resolve("approvals.request:248", kind="approvals.requested") == 2
    assert (
        Notification.objects.filter(
            kind="approvals.requested", read_at__isnull=True
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_backfill_marks_read_the_bells_of_an_already_decided_request(django_user_model):
    """The half a forward-only fix cannot do.

    Several of the stale rows on the reference install pointed at requests that
    were *already decided*. Those were never going to become actionable again, so
    clicking one is a wasted trip; marking them read is what the operator actually
    wants from "retire stale bells".
    """
    from django.apps import apps as django_apps

    from apps.approvals import services as approval_services
    from apps.approvals.registry import ApprovalKind, get_kind, register_kind

    if get_kind("f42.kind") is None:
        register_kind(ApprovalKind(key="f42.kind", label="F42 probe"))
    requester = django_user_model.objects.create_user("f42-req", password="p")
    staff = django_user_model.objects.create_user("f42-staff", password="p", is_staff=True)

    live = approval_services.request_approval(
        kind="f42.kind", title="still open", actor=requester
    )
    done = approval_services.request_approval(
        kind="f42.kind", title="already decided", actor=requester
    )
    approval_services.decide(done, actor=staff, approved=True)
    assert done.status == "approved"

    Notification.objects.all().delete()
    for req in (live, done):
        notify(
            [staff],
            title=f"Approval needed: {req.title}",
            kind="approvals.requested",
            url=f"/smallstack/approvals/requests/{req.pk}/",
        )
    Notification.objects.update(subject_key="", read_at=None)

    _load_backfill()(django_apps, None)

    by_subject = {
        n.subject_key: n
        for n in Notification.objects.filter(kind="approvals.requested")
    }
    decided_row = by_subject[f"approvals.request:{done.pk}"]
    live_row = by_subject[f"approvals.request:{live.pk}"]
    assert decided_row.read_at is not None, "a bell for a decided request stayed unread"
    assert live_row.read_at is None, "a bell for a STILL-PENDING request was marked read"


@pytest.mark.django_db
def test_backfill_is_idempotent_and_leaves_other_rows_alone(django_user_model):
    """It ships as a migration but must survive being re-run as a one-off."""
    from django.apps import apps as django_apps

    alice = django_user_model.objects.create_user("f42-c", password="p")
    notify(
        [alice],
        title="Approval needed: x",
        kind="approvals.requested",
        url="/smallstack/approvals/requests/77/",
    )
    # A non-approvals row, and an approvals row with no usable URL: neither must
    # be touched.
    notify([alice], title="unrelated", kind="tasks.finished", url="/smallstack/tasks/1/")
    notify([alice], title="no url", kind="approvals.decided", url="")
    Notification.objects.update(subject_key="")

    backfill = _load_backfill()
    backfill(django_apps, None)
    first = dict(Notification.objects.values_list("title", "subject_key"))
    backfill(django_apps, None)
    second = dict(Notification.objects.values_list("title", "subject_key"))

    assert first == second, "re-running the backfill changed the result"
    assert first["Approval needed: x"] == "approvals.request:77"
    assert first["unrelated"] == "", "a non-approvals row was rewritten"
    assert first["no url"] == "", "a row with no derivable pk was rewritten"
