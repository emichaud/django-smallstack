# Dashboards — metrics, grid dashboards and KPI reports (`apps/dashboards/`)

**Read this** before building a KPI, a dashboard, or a metrics report — or before
letting an AI agent build one. The app label is `smallstack_dashboards`; pages
live under `/smallstack/dashboards/`.

> **Prerequisite**: [`datasets.md`](datasets.md). Every number here is a
> `@dataset` rolled up through a stored **filter tree** (the "Filter trees"
> section there is the grammar). For a one-off tile computed in a view, the
> lower-level [`dashboard-cards.md`](dashboard-cards.md) `{% stat_card %}` is
> still right.

## The model — three nouns, all JSON an agent can write

```
@dataset ──(filter_tree + agg)──▶ Metric ──▶ Dashboard cell   (grid, period bar, refresh)
                                         └─▶ Report row        (metrics × periods, CSV)
                                         └─▶ {% metric_card %}  (any template)
```

| Model | What it is | Key fields |
|---|---|---|
| **Metric** | A named, stored filter over a dataset rolled up to one value — the KPI. The reusable unit. | `key` (stable slug), `dataset`, `filter_tree`, `agg`, `measure`, `period_field`, `format`, `unit`, `thresholds` |
| **Dashboard** | A grid of cards. | `slug`, `layout` (list of cells), `default_period`, `refresh_seconds` |
| **Report** | Metrics × periods as a table (+ CSV). | `slug`, `items` (`[{metric, label?}]`), `periods` (`["mtd", "pmtd", "ytd"]`) |

All three: `owner` blank = **shared** (staff edit, every signed-in user views);
set = **personal** (owner edits, staff view). `can_view` / `can_edit` on the
model is the one rule — views, REST and MCP never re-derive it. Every model
calls `full_clean()` in `save()`, so a bad filter, a cell pointing at a
missing metric, or a malformed threshold is refused on **every** surface.

## A metric

```python
Metric(
    key="open_urgent",
    name="Open urgent tickets",
    dataset="tickets",                      # a @dataset key
    filter_tree={"and": [
        {"field": "status", "op": "=", "value": "open"},
        {"field": "priority", "op": "in", "value": ["high", "urgent"]},
    ]},
    agg="count",                            # count | distinct | sum | avg | min | max
    measure="",                             # the column for non-count aggs
    period_field="created_at",              # a dashboard/report period narrows this; blank = never
    format="number",                        # number | compact | decimal | percent | currency | duration
    unit="tickets",
    thresholds=[{"op": ">=", "value": 10, "state": "danger"},
                {"op": ">=", "value": 5, "state": "warning"}],   # first match wins
).save()
```

**Evaluate** with the one seam — `apps.dashboards.metrics.evaluate(metric, request, period=None)`
→ `MetricResult(value, display, unit, state, error, restricted, summary, period_label, problems)`.
Cards, cells, reports, REST and MCP all call it, so a number means the same
thing everywhere. Outside a view, `request_for(user)` builds a request.

- **period**: when a period key is given *and* the metric has a `period_field`,
  a `{"field": period_field, "op": "period", "value": period}` leaf is AND-ed
  on. A metric with no `period_field` is unaffected (a report shows it once,
  marked n/a in the other columns, rather than repeating one number).
- **thresholds** → `state` ∈ `success | warning | danger | muted` — the
  stat-card states, so the colour comes from the theme on every palette.
- **failure is explicit**: an unknown dataset or a filter that no longer
  compiles gives `error` (+ `problems`) and **no value** — never the
  unfiltered count. A viewer the dataset doesn't admit gets `restricted`.

### A metric's source — dataset, by hand, or a rate

`Metric.source` says where the number comes from. Everything downstream goes through
`metrics.evaluate`, `weeks.weekly_values` and `trends.metric_trend`, so cards, goals,
reports and weeks need no special cases.

| `source` | Fields you set | What the model sets |
|---|---|---|
| `dataset` (default) | `dataset`, `filter_tree`, `agg`, `measure`, `period_field` | |
| `manual` | `agg`: `latest` (default), `sum`, `avg`, `min`, `max` | `dataset="metric_entries"`, `measure="value"`, `period_field="date"`, and a filter fixed to its own entries |
| `rate` | `numerator`, `denominator` (metric keys) | blank `dataset`, and `period_field` copied from the numerator |

**By hand.** One `MetricEntry` per metric per date. Write through `entries.record_entry` /
`entries.delete_entry`, the one seam for the page, REST and MCP, because it also refreshes a
saved week. `metric_entries` is an `access="auth"` dataset whose rows are scoped to the metrics
the viewer can see. An empty period is `None`, never 0, even for `sum`.

**Rates.** `format="percent"` multiplies by 100. The parts can't be rates themselves, must be
different metrics, and must both be period-aware or both not. A rate reads as restricted unless
the viewer can open both parts and read both datasets. It has no rows, so `drill_rows` raises and
the rows modal links to the parts. Deleting a part leaves the rate showing an error, and
`metric_usage(...)["rates"]` lists them first.

A manual metric or a rate can't back a card that groups by a column (`requires={"dimension"}`).

## Access — who sees the number

