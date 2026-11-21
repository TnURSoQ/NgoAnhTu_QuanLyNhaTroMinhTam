from django import forms

from accounts.forms import BootstrapFormMixin
from .models import Announcement, MaintenanceRequest
from rooms.models import Room
from accounts.images import MultipleImagesField, MultipleImageInput, validate_uploaded_image


class MaintenanceRequestForm(BootstrapFormMixin, forms.ModelForm):
    photos = MultipleImagesField(label='Ảnh sự cố', required=False, max_images=5,
        widget=MultipleImageInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
        help_text='Tối đa 5 ảnh JPG, PNG hoặc WebP; mỗi ảnh tối đa 5 MB. Chỉ bạn và chủ trọ xem được ảnh.')
    camera_photo = forms.ImageField(label='Chụp ảnh', required=False,
        widget=forms.FileInput(attrs={'accept': 'image/*', 'capture': 'environment'}))

    class Meta:
        model = MaintenanceRequest
        fields = ['title', 'category', 'description', 'priority', 'preferred_date', 'preferred_slot', 'contact_method']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Mô tả tình trạng và vị trí xảy ra sự cố…'}),
            'preferred_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def clean_camera_photo(self):
        image = self.cleaned_data.get('camera_photo')
        return validate_uploaded_image(image) if image else None

    def clean(self):
        data = super().clean()
        images = data.get('photos', []) + ([data['camera_photo']] if data.get('camera_photo') else [])
        if len(images) > 5:
            self.add_error('photos', 'Mỗi yêu cầu tối đa 5 ảnh, bao gồm ảnh chụp mới.')
        data['uploaded_images'] = images
        date = data.get('preferred_date')
        if date:
            from django.utils import timezone
            if date < timezone.localdate():
                self.add_error('preferred_date', 'Hãy chọn ngày hôm nay hoặc ngày sắp tới.')
        return data


class MaintenanceUpdateForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(label='Thao tác', choices=MaintenanceRequest.Status.choices)
    expected_done = forms.DateField(label='Ngày dự kiến xong', required=False,
                                   widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    owner_note = forms.CharField(label='Lời nhắn cho người thuê', required=False,
                                widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, maintenance, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import TRANSITIONS
        allowed = TRANSITIONS.get(maintenance.status, ())
        labels = {'dang_xu_ly': 'Tiếp nhận và xử lý', 'hoan_thanh': 'Đánh dấu hoàn thành', 'da_huy': 'Hủy yêu cầu'}
        self.fields['status'].choices = [(s, labels[s]) for s in allowed]


class AnnouncementForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'content', 'audience', 'rooms', 'is_active']
        widgets = {'content': forms.Textarea(attrs={'rows': 7})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rooms'].widget = forms.CheckboxSelectMultiple()
        self.fields['rooms'].queryset = Room.objects.order_by('floor', 'room_number')
        self.fields['rooms'].help_text = 'Chọn một hoặc nhiều phòng. Chỉ người đang thuê phòng được chọn mới thấy thông báo.'

    def clean(self):
        data = super().clean()
        if data.get('audience') == Announcement.Audience.ROOMS and not data.get('rooms'):
            self.add_error('rooms', 'Hãy chọn ít nhất một phòng nhận thông báo.')
        if data.get('audience') == Announcement.Audience.ALL:
            data['rooms'] = Room.objects.none()
        return data
