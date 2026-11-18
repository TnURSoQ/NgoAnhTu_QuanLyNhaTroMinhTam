from django.core.exceptions import ValidationError
from django.utils import timezone

from rooms.models import Contract
from .models import MaintenanceRequest as MR


TRANSITIONS = {
    MR.Status.DA_GUI: (MR.Status.DANG_XU_LY, MR.Status.DA_HUY),
    MR.Status.DANG_XU_LY: (MR.Status.HOAN_THANH, MR.Status.DA_HUY),
}


def active_contract(tenant):
    return (Contract.objects.filter(contract_tenants__tenant=tenant, status=Contract.Status.HIEU_LUC)
            .select_related('room').order_by('-start_date', '-pk').first())


def transition(maintenance, status, **updates):
    if status not in TRANSITIONS.get(maintenance.status, ()):
        raise ValidationError('Không thể chuyển yêu cầu sang trạng thái này.')
    changes = {key: value for key, value in updates.items() if key in ('owner_note', 'expected_done')}
    changes['status'] = status
    if status == MR.Status.HOAN_THANH:
        changes['resolved_at'] = timezone.now()
    # Kiểm tra trạng thái cùng lúc ghi để một thao tác cũ không ghi đè thao tác vừa xử lý.
    changed = MR.objects.filter(pk=maintenance.pk, status=maintenance.status).update(**changes)
    if not changed:
        raise ValidationError('Yêu cầu vừa được cập nhật. Vui lòng tải lại trang.')
    maintenance.refresh_from_db()
