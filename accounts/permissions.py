from .models import User


def is_owner(user):
    """Chủ trọ = tài khoản có vai trò 'owner'.
    Quyền vào Django Admin (is_staff) là chuyện riêng của lập trình viên."""
    return user.is_authenticated and user.role == User.Role.OWNER