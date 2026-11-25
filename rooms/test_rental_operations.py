import csv
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from billing import drafts
from billing import services as billing
from billing.models import Invoice, InvoiceDraft, Payment, Service, UtilityRate, UtilityReading
from . import services
from .forms import RoomForm
from .models import CheckoutRecord, Contract, ContractTenant, DepositEntry, Room


class RentalOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.owner = User.objects.create_user('operations-owner', role='owner')
        cls.room = Room.objects.create(room_number='101', price=2500000, max_occupants=3)
        cls.tenant = Tenant.objects.create(full_name='Người thuê A', id_card_number='010101010101', phone='0901234567')
        cls.wifi = Service.objects.create(name='Wifi', unit_price=100000)
        cls.optional = Service.objects.create(name='Giữ xe ô tô', unit_price=500000)
        UtilityRate.objects.create(water_billing_method='metered', electric_price=3500, water_price=15000, effective_date=cls.today - timedelta(days=365))
        cls.contract = services.create_contract(
            cls.room, [cls.tenant], cls.tenant, cls.today - timedelta(days=60), cls.today + timedelta(days=365),
            Decimal('2000000'), monthly_rent=2500000, initial_electric=100, initial_water=10,
            service_ids=[cls.wifi.pk])

    def invoice(self, **kwargs):
        return billing.create_invoice(room=self.room, month=self.today.month, year=self.today.year,
                                       new_electric=150, new_water=13, **kwargs)

    def receive(self, amount=1000000, **kwargs):
        return services.receive_deposit(self.contract, amount=amount, created_by=self.owner, **kwargs)

    def target_room(self):
        return Room.objects.create(room_number='201', price=2800000, max_occupants=3)

    def test_contract_rent_and_services_are_used_in_invoice_and_draft(self):
        self.room.price = 4000000
        self.room.save()
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        draft = InvoiceDraft.objects.get(contract=self.contract)
        self.assertEqual(draft.room_fee, 2500000)
        self.assertEqual([line['service'] for line in draft.service_items], [self.wifi.pk])
        invoice = self.invoice()
        self.assertEqual(invoice.room_fee, 2500000)
        self.assertEqual(invoice.total_amount, 2820000)
        self.assertEqual(list(invoice.invoice_services.values_list('service_id', flat=True)), [self.wifi.pk])

    def test_no_registered_service_does_not_add_global_fees(self):
        self.contract.services.clear()
        invoice = self.invoice()
        self.assertEqual(invoice.invoice_services.count(), 0)
        self.assertEqual(invoice.total_amount, 2720000)

    def test_initial_readings_override_orphan_from_before_handover(self):
        previous = self.contract.start_date.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=0, new_electric=10, old_water=0, new_water=1)
        invoice = self.invoice(old_electric=0, old_water=0)
        self.assertEqual(invoice.utility_reading.old_electric, 100)
        self.assertEqual(invoice.utility_reading.old_water, 10)

    def test_first_month_proration_uses_actual_calendar_days(self):
        contract = Contract(room=self.room, monthly_rent=2900000, start_date=date(2024, 2, 15),
                            end_date=date(2025, 2, 15), prorate_first_month=True)
        self.assertEqual(billing.default_room_fee(contract, 2, 2024), 1500000)
        self.assertEqual(billing.default_room_fee(contract, 3, 2024), 2900000)
        contract.prorate_first_month = False
        self.assertEqual(billing.default_room_fee(contract, 2, 2024), 2900000)

    def test_invoice_cannot_precede_contract(self):
        previous = self.contract.start_date.replace(day=1) - timedelta(days=1)
        with self.assertRaisesMessage(ValidationError, 'trong kỳ hóa đơn'):
            billing.create_invoice(room=self.room, month=previous.month, year=previous.year,
                                     old_electric=0, old_water=0, new_electric=1, new_water=1)
        self.assertFalse(Invoice.objects.exists())

    def test_two_occupants_in_same_room_month_have_separate_readings_and_invoices(self):
        old_invoice = self.invoice()
        billing.record_payment(old_invoice, amount=old_invoice.total_amount)
        services.checkout_contract(self.contract, self.today)
        other = Tenant.objects.create(full_name='Người thuê B', id_card_number='020202020202', phone='0901234568')
        new = services.create_contract(self.room, [other], other, self.today, self.today + timedelta(days=365),
                                       Decimal('1000000'), initial_electric=160, initial_water=14, service_ids=[])
        self.assertIn(self.room, billing.available_rooms(self.today.month, self.today.year))
        self.assertEqual(drafts.generate_monthly_drafts(self.today.month, self.today.year), 1)
        new_invoice = billing.create_invoice(room=self.room, month=self.today.month, year=self.today.year,
                                              new_electric=180, new_water=15)
        self.assertEqual(new_invoice.contract, new)
        self.assertEqual(new_invoice.utility_reading.old_electric, 160)
        self.assertEqual(new_invoice.utility_reading.electric_usage(), 20)
        old_invoice.utility_reading.refresh_from_db()
        self.assertEqual(old_invoice.utility_reading.old_electric, 100)
        self.assertEqual(old_invoice.utility_reading.new_electric, 150)
        self.assertEqual(UtilityReading.objects.filter(room=self.room, month=self.today.month, year=self.today.year).count(), 2)

    def test_deposit_agreement_is_not_automatically_counted_as_received(self):
        self.assertEqual(self.contract.deposit, 2000000)
        self.assertEqual(self.contract.deposit_balance, 0)
        self.assertFalse(DepositEntry.objects.exists())

    def test_deposit_can_be_received_in_parts_but_never_above_agreed_amount(self):
        self.receive(500000)
        self.receive(1500000)
        self.assertEqual(self.contract.deposit_balance, 2000000)
        with self.assertRaises(ValidationError):
            self.receive(1)
        self.assertEqual(DepositEntry.objects.count(), 2)
        self.assertFalse(Payment.objects.exists())

    def test_receipt_idempotency_and_bad_amounts_or_dates(self):
        reference = uuid.uuid4()
        first = self.receive(500000, reference=reference)
        self.assertEqual(self.receive(500000, reference=reference).pk, first.pk)
        with self.assertRaises(ValidationError):
            self.receive(500001, reference=reference)
        for value in [0, -1, Decimal('0.5'), 100000000]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.receive(value)
        with self.assertRaises(ValidationError):
            self.receive(1, occurred_on=self.today + timedelta(days=1))
        self.assertEqual(DepositEntry.objects.count(), 1)

    def test_checkout_records_refund_due_without_assuming_money_has_been_returned(self):
        self.receive(1500000)
        services.checkout_contract(self.contract, self.today, expected_deposit_balance=1500000,
                                    room_condition=Room.Status.BAO_TRI, created_by=self.owner)
        record = CheckoutRecord.objects.get()
        self.assertEqual(record.deposit_held, 1500000)
        self.assertEqual(record.deposit_refunded, 0)
        self.assertEqual(record.refund_due_at_checkout, 1500000)
        self.assertEqual(self.contract.deposit_balance, 1500000)
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.BAO_TRI)
        self.contract.refresh_from_db()
        self.contract.save()
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.BAO_TRI)

    def test_deduction_requires_reason_and_cannot_exceed_deposit(self):
        self.receive(1000000)
        for kwargs in [dict(deposit_deduction=100000), dict(deposit_deduction=1000001, deduction_reason='Hư hỏng')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                services.checkout_contract(self.contract, self.today, **kwargs)
        self.assertFalse(CheckoutRecord.objects.exists())
        services.checkout_contract(self.contract, self.today, deposit_deduction=100000, deduction_reason='Vỡ kính bàn giao')
        record = CheckoutRecord.objects.get()
        self.assertEqual(record.deposit_deducted, 100000)
        self.assertEqual(record.deposit_refunded, 0)
        self.assertEqual(record.refund_due_at_checkout, 900000)
        self.assertEqual(self.contract.deposit_balance, 900000)
        self.assertEqual(DepositEntry.objects.filter(kind='deduct').get().note, 'Vỡ kính bàn giao')

    def test_stale_deposit_summary_blocks_checkout_without_partial_updates(self):
        self.receive(1000000)
        with self.assertRaisesMessage(ValidationError, 'Số dư cọc đã thay đổi'):
            services.checkout_contract(self.contract, self.today, expected_deposit_balance=0)
        self.assertFalse(CheckoutRecord.objects.exists())
        self.assertEqual(self.contract.deposit_balance, 1000000)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.HIEU_LUC)

    def test_pending_draft_blocks_checkout_and_transfer(self):
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        with self.assertRaisesMessage(ValidationError, 'hóa đơn nháp'):
            services.checkout_contract(self.contract, self.today)
        with self.assertRaisesMessage(ValidationError, 'hóa đơn nháp'):
            services.transfer_contract(self.contract, self.target_room(), self.today, self.contract.end_date)
        self.assertFalse(CheckoutRecord.objects.exists())

    def test_transfer_moves_actual_deposit_once_and_uses_target_rent_and_meters(self):
        self.receive(1200000)
        target = self.target_room()
        new = services.transfer_contract(self.contract, target, self.today, self.contract.end_date,
                                         initial_electric=500, initial_water=30, created_by=self.owner)
        self.assertEqual(self.contract.deposit_balance, 0)
        self.assertEqual(new.deposit_balance, 1200000)
        self.assertEqual(new.agreed_rent, 2800000)
        self.assertEqual(list(new.services.all()), [self.wifi])
        self.assertEqual(DepositEntry.objects.filter(kind='receive').count(), 1)
        self.assertEqual(DepositEntry.objects.filter(kind='transfer_out').count(), 1)
        self.assertEqual(DepositEntry.objects.filter(kind='transfer_in').count(), 1)
        invoice = billing.create_invoice(room=target, month=self.today.month, year=self.today.year,
                                          new_electric=510, new_water=31)
        self.assertEqual(invoice.utility_reading.old_electric, 500)
        self.assertEqual(invoice.utility_reading.old_water, 30)

    def test_saving_old_contract_does_not_mark_new_occupancy_empty(self):
        services.checkout_contract(self.contract, self.today)
        new = services.create_contract(self.room, [self.tenant], self.tenant, self.today,
                                       self.today + timedelta(days=365), 0)
        self.contract.refresh_from_db()
        self.contract.save()
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.DANG_THUE)
        self.assertEqual(Contract.objects.get(room=self.room, status='hieu_luc').pk, new.pk)

    def test_active_room_constraint_and_capacity_reduction(self):
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Contract.objects.create(room=self.room, start_date=self.today, end_date=self.today)
        other = Tenant.objects.create(full_name='Ở cùng', id_card_number='030303030303', phone='0901234569')
        ContractTenant.objects.create(contract=self.contract, tenant=other)
        form = RoomForm({'room_number': '101', 'floor': 1, 'price': '2500000', 'max_occupants': 1,
                         'status': 'dang_thue'}, instance=self.room)
        self.assertFalse(form.is_valid())
        self.assertIn('max_occupants', form.errors)

    def test_future_receipt_and_username_collision_are_rejected(self):
        invoice = self.invoice()
        with self.assertRaisesMessage(ValidationError, 'Ngày thu tiền'):
            billing.record_payment(invoice, amount=1, paid_date=self.today + timedelta(days=1))
        target = self.target_room()
        User.objects.create_user('040404040404', role='owner')
        other = Tenant.objects.create(full_name='Trùng tài khoản', id_card_number='040404040404', phone='0901234570')
        with self.assertRaisesMessage(ValidationError, 'tài khoản khác'):
            services.create_contract(target, [other], other, self.today, self.today + timedelta(days=30), 0)
        self.assertFalse(target.contracts.exists())

    def test_contract_future_start_and_incomplete_meter_handover_are_rejected(self):
        target = self.target_room()
        other = Tenant.objects.create(full_name='Người thuê B', id_card_number='050505050505', phone='0901234571')
        for options in [dict(start_date=self.today + timedelta(days=1)), dict(initial_electric=1)]:
            values = dict(start_date=self.today, end_date=self.today + timedelta(days=365))
            values.update(options)
            with self.assertRaises(ValidationError):
                services.create_contract(target, [other], other, deposit=0, **values)
        self.assertFalse(target.contracts.exists())


    def test_receive_deposit_view_is_idempotent_and_checkout_records_refund(self):
        self.client.force_login(self.owner)
        payload = {'amount': '500.000', 'occurred_on': self.today, 'method': 'cash',
                   'note': 'Nhận trực tiếp', 'reference': str(uuid.uuid4())}
        url = reverse('contract_deposit_receive', args=[self.contract.pk])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.contract.deposit_balance, 500000)
        response = self.client.post(reverse('contract_checkout', args=[self.contract.pk]), {
            'checkout_date': self.today, 'deposit_deduction': '100.000', 'deduction_reason': 'Vỡ kính',
            'refund_method': 'bank', 'room_condition': 'bao_tri', 'expected_deposit_balance': '500000'}, follow=True)
        self.assertContains(response, 'Biên bản trả phòng')
        record = CheckoutRecord.objects.get()
        self.assertEqual(record.deposit_refunded, 0)
        self.assertEqual(record.refund_due_at_checkout, 400000)
        self.assertEqual(record.deposit_deducted, 100000)
        self.assertEqual(record.created_by, self.owner)

    def test_pending_draft_is_shown_on_checkout_page_and_dashboard(self):
        self.client.force_login(self.owner)
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        response = self.client.get(reverse('contract_checkout', args=[self.contract.pk]))
        self.assertContains(response, 'Hoàn tất điện nước tháng')
        self.assertContains(response, 'Xác nhận trả phòng')
        self.assertContains(self.client.get(reverse('owner_dashboard')), 'Điện nước chưa chốt')

    def test_single_create_loads_agreed_rent_baseline_and_only_registered_services(self):
        self.client.force_login(self.owner)
        self.room.price = 4000000
        self.room.save()
        response = self.client.get(reverse('invoice_create'), {'room': self.room.pk})
        self.assertEqual(response.context['form'].initial['room_fee'], '2500000')
        self.assertEqual(response.context['form'].initial['old_electric'], '100.00')
        self.assertTrue(response.context['form'].fields['old_electric'].disabled)
        self.assertEqual(len(response.context['lines'].forms), 1)
        self.assertEqual(response.context['lines'].forms[0].initial['service'], self.wifi.pk)

    def test_print_custom_charge_and_report_keep_deposits_separate_from_revenue(self):
        self.client.force_login(self.owner)
        self.receive(1200000, note='=SUM(1,2)')
        invoice = self.invoice(service_items=[{'description': 'Vệ sinh riêng', 'quantity': 1, 'unit_price': 50000}])
        response = self.client.get(reverse('invoice_print', args=[invoice.pk]))
        self.assertContains(response, 'Vệ sinh riêng')
        self.assertContains(response, 'Chưa ghi nhận thanh toán')
        response = self.client.get(reverse('report_dashboard'))
        self.assertEqual(response.context['deposit_held'], 1200000)
        self.assertEqual(response.context['year_total'], 0)
        response = self.client.get(reverse('cashbook_csv'), {'year': self.today.year})
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(rows[1][1], 'Tiền cọc (tách riêng)')
        self.assertEqual(rows[1][-1], "'=SUM(1,2)")

    def test_new_contract_form_records_services_handover_and_actual_deposit(self):
        self.client.force_login(self.owner)
        target = self.target_room()
        other = Tenant.objects.create(full_name='Người thuê B', id_card_number='060606060606', phone='0901234572')
        response = self.client.post(reverse('contract_create'), {
            'room': target.pk, 'tenants': [other.pk], 'representative': other.pk,
            'start_date': self.today, 'end_date': self.today + timedelta(days=365),
            'deposit': '2.000.000', 'monthly_rent': '2.600.000', 'initial_electric': '500',
            'initial_water': '30', 'prorate_first_month': 'on', 'services': [self.wifi.pk],
            'deposit_paid': '500.000', 'deposit_method': 'bank'})
        self.assertEqual(response.status_code, 302)
        contract = Contract.objects.get(room=target)
        self.assertEqual(contract.agreed_rent, 2600000)
        self.assertEqual(contract.deposit_balance, 500000)
        self.assertEqual(contract.initial_electric, 500)
        self.assertEqual(list(contract.services.all()), [self.wifi])

    def test_tenant_sees_agreed_rent_but_cannot_receive_deposit_print_or_export(self):
        invoice = self.invoice()
        self.room.price = 4000000
        self.room.save()
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        response = self.client.get(reverse('my_room'))
        self.assertContains(response, '2.500.000')
        self.assertNotContains(response, '4.000.000')
        for url in [reverse('contract_deposit_receive', args=[self.contract.pk]),
                    reverse('invoice_print', args=[invoice.pk]), reverse('cashbook_csv')]:
            self.assertEqual(self.client.get(url).status_code, 302)
