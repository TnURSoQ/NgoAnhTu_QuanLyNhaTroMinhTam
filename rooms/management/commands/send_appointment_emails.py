from django.core.management.base import BaseCommand, CommandError

from rooms.appointment_emails import configuration_problem, dispatch_safely, pending_email_ids, preview_mode
from rooms.models import AppointmentEmail


class Command(BaseCommand):
    help = 'Gửi/gửi lại email lịch hẹn đang chờ, bỏ qua thư đã gửi và thông tin đã cũ.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--check-config', action='store_true', help='Chỉ kiểm tra cấu hình, không gửi thư.')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 1000:
            raise CommandError('--limit phải nằm trong khoảng 1..1000.')
        problem = configuration_problem()
        if problem:
            raise CommandError(f'Chưa sẵn sàng gửi email ({problem}). Kiểm tra cấu hình trong .env.')
        if options['check_config']:
            if preview_mode():
                raise CommandError('Đang ở chế độ xem thử. Cần cấu hình gửi thư thật trước khi bật lịch gửi lại.')
            self.stdout.write('Đủ thông tin cấu hình gửi email; chưa kiểm tra đăng nhập hoặc gửi thư thật.')
            return
        ids = pending_email_ids(options['limit'])
        for pk in ids:
            dispatch_safely(pk)
        sent = AppointmentEmail.objects.filter(pk__in=ids, status=AppointmentEmail.Status.SENT).count()
        self.stdout.write(f'Đã xử lý {len(ids)} email; máy chủ thư tiếp nhận {sent}.')
        if preview_mode():
            self.stdout.write('Đang ở chế độ xem thử; chưa gửi email thật tới khách.')
