from django.db import models
from rooms.models import Room, Contract
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone

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
    old_electric = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    new_electric = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    old_water = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    new_water = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room', 'month', 'year'], name='unique_room_month_year_reading'),
        ]

    def clean(self):
        # Đúng theo đặc tả UC-06: chỉ số mới phải lớn hơn hoặc bằng chỉ số cũ
        if self.new_electric is not None and self.old_electric is not None \
                and self.new_electric < self.old_electric:
            raise ValidationError('Chỉ số điện mới không được nhỏ hơn chỉ số cũ.')
        if self.new_water is not None and self.old_water is not None \
                and self.new_water < self.old_water:
            raise ValidationError('Chỉ số nước mới không được nhỏ hơn chỉ số cũ.')

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

    def update_status(self):
        """Tính lại trạng thái từ số tiền đã thu và hạn thanh toán."""
        if self.total_paid() >= self.total_amount:
            new_status = self.Status.DA_THANH_TOAN
        elif self.due_date < timezone.localdate():
            new_status = self.Status.QUA_HAN
        else:
            new_status = self.Status.CHUA_THANH_TOAN
        self.status = new_status
        Invoice.objects.filter(pk=self.pk).update(status=new_status)

    def recalculate_total(self):
        services_total = self.invoice_services.aggregate(
            total=models.Sum('subtotal')
        )['total'] or 0
        self.total_amount = self.room_fee + self.electric_fee + self.water_fee + services_total
        self.save(update_fields=['total_amount'])
        self.update_status()

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

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.service.unit_price
        super().save(*args, **kwargs)

class Payment(models.Model):
    class Method(models.TextChoices):
        TIEN_MAT = 'tien_mat', 'Tiền mặt'
        CHUYEN_KHOAN = 'chuyen_khoan', 'Chuyển khoản'

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.TIEN_MAT)

    def clean(self):
        if self.amount is None:
            return
        if self.amount <= 0:
            raise ValidationError('Số tiền thanh toán phải lớn hơn 0.')
        if self.invoice_id:
            paid_before = self.invoice.payments.exclude(pk=self.pk).aggregate(
                total=models.Sum('amount')
            )['total'] or 0
            remaining = self.invoice.total_amount - paid_before
            if self.amount > remaining:
                raise ValidationError(
                    f'Số tiền vượt quá số còn nợ ({remaining:,.0f}đ).'
                )

    def __str__(self):
        return f'{self.amount}đ - {self.invoice}'