# Uptime Monitoring

SmallStack includes a lightweight heartbeat/uptime monitoring system with a public status page, SLA tracking, and staff dashboard. No external services needed.

## How It Works

A cron job runs `python manage.py heartbeat` every minute inside the Docker container. Each run:

1. Checks database connectivity (`connection.ensure_connection()`)
2. Records a `Heartbeat` row with status (ok/fail) and response time
3. Auto-creates a monitoring epoch on the first heartbeat (sets the SLA baseline)
4. Prunes records older than the retention period, writing daily summaries first

## Pages

| URL | Access | Description |
|-----|--------|-------------|
| `/status/` | Public | Status page with uptime %, timelines, response times |
| `/status/json/` | Public | Machine-readable JSON for external monitors |
| `/status/dashboard/` | Staff only | Heartbeat log with sortable table, tabs (All/OK/Failures) |
| `/status/sla/` | Staff only | SLA configuration, thresholds, and daily summaries |

## Status Logic

- **Operational** — Last 5 heartbeats all OK
- **Degraded** — Any failures in last 5, but most recent is OK
- **Down** — Most recent heartbeat is "fail" OR no heartbeat in last 5 minutes

## Uptime Calculation

Uptime is calculated as `ok_count / expected_heartbeats * 100` where expected heartbeats = elapsed seconds / interval. This means missed heartbeats count against uptime — if no heartbeat arrives when one was expected, uptime drops.

All uptime calculations are **epoch-aware**. The epoch is the monitoring start date — uptime is only measured from that point forward. The epoch is auto-created on the first heartbeat, or can be reset from the SLA page.

## SLA Tracking

The SLA system provides target and minimum thresholds for uptime:

- **Service Target** (default 99.9%) — the goal. Uptime at or above this is green.
- **Service Minimum** (default 99.5%) — the floor. Uptime between minimum and target is yellow (warning). Below minimum is red (breach).

These colors are applied consistently across the public status page, dashboard, and SLA detail page.

### SLA Configuration

Staff can update SLA settings from `/status/sla/`:

- **Monitoring Start** — reset the epoch (uptime recalculates from this date)
- **Service Target %** — the uptime goal
- **Service Minimum %** — the minimum acceptable uptime
- **Note** — reason for the change

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

In production Docker containers, cron runs automatically. The heartbeat job is in `scripts/smallstack-cron`:

```cron
* * * * * . /app/.env.cron && cd /app && python manage.py heartbeat >> /proc/1/fd/1 2>&1
```

Cron runs in the container's system timezone (set via the `TZ` environment variable, defaults to UTC). The heartbeat fires every minute so timezone doesn't matter for it, but the backup job in the same cron file is timezone-sensitive. See [Database Backups — Cron and Timezones](/help/smallstack/database-backups/#cron-and-timezones) for details on setting your timezone.

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

Use this endpoint with external monitoring services like UptimeRobot or Healthchecks.io for alerting.

## Extending

To add more checks beyond database connectivity, modify `apps/heartbeat/management/commands/heartbeat.py`. For example, check Redis, external APIs, or disk space.
