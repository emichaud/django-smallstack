from django.db import migrations


def migrate_light_blue_to_high_contrast(apps, schema_editor):
    UserProfile = apps.get_model("profile", "UserProfile")
    UserProfile.objects.filter(color_palette="light-blue").update(color_palette="high-contrast")


def migrate_high_contrast_to_light_blue(apps, schema_editor):
    UserProfile = apps.get_model("profile", "UserProfile")
    UserProfile.objects.filter(color_palette="high-contrast").update(color_palette="light-blue")


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0003_replace_light_blue_with_high_contrast"),
    ]

    operations = [
        migrations.RunPython(
            migrate_light_blue_to_high_contrast,
            migrate_high_contrast_to_light_blue,
        ),
    ]
