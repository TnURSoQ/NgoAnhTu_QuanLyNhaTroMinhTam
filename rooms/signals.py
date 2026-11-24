from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.db import transaction

from accounts.services import create_account_for_tenant
from .models import Contract, ContractTenant, Room, RoomPhoto


@receiver(post_save, sender=ContractTenant)
def create_account_for_representative(sender, instance, **kwargs):
    # Quy tắc: chỉ người đại diện được cấp tài khoản
    if instance.is_representative:
        create_account_for_tenant(instance.tenant)

@receiver(post_save, sender=Contract)
def sync_room_status_on_save(sender, instance, **kwargs):
    _sync_room(instance.room_id)
    if kwargs.get('created') and not kwargs.get('raw') and instance.status == Contract.Status.HIEU_LUC:
        from .appointment_services import reconcile_created_contract
        transaction.on_commit(lambda pk=instance.pk: reconcile_created_contract(pk), robust=True)


@receiver(post_delete, sender=Contract)
def free_room_on_delete(sender, instance, **kwargs):
    _sync_room(instance.room_id)


def _sync_room(room_id):
    if Contract.objects.filter(room_id=room_id, status=Contract.Status.HIEU_LUC).exists():
        Room.objects.filter(pk=room_id).update(status=Room.Status.DANG_THUE)
    else:
        # Lưu hợp đồng cũ không được mở lại phòng đang bảo trì.
        Room.objects.filter(pk=room_id, status=Room.Status.DANG_THUE).update(status=Room.Status.TRONG)


@receiver(post_delete, sender=RoomPhoto)
def remove_deleted_room_photo(sender, instance, **kwargs):
    if instance.image:
        storage, name = instance.image.storage, instance.image.name
        transaction.on_commit(lambda: storage.delete(name), robust=True)
