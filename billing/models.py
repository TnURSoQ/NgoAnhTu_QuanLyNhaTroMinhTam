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
from .model_fields import ElectricMeterReadingField
from .meters import electric_reading

class WaterBillingMethod(models.TextChoices):
    PER_PERSON = 'per_person', 'Theo người / tháng'
    METERED = 'metered', 'Theo công tơ (lịch sử)'


class UtilityRate(models.Model):
    electric_price = DongField()
    water_price = DongField(default=50000)
    water_billing_method = models.CharField(max_length=12, choices=WaterBillingMethod.choices,
                                           default=WaterBillingMethod.PER_PERSON)
    effective_date = models.DateField()

    class Meta:
        ordering = ['-effective_date', '-pk']

    def __str__(self):
        return f'Đơn giá từ {self.effective_date}'

    @property
    def water_unit_label(self):
        return 'đ/người/tháng' if self.water_billing_method == WaterBillingMethod.PER_PERSON else 'đ/m³'

    @classmethod
    def current(cls):
        """Lấy đơn giá hiện hành (mới nhất, có hiệu lực tới hôm nay)."""
        from django.utils import timezone
        return cls.objects.filter(effective_date__lte=timezone.localdate()).first()


class UtilityReading(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='utility_readings')
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name='utility_readings')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    old_electric = ElectricMeterReadingField()
    new_electric = ElectricMeterReadingField()
    old_water = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    new_water = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['contract', 'month', 'year'],
                                    condition=models.Q(contract__isnull=False), name='unique_contract_period_reading'),
            models.UniqueConstraint(fields=['room', 'month', 'year'],
                                    condition=models.Q(contract__isnull=True), name='unique_legacy_room_period_reading'),
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
        if self.new_water is not None and self.old_water is not None:
            return self.new_water - self.old_water
        return None

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
    # Legacy/manual imported invoices retain their original metered interpretation.
    water_billing_method = models.CharField(max_length=12, choices=WaterBillingMethod.choices,
                                           default=WaterBillingMethod.METERED)
    water_people_count = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
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
        return self.payments.active().aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def electric_calculation_matches(self):
        return bool(self.utility_reading and whole_dong(
            self.utility_reading.electric_usage() * self.electric_unit_price) == self.electric_fee)

    @property
    def water_calculation_matches(self):
        if self.water_billing_method == WaterBillingMethod.PER_PERSON:
            return self.water_people_count is not None and self.water_people_count * self.water_unit_price == self.water_fee
        usage = self.utility_reading.water_usage() if self.utility_reading else None
        return usage is not None and whole_dong(usage * self.water_unit_price) == self.water_fee

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


class InvoiceDraft(models.Model):
    """Bản nháp chưa phát hành; không tham gia công nợ hay thanh toán."""

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='invoice_drafts')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    room_fee = DongField()
    electric_unit_price = DongField(null=True, blank=True)
    water_unit_price = DongField(null=True, blank=True)
    water_billing_method = models.CharField(max_length=12, choices=WaterBillingMethod.choices,
                                           default=WaterBillingMethod.PER_PERSON)
    water_people_count = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    old_electric = ElectricMeterReadingField(null=True, blank=True)
    new_electric = ElectricMeterReadingField(null=True, blank=True)
    old_water = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    validators=[MinValueValidator(0)])
    new_water = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    validators=[MinValueValidator(0)])
    # Lưu tên, số lượng và đơn giá tại lúc tạo nháp, kể cả khi dịch vụ sau đó bị xóa.
    service_items = models.JSONField(default=list, blank=True)
    due_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default='')
    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='draft')
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['contract', 'month', 'year'],
                                    name='unique_contract_period_draft'),
            models.CheckConstraint(condition=models.Q(month__gte=1, month__lte=12),
                                   name='draft_valid_month'),
            models.CheckConstraint(condition=models.Q(year__gte=2000, year__lte=2100),
                                   name='draft_valid_year'),
        ]
        ordering = ['contract__room__room_number', 'pk']

    def clean(self):
        errors = {}
        for utility, label in [('electric', 'điện'), ('water', 'nước')]:
            if utility == 'water' and self.water_billing_method == WaterBillingMethod.PER_PERSON:
                continue
            old, new = getattr(self, f'old_{utility}'), getattr(self, f'new_{utility}')
            if old is not None and new is not None and new < old:
                errors[f'new_{utility}'] = f'Chỉ số {label} mới không được nhỏ hơn chỉ số cũ.'
        if errors:
            raise ValidationError(errors)

    @property
    def is_ready(self):
        try:
            electric_reading(self.old_electric)
            electric_reading(self.new_electric)
        except ValidationError:
            return False
        present = all(getattr(self, name) is not None for name in (
            'old_electric', 'new_electric', 'electric_unit_price', 'water_unit_price'))
        water_ready = (self.water_people_count is not None and self.water_people_count > 0
                       if self.water_billing_method == WaterBillingMethod.PER_PERSON else
                       self.old_water is not None and self.new_water is not None
                       and self.new_water >= self.old_water >= 0)
        return (present and self.new_electric >= self.old_electric >= 0
                and water_ready
                and self.electric_unit_price > 0 and self.water_unit_price > 0)

    @property
    def services_total(self):
        return sum((item['quantity'] * int(item['unit_price']) for item in self.service_items), 0)

    @property
    def estimated_total(self):
        if not self.is_ready:
            return None
        return (self.room_fee + self.services_total
                + whole_dong((self.new_electric - self.old_electric) * self.electric_unit_price)
                + (self.water_people_count * self.water_unit_price
                   if self.water_billing_method == WaterBillingMethod.PER_PERSON else
                   whole_dong((self.new_water - self.old_water) * self.water_unit_price)))

    def __str__(self):
        return f'Nháp T{self.month}/{self.year} - {self.contract}'


