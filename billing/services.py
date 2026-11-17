from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from accounts.permissions import is_owner
from accounts.money import MAX_MONEY, whole_dong
from accounts.text import normalize
from rooms.display import representative_of
from rooms.models import Contract, Room
from .models import (BankAccount, Invoice, InvoiceService, Payment, PaymentNotice, Service,
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
    billed = Invoice.objects.filter(month=month, year=year).values_list('contract__room_id', flat=True)
    return Room.objects.filter(contracts__status=Contract.Status.HIEU_LUC).exclude(
        pk__in=billed).distinct().order_by('room_number')


def _make_invoice(reading, *, room_fee=None, due_date=None, note='', service_items=None):
    contract = Contract.objects.select_for_update().filter(
        room=reading.room, status=Contract.Status.HIEU_LUC).first()
    if not contract:
        raise ValidationError(['Phòng này không có hợp đồng còn hiệu lực.'])
    if Invoice.objects.filter(contract=contract, month=reading.month, year=reading.year).exists():
        raise ValidationError([f'Đã có hóa đơn tháng {reading.month}/{reading.year} cho hợp đồng này.'])
    rate = UtilityRate.current()
    if not rate:
        raise ValidationError(['Chưa cấu hình đơn giá điện nước.'])
    electric_price = _money(rate.electric_price, 'Đơn giá điện', positive=True)
    water_price = _money(rate.water_price, 'Đơn giá nước', positive=True)
    electric_fee = _money(whole_dong(reading.electric_usage() * electric_price), 'Tiền điện')
    water_fee = _money(whole_dong(reading.water_usage() * water_price), 'Tiền nước')
    room_fee = _money(reading.room.price if room_fee is None else room_fee, 'Tiền phòng')
    invoice = Invoice(
        contract=contract, utility_reading=reading, month=reading.month, year=reading.year,
        room_fee=room_fee, electric_fee=electric_fee, water_fee=water_fee,
        electric_unit_price=electric_price, water_unit_price=water_price,
        total_amount=0, due_date=due_date or timezone.localdate() + timedelta(days=DUE_DAYS), note=note)
    invoice.full_clean()
    invoice.save()
    if service_items is None:
        service_items = [{'service': s, 'quantity': 1} for s in Service.objects.all()]
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
    return invoice


@transaction.atomic
def create_invoice_from_reading(reading):
    """Giữ luồng lập hóa đơn trong quản trị, cùng quy tắc lưu đơn giá."""
    Room.objects.select_for_update().get(pk=reading.room_id)
    _period(reading.month, reading.year)
    reading.full_clean()
    return _make_invoice(reading)


@transaction.atomic
def create_invoice(*, room, month, year, old_electric, new_electric, old_water, new_water,
                   room_fee=None, due_date=None, note='', service_items=None):
    month, year = _period(month, year)
    room = Room.objects.select_for_update().get(pk=room.pk)
    reading = UtilityReading(room=room, month=month, year=year, old_electric=old_electric,
                             new_electric=new_electric, old_water=old_water, new_water=new_water)
    reading.clean_fields()
    reading.clean()
    if UtilityReading.objects.filter(room=room, month=month, year=year, invoices__isnull=False).exists():
        raise ValidationError(['Đã có hóa đơn sử dụng chỉ số của phòng trong tháng này.'])
    reading, _ = UtilityReading.objects.update_or_create(
        room=room, month=month, year=year,
        defaults={key: getattr(reading, key) for key in
                  ('old_electric', 'new_electric', 'old_water', 'new_water')})
    try:
        with transaction.atomic():
            return _make_invoice(reading, room_fee=room_fee, due_date=due_date,
                                 note=note, service_items=service_items)
    except IntegrityError:
        raise ValidationError(['Hóa đơn tháng này hoặc dịch vụ đã tồn tại. Vui lòng kiểm tra lại.'])


@transaction.atomic
def record_payment(invoice, *, amount, paid_date=None, method=Payment.Method.TIEN_MAT, note=''):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    payment = Payment(invoice=invoice, amount=_money(amount, 'Số tiền thanh toán', positive=True),
                      paid_date=paid_date or timezone.localdate(), method=method, note=note)
    payment.full_clean()
    payment.save()
    return payment


@transaction.atomic
def delete_payment(payment):
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
