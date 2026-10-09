from django.db import models
from accounts.models import Tenant

class Room(models.Model):
    class Status(models.TextChoices):
        TRONG = 'trong', 'Trống'
        DANG_THUE = 'dang_thue', 'Đang thuê'
        BAO_TRI = 'bao_tri', 'Bảo trì'

    room_number = models.CharField(max_length=10, unique=True)
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

    def __str__(self):
        return f'HĐ #{self.id} - {self.room}'


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