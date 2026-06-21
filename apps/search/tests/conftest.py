"""Test fixtures for the search app.

The headline fixture here is ``search_registry_snapshot``: an opt-in
context manager + fixture that snapshots ``apps.search.registry._search_registry``
before a test runs and restores it after. Use it whenever a test
registers or unregisters CRUDViews and you want to leave the registry
unchanged for downstream tests in the same Python process — class-level
state in the registry is the most common source of order-dependent
flakes here.

Tests that already use the module-level ``unregister(label)`` pattern
(see ``test_security.py:cleanup_registry``) don't need this fixture —
they're already managing their own cleanup. The snapshot is for new
tests that want a clean-slate-and-restore semantic without having to
enumerate every CRUDView they touch.

Round-4 audit A1 motivation: the bundled tests used to assert
``model_sources == []`` to verify the STAFF-tier gate. That assertion
fails the moment a downstream project registers an AUTH-tier CRUDView,
even though the gate is working correctly. The fix landed in the test
assertions (test the specific gate, not the empty-state) — this
fixture is provided so downstream tests that *do* want
clean-registry-during-this-test semantics have one knob.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def search_registry_snapshot():
    """Snapshot ``_search_registry`` before the test and restore after.

    Yield value: the live registry dict (so the test can mutate it
    directly if it wants). The fixture replaces the in-memory dict, so
    any code that walks the registry during the test sees only what the
    test puts there. After the test, the original entries are restored.

    Usage::

        def test_my_view_in_isolation(search_registry_snapshot):
            from apps.search.registry import register
            register(MyOptInCRUDView)
            # … assertions against a registry containing only MyOptInCRUDView …
    """
    from apps.search import registry as _reg

    snapshot = dict(_reg._search_registry)
    try:
        _reg._search_registry.clear()
        yield _reg._search_registry
    finally:
        _reg._search_registry.clear()
        _reg._search_registry.update(snapshot)
