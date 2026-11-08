"""Goals — numbers judged against targets, in sections, for a meeting.

A goal is one value (a metric, or a saved single-stat card) and a **target
rule**: ``{"op": ">=", "value": 95}``. The value either meets it (*on
target*), meets an optional second, looser rule (*at risk*), or neither
(*missed*); no number at all is *no data*. Rules use the metric threshold
operators (``> >= < <= = != between``; ``between`` takes ``[low, high]``)::

    {"metric": "first_response_p95", "label": "First response (p95)",
     "target": {"op": "<=", "value": 3600}, "warn": {"op": "<=", "value": 5400},
     "period": "last_7", "note": "Support lead owns this"}

The building blocks, for the pages here and for a downstream app's own UI:

- :func:`normalize_sections` — validate and tidy ``GoalList.sections``
  (``clean()`` calls it, so every surface is checked the same way).
- :func:`judge` — a value and its rules → ``pass`` / ``warn`` / ``fail`` / ``none``.
- :func:`evaluate_goals` — a goal list as one viewer sees it: every goal's
  value, status, target in words and change from the previous period, per
  section and overall (:func:`summarize`).
- :func:`goals_embed` — the same with its heading, for a playlist slide or
  any page (``dashboards/includes/goals_board.html`` renders it).
- :func:`goal_values` — the same, JSON-safe, for REST and MCP.
- :func:`add_goal` — append one goal to a section (the "Add to goals"
  button, the ``goal_list_add_goal`` tool).
- :func:`suggest_target` — a target and an at-risk rule read off a metric's
  colour rules, to prefill a new goal.

A saved card can be a goal when its type declares ``single_value=True``
(``ComponentType``): the goal takes the card's metric, number format and
unit. The framework's single stat does; an app's own one-number card can.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest
from django.urls import reverse

from .metrics import THRESHOLD_OPS, _is_number, display_unit, format_value, state_for

if TYPE_CHECKING:
    from .models import Component, GoalList, Metric

MAX_SECTIONS = 20
MAX_GOALS = 100
MAX_NOTE = 280
_SECTION_KEYS = {"title", "goals"}
_GOAL_KEYS = {"targets", "id", "metric", "component", "label", "target", "warn", "period", "note"}

#: A goal's status → what it's called, and the theme state that colours it.
STATUS_LABELS = {"pass": "On target", "warn": "At risk", "fail": "Missed", "none": "No data"}
STATUS_STATES = {"pass": "success", "warn": "warning", "fail": "danger", "none": "muted"}
#: The cadences a goal can have its own target for (``snapshots.py``).
CADENCE_KEYS = ("hourly", "daily", "weekly", "monthly", "quarterly")
_SYMBOLS = {">=": "≥", "<=": "≤", "!=": "≠", "=": "="}


# -- validation -------------------------------------------------------------------


def rule_problems(rule: Any, where: str) -> list[str]:
    if not isinstance(rule, dict) or set(rule) - {"op", "value"}:
        return [f"{where}: an object with 'op' and 'value'"]
    op, value = rule.get("op"), rule.get("value")
    if op not in THRESHOLD_OPS:
        return [f"{where}.op: one of {list(THRESHOLD_OPS)}"]
    if op == "between":
        if not (isinstance(value, list) and len(value) == 2 and all(_is_number(v) for v in value)):
            return [f"{where}.value: 'between' takes [low, high]"]
        if value[0] > value[1]:
            return [f"{where}.value: low must not be above high"]
    elif not _is_number(value):
        return [f"{where}.value: a number"]
    return []


def _as_sections(raw: Any) -> Optional[list[Any]]:
    """Sections as given, or a bare list of goals wrapped in one untitled section."""
    if not isinstance(raw, list):
        return None
    if raw and all(isinstance(s, dict) and "goals" not in s and ("metric" in s or "component" in s) for s in raw):
        return [{"title": "", "goals": raw}]
    return raw


def normalize_sections(raw: Any, *, owner_id: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """``(sections, problems)``. Fills in each goal's ``id`` and drops blank
    optional keys; a bare list of goals becomes one untitled section.

    A goal must name exactly one of a metric or a saved card, and either must
    be one the list's owner may use — shared, or (for a personal list) the
    owner's own — the rule dashboards and reports apply, so a shared goal list
    can't carry someone's personal metric to everyone."""
    from apps.datasets.dateranges import is_period

    from .components import get_component_type, personal_problem
    from .models import Component, Metric, _visible_to_owner

    if raw in (None, ""):
        return [], []
    sections = _as_sections(raw)
    if sections is None:
        return [], ['sections must be a list of {"title", "goals"}']
    if len(sections) > MAX_SECTIONS:
        return [], [f"at most {MAX_SECTIONS} sections"]
    goals_in = [g for s in sections if isinstance(s, dict) for g in (s.get("goals") or []) if isinstance(g, dict)]
    if len(goals_in) > MAX_GOALS:
        return [], [f"at most {MAX_GOALS} goals"]
    metrics = {
        m.key: m
        for m in Metric.objects.filter(key__in=[g["metric"] for g in goals_in if isinstance(g.get("metric"), str)])
    }
    cards = {
        c.key: c
        for c in Component.objects.filter(
            key__in=[g["component"] for g in goals_in if isinstance(g.get("component"), str)]
        )
    }
    used = {g["id"] for g in goals_in if isinstance(g.get("id"), str)}
    seen: set[str] = set()
    counter = 0
    problems: list[str] = []
    out: list[dict[str, Any]] = []
    for s_n, section in enumerate(sections):
        s_where = f"sections[{s_n}]"
        if not isinstance(section, dict):
            problems.append(f"{s_where}: expected an object")
            continue
        extra = sorted(set(section) - _SECTION_KEYS)
        if extra:
            problems.append(f"{s_where}: unexpected key(s) {extra}")
        title = section.get("title") or ""
        if not isinstance(title, str) or len(title) > 120:
            problems.append(f"{s_where}.title: text, at most 120 characters")
            title = ""
        goals = section.get("goals") or []
        if not isinstance(goals, list):
            problems.append(f"{s_where}.goals: a list")
            goals = []
        clean_goals: list[dict[str, Any]] = []
        for g_n, goal in enumerate(goals):
            where = f"{s_where}.goals[{g_n}]"
            if not isinstance(goal, dict):
                problems.append(f"{where}: expected an object")
                continue
            extra = sorted(set(goal) - _GOAL_KEYS)
            if extra:
                problems.append(f"{where}: unexpected key(s) {extra}")
                continue
            clean: dict[str, Any] = {}
            gid = goal.get("id")
            if gid in (None, ""):
                counter += 1
                while f"g{counter}" in used or f"g{counter}" in seen:
                    counter += 1
                gid = f"g{counter}"
            if not isinstance(gid, str) or not gid.replace("-", "").replace("_", "").isalnum() or len(gid) > 40:
                problems.append(f"{where}.id: letters, digits, - and _ only (max 40)")
                continue
            if gid in seen:
                problems.append(f"{where}.id: duplicate id {gid!r}")
                continue
            seen.add(gid)
            clean["id"] = gid
            metric_key, card_key = goal.get("metric") or "", goal.get("component") or ""
            if bool(metric_key) == bool(card_key):
                problems.append(f"{where}: name a 'metric' or a 'component' (one of them)")
                continue
            if metric_key:
                metric = metrics.get(metric_key) if isinstance(metric_key, str) else None
                if metric is None:
                    problems.append(f"{where}.metric: no metric with key {metric_key!r}")
                    continue
                if not _visible_to_owner(metric.owner_id, owner_id):
                    problems.append(f"{where}.metric: {personal_problem(metric_key, 'metric', owner_id)}")
                    continue
                clean["metric"] = metric.key
            else:
                card = cards.get(card_key) if isinstance(card_key, str) else None
                if card is None:
                    problems.append(f"{where}.component: no saved card {card_key!r}")
                    continue
                ct = get_component_type(card.type)
                if ct is None or not ct.single_value:
                    problems.append(f"{where}.component: {card_key!r} isn't a one-number card (a single stat)")
                    continue
                if not card.metric:
                    problems.append(
                        f"{where}.component: {card_key!r} filters a dataset of its own; a goal judges a metric, "
                        "so save its filter as a metric first"
                    )
                    continue
                if not _visible_to_owner(card.owner_id, owner_id):
                    problems.append(f"{where}.component: {personal_problem(card_key, 'card', owner_id)}")
                    continue
                clean["component"] = card.key
            for key, limit in (("label", 120), ("note", MAX_NOTE)):
                value = goal.get(key)
                if value in (None, ""):
                    continue
                if not isinstance(value, str) or len(value) > limit:
                    problems.append(f"{where}.{key}: text, at most {limit} characters")
                else:
                    clean[key] = value
            rule_errors = rule_problems(goal.get("target"), f"{where}.target")
            if goal.get("warn") not in (None, "", {}):
                rule_errors += rule_problems(goal.get("warn"), f"{where}.warn")
                if not rule_errors:
                    rule_errors += _warn_problems(goal["target"], goal["warn"], f"{where}.warn")
            if rule_errors:
                problems.extend(rule_errors)
                continue
            clean["target"] = {"op": goal["target"]["op"], "value": goal["target"]["value"]}
            if goal.get("warn") not in (None, "", {}):
                clean["warn"] = {"op": goal["warn"]["op"], "value": goal["warn"]["value"]}
            own_targets, target_errors = _clean_cadence_targets(goal.get("targets"), where)
            if target_errors:
                problems.extend(target_errors)
                continue
            if own_targets:
                clean["targets"] = own_targets
            period = goal.get("period")
            if period not in (None, ""):
                if not isinstance(period, str) or not (period == "all" or is_period(period)):
                    problems.append(f"{where}.period: {period!r} is not a known period")
                    continue
                # Judged with no way to narrow it, an all-time total would be
                # scored against what the author meant as a weekly target.
                source = metrics.get(metric_key) if metric_key else None
                if period != "all" and source is not None and not source.period_field:
                    problems.append(
                        f"{where}.period: {source.key!r} has no period field, so it can't be judged over "
                        f"{period}; give the metric a period_field or drop this period"
                    )
                    continue
                clean["period"] = period
            clean_goals.append(clean)
        out.append({"title": title, "goals": clean_goals})
    return out, problems


def _warn_problems(target: dict[str, Any], warn: dict[str, Any], where: str) -> list[str]:
    """The at-risk line is an easier target: a value that misses the target but meets
    this reads at risk. Pointing the other way, or harder than the target, it scores
    a bad number better than a good one, so it's refused."""
    up, down = {">", ">="}, {"<", "<="}
    aims = target.get("op"), warn.get("op")
    if not all(op in up | down for op in aims) or not (_is_number(target["value"]) and _is_number(warn["value"])):
        return []
    same_way = (aims[0] in up) == (aims[1] in up)
    aim, line = float(target["value"]), float(warn["value"])
    easier = line <= aim if aims[0] in up else line >= aim
    if same_way and easier:
        return []
    example = "target < 1 with at-risk < 2" if aims[0] in down else "target >= 90 with at-risk >= 85"
    return [
        f"{where}: the at-risk line is an easier target, reached when the real one is missed. It has to point "
        f"the same way as the target and be easier to meet, like {example}"
    ]


