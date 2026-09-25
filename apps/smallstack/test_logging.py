"""Structured logging: JSON output, request context, and settings wiring.

The production formatter used to be a ``%``-style string template that merely
*looked* like JSON::

    '{"time": "%(asctime)s", ..., "message": "%(message)s"}'

It broke in three ways, each pinned by a test below: any quote/backslash/newline
in a message produced invalid JSON; ``logger.exception()`` appended a raw
multi-line traceback after the closing brace; and ``extra={...}`` fields were
dropped on the floor. These tests are the regression fence.

They also pin the correlation contract the docs promise: a log line emitted
while handling a request carries the same ``request_id`` as the response's
``X-Request-ID`` header and the ``RequestLog`` row.
"""

import json
import logging
import logging.config

import pytest
from django.test import RequestFactory

from apps.smallstack.logging import (
    JSONFormatter,
    RequestContextFilter,
    TextFormatter,
    bind_request_id,
    bind_trace_id,
    get_request_id,
    reset_request_id,
    reset_trace_id,
)
from apps.smallstack.middleware import RequestIDMiddleware


def make_record(msg="hello", args=(), *, level=logging.INFO, exc_info=None, **extra):
    """Build a LogRecord the way logging.Logger._log() would."""
    record = logging.LogRecord(
        name="apps.tickets.views",
        level=level,
        pathname="/app/apps/tickets/views.py",
        lineno=42,
        msg=msg,
        args=args,
        exc_info=exc_info,
        func="close_ticket",
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def emit(record, formatter=None):
    """Format a record and parse the result back as JSON."""
    return json.loads((formatter or JSONFormatter()).format(record))


@pytest.fixture
def clean_context():
    """Guarantee no request/trace ID leaks between tests."""
    token = bind_request_id("")
    trace_token = bind_trace_id("")
    yield
    reset_request_id(token)
    reset_trace_id(trace_token)


# ---------------------------------------------------------------------------
# JSON validity — the bug this phase exists to fix
# ---------------------------------------------------------------------------


def test_plain_message_is_valid_json():
    payload = emit(make_record("Ticket 42 closed"))
    assert payload["message"] == "Ticket 42 closed"
    assert payload["level"] == "INFO"
    assert payload["name"] == "apps.tickets.views"
    assert payload["line"] == 42
    assert payload["func"] == "close_ticket"


@pytest.mark.parametrize(
    "message",
    [
        'Ticket "42" closed',  # double quotes closed the JSON string early
        r"Bad path C:\Users\admin",  # backslash produced an invalid escape
        "line one\nline two",  # newline split the record across lines
        "tab\there",
        'nested {"json": "payload"}',  # a serialized payload inside a message
        "unicode: café ☃",
    ],
)
def test_special_characters_survive_round_trip(message):
    """Each of these produced unparseable output under the old format string."""
    assert emit(make_record(message))["message"] == message


def test_output_is_exactly_one_line():
    record = make_record("first\nsecond\nthird")
    assert "\n" not in JSONFormatter().format(record)


def test_message_interpolation_uses_record_args():
    payload = emit(make_record("Ticket %s closed by %s", (42, "admin")))
    assert payload["message"] == "Ticket 42 closed by admin"


def test_bad_interpolation_does_not_raise():
    """A broken call site must not cost us the log line — it IS the clue."""
    payload = emit(make_record("%d items", ("seven",)))
    assert "unformattable" in payload["message"]
    assert "seven" in payload["message"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


def _exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        return sys.exc_info()


def test_exception_traceback_lands_inside_the_json():
    """Old behavior: the traceback was appended AFTER the closing brace."""
    rendered = JSONFormatter().format(make_record("failed", level=logging.ERROR, exc_info=_exc_info()))

    assert "\n" not in rendered  # the whole record, traceback included, is one line
    payload = json.loads(rendered)
    assert payload["exc_type"] == "ValueError"
    assert "Traceback (most recent call last)" in payload["exc"]
    assert "ValueError: boom" in payload["exc"]


def test_exception_text_is_cached_on_the_record():
    """formatException() is not cheap and every handler formats the record."""
    record = make_record("failed", level=logging.ERROR, exc_info=_exc_info())
    JSONFormatter().format(record)
    assert record.exc_text
    # Second handler reuses the cached text rather than re-rendering.
    assert emit(record)["exc"] == record.exc_text


def test_no_exception_fields_when_there_is_no_exception():
    payload = emit(make_record("all good"))
    assert "exc" not in payload
    assert "exc_type" not in payload


# ---------------------------------------------------------------------------
# extra={...} — silently discarded by the old formatter
# ---------------------------------------------------------------------------


def test_extra_fields_are_preserved():
    """Real call sites rely on this — see apps/api/threats.py, apps/help/search.py."""
    payload = emit(make_record("blocked probe", user_agent="curl/8.1", token="tok_abc"))
    assert payload["extra"] == {"user_agent": "curl/8.1", "token": "tok_abc"}


def test_no_extra_key_when_call_site_passed_none():
    assert "extra" not in emit(make_record("plain"))


def test_unserializable_extra_falls_back_to_repr():
    payload = emit(make_record("odd", thing=object()))
    assert "object object at" in payload["extra"]["thing"]


def test_unserializable_extra_uses_repr_not_str_for_a_datetime():
    """repr() and str() only diverge for types with a non-identity __str__ —
    a bare object() (the test above) can't tell them apart. A datetime can:
    str() gives '2026-08-16 12:00:00' (looks like a plain string), repr()
    gives 'datetime.datetime(2026, 8, 16, 12, 0, 0)' (unambiguous)."""
    import datetime

    payload = emit(make_record("odd", when=datetime.datetime(2026, 8, 16, 12, 30, 5)))
    assert payload["extra"]["when"] == "datetime.datetime(2026, 8, 16, 12, 30, 5)"


def test_json_default_survives_a_repr_that_raises():
    """json_default's own first attempt must degrade gracefully — see
    apps.telemetry.tests.test_handlers for the DB-row-level regression this
    protects (a poisoned field must not cost the whole log line)."""
    from apps.smallstack.logging import json_default

    class BadRepr:
        def __repr__(self):
            raise ValueError("nope")

    rendered = json_default(BadRepr())
    assert "repr() raised" in rendered
    assert "BadRepr" in rendered


def test_json_default_survives_a_recursive_repr():
    """A hand-written recursive __repr__ raises RecursionError — not caught
    by Python's built-in container-cycle detection, since it isn't a
    container cycle."""
    from apps.smallstack.logging import json_default

    class RecursiveRepr:
        def __repr__(self):
            return repr(self)

    rendered = json_default(RecursiveRepr())
    assert "repr() raised" in rendered
    assert "RecursiveRepr" in rendered


def test_json_default_still_works_for_a_normal_value():
    from apps.smallstack.logging import json_default

    assert json_default(object()).startswith("<object object at")


def test_unserializable_extra_is_truncated_when_huge():
    """A set isn't natively JSON-serializable (unlike a list), so its repr()
    goes through json_default — and repr() of a big one is easily oversized."""
    from apps.smallstack.logging import MAX_UNSERIALIZABLE_REPR_CHARS

    payload = emit(make_record("odd", huge=set(range(10_000))))
    rendered = payload["extra"]["huge"]
    assert len(rendered) <= MAX_UNSERIALIZABLE_REPR_CHARS + len("...(truncated)")
    assert rendered.endswith("...(truncated)")


def test_context_ids_are_not_duplicated_into_extra(clean_context):
    token = bind_request_id("req_abc")
    try:
        record = make_record("hi")
        RequestContextFilter().filter(record)
        payload = emit(record)
    finally:
        reset_request_id(token)

    assert payload["request_id"] == "req_abc"
    assert "extra" not in payload


# ---------------------------------------------------------------------------
# Request / trace context
# ---------------------------------------------------------------------------


def test_filter_injects_bound_request_id(clean_context):
    token = bind_request_id("req_123")
    try:
        record = make_record()
        assert RequestContextFilter().filter(record) is True
        assert record.request_id == "req_123"
    finally:
        reset_request_id(token)


def test_filter_never_drops_records(clean_context):
    record = make_record()
    assert RequestContextFilter().filter(record) is True
    assert emit(record)["message"] == "hello"


def test_context_ids_omitted_when_unbound(clean_context):
    record = make_record()
    RequestContextFilter().filter(record)
    payload = emit(record)
    assert "request_id" not in payload
    assert "trace_id" not in payload


def test_trace_id_binds_independently(clean_context):
    token = bind_trace_id("trace_xyz")
    try:
        record = make_record()
        RequestContextFilter().filter(record)
        payload = emit(record)
    finally:
        reset_trace_id(token)

    assert payload["trace_id"] == "trace_xyz"
    assert "request_id" not in payload


def test_explicit_extra_request_id_wins_over_context(clean_context):
    """A call site that knows better (e.g. replaying a stored event) keeps its ID."""
    token = bind_request_id("req_ambient")
    try:
        record = make_record("replay", request_id="req_explicit")
        RequestContextFilter().filter(record)
    finally:
        reset_request_id(token)

    assert emit(record)["request_id"] == "req_explicit"


# ---------------------------------------------------------------------------
# record.request fallback — Django's own 4xx/5xx access-log lines
#
# BaseHandler.get_response() calls log_response(..., request=request) *after*
# _middleware_chain(request) returns, i.e. after RequestIDMiddleware's
# `finally: reset_request_id(token)` has already fired — so the contextvar is
# empty by the time django.request's auto-logged 4xx/5xx line is built. The
# request object itself (still referenced via record.request, which
# log_response's request= kwarg lands on) is untouched by that reset.
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, request_id):
        self.id = request_id


def test_filter_falls_back_to_record_request_id_when_context_is_unbound(clean_context):
    record = make_record(request=_FakeRequest("req_from_response"))
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == "req_from_response"


def test_filter_prefers_contextvar_over_record_request(clean_context):
    """The common case (an app-level logger.*() call during view processing,
    or any line logged before the middleware's `finally` fires) should keep
    using the contextvar — the record.request fallback only matters once it's
    already empty."""
    token = bind_request_id("req_context")
    try:
        record = make_record(request=_FakeRequest("req_from_response"))
        RequestContextFilter().filter(record)
    finally:
        reset_request_id(token)

    assert record.request_id == "req_context"


def test_filter_fallback_is_empty_when_record_has_no_request(clean_context):
    record = make_record()
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == ""


def test_filter_fallback_is_empty_when_record_request_is_none(clean_context):
    record = make_record(request=None)
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == ""


def test_filter_fallback_ignores_a_non_string_request_id(clean_context):
    """Defensive: whatever set .id on the request-like object may not have
    put a string there — don't propagate a non-string into a CharField."""
    record = make_record(request=_FakeRequest(12345))
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == ""


def test_filter_fallback_survives_a_request_object_that_raises(clean_context):
    """A filter must never raise — that would drop the record it's enriching,
    which is precisely the failure mode this whole fallback exists to avoid."""

    class ExplodingRequest:
        @property
        def id(self):
            raise RuntimeError("boom")

    record = make_record(request=ExplodingRequest())
    assert RequestContextFilter().filter(record) is True
    assert record.request_id == ""


def test_filter_fallback_survives_record_request_itself_raising_on_access(clean_context):
    """Belt-and-suspenders: even a record whose `request` attribute access
    itself explodes (not just `.id` on it) must not crash the filter."""

    class WeirdRecord:
        name = "apps.weird"

        @property
        def request(self):
            raise RuntimeError("no request for you")

        def __getattr__(self, item):
            if item in ("request_id", "trace_id"):
                return ""
            raise AttributeError(item)

    record = WeirdRecord()
    assert RequestContextFilter().filter(record) is True


# ---------------------------------------------------------------------------
# End-to-end: Django's own auto-logged 4xx access log line
# ---------------------------------------------------------------------------


def test_django_auto_logged_404_carries_request_id_matching_the_response_header(clean_context):
    """Regression for the blocker finding: exercised through the real Django
    request/response cycle (test Client -> BaseHandler.get_response ->
    log_response), not a hand-built LogRecord, so it actually pins the bug —
    a hand-built record could pass even if RequestIDMiddleware/BaseHandler's
    real interaction were still broken.
    """
    from django.test import Client

    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    collector = _Collect()
    collector.addFilter(RequestContextFilter())
    django_request_logger = logging.getLogger("django.request")
    original_level = django_request_logger.level
    original_disabled = django_request_logger.disabled
    # Test settings ship `LOGGING = {"disable_existing_loggers": True, ...}` to
    # keep the suite quiet — which, as a side effect, disables the
    # already-created "django.request" logger outright. Undo that just for
    # this test, or the record never reaches any handler regardless of level.
    django_request_logger.disabled = False
    django_request_logger.addHandler(collector)
    django_request_logger.setLevel(logging.WARNING)
    try:
        response = Client().get("/this-path-does-not-exist-anywhere-in-the-urlconf/")
    finally:
        django_request_logger.removeHandler(collector)
        django_request_logger.setLevel(original_level)
        django_request_logger.disabled = original_disabled

    assert response.status_code == 404
    response_request_id = response["X-Request-ID"]
    assert response_request_id

    matching = [r for r in records if r.name == "django.request"]
    assert matching, "django.request should have auto-logged the 404"
    assert matching[-1].request_id == response_request_id


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def test_timestamp_is_utc_iso8601():
    """UTC with a Z suffix so lines from different hosts sort correctly."""
    time_field = emit(make_record())["time"]
    assert time_field.endswith("Z")
    assert time_field[4] == "-" and time_field[10] == "T"


# ---------------------------------------------------------------------------
# Development text formatter
# ---------------------------------------------------------------------------


def test_text_formatter_appends_request_id(clean_context):
    formatter = TextFormatter(fmt="{levelname} {name} {message}", style="{")
    token = bind_request_id("req_123")
    try:
        record = make_record("Ticket closed")
        RequestContextFilter().filter(record)
        line = formatter.format(record)
    finally:
        reset_request_id(token)

    assert line == "INFO apps.tickets.views Ticket closed request_id=req_123"


def test_text_formatter_stays_quiet_without_context(clean_context):
    formatter = TextFormatter(fmt="{levelname} {message}", style="{")
    record = make_record("startup")
    RequestContextFilter().filter(record)
    assert formatter.format(record) == "INFO startup"


# ---------------------------------------------------------------------------
# Middleware wiring
# ---------------------------------------------------------------------------


def test_middleware_binds_request_id_for_the_duration_of_the_request():
    seen = {}

    def get_response(request):
        seen["during"] = get_request_id()
        return _Response()

    response = RequestIDMiddleware(get_response)(RequestFactory().get("/"))

    assert seen["during"].startswith("req_")
    assert seen["during"] == response["X-Request-ID"]


def test_middleware_reuses_upstream_request_id():
    seen = {}

    def get_response(request):
        seen["during"] = get_request_id()
        return _Response()

    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="req_from_lb")
    response = RequestIDMiddleware(get_response)(request)

    assert seen["during"] == "req_from_lb"
    assert response["X-Request-ID"] == "req_from_lb"


