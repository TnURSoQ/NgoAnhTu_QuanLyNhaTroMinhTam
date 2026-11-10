from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import User
from .permissions import is_owner


def tenant_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        tenant = getattr(request.user, 'tenant_profile', None)
        if request.user.role != User.Role.TENANT or tenant is None:
            return redirect('home')
        request.tenant = tenant
        return view_func(request, *args, **kwargs)
    return wrapper


def owner_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_owner(request.user):
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper