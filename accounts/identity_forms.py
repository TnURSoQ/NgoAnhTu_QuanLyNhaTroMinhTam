import json

from django import forms
from .images import validate_uploaded_image


IDENTITY_FIELDS = ('identity_front', 'identity_front_camera', 'identity_back', 'identity_back_camera',
                   'identity_recognition', 'confirm_identity_correction')
RECOGNIZED_FIELDS = {'full_name': 100, 'id_card_number': 12, 'date_of_birth': 10, 'hometown': 255, 'back_id_card_number': 12}


class IdentityScanFormMixin(forms.Form):
    identity_front = forms.ImageField(label='Ảnh mặt trước CCCD', required=False,
        widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))
    identity_front_camera = forms.ImageField(required=False,
        widget=forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment', 'style': 'display:none'}))
    identity_back = forms.ImageField(label='Ảnh mặt sau CCCD', required=False,
        widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))
    identity_back_camera = forms.ImageField(required=False,
        widget=forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment', 'style': 'display:none'}))
    identity_recognition = forms.CharField(required=False, max_length=2000, widget=forms.HiddenInput)
    confirm_identity_correction = forms.BooleanField(required=False,
        label='Tôi đã đối chiếu số trên ảnh và kiểm tra lại số giấy tờ được nhập trong hồ sơ.')

    def __init__(self, *args, **kwargs):
        self.existing_identity_document = kwargs.pop('existing_identity_document', None)
        super().__init__(*args, **kwargs)
        if self.existing_identity_document is None and getattr(self, 'instance', None) and self.instance.pk:
            documents = getattr(self.instance, 'identity_documents', None)
            if documents is not None:
                self.existing_identity_document = documents.first()

    @property
    def profile_fields(self):
        return [self[name] for name in self.fields if name not in IDENTITY_FIELDS]

    def clean(self):
        data = super().clean()
        selected = {}
        for side in ('front', 'back'):
            regular, camera = data.get(f'identity_{side}'), data.get(f'identity_{side}_camera')
            if regular and camera:
                self.add_error(f'identity_{side}', 'Chọn một ảnh tải lên hoặc một ảnh chụp cho mỗi mặt.')
            upload = regular or camera
            if upload:
                try:
                    selected[side] = validate_uploaded_image(upload)
                except forms.ValidationError as error:
                    self.add_error(f'identity_{side}', error)
        if selected.get('back') and not selected.get('front'):
            self.add_error('identity_front', 'Hãy chọn cả ảnh mặt trước để lưu cùng mặt sau.')
        recognition = {}
        raw = data.get('identity_recognition', '')
        if raw and selected.get('front'):
            try:
                supplied = json.loads(raw)
                if not isinstance(supplied, dict):
                    raise ValueError
                for key, limit in RECOGNIZED_FIELDS.items():
                    value = supplied.get(key, '')
                    if not isinstance(value, str) or len(value) > limit:
                        raise ValueError
                    if value:
                        recognition[key] = value
            except (ValueError, TypeError):
                self.add_error('identity_recognition', 'Kết quả đọc ảnh không hợp lệ. Hãy đọc lại hoặc nhập thông tin thủ công.')
        entered = data.get('id_card_number')
        recognized = recognition.get('id_card_number')
        back_number = recognition.get('back_id_card_number')
        if recognized and back_number and len(recognized) == len(back_number) == 12 and recognized != back_number:
            self.add_error('identity_back', 'Hai mặt ảnh đọc được số CCCD khác nhau. Hãy chọn đúng hai mặt của cùng một giấy tờ.')
        baseline = recognized if selected.get('front') else getattr(self.existing_identity_document, 'entered_id_number', '')
        changed = entered != self.initial.get('id_card_number', '')
        if recognized and entered and recognized != entered and self.fields['id_card_number'].disabled:
            self.add_error('identity_front', 'Số trên ảnh khác hồ sơ đang khóa số CCCD. Hãy yêu cầu người thuê kiểm tra lại thông tin cá nhân trước khi lưu ảnh này.')
        elif baseline and entered and baseline != entered and (selected.get('front') or changed) and not data.get('confirm_identity_correction'):
            self.add_error('confirm_identity_correction', 'Số CCCD đang nhập khác số đọc được hoặc hồ sơ ảnh trước đó. Hãy kiểm tra ảnh và xác nhận lại.')
        data['_identity_front'] = selected.get('front')
        data['_identity_back'] = selected.get('back')
        data['_identity_recognized'] = recognition
        return data
