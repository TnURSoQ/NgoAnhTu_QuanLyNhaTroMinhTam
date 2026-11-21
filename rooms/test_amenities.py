from django.urls import reverse

from support.tests import SupportBase
from .forms import RoomForm


class RoomAmenitiesTests(SupportBase):
    def room_data(self, **changes):
        return {'room_number': 'NEW101', 'floor': 1, 'max_occupants': 2, 'price': '2500000',
                'status': 'trong', 'amenities': '', **changes}

    def test_checkboxes_and_custom_amenities_deduplicate_and_display_everywhere(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('room_update', args=[self.room.pk]), self.room_data(
            room_number=self.room.room_number, amenity_choices=['Điều hòa', 'Wifi'], amenities='Wifi, Sân phơi riêng, sân phơi riêng'))
        self.assertEqual(response.status_code, 302)
        self.room.refresh_from_db()
        self.assertEqual(self.room.amenity_list, ['Điều hòa', 'Wifi', 'Sân phơi riêng'])
        self.assertContains(self.client.get(reverse('room_detail', args=[self.room.pk])), 'Sân phơi riêng')
        self.assertContains(self.client.get(reverse('public_room_detail', args=[self.room.pk])), 'Sân phơi riêng')
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_room'))
        self.assertContains(response, 'Tiện ích trong phòng')
        self.assertContains(response, 'Sân phơi riêng')

    def test_legacy_amenities_prefill_without_loss_and_clear_is_supported(self):
        self.room.amenities = 'Điều hòa, Nội thất đặc biệt, Wifi'
        self.room.save()
        form = RoomForm(instance=self.room)
        self.assertEqual(form.initial['amenity_choices'], ['Điều hòa', 'Wifi'])
        self.assertEqual(form.initial['amenities'], 'Nội thất đặc biệt')
        form = RoomForm(self.room_data(room_number=self.room.room_number), instance=self.room)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.room.refresh_from_db()
        self.assertEqual(self.room.amenities, '')

    def test_unknown_choice_or_combined_text_too_long_rejected(self):
        for changes, field in [({'amenity_choices': ['made-up']}, 'amenity_choices'),
                               ({'amenity_choices': ['Điều hòa'], 'amenities': 'a' * 250}, 'amenities')]:
            form = RoomForm(self.room_data(**changes))
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)

    def test_create_page_has_amenity_checkboxes_and_photo_upload(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('room_create'))
        self.assertContains(response, 'name="amenity_choices"')
        self.assertContains(response, 'Tiện ích khác')
        self.assertContains(response, 'name="photos"')
