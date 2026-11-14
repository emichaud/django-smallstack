---
name: calendar
description: "Put anything with a date on a calendar — the calendar protocol over @dataset (@calendar_dataset / register_calendar: start/end columns, title/status resolvers, access), the merged /smallstack/calendar/ grid with saved views, the events + .ics API, MCP tools, the eleven bundled calendars, and a calendar on any page ({% calendar_card %}, the calendar dashboard card)"
license: MIT
metadata:
  source: "docs/skills/calendar.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/calendar.md` by `make skills-index` — edit the source, not this file.

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
MCP: list_calendars, calendar_events, event_skip_date, + the generated *_event and *_calendar_view tools
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

**Or compute the events yourself** — a **provider** replaces the column
protocol for dates that are derived rather than stored (holidays from
recurrence rules, the start/end milestones of a long-lived record, a rota
folded onto the night it starts, a mirror of another system). No dataset, no
model:

```python
from apps.calendar import calendar_provider
from apps.calendar.core import CalendarEvent

@calendar_provider("company_holidays", label="Company holidays", access="authenticated", color=5)
def company_holidays(lower, upper, request):          # the half-open day window
    for name, day in resolve_holidays(lower, upper):
        yield CalendarEvent.make("company_holidays", f"{name}:{day}", name, day)
    yield CalendarEvent.make("company_holidays", "offsite", "Offsite",
                             start_dt, end_dt, subtitle="Grand Rapids", cancelled=True)
```

`CalendarEvent.make(calendar, id, title, start, end=None, *, subtitle, status,
url, cancelled, image)` — a `date` start is all-day, a `datetime` is timed; `id`
must be stable (it is the ICS UID). Core stamps the calendar key and label,
drops anything outside the window, sorts and caps, so a provider may over-read.
`register_calendar(key, provider=fn, …)` is the non-decorator form. A provider
calendar has no `window_queryset()`; `count()` materialises its events.

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
- **`cancelled`** and **`image`** are optional resolvers: a cancelled event
  stays on the board struck through (and goes out as `STATUS:CANCELLED` in the
  ICS feed) because a cancelled window is still information; `image` is a URL
  drawn as a small round face beside the row (a person, a logo).
- **`color=N`** pins the calendar to one of the eight `--series-N` tokens;
  unpinned calendars fill the remaining slots in list order (`assign_series`).
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
`weekends=0|1` hides or shows Sat/Sun (a five-column grid, weekend days
dropped from the board; totals unchanged). The default is the
`SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT` setting, so a work-week site needs no
parameter. Two honesty rules from the board's first user: entries that fall on
hidden weekend days are **counted and announced** beside the toggle
(`weekend_hidden` / `core.weekend_entries`), never dropped silently; and a week
column with **no visible day in range** is dropped (a window opening on a Sunday
with weekends hidden), while a week in range with nothing booked keeps its
"Nothing scheduled" column — those are different statements. The right column groups the day's events by calendar
(`core.group_by_calendar`, series order). Saved views are a `<select>` sorted
A–Z whose options carry the current window. Precedence: explicit `ds`
> `view` > the user's default view (only when there are **no** params) > the Events calendar.
An explicit empty `ds=` means "none" and is emitted by the None link so the
state round-trips. A `view` whose selection has been changed by `ds` is
treated as modified (links carry `ds`, the view loses its highlight).

Colours: `core.assign_series` gives each visible calendar a stable 1-based
index into the theme's **`--series-1…8`** tokens (in `core.css`, which `theme.css` imports, for
exactly this: categorical, light + dark variants, never surfaces or state).
Position is by `visible_calendars` order (project calendars A–Z, then bundled
A–Z), so a calendar keeps its colour whether or not it is selected. Status
tints the chip's left edge with the semantic vars and adds a dot in the panel.

Grid CSS reuses the `.calendar-*` classes from `components.css`; the page's
own rules are `.cal-*` in `apps/calendar/static/calendar/css/calendar.css`.

## A calendar on any page — `{% calendar_card %}` and the dashboard card

The one-line form, the calendar counterpart of `{% metric_card %}` /
`{% dashboard %}` in `dashboards.md`. Name the calendars; the embed does the
rest — access, events, colours, navigation:

```django
{% load calendar_tags %}
{% calendar_card "ticket_due_dates" %}                                  {# this month, loaded lazily #}
{% calendar_card "ticket_due_dates,smallstack_events" mode="upcoming" days=7 limit=5 title="Due soon" %}
{% calendar_card view mode="board" lazy=False %}                        {# a SavedCalendarView, rendered now #}
{% calendar_card "smallstack_events" title=False weekends=False month="2026-04" %}
```

