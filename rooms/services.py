"""Nghiệp vụ hợp đồng: lập, gia hạn, trả phòng, chuyển phòng.
Mọi kiểm tra nằm ở đây để giao diện và test dùng chung một bộ luật."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing.models import Invoice, Payment
from billing.services import _money
from accounts.money import MAX_MONEY
from accounts.models import Tenant
from .models import CheckoutRecord, Contract, ContractRenewal, ContractTenant, DepositEntry, Room
from .appointment_schedule import lock_calendar


def money(amount):
    return f'{amount:,.0f}'.replace(',', '.')


def unpaid_invoices(contract):
    """Danh sách (hóa đơn, số còn nợ) của các hóa đơn chưa thu đủ."""
    result = []
    invoices = contract.invoices.exclude(status=Invoice.Status.DA_THANH_TOAN).prefetch_related('payments')
    for inv in invoices.order_by('year', 'month'):
        remaining = inv.total_amount - sum((p.amount for p in inv.payments.all() if not p.is_voided), Decimal('0'))
        if remaining > 0:
            result.append((inv, remaining))
    return result


def _unpaid_error(contract):
    unpaid = unpaid_invoices(contract)
    if not unpaid:
        return None
    total = sum(r for _, r in unpaid)
    return f'Còn {len(unpaid)} hóa đơn chưa thanh toán (tổng {money(total)} đ).'


def settlement_summary(contract):
    unpaid = unpaid_invoices(contract)
    debt = sum((remaining for _, remaining in unpaid), Decimal('0'))
    pending = contract.invoice_drafts.filter(invoice__isnull=True).order_by('year', 'month')
    pending_count = pending.count()
    held = contract.deposit_balance
    refunded = contract.deposit_entries.filter(kind=DepositEntry.Kind.REFUND).aggregate(
        total=Sum('amount'))['total'] or Decimal('0')
    refundable = max(held - debt, Decimal('0')) if not pending_count else Decimal('0')
    return {'unpaid': unpaid, 'debt': debt, 'pending_drafts': pending, 'pending_count': pending_count,
            'held': held, 'refunded': refunded, 'refundable': refundable,
            'settled': contract.status == Contract.Status.KET_THUC and not pending_count and debt == 0 and held == 0}


def _require_outstanding_ack(contract, accept_outstanding):
    summary = settlement_summary(contract)
    if not accept_outstanding and (summary['debt'] or summary['pending_count']):
        details = [_unpaid_error(contract)] if summary['debt'] else []
        if summary['pending_count']:
            details.append(f"Còn {summary['pending_count']} hóa đơn nháp chưa chốt.")
        raise ValidationError(details + ['Hãy xác nhận bàn giao và tiếp tục theo dõi các khoản chưa tất toán trên hợp đồng cũ.'])
    return summary


def _is_free(room):
    return room.status == Room.Status.TRONG and not room.contracts.filter(
        status=Contract.Status.HIEU_LUC).exists()

def is_free(room):
    """Phòng có đang trống và sẵn sàng cho thuê không."""
    return _is_free(room)

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
    if start_date and start_date > timezone.localdate():
        errors.append('Ngày nhận phòng không được ở tương lai. Chỉ lập hợp đồng hiệu lực khi bàn giao phòng.')
    if len({t.pk for t in tenants}) != len(tenants):
        errors.append('Danh sách người thuê bị trùng.')
    if deposit is not None and deposit < 0:
        errors.append('Tiền đặt cọc không được âm.')
    if deposit is not None and (deposit != int(deposit) or deposit > MAX_MONEY):
        errors.append('Tiền đặt cọc phải là số nguyên đồng và không vượt 99.999.999 đ.')
    return errors


@transaction.atomic
def create_contract(room, tenants, representative, start_date, end_date, deposit, *, monthly_rent=None,
                    initial_electric=None, initial_water=None, prorate_first_month=False,
                    service_ids=None, deposit_paid=0, deposit_method=DepositEntry.Method.CASH,
                    created_by=None, appointment_id=None):
    lock_calendar()
    room = Room.objects.select_for_update().get(pk=room.pk)
    from .appointment_services import settle_for_contract, validate_contract_source
    validate_contract_source(appointment_id, room)
    list(Tenant.objects.select_for_update().filter(pk__in=[t.pk for t in tenants]).order_by('pk'))
    errors = contract_errors(room, tenants, representative, start_date, end_date, deposit)
    if errors:
        raise ValidationError(errors)
    if (initial_electric is None) != (initial_water is None):
        raise ValidationError(['Hãy nhập đủ cả chỉ số điện và nước lúc bàn giao, hoặc để trống cả hai.'])
    contract = Contract(
        room=room, start_date=start_date, end_date=end_date, deposit=_money(deposit, 'Tiền cọc thỏa thuận'),
        monthly_rent=_money(room.price if monthly_rent is None else monthly_rent, 'Giá thuê thỏa thuận', positive=True),
        initial_electric=initial_electric, initial_water=initial_water,
        prorate_first_month=prorate_first_month, use_default_services=service_ids is None)
    contract.full_clean()
    contract.save()
    if service_ids is not None:
        from billing.models import Service
        ids = set(service_ids)
        if Service.objects.filter(pk__in=ids).count() != len(ids):
            raise ValidationError(['Một dịch vụ đã chọn không còn tồn tại. Vui lòng tải lại.'])
        contract.services.set(ids)
    for t in tenants:
        ContractTenant.objects.create(
            contract=contract, tenant=t, is_representative=(t == representative))
    if deposit_paid:
        receive_deposit(contract, amount=deposit_paid, occurred_on=start_date, method=deposit_method,
                        note='Thu cọc khi nhận phòng', created_by=created_by)
    settle_for_contract(contract, appointment_id)
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
    Room.objects.select_for_update().get(pk=contract.room_id)
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
    if checkout_date:
        if contract.invoices.filter(payments__paid_date__gt=checkout_date, payments__voided_at__isnull=True).exists():
            errors.append('Ngày trả phòng không được trước ngày thu tiền đã ghi nhận của hợp đồng.')
        if contract.deposit_entries.filter(occurred_on__gt=checkout_date).exists():
            errors.append('Ngày trả phòng không được trước giao dịch cọc đã ghi nhận.')
    return errors


@transaction.atomic
def checkout_contract(contract, checkout_date, *, deposit_deduction=0, deduction_reason='',
                      room_condition=Room.Status.TRONG, accept_outstanding=False,
                      expected_deposit_balance=None, created_by=None):
    Room.objects.select_for_update().get(pk=contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    errors = checkout_errors(contract, checkout_date)
    if errors:
        raise ValidationError(errors)
    summary = _require_outstanding_ack(contract, accept_outstanding)
    balance = contract.deposit_balance
    if expected_deposit_balance is not None and balance != expected_deposit_balance:
        raise ValidationError(['Số dư cọc đã thay đổi. Hãy tải lại trang và kiểm tra trước khi trả phòng.'])
    deduction = _money(deposit_deduction, 'Tiền khấu trừ cọc')
    if deduction > balance:
        raise ValidationError(['Tiền khấu trừ không được vượt số cọc thực tế đang giữ.'])
    if deduction and not deduction_reason.strip():
        raise ValidationError(['Cần ghi rõ lý do khấu trừ cọc, ví dụ hư hỏng hoặc thiếu tài sản bàn giao.'])
    if room_condition not in (Room.Status.TRONG, Room.Status.BAO_TRI):
        raise ValidationError(['Tình trạng phòng sau bàn giao không hợp lệ.'])
    if len(deduction_reason) > 500:
        raise ValidationError(['Ghi chú bàn giao tối đa 500 ký tự.'])
    if deduction:
        DepositEntry.objects.create(contract=contract, kind=DepositEntry.Kind.DEDUCT, amount=deduction,
                                     occurred_on=checkout_date, method=DepositEntry.Method.INTERNAL,
                                     note=deduction_reason.strip(), created_by=created_by)
    refund_due = max(balance - deduction - summary['debt'], Decimal('0')) if not summary['pending_count'] else None
    CheckoutRecord.objects.create(contract=contract, checkout_date=checkout_date, deposit_held=balance,
                                   deposit_deducted=deduction, deposit_refunded=0,
                                   debt_at_checkout=summary['debt'], drafts_at_checkout=summary['pending_count'],
                                   refund_due_at_checkout=refund_due,
                                   note=deduction_reason.strip(), room_condition=room_condition,
                                   created_by=created_by)
    contract.status = Contract.Status.KET_THUC
    contract.checkout_date = checkout_date
    contract.save(update_fields=['status', 'checkout_date'])   # phòng tự về "Còn trống"
    Room.objects.filter(pk=contract.room_id).update(status=room_condition)
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
    if transfer_date and contract.deposit_entries.filter(occurred_on__gt=transfer_date).exists():
        errors.append('Ngày chuyển phòng không được trước giao dịch cọc đã ghi nhận.')
    if transfer_date and contract.invoices.filter(payments__paid_date__gt=transfer_date, payments__voided_at__isnull=True).exists():
        errors.append('Ngày chuyển phòng không được trước giao dịch thu tiền đã ghi nhận.')
    return errors


@transaction.atomic
def transfer_contract(contract, new_room, transfer_date, new_end_date, *, initial_electric=None,
                      initial_water=None, accept_outstanding=False, transfer_deposit=True, created_by=None):
    """Kết thúc hợp đồng cũ rồi lập hợp đồng mới ở phòng mới cho đúng những người đó.
    Hóa đơn cũ vẫn thuộc phòng cũ nên lịch sử không bị lệch."""
    lock_calendar()
    list(Room.objects.select_for_update().filter(pk__in=[contract.room_id, new_room.pk]).order_by('pk'))
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    new_room = Room.objects.select_for_update().get(pk=new_room.pk)
    errors = transfer_errors(contract, new_room, transfer_date, new_end_date)
    if errors:
        raise ValidationError(errors)
    summary = _require_outstanding_ack(contract, accept_outstanding)
    people = list(contract.contract_tenants.select_related('tenant'))
    contract.status = Contract.Status.KET_THUC
    contract.checkout_date = transfer_date
    contract.save(update_fields=['status', 'checkout_date'])   # phòng cũ về "Còn trống"
    new_contract = Contract.objects.create(
        room=new_room, start_date=transfer_date, end_date=new_end_date,
        deposit=contract.deposit, previous_contract=contract, monthly_rent=new_room.price,
        initial_electric=initial_electric, initial_water=initial_water,
        use_default_services=contract.use_default_services,
        prorate_first_month=contract.prorate_first_month)
    if (initial_electric is None) != (initial_water is None):
        raise ValidationError(['Hãy nhập đủ chỉ số điện và nước của phòng mới.'])
    new_contract.full_clean()
    new_contract.services.set(contract.services.all())
    # Giữ lại phần bảo đảm cho nợ cũ; chưa chốt phí thì chưa xác định được phần dư.
    balance = summary['refundable'] if transfer_deposit else Decimal('0')
    if balance:
        DepositEntry.objects.create(contract=contract, kind=DepositEntry.Kind.TRANSFER_OUT,
                                     amount=balance, occurred_on=transfer_date,
                                     method=DepositEntry.Method.INTERNAL, related_contract=new_contract,
                                     note='Chuyển cọc khi chuyển phòng', created_by=created_by)
        DepositEntry.objects.create(contract=new_contract, kind=DepositEntry.Kind.TRANSFER_IN,
                                     amount=balance, occurred_on=transfer_date,
                                     method=DepositEntry.Method.INTERNAL, related_contract=contract,
                                     note='Nhận cọc từ hợp đồng phòng cũ', created_by=created_by)
    for ct in people:
        ContractTenant.objects.create(
            contract=new_contract, tenant=ct.tenant, is_representative=ct.is_representative)
    from .appointment_services import settle_for_contract
    settle_for_contract(new_contract)
    return new_contract


@transaction.atomic
def receive_deposit(contract, *, amount, occurred_on=None, method=DepositEntry.Method.CASH,
                     note='', reference=None, created_by=None):
    Room.objects.select_for_update().get(pk=contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    amount = _money(amount, 'Tiền thu cọc', positive=True)
    if reference:
        existing = DepositEntry.objects.filter(reference=reference).first()
        if existing:
            if existing.contract_id == contract.pk and existing.kind == DepositEntry.Kind.RECEIVE and existing.amount == amount:
                return existing
            raise ValidationError(['Mã giao dịch đã được dùng cho một nội dung khác.'])
    if contract.status != Contract.Status.HIEU_LUC:
        raise ValidationError(['Hợp đồng đã kết thúc, không thể thu thêm cọc.'])
    occurred_on = occurred_on or timezone.localdate()
    if not contract.start_date <= occurred_on <= timezone.localdate():
        raise ValidationError(['Ngày thu cọc phải từ ngày nhận phòng đến hôm nay.'])
    if contract.deposit_balance + amount > contract.deposit:
        raise ValidationError(['Tổng cọc đã thu không được vượt tiền cọc thỏa thuận trên hợp đồng.'])
    if method not in (DepositEntry.Method.CASH, DepositEntry.Method.BANK):
        raise ValidationError(['Chọn tiền mặt hoặc chuyển khoản để thu cọc.'])
    if len(note) > 500:
        raise ValidationError(['Ghi chú tối đa 500 ký tự.'])
    kwargs = {'reference': reference} if reference else {}
    return DepositEntry.objects.create(contract=contract, kind=DepositEntry.Kind.RECEIVE, amount=amount,
                                        occurred_on=occurred_on, method=method, note=note.strip(),
                                        created_by=created_by, **kwargs)


def _existing_deposit_action(reference, contract, kind, amount, *, payment_invoice=None):
    if reference is None:
        return None
    entry = DepositEntry.objects.select_related('payment').filter(reference=reference).first()
    if entry is None:
        return None
    if (entry.contract_id != contract.pk or entry.kind != kind or entry.amount != amount
            or (payment_invoice is not None and (not entry.payment_id or entry.payment.invoice_id != payment_invoice.pk))):
        raise ValidationError(['Mã giao dịch đã được sử dụng cho nội dung khác.'])
    return entry


def _deposit_action_date(contract, occurred_on, *, after_checkout=False):
    occurred_on = occurred_on or timezone.localdate()
    first = contract.checkout_date if after_checkout else contract.start_date
    if first is None or not first <= occurred_on <= timezone.localdate():
        raise ValidationError(['Ngày giao dịch phải từ ngày bàn giao đến hôm nay.' if after_checkout
                               else 'Ngày giao dịch phải nằm trong thời gian từ nhận phòng đến hôm nay.'])
    if contract.deposit_entries.filter(occurred_on__gt=occurred_on).exists():
        raise ValidationError(['Không ghi lùi ngày trước giao dịch cọc đã có. Hãy dùng ngày thực hiện giao dịch mới.'])
    return occurred_on


@transaction.atomic
def refund_deposit(contract, *, amount, occurred_on=None, method=DepositEntry.Method.CASH,
                    note='', reference=None, expected_deposit_balance=None, created_by=None):
    Room.objects.select_for_update().get(pk=contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    amount = _money(amount, 'Tiền cọc thực tế đã hoàn', positive=True)
    existing = _existing_deposit_action(reference, contract, DepositEntry.Kind.REFUND, amount)
    if existing:
        return existing
    if contract.status != Contract.Status.KET_THUC or not contract.checkout_date:
        raise ValidationError(['Hãy ghi nhận bàn giao phòng trước khi hoàn cọc.'])
    summary = settlement_summary(contract)
    if expected_deposit_balance is not None and expected_deposit_balance != summary['held']:
        raise ValidationError(['Số dư cọc đã thay đổi. Hãy tải lại trang để kiểm tra.'])
    if summary['pending_count']:
        raise ValidationError(['Còn hóa đơn nháp chưa chốt, chưa xác định được số cọc có thể hoàn.'])
    if amount > summary['refundable']:
        raise ValidationError(['Số tiền hoàn vượt phần cọc còn dư sau khi giữ lại công nợ chưa thanh toán.'])
    occurred_on = _deposit_action_date(contract, occurred_on, after_checkout=True)
    if method not in (DepositEntry.Method.CASH, DepositEntry.Method.BANK):
        raise ValidationError(['Chọn tiền mặt hoặc chuyển khoản để ghi nhận tiền đã hoàn.'])
    if len(note) > 500:
        raise ValidationError(['Ghi chú tối đa 500 ký tự.'])
    return DepositEntry.objects.create(contract=contract, kind=DepositEntry.Kind.REFUND, amount=amount,
                                        occurred_on=occurred_on, method=method, note=note.strip(),
                                        created_by=created_by, **({'reference': reference} if reference else {}))


@transaction.atomic
def apply_deposit_to_invoice(invoice, *, amount, occurred_on=None, note='', reference=None,
                              expected_deposit_balance=None, created_by=None):
    Room.objects.select_for_update().get(pk=invoice.contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=invoice.contract_id)
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    amount = _money(amount, 'Tiền cọc đối trừ', positive=True)
    existing = _existing_deposit_action(reference, contract, DepositEntry.Kind.PAY_INVOICE, amount,
                                         payment_invoice=invoice)
    if existing:
        return existing
    balance = contract.deposit_balance
    if expected_deposit_balance is not None and expected_deposit_balance != balance:
        raise ValidationError(['Số dư cọc đã thay đổi. Hãy tải lại trang để kiểm tra.'])
    if amount > balance:
        raise ValidationError(['Tiền đối trừ vượt số cọc thực tế đang giữ.'])
    occurred_on = _deposit_action_date(contract, occurred_on)
    if not note.strip():
        raise ValidationError(['Cần ghi rõ nội dung đã thống nhất với người thuê để đối trừ cọc.'])
    if len(note) > 500:
        raise ValidationError(['Ghi chú tối đa 500 ký tự.'])
    payment = Payment(invoice=invoice, amount=amount, paid_date=occurred_on,
                       method=Payment.Method.TU_COC, note=note.strip(), recorded_by=created_by)
    payment._from_deposit = True
    payment.full_clean()
    payment.save()
    return DepositEntry.objects.create(contract=contract, kind=DepositEntry.Kind.PAY_INVOICE,
                                        amount=amount, occurred_on=occurred_on, method=DepositEntry.Method.INTERNAL,
                                        note=note.strip(), payment=payment, created_by=created_by,
                                        **({'reference': reference} if reference else {}))
