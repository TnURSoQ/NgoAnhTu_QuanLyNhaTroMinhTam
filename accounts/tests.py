from datetime import date

from django.test import TestCase
from django.urls import reverse

from rooms.models import Contract, ContractTenant, Room
from .models import Tenant, User


def make_tenant_account(cccd='001', name='Nguyen A'):
    room = Room.objects.create(room_number='101', price=1)
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='0900000000')
    contract = Contract.objects.create(room=room, start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=True)
    return tenant


class LoginPageTests(TestCase):
    def setUp(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)

    def test_login_page_renders(self):
        r = self.client.get(reverse('login'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Chào mừng đến với Nhà trọ Minh Tâm')
        self.assertContains(r, 'Ghi nhớ đăng nhập')
        self.assertContains(r, 'Quên mật khẩu?')

    def test_wrong_password_shows_error(self):
        r = self.client.post(reverse('login'), {'username': 'chutro', 'password': 'sai'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['form'].errors)

    def test_remember_me_keeps_session_after_browser_close(self):
        self.client.post(reverse('login'), {'username': 'chutro', 'password': 'pw12345!', 'remember_me': 'on'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_without_remember_me_session_ends_with_browser(self):
        self.client.post(reverse('login'), {'username': 'chutro', 'password': 'pw12345!'})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_logged_in_user_skips_login_page(self):
        self.client.login(username='chutro', password='pw12345!')
        self.assertEqual(self.client.get(reverse('login')).status_code, 302)


class SidebarTests(TestCase):
    def test_owner_sees_owner_menu_without_admin(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)
        self.client.login(username='chutro', password='pw12345!')
        r = self.client.get(reverse('owner_dashboard'))
        for text in ['Tổng quan', 'Phòng', 'Người thuê', 'Hợp đồng', 'Hóa đơn', 'Báo cáo', 'Chủ trọ']:
            self.assertContains(r, text)
        self.assertNotContains(r, 'Quản trị hệ thống')
        self.assertNotContains(r, 'href="/admin/')
        self.assertNotContains(r, 'Thanh toán')

    def test_developer_sees_admin_link(self):
        User.objects.create_user('dev', password='pw12345!', role=User.Role.OWNER, is_staff=True)
        self.client.login(username='dev', password='pw12345!')
        r = self.client.get(reverse('owner_dashboard'))
        self.assertContains(r, 'Quản trị hệ thống')

    def test_tenant_sees_tenant_menu_only(self):
        make_tenant_account('001')
        self.client.login(username='001', password='001')
        r = self.client.get(reverse('my_invoices'))
        for text in ['Hóa đơn', 'Thanh toán', 'Hợp đồng', 'Đổi mật khẩu', 'Người thuê']:
            self.assertContains(r, text)
        self.assertNotContains(r, 'Quản trị')
        self.assertNotContains(r, 'Báo cáo')
        self.assertNotContains(r, reverse('room_list'))

    def test_active_menu_item_is_marked(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)
        self.client.login(username='chutro', password='pw12345!')
        r = self.client.get(reverse('owner_dashboard'))
        self.assertContains(r, 'nav-item-link active')


class RoleAccessTests(TestCase):
    def test_owner_cannot_enter_django_admin(self):
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)
        self.client.login(username='chutro', password='pw12345!')
        r = self.client.get('/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])

    def test_developer_without_role_goes_to_admin(self):
        User.objects.create_user('dev', password='pw12345!', is_staff=True, is_superuser=True)
        self.client.login(username='dev', password='pw12345!')
        self.assertRedirects(self.client.get('/'), '/admin/', fetch_redirect_response=False)

    def test_developer_without_role_is_not_owner(self):
        User.objects.create_user('dev', password='pw12345!', is_staff=True, is_superuser=True)
        self.client.login(username='dev', password='pw12345!')
        for name in ['owner_dashboard', 'room_list', 'tenant_list', 'report_dashboard']:
            self.assertRedirects(self.client.get(reverse(name)), reverse('home'),
                                 fetch_redirect_response=False)