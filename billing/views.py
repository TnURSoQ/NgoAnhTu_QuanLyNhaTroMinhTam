from django.shortcuts import get_object_or_404, render

from accounts.decorators import tenant_required
from .models import Invoice, Payment


def _invoices_of(tenant):
    # Chỉ hóa đơn thuộc hợp đồng mà người thuê này tham gia
    return (
        Invoice.objects.filter(contract__contract_tenants__tenant=tenant)
        .select_related('contract__room')
        .order_by('-year', '-month')
    )


@tenant_required
def my_invoices(request):
    invoices = list(_invoices_of(request.tenant))
    total_debt = 0
    for inv in invoices:
        inv.paid = inv.total_paid()
        inv.remaining = inv.total_amount - inv.paid
        if inv.status != Invoice.Status.DA_THANH_TOAN:
            total_debt += inv.remaining
    # Nhắc đổi mật khẩu nếu vẫn đang dùng mật khẩu mặc định (số CCCD)
    default_password = request.user.check_password(request.tenant.id_card_number)
    return render(request, 'billing/invoice_list.html', {
        'invoices': invoices,
        'total_debt': total_debt,
        'default_password': default_password,
    })


@tenant_required
def my_invoice_detail(request, pk):
    invoice = get_object_or_404(_invoices_of(request.tenant), pk=pk)
    paid = invoice.total_paid()
    return render(request, 'billing/invoice_detail.html', {
        'invoice': invoice,
        'reading': invoice.utility_reading,
        'invoice_services': invoice.invoice_services.select_related('service'),
        'payments': invoice.payments.order_by('paid_date', 'id'),
        'paid': paid,
        'remaining': invoice.total_amount - paid,
    })


@tenant_required
def my_payments(request):
    payments = (
        Payment.objects.filter(invoice__contract__contract_tenants__tenant=request.tenant)
        .select_related('invoice__contract__room')
        .order_by('-paid_date', '-id')
    )
    return render(request, 'billing/payment_list.html', {'payments': payments})