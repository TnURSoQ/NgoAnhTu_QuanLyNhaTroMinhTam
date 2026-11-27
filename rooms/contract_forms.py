import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from accounts.forms import BootstrapFormMixin
from billing.form_fields import ElectricMeterFormField
from accounts.models import Tenant
from . import services
from billing.models import Service
from billing.services import water_is_metered
from .models import Contract, DepositEntry, Room


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
    deposit = MoneyField(label='Tiền đặt cọc (đ)', max_digits=8, decimal_places=0, min_value=0)
    monthly_rent = MoneyField(label='Giá thuê thỏa thuận (đ/tháng)', min_value=1, required=False,
                              help_text='Để trống: lấy giá niêm yết hiện tại. Giá này được giữ riêng cho hợp đồng.')
    initial_electric = ElectricMeterFormField(label='Chỉ số điện lúc nhận phòng', required=False)
    initial_water = FlexibleDecimalField(label='Chỉ số nước lúc nhận phòng', min_value=0, max_digits=10,
                                         decimal_places=2, required=False, widget=PlainDecimalInput)
    prorate_first_month = forms.BooleanField(label='Tính tiền phòng tháng đầu theo ngày ở thực tế',
                                             required=False, initial=True,
                                             help_text='Giá tháng × số ngày từ ngày nhận phòng đến cuối tháng / số ngày trong tháng.')
    services = forms.ModelMultipleChoiceField(label='Dịch vụ sử dụng', queryset=Service.objects.all(),
                                               required=False, widget=forms.CheckboxSelectMultiple,
                                               help_text='Chỉ các dịch vụ được chọn mới được đưa vào nháp hằng tháng.')
    deposit_paid = MoneyField(label='Tiền cọc đã thực thu khi nhận phòng (đ)', min_value=0, required=False,
                              initial=0, help_text='Chỉ nhập khi đã nhận tiền. Để 0 nếu khách chưa nộp cọc.')
    deposit_method = forms.ChoiceField(label='Hình thức thu cọc', required=False,
                                       choices=[('cash', 'Tiền mặt'), ('bank', 'Chuyển khoản')], initial='cash')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not water_is_metered():
            self.fields.pop('initial_water')
        self.fields['room'].queryset = free_rooms()
        eligible = Tenant.objects.exclude(
            contract_tenants__contract__status=Contract.Status.HIEU_LUC).order_by('full_name')
        self.fields['tenants'].queryset = eligible
        self.fields['representative'].queryset = eligible
        self.fields['start_date'].initial = timezone.localdate()
        self.fields['services'].initial = list(Service.objects.values_list('pk', flat=True))

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
        if water_is_metered() and (cleaned.get('initial_electric') is None) != (cleaned.get('initial_water') is None):
            raise ValidationError('Hãy nhập đủ cả chỉ số điện và nước lúc nhận phòng.')
        if cleaned.get('deposit_paid', 0) and cleaned.get('deposit') is not None and cleaned['deposit_paid'] > cleaned['deposit']:
            self.add_error('deposit_paid', 'Tiền cọc đã thu không được vượt tiền cọc thỏa thuận.')
        return cleaned


class ContractCheckoutForm(BootstrapFormMixin, forms.Form):
    checkout_date = forms.DateField(label='Ngày trả phòng', widget=_date_widget())
    deposit_deduction = MoneyField(label='Khấu trừ cọc do hư hỏng / thiếu tài sản (đ)', min_value=0, required=False, initial=0,
        help_text='Nợ tiền phòng, điện nước cần đối trừ vào hóa đơn; không nhập vào khoản khấu trừ tài sản này.')
    deduction_reason = forms.CharField(label='Lý do khấu trừ / ghi chú bàn giao', max_length=500,
                                       required=False, widget=forms.Textarea(attrs={'rows': 3}))
    room_condition = forms.ChoiceField(label='Tình trạng phòng sau bàn giao', required=False,
                                       choices=[('trong', 'Sẵn sàng cho thuê'), ('bao_tri', 'Cần vệ sinh / sửa chữa')], initial='trong')
    expected_deposit_balance = forms.DecimalField(required=False, widget=forms.HiddenInput)
    accept_outstanding = forms.BooleanField(required=False,
        label='Xác nhận bàn giao phòng và tiếp tục theo dõi nợ, hóa đơn chưa chốt trên hợp đồng cũ')

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields['checkout_date'].initial = timezone.localdate()
        self.initial['expected_deposit_balance'] = contract.deposit_balance
        summary = services.settlement_summary(contract)
        if summary['debt'] or summary['pending_count']:
            self.fields['accept_outstanding'].required = True
        else:
            self.fields.pop('accept_outstanding')


