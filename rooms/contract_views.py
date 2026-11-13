from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import owner_required
from accounts.text import normalize
from . import services
from .contract_forms import (ContractCheckoutForm, ContractCreateForm, ContractRenewForm,
                             ContractTransferForm)
from .display import contract_status_ui, representative_of
from .models import Contract


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
                    data['start_date'], data['end_date'], data['deposit'])
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
                return redirect('contract_detail', pk=contract.pk)
    else:
        initial = {}
        room_id = request.GET.get('room', '')
        tenant_id = request.GET.get('tenant', '')
        if room_id.isdigit():
            initial['room'] = int(room_id)
        if tenant_id.isdigit():
            initial['tenants'] = [int(tenant_id)]
            initial['representative'] = int(tenant_id)
        form = ContractCreateForm(initial=initial)

    selected = form['tenants'].value() or []
    rep_value = form['representative'].value()
    return render(request, 'rooms/contracts/create.html', {
        'form': form,
        'eligible': form.fields['tenants'].queryset,
        'selected_ids': {int(x) for x in selected if str(x).isdigit()},
        'rep_id': int(rep_value) if str(rep_value or '').isdigit() else None,
        'has_free_rooms': form.fields['room'].queryset.exists(),
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
    })


def _action_page(request, contract, template_context):
    ctx = {'contract': contract, 'people': contract.contract_tenants.all()}
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


def _blocked_page(request, contract, title, subtitle):
    unpaid = services.unpaid_invoices(contract)
    if not unpaid:
        return None
    return _action_page(request, contract, {
        'title': title, 'subtitle': subtitle, 'blocked': True,
        'unpaid': unpaid, 'unpaid_total': sum(r for _, r in unpaid),
    })


@owner_required
def contract_checkout(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng này đã kết thúc.')
        return redirect('contract_detail', pk=pk)
    title, subtitle = 'Trả phòng', f'Hợp đồng {contract.display_code} · phòng {contract.room.room_number}'
    blocked = _blocked_page(request, contract, title, subtitle)
    if blocked:
        return blocked
    form = ContractCheckoutForm(contract, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.checkout_contract(contract, form.cleaned_data['checkout_date'])
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'Đã trả phòng {contract.room.room_number}. Phòng đã chuyển sang "Còn trống".')
            return redirect('contract_detail', pk=pk)
    return _action_page(request, contract, {
        'title': title, 'subtitle': subtitle, 'form': form, 'submit_label': 'Xác nhận trả phòng',
        'danger': True,
        'notice': 'Sau khi trả phòng, hợp đồng kết thúc và phòng chuyển sang "Còn trống". Không hoàn tác được.',
    })


@owner_required
def contract_transfer(request, pk):
    contract = _get_contract(pk)
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng này đã kết thúc.')
        return redirect('contract_detail', pk=pk)
    title, subtitle = 'Chuyển phòng', f'Hợp đồng {contract.display_code} · phòng {contract.room.room_number}'
    blocked = _blocked_page(request, contract, title, subtitle)
    if blocked:
        return blocked
    form = ContractTransferForm(contract, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            new_contract = services.transfer_contract(
                contract, data['new_room'], data['transfer_date'], data['new_end_date'])
        except ValidationError as e:
            form.add_error(None, e)
        else:
            messages.success(request, f'Đã chuyển sang phòng {data["new_room"].room_number}. '
                                      f'Hợp đồng mới: {new_contract.display_code}.')
            return redirect('contract_detail', pk=new_contract.pk)
    return _action_page(request, contract, {
        'title': title, 'subtitle': subtitle, 'form': form, 'submit_label': 'Xác nhận chuyển phòng',
        'danger': False,
        'notice': 'Hợp đồng hiện tại sẽ kết thúc và một hợp đồng mới được lập ở phòng mới cho đúng những người này. '
                  'Tiền đặt cọc được giữ nguyên. Hóa đơn cũ vẫn thuộc phòng cũ.',
    })