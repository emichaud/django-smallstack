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

**Keeping the pile small.** Every owned row (metrics, dashboards, cards, playlists, reports, goal lists) carries `tags` (one text field, comma-separated; `tag_list`, `split_tags`, `OwnedQuerySet.tagged(tag)` matches a whole tag, any case) and `archived_at` (`is_archived`, `set_archived(bool)`, `OwnedQuerySet.active()` / `.archived()`). The rule: **lists and pickers show active rows; references keep working.** Overviews, CRUD lists (`?archived=1` shows the archived ones instead), REST/MCP lists, the board editor's metric and card pickers, the goal-add picker and the rate's numerator/denominator pickers all go through `.active()`; a card drawing an archived metric, a report row, a goal, `get_detail_queryset` and the REST/MCP `get_*` by key do not. `usage_index` ignores archived boards, reports and goal lists, so archiving a board frees its metrics. Archive or restore from the page's header (`POST dashboards/archive/<kind>/<pk>/`, editors only, `kind` in `metric dashboard component playlist report goals`). Both overviews narrow to one tag with `?tag=` (chips on every row link there) and say how many rows are archived. **Duplicate** (every page's header, a card's builder) is the create form opened with `?from=<key or slug>`: the original's defining fields and tags prefilled, the name "(copy)", visibility personal, nothing saved until Save; a metric's or card's key comes from its name, a slug-keyed type gets the next free slug (`_free_slug`), and the original is untouched. `MetricCreateMixin.COPIED` and each `*DuplicateMixin.duplicate_fields` say what's carried over. Over REST or MCP a duplicate is a get followed by a create.

This skill is long; the full text is in [references/dashboards.md](references/dashboards.md) — read it before acting.
