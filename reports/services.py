"""Read-only reports: invoice periods, actual collections and current balances."""
import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from billing.models import Invoice, InvoiceDraft, Payment
from rooms.display import representative_of, room_status_ui
from rooms.models import Contract, DepositEntry, Room
from support.models import MaintenanceRequest


@dataclass(frozen=True)
class ReportPeriod:
    year: int
    month: int = 0

    @property
    def first(self):
        return date(self.year, self.month or 1, 1)

    @property
    def last(self):
        month = self.month or 12
        return date(self.year, month, calendar.monthrange(self.year, month)[1])

    @property
    def label(self):
        return f'tháng {self.month}/{self.year}' if self.month else f'năm {self.year}'

    @property
    def query(self):
        return urlencode({'year': self.year, 'month': self.month})


def report_period(params, *, strict=False):
    today = timezone.localdate()
    error = ''
    try:
        year = int(params.get('year', today.year))
        month = int(params.get('month') or 0)
        if not 2000 <= year <= 2100 or not 0 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        if strict:
            raise ValueError('Kỳ báo cáo không hợp lệ. Chọn năm 2000–2100 và tháng 1–12 hoặc cả năm.')
        year, month = today.year, 0
        error = 'Kỳ báo cáo không hợp lệ. Đang hiển thị cả năm hiện tại; vui lòng chọn lại.'
    return ReportPeriod(year, month), error


def cashbook_rows(period):
    """Cash is counted once; linked offsets retain both sides of the internal ledger."""
    rows = []
    payments = Payment.objects.filter(paid_date__range=(period.first, period.last)).select_related('invoice__contract__room')
    for payment in payments:
        contract = payment.invoice.contract
        internal = payment.method == Payment.Method.TU_COC
        note = payment.note
        if payment.is_voided:
            note = (f'Số tiền gốc {payment.amount}; hủy lúc {timezone.localtime(payment.voided_at):%d/%m/%Y %H:%M}; '
                    f'lý do: {payment.void_reason}')
        rows.append({'date': payment.paid_date, 'group': 'Khoản thu đã hủy (không cộng tiền)' if payment.is_voided else
                     'Đối trừ cọc vào hóa đơn' if internal else 'Thực thu hóa đơn',
                     'code': payment.display_code, 'contract': contract, 'room': contract.room.room_number,
                     'amount': 0 if payment.is_voided else payment.amount,
                     'cash_in': 0 if payment.is_voided or internal else payment.amount,
                     'cash_out': 0, 'internal': payment.amount if internal and not payment.is_voided else 0,
                     'method': payment.get_method_display(), 'note': note, 'sort': (0, payment.pk)})
    entries = DepositEntry.objects.filter(occurred_on__range=(period.first, period.last)).select_related('contract__room')
    for entry in entries:
        internal = (entry.amount if entry.kind == DepositEntry.Kind.TRANSFER_IN else -entry.amount
                    if entry.kind in (DepositEntry.Kind.TRANSFER_OUT, DepositEntry.Kind.DEDUCT, DepositEntry.Kind.PAY_INVOICE) else 0)
        rows.append({'date': entry.occurred_on, 'group': 'Tiền cọc (tách riêng)',
            'code': f'COC-{entry.pk:06d} · {entry.get_kind_display()}', 'contract': entry.contract,
            'room': entry.contract.room.room_number, 'amount': entry.amount,
            'cash_in': entry.amount if entry.kind == DepositEntry.Kind.RECEIVE else 0,
            'cash_out': entry.amount if entry.kind == DepositEntry.Kind.REFUND else 0,
            'internal': internal, 'method': entry.get_method_display(), 'note': entry.note, 'sort': (1, entry.pk),
            'linked_offset_ledger': entry.kind == DepositEntry.Kind.PAY_INVOICE})
    return sorted(rows, key=lambda row: (row['date'], row['sort']))