def _clean_cadence_targets(raw: Any, where: str) -> tuple[dict[str, Any], list[str]]:
    """A goal's ``targets``: ``{"hourly": {"target": rule, "warn"?: rule}, …}``."""
    if raw in (None, "", {}):
        return {}, []
    if not isinstance(raw, dict):
        return {}, [f"{where}.targets: an object of cadence to its target"]
    clean: dict[str, Any] = {}
    problems: list[str] = []
    for cadence, entry in raw.items():
        at = f"{where}.targets.{cadence}"
        if cadence not in CADENCE_KEYS:
            problems.append(f"{at}: use one of {', '.join(CADENCE_KEYS)}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"{at}: an object with a target")
            continue
        problems += rule_problems(entry.get("target"), f"{at}.target")
        has_warn = entry.get("warn") not in (None, "", {})
        if has_warn:
            problems += rule_problems(entry.get("warn"), f"{at}.warn")
        if not problems:
            clean[cadence] = {"target": {"op": entry["target"]["op"], "value": entry["target"]["value"]}}
            if has_warn:
                clean[cadence]["warn"] = {"op": entry["warn"]["op"], "value": entry["warn"]["value"]}
    return clean, problems


# -- judging ----------------------------------------------------------------------


def scales_with_time(metric: Optional["Metric"]) -> bool:
    """Whether a longer period makes *metric* bigger: a count or a sum does, so a
    weekly target says nothing about one hour. An average, a rate, a latest reading
    or a number that doesn't depend on time reads on the same scale at any length."""
    if metric is None or not metric.period_field or metric.is_rate:
        return False
    if (metric.agg or "count") not in ("count", "distinct", "sum"):
        return False
    from apps.datasets.core import get_dataset

    ds = get_dataset(metric.dataset)
    return ds is None or metric.measure not in ds.declared_measures()


def goal_at(goal: dict[str, Any], cadence: str, metric: Optional["Metric"]) -> dict[str, Any]:
    """*goal* with the target that applies at *cadence*: its own for that cadence;
    else the main one for a week (what it has always meant), or for a number on the
    same scale at any length. Otherwise ``target`` is None: not judged, because
    calling every hour "missed" against a weekly target would be false."""
    own = (goal.get("targets") or {}).get(cadence)
    if own:
        return {**goal, "target": own["target"], "warn": own.get("warn")}
    if cadence == "weekly" or not scales_with_time(metric):
        return goal
    return {**goal, "target": None, "warn": None}


def _meets(value: Any, rule: Optional[dict[str, Any]]) -> bool:
    return bool(rule) and state_for(value, [{**(rule or {}), "state": "success"}]) == "success"


def judge(value: Any, target: dict[str, Any], warn: Optional[dict[str, Any]] = None) -> str:
    """``pass`` when *value* meets *target*, ``warn`` when it meets only
    *warn*, ``fail`` when it meets neither, ``none`` when it isn't a number."""
    if not _is_number(value):
        return "none"
    if _meets(value, target):
        return "pass"
    if warn and _meets(value, warn):
        return "warn"
    return "fail"


def rule_text(rule: Optional[dict[str, Any]], fmt: str = "number", unit: str = "") -> str:
    """A rule in words, in the value's own format: "≥ 95.0%", "1,000–2,000 ms"."""
    if not rule:
        return ""
    trail = display_unit(fmt, unit)
    tail = f" {trail}" if trail else ""
    value = rule.get("value")
    if rule.get("op") == "between" and isinstance(value, list) and len(value) == 2:
        return f"{format_value(value[0], fmt, unit)}–{format_value(value[1], fmt, unit)}{tail}"
    op = str(rule.get("op"))
    return f"{_SYMBOLS.get(op, op)} {format_value(value, fmt, unit)}{tail}"


def gap_text(value: Any, target: dict[str, Any], fmt: str = "number", unit: str = "") -> str:
    """How far a missed value is from its target: "4 short", "12 over",
    "3 outside" — "" when it's on target or the distance means nothing."""
    if not _is_number(value) or _meets(value, target):
        return ""
    op, goal = target.get("op"), target.get("value")
    num = float(value)  # a number: _is_number above
    trail = display_unit(fmt, unit)
    tail = f" {trail}" if trail else ""
    if op in (">", ">=") and goal is not None and _is_number(goal):
        return f"{format_value(float(goal) - num, fmt, unit)}{tail} short"
    if op in ("<", "<=") and goal is not None and _is_number(goal):
        return f"{format_value(num - float(goal), fmt, unit)}{tail} over"
    if op == "between" and isinstance(goal, list) and len(goal) == 2:
        lo, hi = float(goal[0]), float(goal[1])
        return f"{format_value(lo - num if num < lo else num - hi, fmt, unit)}{tail} outside"
    return ""


_NEGATE = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "=": "!=", "!=": "="}