A dashboard being visible doesn't make its numbers visible. Each card checks
the metric's **dataset `access` tier** (`@dataset(..., access="staff"|"auth")`,
default `staff`) against the viewer: a member opening a shared dashboard sees
"restricted" on a staff-dataset card, and the drill-down 404s. Forms
(HTML/REST/MCP) only offer — and only accept — datasets the user may read, so
a non-staff user can't build a metric over a staff dataset. Only staff may
share (`visibility: "shared"`); omitting `visibility` on an edit keeps the
current setting.

## A dashboard layout

```json
[
  {"id": "intro", "type": "text", "x": 0, "y": 0, "w": 12, "h": 1, "options": {"markdown": "**Support desk**"}},
  {"id": "open",  "type": "metric", "metric": "open_urgent", "x": 0, "y": 1, "w": 3, "h": 2},
  {"id": "byq",   "type": "metric_group", "metric": "open_tickets", "x": 3, "y": 1, "w": 6, "h": 2,
   "options": {"dimension": "queue", "limit": 5, "other": true}},
  {"id": "users", "type": "widget", "x": 9, "y": 1, "w": 3, "h": 2,
   "options": {"widget": "apps.api.dashboard_widgets.APIDashboardWidget"}},
  {"id": "mtd",   "type": "metric", "metric": "open_urgent", "use_period": false, "x": 0, "y": 3, "w": 3, "h": 2}
]
```

12-column grid (gridstack.js, vendored); `w` 1–12, `h` 1–12 rows of 70px;
`x + w ≤ 12`. `id`, `w`, `h`, `x`, `y` may be omitted (the size from the type's
default; a cell with neither `x` nor `y` goes after the cards so far). Cells may not overlap. `use_period: false` pins a cell to all-time regardless of the
period bar. Cells load lazily over htmx (`hx-trigger="load[, every Ns]"`), so
one slow card doesn't block the page and `refresh_seconds` is free.

### Built-in card types

| `type` | Shows | Options |
|---|---|---|
| `metric` | one stat card — the exact `{% stat_card %}` markup; click → the rows behind it | — |
| `metric_group` | the metric split by a column: top N groups, biggest first, each drilling into its rows and showing its change from the previous period; an `Other` folds the tail for additive aggs (count/sum) only | `dimension` (req), `limit` 1–12, `other` |
| `widget` | an existing `DashboardWidget` from `/smallstack/` (staff only) | `widget` (class path — `list_dashboard_components` lists them) |
| `text` | markdown (rendered by the hardened `render_markdown`; raw HTML is escaped) | `markdown` (required) |
| `goals` | a goal list's summary and first goals | `goal_list`, `limit`, `order` |
| `calendar` | upcoming entries, a month or a board (registered by `apps/calendar`) | `calendars`, `mode`, `days`, `limit` |

### Card types — a small framework set, open to apps

| Type | Label | Palette group | Draws |
|---|---|---|---|
| `metric` | Single stat | Stats | one metric's value, threshold state, drill-down |
| `metric_group` | Grouped stat | Stats | a metric split by `options.dimension`: top N (+ "Other"), each value drillable |
| `widget` | Info card | Info | a published `DashboardWidget` (the `/smallstack/` cards; staff only) |
| `text` | Note | Info | markdown |

Charts belong to apps. The grouped stat on the sample dashboard is `metric_group`:
`build_metric_group` calls `metrics.group_values(metric, dimension, limit)`, which runs
the metric's filter and aggregate grouped by the column, keeps the top `limit`, and
folds the rest into "Other". Each value carries a `narrow` filter, so clicking it opens
exactly its rows.

### Adding your own card type (the extension seam)

**The working reference is `apps/website/dashboard_cards.py`**, a "Trend chart"
registered from `WebsiteConfig.ready()`. It lives in the project's app, not in
SmallStack, because SmallStack's built-in cards stay stats and info cards:

```python
# myapp/apps.py  ready()
from apps.dashboards.components import ComponentType, cell_title, register_component_type
from apps.dashboards.trends import metric_trend

def build_trend(cell, ctx):                # ctx: CellContext(request, dashboard, metric, period)
    trend = metric_trend(ctx.metric, ctx.request, ctx.period, cell["options"].get("grain"))
    return {"label": cell_title(cell) or ctx.metric.name, "trend": trend}   # cell_title: placement or saved-card name

register_component_type(ComponentType(
    key="trend", label="Trend chart", description="A metric over time",
    template="myapp/cells/trend.html", build=build_trend,
    needs_metric=True, default_size=(6, 3),
    requires=frozenset({"date"}),          # dataset capabilities; the builder dims the tile otherwise
    validate=validate_trend,               # cell -> [problems]; runs on every save, every surface
    group="Charts",                        # the builder palette section
    icon="M3.5 18.5l6-6 4 4L22 6.92…",     # a 24x24 SVG path for the palette tile
    media={"js": ["myapp/vendor/echarts.min.js", "myapp/js/charts.js"]},   # loaded once per page
    options_schema=[                       # the builder AND the Add card dialog render these
        {"name": "kind", "label": "Chart", "type": "choice", "choices": [["bars", "Bars"], ["line", "Line"]]},
        {"name": "grain", "label": "Buckets", "type": "choice", "choices": [["", "Fit the period"], ["week", "Weeks"]]},
    ],
))
```

