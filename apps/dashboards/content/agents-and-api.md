---
title: Agents and the API
order: 3
---

# Agents and the API

Everything in Dashboards can be built by an AI agent, through the MCP server
(Claude Desktop, Claude.ai connectors) or the REST API. The agent works with
exactly your account's rights: it sees the dashboards and datasets you can see
and edits what you can edit.

## Asking an agent

With the SmallStack connector added, ask in plain language:

> Build a "Support health" dashboard: open tickets, tickets opened this month,
> average first-response time with a warning over 4 hours, and open tickets
> by queue.

A well-behaved agent will:

1. **Look** at the datasets — `list_datasets`, then `describe_dataset` for the
   fields, the operators each takes and the period names.
2. **Dry-run** each metric with `metric_preview`. That returns the value, how
   many rows match and every problem, without saving anything. It repeats
   until the problems are gone and the number is plausible.
3. **Save** with `create_metric`, then `create_dashboard`, then
   `dashboard_add_card` per card.
4. **Check** with `dashboard_snapshot`, which evaluates every card.

## The MCP tools

| Tool | Does |
|---|---|
| `list_datasets`, `describe_dataset` | what can be measured, and how it can be filtered |
| `metric_preview` | evaluate an unsaved metric (dry run) |
| `create_metric`, `update_metric`, `list_metrics`, … | metric CRUD |
| `metric_value` | a saved metric's value, optionally for a period, with the change from the previous period |
| `metric_trend` | a saved metric per day, week or month across a period, which is what a chart draws |
| `list_dashboard_components` | the card types and their options |
| `create_dashboard`, `update_dashboard`, … | dashboard CRUD (the whole layout at once) |
| `dashboard_add_card`, `dashboard_remove_card` | one card at a time |
| `dashboard_snapshot` | every card on a dashboard, evaluated |
| `create_report`, `report_values`, … | KPI reports |

## REST

With a token (`Authorization: Bearer …`), the CRUD routes are
`/smallstack/api/dashboards/metrics/`, `…/boards/` and `…/reports/`. These
routes evaluate:

```
GET  /smallstack/dashboards/api/datasets/
GET  /smallstack/dashboards/api/datasets/<key>/schema/
POST /smallstack/dashboards/api/preview/            {"dataset": …, "filter_tree": {…}, "agg": …}
POST /smallstack/dashboards/api/report-preview/     {"items": [{"metric": …}], "periods": ["mtd", "pmtd"]}
GET  /smallstack/dashboards/api/metrics/<key>/value/?period=mtd
GET  /smallstack/dashboards/api/boards/<slug>/values/
GET  /smallstack/dashboards/api/reports/<slug>/values/
GET  /smallstack/dashboards/api/components/
```

## Safety

- An agent can't share. Only a staff account's agent can mark something shared.
- A metric can only use datasets its user may read. A card on a shared
  dashboard shows *restricted* to anyone whose account can't read its data.
- A bad filter is refused with a precise reason. It is never applied as
  "no filter".
