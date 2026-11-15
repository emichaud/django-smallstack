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

import pytest
from django.contrib.auth import get_user_model

from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _ensure_search_tools_registered():
    """Re-register the search MCP tools before each test in this module.

    The MCP test suite's ``clean_registry`` fixture calls
    ``clear_registry_for_tests()``, which wipes ``TOOL_HANDLERS`` — including
    the search tools that registered at app startup. Without this, whether
    these security-regression tests run depends on test ordering: after any
    MCP test they'd find an empty registry and silently ``pytest.skip`` with a
    misleading "not installed" message, disabling the §3.3 authz coverage in
    the base *and* every downstream. ``register_search_tools()`` is idempotent
    and a no-op when apps.mcp isn't installed, so the per-test skip guards stay
    correct for projects that genuinely lack these apps.
    """
    from apps.search.mcp_tools import register_search_tools

    register_search_tools()


def _call_handler(name, args, *, user, token=None):
    """Invoke an MCP tool handler with the given calling user."""
    ctx = set_context(ToolContext(user=user, token=token))
    try:
        return TOOL_HANDLERS[name](args)
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
    # Users are read with accounts.view_user (S2-1); search follows the list.
    from django.contrib.auth.models import Permission

    staff.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    staff = User.objects.get(pk=staff.pk)

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


# ────────────────────────────────────────────────────────────────────────────
#  Carry-over from round-2 §3.3 / v0.11.10 audit: search tools must not appear
#  in tools/list for callers who can't actually invoke them. The v0.11.10
#  filter only checked check_tool_access (flat requires_access level), which
#  let search_users + search_api_tokens stay visible-but-non-functional for
#  non-staff. v0.11.12 wires visible_to on each per-view search tool to mirror
#  the runtime gate.
# ────────────────────────────────────────────────────────────────────────────


def test_search_users_hidden_from_tools_list_for_non_staff_token(db):
    """alice (non-staff) calling tools/list does NOT see search_users.

    Was the v0.11.10 carry-over: the tool was in her tools/list response
    because its requires_access was readonly, but its handler returned
    {"denied": true} due to the underlying view's SearchAccess.STAFF tier.
    Visible-but-non-functional. Now hidden at list time too.
    """
    if "search_users" not in TOOL_HANDLERS:
        pytest.skip("search_users not registered")

    import json as jsonlib

    from django.test import Client

    User = get_user_model()
    from apps.smallstack.models import APIToken

    alice = User.objects.create_user(username="alice-tlist", password="x", is_staff=False)
    _, raw = APIToken.create_token(user=alice, name="alice-tlist-ro", access_level="readonly")

    resp = Client().post(
        "/mcp",
        data=jsonlib.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    # search_users (STAFF tier) MUST be hidden from alice's list.
    assert "search_users" not in names
    # search_api_tokens (STAFF tier by default) likewise.
    assert "search_api_tokens" not in names


def test_search_users_visible_in_tools_list_for_staff_token(db):
    """Regression guard: staff users still see staff-tier search tools."""
    if "search_users" not in TOOL_HANDLERS:
        pytest.skip("search_users not registered")

    import json as jsonlib

    from django.test import Client

    User = get_user_model()
    from apps.smallstack.models import APIToken

    bob = User.objects.create_user(username="bob-tlist", password="x", is_staff=True)
    from django.contrib.auth.models import Permission

    bob.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    _, raw = APIToken.create_token(user=bob, name="bob-tlist-staff", access_level="staff")

    resp = Client().post(
        "/mcp",
        data=jsonlib.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = [t["name"] for t in resp.json()["result"]["tools"]]
    assert "search_users" in names


def test_search_help_and_search_all_stay_visible_for_all_callers(db):
    """The cross-model and help-docs tools are intentionally always-visible.
    Any change that hides them is a regression — alice needs both to use the
    search surface at all."""
    if "search_all" not in TOOL_HANDLERS or "search_help" not in TOOL_HANDLERS:
        pytest.skip("search_all/search_help not registered")

    import json as jsonlib

    from django.test import Client

    User = get_user_model()
    from apps.smallstack.models import APIToken

    alice = User.objects.create_user(username="alice-meta", password="x", is_staff=False)
    _, raw = APIToken.create_token(user=alice, name="alice-meta-ro", access_level="readonly")

    resp = Client().post(
        "/mcp",
        data=jsonlib.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )
    names = set(t["name"] for t in resp.json()["result"]["tools"])
    assert "search_all" in names
    assert "search_help" in names
