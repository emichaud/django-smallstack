from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="color_palette",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Color palette override (blank = system default)",
                max_length=20,
            ),
        ),
    ]
