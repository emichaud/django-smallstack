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

ROOT = Path(__file__).resolve().parents[2]
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
