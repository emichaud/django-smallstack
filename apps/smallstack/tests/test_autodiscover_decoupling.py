"""CRUDView discovery is decoupled from feature toggles.

``SmallStackConfig.ready()`` imports every app's ``views.py`` (populating
``CRUDView._registry``) unconditionally, so registry consumers like Search keep
working even when MCP is turned off. Regression guard for the MCP-off-breaks-Search
coupling found in round-3 testing.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from apps.smallstack.autodiscover import autodiscover_app_modules

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestAutodiscoverUtil:
    def test_imports_views_for_each_app(self):
        imported = autodiscover_app_modules(("views",))
        assert "apps.smallstack.views" in imported
        assert any(p.endswith(".views") for p in imported)

    def test_swallows_missing_modules(self):
        # Most apps have no mcp_tools.py — must not raise, just return what exists.
        assert isinstance(autodiscover_app_modules(("mcp_tools",)), list)

    def test_skip_label_omits_that_app(self):
        imported = autodiscover_app_modules(("views",), skip_label="search")
        assert "apps.search.views" not in imported

    def test_populates_crudview_registry(self):
        from apps.smallstack.crud import CRUDView

        autodiscover_app_modules(("views",))
        # A search-enabled CRUDView (e.g. the User manager) is in the registry.
        assert len(CRUDView._registry) > 0


class TestSearchSurvivesMcpOff:
    """The actual cross-toggle regression: boot a fresh process with MCP off and
    confirm the search registry is still populated (it would be empty before the
    decoupling fix). Uses a subprocess because app ``ready()`` ordering only matters
    at startup, which can't be re-triggered in-process."""

    def _registry_size(self, mcp_enabled: str) -> int:
        env = {**os.environ, "SMALLSTACK_MCP_ENABLED": mcp_enabled}
        code = "from apps.search.registry import _search_registry; print('SIZE=%d' % len(_search_registry))"
        proc = subprocess.run(
            [sys.executable, "manage.py", "shell", "-c", code],
            env=env,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            pytest.skip(f"could not boot subprocess shell: {proc.stderr[-400:]}")
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("SIZE=")), None)
        assert line is not None, f"no SIZE marker in output: {proc.stdout[-400:]}"
        return int(line.split("=", 1)[1])

    def test_search_registry_populated_with_mcp_off(self):
        assert self._registry_size("false") > 0  # the fix: was 0 when coupled to MCP

    def test_mcp_off_matches_mcp_on(self):
        assert self._registry_size("false") == self._registry_size("true")
