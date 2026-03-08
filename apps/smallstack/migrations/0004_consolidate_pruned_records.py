"""Data migration: consolidate separate 'pruned' records into the original success record."""

from django.db import migrations


def consolidate_pruned_records(apps, schema_editor):
    BackupRecord = apps.get_model("smallstack", "BackupRecord")

    for pruned_record in BackupRecord.objects.filter(status="pruned"):
        # Find matching success record by filename
        success_record = (
            BackupRecord.objects.filter(
                filename=pruned_record.filename,
                status="success",
                pruned_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        if success_record:
            success_record.pruned_at = pruned_record.created_at
            success_record.save(update_fields=["pruned_at"])
            pruned_record.delete()
        else:
            # No matching success record — convert the pruned record itself
            pruned_record.pruned_at = pruned_record.created_at
            pruned_record.status = "success"
            pruned_record.save(update_fields=["pruned_at", "status"])


class Migration(migrations.Migration):
    dependencies = [
        ("smallstack", "0003_add_pruned_at_to_backuprecord"),
    ]

    operations = [
        migrations.RunPython(consolidate_pruned_records, migrations.RunPython.noop),
    ]
