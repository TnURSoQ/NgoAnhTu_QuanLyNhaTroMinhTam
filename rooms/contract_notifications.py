"""Date-derived reminders work without cron and never write during GET requests."""
from datetime import timedelta

from django.db.models import Case, CharField, DateField, DateTimeField, F, OuterRef, Subquery, TextField, Value, When
from django.db.models.functions import Cast, Coalesce, Concat, Greatest
from django.utils import timezone

from accounts.permissions import is_owner
from support.services import _with_unread_state
from .models import Contract, ContractEvent, ContractRenewal


def _party_contracts(user):
    contracts = Contract.objects.all()
    if not user:
        return contracts.none()
    if is_owner(user):
        return contracts
    if user.is_authenticated and user.role == 'tenant':
        return contracts.filter(contract_tenants__tenant__user=user, contract_tenants__is_representative=True)
    return contracts.none()


def due_queryset(user):
    today = timezone.localdate()
    return _party_contracts(user).filter(status=Contract.Status.HIEU_LUC,
        end_date__lte=today + timedelta(days=30)).order_by().annotate(
        title=Case(When(end_date__lt=today, then=Value('Hợp đồng đã hết hạn – cần xử lý')),
            When(end_date__lte=today + timedelta(days=7), then=Value('Hợp đồng sắp hết hạn trong 7 ngày')),
            default=Value('Hợp đồng sắp hết hạn trong 30 ngày'), output_field=CharField()),
        reminder_stage_time=Case(
            When(end_date__lt=today, then=Cast('end_date', DateTimeField()) + timedelta(days=1)),
            When(end_date__lte=today + timedelta(days=7), then=Cast('end_date', DateTimeField()) - timedelta(days=7)),
            default=Cast('end_date', DateTimeField()) - timedelta(days=30), output_field=DateTimeField()),
        notification_content=Concat(Value('Phòng '), F('room__room_number'), Value(' · Hạn hợp đồng: '),
                                    Cast('end_date', CharField()), output_field=TextField())).annotate(
        # A short renewal can have an earlier 7-day milestone than the previous
        # expiry warning. The renewed term must become unread independently.
        notification_time=Greatest(F('reminder_stage_time'), Coalesce(Subquery(
            ContractRenewal.objects.filter(contract_id=OuterRef('pk')).order_by('-created_at', '-pk').values(
                'created_at')[:1]), F('reminder_stage_time'))))


def event_queryset(user):
    return ContractEvent.objects.filter(contract__in=_party_contracts(user),
        audience='owner' if is_owner(user) else 'tenant')


def feeds(user, *, owner, unread_only, fields):
    due = due_queryset(user)
    due = _with_unread_state(due, getattr(user, 'pk', None), 'contract_due', 'notification_time', unread_only).annotate(
        notification_kind=Value('contract_due', output_field=CharField()),
        notification_expected=Value(None, output_field=DateField()))
    events = _with_unread_state(event_queryset(user), getattr(user, 'pk', None), 'contract_event', 'created_at', unread_only).order_by().annotate(
        notification_kind=Value('contract_event', output_field=CharField()), notification_time=F('created_at'),
        notification_content=F('content'), notification_expected=Value(None, output_field=DateField()))
    if owner:
        due = due.annotate(target_id=F('pk'))
        events = events.annotate(target_id=F('contract_id'))
    else:
        # Tenant union has no target_id; resolve contract through event PK in the panel.
        due = due.annotate(notification_status=Value('', output_field=CharField()))
        events = events.annotate(notification_status=Value('', output_field=CharField()))
    return due.values(*fields), events.values(*fields)
