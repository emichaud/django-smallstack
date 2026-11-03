"""This period against the one before — the one comparison every surface shows.

- :func:`compare_with_previous` — a metric's change from the previous period,
  for the metric page, dashboard cards, lists, ``metric_value`` (MCP) and the
  REST value route
- :func:`compare_groups` — the same, per group, for a grouped card
- :func:`delta` — two results → ``{dir, text}``; the report compares its own
  columns with it

Neutral on purpose: whether up is good depends on the metric, so the result
carries a direction, never a good/bad state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest

from .metrics import MetricResult, evaluate, group_value_map
from .periods import PREVIOUS_PERIOD, comparison_target

if TYPE_CHECKING:
    from .models import Metric


def delta(current: Optional[MetricResult], previous: Optional[MetricResult], against: str) -> dict[str, Any] | None:
    """The change from *previous* to *current* as ``{dir, text}`` — ``dir`` is
    ``up`` / ``down`` / ``flat`` — or None when either side has no number."""
    if current is None or previous is None or not (current.ok and previous.ok):
        return None
    a, b = current.value, previous.value
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or isinstance(a, bool):
        return None
    if a == b:
        return {"dir": "flat", "text": f"No change vs {against}"}
    if b == 0:
        return {"dir": "up", "text": f"Up from 0 in {against}"}
    pct = (a - b) / abs(b) * 100
    shown = f"{abs(pct):.0f}%" if abs(pct) >= 1 else f"{abs(pct):.1f}%"
    return {"dir": "up" if pct > 0 else "down", "text": f"{shown} vs {against}"}


def compare_with_previous(
    metric: "Metric", request: HttpRequest, period: Optional[str], result: Optional[MetricResult]
) -> dict[str, Any] | None:
    """*metric*'s change from the period before *period* — ``{dir, text,
    previous, unit}`` (``previous`` is the earlier value, formatted) or None.

    None for a period without a natural predecessor (all time, a rolling
    window), a metric without a period field, or a *result* that didn't
    evaluate. Costs one more evaluation."""
    prev_key = PREVIOUS_PERIOD.get(period or "")
    if not prev_key or not metric.period_field or result is None or not result.ok:
        return None
    prev_result = evaluate(metric, request, period=prev_key)
    change = delta(result, prev_result, comparison_target(period, prev_key))
    if not change:
        return None
    return {**change, "previous": prev_result.display, "unit": prev_result.unit}


def compare_groups(
    groups: list[dict[str, Any]], metric: "Metric", request: HttpRequest, period: Optional[str], dimension: str
) -> None:
    """Set ``g["change"] = {dir, short, text}`` on each of :func:`metrics.group_values`'
    *groups* — the group against the same group in the previous period (when
    *period* has one). ``short`` fits beside a group: "12%", "new", "same".

    "Other" is skipped: its membership is "everything not shown", which isn't
    the same set last period."""
    prev_key = PREVIOUS_PERIOD.get(period or "")
    if not prev_key or not metric.period_field or not groups:
        return
    previous = group_value_map(metric, request, dimension, prev_key)
    against = comparison_target(period, prev_key)
    for g in groups:
        if g.get("other"):
            continue
        change = delta(
            MetricResult(value=g.get("value"), display=""),
            MetricResult(value=previous.get(g.get("raw"), 0), display=""),
            against,
        )
        if change:
            if change["text"].startswith("Up from 0"):
                short = "new"
            elif change["dir"] == "flat":
                short = "same"
            else:
                short = change["text"].split(" vs ")[0]
            g["change"] = {"dir": change["dir"], "short": short, "text": change["text"]}
