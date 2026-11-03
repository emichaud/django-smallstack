"""``{% metric_card %}`` — a saved metric as a stat card, anywhere.

    {% load dashboard_tags %}
    <div class="stat-cards">
      {% metric_card "open_tickets" %}
      {% metric_card "p95_latency" period="mtd" label="p95 this month" %}
    </div>

It renders the framework's ``{% stat_card %}`` markup (same template, same
global drill-down modal) from a stored Metric — so a hand-placed card on any
page, a dashboard cell and a report column show the same number. The card
drills into the rows behind the value; thresholds drive its state colour.

A metric the viewer may not open, or whose dataset they may not read, renders
a muted "—" card rather than an error or a number.
"""

from __future__ import annotations

from typing import Any, Optional

from django import template

from ..components import metric_card_context
from ..periods import PREVIOUS_PERIOD, period_heading, period_phrase

register = template.Library()


@register.inclusion_tag("smallstack/includes/stat_card.html", takes_context=True)
def metric_card(context: Any, key: str, period: Optional[str] = None, label: Optional[str] = None) -> dict[str, Any]:
    from ..models import Metric

    request = context.get("request")
    user = getattr(request, "user", None)
    metric = Metric.objects.filter(key=key).first()
    if metric is None or request is None or not metric.can_view(user):
        return {
            "value": "—",
            "label": label or key,
            "title": label or key,
            "href": None,
            "mode": None,
            "state": "muted",
        }
    return metric_card_context(metric, request, period=period, label=label)


@register.inclusion_tag("dashboards/includes/embed.html", takes_context=True)
def dashboard(
    context: Any, dashboard: Any, period: Optional[str] = None, title: bool = True, lazy: bool = True
) -> dict[str, Any]:
    """``{% dashboard "site-health" %}`` — a saved dashboard, on any page.

    *dashboard* is a slug or a ``Dashboard``. ``period`` overrides the one it
    opens with (``"all"`` for all time); ``title=False`` drops the heading;
    ``lazy=False`` renders the cards now instead of loading each over htmx.
    Renders nothing for a dashboard the viewer may not open (or an anonymous
    viewer — the cards load from a login-protected endpoint), so a page never
    reveals one exists. Same cards, same access checks, same drill-down modal
    as the dashboard page."""
    from ..boards import board_embed
    from ..models import Dashboard

    request = context.get("request")
    user = getattr(request, "user", None)
    obj = dashboard if isinstance(dashboard, Dashboard) else Dashboard.objects.filter(slug=str(dashboard)).first()
    if request is None or obj is None or not getattr(user, "is_authenticated", False) or not obj.can_view(user):
        return {"embed": None}
    # None = the dashboard's own period; "" = all time.
    chosen = "" if period == "all" else (period or None)
    return {"embed": board_embed(obj, request, period=chosen, lazy=lazy), "title": title, "request": request}


@register.simple_tag
def relative_periods() -> list[tuple[str, str]]:
    """The period vocabulary, for a template's own period picker:
    ``{% relative_periods as periods %}``."""
    from apps.datasets.dateranges import RELATIVE_PERIODS

    return list(RELATIVE_PERIODS)


@register.simple_tag
def layout_preview(layout: Any) -> dict[str, Any]:
    """A dashboard layout shaped for a miniature grid: each cell with a label,
    its type's label, and its CSS grid placement. Tolerates a malformed layout
    (an unsaved, invalid form) by skipping cells it can't place."""
    from ..components import get_component_type
    from ..models import Metric

    cells = [c for c in (layout if isinstance(layout, list) else []) if isinstance(c, dict)]
    keys = {c.get("metric") for c in cells if isinstance(c.get("metric"), str)}
    names = dict(Metric.objects.filter(key__in=keys).values_list("key", "name")) if keys else {}
    out = []
    rows = 0
    for c in cells:
        try:
            x, y, w, h = (int(c.get(k, d)) for k, d in (("x", 0), ("y", 0), ("w", 3), ("h", 2)))
        except (TypeError, ValueError):
            continue
        ct = get_component_type(str(c.get("type", "")))
        label = c.get("title") or names.get(str(c.get("metric") or "")) or (ct.label if ct else str(c.get("type")))
        if c.get("type") == "text" and not c.get("title"):
            md = str((c.get("options") or {}).get("markdown") or "")
            label = md.replace("*", "").replace("#", "").strip()[:60] or "Text"
        rows = max(rows, y + h)
        out.append(
            {
                "id": c.get("id"),
                "metric": c.get("metric") if c.get("type") == "metric" else None,
                "label": label,
                "type": c.get("type"),
                "type_label": ct.label if ct else c.get("type"),
                "style": f"grid-column: {x + 1} / span {w}; grid-row: {y + 1} / span {h};",
            }
        )
    return {"cells": out, "rows": rows}


