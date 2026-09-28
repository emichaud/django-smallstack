"""Test-only models for the MCP test suite.

Widget and Gadget exercise the CRUDView factory without coupling the test
suite to any project-specific model. They're declared `managed=False` so
Django's migration framework leaves them alone; the conftest creates the
backing tables via schema_editor at session start.
"""

from django.conf import settings
from django.db import models


class Widget(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_test_widgets",
        # No DB-level constraint: these tables are created outside migration
        # control (root conftest, schema_editor), so Django's flush for
        # transaction=True tests doesn't truncate them — and Postgres refuses
        # to TRUNCATE accounts_user while a real FK references it, failing
        # EVERY transaction=True teardown ("cannot truncate a table
        # referenced in a foreign key constraint") and leaking rows into the
        # next test (the duplicate-username collisions were this, downstream).
        # The ORM join/expansion behaviour tests need is unchanged.
        db_constraint=False,
    )

    class Meta:
        app_label = "mcp_server"
        managed = False

    def __str__(self) -> str:
        return self.name


class Gadget(models.Model):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_test_gadgets",
        db_constraint=False,  # see Widget.owner
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = "mcp_server"
        managed = False

    def __str__(self) -> str:
        return self.name
