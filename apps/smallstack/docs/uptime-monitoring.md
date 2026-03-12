# Uptime Monitoring

SmallStack includes a lightweight heartbeat/uptime monitoring system with a public status page, SLA tracking, and staff dashboard. No external services needed.

## Why Built-In Monitoring?

For small to medium apps — internal tools, side projects, client portals — dedicated monitoring services like Datadog or UptimeRobot are often overkill. SmallStack gives you "just enough" out of the box:

- **Proof of life** — a heartbeat that proves cron, the database, and the application are all working
- **Public status page** — give your users confidence that the system is healthy
- **SLA tracking** — measure and report on uptime commitments

As your site grows, you may want to add an external monitoring tool that can alert you when the site is unreachable from outside your network. SmallStack's JSON API at `/status/json/` is designed for exactly this — point your external monitor at it, and use SmallStack's built-in tracking for the historical record.

## How It Works

A cron job runs `python3 manage.py heartbeat` every minute inside the Docker container. Each run:

1. Checks database connectivity (`connection.ensure_connection()`)
2. Records a `Heartbeat` row with status (ok/fail) and response time
3. Auto-creates a monitoring epoch on the first heartbeat (sets the SLA baseline)
4. Prunes records older than the retention period, writing daily summaries first

Heartbeat timestamps are truncated to the minute boundary (`:00` seconds) so they align cleanly with the epoch. This ensures 100% uptime is achievable when no checks are missed.

## Pages

| URL | Access | Description |
|-----|--------|-------------|
| `/status/` | Public | Status page with uptime %, timelines, response times |
| `/status/json/` | Public | Machine-readable JSON for external monitors |
| `/status/dashboard/` | Staff only | Heartbeat log with sortable table, timelines, and JSON view |
| `/status/sla/` | Staff only | SLA configuration, thresholds, and daily summaries |

### Public Status Page

The status page requires no login — share it with users, embed it in a status site, or use it as a health dashboard.

![Public status page](/static/smallstack/docs/images/about-status.png)

The page shows:
- Current status indicator (Operational / Degraded / Down)
- Overall, 24-hour, and 7-day uptime percentages
- Last and average response times
- 24-hour and 1-hour visual timelines with per-slot tooltips
- Monitoring start date

### Staff Dashboard

The dashboard provides detailed operational data behind a staff login.

![Staff dashboard](/static/smallstack/docs/images/status-dashboard.png)

Three tabs:
- **Timelines** — the same 24h and 1h bar charts from the public page
- **Heartbeat Log** — a sortable, paginated django-tables2 table with All/OK/Fail filters
- **JSON** — the raw JSON response from `/status/json/`, formatted for easy reading

### SLA Page

Staff can configure SLA targets and reset the monitoring epoch.

![SLA configuration](/static/smallstack/docs/images/status-sla.png)

The SLA page shows uptime against Goal and Commitment thresholds, a configuration form for adjusting targets, and a reference panel explaining how uptime is calculated.

## Status Logic

- **Operational** — Last 5 heartbeats all OK
- **Degraded** — Any failures in last 5, but most recent is OK
- **Down** — Most recent heartbeat is "fail" OR no heartbeat in last 5 minutes

## Uptime Calculation

Uptime is calculated as:

```
uptime % = (ok checks / expected checks) x 100
```

Where expected checks = `floor(elapsed seconds / interval)`. The floor means the current incomplete minute doesn't count against uptime — if you're 30 seconds into a new minute, you aren't penalized for a check that hasn't happened yet. This ensures 100% is achievable when every expected check succeeds.

All uptime calculations are **epoch-aware**. The epoch is the monitoring start date — uptime is only measured from that point forward. The epoch is auto-created on the first heartbeat, or can be reset from the SLA page.

## SLA Tracking

The SLA system provides two thresholds:

- **Goal** (default 99.95%) — the internal target. Dashboard shows yellow (warning) when uptime is between goal and commitment. Allows ~21.6 min downtime/month.
- **Commitment** (default 99.9%) — the public threshold. Below this is red (breach). Allows ~43.2 min downtime/month.

The dashboard uses 3-tier coloring (green/yellow/red) to show performance against the goal. The public status page and SLA page use 2-tier coloring (green/red) against the commitment — no need to expose internal targets publicly.

### SLA Configuration

Staff can update SLA settings from `/status/sla/`:

- **Monitoring Start** — reset the epoch (uptime recalculates from this date). The form shows the active timezone so you know how the input is interpreted.
- **Goal %** — the internal uptime target
- **Commitment %** — the public minimum acceptable uptime
- **Note** — reason for the change (e.g., "After server migration")

### Daily Summaries

When heartbeat records are pruned (after the retention period), they are first aggregated into `HeartbeatDaily` summaries. This preserves long-term uptime data even after individual records are deleted. Daily summaries are visible on the SLA page.

## Settings

```python
# config/settings/base.py
HEARTBEAT_RETENTION_DAYS = 7       # How long to keep individual records (default: 7)
HEARTBEAT_EXPECTED_INTERVAL = 60   # Seconds between checks (default: 60)
```

Both can be set via environment variables.

## Running Locally

The heartbeat command works outside Docker too:

```bash
uv run python manage.py heartbeat
```

To reset the monitoring epoch from the command line:

```bash
uv run python manage.py heartbeat --reset-epoch --reset-note "Fresh start"
```

## Cron Setup

In production Docker containers, scheduled tasks run automatically via [supercronic](https://github.com/aptible/supercronic). The heartbeat job is in `scripts/smallstack-cron`:

```cron
* * * * * cd /app && python3 manage.py heartbeat
```

Supercronic inherits the container's environment variables directly — no `.env.cron` sourcing needed. It runs as a non-root user alongside the application. Logs go to stdout for easy access via `docker logs` or `kamal app logs`.

## JSON API

`GET /status/json/` returns:

```json
{
    "status": "operational",
    "status_label": "Operational",
    "last_heartbeat": "2025-01-15T12:00:00+00:00",
    "response_time_ms": 1,
    "age_seconds": 45,
    "uptime_24h": 100.0,
    "uptime_7d": 99.93,
    "uptime_overall": 99.95,
    "sla_target": 99.9,
    "sla_minimum": 99.5,
    "monitoring_since": "2025-01-08T00:00:00+00:00"
}
```

Use this endpoint with external monitoring services like UptimeRobot, Healthchecks.io, or your own scripts for alerting. The built-in system tracks history and shows it on the status page — external tools handle the alerting and outside-in verification.

## Growing Beyond Built-In Monitoring

SmallStack's monitoring is designed for simplicity. As your needs grow, here's a natural progression:

1. **Start here** — SmallStack heartbeat + status page covers most small/internal sites
2. **Add external pings** — Point an external monitor at `/status/json/` for outside-in checks and alerting
3. **Full observability** — When you need APM, distributed tracing, or multi-service dashboards, consider dedicated tools like Sentry, Datadog, or Grafana

The built-in system doesn't try to replace professional monitoring — it fills the gap between "no monitoring at all" and "we need a full observability platform."

## Extending

To add more checks beyond database connectivity, modify `apps/heartbeat/management/commands/heartbeat.py`. For example, check Redis, external APIs, or disk space.
