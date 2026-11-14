"""No hard-coded colours in app stylesheets.

The house rule (CLAUDE.md, modern-dark-theme.md): a page never names a colour,
it names a variable, so six palettes × two themes all render it correctly.
``help.css`` is the file the skill doc cites as the fixed example — and it had
regressed to 26 legacy-grey literals inside ``[data-theme="dark"]`` blocks, which
rendered fine on purple and muddy on orange and gold. This pins every app
stylesheet so it cannot drift back quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

SHEETS = [
    "apps/smallstack/static/smallstack/help/css/help.css",
    "apps/runbook/static/runbook/runbook.css",
    "apps/blog/static/blog/blog.css",
    "apps/blog/static/blog/studio.css",
    "apps/blog/static/blog/public.css",
]


def _literals(path: Path) -> list[str]:
    out = []
    in_comment = False
    for n, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if "/*" in stripped:
            in_comment = "*/" not in stripped[stripped.index("/*"):]
            continue
        if in_comment:
            in_comment = "*/" not in stripped
            continue
        if HEX.search(line):
            out.append(f"{path.name}:{n}: {stripped}")
    return out


@pytest.mark.parametrize("sheet", SHEETS)
def test_app_stylesheet_has_no_hex_literals(sheet):
    found = _literals(ROOT / sheet)
    assert not found, "hard-coded colours bypass the palette system:\n  " + "\n  ".join(found)


def test_the_topbar_mark_names_no_colour_of_its_own():
    """The four-square mark in the top bar is filled by ``.brand-mark`` from
    ``--brand-mark``. Drawn with green fills of its own, it stayed green on
    every palette. Read from this app's files, so a project that ships its own
    top bar or its own mark isn't being checked."""
    includes = ROOT / "apps/smallstack/templates/smallstack/includes"
    assert 'includes/brand_mark.html" %}' in (includes / "topbar.html").read_text()
    mark = (includes / "brand_mark.html").read_text().split('<svg class="brand-mark"', 1)[1].split("</svg>", 1)[0]
    assert mark.count("<rect") == 4 and "fill=" not in mark and not HEX.search(mark)
    theme = (ROOT / "apps/smallstack/static/smallstack/css/theme.css").read_text()
    assert ".brand-mark rect { fill: var(--brand-mark); }" in theme
    # A light theme's bar is the accent itself, so the mark takes the bar's text
    # colour there; on a dark theme's near-black bar it is the accent. The tokens
    # live in core.css, which theme.css imports.
    tokens = (ROOT / "apps/smallstack/static/smallstack/css/core.css").read_text()
    light, dark = tokens.split('[data-theme="dark"] {', 1)
    assert "--brand-mark: var(--header-fg);" in light.split(":root {", 1)[1].split("}", 1)[0]
    assert "--brand-mark: var(--primary);" in dark.split("}", 1)[0]

