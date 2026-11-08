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
| **Metric** | One named number: counted from a dataset ("requests that answered 5xx"), entered by hand, or one metric divided by another. See [Building metrics](/smallstack/help/dashboards/building-metrics/). The reusable unit: one metric can sit on many dashboards, reports and goal lists. |
| **Goal list** | Metrics against their targets, in sections: on target, at risk or missed. See [Goals](/smallstack/help/dashboards/goals/). |
| **Report** | A table of metrics across periods — this month vs last month vs the year so far — that can be downloaded as CSV. |
| **Dashboard** | A grid of cards: a metric as a number, a dataset filtered for the card and split or charted, a widget, a goal list, a note. |
| **Component** | A saved card: a dataset filtered for it (any design), or a saved metric for a single number, which lends the card its format, unit and colour rules until the card overrides them. |

## Getting a team started

For a weekly operations meeting, from nothing:

1. **Metrics.** Under **Goals → Metrics → New metric**, build the numbers you read each week, and
   choose **Shared** under *Who can see it*. Counted from a dataset, set **Date to count by**, so it can
   be narrowed to a week. A number from outside can be **entered by hand**, and a percentage is a
   **rate**: see [Building metrics](/smallstack/help/dashboards/building-metrics/).
2. **A goal list.** **Goals → Goal lists → New goal list**: choose **Shared** and judge it over
   **Previous week**, then add sections and targets. See [Goals](/smallstack/help/dashboards/goals/).
3. **A dashboard**, also shared, opening on the previous week, with those metrics, grouped cards and a
   **Calendar** card for what's coming.
4. **A playlist** under **Dashboards → Playlists**: the dashboard, then the goal list as *Goals now*,
   *Last week* and *Week over week*.

Put the meeting itself on the calendar as a [repeating event](/smallstack/help/calendar/), and use
**Print** on the goal list for a paper copy. Last week's hand-entered numbers can be typed on Monday
morning: the saved week picks them up.

While a list tracks weeks (new ones do), the week just ended is saved early each Monday; see *Saving
weeks* in [Goals](/smallstack/help/dashboards/goals/). An agent can do all of this: see
[Agents and the API](/smallstack/help/dashboards/agents-and-api/).

## The ladder: dataset → metric → card

A **dataset** is a named, filterable table the project has declared
(requests, tickets, health checks…). SmallStack bundles its own (requests, heartbeats, job runs…);
your own data becomes one with a few lines of code, which a developer can add from
`docs/skills/datasets.md` (`@dataset`). A **metric** stores *which rows* (a
filter) and *how to roll them up* (count, sum, average…). A **card** shows the
metric's current value, coloured by its thresholds; click it to see the rows
behind the number. Because the card re-runs the stored filter every time, it
is always current.

## Reading a dashboard

- **Period** (top left) narrows every *period-aware* card to "This week", "Last week", "7 days",
  "This month" and so on (see *Periods*, below). A card whose metric has no
  date column ignores it, and so does a card pinned to all time.
- **Click a number** to open the rows behind it. On a grouped card, each group
  opens its own rows.
- A card that says **restricted** draws on data your account can't read. The
  dashboard is shared with you; that card's data isn't.
- A dashboard with **Refreshes every N s** re-fetches its cards on its own; **Refresh**, in the
  page's header, reloads them now.
- **Linked cards.** Some dashboards connect their cards: clicking a slice, bar or calendar day
  in one card narrows another to it instead of opening rows. The narrowed card says so,
  e.g. *Showing POST ✕*; the ✕ puts it back.
- On **Today** or **This week / month / quarter / year**, each card shows its change from the
  period before, e.g. *▼ 35% vs all of last month*. "All of" means this period is still running
  and is being compared with a finished one. The change is grey on purpose: whether up is good
  depends on the metric.

## Periods

| On the page | In forms and the API | Means |
|---|---|---|
| Today / Yesterday | `today`, `yesterday` | that calendar day |
| This week | Week to date, `wtd` | Monday up to now, so it's still running |
| Last week | Previous week, `pwtd` | the last full week, Monday to Sunday |
| This month, This quarter, This year | `mtd`, `qtd`, `ytd` | from the 1st up to now |
| Last month, Last quarter, Last year | `pmtd`, `pqtr`, `prev_year` | the last full one |
| This month, whole / This year, whole | `this_month`, `this_year` | the whole calendar month or year, including days still to come |
| 7 days, 30 days, 90 days | `last_7`, `last_30`, `last_90` | rolling, from that many days ago through today |
| Next 7 days, Next 30 days | `next_7`, `next_30` | rolling, from today on |

