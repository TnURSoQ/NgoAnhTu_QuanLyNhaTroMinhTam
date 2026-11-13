"""Nghiệp vụ hợp đồng: lập, gia hạn, trả phòng, chuyển phòng.
Mọi kiểm tra nằm ở đây để giao diện và test dùng chung một bộ luật."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from billing.models import Invoice
from .models import Contract, ContractRenewal, ContractTenant, Room


def money(amount):
    return f'{amount:,.0f}'.replace(',', '.')


def unpaid_invoices(contract):
    """Danh sách (hóa đơn, số còn nợ) của các hóa đơn chưa thu đủ."""
    result = []
    invoices = contract.invoices.exclude(status=Invoice.Status.DA_THANH_TOAN).prefetch_related('payments')
    for inv in invoices.order_by('year', 'month'):
        remaining = inv.total_amount - sum((p.amount for p in inv.payments.all()), Decimal('0'))
        if remaining > 0:
            result.append((inv, remaining))
    return result


def _unpaid_error(contract):
    unpaid = unpaid_invoices(contract)
    if not unpaid:
        return None
    total = sum(r for _, r in unpaid)
    return f'Còn {len(unpaid)} hóa đơn chưa thanh toán (tổng {money(total)} đ). Hãy thu đủ tiền trước.'


def _is_free(room):
    return room.status == Room.Status.TRONG and not room.contracts.filter(
        status=Contract.Status.HIEU_LUC).exists()


# ---------------- lập hợp đồng ----------------
def contract_errors(room, tenants, representative, start_date, end_date, deposit):
    errors = []
    if not _is_free(room):
        errors.append(f'Phòng {room.room_number} không còn trống.')
    if not tenants:
        errors.append('Hãy chọn ít nhất một người thuê.')
    elif representative is None:
        errors.append('Hãy chọn một người đại diện ký hợp đồng.')
    elif representative not in tenants:
        errors.append('Người đại diện phải nằm trong danh sách người thuê.')
    if tenants and len(tenants) > room.max_occupants:
        errors.append(f'Phòng {room.room_number} chỉ cho tối đa {room.max_occupants} người, '
                      f'bạn đang chọn {len(tenants)} người.')
    for t in tenants:
        current = ContractTenant.objects.filter(
            tenant=t, contract__status=Contract.Status.HIEU_LUC).select_related('contract__room').first()
        if current:
            errors.append(f'{t.full_name} đang thuê phòng {current.contract.room.room_number}.')
    if start_date and end_date and end_date < start_date:
        errors.append('Ngày kết thúc không được trước ngày bắt đầu.')
    if deposit is not None and deposit < 0:
        errors.append('Tiền đặt cọc không được âm.')
    return errors


@transaction.atomic
def create_contract(room, tenants, representative, start_date, end_date, deposit):
    errors = contract_errors(room, tenants, representative, start_date, end_date, deposit)
    if errors:
        raise ValidationError(errors)
    contract = Contract.objects.create(
        room=room, start_date=start_date, end_date=end_date, deposit=deposit)
    for t in tenants:
        ContractTenant.objects.create(
            contract=contract, tenant=t, is_representative=(t == representative))
    return contract


# ---------------- gia hạn ----------------
def renew_errors(contract, new_end_date):
    errors = []
    if contract.status != Contract.Status.HIEU_LUC:
        errors.append('Hợp đồng đã kết thúc nên không gia hạn được.')
    if new_end_date and new_end_date <= contract.end_date:
        errors.append('Ngày kết thúc mới phải sau ngày kết thúc hiện tại '
                      f'({contract.end_date:%d/%m/%Y}).')
    return errors


@transaction.atomic
def renew_contract(contract, new_end_date, note=''):
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    errors = renew_errors(contract, new_end_date)
    if errors:
        raise ValidationError(errors)
    ContractRenewal.objects.create(
        contract=contract, old_end_date=contract.end_date, new_end_date=new_end_date, note=note)
    contract.end_date = new_end_date
    contract.save(update_fields=['end_date'])
    return contract


# ---------------- trả phòng ----------------
def _date_errors(contract, the_date, label):
    errors = []
    today = timezone.localdate()
    if the_date and the_date > today:
        errors.append(f'{label} không được ở tương lai.')
    if the_date and the_date < contract.start_date:
        errors.append(f'{label} không được trước ngày bắt đầu hợp đồng ({contract.start_date:%d/%m/%Y}).')
    return errors


def checkout_errors(contract, checkout_date):
    errors = []
    if contract.status != Contract.Status.HIEU_LUC:
        errors.append('Hợp đồng này đã kết thúc.')
        return errors
    errors += _date_errors(contract, checkout_date, 'Ngày trả phòng')
    unpaid = _unpaid_error(contract)
    if unpaid:
        errors.append(unpaid)
    return errors


@transaction.atomic
def checkout_contract(contract, checkout_date):
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    errors = checkout_errors(contract, checkout_date)
    if errors:
        raise ValidationError(errors)
    contract.status = Contract.Status.KET_THUC
    contract.checkout_date = checkout_date
    contract.save(update_fields=['status', 'checkout_date'])   # phòng tự về "Còn trống"
    return contract


# ---------------- chuyển phòng ----------------
def transfer_errors(contract, new_room, transfer_date, new_end_date):
    errors = []
    if contract.status != Contract.Status.HIEU_LUC:
        errors.append('Hợp đồng này đã kết thúc.')
        return errors
    if new_room.pk == contract.room_id:
        errors.append('Hãy chọn một phòng khác với phòng hiện tại.')
    elif not _is_free(new_room):
        errors.append(f'Phòng {new_room.room_number} không còn trống.')
    people = contract.contract_tenants.count()
    if people > new_room.max_occupants:
        errors.append(f'Phòng {new_room.room_number} chỉ cho tối đa {new_room.max_occupants} người, '
                      f'hợp đồng đang có {people} người.')
    errors += _date_errors(contract, transfer_date, 'Ngày chuyển phòng')
    if transfer_date and new_end_date and new_end_date < transfer_date:
        errors.append('Ngày kết thúc hợp đồng mới không được trước ngày chuyển phòng.')
    unpaid = _unpaid_error(contract)
    if unpaid:
        errors.append(unpaid)
    return errors


@transaction.atomic
def transfer_contract(contract, new_room, transfer_date, new_end_date):
    """Kết thúc hợp đồng cũ rồi lập hợp đồng mới ở phòng mới cho đúng những người đó.
    Hóa đơn cũ vẫn thuộc phòng cũ nên lịch sử không bị lệch."""
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    new_room = Room.objects.select_for_update().get(pk=new_room.pk)
    errors = transfer_errors(contract, new_room, transfer_date, new_end_date)
    if errors:
        raise ValidationError(errors)
    people = list(contract.contract_tenants.select_related('tenant'))
    contract.status = Contract.Status.KET_THUC
    contract.checkout_date = transfer_date
    contract.save(update_fields=['status', 'checkout_date'])   # phòng cũ về "Còn trống"
    new_contract = Contract.objects.create(
        room=new_room, start_date=transfer_date, end_date=new_end_date,
        deposit=contract.deposit, previous_contract=contract)
    for ct in people:
        ContractTenant.objects.create(
            contract=new_contract, tenant=ct.tenant, is_representative=ct.is_representative)
    return new_contract