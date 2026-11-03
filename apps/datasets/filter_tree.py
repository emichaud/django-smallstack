"""The filter tree — a stored, nested AND/OR filter over a dataset.

The flat ``filters={name: value}`` map is AND-only and query-param shaped; it
stays the right tool for a URL. A **filter tree** is the stored form: a small
JSON document a builder UI, an AI agent or a hand-edited text field produces,
saved on a metric/dashboard and compiled to a Django ``Q`` every time the value
is needed::

    {"and": [
        {"field": "status", "op": "=", "value": "open"},
        {"or": [
            {"field": "priority", "op": "in", "value": ["high", "urgent"]},
            {"field": "age_days", "op": ">", "value": 30}
        ]},
        {"field": "created_at", "op": "period", "value": "mtd"}
    ]}

Nodes are a branch (``{"and": [...]}`` / ``{"or": [...]}``, plus ``{"not": node}``)
or a leaf ``{"field", "op", "value", "value2"?}``. ``{}`` / ``None`` means "no
filter". Ops (``OPS``) are symbols with a few word aliases (``ALIASES``); the
operators a column offers depend on its type (``ops_for_type``), and
``period`` resolves a relative date (``dateranges.py``) at query time.

**Strict, not tolerant.** call_stats' original compiler dropped any leaf it
could not apply ("absent-not-error"). For a stored filter that is the worst
possible failure: a renamed column or a typo removes the condition and the KPI
quietly gets *bigger* — the fail-open shape SmallStack treats as top severity
(v0.21.11). Here every problem raises ``FilterTreeError`` with a path-addressed
message, so a bad filter is rejected when it is saved and surfaces as an error,
never as a wider number, when it is evaluated.

Ported from call_stats ``apps/datasets/core._tree_to_q``; DB-free apart from
building ``Q`` objects.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.db.models import Q

from .dateranges import is_period, period_label, relative_dates

#: Canonical operators. ``=`` / ``!=`` compare exactly; ``contains`` is a
#: case-insensitive substring; ``in`` takes a list; ``between`` takes ``value``
#: and ``value2`` (inclusive low, exclusive high for dates, inclusive for
#: numbers); ``isnull`` takes a boolean; ``period`` a relative-date key.
OPS: tuple[str, ...] = ("=", "!=", ">", ">=", "<", "<=", "between", "in", "contains", "isnull", "period")

#: Word spellings a builder or an agent may emit — normalised before compiling.
ALIASES: dict[str, str] = {
    "eq": "=",
    "==": "=",
    "is": "=",
    "ne": "!=",
    "is not": "!=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "after": ">=",
    "before": "<",
    "icontains": "contains",
    "relative": "period",
}

_CMP_LOOKUP = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}

_DATE_TYPES = frozenset({"date", "datetime"})
_NUMBER_TYPES = frozenset({"integer", "float", "decimal"})

#: Guard rails: a stored tree is user/agent input.
MAX_DEPTH = 8
MAX_LEAVES = 100


class FilterTreeError(ValueError):
    """A filter tree can't be applied as written. ``problems`` lists every
    issue found (path-addressed, e.g. ``and[1].field: unknown field 'stauts'``)
    so a builder or an agent can fix them all in one round trip."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def normalize_op(op: object) -> Optional[str]:
    """The canonical spelling of *op*, or None if it isn't an operator."""
    if not isinstance(op, str):
        return None
    op = op.strip()
    op = ALIASES.get(op.lower(), op)
    return op if op in OPS else None


def ops_for_type(col_type: str) -> list[str]:
    """The operators that make sense for a column type — what a builder offers."""
    if col_type in _DATE_TYPES:
        return ["=", "!=", ">", ">=", "<", "<=", "between", "period", "isnull"]
    if col_type in _NUMBER_TYPES:
        return ["=", "!=", ">", ">=", "<", "<=", "between", "in", "isnull"]
    if col_type == "boolean":
        return ["=", "isnull"]
    if col_type == "fk":
        return ["=", "!=", "in", "isnull"]
    return ["=", "!=", "in", "contains", "isnull"]


