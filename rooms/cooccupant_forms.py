from django import forms

from accounts.forms import BootstrapFormMixin
from accounts.identity_forms import IdentityScanFormMixin
from accounts.identity_profile import DETAIL_FIELDS
from .models import CoOccupantRequest


PROFILE_FIELDS = ('full_name', 'id_card_number', 'phone', 'email', 'date_of_birth', 'hometown', 'occupation', *DETAIL_FIELDS, 'note')


class CoOccupantRequestForm(BootstrapFormMixin, IdentityScanFormMixin, forms.ModelForm):
    confirm_information = forms.BooleanField(label='Tôi đã kiểm tra thông tin và được người ở cùng đồng ý cung cấp hồ sơ cho chủ trọ.')

    class Meta:
        model = CoOccupantRequest
        fields = PROFILE_FIELDS
        widgets = {
            'date_of_birth': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'note': forms.Textarea(attrs={'rows': 3}),
            'permanent_address': forms.Textarea(attrs={'rows': 2}),
            'identity_issued_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'identity_expires_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }
        help_texts = {'id_card_number': 'Nhập số trên giấy tờ của người ở cùng. Hồ sơ được gửi để chủ trọ đối chiếu trước khi xác nhận.'}


class CoOccupantReviewForm(BootstrapFormMixin, forms.Form):
    action = forms.ChoiceField(choices=[('approve', 'Xác nhận người ở cùng'), ('reject', 'Yêu cầu bổ sung / Từ chối')],
                               label='Thao tác')
    review_note = forms.CharField(label='Phản hồi cho người đại diện', required=False, max_length=1000,
                                  widget=forms.Textarea(attrs={'rows': 3}))
    confirm_information = forms.BooleanField(required=False,
        label='Tôi đã đối chiếu hồ sơ và đồng ý thêm người này vào hợp đồng.')
    reuse_existing = forms.BooleanField(required=False,
        label='Tôi xác nhận đây là người trong hồ sơ đã có; sử dụng hồ sơ hiện có sau khi đối chiếu.')

    def __init__(self, *args, existing_tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing_tenant = existing_tenant
        if existing_tenant is None:
            self.fields.pop('reuse_existing')

    def clean(self):
        data = super().clean()
        if data.get('action') == 'approve':
            if not data.get('confirm_information'):
                self.add_error('confirm_information', 'Hãy đối chiếu hồ sơ và xác nhận trước khi thêm người ở cùng.')
            if self.existing_tenant and not data.get('reuse_existing'):
                self.add_error('reuse_existing', 'Hãy đối chiếu người này với hồ sơ đã có trước khi sử dụng.')
        if data.get('action') == 'reject' and not (data.get('review_note') or '').strip():
            self.add_error('review_note', 'Hãy ghi rõ nội dung cần bổ sung hoặc lý do từ chối.')
        return data
