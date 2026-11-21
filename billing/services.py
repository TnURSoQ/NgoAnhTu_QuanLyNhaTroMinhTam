import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from accounts.permissions import is_owner
from accounts.money import MAX_MONEY, whole_dong
from accounts.text import normalize
from rooms.display import representative_of
from rooms.models import Contract, Room
from .models import (BankAccount, Invoice, InvoiceDraft, InvoiceService, Payment, PaymentNotice, Service,
                     UtilityRate, UtilityReading)

DUE_DAYS = 10
MAX_FEE = MAX_MONEY


def _money(value, label, positive=False):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value < 0 or value > MAX_FEE:
            raise ValueError
        if positive and value <= 0:
            raise ValueError
        if value != value.to_integral_value():
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError([f'{label} phải {"lớn hơn 0" if positive else "không âm"}, '
                               'không vượt 99.999.999 đ và là số nguyên đồng.'])
    return whole_dong(value)


def _period(month, year):
    try:
        m, y = int(month), int(year)
        if str(month) != str(m) or str(year) != str(y) or not (1 <= m <= 12 and 2000 <= y <= 2100):
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError(['Tháng/năm không hợp lệ (tháng 1–12, năm 2000–2100).'])
    return m, y


def available_rooms(month, year):
    first, last = period_dates(month, year)
    billed = Contract.objects.filter(status=Contract.Status.HIEU_LUC, invoices__month=month,
                                     invoices__year=year).values_list('room_id', flat=True)
    return Room.objects.filter(contracts__status=Contract.Status.HIEU_LUC,
                                contracts__start_date__lte=last, contracts__end_date__gte=first).exclude(
        pk__in=billed).distinct().order_by('room_number')


def period_dates(month, year):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def validate_contract_period(contract, month, year):
    if contract.status == Contract.Status.KET_THUC and not contract.checkout_date:
        raise ValidationError(['Hợp đồng đã kết thúc nhưng chưa có ngày bàn giao để đối chiếu kỳ hóa đơn.'])
    first, last = period_dates(month, year)
    end = contract.checkout_date if contract.status == Contract.Status.KET_THUC else contract.end_date
    if contract.start_date > last or end < first:
        raise ValidationError(['Kỳ hóa đơn phải nằm trong thời gian thuê thực tế của hợp đồng.'])


def room_contract(room_id, month, year):
    first, last = period_dates(month, year)
    return Contract.objects.filter(room_id=room_id, status=Contract.Status.HIEU_LUC,
                                    start_date__lte=last, end_date__gte=first).first()


def billable_services(contract):
    return Service.objects.all() if contract.use_default_services else contract.services.all()


def default_room_fee(contract, month, year):
    rent = contract.agreed_rent
    if contract.prorate_first_month and (contract.start_date.year, contract.start_date.month) == (year, month):
        _, last = period_dates(month, year)
        rent = whole_dong(rent * (last.day - contract.start_date.day + 1) / last.day)
    return rent


def previous_utility_reading(room_id, month, year, contract=None):
    """Chỉ số cuối kỳ trước của chính phòng này, kể cả qua tháng 12/tháng 1."""
    contract = contract or room_contract(room_id, month, year)
    readings = UtilityReading.objects.filter(room_id=room_id)
    if contract:
        legacy = Q(contract__isnull=True, invoices__isnull=True)
        if contract.initial_electric is not None and contract.initial_water is not None:
            legacy &= Q(year__gt=contract.start_date.year) | Q(year=contract.start_date.year, month__gte=contract.start_date.month)
        readings = readings.filter(Q(contract=contract) | legacy)
    return readings.filter(
        Q(year__lt=year) | Q(year=year, month__lt=month)
    ).order_by('-year', '-month').first()


def utility_baseline(room_id, month, year, contract=None):
    contract = contract or room_contract(room_id, month, year)
    previous = previous_utility_reading(room_id, month, year, contract)
    if previous:
        return previous.new_electric, previous.new_water, f'reading:{previous.pk}:{previous.new_electric}:{previous.new_water}'
    if contract and contract.initial_electric is not None and contract.initial_water is not None:
        return contract.initial_electric, contract.initial_water, f'handover:{contract.pk}:{contract.initial_electric}:{contract.initial_water}'
    return None, None, ''


