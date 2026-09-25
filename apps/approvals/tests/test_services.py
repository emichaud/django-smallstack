"""The approval state machine — eligibility, races, callbacks, expiry.

These are the invariants the whole primitive stands on: transitions are
race-safe and single-winner, eligibility is identical on every surface
(it lives in one place), callbacks can fail without breaking decisions, and
expiry works with or without the background worker.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.utils import timezone

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from apps.approvals.registry import ApprovalKind, register_kind, unregister

pytestmark = pytest.mark.django_db


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


# --- filing -----------------------------------------------------------------


def test_request_stamps_requester_and_audits(requester, sample_kind):
    req = _file(requester, source="unit")
    assert req.requested_by == requester
    assert req.is_pending
    entry = LogEntry.objects.get(object_id=str(req.pk))
    assert "unit" in entry.change_message


def test_kind_default_expiry_applies(requester):
    register_kind(ApprovalKind(key="test.ttl", default_expires_in=timedelta(hours=2)))
    try:
        req = _file(requester, kind="test.ttl")
        assert req.expires_at is not None
        assert timedelta(hours=1) < (req.expires_at - timezone.now()) <= timedelta(hours=2)
    finally:
        unregister("test.ttl")


def test_settings_fallback_expiry(requester, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES = 30
    req = _file(requester)
    assert req.expires_at is not None


def test_unknown_kind_allowed_by_default_but_rejectable(requester):
    req = _file(requester, kind="nobody.registered.this")
    assert req.is_pending  # tolerated: rows outlive code churn
    with pytest.raises(services.UnknownKind) as exc:
        _file(requester, kind="nobody.registered.this", require_known_kind=True)
    assert "Known kinds" in str(exc.value)


def test_target_pointer_round_trip(requester, staff, sample_kind):
    req = _file(requester, target=staff)
    assert req.target == staff
    assert req.target_repr == str(staff)
    staff_pk = staff.pk
    staff.delete()
    req.refresh_from_db()
    assert req.target is None  # deleted target resolves to None, repr survives
    assert req.target_repr
    assert req.target_object_id == str(staff_pk)


# --- eligibility ------------------------------------------------------------


def test_staff_decides_by_default(requester, staff, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff, note="ok")
    assert req.status == ApprovalRequest.Status.APPROVED
    assert req.decided_by == staff


def test_non_staff_bystander_cannot_decide(requester, bystander, sample_kind):
    req = _file(requester)
    with pytest.raises(services.NotEligible):
        services.approve(req, actor=bystander)


def test_self_approval_blocked_by_default(staff, sample_kind):
    req = _file(staff)  # staff files their own request
    with pytest.raises(services.NotEligible):
        services.approve(req, actor=staff)


def test_self_approval_allowed_with_setting(staff, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE = True
    req = _file(staff)
    services.approve(req, actor=staff)
    assert req.status == ApprovalRequest.Status.APPROVED


def test_assignees_narrow_eligibility(requester, staff, assignee, bystander, sample_kind, settings):
    req = _file(requester, assignees=[assignee])
    # non-staff assignee CAN decide
    assert __import__("apps.approvals.permissions", fromlist=["can_decide"]).can_decide(
        assignee, req
    )
    # bystander cannot
    with pytest.raises(services.NotEligible):
        services.approve(req, actor=bystander)
    # staff override on (default): staff can still decide
    services.reject(req, actor=staff, note="staff override")
    assert req.status == ApprovalRequest.Status.REJECTED


def test_staff_override_can_be_disabled(requester, staff, assignee, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_STAFF_OVERRIDE = False
    req = _file(requester, assignees=[assignee])
    with pytest.raises(services.NotEligible):
        services.approve(req, actor=staff)
    services.approve(req, actor=assignee)
    assert req.status == ApprovalRequest.Status.APPROVED


def test_kind_hook_narrows_but_cannot_widen(requester, staff, bystander, settings):
    register_kind(
        ApprovalKind(key="test.hook", can_decide=lambda user, req: user.username == "staff")
    )
    register_kind(ApprovalKind(key="test.hook-open", can_decide=lambda user, req: True))
    try:
        from apps.approvals.permissions import can_decide

        narrowed = _file(requester, kind="test.hook")
        assert can_decide(staff, narrowed) is True
        # A hook returning True can NOT widen: bystander is still not staff.
        widened = _file(requester, kind="test.hook-open")
        assert can_decide(bystander, widened) is False
    finally:
        unregister("test.hook")
        unregister("test.hook-open")


def test_broken_hook_fails_closed(requester, staff):
    register_kind(
        ApprovalKind(key="test.broken", can_decide=lambda user, req: 1 / 0)
    )
    try:
        from apps.approvals.permissions import can_decide

        req = _file(requester, kind="test.broken")
        assert can_decide(staff, req) is False
    finally:
        unregister("test.broken")


# --- transitions ------------------------------------------------------------


def test_raced_decide_single_winner(requester, staff, staff2, sample_kind):
    req = _file(requester)
    # simulate staff2 winning between staff's load and update
    stale = ApprovalRequest.objects.get(pk=req.pk)
    services.approve(req, actor=staff2)
    with pytest.raises(services.NotPending) as exc:
        services.reject(stale, actor=staff)
    assert "already approved" in str(exc.value).lower()
    stale.refresh_from_db()
    assert stale.decided_by == staff2  # loser clobbered nothing


def test_decide_is_not_repeatable(requester, staff, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff)
    with pytest.raises(services.NotPending):
        services.approve(req, actor=staff)


def test_cancel_by_requester_and_gate(requester, bystander, sample_kind):
    req = _file(requester)
    with pytest.raises(services.NotEligible):
        services.cancel(req, actor=bystander)
    services.cancel(req, actor=requester, note="changed my mind")
    assert req.status == ApprovalRequest.Status.CANCELED


# --- callback ---------------------------------------------------------------


def test_callback_runs_with_terminal_status(requester, staff, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff)
    assert sample_kind.calls == [(req.pk, "approved")]


def test_callback_failure_recorded_but_decision_stands(requester, staff):
    register_kind(
        ApprovalKind(key="test.boom", on_decision=lambda req: 1 / 0)
    )
    try:
        req = _file(requester, kind="test.boom")
        services.approve(req, actor=staff)  # must NOT raise
        req.refresh_from_db()
        assert req.status == ApprovalRequest.Status.APPROVED
        assert "ZeroDivisionError" in req.callback_error
    finally:
        unregister("test.boom")


def test_dotted_path_callback_resolves(requester, staff):
    register_kind(
        ApprovalKind(key="test.dotted", on_decision="apps.approvals.tests.test_services._dotted_sink")
    )
    try:
        _DOTTED_CALLS.clear()
        req = _file(requester, kind="test.dotted")
        services.approve(req, actor=staff)
        assert _DOTTED_CALLS == [req.pk]
    finally:
        unregister("test.dotted")


_DOTTED_CALLS: list[int] = []


def _dotted_sink(req) -> None:
    _DOTTED_CALLS.append(req.pk)


# --- expiry -----------------------------------------------------------------


def test_lazy_expiry_on_decide(requester, staff, sample_kind):
    req = _file(requester, expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(services.NotPending) as exc:
        services.approve(req, actor=staff)
    assert "expired" in str(exc.value)
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.EXPIRED
    # the callback fired for the expiry transition too
    assert sample_kind.calls == [(req.pk, "expired")]


def test_mark_expired_sweep(requester, sample_kind):
    _file(requester, expires_at=timezone.now() - timedelta(minutes=5))
    _file(requester, expires_at=timezone.now() + timedelta(hours=1))
    _file(requester)  # no expiry
    assert services.mark_expired() == 1
    assert ApprovalRequest.objects.filter(status="expired").count() == 1
    assert services.mark_expired() == 0  # idempotent


# --- signals ----------------------------------------------------------------


def test_signals_fire_after_commit(requester, staff, sample_kind, django_capture_on_commit_callbacks):
    from apps.approvals.signals import approval_decided, approval_requested

    seen: list[str] = []
    approval_requested.connect(lambda sender, **kw: seen.append("requested"), weak=False)
    approval_decided.connect(
        lambda sender, **kw: seen.append(f"decided:{kw['request'].status}"), weak=False
    )
    with django_capture_on_commit_callbacks(execute=True):
        req = _file(requester)
    with django_capture_on_commit_callbacks(execute=True):
        services.approve(req, actor=staff)
    assert seen == ["requested", "decided:approved"]
