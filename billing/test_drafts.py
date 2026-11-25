from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from rooms.models import Contract, Room
from . import drafts, services
from .models import Invoice, InvoiceDraft, Payment, Service, UtilityRate, UtilityReading
from .test_owner import BillingBase


class DraftBase(BillingBase):
    def generate(self):
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        return InvoiceDraft.objects.get(contract=self.contract)

    def row(self, draft, **changes):
        draft.refresh_from_db()
        drafts.fill_missing_defaults(draft)
        values = {name: getattr(draft, name) for name in drafts.EDITABLE_FIELDS}
        return {'draft': draft, 'revision': draft.revision, 'preview_token': draft.preview_token,
                'selected': True, **values, **changes}

    def save(self, *rows, publish=False):
        return drafts.save_draft_rows(list(rows), month=self.today.month, year=self.today.year,
                                     publish=publish)

    def complete_row(self, draft, **changes):
        return self.row(draft, old_electric=100, new_electric=150, old_water=10,
                        new_water=13, **changes)


class MonthlyDraftServiceTests(DraftBase):
    def test_generation_idempotent_and_preserves_saved_values(self):
        draft = self.generate()
        self.save(self.row(draft, old_electric=100, new_electric=120))
        self.assertEqual(drafts.generate_monthly_drafts(self.today.month, self.today.year), 0)
        draft.refresh_from_db()
        self.assertEqual(draft.new_electric, 120)
        self.assertIsNone(draft.new_water)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(UtilityReading.objects.exists())

    def test_carries_previous_year_and_keeps_initial_readings_blank(self):
        draft = self.generate()
        self.assertIsNone(draft.old_electric)
        previous = date(self.today.year, self.today.month, 1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=0, new_electric=1250, old_water=0, new_water=85)
        drafts.fill_missing_defaults(draft)
        self.assertEqual(draft.old_electric, 1250)
        self.assertEqual(draft.old_water, 85)
        self.assertIsNone(draft.new_electric)
        self.assertIsNone(draft.new_water)

    def test_excludes_future_ended_and_outside_period_contracts(self):
        first = date(self.today.year, self.today.month, 1)
        for number, start, end, status in [
            ('201', first + timedelta(days=40), first + timedelta(days=400), Contract.Status.HIEU_LUC),
            ('202', first - timedelta(days=100), first - timedelta(days=1), Contract.Status.HIEU_LUC),
            ('203', first - timedelta(days=10), first + timedelta(days=30), Contract.Status.KET_THUC),
        ]:
            room = Room.objects.create(room_number=number, price=2000000)
            Contract.objects.create(room=room, start_date=start, end_date=end, status=status)
        self.assertEqual(drafts.generate_monthly_drafts(self.today.month, self.today.year), 1)
        self.assertEqual(InvoiceDraft.objects.get().contract_id, self.contract.pk)

    def test_skips_existing_published_invoice(self):
        self.create()
        self.assertEqual(drafts.generate_monthly_drafts(self.today.month, self.today.year), 0)
        self.assertFalse(InvoiceDraft.objects.exists())

    def test_dry_run_and_command_validation(self):
        out = StringIO()
        call_command('generate_monthly_invoice_drafts', dry_run=True, stdout=out)
        self.assertIn('1', out.getvalue())
        self.assertFalse(InvoiceDraft.objects.exists())
        call_command('generate_monthly_invoice_drafts', stdout=StringIO())
        call_command('generate_monthly_invoice_drafts', stdout=StringIO())
        self.assertEqual(InvoiceDraft.objects.count(), 1)
        for options in [{'month': 1}, {'year': 2026}, {'month': 13, 'year': 2026}]:
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command('generate_monthly_invoice_drafts', **options)
        next_month = (self.today.replace(day=1) + timedelta(days=32)).replace(day=1)
        with self.assertRaisesMessage(ValidationError, 'Chưa đến kỳ'):
            drafts.generate_monthly_drafts(next_month.month, next_month.year)

    def test_partial_selected_row_stays_draft(self):
        draft = self.generate()
        published, skipped = self.save(self.row(draft, old_electric=0, new_electric=15), publish=True)
        self.assertEqual((published, skipped), (0, 1))
        draft.refresh_from_db()
        self.assertEqual(draft.new_electric, 15)
        self.assertIsNone(draft.new_water)
        self.assertFalse(Invoice.objects.exists())

    def test_zero_usage_is_complete_and_due_date_begins_when_published(self):
        draft = self.generate()
        self.assertEqual(self.save(self.row(draft, old_electric=0, new_electric=0,
                                           old_water=0, new_water=0), publish=True), (1, 0))
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.electric_fee, 0)
        self.assertEqual(invoice.water_fee, 0)
        self.assertEqual(invoice.total_amount, 2600000)
        self.assertEqual(invoice.due_date, self.today + timedelta(days=10))
        draft.refresh_from_db()
        self.assertEqual(draft.invoice_id, invoice.pk)
        self.assertEqual(invoice.status, Invoice.Status.CHUA_THANH_TOAN)

    def test_publication_keeps_price_and_service_snapshots(self):
        draft = self.generate()
        UtilityRate.objects.create(water_billing_method='metered', electric_price=9000, water_price=50000, effective_date=self.today)
        self.room.price = 9000000
        self.room.save()
        self.wifi.unit_price = 500000
        self.wifi.name = 'Tên mới'
        self.wifi.save()
        self.save(self.complete_row(draft), publish=True)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.total_amount, 2820000)
        self.assertEqual(invoice.electric_unit_price, 3500)
        self.assertEqual(invoice.water_unit_price, 15000)
        self.assertEqual(invoice.room_fee, 2500000)
        line = invoice.invoice_services.get()
        self.assertEqual(line.unit_price, 100000)
        self.assertEqual(line.description, 'Wifi')

    def test_deleted_service_still_bills_snapshot(self):
        draft = self.generate()
        self.wifi.delete()
        self.save(self.complete_row(draft), publish=True)
        line = Invoice.objects.get().invoice_services.get()
        self.assertIsNone(line.service_id)
        self.assertEqual(line.description, 'Wifi')
        self.assertEqual(line.subtotal, 100000)

    def test_missing_rates_block_publish_until_configured(self):
        UtilityRate.objects.all().delete()
        draft = self.generate()
        self.assertEqual(self.save(self.complete_row(draft), publish=True), (0, 1))
        UtilityRate.objects.create(water_billing_method='metered', electric_price=4000, water_price=20000, effective_date=self.today)
        self.assertEqual(self.save(self.row(draft), publish=True), (1, 0))
        self.assertEqual(Invoice.objects.get().electric_unit_price, 4000)

    def test_decreasing_readings_and_excessive_fees_are_rejected(self):
        draft = self.generate()
        for fields in [dict(old_electric=100, new_electric=99),
                       dict(old_water=20, new_water=19),
                       dict(old_electric=0, new_electric=99999999)]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.save(self.row(draft, **fields))
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 0)
        self.assertIsNone(draft.new_electric)

    def test_fractional_usage_truncates_to_whole_dong(self):
        draft = self.generate()
        self.save(self.row(draft, old_electric=0, new_electric=Decimal('0.01'),
                           old_water=0, new_water=Decimal('0.01')), publish=True)
        self.assertEqual(Invoice.objects.get().electric_fee, 35)
        self.assertEqual(Invoice.objects.get().water_fee, 150)

    def test_other_period_and_duplicate_rows_rejected(self):
        draft = self.generate()
        row = self.complete_row(draft)
        with self.assertRaises(ValidationError):
            self.save(row, row, publish=True)
        prior = self.today.replace(day=1) - timedelta(days=1)
        with self.assertRaises(ValidationError):
            drafts.save_draft_rows([row], month=prior.month, year=prior.year, publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_stale_edit_and_duplicate_publication_rejected(self):
        draft = self.generate()
        stale = self.complete_row(draft)
        self.save(self.row(draft, old_electric=100, new_electric=160))
        with self.assertRaisesMessage(ValidationError, 'phiên khác'):
            self.save(stale)
        self.save(self.complete_row(draft), publish=True)
        with self.assertRaises(ValidationError):
            self.save(self.complete_row(draft), publish=True)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(UtilityReading.objects.count(), 1)

    def test_manual_creation_closes_matching_draft(self):
        draft = self.generate()
        invoice = self.create()
        draft.refresh_from_db()
        self.assertEqual(draft.invoice_id, invoice.pk)
        with self.assertRaises(ValidationError):
            self.save(self.complete_row(draft), publish=True)

    def test_ended_contract_does_not_bill_new_occupant(self):
        draft = self.generate()
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        Contract.objects.create(room=self.room, start_date=self.today,
                                end_date=self.today + timedelta(days=365))
        with self.assertRaisesMessage(ValidationError, 'đã kết thúc'):
            self.save(self.complete_row(draft), publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_batch_rolls_back_if_later_row_invalid(self):
        draft = self.generate()
        room = Room.objects.create(room_number='102', price=2000000)
        contract = Contract.objects.create(room=room, start_date=self.today,
                                           end_date=self.today + timedelta(days=365))
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        second = InvoiceDraft.objects.get(contract=contract)
        with self.assertRaises(ValidationError):
            self.save(self.complete_row(draft), self.row(second, old_water=10, new_water=9), publish=True)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(UtilityReading.objects.exists())
        draft.refresh_from_db()
        self.assertEqual(draft.revision, 0)

    def test_only_selected_ready_rows_publish(self):
        draft = self.generate()
        self.save({**self.complete_row(draft), 'selected': False})
        with self.assertRaisesMessage(ValidationError, 'ít nhất một phòng'):
            self.save(self.row(draft, selected=False), publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_late_previous_reading_refreshes_baseline_and_stale_page_is_rejected(self):
        draft = self.generate()
        stale = self.complete_row(draft)
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=0, new_electric=125, old_water=0, new_water=12)
        with self.assertRaisesMessage(ValidationError, 'Chỉ số kỳ trước'):
            self.save(stale, publish=True)
        # Dù dòng gửi chỉ số cũ khác, máy chủ luôn nối tiếp kỳ trước.
        self.save(self.complete_row(draft), publish=True)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.utility_reading.old_electric, 125)
        self.assertEqual(invoice.utility_reading.old_water, 12)
        self.assertEqual(invoice.electric_fee, 87500)
        self.assertEqual(invoice.water_fee, 15000)

    def test_new_rate_after_page_open_requires_recheck(self):
        UtilityRate.objects.all().delete()
        draft = self.generate()
        stale = self.complete_row(draft)
        UtilityRate.objects.create(water_billing_method='metered', electric_price=4000, water_price=20000, effective_date=self.today)
        with self.assertRaisesMessage(ValidationError, 'đã thay đổi'):
            self.save(stale, publish=True)
        self.assertFalse(Invoice.objects.exists())

    def test_batch_publishes_ready_and_keeps_incomplete_selected_room(self):
        draft = self.generate()
        room = Room.objects.create(room_number='102', price=2000000)
        contract = Contract.objects.create(room=room, start_date=self.today,
                                           end_date=self.today + timedelta(days=365))
        drafts.generate_monthly_drafts(self.today.month, self.today.year)
        second = InvoiceDraft.objects.get(contract=contract)
        due_date = self.today + timedelta(days=20)
        self.assertEqual(self.save(self.complete_row(draft, due_date=due_date), self.row(second),
                                   publish=True), (1, 1))
        self.assertEqual(Invoice.objects.get().due_date, due_date)
        second.refresh_from_db()
        self.assertIsNone(second.invoice_id)
        self.assertEqual(second.revision, 1)


class MonthlyDraftViewTests(DraftBase):
    def setUp(self):
        self.client.force_login(self.owner)

    def url(self):
        return reverse('invoice_drafts') + f'?month={self.today.month}&year={self.today.year}'

    def payload(self, draft, **changes):
        drafts.fill_missing_defaults(draft)
        values = dict(old_electric='100', new_electric='150', old_water='10', new_water='13',
                      room_fee='2.500.000', due_date='', note='', selected='on', revision=str(draft.revision),
                      preview_token=draft.preview_token)
        values.update(changes)
        return {'month': self.today.month, 'year': self.today.year, 'draft_ids': [str(draft.pk)],
                'action': 'publish', **{f'draft-{draft.pk}-{name}': value for name, value in values.items()}}

    def test_invoice_list_automatically_prepares_current_period(self):
        response = self.client.get(reverse('invoice_list'))
        self.assertContains(response, 'Nhập điện nước / Chốt hóa đơn')
        self.assertEqual(response.context['draft_count'], 1)
        self.assertEqual(InvoiceDraft.objects.count(), 1)
        self.assertFalse(Invoice.objects.exists())

    def test_table_renders_snapshots_and_empty_readings(self):
        draft = self.generate()
        response = self.client.get(self.url())
        self.assertContains(response, 'P.101')
        self.assertContains(response, 'Wifi')
        self.assertContains(response, f'name="draft-{draft.pk}-new_electric"')
        self.assertContains(response, 'Lưu và chốt các phòng đã chọn')

    def test_post_publishes_and_redirects(self):
        draft = self.generate()
        response = self.client.post(reverse('invoice_drafts'), self.payload(draft), follow=True)
        self.assertContains(response, 'Đã chốt 1 hóa đơn')
        self.assertEqual(Invoice.objects.get().total_amount, 2820000)
        self.assertEqual(len(response.context['rows']), 0)

    def test_partial_save_and_invalid_reading_errors(self):
        draft = self.generate()
        payload = self.payload(draft, new_water='')
        payload['action'] = 'save'
        self.assertEqual(self.client.post(reverse('invoice_drafts'), payload).status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.new_electric, 150)
        self.assertIsNone(draft.new_water)
        payload = self.payload(draft, new_electric='99')
        response = self.client.post(reverse('invoice_drafts'), payload)
        self.assertContains(response, 'Chỉ số điện mới không được nhỏ hơn chỉ số cũ.')
        self.assertFalse(Invoice.objects.exists())

    def test_missing_or_tampered_row_ids_never_publish(self):
        draft = self.generate()
        payload = self.payload(draft)
        payload['draft_ids'] = ['999999']
        response = self.client.post(reverse('invoice_drafts'), payload)
        self.assertContains(response, 'Danh sách nháp đã thay đổi')
        self.assertFalse(Invoice.objects.exists())

    def test_tenant_cannot_see_drafts_or_publish_them(self):
        self.generate()
        self.tenant.refresh_from_db()
        self.client.force_login(self.tenant.user)
        self.assertEqual(self.client.get(reverse('invoice_drafts')).status_code, 302)
        self.assertEqual(self.client.post(reverse('invoice_generate_drafts'), {
            'month': self.today.month, 'year': self.today.year}).status_code, 302)
        response = self.client.get(reverse('my_invoices'))
        self.assertEqual(list(response.context['invoices']), [])
        self.assertEqual(response.context['total_debt'], 0)
        self.assertFalse(Payment.objects.exists())

    def test_drafts_do_not_count_as_debt_or_prevent_checkout(self):
        self.generate()
        from rooms.services import unpaid_invoices
        self.assertEqual(unpaid_invoices(self.contract), [])
        response = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        output = StringIO()
        call_command('check_overdue_invoices', dry_run=True, stdout=output)
        self.assertEqual(output.getvalue(), '')

    def test_generate_is_post_only_and_rejects_invalid_period(self):
        self.assertEqual(self.client.get(reverse('invoice_generate_drafts')).status_code, 405)
        self.client.post(reverse('invoice_generate_drafts'), {'month': 99, 'year': 2026})
        self.assertFalse(InvoiceDraft.objects.exists())

    def test_csrf_is_required(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse('invoice_generate_drafts'), {
            'month': self.today.month, 'year': self.today.year}).status_code, 403)

    def test_reading_baseline_locked_when_history_exists(self):
        draft = self.generate()
        previous = self.today.replace(day=1) - timedelta(days=1)
        UtilityReading.objects.create(room=self.room, month=previous.month, year=previous.year,
                                      old_electric=0, new_electric=125, old_water=0, new_water=12)
        response = self.client.get(self.url())
        self.assertTrue(response.context['rows'][0]['form'].fields['old_electric'].disabled)
        self.assertTrue(response.context['rows'][0]['form'].fields['old_water'].disabled)
        response = self.client.post(reverse('invoice_drafts'), self.payload(draft))
        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.utility_reading.old_electric, 125)
        self.assertEqual(invoice.electric_fee, 87500)
