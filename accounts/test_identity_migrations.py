from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SimplifyIdentityMigrationTests(TransactionTestCase):
    def test_existing_addresses_types_and_cooccupant_proposals_are_preserved(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [node for node in latest if node[0] not in ('accounts', 'rooms')] + [
            ('accounts', '0004_tenant_birth_registration_place_tenant_document_type_and_more'),
            ('rooms', '0015_cooccupantrequest_birth_registration_place_and_more')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            Tenant = apps.get_model('accounts', 'Tenant')
            Room = apps.get_model('rooms', 'Room')
            Contract = apps.get_model('rooms', 'Contract')
            Request = apps.get_model('rooms', 'CoOccupantRequest')
            person = Tenant.objects.create(full_name='Người thử', id_card_number='012345678901', phone='0901111222',
                document_type='can_cuoc', residence_address='Địa chỉ trên thẻ thử', note='Ghi chú ban đầu')
            room = Room.objects.create(room_number='801', price=2500000)
            contract = Contract.objects.create(room=room, start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
            proposal = Request.objects.create(contract=contract, submitted_by=person, full_name='Người ở cùng thử',
                id_card_number='012345678902', phone='0901111222', document_type='can_cuoc',
                residence_address='Địa chỉ người ở cùng thử')
            conflicting = Tenant.objects.create(full_name='Người cần đối chiếu', id_card_number='012345678903', phone='0901111222',
                document_type='cccd', permanent_address='Địa chỉ đã chọn', residence_address='Địa chỉ nhập khác', note='Giữ ghi chú')
            blank = Tenant.objects.create(full_name='Chưa bổ sung', id_card_number='123456789', phone='0901111222')
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            Tenant = apps.get_model('accounts', 'Tenant')
            Request = apps.get_model('rooms', 'CoOccupantRequest')
            person = Tenant.objects.get(pk=person.pk)
            proposal = Request.objects.get(pk=proposal.pk)
            for record, address in [(person, 'Địa chỉ trên thẻ thử'), (proposal, 'Địa chỉ người ở cùng thử')]:
                self.assertEqual(record.document_type, 'cccd')
                self.assertEqual(record.permanent_address, address)
                self.assertFalse(hasattr(record, 'residence_address'))
                self.assertFalse(hasattr(record, 'identifying_features'))
            self.assertEqual(person.note, 'Ghi chú ban đầu')
            conflicting = Tenant.objects.get(pk=conflicting.pk)
            self.assertEqual(conflicting.permanent_address, 'Địa chỉ đã chọn')
            self.assertIn('Địa chỉ nhập khác', conflicting.note)
            self.assertTrue(conflicting.note.startswith('Giữ ghi chú'))
            blank = Tenant.objects.get(pk=blank.pk)
            self.assertEqual(blank.permanent_address, '')
            self.assertEqual(blank.document_type, '')
        finally:
            MigrationExecutor(connection).migrate(latest)