Periods still running are compared with **all** of the period before, so early in a week a number
that only goes up looks low. For a meeting, read **Last week**, which compares with the week before.

## A card's menu

Point at a card and a **⋯** appears at its corner (on a touch screen it's always there).
What it offers depends on the card and on you:

- **Edit card** opens the card's builder in a window over the dashboard: its design, metric,
  options, style and drill-down, with a live preview. **Save** and you're back on the dashboard.
  A card that belongs to this dashboard only changes here. A **saved card** (one from
  **Components**) changes on every dashboard that shows it, and the window says so. You see
  Edit on a saved card only if you may edit that card.
- **Make a unique copy** is on a saved card that other dashboards show too. The card stays
  where it is, looking as it did, but stops following the saved card: it becomes this
  dashboard's own. Tick **Copy its metric too** (it's ticked to start with) and the card gets
  its own copy of the metric as well, named after the dashboard, so you can change its filter
  here without changing the number anywhere else. The saved card and the other dashboards are
  left as they were.
- **Give it its own metric** is on a card that already belongs to this dashboard: it copies
  the metric the same way, without changing the card.
- **Move or resize** starts arranging the cards (the same as **Edit layout**).
- **Open the metric** goes to the page of the number the card draws. **Edit the metric** goes
  straight to its filter, when it's yours to change.
- **Refresh this card** reloads just that one.
- **Remove from dashboard** asks first, then takes the card off. Its metric stays, and so does
  a saved card under Components.

Someone who can open a dashboard but not edit it sees only Open the metric and Refresh.

**A card other dashboards show too is marked**, for anyone who can edit the dashboard: a small
tab on its bottom edge with a link and the number of dashboards showing it. Editing that card
changes all of them.

**A new dashboard from an old one.** Open the old one and choose **Duplicate**, then on the copy:
remove the cards you don't want, choose **Make a unique copy** (or **Give it its own metric**)
on each one that should show different numbers, and use **Edit the metric** to change each
filter. The original dashboard and its numbers don't change. A number entered by hand isn't
copied, because its values are typed against that one metric.

## Editing a layout

On a dashboard you can edit, click **Edit layout**:

1. **Drag** cards to move them; drag a corner to resize. The grid is 12 columns wide.
2. **Add card** → pick a type:
   - **Saved card** — one you've built under **Components** (when you have any).
   - **Single stat** — one number, from a saved metric.
   - **Gauge** — one number on a half dial, coloured by its rules.
   - A grouped stat or a chart (requests by method, latency over time) filters a dataset of its own, so it's built under **Components** and placed as a saved card, or added here and opened with **Edit card**.
   - **Goals** — a goal list's summary and first goals.
   - **Calendar** — upcoming entries, a month or a day-range board.
   - **Info card** — any card from the main `/smallstack/` dashboard (staff).
   - **Note** — a heading or a note, in markdown, with its own text colour, size and alignment.
   - **Menu** — a row or column of links, to other dashboards or anywhere.
3. **Remove** takes a card off (the metric itself stays).
4. **Save layout**. **Cancel** throws the changes away.

**Settings** edits the name, picture, tags, the default period and auto-refresh. It also lists every card with its design, metric, size and current value. Sorting that table only changes the table; a card's place on the dashboard doesn't move.

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

**Print** on a report opens a document of it, then your browser's print dialog. A report with more
than three period columns prints sideways.

## Finding things

The two overviews, **Dashboards** and **Goals**, each show a short sample of what's there, most
recently changed first, and each section sorts on its own:

| On the Dashboards overview | Shown | The rest |
|---|---|---|
| Dashboards | 8 as cards, or 20 as a list | **All N dashboards** |
| Playlists | 6 | **All N playlists** |
| Saved cards | 6 | **All N cards** |

An overview never pages. Past those numbers, the link beside each section opens its full list,
which shows 15 to a page with a **Rows per page** choice (15, 25, 50 or 100). The pager appears
once there are more than 15. **My dashboards** pages the same way.

