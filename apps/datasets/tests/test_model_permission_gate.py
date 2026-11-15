"""Datasets over access models need the model's view permission (B6, finding R2-6).

Explorer refuses accounts and API tokens to a staff account without
``view_user`` / ``view_apitoken``; the bundled datasets over the same models
must too, on the browse page, the index, REST and MCP.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.datasets.registry import get_def, user_may_read, user_may_view_model
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()
SENSITIVE = ["smallstack_users", "smallstack_api_tokens"]


@pytest.fixture
def staff():
    return User.objects.create_user("b6-staff", password="p", is_staff=True, email="b6@example.com")


def _grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return User.objects.get(pk=user.pk)


@pytest.mark.parametrize("key", SENSITIVE)
def test_browse_refuses_without_view(client, staff, key):
    client.force_login(staff)
    assert client.get(reverse("datasets:browse", args=[key])).status_code == 403


def test_browse_opens_with_view(client, staff):
    client.force_login(_grant(staff, "view_user", "view_apitoken"))
    for key in SENSITIVE:
        assert client.get(reverse("datasets:browse", args=[key])).status_code == 200


def test_index_leaves_them_out(client, staff):
    client.force_login(staff)
    resp = client.get(reverse("datasets:browse-index"))
    keys = {row["key"] for row in resp.context["framework_datasets"]}
    assert not keys & set(SENSITIVE)
    assert "smallstack_requests" in keys


def test_rest_refuses_with_a_staff_token(client, staff):
    _token, raw = APIToken.create_token(staff, name="b6")
    auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    for key in SENSITIVE:
        assert client.get(reverse("datasets:rows", args=[key]), **auth).status_code == 404
    keys = {d["key"] for d in client.get(reverse("datasets:list"), **auth).json()["results"]}
    assert not keys & set(SENSITIVE)
    # With the permission, the same token reads them (bearer user, not request.user).
    _grant(staff, "view_user", "view_apitoken")
    body = client.get(reverse("datasets:rows", args=["smallstack_users"]), **auth).json()
    assert any(r.get("username") == "b6-staff" for r in body.get("rows") or body.get("results") or [])


def test_in_app_read_needs_view(staff):
    for key in SENSITIVE:
        dfn = get_def(key)
        assert not user_may_view_model(dfn, staff)
        assert not user_may_read(dfn, staff)
    # Datasets over ordinary models keep the staff rule.
    assert user_may_read(get_def("smallstack_requests"), staff)
    # Trusted internal calls are unchanged.
    assert user_may_view_model(get_def("smallstack_users"), None)


def test_mcp_list_and_describe_refuse(staff):
    from apps.datasets.mcp_tools import _caller_may_read, caller_may_use
    from apps.mcp.server import ToolContext, reset_context, set_context

    ctx = set_context(ToolContext(user=staff, token=None))
    try:
        for key in SENSITIVE:
            assert not _caller_may_read(get_def(key))
            assert not caller_may_use(get_def(key))
    finally:
        reset_context(ctx)
