from django.contrib import admin

from .models import Room, Contract, ContractTenant


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_number', 'area', 'price', 'max_occupants', 'status')
    list_filter = ('status',)
    search_fields = ('room_number',)


class ContractTenantInline(admin.TabularInline):
    model = ContractTenant
    extra = 1


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'start_date', 'end_date', 'deposit', 'status')
    list_filter = ('status',)
    # Thêm người thuê và đánh dấu người đại diện ngay trong form hợp đồng
    inlines = [ContractTenantInline]