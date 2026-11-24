"""Access reviews (attestations): a frozen roster, a named attester's decision
per account, a signature that locks it. Nothing here changes access."""

from __future__ import annotations

import json
from datetime import date
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.access import reviews
from apps.access.models import AccessEvent, AccessReview, ReviewLocked
from apps.access.registry import run_checks
from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/smallstack/api/access/"


@pytest.fixture
def attester(db):
    user = User.objects.create_user("attester", password="p", is_staff=True, first_name="Ann", last_name="Attester")
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def attester2(db):
    user = User.objects.create_user("attester2", password="p", is_staff=True)
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def period():
    return date(2026, 7, 1), date(2026, 9, 30)


@pytest.fixture
def review(attester, manager, alice, root, period):
    return reviews.open_review(period_start=period[0], period_end=period[1], scope="privileged", actor=attester)


def finding(key):
    return next(f for f in run_checks() if f.key == key)


def item_for(review, user):
    return review.items.get(user_label=user.get_username())


# --- Opening ----------------------------------------------------------------------


def test_opening_freezes_the_privileged_roster(review, attester, manager, alice, root, staffer):
    names = set(review.items.values_list("user_label", flat=True))
    # root (superuser), manager (change_user), attester (sign_accessreview) are privileged; alice isn't.
    assert {"root", "manager", "attester"} <= names and "alice" not in names
    facts = item_for(review, manager).facts
    assert facts["groups"] == [] and "accounts.change_user" in facts["privileged_permissions"]
    assert facts["sign_in"] == "password" and facts["live_tokens"] == 0
    assert review.status == "open" and review.opened_by_label == "attester"


def test_scope_all_covers_every_active_account(attester, alice, period):
    inactive = User.objects.create_user("gone", password="p", is_active=False)
    review = reviews.open_review(period_start=period[0], period_end=period[1], scope="all", actor=attester)
    names = set(review.items.values_list("user_label", flat=True))
    assert "alice" in names and inactive.get_username() not in names


def test_facts_carry_grants_in_period_and_directory_sightings(attester, alice, readers, root, period):
    from apps.access import directory
    from apps.access.context import acting_as

    with acting_as(root, "test"):
        alice.groups.add(readers)
    AccessEvent.objects.filter(subject=alice).update(at="2026-08-15T12:00:00Z")
    directory.sign_in("entra", "oid-alice", [], email="alice@example.com")
    review = reviews.open_review(period_start=period[0], period_end=period[1], scope="all", actor=attester)
    facts = item_for(review, alice).facts
    assert facts["sign_in"] == "directory" and facts["directory"][0]["provider"] == "entra"
    assert [g["what"] for g in facts["grants_in_period"]] == ["Readers"]
    assert facts["grants_in_period"][0]["by"] == "root"


def test_opening_is_refused_when_it_should_be(attester, staffer, root, review, period):
    with pytest.raises(reviews.ReviewRefused, match="still open"):
        reviews.open_review(period_start=period[0], period_end=period[1], scope="privileged", actor=attester)
    with pytest.raises(reviews.ReviewRefused, match="ends before"):
        reviews.open_review(period_start=period[1], period_end=period[0], scope="all", actor=attester)
    with pytest.raises(reviews.ReviewRefused, match="scope must be"):
        reviews.open_review(period_start=period[0], period_end=period[1], scope="some", actor=attester)
    with pytest.raises(reviews.ReviewRefused, match="Access attester"):
        reviews.open_review(period_start=period[0], period_end=period[1], scope="all", actor=staffer)
    # A superuser may open (not sign); a local command (no actor) may open.
    assert reviews.open_review(period_start=period[0], period_end=period[1], scope="all", actor=root).pk
    AccessReview.objects.filter(scope="all").delete()
    assert reviews.open_review(period_start=period[0], period_end=period[1], scope="all", actor=None).pk


# --- Deciding ---------------------------------------------------------------------


