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
        self.assertContains(r, 'Đăng nhập')
        self.assertNotContains(r, 'Menu tài khoản')
        for name in ['public_rooms', 'appointment_lookup']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_owner_and_tenant_browse_public_pages_and_enter_their_own_area(self):
        for role, label, target, forbidden in [
            (User.Role.OWNER, 'Quản lý phòng trọ', 'owner_dashboard', 'my_room'),
            (User.Role.TENANT, 'Phòng của tôi', 'my_room', 'owner_dashboard'),
        ]:
            with self.subTest(role=role):
                user = User.objects.create_user(role, role=role)
                if role == User.Role.TENANT:
                    Tenant.objects.create(user=user, full_name='Người thuê', id_card_number='001', phone='0901234567')
                self.client.force_login(user)
                for url in [reverse('home'), reverse('public_rooms'),
                            reverse('public_room_detail', args=[self.r101.pk]), reverse('appointment_lookup')]:
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'Menu tài khoản')
                    self.assertContains(response, f'href="{reverse(target)}"')
                    self.assertContains(response, label)
                    self.assertNotContains(response, f'href="{reverse(forbidden)}"')
                    self.assertNotContains(response, 'Vào trang quản lý')
                home = self.client.get(reverse('home'))
                self.assertTemplateUsed(home, 'public/home.html')
                self.assertContains(home, 'P.101')
                self.assertNotContains(home, 'P.102')
                management = self.client.get(reverse(target))
                self.assertEqual(management.status_code, 200)
                self.assertContains(management, f'href="{reverse("home")}"')
                forbidden_page = self.client.get(reverse(forbidden), follow=True)
                self.assertTemplateUsed(forbidden_page, 'public/home.html')
                self.assertEqual(forbidden_page.redirect_chain, [(reverse('home'), 302)])

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

    def test_keyword_search_ignores_accents_and_searches_room_amenities_description(self):
        for page in ('home', 'public_rooms'):
            for query in ('101', 'P.101', 'dieu hoa', 'PHÒNG THOÁNG', 'wifi thoang'):
                with self.subTest(page=page, query=query):
                    response = self.client.get(reverse(page), {'q': query})
                    self.assertEqual(list(response.context['rooms']), [self.r101])
                    self.assertContains(response, f'value="{query}"')

    def test_combined_filters_and_reset_preserve_search_form_values(self):
        for page in ('home', 'public_rooms'):
            with self.subTest(page=page):
                response = self.client.get(reverse(page), {
                    'q': 'dieu hoa', 'price': '2-3', 'floor': 1, 'people': 2,
                    'amenity': 'Wifi', 'sort': 'gia_tang'})
                self.assertEqual(list(response.context['rooms']), [self.r101])
                self.assertEqual(response.context['filtered_count'], 1)
                self.assertEqual(response.context['total_free'], 2)
                self.assertContains(response, 'value="Wifi" selected')
                self.assertContains(response, 'value="gia_tang" selected')
                self.assertContains(response, f'href="{reverse(page)}#phong-trong"')
                self.assertContains(response, 'Xóa bộ lọc')

    def test_home_carousel_has_all_available_rooms_and_filters_beyond_first_three(self):
        for n in range(5):
            room(f'30{n}', floor=3)
        last = room('999', floor=9)
        home = self.client.get(reverse('home'))
        self.assertEqual(len(home.context['rooms']), 8)
        self.assertEqual(home.context['total_free'], 8)
        self.assertIn(last, home.context['rooms'])
        self.assertContains(home, 'data-room-showcase')
        self.assertContains(home, 'data-room-next')
        catalog = self.client.get(reverse('public_rooms'))
        self.assertEqual(len(catalog.context['rooms']), 8)
        self.assertNotContains(catalog, 'data-room-showcase')
        response = self.client.get(reverse('home'), {'floor': 9})
        self.assertEqual(list(response.context['rooms']), [last])

    def test_search_never_exposes_rented_rooms_and_shows_empty_state(self):
        for page in ('home', 'public_rooms'):
            response = self.client.get(reverse(page), {'q': self.rented.room_number})
            self.assertEqual(response.context['filtered_count'], 0)
            self.assertNotContains(response, 'Phòng P.102')
            self.assertContains(response, 'Chưa tìm thấy căn phòng phù hợp')

    def test_invalid_optional_filters_are_ignored(self):
        response = self.client.get(reverse('home'), {
            'people': '-4', 'floor': 'abc', 'amenity': 'unknown', 'sort': 'unknown', 'price': 'unknown'})
        self.assertFalse(response.context['has_filters'])
        self.assertEqual(response.context['filtered_count'], 2)


