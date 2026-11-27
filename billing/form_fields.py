import re

from django import forms

from accounts.form_fields import FlexibleDecimalField, PlainDecimalInput
from .meters import ELECTRIC_ERROR, ELECTRIC_HELP, ELECTRIC_MAX, electric_reading


class ElectricMeterInput(PlainDecimalInput):
    def __init__(self, attrs=None):
        super().__init__({'placeholder': 'VD: 1.611,1', 'data-electric-meter': 'true', **(attrs or {})})

    def format_value(self, value):
        if value in (None, ''):
            return ''
        try:
            number = electric_reading(value)
            text = f'{number:,.1f}'.replace(',', '_').replace('.', ',').replace('_', '.')
            return text[:-2] if text.endswith(',0') else text
        except forms.ValidationError:
            return value


class ElectricMeterFormField(FlexibleDecimalField):
    widget = ElectricMeterInput

    def __init__(self, *args, **kwargs):
        kwargs.update(max_digits=6, decimal_places=1, min_value=0, max_value=ELECTRIC_MAX)
        kwargs.setdefault('help_text', ELECTRIC_HELP)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip()
            if ',' in value:
                if not re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+),\d', value):
                    raise forms.ValidationError(ELECTRIC_ERROR)
                value = value.replace('.', '').replace(',', '.')
            elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', value):
                value = value.replace('.', '')
            elif value and not re.fullmatch(r'\d+(?:\.\d)?', value):
                raise forms.ValidationError(ELECTRIC_ERROR)
        return electric_reading(super().to_python(value))

    def bound_data(self, data, initial):
        if self.disabled:
            return initial
        try:
            return self.to_python(data)
        except forms.ValidationError:
            return data
