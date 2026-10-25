# activity — request tracking

`ActivityMiddleware` records each HTTP request to the `RequestLog` table (path, matched
`route`, status, user, timing, IP, agent). The staff pages at `/smallstack/activity/`
show the traffic by time window: a dashboard, the request log (with a probing/noise
warning area), per-user and per-resource drilldowns. Pruning is handled by the
`prune_activity` management command.

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `middleware.py`, `models.py` (`RequestLog`), `services.py` (windows,
summaries, roll-ups, probe classifier), `views.py`, `admin.py`,
`management/commands/prune_activity.py`. **URL:** `/smallstack/activity/`.

**See:** [`../../docs/skills/activity-tracking.md`](../../docs/skills/activity-tracking.md) ·
[`../../docs/skills/logging-audit.md`](../../docs/skills/logging-audit.md).
