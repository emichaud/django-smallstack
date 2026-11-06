---
title: Weeks, captures and history
description: "How a goal list keeps its numbers as they stood when a week, day or month ended: captures, saved weeks, week over week, and trends"
related: [goal-list, how-it-fits, metric, playlist]
guide: goals
---

# Weeks, captures and history

A metric is always live: it reads the data as it is now. That's right for
today, and wrong for a record. A **capture** saves a goal list's numbers as
they stood when a period ended, so last week's review still says what it said
last week.

## What it represents

A capture is a snapshot of one goal list for one period: each goal's value,
its status, and the target it was judged against. Three things make it a
record you can trust:

- **It keeps the target of the moment.** Changing a target later doesn't
  rewrite a saved week.
- **Nothing is overwritten.** Saving a period again adds a new capture beside
  the old one. Pages show the newest, and History keeps them all.
- **It survives the data changing.** Rows get edited, closed and deleted.
  The capture holds the number as it was.

This is what a spreadsheet with one tab per week does by hand.

## How it's set up

**Weekly capture is on from the start.** Every Monday the week just ended is
saved automatically. This needs the scheduler and a background worker
running.

**History**, on a goal list's page, is where you choose what else to track:
**hourly**, **daily**, **weekly**, **monthly** or **quarterly**, in any
combination. Each tracked period is captured once it ends. Turning a rhythm
off keeps what it captured.

A week that was never saved is worked out when you look at it, against
today's targets. If you can edit the list, **Save this week** saves the one
you're on, and **Save past weeks** fills in earlier ones.

A target that suits a week often doesn't suit an hour. In the goal list's
editor, **Targets by cadence** sets a target for each rhythm.

## How to use it

**Weeks** (top right of a goal list) has three views:

- **One week** shows a week, Monday to Sunday, like the meeting view, with
  each goal's change from the week before. A dot marks a saved week.
- **Week over week** puts goals down the side and weeks across, eight at a
  time, and downloads as CSV.
- **Trends** takes one week and shows the four before it and the weeks since,
  for each goal: a bar per week, that week against the one before and against
  the average, the run it's on, and its best and worst week.

**History** shows the same grid at any tracked rhythm. **Open** on a period
lists every capture of it, newest first, with who or what took each.

In a **playlist**, a goal list slide can show *Last week* exactly as it was
saved, or the *Week over week* grid.

## Good to know

- **A number that doesn't depend on time**, like *open tickets right now*, is
  captured as it stands. Capturing is the only way to keep a history of a
  number like that, and it can't be filled in for the past.
- **Values entered by hand can arrive late.** Typing last week's number on
  Monday morning adds a new capture of that week, with the target the week
  was saved with.
- **A capture uses the access of the list's owner.** If you can't read a
  metric's data, you still won't see its saved values.
- **Old fine-grained captures are cleared out:** hourly ones after 90 days,
  daily ones after 2 years. Weekly, monthly and quarterly ones are kept.
- A blank cell means nothing was captured for that period.
