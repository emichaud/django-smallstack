"""The staff log viewer: access, filters, correlation, and capture controls."""

import logging
from datetime import timedelta

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.telemetry import capture
from apps.telemetry.models import LogCaptureWindow, LogRecord

pytestmark = pytest.mark.django_db

User = get_user_model()

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def make_record(level="WARNING", logger="apps.demo", message="something happened", *, age_seconds=0, **kwargs):
    return LogRecord.objects.create(
        ts=timezone.now() - timedelta(seconds=age_seconds),
        level=level,
        level_no=LEVELS[level],
        logger=logger,
        message=message,
        **kwargs,
    )


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="ops", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def logs_url():
    return reverse("telemetry:logs")


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def test_anonymous_is_sent_to_login(client, logs_url):
    response = client.get(logs_url)
    assert response.status_code == 302
    assert "/login" in response.url


def test_signed_in_non_staff_is_forbidden(client, logs_url):
    client.force_login(User.objects.create_user(username="jo", password="x"))
    assert client.get(logs_url).status_code == 403


def test_capture_control_is_staff_only(client):
    client.force_login(User.objects.create_user(username="jo", password="x"))
    response = client.post(reverse("telemetry:capture"), {"action": "start"})
    assert response.status_code == 403
    assert capture.active_window() is None


def test_detail_is_staff_only(client):
    record = make_record()
    client.force_login(User.objects.create_user(username="jo", password="x"))
    assert client.get(reverse("telemetry:log_detail", args=[record.pk])).status_code == 403


# ---------------------------------------------------------------------------
# Listing and filters
# ---------------------------------------------------------------------------


def test_records_are_listed_newest_first(client, staff, logs_url):
    make_record(message="the older one", age_seconds=60)
    make_record(message="the newer one", age_seconds=0)

    # Asserted on the context rather than by searching the HTML: the rendered
    # page contains the word "placeholder", and a substring search for "older"
    # matches that instead of the record.
    records = client.get(logs_url).context["records"]
    assert [r.message for r in records] == ["the newer one", "the older one"]


def test_level_filter_means_this_level_and_above(client, staff, logs_url):
    make_record(level="DEBUG", message="debug line")
    make_record(level="INFO", message="info line")
    make_record(level="WARNING", message="warning line")
    make_record(level="ERROR", message="error line")

    body = client.get(logs_url, {"level": "WARNING"}).content.decode()

    assert "warning line" in body
    assert "error line" in body
    assert "info line" not in body
    assert "debug line" not in body


def test_critical_level_filter_and_unknown_level_notice(client, staff, logs_url):
    make_record(level="ERROR", message="error line")
    make_record(level="CRITICAL", message="critical line")

    body = client.get(logs_url, {"level": "CRITICAL"}).content.decode()
    assert "critical line" in body
    assert "error line" not in body

    body = client.get(logs_url, {"level": "BOGUS"}).content.decode()
    assert "Unknown level" in body


def test_level_counts_are_totals_not_one_per_row(client, staff, logs_url):
    """Regression: the queryset is ordered by ("-ts", "-pk"), and Django folds
    ordering fields into the GROUP BY of a values().annotate() — which made
    every count come back as 1."""
    for i in range(7):
        make_record(level="ERROR", message=f"boom {i}", age_seconds=i)
    for i in range(3):
        make_record(level="INFO", message=f"note {i}", age_seconds=i)

    options = {o["value"]: o["count"] for o in client.get(logs_url).context["level_options"]}

    assert options[""] == 10
    assert options["ERROR"] == 7
    assert options["INFO"] == 10, "INFO means INFO and above"
    assert options["DEBUG"] == 10


def test_logger_options_are_distinct_names(client, staff, logs_url):
    """Same GROUP BY trap: without .order_by() this returned one entry per record."""
    for i in range(5):
        make_record(logger="apps.webhooks", age_seconds=i)
    make_record(logger="apps.search")

    options = client.get(logs_url).context["logger_options"]

    assert sorted(options) == ["apps.search", "apps.webhooks"]


