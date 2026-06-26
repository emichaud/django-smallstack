# Skill: Testing (pytest, auth flows, email, CRUDView, regressions)

**Read this before writing or changing tests** — especially for auth, email, or
User-Manager / CRUDView work. It documents the test stack, the conventions, the
patterns for the hard-to-test surfaces (emails, multi-step auth, guardrails),
and the gotchas that have bitten this codebase.

## The stack

- **pytest + pytest-django** (`make test`, or `uv run pytest`).
- Settings: **`config.settings.test`** (`--ds=config.settings.test`, set in `pyproject.toml [tool.pytest.ini_options]`). It `from .base import *`, then for speed/determinism sets:
  - `EMAIL_BACKEND = locmem` → sent mail lands in `django.core.mail.outbox` (reset per test).
  - `AXES_ENABLED = False` → `client.login()` works without a request; no lockout flakiness.
  - Fast `PASSWORD_HASHERS`.
  - `AUTHENTICATION_BACKENDS` inherits base, so the `EmailOrUsernameBackend` is active in tests.
- `testpaths = ["apps"]`; test files match `test_*.py`, `*_test.py`, `tests.py`. Put tests in `apps/<app>/tests.py` or `apps/<app>/test_<area>.py`.
- Coverage is on by default (`--cov`). Add **`--no-cov`** for a fast inner loop.

```bash
make test                                   # full suite + coverage
uv run pytest apps/accounts -q --no-cov     # one app, fast
uv run pytest -k invite --no-cov            # by name
uv run pytest apps/accounts/test_invite_passwordless.py::TestInvite -q --no-cov
```

## Conventions (match these)

```python
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db        # module-level DB access
User = get_user_model()

@pytest.fixture
def staff_user(db):
    return User.objects.create_user("staff", email="s@x.com", password="pw", is_staff=True)

def test_staff_only(client, staff_user):
    client.force_login(staff_user)        # skip the login form
    assert client.get(reverse("manage/users-list")).status_code == 200
```

- `client` is pytest-django's test-client fixture. **`force_login(user)`** to authenticate without credentials; **`client.login(username=…, password=…)`** when you're testing the login path itself.
- Authenticated-but-unauthorized → **403** (StaffRequiredMixin); unauthenticated → **302** to the login URL. Use this to assert "is the session logged in":
  ```python
  assert "_auth_user_id" in client.session
  ```
- Override settings per-test with the **`settings`** fixture: `settings.SMALLSTACK_PASSWORDLESS_LOGIN = True`.

## Pattern: email flows (the whole point of locmem)

Don't scrape the dev console — read `mail.outbox`, and pull the link/code straight out to drive the next step.

```python
from django.core import mail

def test_invite_emails_a_set_password_link(client, staff_user):
    client.force_login(staff_user)
    client.post(reverse("accounts:invite"), {"email": "new@acme.com"})

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["new@acme.com"]
    html = next(c for c, t in msg.alternatives if t == "text/html")   # HTML part
    # ... assert the link / branding is present, or extract a token to POST next.
```

For **codes** (passwordless), the 6-digit code is in the subject + body:

```python
import re
code = re.search(r"\b(\d{6})\b", msg.subject + msg.body).group(1)
```

**No-enumeration tests**: an unknown email must produce the *same* response and **send nothing** — assert `len(mail.outbox) == 0`.

## Pattern: multi-step auth flows

The test client carries the session across requests, so two-step flows just work:

```python
def test_passwordless_login(client, settings):
    settings.SMALLSTACK_PASSWORDLESS_LOGIN = True
    User.objects.create_user("u", email="u@x.com", password="pw")
    client.post(reverse("accounts:passwordless_login"), {"action": "request", "email": "u@x.com"})
    code = re.search(r"\b(\d{6})\b", mail.outbox[0].subject).group(1)
    resp = client.post(reverse("accounts:passwordless_login"), {"action": "verify", "code": code})
    assert resp.status_code == 302 and "_auth_user_id" in client.session
```

