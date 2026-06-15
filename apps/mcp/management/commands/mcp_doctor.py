"""Self-diagnostic for the MCP server.

Run `python manage.py mcp_doctor` after a fresh install or any time
Claude.ai's Connectors UI fails to attach. Each section prints PASS / WARN
/ FAIL with an actionable hint.
"""

from __future__ import annotations

import json as jsonlib
import sys
from io import StringIO

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import URLResolver, get_resolver

from apps.mcp.server import TOOL_REGISTRY
from apps.smallstack.models import APIToken


GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class Command(BaseCommand):
    help = "Diagnose the MCP server end-to-end."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-self-test",
            action="store_true",
            help="Skip the test-client smoke check.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emit machine-readable JSON to stdout.",
        )
        parser.add_argument(
            "--check-only",
            action="store_true",
            help="Exit non-zero on any FAIL.",
        )

    def handle(self, *args, **options):
        report: list[dict] = []
        self._check_mcp_package(report)
        self._check_settings(report)
        self._check_registry(report)
        self._check_urls(report)
        self._check_tokens(report)
        self._check_apitoken_admin(report)
        if not options.get("no_self_test"):
            self._self_test(report)

        if options.get("json"):
            self.stdout.write(jsonlib.dumps(report, indent=2))
        else:
            self._print_human(report)

        fail_count = sum(1 for c in report if c["status"] == "FAIL")
        warn_count = sum(1 for c in report if c["status"] == "WARN")
        if options.get("check_only") and fail_count:
            sys.exit(1)
        if not options.get("json"):
            self.stdout.write("")
            self.stdout.write(
                f"Summary: {len(report) - fail_count - warn_count} ✓ / "
                f"{warn_count} ⚠ / {fail_count} ✗"
            )

    # ---- checks -----------------------------------------------------------

    def _check_mcp_package(self, report):
        try:
            import importlib
            import importlib.metadata as md

            importlib.import_module("mcp.server.lowlevel")
            version = md.version("mcp")
            report.append({"name": "mcp package", "status": "PASS", "detail": f"mcp=={version}"})
        except Exception as exc:
            report.append({"name": "mcp package", "status": "FAIL", "detail": str(exc)})

    def _check_settings(self, report):
        keys = [
            "MCP_SERVER_NAME",
            "MCP_SERVER_VERSION",
            "MCP_BASE_TEMPLATE",
            "MCP_TOKEN_NAME_PREFIX",
            "MCP_SUPPORTED_PROTOCOL_VERSIONS",
            "MCP_ENABLE_OAUTH",
            "MCP_VERBOSE_LOGGING",
            "MCP_OAUTH_CODE_TTL_SECONDS",
        ]
        kv = {k: getattr(settings, k, None) for k in keys}
        missing = [k for k, v in kv.items() if v is None]
        if missing:
            report.append(
                {
                    "name": "Settings",
                    "status": "FAIL",
                    "detail": f"Missing: {missing}",
                }
            )
        else:
            report.append({"name": "Settings", "status": "PASS", "detail": kv})

    def _check_registry(self, report):
        names = sorted(TOOL_REGISTRY.keys())
        entry: dict = {
            "name": "Server registry",
            "status": "PASS",
            "detail": f"{len(names)} tools registered",
            "tools": names[:20],
        }
        # If the registry is empty but the tree contains `enable_mcp = True`
        # somewhere, that's almost certainly the import-ordering footgun —
        # downgrade to WARN with the fix.
        if not names:
            orphans = self._scan_for_enable_mcp_optins()
            if orphans:
                preview = ", ".join(orphans[:3]) + ("…" if len(orphans) > 3 else "")
                entry["status"] = "WARN"
                entry["detail"] = (
                    f"Registry empty but found `enable_mcp = True` in {len(orphans)} file(s): {preview}. "
                    "Likely cause: the file isn't imported during app startup. "
                    "Verify MCP_AUTODISCOVER is True (default), or add "
                    "`from . import views` to that app's AppConfig.ready()."
                )
                entry["orphans"] = orphans
        report.append(entry)

    def _scan_for_enable_mcp_optins(self) -> list[str]:
        """Return repo-relative paths of .py files containing the literal
        ``enable_mcp = True`` outside tests/migrations. Used to warn the
        operator when the registry is empty but they almost certainly
        meant to register tools."""
        from pathlib import Path

        from django.apps import apps as django_apps

        marker = "enable_mcp = True"
        hits: list[str] = []
        for app_config in django_apps.get_app_configs():
            if app_config.label == "mcp_server":
                continue
            try:
                app_path = Path(app_config.path)
            except Exception:
                continue
            for py_file in app_path.rglob("*.py"):
                parts = py_file.parts
                if "tests" in parts or "migrations" in parts:
                    continue
                try:
                    if marker in py_file.read_text(encoding="utf-8", errors="ignore"):
                        try:
                            hits.append(str(py_file.relative_to(app_path.parent)))
                        except ValueError:
                            hits.append(str(py_file))
                except OSError:
                    continue
        return sorted(hits)

    def _check_urls(self, report):
        wanted = [
            ("/mcp", False),
            ("/mcp/", False),
            ("/.well-known/oauth-authorization-server", False),
            ("/.well-known/oauth-protected-resource", False),
            ("/mcp/oauth/register", False),
            ("/mcp/oauth/authorize", False),
            ("/mcp/oauth/token", False),
            ("/mcp/oauth/revoke", False),
        ]
        resolved = []
        missing = []
        resolver = get_resolver()
        for path, _ in wanted:
            try:
                resolver.resolve(path)
                resolved.append(path)
            except Exception:
                missing.append(path)
        if missing:
            report.append({"name": "URL conf", "status": "FAIL", "detail": {"missing": missing}})
        else:
            report.append({"name": "URL conf", "status": "PASS", "detail": resolved})

    def _check_tokens(self, report):
        active = APIToken.objects.filter(is_active=True).count()
        revoked = APIToken.objects.filter(is_active=False).count()
        report.append(
            {
                "name": "APIToken inventory",
                "status": "PASS",
                "detail": f"{active} active, {revoked} revoked",
            }
        )

    def _check_apitoken_admin(self, report):
        from django.contrib import admin

        try:
            site_entry = admin.site._registry.get(APIToken)
            if site_entry and getattr(site_entry, "explorer_enabled", False):
                report.append(
                    {"name": "APIToken admin", "status": "PASS", "detail": "explorer_enabled=True"}
                )
            else:
                report.append(
                    {
                        "name": "APIToken admin",
                        "status": "WARN",
                        "detail": "Add explorer_enabled=True to APITokenAdmin so users can manage tokens via Explorer.",
                    }
                )
        except Exception as exc:
            report.append({"name": "APIToken admin", "status": "FAIL", "detail": str(exc)})

    def _self_test(self, report):
        """Mint a temp readonly token, run a few JSON-RPC calls, clean up."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(is_staff=True).first() or User.objects.first()
        if user is None:
            report.append(
                {
                    "name": "Self-test",
                    "status": "WARN",
                    "detail": "No users exist; skipping self-test.",
                }
            )
            return
        token, raw_key = APIToken.create_token(
            user=user,
            name="mcp_doctor self-test",
            token_type="manual",
            access_level="readonly",
        )
        try:
            client = Client()
            headers = {
                "HTTP_AUTHORIZATION": f"Bearer {raw_key}",
                "HTTP_HOST": "localhost",
            }
            tl = client.post(
                "/mcp",
                data='{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                content_type="application/json",
                **headers,
            )
            ok_tl = tl.status_code == 200 and "result" in tl.json()
            ping = client.post(
                "/mcp",
                data='{"jsonrpc":"2.0","id":2,"method":"ping"}',
                content_type="application/json",
                **headers,
            )
            ok_ping = ping.status_code == 200
            notif = client.post(
                "/mcp",
                data='{"jsonrpc":"2.0","method":"notifications/initialized"}',
                content_type="application/json",
                **headers,
            )
            ok_notif = notif.status_code == 202 and not notif.content
            report.append(
                {
                    "name": "Self-test",
                    "status": "PASS" if (ok_tl and ok_ping and ok_notif) else "FAIL",
                    "detail": {
                        "tools/list": ok_tl,
                        "ping": ok_ping,
                        "notifications/initialized 202+empty": ok_notif,
                    },
                }
            )
        finally:
            token.delete()

    # ---- output -----------------------------------------------------------

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("SmallStack MCP — Doctor"))
        self.stdout.write("=" * 30)
        for row in report:
            mark = {"PASS": f"{GREEN}✓{RESET}", "WARN": f"{YELLOW}!{RESET}", "FAIL": f"{RED}✗{RESET}"}[
                row["status"]
            ]
            self.stdout.write(f"[{mark}] {row['name']:<22} {self._fmt_detail(row.get('detail', ''))}")
            if "tools" in row and row["tools"]:
                preview = ", ".join(row["tools"])
                if len(row["tools"]) > 8:
                    preview = ", ".join(row["tools"][:8]) + f"… (+{len(row['tools']) - 8} more)"
                self.stdout.write(f"           {preview}")

    def _fmt_detail(self, detail):
        if isinstance(detail, dict):
            buf = StringIO()
            for k, v in detail.items():
                buf.write(f"\n           {k:<28} = {v}")
            return buf.getvalue()
        return str(detail)
