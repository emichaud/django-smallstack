---
title: What is a dashboard?
description: "A dashboard is a grid of cards over your metrics: how to read one, how to build one, and who can see it"
related: [how-it-fits, component, metric, playlist, goal-list]
guide: index
---

# What is a dashboard?

A dashboard is a **grid of cards** that puts related numbers on one page:
*Site health*, *Support this week*, *Sales*. Each card shows a metric, and the
page as a whole answers "how are we doing?" at a glance.

## What it represents

A dashboard is a collection. It holds no data of its own: every card re-reads
its metric each time the page opens, so what you see is current. Some cards
are there for information (traffic, a calendar, a note). Others are numbers
you track closely, coloured by their rules so a problem stands out.

Think of it as an arrangement. The metrics define the numbers, the components
decide how each looks, and the dashboard decides which ones sit together and
where.

## Reading one

- **The period bar** (top left) narrows every card that depends on time:
  Today, This week, Last week, This month and more. A card whose metric has
  no date ignores it.
- **Tap a number** to open the rows behind it, and download them as CSV. On a
  split or a chart, each group or bar opens its own rows.
- **The small grey change** under a number compares it with the period
  before. It's grey on purpose: whether up is good depends on the metric.
- **Restricted** on a card means the dashboard is shared with you but that
  card's data isn't.
- A dashboard set to refresh reloads its cards on its own. **Refresh** does
  it now.

## How it's set up

**Dashboards → New dashboard** asks for a name, who can see it, the period it
opens on and whether it refreshes by itself. Then, on the dashboard, choose
**Edit layout**:

1. **Add card** and pick a type: a **Saved card** from Components, or a
   Single stat, Gauge, Goals, Calendar, Menu, Info card or Note made on the
   spot. Charts and grouped stats are built under Components.
2. **Drag** cards to move them, and drag a corner to resize. The grid is
   twelve columns wide.
3. **Remove** takes a card off. Its metric stays.
4. **Save layout**, or **Cancel** to throw the changes away.

**Settings** changes the name, picture, tags, default period and refresh, and
lists every card with its design, metric and current value.

You don't have to rearrange to change one card. Point at it and open the **⋯**
at its corner: **Edit card** opens its builder right there, over the dashboard,
and **Remove** takes it off.

## How to use it

- **Open it in a meeting**, on *Last week* rather than *This week*: a week
  still running looks low for any number that only goes up.
- **Put it on a wall.** Add it to a **playlist** and it rotates with other
  dashboards and goal lists.
- **Start from one you have.** **Duplicate** opens a copy to change. On the
  copy, a card's **Make a unique copy** gives it its own metric, so its
  filter can change without touching the original.
- **Show it on another page of your project** with `{% dashboard "slug" %}`
  in a template.
- **Ask an agent for one.** A dashboard's layout is stored as text, so an
  agent can build the metrics, the cards and the layout from a description.

## Good to know

- **Personal or shared.** A personal dashboard is yours. A shared one opens
  for everyone signed in, and staff edit it. Only staff can make those.
- **Share your own.** **Share** on a personal dashboard lets everyone who can
  sign in open it, or people you name (each gets a notification). You still
  edit it; they read its cards as you do, and find it under **Shared with
  you** on My dashboards.
- **Sharing a dashboard doesn't share its data.** Each dataset has its own
  access rule, so the same dashboard can show numbers to one person and
  *restricted* to another.
- **A shared dashboard holds only shared metrics and cards.** A personal one
  can hold shared ones and your own.
- **My dashboards** lists the ones you made, and the ones shared with you.
  The **Dashboards** overview shows every one you can open.
- Deleting a dashboard leaves its metrics and saved cards alone.
