"""The test-only Widget/Gadget tables must carry NO database-level FKs.

Downstream-reported (Postgres, fourth of the family): these tables are
created outside migration control (root conftest, schema_editor), so
Django's flush for ``transaction=True`` tests doesn't truncate them — and
Postgres refuses to TRUNCATE ``accounts_user`` while a real FK references
it::

    FeatureNotSupported: cannot truncate a table referenced in a foreign
    key constraint
    DETAIL:  Table "mcp_server_widget" references "accounts_user".

That failed EVERY ``transaction=True`` teardown in the suite on Postgres
(46 errors), and the leaked rows produced the ``accounts_user_username_key``
duplicate-key collisions in later tests — a symptom that was misattributed
twice before the flush error was read. SQLite hides the category: its test
teardown deletes rows instead of TRUNCATE and enforces no such constraint
ordering.

The fix is ``db_constraint=False`` on the FKs — the ORM joins/expansions the
MCP factory tests rely on are unchanged; only the ``REFERENCES`` clause in
the database disappears. This test introspects the LIVE created tables, so
it fails on any backend if a real constraint sneaks back in.
"""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("table", ["mcp_server_widget", "mcp_server_gadget"])
def test_no_database_level_foreign_keys(table):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    fks = {name: c for name, c in constraints.items() if c.get("foreign_key")}
    assert not fks, (
        f"{table} carries DB-level FK constraint(s) {list(fks)} — on Postgres this "
        "makes accounts_user un-TRUNCATE-able and fails every transaction=True "
        "teardown. Use db_constraint=False on test-only models."
    )


def test_orm_relation_still_works_without_the_constraint(django_user_model):
    """The constraint is gone; the relation is not — joins and reverse
    accessors keep working, which is what the MCP factory tests need."""
    from apps.mcp.tests.models import Widget

    owner = django_user_model.objects.create_user("widget-owner", password="p")
    w = Widget.objects.create(name="w1", owner=owner)
    assert Widget.objects.filter(owner__username="widget-owner").count() == 1
    assert list(owner.mcp_test_widgets.all()) == [w]
