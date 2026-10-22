from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Tenant, User
from rooms.models import Contract, ContractTenant, Room
from .models import Invoice, InvoiceService, Payment, Service


def make_tenant_with_invoice(cccd, name, room_number, month=10, year=2026):
    room = Room.objects.create(room_number=room_number, price=Decimal('2000000'), max_occupants=2)
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='0900000000')
    contract = Contract.objects.create(
        room=room, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), deposit=Decimal('2000000'))
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=True)
    invoice = Invoice.objects.create(
        contract=contract, month=month, year=year, room_fee=Decimal('2000000'),
        electric_fee=Decimal('227500'), water_fee=Decimal('45000'),
        total_amount=Decimal('0'), due_date=date(2099, 1, 1))
    svc = Service.objects.get_or_create(name='Wifi', defaults={'unit_price': Decimal('120000')})[0]
    InvoiceService.objects.create(invoice=invoice, service=svc, quantity=1)
    invoice.total_amount = Decimal('2392500')
    invoice.save()
    return tenant, invoice


class TenantPortalTests(TestCase):
    def setUp(self):
        self.tenant_a, self.inv_a = make_tenant_with_invoice('001', 'Nguyen A', '101')
        self.tenant_b, self.inv_b = make_tenant_with_invoice('002', 'Tran B', '102')
        Payment.objects.create(invoice=self.inv_a, amount=Decimal('1000000'), paid_date=date(2026, 10, 5))
        self.owner = User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER, is_staff=True)

    def login_a(self):
        self.assertTrue(self.client.login(username='001', password='001'))

    # --- tài khoản tự tạo và đăng nhập ---
    def test_representative_account_created_with_default_password(self):
        self.tenant_a.refresh_from_db()
        self.assertIsNotNone(self.tenant_a.user)
        self.assertEqual(self.tenant_a.user.role, User.Role.TENANT)
        self.assertFalse(self.tenant_a.user.is_staff)

    def test_login_view_with_cccd(self):
        r = self.client.post(reverse('login'), {'username': '001', 'password': '001'})
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)

    # --- chặn truy cập ---
    def test_anonymous_redirected_to_login(self):
        for name in ['my_invoices', 'my_payments', 'my_contracts']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assertIn('/dang-nhap/', r['Location'])

    def test_owner_goes_to_admin_not_portal(self):
        self.client.login(username='chutro', password='pw12345!')
        self.assertRedirects(self.client.get('/'), '/admin/', fetch_redirect_response=False)
        r = self.client.get(reverse('my_invoices'))
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)

    def test_user_without_role_gets_403_no_redirect_loop(self):
        User.objects.create_user('la', password='pw12345!')
        self.client.login(username='la', password='pw12345!')
        self.assertEqual(self.client.get('/').status_code, 403)
        r = self.client.get(reverse('my_invoices'), follow=True)
        self.assertEqual(r.status_code, 403)

    def test_tenant_cannot_enter_admin(self):
        self.login_a()
        r = self.client.get('/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])

    # --- cô lập dữ liệu giữa các người thuê ---
    def test_tenant_home_redirects_to_invoices(self):
        self.login_a()
        self.assertRedirects(self.client.get('/'), reverse('my_invoices'), fetch_redirect_response=False)

    def test_invoice_list_shows_only_own(self):
        self.login_a()
        r = self.client.get(reverse('my_invoices'))
        self.assertContains(r, 'Phòng 101')
        self.assertNotContains(r, 'Phòng 102')

    def test_cannot_open_other_tenants_invoice(self):
        self.login_a()
        self.assertEqual(self.client.get(reverse('my_invoice_detail', args=[self.inv_a.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('my_invoice_detail', args=[self.inv_b.pk])).status_code, 404)

    def test_payments_only_own(self):
        Payment.objects.create(invoice=self.inv_b, amount=Decimal('777000'), paid_date=date(2026, 10, 6))
        self.login_a()
        r = self.client.get(reverse('my_payments'))
        self.assertContains(r, '1.000.000đ')
        self.assertNotContains(r, '777.000')

    def test_contracts_only_own(self):
        self.login_a()
        r = self.client.get(reverse('my_contracts'))
        self.assertContains(r, 'Phòng 101')
        self.assertNotContains(r, 'Phòng 102')
        self.assertNotContains(r, 'Tran B')

    # --- hiển thị tiền ---
    def test_money_formatting_and_remaining(self):
        self.login_a()
        r = self.client.get(reverse('my_invoice_detail', args=[self.inv_a.pk]))
        self.assertContains(r, '2.392.500đ')   # tổng
        self.assertContains(r, '1.392.500đ')   # còn nợ = 2.392.500 - 1.000.000
        r = self.client.get(reverse('my_invoices'))
        self.assertContains(r, '1.392.500đ')   # tổng nợ trên danh sách

    # --- đăng xuất và đổi mật khẩu ---
    def test_logout_requires_post(self):
        self.login_a()
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        r = self.client.post(reverse('logout'))
        self.assertRedirects(r, reverse('login'), fetch_redirect_response=False)

    def test_default_password_banner_then_change(self):
        self.login_a()
        self.assertContains(self.client.get(reverse('my_invoices')), 'mật khẩu mặc định')
        r = self.client.post(reverse('password_change'), {
            'old_password': '001', 'new_password1': 'MatKhauMoi#2026x', 'new_password2': 'MatKhauMoi#2026x'})
        self.assertRedirects(r, reverse('password_change_done'))
        self.assertNotContains(self.client.get(reverse('my_invoices')), 'mật khẩu mặc định')