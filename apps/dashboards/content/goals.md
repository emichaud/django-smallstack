---
title: Goals
order: 3
---

# Goals

A goal list puts your key numbers against the targets they should reach, in
sections, so a meeting can read straight down it. Each goal is **on target**,
**at risk** or **missed**, and a summary at the top says how many of each and
which ones need attention.

Find them under **Goals** in the sidebar: **Overview** shows every list's summary and
the metrics behind them, **Goal lists** is the full list. A *shared* goal list is the team's:
everyone signed in can open it and staff edit it. A *personal* one is yours.

## How a goal is judged

A goal is one number (a metric, or a single stat card) and a rule:

| The value… | Status |
|---|---|
| meets the **target** | On target |
| doesn't, but meets the optional **at-risk** line | At risk |
| meets neither | Missed |
| has no number (no access, or the metric can't be evaluated) | No data |

A rule is *at least*, *more than*, *at most*, *less than*, *exactly*, *not* or
*between*. For a target of "at most 300 ms" with an at-risk line of "less than
800 ms", 250 is on target, 500 is at risk and 900 is missed.

Goals with no number are left out of the count, so "6 of 8 on target" means six
of the eight goals that have a number.

A count of nothing is 0, so a goal on "failed jobs" reads as on target while no job has run at
all. An average with no rows has no number, and reads as *no data*.

## Making a list

1. Choose **New goal list**, give it a name, and choose the period the goals are
   judged over. For a team's list, choose **Shared** under *Who can see it*: it can
   then only hold shared metrics and cards.
2. Add a section (Reliability, Traffic…) and add goals to it.
3. For each goal, pick the metric or card and set its target. A metric with colour
   rules fills these in for you when its rules include a success rule.
4. Move goals by dragging the handle, or with ↑ and ↓. Both also move a goal into
   another section. Sections move with their own ↑ and ↓.
5. To put a section in order quickly, click a column heading: Goal, Target, At risk
   or Period. This sorts that section's goals and changes the order they're read
   in. **Undo** puts them back, and nothing changes until you save. Columns can be
   dragged wider or narrower, and all the sections' columns move together.

A goal can also have its own label, a note (who owns it, say) and its own period,
which it keeps whichever period the page is showing.

## Adding from a metric or a card

**Add to goals** is on a metric's page, its edit page and the metrics list, and on
saved single stat cards in the components list and the builder. A metric or card
needs saving first. Pick a list and a section (typing a new name starts a new
section at the end), check the target, and it's added.

Only cards that boil down to one number can be goals. A grouped stat can't.

## In the meeting

- **Change the period** with the links above the summary. *Last week* is usually the one to
  read: *This week* is still running, so a count that only goes up looks on target early on.
- **Choose Present** to drop the site's menus and make everything larger, for a
  shared screen.
- **Click a value** to see the rows behind it.
- **Click a name under Needs attention** to jump to that goal.

## The trend

Each goal shows its last six periods as small bars, each coloured by how that
period did against the target. The period still running is outlined. The size
of each period follows the list's: days for today or yesterday, weeks for this or last
week or 7 days, quarters for this or last quarter or 90 days, years for this or last year,
months otherwise. When the latest finished periods share a
status, the goal says so, for example *Missed 3 weeks running*.

## Week by week

**Weeks** does what a spreadsheet with one tab per week does. Find it on a goal
list's page (top right), beside each list on the Goals overview, or as the calendar
icon in the Goal lists table.

- **One week** shows a week (Monday to Sunday) like the meeting view, with each
  goal's change from the week before. Move with the arrows or pick a week; ● marks
  a saved week.
- **Week over week** puts goals down the side and weeks across, eight at a time.
  **Download CSV** gives you the same table for a spreadsheet.
- **Trends** on any week (the button in the grid's column headers, or
  **Trends around this week**) shows the four weeks before it and the weeks
  since, for each goal:
  - a bar per week;
  - that week's value against the week before, and against the average of the
    weeks before;
  - the run it's on, and its best and worst week.

**Saving weeks.** Every Monday the week just ended is saved automatically (this needs
the scheduler and a background worker running), with each goal's value, status and the
target it had. Changing a target later doesn't rewrite a saved week, unless you save
that week again, which uses the targets of that moment.

A week that hasn't been saved is worked out when you look at it, against today's
targets. If you can edit the list, **Save this week** saves the week you're on,
and **Save past weeks** fills in earlier ones.

A week is saved using the access of the list's owner (or its creator, for a shared
list). If you can't read a metric's data, you still won't see its saved values.

A value entered by hand after a week was saved updates that saved week, so it's fine to type last
week's numbers on Monday morning. The week keeps the target it was saved with.

## On a dashboard and in a playlist

On a dashboard, choose **Edit layout → Add card → Goals**, pick the list, and
choose up to 10 goals to show, as listed or with misses first. The card's headline
counts the whole list, and it's judged over the dashboard's period.

In a playlist, pick the goal list under **Slides, in order**, then choose what it
shows: **Goals now**, **Last week** (the week just ended, as saved), or **Week over
week** (the grid). Links to the playlist
work as usual. See [Playlists](/smallstack/help/dashboards/playlists/).

## Renaming and deleting

- Renaming a list's address updates playlists and Goals cards that show it, but any
  link or bookmark you saved to the old address stops working.
- Deleting a list removes it from playlists and dashboards.
- Deleting a metric removes its goals from the lists you can edit, and the
  confirmation counts them. A list you can't edit keeps the goal, shown as no data.
- Deleting a single stat card keeps its goals, now on the card's metric.
