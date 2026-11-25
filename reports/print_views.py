from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from accounts.decorators import owner_required
from billing.models import Payment, UtilityRate
from billing.receipts import payment_records, payment_receipt
from rooms.display import representative_of
from rooms.models import CheckoutRecord, Contract, ContractTenant, DepositEntry, Room
from support.models import MaintenanceRequest


def _contract(pk):
    return get_object_or_404(Contract.objects.select_related('room').prefetch_related(
        'contract_tenants__tenant', 'services', 'renewals'), pk=pk)


@owner_required
@require_GET
def contract_print(request, pk):
    contract = _contract(pk)
    return render(request, 'print/contract.html', {'contract': contract, 'utility_rate': UtilityRate.current(),
        'people': contract.contract_tenants.all(), 'document_title': f'Thông tin hợp đồng {contract.display_code}'})


@owner_required
@never_cache
@require_GET
def payment_print(request, pk):
    payment = get_object_or_404(payment_records(), pk=pk)
    return render(request, 'print/transaction.html', payment_receipt(payment))


@owner_required
@require_GET
def deposit_print(request, pk):
    entry = get_object_or_404(DepositEntry.objects.select_related('contract__room', 'related_contract__room', 'payment__invoice')
                              .prefetch_related('contract__contract_tenants__tenant'), pk=pk)
    titles = {'receive': 'Phiếu thu tiền cọc', 'refund': 'Phiếu hoàn tiền cọc',
              'deduct': 'Phiếu khấu trừ tiền cọc', 'transfer_in': 'Phiếu nhận cọc chuyển phòng',
              'transfer_out': 'Phiếu chuyển cọc sang phòng mới', 'pay_invoice': 'Phiếu đối trừ cọc thanh toán hóa đơn'}
    return render(request, 'print/transaction.html', {'entry': entry, 'contract': entry.contract,
        'tenant': representative_of(entry.contract), 'document_title': titles[entry.kind],
        'code': f'COC-{entry.pk:06d}', 'amount': entry.amount, 'occurred_on': entry.occurred_on,
        'method': entry.get_method_display(), 'note': entry.note,
        'internal': entry.kind not in (DepositEntry.Kind.RECEIVE, DepositEntry.Kind.REFUND)})


@owner_required
@require_GET
def checkout_print(request, pk):
    record = get_object_or_404(CheckoutRecord, contract_id=pk)
    contract = _contract(pk)
    return render(request, 'print/checkout.html', {'record': record, 'contract': contract,
        'tenant': representative_of(contract), 'document_title': f'Biên bản trả phòng {contract.room.room_number}'})


@owner_required
@require_GET
def residents_print(request):
    people = ContractTenant.objects.filter(contract__status=Contract.Status.HIEU_LUC).select_related(
        'contract__room', 'tenant').order_by('contract__room__floor', 'contract__room__room_number',
                                           '-is_representative', 'tenant__full_name')
    return render(request, 'print/residents.html', {'people': people, 'document_title': 'Danh sách người đang ở'})


@owner_required
@require_GET
def rooms_print(request):
    rooms = Room.objects.annotate(people_count=Count('contracts__contract_tenants',
        filter=Q(contracts__status=Contract.Status.HIEU_LUC)))
    return render(request, 'print/rooms.html', {'rooms': rooms.order_by('floor', 'room_number'),
                                               'document_title': 'Danh sách phòng'})


@owner_required
@never_cache
@require_GET
def report_print(request):
    from django.http import HttpResponse
    from .services import build_report, report_period
    try:
        period, _ = report_period(request.GET, strict=True)
    except ValueError as exc:
        return HttpResponse(str(exc), status=400)
    context = build_report(period)
    context['document_title'] = f'Báo cáo quản lý nhà trọ {period.label}'
    context['landscape'] = True
    return render(request, 'print/report.html', context)


@owner_required
@require_GET
def maintenance_print(request, pk):
    maintenance = get_object_or_404(MaintenanceRequest.objects.select_related('room', 'tenant').prefetch_related('photos'), pk=pk)
    return render(request, 'print/maintenance.html', {'maintenance': maintenance,
        'document_title': f'Phiếu sửa chữa {maintenance.display_code}'})
