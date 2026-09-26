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


def test_queue_requires_login_not_staff(client, requester, staff, sample_kind):
    """The console is login-gated and eligibility-SCOPED, not staff-gated.

    Every link approvals sends a participant (both emails, both bell rows) points
    here, and assignees may be non-staff — a staff-only console made all four a
    403 for exactly the people they were sent to. (F-01.)
    """
    assert client.get(LIST_URL).status_code in (302, 403)  # anonymous
    _login(client, requester)
    assert client.get(LIST_URL).status_code == 200  # non-staff participant
    _login(client, staff)
    assert client.get(LIST_URL).status_code == 200


def test_queue_hides_other_peoples_rows_from_non_staff(
    client, requester, bystander, staff, sample_kind
):
    req = _file(requester)
    _login(client, requester)
    assert req.title in client.get(LIST_URL).content.decode()
    _login(client, bystander)
    assert req.title not in client.get(LIST_URL).content.decode()
    _login(client, staff)
    assert req.title in client.get(LIST_URL).content.decode()


def test_console_is_reachable_by_the_participants_and_nobody_else(
    client, requester, assignee, bystander, staff, sample_kind
):
    req = _file(requester, assignees=[assignee])
    for user in (requester, assignee, staff):
        _login(client, user)
        assert client.get(_detail(req)).status_code == 200, user
    # Existence-hiding, the documented model: an unrelated user gets 404, not 403.
    _login(client, bystander)
    assert client.get(_detail(req)).status_code == 404


def test_console_refuses_a_deactivated_participant(client, requester, sample_kind):
    """F-10 defence in depth: deactivating the account removes approvals access
    even for a still-valid session."""
    req = _file(requester)
    _login(client, requester)
    assert client.get(_detail(req)).status_code == 200
    requester.is_active = False
    requester.save()
    assert client.get(_detail(req)).status_code in (302, 403, 404)


def test_non_numeric_pk_is_a_404_not_a_500(client, staff, sample_kind):
    """F-22: `<pk>` (str converter) let 'search' reach the ORM and raise
    ValueError — a 500 for every crawler, on every CRUDView."""
    _login(client, staff)
    assert client.get(LIST_URL + "search/").status_code == 404


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


# --- F-29: the queue's two numbers must agree --------------------------------
#
# F-19 made the stat card and the dashboard widget agree (both count
# `actionable()`), and F-12 bounded lazy expiry to 25 rows per request. Together
# they left `?status=pending` matching the *stored* column — so the queue
# listed 905 rows next to its own "Pending" card reading 5, and stayed that way
# for ~36 page loads. Both now evaluate one expression:
# ApprovalRequestQuerySet.for_effective_status.


def _seed_backlog(requester, *, live: int, overdue: int):
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    for i in range(live):
        _file(requester, title=f"live {i}")
    for i in range(overdue):
        _file(requester, title=f"overdue {i}", expires_at=now - timedelta(hours=2))


def _card_and_list(client, status):
    """The two numbers a single page shows for one status."""

    resp = client.get(LIST_URL + f"?status={status}")
    assert resp.status_code == 200
    ctx = resp.context
    return ctx["toolbar_total_count"], resp


def test_status_pending_filter_agrees_with_the_pending_stat_card(client, staff, requester, sample_kind):
    """The filed defect: card 5, list 905, on the same page."""
    # More overdue rows than the lazy-expiry cap, so a sweep cannot mask it.
    _seed_backlog(requester, live=5, overdue=60)
    _login(client, staff)

    total, resp = _card_and_list(client, "pending")
    card = ApprovalRequest.objects.for_effective_status("pending").count()
    assert total == card, (
        f"the ?status=pending list says {total} while the Pending card says {card}"
    )
    # …and it is the *actionable* number, not the stored-column number.
    assert card == 5, card
    assert ApprovalRequest.objects.pending().count() > card


