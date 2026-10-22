from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass


class ChangePasswordForm(BootstrapFormMixin, PasswordChangeForm):
    pass