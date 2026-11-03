"""Seed a working demo: metrics over the bundled framework datasets, a "Site
health" dashboard and a "Monthly KPIs" report — every one shared.

Idempotent: rows are upserted by key/slug, so re-running refreshes them
without duplicating. ``--reset`` deletes the demo rows first.

    uv run python manage.py seed_dashboards
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.datasets.core import get_dataset

from ...models import Dashboard, Metric, Report

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
        "metric": "demo_requests",
        "title": "Requests by method",
        "x": 0,
        "y": 3,
        "w": 6,
        "h": 2,
        "options": {"dimension": "method", "limit": 5, "other": True},
    },
    {
        "id": "by_status",
        "type": "metric_group",
        "metric": "demo_requests",
        "title": "Requests by status",
        "x": 6,
        "y": 3,
        "w": 6,
        "h": 2,
        "options": {"dimension": "status_code", "limit": 6, "other": True},
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


class Command(BaseCommand):
    help = "Seed demo metrics, a 'Site health' dashboard and a 'Monthly KPIs' report (shared)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--reset", action="store_true", help="Delete the demo rows first.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["reset"]:
            Dashboard.objects.filter(slug="site-health").delete()
            Report.objects.filter(slug="monthly-kpis").delete()
            Metric.objects.filter(key__startswith="demo_").delete()

        created_keys: list[str] = []
        for spec in METRICS:
            if get_dataset(spec["dataset"]) is None:
                self.stdout.write(self.style.WARNING(f"skip {spec['key']}: dataset {spec['dataset']} not registered"))
                continue
            defaults = {k: v for k, v in spec.items() if k != "key"}
            defaults.setdefault("filter_tree", {})
            defaults.setdefault("thresholds", [])
            defaults["owner"] = None
            metric = Metric.objects.filter(key=spec["key"]).first() or Metric(key=spec["key"])
            for k, v in defaults.items():
                setattr(metric, k, v)
            metric.save()
            created_keys.append(metric.key)

        layout = [c for c in LAYOUT if not c.get("metric") or c["metric"] in created_keys]
        dashboard = Dashboard.objects.filter(slug="site-health").first() or Dashboard(slug="site-health")
        dashboard.name = "Site health"
        dashboard.description = "Traffic, errors, latency and health checks, built from saved metrics."
        dashboard.default_period = "last_7"
        dashboard.layout = layout
        dashboard.owner = None
        dashboard.save()

        report = Report.objects.filter(slug="monthly-kpis").first() or Report(slug="monthly-kpis")
        report.name = "Monthly KPIs"
        report.description = "This month against last month and the year so far."
        report.items = [{"metric": k} for k in created_keys]
        report.periods = ["mtd", "pmtd", "ytd"]
        report.owner = None
        report.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(created_keys)} metrics, dashboard {dashboard.get_absolute_url()}, "
                f"report {report.get_absolute_url()}"
            )
        )
