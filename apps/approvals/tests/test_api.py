"""The REST surface — the token access matrix and the error contract.

The matrix that matters: readonly tokens may poll but never write (refused by
api_view structurally, before our code runs); auth-level tokens file and —
when eligible — decide; ineligible callers get 403, decided rows 409, and
invisible rows 404 (existence-hiding via the scoper).
"""

from __future__ import annotations

import pytest

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

CREATE_URL = "/smallstack/api/approvals/requests/create/"
LIST_URL = "/smallstack/api/approvals/requests/"


def _decide_url(req):
    return f"/smallstack/api/approvals/requests/{req.pk}/decide/"


def _bearer(user, access_level="auth"):
    _token, raw = APIToken.create_token(user=user, name=f"t-{access_level}", access_level=access_level)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


# --- create -----------------------------------------------------------------


def test_create_requires_auth(client, sample_kind):
    resp = client.post(CREATE_URL, {"kind": "test.sample", "title": "x"},
                       content_type="application/json")
    assert resp.status_code in (401, 403)


def test_readonly_token_cannot_create(client, requester, sample_kind):
    resp = client.post(
        CREATE_URL,
        {"kind": "test.sample", "title": "x"},
        content_type="application/json",
        **_bearer(requester, "readonly"),
    )
    assert resp.status_code == 403
    assert ApprovalRequest.objects.count() == 0


def test_create_files_and_serializes(client, requester, sample_kind):
    resp = client.post(
        CREATE_URL,
        {"kind": "test.sample", "title": "Ship it", "context": {"n": 3},
         "expires_in_minutes": 60},
        content_type="application/json",
        **_bearer(requester),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["kind"] == "test.sample"
    assert data["expires_at"] is not None
    req = ApprovalRequest.objects.get(pk=data["id"])
    assert req.requested_by == requester
    assert req.context == {"n": 3}


def test_create_unknown_kind_is_400_listing_known(client, requester, sample_kind):
    resp = client.post(
        CREATE_URL,
        {"kind": "tpyo.kind", "title": "x"},
        content_type="application/json",
        **_bearer(requester),
    )
    assert resp.status_code == 400
    msg = resp.json()["errors"]["__all__"][0]
    assert "tpyo.kind" in msg and "test.sample" in msg


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "no kind"},
        {"kind": "test.sample"},
        {"kind": "test.sample", "title": "x", "context": "not-an-object"},
        {"kind": "test.sample", "title": "x", "expires_in_minutes": "soon"},
    ],
)
def test_create_validation_400s(client, requester, sample_kind, payload):
    resp = client.post(CREATE_URL, payload, content_type="application/json", **_bearer(requester))
    assert resp.status_code == 400


# --- decide -----------------------------------------------------------------


def test_decide_approves(client, requester, staff, sample_kind):
    req = _file(requester)
    resp = client.post(
        _decide_url(req),
        {"approved": True, "note": "ok"},
        content_type="application/json",
        **_bearer(staff, "staff"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"
    req.refresh_from_db()
    assert req.decided_by == staff


def test_decide_requires_boolean_approved(client, requester, staff, sample_kind):
    req = _file(requester)
    resp = client.post(
        _decide_url(req), {"approved": "yes"}, content_type="application/json",
        **_bearer(staff, "staff"),
    )
    assert resp.status_code == 400


def test_decide_self_approval_is_403(client, staff, sample_kind):
    req = _file(staff)
    resp = client.post(
        _decide_url(req), {"approved": True}, content_type="application/json",
        **_bearer(staff, "staff"),
    )
    assert resp.status_code == 403
    req.refresh_from_db()
    assert req.is_pending


def test_decide_invisible_row_is_404_not_403(client, requester, bystander, sample_kind):
    """Existence-hiding: a row the caller can't view must not confirm it exists."""
    req = _file(requester)
    resp = client.post(
        _decide_url(req), {"approved": True}, content_type="application/json",
        **_bearer(bystander),
    )
    assert resp.status_code == 404


def test_decide_already_decided_is_409(client, requester, staff, staff2, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff2)
    resp = client.post(
        _decide_url(req), {"approved": False}, content_type="application/json",
        **_bearer(staff, "staff"),
    )
    assert resp.status_code == 409
    assert "approved" in resp.json()["errors"]["__all__"][0].lower()


def test_non_staff_assignee_decides_via_rest(client, requester, assignee, sample_kind):
    req = _file(requester, assignees=[assignee])
    resp = client.post(
        _decide_url(req), {"approved": True}, content_type="application/json",
        **_bearer(assignee),
    )
    assert resp.status_code == 200
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.APPROVED


# --- the CRUD poll surface --------------------------------------------------


def test_readonly_token_can_poll_list_and_detail(client, requester, staff, sample_kind):
    req = _file(requester)
    headers = _bearer(staff, "readonly")
    listing = client.get(LIST_URL, **headers)
    assert listing.status_code == 200
    assert any(r["id"] == req.pk for r in listing.json()["results"])
    detail = client.get(f"{LIST_URL}{req.pk}/", **headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"  # the poll story


def test_crud_surface_has_no_write_endpoints(client, staff, sample_kind):
    """actions=[LIST, DETAIL] ⇒ no CRUD create; filing goes through create/."""
    resp = client.post(
        LIST_URL, {"kind": "test.sample", "title": "x"},
        content_type="application/json", **_bearer(staff, "staff"),
    )
    assert resp.status_code in (404, 405)