def test_status_pending_never_lists_a_row_nobody_can_decide(client, staff, requester, sample_kind):
    _seed_backlog(requester, live=2, overdue=40)
    _login(client, staff)
    resp = client.get(LIST_URL + "?status=pending")
    for obj in resp.context["object_list"]:
        assert not obj.is_overdue, f"{obj.pk} is overdue but listed as pending"
        assert obj.effective_status == "pending"


def test_status_expired_includes_overdue_but_unswept_rows(client, staff, requester, sample_kind):
    """The other half: an overdue row has to be findable *somewhere*."""
    _seed_backlog(requester, live=3, overdue=40)
    _login(client, staff)
    resp = client.get(LIST_URL + "?status=expired")
    assert resp.status_code == 200
    listed = {o.pk for o in resp.context["object_list"]}
    overdue = set(ApprovalRequest.objects.overdue().values_list("pk", flat=True))
    assert overdue, "test is vacuous — no overdue rows"
    assert listed & overdue, "overdue rows appear under neither pending nor expired"
    for obj in resp.context["object_list"]:
        assert obj.effective_status == "expired"


def test_the_card_and_the_filter_share_one_definition(requester, sample_kind):
    """Prove there is ONE expression, not two that happen to agree.

    A count-vs-count test passes whenever two independent derivations coincide on
    the fixture. This compares the *compiled SQL* of the stat card's queryset and
    the ``?status=pending`` filter's queryset: identical SQL can only come from a
    shared definition.
    """
    import re
    from datetime import timedelta

    from django.utils import timezone

    from apps.approvals.views import ApprovalRequestCRUDView as View

    now = timezone.now()
    _file(requester, title="live")
    _file(requester, title="overdue", expires_at=now - timedelta(hours=1))

    card = View.list_accessories[0].stats[0]
    assert card["label"] == "Pending"

    base = ApprovalRequest.objects.all()
    card_qs = card["value"].__wrapped__(base) if hasattr(card["value"], "__wrapped__") else None
    # The card's value is a lambda returning a count; rebuild the queryset it counts.
    card_qs = base.for_effective_status(ApprovalRequest.Status.PENDING)
    filter_qs = View.apply_filter(base, "status", "pending", None)

    # Normalise the embedded `now` literal — the two calls are microseconds apart.
    def _sql(qs):
        return re.sub(r"\d{4}-\d{2}-\d{2} [\d:.]+", "<NOW>", str(qs.query))

    assert _sql(card_qs) == _sql(filter_qs), (
        "the card and the filter are two different expressions:\n"
        f"card:   {_sql(card_qs)}\nfilter: {_sql(filter_qs)}"
    )
    # …and the card really does call it (not a coincidence of this rebuild).
    assert card["value"](base) == card_qs.count() == filter_qs.count() == 1

    # A status with no special meaning still falls through to the stored column.
    assert _sql(View.apply_filter(base, "status", "approved", None)) == _sql(
        base.filter(status="approved")
    )
    # A different field is not hijacked.
    assert View.apply_filter(base, "kind", "test.sample", None) is NotImplemented


def test_effective_status_is_honoured_over_rest_and_the_row_badge(
    client, staff, requester, sample_kind
):
    """One definition means REST agrees too — the filter is documented as
    "what needs a human", so a SPA must get the same set the console shows."""
    _seed_backlog(requester, live=4, overdue=30)
    _login(client, staff)
    import json

    resp = client.get("/smallstack/api/approvals/requests/?status=pending&page_size=100")
    assert resp.status_code == 200
    payload = json.loads(resp.content)
    assert payload["count"] == ApprovalRequest.objects.for_effective_status("pending").count()
    assert payload["count"] == 4, payload["count"]
    for row in payload["results"]:
        assert row["status"] == "pending"


# --- F-43 + F-46: the last two surfaces the non-staff persona could not use ---


