from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from billing.models import Invoice, Payment
from rooms.models import Contract, ContractTenant, Room
from .form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from .models import Tenant, User
from .text import normalize


def rent(room_number, cccd, name, status='hieu_luc', start=date(2026, 1, 1), representative=True):
    room = Room.objects.create(room_number=room_number, price=Decimal('2000000'))
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='09' + cccd[-8:])
    contract = Contract.objects.create(room=room, start_date=start, end_date=date(2030, 1, 1), status=status)
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=representative)
    return tenant, contract


class TextAndFieldTests(SimpleTestCase):
    def test_normalize(self):
        self.assertEqual(normalize('Nguyễn Văn Đạt'), 'nguyen van dat')
        self.assertEqual(normalize('  Đỗ Hoàng Nam'), '  do hoang nam')
        self.assertEqual(normalize(None), '')

    def test_money_field_parsing(self):
        field = MoneyField(max_digits=10, decimal_places=2)
        self.assertEqual(field.clean('2.500.000'), Decimal('2500000'))
        self.assertEqual(field.clean('2500000'), Decimal('2500000'))
        self.assertEqual(field.clean('2 500 000'), Decimal('2500000'))
        self.assertEqual(field.clean('2.500.000,50'), Decimal('2500000.50'))
        with self.assertRaises(Exception):
            field.clean('abc')

    def test_money_widget_formats_whole_numbers_with_dots(self):
        widget = MoneyField(max_digits=10, decimal_places=2).widget
        self.assertEqual(widget.format_value(Decimal('2500000.00')), '2.500.000')
        self.assertEqual(widget.format_value(None), '')

    def test_plain_decimal_widget(self):
        widget = PlainDecimalInput()
        self.assertEqual(widget.format_value(Decimal('20.00')), '20')
        self.assertEqual(widget.format_value(Decimal('20.50')), '20.5')
        self.assertEqual(widget.format_value(Decimal('100.00')), '100')
        self.assertEqual(widget.format_value(None), '')

    def test_flexible_decimal(self):
        field = FlexibleDecimalField(max_digits=5, decimal_places=2)
        self.assertEqual(field.clean('20,5'), Decimal('20.5'))
        self.assertEqual(field.clean('20.5'), Decimal('20.5'))


class TenantBase(TestCase):
    def setUp(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)

    def login_owner(self):
        self.client.login(username='chutro', password='pw12345!')


