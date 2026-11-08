"""Outbound deliveries run on their own task queue, with a fallback.

The ``webhooks`` queue lets a dedicated worker drain deliveries (each can wait
up to SMALLSTACK_WEBHOOK_TIMEOUT on a slow endpoint) so they can't hold up
sign-in emails or scheduled jobs on the shared worker. A project whose TASKS
setting doesn't list the queue must keep delivering on ``default``.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.core.management import call_command
from django_tasks_db.management.commands.db_worker import Worker
from django_tasks_db.models import DBTaskResult

from apps.webhooks import services
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint

DB_TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email", "webhooks"],
    }
}


@pytest.fixture(autouse=True)
def _allow_private(settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = True


class TestDeliveryQueue:
    def test_uses_the_webhooks_queue_when_configured(self):
        assert services.delivery_queue() == "webhooks"

    def test_falls_back_to_default_when_tasks_lacks_it(self, settings):
        settings.TASKS = {
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
                "QUEUES": ["default", "email"],
            }
        }
        assert services.delivery_queue() == "default"

    def test_a_backend_accepting_any_queue_gets_the_named_one(self, settings):
        settings.TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend", "QUEUES": []}}
        assert services.delivery_queue() == "webhooks"

    def test_queue_name_is_configurable(self, settings):
        settings.SMALLSTACK_WEBHOOK_QUEUE = "outbound"
        settings.TASKS = {
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
                "QUEUES": ["default", "outbound"],
            }
        }
        assert services.delivery_queue() == "outbound"


@pytest.mark.django_db(transaction=True)
class TestRealWorkerRouting:
    """Through the database backend and the real db_worker, as the container runs it."""

    def _worker(self, **queues) -> None:
        with mock.patch.object(Worker, "configure_signals"):
            call_command("db_worker", batch=True, startup_delay=False, worker_id="t", verbosity=0, **queues)

    def _queued_delivery(self) -> WebhookDelivery:
        ep = WebhookEndpoint.objects.create(name="e", target_url="http://127.0.0.1:9/hook")
        delivery = WebhookDelivery.objects.create(endpoint=ep, event_type="t.ping", payload={"x": 1})
        services._enqueue_delivery(delivery.pk)
        return delivery

    def test_main_worker_skips_deliveries_and_the_webhooks_worker_sends_them(self, settings):
        settings.TASKS = DB_TASKS
        delivery = self._queued_delivery()
        row = DBTaskResult.objects.get()
        assert row.queue_name == "webhooks"

        self._worker(queue_name="*", exclude_queues="webhooks")  # the main inline worker
        delivery.refresh_from_db()
        assert delivery.attempt == 0
        assert DBTaskResult.objects.get().status == "READY"

        resp = mock.MagicMock(status=200)
        resp.__enter__.return_value = resp
        with mock.patch("apps.webhooks.tasks._open", return_value=resp) as sent:
            self._worker(queue_name="webhooks")  # the dedicated worker
        assert sent.call_count == 1
        delivery.refresh_from_db()
        assert delivery.attempt == 1 and delivery.status == "success"

    def test_without_the_queue_configured_the_shared_worker_still_delivers(self, settings):
        settings.TASKS = {"default": {**DB_TASKS["default"], "QUEUES": ["default", "email"]}}
        delivery = self._queued_delivery()
        assert DBTaskResult.objects.get().queue_name == "default"

        resp = mock.MagicMock(status=200)
        resp.__enter__.return_value = resp
        with mock.patch("apps.webhooks.tasks._open", return_value=resp):
            self._worker(queue_name="*")
        delivery.refresh_from_db()
        assert delivery.status == "success"


@pytest.mark.django_db
def test_monitor_goes_down_when_deliveries_sit_unattempted():
    # A worker started with only "default,email" leaves deliveries PENDING at
    # attempt 0 forever; they never retry or die, so the monitor said UP.
    from datetime import timedelta

    from django.utils import timezone

    from apps.webhooks.monitors import WebhooksMonitor

    ep = WebhookEndpoint.objects.create(name="e", target_url="http://127.0.0.1:9/hook")
    fresh = WebhookDelivery.objects.create(endpoint=ep, event_type="t.ping", payload={})
    assert WebhooksMonitor().check().ok  # just queued: within the grace
    WebhookDelivery.objects.filter(pk=fresh.pk).update(created_at=timezone.now() - timedelta(hours=1))
    result = WebhooksMonitor().check()
    assert not result.ok
    assert "never attempted" in result.note
