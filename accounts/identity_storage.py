import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def identity_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def identity_image_path(instance, filename):
    return f'identity/{instance.reference}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'
