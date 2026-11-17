from decimal import Decimal

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Invoice = apps.get_model('billing', 'Invoice')
    Line = apps.get_model('billing', 'InvoiceService')
    Rate = apps.get_model('billing', 'UtilityRate')
    rate = Rate.objects.using(alias).filter(effective_date__lte=timezone.localdate()).order_by(
        '-effective_date', '-pk').first()
    for invoice in Invoice.objects.using(alias).select_related('utility_reading').iterator():
        reading = invoice.utility_reading
        for utility, fallback in [('electric', rate.electric_price if rate else 0),
                                  ('water', rate.water_price if rate else 0)]:
            usage = (getattr(reading, f'new_{utility}') - getattr(reading, f'old_{utility}')) if reading else 0
            price = (getattr(invoice, f'{utility}_fee') / usage).quantize(Decimal('0.01')) if usage > 0 else fallback
            setattr(invoice, f'{utility}_unit_price', price)
        paid = sum(invoice.payments.using(alias).values_list('amount', flat=True), Decimal('0'))
        invoice.status = ('da_thanh_toan' if paid >= invoice.total_amount else
                          'qua_han' if invoice.due_date < timezone.localdate() else
                          'thu_mot_phan' if paid > 0 else 'chua_thanh_toan')
        invoice.save(using=alias, update_fields=['electric_unit_price', 'water_unit_price', 'status'])
    for line in Line.objects.using(alias).select_related('service').iterator():
        line.unit_price = line.service.unit_price
        line.description = line.service.name
        line.save(using=alias, update_fields=['unit_price', 'description'])


class Migration(migrations.Migration):
    dependencies = [('billing', '0005_alter_utilityrate_options_and_more')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