def test_decisions_are_recorded_and_own_row_can_only_be_flagged(review, attester, manager):
    item = reviews.decide(item_for(review, manager), "confirmed", actor=attester, note="still on the help desk")
    assert item.decision == "confirmed" and item.decided_by_label == "attester" and item.note
    mine = item_for(review, attester)
    with pytest.raises(reviews.ReviewRefused, match="your own access"):
        reviews.decide(mine, "confirmed", actor=attester)
    assert reviews.decide(mine, "flagged", actor=attester).decision == "flagged"
    with pytest.raises(reviews.ReviewRefused, match="decision must be"):
        reviews.decide(mine, "pending", actor=attester)


def test_only_an_attester_decides(review, manager, root, staffer):
    item = item_for(review, manager)
    with pytest.raises(reviews.ReviewRefused, match="Access attester"):
        reviews.decide(item, "confirmed", actor=staffer)
    with pytest.raises(reviews.ReviewRefused, match="superuser can't attest"):
        reviews.decide(item, "confirmed", actor=root)
    assert not reviews.can_attest(root) and not reviews.can_attest(staffer)


def test_remove_files_an_approval_and_approving_deactivates(review, attester, manager, root):
    APIToken.create_token(user=manager, name="laptop")
    item = reviews.decide(item_for(review, manager), "remove", actor=attester, note="left in August")
    assert item.follow_up.startswith("approval:")
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    assert req.kind == "access.review_remove" and req.target == manager and req.status == "pending"
    assert req.context["review_id"] == review.pk and req.context["reason"] == "left in August"
    # The review changed nothing yet.
    manager.refresh_from_db()
    assert manager.is_active
    # Deciding again keeps the one approval.
    again = reviews.decide(item, "remove", actor=attester, note="confirmed with HR")
    assert again.follow_up == item.follow_up
    approvals.approve(req, actor=root)
    manager.refresh_from_db()
    assert not manager.is_active and not manager.api_tokens.filter(is_active=True).exists()
    event = AccessEvent.objects.get(kind="deactivated", subject=manager)
    assert event.actor == root and event.source == f"approval:{req.pk}"


def test_removal_approval_is_refused_when_pointless(review, attester, manager, root):
    item = reviews.decide(item_for(review, manager), "remove", actor=attester)
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    manager.is_active = False
    manager.save()
    with pytest.raises(approvals.ApprovalRefused, match="already deactivated"):
        approvals.approve(req, actor=root)
    req.refresh_from_db()
    assert req.status == "pending"


def test_confirm_all_skips_the_attesters_own_row(review, attester):
    done = reviews.confirm_all(review, actor=attester)
    assert done["skipped"] == 1 and done["confirmed"] == review.items.count() - 1
    assert item_for(review, attester).decision == "pending"


# --- Signing ------------------------------------------------------------------------


def test_signing_needs_every_row_decided_and_the_right_name(review, attester, attester2, root):
    assert "pending" in reviews.sign_refusal(review, attester, "attester")
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    assert "Type your username" in reviews.sign_refusal(review, attester, "someone else")
    assert "superuser" in reviews.sign_refusal(review, root, "root")
    assert reviews.sign_refusal(review, attester, "ann attester") == ""  # full name, case-insensitive
    signed = reviews.sign(review, actor=attester, typed_name="Attester", note="Q3 evidence", signed_from="10.0.0.5")
    assert signed.is_signed and signed.signed_by_label == "attester" and signed.signed_name == "Attester"
    assert signed.signed_from == "10.0.0.5" and signed.note == "Q3 evidence"
    assert signed.summary["items"] == signed.summary["confirmed"] == review.items.count()
    assert signed.summary["previous"] is None
    event = AccessEvent.objects.get(kind="review_signed")
    assert event.actor == attester and event.detail["review_id"] == review.pk and event.detail["scope"] == "privileged"
    assert not event.is_grant