def _set_previous_reading(reading):
    electric, water, token = utility_baseline(reading.room_id, reading.month, reading.year, reading.contract)
    if token:
        reading.old_electric, reading.old_water = electric, water
    return bool(token)


def _store_reading(reading):
    existing = UtilityReading.objects.filter(contract=reading.contract, month=reading.month,
                                              year=reading.year).first()
    if existing is None:
        existing = UtilityReading.objects.filter(room_id=reading.room_id, month=reading.month,
                                                  year=reading.year, contract__isnull=True,
                                                  invoices__isnull=True).first()
    if existing:
        for name in ('contract', 'room', 'old_electric', 'new_electric', 'old_water', 'new_water'):
            setattr(existing, name, getattr(reading, name))
        reading = existing
    reading.full_clean()
    reading.save()
    return reading


def _make_invoice(reading, *, room_fee=None, due_date=None, note='', service_items=None,
                  contract=None, unit_prices=None):
    if contract is None:
        contract = room_contract(reading.room_id, reading.month, reading.year)
    if not contract or contract.room_id != reading.room_id:
        raise ValidationError(['Phòng này không có hợp đồng còn hiệu lực.'])
    validate_contract_period(contract, reading.month, reading.year)
    if reading.contract_id and reading.contract_id != contract.pk:
        raise ValidationError(['Chỉ số điện nước không thuộc hợp đồng này.'])
    if Invoice.objects.filter(contract=contract, month=reading.month, year=reading.year).exists():
        raise ValidationError([f'Đã có hóa đơn tháng {reading.month}/{reading.year} cho hợp đồng này.'])
    if unit_prices is None:
        rate = UtilityRate.current()
        if not rate:
            raise ValidationError(['Chưa cấu hình đơn giá điện nước.'])
        unit_prices = (rate.electric_price, rate.water_price)
    electric_price = _money(unit_prices[0], 'Đơn giá điện', positive=True)
    water_price = _money(unit_prices[1], 'Đơn giá nước', positive=True)
    electric_fee = _money(whole_dong(reading.electric_usage() * electric_price), 'Tiền điện')
    water_fee = _money(whole_dong(reading.water_usage() * water_price), 'Tiền nước')
    room_fee = _money(default_room_fee(contract, reading.month, reading.year) if room_fee is None else room_fee, 'Tiền phòng')
    invoice = Invoice(
        contract=contract, utility_reading=reading, month=reading.month, year=reading.year,
        room_fee=room_fee, electric_fee=electric_fee, water_fee=water_fee,
        electric_unit_price=electric_price, water_unit_price=water_price,
        total_amount=0, due_date=due_date or timezone.localdate() + timedelta(days=DUE_DAYS), note=note)
    invoice.full_clean()
    invoice.save()
    if service_items is None:
        service_items = [{'service': s, 'quantity': 1} for s in billable_services(contract)]
    total = room_fee + electric_fee + water_fee
    for item in service_items:
        service = item.get('service')
        if service is not None:
            service = Service.objects.filter(pk=getattr(service, 'pk', service)).first()
            if service is None:
                raise ValidationError(['Dịch vụ đã chọn không còn tồn tại.'])
        quantity = item.get('quantity', 1)
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 2147483647:
            raise ValidationError(['Số lượng dịch vụ phải là số nguyên dương hợp lệ.'])
        description = str(item.get('description') or (service.name if service else '')).strip()
        if not description or len(description) > 255:
            raise ValidationError(['Mô tả khoản thu phải có từ 1 đến 255 ký tự.'])
        price = item.get('unit_price')
        if price is None and service:
            price = service.unit_price
        price = _money(price, 'Đơn giá khoản thu')
        subtotal = _money(price * quantity, 'Thành tiền khoản thu')
        line = InvoiceService(invoice=invoice, service=service, description=description,
                              quantity=quantity, unit_price=price, subtotal=subtotal)
        line.full_clean()
        line.save()
        total += subtotal
    invoice.total_amount = _money(total, 'Tổng hóa đơn')
    invoice.save(update_fields=['total_amount'])
    invoice.update_status()
    InvoiceDraft.objects.filter(contract=contract, month=reading.month, year=reading.year,
                                invoice__isnull=True).update(invoice=invoice)
    return invoice


