"""The public subscriber lifecycle: subscribe, confirm, unsubscribe.

**GET shows, POST acts.** Every mutating step is a POST behind a page with a
button. A GET that unsubscribes is triggered by link prefetchers, corporate
mail scanners and "open all links" extensions — people get silently removed
from lists they never left.

**The unsubscribe POST is `@csrf_exempt`, deliberately.** RFC 8058 one-click
arrives from Gmail/Yahoo infrastructure with no session and no CSRF token; a
`@csrf_protect` view answers 403 and the unsubscribe button in the mail client
silently does nothing. The signed token *is* the credential — same reasoning
as the inbound webhook receiver in config/urls.py. The confirm POST keeps CSRF
because it is always submitted from a page we rendered.

**The subscribe form never varies its response** on whether the address is
already subscribed. Doing so turns it into a membership oracle for any
address an attacker wants to test.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import service, tokens
from .models import Blog
from .public_views import _base_context, _MembersOnly, _visible_blog, public_surface_enabled


def _gate() -> None:
    from django.http import Http404

    if not public_surface_enabled():
        raise Http404("The public blog is disabled.")


def _render(request: HttpRequest, template: str, **ctx: Any) -> HttpResponse:
    return render(request, template, _base_context(request, **ctx))


@require_http_methods(["GET", "POST"])
def subscribe(request: HttpRequest, blog_slug: str) -> HttpResponse:
    """`/blog/<slug>/subscribe/` — the signup form."""
    _gate()
    try:
        blog = _visible_blog(request, blog_slug)
    except _MembersOnly:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())

    if not blog.newsletter_enabled:
        from django.http import Http404

        raise Http404("This blog has no newsletter.")

    if request.method == "GET":
        return _render(request, "blog/public/subscribe.html", blog=blog)

    email = (request.POST.get("email") or "").strip()
    name = (request.POST.get("name") or "").strip()

    # A honeypot: a field a human never sees and a naive bot always fills.
    if (request.POST.get("website") or "").strip():
        return _render(request, "blog/public/subscribe_sent.html", blog=blog, email=email)

    error = ""
    try:
        service.subscribe(blog, email, name=name, source="web")
    except service.InvalidState as exc:
        error = str(exc)
    except service.BlogServiceError:
        # Anything else — including "the newsletter is off" — is reported as
        # the same neutral confirmation. The alternative leaks list state.
        pass

    if error:
        return _render(request, "blog/public/subscribe.html", blog=blog, error=error, email=email)
    return _render(request, "blog/public/subscribe_sent.html", blog=blog, email=email)


@require_http_methods(["GET", "POST"])
def confirm(request: HttpRequest, token: str) -> HttpResponse:
    """`/blog/subscribe/confirm/<token>/` — GET shows a button, POST confirms."""
    _gate()
    try:
        subscription = tokens.read_confirm_token(token)
    except tokens.InvalidToken as exc:
        return _render(
            request, "blog/public/token_invalid.html", reason=str(exc), kind="confirm"
        )

    if request.method == "GET":
        return _render(
            request, "blog/public/confirm.html", subscription=subscription,
            blog=subscription.blog, token=token,
        )

    subscription = service.confirm_subscription(token)
    return _render(
        request, "blog/public/confirmed.html", subscription=subscription,
        blog=subscription.blog,
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def unsubscribe(request: HttpRequest, token: str) -> HttpResponse:
    """`/blog/unsubscribe/<token>/`.

    ``@csrf_exempt`` is load-bearing — see the module docstring. The GET is
    still a page with a button, so a prefetch cannot unsubscribe anyone; only
    a deliberate POST (from the page, or from a mail provider's one-click
    infrastructure) does.
    """
    _gate()
    try:
        subscription = tokens.read_unsubscribe_token(token)
    except tokens.InvalidToken as exc:
        return _render(
            request, "blog/public/token_invalid.html", reason=str(exc), kind="unsubscribe"
        )

    if request.method == "GET":
        return _render(
            request, "blog/public/unsubscribe.html", subscription=subscription,
            blog=subscription.blog, token=token,
        )

    subscription = service.unsubscribe(token, reason="one-click")
    return _render(
        request, "blog/public/unsubscribed.html", subscription=subscription,
        blog=subscription.blog,
    )


def newsletter_archive(request: HttpRequest, blog_slug: str) -> HttpResponse:
    """`/blog/<slug>/newsletter/` — past issues. Sent ones only."""
    from .models import Issue

    _gate()
    try:
        blog = _visible_blog(request, blog_slug)
    except _MembersOnly:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())

    issues = Issue.objects.filter(blog=blog, status=Issue.Status.SENT).order_by("-finished_at")
    return _render(request, "blog/public/issue_archive.html", blog=blog, issues=issues)


def newsletter_issue(request: HttpRequest, blog_slug: str, issue_uid: str) -> HttpResponse:
    """`/blog/<slug>/newsletter/<uid>/` — "view this in your browser"."""
    from django.shortcuts import get_object_or_404

    from .models import Issue

    _gate()
    try:
        blog = _visible_blog(request, blog_slug)
    except _MembersOnly:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())

    issue = get_object_or_404(
        Issue.objects.filter(blog=blog, status=Issue.Status.SENT), uid=issue_uid
    )
    return _render(request, "blog/public/issue_detail.html", blog=blog, issue=issue)


def blog_has_newsletter(blog: Blog) -> bool:
    return bool(blog.newsletter_enabled)