**Option field types:** `choice`, `integer`/`number`, `text`, `boolean`, `column` (a
column of the metric's dataset), `widget` (a published info card) and `markdown`.

**What a registered type gets, with no other changes:**
- a tile in the **component builder** palette, with its form drawn from
  `options_schema`, the live preview, and dimming with a reason when the chosen
  metric's data lacks `requires`;
- the dashboard editor's Add card list;
- layout validation, the period bar, lazy loading, refresh and access checks;
- REST/MCP authoring, `card_preview` and `dashboard_snapshot`.

**A chart library** goes in `media`. `{% component_media %}` writes each file once on
every page that can show cards: dashboards, the builder, `{% dashboard %}` embeds and
playlists. Cards arrive over htmx, so the card's script must mount on load **and** on
`htmx:afterSettle`:

```js
function mountCharts(root) { root.querySelectorAll("[data-echart]:not([data-mounted])").forEach(mountOne); }
document.addEventListener("DOMContentLoaded", function () { mountCharts(document); });
document.addEventListener("htmx:afterSettle", function (e) { mountCharts(e.target); });
```

Pass the series to the script as JSON in the card's template (`{{ series|json_script }}`),
built in `build` from `metric_trend` or `group_values`. `build` may raise; the cell then
renders an error card instead of taking the page down. This is how call_stats' reporter
sits on top: each ECharts kind becomes a registered type, its spec options become
`options_schema`, and its data comes from metrics.

### Styling and a card's own colour rules (`stylable` types)

A metric's `thresholds` colour it everywhere it appears. A card of a `stylable` type
(Single stat, Grouped stat, and any app type that opts in) can also set:

```json
"options": {
  "thresholds": [{"op": ">=", "value": 1000, "state": "danger"}],
  "style": {"format": "compact", "unit": "req", "size": "xl", "color": "state",
            "title_size": "s", "title_color": "plain", "align": "center"}
}
```

- **`thresholds`** replaces the metric's rules on this card. `[]` turns colouring off;
  absent means the metric's rules.
- **`style`** comes from a fixed vocabulary (`components.CARD_STYLE`; agents read it as
  `style` in `list_dashboard_components`):
  - `format`, `unit`: blank means the metric's;
  - `size`: s / m / l / xl;
  - `color`: state, accent, plain, success, warning, danger, muted;
  - `title_size`: s / m / l;
  - `title_color`: quiet, plain, accent;
  - `align`: start, center, end.
- **No literal colours:** colours are theme tokens, never hex, so a styled card works on
  every palette. `normalize_layout` refuses anything else, and a non-stylable type
  given `style` or `thresholds` is an error.
- **The builder** shows these under **Style it**, with "Give this card its own rules"
  (it starts from the metric's rules).

**Making your own type stylable** works the way `apps/website`'s Trend chart does it, so
copy that. Set `stylable=True`. In `build`, call
`style = card_style(cell)` and, for each value,
`styled_value(value, metric, style, state)` → `{display, unit, state}`. Put
`style.classes` (the `cs-size-xl cs-color-accent …` hooks) on the template's root
element and style those hooks with theme tokens. The Trend chart applies each bucket's
state to its bar (and a dot per bucket on a line), uses the chosen colour for the whole
series and the headline, and routes every bar colour through one CSS variable
(`--bar`), so the "so far" hatching follows it.

**Info cards** are stylable with a narrower set (`style_settings`: size, colour, title
size and colour, alignment). Their headline is text, so there is no format or unit. Their
colour rules compare the widget's numeric `value` when its `get_data()` returns one
(return it, for exact rules), else the first number in the headline. A matching rule
replaces the app's status colour (success → operational, warning → degraded,
danger → down).

### Drill-downs — what opens when a number is tapped (`drillable` types)

Tapping a number opens its rows in the stat modal, with **Download CSV**. A card of a
`drillable` type (Single stat, Grouped stat, Trend chart) can design that modal:

```json
"options": {"drilldown": {
  "columns": [{"field": "path"}, {"field": "status_code", "label": "Status"},
              {"field": "timestamp", "format": "date"}],
  "sort": "-timestamp", "limit": 25}}
```

- **Columns:** up to 12, each a column of the metric's dataset (checked on save), with
  an optional `label` and a `format`: number, compact, decimal, percent, currency,
  duration, date, datetime or yesno.
- **Rows:** `sort` is a column, with `-` for descending; `limit` is 1–500 rows shown.
- **Export:** the CSV uses the same columns and formats, up to 10,000 rows.
- **Without a design**, the modal shows the dataset's first six columns, as stored.
- **In the modal:**
  - Headers are sort links (`?order=col` / `-col`, validated, overriding the design's
    `sort`; the CSV follows it).
  - Columns resize with the framework's `table-resize.js` (`crud-table` +
    `data-table-key="drill/<metric>:<columns>"` + `th[data-field]` +
    `col_resizer.html`). Drag, use the arrow keys, or double-click to fit; widths
    are remembered per card.

**How a card carries it:**
- Every rows URL a drillable card renders gets `?drill=<json>`
  (`components.drill_params(cell)` / `with_drill(url, cell)`).
- So the modal follows the card everywhere: a dashboard, an embed, a playlist, the
  builder's preview.
- `MetricRowsView` validates the design against the dataset. A design can only pick,
  label, format and sort columns of rows the viewer may already read, and a bad one is
  a 400.
- `?format=csv` on the same URL is the export.

**Your own type:** set `drillable=True` and pass every rows URL your template renders
through `with_drill(url, cell)` (or add `**drill_params(cell)` to its query), as the
Trend chart does. The builder's **Drill-down** step appears for it automatically. The
pieces for other surfaces: `metrics.drill_rows(..., spec=)`, `drill_csv` and
`format_cell`.

