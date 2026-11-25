from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Prefetch
from django.db import DatabaseError, transaction
from django.views.decorators.http import require_GET, require_POST
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from accounts.decorators import owner_required
from accounts.mixins import OwnerRequiredMixin
from accounts.text import normalize
from billing.models import Invoice
from .display import ROOM_STATUS_UI, representative_of, room_status_ui
from .forms import MAX_ROOM_PHOTOS, RoomForm
from .models import Contract, PropertyInfo, Room, RoomPhoto


def _room_items():
    """Mọi phòng kèm hợp đồng đang hiệu lực và người đại diện."""
    active = Contract.objects.filter(
        status=Contract.Status.HIEU_LUC).prefetch_related('contract_tenants__tenant')
    rooms = Room.objects.order_by('floor', 'room_number').prefetch_related(
        Prefetch('contracts', queryset=active, to_attr='active_contracts'))
    items = []
    for room in rooms:
        contract = room.active_contracts[0] if room.active_contracts else None
        label, tone = room_status_ui(room)
        items.append({
            'room': room, 'contract': contract, 'label': label, 'tone': tone,
            'tenant': representative_of(contract) if contract else None,
        })
    return items


@owner_required
def room_list(request):
    items = _room_items()
    counts = {'all': len(items)}
    for key in ROOM_STATUS_UI:
        counts[key] = sum(1 for i in items if i['room'].status == key)
    floors = sorted({i['room'].floor for i in items})

    status = request.GET.get('status', '')
    if status not in ROOM_STATUS_UI:
        status = ''
    try:
        floor = int(request.GET.get('floor', ''))
    except ValueError:
        floor = None
    q = request.GET.get('q', '').strip()

    shown = items
    if status:
        shown = [i for i in shown if i['room'].status == status]
    if floor is not None:
        shown = [i for i in shown if i['room'].floor == floor]
    if q:
        nq = normalize(q)

        def match(item):
            names = ([ct.tenant.full_name for ct in item['contract'].contract_tenants.all()]
                     if item['contract'] else [])
            return nq in normalize(item['room'].room_number) or any(nq in normalize(n) for n in names)

        shown = [i for i in shown if match(i)]

    return render(request, 'rooms/room_list.html', {
        'items': shown, 'counts': counts, 'floors': floors,
        'status': status, 'floor': floor, 'q': q,
    })


@owner_required
def room_detail(request, pk):
    room = get_object_or_404(Room.objects.prefetch_related('photos'), pk=pk)
    contract = (
        Contract.objects.filter(room=room, status=Contract.Status.HIEU_LUC)
        .prefetch_related('contract_tenants__tenant').first()
    )
    people = list(contract.contract_tenants.all()) if contract else []
    last_invoice = (
        Invoice.objects.filter(contract__room=room)
        .prefetch_related('payments').order_by('-year', '-month').first()
    )
    invoice_info = None
    if last_invoice:
        payments = [p for p in last_invoice.payments.all() if not p.is_voided]
        paid = sum((p.amount for p in payments), 0)
        invoice_info = {
            'invoice': last_invoice, 'paid': paid,
            'remaining': last_invoice.total_amount - paid,
            'paid_date': max((p.paid_date for p in payments), default=None)
            if last_invoice.status == Invoice.Status.DA_THANH_TOAN else None,
        }
    history = Contract.objects.filter(room=room).order_by('-start_date', '-id')[:6]
    label, tone = room_status_ui(room)
    return render(request, 'rooms/room_detail.html', {
        'room': room, 'contract': contract, 'people': people, 'invoice_info': invoice_info,
        'history': history, 'label': label, 'tone': tone, 'property_info': PropertyInfo.current(),
        'maintenance_requests': room.maintenance_requests.all()[:5],
    })


