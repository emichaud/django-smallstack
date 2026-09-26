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


# --- F-15: the expiry transition leaves an audit trail -----------------------


def test_expiry_writes_a_system_audit_entry(requester, sample_kind, settings):
    """The docs promise a LogEntry with source `expiry`; it was unreachable.

    ``log_write`` no-ops without an acting user and LogEntry.user is a non-null
    FK, so the one terminal outcome no human caused was the one with no durable
    record — exactly the transition an auditor asks about.
    """
    req = _file(requester, expires_at=timezone.now() - timedelta(minutes=1))
    assert services.mark_expired() == 1

    entries = LogEntry.objects.filter(object_id=str(req.pk)).order_by("pk")
    change = [e for e in entries if "expiry" in e.change_message]
    assert change, [e.change_message for e in entries]
    system = change[-1].user
    assert system.username == settings.SMALLSTACK_AUDIT_SYSTEM_USERNAME
    # The system identity is a LABEL, not a credential: nothing can sign in as it.
    assert system.is_active is False
    assert system.is_staff is False
    assert system.has_usable_password() is False


def test_expiry_audit_can_be_switched_off(requester, sample_kind, settings):
    settings.SMALLSTACK_AUDIT_SYSTEM_USERNAME = ""
    req = _file(requester, expires_at=timezone.now() - timedelta(minutes=1))
    services.mark_expired()
    assert not LogEntry.objects.filter(object_id=str(req.pk), action_flag=2).exists()


# --- F-12: lazy expiry is bounded -------------------------------------------


def test_mark_expired_honours_a_limit_oldest_first(requester, sample_kind):
    now = timezone.now()
    reqs = [
        _file(requester, title=f"r{i}", expires_at=now - timedelta(minutes=10 - i))
        for i in range(5)
    ]
    assert services.mark_expired(limit=2) == 2
    statuses = [ApprovalRequest.objects.get(pk=r.pk).status for r in reqs]
    # The two most-overdue rows went first; the rest wait for the sweep.
    assert statuses[:2] == ["expired", "expired"]
    assert statuses[2:] == ["pending", "pending", "pending"]
    # Unbounded drains the remainder (negative control).
    assert services.mark_expired() == 3


