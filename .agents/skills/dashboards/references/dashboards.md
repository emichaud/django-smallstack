# Dashboards — metrics, grid dashboards and KPI reports (`apps/dashboards/`)

**Read this** before building a KPI, a dashboard, or a metrics report — or before
letting an AI agent build one. The app label is `smallstack_dashboards`; pages
live under `/smallstack/dashboards/`.

> **Prerequisite**: [`datasets.md`](datasets.md). Every number here is a
> `@dataset` rolled up through a stored **filter tree** (the "Filter trees"
> section there is the grammar). For a one-off tile computed in a view, the
> lower-level [`dashboard-cards.md`](dashboard-cards.md) `{% stat_card %}` is
> still right.

**Start here.** Building one over MCP/REST → *Building agentically (MCP + REST)* (the five-step
loop and the tool table). Adding a card design → [`card-types.md`](card-types.md). Shipping
defaults with an app → [`app-defaults.md`](app-defaults.md). Using the pieces on your own page →
*On your own pages*.

## The model — six owned kinds, all JSON an agent can write

```
@dataset ──(filter_tree + agg)──▶ Metric ──▶ Dashboard cell   (grid, period bar, refresh)
                                         └─▶ Report row        (metrics × periods, CSV)
                                         └─▶ {% metric_card %}  (any template)
```

| Model | What it is | Key fields |
|---|---|---|
| **Metric** | A named number, the KPI and the reusable unit: a stored filter over a dataset rolled up to one value (`source="dataset"`), values entered by hand (`manual`, `MetricEntry`) or one metric divided by another (`rate`). | `key` (stable slug), `source`, `dataset`, `numerator`, `denominator`, `filter_tree`, `agg`, `measure`, `period_field`, `format`, `unit`, `thresholds` |
| **Dashboard** | A grid of cards. | `slug`, `layout` (list of cells), `default_period`, `refresh_seconds` |
| **Report** | Metrics × periods as a table (+ CSV). | `slug`, `items` (`[{metric, label?}]`), `periods` (`["mtd", "pmtd", "ytd"]`) |
| **Component** | A saved card: a design and its source, placed on dashboards with `{"component": key}`. | `key`, `type`, a source (`dataset` + `filter_tree` + `agg`/`measure` + `period_field`, or `metric`), `options` |
| **GoalList** | Goals judged against targets, in titled sections. | `slug`, `sections` (`[{title, goals: [{metric or component, target, warn?}]}]`), `default_period` |
| **Playlist** | Dashboards shown one after another. | `slug`, `items` (`[{dashboard, seconds?, period?}]`), `seconds` |

All six: `owner` blank = **shared** (staff edit, every signed-in user views);
set = **personal** (owner edits, staff view). `can_view` / `can_edit` on the
model is the one rule — views, REST and MCP never re-derive it. Every model
calls `full_clean()` in `save()`, so a bad filter, a cell pointing at a
missing metric, or a malformed threshold is refused on **every** surface.

