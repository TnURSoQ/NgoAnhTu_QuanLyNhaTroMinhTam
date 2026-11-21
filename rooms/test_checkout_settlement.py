from datetime import timedelta
from decimal import Decimal
from io import StringIO
import csv
import uuid
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse

from accounts.models import Tenant
from billing import drafts
from billing import services as billing
from billing.forms import PaymentForm
from billing.models import Invoice, InvoiceDraft, Payment
from billing.test_owner import BillingBase
from . import services
from .models import CheckoutRecord, Contract, DepositEntry, Room


class CheckoutSettlementTests(BillingBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contract.deposit = 2000000
        cls.contract.initial_electric = 100
        cls.contract.initial_water = 10
        cls.contract.save()

    def receive(self, amount=2000000):
        return services.receive_deposit(self.contract, amount=amount)

    def invoice(self):
        # 780.000 tiền phòng + 175.000 điện + 45.000 nước = 1.000.000.
        return self.create(room_fee=780000, service_items=[])

    def target(self):
        return Room.objects.create(room_number='201', price=2800000, max_occupants=3)

    def test_handover_with_debt_requires_acknowledgement_and_keeps_old_debt(self):
        invoice = self.invoice()
        self.receive()
        with self.assertRaises(ValidationError):
            services.checkout_contract(self.contract, self.today)
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        self.contract.refresh_from_db()
        self.room.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.KET_THUC)
        self.assertEqual(self.room.status, Room.Status.TRONG)
        self.assertEqual(invoice.total_paid(), 0)
        self.assertEqual(services.unpaid_invoices(self.contract)[0][1], 1000000)
        self.assertEqual(self.contract.deposit_balance, 2000000)
        record = CheckoutRecord.objects.get()
        self.assertEqual(record.debt_at_checkout, 1000000)
        self.assertEqual(record.refund_due_at_checkout, 1000000)
        self.assertEqual(record.deposit_refunded, 0)

    def test_checkout_does_not_refund_until_actual_payment_is_recorded(self):
        self.receive(1500000)
        services.checkout_contract(self.contract, self.today)
        self.assertFalse(DepositEntry.objects.filter(kind='refund').exists())
        first = services.refund_deposit(self.contract, amount=500000, method='bank', reference=uuid.uuid4())
        self.assertEqual(first.method, 'bank')
        self.assertEqual(self.contract.deposit_balance, 1000000)
        self.assertEqual(services.settlement_summary(self.contract)['refunded'], 500000)
        self.contract.refresh_from_db()
        self.assertFalse(services.settlement_summary(self.contract)['settled'])
        services.refund_deposit(self.contract, amount=1000000)
        self.assertTrue(services.settlement_summary(self.contract)['settled'])
        self.assertEqual(CheckoutRecord.objects.get().deposit_refunded, 0)

    def test_refund_keeps_enough_deposit_for_unpaid_invoices(self):
        invoice = self.invoice()
        self.receive()
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        with self.assertRaises(ValidationError):
            services.refund_deposit(self.contract, amount=1000001)
        services.refund_deposit(self.contract, amount=1000000)
        with self.assertRaises(ValidationError):
            services.refund_deposit(self.contract, amount=1)
        billing.record_payment(invoice, amount=1000000)
        services.refund_deposit(self.contract, amount=1000000)
        self.assertEqual(self.contract.deposit_balance, 0)
        self.assertEqual(invoice.total_paid(), 1000000)

    def test_pending_old_draft_can_be_finalized_after_room_has_new_tenant(self):
        self.receive()
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        old_draft = InvoiceDraft.objects.get(contract=self.contract)
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        record = CheckoutRecord.objects.get()
        self.assertEqual(record.drafts_at_checkout, 1)
        self.assertIsNone(record.refund_due_at_checkout)
        with self.assertRaisesMessage(ValidationError, 'hóa đơn nháp'):
            services.refund_deposit(self.contract, amount=1)
        other = Tenant.objects.create(full_name='Khách mới', id_card_number='919191919191', phone='0901234568')
        new = services.create_contract(self.room, [other], other, self.today,
                                       self.today + timedelta(days=365), 0,
                                       initial_electric=500, initial_water=30)
        self.assertEqual(drafts.generate_monthly_drafts(self.today.month, self.today.year), 1)
        drafts.fill_missing_defaults(old_draft)
        row = {name: getattr(old_draft, name) for name in drafts.EDITABLE_FIELDS}
        row.update(draft=old_draft, revision=old_draft.revision, preview_token=old_draft.preview_token,
                   selected=True, new_electric=150, new_water=13)
        self.assertEqual(drafts.save_draft_rows([row], month=self.today.month, year=self.today.year, publish=True), (1, 0))
        invoice = Invoice.objects.get(contract=self.contract)
        self.assertEqual(invoice.utility_reading.old_electric, 100)
        self.assertEqual(invoice.utility_reading.new_electric, 150)
        self.assertEqual(invoice.contract_id, self.contract.pk)
        self.assertTrue(InvoiceDraft.objects.filter(contract=new, invoice__isnull=True).exists())
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('invoice_drafts')), new.display_code)

    def test_apply_deposit_updates_payment_and_ledger_atomically(self):
        invoice = self.invoice()
        self.receive()
        entry = services.apply_deposit_to_invoice(invoice, amount=600000, note='Đã thống nhất trừ nợ tháng này')
        self.assertEqual(entry.kind, DepositEntry.Kind.PAY_INVOICE)
        self.assertEqual(entry.payment.method, Payment.Method.TU_COC)
        self.assertEqual(invoice.total_paid(), 600000)
        self.assertEqual(self.contract.deposit_balance, 1400000)
        self.assertEqual(services.settlement_summary(self.contract)['debt'], 400000)
        with self.assertRaises(ValidationError):
            billing.delete_payment(entry.payment)
        with self.assertRaises(ProtectedError):
            entry.payment.delete()

    def test_failed_ledger_write_rolls_back_deposit_payment_and_status(self):
        invoice = self.invoice()
        self.receive()
        with patch('rooms.services.DepositEntry.objects.create', side_effect=ValidationError('Failed ledger')):
            with self.assertRaises(ValidationError):
                services.apply_deposit_to_invoice(invoice, amount=500000, note='Thống nhất đối trừ')
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.contract.deposit_balance, 2000000)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.CHUA_THANH_TOAN)

    def test_application_cannot_exceed_deposit_or_invoice_remaining(self):
        invoice = self.invoice()
        self.receive(500000)
        with self.assertRaises(ValidationError):
            services.apply_deposit_to_invoice(invoice, amount=500001, note='Thống nhất đối trừ')
        services.receive_deposit(self.contract, amount=1500000)
        with self.assertRaises(ValidationError):
            services.apply_deposit_to_invoice(invoice, amount=1000001, note='Thống nhất đối trừ')
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.contract.deposit_balance, 2000000)

    def test_normal_collection_cannot_bypass_deposit_ledger(self):
        invoice = self.invoice()
        with self.assertRaises(ValidationError):
            billing.record_payment(invoice, amount=1, method=Payment.Method.TU_COC)
        payment = Payment(invoice=invoice, amount=1, paid_date=self.today, method=Payment.Method.TU_COC)
        with self.assertRaises(ValidationError):
            payment.full_clean()
        self.assertNotIn(Payment.Method.TU_COC, dict(PaymentForm().fields['method'].choices))

    def test_same_reference_cannot_refund_or_apply_twice(self):
        invoice = self.invoice()
        self.receive()
        reference = uuid.uuid4()
        entry = services.apply_deposit_to_invoice(invoice, amount=500000, note='Đối trừ', reference=reference)
        self.assertEqual(services.apply_deposit_to_invoice(invoice, amount=500000, note='Đối trừ', reference=reference).pk, entry.pk)
        with self.assertRaises(ValidationError):
            services.apply_deposit_to_invoice(invoice, amount=500001, note='Đối trừ', reference=reference)
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        refund_ref = uuid.uuid4()
        refund = services.refund_deposit(self.contract, amount=1000000, reference=refund_ref)
        self.assertEqual(services.refund_deposit(self.contract, amount=1000000, reference=refund_ref).pk, refund.pk)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(DepositEntry.objects.filter(kind='refund').count(), 1)

    def test_stale_deposit_balance_blocks_refund_and_application(self):
        invoice = self.invoice()
        self.receive()
        with self.assertRaisesMessage(ValidationError, 'Số dư cọc đã thay đổi'):
            services.apply_deposit_to_invoice(invoice, amount=1, note='Đối trừ', expected_deposit_balance=0)
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        with self.assertRaisesMessage(ValidationError, 'Số dư cọc đã thay đổi'):
            services.refund_deposit(self.contract, amount=1, expected_deposit_balance=0)
        self.assertFalse(Payment.objects.exists())

    def test_refund_requires_closed_contract_real_date_and_supported_method(self):
        self.receive()
        with self.assertRaises(ValidationError):
            services.refund_deposit(self.contract, amount=1)
        services.checkout_contract(self.contract, self.today)
        for values in [{'occurred_on': self.today + timedelta(days=1)},
                       {'occurred_on': self.today - timedelta(days=1)}, {'method': 'internal'},
                       {'amount': 0}, {'amount': Decimal('0.5')}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                services.refund_deposit(self.contract, **{'amount': 1, **values})
        self.assertFalse(DepositEntry.objects.filter(kind='refund').exists())

    def test_transfer_with_debt_keeps_reserved_deposit_on_old_contract(self):
        invoice = self.invoice()
        self.receive()
        new = services.transfer_contract(self.contract, self.target(), self.today, self.contract.end_date,
                                          accept_outstanding=True, transfer_deposit=True)
        self.assertEqual(new.deposit_balance, 1000000)
        self.assertEqual(self.contract.deposit_balance, 1000000)
        self.assertEqual(invoice.contract_id, self.contract.pk)
        self.assertEqual(invoice.total_paid(), 0)

    def test_transfer_with_pending_fees_does_not_move_unknown_surplus(self):
        self.receive()
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        new = services.transfer_contract(self.contract, self.target(), self.today, self.contract.end_date,
                                          accept_outstanding=True, transfer_deposit=True)
        self.assertEqual(new.deposit_balance, 0)
        self.assertEqual(self.contract.deposit_balance, 2000000)
        self.assertFalse(DepositEntry.objects.filter(kind='transfer_out').exists())

    def test_cashbook_and_report_do_not_count_deposit_application_as_new_cash(self):
        invoice = self.invoice()
        self.receive()
        services.apply_deposit_to_invoice(invoice, amount=600000, note='Đối trừ')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('report_dashboard'))
        self.assertEqual(response.context['year_total'], 600000)
        self.assertEqual(response.context['cash_received'], 0)
        self.assertEqual(response.context['deposit_applied'], 600000)
        self.assertEqual(response.context['deposit_held'], 1400000)
        response = self.client.get(reverse('cashbook_csv'), {'year': self.today.year})
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(sum(int(row[6]) for row in rows[1:]), 2000000)
        self.assertEqual(sum(int(row[7]) for row in rows[1:]), 0)
        self.assertEqual(sum(int(row[8]) for row in rows[1:]), 0)

    def test_checkout_view_requires_outstanding_ack_but_allows_handover(self):
        invoice = self.invoice()
        self.client.force_login(self.owner)
        url = reverse('contract_checkout', args=[self.contract.pk])
        self.assertContains(self.client.get(url), 'Xác nhận trả phòng')
        self.client.post(url, {'checkout_date': self.today})
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.HIEU_LUC)
        self.assertEqual(self.client.post(url, {'checkout_date': self.today, 'accept_outstanding': 'on'}).status_code, 302)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.KET_THUC)
        self.assertEqual(invoice.total_paid(), 0)

    def test_refund_view_requires_confirmation_of_actual_payment(self):
        self.receive()
        services.checkout_contract(self.contract, self.today)
        self.client.force_login(self.owner)
        url = reverse('contract_deposit_refund', args=[self.contract.pk])
        data = {'amount': '500.000', 'occurred_on': self.today, 'method': 'bank', 'note': '',
                'expected_deposit_balance': '2000000', 'reference': str(uuid.uuid4())}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertFalse(DepositEntry.objects.filter(kind='refund').exists())
        data['confirm_refund'] = 'on'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.contract.deposit_balance, 1500000)
        self.assertContains(self.client.get(reverse('owner_dashboard')), 'Cọc còn giữ sau bàn giao')

    def test_application_view_validates_confirmation_and_hides_independent_delete(self):
        invoice = self.invoice()
        self.receive()
        self.client.force_login(self.owner)
        url = reverse('contract_deposit_apply', args=[self.contract.pk, invoice.pk])
        data = {'amount': '500.000', 'occurred_on': self.today, 'note': 'Thống nhất đối trừ',
                'reference': str(uuid.uuid4()), 'expected_deposit_balance': '2000000'}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        data['confirm_application'] = 'on'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        payment = Payment.objects.get()
        response = self.client.get(reverse('invoice_detail', args=[invoice.pk]))
        self.assertNotContains(response, f'href="{reverse("payment_delete", args=[payment.pk])}"')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Payment.objects.count(), 1)

    def test_tenant_and_missing_csrf_cannot_refund_or_apply_deposit(self):
        invoice = self.invoice()
        self.receive()
        services.checkout_contract(self.contract, self.today, accept_outstanding=True)
        urls = [reverse('contract_deposit_refund', args=[self.contract.pk]),
                reverse('contract_deposit_apply', args=[self.contract.pk, invoice.pk])]
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url, {}).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in urls:
            self.assertEqual(client.post(url, {}).status_code, 403)
        self.assertFalse(Payment.objects.exists())
