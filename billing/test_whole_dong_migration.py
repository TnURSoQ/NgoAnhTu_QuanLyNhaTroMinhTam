from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class WholeDongMigrationTests(TransactionTestCase):
    def test_normalizes_legacy_amounts_without_rounding_up_and_keeps_totals_consistent(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        other_apps = [node for node in latest if node[0] not in ('billing', 'rooms')]
        target = other_apps + [('billing', '0007_bankaccount_paymentnotice'),
                               ('rooms', '0004_room_amenities_room_description_viewingappointment')]
        try:
            executor.migrate(target)
            apps = executor.loader.project_state(target).apps
            Room = apps.get_model('rooms', 'Room')
            Contract = apps.get_model('rooms', 'Contract')
            Invoice = apps.get_model('billing', 'Invoice')
            Reading = apps.get_model('billing', 'UtilityReading')
            Rate = apps.get_model('billing', 'UtilityRate')
            Service = apps.get_model('billing', 'Service')
            Line = apps.get_model('billing', 'InvoiceService')
            Payment = apps.get_model('billing', 'Payment')
            Notice = apps.get_model('billing', 'PaymentNotice')
            Tenant = apps.get_model('accounts', 'Tenant')
            today = timezone.localdate()
            room = Room.objects.create(room_number='VND', price=Decimal('2000000.99'), area=Decimal('20.50'))
            contract = Contract.objects.create(room=room, deposit=Decimal('2000000.75'), start_date=today,
                                                 end_date=today + timedelta(days=365))
            rate = Rate.objects.create(electric_price=Decimal('3.50'), water_price=Decimal('50000.99'),
                                        effective_date=today)
            service = Service.objects.create(name='Wifi', unit_price=Decimal('120000.99'))
            reading = Reading.objects.create(room=room, month=11, year=2026, old_electric=0,
                                               new_electric=Decimal('65.00'), old_water=0, new_water=2)
            invoice = Invoice.objects.create(contract=contract, utility_reading=reading, month=11, year=2026,
                                               room_fee=2000000, electric_fee=Decimal('227.50'), water_fee=100000,
                                               electric_unit_price=Decimal('3.50'), water_unit_price=50000,
                                               total_amount=Decimal('2220227.50'), due_date=today + timedelta(days=10))
            Line.objects.create(invoice=invoice, service=service, quantity=1, unit_price=120000,
                                  description='Wifi', subtotal=120000)
            payment = Payment.objects.create(invoice=invoice, amount=Decimal('1000000.75'))
            tenant = Tenant.objects.create(full_name='Kiểm thử', id_card_number='test-migration', phone='0900000000')
            notice = Notice.objects.create(invoice=invoice, tenant=tenant, amount=Decimal('1220226.75'))
            paid_invoice = Invoice.objects.create(contract=contract, month=12, year=2026, room_fee=Decimal('0.75'),
                                                    electric_fee=Decimal('0.75'), total_amount=Decimal('1.50'),
                                                    due_date=today)
            Payment.objects.create(invoice=paid_invoice, amount=Decimal('0.75'))
            Payment.objects.create(invoice=paid_invoice, amount=Decimal('0.75'))
            small_notice = Notice.objects.create(invoice=paid_invoice, tenant=tenant, amount=Decimal('0.75'))
            MigrationExecutor(connection).migrate(latest)
            from billing.models import Invoice as CurrentInvoice
            from billing.models import PaymentNotice, UtilityRate
            from rooms.models import Contract as CurrentContract, Room as CurrentRoom
            converted = CurrentInvoice.objects.get(pk=invoice.pk)
            self.assertEqual(converted.total_amount, 2220227)
            self.assertEqual(converted.electric_fee, 227)
            self.assertEqual(converted.electric_unit_price, 3)
            self.assertEqual(converted.total_paid(), 1000000)
            self.assertEqual(converted.total_amount - converted.total_paid(), 1220227)
            self.assertEqual(converted.status, 'thu_mot_phan')
            self.assertFalse(converted.electric_calculation_matches)
            self.assertEqual(PaymentNotice.objects.get(pk=notice.pk).amount, 1220226)
            self.assertIsNone(PaymentNotice.objects.get(pk=small_notice.pk).amount)
            self.assertEqual(CurrentRoom.objects.get(pk=room.pk).price, 2000000)
            self.assertEqual(CurrentRoom.objects.get(pk=room.pk).area, Decimal('20.50'))
            self.assertEqual(CurrentContract.objects.get(pk=contract.pk).deposit, 2000000)
            self.assertEqual(UtilityRate.objects.get(pk=rate.pk).electric_price, 3)
            converted_paid = CurrentInvoice.objects.get(pk=paid_invoice.pk)
            self.assertEqual(converted_paid.total_amount, 1)
            self.assertEqual(converted_paid.status, 'da_thanh_toan')
            self.assertEqual(converted_paid.total_paid(), 1)
            self.assertEqual(converted_paid.invoice_services.get().subtotal, 1)
            for inv in [converted, converted_paid]:
                subtotal = sum(inv.invoice_services.values_list('subtotal', flat=True), Decimal('0'))
                self.assertEqual(inv.total_amount, inv.room_fee + inv.electric_fee + inv.water_fee + subtotal)
                self.assertGreaterEqual(inv.total_amount - inv.total_paid(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
