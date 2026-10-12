"""Outbound mail for the newsletter.

Two kinds, and they behave differently on purpose:

* **Transactional** (confirm, welcome, unsubscribe receipt) — one message,
  sent inline, best-effort. A mail failure must never break the signup that
  triggered it, so everything here swallows and logs rather than raising.
* **Issue delivery** — built, not sent, by :func:`build_issue_message`. The
  send pipeline owns the connection and the retry policy, because a blast
  needs one SMTP connection per *batch* rather than per message, and needs to
  record the outcome of each recipient.

Every issue message carries ``List-Unsubscribe`` and
``List-Unsubscribe-Post``. Those two headers are what make the one-click
unsubscribe button appear in Gmail and Yahoo, and bulk senders are now
expected to have them.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from apps.accounts.emails import email_brand_context, send_branded_email, site_base_url
from apps.smallstack.transforms import render_markdown

from . import tokens
from .models import Blog, Delivery, Issue, Subscription, issue_body_source

logger = logging.getLogger("smallstack.blog")


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def _absolute(path: str) -> str:
    return f"{site_base_url().rstrip('/')}{path}"


def confirm_url(subscription: Subscription) -> str:
    from django.urls import reverse

    return _absolute(
        reverse("blog:confirm", kwargs={"token": tokens.make_confirm_token(subscription)})
    )


def unsubscribe_url(subscription: Subscription) -> str:
    from django.urls import reverse

    return _absolute(
        reverse(
            "blog:unsubscribe",
            kwargs={"token": tokens.make_unsubscribe_token(subscription)},
        )
    )


def blog_url(blog: Blog) -> str:
    try:
        return _absolute(blog.get_absolute_url())
    except Exception:  # noqa: BLE001 — public surface may be disabled
        return site_base_url()


# ---------------------------------------------------------------------------
# Sender identity
# ---------------------------------------------------------------------------


def from_email_for(blog: Blog) -> str | None:
    """A display name for the blog over the configured From address.

    Only the display name is per-blog: the address itself stays the
    deployment's ``DEFAULT_FROM_EMAIL`` because that is the domain SPF/DKIM
    are aligned to. Letting a blog owner choose the address would silently
    destroy deliverability.
    """
    default = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    name = (blog.newsletter_from_name or "").strip()
    if not name or not default:
        return default
    address = default.split("<")[-1].strip(" <>") if "<" in default else default
    return f"{name} <{address}>"


def list_headers(subscription: Subscription, *, issue: Issue | None = None) -> dict[str, str]:
    """The headers that make bulk mail behave.

    ``List-Unsubscribe`` must put the HTTPS URL **first** — that is the one
    Gmail reads for its one-click button — with the ``mailto:`` as a fallback.
    ``List-Unsubscribe-Post`` is what signals RFC 8058 one-click support; the
    receiving provider then POSTs the URL directly, with no session and no
    CSRF token, which is why that view is ``@csrf_exempt`` and authenticated
    by the signed token instead.

    ``Precedence: bulk`` + ``Auto-Submitted`` stop vacation auto-responders
    replying to every recipient.
    """
    unsub = unsubscribe_url(subscription)
    host = site_base_url().split("//", 1)[-1].split("/")[0]
    reply_to = subscription.blog.newsletter_reply_to or getattr(
        settings, "DEFAULT_FROM_EMAIL", ""
    )
    headers = {
        "List-Unsubscribe": f"<{unsub}>, <mailto:{reply_to}?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "List-ID": f'"{subscription.blog.name}" <{subscription.blog.slug}.blog.{host}>',
        "Precedence": "bulk",
        "Auto-Submitted": "auto-generated",
    }
    if issue is not None:
        headers["Message-ID"] = f"<{issue.uid}.{subscription.pk}@{host}>"
        headers["X-SmallStack-Issue"] = str(issue.uid)
    return headers


# ---------------------------------------------------------------------------
# Transactional
# ---------------------------------------------------------------------------


def _context(subscription: Subscription, **extra: Any) -> dict[str, Any]:
    ctx = {
        "blog": subscription.blog,
        "subscriber": subscription.subscriber,
        "blog_url": blog_url(subscription.blog),
        "unsubscribe_url": unsubscribe_url(subscription),
    }
    ctx.update(extra)
    return ctx


def _send(subject: str, template: str, context: dict[str, Any], to: str) -> int:
    """Best-effort transactional send. Never raises."""
    if not getattr(settings, "SMALLSTACK_BLOG_ENABLED", True):
        return 0
    try:
        return send_branded_email(subject=subject, template=template, context=context, to=to)
    except Exception:  # noqa: BLE001 — mail must not break the signup
        logger.exception("blog: failed to send %s to %s", template, to)
        return 0


def send_confirmation(subscription: Subscription) -> int:
    """Ask a new subscriber to confirm. The double-opt-in step."""
    return _send(
        subject=f"Confirm your subscription to {subscription.blog.name}",
        template="blog/email/confirm.html",
        context=_context(subscription, confirm_url=confirm_url(subscription)),
        to=subscription.subscriber.email,
    )


def send_welcome(subscription: Subscription) -> int:
    return _send(
        subject=f"You're subscribed to {subscription.blog.name}",
        template="blog/email/welcome.html",
        context=_context(subscription),
        to=subscription.subscriber.email,
    )


# ---------------------------------------------------------------------------
# Issue delivery
# ---------------------------------------------------------------------------


def render_issue_html(issue: Issue, subscription: Subscription) -> tuple[str, str]:
    """``(html, text)`` for one recipient's copy of an issue.

    The body comes from ``issue.body_html`` — the snapshot frozen when the
    issue was queued — so editing the post afterwards cannot change what a
    subscriber already received, and every recipient in a send gets byte-identical
    content regardless of how long the send takes.
    """
    blog = issue.blog
    footer_html = ""
    if blog.newsletter_footer_markdown:
        footer_html = render_markdown(blog.newsletter_footer_markdown, toc=False)["html"]

    context = email_brand_context(
        issue=issue,
        blog=blog,
        subscriber=subscription.subscriber,
        body_html=issue.body_html,
        # The markdown source doubles as the plaintext part. Not ideal
        # typography, but it is the author's own words rather than a
        # tag-stripped approximation of the HTML, and it stays readable.
        body_markdown_text=issue_body_source(issue),
        footer_markdown=blog.newsletter_footer_markdown,
        footer_html=footer_html,
        blog_url=blog_url(blog),
        unsubscribe_url=unsubscribe_url(subscription),
        preheader=issue.preheader,
    )

    template = f"blog/email/newsletter_{blog.email_template}.html" if blog.email_template else ""
    html = ""
    if template:
        # Per-blog branded shell when one exists, generic wrapper otherwise —
        # the slug-with-fallback pattern, so a blog can be styled without any
        # configuration and without forking the default.
        try:
            html = render_to_string(template, context)
        except Exception:  # noqa: BLE001
            logger.warning("blog: email template %s failed; using the default", template)
    if not html:
        html = render_to_string("blog/email/newsletter.html", context)

    text = render_to_string("blog/email/newsletter.txt", context)
    return html, text


def build_issue_message(
    issue: Issue,
    delivery: Delivery,
    subscription: Subscription,
    *,
    connection: Any = None,
) -> EmailMultiAlternatives:
    """One recipient's message, ready to send on a caller-owned connection."""
    html, text = render_issue_html(issue, subscription)
    reply_to = issue.blog.newsletter_reply_to
    message = EmailMultiAlternatives(
        subject=issue.subject,
        body=text,
        from_email=from_email_for(issue.blog),
        to=[delivery.email],
        reply_to=[reply_to] if reply_to else None,
        connection=connection,
        headers=list_headers(subscription, issue=issue),
    )
    message.attach_alternative(html, "text/html")
    return message


def send_test_copy(issue: Issue, to: str, subscription: Subscription) -> int:
    """Send one preview copy. Writes no Delivery row — a test send must never
    appear in the ledger that drives resumability."""
    html, text = render_issue_html(issue, subscription)
    try:
        message = EmailMultiAlternatives(
            subject=f"[Test] {issue.subject}",
            body=text,
            from_email=from_email_for(issue.blog),
            to=[to],
            headers=list_headers(subscription, issue=issue),
        )
        message.attach_alternative(html, "text/html")
        return message.send()
    except Exception:  # noqa: BLE001
        logger.exception("blog: test send failed for issue %s", issue.pk)
        return 0


def issue_markdown(issue: Issue) -> str:
    """The markdown an issue renders from — its own, else its post's."""
    return issue_body_source(issue)
