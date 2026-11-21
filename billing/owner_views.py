from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import owner_required
from accounts.text import normalize
from rooms.display import representative_of
from rooms.models import Contract
from . import drafts, services
from .forms import (BankAccountForm, InvoiceCreateForm, InvoiceLineFormSet, PaymentForm,
                    PaymentNoticeConfirmForm, PaymentNoticeRejectForm, PeriodForm,
                    ServiceForm, UtilityRateForm, InvoiceDraftForm)
from .models import BankAccount, Invoice, InvoiceDraft, Payment, PaymentNotice, Service, UtilityRate


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
    today = timezone.localdate()
    if (month, year) == (today.month, today.year):
        try:
            drafts.generate_monthly_drafts(month, year)
        except ValidationError as exc:
            messages.error(request, 'Chưa tạo được bản nháp: ' + '; '.join(exc.messages))
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    rows = []
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
        'draft_count': _pending_drafts(month, year).count(),
        'period_form': PeriodForm(initial={'month': month, 'year': year})})


def _pending_drafts(month, year):
    return InvoiceDraft.objects.filter(
        month=month, year=year, invoice__isnull=True
    ).select_related('contract__room').prefetch_related('contract__contract_tenants__tenant')


@owner_required
@require_POST
def invoice_generate_drafts(request):
    form = PeriodForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Tháng/năm không hợp lệ.')
        return redirect('invoice_list')
    month, year = form.cleaned_data['month'], form.cleaned_data['year']
    try:
        count = drafts.generate_monthly_drafts(month, year)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    else:
        if count:
            messages.success(request, f'Đã bổ sung {count} phòng vào bảng điện nước tháng {month}/{year}.')
    return redirect(f'{reverse("invoice_drafts")}?month={month}&year={year}')


@owner_required
def invoice_drafts(request):
    period = PeriodForm(request.POST if request.method == 'POST' else request.GET or {
        'month': timezone.localdate().month, 'year': timezone.localdate().year})
    if not period.is_valid():
        return _render(request, 'billing/owner/drafts.html', {'period_form': period, 'rows': []})
    month, year = period.cleaned_data['month'], period.cleaned_data['year']
    pending = list(_pending_drafts(month, year))
    rows = []
    for draft in pending:
        drafts.fill_missing_defaults(draft)
        form = InvoiceDraftForm(request.POST if request.method == 'POST' else None,
                                instance=draft, prefix=f'draft-{draft.pk}')
        rows.append({'draft': draft, 'form': form, 'tenant': representative_of(draft.contract)})
    if request.method == 'POST':
        action = request.POST.get('action')
        posted_ids = request.POST.getlist('draft_ids')
        if posted_ids != [str(d.pk) for d in pending]:
            messages.error(request, 'Danh sách nháp đã thay đổi. Hãy tải lại bảng trước khi lưu.')
        elif action not in ('save', 'publish'):
            messages.error(request, 'Thao tác không hợp lệ.')
        elif not rows:
            messages.info(request, 'Không còn bản nháp trong kỳ này.')
        elif all([row['form'].is_valid() for row in rows]):
            data = [{**row['form'].cleaned_data, 'draft': row['draft']} for row in rows]
            try:
                published, skipped = drafts.save_draft_rows(data, month=month, year=year,
                                                           publish=action == 'publish')
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
            else:
                if action == 'publish':
                    messages.success(request, f'Đã chốt {published} hóa đơn. '
                                     f'{skipped} phòng được chọn còn thiếu chỉ số hoặc đơn giá, đã giữ nháp.')
                else:
                    messages.success(request, f'Đã lưu chỉ số cho {len(rows)} bản nháp.')
                return redirect(f'{reverse("invoice_drafts")}?month={month}&year={year}')
    return _render(request, 'billing/owner/drafts.html', {
        'period_form': period, 'rows': rows, 'month': month, 'year': year,
        'ready_count': sum(row['draft'].is_ready for row in rows),
        'missing_rate': any(row['draft'].electric_unit_price is None or
                            row['draft'].water_unit_price is None for row in rows)})


@owner_required
def invoice_create(request):
    month, year = _period(request)
    form = InvoiceCreateForm(request.POST if request.method == 'POST' else None, month=month, year=year,
                             initial={'room': request.GET.get('room', '')})
    selected_id = request.POST.get('room') if request.method == 'POST' else request.GET.get('room')
    selected_room = next((r for r in form.fields['room'].queryset if str(r.pk) == selected_id), None)
    selected_contract = services.room_contract(selected_room.pk, month, year) if selected_room else None
    selected_services = services.billable_services(selected_contract) if selected_contract else Service.objects.all()
    initial_lines = [{'service': s.pk, 'description': s.name, 'quantity': 1, 'unit_price': s.unit_price}
                     for s in selected_services.order_by('name')]
    lines = InvoiceLineFormSet(request.POST if request.method == 'POST' else None,
                               initial=initial_lines, prefix='items')
    rooms = list(form.fields['room'].queryset)
    room_data = {}
    for room in rooms:
        contract = services.room_contract(room.pk, month, year)
        electric, water, baseline = services.utility_baseline(room.pk, month, year, contract)
        room_data[str(room.pk)] = {
            'price': str(services.default_room_fee(contract, month, year)),
            'has_previous_reading': bool(baseline),
            'old_electric': str(electric) if electric is not None else '',
            'old_water': str(water) if water is not None else '',
            'service_items': [{'service': s.pk, 'description': s.name, 'quantity': 1, 'unit_price': str(s.unit_price)}
                              for s in services.billable_services(contract).order_by('name')]}
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
        'payment_notices': inv.payment_notices.select_related('tenant', 'payment', 'processed_by'),
        'remaining': inv.total_amount - paid, 'form': form})


