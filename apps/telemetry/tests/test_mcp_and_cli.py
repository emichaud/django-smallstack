"""Phase 3 — the MCP tools and the CLI read/JSON surfaces.

The point of these tests is less "does each transport work" than **do the three
transports agree**. Two of this feature's findings were one rule implemented
twice and drifting apart, so the tests that matter most here are the ones
asserting the REST API, the MCP tools and the CLI return the same answer for
the same question.
"""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.telemetry import queries
from apps.telemetry.models import LogRecord

pytestmark = pytest.mark.django_db


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


class _StaffStub:
    """Minimal staff user for tools that only need `.is_staff` / `.get_username`."""

    is_staff = True
    pk = 0

    def get_username(self):
        return "stub"


def run_tool(name: str, args: dict, *, user=None):
    """Dispatch a registered MCP tool the way the server does."""
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=_StaffStub() if user is None else user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(token)


def cli(command: str, *args, **kwargs) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out, **kwargs)
    return out.getvalue()


@pytest.fixture(autouse=True)
def _close_windows():
    yield
    from apps.telemetry import capture

    capture.stop()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def test_the_five_tools_are_registered_with_the_right_gating():
    """Read tools staff-only; capture tools additionally write=True, which is
    what makes the MCP auth layer refuse a read-only token."""
    import apps.telemetry.mcp_tools  # noqa: F401  (registers on import)
    from apps.mcp.server import TOOL_REGISTRY

    expected = {
        "logs_search": False,
        "logs_get": False,
        "logs_status": False,
        "logs_capture_start": True,
        "logs_capture_stop": True,
    }
    for name, is_write in expected.items():
        assert name in TOOL_REGISTRY, f"{name} not registered"
        assert TOOL_REGISTRY[name].write is is_write
        # Hidden from non-staff callers. NOT gated with requires_access="staff":
        # that checks the *token's* level, while the REST surface checks the
        # *user*. Handlers enforce the user check themselves — see below.
        assert TOOL_REGISTRY[name].visible_to is not None, f"{name} is visible to everyone"
        assert TOOL_REGISTRY[name].visible_to(_StaffStub()) is True


def test_tool_schemas_reject_unknown_properties():
    """additionalProperties:False lets a client catch a typo'd argument before
    the call, which is the schema-level version of the API's 400 rule."""
    import apps.telemetry.mcp_tools  # noqa: F401
    from apps.mcp.server import TOOL_REGISTRY

    for name in ("logs_search", "logs_get", "logs_status", "logs_capture_start", "logs_capture_stop"):
        assert TOOL_REGISTRY[name].input_schema.get("additionalProperties") is False, name


def test_capture_start_declares_note_required():
    import apps.telemetry.mcp_tools  # noqa: F401
    from apps.mcp.server import TOOL_REGISTRY

    assert TOOL_REGISTRY["logs_capture_start"].input_schema["required"] == ["note"]


# ---------------------------------------------------------------------------
# The tools do the right thing
# ---------------------------------------------------------------------------


def test_logs_search_filters_like_the_api():
    make_record(message="needle", request_id="req_x")
    make_record(message="haystack", request_id="req_y")

    result = run_tool("logs_search", {"request_id": "req_x"})

    assert [r["message"] for r in result["records"]] == ["needle"]
    assert result["applied_filters"]["request_id"] == "req_x"


def test_logs_search_rejects_an_unknown_argument():
    """Returned as data, not raised: an agent recovers from an error message by
    correcting the argument; a tool exception it tends to abandon."""
    make_record()
    result = run_tool("logs_search", {"sevrity": "ERROR"})

    assert "error" in result
    assert "sevrity" in result["error"]
    assert "records" not in result, "a bad filter must not return an unfiltered table"


def test_logs_search_rejects_a_bad_level_value():
    result = run_tool("logs_search", {"level": "LOUD"})
    assert "error" in result and "level must be one of" in result["error"]


def test_logs_get_returns_the_full_traceback():
    record = make_record(exc_text="Y" * 50_000, exc_type="BoomError")

    result = run_tool("logs_get", {"id": record.pk})

    assert result["exc_truncated"] is False
    assert len(result["exc_text"]) == 50_000


def test_logs_get_on_a_missing_id_is_an_error_not_a_crash():
    result = run_tool("logs_get", {"id": 999999})
    assert "error" in result


def test_logs_status_answers_the_orientation_questions():
    make_record(logger="apps.alpha")
    make_record(logger="apps.alpha")
    make_record(logger="apps.beta")

    result = run_tool("logs_status", {})

    assert result["capture"]["open"] is False
    assert result["config"]["baseline_level"]
    assert result["config"]["writable"] is False
    counts = {row["logger"]: row["count"] for row in result["top_loggers"]}
    assert counts["apps.alpha"] == 2