## Navigation — two areas

The sidebar has two areas. Many pages share the `/smallstack/dashboards/` path, so the entries register tuples of `active_prefix` values (`nav.register(active_prefix=(...))`); the longest match wins the highlight.

- **Goals** (`goals_index`): Overview, Goal lists, Metrics, Reports. Metrics, reports and goal lists use `breadcrumb_parent = ("Goals", "goals_index")`.
- **Dashboards**: Overview, My dashboards, Components, Playlists.

URLs did not move.

## Saved cards — `Component` and the component builder

A **metric** is *what* number; a **component** is *how it's drawn*:

```json
{"name": "Requests by method", "type": "metric_group", "metric": "requests",
 "options": {"dimension": "method", "limit": 5}, "visibility": "shared"}
```

- **The key** is made from the name (`requests_by_method`) and is permanent.
- **Validation:** a component is checked exactly as a one-cell layout is: a known type,
  a metric the owner may use, and the type's own rules.
- **Placement:** a dashboard places it with `{"component": key}` (plus position,
  `title`, `use_period`). `normalize_layout` copies the design into the cell, so every
  consumer still reads a self-contained cell.
- **Edits flow:** saving the component re-saves every dashboard showing it. Deleting it
  leaves the copies as ordinary cards, keeping its name as their title.
- **The builder** is `/smallstack/dashboards/components/new/` (palette → metric →
  options → live preview → save). The editor's **Add card → Saved card** places one.
- **Agents:** `create_component` / `update_component`, `card_preview` (a dry run), and
  `dashboard_add_card {component: key}`. REST: `/smallstack/api/dashboards/components/`
  and `POST dashboards/api/card-preview/`.

## A metric over time — `trends.metric_trend`

`metric_trend(metric, request, period=None, grain=None)` returns the metric's own filter and
aggregation per calendar bucket. Over REST it's `GET dashboards/api/metrics/<key>/trend/?period=&grain=`,
and over MCP it's the `metric_trend` tool. Built on `Dataset.series(dimension, grain=…)`, the
call_stats grain grammar ported to SmallStack's datasets: day/week/month/quarter/year, Monday
weeks, `[lo, hi)` bounds.

- **Every bucket of the period is present.** An empty one reads 0 for count/distinct/sum and
  `None` (a gap) for avg/min/max/ratio.
- **The running bucket has `partial: true`.**
- **Each point carries `narrow`**, the `[lo, hi)` filter for `m/<key>/rows/?narrow=`, so a bar
  opens exactly its rows. The rows modal drops its period links for a time-narrowed drill.
- **The default grain fits the span:** days up to a month, weeks up to four months, months up to
  two years. No period means the last 12 buckets with data.
- **It needs a metric with a `period_field`.** Without one, `error` says so.

## Playlists — dashboards in a sequence (`playlists.py`)

A **Playlist** (`OwnedModel`) is dashboards shown one after another: paged by
hand like slides, or rotated on a timer for a wall screen.

```json
{"name": "Ops wall", "slug": "ops-wall", "seconds": 30, "loop": true, "auto_start": false,
 "items": [{"dashboard": "site-health"}, {"dashboard": "sales", "seconds": 60, "period": "last_7"}, "errors"]}
```

**Items:**
- `seconds` (5–3600) and `period` (a period key, or `"all"`) are optional per item.
- A bare slug is shorthand for `{"dashboard": slug}`.
- `clean()` → `normalize_items`: every dashboard must exist and be one the owner
  may use. A **shared playlist holds only shared dashboards**.
- A renamed dashboard is renamed in every playlist, and a deleted one leaves them
  (`signals.py`).

**The components** — build your own playlist UI from these:

| Piece | What it gives you |
|---|---|
| `playlists.playlist_slides(playlist, user)` | the slides this viewer gets: `[{position, dashboard, slug, name, seconds, period, url}]`. Dashboards they can't open are **skipped**, never shown as an error |
| `playlists.player_options(params, playlist, count)` | a link's options resolved against the playlist: `{start, play, loop, seconds, kiosk}` |
| `playlists.player_context(playlist, request, params=None, sync_url=False)` | everything the player include needs, with the first slide already rendered |
| `dashboards/includes/playlist_player.html` + `static/dashboards/js/playlist.js` | the player. Every `[data-playlist]` on a page gets one; it works without JS (the controls are `?slide=N` links) |
| `{% playlist "slug" slide=1 play=True seconds=20 loop=False %}` | a player on any page. Arguments = link options; the page's address stays put; renders nothing for a playlist the viewer can't open |
| `playlists.slide_embed(slide, request)` | one slide laid out like `{% dashboard %}` (CSS grid, lazy cells) |
| `playlists.playlist_payload(playlist, user)` | the same, as JSON (REST + MCP) |

**Link options** (the player page `…/p/<slug>/`):
- `?slide=N` — start position, 1-based and clamped.
- `?play=1|0` — overrides `auto_start`.
- `?seconds=N` — this viewing only, clamped to 5–3600.
- `?loop=1|0` — overrides `loop`.
- `?kiosk=1` — no topbar, sidebar or header, for a wall screen.

The page keeps the address bar on the current slide (`replaceState`), so a copied
link resumes where it was.

