from decimal import Decimal

from django import forms


class MoneyInput(forms.TextInput):
    """Ô nhập tiền: hiện 2.500.000 và chấp nhận gõ 2.500.000 hoặc 2500000."""

    def __init__(self, attrs=None):
        super().__init__({'inputmode': 'numeric', 'placeholder': 'VD: 2.500.000', **(attrs or {})})

    def format_value(self, value):
        if value in (None, ''):
            return ''
        try:
            number = Decimal(str(value))
        except Exception:
            return value
        if number == number.to_integral_value():
            return f'{int(number):,}'.replace(',', '.')
        return str(number).replace('.', ',')


class MoneyField(forms.DecimalField):
    widget = MoneyInput

    def to_python(self, value):
        if isinstance(value, str):
            # dấu chấm là dấu ngăn nghìn, dấu phẩy là dấu thập phân (kiểu Việt Nam)
            value = value.strip().replace(' ', '').replace('.', '').replace(',', '.')
        return super().to_python(value)


class FlexibleDecimalField(forms.DecimalField):
    """Số thập phân, chấp nhận cả 20,5 và 20.5."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(',', '.')
        return super().to_python(value)


class PlainDecimalInput(forms.TextInput):
    """Ô nhập số thập phân gọn: 20.00 hiện là 20, 20.50 hiện là 20.5."""

    def __init__(self, attrs=None):
        super().__init__({'inputmode': 'decimal', **(attrs or {})})

    def format_value(self, value):
        if value in (None, ''):
            return ''
        try:
            return format(Decimal(str(value)).normalize(), 'f')
        except Exception:
            return value