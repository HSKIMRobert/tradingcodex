from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0002_brokerconnection_brokeraccount_instrumentmap"),
    ]

    operations = [
        migrations.AlterField(
            model_name="brokeraccount",
            name="base_currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="instrumentmap",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
    ]
