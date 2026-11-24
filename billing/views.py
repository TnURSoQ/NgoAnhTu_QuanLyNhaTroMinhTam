from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache

from accounts.decorators import tenant_required
from rooms.models import Contract
from support.models import Announcement, MaintenanceRequest
from support.services import announcements_for
from . import services
from .forms import PaymentNoticeForm
from .models import BankAccount, Invoice, Payment, PaymentNotice
from .receipts import invoice_statement, payment_records, payment_receipt


def _invoices_of(tenant):
    # Chỉ hóa đơn thuộc hợp đồng mà người thuê này tham gia
    return (
        Invoice.objects.filter(contract__contract_tenants__tenant=tenant)
        .select_related('contract__room', 'utility_reading')
        .prefetch_related('contract__contract_tenants__tenant')
        .order_by('-year', '-month', '-pk')
    )


def _transfer_context(invoice, remaining, notice_form=None):
    notice = invoice.payment_notices.select_related('payment').first() if invoice else None
    return {
        'bank_account': BankAccount.objects.first(), 'transfer_invoice': invoice,
        'transfer_content': services.transfer_content(invoice) if invoice else '',
        'latest_notice': notice,
        'notice_form': notice_form if notice_form is not None else PaymentNoticeForm(),
        'can_report_transfer': bool(invoice and remaining > 0 and (
            not notice or notice.status != PaymentNotice.Status.CHO_XAC_NHAN)),
    }


def _detail_context(invoice, notice_form=None):
    context = invoice_statement(invoice)
    return {
        **context, **_transfer_context(invoice, context['remaining'], notice_form),
    }


@tenant_required
def my_room(request):
    contract = (Contract.objects.filter(contract_tenants__tenant=request.tenant,
                                         status=Contract.Status.HIEU_LUC)
                .select_related('room').order_by('-start_date', '-pk').first())
    invoices = list(_invoices_of(request.tenant).prefetch_related('payments'))
    for invoice in invoices:
        invoice.paid = sum((p.amount for p in invoice.payments.all() if not p.is_voided), Decimal('0'))
        invoice.remaining = invoice.total_amount - invoice.paid
    latest_invoice = invoices[0] if invoices else None
    unpaid_invoice = next((i for i in invoices if i.remaining > 0), None)
    transfer_invoice = unpaid_invoice or latest_invoice
    return render(request, 'billing/my_room.html', {
        'contract': contract, 'room': contract.room if contract else None,
        'can_submit_cooccupants': bool(contract and contract.contract_tenants.filter(tenant=request.tenant, is_representative=True).exists()),
        'latest_invoice': latest_invoice, 'unpaid_invoice': unpaid_invoice,
        'maintenance_requests': MaintenanceRequest.objects.filter(tenant=request.tenant)[:3],
        'announcements': announcements_for(request.tenant)[:3],
        **_transfer_context(transfer_invoice, transfer_invoice.remaining if transfer_invoice else 0),
    })


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
    default_password = (request.user.check_password(request.tenant.id_card_number)
                        or request.user.check_password(request.user.username))
    return render(request, 'billing/invoice_list.html', {
        'invoices': invoices,
        'total_debt': total_debt,
        'default_password': default_password,
    })


@tenant_required
@never_cache
def my_invoice_detail(request, pk):
    invoice = get_object_or_404(_invoices_of(request.tenant), pk=pk)
    return render(request, 'billing/invoice_detail.html', _detail_context(invoice))


@tenant_required
@require_POST
def report_transfer(request, pk):
    invoice = get_object_or_404(_invoices_of(request.tenant), pk=pk)
    form = PaymentNoticeForm(request.POST)
    if form.is_valid():
        try:
            services.report_payment(invoice, request.tenant, **form.cleaned_data)
        except ValidationError as e:
            form.add_error(None, e.messages)
        else:
            messages.success(request, 'Đã báo chuyển khoản. Vui lòng chờ chủ trọ xác nhận.')
            return redirect('my_invoice_detail', pk=pk)
    return render(request, 'billing/invoice_detail.html', _detail_context(invoice, form))


@tenant_required
@never_cache
@require_GET
def my_payments(request):
    payments = (
        Payment.objects.filter(invoice__contract__contract_tenants__tenant=request.tenant)
        .select_related('invoice__contract__room', 'replaces', 'replacement')
        .order_by('-paid_date', '-id')
    )
    return render(request, 'billing/payment_list.html', {'payments': payments})


def _payment_of(tenant, pk):
    return get_object_or_404(payment_records().filter(invoice__contract__contract_tenants__tenant=tenant), pk=pk)


@tenant_required
@never_cache
@require_GET
def my_payment_detail(request, pk):
    payment = _payment_of(request.tenant, pk)
    return render(request, 'billing/payment_detail.html', payment_receipt(payment))


@tenant_required
@never_cache
@require_GET
def my_payment_print(request, pk):
    payment = _payment_of(request.tenant, pk)
    return render(request, 'print/transaction.html', payment_receipt(payment))


@tenant_required
@never_cache
@require_GET
def my_invoice_print(request, pk):
    invoice = get_object_or_404(_invoices_of(request.tenant), pk=pk)
    return render(request, 'print/invoice.html', invoice_statement(invoice))