def test_capture_start_and_stop_through_the_tools(django_user_model):
    from apps.telemetry import capture

    user = django_user_model.objects.create_user(username="agent", password="pw12345!x", is_staff=True)

    started = run_tool("logs_capture_start", {"note": "agent investigating", "minutes": 5}, user=user)
    assert started["open"] is True
    assert capture.active_window() is not None, "the tool reported success without opening a window"

    stopped = run_tool("logs_capture_stop", {}, user=user)
    assert stopped["closed"] == 1
    assert capture.active_window() is None


def test_capture_start_requires_a_note_at_runtime_too(django_user_model):
    """The schema says required, but a client can still omit it — the handler
    must not depend on the schema being enforced upstream."""
    from apps.telemetry import capture

    user = django_user_model.objects.create_user(username="agent2", password="pw12345!x", is_staff=True)

    result = run_tool("logs_capture_start", {}, user=user)

    assert "error" in result and "note is required" in result["error"]
    assert capture.active_window() is None, "a rejected call still opened a window"


def test_capture_stop_is_idempotent(django_user_model):
    user = django_user_model.objects.create_user(username="agent3", password="pw12345!x", is_staff=True)
    result = run_tool("logs_capture_stop", {}, user=user)
    assert result["closed"] == 0


def test_capture_start_is_audited(django_user_model):
    from django.contrib.admin.models import LogEntry

    user = django_user_model.objects.create_user(username="agent4", password="pw12345!x", is_staff=True)
    before = LogEntry.objects.count()

    run_tool("logs_capture_start", {"note": "audit me"}, user=user)

    assert LogEntry.objects.count() == before + 1
    assert LogEntry.objects.latest("pk").user_id == user.pk


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_logs_command_prints_matching_records():
    make_record(message="findable line", level="ERROR", level_no=logging.ERROR)
    make_record(message="other line")

    output = cli("logs", "--level", "ERROR")

    assert "findable line" in output
    assert "other line" not in output


def test_logs_command_searches_tracebacks():
    make_record(message="it broke", exc_text="Traceback…\nValidationError: nope")

    assert "it broke" in cli("logs", "--search", "ValidationError")


def test_logs_command_json_matches_the_api_payload():
    """Same keys as /api/logger/records/ — a script moving between the shell
    and HTTP must not meet two vocabularies for one thing."""
    make_record()

    payload = json.loads(cli("logs", "--limit", "1", "--json"))

    assert set(payload) == {
        "records",
        "count",
        "has_more",
        "next_after_id",
        "total_matching",
        "applied_filters",
    }


def test_logs_command_detail_shows_the_traceback():
    record = make_record(exc_text="Traceback…\nBoomError: kaboom", exc_type="BoomError")

    output = cli("logs", "--id", str(record.pk))

    assert "BoomError: kaboom" in output


def test_a_bad_filter_is_a_command_error_not_a_traceback():
    """Exits non-zero with a usable message, which is what a script checks."""
    with pytest.raises(CommandError) as exc:
        cli("logs", "--level", "LOUD")
    assert "level must be one of" in str(exc.value)

    with pytest.raises(CommandError):
        cli("logs", "--id", "999999")


def test_empty_results_point_at_the_baseline():
    """The most common cause of 'no logs' is that they were never stored —
    invisible unless the tool says so."""
    output = cli("logs", "--logger", "apps.nothing")

    assert "No matching records" in output
    assert "baseline" in output


def test_log_capture_json_is_parseable():
    """The human output printed a Python dict repr (single quotes, False not
    false), so anything consuming it was screen-scraping non-JSON."""
    payload = json.loads(cli("log_capture", "status", "--json"))

    assert payload["open"] is False
    assert "baseline_level" in payload
    assert "handlers" in payload


def test_log_capture_start_stop_json_round_trip():
    from apps.telemetry import capture

    started = json.loads(cli("log_capture", "start", "--json", "--minutes", "5", "--note", "cli json"))
    assert started["open"] is True
    assert started["clamped"] is False
    assert capture.active_window() is not None

    stopped = json.loads(cli("log_capture", "stop", "--json"))
    assert stopped["closed"] == 1


def test_log_capture_start_json_reports_a_clamp(settings):
    settings.TELEMETRY_MAX_CAPTURE_MINUTES = 30
    payload = json.loads(cli("log_capture", "start", "--json", "--minutes", "600", "--note", "long"))
    assert payload["clamped"] is True
    assert payload["requested_minutes"] == 600


def test_prune_logs_json_reports_what_it_deleted():
    old = timezone.now() - timezone.timedelta(days=30)
    for _ in range(3):
        make_record(ts=old)
    make_record()

    payload = json.loads(cli("prune_logs", "--json", "--keep-days", "7"))

    assert payload["deleted_by_age"] == 3
    assert payload["remaining"] == 1