**Addresses.** Dashboards, reports, playlists and goal lists are addressed by `slug`
(`…/d/<slug>/`, `{% dashboard "slug" %}`, playlist items, the MCP lookup field). Nobody types
one: `forms._OwnedForm` makes it from the name on create (`models.free_slug`: `site-health`,
then `site-health-2`; a name with nothing sluggable takes the model's word, `dashboard`), the
way a metric or card gets its `key`. A create that sends a `slug` (an agent, REST) keeps it. On
an existing row the slug never follows the name, and `clean_slug` lets only an administrator
change it (`models.can_change_address`: a superuser, or a member of the `admin` group,
`ADDRESS_ADMIN_GROUP`; plain staff don't count); anyone else's attempt, over REST and MCP too, is a
validation error, not a silent no-op. The forms show the address read-only
(`partials/address_field.html`, the `can_change_address` filter) with **Change the address** for
administrators only; `signals.py`
carries a changed slug into playlists and Goals cards.

**Keeping the pile small: tags and archive.** Every owned row (metrics, dashboards, cards,
playlists, reports, goal lists) has `tags` and `archived_at`.

- **Tags** are one comma-separated text field (`tag_list`, `split_tags`;
  `OwnedQuerySet.tagged(tag)` matches a whole tag, any case).
- **Archive** puts a row away without breaking anything. The rule: *lists and pickers show
  active rows; references keep working.* Overviews, CRUD lists, REST/MCP lists and every
  picker go through `.active()`; a card drawing an archived metric, a report row, a goal,
  `get_detail_queryset` and REST/MCP `get_*` don't. `usage_index` ignores archived boards,
  reports and goal lists, so archiving a board frees its metrics.
- **Archiving and restoring:** `POST dashboards/archive/<kind>/<pk>/` (editors only; `kind`
  is `metric`, `dashboard`, `component`, `playlist`, `report` or `goals`; `restore=1` brings
  it back). Restore is one click.
- **Finding archived rows:** each list's tags bar (`displays.TagBar`) offers **Show archived
  (N)** (`?archived=1`) and **Back to the list**; the overviews name what's archived by kind,
  each a link ("Archived: 2 metrics, 1 report", `displays.archived_links`).
- **Confirmations.** Archive, Delete and Duplicate each ask first, in the global stat modal
  (htmx), or as a page without JavaScript, and say what the action means:
  - `GET dashboards/archive/<kind>/<pk>/`: what archiving means and what still uses the row;
  - each kind's delete view (`_DeleteInModalMixin`; cards, playlists and goal lists through
    `_ConfirmDeleteMixin`): what goes and what stays;
  - `GET dashboards/duplicate/<kind>/<pk>/` (`DuplicateConfirmView`, anyone who can see the
    row): what the copy will be; its button opens the create form.

  The shared wrappers are `smallstack_dashboards/crud/owned_confirm_{modal,page}.html` around
  a body template; `views.where_used(kind, obj, user)` lists what still uses a row.
- **Duplicate** is the create form opened with `?from=<key or slug>`: the original's defining
  fields and tags, the name "… (copy)", visibility personal, nothing saved until Save. The
  original is untouched. `MetricCreateMixin.COPIED` and each `*DuplicateMixin.duplicate_fields`
  say what's carried over. Over REST or MCP a duplicate is a get followed by a create.

**Finding by tag.** `models.tag_cloud(*querysets, current=)` is the tags in use with their row
counts (any case counted together, the 30 most used, the current one always kept). The
overviews and My dashboards put it in `tags`; every CRUD list gets it from the
`displays.TagBar` list accessory. One partial draws it, `partials/tag_filter.html`: chips that
set `?tag=` on the current address (other parameters kept, `page` dropped) and **Show
everything**. `_OwnedCRUD.get_list_queryset` applies `?tag=` (so REST lists take it too), the
overviews' "All N …" links carry it, and each list display shows a row's tags
(`partials/tags.html`). The overviews are samples and never page
(`DashboardIndexView.DASHBOARD_CARDS` = 8, `DASHBOARD_ROWS` = 20, `PLAYLISTS` = `COMPONENTS` =
6); the lists and `…/mine/` page at `PAGE_SIZE_CHOICES` (15 first).

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
    agg="count",                            # count | distinct | sum | avg | median | min | max
    measure="",                             # the column for non-count aggs
    period_field="created_at",              # a dashboard/report period narrows this; blank = never
    format="number",                        # number | compact | decimal | percent | currency | duration
    unit="tickets",
    thresholds=[{"op": ">=", "value": 10, "state": "danger"},
                {"op": ">=", "value": 5, "state": "warning"}],   # first match wins
).save()
```

**Evaluate** with the one seam — `apps.dashboards.metrics.evaluate(metric, request, period=None)`
→ `MetricResult(value, display, unit, state, error, restricted, summary, period, period_label, problems)`.
Cards, cells, reports, REST and MCP all call it, so a number means the same
thing everywhere. Outside a view, `request_for(user)` builds a request.

- **period**: when a period key is given *and* the metric has a `period_field`,
  a `{"field": period_field, "op": "period", "value": period}` leaf is AND-ed
  on. A metric with no `period_field` is unaffected (a report shows its one
  value once, across every period column, noted "Same in every period").
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
saved period. `metric_entries` is an `access="auth"` dataset whose rows are scoped to the metrics
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
make an ownerless shared row (`visibility: "shared"`, everyone's, staff-edited);
omitting `visibility` on an edit keeps the current setting.

**A personal dashboard its owner shares.** `Dashboard.shared_with_everyone` and
`Dashboard.shared_with` (people by name) let others *open* a personal dashboard
while its owner keeps editing it (`can_edit` unchanged; `can_view` and
`visible_to` widen; `shared_with_me(user)` lists them for "Shared with you").
The header's **Share** opens `d/<slug>/share/` (the dialog, in the stat modal:
everyone on/off, find and add people, remove); `boards.set_sharing(dashboard,
actor=, everyone=, add=, remove=)` is the service (a `notify()` bell with the link
for each person added), `dashboard.sharing` is what REST reads, and the
`dashboard_share` MCP tool reports or sets it. A viewer reads the cards as the
owner does: a card over the owner's personal metric still draws, and its rows
open by the card's place (`d/<slug>/cards/<id>/rows/`, access = the dashboard's)
rather than the metric's own route they couldn't open; the card menu offers
"Open the metric" only to who may. The dataset access tier still applies to
the viewer, so a staff-only dataset stays "restricted" for a member; `set_sharing`
(and `dashboard_share`) says so when it adds such a person: its reply carries `cant_read`
(`{username: [card titles]}`) and a `warning` sentence.
`dashboard.audience(user)` / `{% dash_audience d %}` word the badge: Personal,
Shared with everyone, Shared with 3 people, Shared by alice.

## A dashboard layout

```json
[
  {"id": "intro", "type": "text", "x": 0, "y": 0, "w": 12, "h": 1, "options": {"markdown": "**Support desk**"}},
  {"id": "open",  "type": "metric", "metric": "open_urgent", "title": "Urgent, open", "x": 0, "y": 1, "w": 3, "h": 2},
  {"id": "byq",   "type": "metric_group", "x": 3, "y": 1, "w": 6, "h": 2,
   "dataset": "tickets", "filter_tree": {"field": "status", "op": "=", "value": "open"}, "agg": "count", "period_field": "created_at",
   "options": {"dimension": "queue", "limit": 5, "other": true}},
  {"id": "users", "type": "widget", "x": 9, "y": 1, "w": 3, "h": 2,
   "options": {"widget": "apps.api.dashboard_widgets.APIDashboardWidget"}},
  {"id": "mtd",   "type": "metric", "metric": "open_urgent", "use_period": false, "x": 0, "y": 3, "w": 3, "h": 2}
]
```

**Where a card's numbers come from.** A card that draws data has one of two
sources, and `normalize_layout` holds every surface (page, REST, MCP) to the
rule. **A dataset it filters itself:** `dataset` + `filter_tree` + `agg` /
`measure` + `period_field`, the definition a metric holds, kept on the card
(`components.SOURCE_KEYS`); any design. **A saved metric:** `metric` = its key;
only a design whose `single_value` is true (the single stat, the gauge), because a metric
is a filtered result rolled up to one number and a chart needs the rows. One
exception: a metric with no dataset to filter (entered by hand, a rate) may be
charted as it is. A card with its own source formats itself through
`options.style` (`format`, `unit`) and `options.thresholds`; a card over a
metric inherits those from the metric. A chart that started life over a metric
(before v0.30) was given a copy of the metric's definition by the migration and
no longer follows edits to the metric. `components.cell_source(cell)` resolves
either kind to a `Metric` (an unsaved one for a card's own source, `is_inline`),
so `evaluate`, `metric_trend`, `group_values` and the drill-down take both.

**A cell's `title`** (optional, text up to 120 characters) is the heading that card shows on this
dashboard; left out, the card is headed by its metric's or saved card's name (`cell_title`).

12-column grid (gridstack.js, vendored); `w` 1–12, `h` 1–12 rows of 70px;
`x + w ≤ 12`. `id`, `w`, `h`, `x`, `y` may be omitted (the size from the type's
default; a cell with neither `x` nor `y` goes after the cards so far). Cells may not overlap. `use_period: false` pins a cell to all-time regardless of the
period bar. Cells load lazily over htmx (`hx-trigger="load[, every Ns]"`), so
one slow card doesn't block the page and `refresh_seconds` is free.

### Card types

The framework's own types, then the six library-free designs the starter registers in
`apps/website/dashboard_cards.py` (palette group in brackets):

| `type` | Label | Shows | Options |
|---|---|---|---|
| `metric` | Single stat (Stats) | one stat card — the exact `{% stat_card %}` markup; click → the rows behind it. Over a saved metric (`metric`) or the card's own filter; `single_value` | — |
| `metric_group` | Grouped stat (Stats) | the card's filtered rows split by a column: top N groups, biggest first, each drilling into its rows and showing its change from the previous period; an `Other` folds the tail for additive aggs (count/sum) only | `dimension` (req), `limit` 1–12, `other` |
| `widget` | Info card (Info) | an existing `DashboardWidget` from `/smallstack/` (staff only) | `widget` (class path — `list_dashboard_components` lists them) |
| `text` | Note (Info) | markdown (rendered by the hardened `render_markdown`; raw HTML is escaped) | `markdown` (required) |
| `menu` | Menu (Info) | links in the card's order — a way around, on the dashboard; across, down, or (`auto`) by the card's shape (a container query) | `items` (required: `[{label, url, new_window?}]`; a page of this site `/…`, `#…`, http(s) or `mailto:`, never a scheme that runs), `layout` auto/horizontal/vertical |
| `goals` | Goals (Stats) | a goal list's summary and first goals | `goal_list`, `limit`, `order` |
| `calendar` | Calendar (Info) | upcoming entries, a month or a board (registered by `apps/calendar`) | `calendars`, `mode`, `days`, `limit` |
| `trend` | Trend chart (Charts) | the source over time, as bars or a line | `kind` bars/line, `grain` ""(fit)/day/week/month/quarter |
| `pie` | Pie chart (Charts) | each group's share of the whole (count or sum only) | `dimension` (req), `limit` 1–12 (default 6), `other` |
| `ranked` | Ranked bars (Charts) | groups as bars, largest first | `dimension` (req), `limit` 1–12 (default 6), `other` |
| `bars` | Bar chart (Charts) | groups as columns or horizontal bars | `dimension` (req), `limit` (default 8), `other`, `direction` vertical/horizontal, `order` value/label |
| `gauge` | Gauge (Stats) | one number on a half dial, the colour rules drawn as bands; `single_value`, so it takes a metric and the Add card dialog offers it | `min` (default 0), `max` (default 100) |
| `table` | Table (Charts) | the filtered rows themselves, sorted by their headers and paged in place through the cell's own URL (`?order=` / `?page=`); its columns are its drill-down design, see below | `rows` a page (default 10), `totals` sums for number columns |

