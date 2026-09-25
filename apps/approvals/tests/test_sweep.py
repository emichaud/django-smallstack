"""The expiry sweep task + its scheduler registration.

Correctness never depends on the worker (lazy expiry is tested in
test_services); this file proves the scheduled wrapper still works as a plain
task and that sync registers the job.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from apps.approvals.tasks import sweep_expired_approvals

pytestmark = pytest.mark.django_db


def test_sweep_task_expires_overdue(requester, sample_kind):
    services.request_approval(
        kind="test.sample", title="old", actor=requester,
        expires_at=timezone.now() - timedelta(minutes=5),
    )
    services.request_approval(kind="test.sample", title="fresh", actor=requester)

    assert sweep_expired_approvals.func() == 1
    assert ApprovalRequest.objects.filter(status="expired").count() == 1
    assert sweep_expired_approvals.func() == 0  # idempotent


def test_sweep_job_registered_with_scheduler(db):
    from apps.scheduler.models import ScheduledJob
    from apps.scheduler.registry import sync_code_jobs

    sync_code_jobs()
    job = ScheduledJob.objects.get(name="Approvals: expire overdue requests")
    assert job.enabled


def test_notifications_prune_job_registered(db):
    from apps.scheduler.models import ScheduledJob
    from apps.scheduler.registry import sync_code_jobs

    sync_code_jobs()
    assert ScheduledJob.objects.filter(name="Notifications: prune old rows").exists()
