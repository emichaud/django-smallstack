"""MCP rejects session-only auth — even a logged-in session needs a Bearer."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_session_login_without_bearer_is_401():
    user = User.objects.create_user(username="ses", password="p")
    client = Client()
    client.force_login(user)
    resp = client.post(
        "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        content_type="application/json",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 401