def suggest_target(metric: "Metric") -> dict[str, Any]:
    """A starting target (and at-risk line) for a new goal on *metric*, read
    off its colour rules: the first *success* rule is the target. When the
    rules have a warning band, the at-risk line is "short of the first
    *danger* rule" — colour rules are first-match, so a warning rule alone
    ("≥ 300") would also cover the danger values above it. ``{}`` when the
    metric has no success rule."""
    rules = [
        r
        for r in (metric.thresholds if isinstance(metric.thresholds, list) else [])
        if isinstance(r, dict) and not rule_problems({"op": r.get("op"), "value": r.get("value")}, "x")
    ]
    target = next((r for r in rules if r.get("state") == "success"), None)
    if target is None:
        return {}
    out: dict[str, Any] = {"target": {"op": target["op"], "value": target["value"]}}
    danger = next((r for r in rules if r.get("state") == "danger" and r["op"] in _NEGATE), None)
    if danger is not None and any(r.get("state") == "warning" for r in rules):
        out["warn"] = {"op": _NEGATE[danger["op"]], "value": danger["value"]}
    return out


# -- evaluating -------------------------------------------------------------------


def _source(goal: dict[str, Any], metrics: dict[str, "Metric"], cards: dict[str, "Component"]) -> tuple[Any, Any]:
    """``(metric, card)`` behind a goal — the card's metric for a card goal."""
    if goal.get("component"):
        card = cards.get(goal["component"])
        return (metrics.get(card.metric) if card is not None else None), card
    return metrics.get(goal.get("metric") or ""), None


