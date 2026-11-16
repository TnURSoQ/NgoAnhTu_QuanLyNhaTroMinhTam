from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import owner_required
from accounts.text import normalize
from .models import ViewingAppointment as VA
from .public_forms import RescheduleForm

STATUS_TONE = {
    VA.Status.CHO_XAC_NHAN: 'amber', VA.Status.DA_XAC_NHAN: 'sky', VA.Status.DA_XEM: 'lavender',
    VA.Status.DA_CHOT: 'mint', VA.Status.HUY: 'gray',
}
# trạng thái hiện tại -> các trạng thái được chuyển tới (nhãn nút, kiểu nút)
TRANSITIONS = {
    VA.Status.CHO_XAC_NHAN: [(VA.Status.DA_XAC_NHAN, 'Xác nhận lịch hẹn', 'btn-primary'),
                             (VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
    VA.Status.DA_XAC_NHAN: [(VA.Status.DA_XEM, 'Khách đã xem phòng', 'btn-primary'),
                            (VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
    VA.Status.DA_XEM: [(VA.Status.DA_CHOT, 'Đánh dấu đã chốt thuê', 'btn-outline-brand'),
                       (VA.Status.HUY, 'Hủy lịch', 'btn-outline-brand text-danger')],
}


@owner_required
def appointment_list(request):
    items = list(VA.objects.select_related('room').order_by('appointment_date', 'id'))
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
                 or (digits and digits in a.visitor_phone) or nq in normalize(a.room.room_number)]
    return render(request, 'rooms/appointments/list.html', {
        'items': shown, 'counts': counts, 'status': status, 'q': q, 'today': timezone.localdate(),
    })


@owner_required
def appointment_detail(request, pk):
    appointment = get_object_or_404(VA.objects.select_related('room'), pk=pk)
    return render(request, 'rooms/appointments/detail.html', {
        'a': appointment, 'tone': STATUS_TONE[appointment.status],
        'actions': TRANSITIONS.get(appointment.status, []),
        'can_reschedule': appointment.status in (VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN),
        'reschedule_form': RescheduleForm(initial={
            'appointment_date': appointment.appointment_date, 'slot': appointment.slot}),
    })


@owner_required
@require_POST
def appointment_set_status(request, pk):
    appointment = get_object_or_404(VA, pk=pk)
    new_status = request.POST.get('status', '')
    allowed = {s for s, _, _ in TRANSITIONS.get(appointment.status, [])}
    if new_status not in allowed:
        messages.error(request, 'Không thể chuyển lịch hẹn sang trạng thái này.')
    else:
        appointment.status = new_status
        note = request.POST.get('owner_note', '').strip()
        if note:
            appointment.owner_note = note[:255]
        appointment.save(update_fields=['status', 'owner_note'])
        messages.success(request, f'Đã cập nhật lịch hẹn {appointment.code}: {appointment.get_status_display()}.')
    return redirect('appointment_detail', pk=pk)


@owner_required
@require_POST
def appointment_reschedule(request, pk):
    appointment = get_object_or_404(VA, pk=pk)
    if appointment.status not in (VA.Status.CHO_XAC_NHAN, VA.Status.DA_XAC_NHAN):
        messages.error(request, 'Lịch hẹn này không đổi ngày được nữa.')
        return redirect('appointment_detail', pk=pk)
    form = RescheduleForm(request.POST)
    if form.is_valid():
        appointment.appointment_date = form.cleaned_data['appointment_date']
        appointment.slot = form.cleaned_data['slot']
        appointment.save(update_fields=['appointment_date', 'slot'])
        messages.success(request, f'Đã đổi lịch hẹn {appointment.code} sang '
                                  f'{appointment.appointment_date:%d/%m/%Y}, {appointment.get_slot_display()}.')
    else:
        messages.error(request, ' '.join(m for errs in form.errors.values() for m in errs))
    return redirect('appointment_detail', pk=pk)