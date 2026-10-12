"""The MCP tool registries are restored after every test.

Several suites call ``clear_registry_for_tests()`` to test registration in
isolation. Before the root-conftest restore, that left ``TOOL_REGISTRY`` empty
for the rest of the process, so any later test asserting its app's tools were
registered (blog, runbook, webhooks, approvals, telemetry) depended on file
order — and each of those apps grew a conftest that re-registered its own
tools to cope. These two tests run in file order and pin the guarantee at the
source: a wipe in one test is invisible to the next.
"""

from __future__ import annotations

from apps.mcp.server import TOOL_HANDLERS, TOOL_REGISTRY, clear_registry_for_tests, isolated_tool_registry

# Tools that exist at startup on the shipped project: the search app's
# site-wide tool and the blog's generated one.
STARTUP_TOOLS = ("search_all", "search_blog_posts")


def test_1_a_test_may_wipe_the_registry():
    for name in STARTUP_TOOLS:
        assert name in TOOL_REGISTRY, f"{name} missing before the wipe — the premise is wrong"
    clear_registry_for_tests()
    assert not TOOL_REGISTRY and not TOOL_HANDLERS


def test_2_the_next_test_still_sees_the_startup_tools():
    for name in STARTUP_TOOLS:
        assert name in TOOL_REGISTRY, f"{name} did not come back after the previous test's wipe"
        assert name in TOOL_HANDLERS


def test_isolated_tool_registry_restores_mutations_too():
    before = dict(TOOL_REGISTRY)
    with isolated_tool_registry():
        TOOL_REGISTRY.pop(STARTUP_TOOLS[0])
        TOOL_REGISTRY["ephemeral"] = TOOL_REGISTRY[STARTUP_TOOLS[1]]
        assert STARTUP_TOOLS[0] not in TOOL_REGISTRY
    assert TOOL_REGISTRY == before
