"""Auth-flow tests for the accounts app — currently the password-reset email.

Covers the previously-untested email surface (Audit L6) and the L4/L5 fixes:
the reset email must carry a branded HTML alternative and sign off with
SITE_NAME rather than the raw request host.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_password_reset_sends_html_alternative_and_site_name():
    User = get_user_model()
    User.objects.create_user(username="reset_me", email="reset@example.com", password="pw")

    resp = Client().post(reverse("password_reset"), {"email": "reset@example.com"})
    assert resp.status_code == 302  # redirect to password_reset_done

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]

    # L5: the sign-off uses SITE_NAME, not the raw request host (the body still
    # contains the host inside the reset *link* — that's expected).
    assert "The SmallStack Team" in msg.body

    # L4: a text/html alternative is attached (branded HTML email actually sent).
    html_parts = [content for content, mimetype in msg.alternatives if mimetype == "text/html"]
    assert html_parts, "expected an HTML alternative on the reset email"
    assert "SmallStack" in html_parts[0]


def test_password_reset_unknown_email_still_redirects_no_send():
    """No account enumeration: unknown emails get the same redirect, no mail."""
    resp = Client().post(reverse("password_reset"), {"email": "nobody@example.com"})
    assert resp.status_code == 302
    assert len(mail.outbox) == 0