def test_a_signed_review_is_immutable(review, attester, attester2):
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    reviews.sign(review, actor=attester, typed_name="attester")
    review.note = "edited"
    with pytest.raises(ReviewLocked):
        review.save()
    with pytest.raises(ReviewLocked):
        review.delete()
    item = review.items.first()
    with pytest.raises(ReviewLocked):
        item.save()
    with pytest.raises(ReviewLocked):
        item.delete()
    with pytest.raises(reviews.ReviewRefused, match="signed"):
        reviews.decide(item, "flagged", actor=attester)
    with pytest.raises(reviews.ReviewRefused, match="already signed"):
        reviews.sign(review, actor=attester, typed_name="attester")
    assert AccessReview.objects.filter(pk=review.pk).exists()


def test_the_next_review_shows_the_delta(review, attester, attester2, manager, period):
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    reviews.sign(review, actor=attester, typed_name="attester")
    manager.is_active = False
    manager.save()
    newcomer = User.objects.create_user("newadmin", password="p", is_staff=True)
    later = reviews.open_review(
        period_start=date(2026, 10, 1), period_end=date(2026, 12, 31), scope="privileged", actor=attester
    )
    d = reviews.delta(later)
    # attester2 was created after the first review opened, so it's new too.
    assert d["new"] == ["attester2", "newadmin"] and d["gone"] == ["manager"] and d["previous"] == review.pk
    assert newcomer.get_username() in set(later.items.values_list("user_label", flat=True))


# --- Findings --------------------------------------------------------------------------


def test_review_overdue_tracks_the_last_two_quarters(attester, attester2, monkeypatch):
    recent = reviews.recent_quarters
    fixed = date(2026, 11, 22)
    monkeypatch.setattr(reviews, "recent_quarters", lambda n=4, today=None: recent(n, fixed))
    f = finding("review_overdue")
    assert f.severity == "info" and f.count == 2, "never reviewed: say so, don't paint a new project red"
    q3 = reviews.quarter_period(2026, 3)
    review = reviews.open_review(period_start=q3.start, period_end=q3.end, scope="privileged", actor=attester)
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    assert finding("review_overdue").severity == "info", "open isn't signed"
    reviews.sign(review, actor=attester, typed_name="attester")
    f = finding("review_overdue")
    assert f.severity == "warning" and [r["label"] for r in f.rows] == ["Q2 2026"]
    # Backdating a signed review is history rewriting: the base manager, not the locked one (T3-1).
    AccessReview._base_manager.filter(pk=review.pk).update(period_start=date(2025, 1, 1), period_end=date(2025, 3, 31))
    assert finding("review_overdue").severity == "danger", "reviewed once, then two quarters missed"


def test_unresolved_and_since_review_findings(review, attester, attester2, manager, root):
    reviews.decide(item_for(review, manager), "remove", actor=attester)
    reviews.decide(item_for(review, root), "flagged", actor=attester, note="who is this?")
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    assert finding("review_unresolved").severity == "ok", "only signed reviews count"
    reviews.sign(review, actor=attester, typed_name="attester")
    f = finding("review_unresolved")
    assert f.severity == "warning" and {r["label"] for r in f.rows} == {"manager", "root"}
    req = ApprovalRequest.objects.get(kind="access.review_remove")
    approvals.reject(req, actor=root)
    # A rejected removal of a still-active account stays unresolved (T3-3) ...
    rows = {r["label"]: r["meta"] for r in finding("review_unresolved").rows}
    assert set(rows) == {"manager", "root"} and "(rejected)" in rows["manager"]
    # ... until the account is deactivated by hand.
    manager.is_active = False
    manager.save()
    assert {r["label"] for r in finding("review_unresolved").rows} == {"root"}
    # attester2 was created after the review opened, so it wasn't on the roster.
    assert [r["label"] for r in finding("privileged_since_review").rows] == ["attester2"]
    User.objects.create_user("newadmin", password="p", is_staff=True)
    f = finding("privileged_since_review")
    assert f.severity == "info" and [r["label"] for r in f.rows] == ["attester2", "newadmin"]