**On a theme of your own** (a base template that doesn't extend `smallstack/base.html`): put `{% smallstack_assets %}` in its `<head>` and `{% smallstack_modal %}` before `</body>`, with the theme scripts `adding-your-own-theme.md` lists. The calendar brings `calendar.css`; those two bring the tokens (`--series-1…8` among them) and components it shares. `/starter/own-theme/` in the showcase is a working example.

| Arg | Meaning |
|---|---|
| `calendars` | a key, comma-separated keys, a list, or a `SavedCalendarView` |
| `mode` | `month` (default: the grid, a clicked day listed beneath it), `board` (the 30/60/90-day board with its toolbar and day column), `upcoming` (the next `days` days as a compact list — the dashboard card's default) |
| `title` | the heading; defaults to the calendar's label (or "N calendars"), `False` for screen-reader-only. It links to the page opened on the same calendars |
| `lazy` | `True` (default) loads the fragment over htmx; `False` renders it now (email, tests, a page with no script) |
| `days`, `limit` | the upcoming list's window and row cap; `days` also seeds the board (snapped to 30/60/90) |
| `weekends`, `month` | seed the month grid (`month` is a date or `YYYY-MM`) |

**How it works.** The tag resolves the keys for `request.user` with
`core.resolve_keys` — a key the viewer may not see is dropped exactly like an
unknown one, and with none left the tag **emits nothing**, so a page never
reveals a calendar exists (the `{% dashboard %}` rule). Otherwise it renders
`calendar/includes/embed.html`: the stylesheet, the heading, and a body that
`hx-get`s **`/smallstack/calendar/embed/`** (`views.CalendarEmbedView`) with
the state in its query string (`ds`, `mode`, `month`, `range`/`from`/`day`/
`weekends`, `days`, `limit`). The fragment's wrapper carries
`hx-boost="true" hx-target="this" hx-swap="outerHTML" hx-push-url="false"`,
so every link inside it — month arrows, day cells, the board's range and
weekend toggles, the day column's × — fetches the fragment and swaps it in
place; **the host page's URL never changes**, and with no script the links
still work (they are ordinary links to the fragment). Links that open a page
(an event's own URL, "Open in Calendar") carry `hx-boost="false"`. Nothing
inline: the CSP's `script-src` is `'self'`, and `test_embed.py` asserts no
calendar template carries a handler or an inline block.

**The service, for your own markup** (`apps/calendar/embed.py`):

```python
from apps.calendar.embed import calendar_embed, embed_context, build_upcoming

embed = calendar_embed(request, "a,b", mode="upcoming", days=7, lazy=False)
# None when the viewer may see none of them; else
# {keys, cals, mode, url (the fragment URL), html (rendered, or None when lazy), page_url, label}
```

`embed_context(request, cals)` is what the fragment renders from (the
request's query string is the state); `build_upcoming(events, lower, upper,
today, limit)` groups any `CalendarEvent` list by day for
`calendar/components/upcoming.html` — the fourth component, beside the grid,
the board and the day column.

**On a dashboard.** The calendar app registers a **`calendar` card type**
with the dashboards registry from its `ready()` — the same
`register_component_type` call a downstream app makes, so it doubles as the
worked example (`apps/calendar/dashboard_cards.py`). Pick it in the dashboard
editor or place it from an agent:

```python
{"type": "calendar", "x": 0, "y": 0, "w": 4, "h": 4, "title": "Due soon",
 "options": {"calendars": "ticket_due_dates,smallstack_events", "mode": "upcoming", "days": 14, "limit": 8}}
```

Options are `calendars` (comma-separated keys — validated to exist when the
layout is saved), `mode`, `days`, `limit`. In the component builder and a
dashboard's **Add card** dialog, `calendars` is a tick-list of the calendars
the person may see (`dashboard_cards.calendar_choices`, a `multichoice`
option), so nobody types a key; an agent reads the same keys and labels from
`list_dashboard_components`. The card renders the fragment
eagerly inside the dashboard's own lazy cell and navigates in place like the
tag; a viewer who may see none of its calendars gets the restricted card
("You don't have access to this card's calendars"), one who may see some
gets those. The card ignores the dashboard's period bar — a calendar has its
own navigation — so `use_period` is moot for it. Its stylesheet rides on
`media={"css": ["calendar/css/calendar.css"]}` through `{% component_media %}`.

**Linked to other cards.** With `"publish": "<channel>"` in its options, a click on
a day (the month grid's cells, the board's day heads, the upcoming list's days;
keyboard too) narrows the cards listening on that channel to that day instead of
opening the calendar page; events inside a day still open their own links. The
day travels on the field `date`, which a listener reads as its own period column
(or the column its `listen.map` names). The type declares `publishes=True` and the
templates mark days with `data-day` / `data-day-label`. See *Linked cards* in
`dashboards.md`.

## Reusing the components on another page

When the tag's shapes don't fit, go one level down. The four renderers are
partials under `templates/calendar/components/` (`month_grid.html`,
`range_board.html`, `day_column.html`, `upcoming.html`), driven only by
`CalendarEvent` rows, and the first three are wrapped in template tags:

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

### The Events and Saved views pages

The calendar's own CRUD pages do not use the generic explorer table and
form. `EventCRUDView.displays` starts with `AgendaDisplay` (rows grouped by
month, a tear-off *leaf* per entry) beside `CalendarDisplay` and
`RangeBoardDisplay`; `SavedCalendarViewCRUDView.displays` is
`[SavedViewsDisplay]` (rows with the view's calendars as colour-swatched
chips). The form, detail and delete templates live under
`apps/calendar/templates/smallstack_calendar/crud/` — the per-app CRUD
template seam (`{app_label}/crud/{model}_{suffix}.html`) — so a project
overrides any one of them by shipping a file at the same path earlier in
`TEMPLATES` / app order. The shared pieces are `calendar/crud/_leaf.html`
(also the `{% event_leaf obj "lg" %}` tag), `calendar/crud/_field.html`
and the `.cal-form` / `.cal-agenda` / `.cal-choices` rules in
`calendar/css/calendar.css`. Follow the same pattern for a downstream
calendar-shaped model: reuse `_leaf.html` and the `.cal-*` form classes
rather than the explorer defaults.

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

## The Events calendar (`models.Event` + `views.EventCRUDView`)

The one bundled calendar a person types into. `Event` is all-day by default
with optional `start_time`/`end_time`, an inclusive `end_date` for spans, a
`category`, `location`, `url`, a `cancelled` flag and a two-step `visibility`
(*members* = everyone signed in, the default; *private* = author and staff).
`EventCRUDView` at `calendar/events/` is `LoginRequiredMixin` + `enable_api` +
`enable_mcp` (so an agent can `create_event`); `datasets.visible_events(user)`
is the one read scoper (list, detail, the calendar provider, the dataset);
`can_update`/`can_delete` = author or staff — and **`check_object_permission`
is what enforces it**: `can_update` only decides which buttons render, so a
CRUDView that stops there still accepts a non-author's POST to `…/edit/`. The
check raises `PermissionDenied` on the edit/delete routes (any method) and on
every non-GET, which covers HTML, REST and the MCP tools at once; the form
stamps `created_by`.

It is registered **twice under one key**, `smallstack_events`: a
`framework_dataset` (rows for the browser/reports) and a **provider** calendar
(`datasets.events_provider`), because a date column plus optional time columns
is two shapes in one table — the provider emits all-day or timed events as the
row dictates. `access="authenticated"`, `spans=True`. The list page carries its
own Table ⇄ Calendar ⇄ Board toggle via the displays.

### Repeating events

A series is one `Event` row with `repeat` (`daily`, `weekdays`, `weekly`, `biweekly`, `monthly`,
`monthly_weekday`, `yearly`), an optional `repeat_until`, and `skip_dates`. `events_provider`
expands it per window through `recurrence.occurrence_starts`, so nothing is stored per date and an
open-ended series costs nothing. Each occurrence's id is `<pk>-<yyyymmdd>`, which keeps its ICS UID
stable, and its URL carries `?on=<date>`.

Edits apply to the whole series. To move one date, skip it (`POST calendar/events/<pk>/skip/`, or
`event_skip_date` over MCP) and add a separate event. Occurrences exist on the calendar surfaces
only: the `smallstack_events` dataset, and the Events list with its calendar and board tabs, read
the row, so a series counts once there and those tabs show its first date.

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
| `SMALLSTACK_CALENDAR_WEEKENDS_DEFAULT` | `True` | Whether Sat/Sun show when a page says nothing — False for a work-week desk. |
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
| **Events** (hand-entered) | `smallstack_events` | provider over `Event` rows; `access="authenticated"` |

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
   "datetime")]` on the dataset) and point `start` at it — or, if the dates
   are genuinely computed, write a `@calendar_provider`.
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
| `apps/calendar/views.py` | the page, `CalendarEmbedView` (the fragment), `SavedCalendarViewCRUDView`, `EventCRUDView` |
| `apps/calendar/embed.py` | `calendar_embed`, `embed_context`, `build_upcoming` — behind `{% calendar_card %}`, the fragment and the dashboard card |
| `apps/calendar/dashboard_cards.py` | the `calendar` dashboard card type (the downstream-style `register_component_type` example) |
| `apps/calendar/templatetags/calendar_tags.py` | `{% calendar_card %}`, `{% calendar_month %}`, `{% calendar_board %}`, `{% calendar_day %}`, `{% event_leaf %}` |
| `apps/calendar/api.py` | list / events / per-calendar / `.ics` routes, `render_ics` |
| `apps/calendar/mcp_tools.py` | `list_calendars`, `calendar_events` |
| `apps/calendar/templates/calendar/index.html` · `static/calendar/css/calendar.css` | the page |
| `apps/calendar/templates/calendar/includes/embed.html` · `embed_body.html` · `cells/calendar.html` | the embed shell, the fragment, the dashboard cell |
| `apps/calendar/content/` | help pages at `/smallstack/help/calendar/` |
| `apps/*/datasets.py` | the bundled `register_calendar` calls |
