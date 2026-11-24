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


# --- Batch 2: the access app ---------------------------------------------------------

from io import StringIO  # noqa: E402

from django.core.management import call_command  # noqa: E402

from apps.access import directory, evidence, registry  # noqa: E402
from apps.access.models import AccessReview, AccessReviewItem, ReviewLocked  # noqa: E402
from apps.access.registry import map_directory_role, register_group, run_checks, sync_groups  # noqa: E402


@pytest.fixture
def dir_groups(monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    monkeypatch.setattr(registry, "_role_overlays", dict(registry._role_overlays))
    register_group("Ops team", permissions=["auth.view_group"], app_label="tests", directory_role="Ops.Team")
    sync_groups(source="test")
    return Group.objects.get(name="Ops team")


def _signed_review(attester, attester2):
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="all", actor=attester)
    reviews.confirm_all(review, actor=attester)
    reviews.decide(review.items.get(user_label=attester.username), "confirmed", actor=attester2)
    return reviews.sign(
        review, actor=attester, typed_name=attester.username, request_id="req_sign", signed_from="10.0.0.9"
    )


@pytest.fixture
def attester2(db):
    user = User.objects.create_user("attester2", password="p", is_staff=True)
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


def test_bulk_writes_to_a_signed_review_are_refused(attester, attester2):
    """T3-1: the lock holds below save(): QuerySet update()/delete() too."""
    review = _signed_review(attester, attester2)
    with pytest.raises(ReviewLocked):
        AccessReview.objects.filter(pk=review.pk).update(note="rewritten")
    with pytest.raises(ReviewLocked):
        AccessReview.objects.filter(pk=review.pk).delete()
    with pytest.raises(ReviewLocked):
        AccessReviewItem.objects.filter(review=review).update(decision="remove")
    with pytest.raises(ReviewLocked):
        review.items.all().delete()
    review.refresh_from_db()
    assert review.note == "" and review.items.count() >= 2
    # Open reviews stay writable in bulk.
    open_review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="privileged", actor=attester)
    assert AccessReview.objects.filter(pk=open_review.pk).update(note="ok") == 1


def test_the_payload_carries_the_signing_ip_and_both_request_ids(attester, attester2):
    """T3-5, G2-6."""
    review = _signed_review(attester, attester2)
    data = reviews.review_payload(review)
    assert data["signed_from"] == "10.0.0.9" and data["signed_request_id"] == "req_sign"
    out = StringIO()
    call_command("access", "review", "show", str(review.pk), "--json", stdout=out)
    assert json.loads(out.getvalue())["signed_from"] == "10.0.0.9"


def test_new_accounts_are_flagged_and_first_in_every_export(attester, attester2):
    """T3-14: the CLI, REST and CSV carry the page's new flag and order."""
    _signed_review(attester, attester2)
    User.objects.create_user("zz-newcomer", password="p", is_staff=True)
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="all", actor=attester)
    items = reviews.review_payload(review)["items"]
    assert items[0]["username"] == "zz-newcomer" and items[0]["new"] is True
    assert all(i["new"] is False for i in items[1:])
    rows = list(reviews.review_csv_rows(review))
    assert rows[0]["username"] == "zz-newcomer" and rows[0]["new_since_last_review"] is True


def test_a_second_remove_keeps_the_first_reason(attester, manager, root):
    """T3-10: the approval keeps the first reason, and so does the row."""
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="privileged", actor=attester)
    item = reviews.decide(review.items.get(user_label="manager"), "remove", actor=attester, note="left in August")
    item = reviews.decide(item, "remove", actor=attester, note="confirmed with HR")
    assert item.note == "left in August · confirmed with HR"


def test_a_withdrawn_removal_names_who_changed_the_decision(attester, attester2, manager, root):
    """G2-8: canceled by the attester who changed the row when they may, and
    the note names them either way."""
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="privileged", actor=attester)
    item = reviews.decide(review.items.get(user_label="manager"), "remove", actor=attester)
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    reviews.decide(item, "flagged", actor=attester2, note="ask HR")
    req.refresh_from_db()
    assert req.status == "canceled" and "attester2" in req.decision_note


def test_the_sign_name_message_says_case_does_not_matter(attester, attester2):
    """T3-7."""
    review = reviews.open_review(period_start=PERIOD[0], period_end=PERIOD[1], scope="all", actor=attester)
    reviews.confirm_all(review, actor=attester)
    reviews.decide(review.items.get(user_label=attester.username), "confirmed", actor=attester2)
    assert "don't matter" in reviews.sign_refusal(review, attester, "someone else")
    assert reviews.sign_refusal(review, attester, "  ATTESTER ") == ""


