from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import owner_required
from accounts.text import normalize
from . import services
from .contract_forms import (ContractCheckoutForm, ContractCreateForm, ContractRenewForm,
                             ContractTransferForm, DepositApplyForm, DepositReceiptForm, DepositRefundForm)
from billing.models import Invoice
from .display import contract_status_ui, representative_of
from .models import Contract, ViewingAppointment


def _get_contract(pk):
    return get_object_or_404(
        Contract.objects.select_related('room', 'previous_contract__room')
        .prefetch_related('contract_tenants__tenant__user'), pk=pk)


@owner_required
def contract_list(request):
    today = timezone.localdate()
    contracts = Contract.objects.select_related('room').prefetch_related(
        'contract_tenants__tenant').order_by('-start_date', '-id')
    rows = []
    for c in contracts:
        key, label, tone = contract_status_ui(c, today)
        rows.append({
            'contract': c, 'key': key, 'label': label, 'tone': tone,
            'tenant': representative_of(c), 'people': len(c.contract_tenants.all()),
            'days_left': (c.end_date - today).days,
        })

    counts = {
        'all': len(rows),
        'hieu_luc': sum(1 for r in rows if r['contract'].status == Contract.Status.HIEU_LUC),
        'sap_het': sum(1 for r in rows if r['key'] in ('sap_het', 'het_han')),
        'ket_thuc': sum(1 for r in rows if r['key'] == 'ket_thuc'),
    }
    status = request.GET.get('status', '')
    if status not in ('hieu_luc', 'sap_het', 'ket_thuc'):
        status = ''
    q = request.GET.get('q', '').strip()

    shown = rows
    if status == 'hieu_luc':
        shown = [r for r in shown if r['contract'].status == Contract.Status.HIEU_LUC]
    elif status == 'sap_het':
        shown = [r for r in shown if r['key'] in ('sap_het', 'het_han')]
    elif status == 'ket_thuc':
        shown = [r for r in shown if r['key'] == 'ket_thuc']
    if q:
        nq = normalize(q)

        def match(r):
            c = r['contract']
            names = [ct.tenant.full_name for ct in c.contract_tenants.all()]
            return (nq in normalize(c.display_code) or nq in normalize(c.room.room_number)
                    or any(nq in normalize(n) for n in names))

        shown = [r for r in shown if match(r)]

    return render(request, 'rooms/contracts/list.html', {
        'rows': shown, 'counts': counts, 'status': status, 'q': q,
    })


@owner_required
def contract_create(request):
    if request.method == 'POST':
        form = ContractCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                contract = services.create_contract(
                    data['room'], list(data['tenants']), data['representative'],
                    data['start_date'], data['end_date'], data['deposit'],
                    monthly_rent=data.get('monthly_rent'), initial_electric=data.get('initial_electric'),
                    initial_water=data.get('initial_water'), prorate_first_month=data['prorate_first_month'],
                    service_ids=[s.pk for s in data['services']], deposit_paid=data.get('deposit_paid') or 0,
                    deposit_method=data.get('deposit_method') or 'cash', created_by=request.user)
            except ValidationError as e:
                form.add_error(None, e)
            else:
                rep = data['representative']
                rep.refresh_from_db()
                msg = f'Đã lập hợp đồng {contract.display_code} cho phòng {contract.room.room_number}.'
                if rep.user and rep.user.check_password(rep.id_card_number):
                    msg += (f' Tài khoản đăng nhập của {rep.full_name}: tên đăng nhập và mật khẩu '
                            f'ban đầu đều là số CCCD ({rep.id_card_number}).')
                messages.success(request, msg)
                appointment_id = request.POST.get('appointment', '')
                ViewingAppointment.objects.filter(
                    pk=int(appointment_id) if appointment_id.isdigit() else 0, room=contract.room,
                    status__in=['cho_xac_nhan', 'da_xac_nhan', 'da_xem']).update(status='da_chot')                
                return redirect('contract_detail', pk=contract.pk)
    else:
        initial = {}
        appt_id = request.GET.get('appointment', '')
        if appt_id.isdigit():
            appt = ViewingAppointment.objects.filter(pk=int(appt_id)).first()
            if appt:
                initial['room'] = appt.room_id        
        room_id = request.GET.get('room', '')
        tenant_id = request.GET.get('tenant', '')
        if room_id.isdigit():
            initial['room'] = int(room_id)
        if tenant_id.isdigit():
            initial['tenants'] = [int(tenant_id)]
            initial['representative'] = int(tenant_id)
        form = ContractCreateForm(initial=initial)

    appt_id = request.GET.get('appointment') or request.POST.get('appointment') or ''
    appointment = (ViewingAppointment.objects.filter(pk=int(appt_id)).select_related('room').first()
                   if appt_id.isdigit() else None)
    selected = form['tenants'].value() or []
    rep_value = form['representative'].value()
    return render(request, 'rooms/contracts/create.html', {
        'form': form,
        'eligible': form.fields['tenants'].queryset,
        'selected_ids': {int(x) for x in selected if str(x).isdigit()},
        'rep_id': int(rep_value) if str(rep_value or '').isdigit() else None,
        'has_free_rooms': form.fields['room'].queryset.exists(),
        'appointment': appointment,
    })