def source_description(metric: Optional["Metric"], card: Optional["Component"]) -> str:
    """What a goal's number means, in its author's words: the card's description,
    else its metric's ("" when neither has one)."""
    if card is not None and card.description:
        return card.description
    return metric.description if metric is not None else ""


def goal_source(goal: dict[str, Any], metrics: dict[str, "Metric"], cards: dict[str, "Component"]) -> dict[str, Any]:
    """What a goal draws: ``{metric, card, label, description, fmt, unit}`` — a card goal
    takes the card's metric, name, number format and unit (``metric`` is
    ``None`` when it's gone)."""
    from .components import card_style

    metric, card = _source(goal, metrics, cards)
    fmt, unit = (metric.format, metric.unit) if metric is not None else ("number", "")
    if card is not None:
        style = card_style(card.as_cell())
        fmt, unit = style.get("format") or fmt, style.get("unit") or unit
    label = goal.get("label") or (card.name if card is not None else (metric.name if metric else ""))
    return {
        "metric": metric,
        "card": card,
        "label": label or goal.get("metric") or goal.get("component") or "",
        "description": source_description(metric, card),
        "fmt": fmt,
        "unit": unit,
    }


def goal_lookups(goal_list: "GoalList") -> tuple[dict[str, "Metric"], dict[str, "Component"]]:
    """The metrics and saved cards a list's goals draw, fetched once."""
    return _lookups(goal_list)


