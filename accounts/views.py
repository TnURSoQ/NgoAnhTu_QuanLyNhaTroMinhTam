from django.contrib.auth.views import LoginView
from django.http import JsonResponse

from rooms.public_views import landing

from .forms import LoginForm
from .forms import TenantProfileForm
from .decorators import tenant_required
from .models import Tenant, User
from django.contrib import messages
from django.db import transaction, IntegrityError, DatabaseError
from django.shortcuts import render, redirect
from .identity_capture import IdentityCapture


@tenant_required
def my_profile(request):
    if request.method == 'POST':
        try:
            with IdentityCapture() as capture, transaction.atomic():
                tenant = Tenant.objects.select_for_update().get(pk=request.tenant.pk, user=request.user)
                form = TenantProfileForm(request.POST, request.FILES or None, instance=tenant)
                if form.is_valid():
                    tenant = form.save()
                    User.objects.filter(pk=request.user.pk).update(first_name=tenant.full_name, email=tenant.email or '')
                    capture.save(form, request.user, tenant)
                    messages.success(request, 'Đã cập nhật thông tin cá nhân.')
                    return redirect('my_profile')
        except IntegrityError:
            form.add_error('id_card_number', 'Số CCCD này đã có trong hệ thống. Vui lòng kiểm tra lại.')
        except (OSError, DatabaseError):
            form.add_error(None, 'Chưa lưu được thông tin và ảnh giấy tờ. Vui lòng thử lại.')
    else:
        form = TenantProfileForm(instance=request.tenant)
    return render(request, 'accounts/my_profile.html', {'form': form})


class RememberLoginView(LoginView):
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def wants_json(self):
        return 'application/json' in self.request.headers.get('Accept', '')

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)  # hết phiên khi đóng trình duyệt
        if self.wants_json():
            return JsonResponse({'redirect_url': self.get_success_url()})
        return response

    def form_invalid(self, form):
        if self.wants_json():
            return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
        return super().form_invalid(form)


def home(request):
    return landing(request)
