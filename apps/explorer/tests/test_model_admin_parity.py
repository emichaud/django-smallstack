"""Explorer reads more of a ModelAdmin, so it means what Django admin means.

``list_display`` methods and callables become columns; ``readonly_fields`` and
``exclude`` keep a field off the form; ``ordering`` and ``list_select_related``
shape the list's queryset; a declared ``list_per_page`` sets the page size;
``search_fields`` prefixes (``^ = @``) work; ``SimpleListFilter`` classes filter
the list; and ``explorer_enable_mcp`` / ``_search`` / ``_webhooks`` turn those
surfaces on.

Each test builds a fresh, unnamed ExplorerSite over Runbook, so the generated
view has the same URL names as the Explorer pages already mounted.
"""

from __future__ import annotations

import json
import logging

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.explorer.registry import ExplorerSite
from apps.runbook.models import Runbook, Section
from apps.smallstack.crud import _apply_admin_filters, _apply_list_search, _CRUDListBase

pytestmark = pytest.mark.django_db

User = get_user_model()


class TemplateFilter(admin.SimpleListFilter):
    title = "kind"
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return [("template", "Templates"), ("book", "Books")]

    def queryset(self, request, queryset):
        if self.value() == "template":
            return queryset.filter(is_template=True)
        if self.value() == "book":
            return queryset.filter(is_template=False)
        return None


@admin.display(description="Loud name")
def shout(obj):  # a plain callable, as Django admin allows in list_display
    return obj.name.upper()


class RunbookAdmin(admin.ModelAdmin):
    list_display = ["name", "section_count", "is_big", shout]
    readonly_fields = ["slug"]
    exclude = ["icon"]
    ordering = ["-name"]
    list_per_page = 7
    search_fields = ["^name", "=slug"]
    list_filter = [TemplateFilter]

    @admin.display(description="Sections")
    def section_count(self, obj):
        return obj.sections.count()

    @admin.display(description="Big?", boolean=True)
    def is_big(self, obj):
        return obj.sections.count() > 1


def build(model=Runbook, admin_class=RunbookAdmin, **attrs):
    site = ExplorerSite()
    admin_class = type(admin_class.__name__, (admin_class,), attrs) if attrs else admin_class
    site.register(model, admin_class, group="Smallstack Runbook")
    site.build_crud_classes()
    return site._crud_classes[0]


@pytest.fixture
def staff():
    return User.objects.create_user("parity-staff", password="p", is_staff=True)


@pytest.fixture
def books():
    big = Runbook.objects.create(name="Alpha ops", slug="alpha")
    Section.objects.create(runbook=big, name="One", slug="one")
    Section.objects.create(runbook=big, name="Two", slug="two")
    Runbook.objects.create(name="Beta notes", slug="beta", is_template=True)
    return big


def list_page(crud, staff, **params):
    request = RequestFactory().get("/", params)
    request.user = staff
    response = crud._make_view(_CRUDListBase).as_view()(request)
    response.render()
    return response


# --- list_display methods ------------------------------------------------------


def test_methods_and_callables_in_list_display_are_columns(staff, books):
    crud = build()
    assert crud._get_list_columns() == ["name", "section_count", "is_big", "shout"]
    assert crud.column_labels == {"section_count": "Sections", "is_big": "Big?", "shout": "Loud name"}
    assert crud.list_fields == ["name"]  # API, CSV and sorting keep to real fields
    html = list_page(crud, staff).content.decode()
    assert "Sections" in html and "Big?" in html and "ALPHA OPS" in html
    assert ">2<" in html.replace(" ", "")  # Alpha ops has two sections


def test_explorer_fields_still_choose_the_columns():
    crud = build(explorer_fields=["name", "slug"])
    assert crud._get_list_columns() == ["name", "slug"] and crud.column_labels is None


def test_a_default_list_display_keeps_explorers_own_columns():
    crud = build(admin_class=admin.ModelAdmin)
    assert crud.list_columns is None and crud.column_labels is None


# --- forms, ordering, joins, page size ------------------------------------------


