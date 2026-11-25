from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import Tenant
from rooms.contract_forms import ContractCreateForm, ContractTransferForm
from rooms.models import CoOccupantRequest, ContractTenant
from . import drafts, services
from .forms import InvoiceCreateForm, UtilityRateForm
from .models import Invoice, UtilityRate, UtilityReading
from .test_drafts import DraftBase


class WaterPerPersonTests(DraftBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.rate.water_billing_method = 'per_person'
        cls.rate.water_price = 50000
        cls.rate.save()
        cls.contract.initial_electric = 100
        cls.contract.save(update_fields=['initial_electric'])
        cls.room.max_occupants = 5
        cls.room.save()

    def add_member(self, suffix='2'):
        tenant = Tenant.objects.create(full_name=f'Người ở cùng {suffix}',
            id_card_number='12345678900' + suffix, phone='0901234567')
        ContractTenant.objects.create(contract=self.contract, tenant=tenant)
        return tenant

    def test_default_price_and_configuration_unit(self):
        rate = UtilityRate.objects.create(electric_price=4000, effective_date=self.today)
        self.assertEqual((rate.water_price, rate.water_billing_method), (50000, 'per_person'))
        self.assertEqual(rate.water_unit_label, 'đ/người/tháng')
        self.assertEqual(UtilityRateForm().fields['water_price'].initial, 50000)
        rate = services.add_utility_rate(electric_price=4000, effective_date=self.today)
        self.assertEqual((rate.water_price, rate.water_billing_method), (50000, 'per_person'))

    def test_draft_counts_approved_people_and_excludes_pending_request(self):
        self.add_member()
        CoOccupantRequest.objects.create(contract=self.contract, submitted_by=self.tenant,
            full_name='Hồ sơ chờ duyệt', id_card_number='123456789003', phone='0901234567')
        draft = self.generate()
        self.assertEqual((draft.water_people_count, draft.water_unit_price), (2, 50000))
        self.assertIsNone(draft.old_water)
        self.assertIsNone(draft.new_water)
        self.assertFalse(draft.is_ready)

    def test_owner_can_close_count_and_publish_without_water_meter(self):
        self.add_member()
        draft = self.generate()
        # A person who left during this period can still be included in the owner's count.
        result = self.save(self.row(draft, new_electric=150, water_people_count=3), publish=True)
        self.assertEqual(result, (1, 0))
        invoice = Invoice.objects.get()
        self.assertEqual((invoice.water_people_count, invoice.water_fee), (3, 150000))
        self.assertEqual(invoice.total_amount, 2925000)
        self.assertTrue(invoice.water_calculation_matches)
        self.assertIsNone(invoice.utility_reading.old_water)
        self.assertIsNone(invoice.utility_reading.new_water)

    def test_partial_month_prorates_rent_but_charges_full_water(self):
        self.contract.start_date = self.today
        self.contract.prorate_first_month = True
        self.contract.save()
        invoice = self.create(water_people_count=2)
        self.assertEqual(invoice.water_fee, 100000)
        self.assertEqual(invoice.room_fee, services.default_room_fee(self.contract, self.today.month, self.today.year))

    def test_manual_create_uses_electric_handover_and_ignores_stale_water_fields(self):
        invoice = self.create(old_electric=0, old_water=999, new_water=1)
        self.assertEqual(invoice.utility_reading.old_electric, 100)
        self.assertIsNone(invoice.utility_reading.water_usage())
        self.assertEqual((invoice.water_billing_method, invoice.water_people_count, invoice.water_fee),
                         ('per_person', 1, 50000))

    def test_later_roster_price_and_service_changes_do_not_change_issued_invoice(self):
        invoice = self.create(water_people_count=2)
        total = invoice.total_amount
        self.add_member()
        services.add_utility_rate(electric_price=5000, water_price=70000, effective_date=self.today)
        invoice.refresh_from_db()
        self.assertEqual((invoice.water_unit_price, invoice.water_people_count, invoice.water_fee), (50000, 2, 100000))
        self.assertEqual(invoice.total_amount, total)
        self.client.force_login(self.owner)
        for name in ('invoice_detail', 'invoice_print'):
            page = self.client.get(reverse(name, args=[invoice.pk]))
            self.assertContains(page, '2 người')
            self.assertContains(page, '50.000')
            self.assertNotContains(page, 'm³')
        self.client.force_login(self.tenant.user)
        for name in ('my_invoice_detail', 'my_invoice_print'):
            page = self.client.get(reverse(name, args=[invoice.pk]))
            self.assertContains(page, '2 người')
            self.assertNotContains(page, 'm³')

    def test_draft_keeps_price_and_owner_count_until_publication(self):
        draft = self.generate()
        services.add_utility_rate(electric_price=9000, water_price=70000, effective_date=self.today)
        self.save(self.row(draft, new_electric=150, water_people_count=4))
        draft.refresh_from_db()
        self.assertEqual((draft.water_unit_price, draft.water_people_count), (50000, 4))
        self.assertEqual(draft.estimated_total, 2975000)
        self.save(self.row(draft), publish=True)
        self.assertEqual(Invoice.objects.get().water_fee, 200000)

    def test_missing_count_stays_draft_and_zero_fraction_or_overflow_rejected(self):
        draft = self.generate()
        self.assertEqual(self.save(self.row(draft, new_electric=150, water_people_count=None), publish=True), (0, 1))
        draft.refresh_from_db()
        self.assertIsNone(draft.water_people_count)
        for count in (0, -1, Decimal('1.5'), 100000):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                self.save(self.row(draft, water_people_count=count), publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_manual_invalid_count_rolls_back_reading_and_invoice(self):
        for count in (0, -1, True, Decimal('1.5'), 100000):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                self.create(water_people_count=count)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(UtilityReading.objects.exists())

    def test_roster_change_while_table_open_requires_reload(self):
        draft = self.generate()
        row = self.row(draft, new_electric=150)
        self.add_member()
        with self.assertRaisesMessage(ValidationError, 'danh sách người ở'):
            self.save(row, publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_next_period_electric_baseline_works_without_any_water_readings(self):
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, contract=self.contract, month=previous.month,
            year=previous.year, old_electric=100, new_electric=135)
        invoice = self.create(new_electric=150)
        self.assertEqual(invoice.utility_reading.old_electric, 135)
        self.assertEqual(invoice.electric_fee, 52500)
        self.assertEqual(invoice.water_fee, 50000)

    def test_new_contract_and_transfer_forms_only_require_electric_meter(self):
        self.assertNotIn('initial_water', ContractCreateForm().fields)
        self.assertNotIn('initial_water', ContractTransferForm(self.contract).fields)
        form = InvoiceCreateForm(month=self.today.month, year=self.today.year,
                                 initial={'room': self.room.pk})
        self.assertEqual(form.initial['water_people_count'], 1)
        self.assertFalse(form.fields['new_water'].required)

    def test_public_pages_show_full_month_person_policy(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse('billing_settings'))
        self.assertContains(page, 'đ/người/tháng')
        page = self.client.get(reverse('public_room_detail', args=[self.room.pk]))
        self.assertContains(page, 'đ/người/tháng')
        self.assertContains(page, 'không chia theo ngày ở')

    def test_manual_post_requires_count_and_has_no_water_meter_inputs(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse('invoice_create'), {'room': self.room.pk})
        self.assertContains(page, 'name="water_people_count"')
        self.assertNotContains(page, 'name="new_water"')
        self.assertNotContains(page, 'name="old_water"')
        data = {'room': self.room.pk, 'month': self.today.month, 'year': self.today.year,
            'new_electric': '150', 'room_fee': '2500000', 'due_date': self.today,
            'items-TOTAL_FORMS': '0', 'items-INITIAL_FORMS': '0'}
        page = self.client.post(reverse('invoice_create'), data)
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context['form'].errors.get('water_people_count'))
        data['water_people_count'] = '3'
        self.assertEqual(self.client.post(reverse('invoice_create'), data).status_code, 302)
        self.assertEqual(Invoice.objects.get().water_fee, 150000)
