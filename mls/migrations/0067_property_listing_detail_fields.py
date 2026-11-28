from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mls", "0066_property_interior_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="property",
            name="garages",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="garage_size",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="garage_yn",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="open_parking_spaces",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="kitchens",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="rooms_total",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="family_room_yn",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="direction_faces",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="cross_street",
            field=models.CharField(blank=True, max_length=2000, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="tax_legal_description",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="possession",
            field=models.CharField(blank=True, max_length=2000, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="laundry_features",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="locker",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="link_yn",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="property_features",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="property",
            name="washrooms_json",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