def evaluate_goal(
    goal: dict[str, Any],
    request: HttpRequest,
    *,
    period: Optional[str],
    metrics: dict[str, "Metric"],
    cards: dict[str, "Component"],
    compare: bool = True,
    trend: bool = False,
) -> dict[str, Any]:
    """One goal as the viewer sees it: ``{id, label, note, status,
    status_label, state, display, unit, value, target_text, warn_text,
    gap_text, comparison, drill, url, period, period_label, error,
    restricted}``. *period* is the list's; the goal's own wins."""
    from .comparison import compare_with_previous
    from .components import card_style, with_drill
    from .metrics import evaluate
    from .periods import period_heading

    metric, card = _source(goal, metrics, cards)
    own = goal.get("period")
    chosen = None if own == "all" else (own or period)
    row: dict[str, Any] = {
        "id": goal.get("id", ""),
        "goal": goal,
        "label": goal.get("label") or (card.name if card is not None else (metric.name if metric else "")),
        "note": goal.get("note", ""),
        "description": source_description(metric, card),
        "source": "component" if goal.get("component") else "metric",
        "key": goal.get("component") or goal.get("metric") or "",
        "status": "none",
        "display": "—",
        "unit": "",
        "value": None,
        "comparison": None,
        "drill": None,
        "url": "",
        "error": "",
        "restricted": False,
        "trend": None,
        "own_period": bool(own),
        "period": chosen,
        "period_label": period_heading(chosen),
    }
    if metric is None:
        row["label"] = row["label"] or row["key"]
        row["error"] = "Its metric or card no longer exists. Edit the goals to remove it."
        row.update(_status_fields("none"), target_text=rule_text(goal.get("target")), warn_text="", gap_text="")
        return row
    fmt, unit = metric.format, metric.unit
    drill_cell: dict[str, Any] = {}
    if card is not None:
        style = card_style(card.as_cell())
        fmt, unit = style.get("format") or fmt, style.get("unit") or unit
        drill_cell = card.as_cell()
    result = evaluate(metric, request, period=chosen)
    row["url"] = metric.get_absolute_url() + (f"?period={result.period}" if result.period else "")
    row["period_label"] = period_heading(result.period) if metric.period_field else "All time"
    if result.restricted:
        row["restricted"] = True
        row["error"] = "You don't have access to this metric's data."
    elif result.error:
        row["error"] = result.error
    else:
        row["value"] = result.value
        row["display"] = format_value(result.value, fmt, unit)
        row["unit"] = display_unit(fmt, unit)
        row["status"] = judge(result.value, goal["target"], goal.get("warn"))
        base = reverse("dashboards_metric_rows", kwargs={"key": metric.key})
        url = f"{base}?period={result.period}" if result.period else base
        where = f", {row['period_label'].lower()}" if result.period else ""
        row["drill"] = {"url": with_drill(url, drill_cell) if drill_cell else url, "title": f"{row['label']}{where}"}
        if compare:
            row["comparison"] = compare_with_previous(metric, request, result.period, result)
        if trend:
            row["trend"] = goal_trend(metric, goal, request, period=chosen, fmt=fmt, unit=unit)
    row.update(_status_fields(row["status"]))
    row["target_text"] = rule_text(goal.get("target"), fmt, unit)
    row["warn_text"] = rule_text(goal.get("warn"), fmt, unit)
    row["gap_text"] = gap_text(row["value"], goal["target"], fmt, unit) if row["status"] != "none" else ""
    return row


