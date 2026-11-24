"""Round 3 of Test Lab evaluation 45: the lower-priority findings, one test
(or more) each, named by finding code."""

from __future__ import annotations

import json
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from apps.access import reviews
from apps.access.models import AccessEvent
from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.approvals.permissions import can_view, viewable_requests
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
PERIOD = (date(2026, 7, 1), date(2026, 9, 30))


@pytest.fixture
def attester(db):
    user = User.objects.create_user("attester", password="p", is_staff=True, email="att@x.test")
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def plain_staff(db):
    return User.objects.create_user("plainstaff", password="p", is_staff=True, email="ps@x.test")


@pytest.fixture
def removal(attester, manager, root):
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="privileged", actor=attester)
    item = review.items.get(user_label="manager")
    item = reviews.decide(item, "remove", actor=attester, note="left")
    return ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))


# --- A-csrf ---------------------------------------------------------------------


def test_a_session_write_to_the_api_needs_the_csrf_token(root):
    """A-csrf: a signed-in browser can't be made to write over REST by another
    site; with the token (as first-party pages send it) the write runs, and a
    Bearer token needs none."""
    from apps.approvals.registry import ApprovalKind, register_kind

    register_kind(ApprovalKind(key="tests.csrf"))
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(root)
    body = json.dumps({"kind": "tests.csrf", "title": "csrf probe"})
    url = "/smallstack/api/approvals/requests/create/"
    refused = browser.post(url, body, content_type="application/json")
    assert refused.status_code == 403 and "CSRF" in refused.json()["errors"]["__all__"][0]
    assert not ApprovalRequest.objects.filter(kind="tests.csrf").exists()
    browser.get("/smallstack/")  # sets the csrftoken cookie
    token = browser.cookies["csrftoken"].value
    ok = browser.post(url, body, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 201 and ApprovalRequest.objects.filter(kind="tests.csrf").count() == 1
    raw = APIToken.create_token(user=root, name="csrf", access_level="staff")[1]
    auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    bearer = Client(enforce_csrf_checks=True).post(url, body, content_type="application/json", **auth)
    assert bearer.status_code == 201
    # Reads stay open to the session.
    assert browser.get("/smallstack/api/access/findings/").status_code == 200


def test_a_dry_run_preview_keeps_working_on_a_session(root):
    """The dashboards previews are dry runs and stay CSRF-free; a saving route isn't."""
    from apps.dashboards.api import CardPreviewApiView, MetricEntriesApiView, PreviewApiView

    assert PreviewApiView.dry_run and CardPreviewApiView.dry_run and not MetricEntriesApiView.dry_run


# --- D-2 ------------------------------------------------------------------------


def test_deleting_a_live_token_records_its_revocation_on_every_path(root):
    """D-2: a delete is a revocation first, recorded, whichever surface deletes."""
    token, _ = APIToken.create_token(user=root, name="to-delete", access_level="staff")
    pk = token.pk
    token.delete()
    assert AccessEvent.objects.filter(kind="token_revoked", detail__token_id=pk).count() == 1


def test_a_token_manager_cannot_delete_a_superusers_token_in_admin(root):
    tm = User.objects.create_user("tm", password="p", is_staff=True)
    tm.groups.add(Group.objects.get(name="Token manager"))
    token, _ = APIToken.create_token(user=root, name="su-token", access_level="auth")
    c = Client()
    c.force_login(tm)
    assert c.get(f"/admin/smallstack/apitoken/{token.pk}/delete/").status_code == 403
    c.post(f"/admin/smallstack/apitoken/{token.pk}/delete/", {"post": "yes"})
    c.post("/admin/smallstack/apitoken/", {"action": "delete_selected", "_selected_action": [token.pk], "post": "yes"})
    assert APIToken.objects.filter(pk=token.pk, is_active=True).exists()


# --- V2-8 -----------------------------------------------------------------------


def test_decide_and_cancel_answer_404_for_any_request_the_caller_cannot_see(root, alice):
    """V2-8: missing, pending and decided all read the same to a non-participant."""
    pending = approvals.request_approval(kind="tests.enum", title="p", actor=root)
    decided = approvals.request_approval(kind="tests.enum", title="d", actor=root)
    other = User.objects.create_superuser("root2", password="p")
    approvals.reject(decided, actor=other)
    c = Client()
    c.force_login(alice)  # active, not staff, not a participant
    for pk in (999999, pending.pk, decided.pk):
        assert c.post(f"/smallstack/approvals/requests/{pk}/decide/", {"decision": "approve"}).status_code == 404
        assert c.post(f"/smallstack/approvals/requests/{pk}/cancel/").status_code == 404
    pending.refresh_from_db()
    assert pending.status == "pending"


# --- T3-9 / T3-6 ------------------------------------------------------------------


def test_only_access_readers_see_a_removal(removal, plain_staff, attester, manager, root):
    """T3-9: the removal's context (who, why) is readable by its requester,
    its assignees and staff who may read access; not by any staff."""
    assert not can_view(plain_staff, removal)
    assert removal not in viewable_requests(plain_staff)
    assert can_view(attester, removal) and can_view(root, removal)
    # A kind without view_permission keeps the default: any staff sees it.
    plain = approvals.request_approval(kind="tests.plain", title="x", actor=root)
    assert can_view(plain_staff, plain) and plain in viewable_requests(plain_staff)
    c = Client()
    c.force_login(plain_staff)
    assert c.get(f"/smallstack/approvals/requests/{removal.pk}/").status_code == 404


def test_a_removal_is_announced_to_its_deciders_only(removal, attester, plain_staff, manager, root):
    """T3-6: not to all staff, and not to the account being removed."""
    from apps.approvals.emails import approver_users

    told = {u.username for u in approver_users(removal)}
    assert "root" in told
    assert "manager" not in told and "plainstaff" not in told and "attester" not in told
    from apps.notifications.models import Notification

    assert not Notification.objects.filter(recipient=manager, kind__startswith="approvals").exists()
    assert not Notification.objects.filter(recipient=plain_staff, kind__startswith="approvals").exists()


# --- T2-9 -----------------------------------------------------------------------


def _mcp(token, name, args):
    c = Client()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    resp = c.post("/mcp/", json.dumps(body), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}",
                  HTTP_ACCEPT="application/json, text/event-stream")
    return resp.json()


def test_any_token_tier_of_an_access_reader_reads_over_mcp(staffer, plain_staff):
    """T2-9: as over REST, the tier doesn't gate the reads; view_user does."""
    for tier in ("readonly", "auth", "staff"):
        raw = APIToken.create_token(user=staffer, name=f"t29-{tier}", access_level=tier)[1]
        out = _mcp(raw, "access_findings", {})
        text = json.loads(out["result"]["content"][0]["text"])
        assert "findings" in text, (tier, out)
    raw = APIToken.create_token(user=plain_staff, name="t29-plain", access_level="auth")[1]
    out = _mcp(raw, "access_findings", {})
    refused = out.get("error") or json.loads(out["result"]["content"][0]["text"]).get("error")
    assert refused, out