def test_logger_filter_includes_children(client, staff, logs_url):
    make_record(logger="apps.webhooks", message="parent line")
    make_record(logger="apps.webhooks.tasks", message="child line")
    make_record(logger="apps.search", message="other line")

    body = client.get(logs_url, {"logger": "apps.webhooks"}).content.decode()

    assert "parent line" in body
    assert "child line" in body
    assert "other line" not in body


def test_logger_filter_excludes_a_sibling_that_shares_a_string_prefix(client, staff, logs_url):
    """Regression: logger__startswith is a raw string prefix at the DB level —
    filtering to "apps.webhooks" must not also match "apps.webhooks_admin",
    which is an unrelated logger, not a child in the "." hierarchy."""
    make_record(logger="apps.webhooks", message="parent line")
    make_record(logger="apps.webhooks_admin", message="sibling line")

    body = client.get(logs_url, {"logger": "apps.webhooks"}).content.decode()

    assert "parent line" in body
    assert "sibling line" not in body


def test_search_covers_the_traceback_not_just_the_message(client, staff, logs_url):
    """The exception class is what you remember, and it lives in exc_text."""
    make_record(message="payment failed", exc_type="GatewayTimeout", exc_text="…raise GatewayTimeout(...)")
    make_record(message="unrelated")

    body = client.get(logs_url, {"q": "GatewayTimeout"}).content.decode()

    assert "payment failed" in body
    assert "unrelated" not in body


def test_time_range_filter(client, staff, logs_url):
    make_record(message="recent line", age_seconds=60)
    make_record(message="ancient line", age_seconds=60 * 60 * 5)

    body = client.get(logs_url, {"range": "1h"}).content.decode()

    assert "recent line" in body
    assert "ancient line" not in body


def test_request_id_filter_gathers_one_request(client, staff, logs_url):
    """The payoff of stamping request IDs: one search, the whole request."""
    make_record(message="first step", request_id="req_abc")
    make_record(message="then this", request_id="req_abc")
    make_record(message="different request", request_id="req_zzz")

    body = client.get(logs_url, {"request_id": "req_abc"}).content.decode()

    assert "first step" in body
    assert "then this" in body
    assert "different request" not in body


def test_filters_combine(client, staff, logs_url):
    make_record(level="ERROR", logger="apps.webhooks", message="wanted")
    make_record(level="ERROR", logger="apps.search", message="wrong logger")
    make_record(level="INFO", logger="apps.webhooks", message="wrong level")

    body = client.get(logs_url, {"level": "ERROR", "logger": "apps.webhooks"}).content.decode()

    assert "wanted" in body
    assert "wrong logger" not in body
    assert "wrong level" not in body


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------


def test_empty_with_no_records_points_at_the_capture_control(client, staff, logs_url):
    body = client.get(logs_url).content.decode()
    assert "Nothing captured yet" in body


def test_empty_under_filters_offers_a_way_back(client, staff, logs_url):
    make_record(level="INFO", message="something")
    body = client.get(logs_url, {"level": "ERROR"}).content.decode()

    assert "No records match these filters" in body
    assert "Clear filters" in body


# ---------------------------------------------------------------------------
# htmx partial
# ---------------------------------------------------------------------------


def test_htmx_request_returns_the_partial(client, staff, logs_url):
    make_record(message="a line")
    response = client.get(logs_url, HTTP_HX_REQUEST="true")

    body = response.content.decode()
    assert "a line" in body
    assert "<html" not in body.lower(), "partial only — no page chrome"


def test_live_partial_carries_its_own_polling_wrapper(client, staff, logs_url):
    """Regression: the refresh swaps outerHTML, so a response without the
    wrapper's hx-trigger would stop refreshing after the first tick."""
    make_record(message="a line")
    body = client.get(logs_url, {"live": "1"}, HTTP_HX_REQUEST="true").content.decode()

    assert 'id="log-table"' in body
    assert 'hx-trigger="every 5s"' in body


def test_polling_is_off_unless_live_is_requested(client, staff, logs_url):
    make_record()
    assert 'hx-trigger="every 5s"' not in client.get(logs_url).content.decode()


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