def test_quarter_arithmetic():
    qs = reviews.recent_quarters(4, today=date(2026, 1, 15))
    assert [q.label for q in qs] == ["Q4 2025", "Q3 2025", "Q2 2025", "Q1 2025"]
    assert (qs[0].start, qs[0].end) == (date(2025, 10, 1), date(2025, 12, 31))
    assert reviews.quarter_period(2026, 1).end == date(2026, 3, 31)
    assert reviews.quarter_period(2024, 1).end == date(2024, 3, 31)


# --- Pages ---------------------------------------------------------------------------------


def test_the_pages_open_decide_and_sign(client, attester, attester2, manager, root):
    client.force_login(attester)
    page = client.get(reverse("access:reviews")).content.decode()
    assert "Start a review" in page and "not reviewed" in page
    q = reviews.recent_quarters(1)[0]
    resp = client.post(reverse("access:review_open"), {"period": q.key, "scope": "privileged", "note": "Q evidence"})
    review = AccessReview.objects.get()
    assert resp.status_code == 302 and resp["Location"].endswith(f"/reviews/{review.pk}/")
    assert (review.period_start, review.period_end, review.note) == (q.start, q.end, "Q evidence")
    detail = client.get(reverse("access:review_detail", kwargs={"pk": review.pk})).content.decode()
    assert "Sign this review" in detail and 'name="signed_name"' in detail and "disabled" in detail
    assert 'value="confirmed"' in detail
    item = item_for(review, manager)
    client.post(reverse("access:review_decide", kwargs={"pk": review.pk}), {"item": item.pk, "decision": "confirmed"})
    item.refresh_from_db()
    assert item.decision == "confirmed" and item.decided_by == attester
    client.post(reverse("access:review_decide", kwargs={"pk": review.pk}), {"action": "confirm_all"})
    assert review.items.filter(decision="pending").count() == 1  # the attester's own row
    # Signing with a row pending is refused with a message, not applied.
    client.post(reverse("access:review_sign", kwargs={"pk": review.pk}), {"signed_name": "attester"})
    review.refresh_from_db()
    assert not review.is_signed
    client.force_login(attester2)
    client.post(
        reverse("access:review_decide", kwargs={"pk": review.pk}),
        {"item": item_for(review, attester).pk, "decision": "confirmed"},
    )
    client.force_login(attester)
    client.post(reverse("access:review_sign", kwargs={"pk": review.pk}), {"signed_name": "Ann Attester"})
    review.refresh_from_db()
    assert review.is_signed and review.signed_name == "Ann Attester"
    signed = client.get(reverse("access:review_detail", kwargs={"pk": review.pk})).content.decode()
    assert "read-only evidence" in signed and 'name="signed_name"' not in signed and 'value="confirmed"' not in signed
    # Exports.
    csv_text = client.get(reverse("access:review_csv", kwargs={"pk": review.pk})).getvalue().decode()
    assert csv_text.startswith("review,period_start") and "manager" in csv_text and "attester" in csv_text
    data = client.get(reverse("access:review_json", kwargs={"pk": review.pk})).json()
    assert data["status"] == "signed" and len(data["items"]) == review.items.count()
    printed = client.get(reverse("access:review_print", kwargs={"pk": review.pk})).content.decode()
    assert "SOC 2" in printed and "Ann Attester" in printed


def test_a_reader_sees_the_pages_without_the_forms(client, staffer, review):
    client.force_login(staffer)
    page = client.get(reverse("access:reviews")).content.decode()
    assert "Access attester" in page and 'action="' + reverse("access:review_open") + '"' not in page
    detail = client.get(reverse("access:review_detail", kwargs={"pk": review.pk})).content.decode()
    assert 'name="signed_name"' not in detail and 'value="confirmed"' not in detail
    resp = client.post(reverse("access:review_open"), {"period": "2026-01-01_2026-03-31", "scope": "all"})
    assert resp.status_code == 302 and AccessReview.objects.count() == 1


