"""The subscriber lifecycle: subscribe → confirm → unsubscribe.

This is the half of a newsletter that is easy to get subtly, silently wrong,
and the prior art this replaces got four things wrong at once. Each is pinned
here:

* unsubscribe was a POST-only endpoint linked as a plain ``<a href>``, so
  clicking it produced a 405 and **unsubscribe simply did not work**;
* the token was a raw unsigned UUID shared across every list, so one link
  governed them all;
* unsubscribing hard-deleted the row, losing the memory that the person opted
  out;
* there was no double opt-in at all.
"""

from __future__ import annotations

import pytest
from django.core import mail

from apps.blog import service, tokens
from apps.blog.models import Subscriber, Subscription

pytestmark = pytest.mark.django_db


@pytest.fixture
def newsletter_blog(blog):
    blog.newsletter_enabled = True
    blog.save(update_fields=["newsletter_enabled"])
    return blog


@pytest.fixture
def pending(newsletter_blog):
    mail.outbox.clear()
    return service.subscribe(newsletter_blog, "reader@example.test", name="Reader")


# ── Subscribing ─────────────────────────────────────────────────────────────


def test_subscribing_creates_a_pending_row_and_sends_one_email(newsletter_blog):
    mail.outbox.clear()
    sub = service.subscribe(newsletter_blog, "new@example.test")

    assert sub.status == Subscription.Status.PENDING
    assert sub.confirmed_at is None
    assert len(mail.outbox) == 1
    assert "Confirm" in mail.outbox[0].subject


def test_the_address_is_normalised(newsletter_blog):
    service.subscribe(newsletter_blog, "  MixedCase@Example.TEST ")
    assert Subscriber.objects.filter(email="mixedcase@example.test").exists()


def test_subscribing_twice_does_not_duplicate(newsletter_blog, pending):
    again = service.subscribe(newsletter_blog, "reader@example.test")
    assert again.pk == pending.pk
    assert Subscription.objects.filter(blog=newsletter_blog).count() == 1


def test_a_blog_without_a_newsletter_refuses(blog):
    with pytest.raises(service.NewsletterNotReady):
        service.subscribe(blog, "x@example.test")


def test_a_malformed_address_is_rejected(newsletter_blog):
    with pytest.raises(service.InvalidState):
        service.subscribe(newsletter_blog, "not-an-address")


def test_an_unconfirmed_subscriber_is_not_in_the_audience(newsletter_blog, pending):
    assert service.audience(newsletter_blog).count() == 0


def test_a_suppressed_address_is_not_in_the_audience(newsletter_blog, pending):
    service.confirm_subscription(tokens.make_confirm_token(pending))
    assert service.audience(newsletter_blog).count() == 1

    service.suppress_subscriber(pending.subscriber, reason="hard bounce")
    assert service.audience(newsletter_blog).count() == 0


# ── Confirming ──────────────────────────────────────────────────────────────


def test_confirming_completes_the_double_opt_in(newsletter_blog, pending):
    mail.outbox.clear()
    sub = service.confirm_subscription(tokens.make_confirm_token(pending))

    assert sub.status == Subscription.Status.CONFIRMED
    assert sub.confirmed_at is not None
    assert len(mail.outbox) == 1, "a welcome email should follow"


def test_confirming_twice_is_idempotent(newsletter_blog, pending):
    token = tokens.make_confirm_token(pending)
    service.confirm_subscription(token)
    first = Subscription.objects.get(pk=pending.pk).confirmed_at
    service.confirm_subscription(token)
    assert Subscription.objects.get(pk=pending.pk).confirmed_at == first


def test_an_expired_confirm_token_is_rejected(newsletter_blog, pending, settings):
    settings.SMALLSTACK_BLOG_CONFIRM_MAX_AGE_DAYS = 0
    with pytest.raises(tokens.InvalidToken):
        tokens.read_confirm_token(tokens.make_confirm_token(pending))


# ── Token integrity ─────────────────────────────────────────────────────────


def test_a_tampered_token_is_rejected(pending):
    token = tokens.make_confirm_token(pending)
    with pytest.raises(tokens.InvalidToken):
        tokens.read_confirm_token(token[:-4] + "AAAA")


def test_garbage_is_rejected():
    for junk in ("", "x", "not.a.token", "a:b:c"):
        with pytest.raises(tokens.InvalidToken):
            tokens.read_confirm_token(junk)


def test_a_confirm_token_cannot_be_replayed_as_an_unsubscribe(pending):
    """Different salts, so the two are not interchangeable even though the
    payloads are identical in shape."""
    with pytest.raises(tokens.InvalidToken):
        tokens.read_unsubscribe_token(tokens.make_confirm_token(pending))
    with pytest.raises(tokens.InvalidToken):
        tokens.read_confirm_token(tokens.make_unsubscribe_token(pending))