@owner_required
def contract_detail(request, pk):
    contract = _get_contract(pk)
    today = timezone.localdate()
    key, label, tone = contract_status_ui(contract, today)
    people = sorted(contract.contract_tenants.all(),
                    key=lambda ct: (not ct.is_representative, ct.tenant.full_name))
    invoices = []
    for inv in contract.invoices.prefetch_related('payments').order_by('-year', '-month')[:12]:
        paid = sum((p.amount for p in inv.payments.all()), 0)
        invoices.append({'invoice': inv, 'paid': paid, 'remaining': inv.total_amount - paid})
    return render(request, 'rooms/contracts/detail.html', {
        'contract': contract, 'status_key': key, 'label': label, 'tone': tone,
        'people': people, 'invoices': invoices,
        'renewals': contract.renewals.all(), 'successors': contract.next_contracts.select_related('room'),
        'days_left': (contract.end_date - today).days,
        'active': contract.status == Contract.Status.HIEU_LUC,
        'deposit_balance': contract.deposit_balance, 'deposit_entries': contract.deposit_entries.select_related('related_contract'),
        'checkout_record': getattr(contract, 'checkout_record', None),
        'settlement': services.settlement_summary(contract),
    })


def _action_page(request, contract, template_context):
    summary = services.settlement_summary(contract)
    ctx = {'contract': contract, 'people': contract.contract_tenants.all(), 'deposit_balance': summary['held'],
           'settlement': summary, 'unpaid': summary['unpaid'], 'unpaid_total': summary['debt'],
           'pending_drafts': summary['pending_drafts']}
    ctx.update(template_context)
    return render(request, 'rooms/contracts/action.html', ctx)


@owner_required
def contract_renew(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng đã kết thúc nên không gia hạn được.')
        return redirect('contract_detail', pk=pk)
    form = ContractRenewForm(contract, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.renew_contract(contract, form.cleaned_data['new_end_date'], form.cleaned_data['note'])
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'Đã gia hạn hợp đồng {contract.display_code} đến '
                                      f'{form.cleaned_data["new_end_date"]:%d/%m/%Y}.')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': 'Gia hạn hợp đồng', 'subtitle': f'Hợp đồng {contract.display_code} · phòng {contract.room.room_number}',
        'form': form, 'submit_label': 'Gia hạn', 'danger': False,
    })


@owner_required
def contract_checkout(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng này đã kết thúc.')
        return redirect('contract_detail', pk=pk)
    title, subtitle = 'Trả phòng', f'Hợp đồng {contract.display_code} · phòng {contract.room.room_number}'
    form = ContractCheckoutForm(contract, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            data = form.cleaned_data
            services.checkout_contract(
                contract, data['checkout_date'], deposit_deduction=data.get('deposit_deduction') or 0,
                deduction_reason=data.get('deduction_reason', ''), accept_outstanding=data.get('accept_outstanding', False),
                room_condition=data.get('room_condition') or 'trong',
                expected_deposit_balance=data.get('expected_deposit_balance'), created_by=request.user)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'Đã trả phòng {contract.room.room_number} và lưu biên bản bàn giao. '
                                      'Nợ cũ và cọc chưa hoàn tiếp tục được theo dõi trên hợp đồng này.')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': title, 'subtitle': subtitle, 'form': form, 'submit_label': 'Xác nhận trả phòng',
        'danger': True, 'show_outstanding': True,
        'notice': 'Xác nhận này ghi nhận bàn giao phòng và khoản khấu trừ có lý do. '
                  'Tiền cọc còn giữ sẽ được xử lý sau; chỉ ghi nhận hoàn tiền khi đã thực sự trả cho người thuê.',
    })


