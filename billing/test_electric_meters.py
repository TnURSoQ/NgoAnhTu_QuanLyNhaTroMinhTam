from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .form_fields import ElectricMeterFormField, ElectricMeterInput
from .meters import electric_reading
from .models import UtilityReading
from .test_owner import BillingBase
from .test_drafts import DraftBase


class ElectricMeterInputTests(SimpleTestCase):
    def test_vietnamese_grouping_and_one_decimal_are_unambiguous(self):
        field = ElectricMeterFormField()
        for text, expected in [('1.611', '1611'), ('1611', '1611'), ('1.611,1', '1611.1'),
                               ('1611.1', '1611.1'), ('1611,1', '1611.1'), ('99.999,9', '99999.9'), ('0', '0')]:
            with self.subTest(text=text):
                self.assertEqual(field.clean(text), Decimal(expected))
        self.assertEqual(ElectricMeterInput().format_value(Decimal('1611')), '1.611')
        self.assertEqual(ElectricMeterInput().format_value(Decimal('1611.1')), '1.611,1')

    def test_extra_decimal_digits_and_overflow_are_rejected_without_rounding(self):
        for value in ['1.611,16', '1611.16', '1611.10', '100000', '100.000', '-1', 'NaN', 'Infinity']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ElectricMeterFormField().clean(value)
        for value in [Decimal('0.01'), Decimal('1611.16'), Decimal('100000'), Decimal('NaN')]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                electric_reading(value)
        self.assertEqual(electric_reading(Decimal('0.50')), Decimal('0.5'))
        self.assertIsNone(ElectricMeterFormField(required=False).clean(''))


class ElectricMeterInvoiceTests(BillingBase):
    def test_one_tenth_is_billed_consistently_and_printed_with_one_decimal(self):
        invoice = self.create(old_electric=Decimal('1611'), new_electric=Decimal('1611.1'))
        self.assertEqual(invoice.utility_reading.electric_usage(), Decimal('0.1'))
        self.assertEqual(invoice.electric_fee, 350)
        self.client.force_login(self.owner)
        for route in ('invoice_detail', 'invoice_print'):
            response = self.client.get(reverse(route, args=[invoice.pk]))
            self.assertContains(response, '1.611,1')
            self.assertContains(response, '0,1 kWh')
            self.assertNotContains(response, '1.611,10')
        response = self.client.get(reverse('report_excel'), {'month': self.today.month, 'year': self.today.year})
        book = load_workbook(BytesIO(response.content))
        row = list(book['Đối soát điện nước'].iter_rows(min_row=2))[0]
        self.assertEqual(row[3].value, 1611.1)
        self.assertEqual(row[3].number_format, '#,##0.0')
        self.assertEqual(row[6].value, 350)

    def test_service_and_direct_model_writes_reject_hundredths(self):
        for value in (Decimal('1611.16'), Decimal('100000')):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.create(old_electric=0, new_electric=value)
        self.assertFalse(UtilityReading.objects.exists())
        with self.assertRaises(ValidationError):
            UtilityReading.objects.create(room=self.room, contract=self.contract, year=self.today.year,
                month=self.today.month, old_electric=0, new_electric=Decimal('0.01'))
        with self.assertRaises(ValidationError):
            type(self.contract).objects.filter(pk=self.contract.pk).update(initial_electric=Decimal('1611.16'))


class ElectricMeterDraftTests(DraftBase):
    def test_draft_rejects_hundredths_and_keeps_revision_on_failure(self):
        draft = self.generate()
        with self.assertRaises(ValidationError):
            self.save(self.row(draft, old_electric=0, new_electric=Decimal('0.01')))
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 0)
        self.assertIsNone(draft.new_electric)
        draft.old_electric, draft.new_electric = Decimal(0), Decimal('0.01')
        self.assertFalse(draft.is_ready)


class ElectricMeterMigrationTests(TransactionTestCase):
    def test_precision_migration_archives_originals_and_preserves_issued_money_and_can_reverse(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [node for node in latest if node[0] not in ('billing', 'rooms')]
        before += [('billing', '0015_water_per_person'), ('rooms', '0018_contract_checkout_terms_contract_payment_terms_and_more')]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            Room = apps.get_model('rooms', 'Room')
            Contract = apps.get_model('rooms', 'Contract')
            Reading = apps.get_model('billing', 'UtilityReading')
            Invoice = apps.get_model('billing', 'Invoice')
            Payment = apps.get_model('billing', 'Payment')
            Draft = apps.get_model('billing', 'InvoiceDraft')
            today = timezone.localdate()
            room = Room.objects.create(room_number='PRECISION', price=2500000)
            contract = Contract.objects.create(room=room, start_date=today, end_date=today + timedelta(days=365),
                initial_electric=Decimal('1000.12'))
            reading = Reading.objects.create(room=room, contract=contract, year=today.year, month=1,
                old_electric=Decimal('1000.12'), new_electric=Decimal('1611.16'), old_water=Decimal('10.23'), new_water=Decimal('12.45'))
            invoice = Invoice.objects.create(contract=contract, utility_reading=reading, year=today.year, month=1,
                room_fee=2500000, electric_fee=1000000, total_amount=3500000, due_date=today)
            payment = Payment.objects.create(invoice=invoice, amount=500000, paid_date=today)
            draft = Draft.objects.create(contract=contract, year=today.year, month=2, room_fee=2500000,
                old_electric=Decimal('1611.16'), new_electric=Decimal('1711.26'), revision=10)
            MigrationExecutor(connection).migrate(latest)
            apps = MigrationExecutor(connection).loader.project_state(latest).apps
            current = apps.get_model('billing', 'UtilityReading').objects.get(pk=reading.pk)
            self.assertEqual(current.old_electric, Decimal('1000.1'))
            self.assertEqual(current.new_electric, Decimal('1611.1'))
            self.assertEqual(current.old_water, Decimal('10.23'))
            self.assertEqual(apps.get_model('billing', 'InvoiceDraft').objects.get(pk=draft.pk).revision, 11)
            audit = apps.get_model('billing', 'ElectricMeterPrecisionAudit').objects.get(source_model='billing.utilityreading', source_pk=reading.pk)
            self.assertEqual(audit.original_values['new_electric'], '1611.16')
            issued = apps.get_model('billing', 'Invoice').objects.get(pk=invoice.pk)
            self.assertEqual(issued.electric_fee, 1000000)
            self.assertEqual(issued.total_amount, 3500000)
            self.assertEqual(apps.get_model('billing', 'Payment').objects.get(pk=payment.pk).amount, 500000)
            MigrationExecutor(connection).migrate(before)
            apps = MigrationExecutor(connection).loader.project_state(before).apps
            restored = apps.get_model('billing', 'UtilityReading').objects.get(pk=reading.pk)
            self.assertEqual(restored.new_electric, Decimal('1611.16'))
            self.assertEqual(apps.get_model('rooms', 'Contract').objects.get(pk=contract.pk).initial_electric, Decimal('1000.12'))
            self.assertEqual(apps.get_model('billing', 'InvoiceDraft').objects.get(pk=draft.pk).revision, 10)
        finally:
            MigrationExecutor(connection).migrate(latest)
