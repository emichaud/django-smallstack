---
title: Calendar
order: 1
---

# Calendar

The calendar at **Calendar** in the sidebar (`/smallstack/calendar/`) puts
every dataset that has a date axis onto one month grid. Maintenance windows,
scheduled jobs, token expiry dates, blog publish dates — anything the project
has declared as a *calendar dataset* can be switched on, alone or together,
and the mix saved under a name.

## The ladder: CRUDView → dataset → calendar dataset

A model gets admin pages from a CRUDView. A **dataset** over it makes it a
typed, filterable table that reports, exports and agents can read. A
**calendar dataset** is that same dataset plus a small protocol: which column
is the event's start, optionally which is its end, and how to label the chip.
Nothing is copied — the calendar reads the dataset's rows, so the dataset's
own per-user scoping and links apply.

## Picking calendars

The list on the left is additive. Click a calendar to add it; click again to
remove it. Each has a colour of its own while few are on (with many, some share one), and the swatch stays the same colour
whether or not it is selected, so a saved view looks the same every time you
open it. **All** and **None** are there for the extremes. The count under a
selected calendar is how many of its events fall in the visible month.

The first time you open it the **Events** calendar is on, so anything you add
shows up straight away. **None** clears the grid, and a saved view you've marked
as the default opens instead.

## Month, or 30 / 60 / 90 days

The control above the grid switches between the **month** grid and a
**day-range board**. The board shows the next 30, 60 or 90 days as one column
per week, each listing its days with an entry card per event — the shape a
schedule reads best in when you care about *what's coming* rather than *which
weekday*. The arrows move by a whole range; **Today** snaps back. The
**Weekends** box hides Saturdays and Sundays in both shapes.

## The grid and the day panel

Events sit on every day they touch; a maintenance window from Friday night to
Saturday morning shows on both days. Timed events show their start time on
their first day. A cell lists up to four events and then a **+N more** count.

The **right-hand column** lists the selected day: every event on it, with its
calendar, its times, any subtitle (the monitor, the blog, the cadence), and a
status dot — green, amber or red — where the dataset reports one. It starts on
today when today is in the visible month; **click any day** to switch it. An event's title links to the record's own page when the dataset knows
where that is.

Use the arrows to move month to month; **Today** jumps back. The selection
travels with you.

## Saving a view

Once you have a selection worth keeping, **Save this view** names it. Saved
views sit in the dropdown at the top of the Calendars list (A–Z) and under
**Saved views**, where you can rename, re-pick or delete them. Mark one as the **default** and the calendar
opens with it whenever you visit with no view chosen.

Views are yours alone. Another user with the same access can be sent the
page's URL instead — every state of the page is a link.

## The Events calendar — the one you type into

Every other calendar here is derived from data the system already holds. The
**Events** calendar is for the rest: a closure, a conference, a release, an
onboarding week. **Add event** in the page header opens the form; all-day by
default, with optional start and end times and an inclusive end date for a
span. An entry is visible to everyone signed in unless you mark it *private*
(then only you and staff see it), can be edited by its author or by staff, and
can be marked **cancelled** to stay on the calendar struck through rather than
disappearing. The entries page (**All events**, under the calendars on the left, or `/smallstack/calendar/events/`) lists them with its own
Table ⇄ Calendar ⇄ Board toggle, and the same entries are available over REST
and MCP, so an agent can file one for you.

### Repeating events

Choose **Repeats** on an event: every day, weekday, week, 2 weeks, month or year, and optionally
a last date under **Until**. For a month, choose the same date or the same weekday, like the 2nd
Tuesday. The first day sets the pattern, and each date shows on the calendar and in subscribed
calendars. The 31st falls on the last day of a shorter month, and a 5th weekday becomes the last one.
**Last day** is how long each one lasts, so leave it blank for a one-day event; **Until** is when the
series ends.

Editing the event changes every date. To skip one, open it from the calendar and choose **Skip this
date**. To move one, skip it and add a separate event. Skipped dates are listed on the event, where
you can put them back. The Events list shows a series once, under its first date, and so do its
calendar and board tabs. The main calendar shows every date.

## Who sees what

Calendars have an access level. The bundled SmallStack calendars plot operator
data (token expiry, approval deadlines, backups) and are **staff-only**. A
project calendar can be opened to every signed-in user; such a calendar should
scope its rows per user, which the dataset's `request` argument makes a
one-liner. A user never sees a calendar they may not open, in the picker or
through the API.

## On a dashboard

A **Calendar** card puts one or more calendars on a dashboard: the upcoming
entries, a month, or a 30/60/90-day board. Add it with **Edit layout → Add
card → Calendar** and tick the calendars it shows. Each viewer sees only the
calendars they may open.

A calendar card can also drive other cards. Give **Send clicks to** a name (in
the Add card dialog, or under **Linked cards** in **Edit card**); a card whose
**Listen to** is that name then narrows to whichever day you click, e.g. the
requests made that day. Click the
✕ on the narrowed card to go back.