def test_readonly_fields_and_exclude_stay_off_the_form():
    crud = build(list_display=["name", "slug", "icon", "description"])
    assert "slug" not in crud.fields and "icon" not in crud.fields
    assert "name" in crud.fields and "description" in crud.fields
    assert {"slug", "icon"} <= set(crud.list_fields)


def test_ordering_is_the_lists_default_order(staff, books):
    crud = build()
    names = [r.name for r in list_page(crud, staff).context_data["object_list"]]
    assert names == ["Beta notes", "Alpha ops"]


def test_foreign_keys_in_the_list_are_joined():
    class SectionAdmin(admin.ModelAdmin):
        list_display = ["name", "runbook"]

    crud = build(Section, SectionAdmin)
    assert crud._get_queryset().query.select_related == {"runbook": {}}
    explicit = build(Section, SectionAdmin, list_select_related=["runbook"])
    assert explicit._get_queryset().query.select_related == {"runbook": {}}


def test_page_size_explorer_setting_then_list_per_page_then_ten():
    assert build().paginate_by == 7
    assert build(explorer_paginate_by=3).paginate_by == 3
    assert build(admin_class=admin.ModelAdmin).paginate_by == 10


# --- search prefixes and SimpleListFilter ------------------------------------------


def test_search_prefixes_mean_what_they_mean_in_django_admin(staff, books):
    crud = build()

    def found(q):
        request = RequestFactory().get("/", {"q": q})
        return sorted(r.slug for r in _apply_list_search(Runbook.objects.all(), request, crud))

    assert found("alp") == ["alpha"]  # ^name: starts with
    assert found("ops") == []  # not a prefix of any name, and =slug wants it whole
    assert found("beta") == ["beta"]  # ^name and =slug both match


def test_the_rest_list_search_reads_prefixes_too(books):
    from apps.smallstack.api import _apply_list_search as rest_search

    request = RequestFactory().get("/", {"q": "alp"})
    assert [r.slug for r in rest_search(request, Runbook.objects.all(), ["^name"])] == ["alpha"]


def test_the_search_index_gets_bare_field_paths():
    from apps.search.registry import register, unregister

    crud = build(explorer_enable_search=True)
    try:
        view = register(crud)
        assert view is not None and view.fields == ["name", "slug"]
    finally:
        unregister(crud)


def test_simple_list_filters_show_in_the_toolbar_and_filter(staff, books):
    crud = build()
    page = list_page(crud, staff, kind="template")
    toolbar = {f["name"]: f for f in page.context_data["toolbar_filters"]}
    assert toolbar["kind"]["label"] == "Kind" and toolbar["kind"]["current_value"] == "template"
    assert ("book", "Books") in toolbar["kind"]["choices"]
    assert [r.slug for r in page.context_data["object_list"]] == ["beta"]
    assert len(list_page(crud, staff).context_data["object_list"]) == 2


def test_rest_and_mcp_apply_the_same_filters(books):
    from apps.mcp.factory import _build_list_input_schema
    from apps.smallstack.api import _api_list

    crud = build()
    request = RequestFactory().get("/", {"kind": "book"})
    request.user = User.objects.create_superuser("parity-root", password="p")
    body = json.loads(_api_list(request, crud).content)
    assert [r["name"] for r in body["results"]] == ["Alpha ops"]
    assert "kind" in _build_list_input_schema(crud)["properties"]
    mcp_request = RequestFactory().get("/")
    narrowed = _apply_admin_filters(Runbook.objects.all(), mcp_request, crud, {"kind": ["template"]})
    assert [r.slug for r in narrowed] == ["beta"]


# --- surface switches -----------------------------------------------------------


def test_switches_set_the_flags():
    crud = build(explorer_enable_mcp=True, explorer_enable_webhooks=True)
    assert crud.enable_mcp and crud.enable_webhooks and not crud.enable_search
    assert (crud.mcp_singular, crud.mcp_plural) == ("runbook", "runbooks")


def test_a_model_another_view_serves_keeps_that_views_surfaces(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.explorer.registry"):
        build(explorer_enable_mcp=True, explorer_enable_webhooks=True)
    text = caplog.text
    assert "explorer_enable_mcp on smallstack_runbook.Runbook skipped" in text
    assert "explorer_enable_webhooks on smallstack_runbook.Runbook has no effect" in text
