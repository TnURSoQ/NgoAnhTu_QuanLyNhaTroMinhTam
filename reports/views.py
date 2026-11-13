from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Prefetch, Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import owner_required
from billing.models import Invoice, Payment
from rooms.display import representative_of, room_status_ui
from rooms.models import Contract, Room

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
    for days, inv in overdue[:5]:
        tenant = representative_of(inv.contract)
        who = tenant.full_name if tenant else 'chưa có người đại diện'
        tasks.append({
            'icon': 'bi-receipt', 'tone': 'rose',
            'title': 'Hóa đơn quá hạn',
            'subtitle': f'P.{inv.contract.room.room_number} - {who}',
            'badge': f'{days} ngày', 'badge_tone': 'danger',
            'url': reverse('report_dashboard'),
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
        'rooms_empty': rooms_empty,
        'month_unpaid': month_unpaid,
        'overdue_count': len(overdue),
        'tasks': tasks,
        'preview': preview,
    })

@owner_required
def dashboard(request):
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

    return render(request, 'reports/dashboard.html', {
        'room_stats': room_stats,
        'year': year,
        'years': years,
        'months': months,
        'year_total': year_total,
        'debts': debts,
        'total_debt': total_debt,
        'overdue_count': sum(1 for d in debts if d['overdue_days'] > 0),
    })