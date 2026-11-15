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
    from django.contrib.auth.models import Permission

    # Inviting needs accounts.add_user (G2-1), like the User Manager's create page.
    user = User.objects.create_user("boss", email="boss@acme.com", password="pw", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="add_user"))
    return user


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

    def test_correct_code_after_attempts_exhausted_is_refused(self, client, settings):
        """The attempt budget is spent atomically before the check (audit H3)."""
        from apps.accounts.models import LoginCode

        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        user = User.objects.create_user("coder3", email="c3@acme.com", password="pw")
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "c3@acme.com"})
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].subject).group(1)
        LoginCode.objects.filter(user=user).update(attempts=LoginCode.MAX_ATTEMPTS)
        client.post(reverse("accounts:passwordless_login"), {"action": "verify", "code": code})
        assert "_auth_user_id" not in client.session

    def test_codes_per_hour_are_capped(self, client, settings):
        """Re-requesting every minute must not mint unlimited codes (audit H3)."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import LoginCode

        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        settings.SMALLSTACK_LOGIN_CODES_PER_HOUR = 2
        user = User.objects.create_user("coder4", email="c4@acme.com", password="pw")
        for _ in range(4):
            client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "c4@acme.com"})
            # step past the 60 s resend throttle
            LoginCode.objects.filter(user=user).update(created_at=timezone.now() - timedelta(minutes=2))
        assert LoginCode.objects.filter(user=user).count() == 2
        assert len(mail.outbox) == 2


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


# ── Queued delivery: secrets never ride the task queue ───────────────────────
class _Captured:
    """Stands in for a Task: records what would have been stored as its args."""

    def __init__(self):
        self.calls = []

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))


@pytest.fixture
def queued(monkeypatch, settings):
    """Force the queued path and capture each account task's arguments."""
    from apps.accounts import tasks

    settings.SMALLSTACK_ACCOUNTS_EMAILS_INLINE = False
    captured = {"invite": _Captured(), "code": _Captured()}
    monkeypatch.setattr(tasks, "send_invite_email_task", captured["invite"])
    monkeypatch.setattr(tasks, "send_login_code_task", captured["code"])
    return captured


class TestQueuedAccountEmails:
    def test_login_code_args_carry_no_code_and_the_worker_send_logs_in(self, client, settings, queued):
        from apps.accounts.emails import send_login_code_now
        from apps.accounts.models import LoginCode

        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        user = User.objects.create_user("q1", email="q1@acme.com", password="pw")
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "q1@acme.com"})

        assert len(mail.outbox) == 0  # queued, not sent in the request
        (args, kwargs), = queued["code"].calls
        lc = LoginCode.objects.get(user=user)
        assert args == (lc.pk, "http://testserver") and kwargs == {}

        assert send_login_code_now(*args) == 1  # what the worker runs
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].subject).group(1)
        assert str(code) not in repr(args)
        resp = client.post(reverse("accounts:passwordless_login"), {"action": "verify", "code": code})
        assert resp.status_code == 302

    def test_throttle_counts_a_queued_code_before_it_is_sent(self, client, settings, queued):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        User.objects.create_user("q2", email="q2@acme.com", password="pw")
        for _ in range(2):
            client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "q2@acme.com"})
        assert len(queued["code"].calls) == 1  # the 60s resend throttle saw the first row

    def test_invite_args_carry_no_token_and_the_worker_link_works(self, client, staff, queued):
        from apps.accounts.emails import send_invite_now

        client.force_login(staff)
        client.post(reverse("accounts:invite"), {"email": "qi@acme.com"})
        user = User.objects.get(email="qi@acme.com")

        assert len(mail.outbox) == 0
        (args, _), = queued["invite"].calls
        assert args[0] == user.pk and args[2] == "http://testserver"
        assert default_token_generator.make_token(user) not in repr(args)

        assert send_invite_now(*args) == 1
        link = _accept_url(user)
        assert "http://testserver" + link in mail.outbox[0].body
        assert client.get(link).status_code == 200

    def test_spent_code_sends_nothing(self):
        from apps.accounts.emails import send_login_code_now
        from apps.accounts.models import LoginCode

        user = User.objects.create_user("q3", email="q3@acme.com", password="pw")
        lc, _ = LoginCode.issue(user)
        LoginCode.objects.filter(pk=lc.pk).update(consumed=True)
        assert send_login_code_now(lc.pk, "http://testserver") == 0
        assert len(mail.outbox) == 0

    def test_inline_setting_sends_in_the_request(self, client, settings, queued):
        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        settings.SMALLSTACK_ACCOUNTS_EMAILS_INLINE = True
        User.objects.create_user("q4", email="q4@acme.com", password="pw")
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "q4@acme.com"})
        assert queued["code"].calls == []
        assert len(mail.outbox) == 1

    def test_unset_inline_follows_debug(self, settings):
        from apps.accounts.emails import account_emails_inline

        settings.SMALLSTACK_ACCOUNTS_EMAILS_INLINE = None
        settings.DEBUG = True
        assert account_emails_inline() is True
        settings.DEBUG = False
        assert account_emails_inline() is False

    def test_no_queue_falls_back_to_sending_inline(self, client, settings, monkeypatch):
        from apps.accounts import tasks

        class Broken:
            name = "broken"

            def enqueue(self, *a, **k):
                raise RuntimeError("no task backend")

        settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
        settings.SMALLSTACK_ACCOUNTS_EMAILS_INLINE = False
        monkeypatch.setattr(tasks, "send_login_code_task", Broken())
        User.objects.create_user("q5", email="q5@acme.com", password="pw")
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "q5@acme.com"})
        assert len(mail.outbox) == 1


def _setting_in_fresh_process(env_extra: dict[str, str], expr: str) -> str:
    """Evaluate ``expr`` after settings load in a new process with ``env_extra``:
    an env var only reaches settings at import, which override_settings can't show."""
    import os
    import subprocess
    import sys

    code = f"import django; django.setup(); from django.conf import settings; print(repr({expr}))"
    env = {**os.environ, **env_extra, "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    return out.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize(("raw", "expected"), [("True", "True"), ("false", "False"), ("", "None")])
def test_emails_inline_is_read_from_the_environment(raw, expected):
    # UPGRADING tells a deployment with no email worker to set this env var;
    # it used to be read only from settings, so the env var did nothing.
    assert _setting_in_fresh_process(
        {"SMALLSTACK_ACCOUNTS_EMAILS_INLINE": raw}, "settings.SMALLSTACK_ACCOUNTS_EMAILS_INLINE"
    ) == expected


def test_an_empty_email_timeout_is_the_default_not_a_crash():
    from config.settings._email import build_mailers  # noqa: F401  (imported in the child)

    got = _setting_in_fresh_process(
        {"EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend", "EMAIL_TIMEOUT": ""},
        "__import__('config.settings._email', fromlist=['x']).build_mailers()['default']['OPTIONS'].get('timeout')",
    )
    assert got == "10"
