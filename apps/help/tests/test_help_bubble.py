"""Help bubbles: a help page opened in the page's modal (``{% help_bubble %}``).

The pages here are made for the test, so nothing depends on which docs a
project ships."""

from __future__ import annotations

import pytest
from django.template import Context, Template
from django.urls import reverse

from .. import utils
from ..utils import get_help_bubble, render_markdown

pytestmark = pytest.mark.django_db

WIDGET = """---
title: What is a widget?
related: [gadget, nowhere]
guide: long-read
---

# What is a widget?

A widget is **one thing**.

## How to use it

Turn it on.
"""


@pytest.fixture
def docs(tmp_path, monkeypatch):
    (tmp_path / "widget.md").write_text(WIDGET)
    (tmp_path / "gadget.md").write_text("---\ntitle: What is a gadget?\n---\n\nA gadget.\n")
    (tmp_path / "long-read.md").write_text("---\ntitle: Things, in full\n---\n\n# Things, in full\n\nLong.\n")
    source = {"things": {"dir": tmp_path, "title": "Things", "app_label": "things"}}
    monkeypatch.setattr(utils, "_get_app_help_sources", lambda: source)
    return tmp_path


def test_a_bubble_is_the_page_without_its_title_or_anchors(docs):
    page = get_help_bubble("widget", "things")
    assert page["title"] == "What is a widget?"
    assert "<strong>one thing</strong>" in page["content"]
    assert "<h1" not in page["content"]  # the modal's header carries the title
    assert "<h2>How to use it</h2>" in page["content"]  # no ids to clash with the host page's
    assert "header-link" not in page["content"]
    assert "header-link" in render_markdown("## A heading")["html"]  # the full page keeps its permalinks


def test_frontmatter_fills_the_footer_and_dead_slugs_are_left_out(docs):
    page = get_help_bubble("widget", "things")
    assert [r["title"] for r in page["related"]] == ["What is a gadget?"]
    assert page["related"][0]["bubble_url"] == reverse("help:section_bubble", args=["things", "gadget"])
    assert page["guide"]["title"] == "Things, in full"
    assert page["guide"]["url"] == reverse("help:section_detail", args=["things", "long-read"])
    plain = get_help_bubble("gadget", "things")
    assert plain["related"] == [] and plain["guide"] is None
    assert get_help_bubble("nowhere", "things") is None


def test_the_fragment_opens_in_the_modal(client, docs):
    url = reverse("help:section_bubble", args=["things", "widget"])
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert '<span id="stat-modal-title" hx-swap-oob="innerHTML">What is a widget?</span>' in html
    assert "<strong>one thing</strong>" in html and "<html" not in html
    # A related page opens in place; the guide and the full page are ordinary links.
    gadget = reverse("help:section_bubble", args=["things", "gadget"])
    assert f'hx-get="{gadget}" hx-target="#stat-modal-body"' in html
    assert f'href="{reverse("help:section_detail", args=["things", "long-read"])}"' in html
    assert f'href="{reverse("help:section_detail", args=["things", "widget"])}"' in html


def test_the_fragment_address_alone_goes_to_the_full_page(client, docs):
    url = reverse("help:section_bubble", args=["things", "widget"])
    response = client.get(url)
    assert response.status_code == 302 and response["Location"] == reverse(
        "help:section_detail", args=["things", "widget"]
    )
    assert client.get(reverse("help:section_bubble", args=["things", "nowhere"])).status_code == 404


def _render(source: str) -> str:
    return Template("{% load help_tags %}" + source).render(Context({})).strip()


def test_the_tag_draws_a_link_that_opens_the_modal(docs):
    html = _render('{% help_bubble "things" "widget" %}')
    assert f'hx-get="{reverse("help:section_bubble", args=["things", "widget"])}"' in html
    assert 'hx-target="#stat-modal-body"' in html and 'data-stat-modal="What is a widget?"' in html
    assert 'data-stat-modal-size="reading"' in html and 'aria-haspopup="dialog"' in html
    # Without JavaScript it's a link to the page; alone, the icon needs a name.
    assert f'href="{reverse("help:section_detail", args=["things", "widget"])}"' in html
    assert 'aria-label="Help: What is a widget?"' in html and 'aria-hidden="true"' in html


def test_a_label_names_the_link_itself(docs):
    html = _render('{% help_bubble "things" "widget" label="About widgets" %}')
    assert "<span>About widgets</span>" in html and "aria-label" not in html


def test_a_page_that_isnt_there_draws_nothing(docs):
    assert _render('{% help_bubble "things" "nowhere" %}') == ""
    assert _render('{% help_bubble "elsewhere" "widget" %}') == ""
