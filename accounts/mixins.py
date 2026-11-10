from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect

from .permissions import is_owner


class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Chỉ chủ trọ được vào. Chưa đăng nhập thì chuyển tới trang đăng nhập."""

    def test_func(self):
        return is_owner(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect('home')