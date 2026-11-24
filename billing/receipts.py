from django.utils import timezone

from rooms.display import representative_of
from .models import Invoice, Payment


def invoice_statement(invoice):
    """Render balances from one payment list, using the issued invoice's stored prices."""
    payments = list(invoice.payments.select_related('recorded_by', 'voided_by', 'replacement', 'replaces').order_by('paid_date', 'pk'))
    paid = sum(payment.amount for payment in payments if not payment.is_voided)
    deposit_applied = sum(payment.amount for payment in payments if not payment.is_voided and payment.method == Payment.Method.TU_COC)
    if paid >= invoice.total_amount:
        status = Invoice.Status.DA_THANH_TOAN
    elif invoice.due_date < timezone.localdate():
        status = Invoice.Status.QUA_HAN
    elif paid:
        status = Invoice.Status.THU_MOT_PHAN
    else:
        status = Invoice.Status.CHUA_THANH_TOAN
    # Refresh the display without writing to the database on a tenant's GET request.
    invoice.status = status
    return {'invoice': invoice, 'reading': invoice.utility_reading,
        'tenant': representative_of(invoice.contract),
        'invoice_services': invoice.invoice_services.select_related('service'), 'payments': payments,
        'paid': paid, 'remaining': invoice.total_amount - paid,
        'cash_paid': paid - deposit_applied, 'deposit_applied': deposit_applied,
        'document_title': f'Hóa đơn tiền phòng tháng {invoice.month}/{invoice.year}'}


def payment_records():
    return Payment.objects.select_related('invoice__contract__room', 'invoice__utility_reading', 'recorded_by',
        'payment_notice__tenant', 'payment_notice__processed_by', 'deposit_entry__created_by', 'voided_by',
        'replaces', 'replacement').prefetch_related(
        'invoice__contract__contract_tenants__tenant')


def payment_receipt(payment):
    internal = payment.method == Payment.Method.TU_COC
    notice = getattr(payment, 'payment_notice', None)
    entry = getattr(payment, 'deposit_entry', None)
    recorder = payment.recorded_by or (notice.processed_by if notice else None) or (entry.created_by if entry else None)
    return {**invoice_statement(payment.invoice), 'payment': payment, 'contract': payment.invoice.contract,
        'internal': internal, 'notice': notice, 'deposit_entry': entry, 'recorder': recorder,
        'code': payment.display_code, 'amount': payment.amount, 'occurred_on': payment.paid_date,
        'method': payment.get_method_display(), 'note': payment.note,
        'document_title': 'Lịch sử giao dịch đã hủy' if payment.is_voided else (
            'Phiếu đối trừ cọc thanh toán hóa đơn' if internal else 'Phiếu xác nhận thanh toán')}
