from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.form_fields import MoneyField
from accounts.forms import BootstrapFormMixin
from accounts.models import Tenant
from . import services
from .models import Contract, Room


def _date_widget():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def free_rooms():
    return Room.objects.filter(status=Room.Status.TRONG).order_by('floor', 'room_number')


class ContractCreateForm(BootstrapFormMixin, forms.Form):
    room = forms.ModelChoiceField(queryset=Room.objects.none(), label='Phòng', empty_label='— Chọn phòng —')
    tenants = forms.ModelMultipleChoiceField(
        queryset=Tenant.objects.none(), label='Người thuê', required=False,
        widget=forms.CheckboxSelectMultiple)
    representative = forms.ModelChoiceField(
        queryset=Tenant.objects.none(), label='Người đại diện', required=False,
        widget=forms.RadioSelect, empty_label=None)
    start_date = forms.DateField(label='Ngày bắt đầu', widget=_date_widget())
    end_date = forms.DateField(label='Ngày kết thúc', widget=_date_widget())
    deposit = MoneyField(label='Tiền đặt cọc (đ)', max_digits=10, decimal_places=2, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['room'].queryset = free_rooms()
        eligible = Tenant.objects.exclude(
            contract_tenants__contract__status=Contract.Status.HIEU_LUC).order_by('full_name')
        self.fields['tenants'].queryset = eligible
        self.fields['representative'].queryset = eligible
        self.fields['start_date'].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        room = cleaned.get('room')
        if room is None:
            return cleaned
        errors = services.contract_errors(
            room, list(cleaned.get('tenants') or []), cleaned.get('representative'),
            cleaned.get('start_date'), cleaned.get('end_date'), cleaned.get('deposit'))
        if errors:
            raise ValidationError(errors)
        return cleaned


class ContractRenewForm(BootstrapFormMixin, forms.Form):
    new_end_date = forms.DateField(label='Ngày kết thúc mới', widget=_date_widget())
    note = forms.CharField(label='Ghi chú', required=False, max_length=255)

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields['new_end_date'].initial = contract.end_date + timedelta(days=365)

    def clean_new_end_date(self):
        value = self.cleaned_data['new_end_date']
        errors = services.renew_errors(self.contract, value)
        if errors:
            raise ValidationError(errors)
        return value


class ContractCheckoutForm(BootstrapFormMixin, forms.Form):
    checkout_date = forms.DateField(label='Ngày trả phòng', widget=_date_widget())

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields['checkout_date'].initial = timezone.localdate()


class ContractTransferForm(BootstrapFormMixin, forms.Form):
    new_room = forms.ModelChoiceField(queryset=Room.objects.none(), label='Chuyển sang phòng',
                                      empty_label='— Chọn phòng —')
    transfer_date = forms.DateField(label='Ngày chuyển', widget=_date_widget())
    new_end_date = forms.DateField(label='Ngày kết thúc hợp đồng mới', widget=_date_widget())

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields['new_room'].queryset = free_rooms().exclude(pk=contract.room_id)
        self.fields['transfer_date'].initial = timezone.localdate()
        self.fields['new_end_date'].initial = contract.end_date