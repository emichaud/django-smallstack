"""Add token_type and access_level fields to APIToken.

Existing tokens are set to token_type="manual", access_level="staff".
"""

from django.db import migrations, models


def set_existing_tokens(apps, schema_editor):
    """Mark all existing tokens as manual/staff."""
    APIToken = apps.get_model("smallstack", "APIToken")
    APIToken.objects.all().update(token_type="manual", access_level="staff")


class Migration(migrations.Migration):

    dependencies = [
        ("smallstack", "0007_add_apitoken_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="apitoken",
            name="token_type",
            field=models.CharField(
                choices=[("login", "Login"), ("manual", "Manual")],
                default="manual",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="access_level",
            field=models.CharField(
                blank=True,
                choices=[("auth", "Auth"), ("staff", "Staff"), ("readonly", "Readonly")],
                default="staff",
                max_length=10,
            ),
        ),
        migrations.RunPython(set_existing_tokens, migrations.RunPython.noop),
    ]
