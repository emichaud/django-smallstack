"""Account events reach the log: sign-in and out, failed sign-ins, sign-ups,
invites, sign-in codes and password resets.

Each line names the account by username and pk. None carries a password, a
sign-in code or a reset token: the tests check that too.
"""

from __future__ import annotations

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
PASSWORD = "Str0ng!pass99"
LOGGERS = ("apps.accounts.signals", "apps.accounts.views")


@pytest.fixture
def logged(caplog):
    for name in LOGGERS:
        caplog.set_level("INFO", logger=name)

    def messages() -> list[str]:
        return [r.getMessage() for r in caplog.records if r.name in LOGGERS]

    return messages


def test_sign_in_failure_and_sign_out(client, logged):
    user = User.objects.create_user("ada", password=PASSWORD)
    client.post(reverse("login"), {"username": "ada", "password": "wrong-one"})
    client.post(reverse("login"), {"username": "ada", "password": PASSWORD})
    client.post(reverse("logout"))
    lines = logged()
    assert "accounts: sign-in failed for 'ada'" in lines
    assert f"accounts: ada (pk={user.pk}) signed in" in lines
    assert f"accounts: ada (pk={user.pk}) signed out" in lines
    assert not any(PASSWORD in line or "wrong-one" in line for line in lines)


def test_sign_up(client, logged):
    client.post(reverse("signup"), {"username": "newbie", "password1": PASSWORD, "password2": PASSWORD})
    user = User.objects.get(username="newbie")
    assert f"accounts: newbie (pk={user.pk}) signed up" in logged()


def test_invite_sent_and_accepted(client, logged):
    from django.contrib.auth.models import Permission

    staff = User.objects.create_user("boss", password=PASSWORD, is_staff=True)
    staff.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="add_user"))
    client.force_login(staff)
    client.post(reverse("accounts:invite"), {"email": "new@acme.com"})
    invited = User.objects.get(email="new@acme.com")
    assert any(f"boss invited {invited.get_username()} (pk={invited.pk}" in line for line in logged())
    client.logout()
    uid = urlsafe_base64_encode(force_bytes(invited.pk))
    token = default_token_generator.make_token(invited)
    url = reverse("accounts:invite_accept", kwargs={"uidb64": uid, "token": token})
    client.post(url, {"new_password1": PASSWORD, "new_password2": PASSWORD})
    assert any("accepted an invite and set a password" in line for line in logged())
    assert not any(token in line for line in logged())


def test_sign_in_codes_issued_and_rejected(client, settings, logged):
    settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
    user = User.objects.create_user("coder", email="coder@acme.com", password=PASSWORD)
    url = reverse("accounts:passwordless_login")
    client.post(url, {"action": "request", "email": "coder@acme.com"})
    code = re.search(r"\b(\d{6})\b", mail.outbox[0].subject + mail.outbox[0].body).group(1)
    client.post(url, {"action": "verify", "code": "000000" if code != "000000" else "111111"})
    lines = logged()
    assert f"accounts: sign-in code issued for coder (pk={user.pk})" in lines
    assert f"accounts: sign-in code rejected for coder (pk={user.pk})" in lines
    assert not any(code in line for line in lines)


def test_the_hourly_code_cap_is_a_warning(client, settings, caplog):
    settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
    settings.SMALLSTACK_LOGIN_CODES_PER_HOUR = 0
    User.objects.create_user("capped", email="capped@acme.com", password=PASSWORD)
    with caplog.at_level("WARNING", logger="apps.accounts.views"):
        client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "capped@acme.com"})
    assert any("sign-in code refused for capped" in r.getMessage() for r in caplog.records)
    assert len(mail.outbox) == 0


def test_password_reset_requested_and_completed(client, logged):
    user = User.objects.create_user("forgetful", email="f@acme.com", password=PASSWORD)
    client.post(reverse("password_reset"), {"email": "f@acme.com"})
    client.post(reverse("password_reset"), {"email": "nobody@acme.com"})
    lines = logged()
    assert f"accounts: password reset requested (1 matching account: [{user.pk}])" in lines
    assert "accounts: password reset requested (0 matching accounts: [])" in lines

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    # Django swaps the token for a session key, then the form posts to set-password/.
    first = client.get(reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token}))
    client.post(first["Location"], {"new_password1": "An0ther!pass77", "new_password2": "An0ther!pass77"})
    assert f"accounts: forgetful (pk={user.pk}) reset their password" in logged()
    assert not any(token in line or "An0ther!pass77" in line for line in logged())
