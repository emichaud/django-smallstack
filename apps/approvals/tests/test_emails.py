"""Email fan-out + the notification receivers.

Recipient rule under test (emails.py docstring): on request → assignees else
staff-with-email, plus kind.notify and the setting, minus the requester;
on decision → the requester plus the extras. Failures are swallowed — a mail
outage must never break a decision.

The receivers fire on the real signals here (django_capture_on_commit_callbacks
+ the test ImmediateBackend runs the enqueued task inline → mail.outbox).
"""

from __future__ import annotations

import pytest
from django.core import mail

from apps.approvals import emails, services
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def mailed_users(django_user_model):
    """Users WITH email addresses (the plain fixtures deliberately have none)."""
    return {
        "requester": django_user_model.objects.create_user(
            "m-req", email="req@example.com", password="p"
        ),
        "staff": django_user_model.objects.create_user(
            "m-staff", email="staff@example.com", password="p", is_staff=True
        ),
        "staff2": django_user_model.objects.create_user(
            "m-staff2", email="staff2@example.com", password="p", is_staff=True
        ),
        "assignee": django_user_model.objects.create_user(
            "m-assignee", email="assignee@example.com", password="p"
        ),
    }


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


# --- recipient computation ---------------------------------------------------


def test_requested_goes_to_staff_minus_requester(mailed_users, sample_kind):
    req = _file(mailed_users["staff"])  # staff files → other staff hear about it
    assert emails.send_requested(req.pk) == 1
    assert mail.outbox[-1].to == ["staff2@example.com"]
    assert "Approval needed" in mail.outbox[-1].subject


def test_requested_goes_to_assignees_when_set(mailed_users, sample_kind):
    req = _file(mailed_users["requester"], assignees=[mailed_users["assignee"]])
    emails.send_requested(req.pk)
    assert mail.outbox[-1].to == ["assignee@example.com"]  # staff NOT mailed


def test_extra_recipients_from_kind_and_setting(mailed_users, settings):
    from apps.approvals.registry import ApprovalKind, register_kind, unregister

    settings.SMALLSTACK_APPROVALS_NOTIFY_EMAILS = ["ops@example.com"]
    register_kind(ApprovalKind(key="test.notify", notify=["kind@example.com"]))
    try:
        req = _file(mailed_users["requester"], kind="test.notify")
        emails.send_requested(req.pk)
        assert set(mail.outbox[-1].to) >= {"kind@example.com", "ops@example.com"}
    finally:
        unregister("test.notify")


def test_decided_goes_to_requester(mailed_users, sample_kind):
    req = _file(mailed_users["requester"])
    services.reject(req, actor=mailed_users["staff"], note="no")
    mail.outbox.clear()
    assert emails.send_decided(req.pk) == 1
    assert mail.outbox[-1].to == ["req@example.com"]
    assert "Rejected" in mail.outbox[-1].subject


def test_emails_disabled_setting(mailed_users, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_EMAILS_ENABLED = False
    req = _file(mailed_users["staff"])
    assert emails.send_requested(req.pk) == 0
    assert mail.outbox == []


def test_send_failure_is_swallowed(mailed_users, sample_kind, monkeypatch):
    import apps.accounts.emails as accounts_emails

    def boom(**kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(accounts_emails, "send_branded_email", boom)
    req = _file(mailed_users["staff"])
    assert emails.send_requested(req.pk) == 0  # no raise — the request stands


def test_missing_row_returns_zero(db):
    assert emails.send_requested(999999) == 0
    assert emails.send_decided(999999) == 0


# --- the receiver fan-out (signals → bell + email) ---------------------------


def test_request_fans_out_bell_and_email(
    mailed_users, sample_kind, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        req = _file(mailed_users["requester"], assignees=[mailed_users["assignee"]])
    # in-app bell for the approver, never the requester
    bells = Notification.objects.filter(kind="approvals.requested")
    assert {n.recipient for n in bells} == {mailed_users["assignee"]}
    assert bells[0].url  # deep-links to the console
    # email rode the task queue (Immediate backend in tests → outbox)
    assert any("Approval needed" in m.subject for m in mail.outbox)
    assert req.pk  # filed


def test_decision_notifies_requester(
    mailed_users, sample_kind, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        req = _file(mailed_users["requester"])
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        services.approve(req, actor=mailed_users["staff"], note="go")
    bell = Notification.objects.get(kind="approvals.decided")
    assert bell.recipient == mailed_users["requester"]
    assert "Approved" in bell.title
    assert any("Approved" in m.subject for m in mail.outbox)
