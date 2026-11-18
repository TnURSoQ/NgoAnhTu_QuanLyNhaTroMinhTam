from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from .models import User


def run(*args, **kw):
    out = StringIO()
    call_command('create_owner', *args, stdout=out, **kw)
    return out.getvalue()


class CreateOwnerCommandTests(TestCase):
    def test_creates_pure_owner_without_admin_rights(self):
        run('chutro', '--name', 'Trần Thị Mai', '--password', 'MatKhau#2026x')
        user = User.objects.get(username='chutro')
        self.assertEqual(user.role, User.Role.OWNER)
        self.assertEqual(user.first_name, 'Trần Thị Mai')
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(self.client.login(username='chutro', password='MatKhau#2026x'))

    def test_existing_account_gets_owner_role_and_keeps_password(self):
        User.objects.create_superuser('dev', password='MatKhauCu#1x', first_name='Tên có sẵn')
        out = run('dev')
        user = User.objects.get(username='dev')
        self.assertEqual(user.role, User.Role.OWNER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.first_name, 'Tên có sẵn')
        self.assertTrue(user.check_password('MatKhauCu#1x'))
        self.assertIn('gán vai trò chủ trọ', out)

    def test_named_owner_cannot_access_admin_but_developer_can(self):
        owner = User.objects.create_superuser('chutro', password='MatKhauCu#1x', last_name='Cũ')
        developer = User.objects.create_superuser('atus', password='MatKhauDev#1x')
        old_password = owner.password

        run('chutro', '--name', 'Hà Thị Minh Tâm')
        owner.refresh_from_db()
        self.assertEqual(owner.get_full_name(), 'Hà Thị Minh Tâm')
        self.assertEqual(owner.password, old_password)
        self.assertEqual(owner.role, User.Role.OWNER)
        self.assertFalse(owner.is_staff or owner.is_superuser)

        self.client.force_login(owner)
        home = self.client.get(reverse('home'))
        self.assertTemplateUsed(home, 'public/home.html')
        self.assertContains(home, 'Quản lý phòng trọ')
        page = self.client.get(reverse('owner_dashboard'))
        self.assertContains(page, 'Hà Thị Minh Tâm')
        self.assertNotContains(page, 'Quản trị hệ thống')
        self.assertRedirects(self.client.get(reverse('admin:index')),
                             reverse('admin:login') + '?next=' + reverse('admin:index'))
        login_response = self.client.post(reverse('admin:login'), {
            'username': 'chutro', 'password': 'MatKhauCu#1x',
            'next': reverse('admin:index'),
        })
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.context['form'].errors)

        self.client.force_login(developer)
        home = self.client.get(reverse('home'))
        self.assertTemplateUsed(home, 'public/home.html')
        self.assertContains(home, 'Quản trị hệ thống')
        self.assertEqual(self.client.get(reverse('admin:index')).status_code, 200)
        self.assertRedirects(self.client.get(reverse('owner_dashboard')), reverse('home'),
                             fetch_redirect_response=False)

    def test_weak_password_rejected(self):
        with self.assertRaises(CommandError):
            run('chutro', '--password', '123')
        self.assertFalse(User.objects.filter(username='chutro').exists())
