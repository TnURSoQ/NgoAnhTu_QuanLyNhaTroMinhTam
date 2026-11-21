from .models import User
from django.core.exceptions import ValidationError


def create_account_for_tenant(tenant):
    """Tạo tài khoản đăng nhập cho người thuê nếu chưa có.
    Username và mật khẩu mặc định đều là số CCCD."""
    if tenant.user_id:
        return tenant.user

    user, created = User.objects.get_or_create(
        username=tenant.id_card_number,
        defaults={
            'role': User.Role.TENANT,
            'first_name': tenant.full_name,
            'email': tenant.email or '',
        },
    )
    if not created and (user.role != User.Role.TENANT or (
            hasattr(user, 'tenant_profile') and user.tenant_profile.pk != tenant.pk)):
        raise ValidationError('Tên đăng nhập này đang thuộc tài khoản khác. Không thể tự liên kết hồ sơ người thuê.')
    if created:
        #dùng set_password để mật khẩu đc mã hoá, k lưu chữ thô trong database
        user.set_password(tenant.id_card_number) 
        user.save()

    tenant.user = user
    tenant.save(update_fields=['user'])
    return user
