from django.db import models
from rooms.models import Room, Contract

class UtilityRate(models.Model):
    electric_price = models.DecimalField(max_digits=10, decimal_places=2)
    water_price = models.DecimalField(max_digits=10, decimal_places=2)
    effective_date = models.DateField()

    class Meta:
        ordering = ['-effective_date']

    def __str__(self):
        return f'Đơn giá từ {self.effective_date}'

    @classmethod
    def current(cls):
        """Lấy đơn giá hiện hành (mới nhất, có hiệu lực tới hôm nay)."""
        from django.utils import timezone
        return cls.objects.filter(effective_date__lte=timezone.now().date()).first()


class UtilityReading(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='utility_readings')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    old_electric = models.PositiveIntegerField()
    new_electric = models.PositiveIntegerField()
    old_water = models.PositiveIntegerField()
    new_water = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'month', 'year'], name='unique_room_month_year_reading'),
        ]

    def electric_usage(self):
        return self.new_electric - self.old_electric

    def water_usage(self):
        return self.new_water - self.old_water

    def __str__(self):
        return f'Chỉ số {self.room} - T{self.month}/{self.year}'


class Service(models.Model):
    name = models.CharField(max_length=100)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.name


class Invoice(models.Model):
    class Status(models.TextChoices):
        CHUA_THANH_TOAN = 'chua_thanh_toan', 'Chưa thanh toán'
        DA_THANH_TOAN = 'da_thanh_toan', 'Đã thanh toán'
        QUA_HAN = 'qua_han', 'Quá hạn'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='invoices')
    utility_reading = models.ForeignKey(
        UtilityReading, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    room_fee = models.DecimalField(max_digits=10, decimal_places=2)
    electric_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    water_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CHUA_THANH_TOAN)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['contract', 'month', 'year'], name='unique_contract_month_year_invoice'),
        ]

    def total_paid(self):
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or 0

    def __str__(self):
        return f'Hóa đơn T{self.month}/{self.year} - {self.contract}'


class InvoiceService(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='invoice_services')
    service = models.ForeignKey(Service, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['invoice', 'service'], name='unique_invoice_service'),
        ]


class Payment(models.Model):
    class Method(models.TextChoices):
        TIEN_MAT = 'tien_mat', 'Tiền mặt'
        CHUYEN_KHOAN = 'chuyen_khoan', 'Chuyển khoản'

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_date = models.DateField(auto_now_add=True)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.TIEN_MAT)

    def __str__(self):
        return f'{self.amount}đ - {self.invoice}'