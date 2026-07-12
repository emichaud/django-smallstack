# heartbeat — uptime monitoring + `/status/`

Runs registered Service/Monitor checks, records beats, computes uptime/SLA (maintenance-aware),
and renders the public + staff status pages. Beats are driven externally (cron/systemd/Kamal)
via the `heartbeat` command; `maintenance` opens SLA-excluded windows.

**Status:** Framework-provided — don't edit in downstream forks; register your own
Service + Monitor to extend it.

**Key files:** `services.py`, `status.py`, `monitors.py`, `surfaces.py`, `models.py`,
`maintenance.py`, `management/commands/{heartbeat,maintenance}.py`. **URL:** `/status/`.

**See:** [`../../docs/skills/status-monitors.md`](../../docs/skills/status-monitors.md).
