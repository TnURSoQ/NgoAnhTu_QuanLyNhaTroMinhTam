from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import Tenant, User
from rooms.models import Contract, ContractTenant
from . import services
from .models import BankAccount, Invoice, Payment, PaymentNotice
from .test_owner import BillingBase


class TransferBase(BillingBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tenant.refresh_from_db()
        cls.tenant_user = cls.tenant.user
        cls.invoice = services.create_invoice(
            room=cls.room, month=cls.today.month, year=cls.today.year,
            old_electric=100, new_electric=150, old_water=10, new_water=13)

    def configure_bank(self):
        return services.configure_bank_account(bank_name='Ngân hàng mẫu', account_number='00123456789',
                                                account_holder='NGUYEN THI MAI')


class BankAccountAndNoticeServiceTests(TransferBase):
    def test_transfer_content_uses_representative_normalized_uppercase(self):
        self.assertEqual(services.transfer_content(self.invoice),
                         f'P101 NGUYEN MINH ANH T{self.today.month}.{self.today.year}')
        self.tenant.full_name = '  Đặng   Thị Ánh  '
        self.tenant.save()
        self.assertEqual(services.transfer_content(self.invoice),
                         f'P101 DANG THI ANH T{self.today.month}.{self.today.year}')

    def test_bank_settings_update_single_record_and_preserve_leading_zeroes(self):
        account = self.configure_bank()
        self.assertEqual(account.account_number, '00123456789')
        services.configure_bank_account(bank_name='Ngân hàng khác', account_number='0000123',
                                         account_holder='TRAN VAN AN')
        self.assertEqual(BankAccount.objects.count(), 1)
        account.refresh_from_db()
        self.assertEqual(account.account_number, '0000123')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            BankAccount.objects.create(pk=2, bank_name='X', account_number='1', account_holder='Y')

    def test_invalid_bank_update_is_rolled_back(self):
        self.configure_bank()
        with self.assertRaises(ValidationError):
            services.configure_bank_account(bank_name=' ', account_number='123', account_holder='X')
        self.assertEqual(BankAccount.objects.get().bank_name, 'Ngân hàng mẫu')

    def test_notice_optional_amount_never_creates_payment_or_changes_debt(self):
        notice = services.report_payment(self.invoice, self.tenant, note='Đã chuyển lúc 10 giờ')
        self.assertIsNone(notice.amount)
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertIsNone(notice.processed_by)
        self.assertIsNone(notice.payment)
        self.assertFalse(Payment.objects.exists())
        self.assert_status(self.invoice, Invoice.Status.CHUA_THANH_TOAN)

    def test_notice_requires_membership_and_invoice_with_debt(self):
        other = Tenant.objects.create(full_name='Người khác', id_card_number='999999999999', phone='0901234567')
        with self.assertRaisesMessage(ValidationError, 'hóa đơn của mình'):
            services.report_payment(self.invoice, other)
        services.record_payment(self.invoice, amount=self.invoice.total_amount)
        with self.assertRaisesMessage(ValidationError, 'đã thu đủ'):
            services.report_payment(self.invoice, self.tenant)
        self.assertFalse(PaymentNotice.objects.exists())

    def test_duplicate_pending_notice_is_blocked_in_service_and_database(self):
        services.report_payment(self.invoice, self.tenant)
        with self.assertRaisesMessage(ValidationError, 'đang có thông báo'):
            services.report_payment(self.invoice, self.tenant)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PaymentNotice.objects.create(invoice=self.invoice, tenant=self.tenant)
        self.assertEqual(PaymentNotice.objects.count(), 1)

    def test_notice_rejects_invalid_claimed_amounts(self):
        for amount in [0, -1, Decimal('100000000'), Decimal('0.001')]:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                services.report_payment(self.invoice, self.tenant, amount=amount)
        self.assertFalse(PaymentNotice.objects.exists())

    def test_confirmation_creates_transfer_payment_and_records_processor(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=1000000)
        notice = services.confirm_payment_notice(notice, processed_by=self.owner, amount=900000,
                                                  paid_date=self.today, note='Đã đối chiếu')
        self.assertEqual(notice.status, PaymentNotice.Status.DA_XAC_NHAN)
        self.assertEqual(notice.processed_by, self.owner)
        self.assertIsNotNone(notice.processed_at)
        self.assertEqual(notice.amount, 1000000)
        self.assertEqual(notice.payment.amount, 900000)
        self.assertEqual(notice.payment.method, Payment.Method.CHUYEN_KHOAN)
        self.assertEqual(notice.payment.paid_date, self.today)
        self.assertEqual(notice.payment.note, 'Đã đối chiếu')
        self.assert_status(self.invoice, Invoice.Status.THU_MOT_PHAN)

    def test_confirmation_rechecks_remaining_after_other_collection(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=self.invoice.total_amount)
        services.record_payment(self.invoice, amount=1000000)
        with self.assertRaisesMessage(ValidationError, 'vượt quá số còn nợ'):
            services.confirm_payment_notice(notice, processed_by=self.owner, amount=self.invoice.total_amount)
        notice.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertIsNone(notice.payment)
        self.assertIsNone(notice.processed_at)
        self.assertEqual(Payment.objects.count(), 1)
        services.confirm_payment_notice(notice, processed_by=self.owner,
                                         amount=self.invoice.total_amount - 1000000)
        self.assert_status(self.invoice, Invoice.Status.DA_THANH_TOAN)

    def test_payment_and_notice_are_atomic_when_notice_save_fails(self):
        notice = services.report_payment(self.invoice, self.tenant)
        with patch.object(PaymentNotice, 'save', side_effect=ValidationError('Không lưu được.')):
            with self.assertRaises(ValidationError):
                services.confirm_payment_notice(notice, processed_by=self.owner, amount=1000000)
        notice.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertFalse(Payment.objects.exists())
        self.assert_status(self.invoice, Invoice.Status.CHUA_THANH_TOAN)

    def test_processed_notice_cannot_create_another_payment_or_be_rejected(self):
        notice = services.report_payment(self.invoice, self.tenant)
        services.confirm_payment_notice(notice, processed_by=self.owner, amount=1)
        for action in [lambda: services.confirm_payment_notice(notice, processed_by=self.owner, amount=1),
                       lambda: services.reject_payment_notice(notice, processed_by=self.owner, reject_reason='Sai')]:
            with self.assertRaisesMessage(ValidationError, 'đã được xử lý'):
                action()
        self.assertEqual(Payment.objects.count(), 1)

    def test_reject_requires_reason_and_allows_new_notice(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=1000000)
        with self.assertRaisesMessage(ValidationError, 'lý do từ chối'):
            services.reject_payment_notice(notice, processed_by=self.owner, reject_reason='  ')
        rejected = services.reject_payment_notice(notice, processed_by=self.owner,
                                                   reject_reason='  Chưa nhận được tiền  ')
        self.assertEqual(rejected.reject_reason, 'Chưa nhận được tiền')
        self.assertEqual(rejected.status, PaymentNotice.Status.TU_CHOI)
        self.assertEqual(rejected.processed_by, self.owner)
        self.assertIsNotNone(rejected.processed_at)
        self.assertIsNone(rejected.payment)
        again = services.report_payment(self.invoice, self.tenant)
        self.assertNotEqual(again.pk, rejected.pk)
        self.assertEqual(again.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertFalse(Payment.objects.exists())

    def test_only_owner_can_process_notice_even_when_service_called_directly(self):
        notice = services.report_payment(self.invoice, self.tenant)
        with self.assertRaisesMessage(ValidationError, 'Chỉ chủ trọ'):
            services.confirm_payment_notice(notice, processed_by=self.tenant_user, amount=1)
        with self.assertRaisesMessage(ValidationError, 'Chỉ chủ trọ'):
            services.reject_payment_notice(notice, processed_by=self.tenant_user, reject_reason='Sai')
        self.assertFalse(Payment.objects.exists())


class TenantRoomAndTransferViewTests(TransferBase):
    def setUp(self):
        self.client.force_login(self.tenant_user)

    def test_my_room_home_and_menu(self):
        home = self.client.get('/')
        self.assertTemplateUsed(home, 'public/home.html')
        self.assertContains(home, reverse('my_room'))
        self.assertEqual(reverse('my_room'), '/phong-cua-toi/')
        response = self.client.get(reverse('my_room'))
        for text in ['Phòng của tôi', 'Phòng 101', 'Đang ở', 'Cần thanh toán tháng',
                     '2.820.000 đ', '50 kWh x 3.500 đ', self.contract.display_code]:
            self.assertContains(response, text)
        self.assertEqual(response.context['unpaid_invoice'].pk, self.invoice.pk)
        self.assertEqual(response.context['latest_invoice'].pk, self.invoice.pk)

    def test_bank_missing_message_on_room_and_invoice(self):
        for url in [reverse('my_room'), reverse('my_invoice_detail', args=[self.invoice.pk])]:
            r = self.client.get(url)
            self.assertContains(r, 'Chủ trọ chưa cập nhật thông tin chuyển khoản')
            self.assertNotContains(r, 'Tôi đã chuyển khoản')

    def test_bank_content_and_copy_controls_on_both_pages(self):
        self.configure_bank()
        for url in [reverse('my_room'), reverse('my_invoice_detail', args=[self.invoice.pk])]:
            r = self.client.get(url)
            for text in ['Ngân hàng mẫu', '00123456789', 'NGUYEN THI MAI', 'Sao chép',
                         services.transfer_content(self.invoice), 'Tôi đã chuyển khoản']:
                self.assertContains(r, text)
            self.assertContains(r, 'data-copy-text=')

    def test_room_debt_is_latest_unpaid_and_accounts_for_partial_payments(self):
        self.contract.start_date = self.today.replace(year=self.today.year - 1, month=1, day=1)
        self.contract.save()
        older = self.create(month=1 if self.today.month != 1 else 2, year=self.today.year - 1)
        services.record_payment(self.invoice, amount=1000000)
        r = self.client.get(reverse('my_room'))
        self.assertEqual(r.context['unpaid_invoice'].pk, self.invoice.pk)
        self.assertContains(r, '1.820.000 đ')
        services.record_payment(self.invoice, amount=self.invoice.total_amount - 1000000)
        r = self.client.get(reverse('my_room'))
        self.assertEqual(r.context['unpaid_invoice'].pk, older.pk)
        self.assertEqual(r.context['latest_invoice'].pk, self.invoice.pk)
        self.assertEqual(r.context['transfer_invoice'].pk, older.pk)
        services.record_payment(older, amount=older.total_amount)
        self.assertContains(self.client.get(reverse('my_room')), 'Bạn đã thanh toán đủ')

    def test_departed_tenant_can_view_and_report_old_debt(self):
        Contract.objects.filter(pk=self.contract.pk).update(status=Contract.Status.KET_THUC)
        r = self.client.get(reverse('my_room'))
        self.assertContains(r, 'Bạn hiện không có hợp đồng hiệu lực')
        self.assertContains(r, 'Cần thanh toán tháng')
        self.assertIsNone(r.context['room'])
        r = self.client.post(reverse('report_transfer', args=[self.invoice.pk]), {})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(PaymentNotice.objects.count(), 1)

    def test_room_handles_no_contract_or_invoices(self):
        other_user = User.objects.create_user('empty-tenant', role='tenant')
        Tenant.objects.create(user=other_user, full_name='Chưa có phòng', id_card_number='888888888888',
                                phone='0901234567')
        self.client.force_login(other_user)
        r = self.client.get(reverse('my_room'))
        self.assertContains(r, 'Bạn hiện không có hợp đồng hiệu lực')
        self.assertContains(r, 'Chưa có hóa đơn nào')
        self.assertNotContains(r, 'Phòng 101')

    def test_report_flow_duplicate_and_latest_notice_status(self):
        self.configure_bank()
        url = reverse('report_transfer', args=[self.invoice.pk])
        r = self.client.post(url, {'amount': '1.000.000', 'note': 'Ngân hàng báo thành công'})
        self.assertRedirects(r, reverse('my_invoice_detail', args=[self.invoice.pk]))
        notice = PaymentNotice.objects.get()
        self.assertEqual(notice.amount, 1000000)
        self.assertEqual(notice.tenant, self.tenant)
        r = self.client.post(url, {})
        self.assertContains(r, 'đang có thông báo')
        self.assertEqual(PaymentNotice.objects.count(), 1)
        for page in [reverse('my_room'), reverse('my_invoice_detail', args=[self.invoice.pk])]:
            r = self.client.get(page)
            self.assertContains(r, 'Đang chờ chủ trọ xác nhận')
            self.assertNotContains(r, 'Tôi đã chuyển khoản')
        services.reject_payment_notice(notice, processed_by=self.owner, reject_reason='Chưa nhận được tiền')
        r = self.client.get(reverse('my_room'))
        self.assertContains(r, 'Bị từ chối:')
        self.assertContains(r, 'Chưa nhận được tiền')
        self.assertContains(r, 'Tôi đã chuyển khoản')
        self.client.post(url, {})
        latest = PaymentNotice.objects.first()
        self.assertNotEqual(latest.pk, notice.pk)
        services.confirm_payment_notice(latest, processed_by=self.owner, amount=self.invoice.total_amount)
        r = self.client.get(reverse('my_room'))
        self.assertContains(r, 'Đã xác nhận')
        self.assertContains(r, 'Bạn đã thanh toán đủ')
        self.assertNotContains(r, 'Tôi đã chuyển khoản')

    def test_invalid_amount_preserves_form_and_creates_nothing(self):
        self.configure_bank()
        r = self.client.post(reverse('report_transfer', args=[self.invoice.pk]),
                             {'amount': '-1', 'note': 'Ghi chú giữ lại'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['notice_form'].errors)
        self.assertContains(r, 'Ghi chú giữ lại')
        self.assertFalse(PaymentNotice.objects.exists())

    def test_report_paid_invoice_fails_and_get_cannot_create_notice(self):
        url = reverse('report_transfer', args=[self.invoice.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        services.record_payment(self.invoice, amount=self.invoice.total_amount)
        self.assertContains(self.client.post(url, {}), 'Hóa đơn đã thu đủ')
        self.assertFalse(PaymentNotice.objects.exists())

    def test_other_tenant_invoice_returns_404_on_get_and_post(self):
        other_user = User.objects.create_user('outsider', role='tenant')
        Tenant.objects.create(user=other_user, full_name='Người ngoài', id_card_number='777777777777',
                                phone='0901234567')
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(reverse('my_invoice_detail', args=[self.invoice.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('report_transfer', args=[self.invoice.pk]), {}).status_code, 404)
        self.assertFalse(PaymentNotice.objects.exists())

    def test_same_contract_other_tenant_cannot_submit_second_pending_notice(self):
        other_user = User.objects.create_user('roommate', role='tenant')
        other = Tenant.objects.create(user=other_user, full_name='Ở cùng', id_card_number='666666666666',
                                       phone='0901234567')
        ContractTenant.objects.create(contract=self.contract, tenant=other)
        services.report_payment(self.invoice, self.tenant)
        self.client.force_login(other_user)
        self.assertContains(self.client.post(reverse('report_transfer', args=[self.invoice.pk]), {}),
                             'đang có thông báo')
        self.assertEqual(PaymentNotice.objects.count(), 1)

    def test_anonymous_and_owner_cannot_access_tenant_routes(self):
        self.client.logout()
        for url in [reverse('my_room'), reverse('report_transfer', args=[self.invoice.pk])]:
            r = self.client.post(url, {})
            self.assertEqual(r.status_code, 302)
            self.assertIn('/dang-nhap/', r.url)
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('my_room')), reverse('home'), fetch_redirect_response=False)
        self.assertRedirects(self.client.post(reverse('report_transfer', args=[self.invoice.pk]), {}),
                             reverse('home'), fetch_redirect_response=False)


class OwnerNoticeViewTests(TransferBase):
    def setUp(self):
        self.client.force_login(self.owner)

    def test_owner_bank_form_saves_and_updates_existing_account(self):
        data = {'action': 'bank', 'bank_name': 'Ngân hàng mẫu', 'account_number': '00123',
                'account_holder': 'NGUYEN THI MAI'}
        self.assertRedirects(self.client.post(reverse('billing_settings'), data), reverse('billing_settings'))
        data['account_number'] = '00456'
        self.client.post(reverse('billing_settings'), data)
        self.assertEqual(BankAccount.objects.count(), 1)
        self.assertEqual(BankAccount.objects.get().account_number, '00456')
        response = self.client.get(reverse('billing_settings'))
        self.assertContains(response, 'Thông tin chuyển khoản')
        self.assertNotContains(response, 'href="/admin/')

    def test_notice_in_history_and_overview_with_link(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=1000000, note='Lần đầu')
        detail = reverse('invoice_detail', args=[self.invoice.pk])
        r = self.client.get(detail)
        for text in ['Chờ xác nhận', 'Lần đầu', reverse('payment_notice_confirm', args=[notice.pk]),
                     reverse('payment_notice_reject', args=[notice.pk])]:
            self.assertContains(r, text)
        self.assertNotContains(r, 'href="/admin/')
        r = self.client.get(reverse('owner_dashboard'))
        task = next(t for t in r.context['tasks'] if t['title'] == 'Chuyển khoản chờ xác nhận')
        self.assertEqual(task['url'], detail)
        self.assertEqual(task['amount'], 1000000)
        self.assertIn(self.tenant.full_name, task['subtitle'])
        self.assertContains(r, '1.000.000 đ')

    def test_confirm_form_prefills_claimed_or_remaining_amount_and_creates_payment(self):
        for declared in [Decimal('1000000'), None]:
            notice = services.report_payment(self.invoice, self.tenant, amount=declared)
            url = reverse('payment_notice_confirm', args=[notice.pk])
            r = self.client.get(url)
            remaining = self.invoice.total_amount - self.invoice.total_paid()
            self.assertEqual(r.context['form'].initial['amount'], declared if declared is not None else remaining)
            self.assertTrue(r.context['form'].fields['method'].disabled)
            self.assertNotContains(r, 'href="/admin/')
            self.assertFalse(Payment.objects.filter(payment_notice=notice).exists())
            r = self.client.post(url, {'amount': '500.000', 'paid_date': self.today,
                                      'method': 'tien_mat', 'note': 'Đã nhận'})
            self.assertRedirects(r, reverse('invoice_detail', args=[self.invoice.pk]))
            notice.refresh_from_db()
            self.assertEqual(notice.payment.amount, 500000)
            self.assertEqual(notice.payment.method, Payment.Method.CHUYEN_KHOAN)
        self.assert_status(self.invoice, Invoice.Status.THU_MOT_PHAN)

    def test_cannot_confirm_more_than_remaining_or_process_twice(self):
        notice = services.report_payment(self.invoice, self.tenant, amount=self.invoice.total_amount + 100)
        url = reverse('payment_notice_confirm', args=[notice.pk])
        r = self.client.post(url, {'amount': '9.000.000', 'paid_date': self.today})
        self.assertContains(r, 'vượt quá số còn nợ')
        self.assertFalse(Payment.objects.exists())
        r = self.client.post(url, {'amount': '1000000', 'paid_date': self.today})
        self.assertEqual(r.status_code, 302)
        self.client.post(url, {'amount': '1000000', 'paid_date': self.today})
        self.assertEqual(Payment.objects.count(), 1)

    def test_reject_form_requires_reason_and_retains_history(self):
        notice = services.report_payment(self.invoice, self.tenant)
        url = reverse('payment_notice_reject', args=[notice.pk])
        self.assertNotContains(self.client.get(url), 'href="/admin/')
        r = self.client.post(url, {'reject_reason': ' '})
        self.assertContains(r, 'Vui lòng nhập lý do từ chối')
        notice.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertRedirects(self.client.post(url, {'reject_reason': 'Sai tài khoản nhận'}),
                             reverse('invoice_detail', args=[self.invoice.pk]))
        notice.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.TU_CHOI)
        self.assertFalse(Payment.objects.exists())
        self.assertContains(self.client.get(reverse('invoice_detail', args=[self.invoice.pk])),
                             'Sai tài khoản nhận')

    def test_voiding_confirmed_payment_keeps_notice_link_and_allows_reporting_again(self):
        notice = services.report_payment(self.invoice, self.tenant)
        notice = services.confirm_payment_notice(notice, processed_by=self.owner, amount=1000000)
        services.void_payment(notice.payment, actor=self.owner, reason='Đối chiếu lại, khoản thu bị ghi nhận nhầm')
        notice.refresh_from_db()
        self.assertTrue(notice.payment.is_voided)
        self.assertEqual(notice.status, PaymentNotice.Status.DA_XAC_NHAN)
        self.assertContains(self.client.get(reverse('invoice_detail', args=[self.invoice.pk])),
                             'đã hủy và không còn tính vào thanh toán.')
        services.report_payment(self.invoice, self.tenant)
        self.assertEqual(PaymentNotice.objects.count(), 2)

    def test_tenant_and_anonymous_cannot_process_notice_or_configure_bank(self):
        notice = services.report_payment(self.invoice, self.tenant)
        urls = [reverse('payment_notice_confirm', args=[notice.pk]),
                reverse('payment_notice_reject', args=[notice.pk]), reverse('billing_settings')]
        self.client.logout()
        for url in urls:
            for method in ['get', 'post']:
                r = getattr(self.client, method)(url)
                self.assertEqual(r.status_code, 302)
                self.assertIn('/dang-nhap/', r.url)
        self.client.force_login(self.tenant_user)
        for url in urls:
            for method in ['get', 'post']:
                self.assertRedirects(getattr(self.client, method)(url, {'amount': 1, 'reject_reason': 'X'}),
                                     reverse('home'), fetch_redirect_response=False)
        notice.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(BankAccount.objects.exists())
