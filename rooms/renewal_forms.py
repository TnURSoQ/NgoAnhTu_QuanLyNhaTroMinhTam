from datetime import timedelta
import calendar
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image

from accounts.form_fields import MoneyField
from accounts.forms import BootstrapFormMixin
from .contract_forms import _date_widget
from .models import Contract, ContractDocument


def validate_document(upload):
    if not upload:
        raise ValidationError('Hãy tải tài liệu đã ký lên để đối chiếu.')
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError('Mỗi tài liệu tối đa 10 MB.')
    ext = Path(upload.name).suffix.lower()
    try:
        upload.seek(0)
        if ext == '.pdf':
            if upload.read(5) != b'%PDF-':
                raise ValueError
        elif ext in ('.jpg', '.jpeg', '.png', '.webp'):
            image = Image.open(upload)
            if image.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValueError
            image.verify()
        else:
            raise ValueError
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError('Tài liệu phải là PDF hoặc ảnh JPG, PNG, WebP hợp lệ.')
    finally:
        upload.seek(0)
    return upload


class RenewalForm(BootstrapFormMixin, forms.Form):
    expected_end_date = forms.DateField(widget=forms.HiddenInput)
    new_end_date = forms.DateField(label='Gia hạn đến ngày', widget=_date_widget())
    effective_date = forms.DateField(label='Ngày áp dụng giá và cọc', widget=_date_widget(),
        help_text='Sau hạn cũ. Nếu đổi giá giữa tháng, tiền phòng được chia theo số ngày áp dụng mỗi mức giá.')
    monthly_rent = MoneyField(label='Giá thuê kỳ gia hạn (đ/tháng)', min_value=1)
    deposit = MoneyField(label='Mức cọc thỏa thuận kỳ gia hạn (đ)', min_value=0,
        help_text='Mức thỏa thuận không phải tiền đã thu. Số cọc thực giữ được chuyển tiếp, không tự thu hoặc hoàn.')
    terms = forms.CharField(label='Điều khoản bổ sung', max_length=5000, required=False,
                            widget=forms.Textarea(attrs={'rows': 4}))
    note = forms.CharField(label='Lời nhắn', max_length=1000, required=False,
                           widget=forms.Textarea(attrs={'rows': 2}))
    confirm = forms.BooleanField(label='Tôi đã kiểm tra thời hạn, giá thuê, tiền cọc và các điều khoản đề nghị')

    def __init__(self, contract, *args, owner=False, offline=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract
        base = max(contract.end_date, timezone.localdate())
        month_index = base.year * 12 + base.month - 1 + 6
        year, month_zero = divmod(month_index, 12)
        default_end = base.replace(year=year, month=month_zero + 1,
                                   day=min(base.day, calendar.monthrange(year, month_zero + 1)[1]))
        self.initial.update(expected_end_date=contract.end_date,
            new_end_date=default_end,
            effective_date=max(contract.end_date + timedelta(days=1), timezone.localdate()),
            monthly_rent=contract.rent_on(contract.end_date), deposit=contract.deposit_on(contract.end_date))
        if not owner:
            for name in ('effective_date', 'monthly_rent', 'deposit', 'terms'):
                self.fields.pop(name)
            self.fields['confirm'].label = 'Tôi đề nghị gia hạn với giá thuê, mức cọc và điều khoản hiện có'
        if offline:
            self.fields['signed_file'] = forms.FileField(label='Phụ lục gia hạn hai bên đã ký',
                validators=[validate_document], widget=forms.ClearableFileInput(attrs={
                    'class': 'form-control', 'accept': '.pdf,.jpg,.jpeg,.png,.webp'}))
            self.fields['confirm'].label = 'Hai bên đã thống nhất gia hạn ngoài ứng dụng; tôi ghi nhận theo tài liệu đã ký'

    def clean(self):
        data = super().clean()
        if data.get('new_end_date') and data['new_end_date'] <= max(self.contract.end_date, timezone.localdate()):
            self.add_error('new_end_date', 'Ngày mới phải sau ngày kết thúc hiện tại và sau hôm nay.')
        if data.get('effective_date') and data.get('new_end_date') and not (
                self.contract.end_date < data['effective_date'] <= data['new_end_date']):
            self.add_error('effective_date', 'Ngày áp dụng phải nằm sau hạn cũ và không sau hạn mới.')
        return data


class ResponseForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(label='Phản hồi', max_length=1000, required=False,
                           widget=forms.Textarea(attrs={'rows': 2}))
    confirm = forms.BooleanField(label='Tôi đã đọc và đồng ý toàn bộ đề nghị gia hạn', required=False)


class MoveOutForm(BootstrapFormMixin, forms.Form):
    planned_date = forms.DateField(label='Ngày dự kiến trả phòng', widget=_date_widget())
    reason = forms.CharField(label='Lý do / lời nhắn', max_length=1000, required=False,
                             widget=forms.Textarea(attrs={'rows': 3}))
    confirm = forms.BooleanField(label='Tôi gửi lịch dự kiến để trao đổi với chủ trọ; việc bàn giao và quyết toán được thực hiện riêng')


class ContractDocumentForm(BootstrapFormMixin, forms.ModelForm):
    proposal = forms.ModelChoiceField(label='Gắn với lần gia hạn', queryset=None,
                                       required=False, empty_label='Tài liệu chung của hợp đồng')
    file = forms.FileField(label='Tài liệu đã ký', validators=[validate_document],
        help_text='PDF, JPG, PNG, WebP; tối đa 10 MB. Chỉ chủ trọ và người thuộc hợp đồng được tải.',
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.jpg,.jpeg,.png,.webp'}))

    class Meta:
        model = ContractDocument
        fields = ['title', 'kind', 'file']
        labels = {'kind': 'Loại tài liệu'}

    def __init__(self, contract, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proposal'].queryset = contract.renewal_proposals.filter(status='accepted')
        self.fields['proposal'].label_from_instance = lambda item: f'{item.display_code} · đến {item.new_end_date:%d/%m/%Y}'

    def clean(self):
        data = super().clean()
        if data.get('proposal') and data.get('kind') != 'annex':
            self.add_error('kind', 'Tài liệu của lần gia hạn phải là phụ lục đã ký.')
        return data


class ContractTermsForm(BootstrapFormMixin, forms.ModelForm):
    confirm = forms.BooleanField(label='Nội dung được nhập đúng theo hợp đồng / phụ lục hai bên đã thống nhất')

    class Meta:
        model = Contract
        fields = ['payment_terms', 'renewal_terms', 'checkout_terms']
        widgets = {name: forms.Textarea(attrs={'rows': 3, 'maxlength': 5000})
                   for name in ('payment_terms', 'renewal_terms', 'checkout_terms')}

    def clean(self):
        data = super().clean()
        for key in self.Meta.fields:
            if len(data.get(key, '')) > 5000:
                self.add_error(key, 'Tối đa 5.000 ký tự.')
        return data