**The player:**
- The timer is per slide, with a progress fill.
- It pauses on its own when the tab is hidden and resumes when the tab comes back.
- Clicking into a card (a drill-down) pauses it.
- Keys: ←/→, Home/End, space/k, f (full screen).
- It fetches the next slide ahead (`…/p/<slug>/slides/<n>/`); cards load lazily.
- `prefers-reduced-motion` turns off the fade and the fill animation.

**Agents:** use `create_playlist` / `update_playlist` (CRUD) with the JSON above,
then `playlist_slides {playlist}` (REST: `GET dashboards/api/playlists/<slug>/slides/`)
to check what a viewer gets.

## Goals — numbers judged against targets (`goals.py`)

`GoalList` (shared or personal, like every noun here) holds titled sections of goals, for reading down in a meeting at `/smallstack/dashboards/g/<slug>/` (`?period=`, `?present=1`):

```json
{"title": "Support", "goals": [
  {"metric": "first_response", "label": "First response", "target": {"op": "<=", "value": 3600},
   "warn": {"op": "<=", "value": 5400}, "period": "last_7", "note": "Support lead"},
  {"component": "open_tickets_card", "target": {"op": "<", "value": 20}}
]}
```

A goal names exactly one of `metric` or `component`. Only `target` is otherwise required. Ops are the threshold ops (`> >= < <= = != between`; `between` takes `[low, high]`). `judge()` gives `pass` (meets target), `warn` (meets only `warn`), `fail`, or `none` (no number). `warn` is checked after `target`, so write it as the outer limit: `<= 5400`, never a band. A goal with no number isn't counted in "6 of 8 on target".

| Function | What it's for |
|---|---|
| `normalize_sections` | the validation `GoalList.clean()` runs; fills in ids |
| `evaluate_goals(goal_list, request, period=, compare=, limit=)` | sections, rows, `summary`, `attention`, for one viewer |
| `goals_embed` + `dashboards/includes/goals_board.html` | a list on any page; a playlist slide uses them |
| `goal_values` | JSON for REST (`dashboards/api/goals/<slug>/values/`) and MCP (`goal_list_values`) |
| `add_goal(goal_list, goal, section)` | append one; the dialog and `goal_list_add_goal` use it |
| `suggest_target(metric)` | a target and at-risk line from colour rules |

Writes go through `create_goal_list` / `update_goal_list` or REST at `/smallstack/api/dashboards/goals/`.

**Sorting.** `goal_order` / `sort_sections` / `goal_sort_links` sort a judged list's sections in place (`?order=goal|status|value`, `-` to flip); rows never leave their section. The meeting view and the one-week view pass `sort_links` and `swap` (the container htmx replaces) to `goals_board.html`. Slides pass neither, so they stay static. Section tables share one `data-table-key`, so a resize applies to all of them.

**An app's own one-number card can be a goal:** set `single_value=True` on its `ComponentType`. The goal then uses the card's metric, number format and unit.

**Dynamic card options:** an `options_schema` entry's `choices` may be a callable `choices(user) -> [[value, label]]`, resolved per viewer by `describe_types(user)`. The `goals` card type uses this for its goal list; its options are `goal_list`, `limit` (1-10) and `order` (`list` | `attention`).

Playlists take `{"goals": "<slug>", "show"?: "week" | "weeks"}` items beside `{"dashboard": "<slug>"}`. `show` is the week just ended (`week_page`, snapshot if saved) or the week-over-week grid (`week_grid`); without it the slide shows the goals now. Slides carry `kind`, and goal slides also carry `show`.

**Trend.** `evaluate_goals(..., trend=True)` (used by the meeting view, slides and `goal_values`) adds `row["trend"]`, built by `goal_trend()`:
- `points`: the last `TREND_POINTS` (6) buckets, each judged against the target.
- `streak`: e.g. "Missed 3 weeks running".
- The bucket size comes from `trend_grain(period)`: week for wtd/pwtd/last_7, quarter, year, else month.
- It costs one `metric_trend` series query per goal.

### Printing

`g/<slug>/print/` and `r/<slug>/print/` render `dashboards/print/*.html`, standalone pages rather
than `base.html`: no menus, `data-theme="light"`, and status as a word so a black-and-white
printer loses nothing. `?period=` and `?order=` follow the page, `?week=` prints one week with its
saved values, and `?auto=1` opens the print dialog on arrival. A report with more than three
period columns prints landscape (`ReportPrintView.PORTRAIT_COLUMNS`).

### Weeks and snapshots (`weeks.py`, `GoalSnapshot`)

A week runs Monday to Sunday, local time. A goal's weekly value is its metric narrowed to `[monday, next monday)` on the period field. `weekly_values()` gets a run of weeks in one `Dataset.series(grain="week")` query per metric. A metric with no period field has the same value every week (`weekly: False`).

`GoalSnapshot(goal_list, week_start, rows, summary, complete, taken_by)` freezes a week. Each row stores the value, status, target and target text, so later target edits don't rewrite history. One snapshot per list per week.

