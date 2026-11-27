from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from billing.models import Invoice, Payment, Service
from support.tests import SupportBase
from .forms import PropertyInfoForm, RoomForm
from .models import PropertyInfo, Room


class SharedAmenitiesTests(SupportBase):
    def setUp(self):
        self.info, _ = PropertyInfo.objects.update_or_create(pk=1, defaults={
            'shared_amenities': 'Chỗ để xe, Camera an ninh, Khu phơi đồ'})
        self.room.amenities = 'Điều hòa, Gác lửng'
        self.room.save()

    def test_configuration_has_only_shared_facilities_without_fee_fields(self):
        form = PropertyInfoForm(instance=self.info)
        self.assertEqual(set(form.fields), {'shared_choices', 'shared_amenities'})
        self.assertIn('Chỗ để xe', form.initial['shared_choices'])
        self.client.force_login(self.owner)
        page = self.client.get(reverse('billing_settings'))
        self.assertContains(page, 'Thông tin nhà trọ')
        self.assertContains(page, 'name="shared_choices"')
        self.assertContains(page, 'name="shared_amenities"')

    def test_owner_save_deduplicates_aliases_and_preserves_room_and_financial_data(self):
        self.client.force_login(self.owner)
        service = Service.objects.create(name='Internet', unit_price=100000)
        before = (self.room.amenities, Invoice.objects.count(), Payment.objects.count(), Service.objects.count())
        response = self.client.post(reverse('billing_settings'), {'action': 'property',
            'shared_choices': ['Chỗ để xe', 'Camera an ninh'], 'shared_amenities': 'bãi để xe, Khu đọc sách, khu đọc sách',
            'water_price': '1', 'unit_price': '999999'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PropertyInfo.current().amenity_list, ['Chỗ để xe', 'Camera an ninh', 'Khu đọc sách'])
        self.room.refresh_from_db()
        service.refresh_from_db()
        self.assertEqual(service.unit_price, 100000)
        self.assertEqual(before, (self.room.amenities, Invoice.objects.count(), Payment.objects.count(), Service.objects.count()))

    def test_empty_selection_clears_common_facilities_without_changing_private_room(self):
        form = PropertyInfoForm({'shared_amenities': ''}, instance=self.info)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(PropertyInfo.current().amenity_list, [])
        self.assertNotContains(self.client.get(reverse('home')), 'Tiện ích chung của nhà trọ')
        self.assertContains(self.client.get(reverse('public_room_detail', args=[self.room.pk])), 'Điều hòa')

    def test_invalid_choice_and_combined_length_are_rejected(self):
        for data in ({'shared_choices': ['fake']}, {'shared_choices': ['Chỗ để xe'], 'shared_amenities': 'x' * 495}):
            form = PropertyInfoForm(data, instance=self.info)
            self.assertFalse(form.is_valid())
        self.assertIn('Chỗ để xe', PropertyInfo.current().amenity_list)

    def test_only_owner_can_change_shared_facilities(self):
        for account in (self.user, User.objects.create_user('staff-only-common', is_staff=True), None):
            self.client.force_login(account) if account else self.client.logout()
            page = self.client.post(reverse('billing_settings'), {'action': 'property', 'shared_amenities': 'Thay đổi'})
            self.assertEqual(page.status_code, 302)
            self.assertEqual(PropertyInfo.current().shared_amenities, self.info.shared_amenities)

    def test_common_block_shows_on_public_and_tenant_pages_but_not_owner_room_detail(self):
        for route, args in (('home', []), ('public_room_detail', [self.room.pk])):
            page = self.client.get(reverse(route, args=args))
            self.assertContains(page, 'Tiện ích chung của nhà trọ')
            self.assertContains(page, 'Chỗ để xe')
            self.assertContains(page, 'Camera an ninh')
        self.client.force_login(self.owner)
        page = self.client.get(reverse('room_detail', args=[self.room.pk]))
        self.assertNotContains(page, 'Tiện ích chung của nhà trọ')
        self.assertContains(page, 'Tiện ích trong phòng')
        self.assertContains(page, 'Điều hòa')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('my_room')), 'Tiện ích chung của nhà trọ')

    def test_legacy_shared_tokens_are_not_room_filters_or_private_badges(self):
        self.other_room.amenities = 'Điều hòa, chỗ để xe, Camera an ninh, Máy giặt chung'
        self.other_room.save()
        self.assertEqual(self.other_room.amenity_list, ['Điều hòa'])
        page = self.client.get(reverse('public_rooms'))
        self.assertNotIn('chỗ để xe', page.context['amenities'])
        self.assertNotIn('Camera an ninh', page.context['amenities'])
        self.assertIn('Điều hòa', page.context['amenities'])

    def test_room_form_points_shared_facilities_to_property_configuration(self):
        for name in ('Chỗ để xe', 'bãi để xe', 'Camera an ninh', 'Máy giặt chung'):
            form = RoomForm({'room_number': 'NEW', 'floor': 1, 'max_occupants': 2, 'price': '2500000',
                             'status': 'trong', 'amenities': name})
            self.assertFalse(form.is_valid(), name)
            self.assertIn('Thông tin nhà trọ', str(form.errors['amenities']))

    def test_public_gets_do_not_create_missing_settings(self):
        PropertyInfo.objects.all().delete()
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(reverse('home')).status_code, 200)
            self.assertEqual(self.client.get(reverse('public_room_detail', args=[self.room.pk])).status_code, 200)
        self.assertFalse(PropertyInfo.objects.exists())
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for q in queries))

    def test_custom_names_are_escaped_on_public_pages(self):
        self.info.shared_amenities = '<script>alert(1)</script>, Khu sinh hoạt chung'
        self.info.save()
        page = self.client.get(reverse('home'))
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')


class SharedAmenitiesMigrationTests(TransactionTestCase):
    def test_existing_shared_tokens_move_without_altering_prices_or_other_room_fields(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        target = [node for node in latest if node[0] not in ('billing', 'rooms')] + [
            ('billing', '0015_water_per_person'), ('rooms', '0016_simplify_identity_profile')]
        try:
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            LegacyRoom = apps.get_model('rooms', 'Room')
            first = LegacyRoom.objects.create(room_number='C01', price=2500000, description='Mô tả giữ nguyên',
                amenities='Điều hòa, Chỗ để xe, Camera an ninh, Sân phơi riêng')
            second = LegacyRoom.objects.create(room_number='C02', price=2700000,
                amenities='Gác lửng, bãi để xe, Máy giặt chung')
            MigrationExecutor(connection).migrate(latest)
            first = Room.objects.get(pk=first.pk)
            self.assertEqual(first.amenities, 'Điều hòa, Sân phơi riêng')
            self.assertEqual((first.price, first.description), (2500000, 'Mô tả giữ nguyên'))
            self.assertEqual(Room.objects.get(pk=second.pk).amenities, 'Gác lửng')
            self.assertEqual(PropertyInfo.current().amenity_list, ['Chỗ để xe', 'Camera an ninh', 'Máy giặt chung'])
        finally:
            MigrationExecutor(connection).migrate(latest)
