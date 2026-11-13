from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from billing.models import Invoice, Payment
from . import services
from .models import Contract, ContractRenewal, ContractTenant, Room


def make_tenant(cccd, name):
    return Tenant.objects.create(full_name=name, id_card_number=cccd, phone='09' + cccd[-8:])


def make_room(no, price=2000000, max_occupants=2, status='trong', floor=1):
    return Room.objects.create(room_number=no, price=price, max_occupants=max_occupants, status=status, floor=floor)


def make_contract(room, tenants, start=None, end=None, deposit=2000000):
    """Lập hợp đồng bằng nghiệp vụ thật: người đầu tiên trong danh sách là người đại diện."""
    today = timezone.localdate()
    return services.create_contract(
        room, tenants, tenants[0], start or today - timedelta(days=30), end or today + timedelta(days=335),
        Decimal(deposit))


def add_invoice(contract, total='1000000', paid='0', month=1, year=2026, due=None):
    inv = Invoice.objects.create(
        contract=contract, month=month, year=year, room_fee=Decimal(total), total_amount=Decimal(total),
        due_date=due or date(2099, 1, 1))
    if Decimal(paid) > 0:
        Payment.objects.create(invoice=inv, amount=Decimal(paid))
    return inv


class CreateContractServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = make_room('101', max_occupants=2)
        self.a = make_tenant('012345678901', 'Nguyen A')
        self.b = make_tenant('012345678902', 'Tran B')

    def create(self, **kw):
        args = dict(room=self.room, tenants=[self.a, self.b], representative=self.a,
                    start_date=self.today, end_date=self.today + timedelta(days=365), deposit=Decimal('2000000'))
        args.update(kw)
        return services.create_contract(**args)

    def test_success_creates_contract_people_and_account(self):
        contract = self.create()
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.DANG_THUE)
        self.assertEqual(contract.contract_tenants.count(), 2)
        self.assertEqual(contract.contract_tenants.get(is_representative=True).tenant, self.a)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.user.username, '012345678901')       # đại diện có tài khoản
        self.assertIsNone(self.b.user)                                # người ở cùng thì không
        self.assertEqual(contract.display_code, f'HD-{contract.pk:04d}')

    def assertInvalid(self, text, **kw):
        before = Contract.objects.count()
        with self.assertRaises(ValidationError) as ctx:
            self.create(**kw)
        self.assertTrue(any(text in m for m in ctx.exception.messages), ctx.exception.messages)
        self.assertEqual(Contract.objects.count(), before)   # không tạo gì cả

    def test_room_must_be_free(self):
        self.room.status = 'bao_tri'; self.room.save()
        self.assertInvalid('không còn trống')

    def test_room_with_active_contract_is_not_free(self):
        make_contract(self.room, [self.a])
        c = make_tenant('012345678903', 'Le C')
        with self.assertRaises(ValidationError):
            services.create_contract(self.room, [c], c, self.today, self.today + timedelta(days=30), Decimal(0))

    def test_needs_tenants_and_one_representative(self):
        self.assertInvalid('ít nhất một người thuê', tenants=[], representative=None)
        self.assertInvalid('chọn một người đại diện', representative=None)
        c = make_tenant('012345678903', 'Le C')
        self.assertInvalid('nằm trong danh sách', representative=c)

    def test_capacity(self):
        c = make_tenant('012345678903', 'Le C')
        self.assertInvalid('tối đa 2 người', tenants=[self.a, self.b, c])

    def test_tenant_already_renting(self):
        other = make_room('102')
        make_contract(other, [self.a])
        self.assertInvalid('Nguyen A đang thuê phòng 102', tenants=[self.a], representative=self.a)

    def test_dates_and_deposit(self):
        self.assertInvalid('không được trước ngày bắt đầu', end_date=self.today - timedelta(days=1))
        self.assertInvalid('không được âm', deposit=Decimal('-1'))

    def test_ended_contract_does_not_block_new_one(self):
        old = make_contract(self.room, [self.a])
        services.checkout_contract(old, self.today)
        new = self.create(tenants=[self.a], representative=self.a)
        self.assertEqual(new.room, self.room)


class RenewServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.contract = make_contract(make_room('101'), [make_tenant('012345678901', 'Nguyen A')])

    def test_renew(self):
        old_end = self.contract.end_date
        new_end = old_end + timedelta(days=365)
        services.renew_contract(self.contract, new_end, 'Gia hạn 1 năm')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, new_end)
        renewal = ContractRenewal.objects.get()
        self.assertEqual((renewal.old_end_date, renewal.new_end_date, renewal.note), (old_end, new_end, 'Gia hạn 1 năm'))

    def test_new_end_must_be_later(self):
        for bad in [self.contract.end_date, self.contract.end_date - timedelta(days=1)]:
            with self.assertRaises(ValidationError):
                services.renew_contract(self.contract, bad)
        self.assertFalse(ContractRenewal.objects.exists())

    def test_cannot_renew_ended_contract(self):
        services.checkout_contract(self.contract, self.today)
        with self.assertRaises(ValidationError):
            services.renew_contract(self.contract, self.today + timedelta(days=999))

    def test_two_renewals_are_kept_in_order(self):
        services.renew_contract(self.contract, self.contract.end_date + timedelta(days=30))
        self.contract.refresh_from_db()
        services.renew_contract(self.contract, self.contract.end_date + timedelta(days=30))
        self.assertEqual(ContractRenewal.objects.count(), 2)


class CheckoutServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = make_room('101')
        self.contract = make_contract(self.room, [make_tenant('012345678901', 'Nguyen A')])

    def test_checkout_frees_room(self):
        services.checkout_contract(self.contract, self.today)
        self.contract.refresh_from_db(); self.room.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.KET_THUC)
        self.assertEqual(self.contract.checkout_date, self.today)
        self.assertEqual(self.room.status, Room.Status.TRONG)

    def test_blocked_by_unpaid_invoice(self):
        add_invoice(self.contract, total='1000000', paid='400000')    # trả một phần vẫn còn nợ
        with self.assertRaises(ValidationError) as ctx:
            services.checkout_contract(self.contract, self.today)
        self.assertIn('1 hóa đơn chưa thanh toán (tổng 600.000 đ)', ctx.exception.messages[0])
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.HIEU_LUC)

    def test_allowed_when_all_paid(self):
        add_invoice(self.contract, total='1000000', paid='1000000')
        services.checkout_contract(self.contract, self.today)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.KET_THUC)

    def test_date_rules_and_double_checkout(self):
        with self.assertRaises(ValidationError):
            services.checkout_contract(self.contract, self.today + timedelta(days=1))
        with self.assertRaises(ValidationError):
            services.checkout_contract(self.contract, self.contract.start_date - timedelta(days=1))
        services.checkout_contract(self.contract, self.today)
        with self.assertRaises(ValidationError):
            services.checkout_contract(self.contract, self.today)


class TransferServiceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.old_room = make_room('101', price=2000000, max_occupants=2)
        self.new_room = make_room('201', price=2500000, max_occupants=3, floor=2)
        self.a = make_tenant('012345678901', 'Nguyen A')
        self.b = make_tenant('012345678902', 'Tran B')
        self.contract = make_contract(self.old_room, [self.a, self.b], deposit=3000000)

    def transfer(self, **kw):
        args = dict(contract=self.contract, new_room=self.new_room, transfer_date=self.today,
                    new_end_date=self.contract.end_date)
        args.update(kw)
        return services.transfer_contract(**args)

    def test_transfer_moves_people_and_keeps_history(self):
        inv = add_invoice(self.contract, total='1000000', paid='1000000')
        new = self.transfer()
        self.contract.refresh_from_db(); self.old_room.refresh_from_db(); self.new_room.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.KET_THUC)
        self.assertEqual(self.contract.checkout_date, self.today)
        self.assertEqual((self.old_room.status, self.new_room.status), (Room.Status.TRONG, Room.Status.DANG_THUE))
        self.assertEqual(new.room, self.new_room)
        self.assertEqual(new.previous_contract, self.contract)
        self.assertEqual(new.deposit, Decimal('3000000'))
        self.assertEqual({(ct.tenant_id, ct.is_representative) for ct in new.contract_tenants.all()},
                         {(self.a.pk, True), (self.b.pk, False)})
        inv.refresh_from_db()
        self.assertEqual(inv.contract.room, self.old_room)           # hóa đơn cũ vẫn ở phòng cũ

    def test_representative_keeps_same_account(self):
        self.a.refresh_from_db()
        user_id = self.a.user_id
        self.transfer()
        self.a.refresh_from_db()
        self.assertEqual(self.a.user_id, user_id)

    def test_errors_leave_everything_unchanged(self):
        cases = [
            dict(new_room=self.old_room),
            dict(new_end_date=self.today - timedelta(days=1)),
            dict(transfer_date=self.today + timedelta(days=1)),
        ]
        for kw in cases:
            with self.assertRaises(ValidationError):
                self.transfer(**kw)
        busy = make_room('202'); other = make_tenant('012345678903', 'Le C')
        make_contract(busy, [other])
        with self.assertRaises(ValidationError):
            self.transfer(new_room=busy)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.HIEU_LUC)
        self.assertEqual(Contract.objects.count(), 2)

    def test_capacity_of_new_room(self):
        small = make_room('301', max_occupants=1)
        with self.assertRaises(ValidationError) as ctx:
            self.transfer(new_room=small)
        self.assertIn('tối đa 1 người', ctx.exception.messages[0])

    def test_blocked_by_unpaid_invoice(self):
        add_invoice(self.contract, total='500000')
        with self.assertRaises(ValidationError):
            self.transfer()
        self.assertEqual(Contract.objects.count(), 1)


