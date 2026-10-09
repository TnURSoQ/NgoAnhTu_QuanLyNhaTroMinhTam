from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Chủ trọ'
        TENANT = 'tenant', 'Người thuê'

    role = models.CharField(max_length=20, choices=Role.choices)

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'


class Tenant(models.Model):
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

    def __str__(self):
        return self.full_name
