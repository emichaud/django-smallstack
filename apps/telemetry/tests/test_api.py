"""The /api/logger/ read surface.

Structured around the acceptance criteria in ``docs/logger-api-spec.md``:
access control, every filter, the 400-on-unknown-param rule, cursor
correctness, and payload bounding.

Where a test asserts a *behaviour* rather than a shape, it is written so that
removing the mechanism makes it fail — see the docstrings. Round 4 of this
feature's verification shipped a test that passed against the broken code
because it called the handler's internals directly; the discipline since has
been to drive the real path and prove the test can fail.
"""

from __future__ import annotations

import json
import logging

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.telemetry.models import LogRecord

pytestmark = pytest.mark.django_db

RECORDS_URL = "/api/logger/records/"
INDEX_URL = "/api/logger/"
CAPTURE_URL = "/api/logger/capture/"


def make_record(**kwargs):
    defaults = {
        "ts": timezone.now(),
        "level": "INFO",
        "level_no": logging.INFO,
        "logger": "apps.demo",
        "message": "hello",
    }
    defaults.update(kwargs)
    return LogRecord.objects.create(**defaults)


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(
        username="staffer", password="pw12345!x", is_staff=True
    )


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


def body(response):
    return json.loads(response.content)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [INDEX_URL, RECORDS_URL, CAPTURE_URL])
def test_anonymous_is_rejected(client, url):
    assert client.get(url).status_code in (401, 403)


@pytest.mark.parametrize("url", [INDEX_URL, RECORDS_URL, CAPTURE_URL])
def test_authenticated_non_staff_is_forbidden(client, django_user_model, url):
    django_user_model.objects.create_user(username="plain", password="pw12345!x")
    client.login(username="plain", password="pw12345!x")
    assert client.get(url).status_code == 403


def test_non_staff_cannot_read_a_record_detail(client, django_user_model):
    record = make_record()
    django_user_model.objects.create_user(username="plain2", password="pw12345!x")
    client.login(username="plain2", password="pw12345!x")
    assert client.get(f"/api/logger/records/{record.pk}/").status_code == 403


def test_staff_can_read(staff_client):
    assert staff_client.get(RECORDS_URL).status_code == 200


# ---------------------------------------------------------------------------
# The unknown-parameter rule — the spec's most important requirement
# ---------------------------------------------------------------------------


def test_unknown_query_parameter_is_a_400_not_a_silently_unfiltered_table():
    """The failure mode this prevents: `?sevrity=ERROR` (typo) silently
    returning every record, which reads to a caller as a successful query."""


@pytest.mark.parametrize(
    "url,params",
    [
        (RECORDS_URL, {"sevrity": "ERROR"}),
        (RECORDS_URL, {"level": "ERROR", "page": "2"}),
        (CAPTURE_URL, {"minutes": "5"}),
        (INDEX_URL, {"anything": "1"}),
    ],
)
def test_unknown_params_are_rejected(staff_client, url, params):
    make_record(level="ERROR", level_no=logging.ERROR)
    response = staff_client.get(url, params)
    assert response.status_code == 400, f"{url} accepted {params}"
    assert "Unknown query parameter" in body(response)["errors"]["__all__"][0]


def test_the_rejection_names_the_offending_param_and_the_valid_ones(staff_client):
    response = staff_client.get(RECORDS_URL, {"sevrity": "ERROR"})
    message = body(response)["errors"]["__all__"][0]
    assert "'sevrity'" in message
    assert "level" in message  # tells the caller what it should have used


def test_a_typo_would_otherwise_have_returned_everything(staff_client):
    """Negative control for the rule above: proves the 400 is doing real work.

    Without the check, this same request returns all records — which is the
    silent failure. Here we assert the request is refused *while* records
    exist, so a regression to 'ignore unknown params' flips this test.
    """
    for i in range(5):
        make_record(message=f"row {i}")
    response = staff_client.get(RECORDS_URL, {"sevrity": "ERROR"})
    assert response.status_code == 400
    assert "records" not in body(response)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_level_filter_is_this_level_and_above(staff_client):
    make_record(level="DEBUG", level_no=logging.DEBUG, message="dbg")
    make_record(level="INFO", level_no=logging.INFO, message="inf")
    make_record(level="ERROR", level_no=logging.ERROR, message="err")

    messages = {r["message"] for r in body(staff_client.get(RECORDS_URL, {"level": "INFO"}))["records"]}
    assert messages == {"inf", "err"}, "level filter must include higher levels"