@register.simple_tag
def report_metric_choices(user: Any, report: Any) -> list[dict[str, Any]]:
    """The metrics a report's row picker offers: shared metrics plus the
    report owner's own (on a new report, the requesting user's) — exactly
    what ``Report.clean`` will accept."""
    from django.db.models import Q

    from ..goals import suggest_target
    from ..models import Metric

    owner_id = getattr(report, "owner_id", None) if getattr(report, "pk", None) else getattr(user, "pk", None)
    qs = (
        Metric.objects.filter(Q(owner__isnull=True) | Q(owner_id=owner_id))
        if owner_id
        else Metric.objects.filter(owner__isnull=True)
    )
    return [
        {
            "key": m.key,
            "name": m.name,
            "dataset": m.dataset,
            "period_aware": bool(m.period_field),
            "suggest": suggest_target(m),
        }
        for m in qs.order_by("name")
    ]


@register.simple_tag
def period_chips(selected: Any) -> list[dict[str, Any]]:
    """Every listed period as ``{key, label, checked}``, plus any selected
    generic period (``last_45``) that isn't in the list — so editing a report
    an agent wrote never silently drops one of its columns."""
    from apps.datasets.dateranges import RELATIVE_PERIODS, period_label

    chosen = [str(s) for s in (selected or []) if s]
    listed = {k for k, _ in RELATIVE_PERIODS}
    out = [{"key": k, "label": lbl, "checked": k in chosen} for k, lbl in RELATIVE_PERIODS]
    out += [{"key": k, "label": period_label(k), "checked": True} for k in chosen if k not in listed]
    return out


#: How the period picker groups the vocabulary — one compact row per group.
_PERIOD_GROUPS: list[tuple[str, list[str]]] = [
    ("This", ["today", "wtd", "mtd", "qtd", "ytd"]),
    ("Previous", ["yesterday", "pwtd", "pmtd", "pqtr", "prev_year"]),
    ("Rolling", ["last_7", "last_30", "last_90", "next_7", "next_30"]),
]
_SHORT_LABELS = {
    "today": "Today",
    "wtd": "Week",
    "mtd": "Month",
    "qtd": "Quarter",
    "ytd": "Year",
    "yesterday": "Yesterday",
    "pwtd": "Week",
    "pmtd": "Month",
    "pqtr": "Quarter",
    "prev_year": "Year",
    "last_7": "Last 7d",
    "last_30": "Last 30d",
    "last_90": "Last 90d",
    "next_7": "Next 7d",
    "next_30": "Next 30d",
}


@register.simple_tag
def period_groups(selected: Any) -> list[dict[str, Any]]:
    """The period vocabulary as compact labelled rows (This / Previous /
    Rolling) of ``{key, label, title, checked}`` chips — short labels, full
    label as the tooltip. A selected key outside the groups (a generic
    ``last_45`` an agent wrote) gets an "Other" row so it is never dropped."""
    from apps.datasets.dateranges import period_label

    if isinstance(selected, (list, tuple)):
        chosen = {str(s) for s in selected if s}
    else:
        chosen = {str(selected)} if selected else set()
    grouped = {k for _g, keys in _PERIOD_GROUPS for k in keys}
    out = [
        {
            "label": name,
            "chips": [
                {
                    "key": k,
                    "label": _SHORT_LABELS.get(k, period_label(k)),
                    "title": period_label(k),
                    "heading": period_heading(k),
                    "checked": k in chosen,
                }
                for k in keys
            ],
        }
        for name, keys in _PERIOD_GROUPS
    ]
    extra = sorted(chosen - grouped)
    if extra:
        out.append(
            {
                "label": "Other",
                "chips": [
                    {
                        "key": k,
                        "label": period_label(k),
                        "title": period_label(k),
                        "heading": period_heading(k),
                        "checked": True,
                    }
                    for k in extra
                ],
            }
        )
    return out


