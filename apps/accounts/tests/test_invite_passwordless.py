"""Tests for invite-by-email, passwordless code login, and email login.

These exercise the auth flows added for 1.0 and would have caught the
passwordless-create blocker (a created user must be able to log in) and the
no-account-enumeration requirement. Email is captured in mail.outbox (locmem).
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff(db):
    return User.objects.create_user("boss", email="boss@acme.com", password="pw", is_staff=True)


def _accept_url(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return reverse("accounts:invite_accept", kwargs={"uidb64": uid, "token": token})


# ── Invite ──────────────────────────────────────────────────────────────────
class TestInvite:
    def test_requires_staff(self, client):
        # Anonymous is redirected to login; the action is staff-gated.
        resp = client.get(reverse("accounts:invite"))
        assert resp.status_code in (302, 403)

    def test_creates_passwordless_user_and_emails_link(self, client, staff):
        client.force_login(staff)
        resp = client.post(
            reverse("accounts:invite"), {"email": "new@acme.com", "first_name": "New"}
        )
        assert resp.status_code == 302
        user = User.objects.get(email="new@acme.com")
        assert user.first_name == "New"
        assert not user.has_usable_password()  # they set it via the link
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["new@acme.com"]
        assert "invited" in mail.outbox[0].subject.lower()

    def test_rejects_duplicate_email(self, client, staff):
        User.objects.create_user("dup", email="dup@acme.com", password="pw")
        client.force_login(staff)
        resp = client.post(reverse("accounts:invite"), {"email": "dup@acme.com"})
        assert resp.status_code == 200  # re-render with form error
        assert User.objects.filter(email__iexact="dup@acme.com").count() == 1
        assert len(mail.outbox) == 0

    def test_accept_sets_password_and_logs_in(self, client):
        user = User.objects.create_user("invitee", email="i@acme.com")
        user.set_unusable_password()
        user.save()
        url = _accept_url(user)
        assert client.get(url).status_code == 200
        resp = client.post(url, {"new_password1": "Str0ng!pass99", "new_password2": "Str0ng!pass99"})
        assert resp.status_code == 302
        user.refresh_from_db()
        assert user.has_usable_password()
        assert user.check_password("Str0ng!pass99")
        assert "_auth_user_id" in client.session  # auto-logged-in

    def test_accept_invalid_token_rejected(self, client):
        user = User.objects.create_user("invitee2", email="i2@acme.com")
        user.set_unusable_password()
        user.save()
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        url = reverse("accounts:invite_accept", kwargs={"uidb64": uid, "token": "bad-token"})
        resp = client.post(url, {"new_password1": "Str0ng!pass99", "new_password2": "Str0ng!pass99"})
        assert resp.status_code == 200
        user.refresh_from_db()
        assert not user.has_usable_password()  # nothing was set
        assert "_auth_user_id" not in client.session


# ── Passwordless ("email me a code") ─────────────────────────────────────────
class TestPasswordless:
    def test_disabled_returns_404(self, client, settings):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = False
        assert client.get(reverse("accounts:passwordless_login")).status_code == 404

    def test_request_then_verify_logs_in(self, client, settings):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        User.objects.create_user("coder", email="coder@acme.com", password="pw")
        resp = client.post(
            reverse("accounts:passwordless_login"), {"action": "request", "email": "coder@acme.com"}
        )
        assert resp.status_code == 200
        assert len(mail.outbox) == 1
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].subject + mail.outbox[0].body).group(1)
        resp2 = client.post(
            reverse("accounts:passwordless_login"), {"action": "verify", "code": code}
        )
        assert resp2.status_code == 302
        assert "_auth_user_id" in client.session

    def test_wrong_code_rejected(self, client, settings):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        User.objects.create_user("coder2", email="c2@acme.com", password="pw")
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "c2@acme.com"})
        resp = client.post(reverse("accounts:passwordless_login"), {"action": "verify", "code": "000000"})
        assert resp.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_no_account_enumeration(self, client, settings):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        resp = client.post(
            reverse("accounts:passwordless_login"), {"action": "request", "email": "ghost@acme.com"}
        )
        assert resp.status_code == 200  # same code-entry screen as a real address
        assert len(mail.outbox) == 0  # but nothing is sent


# ── Username-or-email login ──────────────────────────────────────────────────
class TestEmailLogin:
    def test_login_with_email(self, client):
        User.objects.create_user("jane", email="jane@acme.com", password="Secret!123")
        assert client.login(username="jane@acme.com", password="Secret!123")
        assert "_auth_user_id" in client.session

    def test_login_with_username_still_works(self, client):
        User.objects.create_user("jane2", email="jane2@acme.com", password="Secret!123")
        assert client.login(username="jane2", password="Secret!123")

    def test_wrong_password_fails(self, client):
        User.objects.create_user("jane3", email="jane3@acme.com", password="Secret!123")
        assert not client.login(username="jane3@acme.com", password="nope")
