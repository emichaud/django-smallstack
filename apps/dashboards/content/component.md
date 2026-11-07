---
title: What is a component?
description: "A component is a saved card: a dataset filtered for it, or a metric for a single number, drawn by one design, built once and placed on any number of dashboards"
related: [how-it-fits, dataset, metric, dashboard, goal-list]
guide: index
---

# What is a component?

A component is a **saved card**: a filtered result and a design to draw it,
built once and placed on any number of dashboards. *Server errors as a big
number. Requests by method as a pie. Latency as a trend line.*

## What it represents

Every card that shows data starts with a dataset and a filter: the **filtered
result**. A component adds **how it looks**: the design, the split, the
colours, what opens on a tap.

A card gets its numbers in one of two ways:

- **A dataset, filtered here.** The card has a filter of its own, rolled up
  to one number or kept as rows to split or bucket. Any design.
- **A saved metric.** A metric is a filtered result already rolled up to one
  number, for targets and colour rules. Only the single-number designs take a
  metric; a split or a chart needs the rows, so it filters a dataset itself.

A dataset can be behind any number of cards, each with its own filter. One
component can sit on many dashboards; edit it and all of them update.

## The designs

| Design | Shows |
|---|---|
| **Single stat** | One number, coloured by its rules: a metric, or a filter of your own. |
| **Grouped stat** | The filtered rows split by a column: the biggest groups as numbers. |
| **Pie chart, Ranked bars** | The same split as shares of a whole, or as bars. |
| **Trend chart** | The filtered rows over time, by day, week or month. |
| **Goals** | The first goals of a goal list and how many are on target. |
| **Calendar** | Upcoming entries from one or more calendars. |
| **Info card** | A status card another part of the app publishes (staff). |
| **Note** | A heading or a few lines of text. |

Your project may add designs. A design the source can't support is dimmed in
the builder, with the reason: a trend needs a **period column** (the date
column it is read over); a metric offers only the single-number designs.

## How it's set up

**Dashboards → Components → Build a card** opens the builder, with a live
preview on the right.

1. **Where the numbers come from.** *A dataset, filtered here*: pick the
   dataset, build the filter, say how rows roll up, pick the period column.
   **Start from a metric's filter** copies a metric's definition in. Or *a
   saved metric*: pick it.
2. **Pick a design.** Picking a chart while on a metric switches to that
   metric's dataset with its filter copied in; the filter is the card's own
   from there.
3. **Say what it shows:** what the design needs, such as the column to split
   by.
4. **Style it** (optional): size, number format, unit, colours. A card over a
   metric starts with the metric's; a card with its own filter sets its own.
5. **Drill-down** (optional): the columns a tap opens, ticked and ordered
   beside the rows they'll show.
6. **Name it**, tag it, and choose **Personal** or **Shared**.

Changing the dataset clears the options that named a column of the old one
(the group-by column, the drill-down columns); the builder says which.

## How to use it

- **Place it on a dashboard:** **Edit layout → Add card → Saved card**. A
  dashboard can give it its own title.
- **Find it again** on the Components page: a gallery of live previews, or a
  table with the design, the source and where it's used; narrow it to a
  dashboard, a dataset or a design.
- **Change it where you see it:** **Edit card** in a card's **⋯** menu opens
  the same builder in a window.
- **Split one off.** A card on several dashboards is marked with a link tab;
  **Make a unique copy** makes that placement the dashboard's own.
- **Make it a goal.** A single stat over a metric has **Add to goals**: a goal
  judges a metric. A stat with its own filter is saved as a metric first; a
  split or a chart can't be a goal.

## Good to know

- **You don't need a component for every card.** **Add card** on a dashboard
  places a metric's number, a note or a calendar directly.
- **A card's own filter is its own.** Editing a metric reaches every card
  over that metric, not a card that copied its filter.
- **A shared card can only draw a shared metric.** Only staff can share.
- **Deleting a saved card doesn't empty your dashboards:** each placement
  becomes an ordinary card.
- Like a metric, a card is stored as text, so an agent can build one for you.
