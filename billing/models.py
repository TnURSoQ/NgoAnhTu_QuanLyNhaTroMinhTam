from django.db import models
from django.conf import settings
from accounts.models import Tenant
from accounts.model_fields import DongField
from accounts.money import whole_dong
from rooms.models import Room, Contract
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.utils.formats import number_format

class UtilityRate(models.Model):
    electric_price = DongField()
    water_price = DongField()
    effective_date = models.DateField()

    class Meta:
        ordering = ['-effective_date', '-pk']

    def __str__(self):
        return f'Đơn giá từ {self.effective_date}'

    @classmethod
    def current(cls):
        """Lấy đơn giá hiện hành (mới nhất, có hiệu lực tới hôm nay)."""
        from django.utils import timezone
        return cls.objects.filter(effective_date__lte=timezone.localdate()).first()


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
    unit_price = DongField()

    def __str__(self):
        return self.name


class Invoice(models.Model):
    class Status(models.TextChoices):
        CHUA_THANH_TOAN = 'chua_thanh_toan', 'Chưa thanh toán'
        THU_MOT_PHAN = 'thu_mot_phan', 'Thu một phần'
        DA_THANH_TOAN = 'da_thanh_toan', 'Đã thanh toán'
        QUA_HAN = 'qua_han', 'Quá hạn'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='invoices')
    utility_reading = models.ForeignKey(
        UtilityReading, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    room_fee = DongField()
    electric_fee = DongField(default=0)
    water_fee = DongField(default=0)
    electric_unit_price = DongField(default=0)
    water_unit_price = DongField(default=0)
    note = models.TextField(blank=True, default='')
    total_amount = DongField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CHUA_THANH_TOAN)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    reminded_at = models.DateField(null=True, blank=True)  # ngày đã gửi email nhắc nợ

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['contract', 'month', 'year'], name='unique_contract_month_year_invoice'),
        ]

    def total_paid(self):
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def electric_calculation_matches(self):
        return bool(self.utility_reading and whole_dong(
            self.utility_reading.electric_usage() * self.electric_unit_price) == self.electric_fee)

    @property
    def water_calculation_matches(self):
        return bool(self.utility_reading and whole_dong(
            self.utility_reading.water_usage() * self.water_unit_price) == self.water_fee)

    def update_status(self):
        """Tính lại trạng thái từ số tiền đã thu và hạn thanh toán."""
        paid = self.total_paid()
        if paid >= self.total_amount:
            new_status = self.Status.DA_THANH_TOAN
        elif self.due_date < timezone.localdate():
            new_status = self.Status.QUA_HAN
        elif paid > 0:
            new_status = self.Status.THU_MOT_PHAN
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
    service = models.ForeignKey(Service, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, default='')
    unit_price = DongField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    subtotal = DongField()

    @property
    def calculation_matches(self):
        return self.unit_price is not None and self.quantity * self.unit_price == self.subtotal

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['invoice', 'service'], name='unique_invoice_service'),
        ]

    def save(self, *args, **kwargs):
        if self.unit_price is None and self.service_id:
            self.unit_price = self.service.unit_price
        if not self.description and self.service_id:
            self.description = self.service.name
        if self.unit_price is None:
            raise ValidationError('Vui lòng nhập đơn giá cho khoản tự nhập.')
        self.unit_price = whole_dong(self.unit_price)
        self.subtotal = self.quantity * self.unit_price
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'unit_price', 'description', 'subtotal'}
        super().save(*args, **kwargs)

class Payment(models.Model):
    class Method(models.TextChoices):
        TIEN_MAT = 'tien_mat', 'Tiền mặt'
        CHUYEN_KHOAN = 'chuyen_khoan', 'Chuyển khoản'

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = DongField()
    paid_date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.TIEN_MAT)
    note = models.TextField(blank=True, default='')

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
                formatted_remaining = number_format(
                    remaining, decimal_pos=0,
                    force_grouping=True)
                raise ValidationError(
                    f'Số tiền vượt quá số còn nợ ({formatted_remaining}đ).'
                )

    def __str__(self):
        return f'{self.amount}đ - {self.invoice}'


class BankAccount(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    bank_name = models.CharField('Ngân hàng', max_length=100)
    account_number = models.CharField('Số tài khoản', max_length=50)
    account_holder = models.CharField('Chủ tài khoản', max_length=150)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name='single_bank_account')]

    def __str__(self):
        return f'{self.bank_name} · {self.account_number}'


class PaymentNotice(models.Model):
    class Status(models.TextChoices):
        CHO_XAC_NHAN = 'cho_xac_nhan', 'Chờ xác nhận'
        DA_XAC_NHAN = 'da_xac_nhan', 'Đã xác nhận'
        TU_CHOI = 'tu_choi', 'Từ chối'

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payment_notices')
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='payment_notices')
    amount = DongField('Số tiền đã chuyển', null=True, blank=True, validators=[MinValueValidator(1)])
    note = models.TextField('Ghi chú', blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CHO_XAC_NHAN)
    reject_reason = models.TextField('Lý do từ chối', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='processed_payment_notices')
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='payment_notice')

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(
            fields=['invoice'], condition=models.Q(status='cho_xac_nhan'),
            name='one_pending_notice_per_invoice')]
        indexes = [models.Index(fields=['status', 'created_at'], name='notice_status_created_idx')]

    def __str__(self):
        return f'Báo chuyển khoản #{self.pk} · {self.invoice}'