class ContractViewBase(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        User.objects.create_user('chutro', password='pw12345!', role=User.Role.OWNER)

    def login_owner(self):
        self.client.login(username='chutro', password='pw12345!')


class ContractPermissionTests(ContractViewBase):
    def test_anonymous_and_tenant_blocked(self):
        room = make_room('101')
        contract = make_contract(room, [make_tenant('012345678901', 'Nguyen A')])
        urls = [reverse('contract_list'), reverse('contract_create'), reverse('contract_detail', args=[contract.pk]),
                reverse('contract_renew', args=[contract.pk]), reverse('contract_checkout', args=[contract.pk]),
                reverse('contract_transfer', args=[contract.pk])]
        for url in urls:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn('/dang-nhap/', r['Location'])
        self.client.login(username='012345678901', password='012345678901')
        for url in urls:
            self.assertRedirects(self.client.get(url), reverse('home'), fetch_redirect_response=False)
        r = self.client.post(reverse('contract_checkout', args=[contract.pk]), {'checkout_date': self.today})
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.HIEU_LUC)

    def test_owner_pages_have_no_admin_links(self):
        room = make_room('101'); make_room('102')
        contract = make_contract(room, [make_tenant('012345678901', 'Nguyen A')])
        self.login_owner()
        for url in [reverse('contract_list'), reverse('contract_create'), reverse('contract_detail', args=[contract.pk]),
                    reverse('contract_renew', args=[contract.pk]), reverse('contract_checkout', args=[contract.pk]),
                    reverse('contract_transfer', args=[contract.pk])]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotContains(r, 'href="/admin/')

    def test_tenant_portal_url_still_works(self):
        make_contract(make_room('101'), [make_tenant('012345678901', 'Nguyen A')])
        self.client.login(username='012345678901', password='012345678901')
        r = self.client.get(reverse('my_contracts'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(reverse('my_contracts'), '/hop-dong-cua-toi/')


class ContractListViewTests(ContractViewBase):
    def setUp(self):
        super().setUp()
        t = self.today
        self.c_ok = make_contract(make_room('101'), [make_tenant('012345678901', 'Nguyễn Minh An')], end=t + timedelta(days=200))
        self.c_soon = make_contract(make_room('102'), [make_tenant('012345678902', 'Trần Thị Mai')], end=t + timedelta(days=10))
        self.c_late = make_contract(make_room('103'), [make_tenant('012345678903', 'Lê Quang Huy')], end=t - timedelta(days=3))
        self.c_end = make_contract(make_room('104'), [make_tenant('012345678904', 'Đỗ Hoàng Nam')])
        services.checkout_contract(self.c_end, t)
        self.login_owner()

    def test_counts_and_status_labels(self):
        r = self.client.get(reverse('contract_list'))
        self.assertEqual(r.context['counts'], {'all': 4, 'hieu_luc': 3, 'sap_het': 2, 'ket_thuc': 1})
        labels = {row['contract'].pk: row['label'] for row in r.context['rows']}
        self.assertEqual(labels[self.c_ok.pk], 'Đang hiệu lực')
        self.assertEqual(labels[self.c_soon.pk], 'Sắp hết hạn')
        self.assertEqual(labels[self.c_late.pk], 'Đã hết hạn')
        self.assertEqual(labels[self.c_end.pk], 'Đã kết thúc')

    def test_filters(self):
        def ids(**params):
            r = self.client.get(reverse('contract_list'), params)
            return {row['contract'].pk for row in r.context['rows']}
        self.assertEqual(ids(status='hieu_luc'), {self.c_ok.pk, self.c_soon.pk, self.c_late.pk})
        self.assertEqual(ids(status='sap_het'), {self.c_soon.pk, self.c_late.pk})
        self.assertEqual(ids(status='ket_thuc'), {self.c_end.pk})
        self.assertEqual(len(ids(status='sai')), 4)

    def test_search_by_name_room_and_code_without_accents(self):
        def ids(q):
            r = self.client.get(reverse('contract_list'), {'q': q})
            return {row['contract'].pk for row in r.context['rows']}
        self.assertEqual(ids('nguyen minh'), {self.c_ok.pk})
        self.assertEqual(ids('do hoang'), {self.c_end.pk})
        self.assertEqual(ids('102'), {self.c_soon.pk})
        self.assertEqual(ids(self.c_late.display_code.lower()), {self.c_late.pk})

    def test_empty_state(self):
        Contract.objects.all().delete()
        self.assertContains(self.client.get(reverse('contract_list')), 'Chưa có hợp đồng nào.')


class ContractCreateViewTests(ContractViewBase):
    def setUp(self):
        super().setUp()
        self.room = make_room('101', max_occupants=2)
        self.a = make_tenant('012345678901', 'Nguyen A')
        self.b = make_tenant('012345678902', 'Tran B')
        self.login_owner()

    def data(self, **extra):
        d = {'room': self.room.pk, 'tenants': [self.a.pk, self.b.pk], 'representative': self.a.pk,
             'start_date': self.today.isoformat(), 'end_date': (self.today + timedelta(days=365)).isoformat(),
             'deposit': '2.000.000'}
        d.update(extra)
        return d

    def test_get_with_prefill(self):
        r = self.client.get(reverse('contract_create'), {'room': self.room.pk, 'tenant': self.a.pk})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['rep_id'], self.a.pk)
        self.assertEqual(r.context['selected_ids'], {self.a.pk})
        self.assertContains(r, 'Phòng 101')
        self.assertContains(r, 'Nguyen A')

    def test_only_free_rooms_and_unassigned_tenants_are_offered(self):
        busy = make_room('102', status='bao_tri')
        rented_room = make_room('103'); c = make_tenant('012345678903', 'Le C')
        make_contract(rented_room, [c])
        r = self.client.get(reverse('contract_create'))
        offered_rooms = {room.room_number for room in r.context['form'].fields['room'].queryset}
        self.assertEqual(offered_rooms, {'101'})
        self.assertNotIn(c, list(r.context['eligible']))
        self.assertIn(self.a, list(r.context['eligible']))

    def test_create_success_shows_account_info(self):
        r = self.client.post(reverse('contract_create'), self.data(), follow=True)
        contract = Contract.objects.get()
        self.assertRedirects(r, reverse('contract_detail', args=[contract.pk]))
        self.assertContains(r, f'Đã lập hợp đồng {contract.display_code} cho phòng 101')
        self.assertContains(r, 'mật khẩu ban đầu đều là số CCCD (012345678901)')
        self.assertEqual(contract.deposit, Decimal('2000000'))
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'dang_thue')

    def test_errors_are_shown_and_nothing_saved(self):
        r = self.client.post(reverse('contract_create'), self.data(representative=''))
        self.assertContains(r, 'Hãy chọn một người đại diện ký hợp đồng.')
        r = self.client.post(reverse('contract_create'), self.data(tenants=[]))
        self.assertContains(r, 'Hãy chọn ít nhất một người thuê.')
        c = make_tenant('012345678903', 'Le C')
        r = self.client.post(reverse('contract_create'), self.data(tenants=[self.a.pk, self.b.pk, c.pk]))
        self.assertContains(r, 'tối đa 2 người')
        r = self.client.post(reverse('contract_create'), self.data(end_date=(self.today - timedelta(days=5)).isoformat()))
        self.assertContains(r, 'không được trước ngày bắt đầu')
        r = self.client.post(reverse('contract_create'), self.data(deposit='abc'))
        self.assertTrue(r.context['form'].errors)
        self.assertFalse(Contract.objects.exists())

    def test_selection_is_kept_when_there_is_an_error(self):
        r = self.client.post(reverse('contract_create'), self.data(end_date=''))
        self.assertEqual(r.context['selected_ids'], {self.a.pk, self.b.pk})
        self.assertEqual(r.context['rep_id'], self.a.pk)

    def test_no_free_room_message(self):
        self.room.status = 'bao_tri'; self.room.save()
        r = self.client.get(reverse('contract_create'))
        self.assertContains(r, 'Hiện không có phòng nào còn trống')

    def test_add_tenant_link_returns_to_contract_page(self):
        r = self.client.get(reverse('contract_create'))
        self.assertContains(r, '/nguoi-thue/them/?next=/hop-dong/them/')
        r = self.client.post(reverse('tenant_create') + '?next=/hop-dong/them/', {
            'full_name': 'Pham D', 'phone': '0912345678', 'id_card_number': '012345678909',
            'next': '/hop-dong/them/'})
        self.assertRedirects(r, '/hop-dong/them/', fetch_redirect_response=False)

    def test_unsafe_next_is_ignored(self):
        r = self.client.post(reverse('tenant_create'), {
            'full_name': 'Pham D', 'phone': '0912345678', 'id_card_number': '012345678909',
            'next': 'https://evil.example.com/'})
        tenant = Tenant.objects.get(id_card_number='012345678909')
        self.assertRedirects(r, reverse('tenant_detail', args=[tenant.pk]))


