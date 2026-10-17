from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.models import Invoice


def fmt(amount):
    return f'{amount:,.0f}'.replace(',', '.')


class Command(BaseCommand):
    help = 'Quét hóa đơn quá hạn: cập nhật trạng thái và gửi email nhắc người đại diện.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Chỉ liệt kê hóa đơn quá hạn, không đổi dữ liệu và không gửi email.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.localdate()

        invoices = Invoice.objects.filter(
            status__in=[Invoice.Status.CHUA_THANH_TOAN, Invoice.Status.QUA_HAN],
            due_date__lt=today,
            reminded_at__isnull=True,
        ).select_related('contract__room')

        marked = sent = skipped = 0

        for invoice in invoices:
            paid = invoice.total_paid()
            remaining = invoice.total_amount - paid
            if remaining <= 0:
                continue

            room = invoice.contract.room
            label = f'HĐ #{invoice.pk} ({room}, T{invoice.month}/{invoice.year})'

            if dry_run:
                self.stdout.write(f'[dry-run] {label}: còn nợ {fmt(remaining)}đ')
                continue

            invoice.update_status()  # chuyển sang Quá hạn
            marked += 1

            rep = (
                invoice.contract.contract_tenants
                .filter(is_representative=True)
                .select_related('tenant')
                .first()
            )
            email = rep.tenant.email if rep else None
            if not email:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f'{label}: người đại diện chưa có email, chưa gửi được.'
                ))
                continue

            message = (
                f'Chào {rep.tenant.full_name},\n\n'
                f'Hóa đơn tháng {invoice.month}/{invoice.year} của phòng {room.room_number} '
                f'đã quá hạn thanh toán từ ngày {invoice.due_date:%d/%m/%Y}.\n\n'
                f'Tổng tiền: {fmt(invoice.total_amount)}đ\n'
                f'Đã thanh toán: {fmt(paid)}đ\n'
                f'Còn nợ: {fmt(remaining)}đ\n\n'
                f'Vui lòng thanh toán sớm cho chủ trọ. Xin cảm ơn.\n'
                f'Nhà trọ Minh Tâm'
            )
            try:
                send_mail(
                    f'[Nhà trọ Minh Tâm] Hóa đơn tháng {invoice.month}/{invoice.year} đã quá hạn',
                    message, None, [email],
                )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'{label}: gửi email lỗi ({exc})'))
                continue

            Invoice.objects.filter(pk=invoice.pk).update(reminded_at=today)
            sent += 1

        if dry_run:
            return
        self.stdout.write(self.style.SUCCESS(
            f'Hoàn tất: {marked} hóa đơn quá hạn, đã gửi {sent} email, bỏ qua {skipped} (thiếu email).'
        ))