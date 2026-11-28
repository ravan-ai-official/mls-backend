from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mls", "0065_property_office_and_original_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="property",
            name="interior_features",
            field=models.TextField(blank=True, null=True),
        ),
    ]
