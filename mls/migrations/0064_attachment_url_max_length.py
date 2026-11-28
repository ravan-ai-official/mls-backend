from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mls", "0063_rename_mls_preconact_proj_evt_idx_mls_precona_project_429f6c_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attachment",
            name="url",
            field=models.URLField(max_length=2000),
        ),
    ]