def test_admin_group_pages_refuse_a_directory_group(dir_groups, root):
    """G2-3: no rename, no permission change, no delete (single or bulk)."""
    member = User.objects.create_user("ed", password="p")
    directory.sign_in("proxy", "sub-ed", ["Ops.Team"], email="ed@x.test")
    member = User.objects.get(directory_identities__subject="sub-ed")
    c = Client()
    c.force_login(root)
    assert c.get(f"/admin/auth/group/{dir_groups.pk}/delete/").status_code == 403
    c.post(f"/admin/auth/group/{dir_groups.pk}/delete/", {"post": "yes"})
    c.post(f"/admin/auth/group/{dir_groups.pk}/change/", {"name": "renamed", "permissions": []})
    c.post("/admin/auth/group/", {"action": "delete_selected", "_selected_action": [dir_groups.pk], "post": "yes"})
    dir_groups.refresh_from_db()
    assert dir_groups.name == "Ops team" and dir_groups.permissions.exists()
    assert member.groups.filter(pk=dir_groups.pk).exists()
    local = Group.objects.create(name="Local only")
    c.post("/admin/auth/group/", {"action": "delete_selected", "_selected_action": [local.pk], "post": "yes"})
    assert not Group.objects.filter(pk=local.pk).exists()


def test_the_mcp_proposal_refuses_a_directory_group(dir_groups, root, alice):
    """T2-3: no request is filed that every decision would refuse."""
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=root, token=None))
    try:
        out = TOOL_HANDLERS["access_request_membership"](
            {"username": "alice", "group": "Ops team", "member": True, "reason": "x"}
        )
    finally:
        reset_context(token)
    assert out["error"]["code"] == "directory_managed"
    assert not ApprovalRequest.objects.filter(kind="access.membership").exists()


def test_recognised_roles_lets_a_middleware_refuse_before_creating(dir_groups):
    """T2-4: the fail-closed check runs before any account exists."""
    before = User.objects.count()
    assert directory.recognised_roles(["Nope", "Other"]) == []
    assert directory.recognised_roles(None) == []
    assert directory.recognised_roles(["Ops.Team", "Nope"]) == ["Ops.Team"]
    assert User.objects.count() == before


def test_the_cli_json_is_one_document_and_groups_show_their_role(dir_groups):
    """T2-6, T2-7."""
    out = StringIO()
    call_command("access", "groups", "--json", stdout=out)
    rows = json.loads(out.getvalue())
    assert any(r["name"] == "Ops team" for r in rows)
    # Laid out as json.dumps lays it out, not a newline after every token.
    assert out.getvalue().strip() == json.dumps(rows, indent=2, default=str)
    text = StringIO()
    call_command("access", "groups", stdout=text)
    assert "directory: Ops.Team" in text.getvalue()


def test_an_unmatched_role_mapping_is_a_system_check_warning(monkeypatch):
    """T2-8."""
    from apps.access.system_checks import check_directory_role_overlays

    monkeypatch.setattr(registry, "_role_overlays", dict(registry._role_overlays))
    map_directory_role("Acess reviewer", "Typo.Role")
    ids = [w.id for w in check_directory_role_overlays()]
    assert ids == ["access.W001"]


def test_a_directory_account_with_a_local_password_is_a_finding(dir_groups):
    """T2-10."""
    bob = User.objects.create_user("bob", email="bob@x.test", password="old-local")
    directory.sign_in("proxy", "sub-bob", ["Ops.Team"], email="bob@x.test")
    f = next(f for f in run_checks() if f.key == "directory_password_beside_identity")
    assert f.severity == "warning" and [r["label"] for r in f.rows] == ["bob"]
    bob.set_unusable_password()
    bob.save()
    assert next(f for f in run_checks() if f.key == "directory_password_beside_identity").count == 0


def test_register_sheet_guards(monkeypatch):
    """G2-4: 'cover' is refused; a builder whose Sheet names another key is
    filed under the registered one."""
    monkeypatch.setattr(evidence, "_SHEETS", list(evidence._SHEETS))
    with pytest.raises(ValueError, match="cover"):
        evidence.register_sheet("cover", lambda s, e, sc: None)
    evidence.register_sheet(
        "vendors", lambda s, e, sc: evidence.Sheet(key="vendor_accounts", title="V", description="", columns=("a",))
    )
    pack = evidence.build(*PERIOD, only=["vendors"])
    assert pack.sheet("vendors").key == "vendors"


def test_stored_packs_go_to_a_temporary_media_root(settings, root):
    """G2-7."""
    from apps.access import cadence

    bundle = cadence.store_bundle(*PERIOD, "all", actor=root)
    assert str(settings.MEDIA_ROOT) in bundle.file.path and "fix-access/media" not in bundle.file.path
