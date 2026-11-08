---
title: Building a metric
order: 2
---

# Building a metric

**Goals → Metrics → New metric** (or **New metric** on the Goals overview) opens the builder. Fill it in from top to bottom;
the **Preview** on the right shows the number, the matching row count and a
plain-English reading of the filter as you go.

## Three kinds of metric

When you create a metric, choose where its number comes from:

- **From a dataset.** Counted or added up from data the app already holds. The rest of this page
  is about these.
- **Entered by hand.** You type the values, for numbers from another tool, like CSAT or spend.
- **A rate.** One metric divided by another, like server errors ÷ all requests.

### Entering values by hand

Save the metric, then enter values on its page: a date, a value and an optional note. Each date
holds one value, so entering a date again replaces it. **Edit** and **Remove** are beside each
value. Anyone who can edit the metric can enter values, and anyone who can see it sees them.

The date decides which period and week a value counts in. **Aggregation** says how several values
in one period combine: use **Latest value** for a reading like CSAT or headcount, and **Sum** for
an amount like spend. A period with no values shows a dash, not zero.

### Rates

Pick a top number and what it's divided by. Both are read for the same period, and each week is
worked out from that week's own two numbers. Choose the **Percent** format to show it as a
percentage, and set a goal's target in the form it shows: with Percent, 2% is 2. If the bottom
number is zero the rate shows a dash. Build the two metrics first; a rate can't use another rate.

Both metrics must depend on time, or neither. A rate's page shows the two numbers it's made from.
If you delete one of them, the rate shows an error until you edit it.

## What it measures

- **Name** — what people read on the card.
- **Key** — made from the name when you save (*Open urgent tickets* →
  `open_urgent_tickets`), and shown under it. Dashboards, reports, templates and
  agents refer to the metric by its key, so it never changes, even if you
  rename the metric.
- **Dataset** — the table it reads. You only see datasets your account may read.

## Filter

Conditions decide which rows count. Each is *field · operator · value*:

| Operator | Means |
|---|---|
| is / is not | equal / not equal |
| > ≥ < ≤ | comparisons (numbers, dates) |
| between | from the first value up to the second |
| is any of | one of a list (`GET, POST`) |
| contains | text contains, ignoring case |
| is empty? | the field has no value (or has one) |
| in period | a relative period: Today, Month to date, Previous quarter, Last 30 days… |

**Match ALL / ANY** decides whether every condition must hold or any one.
**+ group** nests a block with the opposite rule, e.g. *status is open* AND
(*priority is high* OR *age > 30*).

A period inside the filter is fixed to the metric ("errors in the last 24
hours"). To let a dashboard or report choose the period, set **Period field**
instead (below).

## Roll-up

- **Aggregation** — *Count rows*, *Count distinct values* of a column, or
  *Sum / Average / Minimum / Maximum* of a numeric column (the **Measure**).
- **Period field** — the date column a dashboard's or report's period narrows.
  Leave it blank for a number that doesn't depend on time ("pending approvals").
- **Format** — Number (9,481), Compact (9.5K), Decimal, Percent, Currency
  (the Unit is the symbol), or Duration (a number of seconds as 2m 19s).
- **Unit** — shown small after the number (ms, tickets).

## Thresholds

Rules colour the card: *≥ 10 → danger*, *≥ 5 → warning*. They're checked in
order and the first match wins. States are danger (red), warning (amber),
success (green) and muted (grey). They follow the theme on every palette.

## Checking it

The preview shows the value, how many rows match and, for Today or This month and the like, the
change from the period before. **See them** opens the matching rows, exactly as you've built the
filter, even before you save. When you edit a metric that's already on dashboards or in reports,
a note above **Save** lists them: your change applies everywhere it's used.

## The stored filter

The builder saves your conditions as a small piece of JSON. You never edit
it in the form, but it's what agents and the API write, and what the metric's
page shows:

```json
{"and": [
  {"field": "status_code", "op": "between", "value": 400, "value2": 499},
  {"field": "status_code", "op": "!=", "value": 404}
]}
```

An agent's filter can use conditions the builder can't show yet, such as NOT.
The form then says so, keeps the filter unchanged when you save, and offers
**Start over with an empty filter**. Saving checks a filter
against the dataset: a field that doesn't exist, an operator that doesn't fit,
or a value that isn't a number is refused with the exact reason. A metric
whose dataset later changes under it shows an **error** on its card rather
than a wrong number.

## Showing a metric on any page

A developer can put any metric on any page with one template tag. It's the same card as on a dashboard:

```django
{% load dashboard_tags %}
{% metric_card "open_urgent_tickets" period="mtd" %}
```
