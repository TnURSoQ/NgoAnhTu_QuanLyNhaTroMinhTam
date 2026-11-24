from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage
import uuid
from pathlib import Path


def maintenance_storage():
    return FileSystemStorage(location=getattr(settings, 'PRIVATE_MEDIA_ROOT', settings.BASE_DIR / 'private-media'))


def maintenance_photo_path(instance, filename):
    return f'maintenance/{instance.maintenance_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class MaintenanceRequest(models.Model):
    class Category(models.TextChoices):
        DIEN = 'dien', 'Điện'
        NUOC = 'nuoc', 'Nước'
        THIET_BI = 'thiet_bi', 'Thiết bị / điều hòa'
        NOI_THAT = 'noi_that', 'Nội thất'
        KHAC = 'khac', 'Khác'

    class Priority(models.TextChoices):
        BINH_THUONG = 'binh_thuong', 'Bình thường'
        KHAN_CAP = 'khan_cap', 'Khẩn cấp'
        RAT_KHAN_CAP = 'rat_khan_cap', 'Rất khẩn cấp'

    class Slot(models.TextChoices):
        SANG = 'sang', 'Buổi sáng'
        CHIEU = 'chieu', 'Buổi chiều'
        TOI = 'toi', 'Buổi tối'

    class ContactMethod(models.TextChoices):
        WEB = 'web', 'Qua ứng dụng (thông báo)'
        DIEN_THOAI = 'dien_thoai', 'Qua điện thoại'

    class Status(models.TextChoices):
        DA_GUI = 'da_gui', 'Đã gửi'
        DANG_XU_LY = 'dang_xu_ly', 'Đang xử lý'
        HOAN_THANH = 'hoan_thanh', 'Hoàn thành'
        DA_HUY = 'da_huy', 'Đã hủy'

    room = models.ForeignKey('rooms.Room', on_delete=models.PROTECT, related_name='maintenance_requests')
    tenant = models.ForeignKey('accounts.Tenant', on_delete=models.PROTECT, related_name='maintenance_requests')
    title = models.CharField('Tiêu đề sự cố', max_length=200)
    category = models.CharField('Danh mục', max_length=20, choices=Category.choices)
    description = models.TextField('Mô tả chi tiết')
    priority = models.CharField('Mức độ ưu tiên', max_length=20, choices=Priority.choices, default=Priority.BINH_THUONG)
    preferred_date = models.DateField('Ngày thuận tiện', null=True, blank=True)
    preferred_slot = models.CharField('Buổi thuận tiện', max_length=10, choices=Slot.choices, blank=True)
    contact_method = models.CharField('Liên hệ khi cần', max_length=20, choices=ContactMethod.choices, default=ContactMethod.WEB)
    contact_phone = models.CharField('Số điện thoại liên hệ', max_length=20, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DA_GUI, db_index=True)
    owner_note = models.TextField('Lời nhắn của chủ trọ', blank=True)
    expected_done = models.DateField('Ngày dự kiến xong', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def display_code(self):
        if not self.pk:
            return 'SC-mới'
        return f'SC-{timezone.localtime(self.created_at).year}-{self.pk:03d}'

    @property
    def status_tone(self):
        return {'da_gui': 'amber', 'dang_xu_ly': 'sky', 'hoan_thanh': 'mint', 'da_huy': 'gray'}[self.status]

    @property
    def priority_tone(self):
        return {'binh_thuong': 'gray', 'khan_cap': 'amber', 'rat_khan_cap': 'rose'}[self.priority]

    def __str__(self):
        return f'{self.display_code} · {self.title}'


class Announcement(models.Model):
    class Audience(models.TextChoices):
        ALL = 'all', 'Tất cả các phòng'
        ROOMS = 'rooms', 'Chọn phòng cụ thể'

    title = models.CharField('Tiêu đề', max_length=200)
    content = models.TextField('Nội dung')
    is_active = models.BooleanField('Hiển thị cho người thuê', default=True)
    audience = models.CharField('Phạm vi thông báo', max_length=10, choices=Audience.choices, default=Audience.ALL)
    rooms = models.ManyToManyField('rooms.Room', blank=True, related_name='announcements', verbose_name='Phòng nhận thông báo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='announcements')

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return self.title


class MaintenancePhoto(models.Model):
    maintenance = models.ForeignKey(MaintenanceRequest, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=maintenance_photo_path, storage=maintenance_storage)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['pk']


class NotificationRead(models.Model):
    class Kind(models.TextChoices):
        ANNOUNCEMENT = 'announcement', 'Thông báo từ chủ trọ'
        MAINTENANCE = 'maintenance', 'Phản hồi sửa chữa'
        OWNER_MAINTENANCE = 'owner_maintenance', 'Yêu cầu sửa chữa mới'
        OWNER_APPOINTMENT = 'owner_appointment', 'Lịch hẹn xem phòng'
        OWNER_APPOINTMENT_CANCEL = 'owner_appointment_cancel', 'Khách hủy lịch xem phòng'
        OWNER_TRANSFER = 'owner_transfer', 'Báo chuyển khoản'
        OWNER_COOCCUPANT = 'owner_cooccupant', 'Hồ sơ người ở cùng chờ duyệt'
        COOCCUPANT_DECISION = 'cooccupant_decision', 'Kết quả hồ sơ người ở cùng'
        PAYMENT_CORRECTION = 'payment_correction', 'Điều chỉnh / hủy khoản thanh toán'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_reads')
    kind = models.CharField(max_length=24, choices=Kind.choices)
    object_id = models.PositiveBigIntegerField()
    version = models.DateTimeField()
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'kind', 'object_id'], name='unique_user_notification_read'),
            models.CheckConstraint(condition=models.Q(object_id__gt=0), name='positive_notification_object_id'),
        ]
