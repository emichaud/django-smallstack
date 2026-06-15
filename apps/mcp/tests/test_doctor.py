"""mcp_doctor management command."""

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_doctor_exits_clean(capsys):
    User.objects.create_user(username="docuser", password="x", is_staff=True)
    call_command("mcp_doctor", "--no-self-test")
    out = capsys.readouterr().out
    assert "SmallStack MCP" in out


def test_doctor_json_emits_parseable_json():
    out = StringIO()
    call_command("mcp_doctor", "--no-self-test", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert isinstance(data, list)
    assert any(row["name"] == "URL conf" for row in data)


def test_self_test_runs_against_real_user(capsys):
    User.objects.create_user(username="docuser2", password="x", is_staff=True)
    call_command("mcp_doctor")
    out = capsys.readouterr().out
    assert "Self-test" in out


def test_doctor_warns_when_registry_empty_but_optin_exists_in_tree():
    """If `enable_mcp = True` appears in the tree but the registry is
    empty, the operator hit the import-ordering footgun. Downgrade to
    WARN with the actionable hint."""
    from unittest.mock import patch

    from apps.mcp.management.commands.mcp_doctor import Command

    report: list[dict] = []
    cmd = Command()
    with patch("apps.mcp.management.commands.mcp_doctor.TOOL_REGISTRY", {}), patch.object(
        Command, "_find_unregistered_optins", return_value=["apps/foo/views.py"]
    ):
        cmd._check_registry(report)

    entry = report[0]
    assert entry["status"] == "WARN"
    assert "apps/foo/views.py" in entry["detail"]
    assert "AppConfig.ready" in entry["detail"]
    # WARN message must mention MCP_AUTODISCOVER first so operators who
    # turned it off don't chase `from . import views` as the fix.
    assert entry["detail"].index("MCP_AUTODISCOVER") < entry["detail"].index(
        "from . import"
    )


def test_doctor_warns_on_partial_orphan_even_when_registry_not_empty():
    """The dangerous case: 10 working CRUDViews + 1 stranded in a
    non-standard module. Doctor must surface the orphan even though the
    registry is non-empty."""
    from unittest.mock import patch

    from apps.mcp.management.commands.mcp_doctor import Command

    report: list[dict] = []
    cmd = Command()
    fake_registry = {"list_widgets": object(), "get_widget": object()}
    with patch(
        "apps.mcp.management.commands.mcp_doctor.TOOL_REGISTRY", fake_registry
    ), patch.object(
        Command, "_find_unregistered_optins", return_value=["apps/bar/crud_legacy.py"]
    ):
        cmd._check_registry(report)

    entry = report[0]
    assert entry["status"] == "WARN"
    # The WARN text acknowledges the registry has some tools.
    assert "2 tools registered" in entry["detail"]
    assert "apps/bar/crud_legacy.py" in entry["detail"]


def test_doctor_passes_when_registry_empty_and_no_optins():
    """Empty registry + no `enable_mcp = True` anywhere = nothing to warn
    about. Stays PASS."""
    from unittest.mock import patch

    from apps.mcp.management.commands.mcp_doctor import Command

    report: list[dict] = []
    cmd = Command()
    with patch("apps.mcp.management.commands.mcp_doctor.TOOL_REGISTRY", {}), patch.object(
        Command, "_find_unregistered_optins", return_value=[]
    ):
        cmd._check_registry(report)

    assert report[0]["status"] == "PASS"


def test_find_unregistered_diffs_orphan_files_against_registered_views():
    """An orphan file whose CRUDView IS in the registry doesn't show up as
    unregistered. Only files NOT represented in the registry are returned."""
    import inspect
    from pathlib import Path
    from unittest.mock import patch

    from apps.mcp.management.commands.mcp_doctor import Command
    from apps.mcp.tests.fake_app.views import AutodiscoverWidgetCRUDView
    from apps.smallstack.crud import CRUDView

    # Ensure the fake app's CRUDView is registered (it is once views.py imports).
    CRUDView._registry[AutodiscoverWidgetCRUDView.model] = AutodiscoverWidgetCRUDView
    registered_file = Path(inspect.getfile(AutodiscoverWidgetCRUDView)).resolve()

    # Scan returns:
    #   - the file that IS registered (should be filtered out)
    #   - a different "orphan" file (should appear in the result)
    orphan_path = Path("/tmp/orphan/crud.py")
    scanned = [
        (registered_file, "fake_app/views.py"),
        (orphan_path, "orphan/crud.py"),
    ]
    with patch.object(Command, "_scan_for_enable_mcp_optins", return_value=scanned):
        result = Command()._find_unregistered_optins()

    assert result == ["orphan/crud.py"]


def test_scanner_skips_tests_and_migrations(tmp_path, monkeypatch):
    """The scanner ignores tests/ and migrations/ dirs — those are full
    of `enable_mcp = True` in fixtures and would always trigger the WARN."""
    from unittest.mock import MagicMock

    from apps.mcp.management.commands.mcp_doctor import Command

    fake_app = tmp_path / "fake_app"
    fake_app.mkdir()
    (fake_app / "views.py").write_text("enable_mcp = True\n")
    (fake_app / "tests").mkdir()
    (fake_app / "tests" / "conftest.py").write_text("enable_mcp = True\n")
    (fake_app / "migrations").mkdir()
    (fake_app / "migrations" / "0001.py").write_text("enable_mcp = True\n")

    fake_cfg = MagicMock()
    fake_cfg.label = "fake_app"
    fake_cfg.path = str(fake_app)

    monkeypatch.setattr("django.apps.apps.get_app_configs", lambda: [fake_cfg])
    hits = Command()._scan_for_enable_mcp_optins()
    # Hits are (path, display) tuples — inspect the display element.
    displays = [d for _, d in hits]
    assert any("views.py" in d for d in displays)
    assert not any("conftest.py" in d for d in displays)
    assert not any("0001.py" in d for d in displays)


# ---------------------------------------------------------------------------
# --explain
# ---------------------------------------------------------------------------


@pytest.fixture
def _registered_tool():
    """Put one concrete tool in the registry for the --explain tests."""
    from apps.mcp.factory import register_mcp_tools_from_crudview
    from apps.mcp.server import clear_registry_for_tests
    from apps.mcp.tests.fake_app.views import AutodiscoverWidgetCRUDView

    clear_registry_for_tests()
    register_mcp_tools_from_crudview(AutodiscoverWidgetCRUDView)
    yield
    clear_registry_for_tests()


def test_explain_dumps_all_tools(_registered_tool, capsys):
    """--explain (no tool name) dumps every registered tool's schema."""
    call_command("mcp_doctor", "--explain")
    out = capsys.readouterr().out
    assert "list_autodiscover_widgets" in out
    assert "get_widget" in out
    assert "inputSchema" in out
    assert "description:" in out


def test_explain_filters_to_a_single_tool(_registered_tool, capsys):
    """--explain <tool_name> dumps only that one tool."""
    call_command("mcp_doctor", "--explain", "get_widget")
    out = capsys.readouterr().out
    assert "get_widget" in out
    assert "list_autodiscover_widgets" not in out
    assert '"pk"' in out  # inputSchema includes pk


def test_explain_with_unknown_tool_exits_nonzero(_registered_tool, capsys):
    """Asking for a tool that doesn't exist exits 1 with an actionable
    list of what IS registered."""
    with pytest.raises(SystemExit) as excinfo:
        call_command("mcp_doctor", "--explain", "no_such_tool")
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "no_such_tool" in out
    assert "list_autodiscover_widgets" in out  # the suggested alternatives


def test_explain_with_json_is_parseable(_registered_tool):
    """--explain --json emits a JSON array of tool dicts."""
    out = StringIO()
    call_command("mcp_doctor", "--explain", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert isinstance(data, list)
    names = [t["name"] for t in data]
    assert "list_autodiscover_widgets" in names
    sample = next(t for t in data if t["name"] == "get_widget")
    assert sample["inputSchema"]["properties"]["pk"]["type"] == "integer"
    assert sample["write"] is False


def test_explain_handles_empty_registry(capsys):
    """No tools registered → friendly "(no tools registered)" line, exit 0."""
    from apps.mcp.server import clear_registry_for_tests

    clear_registry_for_tests()
    call_command("mcp_doctor", "--explain")
    out = capsys.readouterr().out
    assert "no tools registered" in out.lower()