def test_a_bad_period_is_a_message_not_a_500(client, attester):
    client.force_login(attester)
    resp = client.post(reverse("access:review_open"), {"period": "custom", "start": "nope", "end": ""}, follow=True)
    assert resp.status_code == 200 and "two dates" in resp.content.decode()
    assert not AccessReview.objects.exists()


# --- CLI and REST -------------------------------------------------------------------------


def run(*args):
    out = StringIO()
    call_command("access", *args, stdout=out)
    return out.getvalue()


def test_the_cli_opens_lists_and_shows(attester, manager):
    out = run("review", "open", "--from", "2026-07-01", "--to", "2026-09-30", "--user", "attester")
    assert "opened (privileged" in out
    review = AccessReview.objects.get()
    assert review.opened_by == attester
    assert "open" in run("review", "list") and str(review.pk) in run("review", "list")
    data = json.loads(run("review", "show", str(review.pk), "--json"))
    assert data["id"] == review.pk and any(i["username"] == "manager" for i in data["items"])
    assert run("review", "show", str(review.pk), "--csv").startswith("review,period_start")
    assert "manager" in run("review", "show", str(review.pk))
    with pytest.raises(CommandError, match="still open"):
        run("review", "open", "--from", "2026-07-01", "--to", "2026-09-30")
    with pytest.raises(CommandError, match="No review #999"):
        run("review", "show", "999")
    with pytest.raises(CommandError, match="YYYY-MM-DD"):
        run("review", "open", "--from", "July", "--to", "2026-09-30")


def test_rest_reads_reviews(client, staffer, alice, review):
    from .test_api import bearer

    assert client.get(BASE + "reviews/", **bearer(alice, "")).status_code == 403
    data = client.get(BASE + "reviews/?status=open", **bearer(staffer, "")).json()
    assert [r["id"] for r in data["results"]] == [review.pk] and "items" not in data["results"][0]
    one = client.get(BASE + f"reviews/{review.pk}/", **bearer(staffer, "")).json()
    assert one["summary"]["pending"] == review.items.count() and len(one["items"]) == review.items.count()
    assert client.get(BASE + "reviews/999/", **bearer(staffer, "")).status_code == 404


def test_the_shipped_groups_carry_the_review_permissions():
    attester = Group.objects.get(name="Access attester")
    assert Permission.objects.get(codename="sign_accessreview") in attester.permissions.all()
    reviewer = Group.objects.get(name="Access reviewer")
    assert Permission.objects.get(codename="view_accessreview") in reviewer.permissions.all()
    assert Permission.objects.get(codename="sign_accessreview") not in reviewer.permissions.all()



# --- Round-2 fixes (Test Lab evaluation 45) ----------------------------------------


@pytest.fixture
def reader(db):
    """An Access reviewer: staff, reads access, decides nothing."""
    user = User.objects.create_user("reader", password="p", is_staff=True)
    user.groups.add(Group.objects.get(name="Access reviewer"))
    return User.objects.get(pk=user.pk)


def test_the_account_under_review_cannot_cancel_its_own_removal(review, attester, manager, reader, root):
    """T3-2: only the requester or someone who could decide withdraws a
    removal; never the account it removes, nor staff who couldn't decide."""
    from apps.approvals.permissions import can_cancel

    item = reviews.decide(item_for(review, manager), "remove", actor=attester)
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    # manager holds change_user (could decide others' removals) but is the target.
    assert not can_cancel(manager, req)
    with pytest.raises(approvals.NotEligible, match="requester or someone who could decide"):
        approvals.cancel(req, actor=manager)
    assert not can_cancel(reader, req)
    with pytest.raises(approvals.NotEligible):
        approvals.cancel(req, actor=reader)
    req.refresh_from_db()
    assert req.status == "pending"
    assert can_cancel(attester, req) and can_cancel(root, req)
    approvals.cancel(req, actor=attester)
    req.refresh_from_db()
    assert req.status == "canceled"


