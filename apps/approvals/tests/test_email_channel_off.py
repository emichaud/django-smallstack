"""The email channel being OFF must be a quiet, stable state. (Test round 2026-09-26, E1/E2/E3.)

Before this, ``SMALLSTACK_APPROVALS_EMAILS_ENABLED=False`` still enqueued a notify task per
request: the gate lived only at *send* time, inside ``send_requested``/``send_decided``.
With no worker those rows sat READY forever, and ``ApprovalsFanoutMonitor`` counted exactly
them — so a **core-category** service card sat permanently DOWN, telling the operator to
start a mail worker they had deliberately chosen not to run. ``UPGRADING.md`` offered that
same setting as the remedy for the symptom, so following the docs did not clear it.

Dispatch is exercised through ``receivers._enqueue`` directly, matching
``test_fanout_visibility.py``: the signal chain does not fire under the test settings, so
driving ``services.request_approval`` here would assert nothing (it passes whether or not
the fix is present).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import receivers
from apps.approvals.monitors import ApprovalsFanoutMonitor

pytestmark = pytest.mark.django_db
TASK_PATH = "apps.approvals.tasks.notify_requested_task"


class _NeverRaisingTask:
    """Stands in for a DatabaseBackend task: enqueue() always succeeds."""

    def __init__(self) -> None:
        self.enqueued: list[int] = []

    def enqueue(self, pk):
        self.enqueued.append(pk)
        return object()


@pytest.fixture(autouse=True)
def _real_site_domain(settings):
    """pytest-django forces ``DEBUG=False``, so the default ``SITE_DOMAIN`` would trip the
    dead-console-link branch in every test here. Only the E3 case wants that."""
    settings.SITE_DOMAIN = "approvals.example.test"


def _queue_row(*, age_minutes: int = 0):
    """A queued approval-email task, as the database backend would leave it.

    ``enqueued_at`` is ``auto_now_add``, so it must be back-dated with ``update()`` —
    passing it to ``create()`` is silently discarded.
    """
    from django_tasks_db.models import DBTaskResult

    row = DBTaskResult.objects.create(
        args_kwargs={"args": [1], "kwargs": {}},
        task_path=TASK_PATH,
        backend_name="default",
        run_after=timezone.now(),
        exception_class_path="",
        traceback="",
        status="READY",
        queue_name="email",
    )
    if age_minutes:
        DBTaskResult.objects.filter(pk=row.pk).update(
            enqueued_at=timezone.now() - timedelta(minutes=age_minutes)
        )
    return row


def _stale_minutes(settings) -> int:
    return int(settings.SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES) + 10


# --- E1: dispatch -----------------------------------------------------------

def test_disabled_channel_neither_queues_nor_sends(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = False
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = False  # would otherwise queue
    task, sent = _NeverRaisingTask(), []
    receivers._enqueue(task, sent.append, 42)
    assert task.enqueued == []
    assert sent == []


def test_disabled_channel_does_not_send_inline_either(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = False
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = True
    task, sent = _NeverRaisingTask(), []
    receivers._enqueue(task, sent.append, 42)
    assert sent == []


def test_enabled_channel_still_queues(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = False
    task, sent = _NeverRaisingTask(), []
    receivers._enqueue(task, sent.append, 42)
    assert task.enqueued == [42], "the fix must not break the normal queue path"


# --- E1: rows from before the switch must not hold the monitor down ----------

def test_monitor_up_when_channel_off_even_with_stale_rows(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    _queue_row(age_minutes=_stale_minutes(settings))
    assert ApprovalsFanoutMonitor().check().ok is False, "baseline: a real backlog is noticed"

    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = False
    assert ApprovalsFanoutMonitor().check().ok is True


# --- E2: the note must describe the queue it actually found -----------------

def test_queued_but_young_is_not_called_drained(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    _queue_row()
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True
    assert "within the grace window" in result.note
    assert "drained" not in result.note


def test_empty_queue_says_clear(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True
    assert "email queue clear" in result.note


# --- E3: one check, every fault ---------------------------------------------

def test_both_faults_reported_together(settings):
    settings.SITE_DOMAIN = "localhost:8000"
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    _queue_row(age_minutes=_stale_minutes(settings))

    result = ApprovalsFanoutMonitor().check()
    assert result.ok is False
    assert "SITE_DOMAIN" in result.note, "the config fault must be reported"
    assert "queued and unrun" in result.note, "and must not hide the backlog behind it"


# --- host resolution: SITE_URL is enough (the two-knob gap) ------------------


def test_site_url_alone_satisfies_the_link_check(settings):
    """A deployment that configured its host ONCE — as SITE_URL, the knob
    webhook_doctor tells it to set — must not be told to also set SITE_DOMAIN.
    The monitor and the emails share one resolution chain."""
    settings.SITE_DOMAIN = "localhost:8000"  # untouched default
    settings.SITE_URL = "https://planner.example.com"
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True

    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True

    from apps.accounts.emails import site_base_url

    assert site_base_url() == "https://planner.example.com"  # emails agree


def test_site_domain_still_wins_when_set(settings):
    settings.SITE_DOMAIN = "planner.example.com"
    settings.USE_HTTPS = True
    settings.SITE_URL = "https://other.example.com"

    from apps.accounts.emails import site_base_url

    assert site_base_url() == "https://planner.example.com"


def test_no_host_anywhere_still_flags(settings):
    settings.SITE_DOMAIN = "localhost:8000"
    for name in ("SITE_URL", "SMALLSTACK_SITE_URL", "BASE_URL"):
        if hasattr(settings, name):
            delattr(settings, name)
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True

    result = ApprovalsFanoutMonitor().check()
    assert result.ok is False
    assert "SITE_DOMAIN" in result.note and "SITE_URL" in result.note
