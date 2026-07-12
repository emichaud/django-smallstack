# Squashed initial migration for smallstack-runbook.

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Runbook",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(unique=True)),
                ("description", models.TextField(blank=True)),
                ("icon", models.CharField(blank=True, max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Section",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField()),
                ("description", models.TextField(blank=True)),
                ("icon", models.CharField(blank=True, max_length=50)),
                ("order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "runbook",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sections",
                        to="smallstack_runbook.runbook",
                    ),
                ),
            ],
            options={
                "ordering": ["order", "name"],
                "unique_together": {("runbook", "slug")},
            },
        ),
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200)),
                (
                    "file",
                    models.FileField(
                        upload_to="runbook/",
                        validators=[django.core.validators.FileExtensionValidator(allowed_extensions=["md"])],
                    ),
                ),
                (
                    "file_type",
                    models.CharField(
                        choices=[("md", "Markdown")],
                        editable=False,
                        max_length=10,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "content_text",
                    models.TextField(
                        blank=True,
                        editable=False,
                        help_text="Extracted plaintext for full-text search.",
                    ),
                ),
                ("is_current", models.BooleanField(default=True)),
                ("version", models.IntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "previous_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="next_versions",
                        to="smallstack_runbook.document",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="runbook_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "section",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="documents",
                        to="smallstack_runbook.section",
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(fields=["is_current"], name="ss_rb_doc_is_curr_idx"),
                    models.Index(fields=["section", "is_current"], name="ss_rb_doc_sec_curr_idx"),
                ],
            },
        ),
    ]
