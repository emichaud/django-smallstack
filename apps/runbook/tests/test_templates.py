"""Tests for the runbook templates feature (clone, make-template, picker, area)."""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.runbook import service
from apps.runbook.forms import DocumentCreateFromScratchForm
from apps.runbook.models import Document, Runbook, Section

User = get_user_model()


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _build_source(slug="src"):
    rb = Runbook.objects.create(name="Src", slug=slug, description="d", icon="📘", default_ttl_days=7)
    Section.objects.create(name="Guides", slug="guides", runbook=rb, order=1)
    service.put_document(slug, "intro", body="# Intro\n\nHello.", title="Intro",
                         section="guides", doc_type="guide", is_generated=False)
    service.put_document(slug, "faq", body="# FAQ\n\nQ?", title="FAQ", section="guides", is_generated=False)
    return rb


@pytest.mark.django_db
class TestCloneRunbook:
    def test_clones_sections_and_docs(self, db):
        _build_source()
        target = service.clone_runbook("src", new_name="Copy", as_template=True)
        assert target.is_template and target.slug != "src"
        assert set(target.sections.values_list("slug", flat=True)) == {"guides"}
        docs = Document.objects.filter(runbook=target)
        assert docs.count() == 2
        intro = docs.get(key="intro")
        assert intro.section.runbook_id == target.pk   # section mapped to the clone
        assert "Hello." in service.read_head(intro)     # body copied
        assert intro.doc_type == "guide" and intro.via == "clone"

    def test_retention_defaults_copied(self, db):
        _build_source()
        assert service.clone_runbook("src", new_name="Copy").default_ttl_days == 7

    def test_source_unchanged(self, db):
        _build_source()
        service.clone_runbook("src", new_name="Copy")
        src = Runbook.objects.get(slug="src")
        assert not src.is_template and Document.objects.filter(runbook=src).count() == 2

    def test_archived_docs_skipped(self, db):
        _build_source()
        service.archive_document(runbook="src", key="faq")
        target = service.clone_runbook("src", new_name="Copy")
        assert Document.objects.filter(runbook=target).count() == 1

    def test_slug_collision_auto_suffixes(self, db):
        _build_source()
        target = service.clone_runbook("src", new_name="Src")  # slugifies to taken "src"
        assert target.slug == "src-2"

    def test_copy_locked_flag(self, db):
        Runbook.objects.create(name="L", slug="l")
        service.put_document("l", "d", body="x", title="D", locked=True)
        unlocked = service.clone_runbook("l", new_name="U", copy_locked=False)
        assert not Document.objects.get(runbook=unlocked, key="d").locked
        locked = service.clone_runbook("l", new_name="K", copy_locked=True)
        assert Document.objects.get(runbook=locked, key="d").locked

    def test_images_copied_independently(self, db):
        rb = _build_source()
        doc = Document.objects.get(runbook=rb, key="intro")
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, "PNG")
        ref = service.attach_image(document=doc, data=buf.getvalue(), alt="fig")
        service.put_document("src", "intro", body="# Intro\n\n" + ref.markdown, on_exists="overwrite")

        target = service.clone_runbook("src", new_name="Copy")
        clone_doc = Document.objects.get(runbook=target, key="intro")
        src_pk = doc.images.first().pk
        clone_img = clone_doc.images.first()
        assert clone_img is not None and clone_img.pk != src_pk    # own row
        body = service.read_head(clone_doc)
        assert f"images/{clone_img.pk}/" in body                   # rewritten to the copy
        assert f"images/{src_pk}/" not in body                     # not the source's
        assert doc.images.first().pk == src_pk                     # source untouched


@pytest.mark.django_db
class TestMakeTemplateCommand:
    def test_clones_a_template(self, db):
        _build_source()
        call_command("make_template", "src", name="Src Template", new_slug="src-template")
        template = Runbook.objects.get(slug="src-template")
        assert template.is_template and Document.objects.filter(runbook=template).count() == 2
        assert not Runbook.objects.get(slug="src").is_template   # original unchanged

    def test_unknown_slug_errors(self, db):
        with pytest.raises(CommandError):
            call_command("make_template", "nope")


@pytest.mark.django_db
class TestNewRunbookFromTemplate:
    def test_instantiates_non_template(self, db):
        _build_source()
        call_command("make_template", "src", new_slug="tmpl")
        call_command("new_runbook_from_template", "tmpl", name="Instance", new_slug="instance")
        inst = Runbook.objects.get(slug="instance")
        assert not inst.is_template and Document.objects.filter(runbook=inst).count() == 2

    def test_requires_a_template(self, db):
        _build_source()  # "src" is a normal runbook, not a template
        with pytest.raises(CommandError):
            call_command("new_runbook_from_template", "src", name="x")


