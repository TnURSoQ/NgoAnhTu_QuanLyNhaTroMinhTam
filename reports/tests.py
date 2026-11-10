from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from billing.models import Invoice, Payment
from rooms.models import Contract, ContractTenant, Room


def make_invoice(room_number, cccd, name, total, due_date, month=10, year=2026):
    room = Room.objects.create(room_number=room_number, price=Decimal('2000000'))
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='09' + cccd)
    contract = Contract.objects.create(room=room, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=True)
    return Invoice.objects.create(
        contract=contract, month=month, year=year, room_fee=Decimal(total),
        total_amount=Decimal(total), due_date=due_date)


class ReportDashboardTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.owner = User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER, is_staff=True)

    def login_owner(self):
        self.client.login(username='chutro', password='pw12345!')

    # --- phân quyền ---
    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse('report_dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/dang-nhap/', r['Location'])

    def test_tenant_cannot_see_report(self):
        make_invoice('101', '001', 'Nguyen A', '1000000', self.today + timedelta(days=5))
        self.client.login(username='001', password='001')
        r = self.client.get(reverse('report_dashboard'))
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)

    def test_owner_can_see_report(self):
        self.login_owner()
        self.assertEqual(self.client.get(reverse('report_dashboard')).status_code, 200)

    # --- tỷ lệ phòng trống ---
    def test_room_stats(self):
        Room.objects.create(room_number='1', price=1, status='trong')
        Room.objects.create(room_number='2', price=1, status='dang_thue')
        Room.objects.create(room_number='3', price=1, status='dang_thue')
        Room.objects.create(room_number='4', price=1, status='bao_tri')
        self.login_owner()
        stats = self.client.get(reverse('report_dashboard')).context['room_stats']
        self.assertEqual(stats['total'], 4)
        self.assertEqual(stats['trong'], 1)
        self.assertEqual(stats['dang_thue'], 2)
        self.assertEqual(stats['bao_tri'], 1)
        self.assertEqual(stats['pct_trong'], 25)

    def test_room_stats_no_rooms(self):
        self.login_owner()
        stats = self.client.get(reverse('report_dashboard')).context['room_stats']
        self.assertEqual(stats['total'], 0)
        self.assertEqual(stats['pct_trong'], 0)

    # --- doanh thu theo tháng ---
    def test_revenue_by_month_and_year_filter(self):
        inv = make_invoice('101', '001', 'Nguyen A', '5000000', self.today + timedelta(days=5))
        Payment.objects.create(invoice=inv, amount=Decimal('1000000'), paid_date=date(2026, 10, 5))
        Payment.objects.create(invoice=inv, amount=Decimal('500000'), paid_date=date(2026, 10, 20))
        Payment.objects.create(invoice=inv, amount=Decimal('300000'), paid_date=date(2026, 11, 2))
        Payment.objects.create(invoice=inv, amount=Decimal('999999'), paid_date=date(2025, 10, 1))
        self.login_owner()

        ctx = self.client.get(reverse('report_dashboard'), {'year': 2026}).context
        self.assertEqual(ctx['months'][9]['total'], Decimal('1500000'))   # tháng 10
        self.assertEqual(ctx['months'][10]['total'], Decimal('300000'))   # tháng 11
        self.assertEqual(ctx['months'][0]['total'], Decimal('0'))
        self.assertEqual(ctx['year_total'], Decimal('1800000'))
        self.assertEqual(ctx['months'][9]['pct'], 100)
        self.assertEqual(ctx['months'][10]['pct'], 20)
        self.assertIn(2025, ctx['years'])

        ctx = self.client.get(reverse('report_dashboard'), {'year': 2025}).context
        self.assertEqual(ctx['year_total'], Decimal('999999'))

    def test_invalid_year_falls_back(self):
        self.login_owner()
        for bad in ['abc', '1', '99999']:
            r = self.client.get(reverse('report_dashboard'), {'year': bad})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.context['year'], self.today.year)

    # --- công nợ ---
    def test_debts(self):
        past, future = self.today - timedelta(days=5), self.today + timedelta(days=30)
        overdue = make_invoice('101', '001', 'Nguyen A', '2000000', past)
        make_invoice('102', '002', 'Tran B', '3000000', future)
        paid_full = make_invoice('103', '003', 'Le C', '1500000', past)
        Payment.objects.create(invoice=overdue, amount=Decimal('500000'))          # trả một phần
        Payment.objects.create(invoice=paid_full, amount=Decimal('1500000'))       # trả đủ -> không còn nợ
        self.login_owner()
        r = self.client.get(reverse('report_dashboard'))
        ctx = r.context

        rooms = [d['invoice'].contract.room.room_number for d in ctx['debts']]
        self.assertEqual(rooms, ['101', '102'])                      # sắp theo hạn, bỏ hóa đơn đã trả đủ
        self.assertEqual(ctx['debts'][0]['remaining'], Decimal('1500000'))
        self.assertEqual(ctx['debts'][0]['overdue_days'], 5)
        self.assertEqual(ctx['debts'][1]['overdue_days'], 0)
        self.assertEqual(ctx['debts'][0]['tenant'].full_name, 'Nguyen A')
        self.assertEqual(ctx['total_debt'], Decimal('4500000'))
        self.assertEqual(ctx['overdue_count'], 1)
        self.assertContains(r, '4.500.000đ')
        self.assertContains(r, 'Quá hạn 5 ngày')
        self.assertContains(r, '09001')                              # số điện thoại người đại diện

    def test_no_debts_message(self):
        self.login_owner()
        self.assertContains(self.client.get(reverse('report_dashboard')), 'Không có công nợ')

