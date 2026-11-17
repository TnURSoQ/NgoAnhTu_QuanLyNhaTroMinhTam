from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class InvoiceSnapshotMigrationTests(TransactionTestCase):
    """Chạy migration thật với hóa đơn cũ, gồm chỉ số bằng 0 và thiếu chỉ số."""

    def test_backfill_preserves_fees_and_copies_prices_and_descriptions(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            target = [node for node in latest if node[0] != 'billing'] + [
                ('billing', '0004_invoice_reminded_at')]
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
            today = timezone.localdate()
            room = Room.objects.create(room_number='M01', price=2500000)
            contract = Contract.objects.create(room=room, start_date=today,
                                                 end_date=today + timedelta(days=365))
            Rate.objects.create(electric_price=3500, water_price=15000, effective_date=today)
            service = Service.objects.create(name='Wifi cũ', unit_price=100000)
            ids = []
            for month, usage in [(1, 50), (2, 0), (3, None)]:
                reading = None
                if usage is not None:
                    reading = Reading.objects.create(room=room, month=month, year=today.year,
                                                       old_electric=100, new_electric=100 + usage,
                                                       old_water=10, new_water=12 if usage else 10)
                inv = Invoice.objects.create(contract=contract, utility_reading=reading,
                                               month=month, year=today.year, room_fee=2500000,
                                               electric_fee=180000 if usage else 0,
                                               water_fee=50000 if usage else 0, total_amount=2930000,
                                               due_date=today + timedelta(days=10))
                Line.objects.create(invoice=inv, service=service, quantity=2, subtotal=200000)
                Payment.objects.create(invoice=inv, amount=100000)
                ids.append(inv.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            Invoice = apps.get_model('billing', 'Invoice')
            Line = apps.get_model('billing', 'InvoiceService')
            first = Invoice.objects.get(pk=ids[0])
            self.assertEqual(first.electric_unit_price, 3600)
            self.assertEqual(first.water_unit_price, 25000)
            self.assertEqual(first.electric_fee, 180000)
            self.assertEqual(first.water_fee, 50000)
            self.assertEqual(first.total_amount, 2930000)
            self.assertEqual(first.status, 'thu_mot_phan')
            for pk in ids[1:]:
                inv = Invoice.objects.get(pk=pk)
                self.assertEqual(inv.electric_unit_price, 3500)
                self.assertEqual(inv.water_unit_price, 15000)
            for line in Line.objects.all():
                self.assertEqual(line.unit_price, 100000)
                self.assertEqual(line.description, 'Wifi cũ')
                self.assertEqual(line.subtotal, Decimal('200000'))
        finally:
            MigrationExecutor(connection).migrate(latest)
