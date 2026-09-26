"""Webhook views — CRUDViews (admin+REST+MCP+search), the dashboard, the inbound
receiver endpoint, the delivery tick, and the test/replay/reveal actions."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import F
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

from . import services
from .models import WebhookDelivery, WebhookEndpoint, WebhookReceipt, WebhookReceiver

logger = logging.getLogger("smallstack.webhooks")

LOCALHOST_IPS = {"127.0.0.1", "::1"}


class EventFilterWidget(forms.Widget):
    """A pattern picker for ``event_filter`` (F-015): checkboxes for the events models
    actually emit, plus a free-text box for custom/wildcard patterns. Serializes to the
    same JSON list the field stored before — so it's a pure UI upgrade over the raw
    textarea, backward-compatible on read and write.
    """

    template_name = None  # rendered inline below

    def value_from_datadict(self, data, files, name):
        import json as _json

        # Scripted surfaces (REST/MCP/CLI) post the field directly by its own name — pass
        # that straight through so the picker is a pure web-UI upgrade, not a new contract.
        picker_keys = f"{name}_choice" in data or f"{name}_extra" in data
        if not picker_keys and name in data:
            return data.get(name)

        chosen = data.getlist(f"{name}_choice") if hasattr(data, "getlist") else data.get(f"{name}_choice", [])
        extra_raw = (data.get(f"{name}_extra") or "").strip()
        patterns = list(dict.fromkeys(chosen))  # de-dupe, keep order
        for line in extra_raw.replace(",", "\n").splitlines():
            p = line.strip()
            if p and p not in patterns:
                patterns.append(p)
        return _json.dumps(patterns)

    def render(self, name, value, attrs=None, renderer=None):
        import json as _json

        from django.utils.html import format_html, format_html_join
        from django.utils.safestring import mark_safe

        current: list[str] = []
        if value:
            try:
                current = value if isinstance(value, list) else _json.loads(value)
            except (ValueError, TypeError):
                current = []

        options = services.available_events()
        known = set(options)
        extra = [p for p in current if p not in known]

        checkboxes = format_html_join(
            "",
            '<label style="display:block; font-size:0.85rem; margin:2px 0;">'
            '<input type="checkbox" name="{}_choice" value="{}"{}> <code>{}</code>'
            '<span style="color:var(--body-quiet-color);">{}</span></label>',
            (
                (
                    name,
                    opt,
                    mark_safe(" checked") if opt in current else "",
                    opt,
                    f" — {hint}" if (hint := services.describe_event_pattern(opt)) else "",
                )
                for opt in options
            ),
        )
        extra_id = f"id_{name}_extra"
        # Static markup, no interpolation — mark_safe (format_html requires args).
        pattern_help = mark_safe(
            '<details class="help-pop">'
            '<summary aria-label="Help: what event patterns look like">?</summary>'
            '<div class="help-pop-panel">'
            "<p>Patterns match the full event name — <code>app.model.action</code> — "
            "with <code>*</code> standing for any part. One pattern per line.</p>"
            '<div class="help-pop-examples">'
            "<div><code>support.ticket.*</code><span>every Ticket event</span></div>"
            "<div><code>support.*</code><span>everything from the support app</span></div>"
            "<div><code>*.deleted</code><span>any record is deleted</span></div>"
            "<div><code>crm.contact.merged</code><span>one exact event</span></div>"
            "</div></div></details>"
        )
        # The custom-pattern box is an advanced/programmatic surface, so it is
        # collapsed to one quiet line when empty. It MUST render (expanded)
        # whenever patterns exist — they usually arrive via REST/MCP/CLI, and a
        # UI save with the textarea absent would silently strip them.
        extra_summary = (
            format_html(
                "Custom patterns <span style=\"color:var(--warning-fg);\">({} set)</span>",
                len(extra),
            )
            if extra
            else mark_safe('Custom patterns <span style="opacity:0.7;">(advanced)</span>')
        )
        return format_html(
            '<div class="event-filter-picker">'
            '<div style="max-height:180px; overflow:auto; border:1px solid var(--card-border);'
            ' border-radius:6px; padding:6px 10px; margin-bottom:6px;">{}</div>'
            '<details class="event-filter-custom"{}>'
            '<summary style="font-size:0.8rem; color:var(--body-quiet-color); cursor:pointer;">{}</summary>'
            '<div style="display:flex; align-items:center; gap:0.4rem; margin-top:0.35rem;">'
            '<label for="{}" style="font-size:0.8rem; color:var(--body-quiet-color);">'
            "One per line, e.g. <code>support.ticket.*</code></label>{}</div>"
            '<textarea id="{}" name="{}_extra" rows="2" class="vTextField" style="width:100%;">{}</textarea>'
            "</details>"
            "</div>",
            checkboxes,
            mark_safe(" open") if extra else "",
            extra_summary,
            extra_id,
            pattern_help,
            extra_id,
            name,
            "\n".join(extra),
        )


def _with_write_only_secret(base_form_class):
    """Add a write-only ``secret`` field to a generated CRUD form.

    The secret must be *settable* (a provider hands you Stripe's ``whsec_…``;
    an operator wants a known signing key) but never *readable* — it stays out
    of every serialized surface and is only recoverable via the staff-gated
    reveal action. Blank means "keep the current secret" on update and
    "auto-generate" on create, so the field is always safe to omit.
    """

    class SecretForm(base_form_class):
        secret = forms.CharField(
            required=False,
            widget=forms.PasswordInput(
                render_value=False,
                attrs={"class": "vTextField", "autocomplete": "new-password"},
            ),
            help_text=(
                "Write-only. Leave blank to keep the current secret "
                "(a new one is generated on create)."
            ),
        )

        def save(self, commit=True):
            obj = super().save(commit=False)
            value = self.cleaned_data.get("secret")
            if value:
                obj.secret = value
            if commit:
                obj.save()
                self.save_m2m()
            return obj

    SecretForm.__name__ = f"{base_form_class.__name__}WithSecret"
    return SecretForm


def _status_color(value: str | None) -> str:
    from django.utils.html import format_html

    color = {
        "success": "var(--success-fg)",
        "pending": "var(--body-quiet-color)",
        "retrying": "var(--warning-fg)",
        "failed": "var(--error-fg)",
        "dead": "var(--error-fg)",
        "accepted": "var(--body-quiet-color)",
        "processed": "var(--success-fg)",
        "rejected": "var(--error-fg)",
    }.get(value or "", "var(--body-quiet-color)")
    return format_html('<span style="color: {};">{}</span>', color, value or "—")


def _delivery_status(value: Any, obj: Any) -> Any:
    return _status_color(obj.status)


def _endpoint_status(value: Any, obj: Any) -> Any:
    return _status_color(obj.last_status or "")


def _receipt_status(value: Any, obj: Any) -> Any:
    return _status_color(obj.status)


# ---------------------------------------------------------------------------
# CRUDViews — the free admin + REST + MCP + search surfaces
# ---------------------------------------------------------------------------


class WebhookEndpointCRUDView(CRUDView):
    """Outbound endpoints — operator- and agent-managed, so REST + MCP are on.

    ``secret`` is deliberately excluded from every serialized surface (list,
    detail, API, MCP): it's auto-generated and only revealed through the staff-only
    reveal action. Only ``secret_preview`` is ever shown.
    """

    model = WebhookEndpoint
    fields = ["name", "target_url", "event_filter", "headers", "transform", "auth_scheme", "enabled"]
    list_fields = ["name", "target_url", "enabled", "last_status", "total_deliveries"]
    detail_fields = [
        "name",
        "target_url",
        "event_filter",
        "headers",
        "transform",
        "auth_scheme",
        "enabled",
        "is_paired",
        "last_status",
        "total_deliveries",
        "consecutive_failures",
        "last_delivery_at",
    ]
    link_field = "name"
    field_transforms = {"last_status": _endpoint_status}
    url_base = "webhooks/endpoints"
    paginate_by = 25
    mixins = [StaffRequiredMixin]

    enable_api = True
    api_extra_fields = ["last_status", "total_deliveries", "consecutive_failures", "last_delivery_at"]

    enable_mcp = True
    mcp_description = (
        "an outbound webhook endpoint — a URL that receives a signed POST when a "
        "subscribed model event fires. event_filter holds fnmatch patterns over "
        "'<app>.<model>.<action>' (e.g. 'scheduler.scheduledjob.*')."
    )
    mcp_singular = "webhook"
    mcp_plural = "webhooks"

    enable_search = True
    search_fields = ["name", "target_url"]
    search_display = "name"
    search_subtitle = "target_url"


class WebhookDeliveryCRUDView(CRUDView):
    """Read-only outbound delivery history."""

    model = WebhookDelivery
    fields = ["endpoint", "event_type", "status", "attempt", "response_status", "created_at"]
    list_fields = ["endpoint", "event_type", "status", "attempt", "response_status", "created_at"]
    detail_fields = [
        "endpoint",
        "event_type",
        "payload",
        "status",
        "attempt",
        "max_attempts",
        "next_attempt_at",
        "response_status",
        "response_ms",
        "error",
        "task_result_id",
        "created_at",
    ]
    link_field = "event_type"
    field_transforms = {"status": _delivery_status}
    url_base = "webhooks/deliveries"
    paginate_by = 30
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]

    enable_api = True
    api_expand_fields = ["endpoint"]


class WebhookReceiverCRUDView(CRUDView):
    """Inbound receivers — external systems POST to /webhooks/in/<slug>/."""

    model = WebhookReceiver
    fields = [
        "name", "slug", "handler", "signature_header", "require_signature",
        "verifier", "challenge", "ignore_origin", "enabled",
    ]
    list_fields = ["name", "slug", "handler", "enabled", "total_received"]
    detail_fields = [
        "name",
        "slug",
        "handler",
        "signature_header",
        "require_signature",
        "verifier",
        "challenge",
        "ignore_origin",
        "enabled",
        "is_paired",
        "total_received",
        "last_received_at",
    ]
    link_field = "name"
    url_base = "webhooks/receivers"
    paginate_by = 25
    mixins = [StaffRequiredMixin]

    enable_api = True
    api_extra_fields = ["total_received", "last_received_at"]

    enable_mcp = True
    mcp_description = (
        "an inbound webhook receiver — a slug-addressed endpoint at "
        "/webhooks/in/<slug>/ that verifies a signature and runs a registered handler."
    )
    mcp_singular = "webhook_receiver"
    mcp_plural = "webhook_receivers"


# Write-only secret on both config models (create/update via any surface;
# reads still go through the staff-gated reveal actions only).
_EndpointForm = _with_write_only_secret(WebhookEndpointCRUDView._make_form_class())
# F-015: replace the raw event_filter JSON textarea with the pattern picker.
if "event_filter" in _EndpointForm.base_fields:
    _EndpointForm.base_fields["event_filter"].widget = EventFilterWidget()
    _EndpointForm.base_fields["event_filter"].help_text = (
        "Pick the events to subscribe to, or add custom fnmatch patterns."
    )

    def _clean_event_filter(self):
        """Reject malformed patterns on every surface (HTML, REST, MCP, CLI all
        validate through this form). A typo is valid JSON, so without this it
        became a pattern that silently matches nothing — an endpoint that just
        never fires, with no error anywhere."""
        value = self.cleaned_data.get("event_filter") or []
        errors = services.validate_event_patterns(value)
        if errors:
            raise forms.ValidationError(errors)
        return value

    _EndpointForm.clean_event_filter = _clean_event_filter
WebhookEndpointCRUDView.form_class = _EndpointForm

WebhookReceiverCRUDView.form_class = _with_write_only_secret(
    WebhookReceiverCRUDView._make_form_class()
)


class WebhookReceiptCRUDView(CRUDView):
    """Read-only inbound receipt history."""

    model = WebhookReceipt
    fields = ["receiver", "status", "verified", "source_ip", "received_at"]
    list_fields = ["receiver", "status", "verified", "source_ip", "received_at"]
    detail_fields = [
        "receiver",
        "status",
        "verified",
        "source_ip",
        "headers",
        "body",
        "error",
        "task_result_id",
        "received_at",
    ]
    link_field = "received_at"
    field_transforms = {"status": _receipt_status}
    url_base = "webhooks/receipts"
    paginate_by = 30
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]

    enable_api = True
    api_expand_fields = ["receiver"]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class WebhooksDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "webhooks/dashboard.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        day_ago = now - timedelta(hours=24)
        deliveries = WebhookDelivery.objects.filter(created_at__gte=day_ago)

        ctx["active_endpoints"] = WebhookEndpoint.objects.filter(enabled=True).count()
        ctx["total_endpoints"] = WebhookEndpoint.objects.count()
        ctx["delivered_24h"] = deliveries.filter(status=WebhookDelivery.Status.SUCCESS).count()
        ctx["retrying"] = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.RETRYING
        ).count()
        ctx["dead_24h"] = deliveries.filter(status=WebhookDelivery.Status.DEAD).count()
        ctx["dead_total"] = WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.DEAD
        ).count()
        ctx["recent_deliveries"] = (
            WebhookDelivery.objects.select_related("endpoint").order_by("-created_at")[:15]
        )
        ctx["active_receivers"] = WebhookReceiver.objects.filter(enabled=True).count()
        ctx["recent_receipts"] = (
            WebhookReceipt.objects.select_related("receiver").order_by("-received_at")[:10]
        )
        # The pairing panel reuses the endpoint form's event picker (F-015) so
        # "which events cross the link" is chosen from what models actually
        # emit, not typed as raw JSON. "*" pre-checked = the old default.
        ctx["pair_events_picker"] = EventFilterWidget().render("events", '["*"]')
        return ctx


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@require_POST
def test_endpoint(request: HttpRequest, pk: int) -> HttpResponse:
    """Fire a sample signed delivery to an endpoint so an operator can confirm
    reachability without waiting for a real event."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    endpoint = get_object_or_404(WebhookEndpoint, pk=pk)
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_type="webhooks.test.ping",
        payload={
            "event": "webhooks.test.ping",
            "action": "test",
            "occurred_at": timezone.now().isoformat(),
            "data": {"message": "This is a test delivery from SmallStack."},
        },
        max_attempts=1,
    )
    services._enqueue_delivery(delivery.pk)
    messages.success(request, f"Test delivery queued for “{endpoint.name}”.")
    if not endpoint.enabled:
        messages.warning(
            request,
            f"“{endpoint.name}” is disabled — test/replay sends still go out, "
            "but signal events will not deliver until it is re-enabled.",
        )
    return redirect("webhooks/endpoints-detail", pk=pk)


