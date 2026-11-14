"""Palette CSS completeness (apps/smallstack/static/smallstack/css/palettes.css).

Two bugs motivated these tests, both invisible until someone switched palette
in light mode:

- `django` shipped with no LIGHT block at all, on the assumption that the
  defaults in theme.css would cover it. They don't. Django admin's base.css
  declares its variables under `html[data-theme="light"], :root` — that first
  branch scores (0,1,1) and the theme JS always writes an explicit data-theme,
  so it outranks theme.css's plain `:root` (0,1,0) regardless of load order.
  A palette with no block therefore falls through to ADMIN's colors, not ours.

- Four light blocks set `--link-color` but not `--link-fg`. SmallStack's own
  CSS reads `--link-color`, but admin's `a:link, a:visited` rule reads
  `--link-fg`, so every plain anchor stayed on admin's #417893 teal and
  ignored the selected palette.

Both classes are caught here by parsing the stylesheet, so a new palette that
omits a block or a variable fails the suite instead of shipping.
"""

import re
from pathlib import Path

from apps.profile.models import UserProfile

PALETTES_CSS = Path(__file__).parents[1] / "static" / "smallstack" / "css" / "palettes.css"

# Django admin's light-mode link color. If a palette ever resolves to this,
# it means the palette failed to claim --link-fg and admin won.
ADMIN_LINK_TEAL = "#417893"

# Anchors get their color from --link-fg (admin's rule) while SmallStack's own
# components read --link-color. A palette must set BOTH or links disagree.
REQUIRED_LINK_VARS = ("--link-fg", "--link-color")


def _palette_ids():
    """Palette ids offered in the UI ('' = system default, which has no block)."""
    return [key for key, _label in UserProfile.COLOR_PALETTE_CHOICES if key]


def _parse_blocks():
    """Map {(palette_id, mode): declarations} for palette variable blocks.

    Only rules whose selector is EXACTLY the palette selector are collected, so
    shared rules that merely list a palette selector among others (accent bands,
    hero overrides) are ignored.
    """
    src = re.sub(r"/\*.*?\*/", "", PALETTES_CSS.read_text(), flags=re.S)
    blocks = {}
    for selector, body in re.findall(r"([^{}]*)\{([^{}]*)\}", src):
        selector = " ".join(selector.split())
        m = re.fullmatch(r'html\[data-palette="([\w-]+)"\](\[data-theme="dark"\])?', selector)
        if not m:
            continue
        mode = "dark" if m.group(2) else "light"
        decls = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
        # A palette may carry extra same-selector rules; merge rather than clobber.
        blocks.setdefault((m.group(1), mode), {}).update(decls)
    return blocks


def test_every_palette_defines_both_light_and_dark_blocks():
    blocks = _parse_blocks()
    missing = [
        f"{palette} ({mode})"
        for palette in _palette_ids()
        for mode in ("light", "dark")
        if (palette, mode) not in blocks
    ]
    assert not missing, (
        "Palette(s) with no variable block in palettes.css: "
        + ", ".join(missing)
        + ". Without a block the palette silently inherits Django admin's colors "
        "in light mode (admin's html[data-theme='light'] outranks theme.css :root)."
    )


def test_every_palette_block_defines_link_fg_and_link_color():
    blocks = _parse_blocks()
    missing = [
        f"{palette} ({mode}) missing {var}"
        for (palette, mode), decls in sorted(blocks.items())
        for var in REQUIRED_LINK_VARS
        if var not in decls
    ]
    assert not missing, (
        "; ".join(missing)
        + ". Anchors read --link-fg (Django admin's a:link rule) while SmallStack "
        "components read --link-color; set both or links ignore the palette."
    )


def test_no_palette_leaves_links_on_admin_teal():
    blocks = _parse_blocks()
    offenders = [
        f"{palette} ({mode})"
        for (palette, mode), decls in sorted(blocks.items())
        if decls.get("--link-fg", "").strip().lower() == ADMIN_LINK_TEAL
    ]
    assert not offenders, (
        f"Palette(s) pinning --link-fg to Django admin's {ADMIN_LINK_TEAL}: "
        + ", ".join(offenders)
    )


def test_parser_actually_finds_the_palette_blocks():
    """Guard the guard: a parser that silently matches nothing would pass above."""
    blocks = _parse_blocks()
    found = {palette for palette, _mode in blocks}
    assert found >= set(_palette_ids()), f"parser found only {sorted(found)}"
    assert len(blocks) >= 2 * len(_palette_ids())
