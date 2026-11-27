from django.db import models

from .meters import ELECTRIC_HELP, electric_reading


class ElectricMeterReadingField(models.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.update(max_digits=6, decimal_places=1)
        kwargs.setdefault('help_text', ELECTRIC_HELP)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        return electric_reading(super().to_python(value))

    def formfield(self, **kwargs):
        from .form_fields import ElectricMeterFormField
        return super().formfield(**{'form_class': ElectricMeterFormField, **kwargs})
