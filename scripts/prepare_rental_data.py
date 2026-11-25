"""Build a coherent, fictional rental dataset before installing it into local SQLite.

Run without --install to prepare only. The live database is backed up again and
checked for intervening changes before an explicitly requested installation.
"""
import argparse
import calendar
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nhatro_minhtam.settings')

PROFILES = [
    ('Nguyễn Hoàng Nam', '1998-05-14', 'male', 'Kỹ thuật viên điện', 'Hòa Khánh'),
    ('Trần Thị Ngọc Hân', '2000-08-21', 'female', 'Nhân viên kế toán', 'Thanh Khê'),
    ('Lê Quốc Bảo', '1999-11-03', 'male', 'Lập trình viên', 'Hải Châu'),
    ('Phạm Thị Thảo My', '2002-02-18', 'female', 'Nhân viên thiết kế đồ họa', 'Hòa Cường'),
    ('Võ Minh Khang', '1996-09-27', 'male', 'Nhân viên giao nhận', 'Liên Chiểu'),
    ('Đặng Thị Quỳnh Như', '2001-06-09', 'female', 'Nhân viên marketing', 'An Hải'),
    ('Bùi Anh Tuấn', '1997-04-11', 'male', 'Nhân viên ngân hàng', 'Cẩm Lệ'),
    ('Hồ Thị Thanh Trúc', '1999-12-06', 'female', 'Giáo viên mầm non', 'Hòa Xuân'),
    ('Huỳnh Đức Huy', '2000-01-22', 'male', 'Nhân viên lễ tân', 'Sơn Trà'),
    ('Ngô Thị Minh Châu', '2003-07-15', 'female', 'Nhân viên hành chính', 'Ngũ Hành Sơn'),
    ('Đỗ Thành Đạt', '1995-10-08', 'male', 'Nhân viên kho', 'Hòa Khánh'),
    ('Phan Thị Thu Hà', '1997-03-19', 'female', 'Điều dưỡng', 'Hải Châu'),
    ('Nguyễn Gia Phúc', '2002-05-26', 'male', 'Kỹ thuật viên cơ khí', 'Liên Chiểu'),
    ('Trần Khánh Linh', '2001-09-12', 'female', 'Nhân viên bán hàng', 'Thanh Khê'),
    ('Lê Nhật Minh', '1998-01-30', 'male', 'Kỹ sư xây dựng', 'Hòa Cường'),
    ('Phạm Ngọc Ánh', '2004-11-02', 'female', 'Sinh viên', 'An Hải'),
    ('Võ Thanh Tùng', '1994-06-17', 'male', 'Đầu bếp', 'Cẩm Lệ'),
    ('Đặng Hoài An', '1999-10-24', 'female', 'Nhân viên văn phòng', 'Sơn Trà'),
    ('Cao Đức Long', '1996-12-05', 'male', 'Kỹ thuật viên mạng', 'Hòa Xuân'),
    ('Dương Thị Diệu Linh', '2000-04-28', 'female', 'Nhân viên chăm sóc khách hàng', 'Ngũ Hành Sơn'),
    ('Dương Hoàng Anh', '1993-08-16', 'male', 'Nhân viên kinh doanh', 'Hòa Khánh'),
    ('Nguyễn Thị Bảo Trân', '1995-02-23', 'female', 'Nhân viên thu ngân', 'Hải Châu'),
    ('Trần Minh Đức', '2000-10-13', 'male', 'Kỹ thuật viên ô tô', 'Liên Chiểu'),
    ('Lê Thị Phương Thảo', '2001-12-20', 'female', 'Nhân viên du lịch', 'An Hải'),
    ('Phạm Quang Huy', '1997-07-07', 'male', 'Nhân viên vận hành', 'Thanh Khê'),
    ('Võ Thị Yến Nhi', '1999-03-25', 'female', 'Nhân viên kế toán', 'Cẩm Lệ'),
]

PHONE_PREFIXES = ('081', '0905', '0949', '0349', '0964', '0353', '0961')
# Familiar hometown labels and current administrative names are separate on purpose.
REGIONS = (
    ('Đông Hà, Quảng Trị', 'Phường Đông Hà, tỉnh Quảng Trị'),
    ('Thành phố Hà Tĩnh, Hà Tĩnh', 'Phường Thành Sen, tỉnh Hà Tĩnh'),
    ('Thành phố Hồ Chí Minh (Sài Gòn)', 'Phường Sài Gòn, Thành phố Hồ Chí Minh'),
    ('Buôn Ma Thuột, Đắk Lắk', 'Phường Buôn Ma Thuột, tỉnh Đắk Lắk'),
    ('Gia Nghĩa, Đắk Nông', 'Phường Nam Gia Nghĩa, tỉnh Lâm Đồng'),
    ('Thành phố Huế, Thừa Thiên Huế', 'Phường Vỹ Dạ, thành phố Huế'),
    ('Đồng Hới, Quảng Bình', 'Phường Đồng Hới, tỉnh Quảng Trị'),
    ('Tam Kỳ, Quảng Nam', 'Phường Tam Kỳ, thành phố Đà Nẵng'),
    ('Thành phố Quảng Ngãi, Quảng Ngãi', 'Phường Cẩm Thành, tỉnh Quảng Ngãi'),
    ('Thành phố Đà Nẵng', 'Phường Hòa Khánh, thành phố Đà Nẵng'),
)


def random_identity(used):
    while True:
        number = f'045{secrets.randbelow(10**9):09d}'
        if number not in used:
            used.add(number)
            return number


def random_phone(prefix, used):
    while True:
        number = prefix + f'{secrets.randbelow(10**(10-len(prefix))):0{10-len(prefix)}d}'
        if number not in used:
            used.add(number)
            return number


def profile_plan(count):
    regions = [REGIONS[index % len(REGIONS)] for index in range(count)]
    prefixes = [PHONE_PREFIXES[index % len(PHONE_PREFIXES)] for index in range(count)]
    secrets.SystemRandom().shuffle(regions)
    secrets.SystemRandom().shuffle(prefixes)
    return list(zip(regions, prefixes))


def regional_fields(region):
    hometown, current = region
    return {'hometown': hometown, 'place_of_birth': hometown,
            'birth_registration_place': current,
            'permanent_address': f'Tổ {secrets.randbelow(35)+1}, {current}'}


