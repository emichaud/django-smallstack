"""Dashboard components — the card types a dashboard cell can be.

A cell is a plain dict stored in ``Dashboard.layout``::

    {"id": "c1", "type": "metric", "metric": "open_tickets",
     "x": 0, "y": 0, "w": 3, "h": 2, "title": "Open", "options": {}}

and its ``type`` names a :class:`ComponentType` registered here. A type says
how to **validate** a cell (so a bad cell is refused when the dashboard is
saved, by any surface) and how to **build** the template context that renders
it. SmallStack ships five:

==================  ===========================================================
``metric``          one stat card — a Metric, or the card's own filter — value, state, drill-down
``metric_group``    the card's own filtered rows split by a dimension: the top N groups as numbers
``widget``          an existing ``DashboardWidget`` (the /smallstack/ cards)
``text``            a markdown note between cards
``goals``           the first goals of a GoalList, each against its target
==================  ===========================================================

**Extending it** — an app on top of SmallStack registers its own type from
its ``AppConfig.ready()`` (a chart, a table, a gauge…)::

    from apps.dashboards.components import ComponentType, register_component_type

    register_component_type(ComponentType(
        key="sparkline", label="Sparkline", description="Daily trend of a metric",
        template="myapp/cells/sparkline.html", needs_metric=True,
        default_size=(4, 2), build=build_sparkline, validate=validate_sparkline,
    ))

``build(cell, ctx)`` returns the template context; ``validate(cell)`` returns a
list of problems. The cell endpoint renders the template inside the shared card
chrome, so a new type gets lazy loading, auto-refresh, the period bar, layout
editing, REST/MCP authoring and access checks for free.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from .comparison import compare_groups, compare_with_previous
from .metrics import (
    DRILL_COLUMNS,
    DRILL_FORMATS,
    DRILL_LIMIT,
    MAX_DRILL_COLUMNS,
    MAX_DRILL_ROWS,
    STATES,
    THRESHOLD_OPS,
    evaluate,
)
from .periods import period_heading

if TYPE_CHECKING:
    from .models import Dashboard, Metric

logger = logging.getLogger(__name__)

GRID_COLUMNS = 12
MAX_ROWS = 12  # a cell's height cap, in grid rows
MAX_CELLS = 60
#: A card's own data source: the definition a metric holds, kept on the card.
SOURCE_KEYS = ("dataset", "filter_tree", "agg", "measure", "period_field")
_CELL_KEYS = {
    "id",
    "type",
    "x",
    "y",
    "w",
    "h",
    "metric",
    "title",
    "options",
    "use_period",
    "component",
    "name",
    *SOURCE_KEYS,
}
#: What a placement of a saved component may set itself; the rest comes from the component.
_PLACEMENT_KEYS = {"id", "x", "y", "w", "h", "title", "use_period"}


#: The shared card styling (``options.style``) a ``stylable`` card type
#: honours, as the builder and agents see it. Colours are the theme's named
#: states and accent, never literals, so a styled card is right on every palette.
CARD_STYLE: list[dict[str, Any]] = [
    {
        "name": "format",
        "label": "Number format",
        "default": "",
        "choices": [
            ["", "The metric's"],
            ["number", "Number — 9,481"],
            ["compact", "Compact — 9.5K"],
            ["decimal", "Decimal — 9,481.24"],
            ["percent", "Percent — 94.2%"],
            ["currency", "Currency — $9,481.00"],
            ["duration", "Duration — 2m 19s"],
        ],
    },
    {"name": "unit", "label": "Unit", "default": "", "max": 20, "help": "Blank = the metric's unit."},
    {
        "name": "size",
        "label": "Number size",
        "default": "m",
        "widget": "segmented",
        "choices": [["s", "S"], ["m", "M"], ["l", "L"], ["xl", "XL"]],
    },
    {
        "name": "color",
        "label": "Number colour",
        "default": "state",
        "widget": "swatches",
        "choices": [
            ["state", "From the thresholds"],
            ["accent", "Accent"],
            ["plain", "Plain"],
            ["success", "Success"],
            ["warning", "Warning"],
            ["danger", "Danger"],
            ["muted", "Quiet"],
        ],
    },
    {
        "name": "title_size",
        "label": "Title size",
        "default": "m",
        "widget": "segmented",
        "choices": [["s", "S"], ["m", "M"], ["l", "L"]],
    },
    {
        "name": "title_color",
        "label": "Title colour",
        "default": "quiet",
        "widget": "swatches",
        "choices": [["quiet", "Quiet"], ["plain", "Plain"], ["accent", "Accent"]],
    },
    {
        "name": "align",
        "label": "Alignment",
        "default": "start",
        "widget": "segmented",
        "choices": [["start", "Left"], ["center", "Centre"], ["end", "Right"]],
    },
]
_STYLE = {spec["name"]: spec for spec in CARD_STYLE}


def validate_card_style(options: dict[str, Any], allowed: tuple[str, ...] = ()) -> list[str]:
    """Problems with a stylable card's ``style`` and ``thresholds`` options.
    *allowed* narrows the settings a type takes (``ComponentType.style_settings``)."""
    from .metrics import validate_thresholds

    problems: list[str] = []
    style = options.get("style", {})
    if not isinstance(style, dict):
        return ["'style' must be an object"]
    names = set(allowed or _STYLE)
    for key, value in style.items():
        spec = _STYLE.get(key)
        if spec is not None and value in ("", None):
            continue  # blank = the default
        if spec is None or key not in names:
            problems.append(f"style: unknown setting {key!r}; use {sorted(names)}")
        elif "choices" in spec and value not in [c[0] for c in spec["choices"]]:
            problems.append(f"style.{key}: one of {[c[0] for c in spec['choices']]}")
        elif "max" in spec and (not isinstance(value, str) or len(value) > spec["max"]):
            problems.append(f"style.{key}: text, at most {spec['max']} characters")
    if "thresholds" in options:
        problems.extend(f"thresholds: {p}" for p in validate_thresholds(options["thresholds"]))
    return problems


def card_style(cell: dict[str, Any]) -> dict[str, Any]:
    """A stylable card's resolved styling: every :data:`CARD_STYLE` setting
    (defaults filled in), its own ``thresholds`` (``None`` = the metric's), and
    ``classes`` — the ``cs-…`` CSS hooks the card's template puts on its root."""
    opts = cell.get("options") or {}
    raw_style = opts.get("style")
    raw: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    style = {spec["name"]: raw.get(spec["name"]) or spec["default"] for spec in CARD_STYLE}
    style["thresholds"] = opts["thresholds"] if isinstance(opts.get("thresholds"), list) else None
    style["classes"] = " ".join(
        [
            "card-style",
            f"cs-size-{style['size']}",
            f"cs-color-{style['color']}",
            f"cs-title-{style['title_size']}",
            f"cs-title-color-{style['title_color']}",
            f"cs-align-{style['align']}",
        ]
    )
    return style


def styled_value(value: Any, metric: "Metric", style: dict[str, Any], state: Optional[str]) -> dict[str, Any]:
    """``{display, unit, state}`` for *value* under a card's style: its format
    and unit when set, else the metric's; its own thresholds when it has them,
    else the *state* the metric's rules already gave."""
    from .metrics import display_unit, format_value, state_for

    fmt = style.get("format") or metric.format
    unit = style.get("unit") or metric.unit
    return {
        "display": format_value(value, fmt, unit),
        "unit": display_unit(fmt, unit),
        "state": state_for(value, style["thresholds"]) if style.get("thresholds") is not None else state,
    }


def drill_params(cell: dict[str, Any]) -> dict[str, str]:
    """The query parameter that carries a card's drill-down design to the rows
    view (``{"drill": "<json>"}``), or ``{}``. A drillable card adds it to every
    rows URL it renders, so the modal shows that card's columns wherever the
    card is drawn — a dashboard, an embed, a playlist, the builder's preview."""
    import json

    spec = (cell.get("options") or {}).get("drilldown")
    return {"drill": json.dumps(spec, separators=(",", ":"))} if isinstance(spec, dict) and spec else {}


def with_drill(url: str, cell: dict[str, Any]) -> str:
    """*url* (a rows URL) with the card's :func:`drill_params` appended."""
    from urllib.parse import urlencode

    params = drill_params(cell)
    if not url or not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


def cell_title(cell: dict[str, Any]) -> str:
    """A card's own title: the placement's ``title``, else the saved
    component's name (``name``), else "" — a card type falls back to its
    metric's or widget's name: ``cell_title(cell) or metric.name``."""
    return str(cell.get("title") or cell.get("name") or "")


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass
class CellContext:
    """What a component's ``build`` receives besides the cell itself.

    ``metric`` is the card's source as a ``Metric``: the saved one it names, or
    an unsaved one built from the card's own dataset definition
    (:func:`cell_source`), so a build evaluates either the same way.
    ``rows_url`` is where the rows behind the card open (a build adds its
    narrowing and the card's drill-down design); blank when they can't."""

    request: HttpRequest
    dashboard: Optional["Dashboard"] = None
    metric: Optional["Metric"] = None
    period: Optional[str] = None
    rows_url: str = ""
    #: The slice a linked card sent this one (``options.listen``), already
    #: mapped to this card's columns and AND-ed into ``metric``'s filter; every
    #: rows link the build draws carries it too (:func:`rows_url`). None = not
    #: narrowed. Only ever narrows: see :func:`listened_narrow`.
    narrow: Any = None


@dataclass(frozen=True)
class ComponentType:
    key: str
    label: str
    template: str
    build: Callable[[dict[str, Any], CellContext], dict[str, Any]]
    description: str = ""
    #: Draws data: a dataset the card filters itself, or (``single_value``) a metric.
    needs_metric: bool = False
    default_size: tuple[int, int] = (3, 2)
    #: Dataset capabilities the card's source must have (``apps.datasets.capabilities``).
    requires: frozenset[str] = field(default_factory=frozenset)
    #: Extra validation of the cell (beyond the shared shape checks) → problems.
    validate: Optional[Callable[[dict[str, Any]], list[str]]] = None
    #: Who may see the card at all (beyond dashboard visibility). ``None`` = anyone who can view the dashboard.
    visible_to: Optional[Callable[[Any], bool]] = None
    #: Option fields a builder offers: ``[{name, label, type, default?, choices?, min?, max?, help?, required?}]``.
    #: ``type``: choice | multichoice (several of ``choices``, as a tick-list; stored
    #: as one comma-separated string) | integer | number | text | boolean | column (a
    #: column of the metric's dataset) | widget (a published DashboardWidget) | markdown |
    #: links (a list of ``{label, url, new_window}``, the builder's row editor).
    #: ``choices`` is ``[[value, label]]``, or ``choices(user)`` returning that. A
    #: choice may add ``widget``: ``"segmented"`` (pills in a row; an alignment
    #: gets icons) or ``"swatches"`` (colour dots — each value a theme token the
    #: stylesheet names, ``.cb-swatch--<option>-<value>``), drawn by cards.js.
    options_schema: list[dict[str, Any]] = field(default_factory=list)
    #: Where the component builder's palette files it: "Stats", "Info", "Charts", …
    group: str = "Other"
    #: The palette tile's icon: an SVG ``<path d>`` on a 24×24 grid (trusted).
    icon: str = ""
    #: Static files the card needs on any page that shows it, e.g.
    #: ``{"js": ["myapp/vendor/echarts.min.js", "myapp/js/cards.js"], "css": [...]}``
    #: (paths for ``{% static %}``). Dashboard, builder, embed and playlist pages
    #: load each once (``{% component_media %}``). A card's script must mount on
    #: what htmx swaps in — listen for ``htmx:afterSettle``.
    media: dict[str, list[str]] = field(default_factory=dict)
    #: Honours the shared card styling and the card's own threshold rules
    #: (``options.style`` / ``options.thresholds``, see :data:`CARD_STYLE`). A
    #: type that sets this reads :func:`card_style` and :func:`styled_value`.
    stylable: bool = False
    #: Which :data:`CARD_STYLE` settings apply; empty = all. A card whose
    #: headline is text (an info card) has no number format or unit.
    style_settings: tuple[str, ...] = ()
    #: Its numbers open rows, so it takes a drill-down design
    #: (``options.drilldown``: columns, formats, sort, rows; see
    #: ``metrics.validate_drilldown``). Its build appends :func:`drill_params`
    #: to every rows URL it renders.
    drillable: bool = False
    #: Draws the rows itself (a table), so its drill-down design is its own
    #: columns: the builder calls that step "Columns", and the design's row
    #: limit applies to the window its rows open in, not to the card.
    shows_rows: bool = False
    #: Its clicks can narrow other cards (``options.publish``) though it draws no
    #: data of its own: a calendar's days. A clicked element sends its
    #: ``data-day`` as a one-day range on the field ``date`` (cards.js), which a
    #: listening card maps to its own date column — its period column by default.
    publishes: bool = False
    #: Boils down to one number, so it may draw a saved metric (the only
    #: designs that may: a metric is one value, a chart needs the rows), and a
    #: saved card of this type over a metric can be a goal (``goals.py``); the
    #: goal takes the card's metric, number format and unit.
    single_value: bool = False


_TYPES: dict[str, ComponentType] = {}


def register_component_type(ct: ComponentType) -> None:
    """Register (or replace — re-import safe) a component type."""
    _TYPES[ct.key] = ct


def get_component_type(key: str) -> Optional[ComponentType]:
    return _TYPES.get(key)


def component_types() -> list[ComponentType]:
    return list(_TYPES.values())


def _resolved_options(schema: list[dict[str, Any]], user: Any) -> list[dict[str, Any]]:
    """*schema* with any callable ``choices`` (``choices(user) -> [[value,
    label]]``) resolved for *user* — options whose values are the viewer's own
    rows, like the goals card's goal list. No user, no choices."""
    out = []
    for spec in schema:
        if callable(spec.get("choices")):
            spec = {**spec, "choices": spec["choices"](user) if user is not None else []}
        out.append(spec)
    return out


def describe_types(user: Any = None) -> list[dict[str, Any]]:
    """The registry as JSON — what an agent or the "Add card" picker reads.
    *user* fills in options whose choices depend on who's asking."""
    return [
        {
            "type": ct.key,
            "label": ct.label,
            "description": ct.description,
            "needs_metric": ct.needs_metric,
            "default_size": {"w": ct.default_size[0], "h": ct.default_size[1]},
            "requires": sorted(ct.requires),
            "options": _resolved_options(ct.options_schema, user),
            "group": ct.group,
            "icon": ct.icon,
            "media": {k: list(v) for k, v in ct.media.items()},
            "staff_only": ct.visible_to is _staff_only,
            "stylable": ct.stylable,
            "style_settings": list(ct.style_settings) or [spec["name"] for spec in CARD_STYLE],
            "drillable": ct.drillable,
            "shows_rows": ct.shows_rows,
            "publishes": ct.publishes or (ct.needs_metric and ct.drillable),
            "single_value": ct.single_value,
        }
        for ct in component_types()
    ]


def component_media() -> dict[str, list[str]]:
    """Every registered card type's static files, de-duplicated, in
    registration order — what ``{% component_media %}`` writes out."""
    out: dict[str, list[str]] = {"css": [], "js": []}
    for ct in component_types():
        for kind in ("css", "js"):
            for path in ct.media.get(kind, []):
                if path not in out[kind]:
                    out[kind].append(path)
    return out


# -- layout validation ------------------------------------------------------------


def components_payload(user: Any) -> dict[str, Any]:
    """What a builder (a person's editor or an agent) may put on a dashboard:
    the card types, the periods, the grid, and — for staff — the admin widgets."""
    from apps.datasets.dateranges import RELATIVE_PERIODS

    payload: dict[str, Any] = {
        "types": describe_types(user),
        "periods": [{"key": k, "label": lbl} for k, lbl in RELATIVE_PERIODS],
        "grid": {"columns": GRID_COLUMNS, "max_rows_per_cell": MAX_ROWS},
        # What a stylable card's options.style / options.thresholds may hold.
        "style": CARD_STYLE,
        "thresholds": {"ops": list(THRESHOLD_OPS), "states": list(STATES)},
        # What a drillable card's options.drilldown may hold, and what it
        # falls back to without one (the builder starts a design from those).
        "drilldown": {
            "formats": DRILL_FORMATS,
            "max_columns": MAX_DRILL_COLUMNS,
            "max_rows": MAX_DRILL_ROWS,
            "default_columns": DRILL_COLUMNS,
            "default_rows": DRILL_LIMIT,
        },
    }
    if getattr(user, "is_staff", False):
        payload["widgets"] = [{"key": k, "title": w.title} for k, w, _i in available_widgets()]
    return payload


def personal_problem(key: Any, noun: str, owner_id: Any) -> str:
    """Why a personal *noun* can't go here. A shared container refuses even your own."""
    if owner_id is None:
        return f"{key!r} is a personal {noun}, and only shared ones can go on something shared; share it first"
    return f"{key!r} is another user's personal {noun}"


def _column_option_problems(ct: ComponentType, metric: Any, options: dict[str, Any]) -> list[str]:
    """A ``column`` option names a column of the metric's dataset. Unchecked, a
    misspelt one saves happily and the card shows an error when it's drawn."""
    from apps.datasets.core import get_dataset

    ds = get_dataset(metric.dataset)
    if ds is None:
        return []
    columns = [name for name, _type in ds.columns()]
    return [
        f"{spec['name']!r} must be a column of {metric.dataset} ({', '.join(columns)}); got {options[spec['name']]!r}"
        for spec in ct.options_schema
        if spec.get("type") == "column" and options.get(spec["name"]) and options[spec["name"]] not in columns
    ]


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _expand_components(raw: list[Any], owner_id: Any, problems: list[str]) -> list[Any]:
    """Replace each ``{"component": key, …}`` placement with the saved
    component's definition (type, metric, options, name) plus the placement's
    own ``id``/position/``title``/``use_period``. A missing component, or
    someone else's personal one, becomes ``None`` and a problem."""
    from .models import Component, _visible_to_owner

    wanted = {c["component"] for c in raw if isinstance(c, dict) and isinstance(c.get("component"), str)}
    if not wanted:
        return raw
    found = {x.key: x for x in Component.objects.filter(key__in=wanted)}
    out: list[Any] = []
    for n, cell in enumerate(raw):
        if not (isinstance(cell, dict) and cell.get("component")):
            out.append(cell)
            continue
        key = cell["component"]
        comp = found.get(key) if isinstance(key, str) else None
        if comp is None:
            problems.append(f"layout[{n}].component: no saved card {key!r}")
            out.append(None)
        elif not _visible_to_owner(comp.owner_id, owner_id):
            problems.append(f"layout[{n}].component: {personal_problem(key, 'card', owner_id)}")
            out.append(None)
        else:
            placed = {k: v for k, v in cell.items() if k in _PLACEMENT_KEYS}
            out.append({**comp.as_cell(), **placed, "component": comp.key, "name": comp.name})
    return out


def normalize_layout(raw: Any, *, owner_id: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate a dashboard layout → ``(normalised cells, problems)``.

    Fills in what an author may omit (``id``, size from the type's default,
    ``x``/``y`` = 0) and checks everything else: known type, grid bounds,
    unique ids, a metric that exists and that the dashboard's owner may use,
    the type's own rules. Problems are path-addressed (``layout[2].metric``).
    A ``{"component": key}`` cell takes its type, metric and options from that
    saved component (:func:`_expand_components`).
    """
    from .models import SOURCE_DATASET, Metric, _visible_to_owner

    if raw in (None, ""):
        return [], []
    if not isinstance(raw, list):
        return [], ["layout must be a list of cells"]
    if len(raw) > MAX_CELLS:
        return [], [f"at most {MAX_CELLS} cells"]

    problems: list[str] = []
    # A null sent in the list (not one _expand_components leaves for a card it
    # couldn't place) was dropped without a word, and the card with it.
    problems.extend(f"layout[{n}]: expected an object, not null" for n, cell in enumerate(raw) if cell is None)
    raw = _expand_components(raw, owner_id, problems)

    keys = {c.get("metric") for c in raw if isinstance(c, dict) and isinstance(c.get("metric"), str)}
    metrics = {m.key: m for m in Metric.objects.filter(key__in=keys)} if keys else {}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, cell in enumerate(raw):
        where = f"layout[{n}]"
        if cell is None:
            continue  # a component that couldn't be placed (already reported)
        if not isinstance(cell, dict):
            problems.append(f"{where}: expected an object")
            continue
        extra = set(cell) - _CELL_KEYS
        if extra:
            problems.append(f"{where}: unexpected key(s) {sorted(extra)}")
        ct = get_component_type(str(cell.get("type", "")))
        if ct is None:
            given = f"unknown component type {cell.get('type')!r}" if cell.get("type") else "a cell needs a type"
            problems.append(f"{where}.type: {given}; use one of {sorted(_TYPES)}")
            continue
        c: dict[str, Any] = {"type": ct.key}
        if cell.get("component"):
            c["component"] = cell["component"]
            c["name"] = cell.get("name", "")

        cid = cell.get("id")
        if cid in (None, ""):
            i = n + 1
            while f"c{i}" in seen or any(isinstance(o, dict) and o.get("id") == f"c{i}" for o in raw):
                i += 1
            cid = f"c{i}"
        if not isinstance(cid, str) or not _ID_RE.match(cid):
            problems.append(f"{where}.id: letters, digits, - and _ only (max 40)")
            continue
        if cid in seen:
            problems.append(f"{where}.id: duplicate id {cid!r}")
            continue
        seen.add(cid)
        c["id"] = cid

        w = _int(cell.get("w", ct.default_size[0]))
        h = _int(cell.get("h", ct.default_size[1]))
        x = _int(cell.get("x", 0))
        y = _int(cell.get("y", 0))
        if w is None or not 1 <= w <= GRID_COLUMNS:
            problems.append(f"{where}.w: 1–{GRID_COLUMNS}")
        if h is None or not 1 <= h <= MAX_ROWS:
            problems.append(f"{where}.h: 1–{MAX_ROWS}")
        if x is None or x < 0 or (w is not None and x + w > GRID_COLUMNS):
            problems.append(f"{where}.x: the cell must fit in {GRID_COLUMNS} columns (x + w ≤ {GRID_COLUMNS})")
        if y is None or not 0 <= y <= 1000:
            problems.append(f"{where}.y: 0–1000")
        c.update({"x": x, "y": y, "w": w, "h": h})
        # No position given: after the cards so far, rather than all on top of
        # one another at 0,0.
        if "x" not in cell and "y" not in cell and w is not None and h is not None:
            c["x"], c["y"] = x, y = next_position(out, w)

        title = cell.get("title")
        if title not in (None, ""):
            if not isinstance(title, str) or len(title) > 120:
                problems.append(f"{where}.title: text, at most 120 characters")
            else:
                c["title"] = title
        if "use_period" in cell:
            if not isinstance(cell["use_period"], bool):
                problems.append(f"{where}.use_period: true or false")
            elif cell["use_period"] is False:
                c["use_period"] = False

        options = cell.get("options") or {}
        if not isinstance(options, dict):
            problems.append(f"{where}.options: expected an object")
            options = {}
        c["options"] = options
        problems.extend(f"{where}.options: {p}" for p in _unknown_option_problems(ct, options))

        source: Optional["Metric"] = None
        if ct.needs_metric:
            key = cell.get("metric")
            if key not in (None, ""):
                # A metric is one number: only a single-value design may draw one.
                # A chart needs the rows, so it filters a dataset of its own — unless
                # the metric has no dataset to filter (entered by hand, or a rate):
                # its values are the only rows there are, so a chart draws it as is.
                metric = metrics.get(key) if isinstance(key, str) else None
                if not ct.single_value and (metric is None or metric.source == SOURCE_DATASET):
                    problems.append(
                        f"{where}.metric: a {ct.label} card filters a dataset of its own "
                        f"(give it {', '.join(SOURCE_KEYS)}); a metric suits a design that shows one number"
                    )
                elif metric is None:
                    problems.append(f"{where}.metric: no metric with key {key!r}")
                elif not _visible_to_owner(metric.owner_id, owner_id):
                    problems.append(f"{where}.metric: {personal_problem(key, 'metric', owner_id)}")
                else:
                    c["metric"] = metric.key
                    source = metric
            elif cell.get("dataset") and not _owner_may_read(str(cell["dataset"]), owner_id):
                # Worded as for a dataset that doesn't exist, as the builder does:
                # the column list in the usual error showed a member a staff-only
                # dataset's columns (the card saved, then drew "no access").
                problems.append(f"{where}.dataset: No dataset named {cell['dataset']!r} is registered.")
            elif cell.get("dataset"):
                source, source_problems = _source_problems(cell)
                problems.extend(f"{where}.{p}" for p in source_problems)
                if source is not None:
                    c["dataset"] = source.dataset
                    c["filter_tree"] = source.filter_tree
                    c["agg"] = source.agg
                    c["measure"] = source.measure
                    c["period_field"] = source.period_field
            else:
                either = " or a metric (metric)" if ct.single_value else ""
                problems.append(f"{where}: a {ct.label} card needs a source: a dataset to filter (dataset){either}")
            if source is not None:
                missing = _missing_caps(ct, source)
                if missing:
                    problems.append(f"{where}: a {ct.label} card {', '.join(missing)}")
                problems.extend(f"{where}.options: {p}" for p in _column_option_problems(ct, source, options))
        else:
            for name in ("metric", *SOURCE_KEYS):
                if cell.get(name) not in (None, "", {}):
                    problems.append(f"{where}.{name}: a {ct.label} card draws no data, so it takes no {name}")

        if ct.validate is not None:
            problems.extend(f"{where}.options: {p}" for p in ct.validate(c))
        problems.extend(f"{where}.options.{p}" for p in link_problems(ct, options, source))
        if ct.drillable:
            if "drilldown" in options:
                from .metrics import validate_drilldown

                names = _dataset_columns(source) if source is not None else None
                problems.extend(f"{where}.options.{p}" for p in validate_drilldown(options["drilldown"], names))
        elif "drilldown" in options:
            problems.append(f"{where}.options: a {ct.label} card has no drill-down")
        if ct.stylable:
            problems.extend(f"{where}.options.{p}" for p in validate_card_style(options, ct.style_settings))
            style = options.get("style")
            if isinstance(style, dict):  # drop blanks: "" means "the default"
                options["style"] = {k: v for k, v in style.items() if v not in ("", None)}
                if not options["style"]:
                    del options["style"]
        elif "style" in options or "thresholds" in options:
            problems.append(f"{where}.options: a {ct.label} card takes no style or thresholds")
        out.append(c)
    problems.extend(_overlap_problems(out))
    return out, problems


def _overlap_problems(cells: list[dict[str, Any]]) -> list[str]:
    """Two cards on the same squares: one hides the other wherever the layout is
    drawn as a grid (``{% dashboard %}``, a playlist). The editor can't make this;
    a hand-written layout can."""
    placed = [c for c in cells if None not in (c.get("x"), c.get("y"), c.get("w"), c.get("h"))]
    return [
        f"layout: {a['id']!r} and {b['id']!r} overlap; move one (x + w and y + h must not cross)"
        for i, a in enumerate(placed)
        for b in placed[i + 1 :]
        if a["x"] < b["x"] + b["w"]
        and b["x"] < a["x"] + a["w"]
        and a["y"] < b["y"] + b["h"]
        and b["y"] < a["y"] + a["h"]
    ]


# -- linked cards: a click on one narrows another ------------------------------
#
# A card with ``options.publish: "<channel>"`` sends what's clicked in it (a
# group, a bucket, a day: the ``narrow`` filter its rows link already carries)
# to that channel instead of opening the rows window. A card with
# ``options.listen: {"channel": …, "map"?: {"their_column": "my_column"}}``
# redraws narrowed to whatever arrives. The bus is in the page (cards.js); the
# server only ever narrows: the slice is AND-ed onto the card's own filter,
# mapped and checked against the card's own dataset, so it can't widen what the
# card shows or reach a column the card's data doesn't have.

CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def link_warnings(layout: Any) -> list[str]:
    """Channels with one end on this dashboard: a card publishing to a channel
    no card listens to, or listening to one no card publishes. Saved as is (a
    layout is built a card at a time), but said: a typo in a channel name
    otherwise breaks the click with no sign."""
    published: dict[str, list[str]] = {}
    heard: dict[str, list[str]] = {}
    for cell in layout or []:
        if not isinstance(cell, dict):
            continue
        options = cell.get("options") or {}
        name = str(cell.get("title") or cell.get("id") or "a card")
        if isinstance(options.get("publish"), str) and options["publish"]:
            published.setdefault(options["publish"], []).append(name)
        listen = options.get("listen")
        if isinstance(listen, dict) and isinstance(listen.get("channel"), str):
            heard.setdefault(listen["channel"], []).append(name)
    out = [
        f"{', '.join(who)} publishes to {ch!r}, which no card listens to"
        for ch, who in published.items()
        if ch not in heard
    ]
    out += [
        f"{', '.join(who)} listens to {ch!r}, which no card publishes to"
        for ch, who in heard.items()
        if ch not in published
    ]
    return out


def link_problems(ct: ComponentType, options: dict[str, Any], source: Optional["Metric"]) -> list[str]:
    """Problems with a card's ``publish`` / ``listen`` options."""
    problems: list[str] = []
    publish, listen = options.get("publish"), options.get("listen")
    if publish in (None, "") and listen in (None, "", {}):
        return problems
    if not ct.needs_metric and not ct.publishes:
        return [f"a {ct.label} card draws no data, so it can't publish or listen"]
    if not ct.needs_metric and listen not in (None, "", {}):
        problems.append(f"listen: a {ct.label} card draws no data, so there's nothing to narrow")
    if publish not in (None, ""):
        if not isinstance(publish, str) or not CHANNEL_RE.match(publish):
            problems.append("publish: a channel name — lower-case letters, digits, - or _, up to 40")
        elif not (ct.publishes or ct.drillable):
            problems.append(f"publish: a {ct.label} card has nothing to click")
    if listen not in (None, "", {}):
        if not isinstance(listen, dict) or not isinstance(listen.get("channel"), str):
            return [*problems, 'listen: {"channel": "<name>", "map"?: {"their_column": "my_column"}}']
        if not CHANNEL_RE.match(listen["channel"]):
            problems.append("listen.channel: lower-case letters, digits, - or _, up to 40")
        if listen["channel"] == publish:
            problems.append("listen.channel: a card can't listen to the channel it publishes to")
        unknown = sorted(set(listen) - {"channel", "map"})
        if unknown:
            problems.append(f"listen: unknown key(s) {unknown}")
        mapping = listen.get("map", {})
        pairs = mapping.items() if isinstance(mapping, dict) else ()
        well_formed = isinstance(mapping, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in pairs)
        if not well_formed:
            problems.append('listen.map: {"their_column": "my_column"}')
        elif source is not None:
            columns = _dataset_columns(source)
            if columns is not None:
                problems.extend(
                    f"listen.map: {theirs!r} → {mine!r}: this card's data has no column {mine!r}"
                    for theirs, mine in mapping.items()
                    if mine not in columns
                )
    return problems


def _rename_fields(tree: Any, mapping: dict[str, str]) -> Any:
    if isinstance(tree, list):
        return [_rename_fields(t, mapping) for t in tree]
    if not isinstance(tree, dict):
        return tree
    out = {k: _rename_fields(v, mapping) for k, v in tree.items()}
    if isinstance(out.get("field"), str):
        out["field"] = mapping.get(out["field"], out["field"])
    return out


def listened_narrow(cell: dict[str, Any], raw: str, source: Optional["Metric"]) -> tuple[Any, str]:
    """The slice a listening card was sent (``?narrow=<json>``), mapped to its
    columns and checked against its dataset: ``(tree or None, problem)``. A
    card that doesn't listen, or a slice that names a column its data doesn't
    have, is refused with a reason — never quietly dropped, which would show
    the whole set under a heading that says it's narrowed."""
    import json

    from apps.datasets.core import get_dataset
    from apps.datasets.filter_tree import tree_fields

    listen = (cell.get("options") or {}).get("listen")
    if not raw:
        return None, ""
    if not isinstance(listen, dict) or source is None:
        return None, "This card doesn't listen to other cards."
    try:
        tree = json.loads(raw)
    except ValueError:
        return None, "The slice sent to this card isn't readable."
    ds = get_dataset(source.dataset) if source.dataset else None
    if ds is None or source.is_rate or source.is_manual:
        return None, "This card's data can't be narrowed by another card."
    mapping = dict(listen.get("map") or {})
    # A calendar's day arrives on "date": unless the card maps it, or its data has a
    # column of that name, it means the card's period column (the date it's read over).
    if "date" not in mapping and "date" not in ds.column_names() and source.period_field:
        mapping["date"] = source.period_field
    tree = _rename_fields(tree, mapping)
    problems = ds.validate_filter_tree(tree)
    if problems:
        if "date" in tree_fields(tree):
            return None, (
                "A day was sent to this card, but it has no period column to read it over. "
                "Give it one, or match the sender's date to one of its date columns."
            )
        return None, "The card that was clicked filters a column this card's data doesn't have: " + "; ".join(problems)
    return tree, ""


def _dataset_columns(metric: "Metric") -> Optional[list[str]]:
    from apps.datasets.core import get_dataset

    ds = get_dataset(metric.dataset)
    return ds.column_names() if ds is not None else None


def inline_source(cell: dict[str, Any], *, name: str = "") -> Optional["Metric"]:
    """The card's own dataset definition as an UNSAVED ``Metric`` (no pk, no
    key): what every build, trend and drill-down evaluates, so a card that
    filters a dataset itself and a card over a saved metric are drawn by one
    code path. Its format, unit and colour rules are the card's own
    (``options.style``, ``options.thresholds``). None without a dataset."""
    from apps.datasets.registry import get_def

    from .models import SOURCE_DATASET, Metric

    if not cell.get("dataset"):
        return None
    if not name and not cell_title(cell):
        dfn = get_def(str(cell["dataset"]))  # untitled: named after its data, as a metric's card is after the metric
        name = str(getattr(dfn, "label", "") or "") if dfn is not None else ""
    options: dict[str, Any] = cell.get("options") or {}
    raw_style = options.get("style")
    style: dict[str, Any] = raw_style if isinstance(raw_style, dict) else {}
    thresholds = options.get("thresholds")
    return Metric(
        name=name or cell_title(cell) or "Card",
        source=SOURCE_DATASET,
        dataset=str(cell["dataset"]),
        filter_tree=cell.get("filter_tree") or {},
        agg=str(cell.get("agg") or "count"),
        measure=str(cell.get("measure") or ""),
        period_field=str(cell.get("period_field") or ""),
        format=str(style.get("format") or "number"),
        unit=str(style.get("unit") or ""),
        thresholds=thresholds if isinstance(thresholds, list) else [],
    )


def cell_source(cell: dict[str, Any], *, metrics: Optional[dict[str, "Metric"]] = None) -> Optional["Metric"]:
    """Where a cell's numbers come from, as a ``Metric``: the saved metric it
    names (looked up in *metrics* when given, else fetched), or its own
    dataset definition (:func:`inline_source`). None when it has neither or
    its metric no longer exists."""
    from .models import Metric

    key = cell.get("metric")
    if isinstance(key, str) and key:
        return metrics.get(key) if metrics is not None else Metric.objects.filter(key=key).first()
    return inline_source(cell)


def is_inline(metric: Optional["Metric"]) -> bool:
    """A source built from a card's own definition (never saved, so it has no page)."""
    return metric is not None and metric.pk is None


def _owner_may_read(dataset: str, owner_id: Any) -> bool:
    """Whether a personal dashboard's owner (the only one who edits it) may
    read *dataset*. An ownerless one is edited by staff, who read everything;
    an unknown dataset is left to the usual check to report."""
    if owner_id is None:
        return True
    from django.contrib.auth import get_user_model

    from apps.datasets.registry import get_def, user_may_read

    dfn = get_def(dataset)
    owner = get_user_model().objects.filter(pk=owner_id).first()
    return dfn is None or owner is None or user_may_read(dfn, owner)


def _source_problems(cell: dict[str, Any]) -> tuple[Optional["Metric"], list[str]]:
    """The card's own definition, checked as a metric is (dataset known,
    filter valid, measure and period column real) → ``(source, problems)``."""
    from django.core.exceptions import ValidationError

    if not isinstance(cell.get("filter_tree", {}), dict):
        return None, ["filter_tree: expected an object"]
    source = inline_source(cell)
    if source is None:
        return None, ["dataset: pick a dataset"]
    from .metrics import aggs_available

    # clean() doesn't check choices (full_clean does), so an unknown aggregate
    # ("count_distinct") was saved and drew a card that couldn't evaluate.
    allowed = [key for key, _label in aggs_available()]
    if source.agg not in allowed:
        return None, [f"agg: use one of {allowed} (not {source.agg!r})"]
    try:
        source.clean()
    except ValidationError as exc:
        return None, [f"{f}: {m}" for f, messages in exc.message_dict.items() for m in messages]
    return source, []


#: Why a card read over time can't draw a metric with no period field. The
#: dataset may well have a date column; the metric has to say which one it is
#: read over, and that lives on the metric's form, not the card's.
NO_PERIOD_FIELD = "needs a period field (the date column it is read over): set one in the metric's settings"
NO_PERIOD_COLUMN = "needs a period column: the date column it is read over"


def _unknown_option_problems(ct: ComponentType, options: dict[str, Any]) -> list[str]:
    """An option the card doesn't read would be saved and do nothing."""
    known = {spec["name"] for spec in ct.options_schema}
    # Whether these fit this card has its own, clearer refusals.
    unknown = sorted(set(options) - known - {"style", "thresholds", "drilldown", "publish", "listen"})
    if not unknown:
        return []
    takes = ", ".join(sorted(known)) or "none"
    hint = ""
    if "period" in unknown:
        hint = " A card follows its dashboard's period; use_period: false fixes it to all time."
    return [f"{', '.join(map(repr, unknown))}: a {ct.label} card doesn't read this (it takes: {takes}).{hint}"]


def _missing_caps(ct: ComponentType, metric: "Metric") -> list[str]:
    if not ct.requires:
        return []
    from apps.datasets.capabilities import DATE, REASONS, capabilities, missing_for

    if metric.is_rate or metric.is_manual:
        if ct.requires == {DATE}:
            return [] if metric.period_field else [NO_PERIOD_FIELD]
        return ["needs a metric over a dataset, to split it into groups"]
    no_period = NO_PERIOD_COLUMN if is_inline(metric) else NO_PERIOD_FIELD
    from apps.datasets.core import get_dataset

    ds = get_dataset(metric.dataset)
    if ds is None:
        return ["needs an available dataset"]
    try:
        caps = capabilities(ds.schema())
    except Exception:  # noqa: BLE001
        return []
    out = [REASONS.get(m, m) for m in sorted(missing_for(ct.requires, caps))]
    # A date column the metric doesn't read over is no use to a chart over time.
    if DATE in ct.requires and DATE in caps and not metric.period_field:
        out.append(no_period)
    return out


def next_position(layout: list[dict[str, Any]], w: int) -> tuple[int, int]:
    """Where a new ``w``-wide card goes: the end of the lowest row, or a new row
    below everything when it won't fit there. Four 3-wide cards make one row."""
    cells = [
        (_int(c.get("x")) or 0, _int(c.get("y")) or 0, _int(c.get("w")) or 1, _int(c.get("h")) or 1)
        for c in layout
        if isinstance(c, dict)
    ]
    if not cells:
        return 0, 0
    top = max(y for _x, y, _w, _h in cells)
    # Anything still occupying that row, including a taller card from above it.
    right = max(x + cw for x, y, cw, ch in cells if y <= top < y + ch)
    if right + w <= GRID_COLUMNS:
        return right, top
    return 0, max(y + ch for _x, y, _w, ch in cells)


# -- built-in types ---------------------------------------------------------------


def rows_url(ctx: CellContext, **params: Any) -> str:
    """Where this card's rows open (``ctx.rows_url``) with *params* — a
    ``narrow`` tree, the drill-down design — and the card's period. "" when
    the card has nowhere to open them. A build uses this for every rows link
    it draws, so a card over a metric and a card with a source of its own
    open their rows the same way."""
    from urllib.parse import urlencode

    if not ctx.rows_url:
        return ""
    query = {k: v for k, v in params.items() if v not in (None, "")}
    if ctx.narrow:
        # The slice this card is listening to narrows its rows too, and a
        # publishing card's clicks send it on (chaining: day, then method).
        import json

        from apps.datasets.filter_tree import and_trees

        own = json.loads(query["narrow"]) if query.get("narrow") else None
        query["narrow"] = json.dumps(and_trees(ctx.narrow, own), default=str)
    if ctx.period:
        query["period"] = ctx.period
    return f"{ctx.rows_url}?{urlencode(query)}" if query else ctx.rows_url


def source_rows_url(
    dashboard: Optional["Dashboard"], cell: dict[str, Any], source: Optional["Metric"], user: Any = None
) -> str:
    """The rows behind *cell*: a metric's own rows route; a card's own source
    reads them by its place on the dashboard — as does a card over a metric
    *user* may not open themselves (a dashboard shared with them), so access
    follows the dashboard; a card not saved anywhere yet (the builder's
    preview) through the preview-rows route, to which the builder posts the
    definition itself."""
    if source is None:
        return ""
    try:
        if not is_inline(source) and (user is None or source.can_view(user)):
            return reverse("dashboards_metric_rows", kwargs={"key": source.key})
        if dashboard is not None and dashboard.pk and cell.get("id"):
            return reverse("dashboards_cell_rows", kwargs={"slug": dashboard.slug, "cell_id": str(cell["id"])})
        return reverse("dashboards_preview_rows")
    except NoReverseMatch:  # dashboards routes switched off
        return ""


def metric_card_context(
    metric: "Metric",
    request: HttpRequest,
    *,
    period: Optional[str] = None,
    label: Optional[str] = None,
    period_in_label: bool = True,
    rows: Optional[str] = None,
) -> dict[str, Any]:
    """The framework ``stat_card.html`` context for *metric* — what
    ``{% metric_card %}`` and the dashboard ``metric`` cell both render, so a
    hand-placed card and a dashboard card are one component. A dashboard passes
    ``period_in_label=False``: its period bar already says the period. *rows*
    is where the number opens its rows; by default the metric's rows route."""
    result = evaluate(metric, request, period=period)
    title = label or metric.name
    href = None
    if result.ok:
        try:
            href = rows if rows is not None else reverse("dashboards_metric_rows", kwargs={"key": metric.key})
            if href and result.period:
                href += f"?period={result.period}"
        except NoReverseMatch:  # dashboards routes switched off
            href = None
    caption = title
    if result.period_label and period_in_label:
        caption = f"{title} · {result.period_label}"
    return {
        "value": "—" if result.restricted else (result.display if result.ok else "!"),
        "label": caption,
        "title": f"{title}, {period_heading(result.period).lower()}" if result.period else title,
        "href": href,
        "mode": "modal" if href else None,
        "state": "muted" if not result.ok else result.state,
        "unit": result.unit if result.ok else "",
        "result": result,
        "metric": metric,
    }


def build_metric(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """A ``metric`` cell: :func:`metric_card_context` plus its change from the
    previous period."""
    metric = ctx.metric
    assert metric is not None
    label = cell_title(cell) or metric.name
    if cell.get("use_period") is False and metric.period_field:
        label = f"{label} (all time)"  # pinned: the only card that differs from the period bar
    card = metric_card_context(
        metric, ctx.request, period=ctx.period, label=label, period_in_label=False, rows=ctx.rows_url
    )
    comparison = compare_with_previous(metric, ctx.request, ctx.period, card["result"])
    style = card_style(cell)
    result = card["result"]
    if result.ok:
        shown = styled_value(result.value, metric, style, result.state)
        card.update(value=shown["display"], unit=shown["unit"], state=shown["state"])
    if card.get("href"):
        # Through rows_url, like every other card: it adds the period, the
        # drill-down design and a slice this card is listening to.
        card["href"] = rows_url(ctx, **drill_params(cell))
    return {"card": card, "metric": metric, "result": result, "comparison": comparison, "style": style}


def _validate_group(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    problems = []
    if not isinstance(opts.get("dimension"), str) or not opts.get("dimension"):
        problems.append("'dimension' (the column to group by) is required")
    limit = opts.get("limit", 5)
    if _int(limit) is None or not 1 <= (_int(limit) or 0) <= 12:
        problems.append("'limit' must be 1–12")
    if "other" in opts and not isinstance(opts["other"], bool):
        problems.append("'other' must be true or false")
    return problems


def build_metric_group(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    import json

    from apps.datasets.filter_tree import FilterTreeError, and_trees

    from .metrics import group_leaf, group_values, may_read

    metric = ctx.metric
    assert metric is not None
    opts = cell.get("options") or {}
    dimension = str(opts.get("dimension") or "")
    style = card_style(cell)
    base = {"metric": metric, "label": cell_title(cell) or metric.name, "dimension": dimension, "style": style}
    if not may_read(metric, getattr(ctx.request, "user", None)):
        return {**base, "restricted": True, "groups": []}
    try:
        groups = group_values(
            metric,
            ctx.request,
            dimension,
            limit=_int(opts.get("limit", 5)) or 5,
            other=opts.get("other", True) is not False,
            period=ctx.period,
        )
    except (FilterTreeError, ValueError) as exc:
        return {**base, "error": str(exc), "groups": []}
    except Exception:  # noqa: BLE001
        logger.exception("metric_group %s: failed", metric.key or cell.get("id"))
        return {**base, "error": "This card could not be evaluated.", "groups": []}
    for g in groups:
        if g.get("other"):
            # The complement of the kept groups. ``NOT IN`` keeps NULLs, so a
            # kept "—" (NULL) group is excluded explicitly.
            kept = [v for v in g["exclude"] if v is not None]
            leaf = and_trees(
                {"not": {"field": dimension, "op": "in", "value": kept}} if kept else None,
                {"field": dimension, "op": "isnull", "value": False} if None in g["exclude"] else None,
            )
        else:
            leaf = group_leaf(dimension, g["raw"])
        g["drill_url"] = rows_url(ctx, narrow=json.dumps(leaf, default=str), **drill_params(cell))
        shown = styled_value(g["value"], metric, style, g.get("state"))
        g["display"] = shown["display"]
        if not g.get("other"):  # "Other" is a remainder, never coloured
            g["state"] = shown["state"]
    total = evaluate(metric, ctx.request, period=ctx.period)
    if total.ok:
        shown = styled_value(total.value, metric, style, total.state)
        total.display, total.unit = shown["display"], shown["unit"]
    compare_groups(groups, metric, ctx.request, ctx.period, dimension)
    return {**base, "groups": groups, "total": total}


def _widget_key(widget: Any) -> str:
    cls = type(widget)
    return f"{cls.__module__}.{cls.__qualname__}"


def available_widgets() -> list[tuple[str, Any, Any]]:
    """``[(key, widget, model_info|None)]`` for every registered DashboardWidget."""
    from apps.smallstack.dashboard import get_standalone_widgets

    out: list[tuple[str, Any, Any]] = []
    try:
        from apps.explorer.registry import explorer

        for widget, info in explorer.get_dashboard_widgets():
            out.append((f"{_widget_key(widget)}:{info.app_label}.{info.model_name}", widget, info))
    except Exception:  # noqa: BLE001 — the explorer is optional
        pass
    for widget in get_standalone_widgets():
        out.append((_widget_key(widget), widget, None))
    return out


def _validate_widget(cell: dict[str, Any]) -> list[str]:
    key = (cell.get("options") or {}).get("widget")
    if not key:
        return ["pick a widget ('widget': a key from list_dashboard_components)"]
    if key not in [k for k, _w, _i in available_widgets()]:
        return [f"no published widget {key!r}; list_dashboard_components lists them"]
    return []


def widget_refused(cell: dict[str, Any], user: Any) -> bool:
    """Whether ``cell`` is a widget card whose widget's ``visible_to`` refuses
    ``user`` (a failing gate refuses). A system board (``/smallstack/``) leaves
    such a card out rather than showing a dead "no access" box (T5-9); a saved
    dashboard shared wider than the widget still shows the restricted card."""
    if cell.get("type") != "widget":
        return False
    key = (cell.get("options") or {}).get("widget")
    for wkey, widget, _info in available_widgets():
        if wkey == key:
            try:
                return not widget.visible_to(user)
            except Exception:  # noqa: BLE001
                return True
    return False


def build_widget(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    from django.utils.safestring import mark_safe

    from apps.smallstack.dashboard import widget_url

    key = (cell.get("options") or {}).get("widget")
    for wkey, widget, info in available_widgets():
        if wkey != key:
            continue
        # The widget's own gate (``visible_to``), as the /smallstack/ cards
        # apply it: a board shared wider than the widget's numbers.
        try:
            visible = widget.visible_to(ctx.request.user)
        except Exception:  # noqa: BLE001 — a gate that fails closes
            visible = False
        if not visible:
            return {"restricted": True, "label": cell_title(cell) or widget.title}
        try:
            from apps.smallstack.displays import widget_data

            data = widget_data(widget, ctx.request.user, info.model_class if info is not None else None)
        except Exception:  # noqa: BLE001
            logger.warning("dashboard widget %s failed", wkey, exc_info=True)
            return {"error": "This widget failed to load."}
        style = card_style(cell)
        state = None
        if style["thresholds"] is not None:
            # The card's own rules replace the widget's status colouring.
            from .metrics import state_for

            state = state_for(widget_number(data), style["thresholds"])
            data = {**data, "status": _WIDGET_STATUS.get(state or "", "")}
        label = cell_title(cell) or widget.title
        return {
            "ctx": {
                "widget": widget,
                "title": label,
                "data": data,
                "url": widget_url(widget, info),
                "icon_safe": mark_safe(widget.icon),
                "group": getattr(info, "group", widget.group),
                "app_label": getattr(info, "app_label", None),
            },
            "label": label,
            "style": style,
            "state": state,
        }
    return {"error": "This widget is no longer registered."}


#: A threshold state as a widget status (the info card's own colouring).
_WIDGET_STATUS = {"success": "operational", "warning": "degraded", "danger": "down"}
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def widget_number(data: dict[str, Any]) -> Optional[float]:
    """The number an info card's colour rules compare: the widget's numeric
    ``value`` when its ``get_data()`` returns one (do, for exact rules), else
    the first number in its headline ("46,849 requests" → 46849)."""
    value = data.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _NUMBER_RE.search(str(data.get("headline") or ""))
    return float(match.group().replace(",", "")) if match else None


#: How a note looks: each a choice of theme tokens, never a literal colour, so
#: the note reads right on every palette. "" = the default (the card's own).
TEXT_LOOKS: dict[str, list[list[str]]] = {
    "size": [["s", "Small"], ["m", "Medium"], ["l", "Large"], ["xl", "Extra large"]],
    "align": [["start", "Left"], ["center", "Centre"], ["end", "Right"]],
    "color": [
        ["plain", "Plain"],
        ["quiet", "Quiet"],
        ["accent", "Accent"],
        ["success", "Success"],
        ["warning", "Warning"],
        ["danger", "Danger"],
    ],
    "background": [
        ["", "None"],
        ["band", "Accent tint"],
        ["raised", "Raised"],
        ["success", "Success"],
        ["warning", "Warning"],
        ["danger", "Danger"],
        ["info", "Info"],
    ],
}
_TEXT_DEFAULTS = {"size": "m", "align": "start", "color": "plain", "background": ""}


def _validate_text(cell: dict[str, Any]) -> list[str]:
    options = cell.get("options") or {}
    if "markdown" not in options:
        return ["'markdown' (the note's text) is required"]
    md = options["markdown"]
    if not isinstance(md, str) or len(md) > 5000:
        return ["'markdown' must be text, at most 5000 characters"]
    problems = []
    for name, choices in TEXT_LOOKS.items():
        value = options.get(name, _TEXT_DEFAULTS[name])
        if value not in (c[0] for c in choices):
            problems.append(f"'{name}' must be one of {[c[0] for c in choices if c[0]]}")
    return problems


def build_text(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    from django.utils.safestring import mark_safe

    from apps.smallstack.transforms import render_markdown

    opts = cell.get("options") or {}
    md = str(opts.get("markdown") or "")
    looks = {name: opts.get(name) or _TEXT_DEFAULTS[name] for name in TEXT_LOOKS}
    classes = " ".join(f"tx-{name}-{value}" for name, value in looks.items() if value)
    return {"html": mark_safe(render_markdown(md, toc=False)["html"]), "label": cell_title(cell), "classes": classes}


#: The most links a menu card holds.
MAX_MENU_LINKS = 30
MENU_LAYOUTS = (("auto", "Fit the card"), ("horizontal", "Across"), ("vertical", "Down"))


def menu_url_problem(url: Any) -> str:
    """Why *url* can't be a menu link ("" when it can): a page of this site
    (``/…``, ``#…``), an http(s) address, or mail. Nothing that runs."""
    if not isinstance(url, str) or not url.strip():
        return "needs a url"
    value = url.strip()
    lowered = value.lower()
    # "//host" and "/\\host" (a browser reads the backslash as a slash) leave the site.
    if lowered.startswith(("/", "#")) and not lowered.startswith(("//", "/\\")):
        return ""
    if lowered.startswith(("http://", "https://", "mailto:")):
        return ""
    return "url must be a page of this site (/…), an http(s) address or mailto:"


def _validate_menu(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    items = opts.get("items")
    problems = []
    if not isinstance(items, list) or not items:
        return ["'items' (the links) is required: [{label, url, new_window?}]"]
    if len(items) > MAX_MENU_LINKS:
        problems.append(f"'items': at most {MAX_MENU_LINKS} links")
    for n, item in enumerate(items[:MAX_MENU_LINKS]):
        where = f"items[{n}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: needs {{label, url}}")
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 60:
            problems.append(f"{where}.label: text, 1–60 characters")
        url_problem = menu_url_problem(item.get("url"))
        if url_problem:
            problems.append(f"{where}.url: {url_problem}")
        if "new_window" in item and not isinstance(item["new_window"], bool):
            problems.append(f"{where}.new_window: true or false")
        unknown = sorted(set(item) - {"label", "url", "new_window"})
        if unknown:
            problems.append(f"{where}: unknown key(s) {unknown}")
    if opts.get("layout", "auto") not in dict(MENU_LAYOUTS):
        problems.append(f"'layout' must be one of {[k for k, _ in MENU_LAYOUTS]}")
    return problems


def build_menu(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The links as given, in order. A link to another site or a new window
    opens with ``rel="noopener"``; the layout class is the chosen one, or
    ``auto`` for the stylesheet to fit the card's shape (container query)."""
    opts = cell.get("options") or {}
    items = [
        {
            "label": str(i.get("label", "")).strip(),
            "url": str(i.get("url", "")).strip(),
            "new_window": bool(i.get("new_window")),
            "external": str(i.get("url", "")).strip().lower().startswith(("http://", "https://")),
        }
        for i in (opts.get("items") or [])
        if isinstance(i, dict)
    ]
    return {"items": items, "label": cell_title(cell), "layout": opts.get("layout") or "auto"}


#: The most goals a goals card shows; the goal list's page has the rest.
MAX_CARD_GOALS = 10


def _goal_list_choices(user: Any) -> list[list[str]]:
    from .models import GoalList

    return [[g.slug, g.name] for g in GoalList.objects.visible_to(user).active().order_by("name")]


def _validate_goals(cell: dict[str, Any]) -> list[str]:
    from .models import GoalList

    opts = cell.get("options") or {}
    problems = []
    slug = opts.get("goal_list")
    if not isinstance(slug, str) or not GoalList.objects.filter(slug=slug).exists():
        problems.append(f"'goal_list' must be a goal list's slug (got {slug!r})")
    limit = _int(opts.get("limit", 5))
    if limit is None or not 1 <= limit <= MAX_CARD_GOALS:
        problems.append(f"'limit' must be 1–{MAX_CARD_GOALS}")
    if opts.get("order", "list") not in ("list", "attention"):
        problems.append("'order' must be 'list' or 'attention'")
    return problems


def build_goals(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """A goals card: the list's first goals (or its misses first), each value
    against its target, and how many of them are on target. Judged over the
    dashboard's period, unless a goal pins its own; a viewer who can't open
    the goal list is told so, never shown its goals."""
    from .goals import evaluate_goals
    from .models import GoalList

    opts = cell.get("options") or {}
    goal_list = GoalList.objects.filter(slug=opts.get("goal_list") or "").first()
    if goal_list is None:
        return {"error": "This goal list no longer exists."}
    label = cell_title(cell) or goal_list.name
    if not goal_list.can_view(getattr(ctx.request, "user", None)):
        return {"label": label, "restricted": True}
    limit = _int(opts.get("limit", 5)) or 5
    attention_first = opts.get("order") == "attention"
    # Every goal is judged, so the headline counts the whole list, not the few shown.
    data = evaluate_goals(goal_list, ctx.request, period=ctx.period, compare=False)
    rows = data["rows"]
    if attention_first:
        rank = {"fail": 0, "warn": 1, "none": 2, "pass": 3}
        rows = sorted(rows, key=lambda r: rank[r["status"]])
    return {
        "label": label,
        "goal_list": goal_list,
        "rows": rows[:limit],
        "summary": data["summary"],
        "more": max(len(rows) - limit, 0),
        "url": goal_list.get_absolute_url() + (f"?period={ctx.period}" if ctx.period else ""),
    }


def _staff_only(user: Any) -> bool:
    return bool(getattr(user, "is_staff", False))


def register_builtins() -> None:
    register_component_type(
        ComponentType(
            key="metric",
            label="Single stat",
            stylable=True,
            drillable=True,
            single_value=True,
            description="One number, a saved metric or a filter of your own, coloured by its rules; click for rows.",
            group="Stats",
            icon="M4 18h3V8H4v10zm6.5 0h3V4h-3v14zM17 18h3v-6h-3v6z",
            template="dashboards/cells/metric.html",
            build=build_metric,
            needs_metric=True,
            default_size=(3, 2),
        )
    )
    register_component_type(
        ComponentType(
            key="metric_group",
            label="Grouped stat",
            stylable=True,
            drillable=True,
            description="Filtered rows split by a column: the top groups as numbers, each drilling into its rows.",
            group="Stats",
            icon="M3 5h8v6H3V5zm10 0h8v6h-8V5zM3 13h5v6H3v-6zm7 0h4v6h-4v-6zm6 0h5v6h-5v-6z",
            template="dashboards/cells/metric_group.html",
            build=build_metric_group,
            needs_metric=True,
            default_size=(6, 2),
            requires=frozenset({"dimension"}),
            validate=_validate_group,
            options_schema=[
                {"name": "dimension", "label": "Group by", "type": "column", "required": True},
                {"name": "limit", "label": "Groups shown", "type": "integer", "default": 5, "min": 1, "max": 12},
                {"name": "other", "label": "Fold the rest into “Other”", "type": "boolean", "default": True},
            ],
        )
    )
    register_component_type(
        ComponentType(
            key="widget",
            label="Info card",
            # Its headline is text, so no number format or unit; its colour
            # rules read the widget's numeric "value", else the headline's first number.
            stylable=True,
            style_settings=("size", "color", "title_size", "title_color", "align"),
            description="A status card an app publishes, like the ones on the SmallStack dashboard (staff only).",
            group="Info",
            icon=(
                "M11 7h2v2h-2V7zm0 4h2v6h-2v-6zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"
                "m0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"
            ),
            template="dashboards/cells/widget.html",
            build=build_widget,
            default_size=(3, 2),
            validate=_validate_widget,
            visible_to=_staff_only,
            options_schema=[{"name": "widget", "label": "Widget", "type": "widget", "required": True}],
        )
    )
    register_component_type(
        ComponentType(
            key="text",
            label="Note",
            description="A markdown note — a heading, an explanation, a link.",
            group="Info",
            icon="M5 4v3h5.5v12h3V7H19V4H5z",
            template="dashboards/cells/text.html",
            build=build_text,
            default_size=(4, 2),
            validate=_validate_text,
            options_schema=[
                {"name": "markdown", "label": "Markdown", "type": "markdown", "required": True},
                # widget: how the builder draws the choice (cards.js): pills, or colour swatches.
                {
                    "name": "size",
                    "label": "Size",
                    "type": "choice",
                    "choices": [["s", "S"], ["m", "M"], ["l", "L"], ["xl", "XL"]],
                    "default": "m",
                    "widget": "segmented",
                },
                {
                    "name": "align",
                    "label": "Align",
                    "type": "choice",
                    "choices": TEXT_LOOKS["align"],
                    "default": "start",
                    "widget": "segmented",
                },
                {
                    "name": "color",
                    "label": "Text colour",
                    "type": "choice",
                    "choices": TEXT_LOOKS["color"],
                    "default": "plain",
                    "widget": "swatches",
                },
                {
                    "name": "background",
                    "label": "Background",
                    "type": "choice",
                    "choices": TEXT_LOOKS["background"],
                    "default": "",
                    "widget": "swatches",
                },
            ],
        )
    )
    register_component_type(
        ComponentType(
            key="menu",
            label="Menu",
            description="Links in your order, across or down: a way around, on the dashboard.",
            group="Info",
            icon="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z",
            template="dashboards/cells/menu.html",
            build=build_menu,
            default_size=(3, 3),
            validate=_validate_menu,
            options_schema=[
                {
                    "name": "items",
                    "label": "Links",
                    "type": "links",
                    "required": True,
                    "help": "Each link: its words, where it goes (a page of this site, /…, or an address), "
                    "and whether it opens a new window.",
                },
                {
                    "name": "layout",
                    "label": "Lay out",
                    "type": "choice",
                    "choices": [list(c) for c in MENU_LAYOUTS],
                    "default": "auto",
                    "widget": "segmented",
                    "help": "Fit the card: across when it's wide, down when it's tall.",
                },
            ],
        )
    )
    register_component_type(
        ComponentType(
            key="goals",
            label="Goals",
            description="The first goals of a goal list — each value against its target, and how many are on target.",
            group="Stats",
            icon=(
                "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm0-14a6 6 0 1 0 0 12"
                " 6 6 0 0 0 0-12zm0 10a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm0-6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"
            ),
            template="dashboards/cells/goals.html",
            build=build_goals,
            default_size=(4, 4),
            validate=_validate_goals,
            options_schema=[
                {
                    "name": "goal_list",
                    "label": "Goal list",
                    "type": "choice",
                    "required": True,
                    "choices": _goal_list_choices,
                },
                {
                    "name": "limit",
                    "label": "Goals shown",
                    "type": "integer",
                    "default": 5,
                    "min": 1,
                    "max": MAX_CARD_GOALS,
                },
                {
                    "name": "order",
                    "label": "Order",
                    "type": "choice",
                    "default": "list",
                    "choices": [["list", "As listed"], ["attention", "Missed and at risk first"]],
                    "widget": "segmented",
                },
            ],
        )
    )


register_builtins()
