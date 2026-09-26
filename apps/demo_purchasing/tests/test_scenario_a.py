"""Scenario A — the app-owned half of the purchasing gate.

The framework's own behaviour is covered by apps/approvals/tests; these tests
pin the parts THIS app owns: tiered routing at filing time, and a callback that
arms a PO on approval and on nothing else.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.approvals import permissions as approval_perms
from apps.approvals import services as approvals
from apps.demo_purchasing import services as purchasing
from apps.demo_purchasing.models import FINANCE_GROUP, PurchaseRequest

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def buyer():
    return User.objects.create_user("a-buyer", password="p")


@pytest.fixture
def approver():
    return User.objects.create_user("a-staff", password="p", is_staff=True)


@pytest.fixture
def finance():
    """A NON-staff finance approver — the tier-2 routing target."""
    user = User.objects.create_user("a-finance", password="p")
    group, _ = Group.objects.get_or_create(name=FINANCE_GROUP)
    user.groups.add(group)
    return user


def make(amount: str, requester, **kwargs):
    return PurchaseRequest.objects.create(
        vendor=kwargs.pop("vendor", "Vendor"),
        description=kwargs.pop("description", "Thing"),
        amount=Decimal(amount),
        requested_by=requester,
        **kwargs,
    )


def test_submit_files_a_pending_approval_and_links_both_ways(buyer):
    pr = make("100.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    pr.refresh_from_db()
    assert (req.status, pr.state) == ("pending", PurchaseRequest.State.PENDING)
    assert pr.approval_id == req.pk
    assert req.target == pr
    # The kind's default TTL, not a hand-rolled one.
    assert req.expires_at is not None
    assert timedelta(days=1, hours=23) < req.expires_at - timezone.now() <= timedelta(days=2)


def test_submitting_twice_is_refused(buyer):
    pr = make("100.00", buyer)
    purchasing.submit_for_approval(pr, actor=buyer)
    with pytest.raises(purchasing.AlreadySubmitted):
        purchasing.submit_for_approval(pr, actor=buyer)


def test_low_value_routes_to_any_staff(buyer, approver):
    pr = make("4999.99", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    assert list(req.assignees.all()) == []
    assert approval_perms.can_decide(approver, req)


def test_high_value_routes_to_the_non_staff_finance_group(buyer, finance):
    pr = make("5000.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    assert list(req.assignees.all()) == [finance]
    assert finance.is_staff is False
    assert approval_perms.can_decide(finance, req)


def test_high_value_without_a_finance_group_falls_back_rather_than_wedging(buyer):
    Group.objects.filter(name=FINANCE_GROUP).delete()
    pr = make("9000.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    assert list(req.assignees.all()) == []  # any staff, with a logged warning


def test_approval_mints_a_deterministic_po(buyer, approver):
    pr = make("100.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    approvals.approve(req, actor=approver, note="ok")
    pr.refresh_from_db()
    assert pr.state == PurchaseRequest.State.APPROVED
    assert pr.po_number == f"PO-{pr.pk:05d}"
    assert pr.decided_note == "ok"


@pytest.mark.parametrize(
    "transition,expected",
    [
        ("reject", PurchaseRequest.State.REJECTED),
        ("cancel", PurchaseRequest.State.CANCELED),
    ],
)
def test_non_approval_outcomes_mint_no_po(buyer, approver, transition, expected):
    pr = make("100.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    if transition == "reject":
        approvals.reject(req, actor=approver)
    else:
        approvals.cancel(req, actor=buyer)
    pr.refresh_from_db()
    assert (pr.state, pr.po_number) == (expected, "")


def test_expiry_mints_no_po(buyer):
    pr = make("100.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    req.expires_at = timezone.now() - timedelta(minutes=1)
    req.save(update_fields=["expires_at"])
    assert approvals.mark_expired() == 1
    pr.refresh_from_db()
    assert (pr.state, pr.po_number) == (PurchaseRequest.State.EXPIRED, "")


def test_a_deleted_target_does_not_break_the_callback(buyer, approver):
    """Rows outlive their targets — the callback must be a no-op, not a 500."""
    pr = make("100.00", buyer)
    req = purchasing.submit_for_approval(pr, actor=buyer)
    pr.delete()
    approvals.approve(req, actor=approver)
    req.refresh_from_db()
    assert req.status == "approved"
    assert req.callback_error == ""


def test_review_page_is_open_to_the_non_staff_assignee(client, buyer, finance):
    pr = make("7000.00", buyer)
    purchasing.submit_for_approval(pr, actor=buyer)
    client.force_login(finance)
    resp = client.get(f"/demo/purchasing/requests/{pr.pk}/review/")
    assert resp.status_code == 200
    assert b'name="decision"' in resp.content  # the embed offers the buttons


def test_review_page_is_closed_to_a_bystander(client, buyer):
    pr = make("7000.00", buyer)
    purchasing.submit_for_approval(pr, actor=buyer)
    client.force_login(User.objects.create_user("a-bystander", password="p"))
    assert client.get(f"/demo/purchasing/requests/{pr.pk}/review/").status_code == 403
