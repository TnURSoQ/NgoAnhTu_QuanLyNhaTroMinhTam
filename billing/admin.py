from django.contrib import admin

from .models import UtilityRate, UtilityReading, Service, Invoice, InvoiceService, Payment


@admin.register(UtilityRate)
class UtilityRateAdmin(admin.ModelAdmin):
    list_display = ('effective_date', 'electric_price', 'water_price')


@admin.register(UtilityReading)
class UtilityReadingAdmin(admin.ModelAdmin):
    list_display = ('room', 'month', 'year', 'old_electric', 'new_electric', 'old_water', 'new_water')
    list_filter = ('year', 'month')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit_price')


class InvoiceServiceInline(admin.TabularInline):
    model = InvoiceService
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'month', 'year', 'total_amount', 'status', 'due_date')
    list_filter = ('status', 'year', 'month')
    inlines = [InvoiceServiceInline, PaymentInline]