# Calendar — datasets with a date axis on one month grid (`apps/calendar/`)

**Read this** before putting anything on a calendar: a due date, an expiry, a
maintenance window, a release, a run. The app label is `smallstack_calendar`;
the package is `apps.calendar` (the stdlib `calendar` module is unaffected —
`apps/` is a package, and the app's own code imports the stdlib one as
`pycal`).

> **Prerequisites**: [`datasets.md`](datasets.md) — a calendar dataset *is* a
> dataset. [`calendar-displays.md`](calendar-displays.md) is the per-CRUDView
> month view (one model, a display toggle); this app is the merged, saveable,
> API-backed calendar across many datasets.

## The ladder: CRUDView → dataset → calendar dataset

```
CRUDView           a model gets list/detail/edit pages (+ REST + MCP)
  └─ @dataset      the same rows as a typed, filterable table (schema/rows/series)
       └─ calendar protocol   which column is the start, optionally the end,
                              how to title/tint a chip, who may see it
```

A **calendar dataset** is a `DatasetDef` plus a `CalendarSpec` keyed by the
same dataset key (`apps/calendar/registry.py`). Nothing is copied: the
calendar reads rows through `Dataset.queryset()` (so the dataset's per-user
scoping and filter pipeline apply) and row links through `Dataset.link_for`.
One spec per dataset — a dataset has one time axis. Two columns of one model
(created vs due) → two datasets, two calendars.

```
/smallstack/calendar/                       the page: picker + grid + day panel   (login)
/smallstack/calendar/views/…                saved views CRUD                     (login, owner-scoped)
/smallstack/api/calendar/views/             saved views REST                     (login, owner-scoped)
/smallstack/calendar/api/                   calendars the caller may see         (Bearer or session)
/smallstack/calendar/api/events/            merged events  ?ds=&ds=&start=&end=
/smallstack/calendar/api/events.ics         the same window as an iCalendar feed
/smallstack/calendar/api/<key>/events/      one calendar
MCP: list_calendars, calendar_events, + the generated *_calendar_view tools
```

## Declare one

```python
from apps.calendar import calendar_dataset

@calendar_dataset(
    "ticket_due_dates",
    start="due_at",                 # date/datetime COLUMN — required
    end=None,                       # a second column for ranged events
    title="subject",                # attr | dotted path | callable(obj)
    subtitle="queue.name",
    status="sla_status",            # → "success" | "warning" | "danger" | None
    access="authenticated",         # default "staff"
    label="Ticket due dates", description="…", enable_api=True,   # → @dataset
)
def ticket_due_dates(request):
    return Ticket.objects.filter(assignee=request.user, status="open")
```

Or attach the protocol to a dataset declared elsewhere:

```python
from apps.calendar import register_calendar
register_calendar("smallstack_maintenance_windows", start="start", end="end", title="title")
```

Both go in an app's `datasets.py` (autodiscovered with `views.py`). Rules:

- **`start`/`end` are column names** of the dataset, typed `date`/`datetime`
  by the dataset's own `columns()`. They drive the month-window query. The
  protocol is validated lazily (`CalendarDataset.validate()`) and raises
  `CalendarProtocolError` naming the bad column — never an empty grid.
- **`title`/`subtitle`/`status` are per-row resolvers** (the same
  `_resolve_field` CalendarDisplay uses): attribute, dotted path, or callable.
  A property on the model beats a lambda (reusable from tables/API).
- **A `DateField` start ⇒ all-day**; a `DateTimeField` ⇒ timed (localised to
  the active timezone). Ranged events are inclusive of every local day they
  touch, exactly as `CalendarDisplay` buckets them.
