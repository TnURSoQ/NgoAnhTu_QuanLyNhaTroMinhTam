import logging
from datetime import timedelta
from email.utils import parseaddr
from smtplib import SMTPAuthenticationError, SMTPRecipientsRefused, SMTPException
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .models import AppointmentEmail as Mail

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
PREVIEW_BACKENDS = {'django.core.mail.backends.console.EmailBackend',
                    'django.core.mail.backends.filebased.EmailBackend', 'django.core.mail.backends.dummy.EmailBackend'}
EVENT_TEXT = {
    Mail.Event.BOOKED: ('Đã tiếp nhận lịch xem phòng', 'Lịch của bạn đang chờ chủ trọ xác nhận. Đây chưa phải lịch đã được xác nhận.'),
    Mail.Event.CONFIRMED: ('Lịch xem phòng đã được xác nhận', 'Chủ trọ đã xác nhận lịch hẹn. Vui lòng đến theo thời gian bên dưới.'),
    Mail.Event.CANCELLED: ('Lịch xem phòng đã được hủy', 'Lịch hẹn này đã hủy. Vui lòng không đến theo lịch cũ; bạn có thể chọn phòng và đặt lịch mới.'),
    Mail.Event.RESCHEDULED: ('Thời gian xem phòng đã thay đổi', 'Vui lòng sử dụng lịch mới bên dưới. Nếu chưa thuận tiện, hãy liên hệ lại chủ trọ.'),
    Mail.Event.VISITED: ('Cảm ơn bạn đã đến xem phòng', 'Chủ trọ đã ghi nhận bạn đến xem phòng. Nếu cần trao đổi thêm, bạn có thể liên hệ lại.'),
    Mail.Event.LEASED: ('Đã ghi nhận chốt thuê phòng', 'Chủ trọ đã ghi nhận chốt thuê. Các điều khoản và ngày nhận phòng thực hiện theo hợp đồng hai bên thống nhất.'),
    Mail.Event.DETAILS: ('Thông tin lịch hẹn của bạn', 'Chủ trọ đã cập nhật địa chỉ email nhận thông báo. Đây là thông tin lịch hẹn hiện tại của bạn.'),
}


def preview_mode():
    return settings.EMAIL_BACKEND in PREVIEW_BACKENDS


def configuration_problem():
    base = urlsplit(settings.PUBLIC_SITE_URL)
    if base.scheme not in ('http', 'https') or not base.netloc or base.username or base.password or base.query or base.fragment:
        return 'site_url'
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend' and not settings.EMAIL_HOST.strip():
        return 'not_configured'
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend' and bool(settings.EMAIL_HOST_USER) != bool(settings.EMAIL_HOST_PASSWORD):
        return 'authentication_config'
    try:
        validate_email(parseaddr(settings.DEFAULT_FROM_EMAIL)[1])
        if settings.EMAIL_REPLY_TO:
            validate_email(settings.EMAIL_REPLY_TO)
    except (ValidationError, ValueError):
        return 'sender_address'
    return ''


def queue_email(appointment, event, previous_schedule=''):
    """Caller locks the appointment inside its business transaction; dispatch only after commit."""
    if not appointment.visitor_email:
        return None  # Do not invent addresses for appointments created before email was required.
    title, introduction = EVENT_TEXT[event]
    if event == Mail.Event.CANCELLED and appointment.cancelled_by == appointment.CancelledBy.GUEST:
        title = 'Bạn đã hủy lịch xem phòng'
        introduction = 'Yêu cầu hủy lịch của bạn đã được ghi nhận và thông báo tới chủ trọ. Bạn không cần đến theo lịch cũ.'
    context = {'a': appointment, 'title': title, 'introduction': introduction,
        'site_name': settings.SITE_NAME, 'site_address': settings.SITE_ADDRESS, 'site_phone': settings.SITE_PHONE,
        'previous_schedule': previous_schedule,
        'status_url': settings.PUBLIC_SITE_URL + reverse('appointment_status', args=[appointment.code]),
        'reply_to': settings.EMAIL_REPLY_TO}
    appointment.notification_version += 1
    appointment.save(update_fields=['notification_version'])
    appointment.emails.filter(status__in=[Mail.Status.PENDING, Mail.Status.FAILED, Mail.Status.PREVIEW]).update(
        status=Mail.Status.SUPERSEDED, next_attempt_at=None)
    record = Mail.objects.create(appointment=appointment, revision=appointment.notification_version, event=event,
        recipient=appointment.visitor_email,
        subject=' '.join(f'[{settings.SITE_NAME}] {title} · {appointment.code}'.splitlines())[:255],
        text_body=render_to_string('emails/appointment.txt', context),
        html_body=render_to_string('emails/appointment.html', context), lookup_url=context['status_url'])
    transaction.on_commit(lambda pk=record.pk: dispatch_safely(pk), robust=True)
    return record


