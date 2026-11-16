"""Markdown tables scroll inside the article instead of running under the TOC.

A table is as wide as its widest unbreakable cell (a setting name in code),
and the help article is 800px wide; with nothing to scroll it, three tables on
the settings page overlapped the "On this page" sidebar. ``render_markdown``
now wraps every table in ``<div class="md-table">`` (the scroller in help.css).
"""

import pytest

from apps.help.utils import render_markdown
from apps.smallstack.transforms import wrap_tables

TABLE_MD = """
Intro.

| Setting | Default |
|---|---|
| `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER` | 50 |

After.
"""


def test_every_table_is_wrapped_in_its_scroller():
    html = render_markdown(TABLE_MD)["html"]
    assert html.count('<div class="md-table"><table') == 1
    assert html.count("</table></div>") == 1
    assert "<p>After.</p>" in html  # the text around it is untouched


def test_wrapping_is_idempotent_and_leaves_tableless_html_alone():
    plain = "<p>No tables here.</p>"
    assert wrap_tables(plain) is plain
    two = '<table class="x"><tr><td>a</td></tr></table><p>x</p><table><tr><td>b</td></tr></table>'
    wrapped = wrap_tables(two)
    assert wrapped.count('<div class="md-table">') == 2 and wrapped.count("</table></div>") == 2


@pytest.mark.django_db
def test_the_settings_page_serves_wrapped_tables(client, django_user_model):
    user = django_user_model.objects.create_user("reader", password="p", is_staff=True)
    client.force_login(user)
    resp = client.get("/smallstack/help/smallstack/settings-configuration/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("<table") == body.count('<div class="md-table"><table')
    assert body.count("<table") >= 3
