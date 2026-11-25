from datetime import timedelta
from decimal import Decimal
import csv

from django.db.models import Case, DecimalField, F, Prefetch, Sum, When
from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import owner_required
from billing.models import Invoice, Payment, PaymentNotice
from rooms.display import representative_of, room_status_ui
from rooms.models import Contract, DepositEntry, Room, ViewingAppointment
from billing.models import InvoiceDraft
from support.models import MaintenanceRequest

@owner_required
def overview(request):
    """Trang Tổng quan của chủ trọ."""
    today = timezone.localdate()

    rooms_total = Room.objects.count()
    rooms_empty = Room.objects.filter(status=Room.Status.TRONG).count()

    # Hóa đơn chưa thu đủ: tổng nợ tháng này và danh sách quá hạn
    unpaid = (
        Invoice.objects.all()
        .select_related('contract__room')
        .prefetch_related('payments', 'contract__contract_tenants__tenant')
    )
    month_unpaid = Decimal('0')
    overdue = []
    for inv in unpaid:
        paid = sum((p.amount for p in inv.payments.all() if not p.is_voided), Decimal('0'))
        remaining = inv.total_amount - paid
        if remaining <= 0:
            continue
        if (inv.year, inv.month) == (today.year, today.month):
            month_unpaid += remaining
        days = (today - inv.due_date).days
        if days > 0:
            overdue.append((days, inv))
    overdue.sort(key=lambda x: -x[0])

    # Công việc cần xử lý
    tasks = []
    pending_drafts = InvoiceDraft.objects.filter(invoice__isnull=True)
    for draft in pending_drafts.select_related('contract__room')[:3]:
        tasks.append({'icon': 'bi-speedometer2', 'tone': 'amber', 'title': 'Điện nước chưa chốt',
                      'subtitle': f'P.{draft.contract.room.room_number} · tháng {draft.month}/{draft.year}',
            'badge': 'Chờ nhập', 'badge_tone': 'warning',
                      'url': f'{reverse("invoice_drafts")}?month={draft.month}&year={draft.year}'})
    deposit_returns = Contract.objects.filter(status=Contract.Status.KET_THUC).annotate(
        held=Sum(Case(
            When(deposit_entries__kind__in=['receive', 'transfer_in'], then=F('deposit_entries__amount')),
            When(deposit_entries__kind__in=['refund', 'deduct', 'transfer_out', 'pay_invoice'], then=-F('deposit_entries__amount')),
            default=0, output_field=DecimalField(max_digits=14, decimal_places=0)))
    ).filter(held__gt=0).select_related('room').order_by('checkout_date', 'pk')[:3]
    for contract in deposit_returns:
        tasks.append({'icon': 'bi-wallet2', 'tone': 'amber', 'title': 'Cọc còn giữ sau bàn giao',
                      'subtitle': f'{contract.display_code} · P.{contract.room.room_number}',
                      'amount': contract.held, 'badge': 'Chờ quyết toán', 'badge_tone': 'warning',
                      'url': reverse('contract_detail', args=[contract.pk])})
    open_maintenance = MaintenanceRequest.objects.filter(
        status__in=[MaintenanceRequest.Status.DA_GUI, MaintenanceRequest.Status.DANG_XU_LY])
    for item in open_maintenance.filter(status=MaintenanceRequest.Status.DA_GUI).select_related('room', 'tenant')[:3]:
        tasks.append({
            'icon': 'bi-tools', 'tone': 'rose', 'title': 'Yêu cầu sửa chữa mới',
            'subtitle': f'{item.display_code} · P.{item.room.room_number} - {item.tenant.full_name} · {item.title}',
            'badge': item.get_priority_display(),
            'badge_tone': 'danger' if item.priority != MaintenanceRequest.Priority.BINH_THUONG else 'warning',
            'url': reverse('maintenance_detail', args=[item.pk]),
        })
    for days, inv in overdue[:5]:
        tenant = representative_of(inv.contract)
        who = tenant.full_name if tenant else 'chưa có người đại diện'
        tasks.append({
            'icon': 'bi-receipt', 'tone': 'rose',
            'title': 'Hóa đơn quá hạn',
            'subtitle': f'P.{inv.contract.room.room_number} - {who}',
            'badge': f'{days} ngày', 'badge_tone': 'danger',
            'url': reverse('invoice_detail', args=[inv.pk]),
        })

    pending_transfers = PaymentNotice.objects.filter(
        status=PaymentNotice.Status.CHO_XAC_NHAN).select_related('invoice__contract__room', 'tenant')
    for notice in pending_transfers.order_by('created_at', 'pk')[:5]:
        tasks.append({
            'icon': 'bi-bank', 'tone': 'amber', 'title': 'Chuyển khoản chờ xác nhận',
            'subtitle': f'P.{notice.invoice.contract.room.room_number} - {notice.tenant.full_name}',
            'amount': notice.amount, 'badge': 'Chờ xác nhận', 'badge_tone': 'warning',
            'url': reverse('invoice_detail', args=[notice.invoice_id]),
        })

    pending = ViewingAppointment.objects.filter(
        status=ViewingAppointment.Status.CHO_XAC_NHAN).select_related('room').order_by('appointment_date')[:3]
    for a in pending:
        tasks.append({
            'icon': 'bi-calendar-check', 'tone': 'lavender',
            'title': 'Lịch hẹn xem phòng mới',
            'subtitle': f'P.{a.room.room_number} - {a.visitor_name}',
            'badge': f'{a.appointment_date:%d/%m}', 'badge_tone': 'warning',
            'url': reverse('appointment_detail', args=[a.pk]),
        })
        
    expiring = (
        Contract.objects.filter(
            status=Contract.Status.HIEU_LUC,
            end_date__lte=today + timedelta(days=30),
        )
        .select_related('room')
        .prefetch_related('contract_tenants__tenant')
        .order_by('end_date')[:5]
    )
    for c in expiring:
        days = (c.end_date - today).days
        tenant = representative_of(c)
        who = tenant.full_name if tenant else 'chưa có người đại diện'
        tasks.append({
            'icon': 'bi-file-earmark-text', 'tone': 'sky',
            'title': 'Hợp đồng sắp hết hạn' if days >= 0 else 'Hợp đồng đã hết hạn',
            'subtitle': f'P.{c.room.room_number} - {who}',
            'badge': f'Còn {days} ngày' if days >= 0 else f'Quá {-days} ngày',
            'badge_tone': 'warning' if days >= 0 else 'danger',
            'url': reverse('contract_detail', args=[c.pk]),
        })

    # Một số phòng tiêu biểu
    active = Contract.objects.filter(
        status=Contract.Status.HIEU_LUC
    ).prefetch_related('contract_tenants__tenant')
    room_qs = Room.objects.order_by('room_number').prefetch_related(
        Prefetch('contracts', queryset=active, to_attr='active_contracts')
    )[:6]
    preview = []
    for room in room_qs:
        contract = room.active_contracts[0] if room.active_contracts else None
        label, tone = room_status_ui(room)
        preview.append({
            'room': room, 'label': label, 'tone': tone, 'contract': contract,
            'tenant': representative_of(contract) if contract else None,
        })

    return render(request, 'reports/overview.html', {
        'today': today,
        'rooms_total': rooms_total,
        'maintenance_count': open_maintenance.count(),
        'rooms_empty': rooms_empty,
        'month_unpaid': month_unpaid,
        'overdue_count': len(overdue),
        'tasks': tasks,
        'preview': preview,
    })

