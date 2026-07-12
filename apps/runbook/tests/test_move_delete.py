"""Tests for uid identity, move_document, delete, and runbook-delete confirmation."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook import mcp_tools, service, signals
from apps.runbook.models import Document, Runbook, Section

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff", password="p", is_staff=True)


@pytest.fixture
def sclient(staff):
    client = Client()
    client.force_login(staff)
    return client


@pytest.fixture
def rbs(db):
    return (
        Runbook.objects.create(name="A", slug="rb-a"),
        Runbook.objects.create(name="B", slug="rb-b"),
    )


@pytest.mark.django_db
class TestUidAndMove:
    def test_get_by_uid(self, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        assert service.get_document(uid=r.uid).id == r.id

    def test_move_between_runbooks_keeps_uid(self, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        m = service.move_document(uid=r.uid, to_runbook="rb-b")
        assert m.runbook == "rb-b"
        assert m.uid == r.uid  # identity stable across the move
        assert m.key == "d"

    def test_move_key_collision(self, rbs):
        service.put_document("rb-a", "d", body="x", title="D")
        service.put_document("rb-b", "d", body="y", title="D2")
        with pytest.raises(service.DocumentAlreadyExists):
            service.move_document(runbook="rb-a", key="d", to_runbook="rb-b")

    def test_detach_to_standalone(self, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        m = service.move_document(uid=r.uid, to_runbook=None)
        assert m.runbook is None and m.key is None
        assert service.get_document(uid=r.uid).id == r.id  # still uid-addressable

    def test_delete_archive_default_then_force(self, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        service.delete_document(uid=r.uid)
        assert Document.objects.get(pk=r.id).is_archived
        service.delete_document(uid=r.uid, force=True)
        assert not Document.objects.filter(pk=r.id).exists()

    def test_moved_signal(self, rbs, django_capture_on_commit_callbacks):
        r = service.put_document("rb-a", "d", body="x", title="D")
        got = []

        def rx(**kw):
            got.append((kw["from_runbook"].slug, kw["to_runbook"].slug if kw["to_runbook"] else None))

        signals.document_moved.connect(rx, weak=False)
        try:
            with django_capture_on_commit_callbacks(execute=True):
                service.move_document(uid=r.uid, to_runbook="rb-b")
        finally:
            signals.document_moved.disconnect(rx)
        assert got == [("rb-a", "rb-b")]


@pytest.mark.django_db
class TestMcpMoveDelete:
    def test_do_move(self, staff, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        assert mcp_tools.do_move(staff, uid=r.uid, to_runbook="rb-b")["runbook"] == "rb-b"

    def test_do_delete(self, staff, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        assert mcp_tools.do_delete(staff, uid=r.uid)["deleted"] is True

    def test_tools_registered(self):
        from apps.mcp.server import TOOL_HANDLERS

        assert "runbook_move_document" in TOOL_HANDLERS
        assert "runbook_delete_document" in TOOL_HANDLERS


@pytest.mark.django_db
class TestRestMoveDelete:
    def test_move_endpoint(self, sclient, rbs):
        service.put_document("rb-a", "d", body="x", title="D")
        url = reverse("runbook:api_document_move", kwargs={"runbook": "rb-a", "key": "d"})
        resp = sclient.post(url, data=json.dumps({"to_runbook": "rb-b"}), content_type="application/json")
        assert resp.status_code == 200 and resp.json()["runbook"] == "rb-b"

    def test_delete_endpoint_archive_then_force(self, sclient, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        url = reverse("runbook:api_document", kwargs={"runbook": "rb-a", "key": "d"})
        assert sclient.delete(url).json()["deleted"] is True
        assert Document.objects.get(pk=r.id).is_archived
        assert sclient.delete(url + "?force=true").status_code == 200
        assert not Document.objects.filter(pk=r.id).exists()

    def test_get_by_uid_endpoint(self, sclient, rbs):
        r = service.put_document("rb-a", "d", body="body-here", title="D")
        resp = sclient.get(reverse("runbook:api_document_by_uid", kwargs={"uid": r.uid}))
        assert resp.status_code == 200
        assert resp.json()["uid"] == r.uid
        assert "body-here" in resp.json()["content_markdown"]


@pytest.mark.django_db
class TestRunbookDeleteConfirm:
    def test_confirm_page_lists_docs(self, sclient, rbs):
        Section.objects.create(name="S", slug="s", runbook=rbs[0])
        service.put_document("rb-a", "d", body="x", title="D")
        resp = sclient.get(reverse("runbook:runbook_delete", kwargs={"slug": "rb-a"}))
        assert resp.status_code == 200
        assert b"document" in resp.content.lower()

    def test_detach_keeps_docs_as_standalone(self, sclient, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        sclient.post(reverse("runbook:runbook_delete", kwargs={"slug": "rb-a"}), {"mode": "detach"})
        assert not Runbook.objects.filter(slug="rb-a").exists()
        doc = Document.objects.get(pk=r.id)
        assert doc.runbook_id is None and doc.key is None

    def test_cascade_deletes_docs(self, sclient, rbs):
        r = service.put_document("rb-a", "d", body="x", title="D")
        sclient.post(reverse("runbook:runbook_delete", kwargs={"slug": "rb-a"}), {"mode": "cascade"})
        assert not Document.objects.filter(pk=r.id).exists()
