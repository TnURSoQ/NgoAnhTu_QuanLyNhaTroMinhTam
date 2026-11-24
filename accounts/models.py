from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
from .identity_storage import identity_image_path, identity_storage
from .identity_profile import IdentityProfile

class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Chủ trọ'
        TENANT = 'tenant', 'Người thuê'

    role = models.CharField(max_length=20, choices=Role.choices)

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'


class Tenant(IdentityProfile):
    user = models.OneToOneField(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tenant_profile',
    )
    full_name = models.CharField(max_length=100)
    id_card_number = models.CharField(max_length=20, unique=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    hometown = models.CharField(max_length=255, blank=True, null=True)
    occupation = models.CharField(max_length=100, blank=True, default='')
    note = models.TextField(blank=True, default='')

    def __str__(self):
        return self.full_name


class IdentityDocument(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='identity_uploads')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name='identity_documents')
    front = models.ImageField(storage=identity_storage, upload_to=identity_image_path)
    back = models.ImageField(storage=identity_storage, upload_to=identity_image_path, blank=True)
    entered_id_number = models.CharField(max_length=20)
    recognized_fields = models.JSONField(default=dict, blank=True)
    number_corrected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
