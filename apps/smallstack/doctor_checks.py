"""Checks shared by the ``*_doctor`` commands.

A doctor is what you run when something is already wrong — so it must report
a broken precondition, not die on it with a traceback. (Audit 2026-09-13, D10f.)
"""

from __future__ import annotations

from typing import Any


def schema_check() -> dict[str, Any] | None:
    """A report entry for an unreachable/unmigrated database, else None.

    ``FAIL`` (callers skip their other checks) when model tables are missing —
    the case that used to traceback. ``WARN`` (callers carry on) when tables
    exist but some migrations are unapplied.
    """
    from django.apps import apps
    from django.db import DEFAULT_DB_ALIAS, connections
    from django.db.migrations.executor import MigrationExecutor

    try:
        connection = connections[DEFAULT_DB_ALIAS]
        existing = set(connection.introspection.table_names())
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:  # noqa: BLE001 — any failure here is the finding
        return {
            "name": "Database",
            "status": "FAIL",
            "detail": f"Could not read the database: {exc}. Other checks skipped.",
        }
    missing = sorted(
        m._meta.db_table
        for m in apps.get_models()
        if m._meta.managed and not m._meta.proxy and m._meta.db_table not in existing
    )
    if missing:
        return {
            "name": "Database schema",
            "status": "FAIL",
            "detail": (
                f"{len(missing)} table(s) missing (e.g. {', '.join(missing[:3])}) — run `make migrate` "
                "(or `manage.py migrate`). Other checks skipped until the schema exists."
            ),
        }
    if pending:
        return {
            "name": "Database schema",
            "status": "WARN",
            "detail": f"{len(pending)} unapplied migration(s) — run `make migrate`.",
        }
    return None