def test_detail_shows_traceback_and_fields(client, staff):
    record = make_record(
        level="ERROR",
        message="payment failed",
        exc_type="GatewayTimeout",
        exc_text="Traceback (most recent call last):\n  ...",
        extra={"cart": 8812},
        request_id="req_abc",
    )

    body = client.get(reverse("telemetry:log_detail", args=[record.pk])).content.decode()

    assert "Traceback (most recent call last)" in body
    assert "GatewayTimeout" in body
    assert "cart" in body and "8812" in body
    assert "req_abc" in body


def test_detail_links_back_to_the_whole_request(client, staff):
    record = make_record(request_id="req_abc")
    body = client.get(reverse("telemetry:log_detail", args=[record.pk])).content.decode()
    assert f"{reverse('telemetry:logs')}?request_id=req_abc" in body


def test_detail_404s_for_an_unknown_record(client, staff):
    assert client.get(reverse("telemetry:log_detail", args=[999999])).status_code == 404


# ---------------------------------------------------------------------------
# Capture controls
# ---------------------------------------------------------------------------


def test_start_opens_a_window_and_audits_it(client, staff):
    response = client.post(reverse("telemetry:capture"), {"action": "start", "level": "DEBUG", "minutes": "15"})

    assert response.status_code == 302
    window = capture.active_window()
    assert window is not None
    assert window.level == "DEBUG"
    assert window.started_by == "ops"
    assert LogEntry.objects.filter(user=staff).exists(), "turning verbosity up is attributable"


def test_start_survives_a_junk_duration(client, staff):
    client.post(reverse("telemetry:capture"), {"action": "start", "minutes": "not-a-number"})
    assert capture.active_window() is not None


@pytest.mark.parametrize("level", ["DEGUB", "WARNING", "ERROR"])
def test_start_refuses_a_window_that_would_capture_nothing(client, staff, level):
    """A typo, or a level at/above the WARNING baseline, used to be accepted,
    audited, and flashed as "Capturing …" while changing nothing. (Audit D6.)"""
    response = client.post(reverse("telemetry:capture"), {"action": "start", "level": level}, follow=True)
    assert capture.active_window() is None
    assert not LogEntry.objects.filter(user=staff).exists()
    assert "Capture not started" in response.content.decode()


def test_stop_closes_the_window(client, staff):
    capture.start(minutes=30)
    response = client.post(reverse("telemetry:capture"), {"action": "stop"})

    assert response.status_code == 302
    assert capture.active_window() is None


def test_stop_is_harmless_when_nothing_is_open(client, staff):
    assert client.post(reverse("telemetry:capture"), {"action": "stop"}).status_code == 302


def test_unknown_action_is_rejected(client, staff):
    assert client.post(reverse("telemetry:capture"), {"action": "drop-everything"}).status_code == 404
    assert LogCaptureWindow.objects.count() == 0


def test_header_reflects_an_open_window(client, staff, logs_url):
    capture.start(level="DEBUG", minutes=15)
    body = client.get(logs_url).content.decode()

    assert "Capturing DEBUG until" in body
    assert "Stop capturing" in body


def test_header_shows_the_baseline_when_closed(client, staff, logs_url):
    body = client.get(logs_url).content.decode()
    assert "Capturing WARNING and above" in body
    assert "Turn up capture" in body


def test_dropped_records_are_surfaced(client, staff, logs_url, monkeypatch):
    """A silent drop is a lie about completeness — the page has to say so."""
    from apps.telemetry import views

    monkeypatch.setattr(views, "get_handlers", lambda: [_FakeHandler(dropped=12)])
    body = client.get(logs_url).content.decode()

    assert "12 records dropped" in body.replace("record dropped", "records dropped")


class _FakeHandler:
    def __init__(self, dropped):
        self._dropped = dropped

    def stats(self):
        return {"dropped": self._dropped, "level": "WARNING", "queued": 0}


def test_capture_baseline_comes_from_settings(client, staff, logs_url, settings):
    settings.TELEMETRY_LOG_LEVEL = "ERROR"
    assert "Capturing ERROR and above" in client.get(logs_url).content.decode()


def test_logging_module_level_is_unchanged_by_viewing(client, staff, logs_url):
    """Rendering the page must not mutate global logging state."""
    before = logging.getLogger("apps").level
    client.get(logs_url)
    assert logging.getLogger("apps").level == before
