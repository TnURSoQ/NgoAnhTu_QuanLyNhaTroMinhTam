from datetime import date

from django.test import Client, TestCase
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

    def test_login_returns_to_shared_public_home(self):
        response = self.client.post(reverse('login'), {'username': 'chutro', 'password': 'pw12345!'})
        self.assertRedirects(response, reverse('home'))
        page = self.client.get(response.url)
        self.assertTemplateUsed(page, 'public/home.html')
        self.assertContains(page, 'Quản lý phòng trọ')

    def test_logout_returns_to_shared_public_home(self):
        self.client.force_login(User.objects.get(username='chutro'))
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('home'))
        page = self.client.get(response.url)
        self.assertTemplateUsed(page, 'public/home.html')
        self.assertContains(page, 'Đăng nhập')
        self.assertNotContains(page, 'Menu tài khoản')

    def test_logged_in_user_skips_login_page(self):
        self.client.login(username='chutro', password='pw12345!')
        self.assertEqual(self.client.get(reverse('login')).status_code, 302)


class ModalLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('modal-owner', password='ModalLogin#2026', role=User.Role.OWNER)
        cls.tenant = User.objects.create_user('modal-tenant', password='ModalLogin#2026', role=User.Role.TENANT)
        Tenant.objects.create(user=cls.tenant, full_name='Người thuê', id_card_number='999', phone='0901234567')

    def post_login(self, **overrides):
        data = {'username': self.owner.username, 'password': 'ModalLogin#2026'}
        data.update(overrides)
        return self.client.post(reverse('login'), data, HTTP_ACCEPT='application/json')

    def test_public_pages_offer_login_modal_with_csrf_and_distinct_field_ids(self):
        for name in ('home', 'public_rooms', 'appointment_lookup'):
            response = self.client.get(reverse(name))
            self.assertContains(response, 'data-bs-target="#loginModal"')
            self.assertContains(response, 'id="modal_username"')
            self.assertContains(response, 'id="modal_password"')
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
            self.assertContains(response, '/static/js/login-modal.js')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('home')), 'id="loginModal"')

    def test_invalid_credentials_and_required_fields_return_inline_errors(self):
        response = self.post_login(password='wrong')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors']['__all__'][0]['code'], 'invalid_login')
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.post_login(username='', password='')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()['errors']), {'username', 'password'})

    def test_owner_and_tenant_can_login_and_see_their_account_menu(self):
        for user, label in ((self.owner, 'Quản lý phòng trọ'), (self.tenant, 'Phòng của tôi')):
            with self.subTest(role=user.role):
                response = self.post_login(username=user.username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'redirect_url': reverse('home')})
                self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
                page = self.client.get(response.json()['redirect_url'])
                self.assertContains(page, label)
                self.assertNotContains(page, 'id="loginModal"')
                self.client.logout()

    def test_remember_me_retains_existing_session_behavior(self):
        for remember in ('on', ''):
            self.post_login(remember_me=remember)
            self.assertEqual(self.client.session.get_expire_at_browser_close(), not bool(remember))
            self.client.logout()

    def test_preserves_current_page_filters_and_rejects_external_redirects(self):
        target = reverse('public_rooms') + '?q=dieu+hoa&floor=1#phong-trong'
        response = self.post_login(next=target)
        self.assertEqual(response.json()['redirect_url'], target)
        self.client.logout()
        response = self.post_login(next='https://attacker.invalid/collect')
        self.assertEqual(response.json()['redirect_url'], reverse('home'))

    def test_inactive_account_cannot_login(self):
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        response = self.post_login()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_json_login_requires_valid_csrf_token(self):
        browser = Client(enforce_csrf_checks=True)
        browser.get(reverse('home'))
        data = {'username': self.owner.username, 'password': 'ModalLogin#2026'}
        self.assertEqual(browser.post(reverse('login'), data, HTTP_ACCEPT='application/json').status_code, 403)
        data['csrfmiddlewaretoken'] = browser.cookies['csrftoken'].value
        response = browser.post(reverse('login'), data, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(browser.session['_auth_user_id'], str(self.owner.pk))


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

    def test_developer_without_role_sees_public_home_and_admin_entry(self):
        User.objects.create_user('dev', password='pw12345!', is_staff=True, is_superuser=True)
        self.client.login(username='dev', password='pw12345!')
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'public/home.html')
        self.assertContains(response, 'href="/admin/"')

    def test_developer_without_role_is_not_owner(self):
        User.objects.create_user('dev', password='pw12345!', is_staff=True, is_superuser=True)
        self.client.login(username='dev', password='pw12345!')
        for name in ['owner_dashboard', 'room_list', 'tenant_list', 'report_dashboard']:
            self.assertRedirects(self.client.get(reverse(name)), reverse('home'),
                                 fetch_redirect_response=False)
