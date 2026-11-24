from datetime import date, timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from rooms.models import Contract, ContractTenant, DepositEntry, Room
from rooms.services import apply_deposit_to_invoice
from . import services
from .models import Invoice, InvoiceService, Payment, PaymentNotice, Service
from .test_owner import BillingBase


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class TenantPaymentReceiptTests(BillingBase):
    def setUp(self):
        self.invoice = self.create()
        self.payment = services.record_payment(self.invoice, amount=300000, recorded_by=self.owner,
            paid_date=self.today-timedelta(days=1), note='Thu tiền đợt một')
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)

    def url(self, name, pk=None):
        return reverse(name, args=[pk if pk is not None else self.payment.pk])

    def test_history_and_invoice_rows_link_to_each_transaction(self):
        url = self.url('my_payment_detail')
        for response in (self.client.get(reverse('my_payments')),
                         self.client.get(self.url('my_invoice_detail', self.invoice.pk))):
            self.assertContains(response, f'href="{url}"')
            self.assertContains(response, self.payment.display_code)
            self.assertContains(response, 'payment-row-link')

    def test_detail_shows_actual_amount_method_date_time_code_and_invoice(self):
        response = self.client.get(self.url('my_payment_detail'))
        self.assertContains(response, self.payment.display_code)
        self.assertContains(response, '300.000 đ')
        self.assertContains(response, 'Tiền mặt')
        self.assertContains(response, self.payment.paid_date.strftime('%d/%m/%Y'))
        self.assertContains(response, timezone.localtime(self.payment.recorded_at).strftime('%d/%m/%Y %H:%M:%S'))
        self.assertContains(response, 'Thu tiền đợt một')
        self.assertContains(response, self.contract.display_code)
        self.assertEqual(response.context['remaining'], self.invoice.total_amount-300000)
        self.assertContains(response, 'công nợ hiện tại')
        self.assertContains(response, self.url('my_payment_print'))
        self.assertContains(response, self.url('my_invoice_print', self.invoice.pk))

    def test_tenant_can_print_invoice_before_full_payment_with_correct_balance(self):
        response = self.client.get(self.url('my_invoice_print', self.invoice.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'In / Lưu PDF')
        self.assertContains(response, 'Thu một phần')
        self.assertEqual(response.context['paid'], 300000)
        self.assertEqual(response.context['cash_paid'], 300000)
        self.assertEqual(response.context['remaining'], self.invoice.total_amount-300000)
        self.assertContains(response, 'không xác nhận đã thanh toán đủ')

    def test_payment_receipt_is_for_one_installment_without_claiming_full_invoice_amount(self):
        response = self.client.get(self.url('my_payment_print'))
        self.assertContains(response, 'PHIẾU XÁC NHẬN THANH TOÁN')
        self.assertContains(response, '300.000 đ')
        self.assertEqual(response.context['amount'], 300000)
        self.assertContains(response, 'riêng lần thanh toán này')
        self.assertNotContains(response, '<form')
        self.assertNotContains(response, 'Xóa khoản thu')

    def test_pending_or_rejected_report_is_not_counted_or_given_a_receipt(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=777777, note='Báo tiền chưa đối chiếu')
        for status in (PaymentNotice.Status.CHO_XAC_NHAN, PaymentNotice.Status.TU_CHOI):
            PaymentNotice.objects.filter(pk=notice.pk).update(status=status)
            history = self.client.get(reverse('my_payments'))
            self.assertEqual(list(history.context['payments']), [self.payment])
            statement = self.client.get(self.url('my_invoice_print', self.invoice.pk))
            self.assertEqual(statement.context['paid'], 300000)
            self.assertNotContains(statement, '777.777 đ')
            self.assertNotContains(statement, notice.note)
        self.assertEqual(Payment.objects.count(), 1)

    def test_confirmed_transfer_shows_reported_and_actual_confirmed_amount_separately(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=400000)
        notice = services.confirm_payment_notice(notice, processed_by=self.owner, amount=350000,
            paid_date=self.today, note='Đã đối chiếu số thực nhận')
        payment = notice.payment
        self.assertEqual(payment.recorded_by, self.owner)
        self.assertIsNotNone(payment.recorded_at)
        response = self.client.get(self.url('my_payment_detail', payment.pk))
        self.assertEqual(response.context['amount'], 350000)
        self.assertContains(response, '400.000 đ')
        self.assertContains(response, '350.000 đ')
        self.assertContains(response, 'Thông tin đối chiếu chuyển khoản')
        self.assertContains(response, timezone.localtime(notice.processed_at).strftime('%d/%m/%Y %H:%M:%S'))

    def test_owner_entry_captures_real_recorder_and_system_time_ignoring_posted_metadata(self):
        self.client.force_login(self.owner)
        before = timezone.now()
        response = self.client.post(self.url('invoice_detail', self.invoice.pk), {
            'amount': '200.000', 'paid_date': self.today-timedelta(days=1), 'method': 'chuyen_khoan',
            'recorded_by': self.tenant.user_id, 'recorded_at': '2000-01-01T00:00:00', 'note': 'Đợt hai'})
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.latest('pk')
        self.assertEqual(payment.recorded_by, self.owner)
        self.assertGreaterEqual(payment.recorded_at, before)
        self.assertEqual(payment.paid_date, self.today-timedelta(days=1))
        recorded = payment.recorded_at
        payment.note = 'Ghi chú cập nhật'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            payment.save(update_fields=['note'])
        payment.refresh_from_db()
        self.assertEqual(payment.recorded_at, recorded)

    def test_deposit_offset_has_own_receipt_but_is_not_new_cash(self):
        DepositEntry.objects.create(contract=self.contract, amount=1000000, kind='receive', occurred_on=self.today)
        entry = apply_deposit_to_invoice(self.invoice, amount=200000, occurred_on=self.today,
            note='Người thuê đồng ý đối trừ', created_by=self.owner)
        self.assertEqual(entry.payment.recorded_by, self.owner)
        detail = self.client.get(self.url('my_payment_detail', entry.payment_id))
        self.assertContains(detail, 'không phát sinh thêm tiền mặt hoặc chuyển khoản')
        self.assertEqual(detail.context['amount'], 200000)
        statement = self.client.get(self.url('my_invoice_print', self.invoice.pk))
        self.assertEqual(statement.context['cash_paid'], 300000)
        self.assertEqual(statement.context['deposit_applied'], 200000)
        self.assertEqual(statement.context['paid'], 500000)
        receipt = self.client.get(self.url('my_payment_print', entry.payment_id))
        self.assertContains(receipt, 'PHIẾU ĐỐI TRỪ CỌC')
        self.assertContains(receipt, 'không phải khoản tiền mặt/chuyển khoản mới thu vào')

    def test_old_payment_without_recording_time_is_not_assigned_a_fictitious_time(self):
        Payment.objects.filter(pk=self.payment.pk).update(recorded_at=None, recorded_by=None)
        for name in ('my_payment_detail', 'my_payment_print'):
            response = self.client.get(self.url(name))
            self.assertContains(response, 'Giao dịch cũ chưa lưu giờ ghi nhận')
            self.assertIsNone(response.context['payment'].recorded_at)

    def test_foreign_tenant_cannot_view_or_print_any_transaction_or_invoice(self):
        other_user = User.objects.create_user('unrelated', role='tenant')
        Tenant.objects.create(user=other_user, full_name='Người phòng khác', id_card_number='012345678999', phone='0901234567')
        self.client.force_login(other_user)
        for name, pk in [('my_payment_detail', self.payment.pk), ('my_payment_print', self.payment.pk),
                         ('my_invoice_print', self.invoice.pk), ('my_invoice_detail', self.invoice.pk)]:
            self.assertEqual(self.client.get(self.url(name, pk)).status_code, 404)
        self.assertEqual(list(self.client.get(reverse('my_payments')).context['payments']), [])

    def test_same_room_new_contract_does_not_grant_access_to_previous_residents_receipts(self):
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save(update_fields=['status'])
        other = Tenant.objects.create(full_name='Người thuê sau', id_card_number='012345678998', phone='0901234567')
        new = Contract.objects.create(room=self.room, start_date=self.today, end_date=self.today+timedelta(days=365))
        ContractTenant.objects.create(contract=new, tenant=other, is_representative=True)
        other.refresh_from_db()
        self.client.force_login(other.user)
        self.assertEqual(self.client.get(self.url('my_payment_detail')).status_code, 404)
        self.assertEqual(self.client.get(self.url('my_invoice_print', self.invoice.pk)).status_code, 404)
        self.client.force_login(self.tenant.user)
        self.assertEqual(self.client.get(self.url('my_payment_detail')).status_code, 200)

    def test_gets_and_prints_are_read_only_and_prevent_private_response_caching(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.CHUA_THANH_TOAN)
        snapshot = (list(Payment.objects.values()), list(Invoice.objects.values()), list(PaymentNotice.objects.values()))
        for name, pk in [('my_payment_detail', self.payment.pk), ('my_payment_print', self.payment.pk),
                         ('my_invoice_print', self.invoice.pk), ('my_invoice_detail', self.invoice.pk)]:
            response = self.client.get(self.url(name, pk))
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(snapshot, (list(Payment.objects.values()), list(Invoice.objects.values()), list(PaymentNotice.objects.values())))

    def test_prints_use_stored_prices_and_owner_tenant_outputs_match(self):
        service = Service.objects.create(name='Giữ xe lúc lập', unit_price=70000)
        InvoiceService.objects.create(invoice=self.invoice, service=service, quantity=1)
        self.invoice.recalculate_total()
        service.name, service.unit_price = 'Tên mới không dùng', 99999
        service.save()
        url = self.url('my_invoice_print', self.invoice.pk)
        tenant_print = self.client.get(url)
        self.assertContains(tenant_print, 'Giữ xe lúc lập')
        self.assertContains(tenant_print, '70.000 đ')
        self.assertNotContains(tenant_print, service.name)
        self.client.force_login(self.owner)
        owner_print = self.client.get(self.url('invoice_print', self.invoice.pk))
        for field in ('paid', 'cash_paid', 'remaining', 'deposit_applied'):
            self.assertEqual(tenant_print.context[field], owner_print.context[field])
        owner_receipt = self.client.get(self.url('payment_print'))
        self.assertEqual(owner_receipt.context['code'], self.payment.display_code)

    def test_tenant_cannot_post_to_detail_or_print_or_use_owner_receipt_routes(self):
        for name, pk in [('my_payment_detail', self.payment.pk), ('my_payment_print', self.payment.pk),
                         ('my_invoice_print', self.invoice.pk)]:
            self.assertEqual(self.client.post(self.url(name, pk)).status_code, 405)
        for name, pk in [('payment_print', self.payment.pk), ('invoice_print', self.invoice.pk)]:
            self.assertEqual(self.client.get(self.url(name, pk)).status_code, 302)
        for user in (self.owner, User.objects.create_user('staff-only', is_staff=True), None):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for name in ('my_payment_detail', 'my_payment_print'):
                self.assertEqual(self.client.get(self.url(name)).status_code, 302)

    def test_notes_are_escaped_in_detail_and_both_prints(self):
        Payment.objects.filter(pk=self.payment.pk).update(note='<script>alert(1)</script>')
        Invoice.objects.filter(pk=self.invoice.pk).update(note='<script>alert(2)</script>')
        for name, pk in [('my_payment_detail', self.payment.pk), ('my_payment_print', self.payment.pk),
                         ('my_invoice_print', self.invoice.pk)]:
            response = self.client.get(self.url(name, pk))
            self.assertNotContains(response, '<script>alert(')
            self.assertContains(response, '&lt;script&gt;')


class PaymentRecordingMigrationTests(TransactionTestCase):
    def test_existing_payments_keep_unknown_time_and_new_payments_capture_time(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [node for node in latest if node[0] != 'billing'] + [('billing', '0012_checkout_settlement')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            room = apps.get_model('rooms', 'Room').objects.create(room_number='901', price=2500000)
            contract = apps.get_model('rooms', 'Contract').objects.create(room=room, start_date=date(2026, 1, 1), end_date=date(2027, 1, 1))
            invoice = apps.get_model('billing', 'Invoice').objects.create(contract=contract, month=1, year=2026,
                room_fee=2500000, total_amount=2500000, due_date=date(2026, 1, 10))
            payment = apps.get_model('billing', 'Payment').objects.create(invoice=invoice, amount=400000, paid_date=date(2026, 1, 5))
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            Payment = executor.loader.project_state(latest).apps.get_model('billing', 'Payment')
            migrated = Payment.objects.get(pk=payment.pk)
            self.assertEqual(migrated.amount, 400000)
            self.assertEqual(migrated.paid_date, date(2026, 1, 5))
            self.assertIsNone(migrated.recorded_at)
            self.assertIsNone(migrated.recorded_by_id)
            self.assertIsNone(migrated.voided_at)
            self.assertEqual(migrated.void_reason, '')
            self.assertIsNone(migrated.replaces_id)
            new = Payment.objects.create(invoice_id=invoice.pk, amount=100000)
            self.assertIsNotNone(new.recorded_at)
        finally:
            MigrationExecutor(connection).migrate(latest)
