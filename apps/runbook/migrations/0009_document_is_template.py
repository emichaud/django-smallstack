from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smallstack_runbook', '0008_runbook_is_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='is_template',
            field=models.BooleanField(default=False),
        ),
    ]
