from django.db import models
from accounts.identity_profile import IdentityProfile
from django.utils import timezone
from accounts.models import Tenant
from accounts.model_fields import DongField
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.core.validators import RegexValidator
import secrets
import uuid
from .amenities import amenity_names, shared_name


class PropertyInfo(models.Model):
    """Shared facilities for this single-property application; no billing fields."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    shared_amenities = models.CharField('Tiện ích chung khác', max_length=500, blank=True, default='')

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='one_property_info')]

    @property
    def amenity_list(self):
        return amenity_names(self.shared_amenities)

    @classmethod
    def current(cls):
        # Reading public pages must never create configuration rows.
        return cls.objects.filter(pk=1).first() or cls(pk=1)

    def __str__(self):
        return 'Thông tin nhà trọ'

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
        return [name for name in amenity_names(self.amenities) if not shared_name(name)]

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
    payment_terms = models.TextField('Điều khoản thanh toán', blank=True, default='')
    renewal_terms = models.TextField('Điều khoản gia hạn', blank=True, default='')
    checkout_terms = models.TextField('Điều khoản báo trước / trả phòng', blank=True, default='')

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
        return self.rent_on(self.checkout_date or timezone.localdate())

    def _renewal_terms_on(self, day):
        if not self.pk:
            return None
        return self.renewal_proposals.filter(status='accepted', effective_date__lte=day).order_by(
            '-effective_date', '-pk').first()

    def rent_on(self, day):
        terms = self._renewal_terms_on(day)
        return terms.monthly_rent if terms else (
            self.monthly_rent if self.monthly_rent is not None else self.room.price)

    def deposit_on(self, day):
        terms = self._renewal_terms_on(day)
        return terms.deposit if terms else self.deposit

    @property
    def agreed_deposit(self):
        return self.deposit_on(self.checkout_date or timezone.localdate())

    @property
    def status_label(self):
        from .display import contract_status_ui
        return contract_status_ui(self, timezone.localdate())[1]

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


class CoOccupantRequest(IdentityProfile):
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
        super().clean()

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
    proposal = models.OneToOneField('RenewalProposal', null=True, blank=True, on_delete=models.PROTECT,
                                      related_name='renewal_record')

    class Meta:
        ordering = ['-renewed_on', '-id']


class RenewalProposal(models.Model):
    class Status(models.TextChoices):
        OWNER = 'awaiting_owner', 'Chờ chủ trọ phản hồi'
        TENANT = 'awaiting_tenant', 'Chờ người thuê xác nhận'
        ACCEPTED = 'accepted', 'Đã thống nhất gia hạn'
        REJECTED = 'rejected', 'Đã từ chối'
        WITHDRAWN = 'withdrawn', 'Đã rút đề nghị'
        SUPERSEDED = 'superseded', 'Đã có đề nghị thay thế'

    class Source(models.TextChoices):
        TENANT = 'tenant', 'Người thuê đề nghị'
        OWNER = 'owner', 'Chủ trọ đề nghị'
        OFFLINE = 'offline', 'Thỏa thuận ngoài ứng dụng'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='renewal_proposals')
    old_end_date = models.DateField()
    new_end_date = models.DateField()
    effective_date = models.DateField('Ngày áp dụng giá và cọc')
    old_rent = DongField()
    monthly_rent = DongField()
    old_deposit = DongField()
    deposit = DongField()
    terms = models.TextField('Điều khoản bổ sung', blank=True)
    base_terms = models.JSONField(default=dict, blank=True)
    note = models.CharField('Lời nhắn', max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    source = models.CharField(max_length=10, choices=Source.choices)
    created_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='renewal_proposals')
    created_at = models.DateTimeField(auto_now_add=True)
    responded_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='renewal_responses')
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(fields=['contract'], condition=models.Q(
                status__in=['awaiting_owner', 'awaiting_tenant']), name='one_pending_renewal_proposal'),
            models.CheckConstraint(condition=models.Q(new_end_date__gt=models.F('old_end_date')),
                                   name='renewal_extends_contract'),
            models.CheckConstraint(condition=models.Q(effective_date__gt=models.F('old_end_date')) &
                                   models.Q(effective_date__lte=models.F('new_end_date')), name='renewal_effective_in_term'),
        ]

    @property
    def pending(self):
        return self.status in (self.Status.OWNER, self.Status.TENANT)

    @property
    def display_code(self):
        return f'GH-{self.pk:05d}'


class MoveOutNotice(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Chờ chủ trọ ghi nhận'
        ACKNOWLEDGED = 'acknowledged', 'Đã ghi nhận lịch dự kiến'
        CANCELLED = 'cancelled', 'Đã rút thông báo'
        COMPLETED = 'completed', 'Đã bàn giao phòng'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='moveout_notices')
    planned_date = models.DateField('Ngày dự kiến trả phòng')
    reason = models.CharField('Lý do / lời nhắn', max_length=1000, blank=True)
    submitted_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='moveout_notices')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    response_note = models.CharField(max_length=1000, blank=True)
    responded_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='moveout_responses')
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['contract'], condition=models.Q(
            status__in=['pending', 'acknowledged']), name='one_open_moveout_notice')]


def contract_document_path(instance, filename):
    from pathlib import Path
    return f'contracts/{instance.contract_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


from accounts.identity_storage import identity_storage


class ContractDocument(models.Model):
    class Kind(models.TextChoices):
        ORIGINAL = 'original', 'Hợp đồng đã ký'
        ANNEX = 'annex', 'Phụ lục đã ký'

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='documents')
    proposal = models.ForeignKey(RenewalProposal, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name='documents')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField('Tên tài liệu', max_length=150)
    file = models.FileField(upload_to=contract_document_path, storage=identity_storage)
    uploaded_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class ContractEvent(models.Model):
    """Immutable in-app notices, scoped to a contract party (never emailed)."""
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name='events')
    audience = models.CharField(max_length=6, choices=[('owner', 'Chủ trọ'), ('tenant', 'Người đại diện')])
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at', '-pk']


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


class AppointmentCalendar(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    revision = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='one_viewing_calendar')]


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

    class CancelledBy(models.TextChoices):
        GUEST = 'guest', 'Khách đặt lịch'
        OWNER = 'owner', 'Chủ trọ'
        SYSTEM = 'system', 'Hệ thống'

    code = models.CharField(max_length=10, unique=True, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='appointments')
    visitor_name = models.CharField(max_length=100)
    visitor_phone = models.CharField(max_length=20)
    visitor_email = models.EmailField(blank=True, default='')
    notification_version = models.PositiveIntegerField(default=0, editable=False)
    appointment_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    contract = models.OneToOneField('Contract', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='viewing_appointment')
    slot = models.CharField(max_length=10, choices=Slot.choices, default=Slot.SANG)
    note = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CHO_XAC_NHAN)
    owner_note = models.CharField(max_length=255, blank=True, default='')
    cancelled_by = models.CharField(max_length=10, choices=CancelledBy.choices, blank=True, default='')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['appointment_date', 'id']
        constraints = [
            models.UniqueConstraint(fields=['appointment_date', 'start_time'],
                condition=models.Q(status='da_xac_nhan', start_time__isnull=False), name='unique_confirmed_viewing_time'),
            models.CheckConstraint(condition=(models.Q(start_time__isnull=True) |
                models.Q(slot='sang', start_time__in=['08:00', '08:30', '09:00', '09:30', '10:00', '10:30', '11:00']) |
                models.Q(slot='chieu', start_time__in=['13:30', '14:00', '14:30', '15:00', '15:30', '16:00', '16:30']) |
                models.Q(slot='toi', start_time__in=['18:00', '18:30', '19:00', '19:30'])), name='valid_viewing_half_hour'),
        ]

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

    @property
    def masked_email(self):
        if '@' not in self.visitor_email:
            return ''
        local, domain = self.visitor_email.rsplit('@', 1)
        return local[:1] + '***@' + domain

    @property
    def time_label(self):
        if self.start_time:
            from .appointment_schedule import time_label
            return time_label(self.start_time)
        return 'Chưa chốt giờ cụ thể'

    @property
    def schedule_label(self):
        return f'{self.appointment_date:%d/%m/%Y} · {self.get_slot_display()} · {self.time_label}'

    @property
    def can_guest_cancel(self):
        return self.status in (self.Status.CHO_XAC_NHAN, self.Status.DA_XAC_NHAN) and not self.contract_id


class AppointmentEmail(models.Model):
    """Durable, private snapshots of appointment notifications and delivery state."""
    class Event(models.TextChoices):
        BOOKED = 'booked', 'Tiếp nhận đặt lịch'
        CONFIRMED = 'confirmed', 'Xác nhận lịch hẹn'
        CANCELLED = 'cancelled', 'Hủy lịch hẹn'
        RESCHEDULED = 'rescheduled', 'Đổi ngày giờ hẹn'
        VISITED = 'visited', 'Đã xem phòng'
        LEASED = 'leased', 'Đã chốt thuê'
        DETAILS = 'details', 'Cập nhật email liên hệ'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Chờ gửi'
        SENDING = 'sending', 'Đang gửi'
        SENT = 'sent', 'Đã gửi'
        FAILED = 'failed', 'Gửi chưa thành công'
        PREVIEW = 'preview', 'Chỉ tạo bản xem thử'
        SUPERSEDED = 'superseded', 'Đã có thông tin mới hơn'

    appointment = models.ForeignKey(ViewingAppointment, on_delete=models.CASCADE, related_name='emails')
    revision = models.PositiveIntegerField()
    event = models.CharField(max_length=20, choices=Event.choices)
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    text_body = models.TextField()
    html_body = models.TextField()
    lookup_url = models.CharField(max_length=1000, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=50, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    @property
    def tone(self):
        return {'sent': 'mint', 'failed': 'amber', 'sending': 'sky', 'pending': 'amber',
                'preview': 'lavender', 'superseded': 'gray'}.get(self.status, 'gray')

    @property
    def error_message(self):
        return {'not_configured': 'Chưa cấu hình máy chủ gửi email.',
                'authentication_config': 'Cần điền đủ tài khoản và mật khẩu ứng dụng cho máy chủ gửi thư.',
                'site_url': 'Cần cấu hình địa chỉ website để khách mở liên kết tra cứu.',
                'sender_address': 'Cần kiểm tra địa chỉ email gửi hoặc nhận phản hồi.',
                'authentication': 'Máy chủ thư chưa chấp nhận tài khoản gửi. Cần kiểm tra cấu hình đăng nhập.',
                'recipient': 'Máy chủ thư từ chối địa chỉ người nhận. Hãy kiểm tra email của khách.',
                'connection': 'Chưa kết nối hoặc gửi được qua máy chủ email. Có thể thử lại.',
                'delivery': 'Chưa gửi được email. Cần kiểm tra cấu hình và thử lại.'}.get(self.error_code, '')

    class Meta:
        ordering = ['-revision']
        constraints = [models.UniqueConstraint(fields=['appointment', 'revision'], name='unique_appointment_email_revision')]
        indexes = [models.Index(fields=['status', 'next_attempt_at'], name='appointment_email_retry_idx')]
