from .models import User


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
    if created:
        #dùng set_password để mật khẩu đc mã hoá, k lưu chữ thô trong database
        user.set_password(tenant.id_card_number) 
        user.save()

    tenant.user = user
    tenant.save(update_fields=['user'])
    return user
