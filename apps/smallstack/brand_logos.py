"""The SmallStack logo as files, one set for each palette.

Inside the app the stock logo is drawn live from the theme
(``includes/brand_mark.html``, ``brand_wordmark.html``, ``brand_lockup.html``).
Outside it (a README, a slide, an email, a marketing page) a logo has to be a
file, and a file has one set of colours. So this writes the same drawing for
every palette, from the accent each palette really uses:

    logo-<palette>-dark.svg    mark + name, for a dark background
    logo-<palette>-light.svg   mark + name, for a light background
    icon-<palette>-dark.svg    the mark alone
    icon-<palette>-light.svg

The palettes are the ones in ``palettes.yaml``; each accent is that palette's
``--primary`` in ``palettes.css`` (its light block and its dark one). The four
squares are one colour stepped by opacity, as on screen, so a file sits on any
background of its kind.

``manage.py brand_logos`` writes them; ``--check`` says whether they're current.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parent
PALETTES_YAML = APP / "palettes.yaml"
PALETTES_CSS = APP / "static" / "smallstack" / "css" / "palettes.css"
OUT_DIR = APP / "static" / "smallstack" / "brand" / "palettes"

#: The four squares, faintest to full: the steps ``.brand-mark`` uses on screen.
STEPS = (0.4, 0.6, 0.8, 1)
#: "Django", beside the accent-coloured "SmallStack", on each kind of background.
NAME_COLOUR = {"dark": "#ffffff", "light": "#1a1a1a"}
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"

_BLOCK = re.compile(r'html\[data-palette="([\w-]+)"\](\[data-theme="dark"\])?\s*\{([^}]*)\}')
_PRIMARY = re.compile(r"--primary:\s*(#[0-9a-fA-F]{3,8})\s*;")


def palette_ids() -> list[str]:
    """The palettes on offer, in the order the picker shows them."""
    data = yaml.safe_load(PALETTES_YAML.read_text()) or {}
    return [str(p["id"]) for p in data.get("palettes", []) if p.get("id")]


def accents(css: str | None = None) -> dict[str, dict[str, str]]:
    """``{palette: {"light": "#…", "dark": "#…"}}``: each palette's ``--primary``
    in each theme, read from ``palettes.css`` (the first block of each that
    sets one). A palette with no dark block of its own uses its light accent."""
    found: dict[str, dict[str, str]] = {}
    for palette, dark, body in _BLOCK.findall(PALETTES_CSS.read_text() if css is None else css):
        primary = _PRIMARY.search(body)
        if primary:
            found.setdefault(palette, {}).setdefault("dark" if dark else "light", primary.group(1).lower())
    for themes in found.values():
        themes.setdefault("dark", themes.get("light", ""))
        themes.setdefault("light", themes["dark"])
    return found


def _squares(colour: str, x: float, y: float, side: float, gap: float, radius: float) -> str:
    cells = ((0, 0), (1, 0), (0, 1), (1, 1))
    return "".join(
        f'<rect x="{x + col * (side + gap):g}" y="{y + row * (side + gap):g}" width="{side:g}" height="{side:g}" '
        f'rx="{radius:g}" fill="{colour}" fill-opacity="{step:g}"/>'
        for (col, row), step in zip(cells, STEPS)
    )


def icon_svg(accent: str) -> str:
    """The mark alone, 48 × 48."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48" role="img" '
        f'aria-label="SmallStack">{_squares(accent, 4, 4, 18, 4, 3)}</svg>\n'
    )


def logo_svg(accent: str, background: str) -> str:
    """The mark and the name, for a *background* that is ``"dark"`` or ``"light"``."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="290" height="48" viewBox="0 0 290 48" role="img" '
        'aria-label="Django SmallStack">'
        f"{_squares(accent, 4, 4, 18, 4, 3)}"
        f'<text x="60" y="33" font-family="{FONT}" font-size="25" letter-spacing="-0.4">'
        f'<tspan fill="{NAME_COLOUR[background]}" fill-opacity="0.92" font-weight="500">Django </tspan>'
        f'<tspan fill="{accent}" font-weight="700">SmallStack</tspan></text></svg>\n'
    )


def build() -> dict[str, str]:
    """Every file, by name: ``{"logo-gold-dark.svg": "<svg…", …}``. A palette
    listed in the YAML with no accent in the CSS yet is left out."""
    colours = accents()
    files: dict[str, str] = {}
    for palette in palette_ids():
        for background in ("dark", "light"):
            accent = colours.get(palette, {}).get(background)
            if not accent:
                continue
            files[f"logo-{palette}-{background}.svg"] = logo_svg(accent, background)
            files[f"icon-{palette}-{background}.svg"] = icon_svg(accent)
    return files


def stale(out_dir: Path | None = None) -> list[str]:
    """The files that are missing or don't match what :func:`build` makes now."""
    out_dir = out_dir or OUT_DIR
    return [
        name
        for name, content in build().items()
        if not (out_dir / name).is_file() or (out_dir / name).read_text() != content
    ]


def write(out_dir: Path | None = None) -> list[str]:
    """Write every file; returns the names it changed."""
    out_dir = out_dir or OUT_DIR
    changed = stale(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in build().items():
        (out_dir / name).write_text(content)
    return changed