class ContractDetailViewTests(ContractViewBase):
    def test_detail_content(self):
        room = make_room('101', price=2500000)
        a = make_tenant('012345678901', 'Nguyễn Minh An'); b = make_tenant('012345678902', 'Trần Thị Mai')
        contract = make_contract(room, [a, b], deposit=2500000)
        add_invoice(contract, total='1000000', paid='400000', month=10, year=2026)
        services.renew_contract(contract, contract.end_date + timedelta(days=30), 'Gia hạn thêm')
        self.login_owner()
        r = self.client.get(reverse('contract_detail', args=[contract.pk]))
        self.assertContains(r, contract.display_code)
        self.assertContains(r, 'Nguyễn Minh An')
        self.assertContains(r, 'Đại diện')
        self.assertContains(r, '2.500.000 đ')
        self.assertContains(r, 'Còn nợ 600.000 đ')
        self.assertContains(r, 'Gia hạn thêm')
        self.assertContains(r, 'Gia hạn</a>')
        self.assertContains(r, 'Trả phòng</a>')

    def test_ended_contract_hides_actions(self):
        contract = make_contract(make_room('101'), [make_tenant('012345678901', 'Nguyen A')])
        services.checkout_contract(contract, self.today)
        self.login_owner()
        r = self.client.get(reverse('contract_detail', args=[contract.pk]))
        self.assertNotContains(r, reverse('contract_renew', args=[contract.pk]))
        self.assertNotContains(r, reverse('contract_checkout', args=[contract.pk]))
        self.assertContains(r, 'Ngày trả phòng')

    def test_warning_banners(self):
        soon = make_contract(make_room('101'), [make_tenant('012345678901', 'A')], end=self.today + timedelta(days=5))
        late = make_contract(make_room('102'), [make_tenant('012345678902', 'B')], end=self.today - timedelta(days=4))
        self.login_owner()
        self.assertContains(self.client.get(reverse('contract_detail', args=[soon.pk])), 'còn 5 ngày')
        self.assertContains(self.client.get(reverse('contract_detail', args=[late.pk])), 'quá hạn 4 ngày')

    def test_transfer_chain_links(self):
        a = make_tenant('012345678901', 'Nguyen A')
        old = make_contract(make_room('101'), [a])
        new = services.transfer_contract(old, make_room('201', floor=2), self.today, old.end_date)
        self.login_owner()
        self.assertContains(self.client.get(reverse('contract_detail', args=[old.pk])), 'Đã chuyển sang')
        self.assertContains(self.client.get(reverse('contract_detail', args=[new.pk])), 'Chuyển từ')

    def test_missing_contract_404(self):
        self.login_owner()
        self.assertEqual(self.client.get(reverse('contract_detail', args=[999])).status_code, 404)


