from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from accounts.text import normalize
from billing.models import Service, UtilityRate
from . import services
from .models import Room, ViewingAppointment
from .public_forms import BookingForm, GuestCancelAppointmentForm
from .appointment_services import book_appointment, cancel_by_guest

PRICE_RANGES = {
    'duoi2': (None, 2000000, 'Dưới 2 triệu'),
    '2-3': (2000000, 3000000, '2 – 3 triệu'),
    'tren3': (3000000, None, 'Trên 3 triệu'),
}


def free_rooms():
    return Room.objects.filter(status=Room.Status.TRONG).exclude(contracts__status='hieu_luc').prefetch_related('photos').order_by('floor', 'room_number')


def landing(request):
    """Trang chủ xem phòng dùng chung trước và sau khi đăng nhập."""
    context = _room_context(request)
    if not context['has_filters']:
        context['rooms'] = context['rooms'][:6]
    return render(request, 'public/home.html', context)


def room_list(request):
    return render(request, 'public/room_list.html', _room_context(request))


def _room_context(request):
    rooms = list(free_rooms())
    total_free = len(rooms)
    starting_price = min((room.price for room in rooms), default=None)
    floors = sorted({r.floor for r in rooms})
    capacities = sorted({1, 2, 3, 4} | {r.max_occupants for r in rooms})
    amenities = sorted({a for room in rooms for a in room.amenity_list}, key=normalize)

    try:
        floor = int(request.GET.get('floor', ''))
    except ValueError:
        floor = None
    try:
        people = int(request.GET.get('people', ''))
    except ValueError:
        people = None
    if people is not None and people < 1:
        people = None
    price = request.GET.get('price', '')
    if price not in PRICE_RANGES:
        price = ''
    sort = request.GET.get('sort', '')
    if sort not in ('gia_tang', 'gia_giam'):
        sort = ''
    q = request.GET.get('q', '').strip()
    amenity = request.GET.get('amenity', '').strip()
    if amenity not in amenities:
        amenity = ''

    if floor is not None:
        rooms = [r for r in rooms if r.floor == floor]
    if people:
        rooms = [r for r in rooms if r.max_occupants >= people]
    if price:
        low, high, _ = PRICE_RANGES[price]
        rooms = [r for r in rooms if (low is None or r.price >= low) and (high is None or r.price < high)]
    if amenity:
        rooms = [r for r in rooms if normalize(amenity) in {normalize(a) for a in r.amenity_list}]
    if q:
        terms = normalize(q).split()
        rooms = [r for r in rooms if all(term in normalize(
            f'Phòng P.{r.room_number} {r.description} {r.amenities}') for term in terms)]
    if sort:
        rooms.sort(key=lambda r: r.price, reverse=(sort == 'gia_giam'))

    return {
        'rooms': rooms, 'floors': floors, 'floor': floor, 'people': people, 'price': price,
        'sort': sort, 'price_ranges': PRICE_RANGES, 'total_free': total_free,
        'q': q, 'amenity': amenity, 'amenities': amenities, 'capacities': capacities,
        'filtered_count': len(rooms), 'starting_price': starting_price,
        'has_filters': bool(q or price or floor is not None or people is not None or amenity or sort),
        'utility_rate': UtilityRate.current(),
    }


def room_detail(request, pk):
    room = get_object_or_404(Room.objects.prefetch_related('photos'), pk=pk)
    available = services.is_free(room)
    form = BookingForm(request.POST if request.method == 'POST' else None, room=room)
    if request.method == 'POST':
        if not available:
            messages.error(request, 'Rất tiếc, phòng này vừa có người thuê nên không đặt lịch được.')
            return redirect('public_room_detail', pk=pk)
        if form.is_valid():
            data = form.cleaned_data
            try:
                appointment = book_appointment(room, data)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('appointment_status', code=appointment.code)
    return render(request, 'public/room_detail.html', {'room': room, 'available': available, 'form': form,
                                                     'utility_rate': UtilityRate.current(),
                                                     'public_services': Service.objects.order_by('name')})


@never_cache
def appointment_status(request, code):
    appointment = get_object_or_404(ViewingAppointment.objects.select_related('room'), code=code.upper())
    return _appointment_status_response(request, appointment)


def _appointment_status_response(request, appointment, cancel_form=None):
    return render(request, 'public/appointment_status.html', {'appointment': appointment,
        'cancel_form': cancel_form if cancel_form is not None else GuestCancelAppointmentForm(),
        'latest_email': appointment.emails.first()})


@never_cache
@require_POST
def appointment_cancel(request, code):
    appointment = get_object_or_404(ViewingAppointment.objects.select_related('room'), code=code.upper())
    form = GuestCancelAppointmentForm(request.POST)
    if not form.is_valid() and appointment.can_guest_cancel:
        return _appointment_status_response(request, appointment, cancel_form=form)
    try:
        appointment, changed = cancel_by_guest(appointment.code, form.cleaned_data.get('reason', ''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        if changed:
            messages.success(request, 'Bạn đã hủy lịch hẹn. Nhà trọ đã nhận được thông báo.')
        else:
            messages.info(request, 'Lịch hẹn này đã được hủy trước đó.')
    return redirect('appointment_status', code=appointment.code)


def appointment_lookup(request):
    code = request.GET.get('code', '').strip().upper()
    error = ''
    if code:
        if ViewingAppointment.objects.filter(code=code).exists():
            return redirect('appointment_status', code=code)
        error = 'Không tìm thấy lịch hẹn với mã này. Hãy kiểm tra lại mã (gồm 8 ký tự, bắt đầu bằng LH).'
    return render(request, 'public/appointment_lookup.html', {'code': code, 'error': error})
