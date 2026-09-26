"""End-to-end harness for the three approvals scenarios.

    uv run python manage.py approval_scenario <a|b|c|all> [--check]

Runs each scenario for real — services, the Django test client (web + REST), and
live MCP JSON-RPC calls — and prints one stable, greppable line per assertion:

    PASS  A01  submit files a pending approval request
    FAIL  B04  a non-staff agent token may poll get_approval  (403 Forbidden: staff_required)

No web server is required: the test client drives the WSGI stack in-process.
``--check`` makes the command exit non-zero if any assertion failed (without it
the same lines are printed and the exit status is always 0).

The harness is self-cleaning: every business row it creates is marked
``[harness]`` / ``harness:`` and deleted (with its approval rows) at the start of
the next run, so counts don't drift. It never touches seeded demo rows.

Requires `create_dev_superuser` + `seed_approval_scenarios` (it re-runs the
idempotent user/webhook setup itself, but not the demo rows).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.utils import timezone

from apps.approvals import permissions as approval_perms
from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.demo_access.models import AccessRequest, WebhookEcho
from apps.demo_agentops.actions import RAISE_IN_CALLBACK_KEY
from apps.demo_agentops.models import AgentAction
from apps.demo_purchasing.models import PurchaseRequest
from apps.demo_purchasing.scenarios import ensure_users, ensure_webhook_wiring, get_user
from apps.notifications.models import Notification
from apps.smallstack.models import APIToken
from apps.webhooks.models import WebhookDelivery

MARK = "[harness]"
RESOURCE_MARK = "harness:"
AGENT_MARK = "harness-agent"

APPROVAL_EVENT = "smallstack_approvals.approvalrequest"
DECIDE_URL = "/smallstack/api/approvals/requests/{pk}/decide/"
CREATE_URL = "/smallstack/api/approvals/requests/create/"
DETAIL_URL = "/smallstack/api/approvals/requests/{pk}/"
LIST_URL = "/smallstack/api/approvals/requests/"
NOTIFY_URL = "/smallstack/notifications/api/"
NOTIFY_MARK_READ_URL = "/smallstack/notifications/api/mark-read/"
CONSOLE_PREFIX = "/smallstack/approvals/requests/"
CONSOLE_URL = CONSOLE_PREFIX + "{pk}/"
FILE_ACCESS_URL = "/api/demo/access/requests/file/"


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------


@dataclass
class Check:
    ident: str
    description: str
    ok: bool
    detail: str = ""


class Runner:
    """Collects and prints assertions. One line per check, never reordered."""

    def __init__(self, command: BaseCommand) -> None:
        self.command = command
        self.checks: list[Check] = []

    def record(self, ident: str, description: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(ident, description, bool(ok), detail))
        label = "PASS" if ok else "FAIL"
        style = self.command.style.SUCCESS if ok else self.command.style.ERROR
        line = f"{label}  {ident}  {description}"
        if detail:
            line = f"{line}  ({detail})"
        self.command.stdout.write(style(line))
        return bool(ok)

    def eq(self, ident: str, description: str, actual: Any, expected: Any) -> bool:
        ok = actual == expected
        return self.record(
            ident, description, ok, "" if ok else f"expected {expected!r}, got {actual!r}"
        )

    def truthy(self, ident: str, description: str, value: Any, detail: str = "") -> bool:
        return self.record(ident, description, bool(value), "" if value else detail or "falsy")

    def section(self, title: str) -> None:
        self.command.stdout.write("")
        self.command.stdout.write(self.command.style.MIGRATE_HEADING(f"== {title} =="))

    def tally(self, name: str) -> tuple[int, int]:
        passed = sum(1 for c in self.checks if c.ok)
        failed = len(self.checks) - passed
        return passed, failed


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def client_for(user: Any = None) -> Client:
    """A test client bound to an ALLOWED_HOST, optionally logged in.

    ``force_login`` with an explicit ModelBackend: the project's first
    AUTHENTICATION_BACKENDS entry is AxesStandaloneBackend, which needs a live
    request, and axes is enabled outside the test settings.
    """
    c = Client(headers={"host": "localhost"})
    if user is not None:
        c.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return c


def token_for(user: Any, level: str) -> str:
    """Mint a throwaway API token for the harness (revoked on the next run)."""
    name = f"{MARK} {level} {user.username}"
    APIToken.objects.filter(user=user, name=name).delete()
    _, raw = APIToken.create_token(
        user=user, name=name, description="approval_scenario harness", access_level=level
    )
    return raw


def bearer(raw: str | None) -> dict[str, str]:
    """Request headers for a Bearer token.

    Passed as ``headers=`` rather than the ``HTTP_AUTHORIZATION`` extra-kwargs
    form: ``**extra`` is untypeable against Client.get/post under django-stubs,
    and ``headers=`` is the supported spelling since Django 4.2.
    """
    return {"authorization": f"Bearer {raw}"} if raw else {}


def post_json(client: Client, url: str, payload: dict, raw_token: str | None = None) -> Any:
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        headers=bearer(raw_token),
    )


def body(response: Any) -> dict:
    try:
        return json.loads(response.content.decode() or "{}")
    except ValueError:
        return {}


# The protocol-level `isError` flag from the LAST mcp() call. It used to be
# discarded by this helper, which made the harness structurally incapable of
# testing half of F-20 — reverting `is_error = False` in apps/mcp/views.py left
# the harness at a green 96/0. Read it with mcp_is_error(). (F-41.)
_LAST_MCP: dict[str, Any] = {"isError": None}


def mcp_is_error() -> Any:
    """`isError` from the last mcp()/mcp_tool() call; None if absent."""
    return _LAST_MCP["isError"]


def mcp(client: Client, raw_token: str, method: str, params: dict) -> tuple[int, Any]:
    """One MCP JSON-RPC call over the real /mcp endpoint. Returns (status, result).

    Also records the protocol-level `isError` flag for mcp_is_error().
    """
    _LAST_MCP["isError"] = None
    resp = client.post(
        "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        content_type="application/json",
        headers=bearer(raw_token),
    )
    payload = body(resp)
    if resp.status_code != 200:
        return resp.status_code, payload.get("error", payload)
    result = payload.get("result") or {}
    if isinstance(result, dict) and "isError" in result:
        _LAST_MCP["isError"] = result["isError"]
    content = result.get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict):
        try:
            return resp.status_code, json.loads(content[0].get("text") or "{}")
        except ValueError:
            return resp.status_code, content[0].get("text")
    return resp.status_code, result


def mcp_tool(client: Client, raw_token: str, name: str, args: dict) -> tuple[int, Any]:
    return mcp(client, raw_token, "tools/call", {"name": name, "arguments": args})


def expire_now(req: ApprovalRequest) -> None:
    """Push a pending request past its deadline without waiting."""
    ApprovalRequest.objects.filter(pk=req.pk).update(
        expires_at=timezone.now() - timedelta(seconds=5)
    )
    req.refresh_from_db()


def notified(user: Any, kind: str, since_ids: set[int]) -> list[Notification]:
    return list(
        Notification.objects.filter(recipient=user, kind=kind).exclude(pk__in=since_ids)
    )


def notification_ids() -> set[int]:
    return set(Notification.objects.values_list("pk", flat=True))


def deliveries_since(pk_floor: int, suffix: str) -> list[WebhookDelivery]:
    return list(
        WebhookDelivery.objects.filter(
            pk__gt=pk_floor, event_type=f"{APPROVAL_EVENT}.{suffix}"
        ).order_by("pk")
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def purge_harness_rows() -> int:
    """Delete everything a previous harness run created (rows + their approvals)."""
    purchases = PurchaseRequest.objects.filter(description__startswith=MARK)
    actions = AgentAction.objects.filter(requested_by_agent=AGENT_MARK)
    accesses = AccessRequest.objects.filter(resource__startswith=RESOURCE_MARK)

    approval_ids = {
        pk
        for qs in (purchases, actions, accesses)
        for pk in qs.exclude(approval__isnull=True).values_list("approval_id", flat=True)
    }
    deleted = purchases.count() + actions.count() + accesses.count()
    purchases.delete()
    actions.delete()
    accesses.delete()
    # Approvals filed by the harness with no business row (the REST-create checks).
    ApprovalRequest.objects.filter(title__contains=MARK).delete()
    ApprovalRequest.objects.filter(pk__in=approval_ids).delete()
    WebhookEcho.objects.filter(title__contains=MARK).delete()
    APIToken.objects.filter(name__startswith=MARK).delete()
    _purge_orphans()
    return deleted


def _purge_orphans() -> None:
    """Drop the fan-out left behind by deleted approvals.

    Notifications and webhook deliveries are created by the framework, not by
    this app, so they survive the row purge above and would pile up in the dev
    database run after run (a four-figure bell badge after a morning of
    regressions). Both are matched by the approval id they point at, so only
    rows whose ApprovalRequest no longer exists are removed — a seeded demo
    notification is never touched.
    """
    live = set(ApprovalRequest.objects.values_list("pk", flat=True))

    orphan_notifications = [
        pk
        for pk, url in Notification.objects.filter(
            kind__startswith="approvals."
        ).values_list("pk", "url")
        for approval_pk in [_approval_pk_from_console_url(url)]
        if approval_pk is not None and approval_pk not in live
    ]
    Notification.objects.filter(pk__in=orphan_notifications).delete()

    orphan_deliveries = [
        pk
        for pk, payload in WebhookDelivery.objects.filter(
            event_type__startswith=APPROVAL_EVENT
        ).values_list("pk", "payload")
        for approval_pk in [(payload or {}).get("data", {}).get("id")]
        if approval_pk is not None and approval_pk not in live
    ]
    WebhookDelivery.objects.filter(pk__in=orphan_deliveries).delete()


def _approval_pk_from_console_url(url: str) -> int | None:
    if not url.startswith(CONSOLE_PREFIX):
        return None
    try:
        return int(url[len(CONSOLE_PREFIX):].strip("/"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Scenario A — purchase requests (web)
# ---------------------------------------------------------------------------


def make_purchase(desc: str, amount: str, requester: Any) -> PurchaseRequest:
    return PurchaseRequest.objects.create(
        vendor="Harness Supply Co",
        description=f"{MARK} {desc}",
        amount=Decimal(amount),
        category=PurchaseRequest.Category.HARDWARE,
        justification="Created by approval_scenario.",
        requested_by=requester,
    )


def run_scenario_a(r: Runner) -> None:
    from apps.demo_purchasing import services as purchasing

    r.section("Scenario A — purchase requests (web, human decides)")

    admin = get_user("admin")
    opslead = get_user("opslead")
    finance = get_user("finance")
    buyer = get_user("buyer")
    analyst = get_user("analyst")

    # --- filing + tiered routing -----------------------------------------
    low = make_purchase("low-value dock station", "900.00", buyer)
    low_req = purchasing.submit_for_approval(low, actor=buyer, source="harness")
    low.refresh_from_db()
    r.eq("A01", "submit files a pending approval and moves the row to pending",
         (low_req.status, low.state), ("pending", "pending"))
    r.truthy("A02", "the approval points AT the purchase request (target pointer)",
             low_req.target == low, f"target={low_req.target!r}")
    ttl = (low_req.expires_at - timezone.now()) if low_req.expires_at else None
    r.truthy("A03", "kind default_expires_in (2 days) applied at filing",
             ttl is not None and timedelta(days=1, hours=23) < ttl <= timedelta(days=2),
             f"ttl={ttl}")
    r.eq("A04", "low-value request names no assignees (any staff decides)",
         list(low_req.assignees.all()), [])
    r.truthy("A05", "low-value: an unrelated staff member may decide",
             approval_perms.can_decide(opslead, low_req))
    r.truthy("A06", "low-value: a non-staff bystander may NOT decide",
             not approval_perms.can_decide(analyst, low_req))

    high = make_purchase("high-value GPU cluster", "18000.00", buyer)
    high_req = purchasing.submit_for_approval(high, actor=buyer, source="harness")
    r.eq("A07", "high-value request routes to the finance approvers group",
         [u.username for u in high_req.assignees.all()], ["finance"])
    r.truthy("A08", "high-value: the NON-staff assignee may decide",
             approval_perms.can_decide(finance, high_req))
    r.truthy("A09", "high-value: an unrelated non-staff user may NOT decide",
             not approval_perms.can_decide(analyst, high_req))

    own = make_purchase("self-approval control", "100.00", opslead)
    own_req = purchasing.submit_for_approval(own, actor=opslead, source="harness")
    r.truthy("A10", "self-approval is blocked even for staff",
             not approval_perms.can_decide(opslead, own_req))
    r.truthy("A11", "another staff member can still decide it",
             approval_perms.can_decide(admin, own_req))

    # --- approve: the PO is minted by the callback ------------------------
    before = notification_ids()
    approvals.approve(low_req, actor=opslead, note="Within budget.", source="harness")
    low.refresh_from_db()
    r.eq("A12", "approve mints a PO number and sets state=approved",
         (low.state, low.po_number), ("approved", f"PO-{low.pk:05d}"))
    r.eq("A13", "the decision note lands on the business row",
         low.decided_note, "Within budget.")
    r.truthy("A14", "the requester is notified in-app on the decision",
             notified(buyer, "approvals.decided", before))
    r.truthy("A15", "the deciding actor is NOT notified of their own decision",
             not notified(opslead, "approvals.decided", before))

    # approvers notified at filing time
    before = notification_ids()
    notify_case = make_purchase("notification routing", "9000.00", buyer)
    purchasing.submit_for_approval(notify_case, actor=buyer, source="harness")
    r.truthy("A16", "the assigned (non-staff) approver is notified in-app on filing",
             notified(finance, "approvals.requested", before))
    r.truthy("A17", "the requester is NOT notified of their own request",
             not notified(buyer, "approvals.requested", before))

    # --- reject / cancel / expire: nothing armed --------------------------
    reject_case = make_purchase("rejected laptop", "700.00", buyer)
    reject_req = purchasing.submit_for_approval(reject_case, actor=buyer, source="harness")
    approvals.reject(reject_req, actor=opslead, note="Use the spare.", source="harness")
    reject_case.refresh_from_db()
    r.eq("A18", "reject sets state=rejected and mints NO PO",
         (reject_case.state, reject_case.po_number), ("rejected", ""))

    cancel_case = make_purchase("withdrawn order", "400.00", buyer)
    cancel_req = purchasing.submit_for_approval(cancel_case, actor=buyer, source="harness")
    approvals.cancel(cancel_req, actor=buyer, note="No longer needed.", source="harness")
    cancel_case.refresh_from_db()
    r.eq("A19", "cancel sets state=canceled and mints NO PO",
         (cancel_case.state, cancel_case.po_number), ("canceled", ""))

    expire_case = make_purchase("stale order", "500.00", buyer)
    expire_req = purchasing.submit_for_approval(expire_case, actor=buyer, source="harness")
    expire_now(expire_req)
    swept = approvals.mark_expired()
    expire_case.refresh_from_db()
    r.truthy("A20", "the expiry sweep expires the overdue request", swept >= 1, f"swept={swept}")
    r.eq("A21", "expiry sets state=expired and mints NO PO",
         (expire_case.state, expire_case.po_number), ("expired", ""))

    # --- web surfaces -----------------------------------------------------
    embed_case = make_purchase("embed decision", "12000.00", buyer)
    embed_req = purchasing.submit_for_approval(embed_case, actor=buyer, source="harness")

    finance_client = client_for(finance)
    review_url = f"/demo/purchasing/requests/{embed_case.pk}/review/"
    resp = finance_client.get(review_url)
    r.eq("A22", "the non-staff assignee can open the embed page", resp.status_code, 200)
    html = resp.content.decode() if resp.status_code == 200 else ""
    # "FINANCE TIER" exists only in the app's own kind card, so its presence
    # proves the key-derived template (approvals/kinds/purchasing-approve.html)
    # beat the shipped default — not just that the amount is on the page.
    r.truthy("A23", "the key-derived kind card wins over the default card",
             "FINANCE TIER" in html and "12000.00" in html,
             "the default card rendered instead")
    r.truthy("A24", "the embed offers the decision form to the eligible assignee",
             'name="decision"' in html, "no decision buttons rendered")

    resp = finance_client.post(
        f"/smallstack/approvals/requests/{embed_req.pk}/decide/",
        {"decision": "approve", "note": "Finance OK.", "next": review_url},
    )
    embed_case.refresh_from_db()
    r.eq("A25", "the NON-staff assignee decides through the embed (web POST)",
         (resp.status_code, embed_case.state, bool(embed_case.po_number)),
         (302, "approved", True))

    analyst_client = client_for(analyst)
    resp = analyst_client.get(review_url)
    r.eq("A26", "an unrelated non-staff user cannot open the review page",
         resp.status_code, 403)

    # Docs §3 / apps/approvals/README.md both say a non-staff assignee can decide
    # "via the emailed console link". The console is StaffRequiredMixin, so that
    # link is a dead end for exactly the users it is advertised to.
    pending_case = make_purchase("console link for a non-staff assignee", "15000.00", buyer)
    pending_req = purchasing.submit_for_approval(pending_case, actor=buyer, source="harness")
    resp = finance_client.get(CONSOLE_URL.format(pk=pending_req.pk))
    r.record(
        "A27",
        "a non-staff assignee can open the console link (F-01, fixed round 2)",
        resp.status_code == 200,
        f"HTTP {resp.status_code} — expected 200. The console must stay "
        f"LoginRequired + eligibility-scoped, not StaffRequired.",
    )

    # the in-app notification for that assignee points at the same dead end
    note = Notification.objects.filter(
        recipient=finance, kind="approvals.requested", url=CONSOLE_URL.format(pk=pending_req.pk)
    ).first()
    r.truthy("A28", "the assignee's in-app notification links to the console path",
             note is not None, "no notification row with the console URL")

    admin_client = client_for(admin)
    resp = admin_client.get("/smallstack/")
    dash = resp.content.decode() if resp.status_code == 200 else ""
    r.truthy("A29", "the /smallstack/ dashboard widget shows a pending-approvals count",
             "pending" in dash.lower() and "Approvals" in dash, f"HTTP {resp.status_code}")

    resp = admin_client.get("/demo/purchasing/requests/")
    r.eq("A30", "the staff console lists the scenario rows", resp.status_code, 200)


# ---------------------------------------------------------------------------
# Scenario B — agent actions (MCP / AI)
# ---------------------------------------------------------------------------


def run_scenario_b(r: Runner) -> None:
    r.section("Scenario B — agent action gate (MCP human-in-the-loop)")

    from apps.mcp.server import TOOL_REGISTRY

    admin = get_user("admin")
    opslead = get_user("opslead")
    agentbot = get_user("agentbot")
    analyst = get_user("analyst")

    agent_token = token_for(agentbot, "auth")
    staff_token = token_for(admin, "staff")
    agent_client = client_for()
    staff_client = client_for()

    # --- the agent files over MCP ----------------------------------------
    status, listed = mcp(agent_client, agent_token, "tools/list", {})
    tool_names = {t["name"] for t in (listed.get("tools") or [])} if isinstance(listed, dict) else set()
    r.truthy("B01", "propose_agent_action is discoverable in the agent's tools/list",
             "propose_agent_action" in tool_names, f"HTTP {status}, tools={sorted(tool_names)[:6]}")
    r.truthy("B02", "request_approval is discoverable in the agent's tools/list",
             "request_approval" in tool_names, f"HTTP {status}")

    status, proposed = mcp_tool(
        agent_client,
        agent_token,
        "propose_agent_action",
        {
            "tool_name": "broadcast.send",
            "risk": "medium",
            "payload": {"audience": "beta-users", "subject": f"{MARK} medium risk"},
            "agent": AGENT_MARK,
        },
    )
    action_id = proposed.get("action_id") if isinstance(proposed, dict) else None
    r.truthy("B03", "the agent proposes an action over MCP and gets ids back",
             status == 200 and action_id, f"HTTP {status}, result={proposed!r}")
    if not action_id:
        raise CommandError("Scenario B cannot continue: propose_agent_action failed.")
    action = AgentAction.objects.get(pk=action_id)
    med_req = ApprovalRequest.objects.get(pk=proposed["approval_id"])
    r.eq("B04", "the proposed action is pending and NOTHING executed",
         (action.state, action.result, action.executed_at), ("pending", "", None))
    ttl = med_req.expires_at - timezone.now() if med_req.expires_at else None
    r.truthy("B05", "kind default_expires_in (30 minutes) applied",
             ttl is not None and timedelta(minutes=28) < ttl <= timedelta(minutes=30),
             f"ttl={ttl}")

    status, generic = mcp_tool(
        agent_client, agent_token, "request_approval",
        {"kind": "agentops.action", "title": f"{MARK} generic request_approval", "context": {"risk": "low"}},
    )
    r.truthy("B06", "the generic request_approval MCP tool works for the agent's token tier",
             status == 200 and isinstance(generic, dict) and generic.get("status") == "pending",
             f"HTTP {status}, result={generic!r}")

    # --- can the agent read the decision back? (docs §2's polling loop) ---
    r.truthy("B07", "the get_approval polling tool named by docs §2 exists",
             "get_approval" in TOOL_REGISTRY,
             f"registry has {[n for n in TOOL_REGISTRY if 'approval' in n]}")

    status, polled = mcp_tool(agent_client, agent_token, "get_approval", {"pk": med_req.pk})
    r.record(
        "B08",
        "the agent's own (non-staff) token can poll get_approval (F-02, fixed round 2)",
        status == 200 and isinstance(polled, dict) and polled.get("status") == "pending",
        f"HTTP {status}, result={polled!r} — expected the agent's own row. "
        f"get_approval must be eligibility-scoped, not staff-gated.",
    )
    # B09 used to assert the OPPOSITE — that get_approval was hidden — because
    # when it was staff-gated, hiding it was at least *consistent* with being
    # uncallable. Now that F-02 scopes the read by eligibility instead of
    # is_staff, the coherent state is visible AND callable, which is what the
    # documented polling loop needs. (Updated with the fix, 2026-09-25 round 2.)
    r.truthy("B09", "get_approval is both visible to the agent AND callable (coherent gating)",
             "get_approval" in tool_names
             and isinstance(polled, dict) and polled.get("status") == "pending",
             f"in tools/list={'get_approval' in tool_names}, call result={polled!r}")

    status, listed_staff = mcp(staff_client, staff_token, "tools/list", {})
    staff_tools = (
        {t["name"] for t in (listed_staff.get("tools") or [])}
        if isinstance(listed_staff, dict)
        else set()
    )
    r.truthy("B10", "a STAFF token does see get_approval (the loop closes only for staff)",
             "get_approval" in staff_tools, f"HTTP {status}")
    status, polled_staff = mcp_tool(staff_client, staff_token, "get_approval", {"pk": med_req.pk})
    r.truthy("B11", "a staff token can poll get_approval and read the status",
             status == 200 and isinstance(polled_staff, dict) and polled_staff.get("status") == "pending",
             f"HTTP {status}, result={polled_staff!r}")

    rest_agent = client_for()
    resp = rest_agent.get(DETAIL_URL.format(pk=med_req.pk), headers=bearer(agent_token))
    r.record(
        "B12",
        "the agent can poll the approval's REST detail without staff rights (F-02)",
        resp.status_code == 200,
        f"HTTP {resp.status_code} — expected 200 for the agent's OWN row. "
        f"See B12a/B12b for the other half: someone else's row must 404.",
    )

    # --- the OTHER half of F-02: scoping is a gate, not just a widening ----
    #
    # B08/B09/B12 all assert the PERMISSIVE direction ("the agent CAN now read").
    # Nothing asserted that a non-staff identity CANNOT read a row it has nothing
    # to do with — so neutering both scopers in apps/approvals/views.py
    # (get_list_queryset / get_detail_queryset returning qs unscoped) left the
    # harness at a green 96/0 while an unrelated non-staff user could read every
    # row in the database. F-02 traded a coarse-but-safe staff gate for
    # fine-grained eligibility; the harness has to be able to see it break. (F-41.)
    analyst_token = token_for(analyst, "readonly")
    resp = client_for().get(DETAIL_URL.format(pk=med_req.pk), headers=bearer(analyst_token))
    r.record(
        "B12a",
        "an UNRELATED non-staff token cannot read someone else's approval (REST detail)",
        resp.status_code == 404,
        f"HTTP {resp.status_code} body={body(resp)!r} — expected 404 (existence-hidden). "
        f"The read scoper in apps/approvals/views.py is missing or bypassed.",
    )
    resp = client_for().get(LIST_URL, headers=bearer(analyst_token))
    analyst_listed = body(resp)
    analyst_ids = {row.get("id") for row in (analyst_listed.get("results") or [])}
    total_approvals = ApprovalRequest.objects.count()
    r.record(
        "B12b",
        "an UNRELATED non-staff token's REST list is scoped, not the whole table",
        resp.status_code == 200
        and med_req.pk not in analyst_ids
        and (analyst_listed.get("count") or 0) < total_approvals,
        f"HTTP {resp.status_code} count={analyst_listed.get('count')!r} of "
        f"{total_approvals} total; med_req visible={med_req.pk in analyst_ids}",
    )
    status, peeked = mcp_tool(
        client_for(), analyst_token, "get_approval", {"id": med_req.pk}
    )
    r.record(
        "B12c",
        "an UNRELATED non-staff token gets nothing from get_approval over MCP",
        status == 200 and isinstance(peeked, dict) and "error" in peeked
        and "title" not in peeked,
        f"HTTP {status}, result={peeked!r} — expected an error, not the row.",
    )
    # And the sibling that PROVES the alias F-25 added is the one an agent gets
    # handed: the same call with `id` works for the row's own requester.
    status, by_id = mcp_tool(agent_client, agent_token, "get_approval", {"id": med_req.pk})
    r.record(
        "B12d",
        "get_approval accepts the `id` key request_approval hands back (F-25)",
        status == 200 and isinstance(by_id, dict) and by_id.get("id") == med_req.pk,
        f"HTTP {status}, result={by_id!r} — the documented poll loop passes `id`.",
    )

    # --- eligibility narrowing on risk -----------------------------------
    status, high = mcp_tool(
        agent_client, agent_token, "propose_agent_action",
        {
            "tool_name": "records.purge",
            "risk": "high",
            "payload": {"table": f"{MARK}_events", "count": 5},
            "agent": AGENT_MARK,
        },
    )
    high_action = AgentAction.objects.get(pk=high["action_id"])
    high_req = ApprovalRequest.objects.get(pk=high["approval_id"])
    r.truthy("B13", "a HIGH-risk action can be proposed", high_action.state == "pending")
    r.truthy("B14", "can_decide narrows: staff-but-not-superuser is refused on HIGH risk",
             not approval_perms.can_decide(opslead, high_req))
    r.truthy("B15", "can_decide still allows a superuser on HIGH risk",
             approval_perms.can_decide(admin, high_req))
    r.truthy("B16", "the hook cannot WIDEN: a non-staff bystander stays refused on low risk",
             not approval_perms.can_decide(analyst, med_req))

    ops_token = token_for(opslead, "staff")
    status, denied = mcp_tool(
        client_for(), ops_token, "decide_approval", {"id": high_req.pk, "approved": True}
    )
    # Was a substring match on prose ("eligible" in str(error)) — which passes for
    # code="conflict" whose message happens to contain the word, and even for
    # code="internal" with "ineligible" in the text. Exactly what B21 was
    # rewritten to stop doing. Assert the machine-readable code and isError. (F-41.)
    denied_err = denied.get("error") if isinstance(denied, dict) else None
    r.truthy("B17", "decide_approval (MCP) enforces the same narrowing as the web surface",
             status == 200
             and isinstance(denied_err, dict)
             and denied_err.get("code") == "not_eligible"
             and mcp_is_error() is True,
             f"HTTP {status}, result={denied!r}, isError={mcp_is_error()!r}")
    high_action.refresh_from_db()
    r.eq("B18", "the refused decision executed nothing",
         (high_action.state, high_action.executed_at), ("pending", None))

    status, decided = mcp_tool(
        staff_client, staff_token, "decide_approval",
        {"id": high_req.pk, "approved": True, "note": "Superuser sign-off."},
    )
    high_action.refresh_from_db()
    r.eq("B19", "a superuser approving over MCP executes the action",
         (status, high_action.state, bool(high_action.executed_at)), (200, "executed", True))
    r.truthy("B20", "the executed action recorded its result",
             "purged 5 records" in high_action.result, f"result={high_action.result!r}")

    first_result, first_at = high_action.result, high_action.executed_at
    status, retried = mcp_tool(
        staff_client, staff_token, "decide_approval", {"id": high_req.pk, "approved": True}
    )
    high_action.refresh_from_db()
    # F-20 turned MCP refusals into {"error": {"code": ..., "message": ...}} so a
    # model can branch on `code` instead of string-matching prose (and so the
    # protocol-level isError flag is true). Assert the code, not the old prefix.
    retried_err = retried.get("error") if isinstance(retried, dict) else None
    r.truthy("B21", "a retried decision is a conflict, not a second execution",
             isinstance(retried_err, dict) and retried_err.get("code") == "conflict"
             and mcp_is_error() is True,
             f"result={retried!r}, isError={mcp_is_error()!r}")
    r.eq("B22", "the action executed exactly once (result + timestamp unchanged)",
         (high_action.result, high_action.executed_at), (first_result, first_at))

    # --- a callback that raises -------------------------------------------
    from apps.demo_agentops import services as agentops

    boom_action, boom_req = agentops.propose(
        tool_name="runbook.execute",
        payload={"slug": f"{MARK}-boom", RAISE_IN_CALLBACK_KEY: True},
        risk="low",
        actor=agentbot,
        agent=AGENT_MARK,
        source="harness",
    )
    approvals.approve(boom_req, actor=admin, note="Callback will raise.", source="harness")
    boom_req.refresh_from_db()
    r.eq("B23", "a raising callback does not break the decision",
         boom_req.status, "approved")
    r.truthy("B24", "the callback traceback is captured in callback_error",
             "deliberate callback failure" in boom_req.callback_error,
             f"callback_error={boom_req.callback_error[:120]!r}")

    # --- failure inside the action ---------------------------------------
    bad_action, bad_req = agentops.propose(
        tool_name="records.purge",
        payload={"table": f"{MARK}_bad", "count": "not-a-number"},
        risk="low",
        actor=agentbot,
        agent=AGENT_MARK,
        source="harness",
    )
    approvals.approve(bad_req, actor=admin, source="harness")
    bad_action.refresh_from_db()
    bad_req.refresh_from_db()
    r.eq("B25", "an action that fails is recorded as state=failed, decision intact",
         (bad_action.state, bad_req.status), ("failed", "approved"))
    r.truthy("B26", "the failure reason is stored on the business row",
             "count" in bad_action.result, f"result={bad_action.result!r}")
    r.eq("B27", "an app-level action failure does NOT set callback_error",
         bad_req.callback_error, "")

    # --- rejection + expiry never execute --------------------------------
    rej_action, rej_req = agentops.propose(
        tool_name="broadcast.send", payload={"audience": f"{MARK}"}, risk="medium",
        actor=agentbot, agent=AGENT_MARK, source="harness",
    )
    approvals.reject(rej_req, actor=admin, note="No.", source="harness")
    rej_action.refresh_from_db()
    r.eq("B28", "a rejected action is never executed",
         (rej_action.state, rej_action.executed_at), ("rejected", None))

    exp_action, exp_req = agentops.propose(
        tool_name="broadcast.send", payload={"audience": f"{MARK} expiring"}, risk="low",
        actor=agentbot, agent=AGENT_MARK, source="harness",
    )
    expire_now(exp_req)
    approvals.mark_expired()
    exp_action.refresh_from_db()
    r.eq("B29", "an expired action is never executed",
         (exp_action.state, exp_action.executed_at), ("expired", None))

    # --- the explicit context_template ------------------------------------
    resp = client_for(admin).get(CONSOLE_URL.format(pk=med_req.pk))
    console = resp.content.decode() if resp.status_code == 200 else ""
    r.truthy("B30", "the kind's explicit context_template renders on the console",
             "broadcast.send" in console and "MEDIUM RISK" in console,
             f"HTTP {resp.status_code}")

    resp = client_for(admin).get("/demo/agentops/actions/")
    r.eq("B31", "the agent-action audit trail lists the scenario rows", resp.status_code, 200)


# ---------------------------------------------------------------------------
# Scenario C — elevated access (REST-first + webhooks)
# ---------------------------------------------------------------------------


def run_scenario_c(r: Runner) -> None:
    r.section("Scenario C — elevated access (REST-first + webhooks)")

    admin = get_user("admin")
    opslead = get_user("opslead")
    svcbot = get_user("svcbot")
    analyst = get_user("analyst")

    write_token = token_for(svcbot, "staff")
    readonly_token = token_for(svcbot, "readonly")
    decider_token = token_for(admin, "staff")
    analyst_token = token_for(analyst, "auth")
    api = client_for()

    ensure_webhook_wiring()
    delivery_floor = WebhookDelivery.objects.order_by("-pk").values_list("pk", flat=True).first() or 0

    # --- the GENERIC filing endpoint (docs §2) ----------------------------
    resp = post_json(
        api, CREATE_URL,
        {"kind": "access.grant", "title": f"{MARK} generic create",
         "context": {"resource": f"{RESOURCE_MARK}generic"}, "expires_in_minutes": 60},
        write_token,
    )
    generic = body(resp)
    r.eq("C01", "REST create with a write token returns 201", resp.status_code, 201)
    r.truthy("C02", "the generic create honours expires_in_minutes",
             generic.get("expires_at"), f"body={generic!r}")

    # C03 used to file WITHOUT a target and then assert target_repr was set — it
    # could only ever fail, which is how it encoded F-03 ("no target parameter").
    # The parameter now exists, so the assertion exercises it: a remote client
    # points an approval at a business row with no app-specific endpoint, and the
    # kind callback sees a real req.target. (Updated with the fix, round 2.)
    target_row = AccessRequest.objects.create(
        resource=f"{RESOURCE_MARK}generic-target", scope=AccessRequest.Scope.READ,
        reason="C03 remote target", requester=get_user("analyst"),
    )
    resp = post_json(
        api, CREATE_URL,
        {"kind": "access.grant", "title": f"{MARK} generic create with target",
         "target": f"demo_access.accessrequest:{target_row.pk}"},
        write_token,
    )
    targeted = body(resp)
    r.eq("C03a", "the generic REST create accepts a target and returns 201",
         resp.status_code, 201)
    r.record(
        "C03",
        "the generic REST create can attach the approval to a business row",
        bool(targeted.get("target_repr")),
        f"body={targeted!r} — REST create must accept `target` (F-03, fixed round 2)",
    )
    targeted_id = targeted.get("id") or 0
    r.truthy("C03b", "the resolved target is the real row, so the kind callback can use it",
             ApprovalRequest.objects.filter(pk=targeted_id).first() is not None
             and ApprovalRequest.objects.get(pk=targeted_id).target == target_row,
             f"target_repr={targeted.get('target_repr')!r}")
    r.record(
        "C03c",
        "a malformed target is a 400 that teaches the format, not a silent drop",
        (lambda rr: rr.status_code == 400
         and "app_label.model:pk" in json.dumps(body(rr)))(
            post_json(api, CREATE_URL,
                      {"kind": "access.grant", "title": f"{MARK} bad target",
                       "target": "not-a-target"},
                      write_token)
        ),
        "expected 400 naming the app_label.model:pk shape",
    )

    resp = post_json(
        api, CREATE_URL, {"kind": "access.grant", "title": f"{MARK} readonly"}, readonly_token
    )
    r.truthy("C04", "REST create with a readonly token is refused",
             resp.status_code in (401, 403), f"HTTP {resp.status_code}")

    resp = post_json(
        api, CREATE_URL, {"kind": "access.typo", "title": f"{MARK} unknown kind"}, write_token
    )
    err = json.dumps(body(resp))
    r.eq("C05", "REST create with an unknown kind returns 400", resp.status_code, 400)
    r.truthy("C06", "the 400 lists the registered kinds so the caller can fix it",
             "access.grant" in err and "agentops.action" in err, f"body={err[:160]}")

    # --- the scenario filing endpoint (target attached) --------------------
    resp = post_json(
        api, FILE_ACCESS_URL,
        {"resource": f"{RESOURCE_MARK}payroll", "scope": "read",
         "reason": "Harness run.", "duration_hours": 6},
        write_token,
    )
    filed = body(resp)
    r.eq("C07", "the scenario REST endpoint files an access request (201)", resp.status_code, 201)
    if resp.status_code != 201:
        raise CommandError(f"Scenario C cannot continue: filing failed — {filed!r}")
    ar = AccessRequest.objects.get(pk=filed["access_request_id"])
    req = ApprovalRequest.objects.get(pk=filed["approval_id"])
    r.truthy("C08", "the approval points at the AccessRequest", req.target == ar,
             f"target={req.target!r}")
    r.eq("C09", "the business row starts pending with no grant",
         (ar.state, ar.granted_until), ("pending", None))

    # --- REST decide -------------------------------------------------------
    resp = post_json(api, DECIDE_URL.format(pk=req.pk), {"approved": True}, write_token)
    ar.refresh_from_db()
    r.truthy("C10", "REST decide by the requester (self-approval) is refused",
             resp.status_code == 403, f"HTTP {resp.status_code}")
    r.eq("C11", "the refused decision left the state unchanged",
         (ar.state, ar.granted_until), ("pending", None))

    resp = post_json(api, DECIDE_URL.format(pk=req.pk), {"approved": True}, analyst_token)
    r.truthy("C12", "REST decide by a non-staff bystander is refused",
             resp.status_code in (403, 404), f"HTTP {resp.status_code}")

    expected_until = timezone.now() + timedelta(hours=6)
    resp = post_json(
        api, DECIDE_URL.format(pk=req.pk), {"approved": True, "note": "Granted for 6h."},
        decider_token,
    )
    ar.refresh_from_db()
    r.eq("C13", "REST decide by an eligible user grants the access",
         (resp.status_code, ar.state), (200, "granted"))
    drift = abs((ar.granted_until - expected_until).total_seconds()) if ar.granted_until else None
    r.truthy("C14", "granted_until == now + duration_hours",
             drift is not None and drift < 60, f"granted_until={ar.granted_until}, drift={drift}")
    r.truthy("C15", "the grant is active", ar.is_active_grant)

    # --- rejection + expiry leave no grant --------------------------------
    resp = post_json(
        api, FILE_ACCESS_URL,
        {"resource": f"{RESOURCE_MARK}vault", "scope": "admin", "reason": "Harness.",
         "duration_hours": 2},
        write_token,
    )
    rej = body(resp)
    rej_ar = AccessRequest.objects.get(pk=rej["access_request_id"])
    post_json(api, DECIDE_URL.format(pk=rej["approval_id"]), {"approved": False}, decider_token)
    rej_ar.refresh_from_db()
    r.eq("C16", "a rejected access request grants nothing",
         (rej_ar.state, rej_ar.granted_until), ("rejected", None))

    resp = post_json(
        api, FILE_ACCESS_URL,
        {"resource": f"{RESOURCE_MARK}stale", "scope": "read", "reason": "Harness.",
         "duration_hours": 1},
        write_token,
    )
    exp = body(resp)
    exp_ar = AccessRequest.objects.get(pk=exp["access_request_id"])
    exp_req = ApprovalRequest.objects.get(pk=exp["approval_id"])
    expire_now(exp_req)
    approvals.mark_expired()
    exp_ar.refresh_from_db()
    r.eq("C17", "an expired access request grants nothing",
         (exp_ar.state, exp_ar.granted_until), ("expired", None))

    # --- the queue filter --------------------------------------------------
    resp = api.get(f"{LIST_URL}?status=pending", headers=bearer(decider_token))
    listed = body(resp)
    results = listed.get("results") or []
    statuses = {row.get("status") for row in results}
    # `statuses - {"pending"} == set()` passed on an EMPTY result set, so a filter
    # that matched nothing at all certified as "clean". Require rows. (F-41.)
    r.eq("C18", "?status=pending is a clean queue filter (and actually returns rows)",
         (resp.status_code, bool(results), statuses - {"pending"}), (200, True, set()))
    # …and the count agrees with what "pending" means everywhere else. An overdue
    # row's stored `status` column still reads "pending" until a sweep flips it, so
    # `?status=pending` used to list 905 rows beside a "Pending" card reading 5.
    # Lazy expiry is capped at 1 here on purpose: with the default cap of 25 the
    # page sweeps this scenario's whole backlog inside the GET and the divergence
    # can never appear — i.e. the assertion would be vacuous. (F-29 / F-41.)
    for i in range(3):
        stale = approvals.request_approval(
            kind="access.grant",
            title=f"{MARK} overdue row {i} for the pending filter",
            actor=analyst,
            source="harness",
        )
        expire_now(stale)
    with override_settings(SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT=1):
        resp = api.get(f"{LIST_URL}?status=pending", headers=bearer(decider_token))
        capped = body(resp)
        stored_pending = ApprovalRequest.objects.pending().count()
        effective_pending = ApprovalRequest.objects.for_effective_status("pending").count()
        r.eq("C18a", "?status=pending excludes overdue rows, matching the Pending stat card",
             (resp.status_code, capped.get("count")), (200, effective_pending))
        r.truthy("C18b", "the C18a check is not vacuous — stored 'pending' really does "
                 "include rows nobody can decide",
                 stored_pending > effective_pending,
                 f"stored pending={stored_pending}, effective={effective_pending} "
                 f"(no unswept overdue rows, so C18a proves nothing)")

    # --- webhooks ----------------------------------------------------------
    created = deliveries_since(delivery_floor, "created")
    updated = deliveries_since(delivery_floor, "updated")
    r.truthy("C19", "filing emits smallstack_approvals.approvalrequest.created",
             any(d.payload.get("data", {}).get("id") == req.pk for d in created),
             f"{len(created)} created deliveries")
    decision_events = [
        d for d in updated
        if d.payload.get("data", {}).get("id") == req.pk
        and d.payload.get("data", {}).get("status") == "approved"
    ]
    r.truthy("C20", "the decision rides .updated carrying data.status",
             decision_events, f"{len(updated)} updated deliveries")
    r.truthy("C21", "expiry also emits .updated with status=expired",
             any(
                 d.payload.get("data", {}).get("id") == exp_req.pk
                 and d.payload.get("data", {}).get("status") == "expired"
                 for d in updated
             ),
             "no expired .updated delivery")

    # Deliver one event into this instance's own receiver, signed, to prove the
    # inbound half works end-to-end without a running server or worker.
    echoes_before = WebhookEcho.objects.count()
    if decision_events:
        from apps.demo_access.webhook_handlers import RECEIVER_SLUG
        from apps.demo_purchasing.scenarios import WEBHOOK_SECRET
        from apps.webhooks import services as webhook_services

        raw = json.dumps(decision_events[-1].payload, default=str).encode()
        sig = webhook_services.signature_header_value(WEBHOOK_SECRET, raw)
        resp = api.post(
            f"/webhooks/in/{RECEIVER_SLUG}/",
            data=raw,
            content_type="application/json",
            headers={"host": "localhost", webhook_services.SIGNATURE_HEADER: sig},
        )
        r.truthy("C22", "the local receiver accepts a signed approvals delivery",
                 resp.status_code in (200, 202), f"HTTP {resp.status_code}")
        # The inbound view ENQUEUES dispatch (`dispatch_incoming.enqueue`), so the
        # handler only runs under `manage.py db_worker`. The harness must not need
        # a worker, so it runs the same task inline on the receipt it just created.
        receipt_pk = body(resp).get("receipt")
        if receipt_pk:
            from apps.webhooks.tasks import dispatch_incoming

            dispatch_incoming.call(int(receipt_pk))
        echo = WebhookEcho.objects.order_by("-pk").first()
        r.truthy("C23", "the receiver's handler recorded the event for inspection",
                 WebhookEcho.objects.count() > echoes_before
                 and echo is not None
                 and echo.status == "approved",
                 f"echo={echo!r}")
    else:
        r.record("C22", "the local receiver accepts a signed approvals delivery", False,
                 "skipped — no decision delivery to replay")
        r.record("C23", "the receiver's handler recorded the event for inspection", False,
                 "skipped — no decision delivery to replay")

    # --- notifications REST ------------------------------------------------
    resp = api.get(f"{NOTIFY_URL}?unread=1", headers=bearer(write_token))
    inbox = body(resp)
    rows = inbox.get("notifications") or []
    mine = [n for n in rows if n.get("kind") == "approvals.decided"]
    r.eq("C24", "notifications REST returns the requester's own rows", resp.status_code, 200)
    r.truthy("C25", "the requester sees the decision notification", mine, f"rows={len(rows)}")
    r.truthy("C26", "the notification names an actor other than the requester",
             all(n.get("actor") != svcbot.username for n in mine),
             f"actors={[n.get('actor') for n in mine]}")

    resp = api.get(f"{NOTIFY_URL}?unread=1", headers=bearer(decider_token))
    decider_rows = body(resp).get("notifications") or []
    other = [
        n for n in decider_rows
        if n.get("kind") == "approvals.decided" and str(req.pk) in (n.get("url") or "")
    ]
    # `not other` alone passed for a 401, a 500 or an empty body — body() swallows
    # ValueError and returns {}, so "the call failed" read as "correctly scoped".
    # Require a 200 AND rows of the decider's own before trusting the absence. (F-41.)
    r.truthy("C27", "notifications are per-user scoped (the decider has no requester row)",
             resp.status_code == 200 and decider_rows and not other,
             f"HTTP {resp.status_code}, decider rows={len(decider_rows)}, leaked={other}")

    resp = post_json(api, NOTIFY_MARK_READ_URL, {"all": True}, write_token)
    marked = body(resp)
    r.eq("C28", "POST mark-read clears the requester's unread count",
         (resp.status_code, marked.get("unread_total")), (200, 0))

    resp = api.get(f"{NOTIFY_URL}?unread=1", headers=bearer(decider_token))
    r.truthy("C29", "marking one user read leaves another user's rows alone",
             (body(resp).get("unread_total") or 0) > 0,
             "the decider's unread count was cleared too")

    # --- kind notify=[...] recipient assembly ------------------------------
    from apps.approvals import emails as approval_emails
    from apps.demo_access.approvals import AUDIT_MAILBOX

    with override_settings(
        SMALLSTACK_APPROVALS_EMAILS_ENABLED=True,
        MAILERS={
            "default": {
                "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
                "OPTIONS": {},
            }
        },
    ):
        from django.core import mail

        mail.outbox = []
        approval_emails.send_decided(req.pk)
        recipients = {addr for m in mail.outbox for addr in m.to}
    r.truthy("C30", "the kind's notify=[...] mailbox is on the decision email",
             AUDIT_MAILBOX in recipients, f"recipients={sorted(recipients)}")
    r.truthy("C31", "the requester is also on the decision email",
             svcbot.email in recipients, f"recipients={sorted(recipients)}")

    resp = client_for(opslead).get("/demo/access/requests/")
    r.eq("C32", "the staff console lists the access requests", resp.status_code, 200)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

SCENARIOS = {"a": run_scenario_a, "b": run_scenario_b, "c": run_scenario_c}


class Command(BaseCommand):
    help = "Run the approvals scenarios end to end and print PASS/FAIL per assertion."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("scenario", choices=["a", "b", "c", "all"])
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit non-zero if any assertion failed (CI / regression mode).",
        )
        parser.add_argument(
            "--verbose-logs",
            action="store_true",
            help="Keep application logging on (noisy; off by default so output stays greppable).",
        )
        parser.add_argument(
            "--keep",
            action="store_true",
            help="Keep the rows this run created (they are purged at the start of the next run).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["verbose_logs"]:
            # Up to ERROR: Scenario B deliberately makes a callback raise, and
            # its traceback would otherwise land in the middle of the report.
            # Every outcome is asserted explicitly, so nothing is hidden that
            # the report doesn't already state; --verbose-logs restores them.
            logging.disable(logging.ERROR)
        try:
            self._run(options)
        finally:
            logging.disable(logging.NOTSET)

    #: Minimum assertion count per scenario. A harness that silently ran fewer
    #: checks than it used to — because a scenario app is missing, or a section
    #: raised past a bare ``except`` — must not report green. Raise these when you
    #: add assertions; never lower them to make a run pass. (F-41.)
    EXPECTED_MIN = {"a": 30, "b": 35, "c": 37}

    def _preflight(self) -> None:
        """Refuse to run — rather than pass — when the harness cannot see the code.

        ``apps/demo_{purchasing,agentops,access}`` are the test contract, and they
        are not in ``INSTALLED_APPS`` on a stock checkout. Without this, a run on a
        tree that lacks them reports a green tally over whatever it *could* reach,
        which is the worst possible failure mode for a certification artifact.
        """
        from django.apps import apps as django_apps

        required = ["demo_purchasing", "demo_agentops", "demo_access", "approvals", "notifications"]
        missing = [label for label in required if not django_apps.is_installed(f"apps.{label}")]
        if missing:
            raise CommandError(
                "approval_scenario cannot certify anything without these apps in "
                f"INSTALLED_APPS: {', '.join(missing)}. A green tally over a subset "
                "of the feature is worse than no tally."
            )

    def _run(self, options: dict[str, Any]) -> None:
        self._preflight()
        ensure_users()
        try:
            get_user("admin")
        except LookupError as exc:
            raise CommandError(str(exc)) from None

        purged = purge_harness_rows()
        if purged:
            self.stdout.write(f"(purged {purged} rows from a previous harness run)")

        selected = ["a", "b", "c"] if options["scenario"] == "all" else [options["scenario"]]
        runners: dict[str, Runner] = {}

        # Emails are best-effort fan-out; silence the channel so the PASS/FAIL
        # lines stay the only output. Scenario C re-enables it for one check.
        with override_settings(SMALLSTACK_APPROVALS_EMAILS_ENABLED=False):
            for key in selected:
                runner = Runner(self)
                runners[key] = runner
                SCENARIOS[key](runner)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("== Tally =="))
        total_pass = total_fail = 0
        shortfalls: list[str] = []
        for key in selected:
            passed, failed = runners[key].tally(key)
            total_pass += passed
            total_fail += failed
            self.stdout.write(f"scenario {key.upper()}: {passed} pass, {failed} fail")
            expected = self.EXPECTED_MIN.get(key, 0)
            if passed + failed < expected:
                shortfalls.append(
                    f"scenario {key.upper()} ran {passed + failed} assertions, "
                    f"expected at least {expected}"
                )
        # A run that asserted less than it used to is a failure, not a pass.
        if shortfalls:
            total_fail += len(shortfalls)
            for line in shortfalls:
                self.stdout.write(self.style.ERROR(f"FAIL  --   {line}"))
        verdict = "PASS" if total_fail == 0 else "FAIL"
        style = self.style.SUCCESS if total_fail == 0 else self.style.ERROR
        self.stdout.write(style(f"RESULT: {verdict} ({total_pass} pass, {total_fail} fail)"))

        if total_fail:
            self.stdout.write("")
            self.stdout.write("Failed assertions:")
            for key in selected:
                for check in runners[key].checks:
                    if not check.ok:
                        self.stdout.write(f"  {check.ident}  {check.description}  ({check.detail})")

        if not options["keep"]:
            purge_harness_rows()

        if options["check"] and total_fail:
            raise SystemExit(1)