def test_a_token_minted_for_one_blog_is_rejected_against_another(
    newsletter_blog, other_blog, pending
):
    """The headline failure of the prior design: one opaque subscriber id
    served every list, so a single unsubscribe link governed all of them."""
    other_blog.newsletter_enabled = True
    other_blog.save(update_fields=["newsletter_enabled"])
    other = service.subscribe(other_blog, "reader@example.test")

    token = tokens.make_unsubscribe_token(pending)
    resolved = tokens.read_unsubscribe_token(token)
    assert resolved.pk == pending.pk
    assert resolved.pk != other.pk
    assert resolved.blog_id == newsletter_blog.pk


def test_resubscribing_invalidates_the_old_unsubscribe_link(newsletter_blog, pending):
    """The replay defence. Without the token_version bump, a one-click link
    from an old email could silently kill a brand-new signup — a failure
    nobody notices until the reader complains a second time."""
    stale = tokens.make_unsubscribe_token(pending)
    service.unsubscribe(stale)
    service.subscribe(newsletter_blog, "reader@example.test")

    with pytest.raises(tokens.InvalidToken):
        tokens.read_unsubscribe_token(stale)


def test_changing_the_address_invalidates_the_token(pending):
    token = tokens.make_unsubscribe_token(pending)
    pending.subscriber.email = "moved@example.test"
    pending.subscriber.save(update_fields=["email"])
    with pytest.raises(tokens.InvalidToken):
        tokens.read_unsubscribe_token(token)


def test_a_deleted_subscription_makes_its_token_invalid(pending):
    token = tokens.make_unsubscribe_token(pending)
    pending.delete()
    with pytest.raises(tokens.InvalidToken):
        tokens.read_unsubscribe_token(token)


# ── Unsubscribing ───────────────────────────────────────────────────────────


def test_unsubscribing_is_a_state_change_not_a_delete(newsletter_blog, pending):
    """The row is what remembers the opt-out. Deleting it lets a later import
    resurrect someone who explicitly left."""
    service.unsubscribe(tokens.make_unsubscribe_token(pending))

    pending.refresh_from_db()
    assert pending.status == Subscription.Status.UNSUBSCRIBED
    assert pending.unsubscribed_at is not None
    assert Subscription.objects.filter(pk=pending.pk).exists()
    assert Subscriber.objects.filter(pk=pending.subscriber_id).exists()


def test_unsubscribing_twice_is_idempotent(pending):
    """A provider that retries the one-click POST must see success, not an
    error."""
    token = tokens.make_unsubscribe_token(pending)
    service.unsubscribe(token)
    first = Subscription.objects.get(pk=pending.pk).unsubscribed_at
    service.unsubscribe(token)
    assert Subscription.objects.get(pk=pending.pk).unsubscribed_at == first


def test_an_unsubscribe_token_never_expires(pending, settings):
    """An RFC 8058 header in a two-year-old email must still work — an
    expired opt-out link is a compliance problem, not a security feature."""
    settings.SMALLSTACK_BLOG_CONFIRM_MAX_AGE_DAYS = 0
    assert tokens.read_unsubscribe_token(tokens.make_unsubscribe_token(pending))


# ── The web flow ────────────────────────────────────────────────────────────


def test_the_subscribe_page_posts_and_reports_neutrally(client, newsletter_blog):
    mail.outbox.clear()
    url = f"/blog/{newsletter_blog.slug}/subscribe/"
    assert client.get(url).status_code == 200

    first = client.post(url, {"email": "a@example.test"}).content.decode()
    second = client.post(url, {"email": "a@example.test"}).content.decode()
    assert "Check your inbox" in first
    # Identical response whether or not the address was already on the list —
    # otherwise the form is a membership oracle.
    assert first == second


def test_the_honeypot_silently_absorbs_a_bot(client, newsletter_blog):
    mail.outbox.clear()
    client.post(
        f"/blog/{newsletter_blog.slug}/subscribe/",
        {"email": "bot@example.test", "website": "http://spam.test"},
    )
    assert not Subscription.objects.filter(subscriber__email="bot@example.test").exists()
    assert mail.outbox == []


def test_get_on_confirm_and_unsubscribe_mutates_nothing(client, pending):
    """A GET that acts is triggered by link prefetchers and mail scanners —
    people get removed from lists they never left."""
    confirm = tokens.make_confirm_token(pending)
    unsub = tokens.make_unsubscribe_token(pending)

    assert client.get(f"/blog/subscribe/confirm/{confirm}/").status_code == 200
    assert client.get(f"/blog/unsubscribe/{unsub}/").status_code == 200

    pending.refresh_from_db()
    assert pending.status == Subscription.Status.PENDING
    assert pending.unsubscribed_at is None


