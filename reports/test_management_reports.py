import csv
from datetime import datetime, time, timedelta
from io import BytesIO, StringIO

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.models import Tenant, User
from billing.models import Invoice, InvoiceDraft, InvoiceService, Payment, PaymentNotice, UtilityReading
from billing.services import void_payment
from rooms.models import CoOccupantRequest, Contract, ContractTenant, DepositEntry
from rooms.services import apply_deposit_to_invoice
from support.models import MaintenanceRequest
from support.tests import SupportBase
from .services import ReportPeriod, build_report, cashbook_rows


class ManagementReportTests(SupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.today = timezone.localdate()
        cls.previous = cls.today.replace(day=1) - timedelta(days=1)
        cls.period = ReportPeriod(cls.today.year, cls.today.month)
        cls.contract.start_date = cls.today - timedelta(days=400)
        cls.contract.deposit = 2000000
        cls.contract.save()
        ContractTenant.objects.filter(contract=cls.contract).update(is_representative=True)
        cls.other_contract = Contract.objects.create(room=cls.other_room, start_date=cls.today - timedelta(days=30),
            end_date=cls.today + timedelta(days=15), deposit=1000000)
        ContractTenant.objects.create(contract=cls.other_contract, tenant=cls.other_tenant, is_representative=True)
        cls.invoice = Invoice.objects.create(contract=cls.contract, month=cls.today.month, year=cls.today.year,
            room_fee=2500000, electric_fee=175000, water_fee=100000, water_billing_method='per_person',
            water_people_count=2, water_unit_price=50000, total_amount=2875000, due_date=cls.today + timedelta(days=5))
        InvoiceService.objects.create(invoice=cls.invoice, description='Wifi', unit_price=100000, quantity=1)
        cls.old_invoice = Invoice.objects.create(contract=cls.contract, month=cls.previous.month, year=cls.previous.year,
            room_fee=1000000, total_amount=1000000, due_date=cls.today - timedelta(days=10))
        Payment.objects.create(invoice=cls.invoice, amount=200000, paid_date=cls.previous)
        Payment.objects.create(invoice=cls.invoice, amount=300000, paid_date=cls.today, method='tien_mat')
        Payment.objects.create(invoice=cls.invoice, amount=100000, paid_date=cls.today, method='chuyen_khoan')
        Payment.objects.create(invoice=cls.old_invoice, amount=200000, paid_date=cls.today, method='chuyen_khoan')
        DepositEntry.objects.create(contract=cls.contract, kind='receive', amount=1000000, occurred_on=cls.previous)
        DepositEntry.objects.create(contract=cls.contract, kind='receive', amount=500000, occurred_on=cls.today)
        DepositEntry.objects.create(contract=cls.contract, kind='refund', amount=100000, occurred_on=cls.today)
        DepositEntry.objects.create(contract=cls.contract, kind='deduct', amount=50000, occurred_on=cls.today, method='internal')
        cls.offset = apply_deposit_to_invoice(cls.invoice, amount=150000, occurred_on=cls.today,
            note='Thỏa thuận đối trừ tiền cọc', created_by=cls.owner)
        DepositEntry.objects.create(contract=cls.contract, kind='transfer_out', amount=200000,
            occurred_on=cls.today, method='internal', related_contract=cls.other_contract)
        DepositEntry.objects.create(contract=cls.other_contract, kind='transfer_in', amount=200000,
            occurred_on=cls.today, method='internal', related_contract=cls.contract)
        cls.canceled = Payment.objects.create(invoice=cls.invoice, amount=50000, paid_date=cls.today)
        void_payment(cls.canceled, reason='Ghi trùng khoản thu', actor=cls.owner)
        PaymentNotice.objects.create(invoice=cls.invoice, tenant=cls.tenant, amount=99999)
        cls.draft = InvoiceDraft.objects.create(contract=cls.other_contract, month=cls.today.month, year=cls.today.year,
            room_fee=2500000, water_unit_price=50000, water_people_count=1)

    def setUp(self):
        self.client.force_login(self.owner)

    def context(self, **params):
        return self.client.get(reverse('report_dashboard'), {'year': self.today.year, 'month': self.today.month, **params}).context

    def test_receipts_offsets_deposits_and_pending_transfers_are_separate(self):
        context = self.context()
        self.assertEqual(context['cash_received'], 600000)
        self.assertEqual(context['cash_collected'], 300000)
        self.assertEqual(context['bank_collected'], 300000)
        self.assertEqual(context['deposit_applied'], 150000)
        self.assertEqual(context['year_total'], 750000)
        self.assertEqual(context['cash_in'], 1100000)
        self.assertEqual(context['cash_out'], 100000)
        self.assertEqual(context['months'][0]['total'], 750000)
        self.assertEqual(len(context['months']), 1)

    def test_invoice_period_is_distinct_from_payment_date_and_current_debt(self):
        context = self.context()
        self.assertEqual(context['invoice_total'], 2875000)
        self.assertEqual(context['invoice_count'], 1)
        self.assertEqual(context['invoice_paid'], 750000)
        self.assertEqual(context['invoice_remaining'], 2125000)
        self.assertEqual(context['invoice_room'] + context['invoice_electric'] + context['invoice_water'] + context['invoice_other'], context['invoice_total'])
        self.assertEqual(context['total_debt'], 2925000)
        self.assertEqual(context['overdue_debt'], 800000)
        self.assertEqual(context['period_draft_count'], 1)
        previous = self.context(year=self.previous.year, month=self.previous.month)
        self.assertEqual(previous['cash_received'], 200000)
        self.assertEqual(previous['invoice_total'], 1000000)
        self.assertEqual(previous['total_debt'], context['total_debt'])

    def test_chart_series_match_receipts_and_current_balances_for_selected_period(self):
        context = self.context()
        charts = context['charts']
        collections = charts['collections']
        self.assertTrue(collections['daily'])
        self.assertEqual(collections['observed_count'], self.today.day)
        self.assertEqual(collections['labels'][self.today.day - 1], f'{self.today.day}/{self.today.month}')
        self.assertEqual(collections['cash'][self.today.day - 1], 300000)
        self.assertEqual(collections['bank'][self.today.day - 1], 300000)
        # Canceled receipts, deposit receipts, offsets and unconfirmed transfers are excluded.
        self.assertEqual(sum(collections['cash']) + sum(collections['bank']), context['cash_received'])
        self.assertEqual(sum(row['value'] for row in charts['debt']), context['total_debt'])
        self.assertEqual(sum(row['count'] for row in charts['debt']), len(context['debts']))
        self.assertEqual(sum(row['value'] for row in charts['rooms']), context['room_stats']['total'])
        yearly = self.context(month=0)
        yearly_series = yearly['charts']['collections']
        self.assertFalse(yearly_series['daily'])
        self.assertEqual(yearly_series['observed_count'], self.today.month)
        self.assertEqual(len(yearly_series['labels']), 12)
        self.assertEqual(yearly_series['cash'], [int(row['cash']) for row in yearly['months']])
        self.assertEqual(yearly_series['bank'], [int(row['bank']) for row in yearly['months']])
        self.assertEqual(yearly['charts']['debt'], charts['debt'])
        self.assertEqual(yearly['charts']['rooms'], charts['rooms'])

    def test_chart_empty_period_has_all_days_in_leap_february_and_keeps_current_balances(self):
        report = build_report(ReportPeriod(2000, 2))
        series = report['charts']['collections']
        self.assertEqual(len(series['labels']), 29)
        self.assertEqual(series['labels'][-1], '29/2')
        self.assertEqual(series['cash'], [0] * 29)
        self.assertEqual(series['bank'], [0] * 29)
        self.assertGreater(sum(row['value'] for row in report['charts']['debt']), 0)
        self.assertGreater(sum(row['value'] for row in report['charts']['rooms']), 0)

    def test_floor_filter_scopes_receipts_invoices_balances_rooms_and_exports(self):
        self.room.floor = 0
        self.room.save(update_fields=['floor'])
        self.other_room.floor = 2
        self.other_room.save(update_fields=['floor'])
        other_invoice = Invoice.objects.create(contract=self.other_contract, month=self.today.month, year=self.today.year,
            room_fee=500000, total_amount=500000, due_date=self.today)
        Payment.objects.create(invoice=other_invoice, amount=100000, paid_date=self.today)
        self.make_request(title='Sửa phòng tầng 0')
        context = self.context(floor=0)
        self.assertEqual(context['cash_received'], 600000)
        self.assertEqual(context['invoice_total'], 2875000)
        self.assertEqual(context['total_debt'], 2925000)
        self.assertEqual(context['deposit_held'], 1000000)
        self.assertEqual(context['period_draft_count'], 0)
        self.assertEqual(context['room_stats']['total'], 1)
        self.assertEqual(context['repair_stats']['total'], 1)
        self.assertEqual({row['contract'].room.floor for row in context['cashbook']}, {0})
        self.assertEqual(context['period'].scope_label, 'Tầng 0')
        self.assertIn('floor=0', context['period'].query)
        params = {'year': self.today.year, 'month': self.today.month, 'floor': 0}
        exported = load_workbook(BytesIO(self.client.get(reverse('report_excel'), params).content))
        self.assertEqual(exported['Hóa đơn trong kỳ'].max_row, 2)
        self.assertEqual(exported['Phòng và hợp đồng'].max_row, 2)
        self.assertEqual(exported['Đối soát điện nước'].max_row, 2)
        self.assertContains(self.client.get(reverse('report_print'), params), 'Tầng 0')
        csv_rows = list(csv.reader(StringIO(self.client.get(reverse('cashbook_csv'), params).content.decode('utf-8-sig'))))
        self.assertEqual({row[4] for row in csv_rows[1:]}, {self.room.room_number})

    def test_utility_report_keeps_metered_and_per_person_water_separate_and_missing_values_unknown(self):
        reading = UtilityReading.objects.create(room=self.room, contract=self.contract, month=self.today.month, year=self.today.year,
            old_electric='100.2', new_electric='150.2')
        self.invoice.utility_reading = reading
        self.invoice.electric_unit_price = 3500
        self.invoice.save(update_fields=['utility_reading', 'electric_unit_price'])
        context = self.context()
        self.assertEqual(context['utility_totals']['electric'], 50)
        self.assertEqual(context['utility_totals']['people'], 2)
        self.assertEqual(context['utility_totals']['water'], 0)
        row = context['utility_rows'][0]
        self.assertTrue(row['electric_matches'])
        self.assertTrue(row['water_matches'])
        self.assertIsNone(row['water_usage'])
        previous_reading = UtilityReading.objects.create(room=self.room, contract=self.contract,
            month=self.previous.month, year=self.previous.year, old_electric=10, new_electric=10, old_water='3.5', new_water='5.5')
        Invoice.objects.filter(pk=self.old_invoice.pk).update(utility_reading=previous_reading, water_unit_price=15000, water_fee=30000)
        previous = self.context(year=self.previous.year, month=self.previous.month)
        self.assertEqual(previous['utility_totals']['electric'], 0)
        self.assertEqual(previous['utility_totals']['missing_electric'], 0)
        self.assertEqual(previous['utility_totals']['water'], 2)
        self.assertEqual(previous['utility_totals']['people'], 0)
        reading.delete()
        missing = self.context()
        self.assertIsNone(missing['utility_rows'][0]['electric_usage'])
        self.assertEqual(missing['utility_totals']['missing_electric'], 1)
        params = {'year': self.today.year, 'month': self.today.month}
        book = load_workbook(BytesIO(self.client.get(reverse('report_excel'), params).content))
        exported = next(book['Đối soát điện nước'].iter_rows(min_row=2, values_only=True))
        self.assertIsNone(exported[4])
        self.assertIsNone(exported[10])
        self.assertEqual(exported[11], 2)
        self.assertEqual(exported[13], 100000)

    def test_empty_floor_has_zero_figures_and_payment_labels_use_actual_balances(self):
        empty = self.context(floor=32767)
        self.assertEqual(empty['cash_received'], 0)
        self.assertEqual(empty['invoice_total'], 0)
        self.assertEqual(empty['total_debt'], 0)
        self.assertEqual(empty['room_stats']['total'], 0)
        self.assertEqual(empty['utility_rows'], [])
        Invoice.objects.filter(pk=self.invoice.pk).update(status=Invoice.Status.DA_THANH_TOAN)
        row = self.context()['issued'][0]
        self.assertEqual(row['payment_status'], Invoice.Status.THU_MOT_PHAN)
        self.assertEqual(row['payment_label'], 'Thu một phần')

    def test_deposit_opening_movements_and_closing_reconcile(self):
        context = self.context()
        dp = context['deposit_period']
        self.assertEqual(dp['opening'], 1000000)
        self.assertEqual(dp['receive'], 500000)
        self.assertEqual(dp['refund'], 100000)
        self.assertEqual(dp['deduct'], 50000)
        self.assertEqual(dp['pay_invoice'], 150000)
        self.assertEqual((dp['transfer_in'], dp['transfer_out']), (200000, 200000))
        self.assertEqual(dp['closing'], 1200000)
        self.assertEqual(dp['opening'] + dp['receive'] + dp['transfer_in'] - dp['refund'] - dp['deduct'] - dp['pay_invoice'] - dp['transfer_out'], dp['closing'])
        self.assertEqual(context['deposit_held'], 1200000)
        self.assertEqual(sum(r['held'] for r in context['deposit_contracts']), 1200000)
        previous = self.context(year=self.previous.year, month=self.previous.month)
        self.assertEqual(previous['deposit_period']['closing'], 1000000)
        self.assertEqual(previous['deposit_held'], 1200000)

    def test_linked_offset_has_balanced_internal_ledger_and_void_has_zero_money(self):
        rows = cashbook_rows(self.period)
        offsets = [r for r in rows if r['group'] == 'Đối trừ cọc vào hóa đơn']
        self.assertEqual(len(offsets), 1)
        self.assertEqual(offsets[0]['internal'], 150000)
        linked = [r for r in rows if r.get('linked_offset_ledger')]
        self.assertEqual(len(linked), 1)
        self.assertEqual(offsets[0]['internal'] + linked[0]['internal'], 0)
        self.assertEqual((linked[0]['cash_in'], linked[0]['cash_out']), (0, 0))
        canceled = next(r for r in rows if r['code'] == self.canceled.display_code)
        self.assertEqual((canceled['amount'], canceled['cash_in'], canceled['cash_out'], canceled['internal']), (0, 0, 0, 0))
        self.assertIn('Ghi trùng khoản thu', canceled['note'])
        self.assertEqual([(r['date'], r['sort']) for r in rows], sorted((r['date'], r['sort']) for r in rows))

    def test_debt_uses_actual_balance_even_when_status_cache_is_stale(self):
        Invoice.objects.filter(pk=self.old_invoice.pk).update(status=Invoice.Status.DA_THANH_TOAN)
        context = self.context()
        self.assertIn(self.old_invoice.pk, [r['invoice'].pk for r in context['debts']])
        overview = self.client.get(reverse('owner_dashboard'))
        self.assertGreaterEqual(overview.context['overdue_count'], 1)
        Payment.objects.create(invoice=self.old_invoice, amount=800000, paid_date=self.today)
        Invoice.objects.filter(pk=self.old_invoice.pk).update(status=Invoice.Status.CHUA_THANH_TOAN)
        self.assertNotIn(self.old_invoice.pk, [r['invoice'].pk for r in self.context()['debts']])

    def test_debt_aging_boundaries_and_ended_contract_debt_are_retained(self):
        before = self.context()
        for month, days in enumerate((0, 1, 7, 8, 30, 31, 60, 61), 1):
            Invoice.objects.create(contract=self.contract, month=month, year=self.today.year - 2,
                room_fee=100, total_amount=100, due_date=self.today - timedelta(days=days))
        context = self.context()
        self.assertEqual([r['amount'] - old['amount'] for r, old in zip(context['aging'], before['aging'])], [100, 200, 200, 200, 100])
        self.assertEqual(sum(r['amount'] for r in context['aging']), context['total_debt'])
        self.contract.status = Contract.Status.KET_THUC
        self.contract.checkout_date = self.today
        self.contract.save()
        context = self.context()
        self.assertEqual(context['ended_debt'], context['total_debt'])
        self.assertEqual(context['deposit_ended'], 1000000)
        ended = next(r for r in context['deposit_contracts'] if r['contract'].pk == self.contract.pk)
        self.assertEqual(ended['shortfall'], 0)
        self.assertGreater(ended['debt'], 0)

    def test_room_people_count_uses_approved_members_and_agreed_rent(self):
        self.contract.monthly_rent = 2300000
        self.contract.save()
        self.room.max_occupants = 4
        self.room.price = 3900000
        self.room.save()
        mate = Tenant.objects.create(full_name='Ở cùng đã duyệt', id_card_number='123456789001', phone='0901234567')
        ContractTenant.objects.create(contract=self.contract, tenant=mate)
        CoOccupantRequest.objects.create(contract=self.contract, submitted_by=self.tenant,
            full_name='Chờ duyệt', id_card_number='123456789002', phone='0901234567')
        context = self.context()
        self.assertEqual(context['people_count'], 3)
        row = next(r for r in context['room_rows'] if r['room'].pk == self.room.pk)
        self.assertEqual((row['people'], row['rent']), (2, 2300000))
        self.assertIn(self.other_contract.pk, [r['contract'].pk for r in context['expiring']])

    def test_repair_creation_and_completion_periods_are_not_confused(self):
        old = self.make_request(status='hoan_thanh', resolved_at=timezone.now())
        MaintenanceRequest.objects.filter(pk=old.pk).update(created_at=timezone.make_aware(datetime.combine(self.previous, time(10))))
        self.make_request(title='Yêu cầu mới')
        context = self.context()
        self.assertEqual(context['repair_stats']['total'], 1)
        self.assertEqual(context['repair_stats']['completed_in_period'], 1)
        self.assertEqual(context['repair_stats']['current_pending'], 1)
        self.assertIn(old.pk, [r.pk for r in context['repairs']])
        self.assertEqual(next(r.report_scope for r in context['repairs'] if r.pk == old.pk), 'Hoàn thành trong kỳ')

    def test_year_selector_includes_years_with_only_repair_activity(self):
        repair = self.make_request(status='hoan_thanh')
        year = self.today.year - 3
        moment = timezone.make_aware(datetime(year, 6, 1, 10))
        MaintenanceRequest.objects.filter(pk=repair.pk).update(created_at=moment, resolved_at=moment)
        self.assertIn(year, self.context()['years'])
        report = self.context(year=year, month=6)
        self.assertEqual(report['repair_stats']['total'], 1)
        self.assertEqual(report['repair_stats']['completed_in_period'], 1)

    def test_read_only_gets_do_not_refresh_invoice_status_or_change_ledgers(self):
        before = list(Invoice.objects.values()), Payment.objects.count(), DepositEntry.objects.count()
        params = {'year': self.today.year, 'month': self.today.month}
        with CaptureQueriesContext(connection) as queries:
            for name in ('report_dashboard', 'report_print', 'report_excel', 'cashbook_csv'):
                self.assertEqual(self.client.get(reverse(name), params).status_code, 200)
        writes = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))]
        self.assertEqual(writes, [])
        self.assertEqual(before, (list(Invoice.objects.values()), Payment.objects.count(), DepositEntry.objects.count()))

    def test_excel_has_real_numbers_dates_safe_text_and_matching_figures(self):
        self.room.room_number = '=1+1'
        self.room.save()
        self.make_request(title='=SUM(1,2)\x01')
        response = self.client.get(reverse('report_excel'), {'year': self.today.year, 'month': self.today.month})
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        book = load_workbook(BytesIO(response.content), data_only=False)
        self.assertEqual(len(book.worksheets), 9)
        summary = {r[0]: r[1] for r in book['Tổng hợp'].iter_rows(min_row=2, values_only=True)}
        self.assertEqual(summary['Tiền mới nhận thanh toán hóa đơn'], 600000)
        self.assertEqual(summary['Cọc cuối kỳ'], 1200000)
        self.assertEqual(summary['Tổng công nợ hiện tại'], 2925000)
        row = list(book['Hóa đơn trong kỳ'].iter_rows(min_row=2))[0]
        self.assertEqual(row[2].value, '=1+1')
        self.assertEqual(row[2].data_type, 's')
        self.assertIsInstance(row[9].value, (int, float))
        self.assertIsInstance(row[12].value, datetime)
        repair = list(book['Sửa chữa và tồn đọng'].iter_rows(min_row=2))[0]
        self.assertEqual(repair[3].value, '=SUM(1,2)')
        self.assertEqual(repair[3].data_type, 's')
        self.assertIsNotNone(book['Sổ thu và cọc'].auto_filter.ref)

    def test_csv_and_excel_same_selected_month_and_no_formula_execution(self):
        DepositEntry.objects.filter(kind='receive', occurred_on=self.today).update(note='=SUM(1,2)')
        response = self.client.get(reverse('cashbook_csv'), {'year': self.today.year, 'month': self.today.month})
        rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(sum(int(row[6]) for row in rows[1:]), 1100000)
        self.assertEqual(sum(int(row[7]) for row in rows[1:]), 100000)
        self.assertTrue(any(row[-1] == "'=SUM(1,2)" for row in rows[1:]))
        self.assertTrue(all(self.period.first <= datetime.fromisoformat(row[0]).date() <= self.period.last for row in rows[1:]))

    def test_print_and_screen_use_same_period_and_totals(self):
        params = {'year': self.today.year, 'month': self.today.month}
        screen = self.client.get(reverse('report_dashboard'), params)
        printed = self.client.get(reverse('report_print'), params)
        for name in ('cash_received', 'invoice_total', 'total_debt', 'deposit_held', 'deposit_period', 'repair_stats'):
            self.assertEqual(screen.context[name], printed.context[name])
        self.assertContains(printed, 'A4 landscape')
        self.assertContains(printed, 'gồm mọi kỳ chưa thanh toán đủ')
        self.assertNotContains(printed, 'app-sidebar')
        self.assertIn('no-store', printed['Cache-Control'])

    def test_invalid_period_is_visible_on_screen_and_rejected_for_exports(self):
        for params in ({'month': '13'}, {'month': '-1'}, {'month': 'abc'}, {'year': 'abc'}, {'year': '1999'},
                       {'floor': '-1'}, {'floor': 'abc'}, {'floor': '32768'}):
            with self.subTest(params=params):
                response = self.client.get(reverse('report_dashboard'), params)
                self.assertContains(response, 'Kỳ báo cáo không hợp lệ')
                for name in ('report_excel', 'report_print', 'cashbook_csv'):
                    self.assertEqual(self.client.get(reverse(name), params).status_code, 400)

    def test_reports_and_exports_require_owner_and_get(self):
        urls = [reverse(name) for name in ('report_dashboard', 'report_excel', 'report_print', 'cashbook_csv')]
        for url in urls:
            self.assertEqual(self.client.post(url).status_code, 405)
        self.owner.is_staff = False
        self.owner.save(update_fields=['is_staff'])
        self.assertEqual(self.client.get(reverse('report_excel')).status_code, 200)
        for account in (self.user, User.objects.create_user('staff-only', is_staff=True), None):
            self.client.force_login(account) if account else self.client.logout()
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_zero_data_exports_have_headers_and_no_division_errors(self):
        period = ReportPeriod(2000, 1)
        report = build_report(period)
        self.assertEqual(report['cash_received'], 0)
        self.assertEqual(report['invoice_total'], 0)
        self.assertEqual(report['months'][0]['pct'], 0)
        self.assertGreater(report['total_debt'], 0)  # Current balances must not masquerade as a 2000 snapshot.
        response = self.client.get(reverse('report_excel'), {'year': 2000, 'month': 1})
        book = load_workbook(BytesIO(response.content))
        self.assertEqual(book['Hóa đơn trong kỳ'].max_row, 1)
        self.assertEqual(book['Sổ thu và cọc'].max_row, 1)