def test_invalid_level_is_rejected(staff_client):
    response = staff_client.get(RECORDS_URL, {"level": "BOGUS"})
    assert response.status_code == 400
    assert "level must be one of" in body(response)["errors"]["__all__"][0]


def test_logger_filter_is_hierarchy_aware_not_a_raw_prefix(staff_client):
    """The round-2 sibling-prefix finding, guarded on this surface too:
    `apps.telemetry` must match its children but not `apps.telemetry_report`."""
    make_record(logger="apps.telemetry", message="parent")
    make_record(logger="apps.telemetry.handlers", message="child")
    make_record(logger="apps.telemetry_report", message="sibling")

    messages = {
        r["message"] for r in body(staff_client.get(RECORDS_URL, {"logger": "apps.telemetry"}))["records"]
    }
    assert messages == {"parent", "child"}, "sibling logger leaked into the results"


def test_request_id_filter_is_exact(staff_client):
    make_record(request_id="req_abc", message="mine")
    make_record(request_id="req_abcdef", message="not mine")
    records = body(staff_client.get(RECORDS_URL, {"request_id": "req_abc"}))["records"]
    assert [r["message"] for r in records] == ["mine"]


def test_trace_id_filter_is_exact(staff_client):
    make_record(trace_id="trace_task_1", message="task line")
    make_record(message="unrelated")
    records = body(staff_client.get(RECORDS_URL, {"trace_id": "trace_task_1"}))["records"]
    assert [r["message"] for r in records] == ["task line"]


def test_search_covers_the_traceback_not_just_the_message(staff_client):
    """The exception class is what you remember, and it only appears in
    exc_text — a message-only search would miss it."""
    make_record(message="something failed", exc_text="Traceback…\nValidationError: nope")
    make_record(message="unrelated")

    records = body(staff_client.get(RECORDS_URL, {"search": "ValidationError"}))["records"]
    assert [r["message"] for r in records] == ["something failed"]


def test_since_and_until_bound_the_window(staff_client):
    now = timezone.now()
    old = make_record(ts=now - timezone.timedelta(hours=3), message="old")
    recent = make_record(ts=now - timezone.timedelta(minutes=5), message="recent")

    since = (now - timezone.timedelta(hours=1)).isoformat()
    records = body(staff_client.get(RECORDS_URL, {"since": since}))["records"]
    assert [r["id"] for r in records] == [recent.pk]

    until = (now - timezone.timedelta(hours=1)).isoformat()
    records = body(staff_client.get(RECORDS_URL, {"until": until}))["records"]
    assert [r["id"] for r in records] == [old.pk]


def test_malformed_timestamp_is_rejected_with_a_useful_message(staff_client):
    response = staff_client.get(RECORDS_URL, {"since": "yesterday"})
    assert response.status_code == 400
    assert "ISO-8601" in body(response)["errors"]["__all__"][0]


def test_applied_filters_echoes_what_the_server_understood(staff_client):
    make_record(level="ERROR", level_no=logging.ERROR)
    data = body(staff_client.get(RECORDS_URL, {"level": "ERROR", "logger": "apps.demo"}))
    assert data["applied_filters"]["level"] == "ERROR"
    assert data["applied_filters"]["logger"] == "apps.demo"
    assert data["applied_filters"]["limit"] == 50


# ---------------------------------------------------------------------------
# Cursor / pagination
# ---------------------------------------------------------------------------


def test_limit_is_honoured_and_capped(staff_client):
    for i in range(5):
        make_record(message=f"r{i}")

    assert len(body(staff_client.get(RECORDS_URL, {"limit": "2"}))["records"]) == 2

    over = staff_client.get(RECORDS_URL, {"limit": "5000"})
    assert over.status_code == 400
    assert "must be <=" in body(over)["errors"]["__all__"][0]

    assert staff_client.get(RECORDS_URL, {"limit": "0"}).status_code == 400
    assert staff_client.get(RECORDS_URL, {"limit": "abc"}).status_code == 400


def test_has_more_is_accurate_at_the_boundary(staff_client):
    """The off-by-one that a naive `len(rows) == limit` check gets wrong:
    exactly `limit` records left means there is nothing more."""
    for i in range(3):
        make_record(message=f"r{i}")

    assert body(staff_client.get(RECORDS_URL, {"limit": "2"}))["has_more"] is True
    assert body(staff_client.get(RECORDS_URL, {"limit": "3"}))["has_more"] is False
    assert body(staff_client.get(RECORDS_URL, {"limit": "10"}))["has_more"] is False


