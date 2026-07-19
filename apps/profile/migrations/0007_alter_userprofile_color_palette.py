from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profile", "0006_userprofile_timezone"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="color_palette",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "System Default"),
                    ("django", "Django"),
                    ("high-contrast", "High Contrast"),
                    ("dark-blue", "Blue"),
                    ("orange", "Orange"),
                    ("purple", "Purple"),
                    ("gold", "Gold"),
                ],
                default="",
                help_text="Color palette override (blank = system default)",
                max_length=20,
            ),
        ),
    ]
