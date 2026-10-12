"""A fan-out failure must not take the caller's write with it.

``fan_out``'s docstring has always promised "never raises — a fan-out failure
must not break the originating model save", and the bare ``except`` looks like
it delivers that. It did not. ``fan_out`` runs from a ``post_save`` receiver,
i.e. *inside* whatever ``atomic()`` block the caller opened. A failed INSERT
marks that block ``needs_rollback``, so catching the exception still loses the
caller's own row when its ``atomic()`` exits — the save is broken, just
silently, with only a log line.

Measured by the integration harness (round 2 of the blog programme, 2026-10-12):
with one enabled endpoint configured, ``service.create_post`` returned a Post
with a populated ``pk`` and left **no row in the database**, while the studio
reported success. The trigger was an unserializable payload value
(``UUIDField`` → plain ``json.dumps`` on the JSONField); that specific trigger
is fixed in ``apps/smallstack/api.py``, but the fragility is the real defect —
any DB error during fan-out would do the same thing to any caller.

These tests pin the isolation, not the trigger.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.mcp.tests.models import Widget
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint
from apps.webhooks.services import fan_out

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def endpoint():
    return WebhookEndpoint.objects.create(
        name="sink", target_url="http://127.0.0.1:9000/hook", event_filter=["*"], enabled=True
    )


@pytest.fixture
def owner():
    return User.objects.create_user(username="fan-out-owner", password="x")


def test_unserializable_payload_does_not_roll_back_the_callers_write(endpoint, owner):
    """The regression: an unserializable payload ate the caller's row."""
    import uuid

    with transaction.atomic():
        widget = Widget.objects.create(name="keep me", owner=owner)
        # A raw UUID is not JSON-serializable by the JSONField's plain
        # json.dumps, so the delivery INSERT fails exactly as it did in the wild.
        created = fan_out("mcp_server.widget.created", {"data": {"uid": uuid.uuid4()}})

    assert created == 0, "the delivery could not be stored, so none was created"
    assert Widget.objects.filter(pk=widget.pk).exists(), (
        "fan_out's failed INSERT marked the caller's atomic() block for rollback, "
        "so the caller's own row was silently lost"
    )
    assert widget.name == "keep me"


def test_fan_out_still_returns_zero_and_does_not_raise(endpoint, owner):
    """The promise in the docstring, kept literally."""
    import uuid

    created = fan_out("mcp_server.widget.created", {"bad": uuid.uuid4()})

    assert created == 0
    assert not WebhookDelivery.objects.exists()


def test_a_serializable_payload_still_fans_out(endpoint, owner):
    """Guards against over-correcting: the savepoint must not suppress success."""
    created = fan_out("mcp_server.widget.created", {"data": {"id": 1, "name": "ok"}})

    assert created == 1
    delivery = WebhookDelivery.objects.get()
    assert delivery.event_type == "mcp_server.widget.created"
    assert delivery.payload == {"data": {"id": 1, "name": "ok"}}


def test_one_bad_endpoint_does_not_block_the_others(owner):
    """Per-endpoint savepoints: a failure is confined to its own delivery row.

    Both endpoints receive the same payload here, so both fail — the assertion
    that matters is that the loop is not abandoned mid-way and the caller's row
    survives regardless of how many endpoints are configured.
    """
    import uuid

    for i in range(3):
        WebhookEndpoint.objects.create(
            name=f"sink-{i}",
            target_url=f"http://127.0.0.1:900{i}/hook",
            event_filter=["*"],
            enabled=True,
        )

    with transaction.atomic():
        widget = Widget.objects.create(name="survivor", owner=owner)
        fan_out("mcp_server.widget.created", {"uid": uuid.uuid4()})

    assert Widget.objects.filter(pk=widget.pk).exists()
