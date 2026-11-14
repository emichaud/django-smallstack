"""mcp_doctor opt-in scan — AST detection, not substring matching.

Regression guard for the false positive where `enable_mcp = True` inside a
docstring / seed-content string (e.g. the runbook seed command) was reported as
an unregistered CRUDView opt-in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.mcp.management.commands.mcp_doctor import _has_enable_mcp_classvar
from apps.smallstack.autodiscover import has_enable_classvar, is_test_module


def test_real_class_attribute_is_detected():
    src = "class TicketView(CRUDView):\n    enable_mcp = True\n"
    assert _has_enable_mcp_classvar(src) is True


def test_annotated_class_attribute_is_detected():
    src = "class TicketView(CRUDView):\n    enable_mcp: bool = True\n"
    assert _has_enable_mcp_classvar(src) is True


def test_marker_in_docstring_is_ignored():
    src = '''
class SeedCommand:
    """Teaching example embedded in docs:

        class TicketView(CRUDView):
            enable_mcp = True
    """
    help = "seed"
'''
    assert _has_enable_mcp_classvar(src) is False


def test_marker_in_string_literal_is_ignored():
    src = 'CONTENT = "class X(CRUDView):\\n    enable_mcp = True\\n"\n'
    assert _has_enable_mcp_classvar(src) is False


def test_marker_in_comment_is_ignored():
    src = "class X(CRUDView):\n    pass  # enable_mcp = True (not really)\n"
    assert _has_enable_mcp_classvar(src) is False


def test_enable_mcp_false_is_not_flagged():
    src = "class X(CRUDView):\n    enable_mcp = False\n"
    assert _has_enable_mcp_classvar(src) is False


def test_module_level_assignment_is_not_a_class_attribute():
    src = "enable_mcp = True\n"
    assert _has_enable_mcp_classvar(src) is False


def test_syntax_error_is_handled_gracefully():
    assert _has_enable_mcp_classvar("class X(:\n  enable_mcp = True") is False


class TestSharedAcrossBothMarkers:
    """`has_enable_classvar` backs both doctors, so both markers get the checks.

    api_doctor used to detect opt-ins with a line-anchored regex while this
    doctor used AST — so the two disagreed about what an opt-in *is*, and
    api_doctor was protected from docstring false positives only because it
    skipped `management/`, where the one offending example happens to live.
    """

    @pytest.mark.parametrize("marker", ["enable_api", "enable_mcp"])
    def test_class_attribute_is_detected(self, marker):
        assert has_enable_classvar(f"class V(CRUDView):\n    {marker} = True\n", marker) is True

    @pytest.mark.parametrize("marker", ["enable_api", "enable_mcp"])
    def test_docstring_example_is_ignored(self, marker):
        src = f'''
class Docs:
    """Example:

        class TicketView(CRUDView):
            {marker} = True
    """
    pass
'''
        assert has_enable_classvar(src, marker) is False

    @pytest.mark.parametrize("marker", ["enable_api", "enable_mcp"])
    def test_prefixed_name_is_not_the_marker(self, marker):
        """`explorer_enable_api` is a different flag and must not match."""
        src = f"class V(CRUDView):\n    explorer_{marker} = True\n"
        assert has_enable_classvar(src, marker) is False

    @pytest.mark.parametrize("marker", ["enable_api", "enable_mcp"])
    def test_false_value_is_not_an_optin(self, marker):
        assert has_enable_classvar(f"class V:\n    {marker} = False\n", marker) is False

    def test_markers_do_not_bleed_into_each_other(self):
        src = "class V(CRUDView):\n    enable_mcp = True\n"
        assert has_enable_classvar(src, "enable_mcp") is True
        assert has_enable_classvar(src, "enable_api") is False


class TestTestModuleExclusion:
    """A CRUDView defined in a test is a fixture, never a deployed surface.

    The scan excluded a ``tests/`` package but not the flat ``test_*.py``
    convention `apps/smallstack` uses, so `smallstack/test_bulk_ops.py` was
    reported as an orphan on every run — a permanent WARN with no action behind
    it, which is how a health check stops being read.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "apps/smallstack/tests/test_bulk_ops.py",  # the file that tripped it
            "apps/foo/test_views.py",
            "apps/foo/views_test.py",
            "apps/foo/conftest.py",
            "apps/foo/tests/test_x.py",
            "apps/foo/tests/fake_app/views.py",
        ],
    )
    def test_test_modules_are_excluded(self, path):
        assert is_test_module(Path(path)) is True

    @pytest.mark.parametrize(
        "path",
        [
            "apps/scheduler/views.py",
            "apps/webhooks/views.py",
            "apps/foo/mcp_tools.py",
            "apps/foo/latest_test_results.py",  # 'test' inside the name, not a test module
            "apps/protests/views.py",  # 'test' as a substring of a dir name
        ],
    )
    def test_real_modules_are_not_excluded(self, path):
        assert is_test_module(Path(path)) is False

    def test_bulk_ops_fixture_is_a_real_optin_but_still_skipped(self):
        """Both halves matter: it genuinely declares the flag, and is still skipped.

        If it were skipped only because the AST check missed it, the exclusion
        would be masking a detection bug rather than filtering a fixture.
        """
        target = Path(__file__).resolve().parents[3] / "apps/smallstack/tests/test_bulk_ops.py"
        if not target.exists():
            pytest.skip("bulk-ops test module not present")
        assert _has_enable_mcp_classvar(target.read_text(encoding="utf-8")) is True
        assert is_test_module(target) is True


def test_seed_runbook_command_is_not_flagged():
    """The concrete file that tripped the old substring scan."""
    from pathlib import Path

    seed = (
        Path(__file__).resolve().parents[3]
        / "apps/runbook/management/commands/seed_platform_runbook.py"
    )
    if not seed.exists():
        import pytest

        pytest.skip("runbook seed command not present")
    source = seed.read_text(encoding="utf-8")
    assert "enable_mcp = True" in source  # the substring IS there…
    assert _has_enable_mcp_classvar(source) is False  # …but not as a class attr
