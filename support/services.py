from django.core.exceptions import ValidationError
from django.utils import timezone

from rooms.models import Contract, CoOccupantRequest
from .models import MaintenanceRequest as MR


def announcements_for(tenant):
    from django.db.models import Q
    from .models import Announcement
    room_ids = Contract.objects.filter(
        contract_tenants__tenant=tenant, status=Contract.Status.HIEU_LUC).values('room_id')
    if not room_ids.exists():
        return Announcement.objects.none()
    return Announcement.objects.filter(is_active=True).filter(
        Q(audience=Announcement.Audience.ALL) |
        Q(audience=Announcement.Audience.ROOMS, rooms__in=room_ids)).distinct()


def _with_unread_state(queryset, user_id, kind, time_field, unread_only):
    from django.db.models import Exists, OuterRef
    from .models import NotificationRead
    reads = NotificationRead.objects.filter(
        user_id=user_id, kind=kind, object_id=OuterRef('pk'), version__gte=OuterRef(time_field))
    queryset = queryset.annotate(is_unread=~Exists(reads))
    return queryset.filter(is_unread=True) if unread_only else queryset


def notification_feed_for(tenant, unread_only=False):
    from django.db.models import Case, CharField, DateField, F, TextField, Value, When
    fields = ('id', 'title', 'notification_kind', 'notification_time',
              'notification_content', 'notification_status', 'notification_expected', 'is_unread')
    announcements = _with_unread_state(announcements_for(tenant), tenant.user_id,
                                     'announcement', 'updated_at', unread_only).order_by().annotate(
        notification_kind=Value('announcement', output_field=CharField()),
        notification_time=F('updated_at'), notification_content=F('content'),
        notification_status=Value('', output_field=CharField()),
        notification_expected=Value(None, output_field=DateField()),
    ).values(*fields)
    replies = _with_unread_state(MR.objects.filter(tenant=tenant).exclude(status=MR.Status.DA_GUI),
                               tenant.user_id, 'maintenance', 'updated_at', unread_only).order_by().annotate(
        notification_kind=Value('maintenance', output_field=CharField()),
        notification_time=F('updated_at'), notification_content=F('owner_note'),
        notification_status=F('status'), notification_expected=F('expected_done'),
    ).values(*fields)
    from django.db.models.functions import Concat
    decisions = _with_unread_state(CoOccupantRequest.objects.filter(submitted_by=tenant,
        status__in=[CoOccupantRequest.Status.APPROVED, CoOccupantRequest.Status.REJECTED], reviewed_at__isnull=False),
        tenant.user_id, 'cooccupant_decision', 'reviewed_at', unread_only).order_by().annotate(
        title=Concat(Value('Hồ sơ người ở cùng: '), F('full_name')),
        notification_kind=Value('cooccupant_decision', output_field=CharField()),
        notification_time=F('reviewed_at'), notification_content=F('review_note'),
        notification_status=F('status'), notification_expected=Value(None, output_field=DateField()),
    ).values(*fields)
    from billing.models import Payment
    from django.db.models.functions import Cast
    corrections = _with_unread_state(Payment.objects.filter(invoice__contract__contract_tenants__tenant=tenant,
        voided_at__isnull=False), tenant.user_id, 'payment_correction', 'voided_at', unread_only).order_by().annotate(
        title=Case(When(replacement__isnull=False, then=Value('Khoản thanh toán đã được điều chỉnh')),
                   default=Value('Khoản thanh toán đã hủy ghi nhận'), output_field=CharField()),
        notification_kind=Value('payment_correction', output_field=CharField()), notification_time=F('voided_at'),
        notification_content=Concat(Value('Giao dịch #'), Cast('pk', CharField()), Value(' · '), F('void_reason'), output_field=TextField()),
        notification_status=Value('', output_field=CharField()), notification_expected=Value(None, output_field=DateField()),
    ).values(*fields)
    from rooms.contract_notifications import feeds
    due, events = feeds(tenant.user, owner=False, unread_only=unread_only, fields=fields)
    return announcements.union(replies, decisions, corrections, due, events, all=True).order_by('-notification_time', '-id', 'notification_kind')


TRANSITIONS = {
    MR.Status.DA_GUI: (MR.Status.DANG_XU_LY, MR.Status.DA_HUY),
    MR.Status.DANG_XU_LY: (MR.Status.HOAN_THANH, MR.Status.DA_HUY),
}


