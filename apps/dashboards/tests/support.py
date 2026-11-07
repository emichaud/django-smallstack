"""Shared helpers for the dashboards tests."""

from __future__ import annotations

import json
from typing import Any

from apps.dashboards.models import Metric


def own(metric_key: str) -> dict[str, Any]:
    """A card's own source, copied from a saved metric: what a split or a
    chart takes in place of ``metric``, since those filter a dataset of their
    own. Unpack it into a cell or a ``Component(...)``."""
    m = Metric.objects.get(key=metric_key)
    return {
        "dataset": m.dataset,
        "filter_tree": m.filter_tree or {},
        "agg": m.agg,
        "measure": m.measure,
        "period_field": m.period_field,
    }


def own_post(metric_key: str) -> dict[str, str]:
    """The same, as the builder's form posts it: the filter as JSON text, and
    ``metric`` blank (an omitted field would keep a saved card's old value)."""
    source = own(metric_key)
    return {
        **{k: str(v) for k, v in source.items() if k != "filter_tree"},
        "filter_tree": json.dumps(source["filter_tree"]),
        "metric": "",
    }