class ElectricMeterPrecisionAudit(models.Model):
    source_model = models.CharField(max_length=40)
    source_pk = models.PositiveBigIntegerField()
    original_values = models.JSONField()
    normalized_values = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source_model', 'source_pk'], name='unique_electric_precision_source')]

    def __str__(self):
        return f'{self.source_model} #{self.source_pk}'


class PaymentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(voided_at__isnull=True)


class Payment(models.Model):
    class Method(models.TextChoices):
        TIEN_MAT = 'tien_mat', 'Tiền mặt'
        CHUYEN_KHOAN = 'chuyen_khoan', 'Chuyển khoản'
        TU_COC = 'tu_coc', 'Đối trừ từ tiền cọc'

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = DongField()
    paid_date = models.DateField(default=timezone.localdate)
    recorded_at = models.DateTimeField('Thời điểm ghi nhận', default=timezone.now, null=True, blank=True, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False, related_name='recorded_payments')
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.TIEN_MAT)
    note = models.TextField(blank=True, default='')
    voided_at = models.DateTimeField('Thời điểm hủy', null=True, blank=True, editable=False)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                  editable=False, related_name='voided_payments')
    void_reason = models.TextField('Lý do hủy / điều chỉnh', blank=True, default='', max_length=1000, editable=False)
    replaces = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True,
                                    editable=False, related_name='replacement')
    objects = PaymentQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(models.Q(voided_at__isnull=True, voided_by__isnull=True, void_reason='') |
                (models.Q(voided_at__isnull=False, voided_by__isnull=False) & ~models.Q(void_reason=''))),
                name='payment_void_has_audit'),
            models.CheckConstraint(condition=~models.Q(pk=models.F('replaces_id')), name='payment_not_own_replacement'),
        ]

    @property
    def is_voided(self):
        return self.voided_at is not None

    @property
    def display_code(self):
        return f'TT-{self.pk:06d}' if self.pk else 'TT-mới'

    def clean(self):
        from rooms.models import DepositEntry
        entry = DepositEntry.objects.filter(payment_id=self.pk).first() if self.pk else None
        if entry:
            if (self.method != self.Method.TU_COC or self.amount != entry.amount
                    or self.invoice.contract_id != entry.contract_id or self.paid_date != entry.occurred_on):
                raise ValidationError('Khoản đối trừ cọc liên kết với sổ cọc, không được sửa độc lập.')
        elif self.method == self.Method.TU_COC and not getattr(self, '_from_deposit', False):
            raise ValidationError('Hãy sử dụng chức năng đối trừ cọc để ghi nhận đồng thời sổ cọc và hóa đơn.')
        if self.paid_date and self.paid_date > timezone.localdate():
            raise ValidationError('Ngày thu tiền không được ở tương lai.')
        if self.amount is None:
            return
        if self.amount <= 0:
            raise ValidationError('Số tiền thanh toán phải lớn hơn 0.')
        if self.replaces_id:
            previous = type(self).objects.get(pk=self.replaces_id)
            if not previous.is_voided or previous.invoice_id != self.invoice_id or previous.method == self.Method.TU_COC:
                raise ValidationError('Giao dịch thay thế cần cùng hóa đơn và liên kết khoản thu đã hủy hợp lệ.')
        if self.invoice_id and not self.is_voided:
            paid_before = self.invoice.payments.active().exclude(pk=self.pk).aggregate(
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

    def save(self, *args, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous:
            fields = ('invoice_id', 'amount', 'paid_date', 'method', 'note', 'recorded_at', 'recorded_by_id',
                      'voided_at', 'voided_by_id', 'void_reason', 'replaces_id')
            if any(getattr(previous, name) != getattr(self, name) for name in fields):
                raise ValidationError('Không sửa trực tiếp giao dịch đã ghi nhận. Hãy dùng chức năng điều chỉnh / hủy có lý do.')
        elif self.is_voided:
            raise ValidationError('Giao dịch mới không được có sẵn thông tin hủy.')
        super().save(*args, **kwargs)

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
