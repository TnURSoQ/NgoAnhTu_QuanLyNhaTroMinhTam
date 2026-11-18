from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import owner_required, tenant_required
from accounts.text import normalize
from .forms import AnnouncementForm, MaintenanceRequestForm, MaintenanceUpdateForm
from .models import Announcement, MaintenanceRequest as MR
from .services import TRANSITIONS, active_contract, transition


def _owner_render(request, template, context):
    return render(request, template, {**context, 'hide_admin_navigation': True})


@tenant_required
def my_maintenance_requests(request):
    return render(request, 'support/my_requests.html', {
        'items': MR.objects.filter(tenant=request.tenant),
        'contract': active_contract(request.tenant),
    })


@tenant_required
def maintenance_create(request):
    contract = active_contract(request.tenant)
    form = MaintenanceRequestForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if not contract:
            form.add_error(None, 'Bạn cần có hợp đồng hiệu lực để gửi yêu cầu sửa chữa.')
        elif form.is_valid():
            maintenance = form.save(commit=False)
            maintenance.room = contract.room
            maintenance.tenant = request.tenant
            maintenance.save()
            return redirect('maintenance_sent', pk=maintenance.pk)
    return render(request, 'support/request_form.html', {'form': form, 'contract': contract})


@tenant_required
def maintenance_sent(request, pk):
    maintenance = get_object_or_404(MR, pk=pk, tenant=request.tenant)
    return render(request, 'support/request_sent.html', {'maintenance': maintenance})


@tenant_required
def my_maintenance_detail(request, pk):
    maintenance = get_object_or_404(MR.objects.select_related('room', 'tenant'), pk=pk, tenant=request.tenant)
    return render(request, 'support/request_detail.html', {'maintenance': maintenance})


@tenant_required
@require_POST
def maintenance_cancel(request, pk):
    maintenance = get_object_or_404(MR, pk=pk, tenant=request.tenant)
    try:
        if maintenance.status != MR.Status.DA_GUI:
            raise ValidationError('Chỉ có thể hủy yêu cầu khi còn ở trạng thái đã gửi.')
        transition(maintenance, MR.Status.DA_HUY)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, 'Đã hủy yêu cầu sửa chữa.')
    return redirect('my_maintenance_detail', pk=pk)


@owner_required
def maintenance_list(request):
    items = MR.objects.select_related('room', 'tenant')
    counts = dict(MR.objects.values_list('status').annotate(n=Count('pk')))
    counts['all'] = sum(counts.values())
    tabs = [{'key': '', 'label': 'Tất cả', 'count': counts['all']}]
    for key, label in MR.Status.choices:
        tabs.append({'key': key, 'label': 'Mới gửi' if key == MR.Status.DA_GUI else label,
                     'count': counts.get(key, 0)})
    status = request.GET.get('status', '')
    if status not in MR.Status.values:
        status = ''
    if status:
        items = items.filter(status=status)
    q = request.GET.get('q', '').strip()
    if q:
        query = normalize(q)
        items = [item for item in items if any(query in normalize(value) for value in (
            item.display_code, item.room.room_number, item.tenant.full_name, item.title))]
    return _owner_render(request, 'support/maintenance_list.html', {
        'items': items, 'tabs': tabs, 'status': status, 'q': q,
    })


@owner_required
def maintenance_detail(request, pk):
    maintenance = get_object_or_404(MR.objects.select_related('room', 'tenant'), pk=pk)
    form = MaintenanceUpdateForm(maintenance=maintenance, initial={
        'expected_done': maintenance.expected_done, 'owner_note': maintenance.owner_note})
    return _owner_render(request, 'support/request_detail.html', {
        'maintenance': maintenance, 'owner_view': True,
        'can_update': maintenance.status in TRANSITIONS, 'form': form,
    })


@owner_required
@require_POST
def maintenance_set_status(request, pk):
    maintenance = get_object_or_404(MR.objects.select_related('room', 'tenant'), pk=pk)
    form = MaintenanceUpdateForm(request.POST, maintenance=maintenance)
    if form.is_valid():
        data = form.cleaned_data.copy()
        status = data.pop('status')
        # Các trường không có trong POST giữ nguyên giá trị hiện tại.
        data = {key: value for key, value in data.items() if key in request.POST}
        try:
            transition(maintenance, status, **data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, f'Đã cập nhật {maintenance.display_code}: {maintenance.get_status_display()}.')
            return redirect('maintenance_detail', pk=pk)
    return _owner_render(request, 'support/request_detail.html', {
        'maintenance': maintenance, 'owner_view': True,
        'can_update': maintenance.status in TRANSITIONS, 'form': form,
    })


@owner_required
def announcement_list(request):
    return _owner_render(request, 'support/announcement_list.html', {'items': Announcement.objects.select_related('created_by')})


@owner_required
def announcement_create(request):
    return _announcement_form(request)


@owner_required
def announcement_update(request, pk):
    return _announcement_form(request, get_object_or_404(Announcement, pk=pk))


def _announcement_form(request, announcement=None):
    form = AnnouncementForm(request.POST if request.method == 'POST' else None, instance=announcement)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        if announcement is None:
            item.created_by = request.user
        item.save()
        messages.success(request, 'Đã lưu thông báo.')
        return redirect('announcement_list')
    return _owner_render(request, '_crud/form.html', {
        'form': form, 'page_title': 'Sửa thông báo' if announcement else 'Thêm thông báo',
        'back_url': reverse('announcement_list'), 'submit_label': 'Lưu thông báo',
    })


@owner_required
@require_POST
def announcement_toggle(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    Announcement.objects.filter(pk=announcement.pk).update(is_active=~F('is_active'))
    messages.success(request, 'Đã đổi trạng thái hiển thị thông báo.')
    return redirect('announcement_list')


@owner_required
def announcement_delete(request, pk):
    announcement = get_object_or_404(Announcement, pk=pk)
    if request.method == 'POST':
        announcement.delete()
        messages.success(request, 'Đã xóa thông báo.')
        return redirect('announcement_list')
    return _owner_render(request, '_crud/confirm_delete.html', {
        'title': f'Xóa thông báo “{announcement.title}”?',
        'message': 'Thông báo sẽ bị xóa vĩnh viễn. Bạn có chắc chắn muốn xóa?',
        'back_url': reverse('announcement_list'),
    })
