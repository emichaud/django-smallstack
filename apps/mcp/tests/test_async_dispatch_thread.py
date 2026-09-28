"""Async tool dispatch must keep ORM work on the request's thread/connection.

Downstream-reported (Postgres, third instance of the SQLite-forgives family):
dispatching async tool handlers with ``asyncio.run(handler(...))`` gives
asgiref no executor context, so every ``sync_to_async(thread_sensitive=True)``
— the default, and what every tool uses for ORM work — ran on asgiref's
process-global ``single_thread_executor``: ONE shared background thread with
its own long-lived connection. Consequences: the tool's DB work ran outside
the request's transaction in production, serialized process-wide across all
tools, tripped asgiref's "would deadlock" guard on any nested
thread-sensitive call, and on Postgres killed ``transaction=True`` test
teardowns ("cursor already closed" during the flush) — the downstream's 46
teardown failures. ``async_to_sync`` installs a ``CurrentThreadExecutor``, so
the ORM code hops back to the CALLING thread and its connection.

These tests pin the mechanism itself (thread + connection identity through
the real ``/mcp`` endpoint), so they prove the fix on any backend — no
Postgres needed to see the difference.
"""

from __future__ import annotations

import json
import threading

import pytest
from asgiref.sync import sync_to_async
from django.test import Client

from apps.mcp.server import clear_registry_for_tests, tool

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _wipe():
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


@pytest.fixture
def staff_raw(db):
    from django.contrib.auth import get_user_model

    from apps.smallstack.models import APIToken

    user = get_user_model().objects.create_user("mcp-async", password="p", is_staff=True)
    _, raw = APIToken.create_token(user=user, name="t", access_level="staff")
    return raw


def _call(raw, name):
    return Client().post(
        "/mcp",
        data=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": {}}}
        ),
        content_type="application/json",
        HTTP_HOST="localhost",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )


def test_thread_sensitive_orm_runs_on_the_request_thread(staff_raw):
    """The decisive identity check: inside the handler's sync_to_async, the
    thread AND the Django connection object must be the request's own. Under
    asyncio.run dispatch this fails — the work lands on asgiref's global
    single-thread executor with a different connection."""
    seen: dict = {}

    @tool("probe_thread", "where does my ORM work run?")
    async def probe_thread(args):
        def _sync_part():
            from django.db import connection

            seen["thread"] = threading.get_ident()
            seen["connection"] = id(connection.__dict__.get("_connections", None) or connection)
            # Touch the ORM for real — this is the operation that must see
            # the caller's transaction.
            from django.contrib.auth import get_user_model

            return get_user_model().objects.count()

        count = await sync_to_async(_sync_part)()  # thread_sensitive=True default
        return {"count": count}

    from django.db import connection as caller_connection

    caller = {
        "thread": threading.get_ident(),
        "connection": id(caller_connection.__dict__.get("_connections", None) or caller_connection),
    }

    resp = _call(staff_raw, "probe_thread")
    assert resp.status_code == 200
    assert seen["thread"] == caller["thread"]          # pre-fix: global executor thread
    assert seen["connection"] == caller["connection"]  # pre-fix: a second connection


def test_orm_writes_inside_async_tool_are_visible_to_the_test_transaction(staff_raw):
    """The practical payoff: a row created inside the handler's sync_to_async
    is visible to the test WITHOUT transaction=True — same connection, same
    transaction. Under asyncio.run the row lands on another connection and
    (on Postgres) commits outside the test transaction."""

    @tool("probe_write", "create a row from inside an async tool")
    async def probe_write(args):
        def _create():
            from django.contrib.auth import get_user_model

            return get_user_model().objects.create_user("made-by-async-tool", password="p").pk

        pk = await sync_to_async(_create)()
        return {"pk": pk}

    resp = _call(staff_raw, "probe_write")
    assert resp.status_code == 200

    from django.contrib.auth import get_user_model

    assert get_user_model().objects.filter(username="made-by-async-tool").exists()


def test_nested_thread_sensitive_calls_do_not_deadlock(staff_raw):
    """asyncio.run dispatch sets asgiref's deadlock_context: a handler whose
    sync code re-enters async land and needs another thread-sensitive hop
    raises 'Single thread executor already being used, would deadlock'.
    async_to_sync's CurrentThreadExecutor chain handles nesting."""

    @tool("probe_nested", "nested sync_to_async hops")
    async def probe_nested(args):
        def _outer():
            from asgiref.sync import async_to_sync as a2s

            async def _inner_async():
                return await sync_to_async(lambda: "deep")()

            return a2s(_inner_async)()

        value = await sync_to_async(_outer)()
        return {"value": value}

    resp = _call(staff_raw, "probe_nested")
    assert resp.status_code == 200
    body = resp.json()
    text = body["result"]["content"][0]["text"]
    assert json.loads(text) == {"value": "deep"}