class ContractTransferForm(BootstrapFormMixin, forms.Form):
    new_room = forms.ModelChoiceField(queryset=Room.objects.none(), label='Chuyển sang phòng',
                                      empty_label='— Chọn phòng —')
    transfer_date = forms.DateField(label='Ngày chuyển', widget=_date_widget())
    new_end_date = forms.DateField(label='Ngày kết thúc hợp đồng mới', widget=_date_widget())
    initial_electric = ElectricMeterFormField(label='Chỉ số điện khi nhận phòng mới', required=False)
    initial_water = FlexibleDecimalField(label='Chỉ số nước khi nhận phòng mới', min_value=0, max_digits=10,
                                         decimal_places=2, required=False, widget=PlainDecimalInput)
    accept_outstanding = forms.BooleanField(required=False,
        label='Xác nhận chuyển phòng và giữ nợ, hóa đơn chưa chốt trên hợp đồng cũ')
    transfer_deposit = forms.BooleanField(required=False, initial=True,
        label='Chuyển phần cọc còn dư sang hợp đồng mới',
        help_text='Giữ lại phần bảo đảm nợ cũ; chưa chốt hết hóa đơn thì cọc tạm ở lại hợp đồng cũ.')

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        self.fields['new_room'].queryset = free_rooms().exclude(pk=contract.room_id)
        if not water_is_metered():
            self.fields.pop('initial_water')
        self.fields['new_room'].label_from_instance = lambda room: f'Phòng {room.room_number} · {services.money(room.price)} đ/tháng'
        self.fields['transfer_date'].initial = timezone.localdate()
        self.fields['new_end_date'].initial = contract.end_date
        summary = services.settlement_summary(contract)
        if summary['debt'] or summary['pending_count']:
            self.fields['accept_outstanding'].required = True
        else:
            self.fields.pop('accept_outstanding')


class DepositReceiptForm(BootstrapFormMixin, forms.Form):
    amount = MoneyField(label='Số tiền thu cọc (đ)', min_value=1)
    occurred_on = forms.DateField(label='Ngày đã nhận tiền', initial=timezone.localdate, widget=_date_widget())
    method = forms.ChoiceField(label='Hình thức', choices=[('cash', 'Tiền mặt'), ('bank', 'Chuyển khoản')])
    note = forms.CharField(label='Ghi chú', max_length=500, required=False)
    reference = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class DepositRefundForm(DepositReceiptForm):
    expected_deposit_balance = forms.DecimalField(min_value=0, required=True, widget=forms.HiddenInput)
    confirm_refund = forms.BooleanField(label='Tôi xác nhận đã thực sự hoàn số tiền này cho người thuê')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amount'].label = 'Số tiền đã thực sự hoàn (đ)'
        self.fields['occurred_on'].label = 'Ngày đã hoàn tiền'


class DepositApplyForm(DepositReceiptForm):
    expected_deposit_balance = forms.DecimalField(min_value=0, required=True, widget=forms.HiddenInput)
    confirm_application = forms.BooleanField(label='Tôi đã thống nhất với người thuê về khoản đối trừ này')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('method')
        self.fields['amount'].label = 'Số tiền cọc dùng thanh toán hóa đơn (đ)'
        self.fields['occurred_on'].label = 'Ngày đối trừ'
        self.fields['note'].label = 'Nội dung đã thống nhất với người thuê'
        self.fields['note'].required = True
