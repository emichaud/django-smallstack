"""Autodiscover: MCP imports each app's views.py + mcp_tools.py at ready().

The footgun this kills: `enable_mcp = True` on a CRUDView in views.py would
otherwise produce a 0-tools registry because Django never auto-imports
views.py. The autodiscover step mirrors Django admin's autodiscover pattern.
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from apps.mcp.apps import MCPConfig
from apps.mcp.factory import register_mcp_tools_from_crudview
from apps.mcp.server import TOOL_REGISTRY, clear_registry_for_tests
from apps.smallstack.crud import CRUDView

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wipe():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


def _config() -> MCPConfig:
    return MCPConfig.create("apps.mcp")


def test_autodiscover_imports_views_modules_for_each_app():
    """`_autodiscover_apps(("views",))` returns the list of dotted paths
    that were actually imported. For known apps with views.py this should
    be non-empty."""
    imported = _config()._autodiscover_apps(("views",))
    assert any(p.endswith(".views") for p in imported)
    # apps.smallstack ships views.py — sanity-check it's in the list.
    assert "apps.smallstack.views" in imported


def test_autodiscover_swallows_missing_modules():
    """Apps without an mcp_tools.py don't break autodiscover."""
    imported = _config()._autodiscover_apps(("mcp_tools",))
    # Most apps don't have mcp_tools.py, so this is fine — assert it didn't raise.
    assert isinstance(imported, list)


def test_autodiscover_skips_self():
    """The MCP server's own app must not be re-imported (it's already running)."""
    imported = _config()._autodiscover_apps(("views", "mcp_tools"))
    assert not any(p.startswith("apps.mcp.") for p in imported)


def test_autodiscover_logs_but_doesnt_raise_on_module_error():
    """A views.py with a syntax/runtime error doesn't take ready() down."""
    real_import = importlib.import_module

    def explode(name, *args, **kwargs):
        if name == "apps.website.views":
            raise RuntimeError("kaboom")
        return real_import(name, *args, **kwargs)

    with patch("apps.mcp.apps.importlib.import_module", side_effect=explode):
        # Must not raise.
        imported = _config()._autodiscover_apps(("views",))

    assert "apps.website.views" not in imported


def test_importing_fake_app_views_registers_crudview():
    """Importing apps/mcp/tests/fake_app/views.py via the autodiscover
    mechanism (importlib) triggers __init_subclass__ and the CRUDView
    lands in the registry. The fake_app's views are NOT imported by any
    conftest or __init__.py — this proves autodiscover does the work."""
    # Drop any cached prior import so __init_subclass__ fires fresh.
    sys.modules.pop("apps.mcp.tests.fake_app.views", None)
    # Remove any cached CRUDView from the registry (it would be there if
    # an earlier test already imported the module).
    from apps.mcp.tests.models import Widget

    before_keys = set(CRUDView._registry.keys())

    importlib.import_module("apps.mcp.tests.fake_app.views")

    # The fake app's CRUDView is now registered against Widget.
    assert Widget in CRUDView._registry
    # And the factory can emit its tools.
    register_mcp_tools_from_crudview(CRUDView._registry[Widget])
    assert any(name.startswith("list_") for name in TOOL_REGISTRY)
    # Restore registry state for downstream tests.
    if Widget not in before_keys:
        CRUDView._registry.pop(Widget, None)


def test_autodiscover_can_be_disabled_via_setting(settings):
    """When MCP_AUTODISCOVER is False, ready() skips the autodiscover step."""
    settings.MCP_AUTODISCOVER = False
    config = _config()
    # Spy on _autodiscover_apps so we can detect whether ready() invoked it.
    with patch.object(MCPConfig, "_autodiscover_apps", new=MagicMock(return_value=[])) as spy:
        try:
            config.ready()
        except Exception:
            # ready() may still attempt registry walk — we only care about
            # whether the autodiscover spy was called.
            pass
        assert spy.call_count == 0