@pytest.mark.django_db
class TestPageTemplates:
    def _staff_client(self, name):
        client = Client()
        client.force_login(User.objects.create_user(name, password="p", is_staff=True))
        return client

    def test_make_template_toggles_flag(self, db):
        _build_source()
        doc = Document.objects.get(runbook__slug="src", key="intro")
        assert not doc.is_template
        resp = self._staff_client("mt").post(reverse("runbook:document_make_template", kwargs={"pk": doc.pk}))
        assert resp.status_code == 302
        doc.refresh_from_db()
        assert doc.is_template
        self._staff_client("mt2").post(reverse("runbook:document_make_template", kwargs={"pk": doc.pk}))
        doc.refresh_from_db()
        assert not doc.is_template  # toggles back off

    def test_list_template_documents_union(self, db):
        # A flagged page in a normal runbook + all docs of a template runbook.
        _build_source()
        Document.objects.filter(runbook__slug="src", key="intro").update(is_template=True)
        service.clone_runbook("src", new_name="T", new_slug="t", as_template=True)  # 2 template-runbook docs
        titles = {d.title for d in service.list_template_documents()}
        assert "Intro" in titles           # flagged page (appears once as src/intro)
        assert titles >= {"Intro", "FAQ"}  # template-runbook docs included

    def test_new_page_with_template_seeds_content(self, db):
        # The single New Page form: picking a template seeds the body.
        _build_source()
        Document.objects.filter(runbook__slug="src", key="faq").update(is_template=True)
        template = Document.objects.get(runbook__slug="src", key="faq")
        work = Runbook.objects.create(name="Work", slug="work")
        resp = self._staff_client("cft").post(
            reverse("runbook:document_create_scratch", kwargs={"slug": "work"}),
            {"title": "New From FAQ", "template": template.pk},
        )
        assert resp.status_code == 302
        new = Document.objects.get(runbook=work, title="New From FAQ")
        assert "Q?" in service.read_head(new)   # body copied from the template
        assert new.key is None                   # keyless — no collision

    def test_new_page_without_template_is_blank(self, db):
        # No template picked → an empty page (just the H1), same as before.
        work = Runbook.objects.create(name="Work", slug="work")
        resp = self._staff_client("cftb").post(
            reverse("runbook:document_create_scratch", kwargs={"slug": "work"}),
            {"title": "Fresh"},
        )
        assert resp.status_code == 302
        assert service.read_head(Document.objects.get(runbook=work, title="Fresh")).strip() == "# Fresh"

    def test_new_page_rejects_invalid_template(self, db):
        work = Runbook.objects.create(name="Work", slug="work")
        resp = self._staff_client("cft2").post(
            reverse("runbook:document_create_scratch", kwargs={"slug": "work"}),
            {"title": "X", "template": 99999},
        )
        assert resp.status_code == 200  # form re-rendered with a validation error
        assert not Document.objects.filter(runbook=work, title="X").exists()

    def test_new_page_template_threads_description(self, db):
        # Description flows through even when seeding from a template (option b).
        _build_source()
        Document.objects.filter(runbook__slug="src", key="faq").update(is_template=True)
        template = Document.objects.get(runbook__slug="src", key="faq")
        work = Runbook.objects.create(name="Work", slug="work")
        resp = self._staff_client("cftd").post(
            reverse("runbook:document_create_scratch", kwargs={"slug": "work"}),
            {"title": "Doc", "template": template.pk, "description": "one-liner"},
        )
        assert resp.status_code == 302
        new = Document.objects.get(runbook=work, title="Doc")
        assert new.description == "one-liner"
        assert "Q?" in service.read_head(new)

    def test_new_page_form_has_template_field(self, db):
        # The picker is folded into the single New Page form.
        _build_source()
        Document.objects.filter(runbook__slug="src", key="intro").update(is_template=True)
        work = Runbook.objects.create(name="Work", slug="work")
        form = DocumentCreateFromScratchForm(runbook=work)
        assert "template" in form.fields
        assert not form.fields["template"].required
        assert any(t.title == "Intro" for t in form.fields["template"].queryset)

    def test_runbook_detail_exposes_template_docs(self, db):
        _build_source()
        Document.objects.filter(runbook__slug="src", key="intro").update(is_template=True)
        resp = self._staff_client("rd").get(reverse("runbook:runbook_detail", kwargs={"slug": "src"}))
        assert any(d.title == "Intro" for d in resp.context["template_docs"])

    def test_create_from_template_assigns_chosen_section(self, db):
        _build_source()
        Document.objects.filter(runbook__slug="src", key="faq").update(is_template=True)
        template = Document.objects.get(runbook__slug="src", key="faq")
        work = Runbook.objects.create(name="Work", slug="work")
        sec = Section.objects.create(name="Ops", slug="ops", runbook=work)
        resp = self._staff_client("cfs").post(
            reverse("runbook:document_create_scratch", kwargs={"slug": "work"}),
            {"title": "Placed", "template": template.pk, "section": sec.pk},
        )
        assert resp.status_code == 302
        assert Document.objects.get(runbook=work, title="Placed").section_id == sec.pk

    def test_runbook_toc_shows_ungrouped_pages(self, db):
        _build_source()
        service.create_document("src", body="# Loose", title="Loose Page", is_generated=False)
        resp = self._staff_client("tocu").get(reverse("runbook:runbook_detail", kwargs={"slug": "src"}))
        assert any(d.title == "Loose Page" for d in resp.context["ungrouped_docs"])
        html = resp.content.decode()
        assert "Ungrouped" in html and "Loose Page" in html

    def test_section_less_doc_breadcrumb_links_runbook(self, db):
        _build_source()
        doc = service.create_document("src", body="# X", title="Loose", is_generated=False)
        html = self._staff_client("bc").get(reverse("runbook:document_detail", kwargs={"pk": doc.pk})).content.decode()
        # Breadcrumb links to the runbook (not the generic Documents fallback).
        assert reverse("runbook:runbook_detail", kwargs={"slug": "src"}) in html


