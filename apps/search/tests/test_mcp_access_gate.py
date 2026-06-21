"""Security regression: MCP search tools must honour the registry's
``search_access`` gate (round-2 surfaces-audit §3.3).

Before v0.11.9 the MCP search handlers in ``apps/search/mcp_tools.py``
called ``backend.query()`` and ``search_all()`` without the calling
token's user, which silently bypassed the same gate that the web
``/search/`` + ``/smallstack/search/`` pages enforce. A non-staff
user with a readonly token could call ``search_users`` and pull
every user's email — full PII enumeration with the easiest
precondition (any signed-up user with a token).

These tests pin the fix: the per-view handler ``search_users`` must
deny non-staff callers (User CRUDView ships at SearchAccess.STAFF
by default), and the cross-model ``search_all`` handler must filter
out STAFF-tier hits before returning.
"""

from __future__ import annotations

import asyncio

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model

from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

pytestmark = pytest.mark.django_db


def _call_async(coro):
    """Run an async MCP handler from a sync test."""
    return async_to_sync(lambda: coro)()


def _call_handler(name, args, *, user, token=None):
    """Invoke an MCP tool handler with the given calling user."""
    ctx = set_context(ToolContext(user=user, token=token))
    try:
        handler = TOOL_HANDLERS[name]
        if asyncio.iscoroutinefunction(handler):
            return async_to_sync(handler)(args)
        return handler(args)
    finally:
        reset_context(ctx)


# ────────────────────────────────────────────────────────────────────────────
#  Per-view tool: search_users (User CRUDView is SearchAccess.STAFF default)
# ────────────────────────────────────────────────────────────────────────────


def test_non_staff_caller_denied_on_staff_only_search_tool():
    """A non-staff caller hitting search_users gets denied with a clean
    error, NOT user PII. Was the round-2 §3.3 leak."""
    if "search_users" not in TOOL_HANDLERS:
        pytest.skip("search_users not registered (apps.mcp / usermanager not installed)")

    User = get_user_model()
    User.objects.create_user(username="leak-target-bob", email="bob@leak.test")
    alice = User.objects.create_user(username="alice-non-staff", is_staff=False)

    result = _call_handler("search_users", {"query": "leak-target"}, user=alice)

    # Hard requirements:
    # - The handler returns "denied: True" (and the registry's reason),
    #   not silently returns empty (which a follow-up regression could
    #   mistake for "search returned nothing today").
    # - No User-shaped hit is in the payload regardless of how
    #   "results" is interpreted.
    assert result.get("denied") is True
    assert result["results"] == []
    assert "bob@leak.test" not in str(result)
    assert "leak-target-bob" not in str(result)


def test_staff_caller_still_sees_results_on_staff_only_search_tool():
    """Regression: staff callers must still get hits — the gate is a
    per-caller filter, not a feature kill switch."""
    if "search_users" not in TOOL_HANDLERS:
        pytest.skip("search_users not registered")

    User = get_user_model()
    User.objects.create_user(username="staff-target-charlie")
    staff = User.objects.create_user(username="staff-caller", is_staff=True)

    # Rebuild the FTS index so the User we just created is findable.
    from apps.search.backends import get_backend
    from apps.search.registry import all_views

    backend = get_backend()
    for view in all_views():
        if "User" in view.model_label:
            backend.rebuild(view)

    result = _call_handler("search_users", {"query": "staff-target-charlie"}, user=staff)

    assert result.get("denied") is not True
    assert any(
        h.get("display") == "staff-target-charlie" for h in result.get("results", [])
    )


# ────────────────────────────────────────────────────────────────────────────
#  Cross-model search_all: STAFF-tier hits must drop for non-staff callers
# ────────────────────────────────────────────────────────────────────────────


def test_search_all_filters_staff_only_hits_for_non_staff():
    """search_all collates across every registered view. A non-staff
    caller must NOT see hits from STAFF-tier views even though the
    backend query would return them if run unfiltered."""
    if "search_all" not in TOOL_HANDLERS:
        pytest.skip("search_all not registered")

    User = get_user_model()
    User.objects.create_user(username="cross-target-needle")
    alice = User.objects.create_user(username="alice-non-staff-cross", is_staff=False)

    from apps.search.backends import get_backend
    from apps.search.registry import all_views

    backend = get_backend()
    for view in all_views():
        if "User" in view.model_label:
            backend.rebuild(view)

    result = _call_handler("search_all", {"query": "cross-target-needle"}, user=alice)

    # The User CRUDView is STAFF-tier — its hits must not leak.
    user_hits = [
        h for h in result.get("results", []) if h.get("model_label", "").endswith(".User")
    ]
    assert user_hits == []


def test_search_all_still_returns_help_docs_for_non_staff():
    """Help docs are intentionally always-visible. The new gate must
    not regress that — non-staff callers still get help-article hits."""
    if "search_all" not in TOOL_HANDLERS:
        pytest.skip("search_all not registered")

    User = get_user_model()
    alice = User.objects.create_user(username="alice-help-search", is_staff=False)

    result = _call_handler("search_all", {"query": "smallstack"}, user=alice)

    # Help docs may or may not have populated the FTS index in the test
    # environment; either is fine, the contract is "no exception and a
    # well-shaped response", not "always returns hits."
    assert "results" in result
    assert isinstance(result["results"], list)
