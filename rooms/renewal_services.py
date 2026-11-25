"""Two-party renewal and move-out intentions. Only acceptance changes the term."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import is_owner
from billing.services import _money, default_room_fee, period_dates
from .models import (Contract, ContractDocument, ContractEvent, ContractRenewal,
                     MoveOutNotice, RenewalProposal as Proposal, Room)

PENDING = (Proposal.Status.OWNER, Proposal.Status.TENANT)
OPEN_NOTICES = (MoveOutNotice.Status.PENDING, MoveOutNotice.Status.ACKNOWLEDGED)


def is_representative(user, contract):
    return bool(user.is_authenticated and user.role == 'tenant' and contract.contract_tenants.filter(
        tenant__user=user, is_representative=True).exists())


def _lock(contract):
    Room.objects.select_for_update().get(pk=contract.room_id)
    locked = Contract.objects.select_for_update().get(pk=contract.pk)
    if locked.status != Contract.Status.HIEU_LUC:
        raise ValidationError('Hợp đồng đã bàn giao phòng, không thể tiếp tục đề nghị này.')
    return locked


def event(contract, audience, title, content=''):
    return ContractEvent.objects.create(contract=contract, audience=audience, title=title,
        content=f'Phòng {contract.room.room_number} · {contract.display_code} · {content}')


def _validate_terms(contract, new_end_date, effective_date, monthly_rent, deposit):
    if not new_end_date or new_end_date <= max(contract.end_date, timezone.localdate()):
        raise ValidationError('Ngày kết thúc mới phải sau ngày kết thúc hiện tại và sau hôm nay.')
    if not effective_date or not contract.end_date < effective_date <= new_end_date:
        raise ValidationError('Ngày áp dụng phải sau hạn cũ và không sau hạn mới.')
    old_rent, old_deposit = contract.rent_on(contract.end_date), contract.deposit_on(contract.end_date)
    if effective_date < timezone.localdate() and (monthly_rent != old_rent or deposit != old_deposit):
        raise ValidationError('Không thay đổi giá thuê hoặc mức cọc lùi ngày. Hãy chọn ngày áp dụng từ hôm nay.')
    if monthly_rent != old_rent:
        for invoice in contract.invoices.all():
            _, last = period_dates(invoice.month, invoice.year)
            if last >= effective_date:
                raise ValidationError('Đã có hóa đơn phát hành từ ngày áp dụng. Chọn kỳ chưa phát hành; hóa đơn cũ được giữ nguyên.')
    return old_rent, old_deposit


@transaction.atomic
def propose(contract, user, *, expected_end_date, new_end_date, effective_date=None,
            monthly_rent=None, deposit=None, terms='', note='', replace_id=None, offline=False):
    contract = _lock(contract)
    owner = is_owner(user)
    if not owner and not is_representative(user, contract):
        raise PermissionDenied
    if offline and not owner:
        raise PermissionDenied
    if contract.end_date != expected_end_date:
        raise ValidationError('Thời hạn hợp đồng đã thay đổi. Hãy tải lại và kiểm tra đề nghị.')
    if contract.moveout_notices.filter(status__in=OPEN_NOTICES).exists():
        raise ValidationError('Đang có lịch dự kiến trả phòng. Người đại diện cần rút thông báo đó trước khi đề nghị gia hạn.')
    pending = contract.renewal_proposals.filter(status__in=PENDING).first()
    if pending and (not owner or pending.pk != replace_id):
        raise ValidationError('Đang có đề nghị chờ phản hồi. Hãy xử lý hoặc rút đề nghị hiện tại trước.')
    if replace_id and (not pending or pending.pk != replace_id):
        raise ValidationError('Đề nghị đã được xử lý. Hãy tải lại trang.')
    effective_date = effective_date or max(contract.end_date + timedelta(days=1), timezone.localdate())
    old_rent, old_deposit = contract.rent_on(contract.end_date), contract.deposit_on(contract.end_date)
    if not owner:
        # The representative asks to continue the existing financial terms.
        monthly_rent, deposit = old_rent, old_deposit
        terms = ''
    monthly_rent = _money(old_rent if monthly_rent is None else monthly_rent, 'Giá thuê', positive=True)
    deposit = _money(old_deposit if deposit is None else deposit, 'Cọc thỏa thuận')
    _validate_terms(contract, new_end_date, effective_date, monthly_rent, deposit)
    if len(terms) > 5000 or len(note) > 1000:
        raise ValidationError('Điều khoản tối đa 5.000 ký tự, lời nhắn tối đa 1.000 ký tự.')
    if pending:
        pending.status = Proposal.Status.SUPERSEDED
        pending.responded_at, pending.responded_by = timezone.now(), user
        pending.response_note = 'Chủ trọ gửi đề nghị thay thế; cần người thuê xác nhận lại.'
        pending.save(update_fields=['status', 'responded_at', 'responded_by', 'response_note'])
    proposal = Proposal.objects.create(contract=contract, old_end_date=contract.end_date,
        new_end_date=new_end_date, effective_date=effective_date, old_rent=old_rent,
        monthly_rent=monthly_rent, old_deposit=old_deposit, deposit=deposit,
        terms=terms.strip(), note=note.strip(), created_by=user,
        base_terms={key: getattr(contract, key) for key in ('payment_terms', 'renewal_terms', 'checkout_terms')},
        source=Proposal.Source.OFFLINE if offline else (Proposal.Source.OWNER if owner else Proposal.Source.TENANT),
        status=Proposal.Status.TENANT if owner else Proposal.Status.OWNER)
    if not offline:
        event(contract, 'tenant' if owner else 'owner', 'Đề nghị gia hạn hợp đồng mới',
              f'{proposal.display_code} · đề nghị đến {new_end_date:%d/%m/%Y}.')
    return proposal


def _apply(contract, proposal, user):
    if contract.end_date != proposal.old_end_date:
        raise ValidationError('Hạn hợp đồng đã thay đổi. Đề nghị này không còn phù hợp.')
    old_rent, old_deposit = _validate_terms(contract, proposal.new_end_date, proposal.effective_date,
                                           proposal.monthly_rent, proposal.deposit)
    if (old_rent, old_deposit) != (proposal.old_rent, proposal.old_deposit):
        raise ValidationError('Điều khoản gốc đã thay đổi. Cần gửi lại đề nghị để hai bên xác nhận.')
    if any(getattr(contract, key) != value for key, value in proposal.base_terms.items()):
        raise ValidationError('Điều khoản hợp đồng đã thay đổi. Cần gửi đề nghị mới để xác nhận lại.')
    proposal.status = Proposal.Status.ACCEPTED
    proposal.responded_by, proposal.responded_at = user, timezone.now()
    proposal.save(update_fields=['status', 'responded_by', 'responded_at', 'response_note'])
    ContractRenewal.objects.create(contract=contract, old_end_date=contract.end_date,
        new_end_date=proposal.new_end_date, note=proposal.note[:255], proposal=proposal)
    contract.end_date = proposal.new_end_date
    contract.save(update_fields=['end_date'])
    # Existing issued invoices are immutable. Refresh only untouched default rents
    # on unissued drafts; retain manually negotiated draft amounts for owner review.
    updated = retained = 0
    if proposal.monthly_rent != old_rent:
        for draft in contract.invoice_drafts.select_for_update().filter(invoice__isnull=True):
            _, last = period_dates(draft.month, draft.year)
            if last < proposal.effective_date:
                continue
            was_default = draft.room_fee == _old_default(contract, draft.month, draft.year, proposal)
            if was_default:
                draft.room_fee = default_room_fee(contract, draft.month, draft.year)
                draft.revision += 1
                draft.save(update_fields=['room_fee', 'revision', 'updated_at'])
                updated += 1
            else:
                retained += 1
    content = f'{proposal.display_code} · đến {proposal.new_end_date:%d/%m/%Y}.'
    if updated or retained:
        content += f' Cập nhật {updated} tiền phòng nháp; {retained} nháp đã sửa riêng cần chủ trọ kiểm tra.'
    event(contract, 'owner', 'Đã thống nhất gia hạn hợp đồng', content)
    event(contract, 'tenant', 'Đã thống nhất gia hạn hợp đồng', content)
    return proposal


def _old_default(contract, month, year, proposal):
    # Same day-based calculation, excluding the newly accepted proposal.
    return default_room_fee(contract, month, year, exclude_proposal=proposal.pk)


@transaction.atomic
def respond(proposal, user, action, note=''):
    contract = _lock(proposal.contract)
    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if not proposal.pending:
        raise ValidationError('Đề nghị đã được xử lý. Hãy tải lại trang.')
    owner = is_owner(user)
    representative = is_representative(user, contract)
    if not owner and not representative:
        raise PermissionDenied
    if action == 'withdraw':
        if proposal.created_by_id != user.pk:
            raise PermissionDenied
        proposal.status = Proposal.Status.WITHDRAWN
    elif action in ('accept', 'reject'):
        if (proposal.status == Proposal.Status.OWNER and not owner) or (
                proposal.status == Proposal.Status.TENANT and not representative):
            raise PermissionDenied
        if action == 'accept':
            if len(note) > 1000:
                raise ValidationError('Phản hồi tối đa 1.000 ký tự.')
            proposal.response_note = note.strip()
            return _apply(contract, proposal, user)
        proposal.status = Proposal.Status.REJECTED
    else:
        raise ValidationError('Thao tác không hợp lệ.')
    if len(note) > 1000:
        raise ValidationError('Phản hồi tối đa 1.000 ký tự.')
    proposal.response_note = note.strip()
    proposal.responded_at, proposal.responded_by = timezone.now(), user
    proposal.save(update_fields=['status', 'response_note', 'responded_at', 'responded_by'])
    event(contract, 'tenant' if owner else 'owner', proposal.get_status_display(),
          f'{proposal.display_code} · {proposal.response_note}')
    return proposal


def save_document(contract, user, upload, *, title, kind, proposal=None):
    from .renewal_forms import validate_document
    if not is_owner(user):
        raise PermissionDenied
    if kind not in ContractDocument.Kind.values or not title.strip() or len(title) > 150:
        raise ValidationError('Tên hoặc loại tài liệu không hợp lệ.')
    if proposal and (proposal.contract_id != contract.pk or kind != ContractDocument.Kind.ANNEX):
        raise ValidationError('Phụ lục phải thuộc đúng lần gia hạn của hợp đồng này.')
    validate_document(upload)
    document = ContractDocument(contract=contract, uploaded_by=user, title=title, kind=kind, proposal=proposal)
    try:
        document.file.save(upload.name, upload, save=False)
        document.save()
    except Exception:
        if document.file.name:
            document.file.delete(save=False)
        raise
    return document


def record_offline(contract, user, upload, **terms):
    document = None
    try:
        with transaction.atomic():
            proposal = propose(contract, user, offline=True, **terms)
            document = save_document(proposal.contract, user, upload, title=f'Phụ lục {proposal.display_code}',
                                     kind=ContractDocument.Kind.ANNEX, proposal=proposal)
            _apply(proposal.contract, proposal, user)
            return proposal
    except Exception:
        if document:
            document.file.delete(save=False)
        raise


@transaction.atomic
def notify_moveout(contract, user, planned_date, reason=''):
    contract = _lock(contract)
    if not is_representative(user, contract):
        raise PermissionDenied
    if planned_date < max(timezone.localdate(), contract.start_date):
        raise ValidationError('Ngày dự kiến trả phòng phải từ hôm nay trở đi.')
    if len(reason) > 1000:
        raise ValidationError('Lời nhắn tối đa 1.000 ký tự.')
    if contract.moveout_notices.filter(status__in=OPEN_NOTICES).exists():
        raise ValidationError('Đã có thông báo dự kiến trả phòng. Hãy rút thông báo cũ trước khi gửi lại.')
    if contract.renewal_proposals.filter(status__in=PENDING).exists():
        raise ValidationError('Đang có đề nghị gia hạn. Hãy rút hoặc xử lý đề nghị đó trước khi báo trả phòng.')
    notice = MoveOutNotice.objects.create(contract=contract, submitted_by=user,
                                         planned_date=planned_date, reason=reason.strip())
    event(contract, 'owner', 'Người thuê dự kiến trả phòng', f'Ngày {planned_date:%d/%m/%Y} · {reason}')
    return notice


@transaction.atomic
def respond_moveout(notice, user, action, note=''):
    contract = _lock(notice.contract)
    notice = MoveOutNotice.objects.select_for_update().get(pk=notice.pk)
    if notice.status not in OPEN_NOTICES:
        raise ValidationError('Thông báo đã được xử lý. Hãy tải lại trang.')
    if action == 'cancel':
        if not is_representative(user, contract):
            raise PermissionDenied
        notice.status = MoveOutNotice.Status.CANCELLED
        audience, title = 'owner', 'Người thuê đã rút dự kiến trả phòng'
    elif action == 'acknowledge':
        if not is_owner(user):
            raise PermissionDenied
        if notice.status != MoveOutNotice.Status.PENDING:
            raise ValidationError('Lịch dự kiến này đã được chủ trọ ghi nhận.')
        notice.status = MoveOutNotice.Status.ACKNOWLEDGED
        audience, title = 'tenant', 'Chủ trọ đã ghi nhận lịch dự kiến trả phòng'
    else:
        raise ValidationError('Thao tác không hợp lệ.')
    if len(note) > 1000:
        raise ValidationError('Phản hồi tối đa 1.000 ký tự.')
    notice.response_note, notice.responded_by, notice.responded_at = note.strip(), user, timezone.now()
    notice.save(update_fields=['status', 'response_note', 'responded_by', 'responded_at'])
    event(contract, audience, title, f'Ngày {notice.planned_date:%d/%m/%Y} · {note}')
    return notice


def close_pending_intentions(contract):
    """Called only inside the real checkout transaction, also for transfers."""
    contract.moveout_notices.filter(status__in=OPEN_NOTICES).update(status=MoveOutNotice.Status.COMPLETED)
    contract.renewal_proposals.filter(status__in=PENDING).update(status=Proposal.Status.WITHDRAWN,
        responded_at=timezone.now(), response_note='Hợp đồng đã bàn giao phòng.')


@transaction.atomic
def record_terms(contract, user, data):
    if not is_owner(user):
        raise PermissionDenied
    contract = _lock(contract)
    if contract.renewal_proposals.filter(status__in=PENDING).exists():
        raise ValidationError('Hãy xử lý hoặc rút đề nghị gia hạn đang chờ trước khi sửa điều khoản đã lưu.')
    fields = ('payment_terms', 'renewal_terms', 'checkout_terms')
    changes = []
    for key in fields:
        new = data[key].strip()
        if len(new) > 5000:
            raise ValidationError('Mỗi điều khoản tối đa 5.000 ký tự.')
        if getattr(contract, key) != new:
            changes.append(f'{contract._meta.get_field(key).verbose_name}: {getattr(contract, key) or "Chưa ghi nhận"} → {new or "Chưa ghi nhận"}')
        setattr(contract, key, new)
    contract.save(update_fields=fields)
    if changes:
        for audience in ('owner', 'tenant'):
            event(contract, audience, 'Cập nhật điều khoản theo tài liệu đã thỏa thuận', '\n'.join(changes))
    return contract
