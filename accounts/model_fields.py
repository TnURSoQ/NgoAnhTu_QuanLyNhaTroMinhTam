from django.core.exceptions import ValidationError
from django.db import models

from .money import whole_dong


class DongField(models.DecimalField):
    """Lưu tiền nguyên đồng trên cả SQLite và PostgreSQL."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 8)
        kwargs.setdefault('decimal_places', 0)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        if value is None:
            return None
        try:
            return whole_dong(value)
        except ArithmeticError:
            raise ValidationError('Số tiền không hợp lệ.')

    def pre_save(self, model_instance, add):
        value = self.to_python(getattr(model_instance, self.attname))
        setattr(model_instance, self.attname, value)
        return value
