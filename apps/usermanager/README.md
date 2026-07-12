# usermanager — staff user administration

Staff-only CRUD over the User model: create-with-password, edit, activate/deactivate, timezone
tools, with guardrails (e.g. can't delete the last superuser).

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `views.py`, `forms.py`, `timezone_views.py`.
**URL:** `/smallstack/manage/users/`.

**See:** [`../../docs/skills/user-management.md`](../../docs/skills/user-management.md).
