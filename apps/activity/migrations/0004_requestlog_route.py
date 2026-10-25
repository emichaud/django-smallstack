"""Add RequestLog.route and backfill it from the current URLconf.

The backfill resolves each distinct path once; a 10k-row retention cap keeps
that cheap. Paths that no longer resolve stay empty, which is also what the
middleware records for a genuine 404.
"""

from django.db import migrations, models


def backfill_routes(apps, schema_editor):
    from django.urls import Resolver404, resolve

    RequestLog = apps.get_model("activity", "RequestLog")
    paths = RequestLog.objects.filter(route="").values_list("path", flat=True).distinct()
    for path in paths:
        try:
            match = resolve(path)
        except Resolver404:
            continue
        except Exception:  # pragma: no cover — a broken view import must not block migrating
            continue
        RequestLog.objects.filter(path=path, route="").update(route=("/" + match.route)[:255])


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0003_add_request_id_to_requestlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestlog",
            name="route",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
        migrations.RunPython(backfill_routes, migrations.RunPython.noop),
    ]
