from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import owner_required
from accounts.text import normalize
from rooms.display import representative_of
from . import services
from .forms import (InvoiceCreateForm, InvoiceLineFormSet, PaymentForm, PeriodForm,
                    ServiceForm, UtilityRateForm)
from .models import Invoice, Payment, Service, UtilityRate


def _render(request, template, context):
    # Các trang nghiệp vụ hóa đơn không dẫn chủ trọ sang giao diện quản trị.
    return render(request, template, {**context, 'hide_admin_navigation': True})


def _period(request):
    today = timezone.localdate()
    data = request.POST if request.method == 'POST' else request.GET
    form = PeriodForm(data or {'month': today.month, 'year': today.year})
    if form.is_valid():
        return form.cleaned_data['month'], form.cleaned_data['year']
    return today.month, today.year


def _invoices():
    return Invoice.objects.select_related('contract__room', 'utility_reading').prefetch_related(
        'payments', 'contract__contract_tenants__tenant')


@owner_required
def invoice_list(request):
    month, year = _period(request)
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    rows = []
    today = timezone.localdate()
    for inv in _invoices().filter(month=month, year=year).order_by('contract__room__room_number'):
        inv.update_status()
        tenant = representative_of(inv.contract)
        if q and normalize(q) not in normalize(' '.join([
                inv.contract.room.room_number,
                *[ct.tenant.full_name for ct in inv.contract.contract_tenants.all()]])):
            continue
        paid = sum((p.amount for p in inv.payments.all()), Decimal('0'))
        days = (inv.due_date - today).days
        rows.append({'invoice': inv, 'tenant': tenant, 'paid': paid,
                     'remaining': inv.total_amount - paid,
                     'due_label': f'Còn {days} ngày' if days >= 0 else f'Quá hạn {-days} ngày'})
    counts = {'': len(rows), **{s: sum(r['invoice'].status == s for r in rows) for s in Invoice.Status.values}}
    tabs = [{'key': key, 'label': label, 'count': counts[key]} for key, label in [
        ('', 'Tất cả'), ('chua_thanh_toan', 'Chưa thu'), ('thu_mot_phan', 'Thu một phần'),
        ('da_thanh_toan', 'Đã thu'), ('qua_han', 'Quá hạn')]]
    if status not in Invoice.Status.values:
        status = ''
    return _render(request, 'billing/owner/list.html', {
        'rows': [r for r in rows if not status or r['invoice'].status == status],
        'tabs': tabs, 'status': status, 'q': q, 'month': month, 'year': year,
        'period_form': PeriodForm(initial={'month': month, 'year': year})})


@owner_required
def invoice_create(request):
    month, year = _period(request)
    form = InvoiceCreateForm(request.POST if request.method == 'POST' else None, month=month, year=year)
    initial_lines = [{'service': s.pk, 'description': s.name, 'quantity': 1, 'unit_price': s.unit_price}
                     for s in Service.objects.order_by('name')]
    lines = InvoiceLineFormSet(request.POST if request.method == 'POST' else None,
                               initial=initial_lines, prefix='items')
    rooms = list(form.fields['room'].queryset)
    room_data = {}
    for room in rooms:
        reading = room.utility_readings.filter(Q(year__lt=year) | Q(year=year, month__lt=month)).order_by(
            '-year', '-month').first()
        room_data[str(room.pk)] = {
            'price': str(room.price),
            'old_electric': str(reading.new_electric) if reading else '',
            'old_water': str(reading.new_water) if reading else ''}
    if request.method != 'POST':
        room_id = request.GET.get('room', '')
        if room_id in room_data:
            defaults = room_data[room_id]
            form.initial.update(room=room_id, room_fee=defaults['price'],
                                old_electric=defaults['old_electric'], old_water=defaults['old_water'])
    if request.method == 'POST':
        valid_form, valid_lines = form.is_valid(), lines.is_valid()
        if valid_form and valid_lines:
            try:
                inv = services.create_invoice(**form.cleaned_data, service_items=[
                    {k: v for k, v in item.items() if k != 'DELETE'}
                    for item in lines.cleaned_data if item and not item.get('DELETE')])
            except ValidationError as e:
                form.add_error(None, e.messages)
            else:
                messages.success(request, 'Đã tạo hóa đơn.')
                return redirect('invoice_detail', pk=inv.pk)
    return _render(request, 'billing/owner/create.html', {
        'form': form, 'lines': lines, 'room_data': room_data, 'rate': UtilityRate.current(),
        'month': month, 'year': year, 'has_rooms': bool(rooms)})


