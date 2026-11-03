"""The dashboards app's layering, enforced.

The building blocks (models, evaluation, comparison, reports, boards,
previews, periods, components) are what a downstream app builds its own UI
on, so they must not depend on SmallStack's UI. The surfaces (pages, REST,
MCP, template tags, list displays) depend on the blocks and never on each
other. These tests parse every module — lazy imports inside functions
included — so a convenience import that inverts a layer fails here instead
of drifting in silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]

#: The building blocks — importable by any surface, by a downstream app.
SERVICES = {
    "boards",
    "comparison",
    "components",
    "forms",
    "metrics",
    "models",
    "periods",
    "playlists",
    "previews",
    "reports",
}
#: SmallStack's own surfaces over them.
SURFACES = {"views", "api", "mcp_tools", "displays", "templatetags", "urls"}


def _module_file(name: str) -> Path:
    return APP / "templatetags" / "dashboard_tags.py" if name == "templatetags" else APP / f"{name}.py"


def _imports(path: Path) -> list[tuple[int, str, list[str]]]:
    """``(line, module, names)`` for every import in *path*, with relative
    modules resolved to their first ``apps.dashboards`` component
    (``from .views import x`` → ``views``; ``from ..models`` → ``models``)."""
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
            if node.level:
                module = (node.module or "").split(".")[0]
            else:
                module = node.module or ""
                if module.startswith("apps.dashboards."):
                    module = module.split(".")[2]
            out.append((node.lineno, module, names))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                module = parts[2] if alias.name.startswith("apps.dashboards.") and len(parts) > 2 else alias.name
                out.append((node.lineno, module, []))
    return out


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_building_blocks_never_import_a_surface(service: str) -> None:
    bad = [
        f"{service}.py:{line} imports from {module}"
        for line, module, _names in _imports(_module_file(service))
        if module in SURFACES
    ]
    assert not bad, "A building block depends on SmallStack's UI:\n" + "\n".join(bad)


@pytest.mark.parametrize(
    ("surface", "forbidden"),
    [
        ("api", {"views", "mcp_tools", "displays", "templatetags"}),
        ("mcp_tools", {"views", "api", "displays", "templatetags"}),
        ("templatetags", {"views", "api", "mcp_tools", "displays"}),
        ("displays", {"views", "api", "mcp_tools"}),
    ],
)
def test_surfaces_never_import_each_other(surface: str, forbidden: set[str]) -> None:
    bad = [
        f"{surface}:{line} imports from {module}"
        for line, module, _names in _imports(_module_file(surface))
        if module in forbidden
    ]
    assert not bad, "One surface depends on another — move the shared code into a building block:\n" + "\n".join(bad)


def test_no_private_names_from_other_apps() -> None:
    """Cross-app imports go through public names, so a refactor inside
    ``datasets`` (or the framework) can't silently break dashboards."""
    bad = []
    for path in sorted(APP.rglob("*.py")):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        for line, module, names in _imports(path):
            if not module.startswith("apps.") or module.startswith("apps.dashboards"):
                continue
            for name in names:
                if name.startswith("_"):
                    bad.append(f"{path.relative_to(APP)}:{line} imports {module}.{name}")
    assert not bad, "\n".join(bad)


def test_no_view_patching() -> None:
    """Generated CRUD views are customised with ``view_mixins`` (ordinary
    mixins, ``super()``), never by overriding ``_make_view`` and assigning
    functions onto the class it returns."""
    source = (APP / "views.py").read_text()
    assert "def _make_view" not in source


# -- templates: behaviour in static JS, versions from the static storage ----------

_TEMPLATES = sorted((APP / "templates").rglob("*.html"))


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: str(p.relative_to(APP / "templates")))
def test_templates_have_no_inline_javascript(path: Path) -> None:
    """Behaviour lives in static JS (``data-stat-modal``, ``data-copy``…), so
    the CSP's script-src needs no ``'unsafe-inline'`` (it has none). A
    ``json_script`` data block is fine; executable inline code is not."""
    import re

    html = path.read_text()
    handlers = re.findall(r"\son[a-z]+\s*=\s*\"", html)
    assert not handlers, f"inline event handler(s) {handlers} — use a data- attribute + a listener in static JS"
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag or "application/json" in tag, f"inline <script> block: {tag}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: str(p.relative_to(APP / "templates")))
def test_static_urls_carry_no_manual_version(path: Path) -> None:
    """``{% static %}`` emits content-hashed names in production
    (``CompressedManifestStaticFilesStorage``); a hand-bumped ``?v=N`` is
    redundant there and drifts everywhere."""
    assert "%}?v=" not in path.read_text()
