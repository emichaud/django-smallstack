---
name: status-monitors
description: "The status/uptime monitoring standard: register a Service + Monitor (cheap check()), the 3-tier taxonomy (Site / Site Monitors / External), the branded public /status/ page (90-day timelines + maintenance calendar), per-monitor public flag + independent SLA/maintenance, the no-code Add-monitor wizard, and pluggable Visualization panels"
license: MIT
metadata:
  source: "docs/skills/status-monitors.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/status-monitors.md` by `make skills-index` — edit the source, not this file.

# Status Monitors — pluggable uptime/health monitoring

The status system tracks the uptime and health of *services* (the site, the REST
API, MCP, search, …) and any *user-created endpoint*. It's a pluggable registry,
like the dashboard-widget system: an app contributes a **Service** and one or more
**Monitors** from `AppConfig.ready()`, and they show up on the overview with a
status dot, uptime, and a per-monitor timeline page — **no changes to the overview,
the runner, or the views**.

The surfaces it powers:

| Surface | URL | Who |
|---|---|---|
| **Staff overview** — 3-tier board, banners, drill-downs | `/smallstack/status/overview/` | staff |
| **Public status page** — branded, 90-day timelines + maintenance calendar | `/status/` | anyone |
| **Per-monitor detail / timeline** | `/smallstack/status/monitor/<key>/` | public-aware |
| **Per-monitor SLA + maintenance** | `/smallstack/status/sla/?monitor=<key>` | staff |
| **Site Timeline** (the site monitor's 1d/7d/90d bars) | `/smallstack/status/dashboard/` | staff |
| **Scheduled maintenance** (list + 6-month calendar) | `/status/maintenance/` | anyone |

Read this before adding monitoring for a subsystem, exposing a health check, adding
a status visualization, or working on any status page.

## The three concepts

| Concept | What it is | Lives in |
|---|---|---|
| **Service** | A monitored subsystem (the tag monitors attach to): `site`, `api`, `mcp`, `search`, `custom`. Owns an icon + title. | `apps.smallstack.monitors.Service` |
| **Monitor** | A single *cheap* liveness check tagged to one service. Produces a per-minute heartbeat timeseries. | `apps.smallstack.monitors.Monitor` |
| **Visualization** | A pluggable panel (timeline bars, uptime stats, …) that renders any monitor's timeseries. | `apps.smallstack.visualizations.Visualization` |

The registries live in `apps/smallstack/monitors.py` and
`apps/smallstack/visualizations.py` — pure, import-light modules that mirror
`dashboard.py` / `navigation.py`.

This skill is long; the full text is in [references/status-monitors.md](references/status-monitors.md) — read it before acting.
