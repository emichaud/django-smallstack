# Datasets — filtered querysets as typed rows & columns (`@dataset`)

**Read this** before building anything that needs "a table of rows the user can slice and chart" — a dashboard builder, a report picker, an export screen, or an MCP/agent that queries structured data. A **dataset** is a named function returning a `QuerySet`; the framework turns it into typed rows + columns you can inspect, filter, and roll up **without knowing the underlying model**. That introspection is the whole point: you build the UI against the *schema*, not against a specific table.

> **Prerequisites**: [`modern-dark-theme.md`](modern-dark-theme.md) for the page/component patterns, [`building-a-user-facing-site.md`](building-a-user-facing-site.md) if the surface is non-staff.

## The one-paragraph model

Declare a dataset with `@dataset` over a queryset. The base derives everything a UI needs from `qs.model`: **column names, datatypes, a dimension/measure role, and ready-made filter widgets**. A visual builder then: lists datasets → reads one dataset's schema → offers field/filter pickers → asks for filtered `rows` or a grouped `series`. The builder is generic — it never hard-codes a model. Base ships one read-only `smallstack_<thing>` dataset per framework module (see [Bundled framework datasets](#bundled-framework-datasets)); you declare your own domain datasets alongside them.

## Declare a dataset

```python
from apps.datasets import dataset

@dataset("open_tickets", label="Open Tickets",
         description="Tickets still awaiting resolution",
         enable_api=True, enable_mcp=True)   # both default False
def open_tickets(request=None):
    return Ticket.objects.filter(status="open").select_related("assignee")
```

- The function takes **zero args or one `request`** (for per-user scoping). It returns a queryset — no model class, no CRUDView, no migration.
- Put it in any app's `datasets.py` — it's autodiscovered at startup and self-registers (zero wiring), exactly like a CRUDView in `views.py`.
- Flags are opt-in: `enable_api` publishes REST routes, `enable_mcp` publishes an agent tool. Neither is required — a dataset is useful in-process with neither flag set.

Key + flags reference:

