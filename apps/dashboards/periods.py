"""Period vocabulary and wording — the one place a period becomes words.

The keys themselves (``mtd``, ``last_30``…) and their date ranges belong to
``apps.datasets.dateranges``; this module adds what the dashboards layer says
about them, so every surface (pages, REST, MCP, a downstream UI) words a
period and a comparison the same way:

- :func:`period_phrase` — the tail of a sentence: "in the last 30 days",
  "this month so far"
- :func:`period_heading` — a heading in sentence case: "This month so far"
- :data:`PREVIOUS_PERIOD` / :data:`TO_DATE_PERIODS` — what a period compares
  with, and whether it's still running (so the comparison says "all of")

No database access here; :func:`requested_period` is the one function that
reads a request, and only its query string.
"""

from __future__ import annotations

from typing import Optional

from django.http import HttpRequest

from apps.datasets.dateranges import RELATIVE_PERIODS, is_period, period_label

#: A period's natural predecessor — what a comparison measures it against.
#: Rolling windows (``last_30``) have none, nor do closed periods other than last
#: week, the one a weekly meeting reads.
PREVIOUS_PERIOD: dict[str, str] = {
    "today": "yesterday",
    "wtd": "pwtd",
    "pwtd": "ppwtd",
    "mtd": "pmtd",
    "this_month": "pmtd",
    "qtd": "pqtr",
    "ytd": "prev_year",
    "this_year": "prev_year",
}

#: Periods with days still to come, so they are partial against a whole
#: period. ``this_month``/``this_year`` reach past today, but those days are
#: empty: an early month read as a collapse against all of last month.
TO_DATE_PERIODS = frozenset({"today", "wtd", "mtd", "qtd", "ytd", "this_month", "this_year"})

#: The periods a metric or dashboard page offers as one-click links; the rest
#: of ``RELATIVE_PERIODS`` sit in a "More" select.
QUICK_PERIODS: list[tuple[str, str]] = [
    ("all", "All time"),
    ("today", "Today"),
    ("wtd", "This week"),
    ("pwtd", "Last week"),
    ("last_7", "7 days"),
    ("last_30", "30 days"),
    ("mtd", "This month"),
    ("pmtd", "Last month"),
    ("qtd", "This quarter"),
    ("ytd", "This year"),
]

#: The shorter set for lists and the rows modal, where space is tight.
SHORT_PERIODS: list[tuple[str, str]] = [
    ("all", "All time"),
    ("today", "Today"),
    ("wtd", "This week"),
    ("pwtd", "Last week"),
    ("last_7", "7 days"),
    ("last_30", "30 days"),
    ("mtd", "This month"),
    ("ytd", "This year"),
]

_PHRASES = {
    "wtd": "this week so far",
    "pwtd": "last week",
    "ppwtd": "the week before",
    "mtd": "this month so far",
    "this_month": "this month",
    "pmtd": "last month",
    "qtd": "this quarter so far",
    "pqtr": "last quarter",
    "ytd": "this year so far",
    "this_year": "this year",
    "prev_year": "last year",
}


def requested_period(request: HttpRequest, default: str = "") -> Optional[str]:
    """``?period=`` (``all`` = none), else *default*. Unknown keys fall back to
    *default* — a period is a narrowing, so a typo must not silently mean "all
    time"; it means "what the author chose"."""
    raw = request.GET.get("period")
    if raw is None:
        return default or None
    if raw in ("", "all"):
        return None
    return raw if is_period(raw) else (default or None)


#: Said alongside a number when a period was asked for and can't apply.
NO_PERIOD_FIELD_NOTE = "This metric has no period_field, so the period was ignored: this is its all-time value."


def period_problem(raw: object) -> Optional[str]:
    """Why *raw* can't be used as a period, or None when it can (``""`` / ``all``
    mean no period). For callers who asked for a period by name and must hear
    about a typo: REST and MCP. A page falls back quietly (:func:`requested_period`);
    an agent reading a number can't see that it got all time instead of this week."""
    if raw in (None, "", "all") or is_period(raw):
        return None
    keys = ", ".join(k for k, _label in RELATIVE_PERIODS)
    return f"unknown period {raw!r} — use 'all', one of {keys}, or last_<N> / next_<N> days"


def period_choices(extra: Optional[str] = None) -> list[tuple[str, str]]:
    """``[("all", "All time"), *RELATIVE_PERIODS]``, plus *extra* if it isn't
    among them (so a select can show the period a page is on)."""
    choices = [("all", "All time"), *RELATIVE_PERIODS]
    if extra and extra not in dict(choices):
        choices.append((extra, period_label(extra)))
    return choices


def period_phrase(key: str) -> str:
    """A period as the tail of a sentence: "in the last 30 days", "last month",
    "this month so far"."""
    if key in _PHRASES:
        return _PHRASES[key]
    label = period_label(key)
    if key.startswith(("last_", "next_")):
        return f"in the {label.lower()}"
    return label.lower()


def period_heading(key: Optional[str]) -> str:
    """A period as a heading in sentence case: "This month so far", "Last 30
    days"; no period is "All time"."""
    if not key:
        return "All time"
    phrase = period_phrase(key)
    if phrase.startswith("in the "):
        phrase = phrase[len("in the ") :]
    return phrase[:1].upper() + phrase[1:]


def comparison_target(period: Optional[str], previous: str) -> str:
    """How a comparison names the period it's against: "last month", or "all
    of last month" when *period* is still running (partial against complete —
    without it a quiet first day reads as a collapse)."""
    phrase = period_phrase(previous)
    return f"all of {phrase}" if period in TO_DATE_PERIODS else phrase


def join_words(items: list[str]) -> str:
    """``["a", "b", "c"]`` → "a, b and c"."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def plain_reading(summary: str) -> str:
    """A filter summary in prose case ("… AND …" → "… and …")."""
    return summary.replace(" AND ", " and ").replace(" OR ", " or ")