Every data card also takes the shared options `list_dashboard_components` names in
`shared_options`: `publish` / `listen` (linked cards), and `style` / `thresholds` on a
`stylable` type. An option a type doesn't take is refused.

Charts belong to apps; SmallStack's own cards stay stats and info cards. The grouped stat
on the sample dashboard is `metric_group`: `build_metric_group` calls
`metrics.group_values(metric, request, dimension, limit=…, other=…, period=…)`, which runs
the metric's filter and aggregate grouped by the column, keeps the top `limit`, and
folds the rest into "Other". Each value carries a `narrow` filter, so clicking it opens
exactly its rows.

### Adding your own card type (the extension seam)

**The contract is [`card-types.md`](card-types.md)**: every `ComponentType` field,
`CellContext`, the data helpers, `options_schema` types and your own option editors,
`validate`, `media` (a chart library) and the `dashboards:card-drawn` event, and testing.
**The working reference is `apps/website/dashboard_cards.py`**: the six designs above,
registered from `WebsiteConfig.ready()`; the trend is the one to copy for a chart.

**What a registered type gets, with no other changes:**
- a tile in the **component builder** palette, with its form drawn from
  `options_schema`, the live preview, and dimming with a reason when the chosen
  source's data lacks `requires`;
- the dashboard editor's Add card list;
- layout validation, the period bar, lazy loading, refresh and access checks;
- REST/MCP authoring, `card_preview` and `dashboard_snapshot`.

### Styling and a card's own colour rules (`stylable` types)

