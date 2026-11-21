from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MaintenancePhoto


@receiver(post_delete, sender=MaintenancePhoto)
def delete_maintenance_photo_file(sender, instance, **kwargs):
    if instance.image:
        storage, name = instance.image.storage, instance.image.name
        transaction.on_commit(lambda: storage.delete(name), robust=True)
