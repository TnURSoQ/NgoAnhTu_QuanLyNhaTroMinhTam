from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from accounts.services import create_account_for_tenant
from .models import Contract, ContractTenant, Room


@receiver(post_save, sender=ContractTenant)
def create_account_for_representative(sender, instance, **kwargs):
    # Quy tắc: chỉ người đại diện được cấp tài khoản
    if instance.is_representative:
        create_account_for_tenant(instance.tenant)

@receiver(post_save, sender=Contract)
def sync_room_status_on_save(sender, instance, **kwargs):
    # Hợp đồng hiệu lực -> phòng đang thuê; hợp đồng kết thúc -> phòng trống
    if instance.status == Contract.Status.HIEU_LUC:
        new_status = Room.Status.DANG_THUE
    else:
        new_status = Room.Status.TRONG
    Room.objects.filter(pk=instance.room_id).update(status=new_status)


@receiver(post_delete, sender=Contract)
def free_room_on_delete(sender, instance, **kwargs):
    if instance.status == Contract.Status.HIEU_LUC:
        Room.objects.filter(pk=instance.room_id).update(status=Room.Status.TRONG)