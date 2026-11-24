"""One shared viewing calendar for this boarding house, in local time."""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import F
from django.utils import timezone

from .models import AppointmentCalendar, ViewingAppointment as VA

DURATION = timedelta(minutes=30)
SLOT_STARTS = {
    'sang': tuple(time(8 + n // 2, (n % 2) * 30) for n in range(7)),
    'chieu': tuple(time(13 + (n + 1) // 2, ((n + 1) % 2) * 30) for n in range(7)),
    'toi': tuple(time(18 + n // 2, (n % 2) * 30) for n in range(4)),
}


def lock_calendar():
    if not connection.in_atomic_block:
        raise RuntimeError('Calendar changes require a transaction.')
    # A write as the first statement serializes SQLite writers as well as PostgreSQL.
    if not AppointmentCalendar.objects.filter(pk=1).update(revision=F('revision') + 1):
        AppointmentCalendar.objects.get_or_create(pk=1)


def start_datetime(day, start):
    return timezone.make_aware(datetime.combine(day, start), timezone.get_current_timezone())


def parse_start(value):
    if isinstance(value, time):
        return value
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError('Hãy chọn giờ xem cụ thể trước khi xác nhận.')


def validate_start(day, slot, value, exclude_pk=None, *, resolve_legacy=False):
    start = parse_start(value)
    if start not in SLOT_STARTS.get(slot, ()):
        raise ValidationError('Giờ xem phải thuộc buổi đã chọn và đúng khung 30 phút.')
    if start_datetime(day, start) <= timezone.now():
        raise ValidationError('Giờ xem đã qua. Hãy chọn lịch trong tương lai.')
    confirmed = VA.objects.filter(status=VA.Status.DA_XAC_NHAN, appointment_date=day).exclude(pk=exclude_pk)
    if not resolve_legacy and confirmed.filter(start_time__isnull=True, slot=slot).exists():
        raise ValidationError('Buổi này có lịch cũ đã xác nhận nhưng chưa ghi giờ. Hãy bổ sung giờ cho lịch cũ trước.')
    if confirmed.filter(start_time=start).exists():
        raise ValidationError('Khung giờ này đã có lịch xem phòng khác được xác nhận. Hãy chọn giờ còn trống.')
    return start


def request_time_available(day, slot):
    return any(start_datetime(day, start) > timezone.now() for start in SLOT_STARTS.get(slot, ()))


def has_started(appointment):
    now = timezone.localtime()
    return appointment.appointment_date < now.date() or (appointment.appointment_date == now.date() and
        (not appointment.start_time or appointment.start_time <= now.time().replace(tzinfo=None)))


def time_label(start):
    end = (datetime.combine(timezone.localdate(), start) + DURATION).time()
    return f'{start:%H:%M}–{end:%H:%M}'
