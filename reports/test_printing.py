from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice, Payment
from rooms.models import CheckoutRecord, Contract, ContractTenant, DepositEntry
from rooms.services import apply_deposit_to_invoice
from support.tests import SupportBase


class PrintingTests(SupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        today = timezone.localdate()
        cls.contract.deposit = 1000000
        cls.contract.save()
        cls.invoice = Invoice.objects.create(contract=cls.contract, month=today.month, year=today.year,
            room_fee=2500000, total_amount=2500000, due_date=today + timedelta(days=10))
        cls.payment = Payment.objects.create(invoice=cls.invoice, amount=300000, note='Thu đợt đầu')
        cls.deposit = DepositEntry.objects.create(contract=cls.contract, kind='receive', amount=1000000,
                                                  occurred_on=today, note='Đã nhận cọc thực tế')

    def setUp(self):
        self.client.force_login(self.owner)

    def test_contract_print_uses_agreed_rent_and_all_people_without_invented_initial_readings(self):
        self.room.price = 3900000
        self.room.save()
        ContractTenant.objects.create(contract=self.contract, tenant=self.other_tenant)
        response = self.client.get(reverse('contract_print', args=[self.contract.pk]))
        self.assertContains(response, '2.500.000 đ/tháng')
        self.assertNotContains(response, '3.900.000 đ/tháng')
        self.assertContains(response, self.tenant.full_name)
        self.assertContains(response, self.other_tenant.full_name)
        self.assertContains(response, 'Chưa ghi nhận')
        self.assertNotContains(response, 'app-sidebar')
        self.assertContains(response, 'In / Lưu PDF')

    def test_payment_receipt_prints_actual_partial_payment_and_is_read_only(self):
        before = (Payment.objects.count(), DepositEntry.objects.count(), CheckoutRecord.objects.count())
        response = self.client.get(reverse('payment_print', args=[self.payment.pk]))
        self.assertContains(response, '300.000 đ')
        self.assertContains(response, 'Thu đợt đầu')
        self.assertNotContains(response, '2.500.000 đ')
        self.assertEqual(before, (Payment.objects.count(), DepositEntry.objects.count(), CheckoutRecord.objects.count()))
        self.assertContains(self.client.get(reverse('invoice_detail', args=[self.invoice.pk])),
                            reverse('payment_print', args=[self.payment.pk]))

    def test_deposit_and_offset_prints_separate_cash_from_internal_movement(self):
        entry = apply_deposit_to_invoice(self.invoice, amount=200000, occurred_on=timezone.localdate(),
                                         note='Người thuê đồng ý đối trừ', created_by=self.owner)
        for route, pk in [('deposit_print', entry.pk), ('payment_print', entry.payment_id)]:
            response = self.client.get(reverse(route, args=[pk]))
            self.assertContains(response, '200.000 đ')
            self.assertContains(response, 'không phải khoản tiền mặt/chuyển khoản mới thu vào')
        receipt = self.client.get(reverse('deposit_print', args=[self.deposit.pk]))
        self.assertContains(receipt, 'PHIẾU THU TIỀN CỌC')
        self.assertNotContains(receipt, 'không phải khoản tiền mặt/chuyển khoản mới thu vào')

    def test_checkout_print_requires_actual_record_and_keeps_refund_estimate_distinct(self):
        url = reverse('checkout_print', args=[self.contract.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        CheckoutRecord.objects.create(contract=self.contract, checkout_date=timezone.localdate(),
            deposit_held=1000000, deposit_deducted=0, deposit_refunded=0, debt_at_checkout=2200000,
            drafts_at_checkout=1, refund_due_at_checkout=None, note='Chờ chốt nước', room_condition='trong')
        response = self.client.get(url)
        self.assertContains(response, 'Chờ chốt nước')
        self.assertContains(response, 'không xác nhận đã trả tiền')
        self.assertContains(response, 'Chưa xác định')
        self.assertFalse(DepositEntry.objects.filter(kind='refund').exists())

    def test_resident_roster_includes_cooccupants_and_excludes_ended_contract(self):
        ContractTenant.objects.create(contract=self.contract, tenant=self.other_tenant)
        response = self.client.get(reverse('residents_print'))
        self.assertContains(response, self.other_tenant.full_name)
        self.assertContains(response, self.tenant.full_name)
        self.assertContains(response, 'A4 landscape')
        self.assertContains(response, 'ngày vào ở thực tế')
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        response = self.client.get(reverse('residents_print'))
        self.assertNotContains(response, self.tenant.full_name)
        self.assertNotContains(response, self.other_tenant.full_name)

    def test_annual_report_matches_existing_report_and_keeps_deposit_out_of_cash_revenue(self):
        apply_deposit_to_invoice(self.invoice, amount=200000, note='Đối trừ theo thỏa thuận', created_by=self.owner)
        year = timezone.localdate().year
        report = self.client.get(reverse('report_print'), {'year': year})
        screen = self.client.get(reverse('report_dashboard'), {'year': year})
        self.assertEqual(report.context['year_total'], Decimal(500000))
        self.assertEqual(report.context['cash_received'], Decimal(300000))
        self.assertEqual(report.context['deposit_applied'], Decimal(200000))
        self.assertEqual(report.context['deposit_held'], Decimal(800000))
        self.assertEqual(report.context['total_debt'], screen.context['total_debt'])
        self.assertContains(report, 'gồm mọi kỳ chưa thanh toán đủ')

    def test_rooms_and_repair_print_escape_content_and_expose_entry_actions(self):
        repair = self.make_request(description='<script>alert(1)</script>')
        response = self.client.get(reverse('maintenance_print', args=[repair.pk]))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, 'Chưa hoàn thành')
        self.assertContains(self.client.get(reverse('maintenance_detail', args=[repair.pk])),
                            reverse('maintenance_print', args=[repair.pk]))
        response = self.client.get(reverse('rooms_print'))
        self.assertEqual(response.context['rooms'].get(pk=self.room.pk).people_count, 1)
        self.assertContains(response, self.other_room.room_number)
        self.assertContains(self.client.get(reverse('room_list')), reverse('rooms_print'))
        self.assertContains(self.client.get(reverse('tenant_list')), reverse('residents_print'))

    def test_all_print_views_require_owner_without_relying_on_admin_permissions(self):
        repair = self.make_request()
        targets = [('contract_print', [self.contract.pk]), ('payment_print', [self.payment.pk]),
                   ('deposit_print', [self.deposit.pk]), ('checkout_print', [self.contract.pk]),
                   ('residents_print', []), ('rooms_print', []), ('report_print', []), ('maintenance_print', [repair.pk])]
        for route, args in targets:
            url = reverse(route, args=args)
            self.assertEqual(self.client.post(url).status_code, 405)
        self.owner.is_staff = False
        self.owner.save(update_fields=['is_staff'])
        self.assertEqual(self.client.get(reverse('contract_print', args=[self.contract.pk])).status_code, 200)
        for account in [self.user, User.objects.create_user('print-staff', is_staff=True), None]:
            if account:
                self.client.force_login(account)
            else:
                self.client.logout()
            for route, args in targets:
                self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 302, route)
