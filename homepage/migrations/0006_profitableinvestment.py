from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("homepage", "0005_sitecontent_curated_key"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfitableInvestment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("listing_key", models.CharField(max_length=64, unique=True)),
                ("address", models.CharField(max_length=255)),
                ("city", models.CharField(db_index=True, max_length=120)),
                ("property_sub_type", models.CharField(blank=True, max_length=120)),
                ("bedrooms", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("bathrooms", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("close_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("close_date", models.DateField()),
                ("previous_close_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("previous_close_date", models.DateField()),
                ("computed_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-close_date"],
            },
        ),
    ]