@register.simple_tag
def metric_choice_chips(kind: str, current: Any) -> list[dict[str, Any]]:
    """``agg`` / ``format`` choices as chips: ``{key, label, example, checked}``
    (a format's "Number — 9,481" splits into label + example)."""
    from ..metrics import ALL_AGGS, FORMATS, MANUAL_AGGS

    vocabulary = ALL_AGGS if kind == "agg" else FORMATS
    manual = {key for key, _label in MANUAL_AGGS}
    default = vocabulary[0][0]
    out = []
    for key, text in vocabulary:
        label, _sep, example = text.partition(" — ")
        out.append(
            {
                "key": key,
                "label": label,
                "example": example,
                "dataset_only": kind == "agg" and key not in manual,
                "manual_only": key == "latest",
                "checked": key == (current or default),
            }
        )
    return out


@register.simple_tag
def metric_usage_for(user: Any, metric: Any) -> Any:
    """Where *metric* is used (``models.metric_usage``), or None for an unsaved one."""
    from ..models import metric_usage

    if metric is None or getattr(metric, "pk", None) is None:
        return None
    return metric_usage(metric, user)


@register.simple_tag
def previous_periods() -> dict[str, list[str]]:
    """``{period: [previous period, how a sentence names it]}`` for previews:
    ``{"mtd": ["pmtd", "last month"], …}``."""
    return {k: [prev, period_phrase(prev)] for k, prev in PREVIOUS_PERIOD.items()}


@register.filter
def index(sequence: Any, i: int) -> Any:
    """``{{ list|index:n }}`` — the nth item, or None past the end."""
    try:
        return sequence[i]
    except (IndexError, KeyError, TypeError):
        return None


#: The generated cover's motifs, picked per dashboard by board_cover.
COVER_MOTIFS = ("bars", "line", "ring", "tiles")


@register.filter
def index_key(mapping: Any, key: str) -> Any:
    """``mapping[key]`` for a key held in a variable (``{{ d|index_key:name }}``);
    ``None`` when absent."""
    try:
        return mapping[key]
    except (KeyError, TypeError):
        return None


@register.simple_tag(takes_context=True)
def board_card_table(context: Any, dashboard: Any) -> dict[str, Any]:
    """The cards table for the settings page, in reading order (``boards.board_cards``)."""
    from ..boards import board_cards

    return board_cards(dashboard, context["request"])


