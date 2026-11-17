from decimal import Decimal, ROUND_DOWN

from django.db import migrations
from django.utils import timezone


def normalize_money(apps, schema_editor):
    alias = schema_editor.connection.alias

    def dong(value):
        return Decimal(value).quantize(Decimal('1'), rounding=ROUND_DOWN)

    Payment = apps.get_model('billing', 'Payment')
    old_paid = {}
    for invoice_id, amount in Payment.objects.using(alias).values_list('invoice_id', 'amount').iterator():
        old_paid[invoice_id] = old_paid.get(invoice_id, Decimal('0')) + amount

    fields_by_model = {
        ('rooms', 'Room'): ['price'],
        ('rooms', 'Contract'): ['deposit'],
        ('billing', 'UtilityRate'): ['electric_price', 'water_price'],
        ('billing', 'Service'): ['unit_price'],
        ('billing', 'InvoiceService'): ['unit_price', 'subtotal'],
        ('billing', 'Payment'): ['amount'],
        ('billing', 'PaymentNotice'): ['amount'],
        ('billing', 'Invoice'): ['room_fee', 'electric_fee', 'water_fee',
                                 'electric_unit_price', 'water_unit_price', 'total_amount'],
    }
    for (app, name), fields in fields_by_model.items():
        model = apps.get_model(app, name)
        for row in model.objects.using(alias).all().iterator():
            for field in fields:
                value = getattr(row, field)
                if value is not None:
                    value = dong(value)
                    if name == 'PaymentNotice' and field == 'amount' and value == 0:
                        value = None
                    setattr(row, field, value)
            row.save(using=alias, update_fields=fields)

    Invoice = apps.get_model('billing', 'Invoice')
    Line = apps.get_model('billing', 'InvoiceService')
    for invoice in Invoice.objects.using(alias).all().iterator():
        lines = invoice.invoice_services.using(alias)
        paid = sum(invoice.payments.using(alias).values_list('amount', flat=True), Decimal('0'))
        paid_target = dong(old_paid.get(invoice.pk, Decimal('0')))
        if paid_target > paid:
            # Gộp phần lẻ của nhiều lần thu để không mở lại hóa đơn đã thu đủ.
            last_payment = invoice.payments.using(alias).order_by('-paid_date', '-pk').first()
            last_payment.amount += paid_target - paid
            last_payment.note = (last_payment.note + '\n' if last_payment.note else '') + (
                'Điều chỉnh cộng dồn phần lẻ khi chuyển sang tiền nguyên đồng.')
            last_payment.save(using=alias, update_fields=['amount', 'note'])
            paid = paid_target
        calculated = (invoice.room_fee + invoice.electric_fee + invoice.water_fee
                      + sum(lines.values_list('subtotal', flat=True), Decimal('0')))
        # Giữ tổng hóa đơn cũ sau khi bỏ phần lẻ và không tạo công nợ âm.
        target = max(invoice.total_amount, calculated, paid)
        if target > calculated:
            difference = target - calculated
            Line.objects.using(alias).create(
                invoice=invoice, description='Điều chỉnh chuyển sang tiền nguyên đồng',
                quantity=1, unit_price=difference, subtotal=difference)
        invoice.total_amount = target
        invoice.status = ('da_thanh_toan' if paid >= target else
                          'qua_han' if invoice.due_date < timezone.localdate() else
                          'thu_mot_phan' if paid > 0 else 'chua_thanh_toan')
        invoice.save(using=alias, update_fields=['total_amount', 'status'])


class Migration(migrations.Migration):
    dependencies = [('billing', '0007_bankaccount_paymentnotice'),
                    ('rooms', '0004_room_amenities_room_description_viewingappointment')]
    operations = [migrations.RunPython(normalize_money, migrations.RunPython.noop)]
