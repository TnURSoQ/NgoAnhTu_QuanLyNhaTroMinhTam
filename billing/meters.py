"""Electric meters in this property: five whole digits and one tenth of a kWh."""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

ELECTRIC_MAX = Decimal('99999.9')
ELECTRIC_STEP = Decimal('0.1')
ELECTRIC_HELP = 'Công tơ 5 số nguyên và 1 số lẻ. Ví dụ: 1.611 hoặc 1.611,1 kWh; tối đa 99.999,9 kWh.'
ELECTRIC_ERROR = 'Chỉ số điện từ 0 đến 99.999,9 kWh, chỉ được có tối đa 1 chữ số thập phân.'


def electric_reading(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= ELECTRIC_MAX or number * 10 != (number * 10).to_integral_value():
            raise ValueError
        return number.quantize(ELECTRIC_STEP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(ELECTRIC_ERROR, code='invalid_electric_reading')
