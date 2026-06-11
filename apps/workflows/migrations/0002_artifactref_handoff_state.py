from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifactref",
            name="handoff_state",
            field=models.CharField(
                choices=[
                    ("accepted", "accepted"),
                    ("revise", "revise"),
                    ("blocked", "blocked"),
                    ("waiting", "waiting"),
                ],
                default="waiting",
                max_length=32,
            ),
        ),
    ]