def test_after_id_tails_forward_without_duplicates_or_gaps(staff_client):
    """A cursor loop over records written *during* the loop — the case page
    numbers get wrong, because new rows shift every page."""
    first_batch = [make_record(message=f"a{i}") for i in range(3)]

    data = body(staff_client.get(RECORDS_URL, {"after_id": first_batch[0].pk, "limit": "10"}))
    seen = [r["id"] for r in data["records"]]
    assert seen == [first_batch[1].pk, first_batch[2].pk]

    # More records arrive between polls, as they would in a live tail.
    second_batch = [make_record(message=f"b{i}") for i in range(2)]

    data2 = body(staff_client.get(RECORDS_URL, {"after_id": data["next_after_id"], "limit": "10"}))
    seen2 = [r["id"] for r in data2["records"]]

    assert seen2 == [r.pk for r in second_batch], "cursor must return only what's new"
    assert not set(seen) & set(seen2), "cursor returned a record twice"


def test_after_id_returns_oldest_first_so_the_cursor_advances(staff_client):
    records = [make_record(message=f"r{i}") for i in range(3)]
    data = body(staff_client.get(RECORDS_URL, {"after_id": 0}))
    assert [r["id"] for r in data["records"]] == [r.pk for r in records]
    assert data["next_after_id"] == records[-1].pk


def test_after_id_never_skips_records_inserted_out_of_capture_order(staff_client):
    """Two workers' batches land in reverse ts order: the later-captured batch
    gets the lower pks. A cursor ordered by ts advanced ``next_after_id`` past
    the earlier-captured rows and reported ``has_more=False`` with half the
    records never returned (audit 2026-09-13, D1)."""
    now = timezone.now()
    late = [make_record(ts=now + timezone.timedelta(seconds=i), message=f"B{i}") for i in range(10)]
    early = [make_record(ts=now - timezone.timedelta(minutes=5, seconds=-i), message=f"A{i}") for i in range(10)]
    expected = {r.pk for r in late + early}

    seen: list[int] = []
    cursor = 0
    for _ in range(10):
        data = body(staff_client.get(RECORDS_URL, {"after_id": cursor, "limit": "10"}))
        seen.extend(r["id"] for r in data["records"])
        cursor = data["next_after_id"]
        if not data["has_more"]:
            break

    assert len(seen) == len(set(seen)), "cursor returned a record twice"
    assert set(seen) == expected, "cursor skipped records"


def test_default_ordering_is_newest_first(staff_client):
    older = make_record(ts=timezone.now() - timezone.timedelta(minutes=5), message="older")
    newer = make_record(message="newer")
    ids = [r["id"] for r in body(staff_client.get(RECORDS_URL))["records"]]
    assert ids == [newer.pk, older.pk]


def test_total_matching_counts_all_matches_not_just_the_page(staff_client):
    for i in range(7):
        make_record(message=f"r{i}")
    data = body(staff_client.get(RECORDS_URL, {"limit": "2"}))
    assert data["count"] == 2
    assert data["total_matching"] == 7


# ---------------------------------------------------------------------------
# Payload bounding + detail
# ---------------------------------------------------------------------------


def test_list_truncates_a_huge_traceback_and_says_so(staff_client):
    make_record(exc_text="X" * 50_000, exc_type="BoomError")
    record = body(staff_client.get(RECORDS_URL))["records"][0]
    assert record["exc_truncated"] is True
    assert len(record["exc_text"]) < 1000


def test_detail_returns_the_full_traceback(staff_client):
    created = make_record(exc_text="Y" * 50_000, exc_type="BoomError")
    data = body(staff_client.get(f"/api/logger/records/{created.pk}/"))
    assert data["exc_truncated"] is False
    assert len(data["exc_text"]) == 50_000
    assert data["exc_type"] == "BoomError"


def test_detail_includes_source_location_that_the_list_omits(staff_client):
    created = make_record(module="views", func="handle", line=42)
    listed = body(staff_client.get(RECORDS_URL))["records"][0]
    assert "module" not in listed, "list rows stay narrow"

    detail = body(staff_client.get(f"/api/logger/records/{created.pk}/"))
    assert (detail["module"], detail["func"], detail["line"]) == ("views", "handle", 42)


