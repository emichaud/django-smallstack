"""P2 surface tests — dashboard render, tick localhost guard, run-now, stat drills."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.scheduler.models import ScheduledJob, ScheduledJobRun

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff(client):
    u = User.objects.create_user(username="staff", password="pw", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def job():
    return ScheduledJob.objects.create(
        name="Nightly", task_path="apps.tasks.tasks.process_data_task",
        schedule_type="cron", cron_expression="0 2 * * *",
    )


def test_dashboard_renders_for_staff(client, staff, job):
    resp = client.get(reverse("scheduler_dashboard"))
    assert resp.status_code == 200
    assert b"Scheduler" in resp.content


def test_dashboard_requires_staff(client):
    resp = client.get(reverse("scheduler_dashboard"))
    assert resp.status_code in (302, 403)  # redirected to login or forbidden


def test_stat_detail_active(client, staff, job):
    resp = client.get(reverse("scheduler_stat_detail", args=["active"]))
    assert resp.status_code == 200
    assert b"Nightly" in resp.content


def test_tick_rejects_non_localhost(client):
    resp = client.post(reverse("scheduler_tick"), REMOTE_ADDR="10.0.0.5")
    assert resp.status_code == 403


def test_tick_allows_localhost(client):
    resp = client.post(reverse("scheduler_tick"), REMOTE_ADDR="127.0.0.1")
    assert resp.status_code == 200
    assert "enqueued" in resp.json()


def test_run_now_enqueues(client, staff, job):
    resp = client.post(reverse("scheduler_run_now", args=[job.pk]))
    assert resp.status_code == 302  # redirects to dashboard
    job.refresh_from_db()
    assert job.total_runs == 1
    assert ScheduledJobRun.objects.filter(job=job).exists()


def test_run_now_requires_staff(client, job):
    resp = client.post(reverse("scheduler_run_now", args=[job.pk]))
    assert resp.status_code in (302, 403)
    job.refresh_from_db()
    assert job.total_runs == 0
