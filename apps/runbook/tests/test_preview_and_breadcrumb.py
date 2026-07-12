"""Tests for the runbook preview fragment and the document → runbook breadcrumb."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.runbook.models import Runbook, Section

from ._factory import make_document

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(username="rb_staff", password="pass", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def doc(db):
    rb = Runbook.objects.create(name="Customer", slug="customer")
    sec = Section.objects.create(name="Billing", slug="billing", runbook=rb)
    return make_document(title="Refunds", body=b"# Refunds\n\nHow to issue refunds.", section=sec)


@pytest.mark.django_db
class TestRunbookPreview:
    def test_preview_fragment_renders_content(self, staff_client, doc):
        url = reverse("runbook:runbook_preview", kwargs={"slug": "customer"})
        resp = staff_client.get(url)
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "How to issue refunds." in html
        assert "Billing" in html
        # links to the full views
        assert reverse("runbook:runbook_read", kwargs={"slug": "customer"}) in html

    def test_preview_requires_staff(self, db, doc):
        resp = Client().get(reverse("runbook:runbook_preview", kwargs={"slug": "customer"}))
        assert resp.status_code in (302, 403)


@pytest.mark.django_db
class TestDocumentBreadcrumb:
    def test_breadcrumb_links_back_to_runbook(self, staff_client, doc):
        resp = staff_client.get(reverse("runbook:document_detail", kwargs={"pk": doc.pk}))
        assert resp.status_code == 200
        html = resp.content.decode()
        # breadcrumb points at the owning runbook's TOC, not the generic CRUD list
        runbook_url = reverse("runbook:runbook_detail", kwargs={"slug": "customer"})
        assert runbook_url in html
        assert "Customer" in html
