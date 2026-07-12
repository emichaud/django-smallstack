# profile — UserProfile + preferences

Per-user profile with theme/palette and timezone preferences, auto-created via a `post_save`
signal on the User model.

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `models.py` (`UserProfile`), `views.py` (theme/palette POST endpoints),
`signals.py` (auto-create), `forms.py`.

**See:** [`../../docs/skills/theming-system.md`](../../docs/skills/theming-system.md) ·
[`../../docs/skills/timezones.md`](../../docs/skills/timezones.md).
