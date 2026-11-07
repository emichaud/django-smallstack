---
title: How it all fits together
description: "The pieces behind Dashboards and Goals, in the order they build on each other: dataset, metric, component, then dashboards, goal lists and reports"
related: [dataset, metric, component, dashboard, goal-list, report, playlist, history]
guide: index
---

# How it all fits together

Dashboards and Goals are built from a few pieces that stack on each other. Once
you know the stack, every page under these two menus is one of its layers.

## The stack, bottom to top

| Piece | What it is |
|---|---|
| **Dataset** | A named table of data the app can read: requests, tickets, health checks. |
| **Metric** | A filtered dataset rolled up to one number: the thing you track and judge. |
| **Component** | A saved card: a dataset filtered for it (a number, a split, a chart), or a metric for a single number. |
| **Dashboard** | A grid of cards, for looking at numbers together. |
| **Goal list** | Metrics against their targets, for a regular review. |
| **Report** | Metrics down the side, periods across the top. |
| **Playlist** | Dashboards and goal lists shown one after another. |

## It starts with a dataset

A dataset sits between your data and everything else. It gives one source a
name, a list of columns and a rule for who may read it. Today every dataset
reads a database table (a Django model). The layer is there so the source can
change: a dataset could just as well read a CSV file or call an API, and
nothing built on top of it would need to know.

## A filter turns data into an answer

SmallStack's filtering works on any dataset: *status is open* AND (*priority
is high* OR *age is over 30 days*). The rows a filter leaves are the answer to
one question. One dataset can carry many filters, one for each situation you
care about.

A filtered result goes one of two ways:

- **Rolled up to one number** (count the rows, total a column, average it)
  and saved on its own, it is a **metric**: something to track, give a target
  and colour rules, and judge in a goal list.
- **Kept as rows** and drawn, it is a **chart** or a **split**: a card that
  filters the dataset itself and shows the groups or the buckets. A card can
  roll its own filter up to a single number too.

A dataset can carry any number of filtered results, some single numbers and
some lists, side by side.

## Stored as text, so it stays live

A metric doesn't keep a copy of its rows. It keeps the filter, as a small
piece of JSON text, and runs it again each time someone looks. Two things
follow:

- **The number is always current.** There is nothing to refresh or rebuild.
- **An AI agent can build it.** Writing a filter is writing text, so an agent
  can make the metrics, components and dashboards you describe in plain
  language, when you need them. Cards and dashboard layouts are stored the
  same way.

## What you do with a metric

- **Show it.** A single-stat card draws it, and a dashboard collects cards
  into one view: metrics you track closely beside charts that filter their
  data themselves. A playlist rotates dashboards on a wall screen.
- **Judge it.** A goal list gives each metric a target and says whether it is
  on target, at risk or missed. This is the KPI review: the page a team reads
  down in its weekly meeting.
- **Compare it.** A report lines metrics up across periods, such as this month
  against last month. It is another way to analyse the same numbers.
- **Keep it.** A capture saves a goal list's numbers as they stood when a week
  (or a day, or a month) ended, so the record holds even when the data changes
  later.

## Where to find each piece

- **Goals** in the sidebar has the numbers: Metrics, Goal lists and Reports.
- **Dashboards** has how they are shown: dashboards, Components and Playlists.
- **Datasets** is under Admin, for staff. You can browse and filter any dataset
  there, and turn a filtered table into a metric.

## Who sees what

Each piece is **personal** (yours) or **shared** (everyone signed in can open
it, and staff edit it). Sharing a dashboard does not share its data: a dataset
has its own access rule, and a card over data you can't read shows
*restricted*.
