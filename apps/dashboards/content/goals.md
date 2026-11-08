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

## Printing

**Print** on a goal list opens a document of what's on screen, for the period you're looking at,
and then your browser's print dialog. It has the summary, what needs attention and each section's
goals, with no menus. Status is written out, so it reads fine in black and white. **Print** on a
single week prints that week.

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

**Saving weeks.** While a list tracks weeks, which new lists do, the week just ended is saved
automatically early on Monday, with each goal's value, status and the target it had. This
needs [the scheduler](/smallstack/help/smallstack/scheduler/) and a background worker (`manage.py db_worker`)
running. Changing a target later doesn't rewrite a saved week, unless you save
that week again, which uses the targets of that moment.

A week that hasn't been saved is worked out when you look at it, against today's
targets. If you can edit the list, **Save this week** saves the week you're on, and
**Save them**, under *Save past weeks that have no snapshot yet*, fills in earlier ones.
Saving part-way through a week doesn't stop that week being saved again when it ends.

A week is saved using the access of the list's owner (or its creator, for a shared
list). If you can't read a metric's data, you still won't see its saved values.

A value entered by hand after a week was saved adds a new capture of that week, so it's fine to type
last week's numbers on Monday morning. It keeps the target the week was saved with, and the earlier
capture stays on the History page.

## History: tracking at other rhythms

**History** on a goal list shows what's captured and lets you choose what to track: **hourly**,
**daily**, **weekly**, **monthly** or **quarterly**, in any combination. Each tracked period is
captured automatically once it ends. New lists track weekly. Turning a rhythm off keeps what it
captured.

Choose a tab to see goals down and periods across. A blank means nothing was captured then.
**Open** shows one period and every capture of it, newest first, with who or what took each.
Saving again adds a capture rather than replacing the last, so you can see what the numbers said at
each point. Pages show the newest. **Capture this week so far** saves the period you're in, marked as
part-way through; the capture when it ends still happens. **Fill in** saves earlier periods with no
finished capture, and **Print this capture** prints one.

### Targets at each rhythm

A goal's main target fits a week. A count doesn't read the same over an hour, so "at least 1,000
requests" would show every hour as missed. Under a goal in the editor, **Targets by cadence** sets
a target and at-risk line for any rhythm. If you leave one blank:

- **Weekly** uses the main target.
- **A count or a total** shows its value marked **No target**, and isn't counted as on target or
  missed.
- **An average, a rate or a latest reading** uses the main target, because it reads the same at any
  length.

Captures keep the target they were judged against, so changing a target later doesn't change them.
The meeting view uses the main target, whichever period you pick.

### Numbers that don't fit a period

Not every number can be read at every rhythm. Where one can't, its cell shows **n/a**.

- **One that doesn't depend on time**, like open tickets right now, is captured as it stands. This
  is the way to keep a history of a number like that. It can't be filled in for past periods.
- **One with only dates**, like a value entered by hand, has no hourly value, rather than showing the
  whole day's number against each hour.

Hourly and daily captures are deleted after 90 days and 2 years. Weekly, monthly and quarterly ones
are kept.

## On a dashboard and in a playlist

On a dashboard, choose **Edit layout → Add card → Goals**, pick the list, and
choose up to 10 goals to show, as listed or with misses first. The card's headline
counts the whole list, and it's judged over the dashboard's period.

In a playlist, pick the goal list under **Slides, in order**, then choose what it
shows: **Goals now**, **Last week** (the week just ended, as saved), or **Week over
week** (the grid). Links to the playlist
work as usual. See [Playlists](/smallstack/help/dashboards/playlists/).

## Renaming and deleting

- Renaming a list keeps its address, so links to it go on working. If an administrator changes the
  address itself (in the list's settings), playlists and Goals cards that show it follow,
  but any link or bookmark you saved to the old address stops working.
- Deleting a list removes it from playlists and dashboards.
- Deleting a metric removes its goals from the lists you can edit, and the
  confirmation counts them. A list you can't edit keeps the goal, shown as no data.
- Deleting a single stat card keeps its goals, now on the card's metric.
