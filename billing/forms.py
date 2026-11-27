from datetime import timedelta

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from accounts.form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from .form_fields import ElectricMeterFormField
from .models import InvoiceDraft, Payment, Service, UtilityRate, WaterBillingMethod
from .services import available_rooms, room_contract, utility_baseline, DUE_DAYS, MAX_FEE


class PeriodForm(BootstrapFormMixin, forms.Form):
    month = forms.TypedChoiceField(label='Tháng', coerce=int,
                                  choices=[(m, f'Tháng {m}') for m in range(1, 13)])
    year = forms.IntegerField(label='Năm', min_value=2000, max_value=2100)


class InvoiceCreateForm(PeriodForm):
    room = forms.ModelChoiceField(label='Phòng', queryset=None, empty_label='Chọn phòng')
    old_electric = ElectricMeterFormField(label='Chỉ số điện cũ')
    new_electric = ElectricMeterFormField(label='Chỉ số điện mới')
    old_water = FlexibleDecimalField(label='Chỉ số nước cũ', min_value=0, max_digits=10,
                                     decimal_places=2, widget=PlainDecimalInput)
    new_water = FlexibleDecimalField(label='Chỉ số nước mới', min_value=0, max_digits=10,
                                     decimal_places=2, widget=PlainDecimalInput)
    water_people_count = forms.IntegerField(label='Số người tính tiền nước', min_value=1, max_value=2147483647,
                                            required=False)
    room_fee = MoneyField(label='Tiền phòng', min_value=0, max_value=MAX_FEE,
                          max_digits=8, decimal_places=0)
    due_date = forms.DateField(label='Hạn thanh toán', widget=forms.DateInput(
        attrs={'type': 'date'}, format='%Y-%m-%d'))
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, month, year, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['room'].queryset = available_rooms(month, year)
        rate = UtilityRate.current()
        self.water_per_person = not rate or rate.water_billing_method == WaterBillingMethod.PER_PERSON
        self.fields['water_people_count'].required = self.water_per_person
        for name in ('old_water', 'new_water'):
            self.fields[name].required = not self.water_per_person
            self.fields[name].disabled = self.water_per_person
        self.initial.setdefault('month', month)
        self.initial.setdefault('year', year)
        self.initial.setdefault('due_date', timezone.localdate() + timedelta(days=DUE_DAYS))
        room_id = self.data.get(self.add_prefix('room')) if self.is_bound else self.initial.get('room')
        try:
            room = self.fields['room'].queryset.filter(pk=room_id).first() if room_id else None
        except (TypeError, ValueError):
            room = None
        electric, water, baseline = utility_baseline(room.pk, month, year) if room else (None, None, '')
        if room and self.water_per_person:
            contract = room_contract(room.pk, month, year)
            self.initial.setdefault('water_people_count', contract.contract_tenants.count() or None)
        if baseline:
            for utility, value in [('electric', electric), ('water', water)]:
                name = f'old_{utility}'
                if value is not None:
                    self.initial[name] = str(value)
                    self.fields[name].disabled = True


class InvoiceDraftForm(BootstrapFormMixin, forms.ModelForm):
    selected = forms.BooleanField(label='Chọn chốt', required=False)
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    preview_token = forms.CharField(max_length=150, widget=forms.HiddenInput)
    room_fee = MoneyField(label='Tiền phòng', min_value=0)
    old_electric = ElectricMeterFormField(label='Điện cũ', required=False)
    new_electric = ElectricMeterFormField(label='Điện mới', required=False)
    old_water = FlexibleDecimalField(label='Nước cũ', min_value=0, max_digits=10,
                                     decimal_places=2, required=False, widget=PlainDecimalInput)
    new_water = FlexibleDecimalField(label='Nước mới', min_value=0, max_digits=10,
                                     decimal_places=2, required=False, widget=PlainDecimalInput)

    class Meta:
        model = InvoiceDraft
        fields = ['old_electric', 'new_electric', 'old_water', 'new_water', 'room_fee',
                  'water_people_count', 'due_date', 'note']
        # A missing count may be saved as a draft, but cannot be published.
        labels = {'due_date': 'Hạn thanh toán', 'note': 'Ghi chú', 'water_people_count': 'Số người tính tiền nước'}
        widgets = {'due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'note': forms.Textarea(attrs={'rows': 1})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['revision'] = self.instance.revision
        self.initial['preview_token'] = self.instance.preview_token
        self.water_per_person = self.instance.water_billing_method == WaterBillingMethod.PER_PERSON
        if self.water_per_person:
            for name in ('old_water', 'new_water'):
                self.fields[name].disabled = True
        else:
            self.fields['water_people_count'].disabled = True
        if self.instance.has_previous_reading:
            self.fields['old_electric'].disabled = True
            self.fields['old_water'].disabled = self.water_per_person or self.instance.old_water is not None
        self.fields['due_date'].help_text = 'Để trống: 10 ngày kể từ khi chốt.'
        for name, field in self.fields.items():
            field.widget.attrs['aria-label'] = f'Phòng {self.instance.contract.room.room_number}: {field.label}'


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
    method = forms.ChoiceField(label='Hình thức', choices=[choice for choice in Payment.Method.choices
                                                         if choice[0] != Payment.Method.TU_COC])
    note = forms.CharField(label='Ghi chú', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class PaymentCorrectionForm(PaymentForm):
    action = forms.ChoiceField(label='Thao tác', choices=[('void', 'Hủy ghi nhận khoản thu'),
        ('adjust', 'Điều chỉnh bằng giao dịch thay thế')], initial='void')
    reason = forms.CharField(label='Lý do hủy / điều chỉnh', max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ghi rõ thông tin bị nhầm và nội dung cần sửa…'}),
        error_messages={'required': 'Hãy nhập lý do hủy / điều chỉnh khoản thu.'})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['action', 'reason', 'amount', 'paid_date', 'method', 'note'])
        action = self.data.get(self.add_prefix('action')) if self.is_bound else self.initial.get('action', 'void')
        for name in ('amount', 'paid_date', 'method', 'note'):
            self.fields[name].disabled = action == 'void'
            if action == 'void':
                # A legacy amount above today's entry limit must still be voidable.
                self.fields[name].validators = []


class UtilityRateForm(BootstrapFormMixin, forms.Form):
    electric_price = MoneyField(label='Giá điện (đ/kWh)', min_value=1,
                                max_digits=8, decimal_places=0)
    water_price = MoneyField(label='Giá nước (đ/người/tháng)', min_value=1, initial=50000,
                             max_digits=8, decimal_places=0,
                             help_text='Mặc định 50.000đ/người/tháng. Thu đủ tháng theo số người chủ trọ chốt trong kỳ.')
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
