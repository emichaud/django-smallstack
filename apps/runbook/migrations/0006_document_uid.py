import uuid

from django.db import migrations, models


def _populate_uids(apps, schema_editor):
    """Give each existing document its own unique uid."""
    Document = apps.get_model("smallstack_runbook", "Document")
    for doc in Document.objects.all().only("id"):
        doc.uid = uuid.uuid4()
        doc.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ('smallstack_runbook', '0005_subscription'),
    ]

    operations = [
        # 1. Add nullable (no unique yet) so existing rows can share the default.
        migrations.AddField(
            model_name='document',
            name='uid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        # 2. Backfill a distinct uid per existing row.
        migrations.RunPython(_populate_uids, migrations.RunPython.noop),
        # 3. Enforce the canonical non-null unique constraint.
        migrations.AlterField(
            model_name='document',
            name='uid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
