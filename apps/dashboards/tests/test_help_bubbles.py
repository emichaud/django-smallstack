"""The "In short" help pages and the bubbles that open them.

Read from this app's own files (its content and its templates), so a project
that overrides a template or adds docs of its own doesn't change the answer."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from apps.help.utils import get_help_bubble

APP = Path(__file__).resolve().parents[1]
CONTENT = APP / "content"
BUBBLE = re.compile(r'{%\s*help_bubble\s+"dashboards"\s+"([\w-]+)"')


def _in_short() -> list[str]:
    config = yaml.safe_load((CONTENT / "_config.yaml").read_text())
    return [p["slug"] for p in config["pages"] if p.get("category") == "In short"]


def _frontmatter(slug: str) -> dict:
    return yaml.safe_load((CONTENT / f"{slug}.md").read_text().split("---", 2)[1])


def _placed() -> dict[str, set[str]]:
    """Each bubble topic → the templates of this app that open it."""
    placed: dict[str, set[str]] = {}
    for template in (APP / "templates").rglob("*.html"):
        for slug in BUBBLE.findall(template.read_text()):
            placed.setdefault(slug, set()).add(template.name)
    return placed


def test_there_is_a_page_for_each_piece():
    assert set(_in_short()) >= {"how-it-fits", "dataset", "metric", "component", "dashboard", "goal-list", "report"}


@pytest.mark.parametrize("slug", _in_short())
def test_an_in_short_page_is_a_page_to_a_page_and_a_half(slug):
    body = (CONTENT / f"{slug}.md").read_text().split("---", 2)[2]
    words = len(re.findall(r"[A-Za-z0-9']+", body))
    assert 400 <= words <= 750, f"{slug}.md is {words} words"


@pytest.mark.parametrize("slug", _in_short())
def test_its_footer_points_at_pages_that_exist(slug):
    meta = _frontmatter(slug)
    page = get_help_bubble(slug, "dashboards")
    assert page is not None and page["title"] == meta["title"]
    assert [r["slug"] for r in page["related"]] == meta["related"]  # none dropped as missing
    assert page["guide"] is not None and page["guide"]["slug"] == meta["guide"]
    assert "<h1" not in page["content"]


def test_every_bubble_opens_a_page_and_every_page_has_a_bubble():
    placed = _placed()
    # dataset.md is opened from the datasets app's pages, which this app doesn't own.
    assert set(placed) == set(_in_short()) - {"dataset"}
    for slug in placed:
        assert (CONTENT / f"{slug}.md").is_file(), slug


def test_the_pages_of_one_piece_open_the_same_help():
    placed = _placed()
    assert {"component_list.html", "component_form.html"} <= placed["component"]
    assert {"metric_list.html", "metric_form.html", "metric_detail.html"} <= placed["metric"]
    assert {"dashboard.html", "dashboard_list.html", "dashboard_form.html", "my_dashboards.html"} <= placed["dashboard"]
    assert {"goals.html", "goallist_list.html", "goallist_form.html"} <= placed["goal-list"]
    assert {"report.html", "report_list.html", "report_form.html"} <= placed["report"]
    assert {"playlist.html", "playlist_list.html", "playlist_form.html"} <= placed["playlist"]
    assert {"goal_weeks.html", "goal_history.html"} <= placed["history"]
    assert {"index.html", "goals_index.html"} <= placed["how-it-fits"]
