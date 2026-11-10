import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .models import Tenant


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'form-check-input'
            elif isinstance(widget, forms.Select):
                css = 'form-select'
            else:
                css = 'form-control'
            widget.attrs['class'] = css

    def full_clean(self):
        super().full_clean()
        # đánh dấu ô nhập sai để Bootstrap viền đỏ
        for name in self._errors or {}:
            if name in self.fields:
                widget = self.fields[name].widget
                css = widget.attrs.get('class', '')
                if 'is-invalid' not in css:
                    widget.attrs['class'] = css + ' is-invalid'


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    remember_me = forms.BooleanField(required=False, initial=True, label='Ghi nhớ đăng nhập')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Tên đăng nhập'
        self.fields['username'].widget.attrs.update(
            {'placeholder': 'Tên đăng nhập hoặc số CCCD', 'autofocus': True})
        self.fields['password'].widget.attrs.update({'placeholder': 'Nhập mật khẩu'})


class ChangePasswordForm(BootstrapFormMixin, PasswordChangeForm):
    pass


class TenantForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ['full_name', 'phone', 'id_card_number', 'email', 'date_of_birth',
                  'hometown', 'occupation', 'note']
        labels = {
            'full_name': 'Họ và tên', 'phone': 'Số điện thoại', 'id_card_number': 'Số CCCD',
            'email': 'Email', 'date_of_birth': 'Ngày sinh', 'hometown': 'Quê quán',
            'occupation': 'Nghề nghiệp', 'note': 'Ghi chú',
        }
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'note': forms.Textarea(attrs={'rows': 3}),
        }
        error_messages = {'id_card_number': {'unique': 'Số CCCD này đã có trong hệ thống.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cccd = self.fields['id_card_number']
        cccd.help_text = ('CCCD gồm 12 số (CMND cũ gồm 9 số). '
                          'Đây cũng là tên đăng nhập của người đại diện hợp đồng.')
        if self.instance.pk and self.instance.user_id:
            cccd.disabled = True
            cccd.help_text = 'Người này đã có tài khoản đăng nhập nên không đổi được số CCCD.'

    def clean_id_card_number(self):
        if self.fields['id_card_number'].disabled:
            return self.instance.id_card_number
        value = (self.cleaned_data.get('id_card_number') or '').strip()
        if not re.fullmatch(r'\d{9}|\d{12}', value):
            raise forms.ValidationError('Số CCCD phải gồm 12 chữ số (hoặc 9 chữ số với CMND cũ).')
        return value

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        if not re.fullmatch(r'[0-9+\s]{9,15}', value):
            raise forms.ValidationError('Số điện thoại không hợp lệ (9 đến 15 chữ số).')
        return value