@pytest.mark.django_db
class TestTemplatesExcludedFromListings:
    def _admin_client(self, name):
        client = Client()
        client.force_login(User.objects.create_superuser(name, email=f"{name}@x.co", password="p"))
        return client

    def test_dashboard_splits_templates(self, db):
        _build_source()
        service.clone_runbook("src", new_name="T", new_slug="t", as_template=True)
        resp = self._admin_client("admin1").get(reverse("runbook:dashboard"))
        runbook_slugs = {rb.slug for rb in resp.context["runbooks"]}
        template_slugs = {rb.slug for rb in resp.context["templates"]}
        assert "src" in runbook_slugs and "t" not in runbook_slugs
        assert "t" in template_slugs
        assert resp.context["total_runbooks"] == 1

    def test_document_list_excludes_template_docs(self, db):
        _build_source()
        service.clone_runbook("src", new_name="T", new_slug="t", as_template=True)
        resp = self._admin_client("admin2").get(reverse("runbook:document_list"))
        assert all(not d.runbook.is_template for d in resp.context["documents"])


@pytest.mark.django_db
class TestRunbookCreateFromTemplate:
    def _staff_client(self, name):
        client = Client()
        client.force_login(User.objects.create_user(name, password="p", is_staff=True))
        return client

    def test_create_form_lists_templates(self, db):
        _build_source()
        service.clone_runbook("src", new_name="T", new_slug="t", as_template=True)
        from apps.runbook.forms import RunbookCreateForm
        qs = RunbookCreateForm().fields["template"].queryset
        assert qs.count() == 1 and qs.first().is_template

    def test_create_from_template_clones(self, db):
        _build_source()
        tmpl = service.clone_runbook("src", new_name="T", new_slug="t", as_template=True)
        resp = self._staff_client("cv").post(
            reverse("runbook:runbook_create"),
            {"name": "From Create", "template": tmpl.pk, "description": "", "icon": "🚀"},
        )
        assert resp.status_code == 302
        rb = Runbook.objects.get(name="From Create")
        assert not rb.is_template
        assert rb.icon == "🚀"                                        # user override applied
        assert Document.objects.filter(runbook=rb).count() == 2       # template docs cloned

    def test_create_blank_without_template(self, db):
        resp = self._staff_client("cv2").post(
            reverse("runbook:runbook_create"),
            {"name": "Blank RB", "description": "", "icon": ""},
        )
        assert resp.status_code == 302
        rb = Runbook.objects.get(name="Blank RB")
        assert Document.objects.filter(runbook=rb).count() == 0