@owner_required
def contract_transfer(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng này đã kết thúc.')
        return redirect('contract_detail', pk=pk)
    title, subtitle = 'Chuyển phòng', f'Hợp đồng {contract.display_code} · phòng {contract.room.room_number}'
    form = ContractTransferForm(contract, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            new_contract = services.transfer_contract(
                contract, data['new_room'], data['transfer_date'], data['new_end_date'],
                initial_electric=data.get('initial_electric'), initial_water=data.get('initial_water'),
                accept_outstanding=data.get('accept_outstanding', False), transfer_deposit=data.get('transfer_deposit', False),
                created_by=request.user)
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'Đã chuyển sang phòng {data["new_room"].room_number}. '
                                      f'Hợp đồng mới: {new_contract.display_code}.')
            return redirect('contract_detail', pk=new_contract.pk)
    return _action_page(request, contract, {
        'title': title, 'subtitle': subtitle, 'form': form, 'submit_label': 'Xác nhận chuyển phòng',
        'danger': False, 'show_outstanding': True,
        'notice': 'Hợp đồng hiện tại sẽ kết thúc và một hợp đồng mới được lập ở phòng mới cho đúng những người này. '
                  'Giá thuê hợp đồng mới theo giá niêm yết của phòng được chọn. Mức cọc thỏa thuận giữ nguyên; '
                  'chỉ phần cọc còn dư được chuyển nếu bạn chọn, phần bảo đảm nợ hoặc phí chưa chốt vẫn giữ ở hợp đồng cũ.',
    })


@owner_required
def contract_deposit_receive(request, pk):
    contract = _get_contract(pk)
    form = DepositReceiptForm(request.POST if request.method == 'POST' else None,
                               initial={'amount': max(contract.deposit - contract.deposit_balance, 0)})
    if request.method == 'POST' and form.is_valid():
        try:
            services.receive_deposit(contract, **form.cleaned_data, created_by=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Đã ghi nhận thu cọc. Tiền cọc được theo dõi riêng, không tính vào doanh thu tiền thuê.')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': 'Ghi nhận thu cọc', 'subtitle': f'{contract.display_code} · P.{contract.room.room_number}',
        'form': form, 'submit_label': 'Xác nhận đã nhận tiền cọc', 'danger': False,
        'notice': 'Chỉ ghi nhận sau khi thực sự nhận tiền. Có thể thu nhiều lần đến đủ mức cọc thỏa thuận.',
    })


@owner_required
def contract_deposit_refund(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.KET_THUC:
        messages.error(request, 'Hãy ghi nhận bàn giao phòng trước khi hoàn cọc.')
        return redirect('contract_detail', pk=pk)
    summary = services.settlement_summary(contract)
    form = DepositRefundForm(request.POST if request.method == 'POST' else None,
        initial={'amount': summary['refundable'], 'expected_deposit_balance': summary['held']})
    if request.method == 'POST' and form.is_valid():
        data = {key: value for key, value in form.cleaned_data.items() if key != 'confirm_refund'}
        try:
            services.refund_deposit(contract, **data, created_by=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Đã ghi nhận khoản tiền cọc thực tế đã hoàn cho người thuê.')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': 'Ghi nhận đã hoàn cọc', 'subtitle': f'{contract.display_code} · P.{contract.room.room_number}',
        'form': form, 'submit_label': 'Xác nhận khoản tiền đã hoàn', 'danger': False,
        'notice': 'Chỉ ghi nhận sau khi đã trả tiền mặt hoặc chuyển tiền cho người thuê. Có thể hoàn nhiều lần. '
                  'Cần chốt các phí còn lại và giữ đủ phần bảo đảm công nợ trước khi hoàn.',
    })


@owner_required
def contract_deposit_apply(request, pk, invoice_pk):
    contract = _get_contract(pk)
    invoice = get_object_or_404(Invoice, pk=invoice_pk, contract=contract)
    remaining = invoice.total_amount - invoice.total_paid()
    form = DepositApplyForm(request.POST if request.method == 'POST' else None,
        initial={'amount': min(remaining, contract.deposit_balance), 'expected_deposit_balance': contract.deposit_balance})
    if request.method == 'POST' and form.is_valid():
        data = {key: value for key, value in form.cleaned_data.items() if key != 'confirm_application'}
        try:
            services.apply_deposit_to_invoice(invoice, **data, created_by=request.user)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Đã đối trừ cọc vào hóa đơn và cập nhật đồng thời sổ cọc, công nợ.')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': 'Đối trừ cọc thanh toán hóa đơn',
        'subtitle': f'{contract.display_code} · Hóa đơn #{invoice.pk}, tháng {invoice.month}/{invoice.year}',
        'form': form, 'submit_label': 'Xác nhận đối trừ cọc', 'danger': False,
        'notice': f'Hóa đơn còn nợ {services.money(remaining)} đ. Khoản này dùng tiền cọc đang giữ để thanh toán, '
                  'không phải một lần nhận tiền mặt hay chuyển khoản mới.',
    })
