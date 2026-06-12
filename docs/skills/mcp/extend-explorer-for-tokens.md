# Skill: Surface APIToken management via Explorer

## When to use this skill
Users need a UI to browse and revoke API tokens without going through Django admin.

## What's already there

`apps/smallstack/admin.py` registers `APITokenAdmin` with `explorer_enabled = True` and `explorer_group = "Auth"`. The bulk admin action "Revoke selected tokens" is wired up. The OAuth consent page (`apps/mcp/templates/mcp/authorize.html`) links to `/explorer/auth/apitoken/` so users know where to manage tokens later.

## If Explorer isn't surfacing APIToken

Check:

1. `apps.smallstack.admin` is imported at startup (it lives in `apps/smallstack/admin.py`, which Django autodiscovers as long as `apps.smallstack` is in `INSTALLED_APPS`).

2. Explorer is in `INSTALLED_APPS` AFTER `django.contrib.admin` (it reads `admin.site._registry`).

3. Explorer autodiscovery is enabled. Look in `apps/explorer/registry.py` and the project's `explorer.py` files.

## Customize the columns

Edit `APITokenAdmin.explorer_list_fields`:

```python
explorer_list_fields = ("name", "user", "token_type", "access_level", "is_active")
```

UI-only — doesn't affect the API or admin views.

## Customize the revoke action

The current bulk action is in `APITokenAdmin.revoke_tokens`. If you want per-row revoke (link in the row, not bulk), add an explorer row action — see how other Explorer-enabled admins handle per-row actions in your project.

## What NOT to do

- Don't add a separate token management UI in `apps/usermanager` or similar. Explorer is the canonical surface, kept identical for all token sources (manual, login, OAuth).
- Don't expose `hashed_key` or `prefix` in editable form fields. They're readonly_fields for a reason.
- Don't mint tokens via Explorer's create action — use `manage.py create_api_token` or the OAuth flow so the raw key is shown exactly once and not persisted.
