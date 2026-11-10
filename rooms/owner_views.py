from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, UpdateView

from accounts.decorators import owner_required
from accounts.mixins import OwnerRequiredMixin
from accounts.text import normalize
from billing.models import Invoice
from .display import ROOM_STATUS_UI, representative_of, room_status_ui
from .forms import RoomForm
from .models import Contract, Room


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
    room = get_object_or_404(Room, pk=pk)
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
        payments = list(last_invoice.payments.all())
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
        'history': history, 'label': label, 'tone': tone,
    })


class RoomFormMixin(OwnerRequiredMixin, SuccessMessageMixin):
    model = Room
    form_class = RoomForm
    template_name = '_crud/form.html'

    def get_success_url(self):
        return reverse('room_detail', args=[self.object.pk])


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