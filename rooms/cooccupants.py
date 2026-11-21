from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Tenant
from accounts.permissions import is_owner
from accounts.identity_capture import IdentityCapture
from .cooccupant_forms import PROFILE_FIELDS
from .models import CoOccupantRequest as Request, Contract, ContractTenant, Room


def representative_contract(tenant):
    return Contract.objects.filter(status=Contract.Status.HIEU_LUC,
        contract_tenants__tenant=tenant, contract_tenants__is_representative=True
    ).select_related('room').order_by('-start_date', '-pk').first()


def _require_representative(contract, sender):
    if not ContractTenant.objects.filter(contract=contract, tenant=sender, is_representative=True).exists():
        raise PermissionDenied
    if contract.status != Contract.Status.HIEU_LUC:
        raise ValidationError('Hợp đồng đã kết thúc; không thể thêm người ở cùng vào hợp đồng này.')


def submit_request(contract, sender, data, previous_request=None, identity_form=None):
    with IdentityCapture() as capture:
        return _submit_request(contract, sender, data, previous_request, identity_form, capture)


@transaction.atomic
def _submit_request(contract, sender, data, previous_request, identity_form, capture):
    room = Room.objects.select_for_update().get(pk=contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=contract.pk)
    _require_representative(contract, sender)
    if previous_request:
        previous_request = Request.objects.select_for_update().get(pk=previous_request.pk)
        if previous_request.submitted_by_id != sender.pk or previous_request.contract_id != contract.pk:
            raise PermissionDenied
        if previous_request.status not in (Request.Status.REJECTED, Request.Status.CANCELLED):
            raise ValidationError('Chỉ gửi lại hồ sơ đã bị từ chối hoặc đã hủy.')
    values = {key: data.get(key, '') for key in PROFILE_FIELDS}
    values['date_of_birth'] = data.get('date_of_birth') or None
    values = {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}
    proposal = Request(contract=contract, submitted_by=sender, previous_request=previous_request, **values)
    proposal.full_clean()
    if ContractTenant.objects.filter(contract=contract, tenant__id_card_number=proposal.id_card_number).exists():
        raise ValidationError('Người có số giấy tờ này đã nằm trong hợp đồng.')
    if contract.contract_tenants.count() >= room.max_occupants:
        raise ValidationError('Phòng đã đủ số người tối đa. Vui lòng trao đổi với chủ trọ.')
    proposal.save()
    if identity_form is not None:
        proposal.identity_document = capture.save(identity_form, sender.user)
    elif previous_request:
        proposal.identity_document = previous_request.identity_document
    if proposal.identity_document_id:
        proposal.save(update_fields=['identity_document'])
    return proposal


@transaction.atomic
def cancel_request(proposal, sender):
    Room.objects.select_for_update().get(pk=proposal.contract.room_id)
    Contract.objects.select_for_update().get(pk=proposal.contract_id)
    proposal = Request.objects.select_for_update().get(pk=proposal.pk)
    if proposal.submitted_by_id != sender.pk:
        raise PermissionDenied
    if proposal.status != Request.Status.PENDING:
        raise ValidationError('Hồ sơ đã được xử lý; không thể hủy yêu cầu này.')
    proposal.status = Request.Status.CANCELLED
    proposal.save(update_fields=['status'])
    return proposal


@transaction.atomic
def review_request(proposal, owner, *, action, review_note='', confirm_information=False, reuse_existing=False):
    if not is_owner(owner):
        raise PermissionDenied
    room = Room.objects.select_for_update().get(pk=proposal.contract.room_id)
    contract = Contract.objects.select_for_update().get(pk=proposal.contract_id)
    proposal = Request.objects.select_for_update().select_related('submitted_by').get(pk=proposal.pk)
    if proposal.status != Request.Status.PENDING:
        raise ValidationError('Hồ sơ đã được xử lý. Vui lòng tải lại trang.')
    note = (review_note or '').strip()
    if len(note) > 1000 or action not in ('approve', 'reject'):
        raise ValidationError('Thao tác hoặc phản hồi không hợp lệ.')
    if action == 'reject':
        if not note:
            raise ValidationError('Cần ghi rõ nội dung cần bổ sung hoặc lý do từ chối.')
        proposal.status = Request.Status.REJECTED
    else:
        try:
            _require_representative(contract, proposal.submitted_by)
        except PermissionDenied:
            raise ValidationError('Người gửi không còn là đại diện hợp đồng này. Hãy yêu cầu đại diện hiện tại gửi hồ sơ mới.')
        proposal.full_clean()
        if not confirm_information:
            raise ValidationError('Cần đối chiếu và xác nhận hồ sơ trước khi thêm người ở cùng.')
        if contract.contract_tenants.count() >= room.max_occupants:
            raise ValidationError('Phòng đã đủ số người tối đa; không thể xác nhận thêm người ở cùng.')
        tenant = Tenant.objects.select_for_update().filter(id_card_number=proposal.id_card_number).first()
        if tenant and not reuse_existing:
            raise ValidationError('Số giấy tờ đã có trong hồ sơ người thuê. Hãy đối chiếu trước khi sử dụng hồ sơ hiện có.')
        if tenant is None:
            values = {key: getattr(proposal, key) for key in PROFILE_FIELDS if key != 'note'}
            try:
                with transaction.atomic():
                    tenant = Tenant(**values)
                    tenant.full_clean(validate_unique=False)
                    tenant.save()
            except IntegrityError:
                # Một chủ trọ khác vừa tạo hồ sơ cùng số giấy tờ; cần đối chiếu lại thay vì ghi đè.
                raise ValidationError('Hồ sơ người này vừa được tạo ở thao tác khác. Vui lòng tải lại để đối chiếu.')
        if ContractTenant.objects.filter(tenant=tenant, contract__status=Contract.Status.HIEU_LUC).exists():
            raise ValidationError('Người này đã thuộc một hợp đồng đang hiệu lực. Hãy kiểm tra hồ sơ hiện tại.')
        ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=False)
        if proposal.identity_document_id:
            document = proposal.identity_document
            if document.tenant_id not in (None, tenant.pk):
                raise ValidationError('Ảnh giấy tờ đang thuộc hồ sơ người khác. Hãy kiểm tra lại hồ sơ gửi duyệt.')
            document.tenant = tenant
            document.save(update_fields=['tenant'])
        proposal.status = Request.Status.APPROVED
        proposal.approved_tenant = tenant
    proposal.review_note = note
    proposal.reviewed_by = owner
    proposal.reviewed_at = timezone.now()
    proposal.save(update_fields=['status', 'approved_tenant', 'review_note', 'reviewed_by', 'reviewed_at'])
    return proposal
