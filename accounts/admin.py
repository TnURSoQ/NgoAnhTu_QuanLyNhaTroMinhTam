from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, Tenant


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Thêm trường role vào form sửa và form tạo user
    fieldsets = UserAdmin.fieldsets + (
        ('Vai trò', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Vai trò', {'fields': ('role',)}),
    )
    list_display = ('username', 'email', 'role', 'is_active')
    list_filter = ('role', 'is_active')


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'id_card_number', 'phone', 'user')
    search_fields = ('full_name', 'id_card_number', 'phone')
