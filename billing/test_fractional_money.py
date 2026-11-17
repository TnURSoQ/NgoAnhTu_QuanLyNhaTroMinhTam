from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.form_fields import MoneyField
from accounts.money import whole_dong
from rooms.models import Room
from . import services
from .models import Invoice, PaymentNotice, UtilityRate
from .test_owner import BillingBase


class WholeDongPaymentTests(BillingBase):
    def setUp(self):
        self.invoice = self.create(room_fee=Decimal('1900227'))
        self.assertEqual(self.invoice.total_amount, Decimal('2220227'))
        self.notice = services.report_payment(self.invoice, self.tenant, amount=Decimal('2220227'))
        self.client.force_login(self.owner)

    def test_confirmation_accepts_exact_whole_dong_and_rejects_overpayment(self):
        url = reverse('payment_notice_confirm', args=[self.notice.pk])
        self.assertContains(self.client.get(url), '2.220.227 đ')
        response = self.client.post(url, {'amount': '2.220.228', 'paid_date': self.today})
        self.assertContains(response, 'Số tiền vượt quá số còn nợ (2.220.227đ).')
        self.assertFalse(self.invoice.payments.exists())
        response = self.client.post(url, {'amount': '2.220.227', 'paid_date': self.today})
        self.assertRedirects(response, reverse('invoice_detail', args=[self.invoice.pk]))
        self.assertEqual(self.invoice.payments.get().amount, Decimal('2220227'))
        self.assert_status(self.invoice, Invoice.Status.DA_THANH_TOAN)

    def test_owner_and_tenant_pages_display_whole_dong(self):
        for url in [reverse('invoice_list'), reverse('invoice_detail', args=[self.invoice.pk]),
                    reverse('owner_dashboard'), reverse('report_dashboard'),
                    reverse('contract_detail', args=[self.contract.pk])]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '2.220.227')
                self.assertNotContains(response, '2.220.227,')
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        for url in [reverse('my_room'), reverse('my_invoices'),
                    reverse('my_invoice_detail', args=[self.invoice.pk])]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '2.220.227')
                self.assertNotContains(response, '2.220.227,')

    def test_collection_default_and_fractional_input_rejected(self):
        response = self.client.get(reverse('invoice_detail', args=[self.invoice.pk]))
        self.assertContains(response, 'value="2.220.227"')
        url = reverse('payment_notice_confirm', args=[self.notice.pk])
        response = self.client.post(url, {'amount': '2.220.227,50', 'paid_date': self.today})
        self.assertContains(response, 'Vui lòng nhập số tiền nguyên đồng')
        self.assertFalse(self.invoice.payments.exists())
        self.notice.refresh_from_db()
        self.assertEqual(self.notice.status, PaymentNotice.Status.CHO_XAC_NHAN)

    def test_fractional_readings_produce_truncated_integer_fees(self):
        UtilityRate.objects.filter(pk=self.rate.pk).update(electric_price=3501, water_price=15001)
        invoice = self.create(month=1 if self.today.month != 1 else 2,
                              old_electric=0, new_electric=Decimal('0.50'),
                              old_water=0, new_water=Decimal('0.25'))
        self.assertEqual(invoice.electric_fee, 1750)
        self.assertEqual(invoice.water_fee, 3750)
        self.assertEqual(invoice.total_amount, 2605500)
        self.assertEqual(invoice.utility_reading.new_electric, Decimal('0.50'))

    def test_service_rejects_fractional_money(self):
        for action in [
            lambda: services.record_payment(self.invoice, amount=Decimal('1.50')),
            lambda: services.report_payment(self.invoice, self.tenant, amount=Decimal('1.50')),
            lambda: services.save_service(name='Rác', unit_price=Decimal('1.50')),
            lambda: services.add_utility_rate(electric_price=Decimal('3500.50'), water_price=15000,
                                              effective_date=self.today),
            lambda: self.create(month=1 if self.today.month != 1 else 2, room_fee=Decimal('2000000.50')),
        ]:
            with self.assertRaises(ValidationError):
                action()

    def test_model_storage_never_keeps_fractional_dong(self):
        room = Room.objects.create(room_number='whole', price=Decimal('2220227.99'))
        self.assertEqual(room.price, 2220227)
        room.refresh_from_db()
        self.assertEqual(room.price, 2220227)
        Room.objects.filter(pk=room.pk).update(price=Decimal('2220227.50'))
        room.refresh_from_db()
        self.assertEqual(room.price, 2220227)
        self.assertEqual(whole_dong(Decimal('2220227.99')), 2220227)
        self.assertEqual(MoneyField().decimal_places, 0)
