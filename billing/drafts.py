"""Lập nháp theo kỳ, lưu chỉ số và phát hành hóa đơn sau khi chủ trọ kiểm tra."""
import calendar
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.money import whole_dong
from rooms.models import Contract, Room
from .models import Invoice, InvoiceDraft, Service, UtilityRate, UtilityReading
from .services import (DUE_DAYS, _make_invoice, _money, _period, _store_reading, billable_services,
                       default_room_fee, previous_utility_reading, utility_baseline, validate_contract_period)

READING_FIELDS = ('old_electric', 'new_electric', 'old_water', 'new_water')
EDITABLE_FIELDS = (*READING_FIELDS, 'room_fee', 'due_date', 'note')


def previous_reading(draft):
    return previous_utility_reading(draft.contract.room_id, draft.month, draft.year, draft.contract)


def fill_missing_defaults(draft):
    """Nối với kỳ trước mới nhất, kể cả khi kỳ trước được chốt sau lúc tạo nháp."""
    electric, water, baseline = utility_baseline(draft.contract.room_id, draft.month, draft.year, draft.contract)
    if baseline:
        draft.old_electric, draft.old_water = electric, water
    if draft.electric_unit_price is None or draft.water_unit_price is None:
        rate = UtilityRate.current()
        if rate:
            if draft.electric_unit_price is None:
                draft.electric_unit_price = rate.electric_price
            if draft.water_unit_price is None:
                draft.water_unit_price = rate.water_price
    # Phát hiện lịch sử/đơn giá bổ sung đã thay đổi từ lúc chủ trọ mở bảng.
    draft.preview_token = ':'.join(str(value) for value in (
        baseline,
        draft.electric_unit_price, draft.water_unit_price))
    draft.has_previous_reading = bool(baseline)
    return draft


def _period_dates(month, year):
    month, year = _period(month, year)
    today = timezone.localdate()
    if (year, month) > (today.year, today.month):
        raise ValidationError(['Chưa đến kỳ lập hóa đơn của tháng này.'])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


@transaction.atomic
def generate_monthly_drafts(month, year, *, dry_run=False):
    """Chạy lại an toàn; chỉ lấy hợp đồng hiệu lực có thời gian thuê giao với kỳ."""
    first, last = _period_dates(month, year)
    started_by = min(last, timezone.localdate())
    contracts = Contract.objects.filter(
        status=Contract.Status.HIEU_LUC, start_date__lte=started_by, end_date__gte=first
    ).select_related('room').order_by('room_id', 'pk')
    rate = UtilityRate.current()
    created = 0
    for candidate in contracts:
        # Cùng thứ tự khóa với luồng lập hóa đơn thủ công.
        Room.objects.select_for_update().get(pk=candidate.room_id)
        contract = Contract.objects.select_for_update().get(pk=candidate.pk)
        if (contract.status != Contract.Status.HIEU_LUC or contract.start_date > started_by
                or contract.end_date < first):
            continue
        period = {'month': first.month, 'year': first.year, 'contract_id': contract.pk}
        if Invoice.objects.filter(**period).exists() or InvoiceDraft.objects.filter(**period).exists():
            continue
        items = [{'service': s.pk, 'description': s.name, 'quantity': 1,
                  'unit_price': str(_money(s.unit_price, 'Đơn giá dịch vụ'))}
                 for s in billable_services(contract).order_by('pk')]
        draft = InvoiceDraft(contract=contract, month=first.month, year=first.year,
                             room_fee=_money(default_room_fee(contract, first.month, first.year), 'Tiền phòng'), service_items=items,
                             electric_unit_price=rate.electric_price if rate else None,
                             water_unit_price=rate.water_price if rate else None)
        fill_missing_defaults(draft)
        draft.full_clean()
        _money(draft.room_fee + draft.services_total, 'Tổng tiền phòng và dịch vụ')
        if not dry_run:
            draft.save()
        created += 1
    return created


