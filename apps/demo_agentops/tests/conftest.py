"""Re-register this app's MCP tool before every test.

The MCP suite calls ``clear_registry_for_tests()``, so whether our tool exists
would otherwise depend on test ordering (the approvals/telemetry conftest
precedent).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reregister_agentops_tools():
    try:
        from apps.demo_agentops.mcp_tools import register_agentops_tools

        register_agentops_tools()
    except Exception:  # noqa: BLE001 — a registry hiccup must not fail the suite
        pass
    yield