| Arg | Meaning |
|---|---|
| `key` (required) | Stable id used in URLs / tool names (`query_dataset_<key>`) |
| `label`, `description` | Human text shown in the picker + tool description |
| `enable_api` | Publish `GET /smallstack/datasets/<key>/…` (staff-gated) |
| `enable_mcp` | Publish a `query_dataset_<key>` MCP tool; `mcp_access` sets the tier (default `"staff"`) |
| `filterable` | Restrict which columns MAY be filtered (default: all). *(The old `filters=` decorator kwarg is a deprecated alias — still works, warns.)* |
| `columns` | Override the column list — needed only for annotations (see [Computed columns](#computed-columns)) |
| `measures` | Declared ratio measures `[(name, numerator, denominator, fmt)]` computed as sum/sum (see [Declared ratio measures](#declared-ratio-measures)) |

> **`filterable` (declaration) vs `filters` (runtime) — two different things.** `@dataset(filterable=["status"])` says *which* columns may be filtered. `ds.rows(filters={"status": "open"})` passes the *active* filter values. The runtime `filters=` on `rows()/series()/scalar()` keeps its name.

## Naming — `dataset` is reserved

`dataset` is standard BI vocabulary, so it's tempting to reuse — don't. This framework primitive owns the generic noun; **name your domain things specifically** so nothing collides with it (in code, app labels, or URLs):

- a metric glossary → `MetricDefinition` (not `DataSet`)
- a saved chart/query definition → a "query" (not a "dataset")
- a raw-export folder → `source_exports/` (not `datasets/`)

The framework app is labelled `smallstack_datasets` precisely so a downstream app *can* still be labelled `datasets` without an `INSTALLED_APPS` clash — but keeping the concept-name clear avoids confusion regardless.

## The four operations a UI is built from

```python
from apps.datasets.core import list_datasets, get_dataset

list_datasets()                       # picker list: [{key, label, description}]
ds = get_dataset("open_tickets")
ds.schema()                           # typed columns + filter widgets  ← build the UI from this
ds.rows(filters={"status": "open"})   # reduced rows: [ {col: val, ...}, ... ]
ds.series("assignee", measure="hours_spent", agg="sum")   # [{label, value}] for bar/pie
ds.series("created_at", grain="week")                      # a trend: [{label, value, lo, hi}], oldest first
ds.series("assignee", sort={"by": "value", "dir": "desc"}, limit=5)   # top 5 by volume
ds.cells("weekday", "hour")                                # heatmap: complete [{x, x_label, y, y_label, value}]
ds.scalar(measure="hours_spent", agg="sum")               # one number for a KPI tile (no GROUP BY)
```

`agg` is `count`, `sum`, `avg`, `min`, `max`, `distinct` or `median`. A median is computed in the
database, grouped or not: `percentile_cont(0.5)` on Postgres, a `MEDIAN` aggregate the app
registers on each SQLite connection, Oracle's own. On any other backend it's refused with a
ValueError, and `schema()["aggs"]` leaves it out. Like `avg`, it has no value over no rows.

Over HTTP the same operations are:

```
GET /smallstack/datasets/                       → list
GET /smallstack/datasets/<key>/schema/          → schema
GET /smallstack/datasets/<key>/?<field>=<val>   → rows (query params are filters)
GET /smallstack/datasets/<key>/?format=csv      → rows as a CSV download (text/csv attachment)
GET /smallstack/datasets/<key>/series/?dimension=assignee&measure=hours_spent&agg=sum
GET /smallstack/datasets/<key>/series/?dimension=assignee&sort=-value&limit=5   → a top 5
GET /smallstack/datasets/<key>/scalar/?measure=hours_spent&agg=sum   → {value} for a KPI tile
GET /smallstack/datasets/<key>/cells/?dimension=weekday&dimension2=hour  → {cells: [...]}
```

`scalar()` (and the `/scalar/` route, or `/series/` with no `dimension`) is an ungrouped `qs.aggregate()` — one DB round-trip, one number. `agg="count"` or no `measure` counts rows; an empty set yields `0`.

### Paging a table — `offset` + `count()`

`rows()` takes `limit` **and** `offset` (applied after ordering; invalid values coerce to the default), and `ds.count(request, filters)` returns the full matching total so a table can show "showing 1–50 of N":

```python
ds.rows(filters=flt, ordering="-created_at", limit=50, offset=100)  # page 3
ds.count(filters=flt)                                               # → total for paging
ds.rows(filters=flt, limit=None)                                    # whole set (no cap)
```

Over REST the rows route grows `?offset=` and returns an **envelope** `{key, count, total, offset, results}` — `count` is this page's length, `total` is the full matching count. CSV export (`?format=csv`) is the **whole filtered set**, ignoring paging unless you pass `limit`/`offset` explicitly.

### Declared ratio measures

Role inference offers `sum/avg/min/max/count` over numeric columns — but the measures desks chart are usually **ratios** (CSAT % = great/total, abandon rate). Averaging a per-row percentage is the classic wrong answer; a ratio must be recomputed from summed parts. Declare it once:

```python
@dataset("surveys", measures=[
    ("csat_pct", "great", "total", "percent"),   # name, numerator, denominator, fmt
    ("abandon_rate", "abandoned", "offered", "ratio"),
])
def surveys(request=None):
    return Survey.objects.all()
```

`series(dimension, measure="csat_pct")` and `scalar(measure="csat_pct")` compute `sum(numerator) / sum(denominator)` **in the database** per group (`× 100` for `percent`), returning **`None`** (not 0) for an empty denominator — never the average of per-row ratios. Declared measures appear in `schema()["columns"]` with `role: "measure", computed: true`, and the MCP tool advertises them as valid `measure` values. `agg` is ignored for a declared measure (the ratio defines its own aggregation).

### Explicit lookups — ranges, comparisons, "is not", "contains", periods

A flat filter key can carry a lookup suffix, anywhere filters are accepted (rows/series/scalar/cells,
in-process and REST/MCP). Each is still one `{name: scalar}` key, so a dashboard link or an agent
call carries it in a query string:

| Column type | Suffixes | Value |
|---|---|---|
| `date`, `datetime` | `__gte` `__gt` `__lte` `__lt` | ISO date or datetime (`__gte`/`__lt` make a half-open range) |
| `date`, `datetime` | `__period` | a period key (`mtd`, `last_30`, … — see Filter trees below), resolved at query time |
| `integer`, `float`, `decimal` | `__gte` `__gt` `__lte` `__lt` | a number (an integer column takes whole numbers only) |
| `string` | `__ne` (is not; rows without a value are kept), `__icontains` | text |

```python
ds.rows(filters={"created_at__gte": "2026-07-01", "created_at__lt": "2026-07-08"})  # one week
ds.scalar(filters={"created_at__period": "mtd", "status__ne": "closed", "hours_spent__gt": "8"})
```

A lookup on a column **wins** over its bare key if both are sent. A blank value is absent. A value
that won't parse (`2026-13-45`, an unknown period, `fast` for a number) raises ValueError, a 400
over REST: ignoring it would drop the narrowing and return more rows than asked for.
`ds.filter_problems(filters)` says the same thing without querying, for a page that shows the
problem instead (the dataset browser does). `schema()`'s filter entry lists each column's
`lookups`, and a date column also carries `"range": true` for a range picker.

### Filter trees — nested AND/OR, stored

The flat `filters` map is AND-only and URL-shaped. A **filter tree** is the
*stored* form — the JSON a builder UI, an agent or a person writes, saved on a
metric (see [`dashboards.md`](dashboards.md)) and compiled to a `Q` each time.
Every read path takes it as `filter_tree=` (rows / count / series / scalar /
queryset), AND-ed with any flat filters; REST takes `?filter_tree=<json>`, the
`query_dataset_<key>` MCP tool a `filter_tree` object.

```python
ds.scalar(filter_tree={"and": [
    {"field": "status", "op": "=", "value": "open"},
    {"or": [
        {"field": "priority", "op": "in", "value": ["high", "urgent"]},
        {"field": "age_days", "op": ">", "value": 30},
    ]},
    {"not": {"field": "assignee", "op": "isnull"}},
    {"field": "created_at", "op": "period", "value": "mtd"},
]})
```

| op | value | applies to |
|---|---|---|
| `=` `!=` | one value (`!=` keeps NULLs) | all |
| `>` `>=` `<` `<=` | number / ISO date | numbers, dates |
| `between` | `value` + `value2` (dates half-open `[lo, hi)`, numbers inclusive) | numbers, dates |
| `in` | non-empty list | text, numbers, FKs |
| `contains` | substring, case-insensitive | text |
| `isnull` | `true` (default) / `false` | all |
| `period` | a relative period key | dates |

Word aliases are accepted (`eq`, `ne`, `is`, `is not`, `gt`, `gte`, `lt`,
`lte`, `before`, `after`, `icontains`, `relative`). `schema()["filters"][*]`
carries each field's `ops` and `column_type`, and date fields their `periods`.

**Periods** (`apps/datasets/dateranges.py`) resolve *at query time*, so a saved
"Month to date" stays current: `today`, `yesterday`, `wtd`, `pwtd`, `mtd`,
`pmtd`, `qtd`, `pqtr`, `ytd`, `prev_year`, and generic `last_<N>` / `next_<N>`
(days, today inclusive). Bounds are local midnights, half-open; "to date"
periods run through the end of today. A key an earlier vocabulary used still
resolves through `PERIOD_ALIASES` (`previous` → `yesterday`) but isn't offered.
The module docstring lists how each period differs from the call_stats original
it was ported from.

**Strict, unlike flat filters.** An unknown field, a non-filterable field, an
op the column's type doesn't take, an unparseable value or an unknown period
raises `FilterTreeError` (a `ValueError` → REST 400) listing **every** problem
with its path (`and[1].or[0].op: …`). It never drops a condition, because a
dropped condition on a stored KPI makes the number silently *bigger*.
Validate before saving with `ds.validate_filter_tree(tree)` (→ list of
problems); `describe_filter_tree(tree, labels)` gives the one-line reading
("Status = open AND (Priority in high, urgent OR Age > 30) AND Created: Month
to date"); `and_trees(...)` combines trees without nesting.

**The editor.** One visual editor draws a tree for people, shared by every
page that filters a dataset: `datasets/js/filter-tree.js` +
`datasets/css/filter-tree.css` (the metric builder mounts it; so does the
dataset browser). Give it a mount element, the hidden input the form posts,
and the dataset's `schema()`:

```html
<div id="my-tree"></div>
<input type="hidden" name="filter_tree" value="{{ tree_json }}">
<script src="{% static 'datasets/js/filter-tree.js' %}" defer></script>
```

```js
var editor = SmallStackFilterTree.create({
    mount: document.getElementById("my-tree"),
    input: form.querySelector('[name="filter_tree"]'),
    onChange: function (tree) { /* re-run a preview */ },
});
editor.setSchema(schema);   // from the schema endpoint or a json_script
```

It builds its field list from `schema()["filters"]` (so `ops`, `choices` and
`periods` drive the controls), writes the JSON back on every edit, and keeps a
tree it can't draw (a `not`, written over the API) as it is, offering to
start over. Theme tokens only, no inline JS, so it is CSP-clean.

### Bucketed grouping (bands, categories, top-N + Other)

**Time grains.** On a date/datetime dimension, `grain=` (`day`/`week`/`month`/`quarter`/`year`)
groups by the calendar bucket, so a bar or line reads as a time series. It returns the most recent
`limit` buckets oldest first, and each row's `lo`/`hi` ISO bounds select exactly that bucket's rows
(`[lo, hi)`). Weeks start Monday, and labels look like "Wk of Mar 3, 2026". Empty buckets are
absent; `apps.dashboards.trends.metric_trend` fills them in. A grain on a non-date column is
ignored. It's the call_stats grammar, lifted verbatim, so extend it here rather than forking it.

**Order.** `sort={"by": "category"|"value", "dir": "asc"|"desc"}` orders a grouped series. The
default, category ascending, is the dimension's order (chronological for a grain). `by: "value"`
ranks by the aggregate, and the database applies it before `limit`, so value-descending with
`limit=N` is a top N, not the first N alphabetically. Ties read in the dimension's order; a group
with no value sorts last. A grain keeps its window either way: the most recent `limit` periods,
then sorted for display. REST: `?sort=value`, `-value`, `category` or `-category`.

**Two dimensions — `cells()`.** `ds.cells(x, y, measure=…, agg=…)` groups by both at once for a
heatmap or punch card. The grid is **complete**: every x × every y that occurs, row-major by y
then x, so a chart can index marks by position. A combination with no rows carries 0 for
count/distinct/sum and `None` for the rest. Each cell has the raw value and its label (`x`,
`x_label`): drill down on the raw value (an FK's pk), show the label. More than 30 distinct values
on either axis (`axis_limit=`) raises ValueError naming the field, rather than leaving part of the
grid out. The `dimension2` capability says a dataset has two columns to cross.

Raw-value grouping is fine until you need "wait time in bands," "top-N queues + Other," or a histogram. Pass `series()` a **dict** dimension instead of a column name — the buckets are the wire grammar (don't invent a second spelling):

```python
# numeric bands — half-open [lo, hi); hi omitted ⇒ open-ended outlier band
ds.series({"field": "wait_s", "buckets": [
    {"key": "fast", "label": "< 30s",  "lo": 0,  "hi": 30},
    {"key": "slow", "label": "30–120s", "lo": 30, "hi": 120},
    {"key": "vslow", "label": "2m+",    "lo": 120, "hi": None},
]})
# categorical: {value} equals, {values:[…]} in-group, {other:true} the complement
ds.series({"field": "queue", "buckets": [
    {"key": "dedicated", "label": "Dedicated", "values": ["8004", "8007"]},
    {"key": "other", "label": "Everything else", "other": True},
]})
# auto — top-N value buckets by volume (+ Other), keyed v:<value>
ds.series({"field": "queue", "auto": {"limit": 8, "label_field": "queue_name"}})
```

Returns `[{key, label, value, lo, hi}]` — `value` is the bucket's **row count** (bucketed grouping is **count-only**; `measure`/`agg` don't apply, that's a future extension). Guarantees:

- **Part-to-whole sums.** With an `{other: true}` bucket the counts sum to the filtered total — no silently dropped rows. Numeric bands are half-open so adjacent bands never double-count.
- **Auto keys are stable.** `auto` buckets derive from the dataset's **unnarrowed** base queryset (the [`queryset()`](#composing-on-a-dataset--the-queryset-seam) seam), so a *filtered* series returns the same buckets, zero-counted where empty — keys never dangle mid-pipeline.

**Drilldown** — the rows behind a clicked bucket — re-apply the *same* bucket condition, so they reconcile with the count by construction:

```python
ds.rows(dimension=dim, bucket="slow")   # exactly the rows in the "slow" band
```

Over REST/MCP: the series/rows routes take the field via `dimension`/`group_by` plus `buckets` (a JSON array — MCP passes it natively; REST URL-encodes it) or `auto=true&auto_limit=&label_field=`; the rows route's `bucket=<key>` is the drilldown.

## Inspecting a dataset to build an interface — the tricks

This is the section that matters for a builder. **`schema()` is your entire source of truth** — pull names, types, roles, and widgets from it and the UI writes itself.

### `schema()` shape

```jsonc
{
  "key": "open_tickets",
  "label": "Open Tickets",
  "columns": [
    {"name": "status",       "label": "Status",   "type": "string",   "role": "dimension"},
    {"name": "created_at",   "label": "Created",   "type": "datetime", "role": "dimension"},
    {"name": "assignee",     "label": "Assignee",  "type": "fk",       "role": "dimension"},
    {"name": "hours_spent",  "label": "Hours",     "type": "float",    "role": "measure", "unit": "hours"}
  ],
  "filters": [
    {"name": "status",   "label": "Status",  "type": "choice",  "choices": [["","All"],["open","Open"],["blocked","Blocked"]]},
    {"name": "created_at","label": "Created", "type": "choice",  "is_date": true, "choices": [["","All"],["today","Today"],["week","Past 7 days"], "..."]},
    {"name": "assignee", "label": "Assignee","type": "choice",  "choices": [["","All"],["3","Ada"],["7","Grace"], "..."]}
  ]
}
```

Every column carries a `unit`: what `@dataset(units={"hours_spent": "hours", "fee": "currency"})`
declares, else a guess from the name (`*_seconds` → `seconds`, `*_minutes` → `minutes`), else
`null`. A declared `percent` ratio's unit is `percent`. A builder offers formats from it rather
than guessing from the column name. Every filter entry also lists its `lookups` (see Explicit
lookups).

### Trick 1 — split pickers by `role`

`role` is the chart-affordance hint. Filter your field pickers by it and each chart type's inputs fall out automatically:

```python
sch = get_dataset(key).schema()
dimensions = [c for c in sch["columns"] if c["role"] == "dimension"]   # categories / axes / group-by
measures   = [c for c in sch["columns"] if c["role"] == "measure"]     # values to aggregate
```

- **Bar / line**: one `dimension` (X) + one `measure` (Y).
- **Pie / donut**: one `dimension` (slices); measure optional (defaults to row count).
- **KPI tile**: one `measure` + an `agg` → call `scalar(measure, agg)` (or the `/scalar/` route). One ungrouped number, computed in the DB — no `dimension`, no client-side summing.
- **Table**: any columns.

Disable a chart type in the UI when the dataset lacks the roles it needs (e.g. grey out bar charts if `measures` is empty) — you know that *before* fetching a single row.

### Trick 2 — build filter widgets straight from `filters`

Don't infer widgets. `schema()["filters"]` already tells you the control to render:

| `type` | Render as | Notes |
|---|---|---|
| `choice` (with `choices`) | dropdown / segmented control | Auto-detected from FK targets, `choices=`, or ≤30 distinct values. `choices` is `[[value, label], …]`; the first is usually `["", "All"]` |
| `choice` + `is_date: true` | date-range preset dropdown | Values are `today` / `yesterday` / `week` / `month` / `year` |
| `boolean` | toggle (All / Yes / No) | |
| `text` | free-text input | Matched with `icontains` server-side |

Each filter's `name` is the query key you send back to `rows()` — round-trips exactly.

### Trick 3 — map `type` to formatting

`type` is the raw Django-derived datatype; use it to format cells and pick input controls:

`string` · `integer` · `float` · `decimal` · `date` · `datetime` · `time` · `boolean` · `fk`

e.g. right-align + thousands-separate `integer`/`float`/`decimal`; render `datetime` with the `localtime_tooltip` tag; render `fk` values as a link.

`fk` columns come back as a **bare pk by default**. Pass `expand=` to `rows()` (or `?expand=fk1,fk2` on the REST rows route, mirroring the CRUD API) to get `{"id", "name"}` for those columns instead:

```python
ds.rows(expand=["assignee", "category"], limit=100)   # → assignee: {"id": 3, "name": "Priya"}
```

Unknown or non-FK names in `expand=` are ignored. For **charts**, `series()` resolves an FK dimension's labels to the related object's `str()` automatically (so a bar chart reads `Electrical`, not `2`) — no `expand` needed there.

### Trick 4 — the round-trip is stable, and filters apply everywhere

Every `name` from `schema()` is the same key you pass back — and **`rows()`, `series()` and `scalar()` share one filter contract**. Pass the *same* `filters` dict to all three and the table, the chart, and the KPI tile all reflect the active filters. This is essential for a filter builder: change a filter once, everything updates together.

```python
flt = {"status": "open", "created_at": "week"}
ds.rows(filters=flt, ordering="-created_at", limit=100)         # filtered table
ds.series("assignee", measure="hours_spent", agg="sum", filters=flt)   # filtered chart
ds.scalar(measure="hours_spent", agg="sum", filters=flt)               # filtered KPI
```

Over REST the contract is the same: any non-reserved query param on the rows, `series`, **or** `scalar` route is a filter. So `GET /<key>/series/?dimension=priority&status=open` groups by priority *within* the open rows, and `GET /<key>/scalar/?agg=count&status=open` counts only the open rows. Unknown filter keys are ignored (never a 500).

So a builder can be fully data-driven: read schema → collect user choices keyed by `name` → post the same filter set to whichever endpoint the widget needs. No translation layer.

**The flat-filter invariant (stable across releases).** A `filters` dict is always a **flat, string-keyed `{name: scalar}` mapping** — the serializable query-param shape. This is deliberate and guaranteed: stored slice descriptors, saved dashboard links, and agent calls all round-trip through `urlencode`, so the contract can't quietly become nested. Richer filtering arrives only as **new param spellings** (e.g. a future `created_at__gte=`), never as nested objects replacing existing keys.

### Trick 5 — probe cheaply, fetch lazily

- `list_datasets()` is **metadata only** (no DB, no schema probe) — safe to call on every page load for the picker.
- `schema()` runs a **small** query per categorical column (distinct-value probe) — call it once when a dataset is selected, then cache it for the session.
- `rows()` / `series()` are the only heavy calls — trigger them on an explicit "run / preview," not on every keystroke.

## Computed columns

`type`/`role` are inferred from **real model fields**. A column produced by `.annotate()` isn't a model field, so declare it explicitly — then it flows through `schema()` with the right type and role:

```python
from django.db.models import Count

@dataset("tickets_by_assignee", columns=[("assignee", "fk"), ("ticket_count", "integer")])
def tickets_by_assignee(request=None):
    return (Ticket.objects.values("assignee")
            .annotate(ticket_count=Count("id")))
```

Model-field columns need nothing; only computed ones need the `(name, type)` hint.

Every operation works on a computed dataset: `list_datasets()`, `schema()`, `series()`, `scalar()`, and `rows()`.

**Filtering a computed column.** List it in `filterable=` and the usual flat
param works — `?hours_band=business`, `?answered=1` — on every read path
(`rows`/`series`/`scalar`, REST, MCP, stored slices). The comparison is typed
from the annotation's `output_field`: booleans take `1/0/true/false`,
date/datetime take the same presets as model dates (`today`, `week`, …), and
everything else is an **exact** match — computed columns are overwhelmingly
categorical (bands, routes, flags), so `?hours_band=busi` matches nothing
rather than guessing. (Before v0.21.11 these filters were silently dropped and
returned **every row** — no error, so a tile labelled "business hours" showed
all hours. If you are on an older release, that is the bug.)

**The builder widget.** `schema()["filters"]` advertises a control for a
computed column too, typed from the annotation: a boolean gets All/Yes/No, a
date/datetime gets the usual preset dropdown (plus `range`), and anything else
gets a **dropdown of the values actually present** (probed, capped at 30
distinct — the same ceiling model fields use).

That pairing is deliberate: in this framework a **choice widget means an exact
match** and a text widget means `icontains`, and computed columns always
compare exactly — so a dropdown is the only widget whose semantics we can
honour. Two cases are therefore advertised as *nothing*:

- an **aggregate** annotation (`Count`, `Sum`): probing its domain would mean a
  GROUP BY over the table, and the filter is a `HAVING` clause;
- a computed string with **more than 30 distinct values**: a text box would
  promise substring matching that the exact comparison won't deliver.

**Not offered is not the same as not supported** — the filter still applies in
both cases when you pass the param. Render your own control if you want one. A `.values().annotate()` queryset yields plain dicts (no model instance), so `rows()` returns those annotated dicts projected onto your declared columns (any extra annotation keys are appended) — no FK `expand` applies to a values-queryset since it's already reduced to scalars.

## Row links — where to view the object

Every row from `rows()` (and so REST, MCP and the CSV's last column) carries a **`url`** key: the page where that record can be viewed, or `null`. `schema()["links"]` says whether a dataset provides it. The staff browser renders the first column as that link.

Resolution needs no code for most datasets. In order:

1. **`link=`** on the decorator — a callable `(obj) -> str | None`, or a URL route name reversed with `pk=<obj.pk>`.
2. The model's **CRUDView** page: its detail route, else (as `{% crud_table %}` does) its edit route.
3. The model's **`get_absolute_url()`**.

`link=False` opts out. A dataset whose own column is named `url` keeps that column and gets no link key. A link that cannot be built (no route, a raising callable) is `null`, never an error.

```python
@dataset("open_tickets", link="tickets:detail")            # reverse("tickets:detail", pk=…)
@dataset("log_lines", link=lambda r: f"/logs/?request_id={r.request_id}")
@dataset("rollup", columns=[...], link=False)              # a .values() rollup has no object
```

The bundled datasets lean on the CRUDView fallback (every explorer-registered model has one), with three explicit links: log records open the logs page filtered to their request or trace id, capture windows open the logs page, notifications open the page they point at.

## Exposing to agents (MCP)

Set `enable_mcp=True` and the dataset becomes a `query_dataset_<key>` tool: the agent passes filter args, gets rows — or passes `group_by` (+ optional `measure`/`agg`) for a `[{label, value}]` series, or `scalar=true` (+ `measure`/`agg`, no `group_by`) for a single KPI number. The filter args apply in **all three** modes (rows, series, scalar), so a grouped or aggregated answer respects the same filters. FK columns come back expanded (`{id, name}`) so the agent reads names, not pks. A site-level `list_datasets` tool lists every dataset the caller may read (`query_tool` names its `query_dataset_<key>` tool, or is null when it has none, as the bundled ones don't by default, though metrics can still be built on them), and `describe_dataset {key}` returns the `schema()` (filterable fields with their filter-tree ops and periods) on the same terms. Every mode also takes a `filter_tree` object. Secure default is `mcp_access="staff"`; widen deliberately. This is the same "declare once, surface everywhere" pattern as `enable_api`/`enable_mcp` on a CRUDView.

## Composing on a dataset — the `queryset()` seam

When a higher layer needs to build *on* a dataset (its own aggregation, annotation, or pagination) rather than consume `rows()`/`series()`, use the public **`queryset()`** method — don't reach into internals:

```python
ds = get_dataset("queued_inbound_calls")
qs = ds.queryset(request, filters={"status": "unanswered"})   # → a plain QuerySet
# you own everything from here: qs.aggregate(...), your own paging, etc.
```

`queryset(request=None, filters=None, *, filter_tree=None)` returns the dataset's queryset with the standard filter pipeline applied and **nothing else** — no serialization, limit, ordering, or expand. Same filter contract as `rows()` (unknown keys ignored); per-user scoping via the dataset function's `request` arg happens inside. Guaranteed: `ds.queryset(r, f).count() == len(ds.rows(request=r, filters=f))` for the same filters (unlimited). This is the supported seam for a reporter/BI layer that treats datasets as its source of blessed, filterable scopes.

## Bundled framework datasets

Every framework module that creates data ships a lightweight, read-only dataset over it — the browse/report seam a downstream reporting tool builds on without re-deriving column lists or working out which fields are safe to show. They are declared in each app's `datasets.py` through `apps.datasets.framework.framework_dataset`, which applies three conventions:

- **Namespaced keys** — every key is `smallstack_<thing>` (the registry is first-wins, so a bare `notifications` key would shadow yours; the prefix is reserved for the framework).
- **Explicit column allow-lists** — rows project onto the declared columns, so credential hashes, webhook secrets, OAuth codes, raw payloads/bodies, post bodies and task kwargs are never columns.
- **Uniform exposure** — REST is always on (staff-gated, `?format=csv` works); MCP tools follow `SMALLSTACK_FRAMEWORK_DATASETS_MCP` (default **off** — two dozen `query_dataset_*` tools crowd an agent's list). `SMALLSTACK_FRAMEWORK_DATASETS_ENABLED=False` registers none of them.
- **Model permissions apply** — a dataset over a model that checks Django model permissions (accounts, API tokens and the other access models always do; any model whose CRUDView sets `model_permissions`) needs that model's `view` permission on every surface (browse page, index, REST, MCP, metrics and dashboards), staff included, so `smallstack_users` and `smallstack_api_tokens` need `accounts.view_user` / `smallstack.view_apitoken`. Over REST such a dataset answers 404, as if absent. `apps.datasets.registry.user_may_view_model(dfn, user)` is the check.

| Module | Keys |
|---|---|
| Core (`apps/smallstack`) | `smallstack_api_tokens`, `smallstack_backups` |
| User manager | `smallstack_users` |
| Profile | `smallstack_user_profiles` |
| Activity | `smallstack_requests` |
| Telemetry | `smallstack_log_records`, `smallstack_log_capture_windows` |
| Heartbeat | `smallstack_heartbeats`, `smallstack_heartbeat_daily`, `smallstack_maintenance_windows` |
| Tasks | `smallstack_task_attempts`, `smallstack_worker_heartbeats` |
| Scheduler | `smallstack_scheduled_jobs`, `smallstack_scheduled_job_runs` |
| Webhooks | `smallstack_webhook_endpoints`, `smallstack_webhook_deliveries`, `smallstack_webhook_receivers`, `smallstack_webhook_receipts` |
| Notifications | `smallstack_notifications` |
| Approvals | `smallstack_approval_requests` |
| Feeds | `smallstack_collected_items` |
| Blog | `smallstack_blog_posts`, `smallstack_blog_subscriptions`, `smallstack_blog_issues` (declared `sent_pct` / `failed_pct`), `smallstack_blog_deliveries` |
| Runbook | `smallstack_runbook_documents`, `smallstack_runbook_document_versions` |

Not covered on purpose: `LoginCode` and `OAuthAuthorizationCode` (credential tables), blog `Subscriber` (email addresses — reach subscribers through `smallstack_blog_subscriptions` by FK), and the modules with no models of their own (api, explorer, help, search, tokenmgr, datasets). `framework_dataset_keys()` lists what is registered at runtime.

**The staff browser** — `/smallstack/datasets/browse/` ("Datasets" in the admin nav) lists every registered dataset (project ones first, then the bundled set) and opens each at `browse/<key>/`: a filter bar built from `schema()["filters"]` (choice/boolean dropdowns, text boxes, date presets + a from/before range), a sortable, paged table built from `schema()["columns"]`, a **More conditions** section (the shared filter-tree editor, travelling as `?filter_tree=<json>` — the parameter REST takes — and AND-ed with the quick filters; a tree that can't be applied shows its problem and no rows), a one-dimension roll-up (group by any column, optional measure + aggregate, declared ratios included) via `series()`, and a **Download CSV** card that deep-links the REST export with the active filters and tree (hidden when the dataset doesn't publish REST). The filters apply as they change: the form hx-gets the page, takes the rows card from it and swaps in the roll-up, the live row count and the CSV link (`hx-select-oob`), so the form and the tree editor stay put; `browse.js` raises `ds-change` for the tree editor, typing in a search box and the roll-up selects; Apply remains for a browser without scripts. At the filters' right edge, the row count and **Make a metric**: a modal (`dashboards_metric_quick`, `MetricQuickView`) with the dataset, every condition on screen as one filter tree (quick filters become leaves: a text box `contains`, a choice `=`, a date preset a `period`, explicit bounds `>=`/`<`) and the roll-up's aggregate — a metric *is* the filtered table reduced to one number. The modal asks for the name, how the rows become a number, the period column, the format and who sees it, shows the value as the choices change, saves through `MetricForm`, and then offers to open the metric, make a card, or make another from the same rows, so several metrics come from one filtered table without leaving it; **Open the full form instead** is the metric page prefilled (`browse_prefill`). A grouped roll-up also offers **keep this roll-up as a card** (Grouped stat, Ranked bars, Pie chart for a count or sum): the same modal with `then=card`, whose saved state leads to the component builder on that card. Both are absent when the dashboards app isn't installed or the conditions can't be applied. **Start from a metric** (above the filters, when this dataset has saved metrics the viewer can see, `DatasetBrowseView._saved_metrics`) loads one: its tree under More conditions and its roll-up, marked `?metric=<key>` and kept in the form as the filters change (a bare `?metric=<key>`, the no-JS pick, redirects to that address). Make a metric is then a copy: the modal gets `from=<key>` with the name "… (copy)", the period column and the format, and its save carries the source's thresholds, unit, description and tags; the full form (`MetricCreateMixin`) lays the browser's conditions over the same copy. The source never changes. It is the reference consumer of the schema contract: it hard-codes no model, so a downstream `@dataset` appears there with zero extra work. Views live in `apps/datasets/views.py`.

A downstream reporting tool consumes them exactly like any dataset:

```python
from apps.datasets.core import get_dataset

ds = get_dataset("smallstack_requests")
ds.series("status_code", filters={"timestamp": "week"})        # status mix this week
ds.scalar(measure="response_time_ms", agg="avg", filters={"route": "/api/"})
get_dataset("smallstack_blog_issues").scalar(measure="sent_pct")  # sum/sum, never avg-of-pct
```

## Calendar datasets — a dataset with a time axis

A dataset whose rows belong on a date grid (due dates, expiries, windows, runs)
can carry the **calendar protocol**: `@calendar_dataset(key, start="due_at",
end=None, title="subject", status="sla_status", access="authenticated", …)` is
`@dataset` plus the columns/resolvers the merged calendar at
`/smallstack/calendar/` needs; `register_calendar(key, …)` attaches the same to
a dataset declared elsewhere (how the bundled `smallstack_*` calendars are
done). The calendar reads rows through `queryset()`, so scoping and `link=`
apply unchanged. See [`calendar.md`](calendar.md).

Coming from call_stats' `Dataset.day_entries()` (a day's entries, ranges spread over each day
they span, "+N more"): that's the calendar protocol. Its `day_counts()` (one number per day) is
`ds.series(date_field, grain="day", filters={f"{date_field}__gte": start, f"{date_field}__lt": end})`,
which returns each day's `lo`/`hi` too.

## When to reach for a dataset vs. a CRUDView

- **Dataset** — read-only, analytical: "a filtered table to slice, chart, or export." No edit/detail pages. Can join/annotate/aggregate; source is any queryset.
- **CRUDView** — the record is a first-class editable thing (admin + REST + detail pages). If you need create/update/delete UI, use a CRUDView; if you only need to *read and shape* rows, use a dataset.

They compose: a dataset can return a queryset over the same model a CRUDView manages.

## Settings & gotchas

- Master switch: `SMALLSTACK_DATASETS_ENABLED` (default on). Off → REST 404s and no MCP tools register; per-dataset `enable_*` become no-ops.
- REST authenticates via **Bearer token OR session** — the same `_authenticate_api_request` path `/api/` uses — so a cross-origin SPA (sending `Authorization: Bearer …`) reaches it directly. Failures return a JSON **401/403**, never a 302 to an HTML login page.
- REST is **staff-only** by default (secure default for an admin data surface): an authenticated non-staff caller gets a JSON 403. For a non-staff end-user builder, build your own view over `get_dataset(key)` with the right auth + tenancy scoping — see [`building-a-user-facing-site.md`](building-a-user-facing-site.md). Scope per-user data inside the dataset function via its `request` arg.
- `series()`/`scalar()` validate `dimension`/`measure` against the dataset's columns: an unknown name raises `ValueError` in-process and returns a JSON **400** over REST (not a 500). `rows()` still silently ignores unknown ordering/filter/expand keys.
- **CSV export**: the rows route honours `?format=csv` — same rows + filters, streamed as a `text/csv` attachment (`<key>.csv`) with the schema columns as the header (expanded FK cells render as the name). That's the "export screen" path; no extra config.
- `filterable` defaults to **all columns**. Numeric columns filter by exact match; text columns with many distinct values fall back to substring (`icontains`); low-cardinality columns become dropdowns.
- `access=` (`"staff"` default, or `"auth"`) says who may read the dataset through **in-app** surfaces that evaluate it for a user — metrics, dashboards, reports (`apps.datasets.registry.user_may_read`). It is independent of `enable_api` (REST, staff-only) and `mcp_access` (the MCP tool tier). `schema()` also reports `aggs` (now including `distinct`) and `capabilities` (`measure`, `dimension`, `dimension2`, `date` — `apps/datasets/capabilities.py`), so a builder can grey out what a dataset can't do.
- The bundled `smallstack_*` datasets are governed by `SMALLSTACK_FRAMEWORK_DATASETS_ENABLED` (default on) and `SMALLSTACK_FRAMEWORK_DATASETS_MCP` (default off). Declare your own in an app's `datasets.py`; never reuse the `smallstack_` prefix.

## Anti-patterns

1. **Hard-coding column lists in the builder** — read `schema()["columns"]` instead; the whole design is that the UI adapts to any dataset.
2. **Inferring filter widgets from `type`** — use `schema()["filters"]`, which already resolved FK/choice/date/boolean widgets (and ran the categorical detection for you).
3. **Calling `schema()` on every render** — cache it per selected dataset; it does per-column distinct probes.
4. **Fetching rows to compute a total** — use `scalar(measure, agg)` for a single KPI number, or `series(dimension, measure, agg)` for a per-group rollup; both aggregate in the database, not in Python. (Don't sum `series` buckets client-side to get one number — that's what `scalar()` is for.)
5. **Forgetting `columns=` for annotations** — an annotated column with no hint types as `string`/`dimension` and won't offer as a measure.
