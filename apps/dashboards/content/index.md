---
title: Dashboards
order: 1
---

# Dashboards

The numbers that matter live in two places in the sidebar: open tickets, errors
this week, average latency, pending approvals.

- **Goals** (`/smallstack/goals/`) is the numbers themselves: the **metrics** that define them, **goal lists** that judge them against targets, and **reports** that compare them across periods.
- **Dashboards** (`/smallstack/dashboards/`) is how they're shown: **dashboards** of cards, the saved **components** (card designs) they're built from, and **playlists** that rotate them.

| | What it is |
|---|---|
| **Metric** | A saved filter over a dataset, rolled up to one number — "requests that answered 5xx", counted. The reusable unit: one metric can sit on many dashboards, reports and goal lists. |
| **Goal list** | Metrics against their targets, in sections: on target, at risk or missed. See [Goals](/smallstack/help/dashboards/goals/). |
| **Report** | A table of metrics across periods — this month vs last month vs the year so far — that can be downloaded as CSV. |
| **Dashboard** | A grid of cards. Each card shows a metric (or a metric split by a column, a widget, a goal list, or a note). |
| **Component** | A saved card design. It takes its number, format, unit and colour rules from its metric; change any of them on the card to override them there only. |

## The ladder: dataset → metric → card

A **dataset** is a named, filterable table the project has declared
(requests, tickets, health checks…). A **metric** stores *which rows* (a
filter) and *how to roll them up* (count, sum, average…). A **card** shows the
metric's current value, coloured by its thresholds; click it to see the rows
behind the number. Because the card re-runs the stored filter every time, it
is always current.

## Reading a dashboard

- **Period** (top left) narrows every *period-aware* card to "Last week",
  "Last 7 days", "Month to date", "Previous quarter" and so on. A card whose metric has no
  date column ignores it, and so does a card pinned to all time.
- **Click a number** to open the rows behind it. On a grouped card, each group
  opens its own rows.
- A card that says **restricted** draws on data your account can't read. The
  dashboard is shared with you; that card's data isn't.
- A dashboard with **Refreshes every N s** re-fetches its cards on its own; **Refresh** reloads
  them now.
- On **Today** or **This week / month / quarter / year**, each card shows its change from the
  period before, e.g. *▼ 35% vs all of last month*. "All of" means this period is still running
  and is being compared with a finished one. The change is grey on purpose: whether up is good
  depends on the metric.

## Editing a layout

On a dashboard you can edit, click **Edit layout**:

1. **Drag** cards to move them; drag a corner to resize. The grid is 12 columns wide.
2. **Add card** → pick a type:
   - **Metric** — one number.
   - **Grouped metric** — the metric split by a column (requests by method, tickets by queue): the biggest groups as numbers, the rest folded into *Other*.
   - **Dashboard widget** — any card from the main `/smallstack/` dashboard (staff).
   - **Text** — a heading or a note, in markdown.
3. **Remove** takes a card off (the metric itself stays).
4. **Save layout**. **Cancel** throws the changes away.

**Settings** edits the name, the default period and auto-refresh. It also lists every card with its design, metric, size and current value. Sorting that table only changes the table; a card's place on the dashboard doesn't move.

## Reports

A report row can have a **target** (and an at-risk line), like a goal. Its values
are then coloured on target, at risk or missed, a Target column appears, and the
CSV adds each value's status. In the report editor, set a row's target under its
name, or choose **Use the colour rules** to start from the metric's.

In the report editor, clicking a column heading (Metric, Target or At risk) sorts the
rows and changes the order the report reads in. **Undo** puts them back, and nothing
changes until you save. Columns can be dragged wider or narrower.

A report's numbers open their rows too. The first column shows its change from the second,
and the reports list shows each report's movement in one line ("▲ 2 up, ▼ 5 down"). When you
edit a report, the preview shows its real values as you build it. The first period you tick is
the first column.

## Deleting

Deleting a metric shows which dashboard cards, report rows, goals and saved cards would break, and
removes them in the same step unless you untick the box. Deletes made by an agent or through the API always
remove them. Deleting a report or a dashboard leaves its metrics alone. The page offers a
CSV or a copy of the layout first.

## On your own pages

Any page in your project can show a dashboard or a single metric:

```django
{% load dashboard_tags %}
{% dashboard "site-health" %}
{% metric_card "open_tickets" period="mtd" %}
```

The cards, numbers and drill-downs are the same ones these pages show. People who can't open the
dashboard see nothing. The **Dashboard** starter page has a working example.

## Sharing

Every metric, dashboard and report is either **personal** (yours; only you can
edit it) or **shared** (every signed-in user can open it; staff edit it). Only
staff can share. Staff can open anyone's personal items to help, but only the
owner edits them.

A shared dashboard can hold only shared metrics, and a personal one can hold
shared metrics and your own. It can't use someone else's personal metric.

## A demo

`uv run python manage.py seed_dashboards` creates a **Site health** dashboard
and a **Monthly KPIs** report from the built-in datasets (requests, health
checks, approvals). It's a good place to see each card type.