#: How many periods a goal's trend shows, and the bucket each list period trends by.
TREND_POINTS = 6
_TREND_GRAIN = {
    "today": "day",
    "yesterday": "day",
    "wtd": "week",
    "pwtd": "week",
    "last_7": "week",
    "qtd": "quarter",
    "pqtr": "quarter",
    "last_90": "quarter",
    "ytd": "year",
    "prev_year": "year",
}
_TREND_SPAN_DAYS = {
    "day": 6,
    "week": 7 * TREND_POINTS,
    "month": 31 * TREND_POINTS,
    "quarter": 92 * TREND_POINTS,
    "year": 366 * TREND_POINTS,
}
_GRAIN_WORDS = {
    "day": ("day", "days"),
    "week": ("week", "weeks"),
    "month": ("month", "months"),
    "quarter": ("quarter", "quarters"),
    "year": ("year", "years"),
}


def trend_grain(period: Optional[str]) -> str:
    """The bucket a goal judged over *period* trends by: weeks for a weekly
    period, quarters for a quarterly one, months otherwise (all time too)."""
    return _TREND_GRAIN.get(period or "", "month")


def goal_trend(
    metric: "Metric",
    goal: dict[str, Any],
    request: HttpRequest,
    *,
    period: Optional[str],
    fmt: str,
    unit: str,
) -> Optional[dict[str, Any]]:
    """The goal over its last :data:`TREND_POINTS` periods, each judged
    against its target: ``{grain, points: [{label, display, status, partial,
    height}], streak, streak_status}`` — ``streak`` is "Missed 3 weeks running" when the
    latest finished periods share a status. One series query
    (``trends.metric_trend``); ``None`` for a metric without a period field or
    one the viewer can't read."""
    from .trends import metric_trend

    if not metric.period_field:
        return None
    grain = trend_grain(period)
    series = metric_trend(metric, request, f"last_{_TREND_SPAN_DAYS[grain]}", grain)
    if not series["ok"] or not series["points"]:
        return None
    raw = series["points"][-TREND_POINTS:]
    numbers = [abs(float(p["value"])) for p in raw if _is_number(p["value"])]
    top = max(numbers) if numbers else 0
    points = []
    for p in raw:
        value = p["value"]
        status = judge(value, goal["target"], goal.get("warn"))
        points.append(
            {
                "label": p["label"],
                "display": format_value(value, fmt, unit) if value is not None else "—",
                "status": status,
                "status_label": STATUS_LABELS[status],
                "partial": p["partial"],
                # Bar height as a share of the largest value shown (a sliver for zero).
                "height": max(8, round(abs(float(value)) * 100 / top)) if top and _is_number(value) else 8,
            }
        )
    finished = [p["status"] for p in points if not p["partial"]]
    streak, streak_status = "", ""
    if finished and finished[-1] in ("pass", "warn", "fail"):
        run = 0
        for status in reversed(finished):
            if status != finished[-1]:
                break
            run += 1
        if run >= 2:
            word = _GRAIN_WORDS[grain][1]
            streak, streak_status = f"{STATUS_LABELS[finished[-1]]} {run} {word} running", finished[-1]
    return {"grain": grain, "points": points, "streak": streak, "streak_status": streak_status}


