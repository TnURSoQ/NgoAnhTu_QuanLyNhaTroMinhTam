from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from billing.drafts import generate_monthly_drafts


class Command(BaseCommand):
    help = 'Tạo hóa đơn nháp cho tháng hiện tại; chạy lại không tạo trùng, không phát hành hóa đơn.'

    def add_arguments(self, parser):
        parser.add_argument('--month', type=int)
        parser.add_argument('--year', type=int)
        parser.add_argument('--dry-run', action='store_true', help='Chỉ đếm số nháp cần tạo, không lưu dữ liệu.')

    def handle(self, *args, **options):
        if (options['month'] is None) != (options['year'] is None):
            raise CommandError('Cần truyền cả --month và --year hoặc bỏ trống cả hai.')
        today = timezone.localdate()
        month = options['month'] if options['month'] is not None else today.month
        year = options['year'] if options['year'] is not None else today.year
        try:
            count = generate_monthly_drafts(month, year, dry_run=options['dry_run'])
        except ValidationError as exc:
            raise CommandError('; '.join(exc.messages)) from exc
        label = '[dry-run] Sẽ tạo' if options['dry_run'] else 'Đã tạo'
        self.stdout.write(self.style.SUCCESS(f'{label} {count} bản nháp tháng {month}/{year}.'))
