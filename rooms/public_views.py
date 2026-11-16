from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .models import Room, ViewingAppointment
from .public_forms import BookingForm

PRICE_RANGES = {
    'duoi2': (None, 2000000, 'Dưới 2 triệu'),
    '2-3': (2000000, 3000000, '2 – 3 triệu'),
    'tren3': (3000000, None, 'Trên 3 triệu'),
}


def free_rooms():
    return Room.objects.filter(status=Room.Status.TRONG).order_by('floor', 'room_number')


def landing(request):
    """Trang chủ công khai (khách chưa đăng nhập)."""
    rooms = list(free_rooms()[:6])
    return render(request, 'public/home.html', {'rooms': rooms, 'total_free': free_rooms().count()})


def room_list(request):
    rooms = list(free_rooms())
    floors = sorted({r.floor for r in rooms})

    try:
        floor = int(request.GET.get('floor', ''))
    except ValueError:
        floor = None
    try:
        people = int(request.GET.get('people', ''))
    except ValueError:
        people = None
    price = request.GET.get('price', '')
    if price not in PRICE_RANGES:
        price = ''
    sort = request.GET.get('sort', '')
    if sort not in ('gia_tang', 'gia_giam'):
        sort = ''

    if floor is not None:
        rooms = [r for r in rooms if r.floor == floor]
    if people:
        rooms = [r for r in rooms if r.max_occupants >= people]
    if price:
        low, high, _ = PRICE_RANGES[price]
        rooms = [r for r in rooms if (low is None or r.price >= low) and (high is None or r.price < high)]
    if sort:
        rooms.sort(key=lambda r: r.price, reverse=(sort == 'gia_giam'))

    return render(request, 'public/room_list.html', {
        'rooms': rooms, 'floors': floors, 'floor': floor, 'people': people, 'price': price,
        'sort': sort, 'price_ranges': PRICE_RANGES, 'total_free': free_rooms().count(),
    })


def room_detail(request, pk):
    room = get_object_or_404(Room, pk=pk)
    available = services.is_free(room)
    form = BookingForm(request.POST or None, room=room)
    if request.method == 'POST':
        if not available:
            messages.error(request, 'Rất tiếc, phòng này vừa có người thuê nên không đặt lịch được.')
            return redirect('public_room_detail', pk=pk)
        if form.is_valid():
            data = form.cleaned_data
            appointment = ViewingAppointment.objects.create(
                room=room, visitor_name=data['visitor_name'].strip(), visitor_phone=data['visitor_phone'],
                appointment_date=data['appointment_date'], slot=data['slot'], note=data['note'].strip())
            return redirect('appointment_status', code=appointment.code)
    return render(request, 'public/room_detail.html', {'room': room, 'available': available, 'form': form})


def appointment_status(request, code):
    appointment = get_object_or_404(ViewingAppointment.objects.select_related('room'), code=code.upper())
    return render(request, 'public/appointment_status.html', {'appointment': appointment})


def appointment_lookup(request):
    code = request.GET.get('code', '').strip().upper()
    error = ''
    if code:
        if ViewingAppointment.objects.filter(code=code).exists():
            return redirect('appointment_status', code=code)
        error = 'Không tìm thấy lịch hẹn với mã này. Hãy kiểm tra lại mã (gồm 8 ký tự, bắt đầu bằng LH).'
    return render(request, 'public/appointment_lookup.html', {'code': code, 'error': error})