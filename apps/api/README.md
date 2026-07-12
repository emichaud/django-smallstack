# api — the REST *observer*

The `/smallstack/api/` admin surface that **introspects** the REST runtime: health checks,
per-endpoint activity, the threat panel, and the `api_doctor` command. It does **not** serve the
API itself — that runtime lives in `apps/smallstack/api.py`.

**Status:** Framework-provided — don't edit in downstream forks.

**Key files:** `admin_views.py`, `monitors.py`, `dashboard_widgets.py`,
`management/commands/api_doctor.py`. **URL:** `/smallstack/api/`.

**See:** [`../smallstack/docs/api-doctor.md`](../smallstack/docs/api-doctor.md) ·
[`../../docs/skills/custom-api-endpoints.md`](../../docs/skills/custom-api-endpoints.md) ·
CONTRIBUTING → "observer vs runtime".