def _status_fields(status: str) -> dict[str, str]:
    return {"status": status, "status_label": STATUS_LABELS[status], "state": STATUS_STATES[status]}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts by status, the share on target (of the goals with a number),
    a headline ("7 of 9 on target") and the bar's segments."""
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_LABELS}
    scored = len(rows) - counts["none"]
    pct = round(counts["pass"] * 100 / scored) if scored else None
    if not rows:
        headline = "No goals yet"
    elif not scored:
        unjudged = any(r.get("value") is not None and r.get("status") == "none" for r in rows)
        headline = "No targets for this period" if unjudged else "No numbers yet"
    else:
        headline = f"{counts['pass']} of {scored} on target"
    return {
        **counts,
        "total": len(rows),
        "scored": scored,
        "pct": pct,
        "headline": headline,
        "segments": [
            {"status": k, "label": STATUS_LABELS[k], "count": counts[k], "share": counts[k] * 100 / len(rows)}
            for k in ("pass", "warn", "fail", "none")
            if rows and counts[k]
        ],
    }


def _lookups(goal_list: "GoalList") -> tuple[dict[str, "Metric"], dict[str, "Component"]]:
    from .models import Component, Metric

    cards = {c.key: c for c in Component.objects.filter(key__in=goal_list.component_keys())}
    keys = goal_list.metric_keys() | {c.metric for c in cards.values() if c.metric}
    return {m.key: m for m in Metric.objects.filter(key__in=keys)}, cards


def evaluate_goals(
    goal_list: "GoalList",
    request: HttpRequest,
    *,
    period: Optional[str] = None,
    compare: bool = True,
    limit: Optional[int] = None,
    trend: bool = False,
) -> dict[str, Any]:
    """The list as the viewer on *request* sees it: ``{sections: [{title,
    rows, summary}], rows, summary, attention}``. *period* is what the goals
    without their own period are judged over (``None`` = all time — pass the
    list's ``default_period`` for its own). *limit* stops after that many
    goals (a dashboard card); the summary then covers only those."""
    metrics, cards = _lookups(goal_list)
    sections: list[dict[str, Any]] = []
    every: list[dict[str, Any]] = []
    for section in goal_list.sections:
        if limit is not None and len(every) >= limit:
            break
        rows = []
        for goal in section.get("goals", []):
            if limit is not None and len(every) >= limit:
                break
            row = evaluate_goal(
                goal, request, period=period, metrics=metrics, cards=cards, compare=compare, trend=trend
            )
            rows.append(row)
            every.append(row)
        sections.append({"title": section.get("title", ""), "rows": rows, "summary": summarize(rows)})
    return {
        "sections": sections,
        "rows": every,
        "summary": summarize(every),
        "attention": [r for r in every if r["status"] in ("fail", "warn")],
        "has_changes": any(r["comparison"] for r in every),
        "has_trends": any(r["trend"] for r in every),
    }


def goals_embed(goal_list: "GoalList", request: HttpRequest, *, period: Optional[str] = None) -> dict[str, Any]:
    """*goal_list* evaluated for showing on any page (a playlist slide, a
    downstream page): :func:`evaluate_goals` plus ``goal_list``, ``period``
    and its ``heading``. *period* defaults to the list's own; ``""`` means all
    time."""
    from .periods import period_heading

    chosen = (goal_list.default_period or None) if period is None else (period or None)
    data = evaluate_goals(goal_list, request, period=chosen, trend=True)
    return {"goal_list": goal_list, "period": chosen, "heading": period_heading(chosen), **data}


#: How the meeting view's headers sort a section: ``?order=`` key.
GOAL_SORTS = ("goal", "status", "value")
_STATUS_RANK = {"fail": 0, "warn": 1, "pass": 2, "none": 3}


def goal_order(raw: Any) -> str:
    """A valid order for a goal list's sections from ``?order=``, else ""
    (the list's own): ``goal`` (A–Z), ``status`` (missed, at risk, on target,
    then no data) or ``value``, ``-`` to flip."""
    order = str(raw or "").strip()
    return order if order.lstrip("-") in GOAL_SORTS else ""


