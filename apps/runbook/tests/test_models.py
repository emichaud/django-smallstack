"""Tests for Runbook models."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.runbook.models import Document, Runbook, Section, strip_frontmatter

from ._factory import make_document

User = get_user_model()


@pytest.fixture
def runbook(db):
    return Runbook.objects.create(name="Test Runbook")


@pytest.fixture
def section(runbook):
    return Section.objects.create(name="Test Section", runbook=runbook)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="testpass")


# -- Runbook ------------------------------------------------------------------


@pytest.mark.django_db
class TestRunbook:
    def test_auto_slug(self):
        rb = Runbook.objects.create(name="My Runbook")
        assert rb.slug == "my-runbook"

    def test_str(self):
        rb = Runbook(name="Operations")
        assert str(rb) == "Operations"

    def test_get_absolute_url(self):
        rb = Runbook(name="Ops", slug="ops")
        assert "/ops/" in rb.get_absolute_url()


# -- Section ------------------------------------------------------------------


@pytest.mark.django_db
class TestSection:
    def test_auto_slug(self, runbook):
        section = Section.objects.create(name="Incident Response", runbook=runbook)
        assert section.slug == "incident-response"

    def test_str(self):
        section = Section(name="Operations")
        assert str(section) == "Operations"

    def test_ordering(self, runbook):
        s1 = Section.objects.create(name="B Section", order=1, runbook=runbook)
        s2 = Section.objects.create(name="A Section", order=0, runbook=runbook)
        sections = list(Section.objects.filter(runbook=runbook))
        assert sections[0] == s2
        assert sections[1] == s1


# -- Document -----------------------------------------------------------------


@pytest.mark.django_db
class TestDocument:
    def test_auto_slug(self):
        doc = Document.objects.create(title="My Document")
        assert doc.slug == "my-document"

    def test_str(self):
        assert str(Document(title="Test", version=3)) == "Test (v3)"

    def test_is_markdown(self):
        doc = Document(title="Test", file_type="md")
        assert doc.is_markdown
        assert not doc.is_pdf
        assert not doc.is_docx

    def test_is_pdf(self):
        doc = Document(title="Test", file_type="pdf")
        assert doc.is_pdf
        assert not doc.is_markdown

    def test_first_version_and_denorm(self, user, section):
        doc = make_document(title="Doc", body=b"# Hello", section=section, created_by=user)
        assert doc.version == 1
        assert doc.file_type == "md"
        assert doc.current_version is not None
        assert doc.versions.count() == 1
        assert doc.file.read().startswith(b"# Hello")


# -- Content extraction -------------------------------------------------------


@pytest.mark.django_db
class TestContentExtraction:
    def test_extract_text_on_version_save(self, user, section):
        doc = make_document(title="Extract", body=b"# Hello World\n\nSome body text.", section=section, created_by=user)
        assert "Hello World" in doc.content_text
        assert "Some body text" in doc.content_text
        assert "Hello World" in doc.current_version.content_text

    def test_extract_strips_frontmatter(self, user, section):
        body = b"---\ntitle: Test\n---\n# Real Content\n\nBody."
        doc = make_document(title="FM", body=body, section=section, created_by=user)
        assert "title: Test" not in doc.content_text
        assert "Real Content" in doc.content_text

    def test_skip_content_extract_on_version(self, user, section):
        doc = make_document(title="Skip", body=b"# Original", section=section, created_by=user)
        version = doc.current_version
        version.content_text = "manually set"
        version.save(update_fields=["content_text"], skip_content_extract=True)
        version.refresh_from_db()
        assert version.content_text == "manually set"


# -- Version creation ---------------------------------------------------------


@pytest.mark.django_db
class TestCreateNewVersion:
    def test_advances_head_and_denorm(self, user, section):
        doc = make_document(title="Versioned", body=b"# V1", section=section, created_by=user)
        assert doc.version == 1

        doc.create_new_version(file=SimpleUploadedFile("v2.md", b"# V2"), created_by=user, description="Updated")
        assert doc.version == 2
        assert doc.versions.count() == 2
        head = doc.current_version
        assert head.version == 2
        assert head.description == "Updated"
        assert head.title == doc.title

    def test_versions_ordered_desc(self, user, section):
        doc = make_document(title="Chain", body=b"# V1", section=section, created_by=user)
        doc.create_new_version(file=SimpleUploadedFile("v2.md", b"# V2"), created_by=user)
        doc.create_new_version(file=SimpleUploadedFile("v3.md", b"# V3"), created_by=user)
        assert [v.version for v in doc.versions.all()] == [3, 2, 1]
        assert doc.current_version.version == 3


# -- strip_frontmatter --------------------------------------------------------


class TestStripFrontmatter:
    def test_strips_yaml_frontmatter(self):
        text = "---\ntitle: Hello\ntags: [a, b]\n---\n# Content\n\nBody."
        assert strip_frontmatter(text) == "# Content\n\nBody."

    def test_no_frontmatter(self):
        text = "# Just Content\n\nBody."
        assert strip_frontmatter(text) == "# Just Content\n\nBody."

    def test_empty_string(self):
        assert strip_frontmatter("") == ""

    def test_incomplete_frontmatter(self):
        text = "---\ntitle: Hello\nNo closing delimiter"
        # Only one --- so it's not valid frontmatter — returned as-is
        assert strip_frontmatter(text) == text.strip()

    def test_frontmatter_with_trailing_whitespace(self):
        text = "---\nkey: val\n---\n\n  # Content  \n\n"
        assert strip_frontmatter(text) == "# Content"
