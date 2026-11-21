from datetime import timedelta
from decimal import Decimal
import csv

from django.db.models import Case, Count, DecimalField, F, Prefetch, Sum, When
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import render
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

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
        Invoice.objects.exclude(status=Invoice.Status.DA_THANH_TOAN)
        .select_related('contract__room')
        .prefetch_related('payments', 'contract__contract_tenants__tenant')
    )
    month_unpaid = Decimal('0')
    overdue = []
    for inv in unpaid:
        paid = sum((p.amount for p in inv.payments.all()), Decimal('0'))
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
def dashboard(request):
    return render(request, 'reports/dashboard.html', _dashboard_context(request))


def _dashboard_context(request):
    today = timezone.localdate()

    # 1. Tình trạng phòng
    counts = dict(Room.objects.values_list('status').annotate(n=Count('id')))
    total_rooms = sum(counts.values())
    room_stats = {
        'total': total_rooms,
        'dang_thue': counts.get(Room.Status.DANG_THUE.value, 0),
        'trong': counts.get(Room.Status.TRONG.value, 0),
        'bao_tri': counts.get(Room.Status.BAO_TRI.value, 0),
    }
    room_stats['pct_trong'] = round(room_stats['trong'] * 100 / total_rooms, 1) if total_rooms else 0

    # 2. Doanh thu (tiền thực thu) theo tháng của năm được chọn
    try:
        year = int(request.GET.get('year', today.year))
    except ValueError:
        year = today.year
    if not 2000 <= year <= 2100:
        year = today.year

    rows = (
        Payment.objects.filter(paid_date__year=year)
        .annotate(m=ExtractMonth('paid_date'))
        .values('m')
        .annotate(total=Sum('amount'))
    )
    by_month = {r['m']: r['total'] for r in rows}
    months = []
    year_total = Decimal('0')
    for m in range(1, 13):
        total = by_month.get(m) or Decimal('0')
        year_total += total
        months.append({'month': m, 'total': total})
    peak = max(x['total'] for x in months)
    for x in months:
        x['pct'] = int(x['total'] * 100 / peak) if peak else 0

    pay_years = (
        Payment.objects.annotate(y=ExtractYear('paid_date'))
        .values_list('y', flat=True).distinct()
    )
    years = sorted(set(pay_years) | {today.year, year}, reverse=True)

    # 3. Công nợ: hóa đơn chưa thu đủ
    invoices = (
        Invoice.objects.exclude(status=Invoice.Status.DA_THANH_TOAN)
        .select_related('contract__room')
        .prefetch_related('payments', 'contract__contract_tenants__tenant')
        .order_by('due_date')
    )
    debts = []
    total_debt = Decimal('0')
    for inv in invoices:
        paid = sum((p.amount for p in inv.payments.all()), Decimal('0'))
        remaining = inv.total_amount - paid
        if remaining <= 0:
            continue
        rep = next(
            (ct.tenant for ct in inv.contract.contract_tenants.all() if ct.is_representative),
            None,
        )
        overdue_days = max((today - inv.due_date).days, 0)
        debts.append({
            'invoice': inv, 'tenant': rep, 'paid': paid,
            'remaining': remaining, 'overdue_days': overdue_days,
        })
        total_debt += remaining

    return {
        'room_stats': room_stats,
        'year': year,
        'years': years,
        'months': months,
        'year_total': year_total,
        'debts': debts,
        'total_debt': total_debt,
        'overdue_count': sum(1 for d in debts if d['overdue_days'] > 0),
        'deposit_held': (DepositEntry.objects.filter(kind__in=['receive', 'transfer_in']).aggregate(
            total=Sum('amount'))['total'] or 0) - (DepositEntry.objects.filter(
                kind__in=['refund', 'deduct', 'transfer_out', 'pay_invoice']).aggregate(total=Sum('amount'))['total'] or 0),
        'cash_received': Payment.objects.filter(paid_date__year=year).exclude(method=Payment.Method.TU_COC).aggregate(
            total=Sum('amount'))['total'] or 0,
        'deposit_applied': Payment.objects.filter(paid_date__year=year, method=Payment.Method.TU_COC).aggregate(
            total=Sum('amount'))['total'] or 0,
    }


def _csv_cell(value):
    text = str(value or '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text


@owner_required
def cashbook_csv(request):
    try:
        year = int(request.GET.get('year', timezone.localdate().year))
        if not 2000 <= year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        return HttpResponse('Năm không hợp lệ.', status=400)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="so-thu-coc-{year}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Ngày', 'Nhóm', 'Nội dung', 'Hợp đồng', 'Phòng', 'Số tiền (đ)',
                     'Thu tiền mới (đ)', 'Chi tiền thực tế (đ)', 'Biến động nội bộ (đ)', 'Hình thức', 'Ghi chú'])
    for payment in Payment.objects.filter(paid_date__year=year).select_related('invoice__contract__room').order_by('paid_date', 'pk'):
        internal = payment.method == Payment.Method.TU_COC
        writer.writerow([payment.paid_date.isoformat(), 'Đối trừ cọc vào hóa đơn' if internal else 'Thực thu hóa đơn', f'Phiếu thu #{payment.pk}',
                         payment.invoice.contract.display_code, _csv_cell(payment.invoice.contract.room.room_number),
                         int(payment.amount), 0 if internal else int(payment.amount), 0,
                         int(payment.amount) if internal else 0, payment.get_method_display(), _csv_cell(payment.note)])
    for entry in DepositEntry.objects.filter(occurred_on__year=year).select_related('contract__room').order_by('occurred_on', 'pk'):
        writer.writerow([entry.occurred_on.isoformat(), 'Tiền cọc (tách riêng)', entry.get_kind_display(),
                         entry.contract.display_code, _csv_cell(entry.contract.room.room_number),
                         int(entry.amount), int(entry.amount) if entry.kind == DepositEntry.Kind.RECEIVE else 0,
                         int(entry.amount) if entry.kind == DepositEntry.Kind.REFUND else 0,
                         (int(entry.amount) if entry.kind == DepositEntry.Kind.TRANSFER_IN else -int(entry.amount))
                         if entry.method == DepositEntry.Method.INTERNAL else 0,
                         entry.get_method_display(), _csv_cell(entry.note)])
    return response
