from django.db import models
from django.utils import timezone
from accounts.models import Tenant
from django.core.exceptions import ValidationError

class Room(models.Model):
    class Status(models.TextChoices):
        TRONG = 'trong', 'Trống'
        DANG_THUE = 'dang_thue', 'Đang thuê'
        BAO_TRI = 'bao_tri', 'Đang sửa chữa'

    room_number = models.CharField(max_length=10, unique=True)
    floor = models.PositiveSmallIntegerField(default=1)
    area = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    max_occupants = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRONG)

    def __str__(self):
        return f'Phòng {self.room_number}'


class Contract(models.Model):
    class Status(models.TextChoices):
        HIEU_LUC = 'hieu_luc', 'Hiệu lực'
        KET_THUC = 'ket_thuc', 'Kết thúc'

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='contracts')
    start_date = models.DateField()
    end_date = models.DateField()
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.HIEU_LUC)
    checkout_date = models.DateField(null=True, blank=True)  # ngày trả phòng thực tế
    previous_contract = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='next_contracts')

    @property
    def display_code(self):
        """Mã hợp đồng hiển thị, ví dụ HD-0007 (cố định, không đổi khi sửa ngày)."""
        return f'HD-{self.pk:04d}' if self.pk else 'HD-mới'

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError('Ngày kết thúc không được trước ngày bắt đầu.')

    def __str__(self):
        return f'{self.display_code} - {self.room}'


class ContractTenant(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='contract_tenants')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='contract_tenants')
    is_representative = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['contract', 'tenant'], name='unique_contract_tenant'),
        ]

    def __str__(self):
        tag = ' (đại diện)' if self.is_representative else ''
        return f'{self.tenant}{tag} - {self.contract}'

class ContractRenewal(models.Model):
    """Lịch sử gia hạn hợp đồng."""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='renewals')
    old_end_date = models.DateField()
    new_end_date = models.DateField()
    renewed_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-renewed_on', '-id']