- **`access`** is the visibility rule: `staff` (default; all bundled
  calendars) or `authenticated`. `core.can_view` → staff see everything,
  signed-in users see `authenticated` ones, anonymous nothing. A key the user
  may not see is reported as *unknown*, not forbidden (existence doesn't leak).
  An `authenticated` calendar **must scope its rows per user** via the dataset
  function's `request` arg — every surface passes the calling user's request.
- A spec whose dataset never registered (bundled set off, typo) is simply
  absent from `iter_calendars()`; `get_calendar(key)` returns `None`.

## The normalised event (the contract every surface shares)

```python
{"calendar": key, "id": pk, "title": str, "subtitle": str,
 "start": ISO, "end": ISO | None, "all_day": bool,
 "status": "success" | "warning" | "danger" | None, "url": str | None}
```

In-process it is `core.CalendarEvent` (plus `start_date`/`end_date` local
dates). Build on `core`, not on the views:

```python
from apps.calendar.core import get_calendar, collect_events, visible_calendars, month_bounds

cal = get_calendar("smallstack_backups")
lower, upper = month_bounds(date(2026, 4, 1))          # half-open [first, next first)
cal.events(lower, upper, request)                      # → [CalendarEvent] sorted by start
cal.window_queryset(lower, upper, request)             # the overlap-filtered QuerySet
events, counts, capped = collect_events(visible_calendars(user), lower, upper, request)
```

`collect_events` caps each calendar at `WINDOW_LIMIT` (2000) rows per window
and reports which hit the cap; the page shows `N+` rather than a silently
partial month.

## The page (`views.CalendarPageView`)

Everything is in the query string, so every state is a link: `ds` (repeatable
or comma-separated) picks calendars; `view=<pk>` loads a saved selection;
`range=30|60|90` switches from the month grid to the **day-range board**
(`core.build_range_board`: one column per Monday-start week, days with events
only, entries counted per day touched) anchored on `from=YYYY-MM-DD` (default
today, arrows move by the range); `month=YYYY-MM` moves the grid;
`day=YYYY-MM-DD` selects the day shown in the right-hand column (default today
when in the window — `panel_day`; only an explicit `day` outlines a cell);
`weekends=0` hides Sat/Sun (a five-column grid, weekend days dropped from the
board; totals unchanged). The right column groups the day's events by calendar
(`core.group_by_calendar`, series order). Saved views are a `<select>` sorted
A–Z whose options carry the current window. Precedence: explicit `ds`
> `view` > the user's default view (only when there are **no** params) > none.
An explicit empty `ds=` means "none" and is emitted by the None link so the
state round-trips. A `view` whose selection has been changed by `ds` is
treated as modified (links carry `ds`, the view loses its highlight).

Colours: `core.assign_series` gives each visible calendar a stable 1-based
index into the theme's **`--series-1…8`** tokens (added to `theme.css` for
exactly this: categorical, light + dark variants, never surfaces or state).
Position is by `visible_calendars` order (project calendars A–Z, then bundled
A–Z), so a calendar keeps its colour whether or not it is selected. Status
tints the chip's left edge with the semantic vars and adds a dot in the panel.

Grid CSS reuses the `.calendar-*` classes from `components.css`; the page's
own rules are `.cal-*` in `apps/calendar/static/calendar/css/calendar.css`.

## Reusing the components on another page

The three renderers are partials under `templates/calendar/components/`
(`month_grid.html`, `range_board.html`, `day_column.html`), driven only by
`CalendarEvent` rows, and wrapped in template tags:

```django
{% load static calendar_tags %}
<link rel="stylesheet" href="{% static 'calendar/css/calendar.css' %}">

{% calendar_month events cursor selected_day=day weekends=False %}   {# the month of `cursor` #}
{% calendar_board events lower upper selected_day=day %}              {# week columns for [lower, upper) #}
{% calendar_day events day explicit=True %}                            {# one day, grouped by calendar #}
```

Build `events` however you like — `collect_events(cals, lower, upper, request)`
for registered calendars, or `core.events_from_objects(qs, start=…, end=…,
title=…, status=…, url_for=…, calendar_label=…)` for any queryset — then
`colourise(events, assign_series(cals))` if you want per-calendar colours.
Day selection is a link: cells and headings point at the **current URL with
`?day=YYYY-MM-DD`** (`core.day_url`), so the host view reads `day` from its
own query string and passes it back as `selected_day`. The shared page
(`views.CalendarPageView`) renders through these same partials.

**On a CRUDView** list page, add the board beside the month view with no
template at all — `apps.calendar.displays.RangeBoardDisplay` is a `ListDisplay`
sibling of `CalendarDisplay`:

```python
from apps.calendar.displays import RangeBoardDisplay

displays = [
    TableDisplay,
    CalendarDisplay(date_field="scheduled_for", title_field="job_name", status_field="calendar_status"),
    RangeBoardDisplay(date_field="scheduled_for", title_field="job_name",
                      subtitle_field="message", status_field="calendar_status", days=30),
]
```

The list page gains a Table ⇄ Calendar ⇄ Board toggle; the board reads
`?display=board&range=30|60|90&from=&day=&weekends=0`, filters the queryset
to the window with `core.window_filter`, and shows the day column beside the
columns. Rows link to the detail page when the CRUDView has `Action.DETAIL`.
`backward=True` ends the window today instead (the last N days — right for
history such as newsletter sends). Live examples: the scheduler's jobs and run
history, the maintenance-window explorer, and the blog's posts and issues.

**On a hand-rolled page**, read the state with `core.RangeWindow.from_request`
(same parameters, `backward=` for history), build events for `win.lower` →
`win.upper`, and include the all-in-one component:

```python
win = RangeWindow.from_request(request, days=30, backward=True)
rows = window_filter(qs, "updated_at", None, win.lower, win.upper)
ctx = win.context(events_from_objects(rows, start="updated_at", title="title", url_for=lambda d: d.get_absolute_url()))
```
```django
{% include "calendar/components/board.html" with count_label="documents updated" %}
```

