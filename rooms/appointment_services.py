from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AppointmentEmail as Mail, Contract, Room, ViewingAppointment as VA
from .appointment_emails import queue_email
from .appointment_schedule import has_started, lock_calendar, validate_start


TRANSITIONS = {
    VA.Status.CHO_XAC_NHAN: [(VA.Status.DA_XAC_NHAN, 'Xác nhận lịch hẹn', 'btn-primary'),
                             (VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
    VA.Status.DA_XAC_NHAN: [(VA.Status.DA_XEM, 'Khách đã xem phòng', 'btn-primary'),
                            (VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
    VA.Status.DA_XEM: [(VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
}
STATUS_EVENTS = {VA.Status.DA_XAC_NHAN: Mail.Event.CONFIRMED, VA.Status.HUY: Mail.Event.CANCELLED,
                 VA.Status.DA_XEM: Mail.Event.VISITED}


def _available(room):
    from .services import is_free
    if not is_free(room):
        raise ValidationError('Phòng không còn sẵn sàng cho thuê. Hãy hủy lịch có lý do hoặc trao đổi với khách về phòng khác.')


@transaction.atomic
def book_appointment(room, data):
    lock_calendar()
    room = Room.objects.select_for_update().get(pk=room.pk)
    _available(room)
    from .public_forms import BookingForm
    # Check duplicate/limit rules under the same lock, including simultaneous posts.
    form = BookingForm(data, room=room)
    if not form.is_valid():
        raise ValidationError(form.errors.as_data())
    appointment = VA.objects.create(room=room, **{key: form.cleaned_data[key] for key in (
        'visitor_name', 'visitor_phone', 'visitor_email', 'appointment_date', 'slot', 'note')})
    queue_email(appointment, Mail.Event.BOOKED)
    return appointment


@transaction.atomic
def change_status(pk, new_status, note='', *, start_time=None):
    lock_calendar()
    appointment = VA.objects.select_for_update().select_related('room').get(pk=pk)
    if new_status == appointment.status:
        return appointment, False
    if new_status not in {s for s, _, _ in TRANSITIONS.get(appointment.status, [])}:
        raise ValidationError('Không thể chuyển lịch hẹn sang trạng thái này. Chốt thuê được ghi nhận khi lập hợp đồng thực tế.')
    note = note.strip()
    if len(note) > 255:
        raise ValidationError('Lời nhắn tối đa 255 ký tự.')
    if new_status == VA.Status.HUY and not note:
        raise ValidationError('Vui lòng nhập lý do hủy để khách nhận được thông tin rõ ràng.')
    if new_status == VA.Status.HUY:
        appointment.cancelled_by = VA.CancelledBy.OWNER
        appointment.cancelled_at = timezone.now()
        appointment.cancellation_reason = note
    if new_status == VA.Status.DA_XEM and not has_started(appointment):
        raise ValidationError('Chưa tới giờ hẹn, chưa thể ghi nhận khách đã xem phòng.')
    if new_status == VA.Status.DA_XAC_NHAN:
        _available(appointment.room)
        appointment.start_time = validate_start(appointment.appointment_date, appointment.slot, start_time, pk)
    appointment.status = new_status
    if note:
        appointment.owner_note = note
    appointment.save(update_fields=['status', 'owner_note', 'start_time', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])
    queue_email(appointment, STATUS_EVENTS[new_status])
    return appointment, True


@transaction.atomic
def cancel_by_guest(code, reason=''):
    lock_calendar()
    appointment = VA.objects.select_for_update().select_related('room').get(code=code.strip().upper())
    if appointment.status == VA.Status.HUY:
        return appointment, False
    if not appointment.can_guest_cancel:
        raise ValidationError('Chỉ có thể tự hủy lịch đang chờ xác nhận hoặc đã xác nhận; lịch đã xem/chốt thuê không thể hủy tại đây.')
    reason = (reason or '').strip()
    if len(reason) > 255:
        raise ValidationError('Lý do hủy tối đa 255 ký tự.')
    appointment.status = VA.Status.HUY
    appointment.cancelled_by = VA.CancelledBy.GUEST
    appointment.cancelled_at = timezone.now()
    appointment.cancellation_reason = reason
    appointment.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])
    # The owner bell is derived from these committed fields; no network call is needed.
    queue_email(appointment, Mail.Event.CANCELLED)
    return appointment, True


@transaction.atomic
def reschedule(pk, data):
    lock_calendar()
    appointment = VA.objects.select_for_update().select_related('room').get(pk=pk)
    if appointment.status not in (VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN):
        raise ValidationError('Lịch hẹn này không đổi ngày được nữa.')
    _available(appointment.room)
    day, slot = data['appointment_date'], data['slot']
    resolving_legacy = (appointment.start_time is None and
                        (day, slot) == (appointment.appointment_date, appointment.slot))
    start = validate_start(day, slot, data.get('start_time'), pk, resolve_legacy=resolving_legacy) if appointment.status == VA.Status.DA_XAC_NHAN else None
    if appointment.status == VA.Status.CHO_XAC_NHAN:
        from .appointment_schedule import request_time_available
        if not request_time_available(day, slot):
            raise ValidationError('Buổi hẹn đã qua. Hãy chọn buổi hoặc ngày khác.')
    if (appointment.appointment_date, appointment.slot, appointment.start_time) == (day, slot, start):
        return appointment, False
    previous = appointment.schedule_label
    appointment.appointment_date, appointment.slot, appointment.start_time = day, slot, start
    if data.get('owner_note'):
        appointment.owner_note = data['owner_note']
    appointment.save(update_fields=['appointment_date', 'slot', 'start_time', 'owner_note'])
    queue_email(appointment, Mail.Event.RESCHEDULED, previous_schedule=previous)
    return appointment, True


@transaction.atomic
def update_email(pk, email):
    lock_calendar()
    appointment = VA.objects.select_for_update().select_related('room').get(pk=pk)
    local, domain = email.rsplit('@', 1)
    email = local + '@' + domain.lower()
    if appointment.visitor_email == email:
        return appointment, False
    appointment.visitor_email = email
    appointment.save(update_fields=['visitor_email'])
    queue_email(appointment, Mail.Event.DETAILS)
    return appointment, True


def validate_contract_source(pk, room):
    if not pk:
        return None
    appointment = VA.objects.select_for_update().filter(pk=pk, room=room).first()
    if not appointment or appointment.status not in (VA.Status.DA_XAC_NHAN, VA.Status.DA_XEM) or appointment.contract_id:
        raise ValidationError('Lịch nguồn phải thuộc phòng này, đã xác nhận/đã xem và chưa chuyển thành hợp đồng.')
    return appointment


@transaction.atomic
def settle_for_contract(contract, appointment_id=None):
    lock_calendar()
    if contract.status != Contract.Status.HIEU_LUC:
        raise ValidationError('Chỉ xử lý lịch xem khi hợp đồng đã có hiệu lực.')
    source = validate_contract_source(appointment_id, contract.room) if appointment_id else None
    if source:
        source.status, source.contract = VA.Status.DA_CHOT, contract
        source.save(update_fields=['status', 'contract'])
        queue_email(source, Mail.Event.LEASED)
    now = timezone.localtime()
    upcoming = Q(appointment_date__gt=now.date()) | Q(appointment_date=now.date(), status=VA.Status.CHO_XAC_NHAN)
    upcoming |= Q(appointment_date=now.date(), start_time__gte=now.time().replace(tzinfo=None))
    for appointment in VA.objects.select_for_update().select_related('room').filter(
            upcoming, room=contract.room, status__in=[VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN]).order_by('pk'):
        appointment.status = VA.Status.HUY
        appointment.cancelled_by = VA.CancelledBy.SYSTEM
        appointment.cancelled_at = timezone.now()
        appointment.owner_note = 'Phòng đã có người thuê và được lập hợp đồng. Nhà trọ xin lỗi vì không thể tiếp tục lịch xem; bạn có thể chọn phòng khác.'
        appointment.cancellation_reason = appointment.owner_note
        appointment.save(update_fields=['status', 'owner_note', 'cancelled_by', 'cancelled_at', 'cancellation_reason'])
        queue_email(appointment, Mail.Event.CANCELLED)


@transaction.atomic
def reconcile_created_contract(pk):
    """Fallback for contracts created through Django Admin/direct model saves."""
    lock_calendar()
    contract = Contract.objects.filter(pk=pk, status=Contract.Status.HIEU_LUC).first()
    if contract:
        settle_for_contract(contract)
