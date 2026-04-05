# Skill: Calendar Displays

`CalendarDisplay` renders a queryset as a month-grid calendar. It's a peer to `TableDisplay` and `CardDisplay` — any model with a date or datetime field can opt in with one line.

## When to use

Use `CalendarDisplay` for models where time-on-a-calendar is the primary way users reason about the records:

- Maintenance windows, outages, scheduled downtime
- Reservations, bookings, appointments
- Events, releases, milestones
- Tasks or tickets with due dates

If the model has no natural date field, use `TableDisplay` or `CardDisplay` instead.

## Usage

Add `CalendarDisplay(...)` to `explorer_displays` (or `crud_displays` on a `CRUDView`):

```python
from apps.smallstack.displays import TableDisplay, CalendarDisplay

class MaintenanceWindowAdmin:
    list_fields = ["title", "start", "end", "status"]

    explorer_displays = [
        TableDisplay,
        CalendarDisplay(date_field="start", end_field="end", title_field="title"),
    ]
```

Users switch between Table and Calendar via the display toggle in the list-page header.

### Single-date events

Omit `end_field` for point-in-time events:

```python
CalendarDisplay(date_field="due_date", title_field="title")
```

### Ranged events

Include `end_field` to stretch an event across every day it spans:

```python
CalendarDisplay(date_field="start", end_field="end", title_field="title")
```

## Config reference

| Kwarg | Required | Default | Purpose |
|-------|----------|---------|---------|
| `date_field` | yes | — | Model field for event start. Date **or** datetime — datetimes are converted to local date. |
| `end_field` | no | `None` | For ranged events. Stretches the event chip across every day in the range. |
| `title_field` | no | `str(obj)` | What appears on the event chip. Attribute name, dotted path, or callable. |
| `status_field` | no | `None` | Resolves to `"success"`, `"warning"`, `"danger"`, or `None` — event chips are tinted green/yellow/red accordingly. Use for outcome signals (SLA, pass/fail, severity). |
| `variant` | no | `"chip"` | `"chip"` for a list of small event chips per day (meetings, windows); `"block"` for one large prominent colored block per day (daily stats, status boards). |
| `month_param` | no | `"month"` | URL query-string parameter used for month navigation (e.g. `?month=2026-03`). |

### Chip vs block variant

Two layouts for two use cases:

- **`variant="chip"`** (default) — small stacked chips, title-first. Multiple events per day. Use for event lists: meetings, maintenance windows, reservations.
- **`variant="block"`** — one large colored block per day with a big prominent title (percentages, counts, statuses). Use for daily status/stat calendars where each day has one outcome and you want immediate at-a-glance recognition.

```python
# Event list — small chips
CalendarDisplay(date_field="start", end_field="end", title_field="title")

# Daily status — big colored blocks
CalendarDisplay(
    date_field="date",
    title_field=lambda d: f"{float(d.uptime_pct):.2f}%",
    status_field="sla_status",
    variant="block",
)
```

### Status colors

Set `status_field` to a model property or callable that returns one of `"success"`, `"warning"`, `"danger"` (or `None` for the default primary tint). The event chip is tinted with the theme's paired alert colors (`--success-bg/fg`, `--warning-bg/fg`, `--error-bg/fg`) — muted greens, yellows, and reds that work in both light and dark mode.

```python
# On the model
class HeartbeatDaily(models.Model):
    ...
    @property
    def sla_status(self):
        if (self.ok_count + self.fail_count) == 0:
            return None
        target, minimum = HeartbeatEpoch.get_sla_targets()
        uptime = float(self.uptime_pct)
        if uptime >= float(target):
            return "success"
        if uptime >= float(minimum):
            return "warning"
        return "danger"

# In explorer.py
CalendarDisplay(
    date_field="date",
    title_field=lambda d: f"{float(d.uptime_pct):.1f}% uptime",
    status_field="sla_status",
)
```

**Where to compute status:** prefer a model property or queryset annotation over a lambda closure. Properties keep the display config declarative and are reusable from the API, detail views, and tables. Lambdas are fine for quick formatting of the title but aren't great for domain logic.