def test_queue_page_load_does_not_fan_out_the_whole_backlog(
    client, requester, staff, sample_kind, settings
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.urls import reverse

    settings.SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT = 3
    now = timezone.now()
    for i in range(12):
        _file(requester, title=f"overdue {i}", expires_at=now - timedelta(minutes=i + 1))
    client.force_login(staff)
    with CaptureQueriesContext(connection) as ctx:
        assert client.get(reverse("approvals/requests-list")).status_code == 200
    assert ApprovalRequest.objects.filter(status="expired").count() == 3
    # The whole point: the bill is bounded by the limit, not by the backlog.
    assert len(ctx.captured_queries) < 200, len(ctx.captured_queries)


# --- F-19: one definition of "pending right now" -----------------------------


def test_actionable_excludes_overdue_rows_so_widget_and_queue_agree(
    requester, sample_kind
):
    now = timezone.now()
    live = _file(requester, title="live")
    _file(requester, title="overdue", expires_at=now - timedelta(minutes=1))
    _file(requester, title="never expires")

    assert ApprovalRequest.objects.pending().count() == 3
    assert ApprovalRequest.objects.overdue().count() == 1
    assert ApprovalRequest.objects.actionable().count() == 2

    from apps.approvals.dashboard_widgets import ApprovalsDashboardWidget

    assert ApprovalsDashboardWidget().get_data()["headline"] == "2 pending"
    # And it stays right after the sweep runs — no number changes on click.
    services.mark_expired()
    assert ApprovalsDashboardWidget().get_data()["headline"] == "2 pending"
    assert live.pk in set(ApprovalRequest.objects.actionable().values_list("pk", flat=True))


# --- F-11: the master switch means something --------------------------------


def test_disabled_app_refuses_every_state_change(requester, staff, sample_kind, settings):
    req = _file(requester)
    settings.SMALLSTACK_APPROVALS_ENABLED = False
    with pytest.raises(services.ApprovalsDisabled):
        _file(requester, title="while dark")
    with pytest.raises(services.ApprovalsDisabled):
        services.decide(req, actor=staff, approved=True)
    with pytest.raises(services.ApprovalsDisabled):
        services.cancel(req, actor=requester)
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.PENDING
    assert services.enabled() is False


def test_disabled_app_does_not_mount_its_urls():
    """The URLs live behind the switch in apps/smallstack/site_urls.py, mirroring
    the SMALLSTACK_MCP_ENABLED precedent. URLconfs are built at import time, so
    this asserts the gate exists rather than re-importing the URLconf."""
    from pathlib import Path

    import apps.smallstack.site_urls as site_urls

    source = Path(site_urls.__file__).read_text()
    assert 'if getattr(settings, "SMALLSTACK_APPROVALS_ENABLED", True):' in source
    assert 'if getattr(settings, "SMALLSTACK_NOTIFICATIONS_ENABLED", True):' in source


# --- F-18: the pending cap --------------------------------------------------


def test_pending_cap_is_per_requester_and_per_kind(requester, staff, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER = 1
    _file(requester)
    with pytest.raises(services.TooManyPending):
        _file(requester)
    # A different requester is unaffected...
    _file(staff)
    # ...and so is a different kind.
    register_kind(ApprovalKind(key="test.other"))
    try:
        _file(requester, kind="test.other")
    finally:
        unregister("test.other")


# --- F-31: the documented 503 has to be reachable -----------------------------
#
# F-11's main defect is fixed — the app really does boot dark. The error story
# layered on top did not hold: approvals' own two handlers caught
# ApprovalsDisabled and returned 503, and its OpenAPI block declared 503, but the
# only routes that reach those handlers are UNMOUNTED whenever the exception can
# be raised. So the 503 could never be observed, while the *reachable* failure —
# any downstream app's endpoint calling services.request_approval — was an
# unhandled 500. Fixed generically: ApprovalsDisabled is a
# smallstack.exceptions.FeatureDisabled, which api_view translates for every
# endpoint in the project.


def test_approvals_disabled_is_a_feature_disabled():
    """The generic marker is what makes the 503 reachable from any app."""
    from apps.smallstack.exceptions import FeatureDisabled

    assert issubclass(services.ApprovalsDisabled, FeatureDisabled)
    assert issubclass(services.ApprovalsDisabled, services.ApprovalError)
    # Its siblings are NOT 503s — a not-eligible is not "the feature is off".
    for other in (services.NotEligible, services.NotPending, services.UnknownKind):
        assert not issubclass(other, FeatureDisabled), other


def test_a_downstream_endpoint_degrades_to_503_not_500(client, settings, requester):
    """Any @api_view endpoint that files an approval, with approvals switched off.

    A synthetic endpoint stands in for the three scenario apps: the property under
    test belongs to `api_view`, not to any one app, and a base test must not
    depend on apps that are not in a stock checkout.
    """
    import json

    from django.test import RequestFactory

    from apps.smallstack.api import api_view

    @api_view(methods=["POST"], require_auth=False)
    def files_an_approval(request):
        services.request_approval(
            kind="test.sample", title="from a downstream app", actor=None
        )
        return {"ok": True}

    settings.SMALLSTACK_APPROVALS_ENABLED = False
    request = RequestFactory().post(
        "/api/demo/thing/", data="{}", content_type="application/json"
    )
    resp = files_an_approval(request)
    assert resp.status_code == 503, resp.status_code
    assert resp["Content-Type"].startswith("application/json")
    payload = json.loads(resp.content)
    text = json.dumps(payload)
    # The standard envelope, and a message that NAMES the setting rather than
    # just saying "unavailable".
    assert "errors" in payload, payload
    assert "SMALLSTACK_APPROVALS_ENABLED" in text, text


def test_the_same_endpoint_is_a_200_when_approvals_is_on(client, settings, requester, sample_kind):
    """Negative control — the 503 branch must not swallow the working path."""
    from django.test import RequestFactory

    from apps.smallstack.api import api_view

    @api_view(methods=["POST"], require_auth=False)
    def files_an_approval_ok(request):
        services.request_approval(
            kind="test.sample", title="from a downstream app", actor=requester
        )
        return {"ok": True}

    settings.SMALLSTACK_APPROVALS_ENABLED = True
    request = RequestFactory().post(
        "/api/demo/thing/", data="{}", content_type="application/json"
    )
    assert files_an_approval_ok(request).status_code == 200


def test_permission_denied_also_gets_the_envelope(client):
    """The sibling translation added alongside it (F-27's hook raises this)."""
    import json

    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory

    from apps.smallstack.api import api_view

    @api_view(methods=["GET"], require_auth=False)
    def refuses(request):
        raise PermissionDenied("not yours")

    resp = refuses(RequestFactory().get("/api/demo/thing/"))
    assert resp.status_code == 403
    assert resp["Content-Type"].startswith("application/json")
    assert "not yours" in json.dumps(json.loads(resp.content))
