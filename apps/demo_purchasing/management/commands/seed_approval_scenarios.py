"""Seed the three approvals scenarios: users, groups, demo rows, webhook wiring.

Deterministic and idempotent — re-running converges on the same state, so
screenshots and row counts are stable. Requires ``create_dev_superuser`` first
(admin/admin is the superuser the HIGH-risk agent path needs).

    uv run python manage.py create_dev_superuser
    uv run python manage.py seed_approval_scenarios

The only non-idempotent part is the API tokens: raw keys can't be read back, so
each run revokes and re-mints the demo tokens and prints the new keys.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand

from apps.approvals import services as approvals
from apps.demo_access.models import AccessRequest
from apps.demo_agentops.models import AgentAction
from apps.demo_purchasing import services as purchasing
from apps.demo_purchasing.models import PurchaseRequest
from apps.demo_purchasing.scenarios import (
    TOKENS,
    USERS,
    ensure_users,
    ensure_webhook_wiring,
    get_user,
    mint_tokens,
)

# --- Scenario A rows -------------------------------------------------------
# (vendor, description, amount, category, justification, submit?, decide)
PURCHASES: list[tuple[str, str, str, str, str, bool, str | None]] = [
    (
        "Dell",
        "4× developer laptops",
        "3800.00",
        "hardware",
        "Two new hires start next month; two machines are out of warranty.",
        False,
        None,
    ),
    (
        "Snowflake",
        "Annual data-warehouse licence",
        "24000.00",
        "software",
        "Renewal. Finance tier — above the $5,000 threshold.",
        True,
        None,
    ),
    (
        "Fastly",
        "CDN overage top-up",
        "900.00",
        "services",
        "Traffic spike from the launch; below threshold, any staff can approve.",
        True,
        None,
    ),
    (
        "Contoso Travel",
        "Conference travel — 2 engineers",
        "2450.00",
        "travel",
        "Two talks accepted at DjangoCon.",
        True,
        "approve",
    ),
    (
        "Acme Hosting",
        "Dedicated GPU box",
        "8200.00",
        "hardware",
        "Rejected in the demo data so the console shows a rejected row.",
        True,
        "reject",
    ),
]

# --- Scenario B rows -------------------------------------------------------
# (tool_name, payload, risk, agent, decide)
AGENT_ACTIONS: list[tuple[str, dict[str, Any], str, str, str | None]] = [
    (
        "broadcast.send",
        {"audience": "all-customers", "subject": "Scheduled maintenance Sunday 02:00 UTC"},
        "medium",
        "support-copilot",
        None,
    ),
    (
        "records.purge",
        {"table": "audit_events", "count": 12000},
        "high",
        "data-retention-agent",
        None,
    ),
    (
        "runbook.execute",
        {"slug": "restart-web-tier"},
        "low",
        "oncall-copilot",
        "approve",
    ),
]

# --- Scenario C rows -------------------------------------------------------
# (resource, scope, reason, duration_hours, requester, decide)
ACCESS_REQUESTS: list[tuple[str, str, str, int, str, str | None]] = [
    ("dataset:payroll", "read", "Quarter-end reconciliation.", 8, "analyst", None),
    ("vault:prod-db", "admin", "Incident INC-4821 — need to rotate a leaked key.", 2, "svcbot", None),
    ("dataset:revenue", "read", "Board deck refresh.", 24, "analyst", "approve"),
]


class Command(BaseCommand):
    help = "Seed users + deterministic demo rows for the three approvals scenarios."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--no-tokens",
            action="store_true",
            help="Skip re-minting the demo API tokens (they are re-minted by default).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING("Users"))
        for user, created in ensure_users():
            verb = "created" if created else "updated"
            self.stdout.write(f"  {verb:8} {user.username:10} staff={user.is_staff}")
        try:
            get_user("admin")
        except LookupError:
            self.stdout.write(
                self.style.WARNING(
                    "  admin is MISSING — run `manage.py create_dev_superuser` "
                    "(the HIGH-risk agent path needs a superuser)."
                )
            )

        # Wire the webhook loop BEFORE the demo rows: the outbound observer only
        # fires for endpoints that already exist, so seeding first would leave the
        # demo data with no deliveries to look at.
        self.stdout.write(self.style.MIGRATE_HEADING("Webhook wiring"))
        endpoint, receiver = ensure_webhook_wiring()
        self.stdout.write(f"  outbound endpoint #{endpoint.pk} → {endpoint.target_url}")
        self.stdout.write(f"  inbound receiver  #{receiver.pk} /webhooks/in/{receiver.slug}/")
        self.stdout.write(f"  shared secret     {receiver.secret}")

        self.stdout.write(self.style.MIGRATE_HEADING("Scenario A — purchase requests"))
        self._seed_purchases()

        self.stdout.write(self.style.MIGRATE_HEADING("Scenario B — agent actions"))
        self._seed_agent_actions()

        self.stdout.write(self.style.MIGRATE_HEADING("Scenario C — access requests"))
        self._seed_access_requests()

        if not options["no_tokens"]:
            self.stdout.write(self.style.MIGRATE_HEADING("API tokens (re-minted — save these)"))
            for name, username, level, raw in mint_tokens():
                self.stdout.write(f"  {name:26} {username:9} {level:9} {raw}")

        self.stdout.write(self.style.MIGRATE_HEADING("Logins"))
        self.stdout.write("  admin      / admin      superuser")
        for spec in USERS:
            self.stdout.write(
                f"  {spec['username']:10} / {spec['password']:10} "
                f"{'staff' if spec['is_staff'] else 'non-staff':9} — {spec['role']}"
            )
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded. Verify with: uv run python manage.py approval_scenario all --check"
            )
        )
        if not options["no_tokens"] and not TOKENS:  # pragma: no cover — defensive
            self.stdout.write(self.style.WARNING("No tokens configured."))

    # --- per-scenario seeding ---------------------------------------------

    def _seed_purchases(self) -> None:
        buyer = get_user("buyer")
        admin = self._decider()
        for vendor, desc, amount, category, why, submit, decision in PURCHASES:
            pr, created = PurchaseRequest.objects.get_or_create(
                vendor=vendor,
                description=desc,
                defaults={
                    "amount": Decimal(amount),
                    "category": category,
                    "justification": why,
                    "requested_by": buyer,
                },
            )
            if not created:
                self.stdout.write(f"  exists   {desc} [{pr.state}]")
                continue
            if submit:
                req = purchasing.submit_for_approval(pr, actor=buyer, source="seed")
                if decision and admin is not None:
                    self._decide(req, admin, decision, "Seeded demo decision.")
                    pr.refresh_from_db()
            self.stdout.write(f"  created  {desc} [{pr.state}] po={pr.po_number or '-'}")

    def _seed_agent_actions(self) -> None:
        from apps.demo_agentops import services as agentops

        agentbot = get_user("agentbot")
        admin = self._decider()
        for tool_name, payload, risk, agent, decision in AGENT_ACTIONS:
            if AgentAction.objects.filter(tool_name=tool_name, payload=payload).exists():
                self.stdout.write(f"  exists   {tool_name} [{risk}]")
                continue
            action, req = agentops.propose(
                tool_name=tool_name,
                payload=payload,
                risk=risk,
                actor=agentbot,
                agent=agent,
                source="seed",
            )
            if decision and admin is not None:
                self._decide(req, admin, decision, "Seeded demo decision.")
                action.refresh_from_db()
            self.stdout.write(f"  created  {tool_name} [{action.state}] {action.result or '-'}")

    def _seed_access_requests(self) -> None:
        from apps.demo_access import services as access

        admin = self._decider()
        for resource, scope, reason, hours, requester, decision in ACCESS_REQUESTS:
            if AccessRequest.objects.filter(resource=resource, scope=scope).exists():
                self.stdout.write(f"  exists   {resource} ({scope})")
                continue
            ar, req = access.file_access_request(
                resource=resource,
                scope=scope,
                reason=reason,
                duration_hours=hours,
                actor=get_user(requester),
                source="seed",
            )
            if decision and admin is not None:
                self._decide(req, admin, decision, "Seeded demo decision.")
                ar.refresh_from_db()
            self.stdout.write(f"  created  {resource} ({scope}) [{ar.state}]")

    # --- helpers ----------------------------------------------------------

    def _decider(self) -> Any:
        try:
            return get_user("admin")
        except LookupError:
            return None

    def _decide(self, req: Any, actor: Any, decision: str, note: str) -> None:
        if decision == "approve":
            approvals.approve(req, actor=actor, note=note, source="seed")
        else:
            approvals.reject(req, actor=actor, note=note, source="seed")
