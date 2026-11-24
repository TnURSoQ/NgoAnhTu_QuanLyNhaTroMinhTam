from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


DETAIL_FIELDS = ('document_type', 'gender', 'nationality', 'place_of_birth', 'birth_registration_place',
                 'permanent_address', 'identity_issued_on', 'identity_expires_on',
                 'identity_no_expiry', 'identity_issued_by')


class IdentityProfile(models.Model):
    """Visible identity-card details shared by tenants and staged co-occupant requests."""
    class DocumentType(models.TextChoices):
        CMND = 'cmnd', 'Chứng minh nhân dân'
        CCCD = 'cccd', 'CCCD / Căn cước'

    class Gender(models.TextChoices):
        MALE = 'male', 'Nam'
        FEMALE = 'female', 'Nữ'

    document_type = models.CharField('Loại giấy tờ', max_length=12, choices=DocumentType.choices, blank=True, default='')
    gender = models.CharField('Giới tính', max_length=8, choices=Gender.choices, blank=True, default='')
    nationality = models.CharField('Quốc tịch', max_length=100, blank=True, default='')
    place_of_birth = models.CharField('Nơi sinh', max_length=255, blank=True, default='')
    birth_registration_place = models.CharField('Nơi đăng ký khai sinh', max_length=255, blank=True, default='')
    permanent_address = models.CharField('Địa chỉ thường trú (theo căn cước)', max_length=500, blank=True, default='')
    identity_issued_on = models.DateField('Ngày cấp giấy tờ', null=True, blank=True)
    identity_expires_on = models.DateField('Ngày hết hạn giấy tờ', null=True, blank=True)
    identity_no_expiry = models.BooleanField('Giấy tờ ghi không thời hạn', default=False)
    identity_issued_by = models.CharField('Cơ quan / nơi cấp giấy tờ', max_length=255, blank=True, default='')

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        errors = {}
        born = self.date_of_birth
        if born and born > timezone.localdate():
            errors['date_of_birth'] = 'Ngày sinh không được ở tương lai.'
        if self.identity_issued_on:
            if self.identity_issued_on > timezone.localdate():
                errors['identity_issued_on'] = 'Ngày cấp không được ở tương lai.'
            elif born and self.identity_issued_on < born:
                errors['identity_issued_on'] = 'Ngày cấp không được trước ngày sinh.'
        if self.identity_expires_on:
            if self.identity_no_expiry:
                errors['identity_expires_on'] = 'Không nhập ngày hết hạn khi đã chọn giấy tờ không thời hạn.'
            elif self.identity_issued_on and self.identity_expires_on < self.identity_issued_on:
                errors['identity_expires_on'] = 'Ngày hết hạn không được trước ngày cấp.'
            elif born and self.identity_expires_on < born:
                errors['identity_expires_on'] = 'Ngày hết hạn không được trước ngày sinh.'
        if self.document_type == self.DocumentType.CCCD and len(self.id_card_number) != 12:
            errors['id_card_number'] = 'CCCD hoặc thẻ căn cước cần có 12 chữ số.'
        if errors:
            raise ValidationError(errors)

    @property
    def identity_missing_labels(self):
        fields = ('document_type', 'date_of_birth', 'gender', 'nationality', 'identity_issued_on', 'identity_issued_by')
        missing = [str(self._meta.get_field(name).verbose_name) for name in fields if not getattr(self, name)]
        if not self.permanent_address:
            missing.append('Địa chỉ thường trú (theo căn cước)')
        if not self.identity_expires_on and not self.identity_no_expiry:
            missing.append('Ngày hết hạn hoặc ghi nhận không thời hạn')
        return missing

    @property
    def identity_expired(self):
        return bool(self.identity_expires_on and self.identity_expires_on < timezone.localdate())
