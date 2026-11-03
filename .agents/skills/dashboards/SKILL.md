---
name: dashboards
description: "KPIs, dashboards and KPI reports over datasets — the Metric (a stored filter tree + aggregate → one value, thresholds, period-aware), grid dashboards (gridstack, lazy htmx cells, period bar, register_component_type for your own card types), reports (metrics × periods, CSV), {% metric_card %}, and the agent loop (metric_preview → create_metric → dashboard_add_card → dashboard_snapshot)"
license: MIT
metadata:
  source: "docs/skills/dashboards.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/dashboards.md` by `make skills-index` — edit the source, not this file.

# Dashboards — metrics, grid dashboards and KPI reports (`apps/dashboards/`)

**Read this** before building a KPI, a dashboard, or a metrics report — or before
letting an AI agent build one. The app label is `smallstack_dashboards`; pages
live under `/smallstack/dashboards/`.

> **Prerequisite**: [`datasets.md`](datasets.md). Every number here is a
> `@dataset` rolled up through a stored **filter tree** (the "Filter trees"
> section there is the grammar). For a one-off tile computed in a view, the
> lower-level [`dashboard-cards.md`](dashboard-cards.md) `{% stat_card %}` is
> still right.

## The model — three nouns, all JSON an agent can write

```
@dataset ──(filter_tree + agg)──▶ Metric ──▶ Dashboard cell   (grid, period bar, refresh)
                                         └─▶ Report row        (metrics × periods, CSV)
                                         └─▶ {% metric_card %}  (any template)
```

| Model | What it is | Key fields |
|---|---|---|
| **Metric** | A named, stored filter over a dataset rolled up to one value — the KPI. The reusable unit. | `key` (stable slug), `dataset`, `filter_tree`, `agg`, `measure`, `period_field`, `format`, `unit`, `thresholds` |
| **Dashboard** | A grid of cards. | `slug`, `layout` (list of cells), `default_period`, `refresh_seconds` |
| **Report** | Metrics × periods as a table (+ CSV). | `slug`, `items` (`[{metric, label?}]`), `periods` (`["mtd", "pmtd", "ytd"]`) |

All three: `owner` blank = **shared** (staff edit, every signed-in user views);
set = **personal** (owner edits, staff view). `can_view` / `can_edit` on the
model is the one rule — views, REST and MCP never re-derive it. Every model
calls `full_clean()` in `save()`, so a bad filter, a cell pointing at a
missing metric, or a malformed threshold is refused on **every** surface.

This skill is long; the full text is in [references/dashboards.md](references/dashboards.md) — read it before acting.
