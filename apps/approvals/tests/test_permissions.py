"""Visibility and cancel gates — the pure-function layer shared by every surface.

``can_decide`` is exercised end-to-end in test_services (through decide());
this file covers the view/cancel gates and the queryset scoper, whose
existence-hiding contract REST relies on (a 404, never a 403).
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.approvals import permissions, services
from apps.approvals.models import ApprovalRequest

pytestmark = pytest.mark.django_db


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


def test_can_view_matrix(requester, staff, assignee, bystander, sample_kind):
    req = _file(requester, assignees=[assignee])
    assert permissions.can_view(staff, req)  # staff see everything
    assert permissions.can_view(requester, req)  # your own request
    assert permissions.can_view(assignee, req)  # named on it
    assert not permissions.can_view(bystander, req)
    assert not permissions.can_view(AnonymousUser(), req)
    assert not permissions.can_view(None, req)


def test_viewable_requests_scopes_and_hides(requester, staff, assignee, bystander, sample_kind):
    mine = _file(requester)
    assigned = _file(staff, assignees=[assignee, requester])
    _file(staff)  # visible to staff only

    assert permissions.viewable_requests(staff).count() == 3
    assert set(permissions.viewable_requests(requester)) == {mine, assigned}
    assert set(permissions.viewable_requests(assignee)) == {assigned}
    assert permissions.viewable_requests(bystander).count() == 0
    assert permissions.viewable_requests(AnonymousUser()).count() == 0


def test_viewable_requests_distinct_when_requester_is_also_assignee(requester, staff, sample_kind):
    # requester + assignee on the SAME row must not duplicate under the OR join
    req = _file(requester, assignees=[requester])
    rows = list(permissions.viewable_requests(requester))
    assert rows.count(req) == 1


def test_can_cancel_gates(requester, staff, bystander, sample_kind):
    req = _file(requester)
    assert permissions.can_cancel(requester, req)
    assert permissions.can_cancel(staff, req)
    assert not permissions.can_cancel(bystander, req)
    assert not permissions.can_cancel(AnonymousUser(), req)
    # terminal rows can't be canceled by anyone
    services.cancel(req, actor=requester)
    assert not permissions.can_cancel(requester, req)
    assert not permissions.can_cancel(staff, req)


def test_can_decide_requires_pending(requester, staff, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff)
    assert not permissions.can_decide(staff, req)
    assert req.status == ApprovalRequest.Status.APPROVED


# --- F-10: a deactivated account has no approval authority anywhere ----------


def test_deactivated_user_cannot_view_decide_or_cancel(
    requester, staff, assignee, sample_kind
):
    """Offboarding must remove approval authority, not just web login.

    Approvals is the compliance control: a decision recorded under an offboarded
    person's name reads as legitimate. Belt AND braces — the token authenticator
    refuses the credential (apps/smallstack/models.py) and eligibility refuses
    the identity here, so neither layer is load-bearing alone.
    """
    req = _file(requester, assignees=[assignee])

    # Negative control: while active, all three answers are the expected ones.
    assert permissions.can_view(staff, req)
    assert permissions.can_decide(staff, req)
    assert permissions.can_decide(assignee, req)
    assert permissions.can_cancel(requester, req)
    assert permissions.viewable_requests(staff).count() == 1

    for user in (staff, assignee, requester):
        user.is_active = False
        user.save()

    assert not permissions.can_view(staff, req)
    assert not permissions.can_decide(staff, req)
    assert not permissions.can_decide(assignee, req)
    assert not permissions.can_cancel(requester, req)
    assert permissions.viewable_requests(staff).count() == 0
    assert permissions.viewable_requests(assignee).count() == 0
    # is_staff alone is not enough — the account must also exist.
    assert not permissions.is_staff(staff)


def test_services_refuse_a_deactivated_actor(requester, staff, sample_kind):
    req = _file(requester)
    staff.is_active = False
    staff.save()
    with pytest.raises(services.NotEligible):
        services.decide(req, actor=staff, approved=True)
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.PENDING
