"""The review cadence: the schedule opens a closed quarter's review, stores the
pack and tells the attesters; reminds and escalates while it stays open; a
signing retires the bells, stores the attested pack and emits the webhook.
Signing itself is never automated."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import date, timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.access import cadence, reviews
from apps.access.dashboard_widgets import AccessReviewWidget
from apps.access.models import AccessReview, EvidenceBundle
from apps.access.registry import run_checks
from apps.notifications.models import Notification
from apps.webhooks import services as webhooks
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/smallstack/api/access/"
#: Q3 2026 has closed; its review is due Oct 30 (period end + 30 days).
TODAY = date(2026, 10, 5)
LATE = date(2026, 11, 5)


@pytest.fixture(autouse=True)
def _cadence_on(settings, tmp_path):
    settings.SMALLSTACK_ACCESS_REVIEW_CADENCE = "quarterly"
    settings.SMALLSTACK_ACCESS_REVIEW_SCOPE = "privileged"
    settings.SMALLSTACK_ACCESS_REVIEW_DUE_DAYS = 30
    settings.SMALLSTACK_ACCESS_REVIEW_REMINDER_DAYS = 7
    settings.SMALLSTACK_ACCESS_REVIEW_ESCALATION_EMAILS = ["grc@example.com"]
    settings.SMALLSTACK_ACCESS_EVIDENCE_KEEP = 24
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def attester(db):
    user = User.objects.create_user(
        "attester", email="ann@example.com", password="p", is_staff=True, first_name="Ann", last_name="Attester"
    )
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def attester2(db):
    user = User.objects.create_user("attester2", email="bo@example.com", password="p", is_staff=True)
    user.groups.add(Group.objects.get(name="Access attester"))
    return User.objects.get(pk=user.pk)


def bells(user, kind=""):
    qs = Notification.objects.filter(recipient=user)
    return qs.filter(kind=kind) if kind else qs


def sign(review, attester, attester2):
    reviews.confirm_all(review, actor=attester)
    reviews.decide(review.items.get(user_label="attester"), "flagged", actor=attester2, note="peer")
    return reviews.sign(review, actor=attester, typed_name="Ann Attester")


# --- The tick ---------------------------------------------------------------------


def test_tick_opens_the_closed_quarter_stores_the_pack_and_tells_the_attesters(attester, attester2, manager, root):
    result = cadence.tick(today=TODAY)
    review = AccessReview.objects.get(pk=result["opened"])
    assert (review.period_start, review.period_end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert review.opened_via == "schedule" and review.opened_by is None and review.reminded_at is not None
    assert {"root", "manager", "attester", "attester2"} <= set(review.items.values_list("user_label", flat=True))
    # The quarter's pack, stored with its digest.
    bundle = EvidenceBundle.objects.get(pk=result["bundle"])
    assert bundle.reason == "period_closed" and bundle.review == review and bundle.built_by_label == "schedule"
    with bundle.file.open("rb") as fh:
        data = fh.read()
    assert hashlib.sha256(data).hexdigest() == bundle.sha256 and bundle.size == len(data)
    assert set(zipfile.ZipFile(io.BytesIO(data)).namelist()) >= {"cover.md", "roster.csv", "evidence.json"}
    assert bundle.counts["roster"] == review.items.count()
    # The attesters (not root: a superuser can't sign) hear in-app and by email.
    assert bells(attester, "access.review.opened").count() == 1 and bells(attester2).count() == 1
    assert not bells(root).exists()
    bell = bells(attester).get()
    assert bell.url == reverse("access:review_detail", kwargs={"pk": review.pk})
    assert bell.subject_key == f"access.review:{review.pk}" and "Q3 2026" in bell.title
    assert len(mail.outbox) == 1 and set(mail.outbox[0].to) == {"ann@example.com", "bo@example.com"}
    assert "due" in mail.outbox[0].subject.lower() and "Oct 30, 2026" in mail.outbox[0].body
    # Not escalated in the same tick it was opened, even when late.
    assert result["escalated"] == [] and result["reminded"] == []


def test_the_tick_is_idempotent(attester, attester2, root):
    first = cadence.tick(today=TODAY)
    mail.outbox.clear()
    again = cadence.tick(today=TODAY)
    assert again["opened"] is None and again["bundle"] is None and again["reminded"] == []
    assert AccessReview.objects.count() == 1 and EvidenceBundle.objects.count() == 1
    assert not mail.outbox and bells(attester).count() == 1
    # A hand-opened review of the scope blocks the schedule the same way: one open roster.
    review = AccessReview.objects.get(pk=first["opened"])
    assert review.status == "open"


def test_reminders_then_escalation(attester, attester2, root):
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])
    mail.outbox.clear()
    # Six days on: nothing yet.
    AccessReview.objects.filter(pk=review.pk).update(reminded_at=timezone.now() - timedelta(days=6))
    assert cadence.tick(today=TODAY)["reminded"] == []
    # Eight days on: a reminder, counted.
    AccessReview.objects.filter(pk=review.pk).update(reminded_at=timezone.now() - timedelta(days=8))
    assert cadence.tick(today=TODAY + timedelta(days=8))["reminded"] == [review.pk]
    review.refresh_from_db()
    assert review.reminders == 1 and review.escalated_at is None
    assert bells(attester, "access.review.reminder").count() == 1
    assert "still open" in mail.outbox[-1].subject and set(mail.outbox[-1].to) == {"ann@example.com", "bo@example.com"}
    # Past due: escalated once, to the attesters and the escalation list.
    mail.outbox.clear()
    AccessReview.objects.filter(pk=review.pk).update(reminded_at=timezone.now())
    assert cadence.tick(today=LATE)["escalated"] == [review.pk]
    review.refresh_from_db()
    assert review.escalated_at is not None and review.reminders == 2
    assert bells(attester, "access.review.overdue").count() == 1
    assert "overdue" in mail.outbox[-1].subject.lower()
    assert set(mail.outbox[-1].to) == {"ann@example.com", "bo@example.com", "grc@example.com"}
    # Not escalated twice; reminders keep their cadence.
    assert cadence.tick(today=LATE + timedelta(days=1))["escalated"] == []
    # The finding names the open review and its due date.
    finding = next(f for f in run_checks() if f.key == "review_overdue")
    row = next(r for r in finding.rows if r["label"] == "Q3 2026")
    assert "open since" in row["meta"] and "due Oct 30, 2026" in row["meta"]
    assert row["href"] == reverse("access:review_detail", kwargs={"pk": review.pk})


def test_off_by_default_nothing_happens_and_nothing_shows(settings, client, attester, attester2, root):
    """The default: attestation on demand. No job, no mail, no bells, no
    dashboard card, no "overdue" anywhere — until someone turns it on or
    opens a review by hand."""
    settings.SMALLSTACK_ACCESS_REVIEW_CADENCE = ""
    result = cadence.tick(today=TODAY)
    assert "skipped" in result and result["opened"] is None and not AccessReview.objects.exists()
    assert not mail.outbox and not Notification.objects.exists() and not cadence.enabled()
    assert not AccessReviewWidget().on_dashboard and cadence.scheduled_job() is None
    client.force_login(attester)
    page = client.get(reverse("access:reviews")).content.decode()
    assert "on demand" in page and "overdue" not in page and "nobody can sign" not in page
    # A card added by hand (Add card → Widget) reports without alarm: no due date while off.
    data = AccessReviewWidget().get_data()
    assert data["headline"] == "Q3 2026 not reviewed" and data["status"] == "ok" and "on demand" in data["detail"]
    reviews.open_review(period_start=date(2026, 7, 1), period_end=date(2026, 9, 30), scope="privileged", actor=attester)
    assert not AccessReviewWidget().on_dashboard
    data = AccessReviewWidget().get_data()
    assert data["headline"] == "Q3 2026 open" and data["status"] == "warning" and "overdue" not in data["headline"]
    assert cadence.tick(today=LATE)["escalated"] == []  # the tick still does nothing while off


def test_no_attester_is_a_warning_not_a_failure(root, manager, caplog):
    result = cadence.tick(today=TODAY)
    assert result["opened"] is not None and not mail.outbox and not Notification.objects.exists()
    assert any("no account can sign" in r.getMessage() for r in caplog.records)


# --- Signing's follow-through ----------------------------------------------------------


def test_signing_retires_bells_stores_the_attested_pack_and_emits_the_webhook(attester, attester2, root, monkeypatch):
    monkeypatch.setattr(webhooks, "_enqueue_delivery", lambda pk: None)
    endpoint = WebhookEndpoint.objects.create(
        name="grc", target_url="https://grc.example.com/hook", secret="s" * 32, event_filter=["access.review.*"]
    )
    other = WebhookEndpoint.objects.create(
        name="other", target_url="https://other.example.com/hook", secret="s" * 32, event_filter=["*.created"]
    )
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])
    assert bells(attester).filter(read_at__isnull=True).count() == 1
    sign(review, attester, attester2)
    # The "review due" bells are retired for everyone.
    assert not Notification.objects.filter(subject_key=f"access.review:{review.pk}", read_at__isnull=True).exists()
    # The attested pack, in the signer's name, beside the period-closed one.
    attested = EvidenceBundle.objects.get(review=review, reason="review_signed")
    assert attested.built_by == attester and attested.counts["reviews"] == review.items.count()
    assert EvidenceBundle.objects.filter(review=review).count() == 2
    # The webhook event, to the endpoint whose filter matches, in the CRUDView envelope shape.
    delivery = WebhookDelivery.objects.get(endpoint=endpoint)
    assert not WebhookDelivery.objects.filter(endpoint=other).exists()
    p = delivery.payload
    assert delivery.event_type == p["event"] == "access.review.signed" and p["action"] == "signed"
    assert p["model"] == "access.accessreview" and p["id"] == review.pk and p["event_id"] == str(delivery.event_id)
    assert (
        p["data"]["status"] == "signed"
        and p["data"]["signed_by"] == "attester"
        and p["data"]["summary"]["flagged"] == 1
    )
    assert p["resource"]["type"] == "access.accessreview" and p["resource"]["id"] == review.pk


def test_the_event_is_in_the_picker():
    assert "access.review.signed" in webhooks.available_events()
    assert webhooks.describe_event_pattern("access.review.signed") == "an access review is signed"
    assert webhooks.unmatched_patterns(["access.review.*"]) == []
    with pytest.raises(ValueError):
        webhooks.register_event("access.*")


def test_a_failing_follow_through_never_fails_the_signing(attester, attester2, root, monkeypatch):
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])

    def boom(*args, **kwargs):
        raise RuntimeError("storage is down")

    monkeypatch.setattr(cadence, "store_bundle", boom)
    monkeypatch.setattr(cadence, "emit_signed", boom)
    signed = sign(review, attester, attester2)
    assert signed.is_signed and EvidenceBundle.objects.filter(review=review).count() == 1


# --- Stored packs -------------------------------------------------------------------------


def test_retention_keeps_the_newest_per_scope(settings, root):
    settings.SMALLSTACK_ACCESS_EVIDENCE_KEEP = 2
    start, end = date(2026, 7, 1), date(2026, 9, 30)
    first = cadence.store_bundle(start, end, "privileged")
    storage, name = first.file.storage, first.file.name
    cadence.store_bundle(start, end, "privileged")
    cadence.store_bundle(start, end, "privileged")
    kept_all = cadence.store_bundle(start, end, "all")
    assert EvidenceBundle.objects.filter(scope="privileged").count() == 2
    assert not EvidenceBundle.objects.filter(pk=first.pk).exists() and not storage.exists(name)
    assert EvidenceBundle.objects.filter(pk=kept_all.pk).exists()
    settings.SMALLSTACK_ACCESS_EVIDENCE_KEEP = 0
    cadence.store_bundle(start, end, "privileged")
    assert EvidenceBundle.objects.filter(scope="privileged").count() == 3


def test_the_pages_list_store_and_download_packs(client, attester, staffer, root):
    client.force_login(attester)
    page = client.get(reverse("access:evidence")).content.decode()
    assert "Stored packs" in page and "Store this pack" in page
    assert "No stored packs yet" in client.get(reverse("access:evidence") + "?tab=packs").content.decode()
    resp = client.post(reverse("access:evidence_store"), {"from": "2026-07-01", "to": "2026-09-30", "scope": "all"})
    assert resp.status_code == 302 and "tab=packs" in resp["Location"]
    bundle = EvidenceBundle.objects.get()
    assert (bundle.scope, bundle.reason, bundle.built_by) == ("all", "manual", attester)
    page = client.get(resp["Location"]).content.decode()
    assert "on request" in page and bundle.sha256[:16] in page and "Download" in page
    # The download is the stored bytes, digest in a header the auditor can check.
    resp = client.get(reverse("access:evidence_pack", kwargs={"pk": bundle.pk}))
    assert resp.status_code == 200 and resp["Content-Type"] == "application/zip"
    assert resp["X-Content-SHA256"] == bundle.sha256 == hashlib.sha256(resp.content).hexdigest()
    assert "cover.md" in zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    # A reader downloads but may not store (an attester or a superuser may).
    client.force_login(staffer)
    assert client.get(reverse("access:evidence_pack", kwargs={"pk": bundle.pk})).status_code == 200
    assert "Store this pack" not in client.get(reverse("access:evidence")).content.decode()
    client.post(reverse("access:evidence_store"), {"from": "2026-07-01", "to": "2026-09-30"})
    assert EvidenceBundle.objects.count() == 1
    # The public media route refuses the stored file.
    assert client.get(f"/media/{bundle.file.name}").status_code == 404


def test_the_reviews_page_shows_the_cadence(client, attester, attester2, root):
    client.force_login(attester)
    page = client.get(reverse("access:reviews")).content.decode()
    assert "By the schedule" in page and "quarterly" in page and "attester, attester2" in page
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])
    AccessReview.objects.filter(pk=review.pk).update(reminders=2, escalated_at=timezone.now())
    page = client.get(reverse("access:reviews")).content.decode()
    assert "by the schedule" in page and "reminded 2×" in page and "escalated" in page
    detail = client.get(reverse("access:review_detail", kwargs={"pk": review.pk})).content.decode()
    assert "the schedule" in detail and "Reminders" in detail


# --- The widget ---------------------------------------------------------------------------


def test_a_dashboard_card_honours_the_widgets_gate(rf, root, staffer):
    """The saved-grid bridge asks the widget's ``visible_to`` like the
    /smallstack/ cards do: a board shared wider than the widget's numbers
    renders a restricted cell, not the numbers."""
    from apps.dashboards.components import CellContext, build_widget

    cell = {"type": "widget", "id": "c1", "options": {"widget": "apps.access.dashboard_widgets.AccessReviewWidget"}}
    plain = User.objects.create_user("plain", password="p", is_staff=True)
    request = rf.get("/smallstack/")
    request.user = plain
    assert build_widget(cell, CellContext(request=request)) == {"restricted": True, "label": "Access review"}
    request.user = staffer
    assert "ctx" in build_widget(cell, CellContext(request=request))


def test_the_widget_follows_the_review(attester, attester2, root, monkeypatch):
    widget = AccessReviewWidget()
    assert widget.visible_to(root) and widget.visible_to(attester2) and widget.on_dashboard
    monkeypatch.setattr(cadence.timezone, "localdate", lambda *a, **k: TODAY)
    # Not reviewed, due in 25 days.
    data = widget.get_data()
    assert data["headline"] == "Q3 2026 not reviewed" and data["status"] == "warning" and "25 days" in data["detail"]
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])
    data = widget.get_data()
    assert data["headline"] == "Q3 2026 due in 25 days" and data["status"] == "warning"
    assert data["detail"].endswith("pending") and data["extra"]["open_review"] == review.pk
    monkeypatch.setattr(cadence.timezone, "localdate", lambda *a, **k: LATE)
    data = widget.get_data()
    assert data["headline"] == "Q3 2026 overdue 6 days" and data["status"] == "error"
    sign(review, attester, attester2)
    data = widget.get_data()
    assert data["headline"] == "Q3 2026 signed" and data["status"] == "ok" and "by attester" in data["detail"]
    assert data["extra"]["signed_review"] == review.pk and data["extra"]["next_close"] == "2026-12-31"


# --- CLI and REST ----------------------------------------------------------------------------


def test_the_cli_runs_the_cadence_and_lists_packs(attester, attester2, root):
    out = StringIO()
    call_command("access", "cadence", "--status", stdout=out)
    assert "Cadence: quarterly" in out.getvalue() and "not reviewed" in out.getvalue()
    out = StringIO()
    call_command("access", "cadence", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert data["opened"] and data["bundle"] and data["status"]["open_review"] == data["opened"]
    out = StringIO()
    args = ["--from", "2026-07-01", "--to", "2026-09-30", "--store", "--user", "root", "--json"]
    call_command("access", "evidence", *args, stdout=out)
    stored = json.loads(out.getvalue())
    assert stored["reason"] == "manual" and stored["built_by"] == "root" and len(stored["sha256"]) == 64
    out = StringIO()
    call_command("access", "packs", stdout=out)
    assert out.getvalue().count("#") == 2 and "period_closed" in out.getvalue() and "manual" in out.getvalue()
    out = StringIO()
    call_command("access", "packs", "--scope", "all", "--json", stdout=out)
    assert json.loads(out.getvalue()) == []


def test_rest_reads_packs_and_the_cadence(client, staffer, attester, root):
    review = AccessReview.objects.get(pk=cadence.tick(today=TODAY)["opened"])
    client.force_login(staffer)
    packs = client.get(BASE + "evidence/packs/").json()["results"]
    assert len(packs) == 1 and packs[0]["reason"] == "period_closed" and packs[0]["review"] == review.pk
    one = client.get(BASE + f"evidence/packs/{packs[0]['id']}/").json()
    assert one["sha256"] == packs[0]["sha256"] and one["filename"].endswith(".zip")
    resp = client.get(BASE + f"evidence/packs/{packs[0]['id']}/?format=zip")
    assert resp.status_code == 200 and resp["X-Content-SHA256"] == one["sha256"]
    assert hashlib.sha256(resp.content).hexdigest() == one["sha256"]
    assert client.get(BASE + "evidence/packs/999/").status_code == 404
    state = client.get(BASE + "reviews/cadence/").json()
    assert state["cadence"] == "quarterly" and state["open"]["id"] == review.pk and state["signed"] is None
    assert state["period"]["label"] == reviews.recent_quarters(1)[0].label
    # Reading needs accounts.view_user, as every Access read does.
    client.force_login(User.objects.create_user("plain", password="p", is_staff=True))
    assert client.get(BASE + "evidence/packs/").status_code == 403


def test_the_scheduled_job_exists_only_when_the_cadence_is_on():
    """Declared at import from the real setting: present iff the environment
    turned the cadence on (the default leaves it off, so nothing is scheduled)."""
    from apps.scheduler.decorators import _SCHEDULE_REGISTRY

    spec = next((s for s in _SCHEDULE_REGISTRY if s.task_path == cadence.TASK_PATH), None)
    if os.environ.get("SMALLSTACK_ACCESS_REVIEW_CADENCE") == "quarterly":
        assert spec is not None and spec.name == "Access: review cadence" and spec.schedule_type == "cron"
    else:
        assert spec is None


def test_stores_on_request_never_push_out_the_attested_pack(settings, root):
    """T4-2: retention counts each reason apart, so pressing *Store this pack*
    can only evict older on-request packs, never the signed or closing one."""
    settings.SMALLSTACK_ACCESS_EVIDENCE_KEEP = 2
    start, end = date(2026, 7, 1), date(2026, 9, 30)
    signed = cadence.store_bundle(start, end, "all", reason=EvidenceBundle.Reason.REVIEW_SIGNED)
    closed = cadence.store_bundle(start, end, "all", reason=EvidenceBundle.Reason.PERIOD_CLOSED)
    for _ in range(4):
        cadence.store_bundle(start, end, "all", actor=root)
    assert EvidenceBundle.objects.filter(pk__in=[signed.pk, closed.pk]).count() == 2
    assert signed.file.storage.exists(signed.file.name)
    assert EvidenceBundle.objects.filter(scope="all", reason=EvidenceBundle.Reason.MANUAL).count() == 2
