"""SmallStack's embeds work on a page that doesn't extend ``smallstack/base.html``.

A project's own theme (Bootstrap, Tailwind, a bought one) loads what the theming
guide says: ``{% smallstack_assets %}`` in the head, ``{% smallstack_modal %}``
before ``</body>``, and the theme scripts. Nothing else of SmallStack's shell.
These tests render the embeds on such a page, follow the fragments htmx would
load into it, and hold the result to that contract:

* every drill-down has a modal to open into, and there is only one;
* no class the embeds use is styled only by ``theme.css`` (the shell a custom
  theme doesn't load), and no token their stylesheets read is defined only there;
* ``embed.css`` keeps SmallStack's shared styles in a cascade layer and sets no
  element styles, so it can't restyle the host page.

The embed that quietly needs ``smallstack/base.html`` fails here, not on a
downstream's page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse

from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Report

pytestmark = pytest.mark.django_db

CSS = Path(finders.find("smallstack/css/theme.css")).parent
DS = "smallstack_requests"

OWN_THEME_PAGE = """{% load static theme_tags dashboard_tags calendar_tags help_tags %}<!DOCTYPE html>
<html lang="en"><head><title>Own theme</title>
{% smallstack_assets %}
</head><body>
<h1>Own theme {% help_bubble "dashboards" "metric" %}</h1>
{% metric_card "ot_requests" period="mtd" %}
{% stat_card value=3 label="Static stat" %}
{% dashboard "ot-board" %}
{% card "ot_card" %}
{% goal_list "ot-goals" %}
{% report "ot-report" %}
{% calendar_card "smallstack_events" lazy=False %}
{% calendar_card "smallstack_events" mode="upcoming" %}
{% smallstack_modal %}
</body></html>"""


@pytest.fixture
def staff():
    return get_user_model().objects.create_user("ot-staff", password="x", is_staff=True, is_superuser=True)


@pytest.fixture
def rows():
    Metric(key="ot_requests", name="OT requests", dataset=DS, period_field="timestamp").save()
    Component(name="OT card", key="ot_card", type="metric", metric="ot_requests").save()
    goals = [{"metric": "ot_requests", "target": {"op": ">=", "value": 0}}]
    GoalList(name="OT goals", slug="ot-goals", sections=[{"title": "", "goals": goals}]).save()
    Report(name="OT report", slug="ot-report", items=[{"metric": "ot_requests"}], periods=["mtd"]).save()
    Dashboard(
        name="OT board",
        slug="ot-board",
        layout=[
            {"type": "metric", "metric": "ot_requests", "x": 0, "y": 0, "w": 3, "h": 2},
            {"type": "calendar", "options": {"calendars": ["smallstack_events"]}, "x": 3, "y": 0, "w": 6, "h": 4},
        ],
    ).save()


def _render_page(user) -> str:
    request = RequestFactory().get("/own-theme/")
    request.user = user
    return Template(OWN_THEME_PAGE).render(Context({"request": request, "user": user}))


def _with_fragments(client, html: str, limit: int = 40) -> list[str]:
    """The page plus what htmx loads into it on its own (hx-trigger load / revealed /
    intersect), one level of nesting deep, as a browser would."""
    out, seen = [html], set()
    queue = [html]
    while queue and len(seen) < limit:
        chunk = queue.pop()
        for tag in re.findall(r"<[^>]+hx-get=\"[^\"]+\"[^>]*>", chunk):
            trigger = re.search(r'hx-trigger="([^"]*)"', tag)
            if not trigger or not re.search(r"\b(load|revealed|intersect)\b", trigger.group(1)):
                continue
            url = re.search(r'hx-get="([^"]+)"', tag).group(1).replace("&amp;", "&")
            if url in seen or not url.startswith("/"):
                continue
            seen.add(url)
            resp = client.get(url, HTTP_HX_REQUEST="true")
            assert resp.status_code == 200, f"{url} -> {resp.status_code}"
            out.append(resp.content.decode())
            queue.append(out[-1])
    return out


def _sheet(rel: str) -> Path:
    found = finders.find(rel)
    assert found, f"stylesheet {rel} not found"
    return Path(found)


def _linked_sheets(htmls: list[str]) -> dict[str, str]:
    """Every stylesheet the page links, with embed.css's @imports followed."""
    rels = set()
    for h in htmls:
        rels.update(re.findall(r'href="/static/([^"?]+\.css)', h))
    texts: dict[str, str] = {}
    pending = sorted(rels)
    while pending:
        rel = pending.pop()
        if rel in texts:
            continue
        text = _sheet(rel).read_text()
        texts[rel] = text
        base = rel.rsplit("/", 1)[0]
        pending += [f"{base}/{name}" for name in re.findall(r'@import url\("([^"]+)"\)', text)]
    return texts


