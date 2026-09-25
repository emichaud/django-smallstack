"""Event-filter pattern picker (F-015): a UI upgrade over the raw-JSON textarea that
serializes to the same JSON list, backward-compatible."""

from __future__ import annotations

import json

import pytest
from django.http import QueryDict

from apps.webhooks import services
from apps.webhooks.views import EventFilterWidget, WebhookReceiverCRUDView

pytestmark = pytest.mark.django_db


def test_widget_combines_checkboxes_and_extra():
    w = EventFilterWidget()
    data = QueryDict(mutable=True)
    data.setlist("event_filter_choice", ["*.created", "*.updated"])
    data["event_filter_extra"] = "support.ticket.*\ncustom.thing.created"
    value = w.value_from_datadict(data, {}, "event_filter")
    assert json.loads(value) == [
        "*.created", "*.updated", "support.ticket.*", "custom.thing.created",
    ]


def test_widget_dedupes():
    w = EventFilterWidget()
    data = QueryDict(mutable=True)
    data.setlist("event_filter_choice", ["*", "*"])
    data["event_filter_extra"] = "*"
    assert json.loads(w.value_from_datadict(data, {}, "event_filter")) == ["*"]


def test_widget_empty_is_empty_list():
    w = EventFilterWidget()
    data = QueryDict(mutable=True)
    assert json.loads(w.value_from_datadict(data, {}, "event_filter")) == []


def test_widget_renders_current_and_custom():
    w = EventFilterWidget()
    html = w.render("event_filter", ["*.created", "my.custom.pattern"])
    # A known option is rendered checked; an unknown one lands in the extra textarea.
    assert "checked" in html
    assert "my.custom.pattern" in html


def test_extra_textarea_has_associated_label():
    """A11y: the custom-patterns textarea must be labelled (id + <label for>),
    not an orphaned control."""
    w = EventFilterWidget()
    html = w.render("event_filter", [])
    assert 'id="id_event_filter_extra"' in html
    assert 'for="id_event_filter_extra"' in html


def test_available_events_includes_opted_in_model():
    """available_events surfaces the concrete events an enable_webhooks model emits."""
    original = WebhookReceiverCRUDView.enable_webhooks
    WebhookReceiverCRUDView.enable_webhooks = True
    try:
        events = services.available_events()
    finally:
        WebhookReceiverCRUDView.enable_webhooks = original
    assert "*" in events
    assert "webhooks.webhookreceiver.*" in events
    assert "webhooks.webhookreceiver.created" in events


# --- plain-English annotations ------------------------------------------------


def test_wildcards_are_annotated():
    assert services.describe_event_pattern("*") == "everything this instance emits"
    assert services.describe_event_pattern("*.created") == "any record is created"
    assert services.describe_event_pattern("*.updated") == "any record is updated"
    assert services.describe_event_pattern("*.deleted") == "any record is deleted"


def test_model_patterns_use_the_verbose_name():
    """Registered models describe themselves by verbose name, not model_name."""
    original = WebhookReceiverCRUDView.enable_webhooks
    WebhookReceiverCRUDView.enable_webhooks = True
    try:
        assert (
            services.describe_event_pattern("webhooks.webhookreceiver.created")
            == "a Webhook Receiver is created"
        )
        assert (
            services.describe_event_pattern("webhooks.webhookreceiver.*")
            == "anything happens to a Webhook Receiver"
        )
    finally:
        WebhookReceiverCRUDView.enable_webhooks = original


def test_unregistered_model_falls_back_to_model_name():
    assert services.describe_event_pattern("crm.contact.created") == "a contact is created"


def test_custom_action_gets_a_generic_hint():
    assert services.describe_event_pattern("crm.contact.merged") == "contact: merged"


def test_unrecognised_shapes_get_no_hint():
    assert services.describe_event_pattern("weird") == ""
    assert services.describe_event_pattern("a.b.c.d") == ""


