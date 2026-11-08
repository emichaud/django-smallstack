"""The framework's own defaults: the demo (``manage.py seed_dashboards``).

A working example of an app's ``dashboard_defaults.py`` (see ``defaults.py`` and
``docs/skills/app-defaults.md``): metrics over the bundled datasets, a rate made
from two of them, a "Site health" dashboard and a "Monthly KPIs" report, all
shared. ``auto=False`` keeps it out of the after-migrate sync, so a project gets
the demo only when it asks for it; ``prefix=""`` because its addresses predate the
prefix rule.
"""

from __future__ import annotations

from typing import Any

from .defaults import Defaults, register_defaults

METRICS: list[dict[str, Any]] = [
    {
        "key": "demo_requests",
        "name": "Requests",
        "description": "Every logged HTTP request.",
        "dataset": "smallstack_requests",
        "period_field": "timestamp",
        "format": "compact",
    },
    {
        "key": "demo_server_errors",
        "name": "Server errors",
        "description": "Requests that answered 5xx.",
        "dataset": "smallstack_requests",
        "filter_tree": {"field": "status_code", "op": ">=", "value": 500},
        "period_field": "timestamp",
        "thresholds": [{"op": ">", "value": 0, "state": "danger"}, {"op": "=", "value": 0, "state": "success"}],
    },
    {
        "key": "demo_client_errors",
        "name": "Client errors (4xx)",
        "description": "Requests that answered 4xx — excluding 404s, which are mostly scanners.",
        "dataset": "smallstack_requests",
        "filter_tree": {
            "and": [
                {"field": "status_code", "op": "between", "value": 400, "value2": 499},
                {"field": "status_code", "op": "!=", "value": 404},
            ]
        },
        "period_field": "timestamp",
        "thresholds": [{"op": ">=", "value": 50, "state": "warning"}],
    },
    {
        "key": "demo_avg_latency",
        "name": "Average latency",
        "description": "Mean response time of successful requests.",
        "dataset": "smallstack_requests",
        "filter_tree": {"field": "status_code", "op": "<", "value": 400},
        "agg": "avg",
        "measure": "response_time_ms",
        "period_field": "timestamp",
        "format": "number",
        "unit": "ms",
        "thresholds": [
            {"op": ">=", "value": 800, "state": "danger"},
            {"op": ">=", "value": 300, "state": "warning"},
            {"op": "<", "value": 300, "state": "success"},
        ],
    },
    {
        "key": "demo_writes",
        "name": "Write requests",
        "description": "POST, PUT, PATCH and DELETE requests.",
        "dataset": "smallstack_requests",
        "filter_tree": {"field": "method", "op": "in", "value": ["POST", "PUT", "PATCH", "DELETE"]},
        "period_field": "timestamp",
    },
    {
        "key": "demo_api_traffic",
        "name": "API & MCP traffic",
        "description": "Requests to the REST API or the MCP endpoint.",
        "dataset": "smallstack_requests",
        "filter_tree": {
            "or": [
                {"field": "path", "op": "contains", "value": "/api/"},
                {"field": "path", "op": "contains", "value": "/mcp"},
            ]
        },
        "period_field": "timestamp",
    },
    {
        "key": "demo_failed_checks",
        "name": "Failed health checks",
        "description": "Heartbeat checks that came back down, outside maintenance windows.",
        "dataset": "smallstack_heartbeats",
        "filter_tree": {
            "and": [
                {"field": "status", "op": "=", "value": "fail"},
                {"field": "maintenance", "op": "=", "value": False},
            ]
        },
        "period_field": "timestamp",
        "thresholds": [{"op": ">", "value": 0, "state": "danger"}, {"op": "=", "value": 0, "state": "success"}],
    },
    {
        "key": "demo_pending_approvals",
        "name": "Pending approvals",
        "description": "Approval requests waiting on a human.",
        "dataset": "smallstack_approval_requests",
        "filter_tree": {"field": "status", "op": "=", "value": "pending"},
        "thresholds": [{"op": ">=", "value": 5, "state": "warning"}],
    },
]

