from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Tenant, User
from billing.models import Invoice, Payment
from .models import Contract, ContractTenant, Room


def rent(room, cccd, name, end=None):
    """Cho một người thuê (đại diện) vào phòng bằng một hợp đồng đang hiệu lực."""
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='09' + cccd)
    contract = Contract.objects.create(
        room=room, start_date=date(2026, 1, 1), end_date=end or date(2030, 1, 1), deposit=Decimal('2000000'))
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=True)
    return tenant, contract


class RoomOwnerBase(TestCase):
    def setUp(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)

    def login_owner(self):
        self.client.login(username='chutro', password='pw12345!')


class RoomPermissionTests(RoomOwnerBase):
    URLS = ['room_list', 'room_create']

    def test_anonymous_redirected_to_login(self):
        for name in self.URLS:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn('/dang-nhap/', r['Location'])

    def test_tenant_cannot_access(self):
        room = Room.objects.create(room_number='101', price=1)
        rent(room, '001', 'Nguyen A')
        self.client.login(username='001', password='001')
        for name in self.URLS:
            self.assertRedirects(self.client.get(reverse(name)), reverse('home'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('room_detail', args=[room.pk])),
                             reverse('home'), fetch_redirect_response=False)
        r = self.client.post(reverse('room_delete', args=[room.pk]))
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_owner_pages_have_no_admin_links(self):
        room = Room.objects.create(room_number='101', price=1)
        self.login_owner()
        for url in [reverse('room_list'), reverse('room_create'), reverse('room_detail', args=[room.pk]),
                    reverse('room_update', args=[room.pk]), reverse('room_delete', args=[room.pk])]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'href="/admin/')