def month_at(anchor, shift):
    value = anchor.year * 12 + anchor.month - 1 + shift
    return date(value // 12, value % 12 + 1, 1)


def stamp(day, hour=10, minute=0):
    from django.utils import timezone
    value = timezone.make_aware(datetime.combine(day, time(hour, minute)))
    return min(value, timezone.now())


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def model_values(obj):
    return {field.attname: getattr(obj, field.attname) for field in obj._meta.concrete_fields}


def close_demo_contract(contract, owner, today):
    """Keep historical money and final drafts when freeing a room in this dataset."""
    from django.utils import timezone
    from accounts.money import whole_dong
    from rooms.services import checkout_contract
    for draft in contract.invoice_drafts.filter(invoice__isnull=True):
        if contract.start_date.replace(day=1) == today.replace(day=1):
            days = (today - contract.start_date).days + 1
            draft.room_fee = whole_dong(contract.agreed_rent * days / calendar.monthrange(today.year, today.month)[1])
            draft.note = (f'Bàn giao ngày {today:%d/%m/%Y}; tiền phòng tính {days} ngày từ ngày nhận phòng '
                          'theo thỏa thuận. Nước thu đủ tháng theo số người đã chốt. Chờ chốt điện cuối.')
        else:
            draft.note = (f'Bàn giao ngày {today:%d/%m/%Y}; tiền phòng tháng cuối tính trọn tháng theo thỏa thuận. '
                          'Nước thu đủ tháng theo số người đã chốt. Chờ chốt điện cuối.')
        draft.revision += 1
        draft.updated_at = timezone.now()
        draft.full_clean()
        draft.save(update_fields=['room_fee', 'note', 'revision', 'updated_at'])
    return checkout_contract(contract, today, room_condition='trong', accept_outstanding=True,
        created_by=owner, deduction_reason='Đã nhận lại phòng và chìa khóa; phòng sẵn sàng cho thuê. '
        'Cọc tiếp tục giữ để chốt điện và đối chiếu hóa đơn cuối, chưa ghi nhận hoàn tiền.')


def build_database(target, snapshot):
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = target
    settings.EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
    import django
    django.setup()
    from django.contrib.auth.models import Group, Permission
    from django.contrib.sessions.models import Session
    from django.core.management import call_command
    from django.db import transaction
    from django.utils import timezone
    from accounts.models import Tenant, User
    from billing.models import (BankAccount, Invoice, InvoiceDraft, InvoiceService, Payment,
                                PaymentNotice, Service, UtilityRate, UtilityReading)
    from rooms.models import (AppointmentCalendar, CheckoutRecord, CoOccupantRequest, Contract,
                              ContractTenant, DepositEntry, PropertyInfo, Room, RoomPhoto, ViewingAppointment)
    from support.models import Announcement, MaintenanceRequest
    from accounts.text import normalize
    from accounts.money import whole_dong
    from billing.services import default_room_fee

    call_command('migrate', interactive=False, verbosity=0)
    today = date.fromisoformat(snapshot['today'])
    first = month_at(today, -5)
    periods = [month_at(first, index) for index in range(6)]
    with transaction.atomic():
        # Bulk creation deliberately avoids account/appointment side effects during historical import.
        users = []
        for row in snapshot['users']:
            values = {field.attname: field.to_python(row.get(field.attname))
                      for field in User._meta.concrete_fields}
            users.append(User(**values))
        User.objects.bulk_create(users)
        for row in snapshot['groups']:
            group = Group.objects.create(name=row['name'])
            group.permissions.set(Permission.objects.get_by_natural_key(*p) for p in row['permissions'])
        for row in snapshot['memberships']:
            user = User.objects.get(pk=row['id'])
            user.groups.set(Group.objects.filter(name__in=row['groups']))
            user.user_permissions.set(Permission.objects.get_by_natural_key(*p) for p in row['permissions'])
        for row in snapshot['sessions']:
            Session.objects.create(**row)
        if snapshot['bank']:
            BankAccount.objects.create(**snapshot['bank'])
        property_values = snapshot.get('property') or {'id': 1, 'shared_amenities': 'Chỗ để xe'}
        PropertyInfo.objects.update_or_create(pk=1, defaults={'shared_amenities': property_values['shared_amenities']})
        owner = User.objects.filter(role='owner').first()
        if not owner:
            raise ValueError('Cần tài khoản chủ trọ có sẵn để giữ nguyên quyền truy cập.')
        rate = UtilityRate.objects.create(electric_price=3500, water_price=50000,
            water_billing_method='per_person', effective_date=first)
        wifi = Service.objects.create(name='Wi-Fi', unit_price=100000)
        garbage = Service.objects.create(name='Vệ sinh và rác', unit_price=20000)
        rooms = {}
        prices = [2500000, 2700000, 2900000, 2600000]
        for floor in range(1, 5):
            for number in range(1, 5):
                code = str(floor * 100 + number)
                rooms[code] = Room.objects.create(room_number=code, floor=floor, area=22 + number * 2,
                    max_occupants=2 if number < 3 else 3, price=prices[number - 1] + (floor - 1) * 50000,
                    amenities='Gác lửng, Nhà vệ sinh riêng, Kệ bếp, Cửa sổ' +
                              (', Điều hòa' if number == 3 else ''),
                    description=f'Phòng tầng {floor}, thoáng sáng, có khu bếp và nhà vệ sinh riêng. '
                        'Lối đi riêng, khu để xe chung và khóa cổng an ninh. Phù hợp 1–2 người đi làm hoặc sinh viên.',
                    status='trong')
        for photo in snapshot['photos']:
            if photo['room_number'] in rooms and (Path(settings.MEDIA_ROOT) / photo['image']).is_file():
                RoomPhoto.objects.create(room=rooms[photo['room_number']], image=photo['image'],
                    caption=photo['caption'], position=photo['position'])

        people = []
        contact_plan = profile_plan(len(PROFILES))
        used_ids = set(User.objects.values_list('username', flat=True))
        used_phones = set()
        for index, (name, born, gender, occupation, ward) in enumerate(PROFILES, 1):
            birthday = date.fromisoformat(born)
            number = random_identity(used_ids)
            region, phone_prefix = contact_plan[index - 1]
            age_limit = next(age for age in (25, 40, 60) if birthday.replace(year=birthday.year + age) > today)
            issued = date(2025, 7 + index % 5, 5 + index % 20)
            last_renewal = birthday.replace(year=birthday.year + 25)
            if issued < last_renewal <= today:
                issued = min(last_renewal + timedelta(days=10), today)
            person = Tenant(full_name=name, id_card_number=number, phone=random_phone(phone_prefix, used_phones),
                email=normalize(name).replace(' ', '').lower() + '@example.com', date_of_birth=birthday,
                occupation=occupation, document_type='cccd', gender=gender, nationality='Việt Nam',
                **regional_fields(region),
                identity_issued_on=issued,
                identity_expires_on=birthday.replace(year=birthday.year + age_limit),
                identity_issued_by='Cục Cảnh sát quản lý hành chính về trật tự xã hội')
            person.full_clean()
            person.save()
            people.append(person)
        specs = [('101', 0, 1), ('102', 0, 3), ('103', 0, 1), ('201', 0, 10),
                 ('202', 1, 1), ('203', 0, 1), ('301', 2, 12), ('302', 0, 1),
                 ('303', 4, 1), ('401', 3, 5), ('402', 0, 1), ('403', 5, 6), ('404', 0, 1)]
        contracts = []
        representatives = []
        next_user_id = max(user.pk for user in users) + 1
        for index, (code, offset, day) in enumerate(specs):
            start = periods[offset].replace(day=min(day, today.day) if offset == 5 else day)
            end = start + timedelta(days=365)
            if code in ('101', '201'):
                end = month_at(start, 6).replace(day=start.day)
            ended = code == '404'
            contract = Contract(room=rooms[code], start_date=start, end_date=end,
                monthly_rent=rooms[code].price - (100000 if code in ('102', '302') else 0),
                deposit=rooms[code].price, initial_electric=Decimal(1200 + index * 137),
                prorate_first_month=True, use_default_services=False,
                status='ket_thuc' if ended else 'hieu_luc',
                checkout_date=periods[4].replace(day=18) if ended else None)
            Contract.objects.bulk_create([contract])
            contract.services.set([wifi, garbage])
            members = people[index * 2:index * 2 + 2]
            representative = members[index % 2]
            representatives.append(representative)
            account = User(id=next_user_id, username=representative.id_card_number, first_name=representative.full_name,
                           email=representative.email, role='tenant', date_joined=stamp(start))
            account.set_password(representative.id_card_number)
            User.objects.bulk_create([account])
            next_user_id += 1
            representative.user = account
            representative.save(update_fields=['user'])
            ContractTenant.objects.bulk_create([ContractTenant(contract=contract, tenant=p,
                is_representative=p.pk == representative.pk) for p in members])
            if not ended:
                Room.objects.filter(pk=contract.room_id).update(status='dang_thue')
            deposit_amount = contract.deposit - (500000 if code == '403' else 0)
            DepositEntry.objects.create(contract=contract, kind='receive', amount=deposit_amount,
                occurred_on=start, method='bank' if index % 2 else 'cash', created_by=owner,
                note='Thu tiền cọc khi bàn giao phòng')
            contracts.append(contract)

        invoice_log = []
        def add_payment(invoice, amount, paid_on, method='chuyen_khoan', note='Thanh toán tiền phòng và dịch vụ'):
            paid_on = min(paid_on, today)
            payment = Payment(invoice=invoice, amount=whole_dong(amount), method=method,
                paid_date=paid_on, recorded_at=stamp(paid_on, 14, 20), recorded_by=owner, note=note)
            payment.full_clean()
            payment.save()
            return payment

        for index, contract in enumerate(contracts):
            meter = contract.initial_electric
            for month_index, period in enumerate(periods):
                if period < contract.start_date.replace(day=1):
                    continue
                if contract.checkout_date and period > contract.checkout_date.replace(day=1):
                    continue
                code = contract.room.room_number
                billing_day = period.replace(day=min(25, today.day if month_index == 5 else 25,
                                                     calendar.monthrange(period.year, period.month)[1]))
                due = min(billing_day + timedelta(days=5), period.replace(day=calendar.monthrange(period.year, period.month)[1]))
                usage = Decimal(68 + (index * 17 + month_index * 13) % 111)
                if period == contract.start_date.replace(day=1) and contract.start_date.day > 1:
                    usage = (usage * (billing_day.day - contract.start_date.day + 1) / billing_day.day).quantize(Decimal('0.01'))
                room_fee = whole_dong(default_room_fee(contract, period.month, period.year))
                if code == '404' and period.month == contract.checkout_date.month:
                    room_fee = whole_dong(contract.agreed_rent * contract.checkout_date.day /
                                          calendar.monthrange(period.year, period.month)[1])
                draft_only = code == '404' and period == contract.checkout_date.replace(day=1)
                draft_only |= month_index == 5 and code in ('301', '401', '403')
                if draft_only:
                    draft = InvoiceDraft.objects.create(contract=contract, month=period.month, year=period.year,
                        room_fee=room_fee, electric_unit_price=3500, water_unit_price=50000,
                        water_billing_method='per_person', water_people_count=2,
                        old_electric=meter, new_electric=None, due_date=due,
                        service_items=[{'service': s.pk, 'description': s.name, 'quantity': 1,
                                        'unit_price': str(s.unit_price)} for s in (wifi, garbage)],
                        note='Chờ ghi chỉ số điện cuối kỳ.' if code != '404' else
                             'Bàn giao ngày 18; tiền phòng tháng cuối tính 18/31 theo thỏa thuận. Chờ chốt điện cuối.')
                    InvoiceDraft.objects.filter(pk=draft.pk).update(created_at=stamp(min(billing_day, today)), updated_at=stamp(min(billing_day, today)))
                    continue
                reading = UtilityReading.objects.create(contract=contract, room=contract.room, month=period.month,
                    year=period.year, old_electric=meter, new_electric=meter + usage, old_water=None, new_water=None)
                meter += usage
                total = room_fee + whole_dong(usage * 3500) + 100000 + wifi.unit_price + garbage.unit_price
                invoice = Invoice.objects.create(contract=contract, utility_reading=reading,
                    month=period.month, year=period.year, room_fee=room_fee,
                    electric_fee=whole_dong(usage * 3500), water_fee=100000,
                    electric_unit_price=3500, water_unit_price=50000, water_billing_method='per_person',
                    water_people_count=2, total_amount=total, due_date=due)
                Invoice.objects.filter(pk=invoice.pk).update(created_at=stamp(billing_day))
                for service in (wifi, garbage):
                    InvoiceService.objects.create(invoice=invoice, service=service, description=service.name,
                                                   unit_price=service.unit_price, quantity=1)
                late_unpaid = code == '302' and month_index == 4
                old_unpaid = code == '404' and month_index == 3
                if late_unpaid or old_unpaid:
                    add_payment(invoice, 1000000, billing_day + timedelta(days=2), note='Thanh toán đợt đầu; phần còn lại thanh toán sau')
                elif month_index == 5:
                    if code in ('101', '103', '202'):
                        add_payment(invoice, total, today, 'tien_mat' if code == '103' else 'chuyen_khoan')
                    elif code in ('102', '203'):
                        add_payment(invoice, 1500000, today, note='Thanh toán trước một phần tiền hóa đơn')
                    elif code == '201':
                        PaymentNotice.objects.create(invoice=invoice, tenant=representatives[index], amount=total,
                            note='Đã chuyển khoản, nhờ chủ trọ kiểm tra và xác nhận.')
                elif index % 3 == 0 and month_index == 2:
                    payment1 = add_payment(invoice, 1000000, billing_day + timedelta(days=1), 'tien_mat', 'Thanh toán đợt 1')
                    add_payment(invoice, total - payment1.amount, billing_day + timedelta(days=4), note='Thanh toán phần còn lại')
                else:
                    paid = add_payment(invoice, total, billing_day + timedelta(days=1 + index % 4),
                                       'tien_mat' if index % 4 == 1 else 'chuyen_khoan')
                    if month_index == 3 and code == '101':
                        notice = PaymentNotice.objects.create(invoice=invoice, tenant=representatives[index], amount=total,
                            status='da_xac_nhan', processed_at=paid.recorded_at, processed_by=owner, payment=paid,
                            note='Chuyển khoản đầy đủ theo hóa đơn')
                        PaymentNotice.objects.filter(pk=notice.pk).update(created_at=paid.recorded_at - timedelta(minutes=15))
                invoice.update_status()
                invoice_log.append(invoice)

        # One checked-out contract retains genuine debt and an unissued final invoice.
        ended = contracts[-1]
        old_debt = ended.invoices.filter(month=periods[3].month, year=periods[3].year).get()
        offset_amount = 400000
        offset_date = ended.checkout_date
        offset = Payment(invoice=old_debt, amount=offset_amount, method='tu_coc', paid_date=offset_date,
                         recorded_at=stamp(offset_date, 16), recorded_by=owner,
                         note='Thống nhất đối trừ một phần cọc vào hóa đơn còn nợ khi bàn giao')
        offset._from_deposit = True
        offset.full_clean()
        offset.save()
        DepositEntry.objects.create(contract=ended, kind='pay_invoice', amount=offset_amount, occurred_on=offset_date,
                                    method='internal', payment=offset, created_by=owner, note=offset.note)
        DepositEntry.objects.create(contract=ended, kind='deduct', amount=200000, occurred_on=offset_date,
                                    method='internal', created_by=owner, note='Thay khóa cửa bị hỏng theo biên bản bàn giao')
        ended_debt = sum(inv.total_amount - inv.total_paid() for inv in ended.invoices.all())
        CheckoutRecord.objects.create(contract=ended, checkout_date=ended.checkout_date,
            deposit_held=ended.deposit - offset_amount, deposit_deducted=200000, deposit_refunded=0,
            debt_at_checkout=ended_debt, drafts_at_checkout=1, refund_due_at_checkout=None,
            note='Đã bàn giao chìa khóa. Cọc còn giữ để đối chiếu hóa đơn tháng cuối và khoản còn nợ.',
            room_condition='bao_tri', created_by=owner)
        for contract in contracts:
            if contract.room.room_number in ('401', '403'):
                close_demo_contract(contract, owner, today)

        # Payment audit example: the original row remains visible, but contributes no money.
        audit_invoice = next(inv for inv in invoice_log if inv.contract.room.room_number == '102' and inv.month == today.month)
        wrong = add_payment(audit_invoice, 100000, today, 'tien_mat', 'Ghi nhận nhầm hình thức thanh toán')
        Payment.objects.filter(pk=wrong.pk).update(voided_at=stamp(today, 15), voided_by=owner,
                                                 void_reason='Đối chiếu sao kê: đây là chuyển khoản, không phải tiền mặt.')
        corrected = Payment(invoice=audit_invoice, amount=100000, method='chuyen_khoan', paid_date=today,
            recorded_at=stamp(today, 15, 5), recorded_by=owner, replaces=wrong, note='Ghi đúng hình thức theo sao kê')
        corrected.full_clean()
        corrected.save()

        for n, (code, title, category, status, days) in enumerate([
            ('101', 'Bóng đèn khu bếp chập chờn', 'dien', 'hoan_thanh', 45),
            ('102', 'Vòi lavabo rỉ nước', 'nuoc', 'hoan_thanh', 28),
            ('103', 'Điều hòa làm lạnh yếu', 'thiet_bi', 'dang_xu_ly', 3),
            ('201', 'Ổ khóa cửa phòng bị kẹt', 'khac', 'hoan_thanh', 12),
            ('202', 'Ổ cắm điện gần bàn học lỏng', 'dien', 'da_gui', 1),
            ('301', 'Bản lề tủ bếp bị lệch', 'noi_that', 'da_gui', 2),
            ('404', 'Thấm nước tại chân tường nhà vệ sinh', 'nuoc', 'hoan_thanh', 40),
        ]):
            contract = next(c for c in contracts if c.room.room_number == code)
            person = contract.contract_tenants.get(is_representative=True).tenant
            created_day = today - timedelta(days=days)
            if code == '404':
                created_day = min(created_day, contract.checkout_date - timedelta(days=1))
            repair = MaintenanceRequest.objects.create(room=contract.room, tenant=person, title=title,
                category=category, description=title + '. Nhờ chủ trọ kiểm tra và hỗ trợ xử lý.',
                priority='khan_cap' if code == '202' else 'binh_thuong', status=status,
                contact_method='dien_thoai' if n % 2 else 'web', contact_phone=person.phone if n % 2 else '',
                preferred_date=min(created_day + timedelta(days=1), today), preferred_slot='chieu',
                expected_done=today + timedelta(days=2) if status == 'dang_xu_ly' else None,
                owner_note='Đã kiểm tra và thay vật tư, người thuê xác nhận hoạt động bình thường.' if status == 'hoan_thanh' else
                           'Đã liên hệ thợ, đang sắp lịch kiểm tra.' if status == 'dang_xu_ly' else '',
                resolved_at=stamp(created_day + timedelta(days=2), 15) if status == 'hoan_thanh' else None)
            MaintenanceRequest.objects.filter(pk=repair.pk).update(created_at=stamp(created_day),
                updated_at=stamp(min(created_day + timedelta(days=2), today)))
            if code == '404':
                MaintenanceRequest.objects.filter(pk=repair.pk).update(resolved_at=stamp(today, 15),
                    updated_at=stamp(today, 15), owner_note='Đã chống thấm, vệ sinh và kiểm tra phòng; sẵn sàng cho thuê.')
        for index, (title, content, codes) in enumerate([
            ('Lịch vệ sinh khu vực chung', 'Khu để xe và hành lang được vệ sinh sáng Chủ nhật. Nhờ mọi người để gọn giày dép, xe và vật dụng cá nhân.', []),
            ('Kiểm tra điện cuối tháng', 'Chủ trọ kiểm tra và ghi chỉ số điện vào ngày 25. Tiền nước tính 50.000đ/người/tháng theo số người đã chốt.', []),
            ('Lịch kiểm tra điều hòa tầng 1', 'Thợ đến kiểm tra điều hòa vào chiều thứ Bảy. Nhờ các phòng sắp xếp người mở cửa hoặc báo lại giờ thuận tiện.', ['103']),
        ]):
            announcement = Announcement.objects.create(title=title, content=content, created_by=owner,
                audience='rooms' if codes else 'all', is_active=True)
            announcement.rooms.set(rooms[code] for code in codes)
            Announcement.objects.filter(pk=announcement.pk).update(created_at=stamp(today - timedelta(days=8 - index * 3)),
                updated_at=stamp(today - timedelta(days=8 - index * 3)))
        # The already approved second resident has no login account.
        approved_request = CoOccupantRequest.objects.create(contract=contracts[0], submitted_by=people[0],
            full_name=people[1].full_name, id_card_number=people[1].id_card_number, phone=people[1].phone,
            email=people[1].email, date_of_birth=people[1].date_of_birth, hometown=people[1].hometown,
            occupation=people[1].occupation, status='approved', reviewed_at=stamp(contracts[0].start_date),
            reviewed_by=owner, approved_tenant=people[1], review_note='Đã đối chiếu hồ sơ và cập nhật vào hợp đồng.',
            **{key: getattr(people[1], key) for key in ('document_type', 'gender', 'nationality', 'place_of_birth',
                'birth_registration_place', 'permanent_address', 'identity_issued_on', 'identity_expires_on', 'identity_issued_by')})
        CoOccupantRequest.objects.filter(pk=approved_request.pk).update(created_at=stamp(contracts[0].start_date, 9))
        CoOccupantRequest.objects.create(contract=contracts[2], submitted_by=people[4],
            full_name='Nguyễn Thị Thùy Dương', id_card_number=random_identity(used_ids),
            phone=random_phone('0961', used_phones),
            email='nguyenthithuyduong@example.com', date_of_birth=date(1998, 8, 14),
            occupation='Nhân viên tư vấn', hometown='Phường Hòa Cường, thành phố Đà Nẵng',
            document_type='cccd', gender='female', nationality='Việt Nam', place_of_birth='Đà Nẵng',
            birth_registration_place='Phường Hòa Cường, thành phố Đà Nẵng',
            permanent_address='Tổ 18, phường Hòa Cường, thành phố Đà Nẵng',
            identity_issued_on=date(2025, 8, 11), identity_expires_on=date(2038, 8, 14),
            identity_issued_by='Cục Cảnh sát quản lý hành chính về trật tự xã hội',
            note='Xin bổ sung người ở cùng vào phòng; dự kiến chuyển vào đầu tháng tới.')
        AppointmentCalendar.objects.get_or_create(pk=1)
        visitors = [('Nguyễn Tuấn Kiệt', '104', 'cho_xac_nhan', 1, None),
                    ('Trần Thị Mai Anh', '204', 'da_xac_nhan', 2, time(9)),
                    ('Lê Anh Duy', '304', 'da_xem', -3, time(14)),
                    ('Phạm Thị Bích Ngọc', '104', 'huy', 3, None)]
        for index, (name, code, status, delta, hour) in enumerate(visitors):
            appointment = ViewingAppointment(room=rooms[code], code=f'LHDN{index + 1:04d}',
                visitor_name=name, visitor_phone=random_phone(PHONE_PREFIXES[index], used_phones),
                visitor_email=normalize(name).replace(' ', '').lower() + '@example.com',
                appointment_date=today + timedelta(days=delta), slot='chieu' if hour and hour.hour >= 13 else 'sang',
                start_time=hour, status=status, note='Muốn xem phòng cho hai người đi làm.',
                owner_note='Đã hẹn giờ và hướng dẫn chỗ để xe.' if status == 'da_xac_nhan' else
                           'Khách đã xem, cần trao đổi thêm với người ở cùng.' if status == 'da_xem' else '',
                cancelled_by='guest' if status == 'huy' else '', cancelled_at=stamp(today, 9) if status == 'huy' else None,
                cancellation_reason='Lịch công tác thay đổi, xin hẹn vào dịp khác.' if status == 'huy' else '')
            appointment.full_clean()
            ViewingAppointment.objects.bulk_create([appointment])
            ViewingAppointment.objects.filter(pk=appointment.pk).update(created_at=stamp(today - timedelta(days=5 + index)))

    # Check data through the application, not only SQLite's foreign-key checker.
    audit = StringIO()
    call_command('audit_rental_data', fail_on_errors=True, stdout=audit)
    assert Room.objects.count() == 16 and Tenant.objects.count() == 26
    assert Room.objects.filter(status='dang_thue').count() == 10
    assert Room.objects.filter(status='trong').count() == 6
    for room in Room.objects.filter(status='trong'):
        assert not room.contracts.filter(status='hieu_luc').exists()
    for person in people:
        person.full_clean()
        assert not person.identity_missing_labels
        assert not person.identity_expired
    for invoice in Invoice.objects.select_related('utility_reading'):
        services = sum(invoice.invoice_services.values_list('subtotal', flat=True))
        assert invoice.total_amount == invoice.room_fee + invoice.electric_fee + invoice.water_fee + services
        assert 0 <= invoice.total_paid() <= invoice.total_amount
        assert invoice.water_fee == invoice.water_people_count * invoice.water_unit_price
        assert invoice.electric_calculation_matches
    assert all(c.deposit_balance >= 0 for c in Contract.objects.all())
    __import__('django.db', fromlist=['connection']).connection.check_constraints()
    export_workbook(target.parent, today, first)
    summary = {'rooms': Room.objects.count(), 'tenants': Tenant.objects.count(),
        'active_contracts': Contract.objects.filter(status='hieu_luc').count(),
        'ended_contracts': Contract.objects.filter(status='ket_thuc').count(),
        'invoices': Invoice.objects.count(), 'drafts': InvoiceDraft.objects.count(), 'payments': Payment.objects.count(),
        'current_people': ContractTenant.objects.filter(contract__status='hieu_luc').count(),
        'repair_requests': MaintenanceRequest.objects.count(), 'appointments': ViewingAppointment.objects.count(),
        'first_period': first.isoformat(), 'last_period': today.replace(day=1).isoformat(),
        'audit': audit.getvalue()}
    (target.parent / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key != 'audit'}, ensure_ascii=False))


