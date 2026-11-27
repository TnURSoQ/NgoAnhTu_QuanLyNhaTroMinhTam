from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class WaterPolicyMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_issued_metered_bills_and_converts_only_unissued_drafts(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        target = [node for node in latest if node[0] not in ('billing', 'rooms')] + [
            ('billing', '0014_payment_correction_audit'), ('rooms', '0018_contract_checkout_terms_contract_payment_terms_and_more')]
        try:
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            Room = apps.get_model('rooms', 'Room')
            Contract = apps.get_model('rooms', 'Contract')
            Tenant = apps.get_model('accounts', 'Tenant')
            Member = apps.get_model('rooms', 'ContractTenant')
            Rate = apps.get_model('billing', 'UtilityRate')
            Invoice = apps.get_model('billing', 'Invoice')
            Draft = apps.get_model('billing', 'InvoiceDraft')
            Reading = apps.get_model('billing', 'UtilityReading')
            Payment = apps.get_model('billing', 'Payment')
            today = timezone.localdate()
            room = Room.objects.create(room_number='W01', price=2500000)
            contract = Contract.objects.create(room=room, start_date=today - timedelta(days=40),
                                              end_date=today + timedelta(days=365))
            for index in (1, 2):
                tenant = Tenant.objects.create(full_name=f'Người {index}', id_card_number=f'12345678900{index}', phone='0901234567')
                Member.objects.create(contract=contract, tenant=tenant, is_representative=index == 1)
            rate = Rate.objects.create(electric_price=3500, water_price=15000, effective_date=today - timedelta(days=30))
            scheduled = Rate.objects.create(electric_price=4000, water_price=20000, effective_date=today + timedelta(days=10))
            reading = Reading.objects.create(room=room, contract=contract, month=1, year=today.year,
                old_electric=0, new_electric=100, old_water=10, new_water=13)
            invoice = Invoice.objects.create(contract=contract, utility_reading=reading, month=1, year=today.year,
                room_fee=2500000, electric_fee=350000, water_fee=45000, electric_unit_price=3500,
                water_unit_price=15000, total_amount=2895000, due_date=today)
            payment = Payment.objects.create(invoice=invoice, amount=100000, paid_date=today)
            issued = Draft.objects.create(contract=contract, invoice=invoice, month=1, year=today.year,
                room_fee=2500000, water_unit_price=15000, old_water=10, new_water=13)
            pending = Draft.objects.create(contract=contract, month=2, year=today.year, room_fee=2500000,
                electric_unit_price=3500, water_unit_price=15000, old_water=13, new_water=15, revision=7,
                service_items=[{'description': 'Wifi', 'quantity': 1, 'unit_price': '100000'}])
            MigrationExecutor(connection).migrate(latest)
            from .models import Invoice as CurrentInvoice, InvoiceDraft, UtilityRate, UtilityReading, Payment as CurrentPayment
            converted = CurrentInvoice.objects.get(pk=invoice.pk)
            self.assertEqual((converted.water_billing_method, converted.water_unit_price, converted.water_fee), ('metered', 15000, 45000))
            self.assertEqual(converted.total_amount, 2895000)
            self.assertIsNone(converted.water_people_count)
            self.assertEqual(CurrentPayment.objects.get(pk=payment.pk).amount, 100000)
            self.assertEqual(UtilityReading.objects.get(pk=reading.pk).new_water, 13)
            issued = InvoiceDraft.objects.get(pk=issued.pk)
            self.assertEqual((issued.water_billing_method, issued.water_unit_price, issued.new_water), ('metered', 15000, 13))
            pending = InvoiceDraft.objects.get(pk=pending.pk)
            self.assertEqual((pending.water_billing_method, pending.water_unit_price, pending.water_people_count), ('per_person', 50000, 2))
            self.assertEqual(pending.revision, 8)
            self.assertEqual(pending.service_items, [{'description': 'Wifi', 'quantity': 1, 'unit_price': '100000'}])
            self.assertIsNone(pending.new_water)
            self.assertEqual(UtilityRate.objects.get(pk=rate.pk).water_billing_method, 'metered')
            self.assertEqual(UtilityRate.objects.get(pk=rate.pk).water_price, 15000)
            self.assertEqual(UtilityRate.objects.get(pk=scheduled.pk).water_price, 20000)
            self.assertEqual((UtilityRate.current().water_price, UtilityRate.current().water_billing_method), (50000, 'per_person'))
            future = UtilityRate.objects.filter(effective_date=scheduled.effective_date).first()
            self.assertEqual((future.electric_price, future.water_price, future.water_billing_method), (4000, 50000, 'per_person'))
        finally:
            MigrationExecutor(connection).migrate(latest)
