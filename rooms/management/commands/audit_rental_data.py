"""Kiểm tra chất lượng dữ liệu; không tự sửa lịch sử hay suy đoán tiền đã thu."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from billing.models import Payment, UtilityRate, WaterBillingMethod
from rooms.models import Contract, Room


class Command(BaseCommand):
    help = 'Rà soát dữ liệu phòng, hợp đồng, bàn giao, cọc và chỉ số chưa chốt (chỉ đọc).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--fail-on-errors', action='store_true')

    def handle(self, *args, **options):
        issues = []
        rate = UtilityRate.current()
        metered_water = bool(rate and rate.water_billing_method == WaterBillingMethod.METERED)

        def add(level, kind, code, message):
            issues.append({'level': level, 'kind': kind, 'code': code, 'message': message})

        for room in Room.objects.all():
            active = room.contracts.filter(status=Contract.Status.HIEU_LUC)
            if active.exists() and room.status != Room.Status.DANG_THUE:
                add('error', 'room_status', f'P.{room.room_number}', 'Có hợp đồng hiệu lực nhưng trạng thái phòng không phải đang thuê.')
            if not active.exists() and room.status == Room.Status.DANG_THUE:
                add('warning', 'room_status', f'P.{room.room_number}', 'Phòng đang thuê nhưng không có hợp đồng hiệu lực.')
        for contract in Contract.objects.filter(status=Contract.Status.HIEU_LUC).select_related('room'):
            members = contract.contract_tenants
            if members.filter(is_representative=True).count() != 1:
                add('error', 'representative', contract.display_code, 'Cần đúng một người đại diện hợp đồng.')
            if members.count() > contract.room.max_occupants:
                add('error', 'capacity', contract.display_code, 'Số người ở vượt sức chứa phòng.')
            if contract.initial_electric is None or (metered_water and contract.initial_water is None):
                add('warning', 'handover', contract.display_code, 'Chưa ghi nhận đủ chỉ số công tơ lúc nhận phòng; cần đối chiếu lịch sử thực tế.')
            balance = contract.deposit_balance
            if balance < 0:
                add('error', 'deposit', contract.display_code, 'Số dư cọc không hợp lệ so với thỏa thuận.')
            elif balance > contract.agreed_deposit:
                add('warning', 'deposit', contract.display_code, 'Cọc còn giữ cao hơn mức thỏa thuận hiện tại; cần đối chiếu việc hoàn / giữ bảo đảm công nợ, không tự ghi nhận hoàn tiền.')
            elif balance < contract.agreed_deposit:
                add('warning', 'deposit', contract.display_code, 'Cọc thực thu chưa đủ hoặc chưa được ghi nhận; không được tự suy đoán đã thu.')
            if contract.invoice_drafts.filter(invoice__isnull=True).exists():
                add('warning', 'drafts', contract.display_code, 'Còn hóa đơn nháp chờ nhập chỉ số hoặc chốt.')
            if contract.end_date < timezone.localdate():
                add('warning', 'expiry', contract.display_code, 'Hết thời hạn hợp đồng; cần gia hạn hoặc làm thủ tục trả phòng.')
        if Payment.objects.active().filter(paid_date__gt=timezone.localdate()).exists():
            add('error', 'payment_date', 'PAYMENT', 'Có giao dịch thu tiền mang ngày ở tương lai.')
        summary = {'rooms': Room.objects.count(), 'contracts': Contract.objects.count(),
                   'errors': sum(item['level'] == 'error' for item in issues),
                   'warnings': sum(item['level'] == 'warning' for item in issues), 'issues': issues}
        if options['json']:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"Rà soát {summary['rooms']} phòng, {summary['contracts']} hợp đồng: "
                              f"{summary['errors']} lỗi, {summary['warnings']} mục cần kiểm tra.")
            for item in issues:
                self.stdout.write(f"[{item['level']}] {item['code']}: {item['message']}")
        if options['fail_on_errors'] and summary['errors']:
            raise CommandError('Có dữ liệu cần xử lý. Chưa tự thay đổi dữ liệu nào.')
