from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Invoice, Payment


@receiver([post_save, post_delete], sender=Payment)
def refresh_invoice_status(sender, instance, **kwargs):
    # Mỗi lần thêm, sửa, xóa khoản thanh toán thì tính lại trạng thái hóa đơn
    invoice = Invoice.objects.filter(pk=instance.invoice_id).first()
    if invoice:
        invoice.update_status()