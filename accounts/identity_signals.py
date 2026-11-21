from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import IdentityDocument


@receiver(post_delete, sender=IdentityDocument)
def delete_identity_images(sender, instance, **kwargs):
    files = [(field.storage, field.name) for field in (instance.front, instance.back) if field]
    for storage, name in files:
        transaction.on_commit(lambda storage=storage, name=name: storage.delete(name), robust=True)
