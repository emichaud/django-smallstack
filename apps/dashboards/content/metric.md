---
title: What is a metric?
description: "A metric is a saved filter over a dataset, rolled up to one number: the reusable unit behind every card, goal and report row"
related: [how-it-fits, dataset, component, goal-list, report]
guide: building-metrics
---

# What is a metric?

A metric is one number with a definition: *open urgent tickets*, *server
errors*, *average response time*. It is the thing you track: build it once and
it can sit on any number of dashboards, goal lists and reports, with a target
to judge it by.

## What it represents

A metric is a **saved filter over a dataset**, plus a way to roll the matching
rows up into one value:

- **Which rows:** the filter. *Status code is 500 or more.*
- **How to roll them up:** count them, count distinct values, or take the sum,
  average, median, minimum or maximum of a number column. For skewed numbers
  like response times or deal sizes, the median is the typical value; a few
  large ones pull the average up.

It does not store the rows or the answer. It stores the question, as a small
piece of JSON text, and asks it again every time someone looks. That is why a
metric is always current, and why an agent can write one: a metric is text.

A dataset can have many metrics. Each is a different question about the same
data.

## How it's set up

**Goals → Metrics → New metric** opens the builder. From top to bottom:

1. **Name** it. A permanent **key** is made from the name; dashboards and
   agents refer to the metric by that key, so renaming is safe. A
   **description** says what it counts; it shows when someone hovers the
   metric's name in a list.
2. Pick the **dataset**.
3. Build the **filter**: conditions joined by ALL or ANY, with nested groups.
4. Choose the **aggregation**, and the measure column if it needs one.
5. Set the **period field**: the date column that a dashboard's or report's
   period narrows, and that a trend chart buckets by. Leave it blank for a
   number that doesn't depend on time, like *pending approvals*; such a metric
   can't be drawn over time.
6. Choose a **format** (number, compact, decimal, percent, currency, duration) and a
   **unit**.
7. Add **colour rules** if you want them: *10 or more is danger, 5 or more is
   warning*. The first rule that matches colours the number.

The preview shows the value and how many rows match as you go, and **See
them** opens those rows before you save.

You can also start on a dataset's page: filter its rows and choose **Make a
metric**. **Start from a metric** there loads one you have, to copy with
changes.

Two other kinds skip the filter. A metric **entered by hand** holds values
you type, for numbers that live in another tool. A **rate** is one metric
divided by another, such as errors ÷ requests.

## How to use it

- **On a dashboard:** add a card and pick the metric, or build a
  **component** from it first to control how it looks. A metric goes on the
  designs that show one number; a split or a chart filters a dataset of its
  own, and can start from the metric's filter.
- **In a goal list:** give it a target. **Add to goals** is on the metric's
  page and in the metrics list.
- **In a report:** add it as a row to compare it across periods.
- **On its own page:** see its value by period, the rows behind it, and every
  dashboard, report and goal list that uses it.
- **On any page of your project:** `{% metric_card "key" %}` in a template.

## Good to know

- **Editing a metric changes it everywhere.** The form lists where it's used
  before you save.
- **A card over a metric takes its format, unit and colour rules from it**,
  unless the card overrides them. A card that copied the metric's filter is on
  its own from then on: editing the metric doesn't reach it.
- **Deleting** shows what would break (cards, report rows, goals) and removes
  them in the same step unless you say otherwise.
- **Personal or shared.** A shared dashboard, report or goal list can only use
  shared metrics.
- A metric can be tagged, duplicated and archived. Archiving takes it out of
  lists and pickers but keeps it working wherever it's already used.