class HomeLivingAmenitiesTests(TestCase):
    def setUp(self):
        from .models import PropertyInfo
        PropertyInfo.objects.all().delete()

    def test_tiles_use_all_available_rooms_before_filters_and_six_room_limit(self):
        from .models import PropertyInfo
        from .amenities import amenity_tiles
        for number in range(7):
            room(f'A{number}', amenities='Điều hòa, điều hòa, Wifi', floor=1)
        room('Z99', amenities='Tủ quần áo, Chỗ để xe', floor=9)
        room('BUSY', status='dang_thue', amenities='Bể bơi riêng')
        room('FIX', status='bao_tri', amenities='Rạp phim riêng')
        PropertyInfo.objects.create(shared_amenities='Chỗ để xe, Máy giặt chung')
        for params in ({}, {'floor': 1}, {'q': 'không có phòng này'}):
            page = self.client.get(reverse('home'), params)
            names = [item['name'] for item in page.context['living_room_amenities']]
            self.assertEqual(names, ['Điều hòa', 'Tủ quần áo', 'Wifi'])
            self.assertEqual([item['name'] for item in page.context['living_shared_amenities']],
                             ['Chỗ để xe', 'Máy giặt chung'])
            self.assertNotIn('Chỗ để xe', names)
            self.assertNotContains(page, 'Bể bơi riêng')
            self.assertNotContains(page, 'Rạp phim riêng')
            self.assertContains(page, 'Tiện ích trong phòng')
            self.assertNotContains(page, 'Tùy từng phòng')
            self.assertNotContains(page, '>Dùng chung<')
            self.assertContains(page, 'Tiện ích chung của nhà trọ', count=1)
        self.assertEqual(len(amenity_tiles(['Điều hòa', 'điều hòa'])), 1)

    def test_custom_names_are_escaped_and_unknown_features_are_not_invented(self):
        room('101', amenities='<script>alert(1)</script>')
        page = self.client.get(reverse('home'))
        self.assertEqual(page.context['living_room_amenities'],
                         [{'name': '<script>alert(1)</script>', 'icon': 'bi-grid'}])
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertEqual(page.context['living_shared_amenities'], [])

    def test_no_data_shows_update_message_without_creating_configuration(self):
        from .models import PropertyInfo
        page = self.client.get(reverse('home'))
        self.assertContains(page, 'Thông tin tiện ích đang được chủ trọ cập nhật.')
        self.assertFalse(PropertyInfo.objects.exists())
        self.assertEqual(page.context['living_room_amenities'], [])
        self.assertEqual(page.context['living_shared_amenities'], [])


class BookingTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = room('101')
        self.url = reverse('public_room_detail', args=[self.room.pk])

    def data(self, **kw):
        d = {'visitor_name': 'Nguyễn Văn A', 'visitor_phone': '0912 345 678', 'visitor_email': 'khach@example.com',
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

    def test_invalid_submission_reopens_booking_modal_and_preserves_input(self):
        for data in ({}, self.data(visitor_email='invalid-email')):
            with self.subTest(data=data):
                response = self.client.post(self.url, data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].is_bound)
                self.assertTrue(response.context['form'].errors)
                self.assertContains(response, 'data-open-on-load="true"')
                self.assertContains(response, 'id="roomBookingModal"')
                if data:
                    self.assertContains(response, 'value="invalid-email"')
                self.assertFalse(ViewingAppointment.objects.exists())

    def test_logged_in_owner_and_tenant_can_still_book_from_public_pages(self):
        for index, role in enumerate((User.Role.OWNER, User.Role.TENANT)):
            with self.subTest(role=role):
                self.client.force_login(User.objects.create_user(role, role=role))
                phone = f'090123456{index}'
                response = self.client.post(self.url, self.data(visitor_phone=phone, visitor_email=f'khach{index}@example.com'))
                appointment = ViewingAppointment.objects.get(visitor_phone=phone)
                self.assertRedirects(response, reverse('appointment_status', args=[appointment.code]))

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
        self.assertNotContains(r, 'Xem trang khách thấy')

    def test_status_flow_and_invalid_jump(self):
        self.login()
        url = reverse('appointment_set_status', args=[self.a.pk])
        self.client.post(url, {'status': 'da_chot'})                        # nhảy cóc: không cho
        self.a.refresh_from_db(); self.assertEqual(self.a.status, 'cho_xac_nhan')
        self.client.post(url, {'status': 'da_xac_nhan', 'owner_note': 'Gọi khi tới', 'start_time': '14:00'})
        self.a.refresh_from_db()
        self.assertEqual((self.a.status, self.a.owner_note), ('da_xac_nhan', 'Gọi khi tới'))
        self.client.post(url, {'status': 'da_xem'})
        self.client.post(url, {'status': 'huy', 'owner_note': 'Khách chưa có nhu cầu thuê'})
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
