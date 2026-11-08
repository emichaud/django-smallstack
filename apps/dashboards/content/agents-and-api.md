---
title: Agents and the API
order: 3
---

# Agents and the API

Everything in Dashboards can be built by an AI agent, through the MCP server
(Claude Desktop, Claude.ai connectors) or the REST API. The agent works with
exactly your account's rights: it sees the dashboards and datasets you can see
and edits what you can edit.

A metric's `source` is `dataset` (the default), `manual` or `rate`. For `manual`, set values with
`metric_record_value {"key", "date", "value", "note"}` or `POST
/smallstack/dashboards/api/metrics/<key>/entries/`. For `rate`, set `numerator` and `denominator`
to metric keys.

To track a goal list over time, set its cadences with `goal_list_tracking`, read them back with
`goal_list_history`, and capture on demand with `goal_list_capture`.

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
   `dashboard_add_card` per card. Personal is the default: a staff agent
   passes `"visibility": "shared"` for the team's copy, on every piece.
4. **Check** with `dashboard_snapshot`, which evaluates every card.

## The MCP tools

| Tool | Does |
|---|---|
| `list_datasets`, `describe_dataset` | what can be measured, and how it can be filtered |
| `metric_preview` | evaluate an unsaved metric (dry run) |
| `list_metrics`, `get_metric`, `create_metric`, `update_metric`, `delete_metric` | metric CRUD. The CRUD families here share these verbs |
| `metric_value` | a saved metric's value, optionally for a period, with the change from the previous period |
| `metric_trend` | a saved metric per day, week, month, quarter or year across a period, which is what a chart draws |
| `metric_rows` | the rows behind a number, to explain it |
| `metric_usage` | where a metric is used, before you change or delete it |
| `list_dashboard_components` | the card types and their options |
| `card_preview`, `*_component` | try a card without saving; saved cards you can place by key |
| `get_dashboard`, `create_dashboard`, `update_dashboard`, … | dashboard CRUD (the whole layout at once) |
| `dashboard_add_card`, `dashboard_remove_card` | one card at a time |
| `dashboard_snapshot` | every card on a dashboard with its live value. Nothing is stored, and a chart or calendar card has no one number |
| `create_goal_list`, `goal_list_add_goal` | goal lists and their targets. To change or remove a goal, read the list with `get_goal_list`, edit its `sections` and send them all to `update_goal_list` |
| `goal_list_values`, `goal_list_weeks` | a list judged now; a list week over week |
| `goal_list_save_week` | save one named week as it stands (a list tracking weeks is also saved each Monday) |
| `goal_list_tracking`, `goal_list_capture`, `goal_list_history` | the cadences a list is captured on; capture the current period or fill past ones; read captures back |
| `metric_record_value`, `metric_delete_value` | a hand-entered metric's value for a date |
| `create_report`, `report_values`, … | KPI reports; `report_values` gives the CSV's link too |
| `create_playlist`, `playlist_slides` | slides for a meeting: dashboards and goal lists |
| `list_calendars`, `calendar_events`, `create_event`, `create_calendar_view` | the calendar. Give an event a `start_time` and it's timed, and a `repeat` and it's a series |
| `event_skip_date` | take one date out of a series, or put it back |
| `query_dataset_<key>` | raw rows from a dataset, when the site publishes that tool. Bundled datasets don't by default (`SMALLSTACK_FRAMEWORK_DATASETS_MCP`); `list_datasets` says which do |

Rows can be named as well as numbered: `get_metric`, `update_metric` and `delete_metric`
take `key` in place of `id`; dashboards, reports, goal lists and playlists take `slug`.
A `slug` is optional when creating one: leave it out and it's made from the name (`site-health`,
then `site-health-2`), and the answer says what it is. An existing one's slug doesn't change
with its name. Only an administrator (a superuser, or a member of the `admin` group) may change it;
anyone else's change, over REST and MCP too, is refused. A changed slug breaks the old address: there
is no redirect, so bookmarks, embeds and playlists that used it stop working.

**Periods** are `today`, `yesterday`, `wtd` (this week so far), `pwtd` (last week), `mtd`, `pmtd`,
`qtd`, `pqtr`, `ytd`, `prev_year`, `this_month` and `this_year` (the whole month or year, days to come
included), `last_<N>`, `next_<N>` and `all`. A name that isn't one is refused,
never answered with an all-time number (a stored `default_period` takes only the fixed names, not
`all` or an arbitrary `last_14`). **A metric with no `period_field`** can't be narrowed, so it gives
its all-time value and a `note` saying so, and a goal on one can't have its own period.

**Counts.** A list tool's `count` is the page and `total` is how many match. Tool links are relative
to the site. `dashboard_snapshot` gives metric cards' values, grouped cards' groups and notes' text;
for a calendar card, ask `calendar_events`.

## REST

With a token (`Authorization: Bearer …`), the CRUD routes are
`/smallstack/api/dashboards/metrics/`, `…/boards/`, `…/reports/`, `…/goals/`,
`…/components/` and `…/playlists/`. These routes evaluate:

```
GET  /smallstack/dashboards/api/datasets/
GET  /smallstack/dashboards/api/datasets/<key>/schema/
POST /smallstack/dashboards/api/preview/            {"dataset": …, "filter_tree": {…}, "agg": …}
POST /smallstack/dashboards/api/report-preview/     {"items": [{"metric": …}], "periods": ["mtd", "pmtd"]}
POST /smallstack/dashboards/api/card-preview/       {"type": …, "metric": …, "options": {…}}
GET  /smallstack/dashboards/api/metrics/<key>/value/?period=mtd
GET  /smallstack/dashboards/api/metrics/<key>/trend/?period=&grain=
GET  /smallstack/dashboards/api/metrics/<key>/rows/?period=&order=&limit=
GET  /smallstack/dashboards/api/boards/<slug>/values/
GET  /smallstack/dashboards/api/reports/<slug>/values/    (?format=csv for the file)
GET  /smallstack/dashboards/api/goals/<slug>/values/?period=
GET  /smallstack/dashboards/api/goals/<slug>/weeks/?week=&weeks=
POST /smallstack/dashboards/api/goals/<slug>/weeks/<week>/save/
GET  /smallstack/dashboards/api/goals/<slug>/tracking/
POST /smallstack/dashboards/api/goals/<slug>/tracking/    {"cadences": ["weekly", "monthly"]}
GET  /smallstack/dashboards/api/goals/<slug>/snapshots/?cadence=weekly
POST /smallstack/dashboards/api/goals/<slug>/snapshots/   {"cadence": "weekly", "fill": 4}
GET  /smallstack/dashboards/api/metrics/<key>/entries/
POST /smallstack/dashboards/api/metrics/<key>/entries/    {"date": …, "value": …, "note": …}
GET  /smallstack/dashboards/api/playlists/<slug>/slides/
GET  /smallstack/dashboards/api/components/
```

All of them are in the OpenAPI schema (`/api/schema/openapi.json`, browsable at `/api/docs/`).

## Safety

- A non-staff account's agent can't share; only a staff account's can mark something shared.
- A metric can only use datasets its user may read. A card on a shared
  dashboard shows *restricted* to anyone whose account can't read its data.
- A bad filter is refused with a precise reason. It is never applied as
  "no filter". So is a misspelt argument, period or week.
- `delete_metric` also removes the metric's cards, report rows, goals and saved cards in
  everything the account can edit, and lists them under `also_removed`, with any rates it
  leaves showing an error under `also_removed.rates_left_without_it`. It isn't a dry run:
  `metric_usage` says where a metric is used, first.