def export_workbook(folder, today, first):
    from django.utils import timezone
    from billing.models import Invoice, InvoiceDraft, Payment, UtilityReading
    from rooms.models import Contract, CoOccupantRequest, DepositEntry, PropertyInfo, Room, ViewingAppointment
    from accounts.models import Tenant
    from support.models import MaintenanceRequest
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    book = Workbook()
    book.remove(book.active)
    def sheet(title, headers, rows):
        ws = book.create_sheet(title)
        ws.append(headers)
        for row in rows:
            ws.append(row)
        for row in ws:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                elif isinstance(cell.value, date):
                    cell.number_format = 'dd/mm/yyyy'
                elif '(đ)' in headers[cell.column - 1] and isinstance(cell.value, (Decimal, int)):
                    cell.number_format = '#,##0'
                elif isinstance(cell.value, Decimal) and cell.value != cell.value.to_integral_value():
                    cell.number_format = '#,##0.00'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for cell in ws[1]:
            cell.fill = PatternFill('solid', fgColor='B55238')
            cell.font = Font(color='FFFFFF', bold=True)
        for index, header in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(index)].width = 42 if any(s in header for s in ('Địa chỉ', 'Ghi chú', 'Nội dung')) else 25
        ws.freeze_panes = 'B2'
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.print_title_rows = '1:1'
        return ws
    sheet('Hướng dẫn', ['Mục', 'Nội dung'], [
        ['Bộ dữ liệu', 'Nhà trọ Minh Tâm · Đà Nẵng · 4 tầng × 4 phòng = 16 phòng · 10 đang thuê, 6 đang trống · 26 hồ sơ người thuê'],
        ['Phạm vi lịch sử', f'Từ tháng {first.month}/{first.year} đến tháng {today.month}/{today.year}'],
        ['Tính chất', 'Toàn bộ nhân vật, số giấy tờ, điện thoại, địa chỉ thường trú và email là hư cấu để mô phỏng; không dùng để liên hệ hoặc khai báo lưu trú thật.'],
        ['Email', 'Dùng tên miền example.com; quá trình nạp không gửi email.'],
        ['CCCD và điện thoại mô phỏng', 'CCCD bắt đầu 045, 9 chữ số còn lại ngẫu nhiên, không đánh số thứ tự. Điện thoại dùng nhiều đầu số và phần đuôi ngẫu nhiên.'],
        ['Quê quán và địa chỉ', 'Quê quán giữ tên vùng quen thuộc, gồm cả tên tỉnh cũ. Địa chỉ thường trú dùng tên đơn vị hành chính hiện hành; TP. Hồ Chí Minh tương ứng cách gọi Sài Gòn. Nguồn: https://baochinhphu.vn/nghi-quyet-cua-quoc-hoi-ve-sap-xep-don-vi-hanh-chinh-cap-tinh-102250612191145158.htm'],
        ['Tài khoản', 'Chỉ người đại diện hợp đồng có tài khoản. Tên đăng nhập và mật khẩu khởi tạo là số căn cước mô phỏng. Tài khoản chủ trọ/quản trị giữ nguyên.'],
        ['Giá mẫu', 'Điện 3.500đ/kWh; nước 50.000đ/người/tháng; Wi-Fi 100.000đ/phòng/tháng; vệ sinh và rác 20.000đ/phòng/tháng.'],
        ['Chỉ số điện', 'Chu kỳ chốt mẫu vào ngày 25; kỳ chưa chốt được để nháp. Nước tính đủ tháng theo số người đã chốt.'],
        ['Ảnh', 'Giữ ảnh phòng đã có cho đúng số phòng. Ảnh căn cước để trống, không tạo ảnh giấy tờ giả.'],
        ['Tên đơn vị hành chính', 'Đối chiếu danh sách phường Đà Nẵng theo Nghị quyết 1659/NQ-UBTVQH15: https://xaydungchinhsach.chinhphu.vn/toan-van-nghi-quyet-so-1659-nq-ubtvqh15-sap-xep-cac-dvhc-cap-xa-cua-thanh-pho-da-nang-nam-2025-119250616202714604.htm'],
        ['Tình huống', '20 người đang ở và 6 người đã bàn giao; có hóa đơn trả đủ, trả từng phần, quá hạn, chờ xác nhận chuyển khoản, điều chỉnh giao dịch, cọc còn giữ sau bàn giao và nháp chưa chốt.'],
    ])
    rooms = list(Room.objects.order_by('floor', 'room_number'))
    sheet('Tiện ích nhà trọ', ['Tiện ích chung'], [[name] for name in PropertyInfo.current().amenity_list])
    sheet('Phòng', ['Phòng', 'Tầng', 'Diện tích (m²)', 'Sức chứa', 'Giá niêm yết (đ)', 'Trạng thái', 'Tiện ích', 'Mô tả', 'Số ảnh'],
        [[r.room_number, r.floor, r.area, r.max_occupants, r.price, r.get_status_display(), r.amenities, r.description, r.photos.count()] for r in rooms])
    people = list(Tenant.objects.order_by('pk'))
    sheet('Hồ sơ người thuê', ['Họ và tên', 'Số căn cước', 'Ngày sinh', 'Giới tính', 'Quốc tịch', 'Điện thoại', 'Email', 'Nghề nghiệp', 'Quê quán', 'Nơi sinh', 'Nơi đăng ký khai sinh', 'Địa chỉ thường trú', 'Ngày cấp', 'Ngày hết hạn', 'Nơi cấp', 'Phòng', 'Vai trò', 'Tình trạng'],
        [[p.full_name, p.id_card_number, p.date_of_birth, p.get_gender_display(), p.nationality, p.phone, p.email, p.occupation,
          p.hometown, p.place_of_birth, p.birth_registration_place, p.permanent_address, p.identity_issued_on,
          p.identity_expires_on, p.identity_issued_by, p.contract_tenants.first().contract.room.room_number,
          'Đại diện' if p.user_id else 'Ở cùng', 'Đang thuê' if p.contract_tenants.filter(contract__status='hieu_luc').exists() else 'Đã trả phòng'] for p in people])
    contracts = list(Contract.objects.select_related('room').order_by('pk'))
    sheet('Hợp đồng', ['Mã', 'Phòng', 'Người đại diện', 'Từ ngày', 'Đến ngày', 'Ngày bàn giao', 'Giá thuê (đ)', 'Cọc thỏa thuận (đ)', 'Cọc còn giữ (đ)', 'Điện nhận phòng', 'Trạng thái'],
        [[c.display_code, c.room.room_number, c.contract_tenants.get(is_representative=True).tenant.full_name,
          c.start_date, c.end_date, c.checkout_date, c.agreed_rent, c.deposit, c.deposit_balance, c.initial_electric, c.get_status_display()] for c in contracts])
    invoices = list(Invoice.objects.select_related('contract__room').order_by('year', 'month', 'contract__room__room_number'))
    sheet('Hóa đơn', ['Mã', 'Phòng', 'Hợp đồng', 'Tháng', 'Năm', 'Phòng (đ)', 'Điện (đ)', 'Nước (đ)', 'Số người tính nước', 'Dịch vụ (đ)', 'Tổng (đ)', 'Đã thanh toán (đ)', 'Còn nợ (đ)', 'Hạn thanh toán', 'Trạng thái'],
        [[i.pk, i.contract.room.room_number, i.contract.display_code, i.month, i.year, i.room_fee, i.electric_fee,
          i.water_fee, i.water_people_count, sum(i.invoice_services.values_list('subtotal', flat=True)),
          i.total_amount, i.total_paid(), i.total_amount - i.total_paid(), i.due_date, i.get_status_display()] for i in invoices])
    sheet('Chỉ số điện', ['Phòng', 'Hợp đồng', 'Tháng', 'Năm', 'Chỉ số cũ', 'Chỉ số mới', 'Tiêu thụ (kWh)'],
        [[r.room.room_number, r.contract.display_code, r.month, r.year, r.old_electric, r.new_electric, r.electric_usage()]
         for r in UtilityReading.objects.select_related('room', 'contract').order_by('year', 'month', 'room__room_number')])
    sheet('Thanh toán', ['Mã', 'Phòng', 'Hợp đồng', 'Kỳ hóa đơn', 'Ngày thu', 'Số tiền (đ)', 'Phương thức', 'Trạng thái', 'Thay thế', 'Ghi chú'],
        [[p.display_code, p.invoice.contract.room.room_number, p.invoice.contract.display_code,
          f'{p.invoice.month}/{p.invoice.year}', p.paid_date, p.amount, p.get_method_display(),
          'Đã hủy, không cộng tiền' if p.is_voided else 'Có hiệu lực', p.replaces.display_code if p.replaces_id else '', p.void_reason if p.is_voided else p.note]
         for p in Payment.objects.select_related('invoice__contract__room', 'replaces').order_by('paid_date', 'pk')])
    sheet('Sổ cọc', ['Ngày', 'Phòng', 'Hợp đồng', 'Loại', 'Số tiền (đ)', 'Phương thức', 'Ghi chú'],
        [[e.occurred_on, e.contract.room.room_number, e.contract.display_code, e.get_kind_display(), e.amount,
          e.get_method_display(), e.note] for e in DepositEntry.objects.select_related('contract__room').order_by('occurred_on', 'pk')])
    sheet('Nháp chưa chốt', ['Phòng', 'Hợp đồng', 'Tháng', 'Năm', 'Tiền phòng (đ)', 'Điện cũ', 'Điện mới', 'Số người tính nước', 'Giá nước (đ)', 'Ghi chú'],
        [[d.contract.room.room_number, d.contract.display_code, d.month, d.year, d.room_fee, d.old_electric,
          d.new_electric, d.water_people_count, d.water_unit_price, d.note]
         for d in InvoiceDraft.objects.select_related('contract__room').order_by('year', 'month', 'pk')])
    sheet('Sửa chữa', ['Mã', 'Phòng', 'Người gửi', 'Nội dung', 'Ngày gửi', 'Trạng thái', 'Lời nhắn chủ trọ'],
        [[r.display_code, r.room.room_number, r.tenant.full_name, r.title, timezone.localtime(r.created_at).date(),
          r.get_status_display(), r.owner_note] for r in MaintenanceRequest.objects.select_related('room', 'tenant').order_by('created_at')])
    sheet('Lịch hẹn', ['Mã', 'Phòng', 'Khách', 'Điện thoại', 'Email', 'Ngày hẹn', 'Giờ', 'Trạng thái', 'Lý do hủy'],
        [[a.code, a.room.room_number, a.visitor_name, a.visitor_phone, a.visitor_email, a.appointment_date,
          a.start_time.isoformat() if a.start_time else '', a.get_status_display(), a.cancellation_reason]
         for a in ViewingAppointment.objects.select_related('room').order_by('appointment_date')])
    sheet('Hồ sơ người ở cùng', ['Phòng', 'Người đề nghị', 'Người ở cùng', 'Số căn cước', 'Điện thoại', 'Ngày sinh', 'Địa chỉ thường trú', 'Trạng thái', 'Ghi chú'],
        [[r.contract.room.room_number, r.submitted_by.full_name, r.full_name, r.id_card_number,
          r.phone, r.date_of_birth, r.permanent_address, r.get_status_display(), r.review_note or r.note]
         for r in CoOccupantRequest.objects.select_related('contract__room', 'submitted_by').order_by('pk')])
    sheet('Tài khoản người thuê', ['Người đại diện', 'Phòng', 'Tên đăng nhập', 'Mật khẩu khởi tạo', 'Tình trạng'],
        [[p.full_name, p.contract_tenants.get(is_representative=True).contract.room.room_number,
          p.user.username, p.id_card_number, 'Đang thuê' if p.contract_tenants.filter(contract__status='hieu_luc').exists() else 'Đã trả phòng']
         for p in people if p.user_id])
    book.properties.title = 'Dữ liệu mô phỏng quản lý nhà trọ tại Đà Nẵng'
    book.save(folder / 'Du_lieu_nha_tro_Da_Nang_16_phong_26_nguoi.xlsx')