class TenantPermissionTests(TenantBase):
    def test_anonymous_redirected(self):
        for name in ['tenant_list', 'tenant_create']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn('/dang-nhap/', r['Location'])

    def test_tenant_cannot_use_owner_pages_or_actions(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        other, _ = rent('102', '012345678902', 'Tran B')
        self.client.login(username='012345678901', password='012345678901')
        self.assertRedirects(self.client.get(reverse('tenant_list')), reverse('home'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('tenant_detail', args=[other.pk])), reverse('home'), fetch_redirect_response=False)
        r = self.client.post(reverse('tenant_reset_password', args=[other.pk]))
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        r = self.client.post(reverse('tenant_toggle_active', args=[other.pk]))
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        other.user.refresh_from_db()
        self.assertTrue(other.user.is_active)

    def test_owner_pages_have_no_admin_links(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        self.login_owner()
        for url in [reverse('tenant_list'), reverse('tenant_create'), reverse('tenant_detail', args=[tenant.pk]),
                    reverse('tenant_update', args=[tenant.pk]), reverse('tenant_delete', args=[tenant.pk])]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'href="/admin/')


class TenantCreateUpdateTests(TenantBase):
    def valid(self, **extra):
        data = {'full_name': 'Nguyễn Minh An', 'phone': '0987 654 321', 'id_card_number': '012345678901',
                'email': '', 'date_of_birth': '2003-04-12', 'hometown': 'Đà Nẵng',
                'occupation': 'Sinh viên', 'note': 'Ở gọn gàng'}
        data.update(extra)
        return data

    def test_create(self):
        self.login_owner()
        r = self.client.post(reverse('tenant_create'), self.valid())
        tenant = Tenant.objects.get(id_card_number='012345678901')
        self.assertRedirects(r, reverse('tenant_detail', args=[tenant.pk]))
        self.assertEqual(tenant.occupation, 'Sinh viên')
        self.assertIsNone(tenant.email)
        self.assertEqual(tenant.date_of_birth, date(2003, 4, 12))
        self.assertIsNone(tenant.user)   # chưa là người đại diện nên chưa có tài khoản

    def test_validation_errors(self):
        self.login_owner()
        r = self.client.post(reverse('tenant_create'), self.valid(id_card_number='123'))
        self.assertContains(r, 'Số CCCD phải gồm 12 chữ số')
        r = self.client.post(reverse('tenant_create'), self.valid(phone='abc'))
        self.assertContains(r, 'Số điện thoại không hợp lệ')
        r = self.client.post(reverse('tenant_create'), self.valid(full_name=''))
        self.assertTrue(r.context['form'].errors)
        self.assertFalse(Tenant.objects.exists())

    def test_duplicate_cccd_rejected(self):
        Tenant.objects.create(full_name='A', id_card_number='012345678901', phone='0900000000')
        self.login_owner()
        r = self.client.post(reverse('tenant_create'), self.valid())
        self.assertContains(r, 'Số CCCD này đã có trong hệ thống.')
        self.assertEqual(Tenant.objects.count(), 1)

    def test_update_profile(self):
        tenant = Tenant.objects.create(full_name='A', id_card_number='012345678901', phone='0900000000')
        self.login_owner()
        self.client.post(reverse('tenant_update', args=[tenant.pk]), self.valid(full_name='Nguyễn Minh An 2'))
        tenant.refresh_from_db()
        self.assertEqual(tenant.full_name, 'Nguyễn Minh An 2')

    def test_cccd_locked_when_account_exists(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        self.login_owner()
        r = self.client.get(reverse('tenant_update', args=[tenant.pk]))
        self.assertContains(r, 'không đổi được số CCCD')
        self.client.post(reverse('tenant_update', args=[tenant.pk]),
                         self.valid(id_card_number='999999999999', full_name='Nguyen A'))
        tenant.refresh_from_db()
        self.assertEqual(tenant.id_card_number, '012345678901')


class TenantListTests(TenantBase):
    def setUp(self):
        super().setUp()
        rent('101', '012345678901', 'Nguyễn Minh An')
        rent('102', '012345678902', 'Trần Thị Mai')
        rent('103', '012345678903', 'Đỗ Hoàng Nam', status='ket_thuc')
        Tenant.objects.create(full_name='Phạm Khánh Linh', id_card_number='012345678904', phone='0966112233')
        self.login_owner()

    def test_stats(self):
        r = self.client.get(reverse('tenant_list'))
        self.assertEqual(r.context['total'], 4)
        self.assertEqual(r.context['counts'], {'dang_thue': 2, 'da_tra': 1, 'chua_thue': 1})
        self.assertEqual(r.context['pct_dang'], 50)
        self.assertEqual(r.context['pct_tra'], 25)
        self.assertContains(r, 'Đã trả phòng')

    def test_row_data(self):
        r = self.client.get(reverse('tenant_list'))
        rows = {row['tenant'].full_name: row for row in r.context['rows']}
        self.assertEqual(rows['Nguyễn Minh An']['room'].room_number, '101')
        self.assertEqual(rows['Nguyễn Minh An']['state'], 'dang_thue')
        self.assertEqual(rows['Đỗ Hoàng Nam']['state'], 'da_tra')
        self.assertEqual(rows['Đỗ Hoàng Nam']['room'].room_number, '103')
        self.assertEqual(rows['Phạm Khánh Linh']['state'], 'chua_thue')
        self.assertIsNone(rows['Phạm Khánh Linh']['room'])

    def test_filter_by_status(self):
        r = self.client.get(reverse('tenant_list'), {'status': 'da_tra'})
        self.assertEqual([x['tenant'].full_name for x in r.context['rows']], ['Đỗ Hoàng Nam'])

    def test_search_by_name_without_accents_and_by_phone(self):
        r = self.client.get(reverse('tenant_list'), {'q': 'tran thi'})
        self.assertEqual([x['tenant'].full_name for x in r.context['rows']], ['Trần Thị Mai'])
        r = self.client.get(reverse('tenant_list'), {'q': 'do hoang'})
        self.assertEqual([x['tenant'].full_name for x in r.context['rows']], ['Đỗ Hoàng Nam'])
        r = self.client.get(reverse('tenant_list'), {'q': '0966 112'})
        self.assertEqual([x['tenant'].full_name for x in r.context['rows']], ['Phạm Khánh Linh'])

    def test_current_contract_beats_old_one(self):
        old_room = Room.objects.create(room_number='900', price=1)
        tenant = Tenant.objects.get(full_name='Nguyễn Minh An')
        old = Contract.objects.create(room=old_room, start_date=date(2020, 1, 1), end_date=date(2021, 1, 1), status='ket_thuc')
        ContractTenant.objects.create(contract=old, tenant=tenant)
        r = self.client.get(reverse('tenant_list'))
        row = next(x for x in r.context['rows'] if x['tenant'] == tenant)
        self.assertEqual(row['state'], 'dang_thue')
        self.assertEqual(row['room'].room_number, '101')

    def test_empty_state(self):
        Tenant.objects.all().delete()
        r = self.client.get(reverse('tenant_list'))
        self.assertContains(r, 'Chưa có người thuê nào.')


class TenantDetailTests(TenantBase):
    def test_detail_tabs_and_debt(self):
        tenant, contract = rent('101', '012345678901', 'Nguyễn Minh An')
        inv = Invoice.objects.create(contract=contract, month=10, year=2026, room_fee=Decimal('2000000'),
                                     total_amount=Decimal('2835000'), due_date=date(2026, 10, 5))
        Payment.objects.create(invoice=inv, amount=Decimal('1000000'), paid_date=date(2026, 10, 3))
        self.login_owner()
        r = self.client.get(reverse('tenant_detail', args=[tenant.pk]))
        self.assertContains(r, 'Nguyễn Minh An')
        self.assertContains(r, 'Đang thuê')
        self.assertContains(r, 'P.101')
        self.assertContains(r, '1.835.000 đ')          # công nợ
        self.assertContains(r, '1.000.000 đ')          # lịch sử thanh toán
        self.assertContains(r, 'Tên đăng nhập')
        self.assertContains(r, '012345678901')

    def test_detail_without_account(self):
        tenant = Tenant.objects.create(full_name='Phạm Khánh Linh', id_card_number='012345678904', phone='0966112233')
        self.login_owner()
        r = self.client.get(reverse('tenant_detail', args=[tenant.pk]))
        self.assertContains(r, 'Chưa có tài khoản')
        self.assertContains(r, 'Không còn công nợ.')

    def test_missing_tenant_is_404(self):
        self.login_owner()
        self.assertEqual(self.client.get(reverse('tenant_detail', args=[999])).status_code, 404)


class TenantAccountActionTests(TenantBase):
    def test_reset_password_to_cccd(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        tenant.user.set_password('MatKhauKhac#1')
        tenant.user.save()
        self.login_owner()
        r = self.client.post(reverse('tenant_reset_password', args=[tenant.pk]))
        self.assertRedirects(r, reverse('tenant_detail', args=[tenant.pk]))
        self.client.logout()
        self.assertTrue(self.client.login(username='012345678901', password='012345678901'))

    def test_reset_requires_post(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        self.login_owner()
        self.assertEqual(self.client.get(reverse('tenant_reset_password', args=[tenant.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('tenant_toggle_active', args=[tenant.pk])).status_code, 405)

    def test_lock_and_unlock(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        self.login_owner()
        self.client.post(reverse('tenant_toggle_active', args=[tenant.pk]))
        tenant.user.refresh_from_db()
        self.assertFalse(tenant.user.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(username='012345678901', password='012345678901'))
        self.login_owner()
        self.client.post(reverse('tenant_toggle_active', args=[tenant.pk]))
        tenant.user.refresh_from_db()
        self.assertTrue(tenant.user.is_active)

    def test_actions_on_tenant_without_account_show_error(self):
        tenant = Tenant.objects.create(full_name='B', id_card_number='012345678904', phone='0966112233')
        self.login_owner()
        r = self.client.post(reverse('tenant_reset_password', args=[tenant.pk]), follow=True)
        self.assertContains(r, 'chưa có tài khoản')
        r = self.client.post(reverse('tenant_toggle_active', args=[tenant.pk]), follow=True)
        self.assertContains(r, 'chưa có tài khoản')


class TenantDeleteTests(TenantBase):
    def test_delete_tenant_without_contract(self):
        tenant = Tenant.objects.create(full_name='B', id_card_number='012345678904', phone='0966112233')
        self.login_owner()
        self.assertContains(self.client.get(reverse('tenant_delete', args=[tenant.pk])), 'Xóa hồ sơ B?')
        self.assertTrue(Tenant.objects.filter(pk=tenant.pk).exists())
        self.client.post(reverse('tenant_delete', args=[tenant.pk]))
        self.assertFalse(Tenant.objects.filter(pk=tenant.pk).exists())

    def test_tenant_with_contract_cannot_be_deleted(self):
        tenant, _ = rent('101', '012345678901', 'Nguyen A')
        self.login_owner()
        self.assertContains(self.client.get(reverse('tenant_delete', args=[tenant.pk])), 'không thể xóa')
        self.client.post(reverse('tenant_delete', args=[tenant.pk]))
        self.assertTrue(Tenant.objects.filter(pk=tenant.pk).exists())