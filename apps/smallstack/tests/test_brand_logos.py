"""The logo that follows the theme: live in the app for the stock brand, and as
files for every palette (``brand_logos``)."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory

from apps.smallstack import brand_logos
from apps.smallstack.context_processors import STOCK_LOGO, STOCK_LOGO_DARK, STOCK_LOGO_TEXT, branding

CSS = """
html[data-palette="sea"] { --primary: #0a7a8f; --header-bg: #0a7a8f; }
html[data-palette="sea"][data-theme="dark"],
html[data-palette="sand"][data-theme="dark"] { --shadow: none; }
html[data-palette="sea"][data-theme="dark"] { --card-bg: #111; --primary: #22C7E0; }
html[data-palette="sand"] { --primary: #a67c00; }
"""


def test_each_palettes_accent_is_read_from_its_own_blocks():
    found = brand_logos.accents(CSS)
    assert found["sea"] == {"light": "#0a7a8f", "dark": "#22c7e0"}  # the first block of each that sets one
    assert found["sand"] == {"light": "#a67c00", "dark": "#a67c00"}  # no dark block: its one accent


def test_a_logo_is_one_accent_stepped_and_a_name_in_two_colours():
    svg = brand_logos.logo_svg("#22c7e0", "dark")
    assert svg.count("<rect") == 4 and svg.count('fill="#22c7e0"') == 5  # four squares and "SmallStack"
    assert [f'fill-opacity="{s:g}"' in svg for s in brand_logos.STEPS] == [True] * 4
    assert '<tspan fill="#ffffff"' in svg and ">Django </tspan>" in svg and ">SmallStack</tspan>" in svg
    assert '<tspan fill="#1a1a1a"' in brand_logos.logo_svg("#0a7a8f", "light")
    icon = brand_logos.icon_svg("#22c7e0")
    assert icon.count("<rect") == 4 and "<text" not in icon and 'viewBox="0 0 48 48"' in icon


def test_the_command_writes_a_set_for_every_palette_and_knows_when_its_stale(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(brand_logos, "APP", tmp_path / "apps" / "smallstack")  # only for the path it prints
    monkeypatch.setattr(brand_logos, "OUT_DIR", tmp_path / "apps" / "smallstack" / "static" / "logos")
    files = brand_logos.build()
    assert files and all(name.endswith(".svg") for name in files)
    palettes = {name.split("-", 1)[1].rsplit("-", 1)[0] for name in files}
    assert len(files) == 4 * len(palettes)  # logo + icon, on dark + light
    with pytest.raises(Exception, match="out of date"):
        call_command("brand_logos", "--check")
    call_command("brand_logos")
    assert sorted(p.name for p in brand_logos.OUT_DIR.iterdir()) == sorted(files)
    call_command("brand_logos", "--check")
    assert "in sync" in capsys.readouterr().out
    (brand_logos.OUT_DIR / next(iter(files))).write_text("<svg/>")
    assert brand_logos.stale(brand_logos.OUT_DIR) == [next(iter(files))]


def test_the_files_that_ship_match_the_palettes_that_ship():
    """Only the files that are there: a project that adds a palette and hasn't
    run the command yet has nothing wrong with it."""
    built = brand_logos.build()
    shipped = [p for p in brand_logos.OUT_DIR.glob("*.svg") if p.name in built]
    assert shipped, "no logo files: run `manage.py brand_logos`"
    for path in shipped:
        assert path.read_text() == built[path.name], f"{path.name} is out of date: run `manage.py brand_logos`"


def _brand(settings, **overrides):
    for name, value in overrides.items():
        setattr(settings, name, value)
    request = RequestFactory().get("/")
    request.user = type("Anon", (), {"is_authenticated": False})()
    return branding(request)["brand"]


def test_the_stock_logo_is_drawn_live_and_a_projects_own_logo_is_its_image(settings):
    stock = _brand(settings, BRAND_LOGO=STOCK_LOGO, BRAND_LOGO_DARK=STOCK_LOGO_DARK, BRAND_LOGO_TEXT=STOCK_LOGO_TEXT)
    assert stock["wordmark_themed"] and stock["logo_themed"]
    word = render_to_string("smallstack/includes/brand_wordmark.html", {"brand": stock})
    assert 'class="brand-word-accent">SmallStack<' in word and "<img" not in word
    lockup = render_to_string("smallstack/includes/brand_lockup.html", {"brand": stock})
    assert 'class="brand-lockup brand-on-page"' in lockup and 'class="brand-mark"' in lockup and "<img" not in lockup

    own = _brand(settings, BRAND_LOGO_TEXT="brand/mine-text.svg", BRAND_LOGO="brand/mine.svg")
    assert not own["wordmark_themed"] and not own["logo_themed"]
    word = render_to_string("smallstack/includes/brand_wordmark.html", {"brand": own})
    assert 'src="/static/brand/mine-text.svg"' in word and "brand-word" not in word
    lockup = render_to_string("smallstack/includes/brand_lockup.html", {"brand": own})
    assert 'src="/static/brand/mine.svg"' in lockup and lockup.count("<img") == 2 and "brand-mark" not in lockup
