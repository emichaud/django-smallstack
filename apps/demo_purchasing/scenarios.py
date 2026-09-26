"""Cross-scenario scaffolding shared by the two management commands.

``apps/demo_purchasing`` hosts the scaffolding (the user matrix, the demo API
tokens, the webhook wiring) and the two cross-scenario commands
(``seed_approval_scenarios``, ``approval_scenario``) because a scenario app has
to own them and A is the first. Nothing here is imported by the other two
scenario apps — the dependency runs one way only.

Everything is idempotent: re-running the seed converges on the same state.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.demo_purchasing.models import FINANCE_GROUP

# --- the user matrix -------------------------------------------------------
# username, password, is_staff, is_superuser, groups, what it is for.
# admin/admin (superuser) is created by `manage.py create_dev_superuser` and is
# listed here so the harness can find it; it is never modified.
USERS: list[dict[str, Any]] = [
    {
        "username": "opslead",
        "password": "opslead",
        "is_staff": True,
        "is_superuser": False,
        "groups": [],
        "role": "staff, NOT superuser — general approver; refused on HIGH-risk agent actions",
    },
    {
        "username": "finance",
        "password": "finance",
        "is_staff": False,
        "is_superuser": False,
        "groups": [FINANCE_GROUP],
        "role": "NON-staff finance approver — assignee on purchases ≥ $5,000",
    },
    {
        "username": "buyer",
        "password": "buyer",
        "is_staff": False,
        "is_superuser": False,
        "groups": [],
        "role": "NON-staff requester — raises purchase requests",
    },
    {
        "username": "agentbot",
        "password": "agentbot",
        "is_staff": False,
        "is_superuser": False,
        "groups": [],
        "role": "NON-staff AI-agent identity — files agentops.action over MCP",
    },
    {
        "username": "svcbot",
        "password": "svcbot",
        "is_staff": True,
        "is_superuser": False,
        "groups": [],
        "role": "staff REST client — files access.grant and polls it over REST",
    },
    {
        "username": "analyst",
        "password": "analyst",
        "is_staff": False,
        "is_superuser": False,
        "groups": [],
        "role": "NON-staff bystander — the ineligible-decider control",
    },
]

# --- the demo API tokens ---------------------------------------------------
# name, username, access_level, what it is for. Raw keys are printed by the
# seed (they cannot be read back) and re-minted on every seed run.
TOKENS: list[dict[str, str]] = [
    {
        "name": "demo: svcbot write",
        "username": "svcbot",
        "access_level": "staff",
        "role": "Scenario C: file + poll + decide over REST",
    },
    {
        "name": "demo: svcbot readonly",
        "username": "svcbot",
        "access_level": "readonly",
        "role": "Scenario C: the refused-write control",
    },
    {
        "name": "demo: agentbot",
        "username": "agentbot",
        "access_level": "auth",
        "role": "Scenario B: the AI agent's MCP/REST token (non-staff user)",
    },
    {
        "name": "demo: admin",
        "username": "admin",
        "access_level": "staff",
        "role": "superuser token — decides HIGH-risk agent actions",
    },
]

# --- webhook wiring --------------------------------------------------------
WEBHOOK_RECEIVER_SLUG = "access-grants"
WEBHOOK_ENDPOINT_NAME = "Approvals echo (local)"
WEBHOOK_SECRET = "demo-approvals-shared-secret"  # noqa: S105 — demo fixture, not a credential
WEBHOOK_EVENT_FILTER = ["smallstack_approvals.approvalrequest.*"]
# SmallStack signs outbound deliveries with services.SIGNATURE_HEADER
# ("X-SmallStack-Signature"), but WSGI header normalization makes the key Django
# hands the verifier "X-Smallstack-Signature" — and WebhookReceiver defaults to
# "X-Signature". So a SmallStack→SmallStack receiver must spell it exactly like
# this or every delivery is rejected. See the findings file.
WEBHOOK_SIGNATURE_HEADER = "X-Smallstack-Signature"


def ensure_group() -> Group:
    group, _ = Group.objects.get_or_create(name=FINANCE_GROUP)
    return group


def ensure_users() -> list[tuple[Any, bool]]:
    """Create/update the scenario users. Returns [(user, created), ...]."""
    User = get_user_model()
    ensure_group()
    out: list[tuple[Any, bool]] = []
    for spec in USERS:
        user, created = User.objects.get_or_create(
            username=spec["username"],
            defaults={
                "email": f"{spec['username']}@example.com",
                "is_staff": spec["is_staff"],
                "is_superuser": spec["is_superuser"],
            },
        )
        # Converge every run: flags and password are part of the fixture.
        user.email = f"{spec['username']}@example.com"
        user.is_staff = spec["is_staff"]
        user.is_superuser = spec["is_superuser"]
        user.is_active = True
        user.set_password(spec["password"])
        user.save()
        user.groups.set(Group.objects.filter(name__in=spec["groups"]))
        out.append((user, created))
    return out


def get_user(username: str) -> Any:
    """Fetch a scenario user, or raise a message the caller can print."""
    User = get_user_model()
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        raise LookupError(
            f"User {username!r} is missing — run `manage.py seed_approval_scenarios` "
            "(and `create_dev_superuser` for admin) first."
        ) from None


def mint_tokens() -> list[tuple[str, str, str, str]]:
    """Re-mint the demo tokens. Returns [(name, username, access_level, raw_key)].

    Raw keys cannot be read back, so an existing demo token is revoked and
    replaced — the seed prints the new keys.
    """
    from apps.smallstack.models import APIToken

    minted: list[tuple[str, str, str, str]] = []
    for spec in TOKENS:
        try:
            user = get_user(spec["username"])
        except LookupError:
            continue
        APIToken.objects.filter(user=user, name=spec["name"]).delete()
        _, raw = APIToken.create_token(
            user=user,
            name=spec["name"],
            description=spec["role"],
            access_level=spec["access_level"],
        )
        minted.append((spec["name"], spec["username"], spec["access_level"], raw))
    return minted


def ensure_webhook_wiring() -> tuple[Any, Any]:
    """The local loop: an outbound endpoint that posts approval events back into
    this instance's own inbound receiver, where demo_access records a WebhookEcho.

    Returns (endpoint, receiver). Idempotent, and deliberately NOT created via
    ``sc webhook pair``: pairing sets ``ignore_origin`` to our own origin, which
    would drop exactly the self-originated events this demo wants to observe.
    """
    from apps.demo_access.webhook_handlers import RECEIVER_SLUG
    from apps.webhooks.models import WebhookEndpoint, WebhookReceiver

    receiver, _ = WebhookReceiver.objects.get_or_create(
        slug=RECEIVER_SLUG,
        defaults={
            "name": "Approvals echo (local receiver)",
            "handler": RECEIVER_SLUG,
            "secret": WEBHOOK_SECRET,
            "signature_header": WEBHOOK_SIGNATURE_HEADER,
            "require_signature": True,
            "enabled": True,
        },
    )
    receiver_state: list[tuple[str, Any]] = [
        ("handler", RECEIVER_SLUG),
        ("secret", WEBHOOK_SECRET),
        ("signature_header", WEBHOOK_SIGNATURE_HEADER),
        ("require_signature", True),
        ("enabled", True),
        ("ignore_origin", ""),
    ]
    changed = False
    for field, value in receiver_state:
        if getattr(receiver, field) != value:
            setattr(receiver, field, value)
            changed = True
    if changed:
        receiver.save()

    target_url = f"http://127.0.0.1:8065/webhooks/in/{RECEIVER_SLUG}/"
    endpoint, _ = WebhookEndpoint.objects.get_or_create(
        name=WEBHOOK_ENDPOINT_NAME,
        defaults={
            "target_url": target_url,
            "secret": WEBHOOK_SECRET,
            "event_filter": WEBHOOK_EVENT_FILTER,
            "enabled": True,
        },
    )
    endpoint_state: list[tuple[str, Any]] = [
        ("target_url", target_url),
        ("secret", WEBHOOK_SECRET),
        ("event_filter", WEBHOOK_EVENT_FILTER),
        ("enabled", True),
    ]
    changed = False
    for field, value in endpoint_state:
        if getattr(endpoint, field) != value:
            setattr(endpoint, field, value)
            changed = True
    if changed:
        endpoint.save()
    return endpoint, receiver