def test_rendered_picker_carries_the_hints():
    html = EventFilterWidget().render("event_filter", [])
    assert "everything this instance emits" in html
    assert "any record is created" in html


def test_custom_patterns_have_a_help_popup():
    """The pattern grammar is explained in-place, with concrete examples."""
    html = EventFilterWidget().render("event_filter", [])
    assert 'class="help-pop"' in html
    assert 'aria-label="Help: what event patterns look like"' in html
    assert "app.model.action" in html
    assert "support.ticket.*" in html
    assert "everything from the support app" in html


# --- progressive disclosure of the custom-pattern box -------------------------


def test_custom_box_is_collapsed_when_no_custom_patterns():
    """UI operators see one quiet "advanced" line, not an open free-text box."""
    html = EventFilterWidget().render("event_filter", ["*"])
    assert '<details class="event-filter-custom">' in html
    assert '<details class="event-filter-custom" open>' not in html


def test_custom_box_is_expanded_and_populated_when_patterns_are_set():
    """Round-trip safety: programmatically-set patterns must render editable —
    a UI save with the textarea absent would silently strip them."""
    html = EventFilterWidget().render("event_filter", ["*", "crm.contact.merged"])
    assert '<details class="event-filter-custom" open>' in html
    assert "crm.contact.merged" in html
    assert "(1 set)" in html


def test_collapsed_box_still_posts_and_preserves_nothing_extra():
    """The textarea is in the DOM even when collapsed, so a plain UI save
    round-trips: checked boxes survive, no phantom extras appear."""
    w = EventFilterWidget()
    data = QueryDict(mutable=True)
    data.setlist("event_filter_choice", ["*"])
    data["event_filter_extra"] = ""
    assert json.loads(w.value_from_datadict(data, {}, "event_filter")) == ["*"]


# --- pattern validation (the hand-typed-garbage path) ------------------------


def test_valid_patterns_pass():
    assert services.validate_event_patterns(["*", "*.created", "support.ticket.*",
                                             "crm.contact.merged", "a-b.c_d.?"]) == []


@pytest.mark.parametrize("bad", [
    '["*"]',                 # pasted JSON into the pattern box
    "support ticket created",  # spaces
    'support."ticket".*',    # quotes
    "",                      # empty line survives only as ''
    "  ",
])
def test_malformed_patterns_are_rejected(bad):
    errors = services.validate_event_patterns([bad])
    assert len(errors) == 1


def test_non_list_is_rejected():
    assert services.validate_event_patterns("*") == ["event_filter must be a list of patterns."]


def test_endpoint_form_rejects_malformed_patterns():
    """Every surface (HTML/REST/MCP/CLI) validates through this form."""
    from apps.webhooks.views import WebhookEndpointCRUDView

    form = WebhookEndpointCRUDView.form_class(
        data={"name": "x", "target_url": "https://ok.example.com/hook",
              "event_filter": '["support ticket created"]', "headers": "{}",
              "auth_scheme": "none", "transform": "", "enabled": "on"}
    )
    assert not form.is_valid()
    assert "event_filter" in form.errors


def test_unmatched_patterns_warns_only_when_events_exist(monkeypatch):
    """On an instance with no concrete events, everything is 'unmatched' — warning
    would be pure noise, so the check stays silent. (The framework ships opted-in
    models — approvals — so the no-events case is constructed explicitly.)"""
    from apps.smallstack.crud import CRUDView

    for view in set(CRUDView._registry.values()):
        if getattr(view, "enable_webhooks", False):
            monkeypatch.setattr(view, "enable_webhooks", False)
    assert services.unmatched_patterns(["nosuch.thing.*"]) == []
    monkeypatch.setattr(WebhookReceiverCRUDView, "enable_webhooks", True)
    dead = services.unmatched_patterns(["nosuch.thing.*", "webhooks.webhookreceiver.*", "*"])
    assert dead == ["nosuch.thing.*"]