The runbook's documents page does exactly this behind its Table | Board toggle.

## Saved views (`models.SavedCalendarView` + `views.SavedCalendarViewCRUDView`)

`owner`, `name` (unique per owner), `datasets` (JSON list of keys),
`is_default` (one per owner, enforced in `save()`). The CRUDView is
`LoginRequiredMixin` + `get_list_queryset` owner scoping, `enable_api` +
`enable_mcp`. The form (`forms.SavedCalendarViewForm`) replaces the JSON
textarea with a checkbox list of the **viewer's** visible calendars — the
narrowed choices *are* the validation, so a non-staff user cannot store a
staff key on any surface (HTML, REST, MCP all build the form with `user=`).
The owner is stamped in `form.save()`, not `on_form_valid` (which fires after
the insert; owner is NOT NULL). `?datasets=a,b` prefills a new view — the
page's **Save this view** link.

## Settings

| Setting | Default | Effect |
|---|---|---|
| `SMALLSTACK_CALENDAR_ENABLED` | `True` | Off ⇒ no nav, no routes, no MCP tools, no widget. Specs still register; `core` keeps working in-process. |
| `SMALLSTACK_CALENDAR_MAX_WINDOW_DAYS` | `366` | Widest window one events/ICS/MCP request may ask for. |
| `SMALLSTACK_FRAMEWORK_DATASETS_ENABLED` | `True` | Off ⇒ the eleven bundled calendars vanish with their datasets. |

## Bundled calendars

Attached in each module's `datasets.py` via `register_calendar` (all staff):

| Calendar | Key | Axis |
|---|---|---|
| Maintenance windows | `smallstack_maintenance_windows` | `start`→`end` |
| Daily uptime | `smallstack_heartbeat_daily` | `date`, status `sla_status` |
| Upcoming scheduled jobs | `smallstack_scheduled_jobs` | `next_run_at`, status `calendar_status` |
| Scheduled job runs | `smallstack_scheduled_job_runs` | `scheduled_for`, status `calendar_status` |
| API token expiry | `smallstack_api_tokens` | `expires_at`; warning ≤14 days, danger past |
| Backups | `smallstack_backups` | `created_at`; success/failed |
| Approval deadlines | `smallstack_approval_requests` | `expires_at`; pending=warning |
| Blog posts | `smallstack_blog_posts` | `published_at` |
| Newsletter sends | `smallstack_blog_issues` | `started_at` |
| Log capture windows | `smallstack_log_capture_windows` | `started_at`→`expires_at` |
| User sign-ups | `smallstack_users` | `date_joined` |

The app's own saved views are a bundled dataset too (`smallstack_calendar_views`).

## Testing

`apps/calendar/tests/`. Seed with aware datetimes near **noon UTC** so the
local day (project TZ `America/New_York`) is the one you assert on; a 02:00
UTC stamp lands on the previous local day. `BackupRecord.created_at` is
`auto_now_add` — set it with `.update()` after `create()`. Register throwaway
calendars with `calendar_dataset` and clean up with **both**
`apps.calendar.registry.unregister` and `apps.datasets.registry.unregister`.

## Anti-patterns

1. **A callable `start`.** It cannot be filtered in the DB; the month window
   would mean a full scan. Declare an annotated column (`columns=[(name,
   "datetime")]` on the dataset) and point `start` at it.
2. **Hard-coding per-calendar colours.** Use the `--series-N` tokens through
   `.cal-series-N`; they carry light/dark variants and stay palette-neutral.
3. **Opening a bundled calendar to `authenticated`.** They plot operator data
   (tokens, approvals, users) and are unscoped; declare your own scoped
   dataset instead.
4. **Reading `SavedCalendarView.datasets` raw.** Use `.keys` — the JSON column
   is untyped and a hand-edited value must not crash the page.
5. **Summing events client-side for a count.** `CalendarDataset.count(lower,
   upper)` is one `COUNT(*)`; the widget uses it.

## Files

| Path | Role |
|---|---|
| `apps/calendar/registry.py` | `CalendarSpec`, `register_calendar`, `calendar_dataset` (stdlib-only imports) |
| `apps/calendar/core.py` | `CalendarDataset`, `CalendarEvent`, access, windows, `build_month_grid` |
| `apps/calendar/views.py` | the page + `SavedCalendarViewCRUDView` |
| `apps/calendar/api.py` | list / events / per-calendar / `.ics` routes, `render_ics` |
| `apps/calendar/mcp_tools.py` | `list_calendars`, `calendar_events` |
| `apps/calendar/templates/calendar/index.html` · `static/calendar/css/calendar.css` | the page |
| `apps/calendar/content/` | help pages at `/smallstack/help/calendar/` |
| `apps/*/datasets.py` | the bundled `register_calendar` calls |
