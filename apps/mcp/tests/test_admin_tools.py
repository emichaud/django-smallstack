"""MCPAdminToolsView + MCPAdminToolDetailView tests."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()


def _staff():
    return User.objects.create_user(username="tools_admin", password="x", is_staff=True)


def _register_a_tool(clean_registry):
    """Wire up one CRUDView tool so the page has something to render.

    `clean_registry` fixture clears TOOL_REGISTRY before/after each test
    so registrations don't bleed.
    """
    from apps.mcp.factory import register_mcp_tools_from_crudview
    from apps.mcp.tests.fake_app.views import AutodiscoverWidgetCRUDView

    register_mcp_tools_from_crudview(AutodiscoverWidgetCRUDView)


def test_anonymous_redirects(clean_registry):
    resp = Client().get(reverse("mcp_admin:tools"), HTTP_HOST="localhost")
    assert resp.status_code in (301, 302)


def test_non_staff_is_forbidden(clean_registry):
    u = User.objects.create_user(username="ordinary_t", password="x")
    c = Client()
    c.force_login(u)
    resp = c.get(reverse("mcp_admin:tools"), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_empty_registry_shows_empty_state(clean_registry):
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:tools"), HTTP_HOST="localhost")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "No tools registered yet" in body
    assert "enable_mcp" in body  # link to the opt-in doc


def test_populated_registry_lists_tools_with_links(clean_registry):
    _register_a_tool(clean_registry)
    c = Client()
    c.force_login(_staff())
    resp = c.get(reverse("mcp_admin:tools"), HTTP_HOST="localhost")
    body = resp.content.decode()
    assert "list_autodiscover_widgets" in body
    assert "get_widget" in body
    assert reverse("mcp_admin:tool_detail", kwargs={"name": "get_widget"}) in body


def test_unknown_tool_detail_returns_404(clean_registry):
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:tool_detail", kwargs={"name": "no_such_tool"}),
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 404


def test_known_tool_detail_renders_schema(clean_registry):
    _register_a_tool(clean_registry)
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:tool_detail", kwargs={"name": "get_widget"}),
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "inputSchema" in body
    # The schema for get_widget includes the pk integer property.
    assert "&quot;pk&quot;" in body or "\"pk\"" in body
    # Curl snippet is rendered with the tool name.
    assert "get_widget" in body


def test_tool_detail_context_exposes_tool_object(clean_registry):
    _register_a_tool(clean_registry)
    c = Client()
    c.force_login(_staff())
    resp = c.get(
        reverse("mcp_admin:tool_detail", kwargs={"name": "list_autodiscover_widgets"}),
        HTTP_HOST="localhost",
    )
    assert resp.context["tool"].name == "list_autodiscover_widgets"
    assert "schema_json" in resp.context
