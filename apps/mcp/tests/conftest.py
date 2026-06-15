"""Shared pytest fixtures for the MCP test suite.

Creates the test-only Widget + Gadget tables once per session via
schema_editor (the models are managed=False so they're invisible to
migrations), and exposes CRUDView subclasses opted into MCP.
"""

from __future__ import annotations

import pytest
from django import forms
from django.contrib.auth import get_user_model

from apps.mcp.server import clear_registry_for_tests
from apps.smallstack.crud import Action, CRUDView

from .models import Gadget, Widget

User = get_user_model()


# ---------------------------------------------------------------------------
# Schema setup is in the project-root conftest.py so Widget/Gadget tables
# exist for any test session, not just MCP tests. (Explorer iterates the
# CRUDView registry and needs the tables to exist when it queries them.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CRUDViews used across factory + dispatch + tenancy tests.
# ---------------------------------------------------------------------------


class WidgetForm(forms.ModelForm):
    class Meta:
        model = Widget
        fields = ["name", "owner"]


class GadgetForm(forms.ModelForm):
    class Meta:
        model = Gadget
        fields = ["name", "owner", "is_active"]


class WidgetCRUDView(CRUDView):
    model = Widget
    fields = ["name", "owner"]
    list_fields = ["name", "owner"]
    detail_fields = ["name", "owner"]
    url_base = "widgets"
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_mcp = True
    mcp_description = "Test widgets."
    form_class = WidgetForm
    search_fields = ["name"]
    filter_fields = ["owner"]

    @classmethod
    def get_list_queryset(cls, qs, request):
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            return qs.filter(owner=request.user)
        return qs.none()


class GadgetCRUDView(CRUDView):
    model = Gadget
    fields = ["name", "owner", "is_active"]
    list_fields = ["name", "owner", "is_active"]
    detail_fields = ["name", "owner", "is_active"]
    url_base = "gadgets"
    actions = [Action.LIST, Action.DETAIL]
    enable_mcp = True
    mcp_description = "Test gadgets, read-only."
    form_class = GadgetForm
    search_fields = ["name"]
    filter_fields = ["is_active", "owner"]

    @classmethod
    def get_list_queryset(cls, qs, request):
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            return qs.filter(owner=request.user)
        return qs.none()


@pytest.fixture
def widget_view():
    return WidgetCRUDView


@pytest.fixture
def gadget_view():
    return GadgetCRUDView


@pytest.fixture
def clean_registry():
    """Wipe TOOL_REGISTRY before each test so registrations don't leak."""
    clear_registry_for_tests()
    yield
    clear_registry_for_tests()


# ---------------------------------------------------------------------------
# Common user + token fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_a(db):
    return User.objects.create_user(username="alice", password="x")


@pytest.fixture
def user_b(db):
    return User.objects.create_user(username="bob", password="x")


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(username="staff", password="x", is_staff=True)


@pytest.fixture
def readonly_token(user_a):
    from apps.smallstack.models import APIToken

    token, raw = APIToken.create_token(user=user_a, name="ro", access_level="readonly")
    return token, raw


@pytest.fixture
def staff_token(staff_user):
    from apps.smallstack.models import APIToken

    token, raw = APIToken.create_token(user=staff_user, name="staff", access_level="staff")
    return token, raw
