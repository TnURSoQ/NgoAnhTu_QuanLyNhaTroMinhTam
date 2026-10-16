from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import UtilityRate, UtilityReading, Service, Invoice, InvoiceService, Payment
from .services import create_invoice_from_reading


@admin.register(UtilityRate)
class UtilityRateAdmin(admin.ModelAdmin):
    list_display = ('effective_date', 'electric_price', 'water_price')


@admin.action(description='Lập hóa đơn từ chỉ số đã chọn')
def create_invoices(modeladmin, request, queryset):
    created = 0
    for reading in queryset.select_related('room'):
        try:
            create_invoice_from_reading(reading)
            created += 1
        except ValidationError as e:
            modeladmin.message_user(
                request, f'{reading}: {"; ".join(e.messages)}', level=messages.ERROR
            )
    if created:
        modeladmin.message_user(request, f'Đã lập {created} hóa đơn.', level=messages.SUCCESS)


@admin.register(UtilityReading)
class UtilityReadingAdmin(admin.ModelAdmin):
    list_display = ('room', 'month', 'year', 'old_electric', 'new_electric', 'old_water', 'new_water')
    list_filter = ('year', 'month')
    actions = [create_invoices]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_price')


class InvoiceServiceInline(admin.TabularInline):
    model = InvoiceService
    extra = 0
    readonly_fields = ('subtotal',)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'month', 'year', 'total_amount', 'status', 'due_date')
    list_filter = ('status', 'year', 'month')
    readonly_fields = ('contract', 'utility_reading', 'month', 'year', 'total_amount', 'created_at')
    inlines = [InvoiceServiceInline, PaymentInline]

    def has_add_permission(self, request):
        # Hóa đơn chỉ được lập từ chỉ số điện nước, không nhập tay
        return False

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Sửa/xóa dòng dịch vụ xong thì tổng tiền tự cập nhật lại
        form.instance.recalculate_total()