def test_extra_fields_survive_to_the_api(staff_client):
    make_record(extra={"item_id": 42, "delta": -5})
    record = body(staff_client.get(RECORDS_URL))["records"][0]
    assert record["extra"] == {"item_id": 42, "delta": -5}


def test_missing_record_is_a_404_not_a_500(staff_client):
    assert staff_client.get("/api/logger/records/999999/").status_code == 404


def test_list_rows_link_to_their_own_detail(staff_client):
    created = make_record()
    record = body(staff_client.get(RECORDS_URL))["records"][0]
    assert record["url"] == f"/api/logger/records/{created.pk}/"
    assert staff_client.get(record["url"]).status_code == 200


# ---------------------------------------------------------------------------
# Capability document + capture status
# ---------------------------------------------------------------------------


def test_capability_document_advertises_every_implemented_filter(staff_client):
    """Guards the drift that makes a self-describing endpoint worse than
    none: a filter added to the query code but not to the advertised list."""
    from apps.telemetry.api import RECORD_FILTERS

    data = body(staff_client.get(INDEX_URL))
    assert set(data["filters"]) == set(RECORD_FILTERS)
    assert data["limits"]["max_limit"] == 200
    # Updated in phase 2: the capture write verbs now exist, and the capability
    # document must say so — a client decides whether it can turn capture up by
    # reading this, rather than by trying and interpreting a 403.
    assert data["writes_enabled"] is True
    assert set(data["capture_write"]["methods"]) == {"POST", "DELETE"}
    assert "config" in data["endpoints"]
    assert "loggers" in data["endpoints"]


def test_capture_status_reports_a_closed_window(staff_client):
    data = body(staff_client.get(CAPTURE_URL))
    assert data["open"] is False
    assert data["baseline_level"]
    assert data["handler_stats_scope"] == "this process only"


def test_capture_status_reports_an_open_window(staff_client):
    from apps.telemetry import capture

    capture.start(level="DEBUG", minutes=5, actor="tester", note="api test")
    try:
        data = body(staff_client.get(CAPTURE_URL))
        assert data["open"] is True
        assert data["level"] == "DEBUG"
        assert data["note"] == "api test"
        assert data["expires_at"]
    finally:
        capture.stop()


def test_capture_endpoint_still_refuses_undefined_methods(staff_client):
    """POST/DELETE arrived in phase 2; PUT/PATCH remain undefined and must 405
    rather than falling through to some other handler."""
    for method in ("put", "patch"):
        response = getattr(staff_client, method)(CAPTURE_URL)
        assert response.status_code == 405, f"{method} must not be accepted"


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_routes_are_reversible_under_their_documented_names():
    assert reverse("api-logger-index") == INDEX_URL
    assert reverse("api-logger-records") == RECORDS_URL
    assert reverse("api-logger-capture") == CAPTURE_URL
    assert reverse("api-logger-record-detail", args=[7]) == "/api/logger/records/7/"


def test_the_surface_is_advertised_in_the_openapi_schema(staff_client):
    """Without this an agent that discovers capabilities from the schema —
    the documented way to find endpoints — never learns this exists."""
    schema = body(staff_client.get("/api/schema/openapi.json"))
    paths = schema["paths"]
    assert RECORDS_URL in paths
    assert "/api/logger/records/{id}/" in paths
    assert CAPTURE_URL in paths


def test_the_logger_api_is_excluded_from_activity_logging():
    """Keeps a polling client out of the activity RequestLog."""
    from django.conf import settings

    assert "/api/logger/" in settings.ACTIVITY_EXCLUDE_PATHS


def test_the_dev_servers_access_log_is_not_captured_to_the_database():
    """The other half of the polling-pollution fix, and the half that actually
    bites: `django.server` logs one INFO line per request, so anything polling
    this table — the viewer's 5s live mode, or a client tailing
    /api/logger/records/ — writes a record per poll into the table it reads.

    Found by measuring rather than reasoning: 10 polls of the live API produced
    11 new records, all django.server. ACTIVITY_EXCLUDE_PATHS does not prevent
    this; it governs a different table.
    """
    from apps.telemetry.handlers import DEFAULT_EXCLUDE_LOGGERS, _is_excluded

    assert _is_excluded("django.server", DEFAULT_EXCLUDE_LOGGERS)
    # Still hierarchy-aware, and unrelated loggers are unaffected.
    assert not _is_excluded("django.server_extras", DEFAULT_EXCLUDE_LOGGERS)
    assert not _is_excluded("apps.demo", DEFAULT_EXCLUDE_LOGGERS)