def dispatch_safely(pk, force=False):
    # A delivery/database failure must never undo an appointment that was already committed.
    try:
        return dispatch_email(pk, force=force)
    except Exception as error:
        logger.warning('Appointment email %s deferred (%s).', pk, type(error).__name__)
        return False


def dispatch_email(pk, force=False):
    now = timezone.now()
    with transaction.atomic():
        # Take the write lock before reading. SQLite cannot safely upgrade a read
        # snapshot while a simultaneous appointment transaction is committing.
        Mail.objects.filter(pk=pk).update(attempts=F('attempts'))
        record = Mail.objects.select_related('appointment').filter(pk=pk).first()
        if record is None or record.status in (Mail.Status.SENT, Mail.Status.SUPERSEDED):
            return False
        if record.revision != record.appointment.notification_version or record.recipient != record.appointment.visitor_email:
            Mail.objects.filter(pk=pk).exclude(status=Mail.Status.SENT).update(status=Mail.Status.SUPERSEDED, next_attempt_at=None)
            return False
        if record.status == Mail.Status.SENDING and record.attempted_at and record.attempted_at > now - LEASE:
            return False
        if record.status == Mail.Status.PREVIEW and preview_mode():
            return False
        if not force and (record.attempts >= MAX_ATTEMPTS or (record.next_attempt_at and record.next_attempt_at > now)):
            return False
        problem = configuration_problem()
        if problem:
            Mail.objects.filter(pk=pk).update(status=Mail.Status.PENDING, error_code=problem)
            return False
        # Compare-and-set avoids sending twice when a retry and a web request pick the same record.
        claimed = Mail.objects.filter(pk=pk, status=record.status, attempts=record.attempts).update(
            status=Mail.Status.SENDING, attempts=F('attempts') + 1, attempted_at=now, error_code='', next_attempt_at=None)
        if not claimed:
            return False
        attempt = record.attempts + 1
    try:
        # Recheck after claiming; never retry an old snapshot after a newer cancellation/change.
        if not Mail.objects.filter(pk=pk, appointment__notification_version=record.revision,
                                   appointment__visitor_email=record.recipient).exists():
            Mail.objects.filter(pk=pk, status=Mail.Status.SENDING, attempts=attempt).update(status=Mail.Status.SUPERSEDED)
            return False
        # A queued preview/failure may be sent after the website moves to its public domain.
        lookup_url = settings.PUBLIC_SITE_URL + reverse('appointment_status', args=[record.appointment.code])
        if record.lookup_url and record.lookup_url != lookup_url:
            record.text_body = record.text_body.replace(record.lookup_url, lookup_url)
            record.html_body = record.html_body.replace(str(escape(record.lookup_url)), str(escape(lookup_url)))
            Mail.objects.filter(pk=pk, status=Mail.Status.SENDING, attempts=attempt).update(
                text_body=record.text_body, html_body=record.html_body, lookup_url=lookup_url)
        message = EmailMultiAlternatives(record.subject, record.text_body, settings.DEFAULT_FROM_EMAIL,
            [record.recipient], reply_to=[settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else [],
            headers={'Message-ID': f'<appointment-{record.pk}-{record.revision}@{urlsplit(settings.PUBLIC_SITE_URL).hostname}>'})
        message.attach_alternative(record.html_body, 'text/html')
        if message.send(fail_silently=False) != 1:
            raise SMTPException('No message accepted')
    except Exception as error:
        code = ('authentication' if isinstance(error, SMTPAuthenticationError) else
                'recipient' if isinstance(error, SMTPRecipientsRefused) else
                'connection' if isinstance(error, (OSError, SMTPException)) else 'delivery')
        Mail.objects.filter(pk=pk, status=Mail.Status.SENDING, attempts=attempt).update(status=Mail.Status.FAILED,
            error_code=code, next_attempt_at=timezone.now() + timedelta(minutes=min(5 * 3 ** (attempt - 1), 180)))
        logger.warning('Appointment email %s failed (%s).', pk, code)
        return False
    is_preview = preview_mode()
    Mail.objects.filter(pk=pk, status=Mail.Status.SENDING, attempts=attempt).update(
        status=Mail.Status.PREVIEW if is_preview else Mail.Status.SENT,
        sent_at=None if is_preview else timezone.now(), error_code='', next_attempt_at=None)
    return not is_preview


def pending_email_ids(limit=100):
    now = timezone.now()
    eligible = Q(status__in=[Mail.Status.PENDING, Mail.Status.FAILED]) | Q(
        status=Mail.Status.SENDING, attempted_at__lte=now - LEASE)
    if not preview_mode():
        eligible |= Q(status=Mail.Status.PREVIEW)
    return list(Mail.objects.filter(eligible, attempts__lt=MAX_ATTEMPTS).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    ).order_by('created_at', 'pk').values_list('pk', flat=True)[:limit])
