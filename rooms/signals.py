from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.services import create_account_for_tenant
from .models import ContractTenant


@receiver(post_save, sender=ContractTenant)
def create_account_for_representative(sender, instance, **kwargs):
    # Quy tắc: chỉ người đại diện được cấp tài khoản
    if instance.is_representative:
        create_account_for_tenant(instance.tenant)