def _validate_draft(draft):
    draft.full_clean()
    _money(draft.room_fee, 'Tiền phòng')
    for name, label in [('electric_unit_price', 'Đơn giá điện'), ('water_unit_price', 'Đơn giá nước')]:
        value = getattr(draft, name)
        if value is not None:
            _money(value, label, positive=True)
    _money(draft.room_fee + draft.services_total, 'Tổng tiền phòng và dịch vụ')
    # Kiểm tra cả khoản đã nhập khi khoản còn lại vẫn đang để trống.
    total = draft.room_fee + draft.services_total
    for utility, label in [('electric', 'điện'), ('water', 'nước')]:
        old, new = getattr(draft, f'old_{utility}'), getattr(draft, f'new_{utility}')
        price = getattr(draft, f'{utility}_unit_price')
        if old is not None and new is not None and price is not None:
            total += _money(whole_dong((new - old) * price), f'Tiền {label}')
    _money(total, 'Tổng hóa đơn')


def _publish_locked(draft):
    if Invoice.objects.filter(contract=draft.contract,
                              month=draft.month, year=draft.year).exists():
        raise ValidationError(['Phòng đã có hóa đơn trong kỳ này. Vui lòng tải lại bảng.'])
    if not draft.is_ready:
        return None
    reading = UtilityReading(room_id=draft.contract.room_id, contract=draft.contract, month=draft.month, year=draft.year,
                             **{name: getattr(draft, name) for name in READING_FIELDS})
    reading.clean_fields()
    reading.clean()
    if UtilityReading.objects.filter(contract=draft.contract, month=reading.month, year=reading.year,
                                     invoices__isnull=False).exists():
        raise ValidationError(['Chỉ số tháng này đã được dùng trong hóa đơn khác.'])
    reading = _store_reading(reading)
    # Dịch vụ có thể đã bị xóa sau khi tạo nháp; giữ nguyên tên và tiền đã lưu.
    service_ids = set(Service.objects.values_list('pk', flat=True))
    items = [{**item, 'service': item.get('service') if item.get('service') in service_ids else None}
             for item in draft.service_items]
    return _make_invoice(
        reading, contract=draft.contract, room_fee=draft.room_fee,
        due_date=draft.due_date or timezone.localdate() + timedelta(days=DUE_DAYS), note=draft.note,
        service_items=items, unit_prices=(draft.electric_unit_price, draft.water_unit_price))


@transaction.atomic
def save_draft_rows(rows, *, month, year, publish=False):
    """Lưu cả bảng hoặc hoàn tác cả bảng; chốt các dòng được chọn đã đủ số."""
    _period_dates(month, year)
    ids = [row['draft'].pk for row in rows]
    if len(ids) != len(set(ids)):
        raise ValidationError(['Bảng có dòng trùng lặp. Vui lòng tải lại.'])
    if publish and not any(row.get('selected') for row in rows):
        raise ValidationError(['Hãy chọn ít nhất một phòng để chốt hóa đơn.'])
    room_ids = sorted(set(InvoiceDraft.objects.filter(pk__in=ids).values_list(
        'contract__room_id', flat=True)))
    list(Room.objects.select_for_update().filter(pk__in=room_ids).order_by('pk'))
    contract_ids = InvoiceDraft.objects.filter(pk__in=ids).values_list('contract_id', flat=True)
    contracts = {c.pk: c for c in Contract.objects.select_for_update().filter(
        pk__in=contract_ids).order_by('pk')}
    drafts = {d.pk: d for d in InvoiceDraft.objects.select_for_update().filter(pk__in=ids)}
    published = skipped = 0
    for row in rows:
        draft = drafts.get(row['draft'].pk)
        if (draft is None or draft.invoice_id or draft.month != month or draft.year != year
                or draft.revision != row['revision']):
            raise ValidationError(['Bảng đã thay đổi ở phiên khác. Hãy tải lại trước khi lưu.'])
        draft.contract = contracts[draft.contract_id]
        validate_contract_period(draft.contract, draft.month, draft.year)
        for name in EDITABLE_FIELDS:
            setattr(draft, name, row[name])
        fill_missing_defaults(draft)
        if draft.preview_token != row['preview_token']:
            raise ValidationError(['Chỉ số kỳ trước hoặc đơn giá đã thay đổi. Hãy tải lại bảng để kiểm tra.'])
        try:
            _validate_draft(draft)
            draft.revision += 1
            draft.save()
            if publish and row.get('selected'):
                if _publish_locked(draft):
                    published += 1
                else:
                    skipped += 1
        except ValidationError as exc:
            raise ValidationError([f'Phòng {draft.contract.room.room_number}: {msg}' for msg in exc.messages])
    return published, skipped
