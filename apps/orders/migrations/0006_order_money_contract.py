from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def backfill_existing_money_contracts(apps, schema_editor):
    OrderTicket = apps.get_model("orders", "OrderTicket")
    ApprovalReceipt = apps.get_model("orders", "ApprovalReceipt")

    for ticket in OrderTicket.objects.all().iterator():
        currency = str(ticket.currency or "").strip().upper()
        updates = {"base_currency": currency}
        notional = ticket.estimated_notional
        if notional is not None and Decimal(notional) > 0:
            updates.update(
                {
                    "native_notional": notional,
                    "fx_rate": Decimal("1"),
                    "fx_source_snapshot_id": f"native-{currency}",
                    "fx_as_of": ticket.created_at,
                }
            )
        OrderTicket.objects.filter(pk=ticket.pk).update(**updates)

    ApprovalReceipt.objects.filter(valid=True, consumed_at__isnull=True).update(
        valid=False,
        superseded_at=timezone.now(),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_security_execution_invariants"),
    ]

    operations = [
        migrations.AlterField(
            model_name="orderticket",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="fill",
            name="currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AddField(
            model_name="orderticket",
            name="native_notional",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="orderticket",
            name="base_currency",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="orderticket",
            name="fx_rate",
            field=models.DecimalField(blank=True, decimal_places=10, max_digits=24, null=True),
        ),
        migrations.AddField(
            model_name="orderticket",
            name="fx_source_snapshot_id",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="orderticket",
            name="fx_as_of",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_existing_money_contracts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="orderticket",
            name="base_currency",
            field=models.CharField(default="USD", max_length=16),
        ),
        migrations.AlterField(
            model_name="orderticket",
            name="estimated_notional",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
        migrations.AlterField(
            model_name="approvalreceipt",
            name="max_notional",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=24, null=True),
        ),
    ]
