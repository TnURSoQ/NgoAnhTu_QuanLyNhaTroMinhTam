from datetime import date, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import FileSystemStorage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.money import whole_dong
from billing.models import Invoice, InvoiceDraft
from billing.services import default_room_fee
from support.models import NotificationRead
from support.notifications import mark_read, read_token, unread_count
from support.services import notification_feed_for, owner_notification_feed
from . import renewal_services as service, services
from .models import (Contract, ContractDocument, ContractEvent, ContractRenewal,
                     ContractTenant, MoveOutNotice, RenewalProposal, Room)
from .renewal_forms import validate_document
from .test_contracts import make_contract, make_room, make_tenant


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RenewalTests(TestCase):
    def setUp(self):
        self.private_folder = TemporaryDirectory()
        self.addCleanup(self.private_folder.cleanup)
        storage_patch = patch.object(ContractDocument._meta.get_field('file'), 'storage',
                                     FileSystemStorage(location=self.private_folder.name))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.today = timezone.localdate()
        self.owner = User.objects.create_user('owner-renewal', role='owner')
        self.a = make_tenant('045123498765', 'Nguyễn Minh An')
        self.b = make_tenant('045987653124', 'Lê Thu Hà')
        self.contract = make_contract(make_room('101'), [self.a, self.b], end=self.today + timedelta(days=90))
        self.a.refresh_from_db()
        self.user = self.a.user
        self.other = make_tenant('045537982146', 'Trần Nam')
        self.other_contract = make_contract(make_room('102'), [self.other])
        self.other.refresh_from_db()

    def propose(self, user=None, **changes):
        data = dict(expected_end_date=self.contract.end_date,
                    new_end_date=self.contract.end_date + timedelta(days=180))
        data.update(changes)
        return service.propose(self.contract, user or self.user, **data)

    def test_tenant_proposal_needs_owner_acceptance(self):
        end = self.contract.end_date
        proposal = self.propose()
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, end)
        self.assertEqual(proposal.status, 'awaiting_owner')
        self.assertEqual(ContractRenewal.objects.count(), 0)
        service.respond(proposal, self.owner, 'accept')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, proposal.new_end_date)
        self.assertEqual(self.contract.deposit_balance, 0)
        self.assertEqual(self.contract.room.status, Room.Status.DANG_THUE)
        self.assertEqual(ContractRenewal.objects.get().proposal, proposal)

    def test_owner_proposal_requires_representative_confirmation(self):
        proposal = self.propose(self.owner, monthly_rent=2700000, deposit=2500000)
        with self.assertRaises(PermissionDenied):
            service.respond(proposal, self.owner, 'accept')
        service.respond(proposal, self.user, 'accept')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.agreed_rent, 2000000)
        self.assertEqual(self.contract.agreed_deposit, 2000000)
        self.assertEqual(self.contract.rent_on(proposal.effective_date), 2700000)
        self.assertEqual(self.contract.deposit_on(proposal.effective_date), 2500000)
        self.assertEqual(self.contract.monthly_rent, 2000000)
        self.assertEqual(self.contract.deposit, 2000000)

    def test_owner_counteroffer_preserves_old_proposal_and_requires_new_consent(self):
        first = self.propose()
        counter = self.propose(self.owner, monthly_rent=2400000, replace_id=first.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, 'superseded')
        with self.assertRaises(ValidationError):
            service.respond(first, self.owner, 'accept')
        with self.assertRaises(ValidationError):
            self.propose(self.owner, replace_id=first.pk)
        service.respond(counter, self.user, 'accept')
        self.assertEqual(ContractRenewal.objects.count(), 1)

    def test_tenant_cannot_inject_financial_terms(self):
        proposal = self.propose(monthly_rent=1, deposit=0, terms='miễn tiền')
        self.assertEqual(proposal.monthly_rent, 2000000)
        self.assertEqual(proposal.deposit, 2000000)
        self.assertEqual(proposal.terms, '')

    def test_nonrepresentative_and_foreign_tenant_cannot_act(self):
        for user in [self.other.user, self.owner.__class__.objects.create_user('cooccupant', role='tenant')]:
            if user.username == 'cooccupant':
                self.b.user = user
                self.b.save(update_fields=['user'])
            with self.assertRaises(PermissionDenied):
                self.propose(user)
        proposal = self.propose(self.owner)
        with self.assertRaises(PermissionDenied):
            service.respond(proposal, self.b.user, 'accept')

    def test_reject_withdraw_and_duplicate_response(self):
        proposal = self.propose()
        with self.assertRaises(PermissionDenied):
            service.respond(proposal, self.owner, 'withdraw')
        service.respond(proposal, self.owner, 'reject', 'Chưa thống nhất thời hạn')
        with self.assertRaises(ValidationError):
            service.respond(proposal, self.owner, 'accept')
        proposal = self.propose()
        service.respond(proposal, self.user, 'withdraw')
        self.assertEqual(ContractRenewal.objects.count(), 0)

    def test_stale_contract_dates_rejected(self):
        with self.assertRaises(ValidationError):
            self.propose(expected_end_date=self.contract.end_date - timedelta(days=1))
        proposal = self.propose()
        Contract.objects.filter(pk=self.contract.pk).update(end_date=self.contract.end_date + timedelta(days=2))
        with self.assertRaises(ValidationError):
            service.respond(proposal, self.owner, 'accept')
        self.assertEqual(ContractRenewal.objects.count(), 0)

    def test_expired_still_occupied_and_can_extend_same_terms(self):
        Contract.objects.filter(pk=self.contract.pk).update(end_date=self.today - timedelta(days=3))
        self.contract.refresh_from_db()
        proposal = self.propose(new_end_date=self.today + timedelta(days=180),
                                effective_date=self.today - timedelta(days=2))
        self.assertEqual(self.contract.room.status, Room.Status.DANG_THUE)
        service.respond(proposal, self.owner, 'accept')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, self.today + timedelta(days=180))

    def test_no_backdated_price_changes(self):
        Contract.objects.filter(pk=self.contract.pk).update(end_date=self.today - timedelta(days=3))
        self.contract.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.propose(self.owner, new_end_date=self.today + timedelta(days=90),
                effective_date=self.today - timedelta(days=2), monthly_rent=2500000)

    def test_price_change_blocked_when_affected_invoice_already_issued(self):
        effective = self.contract.end_date + timedelta(days=1)
        invoice = Invoice.objects.create(contract=self.contract, month=effective.month, year=effective.year,
            room_fee=2000000, total_amount=2000000, due_date=effective)
        with self.assertRaises(ValidationError):
            self.propose(self.owner, monthly_rent=2500000)
        invoice.refresh_from_db()
        self.assertEqual(invoice.room_fee, 2000000)

    def test_invoice_created_after_offer_prevents_later_price_acceptance(self):
        proposal = self.propose(self.owner, monthly_rent=2500000)
        effective = proposal.effective_date
        Invoice.objects.create(contract=self.contract, month=effective.month, year=effective.year,
            room_fee=2000000, total_amount=2000000, due_date=effective)
        with self.assertRaises(ValidationError):
            service.respond(proposal, self.user, 'accept')

    def test_rent_by_billing_period_with_midmonth_effective_date(self):
        Contract.objects.filter(pk=self.contract.pk).update(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.contract.refresh_from_db()
        proposal = self.propose(self.owner, new_end_date=date(2027, 6, 30),
            effective_date=date(2027, 1, 16), monthly_rent=3100000)
        service.respond(proposal, self.user, 'accept')
        self.assertEqual(default_room_fee(self.contract, 12, 2026), 2000000)
        expected = whole_dong((Decimal(2000000) * 15 + Decimal(3100000) * 16) / 31)
        self.assertEqual(default_room_fee(self.contract, 1, 2027), expected)
        self.assertEqual(default_room_fee(self.contract, 2, 2027), 3100000)

    def test_drafts_refresh_defaults_but_preserve_owner_amounts_and_old_invoices(self):
        Contract.objects.filter(pk=self.contract.pk).update(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.contract.refresh_from_db()
        default = InvoiceDraft.objects.create(contract=self.contract, month=1, year=2027, room_fee=2000000)
        custom = InvoiceDraft.objects.create(contract=self.contract, month=2, year=2027, room_fee=1900000)
        old = Invoice.objects.create(contract=self.contract, month=12, year=2026, room_fee=2000000,
                                     total_amount=2000000, due_date=date(2026, 12, 10))
        proposal = self.propose(self.owner, new_end_date=date(2027, 6, 30), monthly_rent=2700000)
        service.respond(proposal, self.user, 'accept')
        default.refresh_from_db(); custom.refresh_from_db(); old.refresh_from_db()
        self.assertEqual((default.room_fee, default.revision), (2700000, 1))
        self.assertEqual((custom.room_fee, custom.revision), (1900000, 0))
        self.assertEqual(old.room_fee, 2000000)
        self.assertTrue(ContractEvent.objects.filter(audience='owner', content__contains='1 nháp đã sửa riêng').exists())

    def test_deposit_is_carried_without_new_cash_or_deleting_debt(self):
        services.receive_deposit(self.contract, amount=2000000, occurred_on=self.today, created_by=self.owner)
        invoice = Invoice.objects.create(contract=self.contract, month=self.today.month, year=self.today.year,
            room_fee=1000000, total_amount=1000000, due_date=self.today)
        proposal = self.propose(self.owner, deposit=2500000)
        service.respond(proposal, self.user, 'accept')
        self.assertEqual(self.contract.deposit_balance, 2000000)
        self.assertEqual(self.contract.deposit_entries.count(), 1)
        self.assertEqual(invoice.total_paid(), 0)
        with self.assertRaises(ValidationError):
            services.receive_deposit(self.contract, amount=500000, occurred_on=self.today)

    def test_moveout_notice_needs_rep_and_does_not_checkout(self):
        notice = service.notify_moveout(self.contract, self.user, self.today + timedelta(days=15), '')
        service.respond_moveout(notice, self.owner, 'acknowledge', 'Sẽ hẹn giờ kiểm tra phòng')
        self.contract.refresh_from_db()
        self.contract.room.refresh_from_db()
        self.assertEqual(self.contract.status, 'hieu_luc')
        self.assertIsNone(self.contract.checkout_date)
        self.assertEqual(self.contract.room.status, 'dang_thue')
        with self.assertRaises(ValidationError):
            self.propose()
        service.respond_moveout(notice, self.user, 'cancel')
        self.propose()

    def test_moveout_is_mutually_exclusive_with_pending_renewal(self):
        self.propose()
        with self.assertRaises(ValidationError):
            service.notify_moveout(self.contract, self.user, self.today)

    def test_checkout_closes_intentions_only_at_actual_handover(self):
        notice = service.notify_moveout(self.contract, self.user, self.today)
        services.checkout_contract(self.contract, self.today)
        notice.refresh_from_db()
        self.assertEqual(notice.status, 'completed')
        with self.assertRaises(ValidationError):
            service.respond_moveout(notice, self.user, 'cancel')

    def test_terms_snapshot_preserved_and_changed_base_blocks_acceptance(self):
        proposal = self.propose()
        Contract.objects.filter(pk=self.contract.pk).update(payment_terms='Ngày 5 hằng tháng')
        with self.assertRaises(ValidationError):
            service.respond(proposal, self.owner, 'accept')
        proposal.refresh_from_db()
        self.assertEqual(proposal.base_terms['payment_terms'], '')

    def test_offline_requires_signed_document_and_distinguishes_owner_recording(self):
        with TemporaryDirectory() as folder, override_settings(PRIVATE_MEDIA_ROOT=folder):
            proposal = service.record_offline(self.contract, self.owner,
                SimpleUploadedFile('phu-luc.pdf', b'%PDF-1.4\n%%EOF'),
                expected_end_date=self.contract.end_date, new_end_date=self.contract.end_date + timedelta(days=180))
            self.assertEqual(proposal.status, 'accepted')
            self.assertEqual(proposal.source, 'offline')
            self.assertEqual(proposal.responded_by, self.owner)
            self.assertTrue(proposal.documents.get().file.storage.exists(proposal.documents.get().file.name))

    def test_invalid_offline_document_rolls_back_entire_agreement(self):
        old_end = self.contract.end_date
        with self.assertRaises(ValidationError):
            service.record_offline(self.contract, self.owner,
                SimpleUploadedFile('fake.pdf', b'<script>bad</script>'),
                expected_end_date=old_end, new_end_date=old_end + timedelta(days=180))
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, old_end)
        self.assertFalse(RenewalProposal.objects.exists())
        self.assertFalse(ContractDocument.objects.exists())

    def test_document_download_and_print_permissions_including_ended_contract(self):
        with TemporaryDirectory() as folder, override_settings(PRIVATE_MEDIA_ROOT=folder):
            document = service.save_document(self.contract, self.owner,
                SimpleUploadedFile('hop-dong.pdf', b'%PDF-1.4\n%%EOF'), title='Hợp đồng', kind='original')
            url = reverse('contract_document_download', args=[document.pk])
            self.client.force_login(self.other.user)
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.get(reverse('my_contract_detail', args=[self.contract.pk])).status_code, 404)
            self.client.force_login(self.user)
            services.checkout_contract(self.contract, self.today)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            response.close()
            self.assertEqual(self.client.get(reverse('my_contract_print', args=[self.contract.pk])).status_code, 200)

    def test_tenant_page_detail_and_representative_actions(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('my_contracts')), reverse('my_contract_detail', args=[self.contract.pk]))
        response = self.client.get(reverse('my_contract_detail', args=[self.contract.pk]))
        for text in ('Đề nghị gia hạn', 'Thông báo dự kiến trả phòng', 'Cọc thực tế đang giữ', 'Tài liệu hợp đồng'):
            self.assertContains(response, text)
        self.assertContains(response, reverse('my_contract_print', args=[self.contract.pk]))

    def test_view_acceptance_requires_checkbox_and_post(self):
        proposal = self.propose(self.owner)
        self.client.force_login(self.user)
        url = reverse('renewal_respond', args=[proposal.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {'action': 'accept'})
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'awaiting_tenant')
        self.client.post(url, {'action': 'accept', 'confirm': 'on'})
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, 'accepted')

    def test_no_auto_renewal_or_room_release_when_expired(self):
        Contract.objects.filter(pk=self.contract.pk).update(end_date=self.today - timedelta(days=1))
        self.client.force_login(self.user)
        response = self.client.get(reverse('my_contract_detail', args=[self.contract.pk]))
        self.assertContains(response, 'Đã hết hạn')
        self.contract.refresh_from_db()
        self.contract.room.refresh_from_db()
        self.assertEqual(self.contract.end_date, self.today - timedelta(days=1))
        self.assertEqual(self.contract.room.status, 'dang_thue')
        self.assertFalse(ContractRenewal.objects.exists())

    def test_notifications_route_to_contract_and_have_independent_read_state(self):
        self.propose()
        rows = list(owner_notification_feed(self.owner))
        row = next(item for item in rows if item['notification_kind'] == 'contract_event')
        result = mark_read(self.owner, read_token(self.owner, row))
        self.assertEqual(result['url'], reverse('contract_detail', args=[self.contract.pk]))
        self.assertFalse(result['is_unread'])
        another = User.objects.create_user('other-owner', role='owner')
        self.assertGreater(unread_count(another), 0)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('owner_notifications_panel')), 'Đề nghị gia hạn hợp đồng mới')

    def test_due_reminder_versions_30_then_7_then_expired_and_no_get_writes(self):
        end = self.today + timedelta(days=20)
        Contract.objects.filter(pk=self.contract.pk).update(end_date=end)
        with patch('rooms.contract_notifications.timezone.localdate', return_value=self.today):
            row = next(item for item in notification_feed_for(self.a) if item['notification_kind'] == 'contract_due')
            result = mark_read(self.user, read_token(self.user, row))
            self.assertFalse(result['is_unread'])
            self.assertEqual(unread_count(self.user), 0)
        with patch('rooms.contract_notifications.timezone.localdate', return_value=end - timedelta(days=7)):
            self.assertEqual(unread_count(self.user), 1)
            row = next(item for item in notification_feed_for(self.a) if item['notification_kind'] == 'contract_due')
            self.assertIn('7 ngày', row['title'])
            mark_read(self.user, read_token(self.user, row))
            self.assertEqual(unread_count(self.user), 0)
        with patch('rooms.contract_notifications.timezone.localdate', return_value=end + timedelta(days=1)):
            self.assertEqual(unread_count(self.user), 1)
            before = NotificationRead.objects.count()
            self.client.force_login(self.user)
            self.assertContains(self.client.get(reverse('my_notifications_panel')), 'Hợp đồng đã hết hạn')
            self.assertEqual(NotificationRead.objects.count(), before)

    def test_staff_without_owner_role_cannot_propose(self):
        staff = User.objects.create_user('staff-renewal', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('contract_renew', args=[self.contract.pk])).status_code, 302)
        with self.assertRaises(PermissionDenied):
            self.propose(staff)

    def test_recorded_terms_are_audited_for_both_sides_and_pending_offers_block_edits(self):
        data = {'payment_terms': 'Thanh toán trước ngày 5 hằng tháng.', 'renewal_terms': '',
                'checkout_terms': 'Báo trước theo tài liệu đã ký.'}
        service.record_terms(self.contract, self.owner, data)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.payment_terms, data['payment_terms'])
        self.assertEqual(ContractEvent.objects.filter(title__contains='Cập nhật điều khoản').count(), 2)
        self.propose()
        with self.assertRaises(ValidationError):
            service.record_terms(self.contract, self.owner, {**data, 'payment_terms': 'Nội dung khác'})
        with self.assertRaises(PermissionDenied):
            service.record_terms(self.contract, self.user, data)

    def test_owner_document_form_rejects_linking_another_contracts_renewal(self):
        from .renewal_forms import ContractDocumentForm
        proposal = self.propose(self.owner)
        service.respond(proposal, self.user, 'accept')
        form = ContractDocumentForm(self.other_contract, {'title': 'Phụ lục', 'kind': 'annex', 'proposal': proposal.pk},
            {'file': SimpleUploadedFile('phu-luc.pdf', b'%PDF-1.4\n%%EOF')})
        self.assertFalse(form.is_valid())
        self.assertIn('proposal', form.errors)

    def test_offline_late_failure_removes_written_file_and_rolls_back_proposal(self):
        from pathlib import Path
        with patch('rooms.renewal_services._apply', side_effect=ValidationError('Không thể chốt')):
            with self.assertRaises(ValidationError):
                service.record_offline(self.contract, self.owner,
                    SimpleUploadedFile('phu-luc.pdf', b'%PDF-1.4\n%%EOF'),
                    expected_end_date=self.contract.end_date, new_end_date=self.contract.end_date + timedelta(days=180))
        self.assertFalse(ContractDocument.objects.exists())
        self.assertFalse(RenewalProposal.objects.exists())
        self.assertFalse(list(Path(self.private_folder.name).rglob('*.pdf')))

    def test_short_renewal_gets_fresh_reminder_after_old_expiry_warning_was_read(self):
        Contract.objects.filter(pk=self.contract.pk).update(end_date=self.today - timedelta(days=1))
        self.contract.refresh_from_db()
        old = next(item for item in notification_feed_for(self.a) if item['notification_kind'] == 'contract_due')
        mark_read(self.user, read_token(self.user, old))
        proposal = self.propose(new_end_date=self.today + timedelta(days=3))
        service.respond(proposal, self.owner, 'accept')
        new = next(item for item in notification_feed_for(self.a) if item['notification_kind'] == 'contract_due')
        self.assertTrue(new['is_unread'])
        self.assertGreater(new['notification_time'], old['notification_time'])
