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
remove it. Each has its own colour, and the swatch stays the same colour
whether or not it is selected, so a saved view looks the same every time you
open it. **All** and **None** are there for the extremes. The count under a
selected calendar is how many of its events fall in the visible month.

With nothing selected the grid is empty on purpose — the calendar does not
guess what you want to see.

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

## Who sees what

Calendars have an access level. The bundled SmallStack calendars plot operator
data (token expiry, approval deadlines, backups) and are **staff-only**. A
project calendar can be opened to every signed-in user; such a calendar should
scope its rows per user, which the dataset's `request` argument makes a
one-liner. A user never sees a calendar they may not open, in the picker or
through the API.