@owner_required
def invoice_detail(request, pk):
    inv = get_object_or_404(_invoices(), pk=pk)
    inv.update_status()
    paid = inv.total_paid()
    form = PaymentForm(request.POST if request.method == 'POST' else None,
                       initial={'amount': inv.total_amount - paid})
    if request.method == 'POST' and form.is_valid():
        try:
            services.record_payment(inv, **form.cleaned_data)
        except ValidationError as e:
            form.add_error(None, e.messages)
        else:
            messages.success(request, 'Đã ghi nhận thu tiền.')
            return redirect('invoice_detail', pk=pk)
    return _render(request, 'billing/owner/detail.html', {
        'invoice': inv, 'tenant': representative_of(inv.contract), 'reading': inv.utility_reading,
        'invoice_services': inv.invoice_services.select_related('service'),
        'payments': inv.payments.order_by('-paid_date', '-pk'), 'paid': paid,
        'remaining': inv.total_amount - paid, 'form': form})


@owner_required
def invoice_delete(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if request.method == 'POST':
        try:
            services.delete_invoice(inv)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            return redirect('invoice_detail', pk=pk)
        messages.success(request, 'Đã xóa hóa đơn và chỉ số không còn sử dụng.')
        return redirect('invoice_list')
    return _render(request, '_crud/confirm_delete.html', {
        'title': 'Xóa hóa đơn', 'message': str(inv), 'blocked': inv.payments.exists(),
        'blocked_message': 'Không thể xóa hóa đơn đã có khoản thanh toán.',
        'back_url': reverse('invoice_detail', args=[pk])})


@owner_required
def payment_delete(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('invoice'), pk=pk)
    back_url = reverse('invoice_detail', args=[payment.invoice_id])
    if request.method == 'POST':
        services.delete_payment(payment)
        messages.success(request, 'Đã xóa khoản thanh toán và tính lại công nợ.')
        return redirect(back_url)
    return _render(request, '_crud/confirm_delete.html', {
        'title': 'Xóa khoản thanh toán', 'message': 'Xác nhận xóa khoản thu này để sửa nhầm?',
        'back_url': back_url})


@owner_required
def billing_settings(request):
    action = request.POST.get('action')
    rate_form = UtilityRateForm(request.POST if request.method == 'POST' and action == 'rate' else None)
    service_form = ServiceForm(request.POST if request.method == 'POST' and action == 'service' else None)
    if request.method == 'POST' and action in ('rate', 'service'):
        form = rate_form if action == 'rate' else service_form
        if form.is_valid():
            try:
                if action == 'rate':
                    services.add_utility_rate(**form.cleaned_data)
                else:
                    services.save_service(**form.cleaned_data)
            except ValidationError as e:
                form.add_error(None, e.messages)
            else:
                messages.success(request, 'Đã thêm đơn giá mới.' if action == 'rate' else 'Đã thêm dịch vụ.')
                return redirect('billing_settings')
    return _render(request, 'billing/owner/settings.html', {
        'rate': UtilityRate.current(), 'rates': UtilityRate.objects.all(),
        'services': Service.objects.order_by('name'), 'rate_form': rate_form, 'service_form': service_form})


@owner_required
def service_edit(request, pk):
    service = get_object_or_404(Service, pk=pk)
    form = ServiceForm(request.POST if request.method == 'POST' else None,
                       initial={'name': service.name, 'unit_price': service.unit_price})
    if request.method == 'POST' and form.is_valid():
        try:
            services.save_service(service=service, **form.cleaned_data)
        except ValidationError as e:
            form.add_error(None, e.messages)
        else:
            messages.success(request, 'Đã cập nhật dịch vụ.')
            return redirect('billing_settings')
    return _render(request, 'billing/owner/service_form.html', {'form': form})


@owner_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk)
    if request.method == 'POST':
        try:
            services.delete_service(service)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(request, 'Đã xóa dịch vụ.')
        return redirect('billing_settings')
    return _render(request, '_crud/confirm_delete.html', {
        'title': 'Xóa dịch vụ', 'message': service.name,
        'blocked': service.invoiceservice_set.exists(),
        'blocked_message': 'Không thể xóa dịch vụ đã dùng trong hóa đơn.',
        'back_url': reverse('billing_settings')})
