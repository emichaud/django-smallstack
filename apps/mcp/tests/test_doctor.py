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
    # Patch the registry to be empty AND the scanner to return a hit.
    with patch("apps.mcp.management.commands.mcp_doctor.TOOL_REGISTRY", {}), patch.object(
        Command, "_scan_for_enable_mcp_optins", return_value=["apps/foo/views.py"]
    ):
        cmd._check_registry(report)

    entry = report[0]
    assert entry["status"] == "WARN"
    assert "apps/foo/views.py" in entry["detail"]
    assert "AppConfig.ready" in entry["detail"]


def test_doctor_passes_when_registry_empty_and_no_optins():
    """Empty registry + no `enable_mcp = True` anywhere = nothing to warn
    about. Stays PASS."""
    from unittest.mock import patch

    from apps.mcp.management.commands.mcp_doctor import Command

    report: list[dict] = []
    cmd = Command()
    with patch("apps.mcp.management.commands.mcp_doctor.TOOL_REGISTRY", {}), patch.object(
        Command, "_scan_for_enable_mcp_optins", return_value=[]
    ):
        cmd._check_registry(report)

    assert report[0]["status"] == "PASS"


def test_scanner_skips_tests_and_migrations(tmp_path, monkeypatch):
    """The scanner ignores tests/ and migrations/ dirs — those are full
    of `enable_mcp = True` in fixtures and would always trigger the WARN."""
    from unittest.mock import MagicMock

    from apps.mcp.management.commands.mcp_doctor import Command

    # Simulate a fake app with the marker in views.py + tests/conftest.py
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

    with monkeypatch.context() as m:
        m.setattr(
            "apps.mcp.management.commands.mcp_doctor.django_apps_get_app_configs"
            if False
            else "django.apps.apps.get_app_configs",
            lambda: [fake_cfg],
        )
        hits = Command()._scan_for_enable_mcp_optins()

    # Only the views.py hit should appear — tests/ and migrations/ skipped.
    assert any("views.py" in h for h in hits)
    assert not any("conftest.py" in h for h in hits)
    assert not any("0001.py" in h for h in hits)
