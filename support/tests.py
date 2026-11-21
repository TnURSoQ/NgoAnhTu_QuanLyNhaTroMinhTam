from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from rooms.models import Contract, ContractTenant, Room
from .models import Announcement, MaintenanceRequest as MR
from .services import transition


class SupportBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('owner', role=User.Role.OWNER, is_staff=True)
        cls.user = User.objects.create_user('tenant', role=User.Role.TENANT)
        cls.other_user = User.objects.create_user('other', role=User.Role.TENANT)
        cls.tenant = Tenant.objects.create(user=cls.user, full_name='Nguyễn Đặng Ánh',
                                           id_card_number='001', phone='0901234567')
        cls.other_tenant = Tenant.objects.create(user=cls.other_user, full_name='Trần Bình',
                                                 id_card_number='002', phone='0907654321')
        cls.room = Room.objects.create(room_number='A101', price=2500000)
        cls.other_room = Room.objects.create(room_number='B202', price=2500000)
        cls.contract = Contract.objects.create(
            room=cls.room, start_date=timezone.localdate() - timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=365))
        ContractTenant.objects.create(contract=cls.contract, tenant=cls.tenant)

    def make_request(self, **overrides):
        data = {'room': self.room, 'tenant': self.tenant, 'title': 'Điều hòa không chạy',
                'category': MR.Category.THIET_BI, 'description': 'Máy không lên nguồn.'}
        data.update(overrides)
        return MR.objects.create(**data)