def build(room_number, cccd, name, end_date, total=None, due=None, month=None, year=None):
    """Tạo phòng + người thuê đại diện + hợp đồng (+ hóa đơn nếu có total)."""
    room = Room.objects.create(room_number=room_number, price=Decimal('2000000'))
    tenant = Tenant.objects.create(full_name=name, id_card_number=cccd, phone='09' + cccd)
    contract = Contract.objects.create(room=room, start_date=date(2020, 1, 1), end_date=end_date)
    ContractTenant.objects.create(contract=contract, tenant=tenant, is_representative=True)
    invoice = None
    if total is not None:
        invoice = Invoice.objects.create(
            contract=contract, month=month, year=year, room_fee=Decimal(total),
            total_amount=Decimal(total), due_date=due)
    return room, contract, invoice


class OverviewTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)
        self.far = self.today + timedelta(days=400)

    def login_owner(self):
        self.client.login(username='chutro', password='pw12345!')

    def test_permissions(self):
        r = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/dang-nhap/', r['Location'])
        build('101', '001', 'Nguyen A', self.far)
        self.client.login(username='001', password='001')
        self.assertRedirects(self.client.get(reverse('owner_dashboard')), reverse('home'),
                             fetch_redirect_response=False)
        self.client.logout()
        self.login_owner()
        r = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tổng quan')
        self.assertContains(r, 'Công việc cần xử lý')

    def test_kpis(self):
        Room.objects.create(room_number='1', price=1, status='trong')
        Room.objects.create(room_number='2', price=1, status='trong')
        Room.objects.create(room_number='3', price=1, status='dang_thue')
        _, _, inv = build('101', '001', 'A', self.far, total='2000000',
                          due=self.today + timedelta(days=5), month=self.today.month, year=self.today.year)
        Payment.objects.create(invoice=inv, amount=Decimal('500000'))
        other_month = 1 if self.today.month != 1 else 2
        build('102', '002', 'B', self.far, total='3000000',
              due=self.today + timedelta(days=5), month=other_month, year=self.today.year)
        self.login_owner()
        r = self.client.get(reverse('owner_dashboard'))
        ctx = r.context
        self.assertEqual(ctx['rooms_total'], 5)     # 1, 2, 3, 101, 102
        self.assertEqual(ctx['rooms_empty'], 2)     # 1 và 2; 101 và 102 đã có hợp đồng
        self.assertEqual(ctx['month_unpaid'], Decimal('1500000'))  # chỉ tính tháng này, trừ phần đã thu
        self.assertContains(r, '1.500.000 đ')

    def test_tasks_overdue_invoices_and_expiring_contracts(self):
        past = self.today - timedelta(days=5)
        build('101', '001', 'Nguyen A', self.far, total='2000000', due=past, month=1, year=2020)
        build('201', '002', 'Tran B', self.today + timedelta(days=21))      # sắp hết hạn
        build('202', '003', 'Le C', self.today - timedelta(days=3))         # đã hết hạn nhưng chưa kết thúc
        build('404', '004', 'Pham D', self.today + timedelta(days=60))      # còn xa, không hiện
        self.login_owner()
        r = self.client.get(reverse('owner_dashboard'))
        titles = [t['title'] for t in r.context['tasks']]
        self.assertEqual(titles, ['Hóa đơn quá hạn', 'Hợp đồng đã hết hạn', 'Hợp đồng sắp hết hạn'])
        badges = [t['badge'] for t in r.context['tasks']]
        self.assertEqual(badges, ['5 ngày', 'Quá 3 ngày', 'Còn 21 ngày'])
        self.assertContains(r, 'P.101 - Nguyen A')
        # P.404 vẫn có thể hiện ở danh sách phòng, nhưng không được nằm trong công việc cần xử lý
        self.assertFalse(any('P.404' in t['subtitle'] for t in r.context['tasks']))
        self.assertEqual(r.context['overdue_count'], 1)

    def test_no_tasks_message(self):
        self.login_owner()
        self.assertContains(self.client.get(reverse('owner_dashboard')), 'Không có việc cần xử lý')

    def test_room_cards_show_tenant_or_empty(self):
        build('101', '001', 'Nguyen A', self.far)
        Room.objects.create(room_number='102', price=1)
        Room.objects.create(room_number='103', price=1, status='bao_tri')
        self.login_owner()
        r = self.client.get(reverse('owner_dashboard'))
        self.assertContains(r, 'Nguyen A')
        self.assertContains(r, '09001')
        self.assertContains(r, 'Đang thuê')
        self.assertContains(r, 'Chưa có người thuê')
        self.assertContains(r, 'Còn trống')
        self.assertContains(r, 'Đang sửa')

    def test_room_cards_limit_to_six(self):
        for i in range(10):
            Room.objects.create(room_number=f'{100 + i}', price=1)
        self.login_owner()
        self.assertEqual(len(self.client.get(reverse('owner_dashboard')).context['preview']), 6)

    def test_overview_has_no_admin_links_for_owner(self):
        build('101', '001', 'Nguyen A', self.today + timedelta(days=10),
              total='1000000', due=self.today - timedelta(days=2), month=1, year=2020)
        self.login_owner()
        r = self.client.get(reverse('owner_dashboard'))
        self.assertNotContains(r, 'href="/admin/')
        r = self.client.get(reverse('report_dashboard'))
        self.assertNotContains(r, 'href="/admin/')