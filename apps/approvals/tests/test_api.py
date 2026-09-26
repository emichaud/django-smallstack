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


# --- F-02: the filing identity can read its own request ----------------------


def test_non_staff_can_poll_its_own_request_but_not_anyone_elses(
    client, requester, bystander, sample_kind
):
    """The advertised "file, then poll until decided" loop must close for a
    non-staff identity — an AI agent, a SPA user.

    The CRUD read surface used to inherit StaffRequiredMixin, so a non-staff
    caller got 403 on the list AND on its own detail while being allowed to POST
    a decision: write-without-read. Existence-hiding scoping is the documented
    model and the decide endpoint already used it.
    """
    mine = _file(requester)
    theirs = _file(bystander)
    headers = _bearer(requester)

    listing = client.get(LIST_URL, **headers)
    assert listing.status_code == 200
    ids = {r["id"] for r in listing.json()["results"]}
    assert ids == {mine.pk}

    assert client.get(f"{LIST_URL}{mine.pk}/", **headers).status_code == 200
    # Not 403 — a viewer who may not see a row is told it isn't there.
    assert client.get(f"{LIST_URL}{theirs.pk}/", **headers).status_code == 404


def test_non_staff_assignee_can_read_the_row_it_may_decide(
    client, requester, assignee, sample_kind
):
    req = _file(requester, assignees=[assignee])
    headers = _bearer(assignee)
    assert client.get(f"{LIST_URL}{req.pk}/", **headers).status_code == 200
    assert client.post(
        _decide_url(req), {"approved": True}, content_type="application/json", **headers
    ).status_code == 200


# --- F-10: a deactivated account's token decides nothing ---------------------


def test_deactivated_staff_token_cannot_read_or_decide(
    client, requester, staff, sample_kind
):
    req = _file(requester)
    headers = _bearer(staff, "staff")
    assert client.get(f"{LIST_URL}{req.pk}/", **headers).status_code == 200  # control

    staff.is_active = False
    staff.save()

    assert client.get(LIST_URL, **headers).status_code == 401
    assert client.get(f"{LIST_URL}{req.pk}/", **headers).status_code == 401
    resp = client.post(
        _decide_url(req), {"approved": True}, content_type="application/json", **headers
    )
    assert resp.status_code == 401
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.PENDING
    assert req.decided_by is None


# --- F-17: errors are always the JSON envelope -------------------------------


def test_decide_404_is_json_not_html(client, staff, sample_kind):
    resp = client.post(
        "/smallstack/api/approvals/requests/999999/decide/",
        {"approved": True},
        content_type="application/json",
        **_bearer(staff, "staff"),
    )
    assert resp.status_code == 404
    assert resp["Content-Type"].startswith("application/json")
    assert "999999" in resp.json()["errors"]["__all__"][0]


def test_api_view_translates_http404_into_the_envelope(client, staff):
    """The generic half of F-17: any @api_view endpoint that raises Http404 —
    get_object_or_404 being the obvious way — answers JSON, not an HTML page."""
    from django.http import Http404

    from apps.smallstack.api import api_view

    @api_view(methods=["GET"], require_auth=False)
    def _raiser(request):
        raise Http404("nope")

    from django.test import RequestFactory

    resp = _raiser(RequestFactory().get("/x/"))
    assert resp.status_code == 404
    assert resp["Content-Type"].startswith("application/json")


# --- F-03: target + assignees on the remote filing surface -------------------


