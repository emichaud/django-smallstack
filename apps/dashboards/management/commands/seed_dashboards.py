"""Seed a working demo: the framework's own defaults (``dashboard_defaults.DEMO``),
metrics over the bundled datasets and a rate made from two of them, a "Site
health" dashboard and a "Monthly KPIs" report, every one shared.

Re-running is safe: it creates what's missing and updates what nobody has
changed since, the way every app's defaults sync (``defaults.sync_defaults``).
``--reset`` deletes the demo rows first, and so puts back any you deleted;
``--adopt`` takes over demo rows seeded before defaults existed.

    uv run python manage.py seed_dashboards
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ...dashboard_defaults import DEMO
from ...defaults import KIND_BY_NAME, sync_defaults
from ...models import Dashboard, Metric, Report


class Command(BaseCommand):
    help = "Seed demo metrics, a 'Site health' dashboard and a 'Monthly KPIs' report (shared)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--reset", action="store_true", help="Delete the demo rows first.")
        parser.add_argument(
            "--adopt", action="store_true", help="Take over demo rows seeded before defaults existed (overwrites them)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["reset"]:
            Dashboard.objects.filter(slug__in=[d["slug"] for d in DEMO.dashboards]).delete()
            Report.objects.filter(slug__in=[r["slug"] for r in DEMO.reports]).delete()
            Metric.objects.filter(key__in=[m["key"] for m in DEMO.metrics]).delete()
        report = sync_defaults([DEMO.app], restore=options["reset"], adopt=options["adopt"])
        for app, kind, key, outcome, detail in report.lines:
            if outcome in ("error", "conflict", "customised"):
                line = f"{KIND_BY_NAME[kind].name} {key}: {outcome}"
                self.stdout.write(self.style.WARNING(line) + (f" — {detail}" if detail else ""))
        self.stdout.write(
            self.style.SUCCESS(
                f"{report.count('created')} created, {report.count('adopted')} adopted, "
                f"{report.count('updated')} updated, "
                f"{report.count('current')} already current: dashboard /smallstack/dashboards/d/site-health/, "
                "report /smallstack/dashboards/r/monthly-kpis/"
            )
        )
