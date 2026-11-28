from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mls", "0064_attachment_url_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="property",
            name="original_list_price",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="list_office_name",
            field=models.CharField(blank=True, max_length=2000, null=True),
        ),
    ]