def is_empty(tree: object) -> bool:
    """True for "no filter": ``None`` or an empty dict."""
    return tree is None or tree == {}


# -- value coercion -----------------------------------------------------------


class _Bad(Exception):
    """Internal: a value couldn't be coerced (message is the reason)."""


def _coerce(value: Any, col_type: str) -> Any:
    """Coerce one leaf value to the column's Python type (raises ``_Bad``)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _Bad("a value is required (use op 'isnull' to match empty)")
    if col_type in _DATE_TYPES:
        return _coerce_date(value, col_type)
    if col_type == "boolean":
        return _coerce_bool(value)
    if col_type in _NUMBER_TYPES:
        return _coerce_number(value, col_type)
    if col_type == "fk":
        if isinstance(value, bool):
            raise _Bad(f"expected a primary key, got {value!r}")
        if isinstance(value, int):
            return value
        text = str(value).strip()
        return int(text) if text.lstrip("-").isdigit() else text
    if isinstance(value, (dict, list)):
        raise _Bad(f"expected a single value, got {type(value).__name__}")
    return value if isinstance(value, (int, float, bool)) else str(value)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "on"):
        return True
    if text in ("false", "0", "no", "n", "off"):
        return False
    raise _Bad(f"expected true/false, got {value!r}")


def _coerce_number(value: Any, col_type: str) -> Any:
    if isinstance(value, bool):
        raise _Bad(f"expected a number, got {value!r}")
    if isinstance(value, (int, float, Decimal)):
        return value
    text = str(value).strip()
    try:
        if col_type == "decimal":
            return Decimal(text)
        return float(text) if any(c in text for c in ".eE") else int(text)
    except (ValueError, InvalidOperation):
        raise _Bad(f"expected a number, got {value!r}") from None


def _coerce_date(value: Any, col_type: str) -> Any:
    from django.conf import settings
    from django.utils import timezone

    if isinstance(value, datetime):
        parsed: date | datetime = value
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text) if ("T" in text or " " in text) else date.fromisoformat(text)
        except ValueError:
            raise _Bad(f"expected an ISO date/datetime, got {value!r}") from None
    if col_type == "date":
        return parsed.date() if isinstance(parsed, datetime) else parsed
    # datetime column: a bare date means local midnight.
    if not isinstance(parsed, datetime):
        parsed = datetime(parsed.year, parsed.month, parsed.day)
    if settings.USE_TZ and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _period_bounds(key: str, col_type: str, today: Optional[date]) -> tuple[Any, Any]:
    from .dateranges import _local_midnight

    bounds = relative_dates(key, today)
    if bounds is None:  # pragma: no cover — guarded by is_period()
        raise _Bad(f"unknown period {key!r}")
    since, until = bounds
    if col_type == "date":
        return since, until
    return _local_midnight(since), _local_midnight(until)


# -- compile / validate -------------------------------------------------------


class _Compiler:
    def __init__(self, columns: dict[str, str], filterable: set[str], today: Optional[date]) -> None:
        self.columns = columns
        self.filterable = filterable
        self.today = today
        self.problems: list[str] = []
        self.leaves = 0

    def node(self, node: Any, path: str, depth: int) -> Optional[Q]:
        where = path or "filter"
        if depth > MAX_DEPTH:
            self.problems.append(f"{where}: nested deeper than {MAX_DEPTH} levels")
            return None
        if not isinstance(node, dict):
            self.problems.append(f"{where}: expected an object, got {type(node).__name__}")
            return None
        branches = [k for k in ("and", "or", "not") if k in node]
        if len(branches) > 1:
            self.problems.append(f"{where}: a node is one of and/or/not or a leaf, not several")
            return None
        if branches:
            return self.branch(node, branches[0], path, depth)
        return self.leaf(node, where)

    def branch(self, node: dict, joiner: str, path: str, depth: int) -> Optional[Q]:
        prefix = f"{path}." if path else ""
        if joiner == "not":
            inner = self.node(node["not"], f"{prefix}not", depth + 1)
            return None if inner is None else ~inner
        children = node[joiner]
        if not isinstance(children, list) or not children:
            self.problems.append(f"{prefix}{joiner}: must be a non-empty list")
            return None
        parts = [self.node(child, f"{prefix}{joiner}[{i}]", depth + 1) for i, child in enumerate(children)]
        if any(p is None for p in parts):
            return None  # the child already recorded why
        result = parts[0]
        assert result is not None
        for part in parts[1:]:
            assert part is not None
            result = (result & part) if joiner == "and" else (result | part)
        return result

    def leaf(self, node: dict, where: str) -> Optional[Q]:
        self.leaves += 1
        if self.leaves == MAX_LEAVES + 1:
            self.problems.append(f"filter: more than {MAX_LEAVES} conditions")
        if self.leaves > MAX_LEAVES:
            return None
        unknown_keys = set(node) - {"field", "op", "value", "value2"}
        if unknown_keys:
            self.problems.append(f"{where}: unexpected key(s) {sorted(unknown_keys)}")
            return None
        field = node.get("field")
        if not isinstance(field, str) or not field:
            self.problems.append(f"{where}.field: a column name is required")
            return None
        if field not in self.columns:
            self.problems.append(f"{where}.field: unknown field {field!r}")
            return None
        if field not in self.filterable:
            self.problems.append(f"{where}.field: {field!r} is not filterable on this dataset")
            return None
        col_type = self.columns[field]
        op = normalize_op(node.get("op"))
        if op is None:
            self.problems.append(f"{where}.op: unknown operator {node.get('op')!r}; use one of {list(OPS)}")
            return None
        if op not in ops_for_type(col_type):
            self.problems.append(
                f"{where}.op: {op!r} does not apply to {field!r} ({col_type}); use one of {ops_for_type(col_type)}"
            )
            return None
        try:
            return self.condition(field, col_type, op, node.get("value"), node.get("value2"))
        except _Bad as exc:
            self.problems.append(f"{where}.value: {exc}")
            return None

    def condition(self, field: str, col_type: str, op: str, value: Any, value2: Any) -> Q:
        if op == "isnull":
            flag = True if value is None else _coerce_bool(value)
            return Q(**{f"{field}__isnull": flag})
        if op == "period":
            if not is_period(value):
                raise _Bad(f"unknown period {value!r}")
            since, until = _period_bounds(str(value), col_type, self.today)
            return Q(**{f"{field}__gte": since, f"{field}__lt": until})
        if op == "in":
            if not isinstance(value, list) or not value:
                raise _Bad("'in' takes a non-empty list")
            return Q(**{f"{field}__in": [_coerce(v, col_type) for v in value]})
        if op == "contains":
            return Q(**{f"{field}__icontains": str(_coerce(value, col_type))})
        if op == "between":
            lo, hi = _coerce(value, col_type), _coerce(value2, col_type)
            upper = "lt" if col_type in _DATE_TYPES else "lte"
            return Q(**{f"{field}__gte": lo, f"{field}__{upper}": hi})
        coerced = _coerce(value, col_type)
        if op == "=":
            return Q(**{field: coerced})
        if op == "!=":
            return ~Q(**{field: coerced})
        return Q(**{f"{field}__{_CMP_LOOKUP[op]}": coerced})


def compile_filter_tree(
    tree: Any,
    *,
    columns: dict[str, str],
    filterable: set[str],
    today: Optional[date] = None,
) -> Optional[Q]:
    """Compile *tree* to a ``Q`` (``None`` for an empty tree).

    ``columns`` maps column name → schema type (``Dataset.columns()``);
    ``filterable`` is the set of names the dataset allows filtering on.
    Raises :class:`FilterTreeError` listing every problem — never drops a
    condition. ``today`` pins the date ``period`` leaves resolve against
    (default: the local date).
    """
    if is_empty(tree):
        return None
    compiler = _Compiler(columns, filterable, today)
    q = compiler.node(tree, "", 0)
    if compiler.problems:
        raise FilterTreeError(compiler.problems)
    return q


def validate_filter_tree(tree: Any, *, columns: dict[str, str], filterable: set[str]) -> list[str]:
    """Every problem with *tree* as a list of messages (empty = valid)."""
    try:
        compile_filter_tree(tree, columns=columns, filterable=filterable)
    except FilterTreeError as exc:
        return exc.problems
    return []


def and_trees(*trees: Any) -> Any:
    """AND several trees together, skipping empty ones. Returns ``{}`` when all
    are empty, the tree itself when only one isn't."""
    parts: list[Any] = []
    for t in trees:
        if is_empty(t):
            continue
        # Splice a top-level AND in rather than nesting it — same meaning, and
        # the one-line reading stays flat ("A AND B AND C", not "(A AND B) AND C").
        if isinstance(t, dict) and set(t) == {"and"} and isinstance(t["and"], list) and t["and"]:
            parts.extend(t["and"])
        else:
            parts.append(t)
    if not parts:
        return {}
    if len(parts) == 1:
        return parts[0]
    return {"and": parts}


