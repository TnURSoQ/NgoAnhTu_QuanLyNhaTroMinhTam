from django.db import models
from django.utils import timezone
from accounts.models import Tenant
from accounts.model_fields import DongField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
import secrets
import uuid

class Room(models.Model):
    class Status(models.TextChoices):
        TRONG = 'trong', 'Trống'
        DANG_THUE = 'dang_thue', 'Đang thuê'
        BAO_TRI = 'bao_tri', 'Đang sửa chữa'

    room_number = models.CharField(max_length=10, unique=True)
    floor = models.PositiveSmallIntegerField(default=1)
    area = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    price = DongField()
    max_occupants = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True, default='')
    amenities = models.CharField(max_length=255, blank=True, default='')  # cách nhau bằng dấu phẩy
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRONG)

    @property
    def amenity_list(self):
        return [a.strip() for a in self.amenities.split(',') if a.strip()]

    @property
    def cover_photo(self):
        return next(iter(self.photos.all()), None)
    
    def __str__(self):
        return f'Phòng {self.room_number}'


def room_photo_path(instance, filename):
    from pathlib import Path
    return f'rooms/{instance.room_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class RoomPhoto(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=room_photo_path)
    caption = models.CharField(max_length=150, blank=True, default='')
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'pk']


class Contract(models.Model):
    class Status(models.TextChoices):
        HIEU_LUC = 'hieu_luc', 'Hiệu lực'
        KET_THUC = 'ket_thuc', 'Kết thúc'

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='contracts')
    start_date = models.DateField()
    end_date = models.DateField()
    deposit = DongField(default=0)
    monthly_rent = DongField(null=True, blank=True)
    initial_electric = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                           validators=[MinValueValidator(0)])
    initial_water = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                        validators=[MinValueValidator(0)])
    prorate_first_month = models.BooleanField(default=False)
    use_default_services = models.BooleanField(default=True)
    services = models.ManyToManyField('billing.Service', blank=True, related_name='contracts')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.HIEU_LUC)
    checkout_date = models.DateField(null=True, blank=True)  # ngày trả phòng thực tế
    previous_contract = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='next_contracts')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['room'], condition=models.Q(status='hieu_luc'),
                                               name='one_active_contract_per_room')]

    def save(self, *args, **kwargs):
        if self.monthly_rent is None:
            self.monthly_rent = self.room.price
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'monthly_rent'}
        super().save(*args, **kwargs)

    @property
    def agreed_rent(self):
        return self.monthly_rent if self.monthly_rent is not None else self.room.price

    @property
    def deposit_balance(self):
        incoming = self.deposit_entries.filter(kind__in=['receive', 'transfer_in']).aggregate(
            total=models.Sum('amount'))['total'] or 0
        outgoing = self.deposit_entries.filter(kind__in=['refund', 'deduct', 'transfer_out', 'pay_invoice']).aggregate(
            total=models.Sum('amount'))['total'] or 0
        return incoming - outgoing

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
            models.UniqueConstraint(fields=['contract'], condition=models.Q(is_representative=True),
                                    name='one_contract_representative'),
        ]

    def __str__(self):
        tag = ' (đại diện)' if self.is_representative else ''
        return f'{self.tenant}{tag} - {self.contract}'


class CoOccupantRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Chờ xác nhận'
        APPROVED = 'approved', 'Đã xác nhận'
        REJECTED = 'rejected', 'Cần bổ sung / Từ chối'
        CANCELLED = 'cancelled', 'Đã hủy'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='cooccupant_requests')
    submitted_by = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='cooccupant_requests')
    full_name = models.CharField('Họ và tên', max_length=100)
    id_card_number = models.CharField('Số CCCD/CMND', max_length=12, validators=[
        RegexValidator(r'\A(?:[0-9]{9}|[0-9]{12})\Z', 'CCCD gồm 12 chữ số hoặc CMND cũ gồm 9 chữ số.')])
    phone = models.CharField('Số điện thoại', max_length=20, validators=[
        RegexValidator(r'\A[0-9+\s]{9,15}\Z', 'Số điện thoại không hợp lệ.')])
    email = models.EmailField('Email', blank=True)
    date_of_birth = models.DateField('Ngày sinh', null=True, blank=True)
    hometown = models.CharField('Quê quán', max_length=255, blank=True)
    occupation = models.CharField('Nghề nghiệp', max_length=100, blank=True)
    note = models.CharField('Lời nhắn cho chủ trọ', max_length=500, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='cooccupant_reviews')
    review_note = models.CharField('Phản hồi của chủ trọ', max_length=1000, blank=True)
    approved_tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name='approved_cooccupant_requests')
    previous_request = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                          related_name='resubmissions')
    identity_document = models.ForeignKey('accounts.IdentityDocument', on_delete=models.PROTECT,
                                           null=True, blank=True, related_name='cooccupant_submissions')

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['contract', 'id_card_number'], condition=models.Q(status='pending'),
                                    name='one_pending_cooccupant_per_contract_id',
                                    violation_error_message='Số giấy tờ này đã có hồ sơ chờ xác nhận trong hợp đồng.'),
            models.CheckConstraint(condition=(models.Q(status='approved', approved_tenant__isnull=False)
                | (~models.Q(status='approved') & models.Q(approved_tenant__isnull=True))),
                name='cooccupant_approval_has_tenant'),
        ]

    def clean(self):
        if self.date_of_birth and self.date_of_birth > timezone.localdate():
            raise ValidationError({'date_of_birth': 'Ngày sinh không được ở tương lai.'})

    @property
    def display_code(self):
        return f'OC-{self.pk:04d}' if self.pk else 'OC-mới'

    @property
    def status_tone(self):
        return {'pending': 'amber', 'approved': 'mint', 'rejected': 'rose', 'cancelled': 'gray'}[self.status]

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


