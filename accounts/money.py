from decimal import Decimal, ROUND_DOWN


MAX_MONEY = Decimal('99999999')


def whole_dong(value):
    """Tiền Việt Nam: bỏ phần lẻ, không làm tròn lên."""
    return Decimal(str(value)).to_integral_value(rounding=ROUND_DOWN)
