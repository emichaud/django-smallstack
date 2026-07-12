"""Shared fixtures for the runbook test suite."""

import pytest


@pytest.fixture(autouse=True)
def _ensure_runbook_mcp_tools_registered():
    """Re-register the ``runbook_*`` MCP tools before each test.

    The MCP test suite's ``clean_registry`` fixture calls
    ``clear_registry_for_tests()``, which wipes the shared ``TOOL_HANDLERS`` /
    ``TOOL_REGISTRY`` — including the runbook tools registered at startup. Without
    this, whether the runbook MCP tests find their tools depends on test ordering
    (they pass alone, fail after an MCP test). ``register_runbook_tools()`` is
    idempotent and a no-op when ``apps.mcp`` isn't installed.
    """
    from apps.runbook.mcp_tools import register_runbook_tools

    register_runbook_tools()
