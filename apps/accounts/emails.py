"""
Branded transactional email helpers.

Emails can't use the live CSS palette (no request-time theme, and many clients
strip <style>/SVG), so branding flows through three plain values that every
SmallStack admin already controls: BRAND_NAME, BRAND_EMAIL_ACCENT, and the
site URL. All HTML emails extend ``email/base_email.html`` and read those, so
re-branding the whole mail surface is a one-setting change.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.crypto import get_random_string

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", ""}  # noqa: S104


def site_base_url() -> str:
    """Absolute ``scheme://host`` for links built OUTSIDE a request
    (signal receivers, tasks — anywhere there's no request to derive from).

    Resolution order:
    1. ``SITE_DOMAIN`` + ``USE_HTTPS`` — when set to a non-local host (the
       documented email knob). **An explicit ``https://`` in one of the
       URL-shaped settings below wins over a false ``USE_HTTPS``** — see below;
    2. a URL-shaped ``SITE_URL`` / ``SMALLSTACK_SITE_URL`` / ``BASE_URL`` —
       the knobs the webhook origin chain already accepts, so a deployment
       that configured its host once for webhooks gets working email links
       without learning a second variable;
    3. the ``SITE_DOMAIN`` default (``localhost:8000``) — dev.

    The scheme rule exists because the two knobs disagreed in a way that
    silently downgraded links. ``USE_HTTPS`` defaults to ``False``, and step 1
    used to win outright for any non-local domain — so a deployment that set
    ``SITE_DOMAIN=example.com`` *and* ``SITE_URL=https://example.com`` (exactly
    what this docstring invites, "configured its host once for webhooks") mailed
    ``http://`` unsubscribe and permalink URLs to its entire list. A setting
    that spells out a scheme is a clearer statement of intent than a boolean
    left at its default, so it now wins.
    """
    domain = str(getattr(settings, "SITE_DOMAIN", "") or "")
    proto = "https" if getattr(settings, "USE_HTTPS", False) else "http"
    explicit = _explicit_site_url()
    if domain.split("/")[0].split(":")[0].lower() not in _LOCAL_HOSTS:
        if explicit and explicit.startswith("https://") and proto == "http":
            # Only upgrade, and only when the explicit URL names the same host —
            # a stale SITE_URL pointing somewhere else must not redirect mail.
            if _host_of(explicit) == _host_of(f"//{domain}"):
                return f"https://{domain}"
        return f"{proto}://{domain}"
    if explicit:
        return explicit
    return f"{proto}://{domain or 'localhost:8000'}"


def _explicit_site_url() -> str:
    """The first URL-shaped site setting, or ``""``."""
    for name in ("SITE_URL", "SMALLSTACK_SITE_URL", "BASE_URL"):
        url = str(getattr(settings, name, "") or "").rstrip("/")
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _host_of(url: str) -> str:
    """Lower-cased ``host[:port]`` of a URL or ``//host`` fragment."""
    from urllib.parse import urlsplit

    return (urlsplit(url).netloc or "").lower()


def site_url_is_local() -> bool:
    """True when :func:`site_base_url` can only produce a dead local link —
    the condition monitors alert on in production."""
    host = site_base_url().split("//", 1)[-1].split("/")[0].split(":")[0].lower()
    return host in _LOCAL_HOSTS


def email_brand_context(request=None, **extra) -> dict:
    """Brand/site values shared by every transactional email.

    Pass ``request`` when sending from a view so links resolve to an absolute,
    correct-host URL; otherwise we fall back to SITE_DOMAIN/USE_HTTPS settings.
    """
    name = getattr(settings, "BRAND_NAME", "SmallStack")
    if request is not None:
        site_url = request.build_absolute_uri("/").rstrip("/")
    else:
        site_url = site_base_url()
    ctx = {
        "brand_name": name,
        "site_name": getattr(settings, "SITE_NAME", name),
        "brand_accent": getattr(settings, "BRAND_EMAIL_ACCENT", "#10b981"),
        "site_url": site_url,
    }
    ctx.update(extra)
    return ctx


def send_branded_email(
    *,
    subject,
    template,
    context,
    to,
    request=None,
    from_email=None,
    reply_to=None,
    headers=None,
    connection=None,
) -> int:
    """Render ``template`` (HTML) + its ``.txt`` sibling and send a multipart
    email with the brand context already mixed in. Sent synchronously so the
    console backend shows it immediately and no worker is required.

    The optional arguments exist for *bulk* senders (the newsletter), and every
    one of them defaults to the previous behaviour:

    ``from_email``
        Override ``DEFAULT_FROM_EMAIL`` — e.g. a per-publication sender name.
    ``reply_to``
        A str or list set as the ``Reply-To`` header.
    ``headers``
        Extra SMTP headers. Required for list mail: ``List-Unsubscribe`` and
        ``List-Unsubscribe-Post`` are what make Gmail/Yahoo one-click
        unsubscribe (RFC 8058) work, and they cannot be set any other way.
    ``connection``
        A backend connection to reuse. Without it every call opens its own
        SMTP connection (one TCP+TLS handshake and one AUTH *per message*),
        which is the difference between a 5,000-recipient send taking minutes
        and taking hours. Pass ``mail.get_connection(...)`` once per batch.
    """
    ctx = email_brand_context(request=request, **(context or {}))
    html_body = render_to_string(template, ctx)
    txt_template = template.rsplit(".", 1)[0] + ".txt"
    try:
        text_body = render_to_string(txt_template, ctx)
    except Exception:
        text_body = subject

    recipients = [to] if isinstance(to, str) else list(to)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=recipients,
        reply_to=[reply_to] if isinstance(reply_to, str) else (list(reply_to) if reply_to else None),
        connection=connection,
        headers=headers or None,
    )
    msg.attach_alternative(html_body, "text/html")
    return msg.send()


def unique_username_from_email(email: str) -> str:
    """Derive a unique username from an email local-part (jane@x -> jane, jane2…)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    base = (email or "").split("@", 1)[0].strip().lower() or "user"
    base = "".join(c for c in base if c.isalnum() or c in "._-") or "user"
    candidate = base[:150]
    i = 1
    while User.objects.filter(username=candidate).exists():
        i += 1
        suffix = str(i)
        candidate = f"{base[: 150 - len(suffix)]}{suffix}"
    return candidate


def generate_numeric_code(length: int = 6) -> str:
    """A numeric one-time code (zero-padded, no ambiguous leading-zero loss)."""
    return get_random_string(length, allowed_chars="0123456789")
