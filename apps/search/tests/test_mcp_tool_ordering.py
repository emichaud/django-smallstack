"""Regression (base QA L3): a search view registered *after* SearchConfig.ready()
— e.g. from a later app in INSTALLED_APPS calling ``registry.register()`` from its
own ready() — must still get its per-model ``search_<plural>`` MCP tool.

Before the fix, ``register_search_tools()`` iterated ``all_views()`` once, eagerly,
during search's own ready(). Any model registered later (a downstream package's
``Document``) was missing from the registry at that instant, so no tool was created
for it, while ``search_all`` / ``search_help`` survived. Registration is now
order-independent via a registry hook.
"""

from __future__ import annotations

import pytest

from apps.smallstack.crud import CRUDView

pytestmark = pytest.mark.django_db

_LATE_LABEL = "heartbeat.Heartbeat"
_LATE_TOOL = "search_late_reg_docs"


def _late_search_view():
    from apps.heartbeat.models import Heartbeat

    return type(
        "LateRegisteredSearchView",
        (CRUDView,),
        {
            "model": Heartbeat,  # not search-registered by default → clean slate
            "url_base": "late-reg-test",
            "enable_search": True,
            "search_fields": ["status"],
            "mcp_tool_noun_plural": "late_reg_docs",
        },
    )


def test_late_registration_still_creates_its_mcp_tool():
    from apps.mcp.server import TOOL_HANDLERS, clear_registry_for_tests
    from apps.search.mcp_tools import register_search_tools
    from apps.search.registry import register, unregister

    clear_registry_for_tests()
    try:
        # Full run: registers the currently-registered views' tools AND subscribes
        # the hook that makes future registrations order-independent.
        register_search_tools()
        assert _LATE_TOOL not in TOOL_HANDLERS  # view not registered yet
        # site-level tools from the full run are present
        assert "search_all" in TOOL_HANDLERS and "search_help" in TOOL_HANDLERS

        # Simulate a downstream app registering a search view from its ready(),
        # which runs *after* search's ready() already fired register_search_tools().
        register(_late_search_view())

        # The per-model tool now exists — created by the registry hook, not lost
        # to app-ready ordering.
        assert _LATE_TOOL in TOOL_HANDLERS
    finally:
        unregister(_LATE_LABEL)
        clear_registry_for_tests()