class RoomCreateUpdateTests(RoomOwnerBase):
    def test_create_with_vietnamese_number_formats(self):
        self.login_owner()
        r = self.client.post(reverse('room_create'), {
            'room_number': '101', 'floor': 1, 'area': '20,5', 'max_occupants': 2,
            'price': '2.500.000', 'status': 'trong'})
        room = Room.objects.get(room_number='101')
        self.assertRedirects(r, reverse('room_detail', args=[room.pk]))
        self.assertEqual(room.price, Decimal('2500000'))
        self.assertEqual(room.area, Decimal('20.5'))

    def test_create_with_plain_number_and_dot_decimal_area(self):
        self.login_owner()
        self.client.post(reverse('room_create'), {
            'room_number': '102', 'floor': 1, 'area': '18.5', 'max_occupants': 1,
            'price': '2300000', 'status': 'trong'})
        room = Room.objects.get(room_number='102')
        self.assertEqual(room.price, Decimal('2300000'))
        self.assertEqual(room.area, Decimal('18.5'))

    def test_duplicate_room_number_rejected(self):
        Room.objects.create(room_number='101', price=1)
        self.login_owner()
        r = self.client.post(reverse('room_create'), {
            'room_number': '101', 'floor': 1, 'max_occupants': 1, 'price': '1000000', 'status': 'trong'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Số phòng này đã tồn tại.')
        self.assertEqual(Room.objects.count(), 1)

    def test_invalid_values_rejected(self):
        self.login_owner()
        for price in ['0', 'abc', '']:
            r = self.client.post(reverse('room_create'), {
                'room_number': '201', 'floor': 2, 'max_occupants': 1, 'price': price, 'status': 'trong'})
            self.assertEqual(r.status_code, 200, price)
            self.assertTrue(r.context['form'].errors, price)
        r = self.client.post(reverse('room_create'), {
            'room_number': '201', 'floor': 2, 'max_occupants': 0, 'price': '1000000', 'status': 'trong'})
        self.assertContains(r, 'Sức chứa tối đa phải từ 1 người trở lên.')
        self.assertFalse(Room.objects.exists())

    def test_form_shows_error_styling(self):
        self.login_owner()
        r = self.client.post(reverse('room_create'), {'room_number': '', 'floor': 1, 'max_occupants': 1, 'price': '1', 'status': 'trong'})
        self.assertContains(r, 'is-invalid')

    def test_update_changes_price(self):
        room = Room.objects.create(room_number='101', price=Decimal('1000000'), max_occupants=2)
        self.login_owner()
        r = self.client.get(reverse('room_update', args=[room.pk]))
        self.assertContains(r, 'value="1.000.000"')
        self.client.post(reverse('room_update', args=[room.pk]), {
            'room_number': '101', 'floor': 3, 'max_occupants': 2, 'price': '2.800.000', 'status': 'bao_tri'})
        room.refresh_from_db()
        self.assertEqual(room.price, Decimal('2800000'))
        self.assertEqual(room.floor, 3)
        self.assertEqual(room.status, 'bao_tri')

    def test_status_locked_while_room_has_active_contract(self):
        room = Room.objects.create(room_number='101', price=1)
        rent(room, '001', 'Nguyen A')
        self.login_owner()
        self.client.post(reverse('room_update', args=[room.pk]), {
            'room_number': '101', 'floor': 1, 'max_occupants': 2, 'price': '1', 'status': 'trong'})
        room.refresh_from_db()
        self.assertEqual(room.status, 'dang_thue')

    def test_status_choices_are_limited_for_empty_room(self):
        room = Room.objects.create(room_number='101', price=1)
        self.login_owner()
        r = self.client.get(reverse('room_update', args=[room.pk]))
        self.assertNotContains(r, 'value="dang_thue"')


class RoomListTests(RoomOwnerBase):
    def setUp(self):
        super().setUp()
        self.r101 = Room.objects.create(room_number='101', price=2500000, floor=1, area=20)
        self.r102 = Room.objects.create(room_number='102', price=2300000, floor=1)
        self.r201 = Room.objects.create(room_number='201', price=2800000, floor=2, status='bao_tri')
        rent(self.r101, '001', 'Nguyễn Minh An')
        self.login_owner()

    def test_counts_and_cards(self):
        r = self.client.get(reverse('room_list'))
        self.assertEqual(r.context['counts'], {'all': 3, 'dang_thue': 1, 'trong': 1, 'bao_tri': 1})
        self.assertContains(r, 'P.101')
        self.assertContains(r, '2.500.000 đ')
        self.assertContains(r, 'Nguyễn Minh An')
        self.assertContains(r, 'Chưa có người thuê')

    def test_filter_by_status(self):
        r = self.client.get(reverse('room_list'), {'status': 'trong'})
        self.assertEqual([i['room'].room_number for i in r.context['items']], ['102'])
        r = self.client.get(reverse('room_list'), {'status': 'khong-hop-le'})
        self.assertEqual(len(r.context['items']), 3)

    def test_filter_by_floor(self):
        r = self.client.get(reverse('room_list'), {'floor': 2})
        self.assertEqual([i['room'].room_number for i in r.context['items']], ['201'])
        r = self.client.get(reverse('room_list'), {'floor': 'abc'})
        self.assertEqual(len(r.context['items']), 3)

    def test_search_room_number_and_tenant_without_accents(self):
        r = self.client.get(reverse('room_list'), {'q': '102'})
        self.assertEqual([i['room'].room_number for i in r.context['items']], ['102'])
        r = self.client.get(reverse('room_list'), {'q': 'nguyen minh'})
        self.assertEqual([i['room'].room_number for i in r.context['items']], ['101'])
        r = self.client.get(reverse('room_list'), {'q': 'NGUYỄN'})
        self.assertEqual([i['room'].room_number for i in r.context['items']], ['101'])

    def test_search_with_no_result_shows_message(self):
        r = self.client.get(reverse('room_list'), {'q': 'khong co'})
        self.assertContains(r, 'Không tìm thấy phòng nào phù hợp.')

    def test_combined_filters_keep_in_tab_links(self):
        r = self.client.get(reverse('room_list'), {'q': 'a', 'floor': 1})
        self.assertContains(r, 'q=a')
        self.assertContains(r, 'floor=1')


class RoomDetailTests(RoomOwnerBase):
    def test_detail_with_contract_and_invoice(self):
        room = Room.objects.create(room_number='101', price=Decimal('2500000'), floor=1, area=20, max_occupants=2)
        _, contract = rent(room, '001', 'Nguyễn Minh An')
        inv = Invoice.objects.create(contract=contract, month=10, year=2026, room_fee=Decimal('2500000'),
                                     total_amount=Decimal('2835000'), due_date=date(2026, 10, 5))
        Payment.objects.create(invoice=inv, amount=Decimal('1000000'), paid_date=date(2026, 10, 3))
        self.login_owner()
        r = self.client.get(reverse('room_detail', args=[room.pk]))
        self.assertContains(r, 'Phòng P.101')
        self.assertContains(r, 'Nguyễn Minh An')
        self.assertContains(r, 'Đại diện')
        self.assertContains(r, contract.display_code)
        self.assertContains(r, '2.835.000 đ')   # tổng hóa đơn
        self.assertContains(r, '1.835.000 đ')   # còn nợ
        self.assertContains(r, '1/2')           # số người đang ở

    def test_detail_of_empty_room(self):
        room = Room.objects.create(room_number='102', price=1)
        self.login_owner()
        r = self.client.get(reverse('room_detail', args=[room.pk]))
        self.assertContains(r, 'Phòng chưa có người thuê.')
        self.assertContains(r, 'Chưa có hóa đơn nào.')

    def test_missing_room_is_404(self):
        self.login_owner()
        self.assertEqual(self.client.get(reverse('room_detail', args=[999])).status_code, 404)


class RoomDeleteTests(RoomOwnerBase):
    def test_confirm_page_then_delete_empty_room(self):
        room = Room.objects.create(room_number='101', price=1)
        self.login_owner()
        self.assertContains(self.client.get(reverse('room_delete', args=[room.pk])), 'Xóa phòng 101?')
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())   # GET không xóa
        r = self.client.post(reverse('room_delete', args=[room.pk]))
        self.assertRedirects(r, reverse('room_list'))
        self.assertFalse(Room.objects.filter(pk=room.pk).exists())

    def test_room_with_history_cannot_be_deleted(self):
        room = Room.objects.create(room_number='101', price=1)
        rent(room, '001', 'Nguyen A')
        self.login_owner()
        r = self.client.get(reverse('room_delete', args=[room.pk]))
        self.assertContains(r, 'không thể xóa')
        self.client.post(reverse('room_delete', args=[room.pk]))
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())