@require_POST
def replay_delivery(request: HttpRequest, pk: int) -> HttpResponse:
    """Re-send a past delivery (e.g. one that died) as a fresh attempt."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    original = get_object_or_404(WebhookDelivery.objects.select_related("endpoint"), pk=pk)
    replay = WebhookDelivery.objects.create(
        endpoint=original.endpoint,
        event_type=original.event_type,
        payload=original.payload,
        event_id=original.event_id,  # reuse the stable key so a consumer dedupes (F-021)
        max_attempts=original.max_attempts,
    )
    services._enqueue_delivery(replay.pk)
    messages.success(request, f"Replayed delivery #{original.pk} as #{replay.pk}.")
    if not original.endpoint.enabled:
        messages.warning(
            request,
            f"“{original.endpoint.name}” is disabled — the replay still goes out, "
            "but signal events will not deliver until it is re-enabled.",
        )
    return redirect("webhooks/deliveries-detail", pk=replay.pk)


@require_POST
def pair_smallstack(request: HttpRequest) -> HttpResponse:
    """'Connect a SmallStack' (F-027/F-031): configure THIS instance's half of a loop-safe
    two-way link (two per-direction secrets) and hand the operator the mirror command for
    the peer. Touches only the local instance — it does not reach the peer."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    target = (request.POST.get("target_url") or "").strip()
    if not target:
        messages.error(request, "A peer SmallStack inbound URL is required to pair.")
        return redirect("webhooks_dashboard")
    # The dashboard posts picker keys (events_choice / events_extra); scripted
    # callers post raw `events` JSON. The widget's value_from_datadict handles
    # both, so the API contract is unchanged.
    events_raw = (EventFilterWidget().value_from_datadict(request.POST, None, "events") or "").strip()
    import json as _json

    events = ["*"]
    if events_raw:
        try:
            events = _json.loads(events_raw)
        except ValueError:
            messages.error(request, 'Events must be a JSON list, e.g. ["*"].')
            return redirect("webhooks_dashboard")
    if not events:
        messages.error(
            request,
            "Select at least one event to pair — leave “*” checked to forward everything.",
        )
        return redirect("webhooks_dashboard")
    pattern_errors = services.validate_event_patterns(events)
    if pattern_errors:
        messages.error(request, " ".join(pattern_errors))
        return redirect("webhooks_dashboard")
    # Advisory only — a pattern may target events that appear later.
    dead = services.unmatched_patterns(events)
    if dead:
        messages.warning(
            request,
            "Heads up: "
            + ", ".join(f"“{p}”" for p in dead)
            + " matches nothing this instance currently emits. "
            "It will apply if such events appear later.",
        )
    one_way = request.POST.get("one_way") in {"1", "true", "on"}
    result = services.pair_smallstack(
        target_url=target, events=events, one_way=one_way, owner=request.user
    )
    # Show the two secrets + peer mirror command ONCE, in a clearly-marked block. Django
    # messages are consumed on the next render (shown once) and are not written to the
    # server/audit log — unlike a logger call, so no plaintext secret leaks there.
    half = "the one-way outbound half" if one_way else "half 1 of 2"
    lines = [
        f"Configured this instance's {half} of the link to {target}. "
        "This touched THIS instance only — nothing was sent to the peer.",
        "── SECRETS (copy now — shown once) ──",
        f"send secret (we sign outbound): {result['send_secret']}",
    ]
    if not one_way:
        lines.append(f"recv secret (we verify inbound): {result['recv_secret']}")
        lines.append("⇒ Half 2 of 2 — run this on the peer to finish (secrets already swapped):")
        lines.append(result["mirror_command"])
    lines.append(
        "Retrieve secrets later via the staff Reveal action here; rotate via Rotate."
    )
    messages.success(request, "\n".join(lines))
    for warning in result.get("warnings") or []:
        # e.g. a loopback target blocked by the SSRF guard — say it here rather
        # than leaving it buried in a failed delivery's error field. (F-06.)
        messages.warning(request, warning)
    return redirect("webhooks/endpoints-detail", pk=result["endpoint_id"])


