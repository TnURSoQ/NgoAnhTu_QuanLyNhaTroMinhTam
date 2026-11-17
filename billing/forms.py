from datetime import timedelta

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from .models import Payment, Service
from .services import available_rooms, DUE_DAYS, MAX_FEE


class PeriodForm(BootstrapFormMixin, forms.Form):
    month = forms.TypedChoiceField(label='Tháng', coerce=int,
                                  choices=[(m, f'Tháng {m}') for m in range(1, 13)])
    year = forms.IntegerField(label='Năm', min_value=2000, max_value=2100)


class InvoiceCreateForm(PeriodForm):
    room = forms.ModelChoiceField(label='Phòng', queryset=None, empty_label='Chọn phòng')
    old_electric = FlexibleDecimalField(label='Chỉ số điện cũ', min_value=0, max_digits=10,
                                        decimal_places=2, widget=PlainDecimalInput)
    new_electric = FlexibleDecimalField(label='Chỉ số điện mới', min_value=0, max_digits=10,
                                        decimal_places=2, widget=PlainDecimalInput)
    old_water = FlexibleDecimalField(label='Chỉ số nước cũ', min_value=0, max_digits=10,
                                     decimal_places=2, widget=PlainDecimalInput)
    new_water = FlexibleDecimalField(label='Chỉ số nước mới', min_value=0, max_digits=10,
                                     decimal_places=2, widget=PlainDecimalInput)
    room_fee = MoneyField(label='Tiền phòng', min_value=0, max_value=MAX_FEE,
                          max_digits=8, decimal_places=0)
    due_date = forms.DateField(label='Hạn thanh toán', widget=forms.DateInput(
        attrs={'type': 'date'}, format='%Y-%m-%d'))
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, month, year, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['room'].queryset = available_rooms(month, year)
        self.initial.setdefault('month', month)
        self.initial.setdefault('year', year)
        self.initial.setdefault('due_date', timezone.localdate() + timedelta(days=DUE_DAYS))


class InvoiceLineForm(BootstrapFormMixin, forms.Form):
    service = forms.ModelChoiceField(label='Dịch vụ', queryset=Service.objects.all(), required=False,
                                     widget=forms.HiddenInput)
    description = forms.CharField(label='Mô tả', max_length=255)
    quantity = forms.IntegerField(label='Số lượng', min_value=1, max_value=2147483647, initial=1)
    unit_price = MoneyField(label='Đơn giá', min_value=0, max_value=MAX_FEE,
                            max_digits=8, decimal_places=0, required=False)

    def clean(self):
        data = super().clean()
        if not data.get('DELETE') and not data.get('service') and data.get('unit_price') is None:
            self.add_error('unit_price', 'Vui lòng nhập số tiền cho khoản tự nhập.')
        return data


InvoiceLineFormSet = formset_factory(InvoiceLineForm, extra=0, can_delete=True, max_num=200,
                                    validate_max=True, absolute_max=200)


class PaymentForm(BootstrapFormMixin, forms.Form):
    amount = MoneyField(label='Số tiền thu', min_value=1, max_value=MAX_FEE,
                        max_digits=8, decimal_places=0)
    paid_date = forms.DateField(label='Ngày thu', initial=timezone.localdate,
                               widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    method = forms.ChoiceField(label='Hình thức', choices=Payment.Method.choices)
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class UtilityRateForm(BootstrapFormMixin, forms.Form):
    electric_price = MoneyField(label='Giá điện (đ/kWh)', min_value=1,
                                max_digits=8, decimal_places=0)
    water_price = MoneyField(label='Giá nước (đ/m³)', min_value=1,
                             max_digits=8, decimal_places=0)
    effective_date = forms.DateField(label='Ngày hiệu lực', initial=timezone.localdate,
                                    widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))


class ServiceForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(label='Tên dịch vụ', max_length=100)
    unit_price = MoneyField(label='Đơn giá', min_value=1,
                            max_digits=8, decimal_places=0)


class BankAccountForm(BootstrapFormMixin, forms.Form):
    bank_name = forms.CharField(label='Ngân hàng', max_length=100)
    account_number = forms.CharField(label='Số tài khoản', max_length=50,
                                     widget=forms.TextInput(attrs={'inputmode': 'numeric'}))
    account_holder = forms.CharField(label='Chủ tài khoản', max_length=150)


class PaymentNoticeForm(BootstrapFormMixin, forms.Form):
    amount = MoneyField(label='Số tiền đã chuyển (không bắt buộc)', required=False,
                        min_value=1, max_value=MAX_FEE, max_digits=8, decimal_places=0)
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={
        'rows': 2, 'placeholder': 'Ví dụ: chuyển lúc 14:30, tên người chuyển...'}))


class PaymentNoticeConfirmForm(PaymentForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['method'].initial = Payment.Method.CHUYEN_KHOAN
        self.fields['method'].disabled = True


class PaymentNoticeRejectForm(BootstrapFormMixin, forms.Form):
    reject_reason = forms.CharField(label='Lý do từ chối', widget=forms.Textarea(attrs={'rows': 3}),
                                    error_messages={'required': 'Vui lòng nhập lý do từ chối.'})
