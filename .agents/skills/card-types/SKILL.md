---
name: card-types
description: "Publish a dashboard card type — the extension API: register_component_type(ComponentType(...)) from ready(), every field, what build gets (CellContext) and the data helpers, rows links, options_schema types and your own editors, validate vs the shared checks, media + the dashboards:card-drawn event, what agents see, how to test. Read before adding a chart, gauge, table or any card design"
license: MIT
metadata:
  source: "docs/skills/card-types.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/card-types.md` by `make skills-index` — edit the source, not this file.

# Publishing a dashboard card type

The API a project (or a reusable app) uses to add a card design to the dashboards:
a chart over a library, a gauge, a table, a navigation card, anything. One
registration gives the type every surface the built-in cards have; the project
never edits `apps/dashboards`. The worked reference is
`apps/website/dashboard_cards.py` (bar chart, gauge, table, pie, ranked bars, trend
chart) with its templates under `templates/website/cells/` and
`static/website/css/dashboard-cards.css`; the framework's own types (`metric` single
stat, `metric_group` grouped stat, `text` note, `menu`, `widget` info card, `calendar`, `goals`)
are registered the same way in
`apps/dashboards/components.py` and `apps/calendar`.

Read `dashboards.md` first for what a metric, a card's source, a dashboard and the
builder are. This file is the contract.

## In one screen

```python
# myapp/dashboard_cards.py
from apps.dashboards.components import CellContext, ComponentType, cell_title, register_component_type
from apps.dashboards.trends import metric_trend

def build_sparkline(cell: dict, ctx: CellContext) -> dict:
    trend = metric_trend(ctx.metric, ctx.request, ctx.period, (cell.get("options") or {}).get("grain"))
    return {"label": cell_title(cell) or ctx.metric.name, "trend": trend}

def register() -> None:
    register_component_type(ComponentType(
        key="sparkline",                      # stored in layouts; stable for life
        label="Sparkline",
        description="A metric's recent buckets as a small line.",
        group="Charts",
        icon="M3 17l6-6 4 4 8-8",             # an SVG path on a 24×24 grid
        template="myapp/cells/sparkline.html",
        build=build_sparkline,
        needs_metric=True,                    # draws data: a source is required
        requires=frozenset({"date"}),         # … with a date column
        default_size=(4, 2),
        options_schema=[{"name": "grain", "label": "Buckets", "type": "choice",
                         "choices": [["", "Fit"], ["day", "Days"], ["week", "Weeks"]], "default": ""}],
        media={"css": ["myapp/css/cards.css"]},
    ))
```

```python
# myapp/apps.py
class MyAppConfig(AppConfig):
    def ready(self) -> None:
        from . import dashboard_cards
        dashboard_cards.register()
```

That is the whole integration. From here the type is stored in `Dashboard.layout`
and `Component`, validated on save from the page, REST and MCP, offered in the
component builder's palette and (if it needs no source, or is `single_value`) a
dashboard's **Add card** dialog, placeable by an agent, lazily loaded, refreshed,
access-checked, and drawn in previews, embeds and playlists.

## `ComponentType` — every field

