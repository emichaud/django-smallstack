"""F-07 — the email channel's dependency on a worker must be VISIBLE.

The original defect was not the queue (queuing mail is right — a decision must
not wait on SMTP). It was that ``receivers._enqueue`` only fell back to inline
delivery when ``enqueue()`` *raised*, and with the shipped database-backed task
backend ``enqueue()`` never raises: it inserts a row and returns. So "no
exception" proved nothing, a default install without a ``db_worker`` sent no
approval email at all, and nothing anywhere said so.

Three visible things now exist, and these tests pin all three:

1. the fallback is capability-based (``SMALLSTACK_APPROVALS_EMAILS_INLINE``,
   defaulting to ``DEBUG``) rather than exception-based,
2. queueing logs a warning naming the command that drains it, and
3. a status monitor reports the un-drained backlog, so the silence ends.
"""

from __future__ import annotations

import logging

import pytest
from django.core import mail

from apps.approvals import receivers, services
from apps.approvals.monitors import ApprovalsFanoutMonitor

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _site_domain_is_configured(settings):
    """A realistic SITE_DOMAIN for the backlog tests.

    The monitor now also reports a still-default SITE_DOMAIN, because every
    approval email builds an absolute link from it and `localhost:8000` makes that
    link dead (F-33). The tests below are about the *backlog* signals, so give
    them a configured host; the F-33 tests at the bottom drive the setting
    explicitly.
    """
    settings.SITE_DOMAIN = "approvals.example.com"


class _NeverRaisingTask:
    """Stands in for a DatabaseBackend task: enqueue() always succeeds."""

    def __init__(self):
        self.enqueued: list[int] = []

    def enqueue(self, pk):
        self.enqueued.append(pk)
        return object()


