---
title: Declaring calendar datasets
order: 2
---

# Declaring calendar datasets

A calendar dataset is an ordinary `@dataset` with the calendar protocol
attached. There are two ways to declare one; both live in an app's
`datasets.py`, which SmallStack imports at startup.

## In one declaration

```python
from apps.calendar import calendar_dataset

@calendar_dataset(
    "ticket_due_dates",
    start="due_at",                 # a date or datetime column — required
    title="subject",                # chip label: attribute, dotted path or callable
    subtitle="queue.name",
    status="sla_status",            # → "success" | "warning" | "danger" | None
    access="authenticated",         # any signed-in user may see it
    label="Ticket due dates",
    description="Open tickets on the day they are due.",
    enable_api=True,
)
def ticket_due_dates(request):
    return Ticket.objects.filter(assignee=request.user, status="open")
```

Every keyword `@dataset` accepts passes straight through (`label`,
`description`, `columns`, `filterable`, `enable_api`, `enable_mcp`, `link` …).
The calendar-specific ones are:

| Keyword | Meaning |
|---|---|
| `start` | Column holding the event's start. A `DateField` makes the event all-day; a `DateTimeField` gives it a time. **Required.** |
| `end` | Column holding the end, for ranged events (windows, bookings). The chip spans every day between. |
| `title` | What the chip says. An attribute name, a dotted path (`"blog.name"`) or a callable taking the row. Defaults to `str(row)`. |
| `subtitle` | A second line in the day panel — the monitor, the queue, the cadence. |
| `status` | Resolves to `"success"`, `"warning"`, `"danger"` or `None`; tints the chip's edge and shows a dot in the day panel. |
| `access` | `"staff"` (default) or `"authenticated"`. |

`start` and `end` must be **real columns** of the dataset, because they drive
the month-window query; the protocol is checked the first time the calendar is
read and a bad column raises a clear error rather than an empty grid.

## Attached to a dataset declared elsewhere

When the dataset already exists — one of the bundled `smallstack_*` datasets,
or your own that you would rather not re-decorate — attach the protocol by key:

```python
from apps.calendar import register_calendar

register_calendar(
    "smallstack_maintenance_windows",
    start="start", end="end", title="title", subtitle="monitor_key",
)
```

One spec per dataset key: a dataset has one time axis. To plot a second column
of the same model (say, tickets by *created* date as well as by *due* date),
declare a second dataset over the model and give that its own calendar.

## Computed calendars — a provider

When the dates aren't stored anywhere — holidays worked out from rules like
"the last Monday in May", the first and last day of a long contract, a rota
that belongs on the night it starts — write the function that produces them:

```python
from apps.calendar import calendar_provider
from apps.calendar.core import CalendarEvent

@calendar_provider("company_holidays", label="Company holidays", access="authenticated")
def company_holidays(lower, upper, request):
    for name, day in resolve_holidays(lower, upper):
        yield CalendarEvent.make("company_holidays", f"{name}:{day}", name, day)
```

The function receives the day window being shown and yields events built with
`CalendarEvent.make(calendar, id, title, start, end=None, ...)`. A date start
makes an all-day event, a datetime a timed one. Keep `id` stable: it is what a
subscribed calendar app uses to update an event rather than duplicate it.
Optional keywords: `subtitle`, `status`, `url`, `cancelled` (shown struck
through, still listed) and `image` (a small picture beside the row).

A provider calendar appears everywhere a column calendar does — the page, saved
views, the events API, the `.ics` feed and the MCP tools — and has no dataset
behind it.

## Colours and weekends

Each calendar gets one of eight colours by position; pass `color=3` to pin
one. Saturdays and Sundays show by default; a site whose desk isn't staffed at
the weekend sets `SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT = False` and every
calendar opens as a work week, with a note beside the Weekends toggle counting
anything that falls on the hidden days.

## Scoping per user

A calendar with `access="authenticated"` appears for every signed-in user, so
its rows must be the user's own. The dataset function's `request` argument is
the place:

```python
def my_deadlines(request):
    return Deadline.objects.filter(owner=request.user)
```

The page, the events API, the `.ics` feed and the MCP tool all pass the
calling user's request, so one filter covers every surface.

## The bundled calendars

SmallStack attaches the protocol to eleven of its own datasets. All are
staff-only and follow the bundled datasets' switches
(`SMALLSTACK_FRAMEWORK_DATASETS_ENABLED`).

| Calendar | Dataset | Plots |
|---|---|---|
| Maintenance windows | `smallstack_maintenance_windows` | each window across the days it spans |
| Daily uptime | `smallstack_heartbeat_daily` | one entry per monitor per day, tinted against the SLA |
| Upcoming scheduled jobs | `smallstack_scheduled_jobs` | each enabled schedule on its next fire, tinted by its last run |
| Scheduled job runs | `smallstack_scheduled_job_runs` | every firing on the day it was due |
| API token expiry | `smallstack_api_tokens` | amber inside two weeks, red once past |
| Backups | `smallstack_backups` | runs on the day taken, green/red by outcome |
| Approval deadlines | `smallstack_approval_requests` | requests on the day they expire |
| Blog posts | `smallstack_blog_posts` | posts on their publish date |
| Newsletter sends | `smallstack_blog_issues` | issues on the day their send began |
| Log capture windows | `smallstack_log_capture_windows` | each window from open to expiry |
| User sign-ups | `smallstack_users` | each account on the day it joined |
