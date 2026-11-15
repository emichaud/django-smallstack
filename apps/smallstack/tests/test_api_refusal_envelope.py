"""A REST delete refused for a cascade answers with the JSON error envelope (B7, R2-5)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def receiver_perms(monkeypatch):
    from apps.webhooks.views import WebhookReceiverCRUDView

    monkeypatch.setattr(WebhookReceiverCRUDView, "model_permissions", True)


def test_cascade_refusal_is_json(client, receiver_perms):
    from apps.webhooks.models import WebhookReceipt, WebhookReceiver

    staff = User.objects.create_user("b7-staff", password="p", is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(codename__in=["view_webhookreceiver", "delete_webhookreceiver"])
    )
    rcv = WebhookReceiver.objects.create(name="b7rcv", slug="b7rcv")
    WebhookReceipt.objects.create(receiver=rcv)
    _t, raw = APIToken.create_token(user=staff, name="b7")
    r = client.delete(
        reverse("webhooks-receivers-api-detail", kwargs={"pk": rcv.pk}), HTTP_AUTHORIZATION=f"Bearer {raw}"
    )
    assert r.status_code == 403
    assert r["Content-Type"].startswith("application/json")
    assert "webhook" in r.json()["errors"]["__all__"][0].lower()
    assert WebhookReceiver.objects.filter(pk=rcv.pk).exists()
