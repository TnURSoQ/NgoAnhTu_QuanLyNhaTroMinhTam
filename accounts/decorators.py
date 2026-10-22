from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import User


def tenant_required(view_func):
    """Chỉ cho người thuê (có hồ sơ Tenant) vào. Gắn request.tenant cho view dùng."""
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        tenant = getattr(request.user, 'tenant_profile', None)
        if request.user.role != User.Role.TENANT or tenant is None:
            return redirect('home')
        request.tenant = tenant
        return view_func(request, *args, **kwargs)
    return wrapper