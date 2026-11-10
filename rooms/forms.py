from django import forms

from accounts.form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from accounts.forms import BootstrapFormMixin
from .models import Contract, Room


class RoomForm(BootstrapFormMixin, forms.ModelForm):
    price = MoneyField(label='Giá thuê (đ/tháng)', max_digits=10, decimal_places=2, min_value=1)
    area = FlexibleDecimalField(
        label='Diện tích (m²)', max_digits=5, decimal_places=2, required=False, min_value=1,
        widget=PlainDecimalInput(attrs={'placeholder': 'VD: 20'}))

    class Meta:
        model = Room
        fields = ['room_number', 'floor', 'area', 'max_occupants', 'price', 'status']
        labels = {
            'room_number': 'Số phòng', 'floor': 'Tầng',
            'max_occupants': 'Sức chứa tối đa (người)', 'status': 'Tình trạng',
        }
        error_messages = {'room_number': {'unique': 'Số phòng này đã tồn tại.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        status = self.fields['status']
        has_contract = bool(self.instance.pk) and self.instance.contracts.filter(
            status=Contract.Status.HIEU_LUC).exists()
        if has_contract:
            status.disabled = True
            status.help_text = 'Phòng đang có hợp đồng nên tình trạng do hệ thống tự cập nhật.'
        else:
            status.choices = [(Room.Status.TRONG, 'Còn trống'), (Room.Status.BAO_TRI, 'Đang sửa chữa')]

    def clean_max_occupants(self):
        value = self.cleaned_data['max_occupants']
        if value < 1:
            raise forms.ValidationError('Sức chứa tối đa phải từ 1 người trở lên.')
        return value