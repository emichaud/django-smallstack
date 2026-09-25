"""Self-diagnostic for the webhook surface.

Run ``python manage.py webhook_doctor`` after wiring up endpoints/receivers or
when deliveries aren't arriving. Each section prints PASS / WARN / FAIL with an
actionable hint. Mirrors ``api_doctor`` so the muscle memory matches.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import sys
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

Report = list[dict[str, str]]

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class Command(BaseCommand):
    help = "Diagnose the webhook surface (outbound + inbound)."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        parser.add_argument("--check-only", action="store_true", help="Exit non-zero on any FAIL.")
        parser.add_argument(
            "--explain",
            action="store_true",
            help="List every model wired for outbound webhooks and every inbound handler.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options.get("explain"):
            self._explain(as_json=options.get("json", False))
            return

        if not getattr(settings, "SMALLSTACK_WEBHOOKS_ENABLED", True):
            disabled_report: Report = [{
                "name": "Webhooks enabled",
                "status": "PASS",
                "detail": "Disabled via SMALLSTACK_WEBHOOKS_ENABLED — nothing to diagnose.",
            }]
            self._emit(disabled_report, options)
            return

        from apps.smallstack.doctor_checks import schema_check

        report: Report = []
        schema_problem = schema_check()
        if schema_problem is not None:
            report.append(schema_problem)
        if schema_problem is None or schema_problem["status"] != "FAIL":
            self._check_outbound_registry(report)
            self._check_origin(report)
            self._check_endpoints(report)
            self._check_stuck_retries(report)
            self._check_inbound(report)
        self._emit(report, options)

        if options.get("check_only") and any(c["status"] == "FAIL" for c in report):
            sys.exit(1)

    # -- checks -------------------------------------------------------------

    def _check_outbound_registry(self, report: Report) -> None:
        from apps.smallstack.crud import CRUDView

        models = [
            v.model._meta.label
            for v in CRUDView._registry.values()
            if v.model is not None and getattr(v, "enable_webhooks", False)
        ]
        if not getattr(settings, "SMALLSTACK_WEBHOOKS_OUTBOUND", True):
            report.append({"name": "Outbound", "status": "PASS", "detail": "Outbound disabled via setting."})
            return
        if not models:
            report.append({
                "name": "Outbound registry",
                "status": "WARN",
                "detail": "No CRUDView has enable_webhooks=True — no model change will fire a webhook.",
            })
        else:
            report.append({
                "name": "Outbound registry",
                "status": "PASS",
                "detail": f"{len(models)} model(s) emit events: {', '.join(models)}",
            })

    def _check_origin(self, report: Report) -> None:
        """F-029: warn when the webhook origin can't resolve to an absolute URL, so the
        flagship envelope's resource.url degrades to null and S2S loop-guard dedupe loses
        its base — a silent degradation an operator should see."""
        from apps.webhooks.context import current_origin, origin_is_configured

        if origin_is_configured():
            report.append({
                "name": "Webhook origin",
                "status": "PASS",
                "detail": f"Origin resolves to {current_origin()} — resource.url + dedupe OK.",
            })
        else:
            report.append({
                "name": "Webhook origin",
                "status": "WARN",
                "detail": (
                    f"Webhook origin unresolved (falls back to bare hostname "
                    f"{current_origin()!r}): set SITE_URL or SMALLSTACK_WEBHOOK_ORIGIN, "
                    "else resource.url and S2S loop-guard dedupe degrade."
                ),
            })

    def _check_endpoints(self, report: Report) -> None:
        from apps.webhooks import services
        from apps.webhooks.models import WebhookEndpoint

        endpoints = list(WebhookEndpoint.objects.all())
        active = [e for e in endpoints if e.enabled]
        if not endpoints:
            report.append({"name": "Endpoints", "status": "WARN", "detail": "No endpoints registered."})
            return

        bad_url = []
        no_filter = []
        for e in active:
            ok, reason = services.url_is_allowed(e.target_url)
            if not ok:
                bad_url.append(f"{e.name}: {reason}")
            if not e.event_filter:
                no_filter.append(e.name)
        if bad_url:
            report.append({"name": "Endpoint URLs", "status": "FAIL", "detail": "; ".join(bad_url)})
        else:
            ok_detail = f"{len(active)} active endpoint(s) OK."
            report.append({"name": "Endpoint URLs", "status": "PASS", "detail": ok_detail})
        if no_filter:
            report.append({
                "name": "Endpoint filters",
                "status": "WARN",
                "detail": f"Empty event_filter (inert): {', '.join(no_filter)}",
            })

    def _check_stuck_retries(self, report: Report) -> None:
        from datetime import timedelta

        from apps.webhooks.models import WebhookDelivery

        grace = int(getattr(settings, "SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS", 300))
        stuck = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.RETRYING,
            next_attempt_at__isnull=False,
            next_attempt_at__lt=timezone.now() - timedelta(seconds=grace),
        ).count()
        if stuck:
            report.append({
                "name": "Delivery tick",
                "status": "FAIL",
                "detail": f"{stuck} retry(ies) overdue — run_due_deliveries / webhooks_tick isn't firing.",
            })
        else:
            report.append({"name": "Delivery tick", "status": "PASS", "detail": "No overdue retries."})

    def _check_inbound(self, report: Report) -> None:
        from apps.webhooks.models import WebhookReceiver
        from apps.webhooks.registry import get_handler, registered_handlers

        if not getattr(settings, "SMALLSTACK_WEBHOOKS_INBOUND", True):
            report.append({"name": "Inbound", "status": "PASS", "detail": "Inbound disabled via setting."})
            return

        receivers = list(WebhookReceiver.objects.filter(enabled=True))
        handlers = registered_handlers()
        missing = [r.name for r in receivers if get_handler(r.handler_name) is None]
        if missing:
            report.append({
                "name": "Inbound handlers",
                "status": "FAIL",
                "detail": f"Receiver(s) with no registered handler: {', '.join(missing)}. "
                          f"Registered: {', '.join(handlers) or 'none'}. "
                          # F-018: the most common cause of a 'missing' handler is a stale worker.
                          "If the handler exists in a webhook_handlers.py, RESTART db_worker / the "
                          "dev server — handlers are autodiscovered at process start, not hot-reloaded.",
            })
        else:
            report.append({
                "name": "Inbound handlers",
                "status": "PASS",
                "detail": f"{len(receivers)} active receiver(s), {len(handlers)} handler(s) registered.",
            })

        # F-016/F-017: distinguish "verifying with a custom scheme" from "fails open".
        # A receiver with a non-default verifier IS verifying (Stripe t.body, Event Grid
        # key, …) — it must not be lumped with require_signature=False.
        self._check_verification(report, receivers)

    def _check_verification(self, report: Report, receivers: list) -> None:
        from apps.webhooks import hooks

        seams = hooks.registered()
        # Custom verifiers that aren't the built-in hmac default.
        custom = [
            r for r in receivers
            if (r.verifier or "hmac") != hooks.DEFAULT_VERIFIER
        ]
        unknown = [
            r.name for r in custom if r.verifier not in seams["verifiers"]
        ]
        if unknown:
            report.append({
                "name": "Inbound verifiers",
                "status": "FAIL",
                "detail": (
                    f"Receiver(s) select an unregistered verifier (falls back to hmac): "
                    f"{', '.join(unknown)}. Register it with @webhook_verifier in a "
                    "webhook_verifiers.py, then RESTART the worker (F-018)."
                ),
            })
        elif custom:
            report.append({
                "name": "Inbound verifiers",
                "status": "PASS",
                "detail": (
                    f"{len(custom)} receiver(s) verify with a custom scheme "
                    f"(e.g. {', '.join(sorted({r.verifier for r in custom}))}) — verified, not fail-open."
                ),
            })

        # Fail-open check applies only to receivers on the DEFAULT verifier with signature
        # verification OFF — those accept unsigned/bad-signature POSTs. A custom-verifier
        # receiver is NOT fail-open even if require_signature is nuanced.
        unsigned = [
            r.name for r in receivers
            if not r.require_signature and (r.verifier or "hmac") == hooks.DEFAULT_VERIFIER
        ]
        if unsigned:
            report.append({
                "name": "Inbound signatures",
                "status": "WARN",
                "detail": (
                    f"require_signature=False (accepts unsigned POSTs): {', '.join(unsigned)}. "
                    "For a provider that signs differently (Stripe, Event Grid), prefer a "
                    "@webhook_verifier over require_signature=False. "
                    "Re-enable with: sc set webhookreceiver <pk> --require_signature=true"
                ),
            })

    # -- output -------------------------------------------------------------

    def _explain(self, *, as_json: bool) -> None:
        from apps.smallstack.crud import CRUDView
        from apps.webhooks import hooks
        from apps.webhooks.registry import registered_handlers

        all_events = ["created", "updated", "deleted"]
        outbound = [
            {"model": v.model._meta.label, "events": getattr(v, "webhook_events", None) or all_events}
            for v in CRUDView._registry.values()
            if v.model is not None and getattr(v, "enable_webhooks", False)
        ]
        seams = hooks.registered()
        data: dict[str, Any] = {
            "outbound_models": outbound,
            "inbound_handlers": registered_handlers(),
            "seams": seams,
        }
        if as_json:
            self.stdout.write(jsonlib.dumps(data, indent=2, default=str))
            return
        self.stdout.write("Outbound models (enable_webhooks=True):")
        for row in outbound:
            self.stdout.write(f"  · {row['model']} → {', '.join(row['events'])}")
        if not outbound:
            self.stdout.write("  (none)")
        self.stdout.write("Inbound handlers (@webhook_handler):")
        for name in data["inbound_handlers"]:
            self.stdout.write(f"  · {name}")
        if not data["inbound_handlers"]:
            self.stdout.write("  (none)")
        self.stdout.write("Extension seams (registered names):")
        self.stdout.write(f"  · transforms : {', '.join(seams['transforms'])}")
        self.stdout.write(f"  · auths      : {', '.join(seams['auths'])}")
        self.stdout.write(f"  · verifiers  : {', '.join(seams['verifiers'])}")
        self.stdout.write(f"  · challenges : {', '.join(seams['challenges']) or 'none'}")

    def _emit(self, report: Report, options: dict[str, Any]) -> None:
        if options.get("json"):
            self.stdout.write(jsonlib.dumps(report, indent=2, default=str))
            return
        marks = {"PASS": f"{GREEN}✓{RESET}", "WARN": f"{YELLOW}!{RESET}", "FAIL": f"{RED}✗{RESET}"}
        for c in report:
            self.stdout.write(f"  {marks.get(c['status'], '?')} {c['name']}: {c['detail']}")
        fail = sum(1 for c in report if c["status"] == "FAIL")
        warn = sum(1 for c in report if c["status"] == "WARN")
        self.stdout.write("")
        self.stdout.write(f"Summary: {len(report) - fail - warn} ✓ / {warn} ⚠ / {fail} ✗")