# ---------------------------------------------------------------------------
# Phase 2 — capture writes
# ---------------------------------------------------------------------------

CONFIG_URL = "/api/logger/config/"
LOGGERS_URL = "/api/logger/loggers/"


@pytest.fixture(autouse=True)
def _no_leftover_window():
    """A window left open by one test changes what another captures."""
    yield
    from apps.telemetry import capture

    capture.stop()


def test_post_opens_a_window_and_reports_it(staff_client):
    response = staff_client.post(
        CAPTURE_URL,
        data=json.dumps({"level": "DEBUG", "minutes": 5, "note": "agent: repro 401"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = body(response)
    assert data["open"] is True
    assert data["level"] == "DEBUG"
    assert data["note"] == "agent: repro 401"
    assert data["clamped"] is False
    assert data["expires_at"]
    assert data["poll_after_seconds"] > 0, "a caller needs to know how long to wait"


def test_the_window_is_actually_open_afterwards_not_just_reported(staff_client):
    """Negative control against a handler that returns a convincing payload
    without doing anything: check the underlying state, not the response."""
    from apps.telemetry import capture

    assert capture.active_window() is None
    staff_client.post(
        CAPTURE_URL,
        data=json.dumps({"note": "real effect check"}),
        content_type="application/json",
    )
    window = capture.active_window()
    assert window is not None
    assert window.note == "real effect check"


def test_note_is_required(staff_client):
    for payload in ({}, {"note": ""}, {"note": "   "}, {"level": "DEBUG", "minutes": 5}):
        response = staff_client.post(
            CAPTURE_URL, data=json.dumps(payload), content_type="application/json"
        )
        assert response.status_code == 400, f"{payload} was accepted without a note"
        assert "note is required" in body(response)["errors"]["__all__"][0]


def test_a_rejected_post_does_not_open_a_window(staff_client):
    from apps.telemetry import capture

    staff_client.post(CAPTURE_URL, data=json.dumps({}), content_type="application/json")
    assert capture.active_window() is None, "a 400 must not have side effects"


def test_unknown_body_field_is_rejected(staff_client):
    response = staff_client.post(
        CAPTURE_URL,
        data=json.dumps({"note": "x", "levl": "DEBUG"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "Unknown field" in body(response)["errors"]["__all__"][0]


def test_invalid_level_and_minutes_are_rejected(staff_client):
    bad_level = staff_client.post(
        CAPTURE_URL,
        data=json.dumps({"note": "x", "level": "LOUD"}),
        content_type="application/json",
    )
    assert bad_level.status_code == 400
    assert "level must be one of" in body(bad_level)["errors"]["__all__"][0]

    for minutes in (0, -5, "abc"):
        response = staff_client.post(
            CAPTURE_URL,
            data=json.dumps({"note": "x", "minutes": minutes}),
            content_type="application/json",
        )
        assert response.status_code == 400, f"minutes={minutes!r} was accepted"


def test_an_over_long_window_is_clamped_and_says_so(staff_client, settings):
    """Silently honouring a different duration than the one asked for is worse
    than clamping: a caller that asked for 8 hours stops polling too late and
    concludes capture is broken."""
    settings.TELEMETRY_MAX_CAPTURE_MINUTES = 30

    response = staff_client.post(
        CAPTURE_URL,
        data=json.dumps({"note": "long one", "minutes": 600}),
        content_type="application/json",
    )
    data = body(response)
    assert data["clamped"] is True
    assert data["requested_minutes"] == 600

    from apps.telemetry import capture

    window = capture.active_window()
    actual = (window.expires_at - window.started_at).total_seconds() / 60
    assert actual <= 31, "the window outlived the configured ceiling"


def test_delete_closes_the_window(staff_client):
    from apps.telemetry import capture

    capture.start(level="DEBUG", minutes=5, actor="t", note="to be closed")
    response = staff_client.delete(CAPTURE_URL)

    assert response.status_code == 200
    assert body(response)["open"] is False
    assert body(response)["closed"] == 1
    assert capture.active_window() is None


def test_delete_is_idempotent(staff_client):
    """A client's cleanup runs in a `finally` and must not fail because the
    window already expired on its own."""
    first = staff_client.delete(CAPTURE_URL)
    second = staff_client.delete(CAPTURE_URL)

    assert first.status_code == 200
    assert second.status_code == 200
    assert body(second)["open"] is False
    assert body(second)["closed"] == 0


def test_opening_and_closing_are_audited(staff_client, staff):
    """Turning production verbosity up should be attributable afterwards."""
    from django.contrib.admin.models import LogEntry

    before = LogEntry.objects.count()
    staff_client.post(
        CAPTURE_URL, data=json.dumps({"note": "audited"}), content_type="application/json"
    )
    staff_client.delete(CAPTURE_URL)

    entries = LogEntry.objects.order_by("-pk")[:2]
    assert LogEntry.objects.count() == before + 2
    assert {e.user_id for e in entries} == {staff.pk}
    assert any("capture" in e.change_message.lower() for e in entries)


def test_non_staff_cannot_open_a_window(client, django_user_model):
    from apps.telemetry import capture

    django_user_model.objects.create_user(username="plain3", password="pw12345!x")
    client.login(username="plain3", password="pw12345!x")

    response = client.post(
        CAPTURE_URL, data=json.dumps({"note": "nope"}), content_type="application/json"
    )
    assert response.status_code == 403
    assert capture.active_window() is None


def test_a_readonly_token_can_read_but_not_open_a_window(client, staff):
    """The access-level split that makes this safe to hand to CI: assert an
    error was logged, without being able to turn DEBUG on in production."""
    from apps.smallstack.models import APIToken
    from apps.telemetry import capture

    raw = APIToken.create_token(name="ro-capture", user=staff, access_level="readonly")
    key = raw[1] if isinstance(raw, tuple) else raw
    auth = {"HTTP_AUTHORIZATION": f"Bearer {key}"}

    assert client.get(RECORDS_URL, **auth).status_code == 200

    write = client.post(
        CAPTURE_URL,
        data=json.dumps({"note": "should be refused"}),
        content_type="application/json",
        **auth,
    )
    assert write.status_code == 403
    assert capture.active_window() is None, "a read-only token opened a capture window"


# ---------------------------------------------------------------------------
# Phase 2 — config + loggers
# ---------------------------------------------------------------------------


def test_config_reports_the_effective_settings(staff_client, settings):
    settings.TELEMETRY_LOG_RETENTION_DAYS = 3
    data = body(staff_client.get(CONFIG_URL))

    assert data["retention_days"] == 3
    assert data["baseline_level"]
    assert "apps" in data["capture_loggers"]
    assert "django.server" in data["excluded_loggers"]
    assert data["writable"] is False, "settings come from env, not this API"
    assert "handler_installed" in data


def test_config_is_read_only(staff_client):
    for method in ("post", "put", "delete", "patch"):
        assert getattr(staff_client, method)(CONFIG_URL).status_code == 405


def test_config_surfaces_the_dropped_count(staff_client):
    """The field that distinguishes 'dropped under load' from 'never logged' —
    the difference between a five-minute diagnosis and an hour of confusion."""
    data = body(staff_client.get(CONFIG_URL))
    assert data["handler_stats_scope"] == "this process only"
    for stats in data["handlers"]:
        assert "dropped" in stats


def test_loggers_lists_names_with_counts(staff_client):
    for _ in range(3):
        make_record(logger="apps.alpha")
    make_record(logger="apps.beta")

    data = body(staff_client.get(LOGGERS_URL))
    counts = {row["logger"]: row["count"] for row in data["loggers"]}

    assert counts["apps.alpha"] == 3
    assert counts["apps.beta"] == 1


def test_logger_counts_are_not_one_per_record(staff_client):
    """Guards the shape of the bug that hit the viewer's level counts: one row
    per record, every count 1.

    Honest caveat, established by running the negative control: this endpoint
    aggregates over the bare manager, and Django does NOT fold Meta.ordering
    into a values().annotate() GROUP BY — only *explicitly* ordered fields (the
    viewer's case, since filtered_queryset() orders before aggregating). So
    removing the defensive .order_by() does not currently break this test. It
    is kept as a shape assertion on the response, not as proof of that call."""
    for _ in range(5):
        make_record(logger="apps.grouped")

    data = body(staff_client.get(LOGGERS_URL))
    rows = [r for r in data["loggers"] if r["logger"] == "apps.grouped"]

    assert len(rows) == 1, "grouped by more than the logger name"
    assert rows[0]["count"] == 5


def test_loggers_rejects_unknown_params(staff_client):
    assert staff_client.get(LOGGERS_URL, {"nope": "1"}).status_code == 400
