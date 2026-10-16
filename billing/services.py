from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from rooms.models import Contract
from .models import Invoice, InvoiceService, Service, UtilityRate

DUE_DAYS = 10  # hạn thanh toán: 10 ngày kể từ ngày lập hóa đơn
CENT = Decimal('0.01')
MAX_FEE = Decimal('99999999.99')

#Hàm có @transaction.atomic, nên nếu lỗi giữa chừng thì không bị sót hóa đơn dở dang.
#Đây chính là yêu cầu toàn vẹn dữ liệu trong phần phi chức năng.
@transaction.atomic
def create_invoice_from_reading(reading):
    """Lập hóa đơn tháng cho phòng từ một bản ghi chỉ số điện nước."""
    contract = Contract.objects.filter(
        room=reading.room, status=Contract.Status.HIEU_LUC
    ).first()
    if not contract:
        raise ValidationError('Phòng này không có hợp đồng còn hiệu lực.')

    if Invoice.objects.filter(
        contract=contract, month=reading.month, year=reading.year
    ).exists():
        raise ValidationError(
            f'Đã có hóa đơn tháng {reading.month}/{reading.year} cho hợp đồng này.'
        )

    rate = UtilityRate.current()
    if not rate:
        raise ValidationError('Chưa cấu hình đơn giá điện nước.')

    electric_fee = (reading.electric_usage() * rate.electric_price).quantize(CENT)
    water_fee = (reading.water_usage() * rate.water_price).quantize(CENT)
    if electric_fee > MAX_FEE or water_fee > MAX_FEE:
        raise ValidationError(
            'Chỉ số điện/nước bất thường. Chỉ số là số trên đồng hồ, '
            'không phải số tiền, vui lòng kiểm tra lại.'
        )

    invoice = Invoice.objects.create(
        contract=contract,
        utility_reading=reading,
        month=reading.month,
        year=reading.year,
        room_fee=reading.room.price,
        electric_fee=electric_fee,
        water_fee=water_fee,
        total_amount=0,
        due_date=timezone.localdate() + timedelta(days=DUE_DAYS),
    )

    for service in Service.objects.all():
        InvoiceService.objects.create(invoice=invoice, service=service, quantity=1)

    invoice.recalculate_total()
    return invoice