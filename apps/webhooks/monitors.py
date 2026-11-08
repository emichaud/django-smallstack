"""Webhooks status monitor — are deliveries getting through?

Three failure signals, mirroring the scheduler monitor's shape: a backlog of
overdue retries (the delivery tick isn't firing / is wedged), deliveries never
attempted (no worker on the ``webhooks`` queue), and a high recent-failure
ratio (with a minimum sample) each trip DOWN.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.smallstack.monitors import CheckResult, Monitor, Service

SERVICE_KEY = "webhooks"


class WebhooksService(Service):
    key = SERVICE_KEY
    title = "Webhooks"
    description = "Outbound event delivery"
    category = "core"
    order = 45
    icon = (
        '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 16.98h-5.99c-1.66 0-3.01-1.34-3.01-3s1.35-3 3.01-3H18"/>'
        '<path d="M8 8.01a3 3 0 1 0 0 6"/></svg>'
    )
    detail_url_name = "webhooks_dashboard"


class WebhooksMonitor(Monitor):
    key = "webhooks-delivery"
    service = SERVICE_KEY
    title = "Webhook delivery healthy"
    order = 10
    detail_url_name = "webhooks_dashboard"

    def _grace(self) -> int:
        # A retry overdue by more than this ⇒ the delivery tick isn't firing.
        return int(getattr(settings, "SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS", 300))

    def _min_sample(self) -> int:
        return int(getattr(settings, "SMALLSTACK_SCHEDULER_FAILURE_MIN_SAMPLE", 5))

    def check(self) -> CheckResult:
        from .models import WebhookDelivery, WebhookEndpoint

        now = timezone.now()
        overdue = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.RETRYING,
            next_attempt_at__isnull=False,
            next_attempt_at__lt=now - timedelta(seconds=self._grace()),
        ).count()
        if overdue:
            return CheckResult.down(note=f"{overdue} retry(ies) overdue — delivery tick not firing?")

        # Never attempted, well past the grace: nothing is draining the
        # ``webhooks`` queue (a worker started with only default,email). These
        # never reach RETRYING or DEAD, so the checks above can't see them.
        unclaimed = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.PENDING,
            attempt=0,
            created_at__lt=now - timedelta(seconds=self._grace()),
        ).count()
        if unclaimed:
            return CheckResult.down(
                note=f"{unclaimed} delivery(ies) never attempted — is a worker draining the webhooks queue?"
            )

        recent = WebhookDelivery.objects.filter(created_at__gte=now - timedelta(hours=1))
        total = recent.count()
        dead = recent.filter(status=WebhookDelivery.Status.DEAD).count()
        if total >= self._min_sample() and dead / total > 0.5:
            return CheckResult.down(note=f"{dead}/{total} deliveries gave up in the last hour")

        active = WebhookEndpoint.objects.filter(enabled=True).count()
        return CheckResult.up(note=f"{active} active endpoint(s)")

    def inventory(self) -> dict:
        """Live: the endpoints + receivers behind the webhooks surface (cheap
        counts + links, mirroring the api/mcp/search drill-downs)."""
        from django.urls import NoReverseMatch, reverse

        from .models import WebhookEndpoint, WebhookReceiver

        def _url(name: str, pk: int) -> str | None:
            try:
                return reverse(name, kwargs={"pk": pk})
            except NoReverseMatch:
                return None

        items = [
            {
                "label": e.name,
                "meta": f"endpoint · {'on' if e.enabled else 'off'}",
                "url": _url("webhooks/endpoints-detail", e.pk),
            }
            for e in WebhookEndpoint.objects.only("id", "name", "enabled")
        ] + [
            {
                "label": r.name,
                "meta": f"receiver · {'on' if r.enabled else 'off'}",
                "url": _url("webhooks/receivers-detail", r.pk),
            }
            for r in WebhookReceiver.objects.only("id", "name", "enabled")
        ]
        n_end = WebhookEndpoint.objects.count()
        n_rec = WebhookReceiver.objects.count()
        summary = (
            f"{n_end} endpoint{'' if n_end == 1 else 's'} · "
            f"{n_rec} receiver{'' if n_rec == 1 else 's'}"
        )
        return {"ok": bool(getattr(settings, "SMALLSTACK_WEBHOOKS_ENABLED", True)), "summary": summary, "items": items}