## Behavior

- **Efficient filtering** — the queryset is narrowed to events that *overlap* the visible month. Large tables stay fast.
- **Month navigation** — prev/next arrows, "Today" button, and a title like "APRIL 2026" render in the header automatically.
- **Navigable URL** — `?month=YYYY-MM` is shareable / bookmarkable. Invalid values fall back to the current month.
- **Event chips** — click a chip to open the object's detail page (when the `DETAIL` action is enabled on the CRUD config).
- **Hover tooltip** — each chip shows title + start (and end, if ranged) on hover.
- **Timezone-aware** — datetime fields are converted to local time via `timezone.localtime()` before bucketing.
- **Today highlight** — the current day cell gets a `calendar-cell--today` class with `--primary`-mix background.
- **Monday-start** — week grid starts on Monday. Leading/trailing cells outside the month are blank.
- **No bulk-select** — `supports_bulk = False`, so the bulk-action toolbar is hidden when the calendar is active.

## Example output

```
┌────────────────────────────────────────────────────────────────────┐
│  ‹  APRIL 2026  ›                        4 MAINTENANCE WINDOWS     │
├──────┬──────┬──────┬──────┬──────┬──────┬──────────────────────────┤
│ MON  │ TUE  │ WED  │ THU  │ FRI  │ SAT  │ SUN                      │
├──────┼──────┼──────┼──────┼──────┼──────┼──────────────────────────┤
│      │      │  1   │  2   │  3   │  4 ● │  5                       │
│      │      │      │      │      │ [DB  │                          │
│      │      │      │      │      │ main │                          │
│      │      │      │      │      │ t]   │                          │
├──────┼──────┼──────┼──────┼──────┼──────┼──────────────────────────┤
```

## Data flow

```
queryset → filter to visible month → bucket by day → weekly grid
              |                         |
       date/end overlap            _to_local_date()
```

Each event dict the template receives:

```python
{
    "title": "DB maintenance",   # from title_field
    "detail_url": "/...",        # None if DETAIL action disabled
    "pk": 42,
    "start": datetime(...),      # raw value, for tooltip
    "end": datetime(...),        # raw value or None
    "status": "success",         # from status_field, or None
}
```

## Styling

All calendar CSS lives under `.calendar-*` in `apps/smallstack/static/smallstack/css/components.css`. It uses theme variables (`--body-fg`, `--body-bg`, `--primary`, `--card-border`, `--hairline-color`) — works in every palette and in dark mode with zero overrides.

Cell sizing is controlled by `.calendar-grid { grid-auto-rows: minmax(68px, auto) }`. Override in your own CSS if you need taller/shorter cells.

## Authoring a new date-based display

`CalendarDisplay` is a reference implementation of the "author your own list display family" pattern. To build a week view, gantt view, or timeline view, follow the same recipe:

1. **Subclass `ListDisplay`** (not `CardDisplay`)
2. Set `name`, `template_name`, `supports_bulk = False`
3. Accept field-name kwargs in `__init__` (`date_field`, `end_field`, `title_field`, etc.)
4. In `get_context()`: filter queryset → shape the data → return a dict your template consumes
5. Use the helpers: `_resolve_field()`, `_to_local_date()`, `CardDisplay._resolve_detail_url()`

Unlike `CardDisplay`, you don't need `item_template` dispatch unless your layout has sub-variants.

## Files

| Path | Role |
|------|------|
| `apps/smallstack/displays.py` | `CalendarDisplay` class, `_to_local_date()` helper |
| `apps/smallstack/templates/smallstack/crud/displays/calendar.html` | Month-grid template |
| `apps/smallstack/static/smallstack/css/components.css` | `.calendar-*` styles |
| `apps/heartbeat/explorer.py` | Reference usage: `MaintenanceWindowAdmin.explorer_displays` |

## Related skills

- `card-displays.md` — sibling list display family (cards vs calendar)
- `crud-views.md` — `ListDisplay` protocol, `crud_displays` attribute
- `explorer.md` — `explorer_displays` attribute on admin classes
- `timezones.md` — how datetimes get converted to local time