| Function | What it's for |
|---|---|
| `take_snapshot(goal_list, monday, by=)` / `backfill(goal_list, n)` | save a week / fill past weeks |
| `snapshot_last_week()` | `tasks.snapshot_goal_lists`, `@scheduled(cron="15 0 * * 1")`; also `manage.py snapshot_goals [--list] [--week] [--fill N [--replace]]` |
| `week_page(goal_list, request, monday)` | one week: the snapshot, else live; `change` vs the week before; rows drill to the week's rows (`?narrow=`) |
| `week_grid(goal_list, request, last, count)` + `write_grid_csv` | goals × weeks; saved weeks as they were, the rest live. `grid_order` / `sort_grid` / `grid_sort_links` sort it (`?order=goal` or `w<monday>`, `-` for descending); the page's table resizes, with `data-field` keyed by position |
| `week_trends(goal_list, request, monday)` | the weeks around one week: bars, vs previous, vs the average before, streak, best/worst. `trends_order` / `sort_trends` / `trends_sort_links` sort it (`?order=goal`, `value`, `change`, `average`, `run`) |
| `weeks_payload` | JSON for REST (`dashboards/api/goals/<slug>/weeks/?week=&weeks=`) and MCP (`goal_list_weeks`) |

Snapshots are evaluated with `snapshot_user(goal_list)`: the owner, else `created_by`, else the first active superuser. When shown, a saved value is masked for viewers who can't read its dataset; the row stores `dataset` for that check.

Pages: `g/<slug>/weeks/` (`?week=`, `?view=grid`, `?format=csv`), `g/<slug>/weeks/<monday>/trends/` (modal fragment) and `POST g/<slug>/weeks/<monday>/snapshot/` (`fill=N` to backfill). Editors only.

**Report targets.** A `Report.items` row may carry `target` / `warn` (goal rules). `report_matrix` then sets each cell's `status`, recolours the value from it, and sets `has_targets`. The page adds a Target column, the CSV adds Target, At risk and per-period status columns, and `report_values` adds `target` and per-value `status`.

A hand-entered value changes the saved week it falls in (`weeks.refresh_saved_week`): the Monday
schedule usually runs before anyone has typed last week's numbers. The row keeps the target it was
saved with. Snapshot rows list every dataset behind the number in `datasets`, and `_masked` checks
them all, because a rate has no dataset of its own.

## `{% dashboard %}` — show a dashboard on any page

```django
{% load dashboard_tags %}
{% dashboard "site-health" %}                                   {# opens on its own period #}
{% dashboard "site-health" period="ytd" title=False %}          {# "all" = all time #}
{% dashboard board lazy=False %}                                {# render the cards now, no htmx #}
```

- **What it renders:** the dashboard's cards through the same cell endpoint, access checks and
  drill-down modal as the dashboard page.
- **Layout:** plain CSS grid using the page's geometry (12 columns, 70px rows); on a phone the
  cards stack in reading order.
- **When it renders nothing:** a dashboard the viewer may not open, or an anonymous viewer (cards
  load from a login-protected endpoint). A page never reveals that a dashboard exists.
- **Building your own markup:** `boards.board_embed(dashboard, request, period=, lazy=)` returns
  the same structure for a page that wants different markup.

`/starter/dashboard/` (`templates/starter/dashboard.html`) is a working page using both tags.

## The `{% metric_card %}` tag

```django
{% load dashboard_tags %}
<div class="stat-cards">
  {% metric_card "open_urgent" %}
  {% metric_card "open_urgent" period="mtd" label="Opened this month" %}
</div>
```

Renders `smallstack/includes/stat_card.html` (same template, same global
drill-down modal) from the stored metric — a hand-placed card and a dashboard
cell are one component. Unknown/unviewable metric → a muted "—" card.

## The forms show no JSON — that's for agents

The HTML forms keep every field, because they are the REST and MCP forms too.
But the JSON travels as hidden inputs written by the visual editors: the metric
filter and thresholds, the report rows, and the playlist items.

- **Dashboard layout:** the settings page doesn't post it at all.
  `DashboardForm` drops the field when it's missing from the data, so saving
  settings can't overwrite a layout arranged meanwhile. REST and MCP always send
  it, and PATCH merges the stored one in.
- **The metric key has no input.**
  - `MetricForm` makes it from the name on create (`metric_key_from_name`:
    `open_urgent_tickets`, then `_2` if taken).
  - After creation it is **permanent**: a different key over REST/MCP is a 400
    ("can't change").
  - An agent may still choose a key when it creates a metric.

Don't add JSON boxes back to these pages: give the editor a control instead, or
leave the capability to agents.

## Building agentically (MCP + REST)

The CRUD tools come from the CRUDViews (`list_metrics`, `create_metric`,
`update_dashboard`, `create_report`, …; REST at `/smallstack/api/dashboards/{metrics,boards,reports,playlists,components,goals}/`).
The evaluation tools are custom:

| MCP tool | REST | Purpose |
|---|---|---|
| `list_datasets` / `describe_dataset` | `GET dashboards/api/datasets/`, `…/<key>/schema/` | what can be measured; each field's filter ops + period keys |
| `metric_preview` | `POST dashboards/api/preview/` | **dry-run** an unsaved metric → value, row count, filter reading, every problem |
| — | `POST dashboards/api/report-preview/` | evaluate an unsaved report: `{items, periods}` → columns, rows, changes |
| `metric_value` | `GET dashboards/api/metrics/<key>/value/?period=` | evaluate a saved metric (+ `comparison` with the previous period) |
| `metric_trend` | `GET dashboards/api/metrics/<key>/trend/?period=&grain=` | the metric per bucket across a period — a chart's series |
| `metric_rows` | `GET dashboards/api/metrics/<key>/rows/?period=&order=&limit=` | the rows behind the number, as JSON |
| `get_metric` `get_dashboard` `get_report` `get_goal_list` `get_playlist` `get_component` | `GET /smallstack/api/dashboards/<noun>/<id>/` | read one back in full. The tools also take `key` / `slug` in place of `id` (`mcp_lookup_field`), as do `update_*` and `delete_*` |
| `goal_list_values` / `goal_list_weeks` | `GET dashboards/api/goals/<slug>/values/`, `…/weeks/` | a list judged; a list week over week |
| `goal_list_save_week` | `POST dashboards/api/goals/<slug>/weeks/<week>/save/` | freeze a week (`fill` backfills, MCP only) |
| `list_dashboard_components` | `GET dashboards/api/components/` | card types, options, default sizes, periods (+ widgets for staff: the `widget` type, "Info card", places one published `DashboardWidget`) |
| `dashboard_add_card` / `dashboard_remove_card` | (PATCH `layout`) | edit one card without rewriting the layout |
| `dashboard_snapshot` | `GET dashboards/api/boards/<slug>/values/` | every card, evaluated — check your work |
| `dashboard_set_picture` (base64, or `remove`) | `POST`/`DELETE dashboards/api/boards/<slug>/picture/` (multipart `image`, `alt`) | the dashboard's picture. The JSON CRUD can't carry a file, so `cover_image` is read-only there (its URL) and left out of the MCP write schema. A session caller sends `X-CSRFToken` |
| `report_values` | `GET dashboards/api/reports/<slug>/values/` | a report's matrix |
| `playlist_slides` | `GET dashboards/api/playlists/<slug>/slides/` | a playlist as the caller sees it (create/edit with `create_playlist` / `update_playlist`) |

**The loop** an agent should follow:

1. `list_datasets` → `describe_dataset {key}` (columns, filterable fields + ops, periods).
2. `metric_preview {dataset, filter_tree, agg, measure, period_field}` — iterate
   until `problems` is empty **and** `row_count`/`value` are plausible.
3. `create_metric` with the same fields (+ `key`, `name`, `visibility`).
4. `create_dashboard {name, slug}` → `dashboard_add_card` per card.
5. `dashboard_snapshot {dashboard}` — confirm no cell has an `error`.

Everything runs as the token's user: ownership and dataset access apply
exactly as on the pages.

**Refusals, not guesses.** REST and MCP refuse a period, grain or week that isn't one (a page falls
back quietly via `requested_period`; a client can't see that it got all time). The MCP dispatcher
holds every tool to its `additionalProperties: false`, so a misspelt argument is an error rather than
a silent no-op. `isError` follows a truthy `error`, so `metric_value`'s `"error": null` is a success.
`list_datasets` / `describe_dataset` cover every dataset the caller may read; `query_tool` says
whether it also has a `query_dataset_<key>` tool. REST 404s on these routes are JSON.

**Empty aggregates.** `count`/`distinct`/`sum` of no rows is 0; `avg`/`min`/`max` of no rows is `None`,
which a card shows as "—" and a goal judges as `none` (a week with no traffic is not "0 ms, on target").

**What a deletion takes** (`metric_usage` reads it first): in everything the caller can edit, `detach_metric` removes the metric's cells, report rows, goals, its saved
cards and the goals on those cards, and `delete_metric` reports them in `also_removed`.

## Where the logic lives — build your own UI on these

SmallStack's dashboard pages are one consumer of these modules, written the way a downstream
app would write its own UI. Import from them, never from `views`, `api` or `mcp_tools`:

| Module | What it gives you |
|---|---|
| `metrics` | `evaluate(metric, request, period=)` → `MetricResult` (the one evaluation seam), `drill_rows`, `group_values`, `metric_sentence`, `threshold_legend`, `format_value` |
| `comparison` | `compare_with_previous`, `compare_groups`, `delta` |
| `reports` | `report_matrix`, `present_report`, `report_values` (JSON), `write_report_csv`, `report_movement` |
| `boards` | `render_cell` (one cell's HTML through the registry), `board_values` (JSON), `board_attention`, `board_embed` (the `{% dashboard %}` layout) |
| `trends` | `metric_trend` — a metric per day/week/month across a period (what a chart reads) |
| `previews` | `unsaved_metric`, `preview_metric`, `preview_report` — dry runs, never save |
| `periods` | `requested_period`, `period_phrase` ("this month so far"), `period_heading`, `PREVIOUS_PERIOD`, `TO_DATE_PERIODS` |
| `components` | the card-type registry (`register_component_type`), `metric_card_context`, `components_payload` |

Every function takes the `request` whose user the numbers are for; access rules apply inside.
`tests/test_layering.py` enforces the direction: a building block importing a surface, one
surface importing another, or a private name imported from another app fails the suite.

## Comparisons, digests and drill-downs (one implementation each)

- **This period against the one before** — `comparison.compare_with_previous(metric, request,
  period, result)` → `{dir, text, previous, unit}` or None. Only for periods with a natural
  predecessor (`today`→`yesterday`, `wtd`→`pwtd`, `pwtd`→`ppwtd`, `mtd`→`pmtd`, `qtd`→`pqtr`, `ytd`→`prev_year`;
  `periods.PREVIOUS_PERIOD`). A still-running period says **"vs all of last month"**
  (partial against complete), and the change is neutral grey, never good/bad. Used by the metric
  page, dashboard metric cells, the index and metrics-list period views, the rows modal (count
  metrics only), `metric_value` (MCP) and `dashboards/api/metrics/<key>/value/`. Grouped cards
  compare each group with the same group last period (`metrics.group_value_map`; "Other" is
  skipped — it isn't the same set), and their groups' threshold states count in the dashboard
  "needs attention" digest. The report page
  compares its own first two columns with the same `comparison.delta`.
- **Digests** (lazy, `hx-trigger="revealed"`): `dashboards/r/<slug>/digest/` (a report's
  up/down/unchanged between its first two columns) and `dashboards/d/<slug>/digest/` (a
  dashboard's metric cards by threshold state at the period it opens on — "1 needs attention").
- **Rows behind a number** — every value is a drill-down into the global stat modal:
  dashboard cards, grouped-card groups, report cells, preview values. `m/<key>/rows/?period=&narrow=` returns the
  fragment, with period links that reload it in place (`&retitle=1` renames the modal via an
  `hx-swap-oob` title). An **unsaved** metric's rows: `POST dashboards/preview-rows/` (session + CSRF; the builder).
- **Delete impact** — the metric delete page/modal lists the cards and report rows that would
  break (`models.metric_usage`). `MetricCRUDView.on_delete` removes them
  (`models.detach_metric`) on **every** delete surface — HTML, bulk, REST, MCP — inside the
  delete's transaction; the page's checkbox is the only opt-out (its form sends
  `detach_choice`, so an unticked box keeps them). `on_delete(request, obj)` is a framework
  CRUDView hook any app can override. Report/dashboard deletes show what goes and offer a
  last CSV / the layout JSON. List views load these into the stat modal; table views do too via
  the framework's opt-in `confirm_modal` on a CRUD delete action (set in `row_actions`).

## Pages

| URL | |
|---|---|
| `/smallstack/` | the staff home: the **system dashboard** (`system_key="smallstack"`) of every published `DashboardWidget` — see dashboard-widgets.md. `boards.system_dashboard(key, …)` + `sync_widgets` |
| `/smallstack/dashboards/` | the **Dashboards** overview: dashboards (cards with a Sort select, or `?boards=list`, a table), playlists, saved cards. Each is a resizable table with its own sort (`?dash=`, `?playlists=`, `?components=`; `views.section_sort`) |
| `/smallstack/goals/` | the **Goals** overview: goal lists (live summaries), metrics (live values, `?period=` + comparisons), reports. Each is a resizable table with its own sort (`?lists=`, `?metrics=`, `?reports=`; `views.section_sort`) |
| `…/mine/` | **My dashboards**: the personal ones you own plus the shared ones you made (`Dashboard.objects.mine(user)`, which reads `created_by`; `owner` is blank once a row is shared). Newest change first, each with its "needs attention" line. In the sidebar beside Dashboards |
| `…/d/<slug>/` | a dashboard — period bar, **Edit layout** (drag/resize, Add card, Remove, Save) |
| `…/d/<slug>/cards/` (`?order=`), `…/cards/<id>/value/` | the settings page's cards table and one row's lazy value (`boards.board_cards`, `boards.cell_value`). It swaps only itself, so a form with unsaved edits is safe; sorting never moves a card |
| `…/m/<key>/` | a metric — value, filter reading + JSON, the rows, where it's used |
| `…/metrics/new/`, `…/metrics/<pk>/edit/` | the **metric builder**: AND/OR filter tree from the schema, measure/period pickers, threshold rules, live preview |
| `…/r/<slug>/` (`?format=csv`) | a report — values drill into their rows; the first column carries the change from the second |
| `…/boards/`, `…/reports/` | CRUD lists |
| `…/components/` (`new/`) | saved cards, and the **component builder** |
| `…/playlists/` | playlists: a strip of each one's dashboards, how it plays, **Play** |
| `…/p/<slug>/` (`?slide=&play=&seconds=&loop=&kiosk=`) | a playlist, playing — see Playlists above |
| `…/goals/` (`new/`, `add/`) | goal lists, the goals editor, and the **Add to goals** dialog (`?metric=` or `?component=`) |
| `…/g/<slug>/` (`?period=&present=1`) | a goal list: the meeting view — see Goals above |

`manage.py seed_dashboards` builds a shared demo (8 metrics over the bundled
datasets, a "Site health" dashboard, a "Monthly KPIs" report).

## Anti-patterns

1. **Computing a KPI in a view and passing it to `{% stat_card %}`** when it
   should be reusable — store it as a Metric; then the dashboard, the report
   and the agent all read the same number.
2. **Copying a filter into two metrics** that differ only by period — use one
   metric with a `period_field` and let the dashboard/report period narrow it.
3. **Hand-writing an `Other` as `total - sum(groups)` for an average** — it's
   meaningless; `metric_group` deliberately shows no Other for non-additive aggs.
4. **Catching `FilterTreeError` and evaluating without the filter** — that's
   the fail-open bug. Show the error.
5. **Adding a chart library to SmallStack** — register a component type in your
   own app instead.
6. **Hex colours in a custom cell template** — use the stat-card states and the
   theme variables ([`modern-dark-theme.md`](modern-dark-theme.md)).

## Settings

- `SMALLSTACK_DASHBOARDS_ENABLED` (default on). Off ⇒ no nav, no routes, no MCP
  tools; the app stays installed (migrations apply) and `evaluate()` /
  `{% metric_card %}` keep working in-process (cards render without a drill link).