class DepositEntry(models.Model):
    class Kind(models.TextChoices):
        RECEIVE = 'receive', 'Thu cọc'
        REFUND = 'refund', 'Hoàn cọc'
        DEDUCT = 'deduct', 'Khấu trừ cọc'
        PAY_INVOICE = 'pay_invoice', 'Đối trừ cọc thanh toán hóa đơn'
        TRANSFER_IN = 'transfer_in', 'Nhận cọc chuyển phòng'
        TRANSFER_OUT = 'transfer_out', 'Chuyển cọc sang hợp đồng mới'

    class Method(models.TextChoices):
        CASH = 'cash', 'Tiền mặt'
        BANK = 'bank', 'Chuyển khoản'
        INTERNAL = 'internal', 'Đối trừ / chuyển nội bộ'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='deposit_entries')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = DongField()
    occurred_on = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CASH)
    note = models.CharField(max_length=500, blank=True, default='')
    related_contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name='linked_deposit_entries')
    payment = models.OneToOneField('billing.Payment', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='deposit_entry')
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_on', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='positive_deposit_entry'),
            models.CheckConstraint(
                condition=(models.Q(kind='pay_invoice', payment__isnull=False)
                           | (~models.Q(kind='pay_invoice') & models.Q(payment__isnull=True))),
                name='deposit_payment_link_matches_kind'),
        ]


class CheckoutRecord(models.Model):
    contract = models.OneToOneField(Contract, on_delete=models.PROTECT, related_name='checkout_record')
    checkout_date = models.DateField()
    deposit_held = DongField(default=0)
    deposit_deducted = DongField(default=0)
    deposit_refunded = DongField(default=0)
    debt_at_checkout = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    drafts_at_checkout = models.PositiveIntegerField(default=0)
    refund_due_at_checkout = DongField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True, default='')
    room_condition = models.CharField(max_length=20, choices=[('trong', 'Sẵn sàng cho thuê'),
                                                             ('bao_tri', 'Cần vệ sinh / sửa chữa')])
    created_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # bỏ I, O, 0, 1 cho khó nhầm


class ViewingAppointment(models.Model):
    """Lịch hẹn xem phòng do khách (chưa đăng nhập) đặt."""

    class Status(models.TextChoices):
        CHO_XAC_NHAN = 'cho_xac_nhan', 'Chờ xác nhận'
        DA_XAC_NHAN = 'da_xac_nhan', 'Đã xác nhận'
        DA_XEM = 'da_xem', 'Đã xem phòng'
        DA_CHOT = 'da_chot', 'Đã chốt thuê'
        HUY = 'huy', 'Đã hủy'

    class Slot(models.TextChoices):
        SANG = 'sang', 'Buổi sáng (8:00 - 11:30)'
        CHIEU = 'chieu', 'Buổi chiều (13:30 - 17:00)'
        TOI = 'toi', 'Buổi tối (18:00 - 20:00)'

    code = models.CharField(max_length=10, unique=True, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='appointments')
    visitor_name = models.CharField(max_length=100)
    visitor_phone = models.CharField(max_length=20)
    appointment_date = models.DateField()
    slot = models.CharField(max_length=10, choices=Slot.choices, default=Slot.SANG)
    note = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CHO_XAC_NHAN)
    owner_note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['appointment_date', 'id']

    @classmethod
    def new_code(cls):
        while True:
            code = 'LH' + ''.join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if not cls.objects.filter(code=code).exists():
                return code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.new_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} - {self.visitor_name}'
