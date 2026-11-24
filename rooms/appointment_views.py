from django.contrib import messages
from django.core.exceptions import ValidationError
from django import forms
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import owner_required
from accounts.text import normalize
from .models import AppointmentEmail as Mail, ViewingAppointment as VA
from .public_forms import AppointmentEmailForm, ConfirmAppointmentForm, RescheduleForm
from . import appointment_services
from .appointment_services import TRANSITIONS
from .appointment_emails import configuration_problem, dispatch_safely, preview_mode
from .services import is_free
from .appointment_schedule import has_started

STATUS_TONE = {
    VA.Status.CHO_XAC_NHAN: 'amber', VA.Status.DA_XAC_NHAN: 'sky', VA.Status.DA_XEM: 'lavender',
    VA.Status.DA_CHOT: 'mint', VA.Status.HUY: 'gray',
}


@owner_required
def appointment_list(request):
    items = list(VA.objects.select_related('room').order_by('appointment_date', 'start_time', 'id'))
    for a in items:
        a.tone = STATUS_TONE[a.status]
    counts = {'all': len(items)}
    for key, _ in VA.Status.choices:
        counts[key] = sum(1 for a in items if a.status == key)

    status = request.GET.get('status', '')
    if status not in dict(VA.Status.choices):
        status = ''
    q = request.GET.get('q', '').strip()
    shown = [a for a in items if not status or a.status == status]
    if q:
        nq = normalize(q)
        digits = ''.join(c for c in q if c.isdigit())
        shown = [a for a in shown if nq in normalize(a.visitor_name) or nq in normalize(a.code)
                 or (digits and digits in a.visitor_phone) or nq in normalize(a.room.room_number)
                 or nq in normalize(a.visitor_email)]
    try:
        calendar_date = forms.DateField().clean(request.GET.get('calendar_date')) or timezone.localdate()
    except ValidationError:
        calendar_date = timezone.localdate()
    calendar_items = [a for a in items if a.status == VA.Status.DA_XAC_NHAN and a.appointment_date == calendar_date]
    return render(request, 'rooms/appointments/list.html', {
        'items': shown, 'counts': counts, 'status': status, 'q': q, 'today': timezone.localdate(),
        'calendar_date': calendar_date, 'calendar_items': calendar_items,
    })


@owner_required
def appointment_detail(request, pk):
    appointment = get_object_or_404(VA.objects.select_related('room'), pk=pk)
    return _detail_response(request, appointment)


def _detail_response(request, appointment, confirmation_form=None, reschedule_form=None):
    emails = list(appointment.emails.all()[:10])
    latest = emails[0] if emails else None
    return render(request, 'rooms/appointments/detail.html', {
        'a': appointment, 'tone': STATUS_TONE[appointment.status],
        'actions': [action for action in TRANSITIONS.get(appointment.status, []) if action[0] != VA.Status.DA_XAC_NHAN],
        'can_confirm': appointment.status == VA.Status.CHO_XAC_NHAN,
        'can_mark_seen': has_started(appointment),
        'confirmation_form': confirmation_form or ConfirmAppointmentForm(appointment=appointment),
        'can_reschedule': appointment.status in (VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN),
        'reschedule_form': reschedule_form or RescheduleForm(appointment=appointment, initial={
            'appointment_date': appointment.appointment_date, 'slot': appointment.slot,
            'start_time': appointment.start_time.strftime('%H:%M') if appointment.start_time else ''}),
        'day_confirmed': VA.objects.filter(appointment_date=appointment.appointment_date,
            status=VA.Status.DA_XAC_NHAN).exclude(pk=appointment.pk).select_related('room').order_by('start_time', 'pk'),
        'room_available': is_free(appointment.room),
        'email_form': AppointmentEmailForm(initial={'visitor_email': appointment.visitor_email}),
        'emails': emails, 'latest_email': latest, 'email_preview_mode': preview_mode(),
        'email_configuration_problem': configuration_problem(),
        'email_can_retry': bool(latest and latest.status in (Mail.Status.PENDING, Mail.Status.FAILED, Mail.Status.PREVIEW)),
    })


@owner_required
@require_POST
def appointment_set_status(request, pk):
    appointment = get_object_or_404(VA, pk=pk)
    confirmation = None
    start = None
    if request.POST.get('status') == VA.Status.DA_XAC_NHAN and appointment.status == VA.Status.CHO_XAC_NHAN:
        confirmation = ConfirmAppointmentForm(request.POST, appointment=appointment)
        if not confirmation.is_valid():
            return _detail_response(request, appointment, confirmation_form=confirmation)
        start = confirmation.cleaned_data['start_time']
    try:
        appointment, changed = appointment_services.change_status(appointment.pk, request.POST.get('status', ''),
                                                                 request.POST.get('owner_note', ''), start_time=start)
    except ValidationError as error:
        if confirmation is not None:
            confirmation.add_error('start_time', error)
            return _detail_response(request, appointment, confirmation_form=confirmation)
        messages.error(request, ' '.join(error.messages))
    else:
        if changed:
            messages.success(request, f'Đã cập nhật lịch hẹn {appointment.code}: {appointment.get_status_display()}.')
        else:
            messages.info(request, 'Lịch hẹn đã ở trạng thái này, không gửi email lặp lại.')
    return redirect('appointment_detail', pk=pk)


@owner_required
@require_POST
def appointment_reschedule(request, pk):
    appointment = get_object_or_404(VA, pk=pk)
    if appointment.status not in (VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN):
        messages.error(request, 'Lịch hẹn này không đổi ngày được nữa.')
        return redirect('appointment_detail', pk=pk)
    form = RescheduleForm(request.POST, appointment=appointment)
    if form.is_valid():
        try:
            appointment, changed = appointment_services.reschedule(pk, form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return _detail_response(request, appointment, reschedule_form=form)
        else:
            if changed:
                messages.success(request, f'Đã đổi lịch hẹn {appointment.code} sang '
                                          f'{appointment.appointment_date:%d/%m/%Y}, {appointment.get_slot_display()}.')
            else:
                messages.info(request, 'Ngày, buổi và giờ chưa thay đổi, không gửi email lặp lại.')
    else:
        return _detail_response(request, appointment, reschedule_form=form)
    return redirect('appointment_detail', pk=pk)


@owner_required
@require_POST
def appointment_update_email(request, pk):
    get_object_or_404(VA, pk=pk)
    form = AppointmentEmailForm(request.POST)
    if form.is_valid():
        _, changed = appointment_services.update_email(pk, form.cleaned_data['visitor_email'])
        if changed:
            messages.success(request, 'Đã cập nhật email và tạo thông báo chứa thông tin lịch hẹn hiện tại.')
        else:
            messages.info(request, 'Email chưa thay đổi. Nếu thư chưa gửi được, dùng nút Gửi lại email.')
    else:
        messages.error(request, 'Vui lòng nhập địa chỉ email hợp lệ.')
    return redirect('appointment_detail', pk=pk)


@owner_required
@require_POST
def appointment_retry_email(request, pk):
    appointment = get_object_or_404(VA, pk=pk)
    latest = appointment.emails.first()
    if latest is None:
        messages.error(request, 'Chưa có email cần gửi. Hãy bổ sung email liên hệ của khách.')
    elif dispatch_safely(latest.pk, force=True):
        messages.success(request, 'Máy chủ thư đã tiếp nhận email thông báo cho khách.')
    else:
        messages.info(request, 'Xem kết quả tại mục Email cho khách. Thư đã gửi sẽ không được gửi lặp lại.')
    return redirect('appointment_detail', pk=pk)
