# tokenmgr — self-service API tokens

The user-facing UI for minting, viewing, and revoking personal API tokens (the admin/CLI path is
`create_api_token`). Owner-or-staff access enforced per token.

**Status:** Framework-provided — don't edit in downstream forks. (The `tokenmgr` label is kept
deliberately — it's baked into migrations + the URL namespace; see CONTRIBUTING.)

**Key files:** `views.py`, `mixins.py` (`is_owner_or_staff`), `forms.py`.
**URL:** `/smallstack/tokens/`.

**See:** [`../../docs/skills/manage-api-tokens.md`](../../docs/skills/manage-api-tokens.md).