class RoomFormMixin(OwnerRequiredMixin, SuccessMessageMixin):
    model = Room
    form_class = RoomForm
    template_name = 'rooms/form.html'

    def get_success_url(self):
        return reverse('room_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context['form']
        context['room_fields'] = [form[name] for name in RoomForm.Meta.fields if name != 'amenities']
        context['existing_photos'] = form.existing_photos
        context['deleted_photo_ids'] = {str(pk) for pk in form['delete_photos'].value() or []}
        return context

    def form_valid(self, form):
        written_files = []
        try:
            with transaction.atomic():
                if self.object is not None:
                    current = Room.objects.select_for_update().get(pk=self.object.pk)
                    active = current.contracts.filter(status=Contract.Status.HIEU_LUC)
                    if active.exists():
                        form.instance.status = Room.Status.DANG_THUE
                        people = Contract.objects.filter(pk__in=active.values('pk')).values_list('contract_tenants__tenant_id', flat=True)
                        if len({pk for pk in people if pk is not None}) > form.cleaned_data['max_occupants']:
                            form.add_error('max_occupants', 'Số người đang ở đã thay đổi. Hãy tải lại và kiểm tra sức chứa.')
                            return self.form_invalid(form)
                    elif form.fields['status'].disabled:
                        form.instance.status = current.status
                    deleted_ids = [photo.pk for photo in form.cleaned_data['delete_photos']]
                    remaining = current.photos.exclude(pk__in=deleted_ids).count()
                else:
                    deleted_ids, remaining = [], 0
                if remaining + len(form.cleaned_data['photos']) > MAX_ROOM_PHOTOS:
                    form.add_error('photos', 'Mỗi phòng tối đa 10 ảnh. Danh sách ảnh đã thay đổi, hãy kiểm tra lại.')
                    return self.form_invalid(form)
                self.object = form.save()
                self.object.photos.filter(pk__in=deleted_ids).delete()
                new_photos = []
                for index, upload in enumerate(form.cleaned_data['photos']):
                    photo = RoomPhoto(room=self.object, image=upload, position=remaining + index)
                    try:
                        photo.save()
                    finally:
                        if photo.image._committed:
                            written_files.append((photo.image.storage, photo.image.name))
                    new_photos.append(photo)
                index = form.cleaned_data.get('new_cover_index')
                cover = new_photos[index] if index is not None else form.cleaned_data.get('cover_photo')
                photos = list(self.object.photos.order_by('position', 'pk'))
                if cover and any(photo.pk == cover.pk for photo in photos):
                    photos.sort(key=lambda photo: photo.pk != cover.pk)
                for position, photo in enumerate(photos):
                    photo.position = position
                if photos:
                    RoomPhoto.objects.bulk_update(photos, ['position'])
        except (OSError, DatabaseError):
            for storage, name in written_files:
                storage.delete(name)
            form.add_error(None, 'Chưa lưu được phòng và ảnh. Vui lòng thử lại; các thay đổi chưa được lưu.')
            return self.form_invalid(form)
        messages.success(self.request, self.get_success_message(form.cleaned_data))
        return HttpResponseRedirect(self.get_success_url())


class RoomCreateView(RoomFormMixin, CreateView):
    success_message = 'Đã thêm phòng %(room_number)s.'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_title='Thêm phòng', subtitle='Nhập thông tin phòng mới.',
                   back_url=reverse('room_list'), submit_label='Lưu phòng')
        return ctx


class RoomUpdateView(RoomFormMixin, UpdateView):
    success_message = 'Đã cập nhật phòng %(room_number)s.'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_title=f'Sửa thông tin phòng {self.object.room_number}',
                   subtitle='Chỉnh sửa rồi bấm Lưu thay đổi.',
                   back_url=reverse('room_detail', args=[self.object.pk]),
                   submit_label='Lưu thay đổi')
        return ctx


@owner_required
def room_delete(request, pk):
    room = get_object_or_404(Room, pk=pk)
    blocked = room.contracts.exists()
    if request.method == 'POST':
        if blocked:
            messages.error(request, 'Phòng đã có hợp đồng nên không thể xóa.')
            return redirect('room_detail', pk=pk)
        number = room.room_number
        room.delete()
        messages.success(request, f'Đã xóa phòng {number}.')
        return redirect('room_list')
    return render(request, '_crud/confirm_delete.html', {
        'title': f'Xóa phòng {room.room_number}?',
        'message': 'Thao tác này không thể hoàn tác.',
        'blocked': blocked,
        'blocked_message': 'Phòng này đã từng có hợp đồng nên không thể xóa. '
                           'Nếu không cho thuê nữa, hãy chuyển tình trạng sang "Đang sửa chữa".',
        'back_url': reverse('room_detail', args=[room.pk]),
    })


@owner_required
@require_GET
def room_photos(request, pk):
    get_object_or_404(Room, pk=pk)
    return redirect(f'{reverse("room_update", args=[pk])}#roomPhotos')


@owner_required
@require_POST
def room_photo_delete(request, pk, photo_pk):
    with transaction.atomic():
        get_object_or_404(Room.objects.select_for_update(), pk=pk)
        photo = get_object_or_404(RoomPhoto, pk=photo_pk, room_id=pk)
        photo.delete()
    messages.success(request, 'Đã xóa ảnh phòng.')
    return redirect(f'{reverse("room_update", args=[pk])}#roomPhotos')
