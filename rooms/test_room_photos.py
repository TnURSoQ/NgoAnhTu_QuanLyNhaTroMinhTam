from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Service, UtilityRate
from .models import Room, RoomPhoto


def uploaded_photo(name='room.png'):
    stream = BytesIO()
    Image.new('RGB', (32, 24), color=(180, 160, 140)).save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


class RoomPhotoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.photo_directory = TemporaryDirectory(prefix='minhtam-photos-')
        cls.media_settings = override_settings(MEDIA_ROOT=cls.photo_directory.name)
        cls.media_settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_settings.disable()
        cls.photo_directory.cleanup()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('photo-owner', role='owner')
        cls.other_user = User.objects.create_user('photo-tenant', role='tenant')
        cls.room = Room.objects.create(room_number='101', price=2500000, amenities='Điều hòa, Wifi')
        cls.other_room = Room.objects.create(room_number='102', price=2000000)
        UtilityRate.objects.create(water_billing_method='metered', electric_price=3500, water_price=15000, effective_date=timezone.localdate())
        Service.objects.create(name='Wifi', unit_price=100000)

    def room_data(self, room=None, **changes):
        room = room or self.room
        values = {'room_number': room.room_number, 'floor': room.floor, 'area': room.area or '',
                  'max_occupants': room.max_occupants, 'price': str(room.price), 'status': room.status,
                  'amenities': room.amenities, 'description': room.description}
        values.update(changes)
        return values

    def upload(self, *images):
        return self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(photos=list(images)))

    def test_owner_upload_appears_on_home_and_detail_with_utility_prices(self):
        self.client.force_login(self.owner)
        response = self.upload(uploaded_photo())
        self.assertEqual(response.status_code, 302)
        photo = RoomPhoto.objects.get()
        self.assertTrue(photo.image.storage.exists(photo.image.name))
        self.assertContains(self.client.get(reverse('room_detail', args=[self.room.pk])), photo.image.url)
        self.client.logout()
        for url in [reverse('home'), reverse('public_room_detail', args=[self.room.pk])]:
            response = self.client.get(url)
            self.assertContains(response, photo.image.url)
            self.assertContains(response, '3.500')
            self.assertContains(response, '15.000')
            self.assertContains(response, 'Điều hòa')

    def test_room_without_photo_uses_honest_placeholder_and_has_price_breakdown(self):
        response = self.client.get(reverse('public_room_detail', args=[self.room.pk]))
        self.assertContains(response, 'đang cập nhật ảnh phòng')
        self.assertContains(response, 'Các dịch vụ có thể đăng ký')
        self.assertContains(response, 'Wifi')
        self.assertContains(response, '2.500.000')

    def test_bad_file_and_oversized_image_are_rejected(self):
        self.client.force_login(self.owner)
        bad = SimpleUploadedFile('room.png', b'<html>not-an-image</html>', content_type='image/png')
        response = self.upload(bad)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        good = uploaded_photo()
        too_large = SimpleUploadedFile('large.png', good.read() + b'0' * (5 * 1024 * 1024), content_type='image/png')
        response = self.upload(too_large)
        self.assertContains(response, 'Ảnh tối đa 5 MB.')
        self.assertFalse(RoomPhoto.objects.exists())

    def test_only_owner_can_upload_or_delete_and_wrong_room_is_rejected(self):
        self.client.force_login(self.owner)
        self.upload(uploaded_photo())
        photo = RoomPhoto.objects.get()
        wrong_url = reverse('room_photo_delete', args=[self.other_room.pk, photo.pk])
        self.assertEqual(self.client.post(wrong_url).status_code, 404)
        url = reverse('room_photo_delete', args=[self.room.pk, photo.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.upload(uploaded_photo()).status_code, 302)
        self.assertEqual(RoomPhoto.objects.count(), 1)

    def test_delete_removes_database_entry_and_file_after_commit(self):
        self.client.force_login(self.owner)
        self.upload(uploaded_photo())
        photo = RoomPhoto.objects.get()
        storage, name = photo.image.storage, photo.image.name
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('room_photo_delete', args=[self.room.pk, photo.pk]))
        self.assertFalse(RoomPhoto.objects.exists())
        self.assertFalse(storage.exists(name))

    def test_photo_limit_prevents_more_than_ten_images(self):
        RoomPhoto.objects.bulk_create([RoomPhoto(room=self.room, image=f'rooms/test-{n}.png') for n in range(10)])
        self.client.force_login(self.owner)
        response = self.upload(uploaded_photo())
        self.assertContains(response, 'Mỗi phòng tối đa 10 ảnh')
        self.assertEqual(self.room.photos.count(), 10)

    def test_create_room_saves_multiple_images_and_selected_cover_together(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('room_create'), self.room_data(
            room_number='201', photos=[uploaded_photo('first.png'), uploaded_photo('second.png')], new_cover_index=1))
        room = Room.objects.get(room_number='201')
        self.assertRedirects(response, reverse('room_detail', args=[room.pk]))
        photos = list(room.photos.order_by('pk'))
        self.assertEqual(len(photos), 2)
        self.assertEqual(room.cover_photo.pk, photos[1].pk)
        self.assertTrue(all(photo.image.storage.exists(photo.image.name) for photo in photos))

    def test_every_image_is_validated_before_creating_room(self):
        self.client.force_login(self.owner)
        bad = SimpleUploadedFile('fake.png', b'not-an-image', content_type='image/png')
        response = self.client.post(reverse('room_create'), self.room_data(
            room_number='201', photos=[uploaded_photo(), bad]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('photos', response.context['form'].errors)
        self.assertFalse(Room.objects.filter(room_number='201').exists())
        self.assertFalse(RoomPhoto.objects.exists())

    def test_editing_room_without_upload_preserves_images(self):
        self.client.force_login(self.owner)
        self.upload(uploaded_photo(), uploaded_photo())
        photo_ids = list(self.room.photos.values_list('pk', flat=True))
        response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(price='2.800.000'))
        self.assertEqual(response.status_code, 302)
        self.room.refresh_from_db()
        self.assertEqual(self.room.price, 2800000)
        self.assertEqual(list(self.room.photos.values_list('pk', flat=True)), photo_ids)

    def test_select_existing_cover_and_delete_another_image_on_same_form(self):
        self.client.force_login(self.owner)
        self.upload(uploaded_photo(), uploaded_photo())
        first, second = list(self.room.photos.all())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(
                cover_photo=second.pk, delete_photos=[first.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.room.cover_photo.pk, second.pk)
        self.assertFalse(first.image.storage.exists(first.image.name))

    def test_deleting_at_limit_allows_replacement_and_can_choose_new_cover(self):
        RoomPhoto.objects.bulk_create([RoomPhoto(room=self.room, image=f'rooms/limit-{n}.png') for n in range(10)])
        old = self.room.photos.first()
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(
                photos=[uploaded_photo()], delete_photos=[old.pk], new_cover_index=0))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.room.photos.count(), 10)
        self.assertFalse(RoomPhoto.objects.filter(pk=old.pk).exists())
        self.assertTrue(self.room.cover_photo.image.storage.exists(self.room.cover_photo.image.name))

    def test_cannot_modify_photos_of_another_room_through_room_form(self):
        other = RoomPhoto.objects.create(room=self.other_room, image='rooms/other.png')
        self.client.force_login(self.owner)
        response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(
            cover_photo=other.pk, delete_photos=[other.pk], price='2.800.000'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('cover_photo', response.context['form'].errors)
        self.assertIn('delete_photos', response.context['form'].errors)
        self.assertTrue(RoomPhoto.objects.filter(pk=other.pk).exists())
        self.room.refresh_from_db()
        self.assertEqual(self.room.price, 2500000)

    def test_storage_failure_rolls_back_room_changes_and_keeps_deleted_photo(self):
        self.client.force_login(self.owner)
        self.upload(uploaded_photo())
        old = self.room.photos.get()
        original_save = FileSystemStorage.save
        saved = []

        def fail_second(storage, *args, **kwargs):
            if saved:
                raise OSError('Simulated storage failure')
            name = original_save(storage, *args, **kwargs)
            saved.append((storage, name))
            return name

        with patch.object(FileSystemStorage, 'save', autospec=True, side_effect=fail_second):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(
                    price='2.800.000', photos=[uploaded_photo(), uploaded_photo()], delete_photos=[old.pk]))
        self.assertContains(response, 'Chưa lưu được phòng và ảnh.')
        self.room.refresh_from_db()
        self.assertEqual(self.room.price, 2500000)
        self.assertEqual(list(self.room.photos.values_list('pk', flat=True)), [old.pk])
        self.assertTrue(old.image.storage.exists(old.image.name))
        self.assertTrue(saved)
        self.assertTrue(all(not storage.exists(name) for storage, name in saved))

    def test_old_photo_page_redirects_to_room_edit(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('room_photos', args=[self.room.pk])),
                             reverse('room_update', args=[self.room.pk]) + '#roomPhotos')
