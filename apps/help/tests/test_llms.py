"""The agent-readable help surfaces: page .md alternates, /llms.txt, /llms-full.txt."""

from __future__ import annotations

import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_markdown_alternate_for_a_section_page(client):
    url = reverse("help:section_detail_md", kwargs={"section": "smallstack", "slug": "getting-started"})
    assert url.endswith("/smallstack/getting-started.md")
    resp = client.get(url)
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/markdown")
    body = resp.content.decode()
    assert body.startswith("# Getting Started") and "{{" not in body  # variables substituted
    missing = reverse("help:section_detail_md", kwargs={"section": "smallstack", "slug": "nope"})
    assert client.get(missing).status_code == 404
    # The HTML page advertises it.
    html = client.get(reverse("help:section_detail", kwargs={"section": "smallstack", "slug": "getting-started"}))
    assert f'rel="alternate" type="text/markdown" href="{url}"' in html.content.decode()
    assert 'rel="describedby" href="/llms.txt"' in html.content.decode()


def test_llms_txt_shape(client):
    resp = client.get("/llms.txt")
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/markdown")
    lines = resp.content.decode().splitlines()
    assert lines[0].startswith("# ") and lines[2].startswith("> ")
    assert "## SmallStack Reference" in lines and "## Optional" in lines
    text = "\n".join(lines)
    assert "http://testserver/smallstack/help/smallstack/getting-started.md" in text
    assert "/llms-full.txt" in text and "/api/schema/openapi.json" in text and "/mcp" in text
    # App-contributed sections (the calendar help) are listed too.
    assert "## Calendar" in lines and "/smallstack/help/calendar/index.md" in text


@override_settings(SMALLSTACK_LLMS_DESCRIPTION="The Acme internal console.")
def test_llms_txt_uses_the_site_description(client):
    assert "> The Acme internal console." in client.get("/llms.txt").content.decode()


def test_llms_full_concatenates_every_page(client):
    resp = client.get("/llms-full.txt")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("<!-- SmallStack Reference ·") > 20
    assert "# Getting Started" in body and "# Prompting a coding agent" in body


@override_settings(SMALLSTACK_DOCS_ENABLED=False)
def test_bundled_docs_switch_hides_them_from_the_agent_surfaces(client):
    md = reverse("help:section_detail_md", kwargs={"section": "smallstack", "slug": "getting-started"})
    assert client.get(md).status_code == 404
    assert "## SmallStack Reference" not in client.get("/llms.txt").content.decode()
