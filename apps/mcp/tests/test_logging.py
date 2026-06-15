"""Sanity-check the log lines we promised the spec."""

import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db
User = get_user_model()


def _post(client, body, **extra):
    return client.post(
        "/mcp",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST="localhost",
        **extra,
    )


def test_request_emits_req_then_resp(caplog):
    caplog.set_level(logging.INFO, logger="smallstack.mcp.views")
    _post(Client(), {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    messages = [r.message for r in caplog.records if r.name == "smallstack.mcp.views"]
    assert any("MCP REQ ua=" in m for m in messages)
    assert any("MCP REQ method=ping" in m for m in messages)
    assert any("MCP RESP method=" in m for m in messages)


def test_failed_auth_emits_warning(caplog):
    caplog.set_level(logging.WARNING, logger="smallstack.mcp.views")
    _post(
        Client(),
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        HTTP_AUTHORIZATION="Bearer bogus",
    )
    assert any("MCP AUTH failed" in r.message for r in caplog.records)


def test_oauth_register_emits_log(caplog):
    caplog.set_level(logging.INFO, logger="smallstack.mcp.oauth")
    Client().post(
        "/mcp/oauth/register",
        data=json.dumps({"client_name": "x", "redirect_uris": ["https://x/cb"]}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert any("OAUTH REGISTER" in r.message for r in caplog.records)
