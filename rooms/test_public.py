from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from . import services
from .models import Room, ViewingAppointment


def room(no, price=2500000, status='trong', floor=1, people=2, amenities='', description=''):
    return Room.objects.create(room_number=no, price=price, status=status, floor=floor,
                               max_occupants=people, amenities=amenities, description=description)


class PublicPagesTests(TestCase):
    def setUp(self):
        self.r101 = room('101', 2000000, floor=1, amenities='Điều hòa, Wifi', description='Phòng thoáng')
        self.r201 = room('201', 3200000, floor=2, people=3)
        self.rented = room('102', status='dang_thue')
        self.fixing = room('103', status='bao_tri')

    def test_anonymous_sees_landing_and_pages_without_login(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tìm phòng trọ ưng ý')
        self.assertContains(r, 'P.101')
        for name in ['public_rooms', 'appointment_lookup']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_list_only_shows_free_rooms(self):
        r = self.client.get(reverse('public_rooms'))
        self.assertEqual({x.room_number for x in r.context['rooms']}, {'101', '201'})
        self.assertNotContains(r, 'P.102')

    def test_list_filters_and_sort(self):
        def numbers(**p):
            return [x.room_number for x in self.client.get(reverse('public_rooms'), p).context['rooms']]
        self.assertEqual(numbers(price='duoi2'), [])
        self.assertEqual(numbers(price='2-3'), ['101'])
        self.assertEqual(numbers(price='tren3'), ['201'])
        self.assertEqual(numbers(floor=2), ['201'])
        self.assertEqual(numbers(people=3), ['201'])
        self.assertEqual(numbers(sort='gia_giam'), ['201', '101'])
        self.assertEqual(numbers(price='bậy', floor='x', people='y'), ['101', '201'])

    def test_detail_shows_info_and_booking_form_for_free_room(self):
        r = self.client.get(reverse('public_room_detail', args=[self.r101.pk]))
        self.assertContains(r, 'Phòng thoáng')
        self.assertContains(r, 'Điều hòa')
        self.assertContains(r, 'Đặt lịch xem phòng')
        self.assertEqual(self.client.get(reverse('public_room_detail', args=[999])).status_code, 404)

    def test_detail_of_rented_room_has_no_form(self):
        r = self.client.get(reverse('public_room_detail', args=[self.rented.pk]))
        self.assertContains(r, 'Phòng này đã có người thuê')
        self.assertNotContains(r, 'name="visitor_phone"')
        r = self.client.post(reverse('public_room_detail', args=[self.rented.pk]), {})
        self.assertRedirects(r, reverse('public_room_detail', args=[self.rented.pk]))
        self.assertFalse(ViewingAppointment.objects.exists())


class BookingTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = room('101')
        self.url = reverse('public_room_detail', args=[self.room.pk])

    def data(self, **kw):
        d = {'visitor_name': 'Nguyễn Văn A', 'visitor_phone': '0912 345 678',
             'appointment_date': (self.today + timedelta(days=2)).isoformat(), 'slot': 'sang', 'note': ''}
        d.update(kw)
        return d

    def test_booking_creates_appointment_with_code_and_shows_status(self):
        r = self.client.post(self.url, self.data())
        a = ViewingAppointment.objects.get()
        self.assertRedirects(r, reverse('appointment_status', args=[a.code]))
        self.assertRegex(a.code, r'^LH[A-Z2-9]{6}$')
        self.assertEqual(a.visitor_phone, '0912345678')
        self.assertEqual(a.status, 'cho_xac_nhan')
        page = self.client.get(reverse('appointment_status', args=[a.code.lower()]))
        self.assertContains(page, a.code)
        self.assertContains(page, 'Chủ trọ sẽ liên hệ')

    def test_validation(self):
        past = (self.today - timedelta(days=1)).isoformat()
        far = (self.today + timedelta(days=60)).isoformat()
        for bad, text in [({'appointment_date': past}, 'quá khứ'), ({'appointment_date': far}, 'trong vòng 30 ngày'),
                          ({'visitor_phone': 'abc'}, 'không hợp lệ'), ({'visitor_name': ''}, 'bắt buộc')]:
            r = self.client.post(self.url, self.data(**bad))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, text)
        self.assertFalse(ViewingAppointment.objects.exists())

    def test_duplicate_and_limit(self):
        self.client.post(self.url, self.data())
        r = self.client.post(self.url, self.data())
        self.assertContains(r, 'đã đặt lịch xem phòng này vào ngày đó')
        for i, no in enumerate(['102', '103'], start=3):
            other = room(no)
            self.client.post(reverse('public_room_detail', args=[other.pk]),
                             self.data(appointment_date=(self.today + timedelta(days=i)).isoformat()))
        extra = room('104')
        r = self.client.post(reverse('public_room_detail', args=[extra.pk]),
                             self.data(appointment_date=(self.today + timedelta(days=9)).isoformat()))
        self.assertContains(r, '3 lịch hẹn chưa hoàn tất')
        self.assertEqual(ViewingAppointment.objects.count(), 3)

    def test_lookup(self):
        self.client.post(self.url, self.data())
        code = ViewingAppointment.objects.get().code
        r = self.client.get(reverse('appointment_lookup'), {'code': f' {code.lower()} '})
        self.assertRedirects(r, reverse('appointment_status', args=[code]))
        r = self.client.get(reverse('appointment_lookup'), {'code': 'LHXXXXXX'})
        self.assertContains(r, 'Không tìm thấy lịch hẹn')
        self.assertEqual(self.client.get(reverse('appointment_status', args=['NOPE'])).status_code, 404)


class OwnerAppointmentTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)
        self.room = room('101')
        self.a = ViewingAppointment.objects.create(
            room=self.room, visitor_name='Khách A', visitor_phone='0912345678',
            appointment_date=self.today + timedelta(days=2), slot='chieu')

    def login(self):
        self.client.login(username='chutro', password='pw12345!')

    def test_permissions(self):
        urls = [reverse('appointment_list'), reverse('appointment_detail', args=[self.a.pk])]
        for url in urls:
            self.assertIn('/dang-nhap/', self.client.get(url)['Location'])
        t = Tenant.objects.create(full_name='T', id_card_number='012345678901', phone='0900000000')
        other = room('102')
        services.create_contract(other, [t], t, self.today, self.today + timedelta(days=30), Decimal(0))
        self.client.login(username='012345678901', password='012345678901')
        for url in urls:
            self.assertRedirects(self.client.get(url), reverse('home'), fetch_redirect_response=False)
        r = self.client.post(reverse('appointment_set_status', args=[self.a.pk]), {'status': 'da_xac_nhan'})
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'cho_xac_nhan')

    def test_list_counts_filter_search(self):
        self.login()
        r = self.client.get(reverse('appointment_list'))
        self.assertEqual(r.context['counts']['cho_xac_nhan'], 1)
        self.assertContains(r, self.a.code)
        self.assertEqual(len(self.client.get(reverse('appointment_list'), {'status': 'huy'}).context['items']), 0)
        self.assertEqual(len(self.client.get(reverse('appointment_list'), {'q': 'khach a'}).context['items']), 1)
        self.assertEqual(len(self.client.get(reverse('appointment_list'), {'q': '0912345'}).context['items']), 1)
        self.assertNotContains(r, 'href="/admin/')

    def test_status_flow_and_invalid_jump(self):
        self.login()
        url = reverse('appointment_set_status', args=[self.a.pk])
        self.client.post(url, {'status': 'da_chot'})                        # nhảy cóc: không cho
        self.a.refresh_from_db(); self.assertEqual(self.a.status, 'cho_xac_nhan')
        self.client.post(url, {'status': 'da_xac_nhan', 'owner_note': 'Gọi khi tới'})
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.owner_note), ('da_xac_nhan', 'Gọi khi tới'))
        self.client.post(url, {'status': 'da_xem'})
        self.client.post(url, {'status': 'huy'})
        self.a.refresh_from_db(); self.assertEqual(self.a.status, 'huy')
        self.client.post(url, {'status': 'da_xac_nhan'})                    # đã hủy: không đổi nữa
        self.a.refresh_from_db(); self.assertEqual(self.a.status, 'huy')
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_reschedule(self):
        self.login()
        url = reverse('appointment_reschedule', args=[self.a.pk])
        new = self.today + timedelta(days=5)
        self.client.post(url, {'appointment_date': new.isoformat(), 'slot': 'toi'})
        self.a.refresh_from_db()
        self.assertEqual((self.a.appointment_date, self.a.slot), (new, 'toi'))
        self.client.post(url, {'appointment_date': (self.today - timedelta(days=1)).isoformat(), 'slot': 'sang'})
        self.a.refresh_from_db(); self.assertEqual(self.a.appointment_date, new)

    def test_contract_from_appointment_marks_it_closed(self):
        self.a.status = 'da_xem'; self.a.save()
        t = Tenant.objects.create(full_name='Khách A', id_card_number='012345678901', phone='0912345678')
        self.login()
        r = self.client.get(reverse('contract_create'), {'appointment': self.a.pk})
        self.assertEqual(r.context['form']['room'].value(), self.room.pk)
        self.assertContains(r, 'full_name=Kh%C3%A1ch%20A')
        self.client.post(reverse('contract_create'), {
            'room': self.room.pk, 'tenants': [t.pk], 'representative': t.pk, 'appointment': self.a.pk,
            'start_date': self.today.isoformat(), 'end_date': (self.today + timedelta(days=365)).isoformat(),
            'deposit': '2.000.000'})
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, 'da_chot')

    def test_tenant_form_prefilled_from_visitor(self):
        self.login()
        r = self.client.get(reverse('tenant_create'), {'full_name': 'Khách A', 'phone': '0912345678'})
        self.assertContains(r, 'value="Khách A"')
        self.assertContains(r, 'value="0912345678"')

    def test_overview_lists_pending_appointment(self):
        self.login()
        tasks = self.client.get(reverse('owner_dashboard')).context['tasks']
        self.assertIn('Lịch hẹn xem phòng mới', [t['title'] for t in tasks])