class ContractActionViewTests(ContractViewBase):
    def setUp(self):
        super().setUp()
        self.room = make_room('101')
        self.a = make_tenant('012345678901', 'Nguyen A')
        self.contract = make_contract(self.room, [self.a])
        self.login_owner()

    def test_renew_flow(self):
        url = reverse('contract_renew', args=[self.contract.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        new_end = self.contract.end_date + timedelta(days=100)
        r = self.client.post(url, {'new_end_date': new_end.isoformat(), 'note': 'ok'}, follow=True)
        self.assertRedirects(r, reverse('contract_detail', args=[self.contract.pk]))
        self.assertContains(r, 'Đã gia hạn hợp đồng')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, new_end)

    def test_renew_rejects_earlier_date(self):
        url = reverse('contract_renew', args=[self.contract.pk])
        r = self.client.post(url, {'new_end_date': self.contract.end_date.isoformat()})
        self.assertContains(r, 'phải sau ngày kết thúc hiện tại')

    def test_checkout_flow(self):
        url = reverse('contract_checkout', args=[self.contract.pk])
        self.assertContains(self.client.get(url), 'Xác nhận trả phòng')
        r = self.client.post(url, {'checkout_date': self.today.isoformat()}, follow=True)
        self.assertContains(r, 'Đã trả phòng 101')
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'trong')

    def test_checkout_blocked_page_lists_unpaid(self):
        add_invoice(self.contract, total='1000000', paid='250000', month=10, year=2026)
        url = reverse('contract_checkout', args=[self.contract.pk])
        r = self.client.get(url)
        self.assertContains(r, 'Chưa thực hiện được')
        self.assertContains(r, '750.000 đ')
        self.assertNotContains(r, 'Xác nhận trả phòng')
        self.client.post(url, {'checkout_date': self.today.isoformat()})
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.HIEU_LUC)

    def test_transfer_flow_and_room_choices(self):
        target = make_room('201', floor=2)
        make_room('202', status='bao_tri')
        url = reverse('contract_transfer', args=[self.contract.pk])
        r = self.client.get(url)
        offered = {room.room_number for room in r.context['form'].fields['new_room'].queryset}
        self.assertEqual(offered, {'201'})
        r = self.client.post(url, {'new_room': target.pk, 'transfer_date': self.today.isoformat(),
                                   'new_end_date': self.contract.end_date.isoformat()}, follow=True)
        new = Contract.objects.get(previous_contract=self.contract)
        self.assertRedirects(r, reverse('contract_detail', args=[new.pk]))
        self.assertContains(r, 'Đã chuyển sang phòng 201')
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, 'trong')

    def test_actions_on_ended_contract_redirect_back(self):
        services.checkout_contract(self.contract, self.today)
        for name in ['contract_renew', 'contract_checkout', 'contract_transfer']:
            r = self.client.get(reverse(name, args=[self.contract.pk]))
            self.assertRedirects(r, reverse('contract_detail', args=[self.contract.pk]))

    def test_overview_task_links_to_contract(self):
        soon = make_contract(make_room('301'), [make_tenant('012345678905', 'Le C')], end=self.today + timedelta(days=7))
        r = self.client.get(reverse('owner_dashboard'))
        urls = [t['url'] for t in r.context['tasks']]
        self.assertIn(reverse('contract_detail', args=[soon.pk]), urls)