def test_middleware_resets_context_after_the_request():
    """WSGI threads are reused — a leak would mis-tag the next request."""
    RequestIDMiddleware(lambda request: _Response())(RequestFactory().get("/"))
    assert get_request_id() == ""


def test_middleware_resets_context_when_the_view_raises():
    def boom(request):
        raise RuntimeError("view exploded")

    with pytest.raises(RuntimeError):
        RequestIDMiddleware(boom)(RequestFactory().get("/"))

    assert get_request_id() == ""


class _Response(dict):
    """Minimal stand-in for HttpResponse — only __setitem__ is exercised."""


# ---------------------------------------------------------------------------
# Settings wiring
# ---------------------------------------------------------------------------


def load_logging_config(module_path, monkeypatch):
    """Import a settings module and hand back its LOGGING dict.

    production.py reads required env vars at import time (SECRET_KEY,
    ALLOWED_HOSTS), so supply throwaway values. Importing the module has no
    effect on django.conf.settings — the suite stays on config.settings.test.
    """
    import importlib

    monkeypatch.setenv("SECRET_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    return importlib.import_module(module_path).LOGGING


@pytest.mark.parametrize("module_path", ["config.settings.development", "config.settings.production"])
def test_settings_logging_config_is_valid(module_path, monkeypatch):
    """Catch typos in the LOGGING dicts — the test settings override them, so
    nothing else in the suite ever exercises these."""
    logging_config = load_logging_config(module_path, monkeypatch)

    # Validate formatters/filters/handlers only. Keeping "root"/"loggers" out
    # means dictConfig doesn't tear down the handlers the test session is using.
    probe = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": logging_config.get("filters", {}),
        "formatters": logging_config["formatters"],
        "handlers": {
            name: handler for name, handler in logging_config["handlers"].items() if name != "file"
        },  # the file handler would create/open LOG_FILE on disk
    }
    logging.config.dictConfig(probe)


@pytest.mark.parametrize("module_path", ["config.settings.development", "config.settings.production"])
def test_console_handler_carries_the_request_context_filter(module_path, monkeypatch):
    logging_config = load_logging_config(module_path, monkeypatch)
    assert "request_context" in logging_config["handlers"]["console"]["filters"]


def test_request_in_extra_is_reduced_to_method_and_path():
    """django.request records carry the HttpRequest in extra; its repr includes
    the query string, where a feed's ?token=<raw key> rides. Neither the JSON
    line nor the telemetry row may contain it. (Audit 2026-09-13, C3.)"""
    from apps.smallstack.logging import extract_extra

    request = RequestFactory().get("/feed/private.rss?token=SUPERSECRETTOKEN123")
    record = make_record("Internal Server Error", status_code=500, request=request)

    line = JSONFormatter().format(record)
    assert "SUPERSECRETTOKEN123" not in line
    assert "/feed/private.rss" in line
    assert "SUPERSECRETTOKEN123" not in str(extract_extra(record))
