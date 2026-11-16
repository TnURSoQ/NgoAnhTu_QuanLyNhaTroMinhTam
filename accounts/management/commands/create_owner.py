from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = 'Tạo hoặc cập nhật tài khoản chủ trọ, không có quyền quản trị hệ thống.'

    def add_arguments(self, parser):
        parser.add_argument('username', help='Tên đăng nhập')
        parser.add_argument('--name', default=None, help='Tên hiển thị, ví dụ "Hà Thị Minh Tâm"')
        parser.add_argument('--password', default=None,
                            help='Mật khẩu. Bỏ trống để được hỏi (gõ không hiện ký tự).')

    def handle(self, *args, **options):
        username = options['username']
        user = User.objects.filter(username=username).first()
        if user:
            user.role = User.Role.OWNER
            user.is_staff = False
            user.is_superuser = False
            update_fields = ['role', 'is_staff', 'is_superuser']
            if options['name'] is not None:
                user.first_name = options['name']
                user.last_name = ''
                update_fields.extend(['first_name', 'last_name'])
            user.save(update_fields=update_fields)
            self.stdout.write(self.style.SUCCESS(
                f'Đã gán vai trò chủ trọ cho tài khoản có sẵn "{username}", '
                'không có quyền quản trị hệ thống (mật khẩu giữ nguyên).'))
            return

        password = options['password']
        if password is None:
            password = getpass('Mật khẩu: ')
            if password != getpass('Nhập lại mật khẩu: '):
                raise CommandError('Hai mật khẩu không khớp.')
        try:
            validate_password(password)
        except ValidationError as e:
            raise CommandError(' '.join(e.messages))

        User.objects.create_user(username, password=password, first_name=options['name'] or '',
                                 role=User.Role.OWNER)
        self.stdout.write(self.style.SUCCESS(f'Đã tạo tài khoản chủ trọ "{username}".'))