@require_POST
def replay_dead_deliveries(request: HttpRequest) -> HttpResponse:
    """Bulk-replay every dead delivery as a fresh attempt (F-023). The dead-letter
    recovery action after an outage — one click instead of one id at a time."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    new_ids = services.replay_dead(limit=1000)
    if new_ids:
        messages.success(request, f"Replayed {len(new_ids)} dead delivery(ies).")
    else:
        messages.info(request, "No dead deliveries to replay.")
    return redirect("webhooks_dashboard")


@require_POST
def reveal_secret(request: HttpRequest, pk: int) -> JsonResponse:
    """Return an endpoint's full signing secret (staff-only, on demand)."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return JsonResponse({"error": "forbidden"}, status=403)
    endpoint = get_object_or_404(WebhookEndpoint, pk=pk)
    return JsonResponse({"secret": endpoint.secret})


@require_POST
def rotate_secret(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate a new signing secret for an endpoint (invalidates the old one)."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    from .models import generate_secret

    endpoint = get_object_or_404(WebhookEndpoint, pk=pk)
    endpoint.secret = generate_secret()
    endpoint.save(update_fields=["secret", "updated_at"])
    messages.success(request, f"Signing secret rotated for “{endpoint.name}”.")
    return redirect("webhooks/endpoints-detail", pk=pk)


@require_POST
def reveal_receiver_secret(request: HttpRequest, pk: int) -> JsonResponse:
    """Return a receiver's full verifying secret (staff-only, on demand) —
    parity with the endpoint reveal."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return JsonResponse({"error": "forbidden"}, status=403)
    receiver = get_object_or_404(WebhookReceiver, pk=pk)
    return JsonResponse({"secret": receiver.secret})


@require_POST
def rotate_receiver_secret(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate a new verifying secret for a receiver (senders must re-sync)."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    from .models import generate_secret

    receiver = get_object_or_404(WebhookReceiver, pk=pk)
    receiver.secret = generate_secret()
    receiver.save(update_fields=["secret", "updated_at"])
    messages.success(request, f"Verifying secret rotated for “{receiver.name}”.")
    return redirect("webhooks/receivers-detail", pk=pk)


# ---------------------------------------------------------------------------
# Delivery tick (localhost, mirrors scheduler_tick)
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
def webhooks_tick(request: HttpRequest) -> JsonResponse:
    """Localhost-only endpoint for cron to drive the retry tick inside gunicorn.

    Mirrors scheduler_tick / heartbeat_ping. Use exactly one trigger per
    deployment (this, the run_due_deliveries command, or fold into scheduler_beat).
    """
    if request.META.get("REMOTE_ADDR", "") not in LOCALHOST_IPS:
        return JsonResponse({"error": "forbidden"}, status=403)
    claimed = services.run_due_deliveries()
    return JsonResponse({"claimed": claimed})


# ---------------------------------------------------------------------------
# Inbound receiver — the public endpoint external systems POST to
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
def incoming_webhook(request: HttpRequest, slug: str) -> HttpResponse:
    """Receive an external POST, verify its signature, record a receipt, and queue
    the registered handler. Returns 202 fast; 401 on bad signature; 404 for an
    unknown/disabled receiver."""
    if not getattr(settings, "SMALLSTACK_WEBHOOKS_ENABLED", True) or not getattr(
        settings, "SMALLSTACK_WEBHOOKS_INBOUND", True
    ):
        return JsonResponse({"error": "inbound webhooks disabled"}, status=404)

    receiver = WebhookReceiver.objects.filter(slug=slug, enabled=True).first()
    if receiver is None:
        return JsonResponse({"error": "no such receiver"}, status=404)

    from . import hooks

    # 1. Challenge/handshake seam (F-026): runs before verify/dispatch. A provider's
    #    validation handshake (Event Grid validationCode, SNS SubscribeURL) returns a
    #    response here to short-circuit; None ⇒ fall through to normal dispatch.
    challenge = hooks.get_challenge(receiver.challenge)
    if challenge is not None:
        try:
            resp = challenge(request, receiver)
        except Exception:  # noqa: BLE001 — a broken challenge must not 500 the sender
            resp = None
        if resp is not None:
            return resp

    # Size cap before the body is read or anything touches the DB — this route
    # is public and unauthenticated. (Audit 2026-09-13, C6.)
    max_bytes = int(getattr(settings, "SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES", 1_048_576))
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > max_bytes:
        return JsonResponse({"error": "payload too large"}, status=413)

    raw = request.body
    if len(raw) > max_bytes:
        return JsonResponse({"error": "payload too large"}, status=413)
    origin = request.headers.get(services.ORIGIN_HEADER, "")

    # 2. Verifier seam (F-016): default "hmac" is the current raw-body HMAC check;
    #    a provider scheme (Stripe t.body, GitHub sha256=) is a plug-in.
    verifier = hooks.get_verifier(receiver.verifier)
    try:
        # Case-INSENSITIVE, and a real mutable dict. HTTP header names are
        # case-insensitive and Django's HttpHeaders honours that; a plain
        # `dict(request.headers)` froze Django's own canonicalisation, so a
        # receiver configured with the documented "X-SmallStack-Signature"
        # spelling silently 401'd while an undocumented "X-Smallstack-Signature"
        # worked (F-06). The first fix used Django's CaseInsensitiveMapping, which
        # is IMMUTABLE — narrowing a seam documented as `dict[str, str]`, so a
        # third-party verifier doing `headers.pop(...)` started 401ing on a
        # correct credential (F-37). hooks.CaseInsensitiveDict satisfies both.
        header_map = hooks.CaseInsensitiveDict(request.headers)
        verified = bool(verifier(raw, header_map, receiver))
    except Exception:
        # A broken verifier fails CLOSED (unverified) — but never silently. This
        # exception used to be swallowed whole, so a verifier raising on a
        # perfectly good signature was indistinguishable from a forged one, with
        # nothing in the log to diagnose. (F-37.)
        logger.exception(
            "webhooks: verifier %r raised for receiver %r — treating the delivery "
            "as UNVERIFIED. Fix the verifier; a raised exception is not a rejection.",
            receiver.verifier or "hmac",
            receiver.slug,
        )
        verified = False

    # Snapshot a safe subset of headers (never store cookies/authorization raw).
    safe_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"cookie", "authorization"}
    }

    if receiver.require_signature and not verified:
        # Anyone can POST here without a credential, so a rejection must not
        # cost a full-size durable row each time: keep a short excerpt plus a
        # digest (enough to debug a mis-set secret), and stop recording once a
        # receiver has taken a burst of rejections this minute. (Audit C6.)
        limit = int(getattr(settings, "SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE", 30))
        recent = WebhookReceipt.objects.filter(
            receiver=receiver,
            status=WebhookReceipt.Status.REJECTED,
            received_at__gte=timezone.now() - timedelta(minutes=1),
        ).count()
        if recent < limit:
            import hashlib

            WebhookReceipt.objects.create(
                receiver=receiver,
                source_ip=request.META.get("REMOTE_ADDR"),
                headers=safe_headers,
                body=raw[:1024].decode("utf-8", "replace"),
                verified=False,
                origin=origin[:200],
                status=WebhookReceipt.Status.REJECTED,
                error=(
                    f"signature verification failed "
                    f"(body {len(raw)} bytes, sha256 {hashlib.sha256(raw).hexdigest()}; first 1 KB kept)"
                ),
            )
        return JsonResponse({"error": "invalid signature"}, status=401)

    # 3. Loop guard (F-020): drop an event this SmallStack originated (a two-way S2S
    #    link echoing back), recording it as ignored rather than dispatching.
    if receiver.ignore_origin and origin and origin == receiver.ignore_origin:
        WebhookReceipt.objects.create(
            receiver=receiver,
            source_ip=request.META.get("REMOTE_ADDR"),
            headers=safe_headers,
            body=raw.decode("utf-8", "replace")[:100_000],
            verified=verified,
            origin=origin,
            status=WebhookReceipt.Status.IGNORED,
            error="self-originated event dropped (ignore_origin)",
        )
        WebhookReceiver.objects.filter(pk=receiver.pk).update(
            last_received_at=timezone.now(),
            total_received=F("total_received") + 1,
        )
        return JsonResponse({"ignored": True, "reason": "self-origin"}, status=202)

    receipt = WebhookReceipt.objects.create(
        receiver=receiver,
        source_ip=request.META.get("REMOTE_ADDR"),
        headers=safe_headers,
        body=raw.decode("utf-8", "replace")[:100_000],
        verified=verified,
        origin=origin,
        status=WebhookReceipt.Status.ACCEPTED,
    )
    WebhookReceiver.objects.filter(pk=receiver.pk).update(
        last_received_at=timezone.now(),
        total_received=F("total_received") + 1,
    )

    try:
        from .tasks import dispatch_incoming

        dispatch_incoming.enqueue(receipt.pk)
    except Exception:  # noqa: BLE001 — a broker hiccup shouldn't 500 the sender
        pass
    return JsonResponse({"accepted": True, "receipt": receipt.pk}, status=202)
