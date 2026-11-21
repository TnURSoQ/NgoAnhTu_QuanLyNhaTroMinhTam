from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.permissions import is_owner
from billing.models import PaymentNotice
from rooms.models import ViewingAppointment, CoOccupantRequest
from .models import MaintenanceRequest as MR, NotificationRead
from .services import announcements_for, notification_feed_for, owner_notification_feed


READ_TOKEN_SALT = 'support.notification.read.v1'


def unread_count(user):
    if not user.is_authenticated or not user.pk:
        return 0
    if is_owner(user):
        return owner_notification_feed(user, unread_only=True).count()
    tenant = getattr(user, 'tenant_profile', None)
    if user.role == 'tenant' and tenant:
        return notification_feed_for(tenant, unread_only=True).count()
    return 0


def read_token(user, item):
    return signing.dumps({'user': user.pk, 'kind': item['notification_kind'], 'id': item['id'],
                          'version': item['notification_time'].isoformat()}, salt=READ_TOKEN_SALT)


def _read_target(user, kind, object_id):
    if is_owner(user):
        if kind == NotificationRead.Kind.OWNER_MAINTENANCE:
            item = get_object_or_404(MR, pk=object_id, status=MR.Status.DA_GUI)
            return item.created_at, reverse('maintenance_detail', args=[item.pk])
        if kind == NotificationRead.Kind.OWNER_APPOINTMENT:
            item = get_object_or_404(ViewingAppointment, pk=object_id, status=ViewingAppointment.Status.CHO_XAC_NHAN)
            return item.created_at, reverse('appointment_detail', args=[item.pk])
        if kind == NotificationRead.Kind.OWNER_TRANSFER:
            item = get_object_or_404(PaymentNotice, pk=object_id, status=PaymentNotice.Status.CHO_XAC_NHAN)
            return item.created_at, reverse('invoice_detail', args=[item.invoice_id])
        if kind == NotificationRead.Kind.OWNER_COOCCUPANT:
            item = get_object_or_404(CoOccupantRequest, pk=object_id, status=CoOccupantRequest.Status.PENDING,
                                     contract__status='hieu_luc')
            return item.created_at, reverse('cooccupant_review', args=[item.pk])
    tenant = getattr(user, 'tenant_profile', None)
    if user.role == 'tenant' and tenant:
        if kind == NotificationRead.Kind.ANNOUNCEMENT:
            item = get_object_or_404(announcements_for(tenant), pk=object_id)
            return item.updated_at, reverse('my_announcement_detail', args=[item.pk])
        if kind == NotificationRead.Kind.MAINTENANCE:
            item = get_object_or_404(MR.objects.filter(tenant=tenant).exclude(status=MR.Status.DA_GUI), pk=object_id)
            return item.updated_at, reverse('my_maintenance_detail', args=[item.pk])
        if kind == NotificationRead.Kind.COOCCUPANT_DECISION:
            item = get_object_or_404(CoOccupantRequest, pk=object_id, submitted_by=tenant,
                status__in=[CoOccupantRequest.Status.APPROVED, CoOccupantRequest.Status.REJECTED], reviewed_at__isnull=False)
            return item.reviewed_at, reverse('my_cooccupant_detail', args=[item.pk])
    raise PermissionDenied


def mark_read(user, token):
    try:
        payload = signing.loads(token, salt=READ_TOKEN_SALT, max_age=7 * 24 * 60 * 60)
        if not isinstance(payload, dict) or payload.get('user') != user.pk:
            raise ValueError
        kind, object_id = payload['kind'], payload['id']
        if kind not in NotificationRead.Kind.values or type(object_id) is not int or object_id <= 0:
            raise ValueError
        version = parse_datetime(payload['version'])
        if version is None or timezone.is_naive(version):
            raise ValueError
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise ValidationError('Thông báo đã thay đổi. Vui lòng mở lại bảng thông báo.')
    current_version, url = _read_target(user, kind, object_id)
    with transaction.atomic():
        state, _ = NotificationRead.objects.get_or_create(
            user=user, kind=kind, object_id=object_id, defaults={'version': version})
        # Yêu cầu cũ không được ghi đè lần đọc một bản cập nhật mới hơn.
        NotificationRead.objects.filter(pk=state.pk, version__lt=version).update(version=version, read_at=timezone.now())
    state.refresh_from_db(fields=['version'])
    return {'url': url, 'is_unread': state.version < current_version, 'unread_count': unread_count(user)}