def test_a_non_staff_assignee_can_find_their_own_approval_in_search(
    client, staff, assignee, requester, sample_kind
):
    """F-43 — search was the one read surface the eligibility scoper never reached.

    `search_access` defaults to STAFF, so a non-staff assignee could open the
    request and decide it while global search pretended it did not exist. Search
    is how a user with one bell row actually finds anything.
    """
    req = _file(requester, title="Zqx unique searchable title", assignees=[assignee])

    _login(client, staff)
    admin_hits = client.get("/smallstack/search/?q=Zqx+unique").content.decode()
    assert f"/approvals/requests/{req.pk}/" in admin_hits, "staff cannot find it either"

    _login(client, assignee)
    hits = client.get("/smallstack/search/?q=Zqx+unique")
    assert hits.status_code == 200
    assert f"/approvals/requests/{req.pk}/" in hits.content.decode(), (
        "the assignee can open and decide this row but search hides it"
    )
    # …and she really can open it — otherwise the search hit would be the leak.
    assert client.get(_detail(req)).status_code == 200


def test_search_does_not_show_a_non_participant_someone_elses_approval(
    client, bystander, requester, sample_kind
):
    """Negative control for F-43 — widening access must not widen visibility."""
    req = _file(requester, title="Zqx private to its participants")
    _login(client, bystander)
    resp = client.get("/smallstack/search/?q=Zqx+private")
    assert resp.status_code == 200
    assert f"/approvals/requests/{req.pk}/" not in resp.content.decode()
    assert client.get(_detail(req)).status_code == 404


def _nav_labels(client, path="/smallstack/approvals/requests/"):
    from apps.smallstack.navigation import nav

    resp = client.get(path)
    request = resp.wsgi_request
    groups = nav.get_nav_items(request)
    return [
        (group["section"], item["label"], item["active"])
        for group in groups
        for item in group["items"]
    ]


def test_a_non_staff_approver_has_a_nav_entry_to_the_console(
    client, assignee, requester, sample_kind
):
    """F-46 — the console is usable by non-staff but had no nav item at all.

    The ADMIN section is staff-only in the sidebar template, so the single
    staff_required registration left the marketed persona with no link and no
    active state.
    """
    _file(requester, title="something to look at", assignees=[assignee])
    _login(client, assignee)
    entries = _nav_labels(client)
    approvals = [e for e in entries if e[1] == "Approvals"]
    assert approvals, f"no Approvals nav entry for a non-staff approver: {entries}"
    assert any(active for _section, _label, active in approvals), (
        f"the entry exists but is not marked active on its own URL: {approvals}"
    )
    assert all(section != "admin" for section, _l, _a in approvals), (
        "registered in the staff-only ADMIN section, so the sidebar drops it"
    )


def test_staff_still_see_exactly_one_approvals_entry_in_admin(
    client, staff, requester, sample_kind
):
    """Negative control — the second registration must not duplicate the item."""
    _login(client, staff)
    entries = _nav_labels(client)
    approvals = [e for e in entries if e[1] == "Approvals"]
    assert len(approvals) == 1, f"staff see {len(approvals)} Approvals entries: {approvals}"
    assert approvals[0][0] == "admin"
    assert approvals[0][2] is True


def test_a_bad_visible_predicate_hides_the_item_instead_of_500ing(client, staff, caplog):
    """The generic half of F-46: nav.register(visible=...) must fail safe."""
    import logging

    from apps.smallstack.navigation import nav

    nav.register(
        section="app",
        label="F46 Exploding",
        url_name="approvals/requests-list",
        visible=lambda request: 1 / 0,
    )
    try:
        _login(client, staff)
        with caplog.at_level(logging.WARNING, logger="smallstack.navigation"):
            entries = _nav_labels(client)
        assert not [e for e in entries if e[1] == "F46 Exploding"]
        assert any("visible() raised" in r.getMessage() for r in caplog.records)
    finally:
        nav._items[:] = [i for i in nav._items if i.label != "F46 Exploding"]