def test_posting_confirm_and_unsubscribe_acts(client, pending):
    client.post(f"/blog/subscribe/confirm/{tokens.make_confirm_token(pending)}/")
    pending.refresh_from_db()
    assert pending.status == Subscription.Status.CONFIRMED

    client.post(f"/blog/unsubscribe/{tokens.make_unsubscribe_token(pending)}/")
    pending.refresh_from_db()
    assert pending.status == Subscription.Status.UNSUBSCRIBED


def test_one_click_unsubscribe_works_without_a_csrf_token(client, pending):
    """**The test that catches the 405 class of bug.**

    An RFC 8058 one-click POST arrives from Gmail/Yahoo infrastructure with no
    session and no CSRF token. If this view ever regains CSRF protection, the
    unsubscribe button in every mail client silently stops working — and
    nobody finds out, because the failure is invisible to both sides.
    """
    from django.test import Client

    enforcing = Client(enforce_csrf_checks=True)
    response = enforcing.post(f"/blog/unsubscribe/{tokens.make_unsubscribe_token(pending)}/")

    assert response.status_code == 200, "one-click unsubscribe must not require CSRF"
    pending.refresh_from_db()
    assert pending.status == Subscription.Status.UNSUBSCRIBED


def test_confirm_still_requires_csrf(client, pending):
    """Only unsubscribe is exempt — confirm is always posted from our own page."""
    from django.test import Client

    enforcing = Client(enforce_csrf_checks=True)
    response = enforcing.post(f"/blog/subscribe/confirm/{tokens.make_confirm_token(pending)}/")
    assert response.status_code == 403


def test_an_invalid_token_renders_a_helpful_page_not_a_500(client):
    response = client.get("/blog/unsubscribe/garbage/")
    assert response.status_code == 200
    assert "isn't valid" in response.content.decode()


def test_subscribing_to_a_blog_without_a_newsletter_404s(client, blog):
    assert client.get(f"/blog/{blog.slug}/subscribe/").status_code == 404


# ── Imports ─────────────────────────────────────────────────────────────────


def test_importing_requires_a_consent_note(newsletter_blog, owner):
    """Importing is the one path that can skip confirmation, so the record of
    why these people may be mailed has to exist before the first send."""
    with pytest.raises(service.InvalidState):
        service.import_subscribers(
            newsletter_blog, [("a@example.test", "A")], consent_note="", actor=owner
        )


def test_importing_can_mark_rows_confirmed(newsletter_blog, owner):
    stats = service.import_subscribers(
        newsletter_blog,
        [("a@example.test", "A"), ("b@example.test", "B"), ("junk", "")],
        consent_note="Internal staff list, opted in at onboarding",
        confirmed=True,
        actor=owner,
    )
    assert stats == {"created": 2, "existing": 0, "skipped": 1}
    assert service.audience(newsletter_blog).count() == 2


def test_importing_refuses_a_blog_you_do_not_own(other_blog, owner):
    with pytest.raises(service.NotAuthorized):
        service.import_subscribers(
            other_blog, [("a@example.test", "")], consent_note="x", actor=owner
        )


# ── Operator-side opt-out ───────────────────────────────────────────────────


def test_an_operator_can_unsubscribe_an_address(newsletter_blog, pending, owner):
    assert service.unsubscribe_email(newsletter_blog, "reader@example.test", actor=owner) == 1
    pending.refresh_from_db()
    assert pending.status == Subscription.Status.UNSUBSCRIBED


def test_suppression_is_global_and_reversible(pending):
    sub = service.suppress_subscriber(pending.subscriber, reason="550 unknown user")
    assert sub.is_suppressed
    assert sub.bounce_count == 1

    sub = service.unsuppress_subscriber(sub)
    assert not sub.is_suppressed
    assert sub.consecutive_failures == 0


def test_a_members_blog_subscribe_page_redirects_anonymous(client, members_blog):
    members_blog.newsletter_enabled = True
    members_blog.save(update_fields=["newsletter_enabled"])
    response = client.get(f"/blog/{members_blog.slug}/subscribe/")
    assert response.status_code == 302
    assert "/login" in response.url


def test_blog_visibility_still_gates_the_newsletter_archive(client, private_blog):
    """Closed anonymously, and indistinguishable from an unknown slug."""
    response = client.get(f"/blog/{private_blog.slug}/newsletter/")

    assert response.status_code == 302
    assert "/login" in response["Location"]
    assert client.get("/blog/no-such-slug/newsletter/").status_code == response.status_code