def tree_fields(tree: Any) -> set[str]:
    """Every column name a tree's leaves reference (well-formed parts only)."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for joiner in ("and", "or"):
            if isinstance(node.get(joiner), list):
                for child in node[joiner]:
                    walk(child)
                return
        if "not" in node:
            walk(node["not"])
            return
        if isinstance(node.get("field"), str):
            found.add(node["field"])

    walk(tree)
    return found


# -- the one-line readable form -----------------------------------------------

_OP_WORDS = {
    "=": "=",
    "!=": "≠",
    ">": ">",
    ">=": "≥",
    "<": "<",
    "<=": "≤",
    "contains": "contains",
}


def _fmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        when = _fmt_iso_datetime(value)
        if when is not None:
            return when
        return f"“{value}”" if " " in value else value
    return str(value)


def _fmt_iso_datetime(text: str) -> Optional[str]:
    """An ISO datetime as people read it, in local time: ``2026-10-19``
    at midnight, ``2026-10-19 14:05`` otherwise. None for anything else."""
    if len(text) < 16 or text[4:5] != "-" or "T" not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        from django.utils import timezone

        parsed = timezone.localtime(parsed)
    if (parsed.hour, parsed.minute, parsed.second) == (0, 0, 0):
        return parsed.date().isoformat()
    return parsed.strftime("%Y-%m-%d %H:%M")


def describe_filter_tree(tree: Any, labels: Optional[dict[str, str]] = None) -> str:
    """A one-line human reading of *tree*, e.g.
    ``Status = open AND (Priority in high, urgent OR Age > 30) AND Created: Month to date``.

    Display only — it never needs to parse back. ``labels`` maps column names
    to display labels (falls back to the name). Malformed parts render as
    ``?`` rather than raising, so a broken stored filter can still be shown.
    """
    labels = labels or {}
    if is_empty(tree):
        return "All rows"

    def render(node: Any, top: bool) -> str:
        if not isinstance(node, dict):
            return "?"
        for joiner in ("and", "or"):
            children = node.get(joiner)
            if isinstance(children, list):
                inner = f" {joiner.upper()} ".join(render(c, False) for c in children) or "?"
                return inner if top or len(children) < 2 else f"({inner})"
        if "not" in node:
            return f"NOT {render(node['not'], False)}"
        field = node.get("field")
        name = labels.get(field, field) if isinstance(field, str) else "?"
        op = normalize_op(node.get("op"))
        value = node.get("value")
        if op == "period":
            return f"{name}: {period_label(str(value))}"
        if op == "isnull":
            empty = True if value is None else str(value).lower() not in ("false", "0", "no")
            return f"{name} is {'empty' if empty else 'not empty'}"
        if op == "in":
            items = value if isinstance(value, list) else [value]
            return f"{name} in {', '.join(_fmt_value(v) for v in items)}"
        if op == "between":
            return f"{name} between {_fmt_value(value)} and {_fmt_value(node.get('value2'))}"
        if op is None:
            return f"{name} ? {_fmt_value(value)}"
        return f"{name} {_OP_WORDS.get(op, op)} {_fmt_value(value)}"

    return render(tree, True)
