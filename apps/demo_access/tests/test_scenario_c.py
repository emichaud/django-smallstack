"""Scenario C — the app-owned half of the elevated-access gate.

Pins: the REST filing endpoint (the one that can attach a target), the
time-bound grant arithmetic, "no grant on any non-approval", and the local
webhook receiver's handler.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.demo_access import services as access
from apps.demo_access.models import AccessRequest, WebhookEcho
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()

FILE_URL = "/api/demo/access/requests/file/"


@pytest.fixture
def requester():
    return User.objects.create_user("c-svc", password="p", is_staff=True)


@pytest.fixture
def decider():
    return User.objects.create_user("c-approver", password="p", is_staff=True)


def token(user, level="staff"):
    _, raw = APIToken.create_token(user=user, name=f"t-{level}", access_level=level)
    return {"authorization": f"Bearer {raw}"}


def file_request(requester, **kwargs):
    defaults = {
        "resource": "dataset:payroll",
        "scope": "read",
        "reason": "test",
        "duration_hours": 8,
        "actor": requester,
    }
    defaults.update(kwargs)
    return access.file_access_request(**defaults)


# --- the filing endpoint ---------------------------------------------------


def test_rest_filing_attaches_the_target(client, requester):
    resp = client.post(
        FILE_URL,
        data=json.dumps({"resource": "dataset:payroll", "scope": "read", "duration_hours": 4}),
        content_type="application/json",
        headers=token(requester),
    )
    assert resp.status_code == 201
    payload = resp.json()
    ar = AccessRequest.objects.get(pk=payload["access_request_id"])
    req = ApprovalRequest.objects.get(pk=payload["approval_id"])
    assert req.target == ar  # the thing the generic endpoint cannot do
    assert (ar.state, ar.granted_until) == (AccessRequest.State.PENDING, None)


def test_rest_filing_refuses_a_readonly_token(client, requester):
    resp = client.post(
        FILE_URL,
        data=json.dumps({"resource": "dataset:payroll"}),
        content_type="application/json",
        headers=token(requester, "readonly"),
    )
    assert resp.status_code in (401, 403)
    assert not AccessRequest.objects.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},  # no resource
        {"resource": "x", "scope": "root"},  # bad scope
        {"resource": "x", "duration_hours": 0},  # out of range
        {"resource": "x", "duration_hours": 9999},
        {"resource": "x", "duration_hours": "soon"},
    ],
)
def test_rest_filing_validates_its_input(client, requester, payload):
    resp = client.post(
        FILE_URL,
        data=json.dumps(payload),
        content_type="application/json",
        headers=token(requester),
    )
    assert resp.status_code == 400
    assert not AccessRequest.objects.exists()


# --- the grant -------------------------------------------------------------


def test_approval_grants_for_exactly_duration_hours(requester, decider):
    ar, req = file_request(requester, duration_hours=6)
    expected = timezone.now() + timedelta(hours=6)
    approvals.approve(req, actor=decider)
    ar.refresh_from_db()
    assert ar.state == AccessRequest.State.GRANTED
    assert abs((ar.granted_until - expected).total_seconds()) < 5
    assert ar.is_active_grant is True


@pytest.mark.parametrize(
    "transition,expected",
    [
        ("reject", AccessRequest.State.REJECTED),
        ("cancel", AccessRequest.State.CANCELED),
    ],
)
def test_non_approval_grants_nothing(requester, decider, transition, expected):
    ar, req = file_request(requester)
    if transition == "reject":
        approvals.reject(req, actor=decider)
    else:
        approvals.cancel(req, actor=requester)
    ar.refresh_from_db()
    assert (ar.state, ar.granted_until) == (expected, None)


def test_expiry_grants_nothing(requester):
    ar, req = file_request(requester)
    req.expires_at = timezone.now() - timedelta(minutes=1)
    req.save(update_fields=["expires_at"])
    assert approvals.mark_expired() == 1
    ar.refresh_from_db()
    assert (ar.state, ar.granted_until) == (AccessRequest.State.EXPIRED, None)


def test_a_lapsed_grant_is_no_longer_active(requester, decider):
    ar, req = file_request(requester, duration_hours=1)
    approvals.approve(req, actor=decider)
    ar.refresh_from_db()
    ar.granted_until = timezone.now() - timedelta(minutes=1)
    ar.save(update_fields=["granted_until"])
    assert ar.is_active_grant is False


def test_the_kind_declares_the_extra_notify_mailbox():
    from apps.approvals.registry import get_kind
    from apps.demo_access.approvals import AUDIT_MAILBOX

    assert get_kind("access.grant").notify == [AUDIT_MAILBOX]


# --- the local webhook receiver -------------------------------------------


def test_the_receiver_handler_records_an_approval_event(requester, decider):
    """The handler turns a delivery into an inspectable WebhookEcho row."""
    from apps.demo_access.webhook_handlers import on_approval_event

    ar, req = file_request(requester)
    approvals.approve(req, actor=decider)

    class _Receipt:
        def json(self):
            return {
                "event": "smallstack_approvals.approvalrequest.updated",
                "data": {"id": req.pk, "status": "approved", "title": req.title},
                "resource": {"id": req.pk},
            }

    on_approval_event(_Receipt())
    echo = WebhookEcho.objects.get()
    assert (echo.approval_id, echo.status) == (req.pk, "approved")
    assert echo.event_type.endswith(".updated")


def test_the_receiver_handler_survives_an_unparseable_body():
    from apps.demo_access.webhook_handlers import on_approval_event

    class _Receipt:
        def json(self):
            return None

    on_approval_event(_Receipt())
    echo = WebhookEcho.objects.get()
    assert (echo.event_type, echo.approval_id, echo.status) == ("", None, "")
