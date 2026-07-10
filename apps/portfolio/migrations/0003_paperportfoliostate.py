from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0002_brokersyncrun_portfolioledgerevent_reconciliationrun"),
    ]

    operations = [
        migrations.AlterField(
            model_name="position",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="cashbalance",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="cashbalance",
            name="amount",
            field=models.DecimalField(decimal_places=6, max_digits=24),
        ),
        migrations.AlterField(
            model_name="portfolioledgerevent",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="portfolioledgerevent",
            name="amount",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
        migrations.CreateModel(
            name="PaperPortfolioState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("portfolio_id", models.CharField(max_length=120)),
                ("account_id", models.CharField(max_length=120)),
                ("strategy_id", models.CharField(max_length=120)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Paper portfolio state",
                "verbose_name_plural": "Paper portfolio states",
            },
        ),
        migrations.AddConstraint(
            model_name="paperportfoliostate",
            constraint=models.UniqueConstraint(
                fields=("portfolio_id", "account_id", "strategy_id"),
                name="unique_paper_portfolio_state",
            ),
        ),
    ]
