# activity — request tracking

`ActivityMiddleware` records each HTTP request to the `RequestLog` table (path, matched
`route`, status, user, timing, IP, agent). The staff pages at `/smallstack/activity/`
show the traffic by time window: a dashboard, the request log (with a probing/noise
warning area), per-user and per-resource drilldowns. Pruning is handled by the
`prune_activity` management command.

A one-time token in the path (password reset, invite, newsletter confirm/unsubscribe, or any route
parameter named `token`) is replaced with `***` before the row is written
(`apps.smallstack.redaction.redact_path`); migration `0005` redacts rows stored before that.

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `middleware.py`, `models.py` (`RequestLog`), `services.py` (windows,
summaries, roll-ups, probe classifier), `views.py`, `admin.py`,
`management/commands/prune_activity.py`. **URL:** `/smallstack/activity/`.

**See:** [`../../docs/skills/activity-tracking.md`](../../docs/skills/activity-tracking.md) ·
[`../../docs/skills/logging-audit.md`](../../docs/skills/logging-audit.md).
