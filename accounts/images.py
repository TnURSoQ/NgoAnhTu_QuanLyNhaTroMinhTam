from pathlib import Path

from django import forms


def validate_uploaded_image(upload):
    if upload.size > 5 * 1024 * 1024:
        raise forms.ValidationError('Ảnh tối đa 5 MB.')
    if upload.image.format not in ('JPEG', 'PNG', 'WEBP'):
        raise forms.ValidationError('Chỉ chấp nhận ảnh JPG, PNG hoặc WebP.')
    if Path(upload.name).suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise forms.ValidationError('Đuôi tệp phải là .jpg, .jpeg, .png hoặc .webp.')
    if upload.image.width * upload.image.height > 20000000:
        raise forms.ValidationError('Ảnh quá lớn. Vui lòng giảm xuống dưới 20 triệu điểm ảnh.')
    return upload


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImagesField(forms.ImageField):
    widget = MultipleImageInput

    def __init__(self, *args, max_images, **kwargs):
        self.max_images = max_images
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > self.max_images:
            raise forms.ValidationError(f'Chỉ được chọn tối đa {self.max_images} ảnh.')
        images = []
        for upload in files:
            try:
                images.append(validate_uploaded_image(super().clean(upload)))
            except forms.ValidationError as error:
                raise forms.ValidationError([f'{upload.name}: {message}' for message in error.messages]) from error
        return images