#: Rates divide two of the metrics above, so they're seeded after them, and only
#: when both parts were.
RATES: list[dict[str, Any]] = [
    {
        "key": "demo_server_error_rate",
        "name": "Server error rate",
        "description": "The share of requests that answered 5xx: server errors ÷ requests, over the same period.",
        "source": "rate",
        "numerator": "demo_server_errors",
        "denominator": "demo_requests",
        "format": "percent",
        "thresholds": [
            {"op": ">", "value": 1, "state": "danger"},
            {"op": ">", "value": 0.5, "state": "warning"},
            {"op": "<=", "value": 0.5, "state": "success"},
        ],
    },
]

#: A grouped card filters a dataset of its own (a metric suits a one-number card):
#: the same definition as demo_requests.
REQUESTS_SOURCE: dict[str, Any] = {
    "dataset": "smallstack_requests",
    "filter_tree": {},
    "agg": "count",
    "measure": "",
    "period_field": "timestamp",
}

LAYOUT: list[dict[str, Any]] = [
    {
        "id": "intro",
        "type": "text",
        "x": 0,
        "y": 0,
        "w": 12,
        "h": 1,
        "options": {
            "markdown": (
                "**Site health** — every card is a saved metric. "
                "Change the period above; click a number to see its rows."
            )
        },
    },
    {"id": "requests", "type": "metric", "metric": "demo_requests", "x": 0, "y": 1, "w": 3, "h": 2},
    {"id": "errors5xx", "type": "metric", "metric": "demo_server_errors", "x": 3, "y": 1, "w": 3, "h": 2},
    {"id": "errors4xx", "type": "metric", "metric": "demo_client_errors", "x": 6, "y": 1, "w": 3, "h": 2},
    {"id": "latency", "type": "metric", "metric": "demo_avg_latency", "x": 9, "y": 1, "w": 3, "h": 2},
    {
        "id": "by_method",
        "type": "metric_group",
        **REQUESTS_SOURCE,
        "title": "Requests by method",
        "x": 0,
        "y": 3,
        "w": 6,
        "h": 2,
        "options": {"dimension": "method", "limit": 5, "other": True, "style": {"format": "compact"}},
    },
    {
        "id": "by_status",
        "type": "metric_group",
        **REQUESTS_SOURCE,
        "title": "Requests by status",
        "x": 6,
        "y": 3,
        "w": 6,
        "h": 2,
        "options": {"dimension": "status_code", "limit": 6, "other": True, "style": {"format": "compact"}},
    },
    {"id": "api", "type": "metric", "metric": "demo_api_traffic", "x": 0, "y": 5, "w": 4, "h": 2},
    {"id": "checks", "type": "metric", "metric": "demo_failed_checks", "x": 4, "y": 5, "w": 4, "h": 2},
    {
        "id": "approvals",
        "type": "metric",
        "metric": "demo_pending_approvals",
        "x": 8,
        "y": 5,
        "w": 4,
        "h": 2,
        "use_period": False,
    },
]


DEMO = Defaults(
    app="smallstack_dashboards",
    prefix="",
    auto=False,
    metrics=METRICS + RATES,
    dashboards=[
        {
            "slug": "site-health",
            "name": "Site health",
            "description": "Traffic, errors, latency and health checks, built from saved metrics.",
            "default_period": "last_7",
            "layout": LAYOUT,
        }
    ],
    reports=[
        {
            "slug": "monthly-kpis",
            "name": "Monthly KPIs",
            "description": "This month against last month and the year so far.",
            "items": [{"metric": m["key"]} for m in METRICS + RATES],
            "periods": ["mtd", "pmtd", "ytd"],
        }
    ],
)

register_defaults(DEMO)
