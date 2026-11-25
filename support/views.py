from django.contrib import messages
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db.models import Count, F
from django.db import transaction, DatabaseError
from django.http import FileResponse, Http404, JsonResponse
from django.contrib.auth.decorators import login_required
from accounts.permissions import is_owner
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from accounts.decorators import owner_required, tenant_required
from accounts.text import normalize
from .forms import AnnouncementForm, MaintenanceRequestForm, MaintenanceUpdateForm
from .models import Announcement, MaintenancePhoto, MaintenanceRequest as MR
from .services import TRANSITIONS, active_contract, transition, announcements_for, notification_feed_for, owner_notification_feed
from .notifications import mark_read, read_token, unread_count
from rooms.models import CoOccupantRequest


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
    form = MaintenanceRequestForm(request.POST if request.method == 'POST' else None, request.FILES or None,
                                  initial={'contact_phone': request.tenant.phone})
    if request.method == 'POST':
        if not contract:
            form.add_error(None, 'Bạn cần có hợp đồng hiệu lực để gửi yêu cầu sửa chữa.')
        elif form.is_valid():
            written_files = []
            try:
                with transaction.atomic():
                    locked = type(contract).objects.select_for_update().get(pk=contract.pk)
                    if locked.status != locked.Status.HIEU_LUC:
                        raise ValidationError('Hợp đồng đã kết thúc. Vui lòng tải lại trang.')
                    maintenance = form.save(commit=False)
                    maintenance.room = locked.room
                    maintenance.tenant = request.tenant
                    maintenance.save()
                    for upload in form.cleaned_data['uploaded_images']:
                        photo = MaintenancePhoto(maintenance=maintenance, image=upload)
                        try:
                            photo.save()
                        finally:
                            if photo.image._committed:
                                written_files.append((photo.image.storage, photo.image.name))
            except (OSError, DatabaseError, ValidationError) as error:
                for storage, name in written_files:
                    storage.delete(name)
                form.add_error(None, error if isinstance(error, ValidationError) else 'Chưa lưu được yêu cầu và ảnh. Vui lòng thử lại.')
            else:
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
    return _owner_render(request, 'support/announcement_list.html', {'items': Announcement.objects.select_related('created_by').prefetch_related('rooms')})


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
        with transaction.atomic():
            item.save()
            form.save_m2m()
        messages.success(request, 'Đã lưu thông báo.')
        return redirect('announcement_list')
    return _owner_render(request, 'support/announcement_form.html', {
        'form': form, 'page_title': 'Sửa thông báo' if announcement else 'Thêm thông báo',
        'back_url': reverse('announcement_list'), 'submit_label': 'Lưu thông báo',
    })


@tenant_required
def my_notifications(request):
    return render(request, 'support/my_notifications.html', _notification_context(request))


def _notification_context(request, per_page=20):
    from django.core.paginator import Paginator
    announcements = Paginator(announcements_for(request.tenant), per_page).get_page(request.GET.get('page'))
    replies = Paginator(MR.objects.filter(tenant=request.tenant).exclude(status=MR.Status.DA_GUI)
                        .select_related('room').order_by('-updated_at', '-pk'), per_page).get_page(request.GET.get('replies_page'))
    return {'announcements': announcements, 'replies': replies}


@tenant_required
@require_GET
def my_notifications_panel(request):
    return _notification_panel_response(request, notification_feed_for(request.tenant))


@tenant_required
@require_GET
def my_announcement_detail(request, pk):
    announcement = get_object_or_404(announcements_for(request.tenant), pk=pk)
    return render(request, 'support/announcement_detail.html', {'announcement': announcement})


@owner_required
@require_GET
def owner_notifications_panel(request):
    return _notification_panel_response(request, owner_notification_feed(request.user), owner=True)


@login_required
@require_GET
def notification_count(request):
    response = JsonResponse({'unread_count': unread_count(request.user)})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def notification_mark_read(request):
    try:
        result = mark_read(request.user, request.POST.get('token', ''))
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    response = JsonResponse(result)
    response['Cache-Control'] = 'private, no-store'
    return response


def _notification_panel_response(request, feed, owner=False):
    from django.core.paginator import Paginator
    notifications = Paginator(feed, 10).get_page(request.GET.get('page'))
    labels = {**dict(MR.Status.choices), **dict(CoOccupantRequest.Status.choices)}
    for item in notifications:
        item['read_token'] = read_token(request.user, item)
        if owner:
            kind = item['notification_kind']
            routes = {'owner_maintenance': 'maintenance_detail', 'owner_appointment': 'appointment_detail',
                      'owner_appointment_cancel': 'appointment_detail',
                      'owner_transfer': 'invoice_detail', 'owner_cooccupant': 'cooccupant_review',
                      'contract_due': 'contract_detail', 'contract_event': 'contract_detail'}
            item['url'] = reverse(routes[kind], args=[item['target_id']])
            if kind == 'owner_maintenance':
                item['title'] = f'Yêu cầu sửa chữa: {item["title"]}'
            if kind in ('owner_appointment', 'owner_appointment_cancel'):
                item['expected_label'] = 'Ngày xem phòng'
        else:
            item['status_label'] = labels.get(item['notification_status'], '')
        if not owner and item['notification_kind'] == 'maintenance':
            item['url'] = reverse('my_maintenance_detail', args=[item['id']])
        elif not owner and item['notification_kind'] == 'announcement':
            item['url'] = reverse('my_announcement_detail', args=[item['id']])
        elif not owner and item['notification_kind'] == 'cooccupant_decision':
            item['url'] = reverse('my_cooccupant_detail', args=[item['id']])
        elif not owner and item['notification_kind'] == 'payment_correction':
            item['url'] = reverse('my_payment_detail', args=[item['id']])
        elif not owner and item['notification_kind'] == 'contract_due':
            item['url'] = reverse('my_contract_detail', args=[item['id']])
        elif not owner and item['notification_kind'] == 'contract_event':
            from rooms.models import ContractEvent
            item['url'] = reverse('my_contract_detail', args=[ContractEvent.objects.get(pk=item['id']).contract_id])
        preview = [' '.join(item.get('notification_content', '').split())]
        if item.get('notification_expected'):
            label = item.get('expected_label', 'Dự kiến xong')
            preview.append(f'{label}: {item["notification_expected"]:%d/%m/%Y}')
        item['preview'] = ' · '.join(part for part in preview if part)
    panel_url = reverse('owner_notifications_panel' if owner else 'my_notifications_panel')
    request.notification_unread_count = unread_count(request.user)
    response = render(request, 'support/_notification_items.html', {
        'notifications': notifications, 'notification_panel_url': panel_url})
    response['Cache-Control'] = 'private, no-store'
    response['X-Notification-Unread-Count'] = str(request.notification_unread_count)
    return response


@login_required
def maintenance_photo(request, pk):
    photos = MaintenancePhoto.objects.select_related('maintenance__tenant')
    if not is_owner(request.user):
        if request.user.role != 'tenant':
            raise Http404
        photos = photos.filter(maintenance__tenant__user=request.user)
    photo = get_object_or_404(photos, pk=pk)
    try:
        response = FileResponse(photo.image.open('rb'), content_type={
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
        }.get(Path(photo.image.name).suffix.lower(), 'application/octet-stream'))
    except (FileNotFoundError, OSError):
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


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
