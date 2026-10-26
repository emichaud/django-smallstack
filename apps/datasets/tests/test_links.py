"""Row links — the ``url`` key that says where a row's object can be viewed."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.activity.models import RequestLog
from apps.datasets.core import get_dataset
from apps.datasets.registry import dataset, unregister
from apps.smallstack.models import BackupRecord

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="lnk-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def _one_request() -> RequestLog:
    return RequestLog.objects.create(path="/x", method="GET", status_code=200, response_time_ms=1)


def test_crud_detail_route_is_the_generic_fallback():
    """Every explorer-registered model has a CRUDView, so bundled datasets link
    to the admin detail page with no per-dataset code."""
    log = _one_request()
    ds = get_dataset("smallstack_requests")
    assert ds is not None
    assert ds.has_links() and ds.schema()["links"] is True
    url = ds.link_for(log)
    assert url and url.endswith(f"/{log.pk}/") and "requestlog" in url
    (row,) = ds.rows(filters={"path": "/x"})
    assert row["url"] == url


def test_every_bundled_dataset_links():
    from apps.datasets.framework import framework_dataset_keys

    unlinked = [k for k in framework_dataset_keys() if not get_dataset(k).has_links()]  # type: ignore[union-attr]
    assert unlinked == []
    # Models whose CRUDView has no detail page link to the edit page instead.
    job = get_dataset("smallstack_scheduled_jobs")
    assert job is not None
    from apps.scheduler.models import ScheduledJob

    first = ScheduledJob.objects.order_by("pk").first()
    if first is not None:
        assert "/edit" in (job.link_for(first) or "") or "/update" in (job.link_for(first) or "")


def test_explicit_callable_wins():
    key = "t_link_callable"
    try:
        dataset(key, link=lambda obj: f"/custom/{obj.pk}/")(lambda: RequestLog.objects.all())
        log = _one_request()
        assert get_dataset(key).link_for(log) == f"/custom/{log.pk}/"  # type: ignore[union-attr]
    finally:
        unregister(key)


def test_route_name_is_reversed_with_pk():
    key = "t_link_route"
    try:
        dataset(key, link="tokenmgr:tokens-detail")(lambda: RequestLog.objects.all())  # any <pk> route
        log = _one_request()
        assert get_dataset(key).link_for(log) == reverse("tokenmgr:tokens-detail", kwargs={"pk": log.pk})  # type: ignore[union-attr]
    finally:
        unregister(key)


def test_bad_route_or_raising_callable_yields_none_not_error():
    log = _one_request()
    for key, link in (("t_link_bad_route", "no:such-route"), ("t_link_raises", lambda obj: 1 / 0)):
        try:
            dataset(key, link=link)(lambda: RequestLog.objects.all())
            ds = get_dataset(key)
            assert ds is not None
            assert ds.link_for(log) is None
            assert ds.rows(limit=1)[0]["url"] is None
        finally:
            unregister(key)


def test_opt_out_and_column_collision_drop_the_key():
    key = "t_link_off"
    try:
        dataset(key, link=False)(lambda: RequestLog.objects.all())
        _one_request()
        ds = get_dataset(key)
        assert ds is not None
        assert not ds.has_links() and ds.schema()["links"] is False
        assert "url" not in ds.rows(limit=1)[0]
    finally:
        unregister(key)
    # A dataset whose own column is called ``url`` keeps that column's meaning.
    from apps.notifications.models import Notification

    key = "t_link_collide"
    try:
        dataset(key, columns=["title", "url"])(lambda: Notification.objects.all())
        ds = get_dataset(key)
        assert ds is not None
        assert not ds.has_links()
    finally:
        unregister(key)


def test_get_absolute_url_fallback_when_no_crud_detail():
    """A model with no CRUDView falls through to get_absolute_url()."""
    from apps.smallstack.crud import CRUDView

    crud = CRUDView._registry.pop(BackupRecord, None)
    key = "t_link_abs"
    try:
        dataset(key, columns=["filename"])(lambda: BackupRecord.objects.all())
        rec = BackupRecord.objects.create(filename="x.sqlite3", file_size=1, duration_ms=1)
        assert get_dataset(key).link_for(rec) == rec.get_absolute_url()  # type: ignore[union-attr]
    finally:
        unregister(key)
        if crud is not None:
            CRUDView._registry[BackupRecord] = crud


def test_rest_rows_and_csv_carry_url(client, staff):
    log = _one_request()
    resp = client.get("/smallstack/datasets/smallstack_requests/?path=/x")
    assert resp.status_code == 200
    (row,) = resp.json()["results"]
    assert row["url"].endswith(f"/{log.pk}/")
    resp = client.get("/smallstack/datasets/smallstack_requests/?path=/x&format=csv")
    header, line = resp.content.decode().splitlines()[:2]
    assert header.split(",")[-1] == "url"
    assert line.endswith(f"/{log.pk}/")


def test_browser_links_first_column(client, staff):
    log = _one_request()
    resp = client.get(reverse("datasets:browse", kwargs={"key": "smallstack_requests"}), {"path": "/x"})
    assert resp.status_code == 200
    assert resp.context["has_links"] is True
    (row,) = resp.context["rows"]
    assert row["url"] and row["url"].endswith(f"/{log.pk}/")
    assert f'href="{row["url"]}"' in resp.content.decode()
    # The target is a real page.
    assert client.get(row["url"]).status_code == 200


def test_notification_link_is_its_local_subject_only(staff):
    from apps.notifications.models import Notification

    ds = get_dataset("smallstack_notifications")
    assert ds is not None
    local = Notification.objects.create(recipient=staff, title="a", url="/smallstack/")
    external = Notification.objects.create(recipient=staff, title="b", url="https://evil.example/")
    assert ds.link_for(local) == "/smallstack/"
    assert ds.link_for(external) is None