A metric's `thresholds` colour it everywhere it appears. A card of a `stylable` type
(Single stat, Grouped stat, Info card, the starter's Trend, Bars, Gauge, Pie and Ranked,
and any app type that opts in) can also set:

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
- **The builder** shows these under **Style it**, with **Override the metric's colour rules for this card**
  (or **Colour rules for this card** when there's no metric); it starts from the metric's rules.

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

### Linked cards — a click on one narrows another

Two cards on a dashboard (or an embed, or a playlist slide) connect through a
named channel. A card with `options.publish: "<channel>"` sends what's clicked
in it, instead of opening the rows window; a card with
`options.listen: {"channel": "<name>", "map"?: {"their_column": "my_column"}}`
redraws narrowed to whatever arrives, with a "Showing POST ✕" chip that clears it.

A channel with only one end on the dashboard (published and never heard, or heard and never published) is saved, and named in `warnings` on `dashboard_add_card`, `dashboard_snapshot` and `GET dashboards/api/boards/<slug>/values/`: a typo in a channel name otherwise breaks the click with no sign.

```json
[{"id": "by", "type": "pie", "dataset": "smallstack_requests", "agg": "count", "options": {"dimension": "method", "publish": "verb"}},
 {"id": "n", "type": "metric", "dataset": "smallstack_requests", "agg": "count", "options": {"listen": {"channel": "verb"}}},
 {"id": "t", "type": "table", "dataset": "smallstack_requests", "agg": "count", "options": {"listen": {"channel": "verb"}}}]
```

- **What travels is an address, not rows:** the `narrow` filter tree the clicked
  group, bar, bucket or day already carries in its rows link. The bus is in the
  page (`cards.js`: publish, subscribe, the last value for a card that loads late,
  an identical re-send dropped).
- **The server only ever narrows.** A listener redraws from its own URL with
  `?narrow=<tree>`; `components.listened_narrow` maps it (`listen.map`), checks
  it against the card's dataset and ANDs it onto a copy of the card's source,
  so every number, group, bucket and row link is narrowed alike, and the card's
  own filter, period and the viewer's access all still apply. A slice naming a
  column the card's data doesn't have, or sent to a card that doesn't listen,
  is refused with a reason, never dropped (which would show the whole set under
  a heading that says it's narrowed).
- **Chaining:** a card that listens and publishes sends its slice on ANDed with
  its own click (`rows_url` merges `ctx.narrow`): pie → ranked bars → table is
  *POST*, then *POST · 204*.
- **A calendar card sends days.** With `options.publish`, a click on a day (the
  month grid, the board's day heads, the upcoming list's days, keyboard too)
  sends that day as `[day, next day)` on the field `date` instead of opening the
  calendar page; events inside a day still open their own links. A listening
  card reads `date` as its own period column unless its `listen.map` names
  another (`{"date": "created_at"}`); with neither, it says it has no column to
  read a day over. Any card type with no data of its own can send clicks the
  same way: `ComponentType(publishes=True)` and a `data-day="YYYY-MM-DD"` (plus
  `data-day-label`) on what's clickable.
- **Checked on save** (`components.link_problems`): channel names are
  `[a-z0-9_-]`, up to 40; only a drillable card or a `publishes` type (the calendar)
  may publish; a data-free card never listens; a card can't listen to the channel it publishes to; `map` targets
  must be columns of the card's own data. The builder's **What it shows** step
  has a *Linked cards* block for both.
- **Your own card type** publishes and listens for free if its clickable things
  are rows links built with `rows_url(ctx, narrow=…)`, and its numbers come
  from `ctx.metric` (already narrowed). `ctx.narrow` is the slice, if you need it.

### Drill-downs — what opens when a number is tapped (`drillable` types)

Tapping a number opens its rows in the stat modal, with **Download CSV**. A card of a
`drillable` type (Single stat, Grouped stat, and the starter's Trend, Bars, Gauge, Pie,
Ranked and Table) can design that modal:

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

**In the builder** (the **Drill-down** step, `component-builder.js`):
- "Choose the columns" opens a dialog (`#cb-drill-dialog`, a native `<dialog>` outside the
  form) that starts from the default six. Every column of the metric's dataset is listed
  once: ticked ones on top in the order they appear, each with a heading and a format;
  the rest below, with a filter once there are eight or more.
- Order by dragging a row's grip or with its ↑ ↓ buttons. **All**, **First six** and
  **None** set the ticks in one go; 12 is still the most.
- Beside the list are the rows that design opens, redrawn as it changes: the JSON rows
  route with `?drill=<json>&limit=25`. Selecting one of its headings sets the design's
  `sort`.
- **Done** keeps the design; **Cancel** or Escape puts back what was there. The form then
  shows it in short (the columns as numbered chips, the sort, the row limit). Unticking
  "Choose the columns" goes back to the default, and ticking it again on the same page
  brings the design back.

**How a card carries it:**
- Every rows URL a drillable card renders gets `?drill=<json>`
  (`components.drill_params(cell)` / `with_drill(url, cell)`).
- So the modal follows the card everywhere: a dashboard, an embed, a playlist, the
  builder's preview.
- `MetricRowsView` validates the design against the dataset
  (`metrics.requested_drilldown`). A design can only pick, label, format and sort
  columns of rows the viewer may already read, and a bad one is a 400. The JSON rows
  route (`dashboards/api/metrics/<key>/rows/`) takes the same `?drill=`.
- `?format=csv` on the same URL is the export.

**Your own type:** set `drillable=True` and pass every rows URL your template renders
through `with_drill(url, cell)` (or add `**drill_params(cell)` to its query), as the
Trend chart does. The builder's **Drill-down** step appears for it automatically. The
pieces for other surfaces: `metrics.drill_rows(..., spec=, order=, limit=, offset=)`,
`drill_csv` and `format_cell`.

**A type that draws the rows itself** (the starter's `table`) sets `shows_rows=True` as
well: its drill-down design *is* its columns, so the builder calls that step **Columns**
(not optional), hides the design's row limit (that applies to the window **All rows**
opens) and words the summary as pages. Its `build` reads the design from
`options.drilldown`, drops `limit` and calls `drill_rows` with its own `limit`/`offset`;
header and page links are the cell's own URL (`request.path`) with `?order=`/`?page=`,
swapped in place with `hx-target="closest .dash-cell-body"`, and only where the cell
has one (`ctx.dashboard.pk`; the builder's preview has none).

## Navigation — two areas

The sidebar has two areas. Many pages share the `/smallstack/dashboards/` path, so the entries register tuples of `active_prefix` values (`nav.register(active_prefix=(...))`); the longest match wins the highlight.

- **Goals** (`goals_index`): Overview, Goal lists, Metrics, Reports. Metrics, reports and goal lists use `breadcrumb_parent = ("Goals", "goals_index")`.
- **Dashboards**: Overview, My dashboards, Components, Playlists.

URLs did not move.

## Saved cards — `Component` and the component builder

A **metric** is *what* number; a **component** is *a filtered result and how it's drawn*:

```json
{"name": "Requests by method", "type": "metric_group",
 "dataset": "smallstack_requests", "filter_tree": {}, "agg": "count", "period_field": "timestamp",
 "options": {"dimension": "method", "limit": 5}, "visibility": "shared"}
{"name": "Requests", "type": "metric", "metric": "demo_requests", "options": {}}
```

The builder's first step is the source: **a dataset, filtered here** (the dataset picker,
the metric form's filter editor, the roll-up and the period column, over `ComponentForm`'s
`dataset`/`filter_tree`/`agg`/`measure`/`period_field` fields; **Start from a metric's
filter** copies a metric's definition in) or **a saved metric**. Picking a chart while on
a metric switches to its dataset with the filter copied. Changing the dataset drops the
column options and drill-down columns that aren't in the new one and names them
(`cb-cleared`). An unsaved card's rows (the preview, the drill-down designer) are read by
posting the definition: `dashboards/preview-rows/` (the modal fragment, with `narrow`,
`drill`, `order`) and `dashboards/api/preview-rows/` (JSON). A placed card's own rows:
`d/<slug>/cards/<cell_id>/rows/`.

- **The key** is made from the name (`requests_by_method`) and is permanent.
- **Opening a builder filled in:** the metric form takes `metrics/new/?dataset=<key>&filter_tree=<json>&agg=&measure=`
  (what the dataset browser's **Make a metric** modal links to as "Open the full form instead"; anything that doesn't
  apply is left out), and the component
  builder takes `components/new/?metric=<key>&type=<card type>&dimension=<column>` (the metric page's **Make a card**).
  With `then=card&card_type=&dimension=` the metric form continues to the component builder after saving, so a
  grouped roll-up becomes a card through a real, named metric rather than a hidden one.
- **Validation:** a component is checked exactly as a one-cell layout is: a known type,
  a source (its own, checked as a metric is; or a metric the owner may use, on a
  single-value design), and the type's own rules. **Add to goals** needs a single stat
  over a metric: a goal judges a metric, so a stat with its own filter is saved as one first.
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

`dashboards/card-preview/<pk>/` draws one saved card through `render_cell`, with the same access
checks as a dashboard. The components page opens on the gallery (`ComponentCardsDisplay`, its
`default_display`), which loads one per card on `revealed`; the table (`?display=library`) shows it on
hover (`component-list.js`). Both page like every other list here (15 a page, "Rows per page"),
search by name/key/description/source, and narrow by tag and by three filters of the view's own
(`ComponentCRUDView.filter_fields` + `apply_filter`, on the page and the REST list alike):
`?dashboard=<slug>` (the cards a dashboard's layout names — its **Cards** button opens this),
`?dataset=<key>` (cards over it, their own filter or their metric's) and `?type=<design>`.
Previews are `inert`.

## A metric over time — `trends.metric_trend`

`metric_trend(metric, request, period=None, grain=None)` returns the metric's own filter and
aggregation per calendar bucket. Over REST it's `GET dashboards/api/metrics/<key>/trend/?period=&grain=`,
and over MCP it's the `metric_trend` tool. Built on `Dataset.series(dimension, grain=…)`:
day/week/month/quarter/year buckets, weeks starting Monday, `[lo, hi)` bounds.

- **Every bucket of the period is present.** An empty one reads 0 for count/distinct/sum and
  `None` (a gap) for avg/median/min/max/ratio.
- **The running bucket has `partial: true`.**
- **Each point carries `narrow`**, the `[lo, hi)` filter for `m/<key>/rows/?narrow=`, so a bar
  opens exactly its rows. The rows modal drops its period links for a time-narrowed drill.
- **The default grain fits the span:** days up to a month, weeks up to four months, months up to
  two years, then quarters. No period means the last 12 buckets with data, the grain fitted to
  the span of the data itself (`data_span`): a week of rows reads by day, three years by quarter.
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
- The bucket size comes from `trend_grain(period)`: a day for today/yesterday, a week for
  this week/last week/7 days, a quarter for the quarterly periods, a year for the yearly ones,
  otherwise a month (all time too).
- It costs one `metric_trend` series query per goal.

### Printing

`g/<slug>/print/` and `r/<slug>/print/` render `dashboards/print/*.html`, standalone pages rather
than `base.html`: no menus, `data-theme="light"`, and status as a word so a black-and-white
printer loses nothing. `?period=` and `?order=` follow the page, `?week=` prints one week with its
saved values, and `?auto=1` opens the print dialog on arrival. A report with more than three
period columns prints landscape (`ReportPrintView.PORTRAIT_COLUMNS`).

### Weeks and snapshots (`weeks.py`)

A week runs Monday to Sunday, local time. A goal's weekly value is its metric narrowed to `[monday, next monday)` on the period field. `weekly_values()` gets a run of weeks in one `Dataset.series(grain="week")` query per metric. A metric with no period field has the same value every week (`weekly: False`).

A weekly `Snapshot` (see the engine below; rows, summary, complete, taken_by) freezes a week. Each row stores the value, status, target and target text, so later target edits don't rewrite history. A week can have several captures, and pages show the newest.

| Function | What it's for |
|---|---|
| `take_snapshot(goal_list, monday, by=)` / `backfill(goal_list, n)` | save a week / fill past weeks |
| `snapshot_last_week()` | `manage.py snapshot_goals`: adds a capture of last week for every list, tracked or not. `--due` does what the hourly job (`tasks.capture_snapshots`) does. Also `[--list] [--week] [--fill N [--replace]]` |
| `week_page(goal_list, request, monday)` | one week: the snapshot, else live; `change` vs the week before; rows drill to the week's rows (`?narrow=`) |
| `week_grid(goal_list, request, last, count)` + `write_grid_csv` | goals × weeks; saved weeks as they were, the rest live. `grid_order` / `sort_grid` / `grid_sort_links` sort it (`?order=goal` or `w<monday>`, `-` for descending); the page's table resizes, with `data-field` keyed by position |
| `week_trends(goal_list, request, monday)` | the weeks around one week: bars, vs previous, vs the average before, streak, best/worst. `trends_order` / `sort_trends` / `trends_sort_links` sort it (`?order=goal`, `value`, `change`, `average`, `run`) |
| `weeks_payload` | JSON for REST (`dashboards/api/goals/<slug>/weeks/?week=&weeks=`) and MCP (`goal_list_weeks`) |

Snapshots are evaluated with `snapshot_user(goal_list)`: the owner, else `created_by`, else the first active superuser. When shown, a saved value is masked for viewers who can't read its dataset; the row stores `dataset` for that check.

Pages: `g/<slug>/weeks/` (`?week=`, `?view=grid`, `?format=csv`), `g/<slug>/weeks/<monday>/trends/` (every goal around one week, a modal fragment), `g/<slug>/goals/<goal id>/trends/?week=` (one goal over the 13 weeks up to that one, `goal_weeks_trend`; the Trends button on a grid row) and `POST g/<slug>/weeks/<monday>/snapshot/` (`fill=N` to backfill). Editors only.

**Report targets.** A `Report.items` row may carry `target` / `warn` (goal rules). `report_matrix` then sets each cell's `status`, recolours the value from it, and sets `has_targets`. The page adds a Target column, the CSV adds Target, At risk and per-period status columns, and `report_values` adds `target` and per-value `status`.

### The snapshot engine (`snapshots.py`, `Snapshot`, `SnapshotTracker`)

The weekly tools above are one cadence of a general engine: `hourly`, `daily`, `weekly`, `monthly`
or `quarterly`, in the site's time zone, weeks starting Monday.

| Call | What it does |
|---|---|
| `period_at(cadence, moment)`, `current_period`, `last_closed`, `Period.shifted(n)` | the period arithmetic. Hours are real time, so clock changes neither repeat nor skip one |
| `window_value(metric, request, period, past=)` | a metric for one period, rates included. A date-only column has no hourly value, and with `past` a number that doesn't depend on time has none: an error, never a wrong figure |
| `capture(obj, period, by=, reason=, past=)` | adds a capture. Never overwrites |
| `latest_captures`, `captures_of` | the newest per period (what pages show), or every capture of one |
| `set_tracking(obj, cadences)`, `tracked_cadences(obj)` | which cadences run. Turning one off keeps its captures |
| `capture_due()`, `prune()` | the hourly job, `tasks.capture_snapshots` (`@scheduled(cron="5 * * * *")`). It captures each tracker's latest ended period if it has none, so it's safe to re-run and catches up within a period |
| `fill(obj, cadence, n)` | capture past periods with none, against today's targets |
| `recapture_for_value(metric, day)` | a hand-entered value changed: adds a capture to each period holding that day, keeping its targets. Not hourly |
| `history_grid`, `history_payload` | goals × periods from captures only. A period with none is blank, never worked out now |

Snapshot rows list every dataset behind the number in `datasets`, and `weeks._masked` checks them
all, because a rate has no dataset of its own.

**Targets per cadence.** A goal may carry `targets`: `{"hourly": {"target": rule, "warn"?: rule}}`.
`goals.goal_at(goal, cadence, metric)` picks the rule: that cadence's own; else the main target for
`weekly`, and for a number where `scales_with_time(metric)` is false (an average, a rate, a latest
reading, a number with no period field); else `target` is `None`, and the cell keeps its value with
status `none`, labelled **No target**. The main target also judges the meeting view, whatever its
period. Rows store the rule they were judged against.

**Another subject.** `Snapshot` and `SnapshotTracker` point at any model. To capture one, call
`register_subject(Model, rows=fn, user=fn, ready=fn)` in `ready()`, where `rows(obj, request,
period, past=)` returns dicts with a `status`, and add a `GenericRelation` so deleting the object
takes its captures. `history_grid` and the History page read goal rows, so a new kind of subject
needs its own reading.

**Settings.** `SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES` (default `["weekly"]`, `[]` for fully opt-in)
and `SMALLSTACK_SNAPSHOT_KEEP_DAYS` (default hourly 90, daily 730; other cadences are kept for good).

Pages: `g/<slug>/history/` (`?cadence=`, `?last=`, `?at=`, `?capture=`, `?format=csv`).

## On your own pages — `{% dashboard %}` and the rest

```django
{% load dashboard_tags %}
{% dashboard "site-health" %}                                   {# opens on its own period #}
{% dashboard "site-health" period="ytd" title=False %}          {# "all" = all time #}
{% dashboard board lazy=False %}                                {# render the cards now, no htmx #}
```

- **On a theme of your own** (a base template that doesn't extend `smallstack/base.html`): put `{% smallstack_assets %}` in its `<head>` and `{% smallstack_modal %}` before `</body>`, with the theme scripts `adding-your-own-theme.md` lists. The embed brings its own stylesheet; those two bring the tokens, components and drill-down modal it shares. `/starter/own-theme/` in the showcase is a working example.
- **What it renders:** the dashboard's cards through the same cell endpoint, access checks and
  drill-down modal as the dashboard page.
- **Layout:** plain CSS grid using the page's geometry (12 columns, 70px rows); on a phone the
  cards stack in reading order.
- **When it renders nothing:** a dashboard the viewer may not open, or an anonymous viewer (cards
  load from a login-protected endpoint). A page never reveals that a dashboard exists.
- **Building your own markup:** `boards.board_embed(dashboard, request, period=, lazy=)` returns
  the same structure for a page that wants different markup.

### The rest of the pieces, and the data behind them

Every piece the Dashboards and Goals pages draw can go on a page of your own, with the
same access checks (nothing is rendered for something the viewer may not open) and the
same drill-down modal. `{% load dashboard_tags %}`:

| Tag | Draws |
|---|---|
| `{% dashboard "slug" period= title= lazy= %}` | a dashboard's cards (above) |
| `{% metric_card "key" period= label= %}` | one metric as a stat card (below) |
| `{% goal_list "slug" period= title= %}` | a goal list judged: summary, sections, status, value, target, trend; names show their description on hover |
| `{% card "key" period= height= %}` | one saved card, drawn as a dashboard draws it (a card over a saved metric drills; one with its own filter drills only on a dashboard) |
| `{% report "slug" title= %}` | a report's table, without the page's sorting |
| `{% playlist "slug" … %}` | a playlist, playing (see Playlists) |
| `{% calendar_card … %}` | a calendar (`calendar.md`) |

`period` is a period key, `"all"` for all time, or omitted for the thing's own.

**Data tags, for markup of your own.** Same engine, same access rules; `None` for
something the viewer may not open:

| Tag | Gives |
|---|---|
| `{% metric_value "key" period= as m %}` | `{metric, result, comparison}`: `m.result` is the `MetricResult` (`display`, `value`, `unit`, `state`, `restricted`, `error`), `m.comparison` `{dir, text}` or None |
| `{% metric_series "key" period= grain= as t %}` | `trends.metric_trend`: `t.points` `[{label, value, display, partial, narrow}]` |
| `{% goal_values "slug" period= as g %}` | `goals.goals_embed`: `summary`, `attention`, `sections`, `rows` (each with `label`, `description`, `status`, `status_label`, `display`, `target_text`, `gap_text`, `trend`) |
| `{% report_values "slug" as r %}` | `reports.present_report`: `columns`, `rows` (`cells`, `delta`, `span`), `lede` |
| `{% dashboard_values "slug" period= as b %}` | `boards.board_values`: every card evaluated |

`{% dashboards_assets %}` writes the stylesheet and scripts such markup needs
(`dashboards.css`, every card type's media, the `data-about` hover script); the
whole-piece tags bring their own. Use the classes the pages use (`.rp-value
.rp-value--<state>`, `.ix-compare`, `.gl-pill`) and theme variables, never colours of
your own.

`/starter/dashboard/` (`apps/showcase/templates/showcase/starter/dashboard.html`) is a working page using every
tag, and drawing the same numbers in markup of its own with the data tags.

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
| `metric_rows` | `GET dashboards/api/metrics/<key>/rows/?period=&order=&limit=` (REST also takes `&drill=<json>`, a card's drill-down design) | the rows behind the number, as JSON |
| `get_metric` `get_dashboard` `get_report` `get_goal_list` `get_playlist` `get_component` | `GET /smallstack/api/dashboards/<noun>/<id>/` | read one back in full. The tools also take `key` / `slug` in place of `id` (`mcp_lookup_field`), as do `update_*` and `delete_*` |
| `goal_list_values` / `goal_list_weeks` | `GET dashboards/api/goals/<slug>/values/`, `…/weeks/` | a list judged; a list week over week |
| `goal_list_save_week` | `POST dashboards/api/goals/<slug>/weeks/<week>/save/` | freeze a week (`fill` backfills, MCP only) |
| `goal_list_tracking` | `GET`/`POST dashboards/api/goals/<slug>/tracking/` | the cadences a list is captured on |
| `goal_list_capture` | `POST dashboards/api/goals/<slug>/snapshots/` | capture the current period, or `fill` past ones |
| `goal_list_history` | `GET dashboards/api/goals/<slug>/snapshots/?cadence=` | captures only: goals × periods |
| `metric_record_value` / `metric_delete_value` | `GET`/`POST dashboards/api/metrics/<key>/entries/` (removing one is MCP or the page) | a hand-entered metric's value for a date |
| `list_dashboard_components` | `GET dashboards/api/components/` | card types, options, default sizes, periods (+ widgets for staff: the `widget` type, "Info card", places one published `DashboardWidget`) |
| `dashboard_add_card` / `dashboard_remove_card` | (PATCH `layout`) | edit one card without rewriting the layout |
| `card_preview` | `POST dashboards/api/card-preview/` | dry-run an unsaved card: draw it and list every problem |
| `metric_usage` | — | where a metric is used, before an edit or delete |
| `goal_list_add_goal` | — | append one goal to a section of a goal list |
| `dashboard_share` (`everyone`, `add`/`remove` usernames; nothing = report) | `GET /smallstack/api/dashboards/boards/<pk>/` reads `sharing` | who may open a personal dashboard; its owner still edits it |
| `dashboard_snapshot` | `GET dashboards/api/boards/<slug>/values/` | every card with its live value, to check your work. Stores nothing; a chart or calendar card has no one number (`card_preview` draws it) |
| `dashboard_set_picture` (base64, or `remove`) | `POST`/`DELETE dashboards/api/boards/<slug>/picture/` (multipart `image`, `alt`) | the dashboard's picture. The JSON CRUD can't carry a file, so `cover_image` is read-only there (its URL) and left out of the MCP write schema. A session caller sends `X-CSRFToken` |
| `report_values` | `GET dashboards/api/reports/<slug>/values/` | a report's matrix |
| `playlist_slides` | `GET dashboards/api/playlists/<slug>/slides/` | a playlist as the caller sees it (create/edit with `create_playlist` / `update_playlist`) |

**The loop** an agent should follow:

1. `list_datasets` → `describe_dataset {key}` (columns, filterable fields + ops, periods).
2. `metric_preview {dataset, filter_tree, agg, measure, period_field}` — iterate
   until `problems` is empty **and** `row_count`/`value` are plausible.
3. `create_metric` with the same fields (+ `key`, `name`, `visibility`).
4. `create_dashboard {name}` (the slug is made from the name and returned) → `dashboard_add_card` per card.
5. `dashboard_snapshot {dashboard}` — confirm no cell has an `error`.

Everything runs as the token's user: ownership and dataset access apply
exactly as on the pages.

**Writing over REST: what replaces, what's final.**
- **A `layout` write replaces the whole list.** `PATCH …/boards/<id>/ {"layout": [...]}` keeps only
  the cells sent, so send every cell (read the board first, change it, send it all back). To change
  one card, use `dashboard_add_card` / `dashboard_remove_card`. `{"layout": null}` is refused.
- **Archive with `"archived": true`** (`false` restores) on any metric, card, dashboard, report,
  playlist or goal list: `PATCH …/boards/<id>/ {"archived": true}` or the `update_*` MCP tool. An
  archived row leaves lists and pickers and is still drawn wherever it's used; `archived_at` reads
  when. Leaving `archived` out keeps the row as it is.
- **`DELETE` removes the row for good**: it isn't an archive, nothing lists it afterwards, and
  its slug or key is free again.
- **Changing a `slug` breaks the old address.** There is no redirect: links, bookmarks and
  `{% dashboard %}` embeds by the old slug 404 (playlists and Goals cards are carried over by
  `signals.py`). Only an administrator may change one (see *Addresses*).

**Refusals, not guesses.** REST and MCP refuse a period, grain or week that isn't one (a page falls
back quietly via `requested_period`; a client can't see that it got all time). The MCP dispatcher
holds every tool to its `additionalProperties: false`, so a misspelt argument is an error rather than
a silent no-op. `isError` follows a truthy `error`, so `metric_value`'s `"error": null` is a success.
`list_datasets` / `describe_dataset` cover every dataset the caller may read; `query_tool` says
whether it also has a `query_dataset_<key>` tool. REST 404s on these routes are JSON.

**Empty aggregates.** `count`/`distinct`/`sum` of no rows is 0; `avg`/`median`/`min`/`max` of no rows is `None`,
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
  predecessor (`today`→`yesterday`, `wtd`→`pwtd`, `pwtd`→`ppwtd`, `mtd`→`pmtd`, `qtd`→`pqtr`, `ytd`→`prev_year`,
  `this_month`→`pmtd`, `this_year`→`prev_year`; `periods.PREVIOUS_PERIOD`). A still-running period says **"vs all of last month"**
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
  CRUDView hook any app can override. Every other kind's delete says what goes and what
  stays too: a report offers a last CSV, a dashboard its layout JSON, a card the dashboards
  it's placed on, a goal list its saved weekly history (see **Confirmations** above). List views load these into the stat modal; table views do too via
  the framework's opt-in `confirm_modal` on a CRUD delete action (set in `row_actions`).

## Pages

| URL | |
|---|---|
| `/smallstack/` | the staff home: the **system dashboard** (`system_key="smallstack"`) of every published `DashboardWidget` — see dashboard-widgets.md. `boards.system_dashboard(key, …)` + `sync_widgets` |
| `/smallstack/dashboards/` | the **Dashboards** overview: dashboards (cards with a Sort select, or `?boards=list`, a table), playlists, saved cards. Each is a resizable table with its own sort (`?dash=`, `?playlists=`, `?components=`; `views.section_sort`) |
| `/smallstack/goals/` | the **Goals** overview: goal lists (live summaries), metrics (live values, `?period=` + comparisons), reports. Each is a resizable table with its own sort (`?lists=`, `?metrics=`, `?reports=`; `views.section_sort`) |
| `…/mine/` | **My dashboards**: the personal ones you own plus the shared ones you made (`Dashboard.objects.mine(user)`, which reads `created_by`; `owner` is blank once a row is shared). Newest change first, each with its "needs attention" line. In the sidebar beside Dashboards |
| `…/d/<slug>/` | a dashboard — controls in the page header, the period bar above the cards, each card's ⋯ menu, **Edit layout** (drag/resize, Add card, Remove, Save) |
| `…/d/<slug>/cards/<id>/edit/` | **Edit card**: the component builder for one card, as a fragment for the dashboard's dialog (`DashboardCardEditView`) |
| `…/d/<slug>/cards/<id>/copy/` (POST, `metric=1`) | **Make a unique copy** / **Give it its own metric**: one card becomes the dashboard's own (`DashboardCardCopyView` → `boards.make_card_unique`) |
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
datasets, a "Server error rate" rate made from two of them, a "Site health"
dashboard, a "Monthly KPIs" report). It's the framework's own defaults bundle
(`dashboard_defaults.py`, `auto=False`), and it installs **only that demo**. An app
ships its own metrics, cards, dashboards and goal lists in the same format, but those
are applied by `migrate` (after every migrate) or `manage.py dashboard_defaults
[--app <label>]`, never by `seed_dashboards`; they're kept in step without overwriting
people's edits. See [`app-defaults.md`](app-defaults.md).

## The dashboard page — controls, card menus, Edit card

The page (`dashboard.html`) is three separable pieces, so the cards can be drawn
anywhere without the rest:

- **The cards** are the grid in `#dash-page`. `{% dashboard %}` draws the same cards
  from its own template (`includes/embed.html`, plain CSS grid): no controls, no
  menus, nothing to edit. Changing the page never changes an embed.
- **The controls** are `includes/dashboard_controls.html` (Updated / Refresh,
  Duplicate, and for editors Share, Archive, Cards, Settings and Edit layout),
  included in the **page header**.
  `dashboard.js` finds each by id, so a page of your own can include them wherever
  its header is. Only the period bar stays above the cards, because it changes what
  they show. All of them carry `.dash-view-only` and step aside while arranging
  (`body.dash-editing-page`).
- **Each card's menu** is the ⋯ button in the cell (`.dash-cell-more`,
  `data-cell-menu`) and one `#dash-card-menu` for the page, positioned at the card
  that opened it (a cell clips what's inside it). The view gives each cell
  `label`, `edit_url` and `metric_url`; the button carries the URLs and the menu
  shows the entries that have one. Edit, Move or resize and Remove are only
  rendered for someone who can edit the dashboard.

**Edit card** (`DashboardCardEditView`, `d/<slug>/cards/<id>/edit/`) is the
component builder in a `<dialog>`. The builder's form is one partial,
`includes/component_builder.html`, drawn in three modes (`cb_mode`):

| `cb_mode` | Where | Saves |
|---|---|---|
| `page` | the builder's own page | a `Component` (the CRUD form) |
| `placed` | the dialog, for a cell that names a saved card | that `Component`, for someone who may edit it; `signals.py` refreshes every dashboard showing it |
| `cell` | the dialog, for a card of this dashboard only | type, metric, options and title back into this dashboard's layout, validated by `Dashboard.clean` |

`dashboard.js` fetches the fragment, calls
`SmallStackDashboards.startComponentBuilder()` (the builder's script starts on
demand as well as on its page), and posts the form: `{"ok": true}` reloads the
page, a `422` is the form again with what was wrong. In the dialog the preview
is `inert`, because a tap on its number would open the rows modal underneath.
Remove from the menu saves the layout without that cell; the card's place and
size are never touched by an edit.

**A card other dashboards show** (`cell.linked`: the cell names a saved card that
`boards.placement_counts` finds on more than one dashboard) is marked for editors:
`.dash-cell--linked` on the cell and a `.dash-cell-linked` tab with the count.
Its menu offers **Make a unique copy**, which posts to `…/copy/`:

- `boards.make_card_unique(dashboard, cell_id, user, copy_metric=)` drops the
  cell's `component` reference (the cell already carries the design; the card's
  name becomes its title), so later edits to the saved card no longer reach it.
- With `copy_metric` it also copies the metric (`METRIC_COPIED` fields, named
  `"<metric> (<dashboard>)"`, owned like the dashboard) and points the card at
  the copy. A hand-entered metric is never copied: its values belong to it.
- One transaction: a layout or metric that won't save leaves nothing behind.

A card that was never a saved one gets **Give it its own metric** (the same call,
metric only). Together they are how a duplicated dashboard gets numbers of its
own. The menu's **Edit the metric** (`metric_edit_url`, when the viewer may edit
it) leads to the copy's filter.

## Help on every page

Every page here carries a help bubble beside its title (`{% help_bubble
"dashboards" "<slug>" %}`, see help-documentation.md), opening one of the "In
short" pages in `apps/dashboards/content/`:

| Page(s) | Opens |
|---|---|
| the two overviews | `how-it-fits`: dataset → metric → component → dashboards, goal lists, reports |
| metrics list, a metric, the metric builder | `metric` |
| components list, the component builder | `component` |
| dashboards list, a dashboard, its settings, My dashboards, `/smallstack/` | `dashboard` |
| goal lists, a goal list, its editor, Add to goals | `goal-list` |
| Weeks, Trends, History | `history` |
| reports list, a report, its editor | `report` |
| playlists list, a playlist, its settings | `playlist` |
| the Datasets browser (`apps/datasets`) | `dataset` |

A new page gets a bubble, and a new kind of thing gets a page of its own.
`tests/test_help_bubbles.py` checks that every bubble opens a page that
exists, that every "In short" page is opened from somewhere, and that each
stays a page to a page and a half.

**What a metric means, on hover.** Wherever metrics or goals are listed (the
metric library, the Goals overview's metrics, a goal list, a week and the
week-by-week grid) the name carries its description as `data-about`, and
`dashboards/js/about-info.js` shows it in a hover box (on focus too) for any
element with that attribute. A goal's text is its card's description, else its
metric's (`goals.source_description`; rows carry it as `description`), always read
from the list as it is now, never from a capture. Playlist slides leave it out.

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
- `SMALLSTACK_DASHBOARD_DEFAULTS_SYNC` (default on, off in test settings): apply apps'
  `dashboard_defaults.py` after every migrate ([`app-defaults.md`](app-defaults.md)).
- `SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES` (`["weekly"]`), `SMALLSTACK_SNAPSHOT_KEEP_DAYS`
  (`{"hourly": 90, "daily": 730}`): see *The snapshot engine*.
