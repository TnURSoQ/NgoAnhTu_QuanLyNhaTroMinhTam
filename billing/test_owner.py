from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from rooms.models import Contract, ContractTenant, Room
from . import services
from .models import Invoice, InvoiceService, Payment, Service, UtilityRate, UtilityReading


class BillingBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.owner = User.objects.create_user('owner', role='owner', is_staff=True)
        cls.room = Room.objects.create(room_number='101', price=Decimal('2500000'))
        cls.contract = Contract.objects.create(room=cls.room, start_date=cls.today - timedelta(days=60),
                                               end_date=cls.today + timedelta(days=365))
        cls.tenant = Tenant.objects.create(full_name='Nguyễn Minh Ánh', id_card_number='012345678901',
                                           phone='0901234567')
        ContractTenant.objects.create(contract=cls.contract, tenant=cls.tenant, is_representative=True)
        cls.rate = UtilityRate.objects.create(water_billing_method='metered', electric_price=3500, water_price=15000,
                                              effective_date=cls.today - timedelta(days=30))
        cls.wifi = Service.objects.create(name='Wifi', unit_price=100000)

    def create(self, **overrides):
        data = dict(room=self.room, month=self.today.month, year=self.today.year,
                    old_electric=100, new_electric=150, old_water=10, new_water=13,
                    due_date=self.today + timedelta(days=10))
        data.update(overrides)
        return services.create_invoice(**data)

    def assert_status(self, inv, expected):
        inv.refresh_from_db()
        self.assertEqual(inv.status, expected)


