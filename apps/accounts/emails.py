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
       documented email knob);
    2. a URL-shaped ``SITE_URL`` / ``SMALLSTACK_SITE_URL`` / ``BASE_URL`` —
       the knobs the webhook origin chain already accepts, so a deployment
       that configured its host once for webhooks gets working email links
       without learning a second variable;
    3. the ``SITE_DOMAIN`` default (``localhost:8000``) — dev.
    """
    domain = str(getattr(settings, "SITE_DOMAIN", "") or "")
    proto = "https" if getattr(settings, "USE_HTTPS", False) else "http"
    if domain.split("/")[0].split(":")[0].lower() not in _LOCAL_HOSTS:
        return f"{proto}://{domain}"
    for name in ("SITE_URL", "SMALLSTACK_SITE_URL", "BASE_URL"):
        url = str(getattr(settings, name, "") or "").rstrip("/")
        if url.startswith(("http://", "https://")):
            return url
    return f"{proto}://{domain or 'localhost:8000'}"


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


def send_branded_email(*, subject, template, context, to, request=None) -> int:
    """Render ``template`` (HTML) + its ``.txt`` sibling and send a multipart
    email with the brand context already mixed in. Sent synchronously so the
    console backend shows it immediately and no worker is required.
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
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=recipients,
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
