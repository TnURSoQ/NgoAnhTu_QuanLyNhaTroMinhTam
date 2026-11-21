from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from rooms.models import Contract, ContractTenant
from .models import Announcement, MaintenancePhoto, MaintenanceRequest as MR
from .services import transition
from .tests import SupportBase


def image(name='issue.png'):
    stream = BytesIO()
    Image.new('RGB', (24, 24)).save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


class AnnouncementAudienceTests(SupportBase):
    def announce(self, title, audience='all', rooms=()):
        item = Announcement.objects.create(title=title, content=title, audience=audience, created_by=self.owner)
        item.rooms.set(rooms)
        return item

    def test_room_scope_filters_both_home_and_notifications_and_deduplicates(self):
        common = self.announce('Thông báo chung')
        own = self.announce('Dành cho A101', 'rooms', [self.room, self.other_room])
        other = self.announce('Riêng phòng B202', 'rooms', [self.other_room])
        hidden = self.announce('Thông báo đã ẩn')
        hidden.is_active = False
        hidden.save()
        self.client.force_login(self.user)
        for name in ['my_room', 'my_notifications']:
            response = self.client.get(reverse(name))
            items = response.context['announcements']
            self.assertEqual(list(items), [own, common])
            self.assertNotContains(response, other.title)
            self.assertNotContains(response, hidden.title)

    def test_form_requires_valid_rooms_and_clears_targets_when_all(self):
        self.client.force_login(self.owner)
        url = reverse('announcement_create')
        base = {'title': 'Sửa điện', 'content': 'Nội dung', 'is_active': 'on', 'audience': 'rooms'}
        for rooms in [[], [999999]]:
            response = self.client.post(url, {**base, 'rooms': rooms})
            self.assertIn('rooms', response.context['form'].errors)
            self.assertFalse(Announcement.objects.exists())
        response = self.client.post(url, {**base, 'rooms': [self.room.pk]})
        self.assertEqual(response.status_code, 302)
        item = Announcement.objects.get()
        self.assertEqual(list(item.rooms.all()), [self.room])
        response = self.client.get(reverse('announcement_update', args=[item.pk]))
        self.assertEqual(list(response.context['form'].instance.rooms.all()), [self.room])
        self.client.post(reverse('announcement_update', args=[item.pk]), {
            **base, 'audience': 'all', 'rooms': [self.other_room.pk]})
        item.refresh_from_db()
        self.assertEqual(item.audience, 'all')
        self.assertFalse(item.rooms.exists())

    def test_form_page_renders_room_choices(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('announcement_create'))
        self.assertContains(response, 'Phạm vi thông báo')
        self.assertContains(response, 'Phòng A101')

    def test_former_tenant_cannot_read_current_room_notices(self):
        self.announce('Thông báo chung')
        self.announce('Riêng phòng', 'rooms', [self.room])
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        self.client.force_login(self.user)
        for name in ['my_room', 'my_notifications']:
            self.assertFalse(list(self.client.get(reverse(name)).context['announcements']))

    def test_target_follows_current_room_after_transfer(self):
        self.announce('Phòng cũ', 'rooms', [self.room])
        target = self.announce('Phòng mới', 'rooms', [self.other_room])
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        new = Contract.objects.create(room=self.other_room, start_date=timezone.localdate(),
                                      end_date=self.contract.end_date)
        ContractTenant.objects.create(contract=new, tenant=self.tenant)
        self.client.force_login(self.user)
        self.assertEqual(list(self.client.get(reverse('my_room')).context['announcements']), [target])

    def test_notifications_contains_only_own_repair_reply(self):
        own = self.make_request()
        transition(own, MR.Status.DANG_XU_LY, owner_note='Thợ đến lúc 9 giờ.')
        self.make_request(tenant=self.other_tenant, status=MR.Status.DANG_XU_LY, owner_note='Riêng tư')
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_notifications'))
        self.assertContains(response, 'Thợ đến lúc 9 giờ.')
        self.assertNotContains(response, 'Riêng tư')
        self.assertContains(response, reverse('my_maintenance_detail', args=[own.pk]))

    def test_panel_filters_private_content_and_returns_fragment_without_page_layout(self):
        self.announce('Thông báo dành cho tôi', 'rooms', [self.room])
        self.announce('Thông báo của phòng khác', 'rooms', [self.other_room])
        hidden = self.announce('Nội dung đã ẩn')
        hidden.is_active = False
        hidden.save()
        own = self.make_request()
        transition(own, MR.Status.DANG_XU_LY, owner_note='Phản hồi của tôi')
        self.make_request(tenant=self.other_tenant, status=MR.Status.DANG_XU_LY, owner_note='Phản hồi riêng của người khác')
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_notifications_panel'))
        self.assertContains(response, 'Thông báo dành cho tôi')
        self.assertContains(response, 'Phản hồi của tôi')
        for private_content in ['Thông báo của phòng khác', 'Nội dung đã ẩn', 'Phản hồi riêng của người khác', '<html', '<header']:
            self.assertNotContains(response, private_content)
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_panel_paginates_one_feed_by_time_and_escapes_announcements(self):
        for index in range(11):
            self.announce(f'Tin {index:02d}')
            self.make_request(title=f'Sửa {index:02d}', status=MR.Status.DANG_XU_LY)
        self.client.force_login(self.user)
        url = reverse('my_notifications_panel')
        response = self.client.get(url)
        self.assertEqual(len(response.context['notifications']), 10)
        self.assertEqual(response.context['notifications'].paginator.count, 22)
        times = [item['notification_time'] for item in response.context['notifications']]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertContains(response, url + '?page=2')
        response = self.client.get(url, {'page': 3})
        self.assertContains(response, 'Tin 00')
        self.assertContains(response, 'Sửa 00')
        self.assertNotContains(response, 'Tin 10')
        self.announce('<script>alert(1)</script>')
        response = self.client.get(url)
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_empty_panel_contains_only_one_message(self):
        self.announce('Phòng khác', 'rooms', [self.other_room])
        self.make_request(status=MR.Status.DA_GUI)
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_notifications_panel'))
        self.assertHTMLEqual(response.content.decode(), '<p class="notification-empty">Không có thông báo</p>')
        self.assertNotContains(response, 'Từ chủ trọ')
        self.assertNotContains(response, 'Phản hồi sửa chữa')

    def test_announcement_card_opens_full_content_only_for_allowed_tenant(self):
        content = 'Nội dung chi tiết dài. ' * 30 + 'PHẦN CUỐI THÔNG BÁO'
        item = self.announce('Thông báo cần đọc đầy đủ', 'rooms', [self.room])
        item.content = content
        item.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_notifications_panel'))
        detail_url = reverse('my_announcement_detail', args=[item.pk])
        self.assertContains(response, f'<a class="notification-item is-unread" href="{detail_url}"')
        self.assertNotContains(response, 'PHẦN CUỐI THÔNG BÁO')
        self.assertContains(self.client.get(detail_url), 'PHẦN CUỐI THÔNG BÁO')
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.client.force_login(self.user)
        item.is_active = False
        item.save()
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_panel_requires_tenant_login_and_rejects_post(self):
        url = reverse('my_notifications_panel')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(url), reverse('home'))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url).status_code, 405)