# ---------------------------------------------------------------------------
# The three transports agree — the reason queries.py exists
# ---------------------------------------------------------------------------


def test_api_mcp_and_cli_return_the_same_records_for_the_same_query(client, django_user_model):
    """One rule, three adapters. Drift between transports is the bug class this
    whole module is arranged to prevent."""
    staff = django_user_model.objects.create_user(username="cmp", password="pw12345!x", is_staff=True)
    client.force_login(staff)

    make_record(message="alpha", logger="apps.match", level="ERROR", level_no=logging.ERROR)
    make_record(message="beta", logger="apps.match", level="ERROR", level_no=logging.ERROR)
    make_record(message="excluded", logger="apps.match_other", level="ERROR", level_no=logging.ERROR)
    make_record(message="too low", logger="apps.match")

    query = {"logger": "apps.match", "level": "ERROR"}

    api_ids = [r["id"] for r in json.loads(client.get("/api/logger/records/", query).content)["records"]]
    mcp_ids = [r["id"] for r in run_tool("logs_search", dict(query))["records"]]
    cli_ids = [
        r["id"]
        for r in json.loads(cli("logs", "--logger", "apps.match", "--level", "ERROR", "--json"))["records"]
    ]

    assert api_ids == mcp_ids == cli_ids
    assert len(api_ids) == 2, "the sibling logger or the sub-level record leaked in"


def test_all_three_transports_reject_the_same_bad_level(client, django_user_model):
    staff = django_user_model.objects.create_user(username="cmp2", password="pw12345!x", is_staff=True)
    client.force_login(staff)

    assert client.get("/api/logger/records/", {"level": "LOUD"}).status_code == 400
    assert "error" in run_tool("logs_search", {"level": "LOUD"})
    with pytest.raises(CommandError):
        cli("logs", "--level", "LOUD")


def test_the_filter_list_is_the_same_everywhere():
    """The capability document, the MCP schema and the CLI flags all derive from
    queries.FILTER_NAMES, so adding a filter can't leave one surface behind."""
    import apps.telemetry.mcp_tools  # noqa: F401
    from apps.mcp.server import TOOL_REGISTRY
    from apps.telemetry.api import RECORD_FILTERS

    schema_props = set(TOOL_REGISTRY["logs_search"].input_schema["properties"])

    assert set(queries.FILTER_NAMES) == set(RECORD_FILTERS) == schema_props


# ---------------------------------------------------------------------------
# Access parity with the REST surface
# ---------------------------------------------------------------------------


class _NonStaff:
    is_staff = False
    pk = 1

    def get_username(self):
        return "plain"


@pytest.mark.parametrize(
    "name,args",
    [
        ("logs_search", {}),
        ("logs_get", {"id": 1}),
        ("logs_status", {}),
        ("logs_capture_start", {"note": "x"}),
        ("logs_capture_stop", {}),
    ],
)
def test_every_tool_refuses_a_non_staff_user(name, args):
    """MCP's requires_access gates the TOKEN's level; /api/logger/ gates the
    USER. A staff-*level* token minted for a non-staff user would otherwise read
    logs over MCP while being refused over REST. The framework only checks
    user.is_staff for CRUDView-derived tools, so these hand-written ones check
    it themselves."""
    from apps.telemetry import capture

    result = run_tool(name, args, user=_NonStaff())

    assert "error" in result, f"{name} served a non-staff user"
    assert "Staff" in result["error"]
    assert capture.active_window() is None, f"{name} had a side effect for a non-staff user"


def test_non_staff_cannot_even_see_the_tools():
    import apps.telemetry.mcp_tools  # noqa: F401
    from apps.mcp.server import TOOL_REGISTRY

    for name in ("logs_search", "logs_capture_start"):
        assert TOOL_REGISTRY[name].visible_to(_NonStaff()) is False


def test_capture_tools_are_write_so_readonly_tokens_are_refused():
    """The MCP auth layer turns write=True into 'read-only tokens rejected',
    which is how a read-only credential gets the same read/no-write split it
    has on the REST surface."""
    import apps.telemetry.mcp_tools  # noqa: F401
    from apps.mcp.auth import check_tool_access
    from apps.mcp.server import TOOL_REGISTRY

    class _Token:
        access_level = "readonly"
        user = _StaffStub()

    assert check_tool_access(_Token(), TOOL_REGISTRY["logs_capture_start"]) is not None
    assert check_tool_access(_Token(), TOOL_REGISTRY["logs_search"]) is None, (
        "a read-only token belonging to a staff user must still be able to READ, "
        "matching /api/logger/"
    )