def test_create_accepts_a_target_so_no_app_needs_its_own_endpoint(
    client, requester, staff, sample_kind
):
    resp = client.post(
        CREATE_URL,
        {
            "kind": "test.sample",
            "title": "points at a row",
            "target": f"smallstack_approvals.approvalrequest:{_file(requester).pk}",
        },
        content_type="application/json",
        **_bearer(requester),
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["target_repr"]


def test_rest_shows_the_target_and_assignees_it_accepts(
    client, requester, assignee, staff, sample_kind
):
    """REST must round-trip what REST takes.

    `target_repr` is a human label; it used to be all a client got back, with
    `target` serializing to null (it is the *instance* property) and the
    assignees M2M invisible. So a client could file against a row, render a
    label for it, and never link back to it or re-derive which object it was —
    the duplication the target pointer exists to remove. (F-35.)
    """
    row = _file(requester)
    ref = f"smallstack_approvals.approvalrequest:{row.pk}"
    resp = client.post(
        CREATE_URL,
        {
            "kind": "test.sample",
            "title": "reads back what it accepts",
            "target": ref,
        },
        content_type="application/json",
        **_bearer(requester),
    )
    assert resp.status_code == 201, resp.content
    created = resp.json()
    # Identical spelling to the one `create` accepts, on create AND on detail.
    assert created["target_ref"] == ref
    assert created["assignee_usernames"] == []

    # Assigned server-side (this kind does not allowlist remote assignees), then
    # read back: the M2M was previously invisible to the wire entirely.
    ApprovalRequest.objects.get(pk=created["id"]).assignees.set([assignee])

    detail = client.get(
        f"/smallstack/api/approvals/requests/{created['id']}/", **_bearer(staff)
    )
    assert detail.status_code == 200, detail.content
    assert detail.json()["target_ref"] == ref
    assert detail.json()["assignee_usernames"] == [assignee.username]

    # The point of the spelling: it resolves back to the row, unaided.
    from apps.approvals.resolvers import resolve_target

    obj, err = resolve_target(detail.json()["target_ref"])
    assert err is None
    assert obj.pk == row.pk


def test_rest_and_mcp_report_the_same_target_identity(requester, sample_kind):
    """Both surfaces read the two model properties, so they cannot drift."""
    from apps.approvals.mcp_tools import _serialize as mcp_serialize

    row = _file(requester)
    target = _file(requester)
    row.set_target(target)
    row.save()

    assert row.target_ref == f"smallstack_approvals.approvalrequest:{target.pk}"
    assert mcp_serialize(row)["target"] == row.target_ref
    assert mcp_serialize(row)["assignees"] == row.assignee_usernames


def test_create_rejects_a_bad_target_and_unallowlisted_assignees(
    client, requester, assignee, sample_kind
):
    bad = client.post(
        CREATE_URL,
        {"kind": "test.sample", "title": "x", "target": "not-a-target"},
        content_type="application/json",
        **_bearer(requester),
    )
    assert bad.status_code == 400
    assert "app_label.model:pk" in bad.json()["errors"]["__all__"][0]

    # A remote caller must not be able to route a request at an arbitrary user.
    refused = client.post(
        CREATE_URL,
        {"kind": "test.sample", "title": "x", "assignees": [assignee.username]},
        content_type="application/json",
        **_bearer(requester),
    )
    assert refused.status_code == 400
    assert "assignable" in refused.json()["errors"]["__all__"][0]


def test_create_accepts_assignees_a_kind_allowlists(client, requester, assignee):
    from apps.approvals.registry import ApprovalKind, register_kind, unregister

    register_kind(ApprovalKind(key="test.routed", assignable=[assignee.username]))
    try:
        resp = client.post(
            CREATE_URL,
            {"kind": "test.routed", "title": "x", "assignees": [assignee.username]},
            content_type="application/json",
            **_bearer(requester),
        )
        assert resp.status_code == 201, resp.content
        req = ApprovalRequest.objects.get(pk=resp.json()["id"])
        assert list(req.assignees.all()) == [assignee]
    finally:
        unregister("test.routed")


# --- F-18: one identity cannot flood every approver's inbox ------------------


def test_pending_cap_returns_429(client, requester, settings, sample_kind):
    settings.SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER = 2
    headers = _bearer(requester)
    body = {"kind": "test.sample", "title": "spam"}
    codes = [
        client.post(CREATE_URL, body, content_type="application/json", **headers).status_code
        for _ in range(3)
    ]
    assert codes == [201, 201, 429]
    # 0 disables the cap (negative control).
    settings.SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER = 0
    assert client.post(
        CREATE_URL, body, content_type="application/json", **headers
    ).status_code == 201


# --- F-16: the OpenAPI document describes what these endpoints really do -----


def test_openapi_declares_the_real_responses_for_both_endpoints(client, staff):
    resp = client.get("/api/schema/openapi.json", **_bearer(staff, "staff"))
    assert resp.status_code == 200
    spec = resp.json()
    create = spec["paths"]["/smallstack/api/approvals/requests/create/"]["post"]
    decide = spec["paths"]["/smallstack/api/approvals/requests/{id}/decide/"]["post"]
    assert "201" in create["responses"]
    assert create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
    # 409-on-already-decided is how a racing client learns it lost; it was
    # invisible to every consumer of the spec.
    assert {"200", "403", "404", "409"} <= set(decide["responses"])
