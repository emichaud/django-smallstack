"""The send pipeline: durable, batched, resumable, and never double-sending.

The design under test is "**Delivery rows are the ledger**". `queue_issue`
materialises one row per recipient up front; everything after that is draining
`pending`. The properties that matter, each asserted here:

* a partial send **resumes** and finishes with exactly N messages, not N+K;
* a worker killed mid-batch leaves claims that the reaper returns, and the
  next tick sends those recipients **exactly once**;
* a hard bounce suppresses the address, a transient failure does **not**;
* one SMTP connection per *batch*, not per message.

Failure paths use the deliberately-raising backends in ``mail_backends``,
because locmem and console never raise and would leave all of this untested.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings

from apps.blog import service
from apps.blog.models import Delivery, Issue, Subscription
from apps.blog.tests import mail_backends

pytestmark = pytest.mark.django_db

BACKEND = "apps.blog.tests.mail_backends.%s"


def _mailers(name: str) -> dict:
    return {"default": {"BACKEND": BACKEND % name, "OPTIONS": {}}}


@pytest.fixture
def newsletter_blog(blog, settings):
    # Unsubscribe links must not point at localhost, or queue_issue refuses —
    # which is the point of that guard, but not what these tests are about.
    settings.SITE_DOMAIN = "blog.example.test"
    blog.newsletter_enabled = True
    blog.save(update_fields=["newsletter_enabled"])
    return blog


def _subscribe(blog, *addresses: str) -> list[Subscription]:
    out = []
    for address in addresses:
        sub = service.subscribe(blog, address, send_email=False)
        sub.status = Subscription.Status.CONFIRMED
        sub.save(update_fields=["status"])
        out.append(sub)
    return out


@pytest.fixture
def issue_with_audience(newsletter_blog, owner):
    _subscribe(newsletter_blog, *[f"r{i}@example.test" for i in range(5)])
    return service.create_issue(
        newsletter_blog, subject="Issue 1", body_markdown="# Hello\n\nBody.", actor=owner
    )


# ── Queueing ────────────────────────────────────────────────────────────────


def test_queueing_freezes_the_body_and_the_audience(issue_with_audience, owner):
    issue = service.queue_issue(issue_with_audience, actor=owner)

    assert issue.status == Issue.Status.SENDING
    assert issue.recipient_count == 5
    assert "<h1" in issue.body_html, "the body is snapshotted, not read at send time"
    assert Delivery.objects.filter(issue=issue).count() == 5
    assert set(Delivery.objects.values_list("status", flat=True)) == {"pending"}


def test_queueing_excludes_pending_unsubscribed_and_suppressed(newsletter_blog, owner):
    confirmed, pending_sub, gone, bad = _subscribe(
        newsletter_blog, "ok@example.test", "p@example.test", "gone@example.test",
        "bad@example.test",
    )
    pending_sub.status = Subscription.Status.PENDING
    pending_sub.save(update_fields=["status"])
    gone.status = Subscription.Status.UNSUBSCRIBED
    gone.save(update_fields=["status"])
    service.suppress_subscriber(bad.subscriber, reason="hard bounce")

    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)
    service.queue_issue(issue, actor=owner)

    assert set(Delivery.objects.values_list("email", flat=True)) == {"ok@example.test"}


def test_requeueing_adds_nobody_twice(issue_with_audience, owner):
    service.queue_issue(issue_with_audience, actor=owner)
    with pytest.raises(service.AlreadySending):
        service.queue_issue(issue_with_audience, actor=owner)
    assert Delivery.objects.count() == 5


def test_queueing_refuses_an_empty_audience(newsletter_blog, owner):
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)
    with pytest.raises(service.InvalidState):
        service.queue_issue(issue, actor=owner)


def test_queueing_refuses_an_empty_body(newsletter_blog, owner):
    _subscribe(newsletter_blog, "a@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="", actor=owner)
    with pytest.raises(service.InvalidState):
        service.queue_issue(issue, actor=owner)


def test_dry_run_changes_nothing(issue_with_audience, owner):
    result = service.queue_issue(issue_with_audience, dry_run=True, actor=owner)
    assert result["recipients"] == 5
    assert Delivery.objects.count() == 0
    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.DRAFT


def test_queueing_refuses_when_the_site_url_is_localhost(issue_with_audience, owner, settings):
    """A blast cannot be recalled, and localhost unsubscribe links are dead
    for every recipient. Refuse rather than warn."""
    settings.SITE_DOMAIN = "localhost:8000"
    settings.SITE_URL = ""
    with pytest.raises(service.NewsletterNotReady, match="localhost"):
        service.queue_issue(issue_with_audience, actor=owner)


def test_the_localhost_guard_can_be_overridden_deliberately(
    issue_with_audience, owner, settings
):
    settings.SITE_DOMAIN = "localhost:8000"
    settings.SMALLSTACK_BLOG_REQUIRE_PUBLIC_URL = False
    assert service.queue_issue(issue_with_audience, actor=owner).status == Issue.Status.SENDING


def test_queueing_refuses_a_stranger(issue_with_audience, other_user):
    with pytest.raises(service.NotAuthorized):
        service.queue_issue(issue_with_audience, actor=other_user)


# ── Sending ─────────────────────────────────────────────────────────────────


def test_a_full_send_delivers_once_per_recipient(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)

    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.SENT
    assert issue_with_audience.sent_count == 5
    assert len(mail.outbox) == 5
    assert Delivery.objects.filter(status=Delivery.Status.SENT).count() == 5


def test_a_partial_send_resumes_without_double_sending(issue_with_audience, owner):
    """**The headline property.** Two batches of three over five recipients
    must total exactly five messages — not six, not eight."""
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)

    first = service.send_issue_batch(issue_with_audience, batch_size=3)
    assert first["sent"] == 3
    assert Delivery.objects.filter(status=Delivery.Status.PENDING).count() == 2

    second = service.send_issue_batch(issue_with_audience, batch_size=3)
    assert second["sent"] == 2

    assert len(mail.outbox) == 5
    assert len({m.to[0] for m in mail.outbox}) == 5, "every recipient exactly once"
    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.SENT


def test_a_dead_worker_is_recovered_by_the_reaper(issue_with_audience, owner):
    """A worker killed mid-batch leaves `claimed` rows. Without the reaper
    they are never retried and the issue never finalises — the send just
    stops, with no error and a progress bar short of 100%."""
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)

    # Simulate the crash: claim rows, then never send them.
    claimed = service._claim(issue_with_audience, 2)
    assert len(claimed) == 2
    assert Delivery.objects.filter(status=Delivery.Status.CLAIMED).count() == 2

    assert service.reap_stale_claims(older_than_minutes=-1) == 2
    assert Delivery.objects.filter(status=Delivery.Status.PENDING).count() == 5

    service.send_issue_batch(issue_with_audience)
    assert len(mail.outbox) == 5
    assert len({m.to[0] for m in mail.outbox}) == 5, "the reaped rows sent exactly once"


def test_the_reaper_leaves_fresh_claims_alone(issue_with_audience, owner):
    """Otherwise it would steal rows from a worker that is still sending
    them — which is how you get duplicates."""
    service.queue_issue(issue_with_audience, actor=owner)
    service._claim(issue_with_audience, 2)
    assert service.reap_stale_claims(older_than_minutes=60) == 0


def test_a_claimed_row_with_no_timestamp_is_still_reaped(issue_with_audience, owner):
    """An interrupted write can leave `claimed` with a NULL `claimed_at`.
    Filtering only on `claimed_at < cutoff` skips NULLs, which orphans the row
    permanently: never retried, and the issue never finalises."""
    service.queue_issue(issue_with_audience, actor=owner)
    service._claim(issue_with_audience, 2)
    Delivery.objects.filter(status=Delivery.Status.CLAIMED).update(claimed_at=None)

    assert service.reap_stale_claims(older_than_minutes=60) == 2
    assert Delivery.objects.filter(status=Delivery.Status.PENDING).count() == 5


def test_a_sent_delivery_is_never_reclaimed(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)

    assert service._claim(issue_with_audience, 10) == []
    service.send_issue_batch(issue_with_audience)
    assert len(mail.outbox) == 5


def test_unsubscribing_mid_send_is_honoured(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)

    leaver = Subscription.objects.get(subscriber__email="r0@example.test")
    leaver.status = Subscription.Status.UNSUBSCRIBED
    leaver.save(update_fields=["status"])

    service.send_issue_batch(issue_with_audience)
    assert "r0@example.test" not in {m.to[0] for m in mail.outbox}
    assert Delivery.objects.get(email="r0@example.test").status == Delivery.Status.SKIPPED


# ── Connection reuse ────────────────────────────────────────────────────────


def test_one_connection_serves_the_whole_batch(issue_with_audience, owner):
    """One TCP+TLS handshake and one AUTH per *batch*. Per-message is the
    difference between a 5,000-recipient send taking minutes and taking hours."""
    mail_backends.reset()
    with override_settings(MAILERS=_mailers("CountingBackend")):
        service.queue_issue(issue_with_audience, actor=owner)
        service.send_issue_batch(issue_with_audience)

    assert mail_backends.STATS["sent"] == 5
    assert mail_backends.STATS["opened"] == 1, (
        f"opened {mail_backends.STATS['opened']} connections for 5 messages"
    )


# ── Bounce policy ───────────────────────────────────────────────────────────


def test_a_hard_bounce_suppresses_the_address(newsletter_blog, owner):
    subs = _subscribe(newsletter_blog, "bounces@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("HardBounceBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)

    subs[0].subscriber.refresh_from_db()
    assert subs[0].subscriber.is_suppressed
    assert subs[0].subscriber.bounce_count == 1
    assert Delivery.objects.get(issue=issue).status == Delivery.Status.FAILED


def test_a_transient_failure_does_not_suppress(newsletter_blog, owner):
    """The most damaging bug in the prior implementation: it suppressed on
    *any* exception, so one flaky moment silently and permanently dropped a
    good reader."""
    subs = _subscribe(newsletter_blog, "flaky@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("SoftFailBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)

    subscriber = subs[0].subscriber
    subscriber.refresh_from_db()
    assert not subscriber.is_suppressed
    assert subscriber.consecutive_failures == 1

    delivery = Delivery.objects.get(issue=issue)
    assert delivery.status == Delivery.Status.PENDING, "retryable, not failed"
    assert delivery.attempts == 1


def test_a_transient_failure_gives_up_after_the_attempt_budget(newsletter_blog, owner, settings):
    settings.SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS = 2
    subs = _subscribe(newsletter_blog, "flaky@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("SoftFailBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)
        service.send_issue_batch(issue)

    delivery = Delivery.objects.get(issue=issue)
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.attempts == 2
    subs[0].subscriber.refresh_from_db()
    assert not subs[0].subscriber.is_suppressed, "giving up is not a bounce"


def test_enough_consecutive_soft_failures_eventually_suppress(newsletter_blog, owner, settings):
    settings.SMALLSTACK_BLOG_SOFT_FAIL_LIMIT = 2
    settings.SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS = 5
    subs = _subscribe(newsletter_blog, "dead@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("SoftFailBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)
        service.send_issue_batch(issue)

    subs[0].subscriber.refresh_from_db()
    assert subs[0].subscriber.is_suppressed


def test_a_success_resets_the_failure_counter(newsletter_blog, owner):
    subs = _subscribe(newsletter_blog, "recovered@example.test")
    subs[0].subscriber.consecutive_failures = 3
    subs[0].subscriber.save(update_fields=["consecutive_failures"])

    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)
    service.queue_issue(issue, actor=owner)
    service.send_issue_batch(issue)

    subs[0].subscriber.refresh_from_db()
    assert subs[0].subscriber.consecutive_failures == 0


def test_retry_failed_requeues_only_failures(newsletter_blog, owner, settings):
    settings.SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS = 1
    _subscribe(newsletter_blog, "a@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("SoftFailBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)
    assert Delivery.objects.get(issue=issue).status == Delivery.Status.FAILED

    settings.SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS = 3
    assert service.retry_failed(issue, actor=owner) == 1
    assert Delivery.objects.get(issue=issue).status == Delivery.Status.PENDING
    issue.refresh_from_db()
    assert issue.status == Issue.Status.SENDING


def test_retry_never_touches_a_sent_delivery(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)
    assert service.retry_failed(issue_with_audience, actor=owner) == 0
    assert len(mail.outbox) == 5


# ── Headers ─────────────────────────────────────────────────────────────────


def test_every_message_carries_both_list_unsubscribe_headers(issue_with_audience, owner):
    """These two are what make the one-click unsubscribe button appear in
    Gmail and Yahoo. Missing them is a deliverability problem that shows up
    as "our mail goes to spam" weeks later."""
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)

    for message in mail.outbox:
        headers = message.extra_headers
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        # The HTTPS URL must come FIRST — that is the one Gmail reads.
        assert headers["List-Unsubscribe"].startswith("<http")
        assert "mailto:" in headers["List-Unsubscribe"]
        assert headers["Precedence"] == "bulk"
        assert "List-ID" in headers


def test_each_recipients_unsubscribe_link_is_their_own(issue_with_audience, owner):
    """A shared link would unsubscribe whoever clicked first, for everyone."""
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)

    links = {m.extra_headers["List-Unsubscribe"] for m in mail.outbox}
    assert len(links) == 5


def test_messages_are_multipart_with_a_plaintext_part(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)

    message = mail.outbox[0]
    assert message.body.strip(), "a plaintext alternative is required"
    assert message.alternatives[0][1] == "text/html"


def test_the_message_id_is_stable_and_issue_scoped(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)
    for message in mail.outbox:
        assert str(issue_with_audience.uid) in message.extra_headers["Message-ID"]


# ── Finalisation and cancellation ───────────────────────────────────────────


def test_an_issue_finalises_only_when_nothing_is_outstanding(issue_with_audience, owner):
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience, batch_size=2)

    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.SENDING, "3 still pending"

    service.send_issue_batch(issue_with_audience, batch_size=10)
    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.SENT
    assert issue_with_audience.finished_at is not None


def test_an_all_failed_issue_finalises_as_failed(newsletter_blog, owner, settings):
    settings.SMALLSTACK_BLOG_SEND_MAX_ATTEMPTS = 1
    _subscribe(newsletter_blog, "a@example.test")
    issue = service.create_issue(newsletter_blog, subject="S", body_markdown="x", actor=owner)

    mail_backends.reset()
    with override_settings(MAILERS=_mailers("HardBounceBackend")):
        service.queue_issue(issue, actor=owner)
        service.send_issue_batch(issue)

    issue.refresh_from_db()
    assert issue.status == Issue.Status.FAILED


def test_cancelling_stops_the_rest(issue_with_audience, owner):
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience, batch_size=2)
    service.cancel_issue(issue_with_audience, actor=owner)

    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.CANCELED
    assert Delivery.objects.filter(status=Delivery.Status.SKIPPED).count() == 3

    service.send_issue_batch(issue_with_audience)
    assert len(mail.outbox) == 2, "cancelling must stop further delivery"


def test_a_sent_issue_cannot_be_cancelled(issue_with_audience, owner):
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)
    with pytest.raises(service.AlreadySending):
        service.cancel_issue(issue_with_audience, actor=owner)


# ── The tick ────────────────────────────────────────────────────────────────


def test_the_tick_drains_an_issue(issue_with_audience, owner, settings):
    settings.SMALLSTACK_BLOG_SEND_BATCH_SIZE = 2
    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)

    from apps.blog.tasks import newsletter_send_tick

    newsletter_send_tick.call()

    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.SENT
    assert len(mail.outbox) == 5


def test_the_tick_reaps_before_it_claims(issue_with_audience, owner):
    service.queue_issue(issue_with_audience, actor=owner)
    service._claim(issue_with_audience, 5)
    Delivery.objects.update(claimed_at=None)  # look ancient

    mail.outbox.clear()
    from apps.blog.tasks import newsletter_send_tick

    newsletter_send_tick.call()
    assert len(mail.outbox) == 5


# ── Test sends ──────────────────────────────────────────────────────────────


def test_a_test_send_writes_no_delivery_row(issue_with_audience, owner):
    """A preview must never appear in the ledger that drives resumability."""
    mail.outbox.clear()
    assert service.send_test(issue_with_audience, "me@example.test", actor=owner) == 1

    assert Delivery.objects.count() == 0
    assert mail.outbox[0].to == ["me@example.test"]
    assert mail.outbox[0].subject.startswith("[Test]")
    issue_with_audience.refresh_from_db()
    assert issue_with_audience.status == Issue.Status.DRAFT


def test_a_test_send_refuses_a_stranger(issue_with_audience, other_user):
    with pytest.raises(service.NotAuthorized):
        service.send_test(issue_with_audience, "me@example.test", actor=other_user)


# ── Issues from posts ───────────────────────────────────────────────────────


def test_an_issue_can_be_opened_from_a_post(newsletter_blog, post, owner):
    issue = service.create_issue_from_post(post, actor=owner)
    assert issue.post == post
    assert issue.subject == post.title
    assert issue.status == Issue.Status.DRAFT


def test_a_post_can_opt_out_of_the_newsletter(newsletter_blog, post, owner):
    post.allow_newsletter = False
    post.save(update_fields=["allow_newsletter"])
    with pytest.raises(service.InvalidState):
        service.create_issue_from_post(post, actor=owner)


def test_an_issue_from_a_post_uses_the_posts_body_at_queue_time(
    newsletter_blog, post, owner
):
    """The body is resolved when queued, so edits right up to the send are
    picked up — and frozen from that moment on."""
    _subscribe(newsletter_blog, "a@example.test")
    issue = service.create_issue_from_post(post, actor=owner)

    service.update_post(post, body_markdown="# Hello World\n\nRewritten.", actor=owner)
    service.queue_issue(issue, actor=owner)

    assert "Rewritten." in issue.body_html

    service.update_post(post, body_markdown="Changed again.", actor=owner)
    issue.refresh_from_db()
    assert "Rewritten." in issue.body_html, "a sent issue is a permanent record"


def test_only_one_live_issue_per_post(newsletter_blog, post, owner):
    """The service refuses readably; the constraint still backs it.

    This used to assert ``pytest.raises(IntegrityError)`` — which was true, and
    was the defect: ``views.issue_queue`` catches ``BlogServiceError`` only, so
    the raw database error escaped as HTTP 500 on the most consequential button
    in the app. The guarantee hasn't changed (see the constraint check below);
    what changed is that callers now get a typed, message-bearing error.
    """
    _subscribe(newsletter_blog, "a@example.test")
    first = service.create_issue_from_post(post, actor=owner)
    service.queue_issue(first, actor=owner)

    second = service.create_issue_from_post(post, actor=owner)
    with pytest.raises(service.BlogServiceError):
        service.queue_issue(second, actor=owner)

    second.refresh_from_db()
    assert second.status == Issue.Status.DRAFT


def test_one_live_issue_per_post_is_still_enforced_by_the_database(
    newsletter_blog, post, owner
):
    """The service-level check is for the message; the constraint is the truth.

    Bypassing the service entirely must still be refused, so that the readable
    error added for the view cannot be mistaken for the whole guarantee.
    """
    from django.db import IntegrityError, transaction

    _subscribe(newsletter_blog, "b@example.test")
    first = service.create_issue_from_post(post, actor=owner)
    service.queue_issue(first, actor=owner)

    second = service.create_issue_from_post(post, actor=owner)
    with pytest.raises(IntegrityError), transaction.atomic():
        Issue.objects.filter(pk=second.pk).update(status=Issue.Status.SENT)


def test_our_default_mailer_alias_matches_djangos():
    """We spell the alias out because django-stubs doesn't export the symbol
    yet. If Django ever changes it, this catches the drift instead of the
    send silently routing to a mailer that doesn't exist."""
    from django.core.mail import DEFAULT_MAILER_ALIAS

    assert service.DEFAULT_MAILER_ALIAS == DEFAULT_MAILER_ALIAS


def test_an_unknown_mailer_alias_falls_back_instead_of_stranding_the_send(
    issue_with_audience, owner
):
    """A typo in a per-blog alias must not cost the whole send."""
    issue_with_audience.blog.mailer_alias = "does-not-exist"
    issue_with_audience.blog.save(update_fields=["mailer_alias"])

    mail.outbox.clear()
    service.queue_issue(issue_with_audience, actor=owner)
    service.send_issue_batch(issue_with_audience)
    assert len(mail.outbox) == 5