def _defines(css: str, cls: str) -> bool:
    return re.search(r"\." + re.escape(cls) + r"(?![\w-])", css) is not None


def test_the_embeds_work_on_a_base_that_isnt_smallstacks(client, staff, rows):
    client.force_login(staff)
    page = _render_page(staff)
    assert "smallstack/css/theme.css" not in page  # really a foreign shell
    htmls = _with_fragments(client, page)
    assert len(htmls) > 1, "no lazy fragments followed; the test lost its reach"
    everything = "\n".join(htmls)

    # Drill-downs have somewhere to open, and only one somewhere.
    assert 'hx-target="#stat-modal-body"' in everything or "data-stat-modal" in everything
    assert page.count('id="stat-modal"') == 1
    assert page.count('id="stat-modal-body"') == 1

    sheets = _linked_sheets(htmls)
    assert "smallstack/css/embed.css" in sheets and "smallstack/css/core.css" in sheets
    linked = "\n".join(sheets.values())
    shell = (CSS / "theme.css").read_text()

    classes = set()
    for h in htmls:
        for value in re.findall(r'class="([^"]*)"', h):
            classes.update(c for c in value.split() if re.fullmatch(r"[\w-]+", c))
    shell_only = sorted(c for c in classes if _defines(shell, c) and not _defines(linked, c))
    assert not shell_only, (
        "styled only by theme.css, which a project's own theme doesn't load; "
        "move the rule to components.css (or core.css for a token):\n" + ", ".join(shell_only)
    )

    defined = set(re.findall(r"(--[\w-]+)\s*:", linked))
    inline = set(re.findall(r"(--[\w-]+)\s*:", everything))  # set on the element itself
    bare_uses = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", linked))  # no fallback
    shell_tokens = set(re.findall(r"(--[\w-]+)\s*:", shell))
    missing = sorted((bare_uses - defined - inline) & shell_tokens)
    assert not missing, "read by the embeds' stylesheets but defined only in theme.css:\n" + ", ".join(missing)


def test_embed_css_is_layered_and_sets_no_element_styles():
    embed = (CSS / "embed.css").read_text()
    imports = re.findall(r'@import url\("([^"]+)"\)\s*layer\(smallstack\);', embed)
    assert imports == ["core.css", "palettes.css", "components.css"]
    assert not re.search(r"@import(?![^;]*layer\(smallstack\))", embed), "an @import outside the layer"
    element = re.compile(
        r"^\s*(\*|html|body|a|p|h[1-6]|ul|ol|li|table|thead|tbody|tr|th|td|input|select|textarea|button|label|img|pre|code)\s*[,{:]",
        re.M,
    )
    for name in ("core.css", "palettes.css", "components.css"):
        hits = element.findall(re.sub(r"/\*.*?\*/", "", (CSS / name).read_text(), flags=re.S))
        assert not hits, f"{name} styles bare elements {hits}: on a project's own theme that restyles the host page"


def test_theme_css_still_brings_the_tokens_to_smallstacks_own_pages():
    theme = (CSS / "theme.css").read_text()
    first_rule = re.sub(r"/\*.*?\*/", "", theme, flags=re.S).strip().splitlines()[0]
    assert first_rule.startswith('@import url("core.css")'), "theme.css must import core.css before any rule"


def test_the_modal_renders_once_per_request(rf):
    request = rf.get("/")
    html = Template("{% load theme_tags %}{% smallstack_modal %}{% smallstack_modal %}").render(
        Context({"request": request})
    )
    assert html.count('id="stat-modal"') == 1


@pytest.mark.parametrize("url_name", ["smallstack_dashboard", "runbook:dashboard"])
def test_smallstack_pages_carry_one_modal(client, staff, url_name):
    client.force_login(staff)
    html = client.get(reverse(url_name)).content.decode()
    assert html.count('id="stat-modal"') == 1, url_name
