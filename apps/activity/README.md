# activity — request tracking

`ActivityMiddleware` records each HTTP request to the `RequestLog` table; the admin surfaces
recent traffic. Pruning is handled by the `prune_activity` management command.

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `middleware.py`, `models.py` (`RequestLog`), `views.py`, `admin.py`,
`management/commands/prune_activity.py`. **URL:** `/smallstack/activity/`.

**See:** [`../../docs/skills/activity-tracking.md`](../../docs/skills/activity-tracking.md) ·
[`../../docs/skills/logging-audit.md`](../../docs/skills/logging-audit.md).