**Tags** are how you group things. Add them to anything in its settings (*ops*, *weekly
review*), and every overview and list shows a **Tags** bar across the top with each tag in use
and how many things carry it. Choose one to narrow the page to it; **Show everything** clears
it. Before anything is tagged, the bar says how to add the first one. The tag follows you from
an overview into a full list. A row's own tags are chips too. A
tag matches whole: *ops* doesn't find *devops*. The search box on a list also looks in tags,
and there it matches part of a word.

**Hover over a metric or goal name** in a list to see its description, if it has one.

**Archived things** are out of the lists and pickers but not gone (see *Archiving*, below). A
list with some shows **Show archived (N)** beside its tags; the overviews say what's archived,
e.g. *Archived: 2 metrics, 1 report*, each a link.

## Addresses

Every dashboard, report, playlist and goal list has an address, such as
`/smallstack/dashboards/d/site-health/`. You don't type it. It's made from the name when you
create the thing: *Site health* becomes `site-health`, and a second one with the same name
becomes `site-health-2`.

**Renaming doesn't change the address**, so bookmarks, links, pages that embed a dashboard and
wall screens pointed at a playlist keep working. A thing's settings page shows its address.

An administrator (a superuser, or a member of the `admin` group) can change an address on purpose, under **Change the address** in its settings. Playlists
and Goals cards that show it follow the change; links and bookmarks to the old address stop
working. Metrics and saved cards have a permanent key instead, also made from the name.

## Archiving, deleting and duplicating

Each of these asks first and says what it will do.

- **Archive** puts something away without breaking anything. It leaves the lists and pickers,
  but every dashboard, report and goal using it keeps showing it. To bring it back, choose
  **Show archived** on its list, open it and press **Restore**. When in doubt, archive.
- **Delete** can't be undone, so the confirmation says what goes and what stays:
  - A **metric**: the dashboard cards, report rows, goals and saved cards that use it. They're
    removed in the same step unless you untick the box. (Deletes by an agent or the API always
    remove them.)
  - A **saved card**: each dashboard showing it keeps it as a card of its own.
  - A **goal list**: its goals and its saved week-by-week history.
  - A **report**, **dashboard** or **playlist**: only itself; the metrics and dashboards it
    uses stay. A report offers a last CSV, a dashboard a copy of its layout.
- **Duplicate** opens the form for a copy, named "… (copy)", filled in from the original.
  The copy starts personal and nothing is saved until you press Save.

## On your own pages

Any page in your project can show what these pages show:

```django
{% load dashboard_tags %}
{% dashboard "site-health" %}
{% metric_card "open_tickets" period="mtd" %}
{% goal_list "weekly-ops" %}
{% card "requests_by_method" %}
{% report "monthly-kpis" %}
```

Or take the numbers and draw them your own way: `{% metric_value "open_tickets" as m %}` gives
the value, its colour state and its change; `{% goal_values "weekly-ops" as g %}` the verdicts.

The cards, numbers and drill-downs are the same ones these pages show. People who can't open
something see nothing. The **Dashboard** starter page has a working example of each.

## Sharing

Every metric, dashboard and report is either **personal** (yours; only you can
edit it) or **shared** (every signed-in user can open it; staff edit it). Only
staff can share. Staff can open anyone's personal items to help, but only the
owner edits them.

A shared dashboard can hold only shared metrics, and a personal one can hold
shared metrics and your own. It can't use someone else's personal metric.

**Sharing a personal dashboard.** Its owner can let others open it without giving it away:
**Share** in its header turns on *everyone* or adds people by name (each gets a notification).
They can view it; only the owner edits it. The badge says who it's shared with.

**Sharing a dashboard doesn't share its data.** Every dataset has its own access level, and all the
ones SmallStack bundles are staff-only, except that a hand-entered metric shows to anyone who can see
the metric. So someone without staff access who opens a shared dashboard
or goal list built on them sees *restricted* on each card, and "No numbers yet" on the goals. To give
a whole team the numbers, make them staff, or have a developer declare a dataset of your own with
`access="auth"`, which opens it to everyone signed in.

## A demo

`uv run python manage.py seed_dashboards` creates a **Site health** dashboard
and a **Monthly KPIs** report from the built-in datasets (requests, health
checks, approvals), plus a **Server error rate** metric: one metric divided by
another. It shows the metric, grouped and note cards.
