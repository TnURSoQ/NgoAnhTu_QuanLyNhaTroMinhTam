from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import LoginForm
from .models import User
from .permissions import is_owner


class RememberLoginView(LoginView):
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)  # hết phiên khi đóng trình duyệt
        return response


@login_required
def home(request):
    user = request.user
    if is_owner(user):
        return redirect('owner_dashboard')
    if user.role == User.Role.TENANT and hasattr(user, 'tenant_profile'):
        return redirect('my_invoices')
    if user.is_staff:
        return redirect('admin:index')  # lập trình viên: vào trang quản trị hệ thống
    # Không thuộc nhóm nào: hiện thông báo thay vì chuyển hướng (tránh vòng lặp)
    return render(request, 'accounts/no_access.html', status=403)