class TenantMaintenanceTests(SupportBase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_create_uses_active_contract_and_sender_despite_tampered_post(self):
        response = self.client.post(reverse('maintenance_create'), {
            'title': 'Mất điện', 'category': 'dien', 'description': 'Ổ điện không hoạt động.',
            'priority': 'rat_khan_cap', 'contact_method': 'dien_thoai',
            'preferred_date': (timezone.localdate() + timedelta(days=1)).isoformat(), 'preferred_slot': 'sang',
            'room': self.other_room.pk, 'tenant': self.other_tenant.pk,
            'status': 'hoan_thanh', 'owner_note': 'Giả mạo', 'resolved_at': timezone.now().isoformat(),
        })
        item = MR.objects.get()
        self.assertEqual(item.room, self.room)
        self.assertEqual(item.tenant, self.tenant)
        self.assertEqual(item.status, MR.Status.DA_GUI)
        self.assertEqual(item.owner_note, '')
        self.assertIsNone(item.resolved_at)
        self.assertEqual(item.preferred_slot, 'sang')
        self.assertEqual(item.display_code, f'SC-{timezone.localtime(item.created_at).year}-{item.pk:03d}')
        self.assertRedirects(response, reverse('maintenance_sent', args=[item.pk]))
        self.assertContains(self.client.get(response.url), item.display_code)

    def test_preferred_date_and_slot_are_optional(self):
        response = self.client.post(reverse('maintenance_create'), {
            'title': 'Rò nước', 'category': 'nuoc', 'description': 'Ống nước rò rỉ.',
            'priority': 'binh_thuong', 'contact_method': 'web'})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(MR.objects.get().preferred_date)
        self.assertEqual(MR.objects.get().preferred_slot, '')

    def test_invalid_submission_shows_errors_without_creating(self):
        response = self.client.post(reverse('maintenance_create'), {
            'title': '', 'category': 'invalid', 'description': '',
            'priority': 'binh_thuong', 'contact_method': 'web', 'preferred_date': 'bad-date'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(MR.objects.exists())

    def test_no_active_contract_cannot_submit(self):
        for user in (self.other_user, self.user):
            with self.subTest(user=user.username):
                if user == self.user:
                    self.contract.status = Contract.Status.KET_THUC
                    self.contract.save()
                self.client.force_login(user)
                response = self.client.post(reverse('maintenance_create'), {
                    'title': 'Sự cố', 'category': 'khac', 'description': 'Cần sửa',
                    'priority': 'binh_thuong', 'contact_method': 'web'})
                self.assertContains(response, 'Bạn cần có hợp đồng hiệu lực')
                self.assertFalse(MR.objects.exists())

    def test_only_own_requests_in_list_detail_confirmation_and_cancel(self):
        own = self.make_request()
        other = self.make_request(tenant=self.other_tenant, title='Yêu cầu riêng của người khác')
        response = self.client.get(reverse('my_maintenance_requests'))
        self.assertEqual(list(response.context['items']), [own])
        for name in ('my_maintenance_detail', 'maintenance_sent'):
            self.assertEqual(self.client.get(reverse(name, args=[own.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse(name, args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('maintenance_cancel', args=[other.pk])).status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.status, MR.Status.DA_GUI)

    def test_cancel_only_sent_requests_and_requires_post(self):
        for status in MR.Status.values:
            with self.subTest(status=status):
                item = self.make_request(status=status)
                url = reverse('maintenance_cancel', args=[item.pk])
                self.assertEqual(self.client.get(url).status_code, 405)
                self.client.post(url)
                item.refresh_from_db()
                self.assertEqual(item.status, MR.Status.DA_HUY if status == MR.Status.DA_GUI else status)
                self.assertIsNone(item.resolved_at)

    def test_detail_displays_owner_reply(self):
        item = self.make_request(status=MR.Status.DANG_XU_LY, owner_note='Thợ sẽ đến buổi sáng.',
                                 expected_done=timezone.localdate() + timedelta(days=1))
        response = self.client.get(reverse('my_maintenance_detail', args=[item.pk]))
        self.assertContains(response, item.owner_note)
        self.assertContains(response, item.expected_done.strftime('%d/%m/%Y'))
        self.assertNotContains(response, 'Hủy yêu cầu</button>')

    def test_my_room_has_only_three_latest_own_requests(self):
        items = [self.make_request(title=f'Sự cố {i}') for i in range(5)]
        other = self.make_request(tenant=self.other_tenant, title='Riêng tư')
        response = self.client.get(reverse('my_room'))
        self.assertEqual(list(response.context['maintenance_requests']), list(reversed(items[-3:])))
        for item in items[-3:]:
            self.assertContains(response, reverse('my_maintenance_detail', args=[item.pk]))
        self.assertNotContains(response, reverse('my_maintenance_detail', args=[other.pk]))
        self.assertNotContains(response, items[0].display_code)


class OwnerMaintenanceTests(SupportBase):
    def setUp(self):
        self.client.force_login(self.owner)

    def test_valid_flow_preserves_reply_and_sets_completion_time(self):
        item = self.make_request()
        due = timezone.localdate() + timedelta(days=2)
        url = reverse('maintenance_set_status', args=[item.pk])
        self.assertRedirects(self.client.post(url, {
            'status': 'dang_xu_ly', 'expected_done': due.isoformat(), 'owner_note': 'Thợ sẽ liên hệ.'}),
            reverse('maintenance_detail', args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.status, MR.Status.DANG_XU_LY)
        self.assertEqual(item.expected_done, due)
        self.assertEqual(item.owner_note, 'Thợ sẽ liên hệ.')
        self.assertIsNone(item.resolved_at)
        before = timezone.now()
        self.client.post(url, {'status': 'hoan_thanh'})
        item.refresh_from_db()
        self.assertEqual(item.status, MR.Status.HOAN_THANH)
        self.assertGreaterEqual(item.resolved_at, before)
        self.assertEqual(item.owner_note, 'Thợ sẽ liên hệ.')
        self.assertEqual(item.expected_done, due)

    def test_every_valid_and_invalid_transition(self):
        allowed = {'da_gui': {'dang_xu_ly', 'da_huy'}, 'dang_xu_ly': {'hoan_thanh', 'da_huy'}}
        for current in MR.Status.values:
            for target in [*MR.Status.values, 'invalid']:
                with self.subTest(current=current, target=target):
                    resolved = timezone.now() if current == MR.Status.HOAN_THANH else None
                    item = self.make_request(status=current, owner_note='Giữ lại', resolved_at=resolved)
                    response = self.client.post(reverse('maintenance_set_status', args=[item.pk]), {
                        'status': target, 'owner_note': 'Thay đổi'})
                    item.refresh_from_db()
                    if target in allowed.get(current, set()):
                        self.assertEqual(response.status_code, 302)
                        self.assertEqual(item.status, target)
                        self.assertEqual(item.owner_note, 'Thay đổi')
                        self.assertEqual(item.resolved_at is not None, target == MR.Status.HOAN_THANH)
                    else:
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(item.status, current)
                        self.assertEqual(item.owner_note, 'Giữ lại')
                        self.assertEqual(item.resolved_at, resolved)

    def test_invalid_expected_date_does_not_change_request(self):
        item = self.make_request()
        response = self.client.post(reverse('maintenance_set_status', args=[item.pk]), {
            'status': 'dang_xu_ly', 'expected_done': 'bad-date', 'owner_note': 'Sẽ sửa'})
        self.assertTrue(response.context['form'].errors)
        item.refresh_from_db()
        self.assertEqual(item.status, MR.Status.DA_GUI)
        self.assertEqual(item.owner_note, '')

    def test_stale_transition_cannot_overwrite_newer_state(self):
        item = self.make_request()
        stale = MR.objects.get(pk=item.pk)
        transition(item, MR.Status.DA_HUY)
        with self.assertRaises(ValidationError):
            transition(stale, MR.Status.DANG_XU_LY)
        item.refresh_from_db()
        self.assertEqual(item.status, MR.Status.DA_HUY)

    def test_accent_insensitive_search_by_code_room_name_title(self):
        item = self.make_request()
        self.make_request(room=self.other_room, tenant=self.other_tenant, title='Hỏng cửa')
        for query in (item.display_code.lower(), 'a101', 'nguyen dang anh', 'DIEU HOA', 'Điều hòa'):
            with self.subTest(query=query):
                response = self.client.get(reverse('maintenance_list'), {'q': query})
                self.assertEqual(list(response.context['items']), [item])

    def test_tabs_counts_filters_and_priority(self):
        items = [self.make_request(status=status, priority='rat_khan_cap') for status in MR.Status.values]
        response = self.client.get(reverse('maintenance_list'))
        counts = {tab['key']: tab['count'] for tab in response.context['tabs']}
        self.assertEqual(counts, {'': 4, 'da_gui': 1, 'dang_xu_ly': 1, 'hoan_thanh': 1, 'da_huy': 1})
        self.assertContains(response, 'Rất khẩn cấp')
        self.assertContains(response, 'pill-rose')
        response = self.client.get(reverse('maintenance_list'), {'status': 'dang_xu_ly', 'q': 'dieu hoa'})
        self.assertEqual(list(response.context['items']), [items[1]])
        self.assertContains(response, 'q=dieu%20hoa')
        response = self.client.get(reverse('maintenance_list'), {'status': 'invalid'})
        self.assertEqual(len(response.context['items']), 4)

    def test_owner_detail_has_clickable_phone_and_post_only_update(self):
        item = self.make_request()
        response = self.client.get(reverse('maintenance_detail', args=[item.pk]))
        self.assertContains(response, self.tenant.full_name)
        self.assertContains(response, f'href="tel:{self.tenant.phone}"')
        self.assertContains(response, 'name="status" value="dang_xu_ly"')
        self.assertContains(response, 'name="status" value="da_huy"')
        self.assertNotContains(response, 'name="status" value="hoan_thanh"')
        self.assertEqual(self.client.get(reverse('maintenance_set_status', args=[item.pk])).status_code, 405)

    def test_room_history_is_limited_to_five_requests_for_that_room(self):
        items = [self.make_request() for _ in range(6)]
        other = self.make_request(room=self.other_room)
        response = self.client.get(reverse('room_detail', args=[self.room.pk]))
        self.assertContains(response, 'Lịch sử sửa chữa')
        self.assertEqual(list(response.context['maintenance_requests']), list(reversed(items[-5:])))
        self.assertContains(response, reverse('maintenance_detail', args=[items[-1].pk]))
        self.assertNotContains(response, other.display_code)

    def test_overview_open_count_and_max_three_new_tasks(self):
        sent = [self.make_request() for _ in range(4)]
        self.make_request(status='dang_xu_ly')
        self.make_request(status='hoan_thanh')
        self.make_request(status='da_huy')
        response = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(response.context['maintenance_count'], 5)
        tasks = [task for task in response.context['tasks'] if task['title'] == 'Yêu cầu sửa chữa mới']
        self.assertEqual(len(tasks), 3)
        self.assertEqual([t['url'] for t in tasks], [reverse('maintenance_detail', args=[i.pk]) for i in reversed(sent[-3:])])
        self.assertContains(response, reverse('maintenance_list'))
        self.assertContains(response, 'Yêu cầu sửa chữa mới')


class SupportPermissionTests(SupportBase):
    def test_anonymous_redirects_to_login(self):
        for name in ('my_maintenance_requests', 'maintenance_create', 'maintenance_list', 'announcement_list'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('login'), response.url)

    def test_tenant_cannot_read_or_mutate_owner_resources(self):
        item = self.make_request()
        announcement = Announcement.objects.create(title='Nội bộ', content='Nội dung', created_by=self.owner)
        self.client.force_login(self.user)
        targets = [
            ('maintenance_list', []), ('maintenance_detail', [item.pk]),
            ('maintenance_set_status', [item.pk]), ('announcement_list', []),
            ('announcement_create', []), ('announcement_update', [announcement.pk]),
            ('announcement_toggle', [announcement.pk]), ('announcement_delete', [announcement.pk]),
        ]
        for name, args in targets:
            for method in ('get', 'post'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(reverse(name, args=args), {
                        'status': 'dang_xu_ly', 'title': 'Giả mạo', 'content': 'Giả mạo'})
                    self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        item.refresh_from_db()
        announcement.refresh_from_db()
        self.assertEqual(item.status, MR.Status.DA_GUI)
        self.assertEqual(announcement.title, 'Nội bộ')
        self.assertEqual(Announcement.objects.count(), 1)

    def test_staff_without_owner_role_cannot_manage(self):
        developer = User.objects.create_user('dev', is_staff=True, is_superuser=True)
        self.client.force_login(developer)
        for name in ('maintenance_list', 'announcement_list', 'announcement_create'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('home'), fetch_redirect_response=False)

    def test_owner_can_access_all_new_pages_without_admin_links(self):
        item = self.make_request()
        announcement = Announcement.objects.create(title='Thông báo', content='Nội dung', created_by=self.owner)
        self.client.force_login(self.owner)
        for name, args in [('maintenance_list', []), ('maintenance_detail', [item.pk]),
                           ('announcement_list', []), ('announcement_create', []),
                           ('announcement_update', [announcement.pk]), ('announcement_delete', [announcement.pk])]:
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'href="/admin/')


class AnnouncementTests(SupportBase):
    def test_owner_create_edit_toggle_and_confirm_delete(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.post(reverse('announcement_create'), {
            'title': 'Cúp nước', 'content': 'Bảo trì đường ống buổi sáng.', 'is_active': 'on',
            'created_by': self.user.pk, 'audience': 'all'}), reverse('announcement_list'))
        item = Announcement.objects.get()
        self.assertEqual(item.created_by, self.owner)
        self.assertTrue(item.is_active)
        self.client.post(reverse('announcement_update', args=[item.pk]), {
            'title': 'Đổi lịch bảo trì', 'content': 'Bảo trì buổi chiều.', 'is_active': 'on',
            'created_by': self.user.pk, 'audience': 'all'})
        item.refresh_from_db()
        self.assertEqual(item.title, 'Đổi lịch bảo trì')
        self.assertEqual(item.created_by, self.owner)
        url = reverse('announcement_toggle', args=[item.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for expected in (False, True):
            self.assertRedirects(self.client.post(url), reverse('announcement_list'))
            item.refresh_from_db()
            self.assertEqual(item.is_active, expected)
        delete_url = reverse('announcement_delete', args=[item.pk])
        self.assertContains(self.client.get(delete_url), 'Bạn có chắc chắn muốn xóa?')
        self.assertTrue(Announcement.objects.filter(pk=item.pk).exists())
        self.assertRedirects(self.client.post(delete_url), reverse('announcement_list'))
        self.assertFalse(Announcement.objects.exists())

    def test_tenant_sees_only_three_latest_active_announcements(self):
        items = [Announcement.objects.create(title=f'Thông báo {i}', content=f'Nội dung số {i}',
                                              created_by=self.owner) for i in range(5)]
        hidden = Announcement.objects.create(title='Thông báo bí mật', content='Nội dung bí mật',
                                               is_active=False, created_by=self.owner)
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_room'))
        self.assertContains(response, 'Thông báo từ chủ trọ')
        self.assertEqual(list(response.context['announcements']), list(reversed(items[-3:])))
        self.assertNotContains(response, hidden.title)
        self.assertNotContains(response, hidden.content)
        self.assertNotContains(response, items[0].title)
        self.client.force_login(self.owner)
        self.client.post(reverse('announcement_toggle', args=[items[-1].pk]))
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_room'))
        self.assertNotContains(response, items[-1].title)

    def test_invalid_announcement_is_not_saved(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('announcement_create'), {'title': '', 'content': ''})
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Announcement.objects.exists())