def owner_notification_feed(user, unread_only=False):
    from django.db.models import Case, CharField, DateField, F, TextField, Value, When
    from django.db.models.functions import Concat
    from billing.models import PaymentNotice
    from rooms.models import ViewingAppointment

    fields = ('id', 'title', 'notification_kind', 'notification_time',
              'notification_content', 'notification_expected', 'target_id', 'is_unread')
    repairs = _with_unread_state(MR.objects.filter(status=MR.Status.DA_GUI), user.pk,
                               'owner_maintenance', 'created_at', unread_only).order_by().annotate(
        notification_kind=Value('owner_maintenance', output_field=CharField()),
        notification_time=F('created_at'),
        notification_content=Concat(Value('Phòng '), F('room__room_number'), Value(' · '),
                                    F('tenant__full_name'), output_field=TextField()),
        notification_expected=Value(None, output_field=DateField()), target_id=F('pk'),
    ).values(*fields)
    appointments = _with_unread_state(
        ViewingAppointment.objects.filter(status=ViewingAppointment.Status.CHO_XAC_NHAN), user.pk,
        'owner_appointment', 'created_at', unread_only).order_by().annotate(
        title=Value('Lịch hẹn xem phòng mới', output_field=CharField()),
        notification_kind=Value('owner_appointment', output_field=CharField()),
        notification_time=F('created_at'),
        notification_content=Concat(Value('Phòng '), F('room__room_number'), Value(' · '),
                                    F('visitor_name'), output_field=TextField()),
        notification_expected=F('appointment_date'), target_id=F('pk'),
    ).values(*fields)
    cancellations = _with_unread_state(ViewingAppointment.objects.filter(status=ViewingAppointment.Status.HUY,
        cancelled_by=ViewingAppointment.CancelledBy.GUEST, cancelled_at__isnull=False), user.pk,
        'owner_appointment_cancel', 'cancelled_at', unread_only).order_by().annotate(
        title=Value('Khách đã hủy lịch xem phòng', output_field=CharField()),
        notification_kind=Value('owner_appointment_cancel', output_field=CharField()),
        notification_time=F('cancelled_at'),
        notification_content=Concat(Value('Phòng '), F('room__room_number'), Value(' · '), F('visitor_name'),
            Value(' · '), Case(When(cancellation_reason='', then=Value('Không ghi lý do')),
                               default=F('cancellation_reason'), output_field=TextField()), output_field=TextField()),
        notification_expected=F('appointment_date'), target_id=F('pk'),
    ).values(*fields)
    transfers = _with_unread_state(
        PaymentNotice.objects.filter(status=PaymentNotice.Status.CHO_XAC_NHAN), user.pk,
        'owner_transfer', 'created_at', unread_only).order_by().annotate(
        title=Value('Báo chuyển khoản chờ xác nhận', output_field=CharField()),
        notification_kind=Value('owner_transfer', output_field=CharField()),
        notification_time=F('created_at'),
        notification_content=Concat(Value('Phòng '), F('invoice__contract__room__room_number'), Value(' · '),
                                    F('tenant__full_name'), output_field=TextField()),
        notification_expected=Value(None, output_field=DateField()), target_id=F('invoice_id'),
    ).values(*fields)
    cooccupants = _with_unread_state(CoOccupantRequest.objects.filter(status=CoOccupantRequest.Status.PENDING,
        contract__status=Contract.Status.HIEU_LUC), user.pk, 'owner_cooccupant', 'created_at', unread_only).order_by().annotate(
        title=Concat(Value('Người ở cùng chờ xác nhận: '), F('full_name')),
        notification_kind=Value('owner_cooccupant', output_field=CharField()),
        notification_time=F('created_at'),
        notification_content=Concat(Value('Phòng '), F('contract__room__room_number'), Value(' · '),
                                    F('submitted_by__full_name'), output_field=TextField()),
        notification_expected=Value(None, output_field=DateField()), target_id=F('pk'),
    ).values(*fields)
    from rooms.contract_notifications import feeds
    due, events = feeds(user, owner=True, unread_only=unread_only, fields=fields)
    return repairs.union(appointments, cancellations, transfers, cooccupants, due, events, all=True).order_by('-notification_time', '-id', 'notification_kind')


def active_contract(tenant):
    return (Contract.objects.filter(contract_tenants__tenant=tenant, status=Contract.Status.HIEU_LUC)
            .select_related('room').order_by('-start_date', '-pk').first())


def transition(maintenance, status, **updates):
    if status not in TRANSITIONS.get(maintenance.status, ()):
        raise ValidationError('Không thể chuyển yêu cầu sang trạng thái này.')
    changes = {key: value for key, value in updates.items() if key in ('owner_note', 'expected_done')}
    changes['status'] = status
    changes['updated_at'] = timezone.now()
    if status == MR.Status.HOAN_THANH:
        changes['resolved_at'] = timezone.now()
    # Kiểm tra trạng thái cùng lúc ghi để một thao tác cũ không ghi đè thao tác vừa xử lý.
    changed = MR.objects.filter(pk=maintenance.pk, status=maintenance.status).update(**changes)
    if not changed:
        raise ValidationError('Yêu cầu vừa được cập nhật. Vui lòng tải lại trang.')
    maintenance.refresh_from_db()
