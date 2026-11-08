---
title: What is a dataset?
description: "A dataset is a named, filterable table of data: the layer between a data source and the metrics, cards and reports built on it"
related: [how-it-fits, metric, component]
guide: building-metrics
---

# What is a dataset?

A dataset is a named table of data that the app is allowed to read and filter:
*Requests*, *Heartbeats*, *Approval requests*, your own *Tickets*. Every
number in Dashboards and Goals starts as rows in a dataset.

## What it represents

A dataset is a layer between a data source and everything that uses it. It
says three things about the source:

- **What it's called**, so people and agents can find it.
- **Which columns it has**, and what kind each is: text, a number, a date, a
  yes/no.
- **Who may read it**: staff only, or everyone signed in.

Today every dataset reads a database table (a Django model). The layer is
there so that can change. A dataset could read a CSV file or call an API
instead, and the metrics and dashboards built on it would carry on as before,
because they only ever talk to the dataset.

## What it does

A dataset can be **filtered**. That is its whole job. A filter is a set of
conditions on the columns, joined by AND and OR:

> *status code is 500 or more* AND *path contains /api/*

The rows a filter leaves are a **filtered result**: the answer to one
question. A dataset can have any number of these, one for each situation you
want to watch (errors, slow requests, sign-ups this month). Rolled up to one
number and saved, a filtered result is a **metric**, for goals and reports.
Kept as rows, it is what a **chart** or a **split** draws: a card that filters
the dataset itself. Both kinds can sit side by side over the same dataset.

Columns come in two kinds, and it helps to know which is which:

- **Dimensions** are things you filter and group by: a status, a method, a
  date, a person.
- **Measures** are numbers you can add up or average: a response time, an
  amount.

## How it's set up

Datasets are declared in code, by a developer, in a few lines (`@dataset` in
an app's `datasets.py`). Nothing is copied: the dataset reads the source
directly, so its rows are always the current ones. SmallStack ships about
thirty of its own, covering requests, logs, health checks, scheduled jobs,
webhooks, approvals and more. All of those are **staff-only**, except `metric_entries` (the values typed
into hand-entered metrics), which is open to everyone signed in but shows
each person only the metrics they can see. A dataset
declared with `access="auth"` is open to everyone signed in.

You don't create or edit a dataset in the browser. What you make in the
browser is what sits on top of one.

## How to use it

- **Browse it.** Staff can open **Datasets** (under Admin) to see every
  dataset, page through its rows, search them and add filters.
- **Turn a filter into a metric.** On a dataset's page, set the filters you
  want and choose **Make a metric**. The conditions carry over, and from there
  a card or a chart can start from the same filter.
- **Copy one you already have.** **Start from a metric**, above the filters,
  loads a saved metric's conditions. Change them, then **Make a metric** saves
  a copy and leaves the original alone.
- **Or start from the metric.** **Goals → Metrics → New metric** asks which
  dataset to read, then lets you build the filter there, with a live preview
  of the number.
- **Download it.** A filtered table downloads as CSV.

## Good to know

- You only see datasets your account may read. A shared dashboard over a
  staff-only dataset shows *restricted* to everyone else.
- If a dataset's columns change, a metric that used a missing column shows an
  error on its card, never a wrong number.
- Agents see datasets through the same door: they list them, read their
  columns, then write filters over them.
