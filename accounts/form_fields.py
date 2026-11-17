from decimal import Decimal

from django import forms

from .money import MAX_MONEY, whole_dong


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
        if not number.is_finite():
            return value
        if abs(number) > MAX_MONEY:
            return value
        return f'{int(whole_dong(number)):,}'.replace(',', '.')


class MoneyField(forms.DecimalField):
    widget = MoneyInput

    def __init__(self, *args, **kwargs):
        kwargs['max_digits'] = 8
        kwargs['decimal_places'] = 0
        kwargs.setdefault('max_value', MAX_MONEY)
        super().__init__(*args, **kwargs)

    def bound_data(self, data, initial):
        if self.disabled:
            return initial
        try:
            # Đọc đúng định dạng Việt trước khi hiển thị lại form có lỗi.
            # Chuỗi "3.500" phải giữ giá trị 3500, không thành "3,500" (3,5 đ).
            return self.to_python(data)
        except forms.ValidationError:
            return data

    def to_python(self, value):
        if isinstance(value, str):
            # dấu chấm là dấu ngăn nghìn, dấu phẩy là dấu thập phân (kiểu Việt Nam)
            value = value.strip().replace(' ', '').replace('.', '').replace(',', '.')
        value = super().to_python(value)
        if value is not None and value != value.to_integral_value():
            raise forms.ValidationError('Vui lòng nhập số tiền nguyên đồng, ví dụ 2.220.227.')
        return whole_dong(value) if value is not None else None


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
