"""Project-root pytest configuration.

Ensures the MCP test-only Widget + Gadget tables exist for every test
session. They live as managed=False models in apps/mcp/tests/models.py so
production migrations don't touch them — schema_editor adds them at
session start and they vanish when the in-memory SQLite test DB is torn
down. Without this, Explorer's iteration of CRUDView._registry would hit
the test-only tables and fail with "no such table" for any tests outside
apps/mcp/.

Any FK on these models MUST be db_constraint=False: flush for
transaction=True tests doesn't truncate unmanaged tables, and Postgres
refuses to TRUNCATE a table (accounts_user) that a real FK references —
which failed every transaction=True teardown on Postgres and leaked rows
into later tests. test_testonly_tables.py pins this.
"""

import pytest
from django.db import connection


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):  # noqa: PT004
    from apps.mcp.tests.models import Gadget, Widget

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            for model in (Widget, Gadget):
                try:
                    editor.create_model(model)
                except Exception:
                    pass
