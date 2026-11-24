import csv
from datetime import timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from rooms.models import DepositEntry
from rooms.services import apply_deposit_to_invoice, unpaid_invoices
from . import services
from .admin import InvoiceAdmin, PaymentInline
from .models import Invoice, Payment, PaymentNotice
from .receipts import invoice_statement
from .test_owner import BillingBase


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PaymentCorrectionTests(BillingBase):
    def setUp(self):
        self.invoice = self.create()
        self.payment = services.record_payment(self.invoice, amount=1000000, recorded_by=self.owner, note='Giao dịch gốc')
        self.tenant.refresh_from_db()
        self.client.force_login(self.owner)
        self.url = reverse('payment_correct', args=[self.payment.pk])

    def void(self, **changes):
        return services.void_payment(self.payment, **{'actor': self.owner, 'reason': 'Nhập nhầm khoản thu', **changes})

    def adjust(self, **changes):
        return services.adjust_payment(self.payment, **{'amount': 600000, 'paid_date': self.today,
            'method': 'chuyen_khoan', 'note': 'Đã kiểm tra số đúng', 'actor': self.owner,
            'reason': 'Điều chỉnh theo đối chiếu', **changes})

    def test_void_preserves_original_and_logs_actor_time_reason(self):
        original = {name: getattr(self.payment, name) for name in ('amount', 'method', 'note', 'paid_date', 'recorded_at', 'recorded_by_id')}
        before = timezone.now()
        result = self.void()
        self.payment.refresh_from_db()
        self.assertEqual(Payment.objects.count(), 1)
        self.assertTrue(self.payment.is_voided)
        self.assertEqual(self.payment.voided_by, self.owner)
        self.assertGreaterEqual(self.payment.voided_at, before)
        self.assertEqual(self.payment.void_reason, 'Nhập nhầm khoản thu')
        self.assertEqual(result.pk, self.payment.pk)
        self.assertEqual(original, {name: getattr(self.payment, name) for name in original})
        self.assertEqual(self.invoice.total_paid(), 0)
        self.assertEqual(Payment.objects.active().count(), 0)
        self.assertEqual(DepositEntry.objects.count(), 0)

    def test_adjust_creates_linked_replacement_and_only_counts_new_amount(self):
        replacement = self.adjust()
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_voided)
        self.assertEqual(self.payment.amount, 1000000)
        self.assertEqual(self.payment.note, 'Giao dịch gốc')
        self.assertEqual(replacement.replaces, self.payment)
        self.assertEqual(self.payment.replacement, replacement)
        self.assertNotEqual(replacement.display_code, self.payment.display_code)
        self.assertEqual(replacement.recorded_by, self.owner)
        self.assertFalse(replacement.is_voided)
        self.assertEqual(replacement.amount, 600000)
        self.assertEqual(self.invoice.total_paid(), 600000)
        self.assertEqual(Payment.objects.count(), 2)

    def test_adjustment_chain_keeps_each_original(self):
        second = self.adjust()
        third = services.adjust_payment(second, amount=700000, paid_date=self.today, method='tien_mat',
            note='Số tiền sau đối chiếu lần hai', actor=self.owner, reason='Sửa phương thức và số tiền')
        self.assertEqual(Payment.objects.count(), 3)
        self.assertEqual(Payment.objects.active().count(), 1)
        self.assertEqual(third.replaces_id, second.pk)
        self.assertEqual(self.invoice.total_paid(), 700000)

    def test_invalid_adjustment_rolls_back_void_and_new_payment_together(self):
        for changes in ({'amount': self.invoice.total_amount+1}, {'amount': 0}, {'method': 'tu_coc'},
                        {'paid_date': self.today+timedelta(days=1)},
                        {'amount': self.payment.amount, 'paid_date': self.payment.paid_date,
                         'method': self.payment.method, 'note': self.payment.note}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.adjust(**changes)
            self.payment.refresh_from_db()
            self.assertFalse(self.payment.is_voided)
            self.assertEqual(self.payment.void_reason, '')
            self.assertEqual(self.invoice.total_paid(), 1000000)
            self.assertEqual(Payment.objects.count(), 1)

    def test_blank_long_reason_and_non_owner_cannot_change_money(self):
        for changes in ({'reason': ''}, {'reason': '  '}, {'reason': 'x'*1001}, {'actor': self.tenant.user}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.void(**changes)
        self.assertEqual(self.invoice.total_paid(), 1000000)

    def test_repeated_void_or_adjust_does_not_overwrite_audit_or_create_more_payments(self):
        replacement = self.adjust()
        self.payment.refresh_from_db()
        original_audit = (self.payment.voided_at, self.payment.void_reason, self.payment.voided_by_id)
        for operation in (self.void, self.adjust):
            with self.assertRaises(ValidationError):
                operation(reason='Lần gửi lại')
        self.payment.refresh_from_db()
        self.assertEqual(original_audit, (self.payment.voided_at, self.payment.void_reason, self.payment.voided_by_id))
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(self.invoice.total_paid(), replacement.amount)

    def test_direct_edit_and_hard_delete_are_blocked(self):
        for name, value in [('amount', 123), ('note', 'Đổi không qua điều chỉnh'), ('method', 'chuyen_khoan'),
                            ('recorded_at', None), ('paid_date', self.today-timedelta(days=1))]:
            payment = Payment.objects.get(pk=self.payment.pk)
            setattr(payment, name, value)
            with self.subTest(name=name), self.assertRaises(ValidationError):
                payment.save()
        for operation in (self.payment.delete, lambda: Payment.objects.filter(pk=self.payment.pk).delete(),
                          lambda: services.delete_payment(self.payment)):
            with self.assertRaises(ValidationError), transaction.atomic():
                operation()
        self.assertEqual(Payment.objects.count(), 1)

    def test_void_audit_constraint_and_owner_deletion_protect_history(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.filter(pk=self.payment.pk).update(voided_at=timezone.now())
        self.void()
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_deposit_offset_cannot_be_corrected_independently(self):
        DepositEntry.objects.create(contract=self.contract, kind='receive', amount=1000000, occurred_on=self.today)
        entry = apply_deposit_to_invoice(self.invoice, amount=200000, note='Đối trừ theo thỏa thuận', created_by=self.owner)
        for operation in (
            lambda: services.void_payment(entry.payment, actor=self.owner, reason='Sai'),
            lambda: services.adjust_payment(entry.payment, actor=self.owner, reason='Sai', amount=100000,
                paid_date=self.today, method='tien_mat')):
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(self.contract.deposit_balance, 800000)
        self.assertEqual(self.invoice.total_paid(), 1200000)

    def test_void_reopens_paid_invoice_and_changes_all_visible_balances(self):
        services.record_payment(self.invoice, amount=self.invoice.total_amount-1000000)
        self.void()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.THU_MOT_PHAN)
        self.assertEqual(unpaid_invoices(self.contract)[0][1], 1000000)
        self.assertEqual(invoice_statement(self.invoice)['remaining'], 1000000)
        owner = self.client.get(reverse('invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(owner.context['remaining'], 1000000)
        tenant_detail = self.client.get(reverse('tenant_detail', args=[self.tenant.pk]))
        self.assertEqual(tenant_detail.context['debt'], 1000000)
        self.client.force_login(self.tenant.user)
        self.assertEqual(self.client.get(reverse('my_invoices')).context['total_debt'], 1000000)
        self.assertEqual(self.client.get(reverse('my_room')).context['latest_invoice'].remaining, 1000000)

    def test_reports_and_csv_keep_void_audit_without_counting_money_twice(self):
        replacement = self.adjust()
        response = self.client.get(reverse('report_dashboard'), {'year': self.today.year})
        self.assertEqual(response.context['year_total'], replacement.amount)
        self.assertEqual(response.context['cash_received'], replacement.amount)
        self.assertEqual(response.context['total_debt'], self.invoice.total_amount-replacement.amount)
        csv_response = self.client.get(reverse('cashbook_csv'), {'year': self.today.year})
        rows = list(csv.reader(StringIO(csv_response.content.decode('utf-8-sig'))))
        canceled = next(row for row in rows[1:] if row[2] == self.payment.display_code)
        self.assertEqual(canceled[5:9], ['0', '0', '0', '0'])
        self.assertIn('Điều chỉnh theo đối chiếu', canceled[-1])
        self.assertEqual(sum(int(row[6]) for row in rows[1:]), replacement.amount)

    def test_adjusting_collection_date_moves_money_to_correct_report_period(self):
        previous = self.today.replace(day=1)-timedelta(days=1)
        replacement = self.adjust(paid_date=previous)
        report = self.client.get(reverse('report_dashboard'), {'year': previous.year})
        self.assertEqual(report.context['months'][previous.month-1]['total'], replacement.amount)
        if previous.year == self.today.year:
            self.assertEqual(report.context['months'][self.today.month-1]['total'], 0)

    def test_confirmed_transfer_keeps_original_notice_link_and_can_be_reported_again(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=300000)
        notice = services.confirm_payment_notice(notice, processed_by=self.owner, amount=300000)
        services.void_payment(notice.payment, actor=self.owner, reason='Đối chiếu lại khoản bị ghi trùng')
        notice.refresh_from_db()
        self.assertIsNotNone(notice.payment_id)
        self.assertEqual(notice.status, PaymentNotice.Status.DA_XAC_NHAN)
        self.assertTrue(notice.payment.is_voided)
        self.client.force_login(self.tenant.user)
        page = self.client.get(reverse('my_invoice_detail', args=[self.invoice.pk]))
        self.assertContains(page, 'Khoản thu đã hủy ghi nhận')
        self.assertTrue(page.context['can_report_transfer'])
        services.report_payment(self.invoice, self.tenant, amount=300000)
        self.assertEqual(PaymentNotice.objects.count(), 2)

    def test_tenant_history_detail_and_reprinted_receipt_make_void_clear(self):
        replacement = self.adjust()
        self.client.force_login(self.tenant.user)
        history = self.client.get(reverse('my_payments'))
        self.assertContains(history, 'payment-row-voided')
        self.assertEqual(history.context['payments'].count(), 2)
        detail = self.client.get(reverse('my_payment_detail', args=[self.payment.pk]))
        self.assertContains(detail, 'Điều chỉnh theo đối chiếu')
        self.assertContains(detail, reverse('my_payment_detail', args=[replacement.pk]))
        receipt = self.client.get(reverse('my_payment_print', args=[self.payment.pk]))
        self.assertContains(receipt, 'LỊCH SỬ GIAO DỊCH ĐÃ HỦY')
        self.assertContains(receipt, 'không xác nhận khoản thanh toán còn hiệu lực')
        self.assertNotContains(receipt, 'PHIẾU XÁC NHẬN THANH TOÁN')
        invoice_print = self.client.get(reverse('my_invoice_print', args=[self.invoice.pk]))
        self.assertEqual(invoice_print.context['paid'], 600000)
        self.assertContains(invoice_print, 'Đã hủy · Không tính vào thanh toán')

    def test_correction_page_requires_reason_and_can_void_or_adjust(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        invalid = self.client.post(self.url, {'action': 'void'})
        self.assertEqual(invalid.status_code, 200)
        self.assertIn('reason', invalid.context['form'].errors)
        response = self.client.post(self.url, {'action': 'adjust', 'reason': 'Sửa số tiền', 'amount': '600.000',
            'paid_date': self.today, 'method': 'chuyen_khoan', 'note': 'Đúng sau đối chiếu'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.invoice.total_paid(), 600000)
        self.assertContains(self.client.get(self.url), 'Giao dịch đã hủy')
        self.assertNotContains(self.client.get(self.url), 'data-payment-correction')
        count = Payment.objects.count()
        self.client.post(self.url, {'action': 'adjust', 'reason': 'Gửi lặp', 'amount': '700000',
            'paid_date': self.today, 'method': 'tien_mat'})
        self.assertEqual(Payment.objects.count(), count)

    def test_legacy_delete_url_cannot_silently_remove_payment(self):
        url = reverse('payment_delete', args=[self.payment.pk])
        self.client.post(url)
        self.assertEqual(self.invoice.total_paid(), 1000000)
        self.client.post(url, {'action': 'void', 'reason': 'Sửa nhầm', 'amount': 'malformed ignored'})
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_voided)
        self.assertEqual(Payment.objects.count(), 1)

    def test_security_csrf_get_read_only_and_malicious_audit_fields_are_ignored(self):
        snapshot = list(Payment.objects.values())
        self.client.get(self.url)
        self.assertEqual(snapshot, list(Payment.objects.values()))
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(self.url, {'action': 'void', 'reason': 'Sai'}).status_code, 403)
        self.client.force_login(self.tenant.user)
        self.assertEqual(self.client.post(self.url, {'action': 'void', 'reason': 'Sai'}).status_code, 302)
        self.client.force_login(self.owner)
        self.client.post(self.url, {'action': 'void', 'reason': 'Nhập nhầm',
            'voided_by': self.tenant.user_id, 'voided_at': '2000-01-01T00:00', 'invoice': 999999})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.voided_by, self.owner)
        self.assertEqual(self.payment.voided_at.date(), timezone.now().date())
        self.assertEqual(self.payment.invoice_id, self.invoice.pk)

    def test_void_reason_is_escaped_on_owner_tenant_and_print(self):
        self.void(reason='<script>alert(1)</script>')
        pages = [self.client.get(self.url)]
        self.client.force_login(self.tenant.user)
        pages += [self.client.get(reverse(name, args=[self.payment.pk])) for name in ('my_payment_detail', 'my_payment_print')]
        for page in pages:
            self.assertContains(page, '&lt;script&gt;')
            self.assertNotContains(page, '<script>alert(')

    def test_admin_payment_inline_has_no_write_or_delete_actions(self):
        from django.contrib import admin
        from django.test import RequestFactory
        inline = PaymentInline(Invoice, admin.site)
        request = RequestFactory().get('/')
        request.user = self.owner
        self.assertFalse(inline.has_add_permission(request, self.invoice))
        self.assertFalse(inline.has_change_permission(request, self.invoice))
        self.assertFalse(inline.has_delete_permission(request, self.invoice))

    def test_tenant_gets_private_unread_notification_and_read_target_is_original_transaction(self):
        from support.notifications import unread_count
        from support.models import NotificationRead
        self.adjust()
        self.assertEqual(unread_count(self.tenant.user), 1)
        self.client.force_login(self.tenant.user)
        response = self.client.get(reverse('my_notifications_panel'))
        item = next(item for item in response.context['notifications'] if item['notification_kind'] == 'payment_correction')
        self.assertIn('điều chỉnh', item['title'])
        self.assertEqual(item['url'], reverse('my_payment_detail', args=[self.payment.pk]))
        result = self.client.post(reverse('notification_mark_read'), {'token': item['read_token']})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['unread_count'], 0)
        self.assertEqual(NotificationRead.objects.filter(kind='payment_correction').count(), 1)
        outsider = User.objects.create_user('outside-payment', role='tenant')
        Tenant.objects.create(user=outsider, full_name='Người không liên quan', id_card_number='012345678909', phone='0901234567')
        self.assertEqual(unread_count(outsider), 0)
        self.client.force_login(outsider)
        self.assertNotEqual(self.client.post(reverse('notification_mark_read'), {'token': item['read_token']}).status_code, 200)

    def test_failed_adjustment_leaves_no_payment_notification(self):
        from support.notifications import unread_count
        with self.assertRaises(ValidationError):
            self.adjust(amount=self.invoice.total_amount+1)
        self.assertEqual(unread_count(self.tenant.user), 0)