class MaintenanceAttachmentTests(SupportBase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = FileSystemStorage(location=directory.name)
        storage_patch = patch.object(MaintenancePhoto._meta.get_field('image'), 'storage', self.storage)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.client.force_login(self.user)

    def submit(self, **extra):
        return self.client.post(reverse('maintenance_create'), {
            'title': 'Rò nước', 'description': 'Ống nước bị rò', 'category': 'nuoc',
            'priority': 'binh_thuong', 'contact_method': 'web', **extra})

    def test_upload_and_camera_saved_together_with_private_urls(self):
        response = self.submit(photos=[image('a.png'), image('b.png')], camera_photo=image('camera.png'))
        self.assertEqual(response.status_code, 302)
        item = MR.objects.get()
        self.assertEqual(item.photos.count(), 3)
        detail = self.client.get(reverse('my_maintenance_detail', args=[item.pk]))
        self.assertContains(detail, 'Qua ứng dụng (thông báo)')
        for photo in item.photos.all():
            self.assertTrue(self.storage.exists(photo.image.name))
            self.assertContains(detail, reverse('maintenance_photo', args=[photo.pk]))
            self.assertNotContains(detail, '/media/' + photo.image.name)
            response = self.client.get(reverse('maintenance_photo', args=[photo.pk]))
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Cache-Control'], 'private, no-store')
            finally:
                response.close()

    def test_private_image_access_owner_sender_only(self):
        self.submit(photos=[image()])
        photo = MaintenancePhoto.objects.get()
        url = reverse('maintenance_photo', args=[photo.pk])
        self.client.force_login(self.owner)
        response = self.client.get(url)
        try:
            self.assertEqual(response.status_code, 200)
        finally:
            response.close()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_all_images_validated_before_saving_and_combined_limit(self):
        bad = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        for uploads in [
            {'photos': [image(), bad]},
            {'photos': [image(f'{i}.png') for i in range(5)], 'camera_photo': image()},
            {'camera_photo': SimpleUploadedFile('bad.png', b'bad')},
            {'photos': [image('unsupported.svg')]},
        ]:
            response = self.submit(**uploads)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
            self.assertFalse(MR.objects.exists())
            self.assertFalse(MaintenancePhoto.objects.exists())
            self.assertFalse(list(Path(self.storage.location).rglob('*.png')))

    def test_storage_failure_rolls_back_request_and_uploaded_files(self):
        original_save = self.storage.save
        saved = []

        def fail_second(*args, **kwargs):
            if saved:
                raise OSError('storage unavailable')
            name = original_save(*args, **kwargs)
            saved.append(name)
            return name

        with patch.object(self.storage, 'save', side_effect=fail_second):
            response = self.submit(photos=[image(), image()])
        self.assertContains(response, 'Chưa lưu được yêu cầu và ảnh')
        self.assertFalse(MR.objects.exists())
        self.assertFalse(MaintenancePhoto.objects.exists())
        self.assertTrue(saved)
        self.assertFalse(self.storage.exists(saved[0]))

    def test_deleting_request_cleans_photos_after_commit(self):
        self.submit(photos=[image()])
        photo = MaintenancePhoto.objects.get()
        name = photo.image.name
        with self.captureOnCommitCallbacks(execute=True):
            photo.maintenance.delete()
        self.assertFalse(self.storage.exists(name))

    def test_form_groups_time_and_exposes_camera_with_multipart(self):
        response = self.client.get(reverse('maintenance_create'))
        for text in ['multipart/form-data', 'capture="environment"', 'Thời gian thuận tiện', 'id_preferred_date', 'id_preferred_slot']:
            self.assertContains(response, text)
        self.assertNotContains(response, '>Buổi thuận tiện<')

    def test_upload_requires_active_contract_and_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse('maintenance_create'), {}).status_code, 403)
        self.client.force_login(self.other_user)
        self.submit(photos=[image()])
        self.assertFalse(MR.objects.exists())
        self.assertFalse(MaintenancePhoto.objects.exists())
