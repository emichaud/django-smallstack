"""@tool registry + ToolContext semantics."""


import pytest

from apps.mcp.server import (
    TOOL_HANDLERS,
    TOOL_REGISTRY,
    ToolContext,
    clear_registry_for_tests,
    current_context,
    reset_context,
    set_context,
    tool,
)


def setup_function(_):
    clear_registry_for_tests()


def test_registers_in_both_dicts():
    @tool("hello", "Greet")
    async def hello(args):
        return {"ok": True}

    assert "hello" in TOOL_REGISTRY
    assert "hello" in TOOL_HANDLERS
    assert TOOL_REGISTRY["hello"].description == "Greet"


def test_write_flag_recorded():
    @tool("commit", "Commit", write=True)
    async def commit(args):
        return {}

    assert TOOL_REGISTRY["commit"].write is True


def test_duplicate_registration_skipped(caplog):
    @tool("dup", "first")
    async def a(args):
        return {"v": 1}

    @tool("dup", "second")  # silently ignored
    async def b(args):
        return {"v": 2}

    # The first registration wins.
    assert TOOL_REGISTRY["dup"].description == "first"


def test_current_context_returns_set_value():
    fake = object()
    sentinel = ToolContext(user=fake, token=None)
    tok = set_context(sentinel)
    try:
        assert current_context() is sentinel
    finally:
        reset_context(tok)


def test_current_context_raises_outside_dispatch():
    with pytest.raises(LookupError):
        current_context()