def verify_database(target):
    """Exercise actual owner/tenant pages inside a transaction that is rolled back."""
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = target
    settings.EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
    settings.ALLOWED_HOSTS = ['testserver']
    import django
    django.setup()
    from django.contrib.auth import authenticate
    from django.db import transaction
    from django.test import Client
    from django.test.utils import setup_test_environment
    from django.urls import reverse
    from django.utils import timezone
    from openpyxl import load_workbook
    from accounts.models import Tenant, User
    from billing.models import Invoice, Payment, UtilityRate
    from reports.services import ReportPeriod, build_report
    from rooms.models import Contract, CoOccupantRequest, Room, ViewingAppointment

    setup_test_environment()
    book = load_workbook(target.parent / 'Du_lieu_nha_tro_Da_Nang_16_phong_26_nguoi.xlsx', data_only=False)
    assert book['Phòng'].max_row == 17 and book['Hồ sơ người thuê'].max_row == 27
    assert book['Tài khoản người thuê'].max_row == 14
    assert all(book['Hồ sơ người thuê'].cell(row, 2).data_type == 's' for row in range(2, 28))
    assert all(book['Hồ sơ người thuê'].cell(row, 6).data_type == 's' for row in range(2, 28))
    assert Room.objects.filter(status='trong').count() == 6
    assert Room.objects.filter(status='dang_thue').count() == 10
    assert Room.objects.filter(status='bao_tri').count() == 0
    assert Contract.objects.filter(status='ket_thuc').count() == 3
    for room in Room.objects.filter(status='trong'):
        assert not room.contracts.filter(status='hieu_luc').exists()
    assert CoOccupantRequest.objects.filter(status='pending').count() == 1
    today = timezone.localdate()
    assert not Payment.objects.filter(paid_date__gt=today).exists()
    for payment in Payment.objects.select_related('invoice', 'replaces'):
        assert payment.recorded_at <= timezone.now()
        assert payment.paid_date >= timezone.localtime(payment.invoice.created_at).date()
        if payment.replaces_id:
            assert payment.replaces.is_voided
    rate = UtilityRate.current()
    assert (rate.electric_price, rate.water_price) == (3500, 50000)
    report = build_report(ReportPeriod(today.year, today.month))
    assert sum(bucket['amount'] for bucket in report['aging']) == report['total_debt']
    assert report['people_count'] == 20
    assert len(report['expiring']) == 2
    dp = report['deposit_period']
    assert dp['opening'] + dp['receive'] + dp['transfer_in'] - dp['refund'] - dp['deduct'] - dp['pay_invoice'] - dp['transfer_out'] == dp['closing']
    before = (Invoice.objects.count(), Payment.objects.count())
    with transaction.atomic():
        client = Client()
        client.force_login(User.objects.get(role='owner'))
        for route in ('owner_dashboard', 'room_list', 'tenant_list', 'contract_list', 'invoice_list',
                      'invoice_drafts', 'appointment_list', 'maintenance_list', 'cooccupant_review_list',
                      'report_dashboard', 'report_print', 'report_excel'):
            response = client.get(reverse(route))
            assert response.status_code == 200, (route, response.status_code)
        for invoice in Invoice.objects.order_by('pk'):
            assert client.get(reverse('invoice_detail', args=[invoice.pk])).status_code == 200
        for tenant in Tenant.objects.filter(user__isnull=False):
            account = authenticate(username=tenant.user.username, password=tenant.id_card_number)
            assert account is not None
            client.force_login(account)
            for route in ('my_room', 'my_profile', 'my_invoices', 'my_payments', 'my_contracts'):
                assert client.get(reverse(route)).status_code == 200, (route, tenant.pk)
        client.logout()
        for room in Room.objects.filter(status='trong'):
            assert client.get(reverse('public_room_detail', args=[room.pk])).status_code == 200
        for appointment in ViewingAppointment.objects.all():
            assert client.get(reverse('appointment_status', args=[appointment.code])).status_code == 200
        transaction.set_rollback(True)
    assert (Invoice.objects.count(), Payment.objects.count()) == before
    print('Verified workbook text/date fields, all owner pages and invoice details, 13 tenant logins/portals, '
          'vacant-room booking pages, guest lookups, payment dates, debt aging and deposit reconciliation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Install the verified dataset into local db.sqlite3')
    parser.add_argument('--build-db', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--snapshot', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--verify-db', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_db:
        assert args.verify_db.resolve().is_relative_to((ROOT / '.backups' / 'rental-data').resolve())
        verify_database(args.verify_db)
        return
    if args.build_db:
        folder = (ROOT / '.backups' / 'rental-data').resolve()
        assert args.build_db.resolve().is_relative_to(folder)
        assert not args.build_db.exists()
        build_database(args.build_db, json.loads(args.snapshot.read_text(encoding='utf-8')))
        return
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth.models import Group
    from django.contrib.sessions.models import Session
    from django.db import connections
    from django.db.models import Q
    from django.utils import timezone
    from accounts.models import User
    from billing.models import BankAccount
    from rooms.models import PropertyInfo, RoomPhoto
    if not settings.DEBUG or settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
        raise SystemExit('This dataset installer is only for the local SQLite development database.')
    live = Path(settings.DATABASES['default']['NAME']).resolve()
    if live != (ROOT / 'db.sqlite3').resolve():
        raise SystemExit('The live target must be this workspace\'s db.sqlite3.')
    folder = ROOT / '.backups' / 'rental-data' / datetime.now().strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    backup = folder / 'before.sqlite3'
    source = sqlite3.connect(live)
    with sqlite3.connect(backup) as saved:
        source.backup(saved)
    original_version = source.execute('PRAGMA data_version').fetchone()[0]
    keep = list(User.objects.filter(Q(role='owner') | Q(is_superuser=True)).order_by('pk'))
    ids = {u.pk for u in keep}
    sessions = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if str(session.get_decoded().get('_auth_user_id', '')) in {str(pk) for pk in ids}:
            sessions.append(model_values(session))
    snapshot = {'today': timezone.localdate().isoformat(), 'users': [model_values(u) for u in keep],
        'bank': model_values(BankAccount.objects.first()) if BankAccount.objects.exists() else None,
        'property': model_values(PropertyInfo.current()),
        'groups': [{'name': group.name, 'permissions': [p.natural_key() for p in group.permissions.all()]}
                   for group in Group.objects.all()],
        'memberships': [{'id': u.pk, 'groups': list(u.groups.values_list('name', flat=True)),
                         'permissions': [p.natural_key() for p in u.user_permissions.all()]} for u in keep],
        'sessions': sessions,
        'photos': [{'room_number': photo.room.room_number, 'image': photo.image.name,
                    'caption': photo.caption, 'position': photo.position}
                   for photo in RoomPhoto.objects.select_related('room')]}
    snapshot_path = folder / 'preserved-settings.json'
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, default=json_value), encoding='utf-8')
    for name, path in [('media', settings.MEDIA_ROOT), ('private-media', settings.PRIVATE_MEDIA_ROOT)]:
        if Path(path).exists():
            shutil.copytree(path, folder / name)
    staged = folder / 'prepared.sqlite3'
    env = {**os.environ, 'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend'}
    subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--build-db', str(staged),
                    '--snapshot', str(snapshot_path)], env=env, check=True)
    subprocess.run([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--verify-db', str(staged)], env=env, check=True)
    with sqlite3.connect(staged) as prepared:
        assert prepared.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not prepared.execute('PRAGMA foreign_key_check').fetchall()
        for user in keep:
            row = prepared.execute('SELECT password,role,is_superuser FROM accounts_user WHERE id=?', (user.pk,)).fetchone()
            assert row == (user.password, user.role, int(user.is_superuser))
        if args.install:
            if source.execute('PRAGMA data_version').fetchone()[0] != original_version:
                raise SystemExit('Dữ liệu đã thay đổi trong lúc chuẩn bị. Bộ dữ liệu mới đã lưu riêng; chưa thay dữ liệu đang dùng.')
            connections.close_all()
            prepared.backup(source)
            assert source.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            print('Installed verified dataset into local db.sqlite3; privileged logins and banking configuration preserved.')
        else:
            print('Prepared only. The live database has not been changed.')
    source.close()
    print('Backup and workbook folder:', folder)


if __name__ == '__main__':
    main()
