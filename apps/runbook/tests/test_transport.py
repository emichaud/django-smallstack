"""Tests for the MCP tools and REST endpoints (both over the service layer)."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook import mcp_tools, service
from apps.runbook.models import Runbook

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff", password="p", is_staff=True)


@pytest.fixture
def rb(db):
    return Runbook.objects.create(name="Ops", slug="ops")


@pytest.fixture
def sclient(staff):
    client = Client()
    client.force_login(staff)
    return client


_NAMES = {"": "api_document", "append": "api_document_append", "archive": "api_document_archive"}


def _url(runbook, key, suffix=""):
    return reverse(f"runbook:{_NAMES[suffix]}", kwargs={"runbook": runbook, "key": key})


def _put(client, runbook, key, payload, **extra):
    return client.put(_url(runbook, key), data=json.dumps(payload), content_type="application/json", **extra)


@pytest.mark.django_db
class TestMcpDelegates:
    def test_put_get_list(self, staff, rb):
        r = mcp_tools.do_put(staff, runbook="ops", key="n", body="# Hi", title="N")
        assert r["version"] == 1 and r["key"] == "n"
        assert isinstance(r["updated_at"], str)  # JSON-safe
        assert "# Hi" in mcp_tools.do_get(runbook="ops", key="n")["content_markdown"]
        assert mcp_tools.do_list(runbook="ops")["results"][0]["key"] == "n"

    def test_put_unknown_runbook_returns_error(self, staff):
        assert "error" in mcp_tools.do_put(staff, runbook="nope", key="n", body="x", title="N")

    def test_get_missing_returns_error(self, rb):
        assert "error" in mcp_tools.do_get(runbook="ops", key="nope")

    def test_append(self, staff, rb):
        mcp_tools.do_put(staff, runbook="ops", key="log", body="a", title="L")
        r = mcp_tools.do_append(staff, runbook="ops", key="log", body="b")
        assert r["version"] == 1
        body = mcp_tools.do_get(runbook="ops", key="log")["content_markdown"]
        assert "a" in body and "b" in body

    def test_tools_registered(self):
        from apps.mcp.server import TOOL_HANDLERS

        for name in (
            "runbook_list_documents",
            "runbook_get_document",
            "runbook_put_document",
            "runbook_append_document",
        ):
            assert name in TOOL_HANDLERS

    def test_write_tools_reachable_by_staff_token(self, staff):
        # Regression for B4: the write tools must be gated at the *staff* tier,
        # not "auth" (the strictest, which no normally-minted token reaches). A
        # staff-level token is allowed; a readonly token is blocked.
        from apps.mcp.auth import check_tool_access
        from apps.mcp.server import TOOL_REGISTRY
        from apps.smallstack.models import APIToken

        def _token(level):
            raw, prefix, hashed = APIToken._generate_raw_key()
            return APIToken.objects.create(
                user=staff, name=level, prefix=prefix, hashed_key=hashed, access_level=level
            )

        staff_tok, ro_tok = _token("staff"), _token("readonly")
        for name in ("runbook_put_document", "runbook_append_document",
                     "runbook_move_document", "runbook_delete_document"):
            tdef = TOOL_REGISTRY[name]
            assert tdef.requires_access == "staff"
            assert check_tool_access(staff_tok, tdef) is None            # staff allowed
            assert check_tool_access(ro_tok, tdef) is not None           # readonly blocked


@pytest.mark.django_db
class TestRestApi:
    def test_put_creates_then_versions(self, sclient, rb):
        resp = _put(sclient, "ops", "n", {"body": "# One", "title": "N"})
        assert resp.status_code == 200, resp.content
        assert resp.json()["version"] == 1
        assert _put(sclient, "ops", "n", {"body": "# Two"}).json()["version"] == 2

    def test_get_returns_body(self, sclient, rb):
        _put(sclient, "ops", "n", {"body": "# Body", "title": "N"})
        resp = sclient.get(_url("ops", "n"))
        assert resp.status_code == 200
        assert "# Body" in resp.json()["content_markdown"]

    def test_get_missing_404(self, sclient, rb):
        assert sclient.get(_url("ops", "nope")).status_code == 404

    def test_get_unknown_runbook_404_not_500(self, sclient):
        # A GET on a nonexistent runbook slug raises RunbookNotFound in the
        # service; the handler must map it to 404, not let it 500 (finding B3).
        assert sclient.get(_url("no-such-runbook", "x")).status_code == 404

    def test_append_and_archive(self, sclient, rb):
        _put(sclient, "ops", "log", {"body": "a", "title": "L"})
        r = sclient.post(_url("ops", "log", "append"), data=json.dumps({"body": "b"}), content_type="application/json")
        assert r.status_code == 200
        arch = sclient.post(_url("ops", "log", "archive"), data=json.dumps({}), content_type="application/json")
        assert arch.status_code == 200 and arch.json()["is_archived"] is True

    def test_version_conflict_409(self, sclient, rb):
        _put(sclient, "ops", "n", {"body": "a", "title": "N"})
        assert _put(sclient, "ops", "n", {"body": "b", "expected_version": 99}).status_code == 409

    def test_unknown_runbook_404(self, sclient):
        assert _put(sclient, "nope", "n", {"body": "x", "title": "N"}).status_code == 404

    def test_auth_required(self, rb):
        assert Client().get(_url("ops", "n")).status_code == 401

    def test_non_viewer_write_hidden_404(self, db, rb):
        # `ops` is a system runbook (owner=None, not public) → invisible to a
        # plain user. Writing to it returns 404, not 403, so the REST surface
        # can't be used to probe for private/system slugs (finding L1).
        client = Client()
        client.force_login(User.objects.create_user("plain", password="p"))
        assert _put(client, "ops", "n", {"body": "x", "title": "N"}).status_code == 404

    def test_viewable_non_owner_write_forbidden_403(self, db):
        # A public runbook IS viewable, so a non-owner write is a real 403 —
        # existence isn't secret, only edit rights are.
        owner = User.objects.create_user("po", password="p")
        Runbook.objects.create(name="Pub", slug="pubr", owner=owner, is_public=True)
        client = Client()
        client.force_login(User.objects.create_user("stranger", password="p"))
        assert _put(client, "pubr", "n", {"body": "x", "title": "N"}).status_code == 403

    def test_readonly_token_forbidden_write_allowed_read(self, staff, rb):
        from apps.smallstack.models import APIToken

        raw, prefix, hashed = APIToken._generate_raw_key()
        APIToken.objects.create(user=staff, name="ro", prefix=prefix, hashed_key=hashed, access_level="readonly")
        auth = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}

        # write blocked
        assert _put(Client(), "ops", "n", {"body": "x", "title": "N"}, **auth).status_code == 403
        # read allowed
        service.put_document("ops", "n", body="x", title="N")
        assert Client().get(_url("ops", "n"), **auth).status_code == 200