class InvoiceServiceTests(BillingBase):
    def test_total_and_snapshots_with_custom_charge(self):
        inv = self.create(note='Kỳ đầu', service_items=[
            {'service': self.wifi, 'quantity': 2},
            {'description': 'Vệ sinh cuối kỳ', 'quantity': 1, 'unit_price': 50000}])
        self.assertEqual(inv.total_amount, Decimal('2970000'))
        self.assertEqual(inv.electric_unit_price, 3500)
        self.assertEqual(inv.water_unit_price, 15000)
        self.assertEqual(inv.note, 'Kỳ đầu')
        line = inv.invoice_services.get(service=self.wifi)
        self.assertEqual(line.unit_price, 100000)
        self.assertEqual(line.description, 'Wifi')
        services.add_utility_rate(electric_price=5000, water_price=20000, effective_date=self.today)
        services.save_service(service=self.wifi, name='Wifi mới', unit_price=300000)
        line.refresh_from_db()
        line.save()
        inv.recalculate_total()
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, Decimal('2970000'))
        self.assertEqual(line.subtotal, 200000)
        self.assertEqual(line.description, 'Wifi')
        self.assertEqual(inv.electric_unit_price, 3500)

    def test_line_explicit_price_and_model_default(self):
        inv = self.create(service_items=[])
        line = InvoiceService.objects.create(invoice=inv, service=self.wifi, quantity=2)
        self.assertEqual(line.unit_price, 100000)
        line.unit_price = Decimal('12345')
        line.save(update_fields=['unit_price'])
        line.refresh_from_db()
        self.assertEqual(line.subtotal, 24690)

    def test_multiple_custom_charges_are_allowed(self):
        inv = self.create(service_items=[{'description': 'A', 'unit_price': 1000},
                                          {'description': 'B', 'unit_price': 2000}])
        self.assertEqual(inv.invoice_services.filter(service=None).count(), 2)

    def test_duplicate_period_is_rejected(self):
        self.create()
        with self.assertRaises(ValidationError):
            self.create(new_electric=999)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(UtilityReading.objects.get().new_electric, 150)

    def test_new_meter_less_than_old_rejected(self):
        for values in [{'new_electric': 99}, {'new_water': 9}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self.create(**values)
        self.assertFalse(UtilityReading.objects.exists())

    def test_room_without_active_contract_rejected(self):
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        with self.assertRaisesMessage(ValidationError, 'không có hợp đồng'):
            self.create()
        self.assertFalse(UtilityReading.objects.exists())

    def test_no_current_rate_rejected_and_rolled_back(self):
        UtilityRate.objects.all().update(effective_date=self.today + timedelta(days=1))
        with self.assertRaisesMessage(ValidationError, 'Chưa cấu hình'):
            self.create()
        self.assertFalse(UtilityReading.objects.exists())
        self.assertFalse(Invoice.objects.exists())

    def test_overflow_and_bad_lines_roll_back_entire_invoice(self):
        for data in [{'room_fee': Decimal('99999999.99')},
                     {'new_electric': 99999999},
                     {'service_items': [{'description': 'Lớn', 'unit_price': 99999999, 'quantity': 2}]},
                     {'service_items': [{'description': 'Sai', 'unit_price': -1}]},
                     {'service_items': [{'description': 'Sai', 'unit_price': 1, 'quantity': 0}]}]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.create(**data)
            self.assertFalse(Invoice.objects.exists())
            self.assertFalse(UtilityReading.objects.exists())

    def test_existing_orphan_reading_updated_and_restored_on_failure(self):
        reading = UtilityReading.objects.create(room=self.room, month=self.today.month, year=self.today.year,
                                                old_electric=0, new_electric=1, old_water=0, new_water=1)
        with self.assertRaises(ValidationError):
            self.create(room_fee=services.MAX_FEE)
        reading.refresh_from_db()
        self.assertEqual(reading.new_electric, 1)
        inv = self.create()
        self.assertEqual(inv.utility_reading_id, reading.pk)
        reading.refresh_from_db()
        self.assertEqual(reading.new_electric, 150)

    def test_admin_creation_also_saves_prices(self):
        reading = UtilityReading.objects.create(room=self.room, month=self.today.month, year=self.today.year,
                                                old_electric=0, new_electric=50, old_water=0, new_water=3)
        inv = services.create_invoice_from_reading(reading)
        self.assertEqual(inv.electric_unit_price, 3500)
        self.assertEqual(inv.water_unit_price, 15000)
        self.assertEqual(inv.total_amount, 2820000)

    def test_create_uses_previous_final_readings_instead_of_submitted_old_values(self):
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        inv = self.create(old_electric=0, old_water=0)
        self.assertEqual(inv.utility_reading.old_electric, 125)
        self.assertEqual(inv.utility_reading.old_water, 12)
        self.assertEqual(inv.electric_fee, 87500)
        self.assertEqual(inv.water_fee, 15000)

    def test_create_only_needs_new_readings_when_previous_period_exists(self):
        self.contract.start_date = self.today.replace(month=1, day=1)
        self.contract.save()
        UtilityReading.objects.create(room=self.room, month=12, year=self.today.year - 1,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        inv = services.create_invoice(room=self.room, month=1, year=self.today.year,
                                       new_electric=150, new_water=13)
        self.assertEqual(inv.utility_reading.old_electric, 125)
        self.assertEqual(inv.utility_reading.old_water, 12)

    def test_first_period_still_requires_initial_readings(self):
        with self.assertRaises(ValidationError):
            services.create_invoice(room=self.room, month=self.today.month, year=self.today.year,
                                     new_electric=150, new_water=13)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(UtilityReading.objects.exists())

    def test_admin_creation_uses_previous_period_and_persists_derived_old_readings(self):
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        reading = UtilityReading.objects.create(room=self.room, month=self.today.month, year=self.today.year,
                                                 old_electric=0, new_electric=150, old_water=0, new_water=13)
        inv = services.create_invoice_from_reading(reading)
        reading.refresh_from_db()
        self.assertEqual(reading.old_electric, 125)
        self.assertEqual(reading.old_water, 12)
        self.assertEqual(inv.electric_fee, 87500)

    def test_previous_readings_ignore_future_period_and_other_rooms(self):
        self.contract.start_date = self.today.replace(month=1, day=1)
        self.contract.save()
        UtilityReading.objects.create(room=self.room, month=12, year=self.today.year - 1,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        UtilityReading.objects.create(room=self.room, month=2, year=self.today.year,
                                      old_electric=200, new_electric=500, old_water=20, new_water=50)
        other_room = Room.objects.create(room_number='102', price=2000000)
        UtilityReading.objects.create(room=other_room, month=12, year=self.today.year - 1,
                                      old_electric=500, new_electric=999, old_water=50, new_water=99)
        inv = self.create(month=1)
        self.assertEqual(inv.utility_reading.old_electric, 125)
        self.assertEqual(inv.utility_reading.old_water, 12)


class PaymentStatusTests(BillingBase):
    def test_partial_paid_adjust_full_and_void_recalculate_status(self):
        inv = self.create()
        payment = services.record_payment(inv, amount=1000000, note='Lần 1')
        self.assertEqual(payment.note, 'Lần 1')
        self.assert_status(inv, Invoice.Status.THU_MOT_PHAN)
        payment = services.adjust_payment(payment, amount=inv.total_amount, paid_date=payment.paid_date,
            method=payment.method, note=payment.note, reason='Sửa số tiền theo đối chiếu', actor=self.owner)
        self.assert_status(inv, Invoice.Status.DA_THANH_TOAN)
        payment = services.adjust_payment(payment, amount=1000000, paid_date=payment.paid_date,
            method=payment.method, note=payment.note, reason='Điều chỉnh lại số thực nhận', actor=self.owner)
        self.assert_status(inv, Invoice.Status.THU_MOT_PHAN)
        services.void_payment(payment, reason='Ghi nhận trùng', actor=self.owner)
        self.assert_status(inv, Invoice.Status.CHUA_THANH_TOAN)

    def test_overdue_has_priority_over_partial_and_paid_has_priority_over_overdue(self):
        inv = self.create(due_date=self.today - timedelta(days=1))
        p = services.record_payment(inv, amount=1000000)
        self.assert_status(inv, Invoice.Status.QUA_HAN)
        services.record_payment(inv, amount=inv.total_amount - p.amount)
        self.assert_status(inv, Invoice.Status.DA_THANH_TOAN)
        services.void_payment(p, reason='Nhập nhầm khoản thu', actor=self.owner)
        self.assert_status(inv, Invoice.Status.QUA_HAN)

    def test_rejects_zero_negative_and_excess_payment(self):
        inv = self.create()
        services.record_payment(inv, amount=1000000)
        for amount in [0, -1, inv.total_amount, services.MAX_FEE + 1]:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                services.record_payment(inv, amount=amount)
        self.assertEqual(inv.payments.count(), 1)

    def test_due_today_is_not_overdue(self):
        inv = self.create(due_date=self.today)
        services.record_payment(inv, amount=1)
        self.assert_status(inv, Invoice.Status.THU_MOT_PHAN)

    def test_command_includes_partial_invoices_and_dry_run_preserves_data(self):
        inv = self.create()
        services.record_payment(inv, amount=1)
        Invoice.objects.filter(pk=inv.pk).update(due_date=self.today - timedelta(days=2))
        out = StringIO()
        call_command('check_overdue_invoices', dry_run=True, stdout=out)
        self.assertIn(f'HĐ #{inv.pk}', out.getvalue())
        self.assert_status(inv, Invoice.Status.THU_MOT_PHAN)
        call_command('check_overdue_invoices', stdout=StringIO())
        self.assert_status(inv, Invoice.Status.QUA_HAN)


class OwnerBillingViewTests(BillingBase):
    def setUp(self):
        self.client.force_login(self.owner)

    def test_permissions_on_all_owner_routes(self):
        inv = self.create()
        payment = services.record_payment(inv, amount=1)
        urls = [reverse('invoice_list'), reverse('invoice_create'), reverse('billing_settings'),
                reverse('invoice_detail', args=[inv.pk]), reverse('invoice_delete', args=[inv.pk]),
                reverse('payment_delete', args=[payment.pk]), reverse('service_edit', args=[self.wifi.pk]),
                reverse('service_delete', args=[self.wifi.pk])]
        self.client.logout()
        for url in urls:
            for method in ['get', 'post']:
                response = getattr(self.client, method)(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/dang-nhap/', response.url)
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        for url in urls:
            for method in ['get', 'post']:
                self.assertRedirects(getattr(self.client, method)(url), reverse('home'),
                                     fetch_redirect_response=False)
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())

    def test_new_pages_have_no_admin_links_even_for_staff_owner(self):
        inv = self.create()
        payment = services.record_payment(inv, amount=1)
        for name, args in [('invoice_list', []), ('invoice_create', []), ('billing_settings', []),
                           ('invoice_detail', [inv.pk]), ('invoice_delete', [inv.pk]),
                           ('payment_delete', [payment.pk]), ('service_edit', [self.wifi.pk]),
                           ('service_delete', [self.wifi.pk])]:
            with self.subTest(name=name):
                r = self.client.get(reverse(name, args=args))
                self.assertEqual(r.status_code, 200)
                self.assertNotContains(r, 'href="/admin/')

    def test_list_defaults_filters_counts_and_search_without_accents(self):
        self.contract.start_date = self.today.replace(month=1, day=1)
        self.contract.save()
        inv = self.create()
        services.record_payment(inv, amount=1)
        other_month = 1 if self.today.month != 1 else 2
        self.create(month=other_month)
        r = self.client.get(reverse('invoice_list'))
        self.assertEqual([row['invoice'].pk for row in r.context['rows']], [inv.pk])
        tabs = {t['key']: t['count'] for t in r.context['tabs']}
        self.assertEqual(tabs['thu_mot_phan'], 1)
        for query in ['nguyen minh anh', '101']:
            r = self.client.get(reverse('invoice_list'), {'q': query, 'status': 'thu_mot_phan'})
            self.assertEqual(len(r.context['rows']), 1)
        r = self.client.get(reverse('invoice_list'), {'status': 'da_thanh_toan'})
        self.assertEqual(r.context['rows'], [])
        r = self.client.get(reverse('invoice_list'), {'month': other_month, 'year': self.today.year})
        self.assertEqual(len(r.context['rows']), 1)
        self.assertEqual(r.context['rows'][0]['invoice'].month, other_month)

    def test_detail_breakdown_snapshot_custom_line_and_collection_flow(self):
        inv = self.create(note='Ghi chú hóa đơn', service_items=[
            {'description': 'Thu dọn phòng', 'unit_price': 50000}])
        url = reverse('invoice_detail', args=[inv.pk])
        r = self.client.get(url)
        for text in ['Cách tính', '50 kWh x 3.500 đ', 'Thu dọn phòng', 'Ghi chú hóa đơn']:
            self.assertContains(r, text)
        self.assertEqual(r.context['form'].initial['amount'], inv.total_amount)
        r = self.client.post(url, {'amount': '1.000.000', 'paid_date': self.today,
                                   'method': 'chuyen_khoan', 'note': 'Thu lần đầu'})
        self.assertRedirects(r, url)
        self.assert_status(inv, Invoice.Status.THU_MOT_PHAN)
        self.assertEqual(inv.payments.get().note, 'Thu lần đầu')
        r = self.client.post(url, {'amount': '99.999.999', 'paid_date': self.today, 'method': 'tien_mat'})
        self.assertContains(r, 'vượt quá số còn nợ')
        self.assertEqual(inv.payments.count(), 1)
        remaining = inv.total_amount - inv.total_paid()
        self.client.post(url, {'amount': str(remaining).replace('.', ','), 'paid_date': self.today,
                              'method': 'tien_mat'})
        self.assert_status(inv, Invoice.Status.DA_THANH_TOAN)

    def test_legacy_delete_url_requires_void_reason_and_keeps_the_record(self):
        inv = self.create()
        payment = services.record_payment(inv, amount=inv.total_amount)
        url = reverse('payment_delete', args=[payment.pk])
        self.assertContains(self.client.get(url), 'Xác nhận')
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assert_status(inv, Invoice.Status.DA_THANH_TOAN)
        self.assertRedirects(self.client.post(url, {'action': 'void', 'reason': 'Ghi nhận nhầm'}), reverse('invoice_detail', args=[inv.pk]))
        self.assertTrue(Payment.objects.get(pk=payment.pk).is_voided)
        self.assert_status(inv, Invoice.Status.CHUA_THANH_TOAN)

    def test_invoice_deletion_removes_unused_reading(self):
        inv = self.create()
        reading_id = inv.utility_reading_id
        url = reverse('invoice_delete', args=[inv.pk])
        self.assertContains(self.client.get(url), 'Xóa hóa đơn')
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertRedirects(self.client.post(url), reverse('invoice_list'))
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertFalse(UtilityReading.objects.filter(pk=reading_id).exists())

    def test_invoice_with_payment_cannot_be_deleted(self):
        inv = self.create()
        services.record_payment(inv, amount=1)
        self.assertRedirects(self.client.post(reverse('invoice_delete', args=[inv.pk])),
                             reverse('invoice_detail', args=[inv.pk]))
        self.assertTrue(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertTrue(UtilityReading.objects.filter(pk=inv.utility_reading_id).exists())

    def test_shared_reading_is_preserved_on_invoice_deletion(self):
        inv = self.create()
        other = Contract.objects.create(room=self.room, start_date=self.today,
                                         end_date=self.today + timedelta(days=30), status='ket_thuc')
        Invoice.objects.create(contract=other, utility_reading=inv.utility_reading, month=1, year=2001,
                                room_fee=1, total_amount=1, due_date=self.today)
        reading_id = inv.utility_reading_id
        services.delete_invoice(inv)
        self.assertTrue(UtilityReading.objects.filter(pk=reading_id).exists())

    def post_data(self):
        return {'month': self.today.month, 'year': self.today.year, 'room': self.room.pk,
                'old_electric': '100', 'new_electric': '150', 'old_water': '10', 'new_water': '13',
                'room_fee': '2.500.000', 'due_date': self.today, 'note': 'Tạo từ giao diện',
                'items-TOTAL_FORMS': '2', 'items-INITIAL_FORMS': '0',
                'items-0-service': str(self.wifi.pk), 'items-0-description': 'Wifi',
                'items-0-quantity': '2', 'items-0-unit_price': '',
                'items-1-description': 'Khoản khác', 'items-1-quantity': '1',
                'items-1-unit_price': '50.000'}

    def test_create_from_single_screen_and_excludes_billed_rooms(self):
        r = self.client.post(reverse('invoice_create'), self.post_data())
        inv = Invoice.objects.get()
        self.assertRedirects(r, reverse('invoice_detail', args=[inv.pk]))
        self.assertEqual(inv.total_amount, 2970000)
        self.assertEqual(inv.note, 'Tạo từ giao diện')
        r = self.client.get(reverse('invoice_create'))
        self.assertNotIn(self.room, r.context['form'].fields['room'].queryset)

    def test_formset_can_remove_default_service(self):
        data = self.post_data()
        data['items-0-DELETE'] = 'on'
        data['items-0-quantity'] = 'bad'
        r = self.client.post(reverse('invoice_create'), data)
        self.assertEqual(r.status_code, 302)
        inv = Invoice.objects.get()
        self.assertEqual(inv.invoice_services.count(), 1)
        self.assertEqual(inv.total_amount, 2770000)

    def test_create_errors_keep_values_and_create_no_partial_data(self):
        data = self.post_data()
        data['new_electric'] = '50'
        r = self.client.post(reverse('invoice_create'), data)
        self.assertContains(r, 'Chỉ số điện mới không được nhỏ hơn chỉ số cũ.')
        self.assertEqual(r.context['form']['note'].value(), data['note'])
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(UtilityReading.objects.exists())

    def test_previous_meter_defaults_and_first_period_blank(self):
        r = self.client.get(reverse('invoice_create'), {'room': self.room.pk})
        self.assertEqual(r.context['form'].initial['old_electric'], '')
        self.assertFalse(r.context['form'].fields['old_electric'].disabled)
        self.assertEqual(r.context['form'].initial['room_fee'], '2500000')
        UtilityReading.objects.create(room=self.room, month=12, year=self.today.year - 1,
                                        old_electric=1, new_electric=123, old_water=1, new_water=12)
        r = self.client.get(reverse('invoice_create'), {'room': self.room.pk})
        self.assertEqual(r.context['form'].initial['old_electric'], '123.0')
        self.assertEqual(r.context['form'].initial['old_water'], '12.00')
        self.assertTrue(r.context['form'].fields['old_electric'].disabled)
        self.assertTrue(r.context['form'].fields['old_water'].disabled)
        self.assertIsNone(r.context['form']['new_electric'].value())
        self.assertIsNone(r.context['form']['new_water'].value())
        self.assertEqual(r.context['lines'].forms[0].initial['quantity'], 1)

    def test_create_without_posting_old_readings_uses_room_history(self):
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        data = self.post_data()
        del data['old_electric']
        del data['old_water']
        response = self.client.post(reverse('invoice_create'), data)
        self.assertEqual(response.status_code, 302)
        inv = Invoice.objects.get()
        self.assertEqual(inv.utility_reading.old_electric, 125)
        self.assertEqual(inv.utility_reading.old_water, 12)
        self.assertEqual(inv.utility_reading.new_electric, 150)
        self.assertEqual(inv.utility_reading.new_water, 13)

    def test_create_validates_new_readings_against_automatic_old_readings(self):
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=100, new_electric=125, old_water=10, new_water=12)
        data = self.post_data()
        data.update(old_electric='0', old_water='0', new_electric='120')
        response = self.client.post(reverse('invoice_create'), data)
        self.assertContains(response, 'Chỉ số điện mới không được nhỏ hơn chỉ số cũ.')
        self.assertEqual(response.context['form']['old_electric'].value(), '125.0')
        self.assertFalse(Invoice.objects.exists())

    def test_settings_appends_rates_and_keeps_history(self):
        r = self.client.post(reverse('billing_settings'), {
            'action': 'rate', 'electric_price': '4.000', 'water_price': '20.000',
            'effective_date': self.today})
        self.assertRedirects(r, reverse('billing_settings'))
        self.assertEqual(UtilityRate.objects.count(), 2)
        self.rate.refresh_from_db()
        self.assertEqual(self.rate.electric_price, 3500)
        self.assertEqual(UtilityRate.current().electric_price, 4000)
        r = self.client.post(reverse('billing_settings'), {
            'action': 'rate', 'electric_price': '0', 'water_price': '20.000',
            'effective_date': self.today})
        self.assertTrue(r.context['rate_form'].errors)
        self.assertEqual(UtilityRate.objects.count(), 2)

    def test_services_crud_and_protect_used_service(self):
        self.client.post(reverse('billing_settings'), {
            'action': 'service', 'name': 'Rác', 'unit_price': '30.000'})
        svc = Service.objects.get(name='Rác')
        self.client.post(reverse('service_edit', args=[svc.pk]), {'name': 'Rác mới', 'unit_price': '40.000'})
        svc.refresh_from_db()
        self.assertEqual(svc.unit_price, 40000)
        self.client.post(reverse('service_delete', args=[svc.pk]))
        self.assertFalse(Service.objects.filter(pk=svc.pk).exists())
        self.create()
        r = self.client.post(reverse('service_delete', args=[self.wifi.pk]), follow=True)
        self.assertContains(r, 'Không thể xóa dịch vụ đã dùng trong hóa đơn.')
        self.assertTrue(Service.objects.filter(pk=self.wifi.pk).exists())

    def test_tenant_routes_partial_label_and_custom_calculation(self):
        inv = self.create(service_items=[{'description': 'Tự nhập', 'unit_price': 50000}])
        services.record_payment(inv, amount=1)
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        self.assertEqual(reverse('my_invoices'), '/hoa-don-cua-toi/')
        self.assertEqual(reverse('my_invoice_detail', args=[inv.pk]), f'/hoa-don-cua-toi/{inv.pk}/')
        self.assertTrue(reverse('my_payments').startswith('/hoa-don-cua-toi/'))
        r = self.client.get(reverse('my_invoice_detail', args=[inv.pk]))
        for text in ['Thu một phần', 'Tự nhập', 'Cách tính', '50 kWh x 3.500 đ']:
            self.assertContains(r, text)

    def test_debt_links_from_overview_report_contract_and_blocked_actions(self):
        inv = self.create(due_date=self.today - timedelta(days=1))
        detail = reverse('invoice_detail', args=[inv.pk])
        for name, args in [('owner_dashboard', []), ('report_dashboard', []),
                           ('contract_detail', [self.contract.pk]), ('contract_checkout', [self.contract.pk]),
                           ('contract_transfer', [self.contract.pk])]:
            with self.subTest(name=name):
                self.assertContains(self.client.get(reverse(name, args=args)), f'href="{detail}"')
        r = self.client.get(reverse('owner_dashboard'))
        self.assertContains(r, f'href="{reverse("invoice_list")}?month={self.today.month}&amp;year={self.today.year}"')
