from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import User

@login_required
def home(request):
    user = request.user
    if user.is_staff:
        return redirect('admin:index')
    if user.role == User.Role.TENANT and hasattr(user, 'tenant_profile'):
        return redirect('my_invoices')
    # Không thuộc nhóm nào: hiện thông báo thay vì chuyển hướng (tránh vòng lặp)
    return render(request, 'accounts/no_access.html', status=403)