@owner_required
@never_cache
@require_GET
def dashboard(request):
    return render(request, 'reports/dashboard.html', _dashboard_context(request))


def _dashboard_context(request):
    from .services import build_report, report_period
    period, error = report_period(request.GET)
    return {**build_report(period), 'filter_error': error}


def _csv_cell(value):
    text = str(value or '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


@owner_required
@never_cache
@require_GET
def cashbook_csv(request):
    from .services import cashbook_rows, report_period
    try:
        period, _ = report_period(request.GET, strict=True)
    except ValueError as exc:
        return HttpResponse(str(exc), status=400)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="so-thu-coc-{period.year}-{period.month:02d}.csv"'
    response['Cache-Control'] = 'private, no-store'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Ngày', 'Nhóm', 'Nội dung', 'Hợp đồng', 'Phòng', 'Số tiền (đ)',
                     'Thu tiền mới (đ)', 'Chi tiền thực tế (đ)', 'Biến động nội bộ (đ)', 'Hình thức', 'Ghi chú'])
    for row in cashbook_rows(period):
        writer.writerow([row['date'].isoformat(), row['group'], _csv_cell(row['code']), row['contract'].display_code,
            _csv_cell(row['room']), int(row['amount']), int(row['cash_in']), int(row['cash_out']),
            int(row['internal']), row['method'], _csv_cell(row['note'])])
    return response


@owner_required
@never_cache
@require_GET
def dashboard_excel(request):
    from .exports import report_excel
    from .services import build_report, report_period
    try:
        period, _ = report_period(request.GET, strict=True)
    except ValueError as exc:
        return HttpResponse(str(exc), status=400)
    return report_excel(build_report(period))