def sort_sections(sections: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """*sections* with each one's rows in *order* (:func:`goal_order`) — rows
    move within their section, never out of it, so the sections a meeting
    reads in stay put. Rows with no number sort last by value either way."""
    if not order:
        return sections
    desc, key = order.startswith("-"), order.lstrip("-")
    out = []
    for section in sections:
        rows = list(section["rows"])
        if key == "goal":
            rows.sort(key=lambda r: str(r["label"]).lower(), reverse=desc)
        elif key == "status":
            rows.sort(key=lambda r: _STATUS_RANK.get(r["status"], 3), reverse=desc)
        else:
            have = [r for r in rows if _is_number(r.get("value"))]
            rest = [r for r in rows if not _is_number(r.get("value"))]
            have.sort(key=lambda r: float(r["value"]), reverse=desc)
            rows = have + rest
        out.append({**section, "rows": rows})
    return out


def goal_sort_links(order: str) -> dict[str, dict[str, str]]:
    """Per sortable header: ``{next, aria_sort}``. Goal starts A–Z, status
    worst first, value largest first; a second click flips it."""
    links = {}
    for key in GOAL_SORTS:
        if order == key:
            links[key] = {"next": f"-{key}", "aria_sort": "ascending"}
        elif order == f"-{key}":
            links[key] = {"next": key, "aria_sort": "descending"}
        else:
            links[key] = {"next": f"-{key}" if key == "value" else key, "aria_sort": "none"}
    return links


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    from datetime import date, datetime
    from decimal import Decimal

    value = row["value"]
    if isinstance(value, (date, datetime)):
        value = value.isoformat()
    elif isinstance(value, Decimal):
        value = float(value)
    goal = row["goal"]
    return {
        "id": row["id"],
        "label": row["label"],
        row["source"]: row["key"],
        "value": value,
        "display": row["display"],
        "unit": row["unit"],
        "status": row["status"],
        "status_label": row["status_label"],
        "target": goal.get("target"),
        "warn": goal.get("warn"),
        "target_text": row["target_text"],
        "warn_text": row["warn_text"],
        "gap_text": row["gap_text"],
        "period": row["period"],
        "period_label": row["period_label"],
        "note": row["note"],
        "change": {"dir": row["comparison"]["dir"], "text": row["comparison"]["text"]} if row["comparison"] else None,
        "error": row["error"] or None,
        "restricted": row["restricted"],
        "trend": (
            {
                "grain": row["trend"]["grain"],
                "streak": row["trend"]["streak"],
                "points": [
                    {k: p[k] for k in ("label", "display", "status", "partial")} for p in row["trend"]["points"]
                ],
            }
            if row.get("trend")
            else None
        ),
    }


def _json_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: summary[k] for k in ("total", "scored", "pass", "warn", "fail", "none", "pct", "headline")}


def goal_values(goal_list: "GoalList", request: HttpRequest, *, period: Optional[str] = None) -> dict[str, Any]:
    """The list evaluated, JSON-safe — what REST and MCP return. *period*
    defaults to the list's own; ``""`` means all time."""
    chosen = period if period is not None else (goal_list.default_period or None)
    data = evaluate_goals(goal_list, request, period=chosen or None, trend=True)
    return {
        "slug": goal_list.slug,
        "name": goal_list.name,
        "url": goal_list.get_absolute_url(),
        "period": chosen or None,
        "summary": _json_summary(data["summary"]),
        "sections": [
            {"title": s["title"], "summary": _json_summary(s["summary"]), "goals": [_json_row(r) for r in s["rows"]]}
            for s in data["sections"]
        ],
    }


# -- editing ----------------------------------------------------------------------


def add_goal(goal_list: "GoalList", goal: dict[str, Any], section: str = "") -> dict[str, Any]:
    """Append *goal* to the section titled *section* (matched ignoring case),
    starting that section at the end when there's none; saves, so the model's
    validation applies. Returns the goal as stored (with its ``id``)."""
    sections = [dict(s, goals=list(s.get("goals", []))) for s in goal_list.sections if isinstance(s, dict)]
    title = (section or "").strip()
    target = next((s for s in sections if (s.get("title") or "").strip().lower() == title.lower()), None)
    if target is None:
        target = {"title": title, "goals": []}
        sections.append(target)
    clean = {k: v for k, v in goal.items() if v not in (None, "", {})}
    clean.pop("id", None)
    target["goals"].append(clean)
    goal_list.sections = sections
    goal_list.save()
    for s in goal_list.sections:
        if (s.get("title") or "").strip().lower() == title.lower() and s["goals"]:
            return dict(s["goals"][-1])
    return clean


def goal_list_choices(user: Any) -> list[dict[str, Any]]:
    """The goal lists *user* may add a goal to, with their section titles."""
    from .models import GoalList

    return [
        {
            "slug": g.slug,
            "name": g.name,
            "shared": g.owner_id is None,
            "sections": [s.get("title", "") for s in g.sections if isinstance(s, dict)],
        }
        for g in GoalList.objects.editable_by(user).order_by("name")
    ]
