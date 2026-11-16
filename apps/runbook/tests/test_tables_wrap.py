"""A wide table in a runbook document scrolls inside the card.

The shared hardened renderer wraps every table in ``<div class="md-table">``
(the scroller in components.css), so a document's rendered HTML, its slides
and its steps all carry it; a ``<table>`` an author types as raw HTML is
escaped to text by the hardening and is not wrapped.
"""

import pytest

from apps.runbook.utils import parse_slides, render_document
from apps.smallstack.transforms import render_markdown

from ._factory import make_document

pytestmark = pytest.mark.django_db

TABLE_MD = """# Settings

| Setting | Default |
|---|---|
| `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER` | 50 |

---

# Next

<table><tr><td>typed raw</td></tr></table>
"""


def test_a_document_table_is_wrapped_once_and_raw_html_is_not():
    doc = make_document(title="Tables", body=TABLE_MD)
    html = render_document(doc)["html"]
    assert html.count('<div class="md-table"><table') == 1
    assert html.count("</table></div>") == 1
    assert "&lt;table&gt;" in html  # the raw one stays escaped text


def test_slides_carry_the_wrapper_too():
    slides = parse_slides(TABLE_MD)
    assert '<div class="md-table"><table' in slides[0]["html"]
    assert "<table" not in slides[1]["html"]


def test_the_wrapper_survives_a_toc_less_render():
    assert '<div class="md-table"><table' in render_markdown("| a |\n|---|\n| b |", toc=False)["html"]
