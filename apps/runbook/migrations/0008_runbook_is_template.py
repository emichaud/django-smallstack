from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('smallstack_runbook', '0007_document_locked'),
    ]

    operations = [
        migrations.AddField(
            model_name='runbook',
            name='is_template',
            field=models.BooleanField(default=False),
        ),
    ]