| Field | Type | Meaning |
|---|---|---|
| `key` | str | The type's name in a cell's `type`. Registering a key again **replaces** it (re-import safe; also how a project overrides a built-in). Never rename a shipped key: saved layouts carry it. |
| `label`, `description` | str | The palette tile and Add-card entry; `description` is also what `list_dashboard_components` tells an agent, so say what the card draws and what its options mean. |
| `group` | str | Palette section: `"Stats"`, `"Info"`, `"Charts"` are the built-in order; any other name follows. |
| `icon` | str | An SVG `<path d="…">` on a 24×24 grid. Trusted: never user text. |
| `template` | str | The cell's template. Rendered with `build`'s dict plus `cell`, `dashboard`, `request`, `period`. |
| `build` | `(cell, ctx) -> dict` | The template context. May raise: the cell renders an error card and the page stands. |
| `needs_metric` | bool | The card **draws data**, so it needs a source: a dataset the card filters itself (`dataset`, `filter_tree`, `agg`, `measure`, `period_field`) or, for a `single_value` type, a saved `metric`. `False` = no source allowed (a note, a menu). The name is historical. |
| `single_value` | bool | Boils down to one number. Only such a type may draw a saved dataset metric. A chart needs the rows, so it filters a dataset of its own, except over a metric with no dataset to filter (entered by hand, a rate), which a design that doesn't split it into groups (the trend) may draw as it is. It is offered in the dashboard's Add card, and a saved card of it over a metric can be a goal. |
| `requires` | frozenset[str] | Dataset capabilities the source must have, from `apps.datasets.capabilities`: `"measure"` (a numeric column), `"dimension"` (a column to group by), `"dimension2"`, `"date"` (a period column). The builder dims the tile with the reason; a save is refused. A trend chart requires `date`; a split requires `dimension`. |
| `default_size` | (w, h) | Grid units on a 12-column grid, used when a cell omits `w`/`h`. |
| `options_schema` | list[dict] | What the builder, the Add card dialog and `validate` know about `options`. See below. |
| `validate` | `(cell) -> list[str]` | The type's own rules on top of the shared checks. Return problems as sentences; the caller prefixes the path (`layout[2].options: …`). |
| `visible_to` | `(user) -> bool` | Who may see the card at all, beyond dashboard visibility; `None` = anyone who can open the dashboard. The info card passes a staff check (`lambda u: u.is_staff`); `describe_types` reports the framework's own as `staff_only`. A project's own `visible_to` is enforced but not reported as `staff_only` (only the framework's private check is). |
| `media` | `{"js": [...], "css": [...]}` | Static paths the card needs on any page that shows it. See *Scripts*. |
| `stylable` | bool | Honours the shared card styling (`options.style`: format, unit, size, colour, title size/colour, alignment) and the card's own colour rules (`options.thresholds`). Read them with `card_style(cell)` / `styled_value(...)`. The builder shows a **Style it** step. |
| `style_settings` | tuple[str, …] | Which styling settings apply; empty = all. A card whose headline is text has no number format or unit. |
| `drillable` | bool | Its numbers open rows, so it takes a drill-down design (`options.drilldown`: columns, headings, formats, sort, limit). The builder shows a **Drill-down** step; the build must pass every rows URL through `rows_url(ctx, **drill_params(cell))` or `with_drill(url, cell)`. |
| `publishes` | bool | Its clicks can narrow other cards (`options.publish`) though it draws no data itself: the calendar. An element with `data-day="YYYY-MM-DD"` (and `data-day-label`) sends that day on the field `date`; a listener maps it to its own date column, its period column by default. |
| `shows_rows` | bool | Draws the rows itself (the table), so the drill-down design **is** its columns: the builder calls the step **Columns**, hides the design's row limit (it applies to the window *All rows* opens) and words the summary as pages. |

## What `build` gets and returns

```python
@dataclass
class CellContext:
    request: HttpRequest            # the viewer; pass it to every data call (per-user scoping)
    dashboard: Dashboard | None     # unsaved (pk None) in the builder's preview
    metric: Metric | None           # the card's source as a Metric — saved, or built from
                                    #   the card's own dataset definition (pk None); None
                                    #   for a type with needs_metric=False
    period: str | None              # the dashboard's period, already narrowed to the cell
                                    #   (use_period: false → None)
    rows_url: str                   # where this card's rows open; "" when they can't
    narrow: Any                     # the slice a linked card sent (already in metric), or None
```

`ctx.metric` is the one thing to know: whether the card names a saved metric or
carries its own filter, the build sees a `Metric` and every helper takes it, so a
chart over a card's own filter and a stat over a saved metric are the same code.
`metric.pk is None` (or `is_inline(metric)`) tells them apart when it matters (a link
to "the metric's page" exists only for a saved one).

Return a plain dict for the template. The framework adds `cell`, `dashboard`,
`request` and `period`. Access is checked before `build` runs (`visible_to`, and
`may_read(metric, user)` for the source), and a build that raises is logged and
replaced by an error card, so don't wrap everything in try/except; do handle the
data-level outcomes your helpers report (`restricted`, `error`, no rows) in the
template.

**The cell's own URL** is `request.path` while a dashboard cell renders
(`d/<slug>/cells/<id>/`), and its query string is yours: a card that re-renders
itself in place (the table's `?order=`/`?page=`) builds links from
`request.path` + `request.GET` and swaps with `hx-target="closest .dash-cell-body"`.
Only where the cell has a URL of its own: `ctx.dashboard.pk is not None and cell.get("id")`
(the builder's preview has neither).

## The data

All of it takes the viewer's `request` and the card's `metric`, and returns the same
numbers REST and MCP return.

| Need | Call |
|---|---|
| One number | `metrics.evaluate(metric, request, period=) → MetricResult` (`.ok`, `.value`, `.display`, `.unit`, `.state`, `.error`, `.restricted`) — or `metric_card_context(metric, request, period=, label=, period_in_label=False, rows=ctx.rows_url)` for the stat card's whole context |
| Split by a column | `metrics.group_values(metric, request, dimension, limit=, other=, period=) → [{label, raw, value, display, state}]`, or `build_metric_group(cell, ctx)` for the grouped-stat context with per-group `drill_url` and `narrow` already made |
| Over time | `trends.metric_trend(metric, request, period, grain) → {ok, error, restricted, grain, unit, points: [{label, lo, hi, value, display, state, partial, narrow}]}` |
| The rows | `metrics.drill_rows(metric, request, period=, extra_tree=, spec=, order=, limit=, offset=) → {columns, rows, total, sort}`; `metrics.format_cell(value, fmt, column_type)` |
| Anything else | `metrics.resolve_dataset(metric).series(...)` / `.rows(...)` / `.queryset(request, filter_tree=metrics.effective_tree(metric, period))` — the dataset's own API, with the card's filter and period applied |
| Formatting | `styled_value(value, metric, card_style(cell), state) → {display, unit, state}` (the card's format, unit and rules, else the metric's); `metrics.format_value(value, fmt, unit)`; `metrics.state_for(value, thresholds)` |

## Linked cards (publish / listen)

Any data card can be linked to others on its dashboard (`options.publish`,
`options.listen`; `dashboards.md` → *Linked cards*). Your type takes part
without code of its own as long as it follows the two rules below: its
clickable things are rows links from `rows_url(ctx, narrow=…)` (cards.js reads
the `narrow` off the clicked element's `hx-get` or `href`), and its numbers
come from `ctx.metric`, which is already narrowed when the card is listening.
`ctx.narrow` holds the slice itself, for a card that wants to say what it's
showing. Mark the type `drillable` to be offered *Send clicks to*.

## Rows links (the drill-down modal)

Every number a card draws can open its rows in the global stat modal. Build the URL
with `rows_url(ctx, narrow=json.dumps(tree), **drill_params(cell))` — `narrow` is an
extra filter AND-ed on (a group, a bucket's `[lo, hi)`; `group_values` and
`metric_trend` hand you one per row), `drill_params` adds the card's drill-down design,
and `rows_url` adds the period and knows where this card's rows live (a saved metric's
rows route, or the card's place on the dashboard, or the preview route while unsaved).
Then in the template:

```html
<button type="button" hx-get="{{ p.rows_url }}" hx-target="#stat-modal-body" hx-swap="innerHTML"
        data-stat-modal="{{ label }}, {{ p.label }}" aria-haspopup="dialog"
        aria-label="{{ p.label }}: {{ p.display }}, show the rows">…</button>
```

A bare `<a href="{{ url }}">` works too (the modal is progressive enhancement over the
same URL). `with_drill(url, cell)` appends the design to a URL you already have.

## `options_schema`

Each entry: `{"name", "label", "type", "default"?, "required"?, "choices"?, "min"?, "max"?, "help"?}`.

| `type` | Builder / Add card draw | Stored as |
|---|---|---|
| `choice` | a select over `choices` | the value |
| `multichoice` | a tick-list over `choices` | one comma-separated string |
| `integer`, `number` | a number field (`min`/`max`) | int / float |
| `text` | a text field | str |
| `boolean` | a checkbox | bool |
| `markdown` | a textarea | str (render with `apps.smallstack.transforms.render_markdown`) |
| `column` | a select over the source's dataset columns (dimensions) | the column name — checked on save against the dataset |
| `widget` | a select over published `DashboardWidget`s | the widget key |
| `links` | rows of words / address / new window, orderable | `[{label, url, new_window?}]` |
| *anything else* | your own editor (see *Scripts*); the Add card dialog falls back to a text field | as your editor `set`s it — give the type a `validate` |

`choices` is `[[value, label], …]` or a callable `choices(user)` returning that (options
whose values are the viewer's own rows). A `choice` may add `"widget": "segmented"` (pills
in a row; an option named `align` gets alignment icons) or `"widget": "swatches"` (colour
dots: give each value a rule `.cb-swatch--<option>-<value> { background: var(--…) }` in
your stylesheet). Small settings sit side by side in the builder; a markdown or text box,
a tick-list or a links editor takes the whole row. `required` makes the builder's preview say
"Choose a … to see the card" until it's set; it is **not** enforced on save — require
the option in `validate` (`'dimension' (the column to group by) is required`). `default` fills
the editor and is what `describe_types` tells an agent; the build should still apply it
(`opts.get("limit", 6)`), since REST and MCP store exactly what they're given.

The builder keeps a design's options aside while another design is tried and restores
them on the way back; an option name shared between designs (`dimension`) carries
across. Changing the dataset clears `column` options and drill-down columns that aren't
in the new one, and says so.

## `validate` and the shared checks

Done for you, for every type, before `validate` runs: the cell's shape (known keys,
`options` an object, grid bounds, unique ids, no overlap), the source rule (a data card
has a dataset of its own or a metric that exists and the owner may use — a dataset metric on a
`single_value` type only, a hand-entered or rate one on any type whose `requires` it meets; a data-free type takes no source), `requires` against the dataset's
capabilities, `column` options against the dataset, `style`/`thresholds` for a
`stylable` type (and refused for one that isn't), `drilldown` for a `drillable` type
(and refused otherwise).

Yours: the meaning of your own options. Return sentences, one per problem, naming the
option in quotes; keep them short, they're shown to people and to agents:

```python
def validate_trend(cell: dict) -> list[str]:
    opts = cell.get("options") or {}
    problems = []
    if opts.get("kind", "bars") not in dict(KINDS):
        problems.append(f"'kind' must be one of {[k for k, _ in KINDS]}")
    return problems
```

`validate` sees the cell as stored (no `ctx`, no request): check shapes and values,
not data. The same function runs on a saved component, a layout cell, a REST body, an
MCP call and the builder's preview, so one message reaches every surface.

## Templates

- Theme tokens only: `var(--card-bg)`, `var(--card-border)`, `var(--body-fg)`,
  `var(--body-quiet-color)`, `var(--primary)`, `var(--success-fg)` / `--warning-fg` /
  `--error-fg`, `var(--series-1)` … `--series-8` for categorical colour. No hex
  literals (`modern-dark-theme.md`).
- No inline script or `onclick`: the CSP's `script-src` is `'self'`. Behaviour is
  `data-` attributes read by a static script; data goes to it with `{{ x|json_script }}`.
- A `stylable` card puts `{{ style.classes }}` on its root (`cs-size-l`, `cs-color-state`,
  `cs-align-center`, …) and styles them; `dashboard-cards.css` shows the set for the trend.
- Leave the top-right corner to the card's ⋯ menu button (1.75rem, 6px in): give
  your top row the class `dash-cell-toprow`, or pad it `2.5rem` on the right, so a
  heading or a total never sits under it.
- Fill the cell: the root is `height: 100%` inside the grid item; the dashboard's period
  is already applied, so don't repeat it in the card unless the card ignores it.
- Say the data-level outcomes in the card, quietly: *You don't have access to this
  metric's data.* / the error / *No rows in last 7 days.*
- A chart carries an `sr-only` table of its values (the trend template is the pattern),
  and every interactive mark is a `<button>` with an `aria-label` that reads the value.

Previews on the components page are `inert`; the builder's preview is live but swaps by
hand (see the event below).

## Scripts (a chart library, an option editor)

`media={"js": [...], "css": [...]}` lists static paths. `{% component_media %}` writes
each file once, `defer`, in registration order, on every page that can show cards:
dashboards, `{% dashboard %}` embeds (so any project page), playlists, the components
page (gallery and the table's hover peek), the component builder and the Edit card
dialog. Vendor the library into your app's `static/`; the CSP allows `'self'` only
(add an origin to `CONTENT_SECURITY_POLICY["DIRECTIVES"]["script-src"]` only if you must).

Ahead of your files it writes `dashboards/js/cards.js`, which fires
**`dashboards:card-drawn`** on the element that now holds a card's HTML, however it got
there — an htmx cell, an eager embed, the builder's preview, the gallery — once per
card and never for a cell still loading. One listener mounts everywhere:

```js
document.addEventListener("dashboards:card-drawn", function (e) {
    e.target.querySelectorAll("[data-sparkline]:not([data-mounted])").forEach(mount);
});
function mount(el) {
    var series = JSON.parse(document.getElementById(el.dataset.sparkline).textContent);
    var accent = getComputedStyle(el).getPropertyValue("--primary").trim();   // follows the palette
    el.dataset.mounted = "1";
    // … draw with your library …
}
```

`SmallStackDashboards.cardDrawn(el)` fires the event for HTML your own script placed.

**An option editor of your own.** An `options_schema` entry whose `type` is not in the
table above is drawn by the editor you register — in a `media` script, which runs
before the builder:

```js
window.SmallStackDashboards = window.SmallStackDashboards || {};
(window.SmallStackDashboards.optionEditors = window.SmallStackDashboards.optionEditors || {})
    .axis = function (api) {        // {spec, value, set(value), columns(done), source()}
        var box = document.createElement("div");
        // … inputs reflecting api.value …
        box.addEventListener("input", function () { api.set(readAxis(box)); });
        return box;                 // appended to the builder's "What it shows" step
    };
```

`set(value)` stores the option (`null`/`""` removes it) and redraws the preview;
`columns(done)` hands `done([[name, label], …])` the source's dataset columns;
`source()` is `{dataset, caps, …}` or null. The dashboard's Add card dialog uses the
same registry with `{spec, value: the default, set}`. The value is stored as given:
the editor is a convenience, `validate` is the check.

## What agents and REST see

`describe_types()` (the `list_dashboard_components` MCP tool, and the data the builder
and Add card read) lists each type as `{type, label, description, needs_metric,
single_value, requires, options, default_size, group, icon, media, stylable, style_settings,
drillable, shows_rows, publishes, staff_only}` (`publishes` is true for any drillable data card
as well; the MCP tool drops `icon` and `media` and adds `shared_options`) with `choices(user)` resolved for the caller. An
agent then places one with `dashboard_add_card {type, dataset, filter_tree, …, options}`
or `{type, metric, options}`, saves one as a component with `create_component`, or
dry-runs it with `card_preview` (`POST dashboards/api/card-preview/`), all through the
same `normalize_layout` and your `validate`. So the type's `description` and each
option's `help` are documentation an agent reads: write them that way.

## Testing a type

```python
def test_sparkline_draws_and_opens_its_rows(client, staff, metric):
    Dashboard(name="T", slug="t", layout=[{"id": "s", "type": "sparkline", **own("wc_req"),
                                           "options": {"grain": "day"}}]).save()      # validation runs here
    html = client.get("/smallstack/dashboards/d/t/cells/s/").content.decode()   # what the cell shows
    assert 'hx-get="/smallstack/dashboards/d/t/cards/s/rows/?narrow=' in html
    with pytest.raises(ValidationError, match="grain"):
        Dashboard(name="B", slug="b", layout=[{"type": "sparkline", **own("wc_req"),
                                               "options": {"grain": "fortnight"}}]).full_clean()
```

`apps.dashboards.tests.support.own(metric_key)` gives a card its own source copied
from a saved metric; `apps/website/tests/test_dashboard_cards.py` has the fixtures (a
registered test dataset, a metric, a staff client) and one test per card. Every GET
the test client makes is itself logged by the activity middleware, so a card over the
requests dataset counts them: filter the card (`"filter_tree": {...}`) or assert on
order, not totals.

## Gotchas

- **`register_component_type` replaces by key.** Useful (override `metric` with your
  own stat), dangerous (shadow a type by accident). Prefix project types if in doubt.
- **A data card has one source.** Two metrics on one chart isn't a first-class shape;
  extra metric keys stashed in `options` are your own to access-check.
- **A card's own filter has no JSON trend/rows endpoint** of its own; a saved metric
  has `dashboards/api/metrics/<key>/trend/` and `rows/`. A script that needs JSON for an
  inline source gets it from the template (`json_script`).
- **Theme switches don't re-render cards.** Read colours at mount; re-draw on
  `dashboards:card-drawn` (a refresh) if the chart caches them.
- **`options` are stored as given.** The builder's editors are a convenience; REST and
  MCP post whatever they like. `validate` is the contract.