**Token links** (invite accept / password reset) — build them with Django's generator instead of parsing the email when you only care about the accept step:

```python
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

uid = urlsafe_base64_encode(force_bytes(user.pk))
token = default_token_generator.make_token(user)
url = reverse("accounts:invite_accept", kwargs={"uidb64": uid, "token": token})
```

## Pattern: CRUDView management pages

A CRUDView (e.g. `UserCRUDView`) generates `{url_base}-list|create|update|delete`
URL names. Test the four operations + the staff gate:

```python
client.post(reverse("manage/users-create"), {"username": "x", "is_active": "on",
            "password1": "Cr3ate!pass99", "password2": "Cr3ate!pass99"})   # 302 on success
client.get(reverse("manage/users-update", kwargs={"pk": u.pk}))            # 200
client.post(reverse("manage/users-delete", kwargs={"pk": u.pk}))          # 302 → list
```

Unchecked checkboxes (`is_staff`, `is_active`) are **omitted** from the POST, not sent as `False`.

## Regression guards (cheap insurance)

When a refactor can silently swap behaviour, assert the wiring directly. Example —
the v0.11.19 CRUD refactor renamed the form template suffix (`form` → `create`/`edit`)
and silently dropped the User Manager's tabbed form:

```python
def test_user_form_template_is_used():
    from apps.usermanager.views import UserCRUDView
    for suffix in ("create", "edit", "form"):
        assert UserCRUDView._get_template_names(suffix) == ["accounts/user_form.html"]

def test_edit_renders_tabbed_form(client, staff_user):
    client.force_login(staff_user)
    body = client.get(reverse("manage/users-update", kwargs={"pk": staff_user.pk})).content.decode()
    assert "user-tabs" in body            # not the generic CRUD form
```

## Gotchas (these have caused real bugs here)

1. **`form.is_valid()` mutates the model instance.** A `ModelForm`'s `is_valid()`
   runs `construct_instance`, copying cleaned data onto `form.instance` (= the
   view's `self.object`). Any guard that reads "the old value" must capture it
   **before** validating, or it compares new-vs-new:
   ```python
   self.object = self.get_object()
   was_staff = self.object.is_staff          # capture BEFORE get_form()/is_valid()
   ```
2. **Django 5+/6 `DeleteView` doesn't call `delete()` on POST** — it routes through
   `FormMixin.form_valid()`. Guard deletes by overriding **`post()`**, and test the
   guard via a `client.post(...delete...)` returning 403 (overriding `delete()`
   alone is a silent no-op — exactly how an old self-delete guard broke).
3. **`mail.outbox` is per-test**, auto-reset by pytest-django. Assert `len(...)`
   rather than clearing it yourself.
4. **`client.login()` needs axes off** (it is, in test settings) because the axes
   backend wants a request. For unauthenticated-flow tests, `force_login` sidesteps it.
5. **Settings read at import time** (e.g. feature flags pulled into module-level
   constants) won't pick up the `settings` fixture. The auth views read flags at
   request time via `getattr(settings, ...)`, so `settings.SMALLSTACK_PASSWORDLESS_LOGIN = True`
   works — but if you add a flag, read it inside the view/dispatch, not at import.

## Where to look

- `apps/accounts/test_invite_passwordless.py` — invite, passwordless, email login.
- `apps/accounts/tests.py` — password-reset email (HTML alternative, no enumeration).
- `apps/usermanager/tests.py` — CRUD, create-with-password, guardrails, account actions, the tabbed-form regression guard.
- `conftest.py` (root) — session-scoped DB setup for the MCP test-only tables.

## Related skills

- `authentication.md` — the auth surfaces these tests cover.
- `user-management.md` — the User Manager / CRUDView under test.
- `background-tasks.md` — testing tasks (use `locmem` + run the task inline).
