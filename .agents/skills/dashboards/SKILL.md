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

**Start here.** Building one over MCP/REST → *Building agentically (MCP + REST)* (the five-step
loop and the tool table). Adding a card design → [`card-types.md`](card-types.md). Shipping
defaults with an app → [`app-defaults.md`](app-defaults.md). Using the pieces on your own page →
*On your own pages*.

## The model — six owned kinds, all JSON an agent can write

```
@dataset ──(filter_tree + agg)──▶ Metric ──▶ Dashboard cell   (grid, period bar, refresh)
                                         └─▶ Report row        (metrics × periods, CSV)
                                         └─▶ {% metric_card %}  (any template)
```

| Model | What it is | Key fields |
|---|---|---|
| **Metric** | A named number, the KPI and the reusable unit: a stored filter over a dataset rolled up to one value (`source="dataset"`), values entered by hand (`manual`, `MetricEntry`) or one metric divided by another (`rate`). | `key` (stable slug), `source`, `dataset`, `numerator`, `denominator`, `filter_tree`, `agg`, `measure`, `period_field`, `format`, `unit`, `thresholds` |
| **Dashboard** | A grid of cards. | `slug`, `layout` (list of cells), `default_period`, `refresh_seconds` |
| **Report** | Metrics × periods as a table (+ CSV). | `slug`, `items` (`[{metric, label?}]`), `periods` (`["mtd", "pmtd", "ytd"]`) |
| **Component** | A saved card: a design and its source, placed on dashboards with `{"component": key}`. | `key`, `type`, a source (`dataset` + `filter_tree` + `agg`/`measure` + `period_field`, or `metric`), `options` |
| **GoalList** | Goals judged against targets, in titled sections. | `slug`, `sections` (`[{title, goals: [{metric or component, target, warn?}]}]`), `default_period` |
| **Playlist** | Dashboards shown one after another. | `slug`, `items` (`[{dashboard, seconds?, period?}]`), `seconds` |

All six: `owner` blank = **shared** (staff edit, every signed-in user views);
set = **personal** (owner edits, staff view). `can_view` / `can_edit` on the
model is the one rule — views, REST and MCP never re-derive it. Every model
calls `full_clean()` in `save()`, so a bad filter, a cell pointing at a
missing metric, or a malformed threshold is refused on **every** surface.

**Addresses.** Dashboards, reports, playlists and goal lists are addressed by `slug`
(`…/d/<slug>/`, `{% dashboard "slug" %}`, playlist items, the MCP lookup field). Nobody types
one: `forms._OwnedForm` makes it from the name on create (`models.free_slug`: `site-health`,
then `site-health-2`; a name with nothing sluggable takes the model's word, `dashboard`), the
way a metric or card gets its `key`. A create that sends a `slug` (an agent, REST) keeps it. On
an existing row the slug never follows the name, and `clean_slug` lets only an administrator
change it (`models.can_change_address`: a superuser, or a member of the `admin` group,
`ADDRESS_ADMIN_GROUP`; plain staff don't count); anyone else's attempt, over REST and MCP too, is a
validation error, not a silent no-op. The forms show the address read-only
(`partials/address_field.html`, the `can_change_address` filter) with **Change the address** for
administrators only; `signals.py`
carries a changed slug into playlists and Goals cards.

**Keeping the pile small: tags and archive.** Every owned row (metrics, dashboards, cards,
playlists, reports, goal lists) has `tags` and `archived_at`.

- **Tags** are one comma-separated text field (`tag_list`, `split_tags`;
  `OwnedQuerySet.tagged(tag)` matches a whole tag, any case).
- **Archive** puts a row away without breaking anything. The rule: *lists and pickers show
  active rows; references keep working.* Overviews, CRUD lists, REST/MCP lists and every
  picker go through `.active()`; a card drawing an archived metric, a report row, a goal,
  `get_detail_queryset` and REST/MCP `get_*` don't. `usage_index` ignores archived boards,
  reports and goal lists, so archiving a board frees its metrics.
- **Archiving and restoring:** `POST dashboards/archive/<kind>/<pk>/` (editors only; `kind`
  is `metric`, `dashboard`, `component`, `playlist`, `report` or `goals`; `restore=1` brings
  it back). Restore is one click.
- **Finding archived rows:** each list's tags bar (`displays.TagBar`) offers **Show archived
  (N)** (`?archived=1`) and **Back to the list**; the overviews name what's archived by kind,
  each a link ("Archived: 2 metrics, 1 report", `displays.archived_links`).
- **Confirmations.** Archive, Delete and Duplicate each ask first, in the global stat modal
  (htmx), or as a page without JavaScript, and say what the action means:
  - `GET dashboards/archive/<kind>/<pk>/`: what archiving means and what still uses the row;
  - each kind's delete view (`_DeleteInModalMixin`; cards, playlists and goal lists through
    `_ConfirmDeleteMixin`): what goes and what stays;
  - `GET dashboards/duplicate/<kind>/<pk>/` (`DuplicateConfirmView`, anyone who can see the
    row): what the copy will be; its button opens the create form.

  The shared wrappers are `smallstack_dashboards/crud/owned_confirm_{modal,page}.html` around
  a body template; `views.where_used(kind, obj, user)` lists what still uses a row.
- **Duplicate** is the create form opened with `?from=<key or slug>`: the original's defining
  fields and tags, the name "… (copy)", visibility personal, nothing saved until Save. The
  original is untouched. `MetricCreateMixin.COPIED` and each `*DuplicateMixin.duplicate_fields`
  say what's carried over. Over REST or MCP a duplicate is a get followed by a create.

**Finding by tag.** `models.tag_cloud(*querysets, current=)` is the tags in use with their row
counts (any case counted together, the 30 most used, the current one always kept). The
overviews and My dashboards put it in `tags`; every CRUD list gets it from the
`displays.TagBar` list accessory. One partial draws it, `partials/tag_filter.html`: chips that
set `?tag=` on the current address (other parameters kept, `page` dropped) and **Show
everything**. `_OwnedCRUD.get_list_queryset` applies `?tag=` (so REST lists take it too), the
overviews' "All N …" links carry it, and each list display shows a row's tags
(`partials/tags.html`). The overviews are samples and never page
(`DashboardIndexView.DASHBOARD_CARDS` = 8, `DASHBOARD_ROWS` = 20, `PLAYLISTS` = `COMPONENTS` =
6); the lists and `…/mine/` page at `PAGE_SIZE_CHOICES` (15 first).

This skill is long; the full text is in [references/dashboards.md](references/dashboards.md) — read it before acting.
