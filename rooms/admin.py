from django import forms
from django.contrib import admin
from django.forms.models import BaseInlineFormSet

from .models import Room, Contract, ContractTenant


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_number', 'area', 'price', 'max_occupants', 'status')
    list_filter = ('status',)
    search_fields = ('room_number',)


class ContractTenantInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        count = 0
        representatives = 0
        for form in self.forms:
            data = getattr(form, 'cleaned_data', None)
            if not data or data.get('DELETE') or not data.get('tenant'):
                continue
            count += 1
            if data.get('is_representative'):
                representatives += 1

        if count == 0:
            raise forms.ValidationError('Hợp đồng phải có ít nhất một người thuê.')
        if representatives != 1:
            raise forms.ValidationError('Phải chọn đúng một người đại diện.')

        room_id = self.instance.room_id
        if room_id and count > self.instance.room.max_occupants:
            raise forms.ValidationError(
                f'Phòng chỉ cho tối đa {self.instance.room.max_occupants} người, '
                f'bạn đang thêm {count} người.'
            )


class ContractTenantInline(admin.TabularInline):
    model = ContractTenant
    formset = ContractTenantInlineFormSet
    extra = 1


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'start_date', 'end_date', 'deposit', 'status')
    list_filter = ('status',)
    inlines = [ContractTenantInline]

    def get_readonly_fields(self, request, obj=None):
        # Không cho đổi phòng của hợp đồng đã tạo, tránh lệch trạng thái phòng
        return ('room',) if obj else ()