def build_report(period):
    today = timezone.localdate()
    payments = list(Payment.objects.active().filter(paid_date__range=(period.first, period.last)))
    months = []
    for month in ([period.month] if period.month else range(1, 13)):
        group = [p for p in payments if p.paid_date.month == month]
        cash = sum(p.amount for p in group if p.method == Payment.Method.TIEN_MAT)
        bank = sum(p.amount for p in group if p.method == Payment.Method.CHUYEN_KHOAN)
        offset = sum(p.amount for p in group if p.method == Payment.Method.TU_COC)
        months.append({'month': month, 'cash': cash, 'bank': bank, 'deposit': offset,
                       'cash_received': cash + bank, 'total': cash + bank + offset})
    peak = max((m['cash_received'] for m in months), default=0)
    for month in months:
        month['pct'] = int(month['cash_received'] * 100 / peak) if peak else 0
    cash_received = sum(m['cash_received'] for m in months)
    deposit_applied = sum(m['deposit'] for m in months)

    # Derive balances from payments, never from cached invoice.status and never by writing on GET.
    invoices = list(Invoice.objects.select_related('contract__room').prefetch_related(
        Prefetch('payments', queryset=Payment.objects.active(), to_attr='report_payments'),
        'contract__contract_tenants__tenant').order_by('due_date', 'pk'))
    debts, issued = [], []
    contract_debts = defaultdict(int)
    aging = [{'label': 'Chưa quá hạn', 'amount': 0, 'count': 0},
             {'label': 'Quá hạn 1–7 ngày', 'amount': 0, 'count': 0},
             {'label': 'Quá hạn 8–30 ngày', 'amount': 0, 'count': 0},
             {'label': 'Quá hạn 31–60 ngày', 'amount': 0, 'count': 0},
             {'label': 'Quá hạn trên 60 ngày', 'amount': 0, 'count': 0}]
    for invoice in invoices:
        paid = sum(p.amount for p in invoice.report_payments)
        remaining = max(invoice.total_amount - paid, 0)
        days = max((today - invoice.due_date).days, 0)
        row = {'invoice': invoice, 'tenant': representative_of(invoice.contract), 'paid': paid,
               'remaining': remaining, 'overdue_days': days,
               'other_fee': invoice.total_amount - invoice.room_fee - invoice.electric_fee - invoice.water_fee}
        if invoice.year == period.year and (not period.month or invoice.month == period.month):
            issued.append(row)
        if remaining:
            debts.append(row)
            contract_debts[invoice.contract_id] += remaining
            bucket = aging[0 if days == 0 else 1 if days <= 7 else 2 if days <= 30 else 3 if days <= 60 else 4]
            bucket['amount'] += remaining
            bucket['count'] += 1
    issued.sort(key=lambda r: (r['invoice'].year, r['invoice'].month, r['invoice'].contract.room.room_number, r['invoice'].pk))

    drafts = InvoiceDraft.objects.filter(invoice__isnull=True)
    draft_counts = dict(drafts.values_list('contract_id').annotate(n=Count('pk')))
    period_drafts = drafts.filter(year=period.year)
    if period.month:
        period_drafts = period_drafts.filter(month=period.month)

    entries = list(DepositEntry.objects.all())
    plus = (DepositEntry.Kind.RECEIVE, DepositEntry.Kind.TRANSFER_IN)
    def balance(items):
        return sum(e.amount if e.kind in plus else -e.amount for e in items)
    deposit_period = {kind: sum(e.amount for e in entries if e.kind == kind and period.first <= e.occurred_on <= period.last)
                      for kind in DepositEntry.Kind.values}
    deposit_period['opening'] = balance(e for e in entries if e.occurred_on < period.first)
    deposit_period['closing'] = balance(e for e in entries if e.occurred_on <= period.last)
    balances = defaultdict(int)
    for entry in entries:
        balances[entry.contract_id] += entry.amount if entry.kind in plus else -entry.amount
    contracts = list(Contract.objects.select_related('room').prefetch_related('contract_tenants__tenant').order_by('room__room_number', 'pk'))
    deposit_contracts, expiring = [], []
    for contract in contracts:
        held = balances[contract.pk]
        active = contract.status == Contract.Status.HIEU_LUC
        shortfall = max(contract.agreed_deposit - held, 0) if active else 0
        if held or shortfall:
            deposit_contracts.append({'contract': contract, 'tenant': representative_of(contract),
                'held': held, 'shortfall': shortfall, 'debt': contract_debts[contract.pk],
                'drafts': draft_counts.get(contract.pk, 0)})
        if active and contract.end_date <= today + timedelta(days=30):
            expiring.append({'contract': contract, 'tenant': representative_of(contract),
                             'days': (contract.end_date - today).days})
    expiring.sort(key=lambda r: (r['contract'].end_date, r['contract'].pk))
    active_by_room = {c.room_id: c for c in contracts if c.status == Contract.Status.HIEU_LUC}
    rooms = list(Room.objects.order_by('floor', 'room_number'))
    room_stats = {'total': len(rooms), 'dang_thue': 0, 'trong': 0, 'bao_tri': 0}
    room_rows, people = [], set()
    for room in rooms:
        room_stats[room.status] = room_stats.get(room.status, 0) + 1
        contract = active_by_room.get(room.pk)
        members = list(contract.contract_tenants.all()) if contract else []
        people.update(member.tenant_id for member in members)
        label, tone = room_status_ui(room)
        room_rows.append({'room': room, 'contract': contract, 'tenant': representative_of(contract) if contract else None,
                          'people': len(members), 'label': label, 'tone': tone,
                          'rent': contract.agreed_rent if contract else room.price})
    room_stats['pct_trong'] = round(room_stats['trong'] * 100 / len(rooms), 1) if rooms else 0
    room_stats['pct_occupied'] = round(room_stats['dang_thue'] * 100 / len(rooms), 1) if rooms else 0

    repairs = list(MaintenanceRequest.objects.filter(
        Q(created_at__date__range=(period.first, period.last)) |
        Q(status=MaintenanceRequest.Status.HOAN_THANH, resolved_at__date__range=(period.first, period.last)) |
        Q(status__in=['da_gui', 'dang_xu_ly'])).select_related('room', 'tenant'))
    created_repairs = []
    completed = pending = 0
    for repair in repairs:
        created = period.first <= timezone.localtime(repair.created_at).date() <= period.last
        resolved = (repair.status == MaintenanceRequest.Status.HOAN_THANH and repair.resolved_at
                    and period.first <= timezone.localtime(repair.resolved_at).date() <= period.last)
        if created:
            created_repairs.append(repair)
        completed += bool(resolved)
        pending += repair.status in ('da_gui', 'dang_xu_ly')
        repair.report_scope = 'Gửi trong kỳ' if created else 'Hoàn thành trong kỳ' if resolved else 'Tồn đọng hiện tại'
    repair_stats = {status: sum(r.status == status for r in created_repairs) for status in MaintenanceRequest.Status.values}
    repair_stats.update(total=len(created_repairs), completed_in_period=completed, current_pending=pending)
    cashbook = cashbook_rows(period)
    years = set(Payment.objects.values_list('paid_date__year', flat=True))
    years.update(Invoice.objects.values_list('year', flat=True))
    years.update(DepositEntry.objects.values_list('occurred_on__year', flat=True))
    years.update(MaintenanceRequest.objects.values_list('created_at__year', flat=True))
    years.update(MaintenanceRequest.objects.filter(resolved_at__isnull=False).values_list('resolved_at__year', flat=True))
    return {'period': period, 'year': period.year, 'years': sorted(years | {today.year, period.year}, reverse=True),
        'today': today, 'month_choices': range(1, 13), 'months': months, 'year_total': cash_received + deposit_applied,
        'cash_received': cash_received, 'cash_collected': sum(m['cash'] for m in months),
        'bank_collected': sum(m['bank'] for m in months), 'deposit_applied': deposit_applied,
        'issued': issued, 'invoice_count': len(issued), 'invoice_total': sum(r['invoice'].total_amount for r in issued),
        'invoice_room': sum(r['invoice'].room_fee for r in issued), 'invoice_electric': sum(r['invoice'].electric_fee for r in issued),
        'invoice_water': sum(r['invoice'].water_fee for r in issued), 'invoice_other': sum(r['other_fee'] for r in issued),
        'invoice_paid': sum(r['paid'] for r in issued), 'invoice_remaining': sum(r['remaining'] for r in issued),
        'period_draft_count': period_drafts.count(), 'debts': debts, 'total_debt': sum(r['remaining'] for r in debts),
        'overdue_count': sum(r['overdue_days'] > 0 for r in debts),
        'overdue_debt': sum(r['remaining'] for r in debts if r['overdue_days'] > 0), 'aging': aging,
        'ended_debt': sum(r['remaining'] for r in debts if r['invoice'].contract.status == Contract.Status.KET_THUC),
        'deposit_held': sum(balances.values()), 'deposit_period': deposit_period, 'deposit_contracts': deposit_contracts,
        'deposit_shortfall': sum(r['shortfall'] for r in deposit_contracts),
        'deposit_ended': sum(r['held'] for r in deposit_contracts if r['contract'].status == Contract.Status.KET_THUC),
        'room_stats': room_stats, 'room_rows': room_rows, 'people_count': len(people), 'expiring': expiring,
        'repair_stats': repair_stats, 'repairs': repairs, 'cashbook': cashbook,
        'cashbook_preview': list(reversed([r for r in cashbook if not r.get('linked_offset_ledger')][-50:])),
        'cash_in': sum(row['cash_in'] for row in cashbook), 'cash_out': sum(row['cash_out'] for row in cashbook)}