@owner_required
def invoice_print(request, pk):
    invoice = get_object_or_404(_invoices(), pk=pk)
    paid = invoice.total_paid()
    return render(request, 'billing/owner/print.html', {
        'invoice': invoice, 'tenant': representative_of(invoice.contract),
        'reading': invoice.utility_reading, 'paid': paid, 'remaining': invoice.total_amount - paid,
        'invoice_services': invoice.invoice_services.all(), 'payments': invoice.payments.order_by('paid_date', 'pk'),
    })


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
        try:
            services.delete_payment(payment)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        else:
            messages.success(request, 'Đã xóa khoản thanh toán và tính lại công nợ.')
        return redirect(back_url)
    return _render(request, '_crud/confirm_delete.html', {
        'title': 'Xóa khoản thanh toán', 'message': 'Xác nhận xóa khoản thu này để sửa nhầm?',
        'blocked': payment.method == Payment.Method.TU_COC,
        'blocked_message': 'Khoản đối trừ cọc gắn với sổ cọc, không được xóa độc lập.',
        'back_url': back_url})


@owner_required
def billing_settings(request):
    action = request.POST.get('action')
    rate_form = UtilityRateForm(request.POST if request.method == 'POST' and action == 'rate' else None)
    service_form = ServiceForm(request.POST if request.method == 'POST' and action == 'service' else None)
    bank = BankAccount.objects.first()
    bank_form = BankAccountForm(request.POST if request.method == 'POST' and action == 'bank' else None,
                                initial={k: getattr(bank, k) for k in
                                         ('bank_name', 'account_number', 'account_holder')} if bank else {})
    if request.method == 'POST' and action in ('rate', 'service', 'bank'):
        form = {'rate': rate_form, 'service': service_form, 'bank': bank_form}[action]
        if form.is_valid():
            try:
                if action == 'rate':
                    services.add_utility_rate(**form.cleaned_data)
                elif action == 'bank':
                    services.configure_bank_account(**form.cleaned_data)
                else:
                    services.save_service(**form.cleaned_data)
            except ValidationError as e:
                form.add_error(None, e.messages)
            else:
                messages.success(request, {'rate': 'Đã thêm đơn giá mới.', 'service': 'Đã thêm dịch vụ.',
                                           'bank': 'Đã cập nhật thông tin chuyển khoản.'}[action])
                return redirect('billing_settings')
    return _render(request, 'billing/owner/settings.html', {
        'rate': UtilityRate.current(), 'rates': UtilityRate.objects.all(),
        'services': Service.objects.order_by('name'), 'rate_form': rate_form, 'service_form': service_form,
        'bank_account': bank, 'bank_form': bank_form})


def _get_payment_notice(pk):
    return get_object_or_404(PaymentNotice.objects.select_related('invoice__contract__room', 'tenant'), pk=pk)


@owner_required
def payment_notice_confirm(request, pk):
    notice = _get_payment_notice(pk)
    if notice.status != PaymentNotice.Status.CHO_XAC_NHAN:
        messages.error(request, 'Thông báo này đã được xử lý.')
        return redirect('invoice_detail', pk=notice.invoice_id)
    remaining = notice.invoice.total_amount - notice.invoice.total_paid()
    form = PaymentNoticeConfirmForm(request.POST if request.method == 'POST' else None, initial={
        'amount': notice.amount if notice.amount is not None else remaining, 'note': notice.note})
    if request.method == 'POST' and form.is_valid():
        try:
            data = {k: v for k, v in form.cleaned_data.items() if k != 'method'}
            services.confirm_payment_notice(notice, processed_by=request.user, **data)
        except ValidationError as e:
            form.add_error(None, e.messages)
        else:
            messages.success(request, 'Đã xác nhận chuyển khoản và ghi nhận thu tiền.')
            return redirect('invoice_detail', pk=notice.invoice_id)
    return _render(request, 'billing/owner/notice_action.html', {
        'notice': notice, 'form': form, 'remaining': remaining,
        'title': 'Xác nhận chuyển khoản', 'submit_label': 'Xác nhận và ghi nhận thu tiền'})


@owner_required
def payment_notice_reject(request, pk):
    notice = _get_payment_notice(pk)
    if notice.status != PaymentNotice.Status.CHO_XAC_NHAN:
        messages.error(request, 'Thông báo này đã được xử lý.')
        return redirect('invoice_detail', pk=notice.invoice_id)
    form = PaymentNoticeRejectForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.reject_payment_notice(notice, processed_by=request.user, **form.cleaned_data)
        except ValidationError as e:
            form.add_error(None, e.messages)
        else:
            messages.success(request, 'Đã từ chối báo chuyển khoản và lưu lý do.')
            return redirect('invoice_detail', pk=notice.invoice_id)
    return _render(request, 'billing/owner/notice_action.html', {
        'notice': notice, 'form': form, 'title': 'Từ chối chuyển khoản', 'danger': True,
        'remaining': notice.invoice.total_amount - notice.invoice.total_paid(),
        'submit_label': 'Từ chối và gửi lý do'})


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