@transaction.atomic
def create_invoice_from_reading(reading):
    """Giữ luồng lập hóa đơn trong quản trị, cùng quy tắc lưu đơn giá."""
    Room.objects.select_for_update().get(pk=reading.room_id)
    _period(reading.month, reading.year)
    if not reading.contract_id:
        reading.contract = room_contract(reading.room_id, reading.month, reading.year)
    if not reading.contract:
        raise ValidationError(['Kỳ hóa đơn phải nằm trong thời gian thuê của hợp đồng còn hiệu lực.'])
    _set_previous_reading(reading)
    reading.full_clean()
    reading.save(update_fields=['old_electric', 'old_water', 'contract'])
    return _make_invoice(reading, contract=reading.contract)


@transaction.atomic
def create_invoice(*, room, month, year, new_electric, new_water, old_electric=None, old_water=None,
                   room_fee=None, due_date=None, note='', service_items=None):
    month, year = _period(month, year)
    room = Room.objects.select_for_update().get(pk=room.pk)
    contract = room_contract(room.pk, month, year)
    if not contract:
        raise ValidationError(['Phòng không có hợp đồng còn hiệu lực trong kỳ hóa đơn đã chọn.'])
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    reading = UtilityReading(room=room, contract=contract, month=month, year=year, old_electric=old_electric,
                             new_electric=new_electric, old_water=old_water, new_water=new_water)
    _set_previous_reading(reading)
    reading.clean_fields()
    reading.clean()
    if Invoice.objects.filter(contract=contract, month=month, year=year).exists():
        raise ValidationError(['Đã có hóa đơn sử dụng chỉ số của phòng trong tháng này.'])
    reading = _store_reading(reading)
    try:
        with transaction.atomic():
            return _make_invoice(reading, contract=contract, room_fee=room_fee, due_date=due_date,
                                 note=note, service_items=service_items)
    except IntegrityError:
        raise ValidationError(['Hóa đơn tháng này hoặc dịch vụ đã tồn tại. Vui lòng kiểm tra lại.'])


@transaction.atomic
def record_payment(invoice, *, amount, paid_date=None, method=Payment.Method.TIEN_MAT, note=''):
    if method not in (Payment.Method.TIEN_MAT, Payment.Method.CHUYEN_KHOAN):
        raise ValidationError(['Khoản đối trừ cọc phải được ghi nhận qua chức năng đối trừ cọc.'])
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    payment = Payment(invoice=invoice, amount=_money(amount, 'Số tiền thanh toán', positive=True),
                      paid_date=paid_date or timezone.localdate(), method=method, note=note)
    payment.full_clean()
    payment.save()
    return payment


@transaction.atomic
def delete_payment(payment):
    if payment.method == Payment.Method.TU_COC:
        raise ValidationError(['Khoản đối trừ đang liên kết với sổ cọc, không được xóa độc lập.'])
    Invoice.objects.select_for_update().get(pk=payment.invoice_id)
    payment.delete()


@transaction.atomic
def delete_invoice(invoice):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.payments.exists():
        raise ValidationError(['Không thể xóa hóa đơn đã có khoản thanh toán.'])
    reading_id = invoice.utility_reading_id
    invoice.delete()
    if reading_id:
        UtilityReading.objects.filter(pk=reading_id, invoices__isnull=True).delete()


@transaction.atomic
def add_utility_rate(*, electric_price, water_price, effective_date):
    rate = UtilityRate(electric_price=_money(electric_price, 'Giá điện', positive=True),
                       water_price=_money(water_price, 'Giá nước', positive=True),
                       effective_date=effective_date)
    rate.full_clean()
    rate.save()
    return rate


