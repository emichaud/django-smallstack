# accounts — custom User model + auth

The custom `AUTH_USER_MODEL`, login/signup views, passwordless invite/code login, and the
username-or-email auth backend.

**Status:** Framework-provided — don't edit in downstream forks; extend via your own app.

**Key files:** `models.py` (User + manager), `views.py`, `forms.py`,
`backends.py` (`EmailOrUsernameBackend`), `emails.py`.

**See:** [`../../docs/skills/authentication.md`](../../docs/skills/authentication.md).
