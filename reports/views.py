from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import owner_required
from billing.models import Invoice, Payment
from rooms.models import Room


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