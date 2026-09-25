"""The web surface — queue gating, the decision console, the POST actions,
the open-redirect guard, and the template-override chain.

The decide POST is deliberately NOT staff-gated (assignees may be non-staff);
these tests prove that's safe because eligibility lives in the service.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.approvals import services
from apps.approvals.models import ApprovalRequest

pytestmark = pytest.mark.django_db


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


def _login(client, user):
    client.force_login(user)
    return client


LIST_URL = reverse("approvals/requests-list")


def _detail(req):
    return reverse("approvals/requests-detail", kwargs={"pk": req.pk})


def _decide(req):
    return reverse("approvals_decide", kwargs={"pk": req.pk})


def _cancel(req):
    return reverse("approvals_cancel", kwargs={"pk": req.pk})


# --- gating -----------------------------------------------------------------


def test_queue_requires_staff(client, requester, staff, sample_kind):
    assert client.get(LIST_URL).status_code in (302, 403)  # anonymous
    _login(client, requester)
    assert client.get(LIST_URL).status_code in (302, 403)  # authenticated non-staff
    _login(client, staff)
    assert client.get(LIST_URL).status_code == 200


def test_console_requires_staff(client, requester, staff, sample_kind):
    req = _file(requester)
    _login(client, requester)
    assert client.get(_detail(req)).status_code in (302, 403)
    _login(client, staff)
    assert client.get(_detail(req)).status_code == 200


# --- the decision console ---------------------------------------------------


def test_console_shows_decision_panel_when_eligible(client, requester, staff, sample_kind):
    req = _file(requester)
    _login(client, staff)
    html = client.get(_detail(req)).content.decode()
    assert 'name="decision"' in html  # Approve/Reject buttons render
    assert req.title in html


def test_console_hides_panel_for_own_request(client, staff, sample_kind):
    req = _file(staff)  # self-approval blocked by default ⇒ no buttons
    _login(client, staff)
    html = client.get(_detail(req)).content.decode()
    assert 'name="decision"' not in html


def test_console_shows_outcome_after_decision(client, requester, staff, sample_kind):
    req = _file(requester)
    services.reject(req, actor=staff, note="nope")
    _login(client, staff)
    html = client.get(_detail(req)).content.decode()
    assert 'name="decision"' not in html  # panel gone
    assert "Rejected" in html
    assert "nope" in html


def test_console_surfaces_callback_error(client, requester, staff):
    from apps.approvals.registry import ApprovalKind, register_kind, unregister

    register_kind(ApprovalKind(key="test.viewboom", on_decision=lambda r: 1 / 0))
    try:
        req = _file(requester, kind="test.viewboom")
        services.approve(req, actor=staff)
        _login(client, staff)
        html = client.get(_detail(req)).content.decode()
        assert "ZeroDivisionError" in html
    finally:
        unregister("test.viewboom")


# --- decide / cancel POSTs --------------------------------------------------


def test_decide_post_approves(client, requester, staff, sample_kind):
    req = _file(requester)
    _login(client, staff)
    resp = client.post(_decide(req), {"decision": "approve", "note": "fine"})
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.APPROVED
    assert req.decided_by == staff
    assert req.decision_note == "fine"


def test_decide_post_by_non_staff_assignee(client, requester, assignee, sample_kind):
    """The reason the endpoint is not staff-gated: assignees may be non-staff."""
    req = _file(requester, assignees=[assignee])
    _login(client, assignee)
    resp = client.post(_decide(req), {"decision": "reject"})
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.REJECTED


def test_decide_post_rejected_for_ineligible(client, requester, bystander, sample_kind):
    req = _file(requester)
    assert client.post(_decide(req), {"decision": "approve"}).status_code == 403  # anonymous
    _login(client, bystander)
    assert client.post(_decide(req), {"decision": "approve"}).status_code == 403
    req.refresh_from_db()
    assert req.is_pending


def test_decide_post_open_redirect_guard(client, requester, staff, sample_kind):
    req = _file(requester)
    _login(client, staff)
    resp = client.post(
        _decide(req), {"decision": "approve", "next": "https://evil.example/phish"}
    )
    assert resp.status_code == 302
    assert resp["Location"] == _detail(req)  # external next ignored


def test_decide_post_honors_safe_next(client, requester, staff, sample_kind):
    req = _file(requester)
    _login(client, staff)
    resp = client.post(_decide(req), {"decision": "approve", "next": LIST_URL})
    assert resp["Location"] == LIST_URL


def test_cancel_post_by_requester(client, requester, sample_kind):
    req = _file(requester)
    _login(client, requester)
    resp = client.post(_cancel(req), {"note": "changed my mind"})
    assert resp.status_code == 302
    req.refresh_from_db()
    assert req.status == ApprovalRequest.Status.CANCELED


def test_cancel_post_rejected_for_bystander(client, requester, bystander, sample_kind):
    req = _file(requester)
    _login(client, bystander)
    assert client.post(_cancel(req)).status_code == 403


# --- template-override chain ------------------------------------------------


def test_console_template_can_be_overridden(client, requester, staff, sample_kind, settings, tmp_path):
    """A project-level ``templates/smallstack_approvals/crud/approvalrequest_detail.html``
    shadows the shipped console (the app_label namespace — the documented wrinkle)."""
    override = tmp_path / "smallstack_approvals" / "crud"
    override.mkdir(parents=True)
    (override / "approvalrequest_detail.html").write_text(
        "{% extends 'smallstack/base.html' %}{% block content %}OVERRIDE-MARKER-77{% endblock %}"
    )
    # Reassign the whole setting (not an in-place mutation) so pytest-django
    # restores it and Django's setting_changed handler rebuilds the engines.
    settings.TEMPLATES = [
        {**settings.TEMPLATES[0], "DIRS": [str(tmp_path), *settings.TEMPLATES[0]["DIRS"]]}
    ]

    req = _file(requester)
    _login(client, staff)
    html = client.get(_detail(req)).content.decode()
    assert "OVERRIDE-MARKER-77" in html
