"""Self-diagnostic for the REST API surface.

Run ``python manage.py api_doctor`` after a fresh install or any time
Swagger / ReDoc / a customer's curl returns something surprising. Each
section prints PASS / WARN / FAIL with an actionable hint.

Mirrors ``apps.mcp.management.commands.mcp_doctor`` so the diagnostic
muscle memory is the same for both protocols.
"""

from __future__ import annotations

import json as jsonlib
import sys
import time
from io import StringIO

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.urls import NoReverseMatch, get_resolver, reverse

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class Command(BaseCommand):
    help = "Diagnose the REST API surface end-to-end."

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
        parser.add_argument(
            "--explain",
            nargs="?",
            const="__ALL__",
            default=None,
            metavar="ENDPOINT",
            help=(
                "Dump every registered API endpoint with its methods + URL "
                "name. Pass an endpoint URL path to filter. Composes with "
                "--json."
            ),
        )

    def handle(self, *args, **options):
        if options.get("explain") is not None:
            self._explain(options["explain"], as_json=options.get("json", False))
            return

        report: list[dict] = []
        self._check_openapi_package(report)
        self._check_dependencies(report)
        self._check_registry(report)
        self._check_urls(report)
        self._check_swagger_redoc(report)
        self._check_openapi_validity(report)
        self._check_endpoint_consistency(report)
        self._check_orphans(report)
        self._check_token_auth(report)
        if not options.get("no_self_test"):
            self._self_test(report)

        if options.get("json"):
            self.stdout.write(jsonlib.dumps(report, indent=2, default=str))
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

    # ---- --explain --------------------------------------------------------

    def _explain(self, endpoint_filter: str, *, as_json: bool) -> None:
        """Dump the API registry — what URL names exist, which model, which methods."""
        from apps.smallstack.api import _api_registry

        rows: list[dict] = []
        for crud_config, list_url_name in _api_registry:
            try:
                list_url = reverse(list_url_name)
            except NoReverseMatch:
                list_url = None
            actions = [a.value for a in getattr(crud_config, "actions", [])]
            rows.append(
                {
                    "model": crud_config.model.__name__,
                    "list_url_name": list_url_name,
                    "list_url": list_url,
                    "actions": actions,
                    "filter_fields": list(getattr(crud_config, "filter_fields", []) or []),
                    "search_fields": list(getattr(crud_config, "search_fields", []) or []),
                    "ordering_fields": list(getattr(crud_config, "ordering_fields", []) or []),
                }
            )

        if endpoint_filter != "__ALL__":
            rows = [r for r in rows if r["list_url"] and endpoint_filter in r["list_url"]]
            if not rows:
                self.stdout.write(self.style.ERROR(f"No endpoint matches {endpoint_filter!r}"))
                sys.exit(1)

        if as_json:
            self.stdout.write(jsonlib.dumps(rows, indent=2, default=str))
            return

        if not rows:
            self.stdout.write("(no endpoints registered)")
            return

        for r in rows:
            self.stdout.write(self.style.MIGRATE_HEADING(r["model"]))
            self.stdout.write(f"  list_url     : {r['list_url']}")
            self.stdout.write(f"  url_name     : {r['list_url_name']}")
            self.stdout.write(f"  actions      : {', '.join(r['actions']) or '(none)'}")
            self.stdout.write(f"  filters      : {', '.join(r['filter_fields']) or '(none)'}")
            self.stdout.write(f"  search       : {', '.join(r['search_fields']) or '(none)'}")
            self.stdout.write(f"  ordering     : {', '.join(r['ordering_fields']) or '(none)'}")
            self.stdout.write("")

    # ---- checks -----------------------------------------------------------

    def _check_openapi_package(self, report):
        try:
            import importlib.metadata as md

            import openapi_spec_validator  # noqa: F401

            try:
                version = md.version("openapi-spec-validator")
            except Exception:
                version = "(unknown)"
            report.append(
                {
                    "name": "openapi-spec-validator",
                    "status": "PASS",
                    "detail": f"openapi-spec-validator=={version}",
                }
            )
        except Exception as exc:
            report.append(
                {
                    "name": "openapi-spec-validator",
                    "status": "FAIL",
                    "detail": f"{exc} — pip install openapi-spec-validator",
                }
            )

    def _check_dependencies(self, report):
        """Check installed-apps prerequisites that the admin pages rely on."""
        installed = set(settings.INSTALLED_APPS)
        required = {"apps.smallstack": "REST surface lives here"}
        optional = {
            "apps.activity": "Activity page + threat heuristics need RequestLog",
            "axes": "Axes lockouts are the highest-signal threat indicator",
        }
        missing_required = [k for k in required if k not in installed]
        missing_optional = [k for k in optional if k not in installed]
        if missing_required:
            report.append(
                {
                    "name": "Installed apps",
                    "status": "FAIL",
                    "detail": {f"missing: {k}": v for k, v in required.items() if k in missing_required},
                }
            )
            return
        status = "WARN" if missing_optional else "PASS"
        detail: dict[str, str] = {}
        for k in required:
            detail[k] = "OK"
        for k in optional:
            detail[k] = "OK" if k in installed else f"NOT INSTALLED — {optional[k]}"
        report.append({"name": "Installed apps", "status": status, "detail": detail})

    def _check_registry(self, report):
        from apps.smallstack.api import _api_registry

        entry: dict = {
            "name": "API registry",
            "status": "PASS",
            "detail": f"{len(_api_registry)} CRUDView(s) with enable_api=True",
            "endpoints": [c.model.__name__ for c, _ in _api_registry][:20],
        }
        if not _api_registry:
            entry["status"] = "WARN"
            entry["detail"] = (
                "0 CRUDViews have enable_api=True. Swagger will be empty. "
                "Add `enable_api = True` to a CRUDView subclass, or check that "
                "the CRUDView is reachable via INSTALLED_APPS (see orphans check)."
            )
        report.append(entry)

    def _check_urls(self, report):
        wanted = [
            "api-schema",
            "api-openapi-schema",
            "api-docs",
            "api-redoc",
            "api-auth-token",
            "api-auth-me",
        ]
        resolver = get_resolver()
        resolved: dict[str, str] = {}
        missing: list[str] = []
        for name in wanted:
            try:
                url = reverse(name)
                resolver.resolve(url)
                resolved[name] = url
            except (NoReverseMatch, Exception):
                missing.append(name)
        if missing:
            report.append({"name": "URL conf", "status": "FAIL", "detail": {"missing": missing}})
        else:
            report.append({"name": "URL conf", "status": "PASS", "detail": resolved})

    def _check_swagger_redoc(self, report):
        """Both shells must return 200 and include their CDN script tag."""
        client = Client()
        try:
            swag = client.get("/api/docs/", HTTP_HOST="localhost")
            redoc = client.get("/api/redoc/", HTTP_HOST="localhost")
        except Exception as exc:
            report.append({"name": "Swagger / ReDoc shells", "status": "FAIL", "detail": str(exc)})
            return
        swag_ok = swag.status_code == 200 and b"swagger" in swag.content.lower()
        redoc_ok = redoc.status_code == 200 and b"redoc" in redoc.content.lower()
        detail = {
            "/api/docs/": f"{swag.status_code} swagger-tag={swag_ok}",
            "/api/redoc/": f"{redoc.status_code} redoc-tag={redoc_ok}",
        }
        status = "PASS" if (swag_ok and redoc_ok) else "FAIL"
        report.append({"name": "Swagger / ReDoc shells", "status": status, "detail": detail})

    def _check_openapi_validity(self, report):
        """Build the spec and validate it against OpenAPI 3.0.3."""
        try:
            from openapi_spec_validator import validate
            from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

            from apps.smallstack.api import _api_registry
            from apps.smallstack.openapi import build_openapi_spec
        except Exception as exc:
            report.append({"name": "OpenAPI validity", "status": "FAIL", "detail": str(exc)})
            return
        try:
            spec = build_openapi_spec(_api_registry, server_url="http://localhost/")
        except Exception as exc:
            report.append({"name": "OpenAPI validity", "status": "FAIL", "detail": f"builder error: {exc}"})
            return
        try:
            validate(spec)
        except OpenAPIValidationError as exc:
            report.append({"name": "OpenAPI validity", "status": "FAIL", "detail": str(exc)})
            return
        report.append(
            {
                "name": "OpenAPI validity",
                "status": "PASS",
                "detail": {
                    "openapi": spec.get("openapi"),
                    "title": spec.get("info", {}).get("title"),
                    "operations": sum(
                        sum(1 for k in ops if k in {"get", "post", "put", "delete", "patch"})
                        for ops in spec.get("paths", {}).values()
                    ),
                    "schemas": len(spec.get("components", {}).get("schemas", {})),
                },
            }
        )

    def _check_endpoint_consistency(self, report):
        """Every entry in _api_registry must resolve to a real list URL."""
        from apps.smallstack.api import _api_registry

        broken: list[str] = []
        for crud_config, list_url_name in _api_registry:
            try:
                reverse(list_url_name)
            except NoReverseMatch:
                broken.append(f"{crud_config.model.__name__}: {list_url_name}")
        if broken:
            report.append(
                {
                    "name": "Endpoint consistency",
                    "status": "FAIL",
                    "detail": {"unresolvable": broken},
                }
            )
        else:
            report.append(
                {
                    "name": "Endpoint consistency",
                    "status": "PASS",
                    "detail": f"all {len(_api_registry)} list URLs resolve",
                }
            )

    def _check_orphans(self, report):
        """Files with enable_api = True that aren't in the live registry."""
        unregistered = self._find_unregistered_optins()
        if not unregistered:
            report.append(
                {
                    "name": "Orphan files",
                    "status": "PASS",
                    "detail": "no orphaned enable_api opt-ins",
                }
            )
            return
        preview = ", ".join(unregistered[:3]) + ("…" if len(unregistered) > 3 else "")
        report.append(
            {
                "name": "Orphan files",
                "status": "WARN",
                "detail": (
                    f"{len(unregistered)} file(s) declare `enable_api = True` but "
                    f"aren't in the registry: {preview}. The CRUDView's module "
                    f"isn't being imported at startup — add `from . import "
                    f"<module>` to that app's AppConfig.ready()."
                ),
                "orphans": unregistered,
            }
        )

    def _find_unregistered_optins(self) -> list[str]:
        """Display paths of .py files whose enable_api=True CRUDViews
        aren't registered (compared against the source files of every
        registered CRUDView in _api_registry)."""
        import inspect
        from pathlib import Path

        from apps.smallstack.api import _api_registry

        scanned = self._scan_for_enable_api_optins()
        if not scanned:
            return []
        registered_paths: set[Path] = set()
        for crud_config, _ in _api_registry:
            try:
                registered_paths.add(Path(inspect.getfile(crud_config)).resolve())
            except (TypeError, OSError):
                continue
        return sorted(
            display
            for absolute, display in scanned
            if absolute.resolve() not in registered_paths
        )

    def _scan_for_enable_api_optins(self) -> list[tuple]:
        """Match `enable_api = True` only as a class-attribute assignment
        (start of line + optional indent). Avoids matching prefixed names
        like `explorer_enable_api` and substrings in comments/docstrings."""
        import re
        from pathlib import Path

        from django.apps import apps as django_apps

        marker = re.compile(r"^\s*enable_api\s*=\s*True\b", re.MULTILINE)
        hits: list[tuple] = []
        for app_config in django_apps.get_app_configs():
            # Skip our own app — its files reference the marker in code
            # that detects opt-ins, not as actual opt-ins.
            if app_config.label == "api_admin_app":
                continue
            try:
                app_path = Path(app_config.path)
            except Exception:
                continue
            for py_file in app_path.rglob("*.py"):
                parts = py_file.parts
                if "tests" in parts or "migrations" in parts or "management" in parts:
                    continue
                try:
                    if marker.search(py_file.read_text(encoding="utf-8", errors="ignore")):
                        try:
                            display = str(py_file.relative_to(app_path.parent))
                        except ValueError:
                            display = str(py_file)
                        hits.append((py_file, display))
                except OSError:
                    continue
        return sorted(hits, key=lambda t: t[1])

    def _check_token_auth(self, report):
        from apps.smallstack.models import APIToken

        try:
            active = APIToken.objects.filter(is_active=True).count()
            revoked = APIToken.objects.filter(is_active=False).count()
        except Exception as exc:
            report.append({"name": "APIToken model", "status": "FAIL", "detail": str(exc)})
            return
        report.append(
            {
                "name": "APIToken inventory",
                "status": "PASS",
                "detail": f"{active} active, {revoked} revoked",
            }
        )

    def _self_test(self, report):
        """Mint a temp readonly token, hit a few endpoints, revoke."""
        from django.contrib.auth import get_user_model

        from apps.smallstack.api import _api_registry
        from apps.smallstack.models import APIToken

        User = get_user_model()
        user = User.objects.filter(is_staff=True).first() or User.objects.first()
        if user is None:
            report.append(
                {"name": "Self-test", "status": "WARN", "detail": "No users exist; skipping."}
            )
            return
        token, raw_key = APIToken.create_token(
            user=user,
            name=f"api_doctor self-test {int(time.time())}",
            token_type="manual",
            access_level="readonly",
        )
        try:
            client = Client()
            headers = {"HTTP_AUTHORIZATION": f"Bearer {raw_key}", "HTTP_HOST": "localhost"}
            schema = client.get("/api/schema/", **headers)
            ok_schema = schema.status_code == 200 and isinstance(schema.json(), dict)
            openapi = client.get("/api/schema/openapi.json", **headers)
            ok_openapi = openapi.status_code == 200 and openapi.json().get("openapi", "").startswith("3.0")

            ok_sample: bool | None = None
            sample_url: str | None = None
            if _api_registry:
                try:
                    crud_config, list_url_name = _api_registry[0]
                    sample_url = reverse(list_url_name)
                    sep = "&" if "?" in sample_url else "?"
                    sample = client.get(f"{sample_url}{sep}limit=1", **headers)
                    ok_sample = sample.status_code in (200, 401, 403)
                except Exception:
                    ok_sample = False

            checks: dict[str, object] = {
                "GET /api/schema/": ok_schema,
                "GET /api/schema/openapi.json": ok_openapi,
            }
            if sample_url is not None:
                checks[f"GET {sample_url}"] = ok_sample
            else:
                checks["sample endpoint"] = "skipped (registry empty)"

            all_ok = ok_schema and ok_openapi and (ok_sample is not False)
            report.append(
                {
                    "name": "Self-test",
                    "status": "PASS" if all_ok else "FAIL",
                    "detail": checks,
                }
            )
        finally:
            token.delete()

    # ---- output -----------------------------------------------------------

    def _print_human(self, report):
        self.stdout.write(self.style.MIGRATE_HEADING("SmallStack API — Doctor"))
        self.stdout.write("=" * 30)
        for row in report:
            mark = {"PASS": f"{GREEN}✓{RESET}", "WARN": f"{YELLOW}!{RESET}", "FAIL": f"{RED}✗{RESET}"}[
                row["status"]
            ]
            self.stdout.write(f"[{mark}] {row['name']:<24} {self._fmt_detail(row.get('detail', ''))}")
            if "endpoints" in row and row["endpoints"]:
                preview = ", ".join(row["endpoints"])
                if len(row["endpoints"]) > 8:
                    preview = ", ".join(row["endpoints"][:8]) + f"… (+{len(row['endpoints']) - 8} more)"
                self.stdout.write(f"             {preview}")
            if "orphans" in row and row["orphans"]:
                for o in row["orphans"][:5]:
                    self.stdout.write(f"             - {o}")
                if len(row["orphans"]) > 5:
                    self.stdout.write(f"             … (+{len(row['orphans']) - 5} more)")

    def _fmt_detail(self, detail):
        if isinstance(detail, dict):
            buf = StringIO()
            for k, v in detail.items():
                buf.write(f"\n             {k:<28} = {v}")
            return buf.getvalue()
        return str(detail)