def test_inline_mode_sends_in_process_without_a_worker(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = True
    task, sent = _NeverRaisingTask(), []
    receivers._enqueue(task, sent.append, 42)
    assert sent == [42]
    assert task.enqueued == []


def test_queue_mode_warns_that_nothing_is_delivered_without_a_worker(settings, caplog):
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = False
    receivers._warned_about_worker = False
    task, sent = _NeverRaisingTask(), []
    with caplog.at_level(logging.WARNING, logger="smallstack.approvals"):
        receivers._enqueue(task, sent.append, 42)
    assert task.enqueued == [42]
    assert sent == []  # queued, not sent — that is the correct design
    assert any("db_worker" in r.message for r in caplog.records), caplog.text
    # Once per process, not once per decision.
    caplog.clear()
    receivers._enqueue(task, sent.append, 43)
    assert not caplog.records


def test_inline_default_follows_debug(settings):
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = None
    settings.DEBUG = True
    assert receivers._emails_inline() is True
    settings.DEBUG = False
    assert receivers._emails_inline() is False


def test_a_broken_queue_still_falls_back_inline(settings):
    """The original exception-based fallback still applies when there is no
    queue at all — it just isn't the only path any more."""
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = False

    class _Broken:
        def enqueue(self, pk):
            raise RuntimeError("no broker")

    sent: list[int] = []
    receivers._enqueue(_Broken(), sent.append, 7)
    assert sent == [7]


def test_monitor_is_up_when_nothing_is_stuck(requester, sample_kind):
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True
    assert "awaiting a human" in result.note


def test_monitor_reports_an_undrained_email_queue(requester, sample_kind, settings):
    """The signal the operator never got: N approval emails queued and ageing."""
    from datetime import timedelta

    from django.utils import timezone
    from django_tasks_db.models import DBTaskResult

    settings.SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES = 5
    monitor = ApprovalsFanoutMonitor()
    assert monitor.check().ok is True  # negative control

    row = DBTaskResult.objects.create(
        task_path="apps.approvals.tasks.notify_requested_task",
        args_kwargs={"args": [1], "kwargs": {}},
        backend_name="default",
        status="READY",
    )
    # enqueued_at is auto_now_add — age it so it crosses the grace window.
    DBTaskResult.objects.filter(pk=row.pk).update(
        enqueued_at=timezone.now() - timedelta(minutes=30)
    )
    result = monitor.check()
    assert result.ok is False
    assert "email task(s) queued and unrun" in result.note
    assert "db_worker" in result.note


def test_monitor_reports_an_unswept_expiry_backlog(requester, sample_kind, settings):
    from datetime import timedelta

    from django.utils import timezone

    settings.SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT = 1
    overdue_at = timezone.now() - timedelta(minutes=10)
    for i in range(10):
        services.request_approval(
            kind="test.sample", title=f"stale {i}", actor=requester, expires_at=overdue_at
        )
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is False
    assert "overdue request(s) still marked pending" in result.note


def test_monitor_is_quiet_when_the_app_is_disabled(settings):
    settings.SMALLSTACK_APPROVALS_ENABLED = False
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True
    assert "disabled" in result.note.lower()


def test_decision_email_actually_arrives_in_the_default_test_regime(
    requester, staff, sample_kind, settings, django_capture_on_commit_callbacks
):
    """End-to-end sanity: with the shipped default in DEBUG the mail is sent."""
    settings.SMALLSTACK_APPROVALS_EMAILS_INLINE = True
    staff.email = "s@example.com"
    staff.save()
    requester.email = "r@example.com"
    requester.save()
    with django_capture_on_commit_callbacks(execute=True):
        req = services.request_approval(
            kind="test.sample", title="mail me", actor=requester
        )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.approve(req, actor=staff)
    assert any("Approved" in m.subject for m in mail.outbox)


# --- F-28: a monitor nobody can see does not solve anything ------------------
#
# The monitor was correct and the page it is advertised on ignored it: the core
# tier of /smallstack/status/overview/ rendered each service row from
# `Monitor.inventory()`, whose base implementation returns {"ok": True}. So
# approvals-fanout recorded FAIL ("191 approval email tasks queued and unrun")
# while the Approvals card showed a green tick reading "on". A silent failure is
# bad; a failure that renders green on a status board is worse.


def _record_beat(monitor_key: str, status: str, note: str = ""):
    from django.utils import timezone as djtz

    from apps.heartbeat.models import Heartbeat

    return Heartbeat.objects.create(
        monitor_key=monitor_key,
        timestamp=djtz.now().replace(second=0, microsecond=0),
        status=status,
        note=note,
    )


def _approvals_row(client):
    """The Approvals row as the overview page actually builds it."""
    from apps.heartbeat.views import _build_site_card, _status_overview_context

    ctx = _status_overview_context(public_only=False)
    core = [s for s in ctx["services"] if s["service"].category == "core"]
    card = _build_site_card(core)
    rows = [r for r in card["services"] if r["label"] == "Approvals"]
    assert rows, f"Approvals is not on the overview at all: {[r['label'] for r in card['services']]}"
    return rows[0]


@pytest.mark.django_db
def test_a_recorded_failure_turns_the_overview_row_red(client, staff):
    """The filed repro: recorded FAIL must not render as green "on"."""
    note = (
        "191 approval email task(s) queued and unrun — start a worker on the "
        "'email' queue (manage.py db_worker --queue-name email)."
    )
    _record_beat("approvals-fanout", "fail", note)

    row = _approvals_row(client)
    assert row["ok"] is False, "the overview shows Approvals green while its monitor is down"
    assert row["state"] == "down"
    assert row["state_label"] == "down"
    # …and the monitor's actionable sentence reaches the page.
    assert "queued and unrun" in row["summary"], row["summary"]
    assert "db_worker" in row["summary"], row["summary"]


@pytest.mark.django_db
def test_a_recorded_pass_leaves_the_row_green(client, staff):
    """Negative control — the fix must not paint everything red."""
    _record_beat("approvals-fanout", "ok", "")
    row = _approvals_row(client)
    assert row["ok"] is True, row
    assert row["state_label"] == "on"


@pytest.mark.django_db
def test_no_recorded_beat_at_all_is_not_treated_as_a_failure(client, staff):
    """A fresh install has run no heartbeat; inventory() is the right answer there.

    This is the boundary that makes the fix safe to ship: "unknown" must not be
    read as "down", or every `make run` demo opens on a red board.
    """
    from apps.heartbeat.models import Heartbeat

    Heartbeat.objects.filter(monitor_key="approvals-fanout").delete()
    row = _approvals_row(client)
    assert row["ok"] is True, row


@pytest.mark.django_db
def test_the_overview_page_itself_renders_the_down_state(client, staff):
    """End-to-end over real HTTP — the page, not just the context builder."""
    from django.urls import reverse

    _record_beat("approvals-fanout", "fail", "nobody is draining the email queue")
    client.force_login(staff)
    resp = client.get(reverse("heartbeat:status_overview"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The card, not the topbar nav link of the same name.
    idx = body.find('site-core-name">Approvals')
    assert idx != -1, "the Approvals core-service row is not on the rendered overview"
    window = body[max(0, idx - 400) : idx + 400]
    assert 'title="on"' not in window, "rendered Approvals card still claims 'on' while down"
    assert 'site-core-state down' in window, window
    assert "nobody is draining" in body, "the monitor's note never reached the page"


# --- F-33: the email channel's other silent prerequisite ---------------------
#
# F-01 fixed WHICH path the four channels point at. The bell rows use a relative
# URL and work. The two email templates build `{{ site_url }}{{ console_path }}`,
# and approvals mail is always sent without a request (signal receiver or task),
# so site_url falls back to SITE_DOMAIN — `localhost:8000` by default, documented
# nowhere in approvals. On any install that has not set it, including every
# `make run` demo, the emailed console link is dead. That is the headline
# non-staff story ("assignees decide via the emailed console link").


@pytest.mark.django_db
def test_monitor_reports_a_default_site_domain(requester, sample_kind, settings):
    settings.DEBUG = False
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    settings.SITE_DOMAIN = "localhost:8000"
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is False
    assert "SITE_DOMAIN" in result.note
    assert "localhost:8000" in result.note


@pytest.mark.django_db
@pytest.mark.parametrize("domain", ["localhost", "127.0.0.1:8065", "0.0.0.0", ""])
def test_every_local_default_counts_as_broken(requester, sample_kind, settings, domain):
    settings.DEBUG = False
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    settings.SITE_DOMAIN = domain
    assert ApprovalsFanoutMonitor().check().ok is False


@pytest.mark.django_db
def test_a_configured_site_domain_is_quiet(requester, sample_kind, settings):
    """Negative control — the check must not nag a correctly configured install."""
    settings.DEBUG = False
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    settings.SITE_DOMAIN = "approvals.example.com"
    result = ApprovalsFanoutMonitor().check()
    assert result.ok is True, result.note
    assert "SITE_DOMAIN" not in result.note


@pytest.mark.django_db
def test_the_check_is_skipped_when_it_cannot_apply(requester, sample_kind, settings):
    """Two exemptions, both deliberate: DEBUG (localhost IS the host) and
    emails-off (no links are being sent, so none can be dead)."""
    settings.SITE_DOMAIN = "localhost:8000"

    settings.DEBUG = True
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = True
    assert ApprovalsFanoutMonitor().check().ok is True

    settings.DEBUG = False
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = False
    assert ApprovalsFanoutMonitor().check().ok is True
