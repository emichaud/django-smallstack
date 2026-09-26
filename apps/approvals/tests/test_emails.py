"""Email fan-out + the notification receivers.

Recipient rule under test — see emails.py's module docstring, which is the
authority: on REQUEST → active assignees else active-staff-with-email, plus
kind.notify and the setting, minus the requester; on DECISION → that same set
(which INCLUDES the decider) plus the requester plus the extras. The bell differs
from the email by exactly one person: it skips the actor. Failures are swallowed —
a mail outage must never break a decision.

The receivers fire on the real signals here (django_capture_on_commit_callbacks
+ the test ImmediateBackend runs the enqueued task inline → mail.outbox).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
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


def test_decided_goes_to_requester_and_the_other_approvers(mailed_users, sample_kind):
    """The requester learns the outcome; so do the approvers it left the queue of.

    Mailing only the requester left every other approver of a multi-approver
    request holding an "Approval needed" mail with no follow-up, forever. (F-13.)
    """
    req = _file(mailed_users["requester"])
    services.reject(req, actor=mailed_users["staff"], note="no")
    mail.outbox.clear()
    assert emails.send_decided(req.pk) == 1  # one message
    assert set(mail.outbox[-1].to) == {
        "req@example.com",  # the requester
        "staff@example.com",  # the approvers (it was on their plate)
        "staff2@example.com",
    }
    assert "Rejected" in mail.outbox[-1].subject


def test_decided_never_mails_a_deactivated_approver(mailed_users, sample_kind):
    """F-09: notify() skipped inactive users while email did not — one notion of
    "active", not two."""
    req = _file(mailed_users["requester"], assignees=[mailed_users["assignee"]])
    mailed_users["assignee"].is_active = False
    mailed_users["assignee"].save()
    mail.outbox.clear()
    emails.send_requested(req.pk)
    # Falls back to staff-with-email rather than mailing the offboarded assignee.
    assert "assignee@example.com" not in (mail.outbox[-1].to if mail.outbox else [])


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
    bells = Notification.objects.filter(kind="approvals.decided")
    assert mailed_users["requester"] in {n.recipient for n in bells}
    assert all("Approved" in n.title for n in bells)
    assert any("Approved" in m.subject for m in mail.outbox)


def test_decision_retires_the_stale_needed_bells_and_tells_the_other_approvers(
    mailed_users, sample_kind, django_capture_on_commit_callbacks
):
    """F-13: one approver decides; the others must not keep an unread
    "Approval needed" row pointing at a settled request, and must be told."""
    staff, staff2 = mailed_users["staff"], mailed_users["staff2"]
    with django_capture_on_commit_callbacks(execute=True):
        req = _file(mailed_users["requester"], assignees=[staff, staff2])

    needed = Notification.objects.filter(kind="approvals.requested")
    assert needed.count() == 2
    assert needed.filter(read_at__isnull=True).count() == 2
    assert all(n.subject_key == f"approvals.request:{req.pk}" for n in needed)

    with django_capture_on_commit_callbacks(execute=True):
        services.approve(req, actor=staff, note="go")

    # Every "needed" row is retired — the decider's included.
    assert (
        Notification.objects.filter(
            kind="approvals.requested", read_at__isnull=True
        ).count()
        == 0
    )
    # The OTHER approver learns the outcome (the actor is auto-skipped).
    decided = Notification.objects.filter(kind="approvals.decided")
    recipients = {n.recipient for n in decided}
    assert staff2 in recipients
    assert mailed_users["requester"] in recipients
    assert staff not in recipients


# --- F-32: a broken route must not become a silent broadcast ------------------
#
# F-09 correctly stopped mailing a deactivated assignee — and the filter emptied
# the assignee list, which means "fall back to every active staff user". So a
# request deliberately routed to ONE named approver became a 10-person broadcast
# the moment that person was offboarded, carrying its title and context to
# everyone with staff. Measured: 1 recipient / 1 bell → 6 recipients / 10 bells.


def test_deactivating_the_sole_assignee_is_flagged_not_silent(
    requester, staff, staff2, sample_kind, caplog
):
    import logging

    from apps.approvals import emails

    named = get_user_model().objects.create_user("f32-assignee", password="p", email="f32@example.test")
    req = services.request_approval(
        kind="test.sample", title="Routed to one person", actor=requester, assignees=[named]
    )

    # Control: while the assignee is active, routing is intact and narrow.
    assert emails.routing_is_broken(req) is False
    assert [u.username for u in emails.approver_users(req)] == ["f32-assignee"]
    assert emails.subject_prefix(req) == ""

    named.is_active = False
    named.save(update_fields=["is_active"])
    req.refresh_from_db()

    # The fallback still happens — the request must not go unseen …
    assert emails.routing_is_broken(req) is True
    fallback = {u.username for u in emails.approver_users(req)}
    assert fallback, "the request would now reach nobody at all"
    assert "f32-assignee" not in fallback
    # … but it is no longer silent, on either channel.
    assert emails.subject_prefix(req) == "(assignee deactivated) "
    with caplog.at_level(logging.WARNING, logger="smallstack.approvals"):
        emails.approver_users(req)
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("every named assignee is deactivated" in m for m in warnings), warnings
    assert any("f32-assignee" in m for m in warnings), warnings


def test_a_request_that_never_named_anyone_is_not_flagged(requester, staff, sample_kind):
    """Negative control: "nobody was named" is a different fact from "all gone".

    Without this distinction the prefix would appear on every ordinary
    no-assignee request, which is most of them.
    """
    from apps.approvals import emails

    req = services.request_approval(
        kind="test.sample", title="Open to any approver", actor=requester
    )
    assert emails.routing_is_broken(req) is False
    assert emails.subject_prefix(req) == ""
    assert {u.username for u in emails.approver_users(req)} == {"staff"}


def test_the_broadcast_says_why_on_the_email_subject_and_the_bell(
    mailed_users, sample_kind
):
    """End to end: the operator-visible strings, not just the helper."""
    from apps.notifications.models import Notification

    requester = mailed_users["requester"]
    named = get_user_model().objects.create_user(
        "f32-gone", password="p", email="gone@example.test"
    )
    req = services.request_approval(
        kind="test.sample", title="Laptop order", actor=requester, assignees=[named]
    )
    Notification.objects.all().delete()
    mail.outbox.clear()

    named.is_active = False
    named.save(update_fields=["is_active"])

    # Re-fire both channels for the now-unroutable request. The email task and
    # the bell are driven directly so the assertion is about the STRINGS, not
    # about on_commit plumbing (covered elsewhere in this file).
    from apps.approvals import emails as approval_emails
    from apps.approvals.receivers import notify_on_request

    notify_on_request(sender=None, request=req, actor=requester)
    approval_emails.send_requested(req.pk)

    subjects = [m.subject for m in mail.outbox]
    assert subjects, "no mail was sent at all"
    assert any("(assignee deactivated)" in s for s in subjects), subjects
    titles = list(Notification.objects.values_list("title", flat=True))
    assert titles, "no bell rows at all"
    assert any("(assignee deactivated)" in t for t in titles), titles
    assert approval_emails.subject_prefix(req) == "(assignee deactivated) "
