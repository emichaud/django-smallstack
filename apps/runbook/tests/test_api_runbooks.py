"""REST tests for the runbook-container resource (api/runbooks/…).

Covers list/create, detail+TOC, sections, and publish/unpublish — including the
ownership (created runbooks belong to the caller) and permission (publish needs
edit rights, private runbooks stay hidden) semantics.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook import service
from apps.runbook.models import Runbook, Section

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def alice(db):
    return User.objects.create_user("alice", password="p")


@pytest.fixture
def bob(db):
    return User.objects.create_user("bob", password="p")


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def _post(client, urlname, payload=None, **kwargs):
    url = reverse(f"runbook:{urlname}", kwargs=kwargs)
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


# -- list / create ------------------------------------------------------------

@pytest.mark.django_db
def test_list_runbooks(alice):
    Runbook.objects.create(slug="ops", name="Ops", owner=alice)
    resp = _client(alice).get(reverse("runbook:api_runbooks"))
    assert resp.status_code == 200
    slugs = [r["slug"] for r in resp.json()["results"]]
    assert "ops" in slugs


@pytest.mark.django_db
def test_create_runbook_is_owned_by_caller(alice):
    resp = _post(_client(alice), "api_runbooks", {"slug": "myrb", "name": "My RB"})
    assert resp.status_code == 200
    assert resp.json()["owner"] == "alice"
    assert Runbook.objects.get(slug="myrb").owner == alice


@pytest.mark.django_db
def test_create_runbook_requires_slug(alice):
    resp = _post(_client(alice), "api_runbooks", {})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_duplicate_runbook_conflicts(alice):
    Runbook.objects.create(slug="ops", name="Ops", owner=alice)
    resp = _post(_client(alice), "api_runbooks", {"slug": "ops"})
    assert resp.status_code == 409


@pytest.mark.django_db
def test_list_hides_other_users_private_runbooks(alice, bob):
    Runbook.objects.create(slug="secret", name="Secret", owner=bob)  # private, bob's
    resp = _client(alice).get(reverse("runbook:api_runbooks"))
    assert "secret" not in [r["slug"] for r in resp.json()["results"]]


# -- detail + TOC -------------------------------------------------------------

@pytest.mark.django_db
def test_runbook_detail_groups_pages_by_section(alice):
    rb = Runbook.objects.create(slug="ops", name="Ops", owner=alice)
    Section.objects.create(runbook=rb, slug="setup", name="Setup", order=0)
    service.put_document("ops", "install", body="# Install", title="Install",
                         section="setup", actor=alice)
    service.put_document("ops", "loose", body="# Loose", title="Loose", actor=alice)

    resp = _client(alice).get(reverse("runbook:api_runbook_detail", kwargs={"slug": "ops"}))
    assert resp.status_code == 200
    data = resp.json()
    setup = next(s for s in data["sections"] if s["slug"] == "setup")
    assert [d["key"] for d in setup["documents"]] == ["install"]
    assert [d["key"] for d in data["sectionless"]] == ["loose"]


@pytest.mark.django_db
def test_runbook_detail_404_for_hidden_runbook(alice, bob):
    Runbook.objects.create(slug="secret", name="Secret", owner=bob)
    resp = _client(alice).get(reverse("runbook:api_runbook_detail", kwargs={"slug": "secret"}))
    assert resp.status_code == 404


# -- sections -----------------------------------------------------------------

@pytest.mark.django_db
def test_create_section(alice):
    Runbook.objects.create(slug="ops", name="Ops", owner=alice)
    resp = _post(_client(alice), "api_runbook_sections", {"slug": "howto", "name": "How-to"}, slug="ops")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "howto"
    assert Section.objects.filter(runbook__slug="ops", slug="howto").exists()


@pytest.mark.django_db
def test_create_section_denied_for_non_owner(alice, bob):
    Runbook.objects.create(slug="ops", name="Ops", owner=bob)  # bob's private runbook
    resp = _post(_client(alice), "api_runbook_sections", {"slug": "x"}, slug="ops")
    assert resp.status_code == 404  # hidden → not-found, never a leak


# -- publish / unpublish ------------------------------------------------------

@pytest.mark.django_db
def test_publish_and_unpublish(alice):
    Runbook.objects.create(slug="ops", name="Ops", owner=alice)
    resp = _post(_client(alice), "api_runbook_publish", slug="ops")
    assert resp.status_code == 200 and resp.json()["is_public"] is True
    assert Runbook.objects.get(slug="ops").is_public is True

    _post(_client(alice), "api_runbook_unpublish", slug="ops")
    assert Runbook.objects.get(slug="ops").is_public is False


@pytest.mark.django_db
def test_publish_denied_for_non_owner(alice, bob):
    Runbook.objects.create(slug="ops", name="Ops", owner=bob, is_public=True)  # bob's, visible
    resp = _post(_client(alice), "api_runbook_publish", slug="ops")
    assert resp.status_code == 403  # alice can view (public) but can't edit


# -- openapi ------------------------------------------------------------------

@pytest.mark.django_db
def test_runbook_resource_in_openapi_schema(client):
    spec = client.get(reverse("api-openapi-schema")).json()
    paths = spec.get("paths", {})
    base = reverse("runbook:api_runbooks")
    assert base in paths
    assert f"{base}{{slug}}/" in paths
    assert f"{base}{{slug}}/publish/" in paths