def test_a_kind_without_the_hook_keeps_the_default_cancel_rule(attester, reader, root):
    """The hook narrows only kinds that set it: any staff still cancels others."""
    req = approvals.request_approval(kind="tests.plain", title="plain", actor=root)
    assert approvals.cancel(req, actor=reader).status == "canceled"


def test_a_dead_removal_is_refiled_when_remove_is_decided_again(review, attester, manager, root):
    """T3-3: a canceled, rejected or expired removal doesn't swallow the
    decision; deciding *remove* again files a new approval."""
    item = reviews.decide(item_for(review, manager), "remove", actor=attester)
    first = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    approvals.cancel(first, actor=attester)
    item = reviews.decide(item, "remove", actor=attester, note="still needs to go")
    second = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    assert second.pk != first.pk and second.status == "pending"
    approvals.reject(second, actor=root)
    third = reviews.decide(item, "remove", actor=attester).follow_up
    assert third not in (f"approval:{first.pk}", f"approval:{second.pk}")
    # A live approval is kept: deciding again doesn't file a fourth.
    assert reviews.decide(item, "remove", actor=attester).follow_up == third


def test_the_review_keeps_the_request_id_of_its_opening_and_signing(client, attester, attester2):
    """T3-4: the views read the id RequestIDMiddleware sets (request.id)."""
    client.force_login(attester)
    q = reviews.recent_quarters(1)[0]
    form = {"period": q.key, "scope": "privileged"}
    client.post(reverse("access:review_open"), form, HTTP_X_REQUEST_ID="req_open_t34")
    review = AccessReview.objects.get()
    assert review.request_id == "req_open_t34"
    reviews.confirm_all(review, actor=attester)
    reviews.decide(item_for(review, attester), "confirmed", actor=attester2)
    sign_url = reverse("access:review_sign", kwargs={"pk": review.pk})
    client.post(sign_url, {"signed_name": "attester"}, HTTP_X_REQUEST_ID="req_sign_t34")
    review.refresh_from_db()
    # The opening's id is kept; the signing's has its own field (G2-6).
    assert review.is_signed and review.signed_request_id == "req_sign_t34" and review.request_id == "req_open_t34"
    payload = reviews.review_payload(review)
    assert payload["signed_request_id"] == "req_sign_t34" and payload["request_id"] == "req_open_t34"


def test_the_target_cannot_reject_its_own_removal_either(review, attester, manager, root):
    """G2-1: an account holding change_user can decide others' removals, but
    not its own: rejecting it would make the removal go away as canceling
    would (T3-2)."""
    from apps.approvals.permissions import can_decide

    item = reviews.decide(item_for(review, manager), "remove", actor=attester)
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    assert manager.has_perm("accounts.change_user") and not can_decide(manager, req)
    with pytest.raises(approvals.NotEligible):
        approvals.reject(req, actor=manager)
    req.refresh_from_db()
    assert req.status == "pending"
    assert can_decide(root, req)


def test_changing_remove_to_confirmed_withdraws_the_removal(review, attester, attester2, manager, root):
    """G2-2: the pending approval goes when the row stops saying remove, and an
    approval that outlived its decision can't deactivate anyone."""
    item = reviews.decide(item_for(review, manager), "remove", actor=attester)
    req = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    item = reviews.decide(item, "confirmed", actor=attester)
    req.refresh_from_db()
    assert req.status == "canceled" and item.follow_up == ""
    # Filed by one attester, changed by another who couldn't cancel it: the
    # approve-time check still refuses.
    item = reviews.decide(item, "remove", actor=attester)
    second = ApprovalRequest.objects.get(pk=int(item.follow_up[9:]))
    second.requested_by.is_active = False
    second.requested_by.save()
    reviews.decide(item, "confirmed", actor=attester2)
    second.refresh_from_db()
    assert second.status == "pending"
    with pytest.raises(approvals.ApprovalRefused, match="now records confirmed"):
        approvals.approve(second, actor=root)
    manager.refresh_from_db()
    assert manager.is_active