@register.simple_tag
def board_cover(dashboard: Any) -> dict[str, Any]:
    """What a dashboard without a picture shows instead: its initials over a
    small chart motif. Stable per dashboard (seeded by its slug), different
    between neighbours, and drawn in theme colours by board_cover.html.

    Coordinates are for the SVG's ``0 0 160 90`` viewBox; the motif sits in
    the right half so the initials have the left."""
    import zlib

    seed = zlib.crc32(str(getattr(dashboard, "slug", "") or getattr(dashboard, "name", "")).encode())
    words = [w for w in str(getattr(dashboard, "name", "")).replace("-", " ").split() if w[:1].isalnum()]
    monogram = "".join(w[0] for w in words[:2]).upper() or "D"

    def n(i: int, lo: int, hi: int) -> int:
        """The i-th pseudo-random number in [lo, hi] for this seed."""
        return lo + (zlib.crc32(f"{seed}:{i}".encode()) % (hi - lo + 1))

    motif = COVER_MOTIFS[seed % len(COVER_MOTIFS)]
    out: dict[str, Any] = {"monogram": monogram, "motif": motif}
    if motif == "bars":
        out["bars"] = [{"x": 80 + i * 12, "y": 78 - (h := n(i, 14, 58)), "h": h} for i in range(6)]
    elif motif == "line":
        pts = [(72 + i * 13, n(i, 18, 62)) for i in range(7)]
        out["points"] = " ".join(f"{x},{y}" for x, y in pts)
        out["area"] = f"72,80 {out['points']} 150,80"
        out["last"] = {"x": pts[-1][0], "y": pts[-1][1]}
    elif motif == "ring":
        share = n(0, 35, 85) / 100
        circumference = 2 * 3.14159 * 24
        out["dash"] = f"{circumference * share:.1f} {circumference:.1f}"
    else:
        strong = {n(i, 0, 8) for i in range(3)}
        out["tiles"] = [{"x": 92 + (i % 3) * 18, "y": 18 + (i // 3) * 18, "strong": i in strong} for i in range(9)]
    return out


@register.inclusion_tag("dashboards/includes/playlist_player.html", takes_context=True)
def playlist(
    context: Any,
    playlist: Any,
    slide: int = 1,
    play: Optional[bool] = None,
    seconds: Optional[int] = None,
    loop: Optional[bool] = None,
) -> dict[str, Any]:
    """``{% playlist "wall" play=True seconds=20 %}`` — a dashboard playlist,
    playing on any page. The arguments are the link options of the playlist
    page (``slide`` is 1-based; ``None`` = the playlist's own setting). Renders
    nothing for a playlist the viewer may not open. Keyboard shortcuts work
    when focus is inside the player, and the page's address stays put."""
    from ..models import Playlist
    from ..playlists import player_context

    request = context.get("request")
    user = getattr(request, "user", None)
    obj = playlist if isinstance(playlist, Playlist) else Playlist.objects.filter(slug=str(playlist)).first()
    if request is None or obj is None or not obj.can_view(user):
        return {"slides": [], "playlist": None}
    params = {"slide": str(slide)}
    if play is not None:
        params["play"] = "1" if play else "0"
    if seconds:
        params["seconds"] = str(seconds)
    if loop is not None:
        params["loop"] = "1" if loop else "0"
    return {**player_context(obj, request, params), "request": request}


@register.simple_tag
def playlist_editor_data(user: Any) -> dict[str, Any]:
    """What the playlist form's picker offers: the dashboards and goal lists
    *user* may put in a playlist (``forms.playlist_dashboard_choices`` /
    ``playlist_goal_choices``) and the period keys an item may pin."""
    from apps.datasets.dateranges import RELATIVE_PERIODS

    from ..forms import playlist_dashboard_choices, playlist_goal_choices

    return {
        "dashboards": playlist_dashboard_choices(user),
        "goal_lists": playlist_goal_choices(user),
        "periods": [["all", "All time"], *[[k, str(label)] for k, label in RELATIVE_PERIODS]],
    }


@register.filter
def single_value(component: Any) -> bool:
    """Whether a saved card boils down to one number, so it can be a goal."""
    from ..components import get_component_type

    ct = get_component_type(str(getattr(component, "type", "") or ""))
    return bool(ct is not None and ct.single_value)


@register.simple_tag
def goal_editor_data(user: Any, goal_list: Any = None) -> dict[str, Any]:
    """What the goals editor offers (``forms.goal_editor_data``): the metrics
    and single-stat cards the list may hold — the owner's personal ones as
    well as shared ones; the editor offers only shared ones while the list is
    set to shared."""
    from ..forms import goal_editor_data as data

    owner_id = getattr(goal_list, "owner_id", None) or getattr(user, "pk", None)
    return data(user, owner_id)


@register.simple_tag
def component_media() -> Any:
    """``{% component_media %}`` — the ``<link>``/``<script>`` tags every
    registered card type declares (``ComponentType.media``), each once. Put it
    on any page that shows cards; the dashboard page, ``{% dashboard %}``,
    the playlist player and the component builder do. Scripts are ``defer``,
    so a card's script mounts on load and again on ``htmx:afterSettle``."""
    from django.templatetags.static import static
    from django.utils.html import format_html, format_html_join

    from ..components import component_media as media

    files = media()
    css = format_html_join("\n", '<link rel="stylesheet" href="{}">', ((static(p),) for p in files["css"]))
    js = format_html_join("\n", '<script src="{}" defer></script>', ((static(p),) for p in files["js"]))
    return format_html("{}\n{}", css, js)


#: The component builder's palette sections, in order; any other group follows.
PALETTE_ORDER = ("Stats", "Info", "Charts")


@register.simple_tag
def component_builder_data(user: Any, component: Any) -> dict[str, Any]:
    """The component builder's data: the palette (card types grouped by
    ``ComponentType.group``), the metrics a card owned by the component's owner
    may draw (``forms.builder_payload``), and the dashboards already showing it."""
    from ..forms import builder_payload
    from ..models import Dashboard

    owner_id = component.owner_id if getattr(component, "pk", None) else getattr(user, "pk", None)
    data = builder_payload(user, owner_id)
    groups: dict[str, list[dict[str, Any]]] = {}
    for t in data["types"]:
        groups.setdefault(t["group"] or "Other", []).append(t)
    order = [g for g in PALETTE_ORDER if g in groups] + sorted(g for g in groups if g not in PALETTE_ORDER)
    data["palette"] = [{"group": g, "types": groups[g]} for g in order]
    used = []
    if getattr(component, "pk", None):
        for board in Dashboard.objects.visible_to(user).order_by("name"):
            if any(isinstance(c, dict) and c.get("component") == component.key for c in board.layout or []):
                used.append({"name": board.name, "url": board.get_absolute_url()})
    data["used_on"] = used
    return data
