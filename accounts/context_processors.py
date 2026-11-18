from django.conf import settings

from .forms import LoginForm


def site_info(request):
    context = {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'Nhà trọ Minh Tâm'),
        'SITE_ADDRESS': getattr(settings, 'SITE_ADDRESS', ''),
        'SITE_PHONE': getattr(settings, 'SITE_PHONE', ''),
    }
    if not request.user.is_authenticated:
        form = LoginForm(request=request, auto_id='modal_%s')
        form.fields['username'].widget.attrs.pop('autofocus', None)
        context['modal_login_form'] = form
    return context
