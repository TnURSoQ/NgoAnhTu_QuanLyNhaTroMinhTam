from datetime import timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from support.tests import SupportBase


class TenantProfileTests(SupportBase):
    def setUp(self):
        self.client.force_login(self.user)

    def profile_data(self, **changes):
        return {'full_name': 'Nguyễn Ánh', 'phone': '0901234567', 'email': 'anh@example.com',
                'date_of_birth': '2000-01-15', 'id_card_number': '012345678901',
                'hometown': 'Đà Nẵng', 'occupation': 'Sinh viên', **changes}

    def test_page_and_navigation_and_own_update_preserves_privileged_fields(self):
        self.tenant.note = 'Ghi chú riêng của chủ trọ'
        self.tenant.save()
        response = self.client.get(reverse('my_profile'))
        self.assertContains(response, 'Thông tin cá nhân')
        self.assertContains(response, 'Số CCCD')
        self.assertNotContains(response, self.tenant.note)
        response = self.client.post(reverse('my_profile'), self.profile_data(
            pk=self.other_tenant.pk, user=self.other_user.pk, role='owner', is_staff='on', note='Bị sửa', username='changed'))
        self.assertRedirects(response, reverse('my_profile'))
        self.tenant.refresh_from_db()
        self.user.refresh_from_db()
        self.other_tenant.refresh_from_db()
        self.assertEqual(self.tenant.full_name, 'Nguyễn Ánh')
        self.assertEqual(self.tenant.id_card_number, '012345678901')
        self.assertEqual(self.tenant.user_id, self.user.pk)
        self.assertEqual(self.tenant.note, 'Ghi chú riêng của chủ trọ')
        self.assertEqual(self.user.username, 'tenant')
        self.assertEqual(self.user.role, 'tenant')
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.user.first_name, self.tenant.full_name)
        self.assertEqual(self.user.email, self.tenant.email)
        self.assertEqual(self.other_tenant.full_name, 'Trần Bình')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('tenant_detail', args=[self.tenant.pk])), '012345678901')

    def test_duplicate_or_invalid_id_and_future_birth_date_do_not_save(self):
        self.other_tenant.id_card_number = '123456789012'
        self.other_tenant.save()
        for changes, field in [
            ({'id_card_number': '123456789012'}, 'id_card_number'),
            ({'id_card_number': 'abc'}, 'id_card_number'),
            ({'date_of_birth': (timezone.localdate() + timedelta(days=1)).isoformat()}, 'date_of_birth'),
            ({'phone': 'bad'}, 'phone'),
        ]:
            response = self.client.post(reverse('my_profile'), self.profile_data(**changes))
            self.assertIn(field, response.context['form'].errors)
            self.tenant.refresh_from_db()
            self.assertEqual(self.tenant.full_name, 'Nguyễn Đặng Ánh')

    def test_access_requires_own_tenant_account_and_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('my_profile'), self.profile_data()).status_code, 403)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('my_profile')), reverse('home'))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('my_profile')).status_code, 302)

    def test_profile_available_after_checkout_and_escapes_content(self):
        from rooms.models import Contract
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        response = self.client.post(reverse('my_profile'), self.profile_data(hometown='<script>alert(1)</script>'))
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse('my_profile'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
