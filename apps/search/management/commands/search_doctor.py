"""Self-diagnostic for the search subsystem.

Mirrors api_doctor / mcp_doctor: each check appends to a shared report
list with PASS / WARN / FAIL plus actionable hints. Run after enabling
search on a model or any time results look surprising.
"""

from __future__ import annotations

import json as jsonlib
import sys
from io import StringIO

from django.core.management.base import BaseCommand

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class Command(BaseCommand):
    help = "Diagnose the search subsystem end-to-end."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output.")
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Exit non-zero if any check FAILs (for CI).",
        )
        parser.add_argument(
            "--explain",
            action="store_true",
            help="Dump every indexed model + its search_fields + the MCP tool name.",
        )

    def handle(self, *args, **options):
        if options.get("explain"):
            self._explain(as_json=options.get("json", False))
            return

        report: list[dict] = []
        self._check_backend(report)
        self._check_registry(report)
        self._check_mcp_integration(report)
        self._check_urls(report)
        self._check_index_health(report)

        if options.get("json"):
            self.stdout.write(jsonlib.dumps(report, indent=2, default=str))
        else:
            self._print_human(report)

        fail_count = sum(1 for r in report if r["status"] == "FAIL")
        warn_count = sum(1 for r in report if r["status"] == "WARN")
        if options.get("check_only") and fail_count:
            sys.exit(1)
        if not options.get("json"):
            self.stdout.write("")
            self.stdout.write(
                f"Summary: {len(report) - fail_count - warn_count} ✓ / "
                f"{warn_count} ⚠ / {fail_count} ✗"
            )

    # ---- checks ---------------------------------------------------------

    def _check_backend(self, report):
        try:
            from apps.search.backends import get_backend

            backend = get_backend()
        except Exception as exc:
            report.append({"name": "Search backend", "status": "FAIL", "detail": str(exc)})
            return

        is_native = "fts" in backend.name or "postgres" in backend.name
        report.append({
            "name": "Search backend",
            "status": "PASS" if is_native else "WARN",
            "detail": (
                f"Selected: {backend.name}"
                + ("" if is_native else " — degrades at scale; use SQLite or Postgres")
            ),
        })

    def _check_registry(self, report):
        try:
            from apps.search.registry import all_views, view_count
        except Exception as exc:
            report.append({"name": "Search registry", "status": "FAIL", "detail": str(exc)})
            return

        n = view_count()
        models = [v.model_label for v in all_views()]
        if n == 0:
            report.append({
                "name": "Search registry",
                "status": "WARN",
                "detail": (
                    "0 CRUDViews have enable_search=True yet. Add enable_search=True "
                    "to a CRUDView subclass and set search_fields to start indexing."
                ),
                "models": [],
            })
            return
        report.append({
            "name": "Search registry",
            "status": "PASS",
            "detail": f"{n} CRUDView(s) registered",
            "models": models,
        })

    def _check_mcp_integration(self, report):
        try:
            from apps.mcp.server import TOOL_REGISTRY  # noqa: F401
        except Exception:
            report.append({
                "name": "MCP integration",
                "status": "WARN",
                "detail": "apps.mcp not installed — search MCP tools skipped",
            })
            return

        from apps.mcp.server import TOOL_REGISTRY

        search_tools = sorted(t for t in TOOL_REGISTRY if t.startswith("search_"))
        if not search_tools:
            report.append({
                "name": "MCP integration",
                "status": "WARN",
                "detail": "No search MCP tools registered (no indexed CRUDViews yet)",
            })
            return
        report.append({
            "name": "MCP integration",
            "status": "PASS",
            "detail": f"{len(search_tools)} MCP search tool(s)",
            "tools": search_tools,
        })

    def _check_urls(self, report):
        from django.urls import reverse

        try:
            reverse("search:page")
            reverse("search:omnibar")
        except Exception as exc:
            report.append({"name": "URL conf", "status": "FAIL", "detail": str(exc)})
            return
        report.append({
            "name": "URL conf",
            "status": "PASS",
            "detail": "/smallstack/search/ + omnibar reachable",
        })

    def _check_index_health(self, report):
        """Spot-check one indexed view: can we issue a query without error?"""
        from apps.search.backends import get_backend
        from apps.search.registry import all_views

        views = list(all_views())
        if not views:
            return
        backend = get_backend()
        for view in views[:1]:
            try:
                backend.query(view, "smoke-test-query-zz", limit=1)
            except Exception as exc:
                report.append({
                    "name": f"Index health ({view.model_label})",
                    "status": "FAIL",
                    "detail": f"Query failed: {exc}. Try `manage.py rebuild_search_index --all`.",
                })
                return
        report.append({
            "name": "Index health",
            "status": "PASS",
            "detail": f"Spot-checked {views[0].model_label} — query returned",
        })

    # ---- --explain ------------------------------------------------------

    def _explain(self, *, as_json: bool):
        from apps.search.registry import all_views

        rows: list[dict] = []
        for view in all_views():
            tool_plural = str(view.model._meta.verbose_name_plural).lower().replace(" ", "_")
            rows.append({
                "model": view.model_label,
                "verbose": view.model_verbose,
                "fields": view.fields,
                "weights": view.weights,
                "display": view.display_field,
                "subtitle": view.subtitle_field,
                "mcp_tool": f"search_{tool_plural}",
            })
        if as_json:
            self.stdout.write(jsonlib.dumps(rows, indent=2, default=str))
            return
        if not rows:
            self.stdout.write("(no models registered)")
            return
        for r in rows:
            self.stdout.write(self.style.MIGRATE_HEADING(r["model"]))
            self.stdout.write(f"  fields    : {', '.join(r['fields'])}")
            self.stdout.write(f"  weights   : {r['weights'] or '(default 1.0 per field)'}")
            self.stdout.write(f"  display   : {r['display'] or '(str(obj))'}")
            self.stdout.write(f"  subtitle  : {r['subtitle'] or '(none)'}")
            self.stdout.write(f"  mcp tool  : {r['mcp_tool']}")
            self.stdout.write("")

    # ---- output ---------------------------------------------------------

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("SmallStack Search — Doctor"))
        self.stdout.write("=" * 30)
        for row in report:
            mark = {"PASS": f"{GREEN}✓{RESET}", "WARN": f"{YELLOW}!{RESET}", "FAIL": f"{RED}✗{RESET}"}[
                row["status"]
            ]
            self.stdout.write(f"[{mark}] {row['name']:<28} {self._fmt(row.get('detail', ''))}")
            for key in ("models", "tools"):
                if key in row and row[key]:
                    preview = ", ".join(row[key][:5])
                    if len(row[key]) > 5:
                        preview += f"… (+{len(row[key]) - 5} more)"
                    self.stdout.write(f"             {preview}")

    def _fmt(self, detail):
        if isinstance(detail, dict):
            buf = StringIO()
            for k, v in detail.items():
                buf.write(f"\n             {k:<24} = {v}")
            return buf.getvalue()
        return str(detail)