@transaction.atomic
def save_service(*, name, unit_price, service=None):
    service = Service.objects.select_for_update().get(pk=service.pk) if service else Service()
    service.name = name.strip()
    if not service.name:
        raise ValidationError(['Vui lòng nhập tên dịch vụ.'])
    service.unit_price = _money(unit_price, 'Giá dịch vụ', positive=True)
    service.full_clean()
    service.save()
    return service


@transaction.atomic
def delete_service(service):
    try:
        service.delete()
    except ProtectedError:
        raise ValidationError(['Không thể xóa dịch vụ đã dùng trong hóa đơn.'])


def transfer_content(invoice):
    representative = representative_of(invoice.contract)
    name = normalize(representative.full_name).upper() if representative else ''
    return ' '.join(f'P{invoice.contract.room.room_number} {name} T{invoice.month}.{invoice.year}'.split())


@transaction.atomic
def configure_bank_account(*, bank_name, account_number, account_holder):
    account, _ = BankAccount.objects.update_or_create(pk=1, defaults={
        'bank_name': bank_name.strip(), 'account_number': account_number.strip(),
        'account_holder': account_holder.strip()})
    account.full_clean()
    return account


@transaction.atomic
def report_payment(invoice, tenant, *, amount=None, note=''):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not invoice.contract.contract_tenants.filter(tenant=tenant).exists():
        raise ValidationError(['Bạn chỉ được báo chuyển khoản cho hóa đơn của mình.'])
    if invoice.total_paid() >= invoice.total_amount:
        raise ValidationError(['Hóa đơn đã thu đủ, không thể báo chuyển khoản.'])
    if invoice.payment_notices.filter(status=PaymentNotice.Status.CHO_XAC_NHAN).exists():
        raise ValidationError(['Hóa đơn đang có thông báo chờ chủ trọ xác nhận.'])
    notice = PaymentNotice(invoice=invoice, tenant=tenant, note=note,
                           amount=_money(amount, 'Số tiền đã chuyển', positive=True) if amount is not None else None)
    notice.full_clean()
    try:
        with transaction.atomic():
            notice.save()
    except IntegrityError:
        raise ValidationError(['Hóa đơn đang có thông báo chờ chủ trọ xác nhận.'])
    return notice


def _pending_notice_for_owner(notice, owner):
    if not is_owner(owner):
        raise ValidationError(['Chỉ chủ trọ mới được xử lý báo chuyển khoản.'])
    # Cùng thứ tự khóa với các thao tác thu tiền: hóa đơn trước, thông báo sau.
    Invoice.objects.select_for_update().get(pk=notice.invoice_id)
    notice = PaymentNotice.objects.select_for_update().get(pk=notice.pk)
    if notice.status != PaymentNotice.Status.CHO_XAC_NHAN:
        raise ValidationError(['Thông báo này đã được xử lý.'])
    return notice


@transaction.atomic
def confirm_payment_notice(notice, *, processed_by, amount, paid_date=None, note=''):
    notice = _pending_notice_for_owner(notice, processed_by)
    payment = record_payment(notice.invoice, amount=amount, paid_date=paid_date,
                             method=Payment.Method.CHUYEN_KHOAN, note=note)
    notice.payment = payment
    notice.status = PaymentNotice.Status.DA_XAC_NHAN
    notice.processed_by = processed_by
    notice.processed_at = timezone.now()
    notice.full_clean()
    notice.save(update_fields=['payment', 'status', 'processed_by', 'processed_at'])
    return notice


@transaction.atomic
def reject_payment_notice(notice, *, processed_by, reject_reason):
    notice = _pending_notice_for_owner(notice, processed_by)
    reason = (reject_reason or '').strip()
    if not reason:
        raise ValidationError(['Vui lòng nhập lý do từ chối.'])
    notice.status = PaymentNotice.Status.TU_CHOI
    notice.reject_reason = reason
    notice.processed_by = processed_by
    notice.processed_at = timezone.now()
    notice.full_clean()
    notice.save(update_fields=['status', 'reject_reason', 'processed_by', 'processed_at'])
    return notice
