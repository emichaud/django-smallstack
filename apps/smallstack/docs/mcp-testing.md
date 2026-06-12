# Testing MCP tools

The `apps/mcp/tests/` suite (55+ tests, <1s) covers dispatch, OAuth, factory, tenancy, logging, and the doctor. Patterns below show what to copy when adding tests for your own tools.

## Calling a tool directly (no HTTP)

```python
import inspect
from apps.mcp.server import TOOL_HANDLERS, ToolContext, set_context, reset_context

def _call(name, args, user, token):
    tok = set_context(ToolContext(user=user, token=token))
    try:
        handler = TOOL_HANDLERS[name]
        if inspect.iscoroutinefunction(handler):
            import asyncio
            return asyncio.run(handler(args))
        return handler(args)
    finally:
        reset_context(tok)
```

## Tenancy assertion

```python
def test_user_b_cant_see_user_a_tickets(user_a, user_b, readonly_token):
    register_mcp_tools_from_crudview(TicketCRUDView)
    Ticket.objects.create(title="A's", owner=user_a)
    Ticket.objects.create(title="B's", owner=user_b)

    token, _ = readonly_token  # belongs to user_a
    result = _call("list_tickets", {}, user_a, token)
    titles = [r["title"] for r in result["results"]]
    assert "A's" in titles
    assert "B's" not in titles
```

## Full HTTP / JSON-RPC

```python
def test_via_http(client, readonly_token):
    _, raw = readonly_token
    resp = client.post(
        "/mcp",
        data='{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 200
```

Pass `HTTP_HOST="localhost"` — the Django test client defaults to `testserver`, which production-style settings won't allow.

## Wiping the registry between tests

`@tool` is idempotent (re-registering the same name is a no-op). For test isolation, use the `clean_registry` fixture from `apps/mcp/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _wipe(clean_registry):
    yield
```

## Test-only Widget + Gadget models

Live in `apps/mcp/tests/models.py` with `managed = False`. The repo-root `conftest.py` creates their tables once per session via `schema_editor`. Use these when you want to exercise the factory without coupling to a project-specific model.
