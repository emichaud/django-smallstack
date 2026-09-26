"""Scripted control-plane regressions (acceptance round 1, F-001/F-002/F-003/F-006).

The sc CLI, REST API, and MCP tools all drive the same ModelForm through
``apps.smallstack.form_bridge``. These tests pin the contract that round 1
found broken on every scripted surface:

- a partial update must round-trip a populated JSONField (F-001),
- create/update must accept the same native JSON shapes GET emits (F-002),
- an omitted field must fall back to the model default — critically
  ``require_signature=True`` (fails-open otherwise, F-003) and
  ``signature_header`` = ``services.SIGNATURE_HEADER`` (F-006; the default
  changed from "X-Signature" so a SmallStack→SmallStack pairing verifies out of
  the box — 2026-09-25 F-06).
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.smallstack.models import APIToken
from apps.webhooks import services
from apps.webhooks.models import WebhookEndpoint, WebhookReceiver

pytestmark = pytest.mark.django_db

ENDPOINTS_URL = "/smallstack/api/webhooks/endpoints/"
RECEIVERS_URL = "/smallstack/api/webhooks/receivers/"


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        username="wh_scripted", password="x", is_staff=True
    )


@pytest.fixture
def auth_header(staff):
    _, raw_key = APIToken.create_token(staff, name="wh-scripted")
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


def _sc(*argv, user):
    out = StringIO()
    call_command("sc", *argv, "--user", user.username, "--json", stdout=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# F-001 — sc set partial update keeps a populated JSONField
# ---------------------------------------------------------------------------


def test_sc_set_enabled_survives_populated_event_filter(staff):
    """The documented remediation `sc set webhook <pk> --enabled=true` must not
    die on 'event_filter: Enter a valid JSON.' when the filter is non-empty."""
    ep = WebhookEndpoint.objects.create(
        name="F001", target_url="https://hooks.example.com/f1",
        event_filter=["*"], headers={"X-Auth": "t"}, enabled=False,
    )
    _sc("set", "webhook", str(ep.pk), "--enabled=true", user=staff)
    ep.refresh_from_db()
    assert ep.enabled is True
    assert ep.event_filter == ["*"]     # untouched fields survive the merge
    assert ep.headers == {"X-Auth": "t"}


# ---------------------------------------------------------------------------
# F-002 — REST + MCP accept the native JSON shapes GET emits
# ---------------------------------------------------------------------------


def test_rest_create_accepts_native_json_array(client, auth_header):
    resp = client.post(
        ENDPOINTS_URL,
        data=json.dumps({
            "name": "F002",
            "target_url": "https://hooks.example.com/f2",
            "event_filter": ["*.created", "support.ticket.*"],
            "headers": {"X-Auth": "token"},
        }),
        content_type="application/json",
        **auth_header,
    )
    assert resp.status_code == 201, resp.content
    ep = WebhookEndpoint.objects.get(name="F002")
    assert ep.event_filter == ["*.created", "support.ticket.*"]
    assert ep.headers == {"X-Auth": "token"}
    # GET emits arrays — and now accepts them: the surface is symmetric.
    assert resp.json()["event_filter"] == ["*.created", "support.ticket.*"]


def test_rest_create_still_accepts_encoded_string(client, auth_header):
    """Backward compat: the previously-required double-encoded form keeps working."""
    resp = client.post(
        ENDPOINTS_URL,
        data=json.dumps({
            "name": "F002-str",
            "target_url": "https://hooks.example.com/f2s",
            "event_filter": '["*"]',
        }),
        content_type="application/json",
        **auth_header,
    )
    assert resp.status_code == 201, resp.content
    assert WebhookEndpoint.objects.get(name="F002-str").event_filter == ["*"]


def test_rest_patch_native_array_and_jsonfield_roundtrip(client, auth_header):
    ep = WebhookEndpoint.objects.create(
        name="F002-patch", target_url="https://hooks.example.com/f2p",
        event_filter=["*"],
    )
    # PATCH another field: the populated JSONField must round-trip (F-001 via REST)
    resp = client.patch(
        f"{ENDPOINTS_URL}{ep.pk}/",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
        **auth_header,
    )
    assert resp.status_code == 200, resp.content
    ep.refresh_from_db()
    assert ep.enabled is False
    assert ep.event_filter == ["*"]
    # PATCH the JSONField itself with a native array
    resp = client.patch(
        f"{ENDPOINTS_URL}{ep.pk}/",
        data=json.dumps({"event_filter": ["*.deleted"]}),
        content_type="application/json",
        **auth_header,
    )
    assert resp.status_code == 200, resp.content
    ep.refresh_from_db()
    assert ep.event_filter == ["*.deleted"]


def test_mcp_create_webhook_accepts_native_list(staff):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    handler = TOOL_HANDLERS["create_webhook"]
    ctx = set_context(ToolContext(user=staff, token=None))
    try:
        result = handler({
            "name": "F002-mcp",
            "target_url": "https://hooks.example.com/f2m",
            "event_filter": ["*.created"],
        })
    finally:
        reset_context(ctx)
    assert "errors" not in result, result
    assert WebhookEndpoint.objects.get(name="F002-mcp").event_filter == ["*.created"]


def test_mcp_input_schema_uses_valid_json_schema_types():
    """The factory schema must not advertise Django-internal type names like
    'text' or 'fk' — MCP clients validate against real JSON-Schema types."""
    from apps.mcp.server import TOOL_REGISTRY

    valid = {"string", "integer", "number", "boolean", "array", "object", "null"}
    for tool_name in ("create_webhook", "update_webhook", "create_webhook_receiver"):
        props = TOOL_REGISTRY[tool_name].input_schema["properties"]
        for fname, schema in props.items():
            declared = schema.get("type")
            types = declared if isinstance(declared, list) else [declared]
            for t in types:
                assert t in valid, f"{tool_name}.{fname}: invalid JSON-Schema type {t!r}"


# ---------------------------------------------------------------------------
# F-003 / F-006 — omitted fields fall back to model defaults
# ---------------------------------------------------------------------------


def test_sc_new_receiver_defaults_require_signature_and_header(staff):
    """[F-003] Omitting --require_signature must NOT store False (fails open);
    [F-006] --signature_header is optional (model default = the header
    SmallStack's own sender emits)."""
    _sc(
        "new", "webhookreceiver",
        "--name", "Stripe demo", "--slug", "stripe-demo",
        user=staff,
    )
    r = WebhookReceiver.objects.get(slug="stripe-demo")
    assert r.require_signature is True
    assert r.signature_header == services.SIGNATURE_HEADER
    assert r.enabled is True
    assert r.secret  # auto-generated model default survives the form path


def test_sc_new_receiver_explicit_false_still_wins(staff):
    _sc(
        "new", "webhookreceiver",
        "--name", "Unsigned", "--slug", "unsigned-demo",
        "--require_signature=false",
        user=staff,
    )
    assert WebhookReceiver.objects.get(slug="unsigned-demo").require_signature is False


def test_rest_create_receiver_defaults_require_signature(client, auth_header):
    resp = client.post(
        RECEIVERS_URL,
        data=json.dumps({"name": "GitHub", "slug": "github-in"}),
        content_type="application/json",
        **auth_header,
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["require_signature"] is True
    r = WebhookReceiver.objects.get(slug="github-in")
    assert r.require_signature is True
    assert r.signature_header == services.SIGNATURE_HEADER
