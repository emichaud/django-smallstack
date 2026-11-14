"""Shared app-module autodiscovery.

Django auto-imports each app's ``models.py`` and ``admin.py`` but **not**
``views.py``. SmallStack's ``CRUDView`` subclasses live in ``views.py``, and
importing a module is what registers its CRUDViews into ``CRUDView._registry``
(via ``__init_subclass__``). Several subsystems walk that registry at startup —
Search (``enable_search``), the MCP factory (``enable_mcp``), the REST layer,
Explorer — so *something* must import every app's ``views.py`` before those walks
run.

This used to be a side effect of the MCP app's autodiscover, which silently coupled
Search (and any registry consumer) to ``SMALLSTACK_MCP_ENABLED``: turning MCP off
skipped the autodiscover and left the registry under-populated. The logic now lives
here and runs unconditionally from ``SmallStackConfig.ready()`` (the framework core
loads before any consumer), so the registry is fully populated regardless of
feature toggles.
"""

from __future__ import annotations

import ast
import importlib
import logging

logger = logging.getLogger(__name__)


def has_enable_classvar(source: str, marker: str) -> bool:
    """True if ``source`` declares ``<marker> = True`` as a real class attribute.

    AST-based, not a substring/regex match: the marker must be an ``Assign`` /
    ``AnnAssign`` to that exact name, with the constant ``True``, in a
    ``ClassDef`` body. The same characters inside a string literal, comment, or
    docstring don't count — which matters because SmallStack documents its own
    flags with embedded CRUDView examples, and a line-anchored regex can't tell
    a teaching example in a docstring from a live opt-in.

    Used by both ``api_doctor`` and ``mcp_doctor`` to find opt-in files, so the
    two agree on what an opt-in is. A file that doesn't parse returns False:
    it can't be defining a live CRUDView either way.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            value: ast.expr | None
            if isinstance(stmt, ast.Assign):
                names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names = [stmt.target.id]
                value = stmt.value
            else:
                continue
            if marker in names and isinstance(value, ast.Constant) and value.value is True:
                return True
    return False


def is_test_module(py_file) -> bool:
    """True if ``py_file`` is a test module (a ``Path``).

    The counterpart to this module's job: autodiscovery imports ``views.py`` /
    ``mcp_tools.py``, never test code. So a CRUDView declared in a test is a
    fixture that is *supposed* to stay out of the registry, and the health
    checks (``api_doctor`` / ``mcp_doctor`` "orphan files") must not report it
    as an unregistered opt-in — their suggested fix, importing the module from
    ``AppConfig.ready()``, would publish a test view as a live API/MCP surface.

    Both layouts count. Excluding only a ``tests/`` package missed the flat
    ``test_*.py`` convention that ``apps/smallstack`` itself uses, so
    ``smallstack/test_bulk_ops.py`` was reported as an orphan by both doctors
    on every run — a permanent WARN with no action behind it, which is how a
    health check stops being read.
    """
    name = py_file.name
    return (
        "tests" in py_file.parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def autodiscover_app_modules(module_names: tuple[str, ...], *, skip_label: str | None = None) -> list[str]:
    """Import ``<app>.<module>`` for every installed app × every name in ``module_names``.

    Returns the dotted paths successfully imported. A *missing* module (the app
    simply doesn't define it — most apps have no ``mcp_tools.py``) is skipped
    silently; an error *during* import (syntax/runtime failure) is logged but never
    re-raised — a crash here would take down ``AppConfig.ready()`` and the whole
    process. ``skip_label`` omits one app by its ``AppConfig.label`` (e.g. the
    caller's own, when it's already imported).
    """
    from django.apps import apps as django_apps

    imported: list[str] = []
    for app_config in django_apps.get_app_configs():
        if skip_label is not None and app_config.label == skip_label:
            continue
        for mod in module_names:
            dotted = f"{app_config.name}.{mod}"
            try:
                importlib.import_module(dotted)
                imported.append(dotted)
            except ImportError:
                pass
            except Exception:
                logger.warning("autodiscover failed to import %s", dotted, exc_info=True)
    return imported
