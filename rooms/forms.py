from django import forms

from accounts.form_fields import FlexibleDecimalField, MoneyField, PlainDecimalInput
from accounts.forms import BootstrapFormMixin
from accounts.images import MultipleImagesField, MultipleImageInput
from .models import Contract, PropertyInfo, Room, RoomPhoto
from .amenities import SHARED_AMENITIES, amenity_names, shared_name

MAX_ROOM_PHOTOS = 10
ROOM_AMENITIES = [
    'Điều hòa', 'Bình nóng lạnh', 'Wifi', 'Gác lửng', 'Nhà vệ sinh riêng',
    'Khu bếp riêng', 'Ban công', 'Cửa sổ', 'Giường', 'Tủ quần áo', 'Tủ lạnh', 'Máy giặt',
]


class PropertyInfoForm(BootstrapFormMixin, forms.ModelForm):
    shared_choices = forms.MultipleChoiceField(label='Tiện ích chung của nhà trọ', required=False,
        choices=[(name, name) for name in SHARED_AMENITIES], widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = PropertyInfo
        fields = ['shared_amenities']
        widgets = {'shared_amenities': forms.Textarea(attrs={'rows': 2,
            'placeholder': 'Ví dụ: Sảnh tiếp khách, khu đọc sách…'})}
        help_texts = {'shared_amenities': 'Nhập tiện ích chung chưa có trong danh sách, cách nhau bằng dấu phẩy.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shared_choices'].widget.attrs['class'] = ''
        names = self.instance.amenity_list
        self.initial['shared_choices'] = [name for name in names if name in SHARED_AMENITIES]
        self.initial['shared_amenities'] = ', '.join(name for name in names if name not in SHARED_AMENITIES)

    def clean(self):
        data = super().clean()
        if 'shared_amenities' in data:
            combined = amenity_names(','.join(data.get('shared_choices', [])) + ',' + data['shared_amenities'])
            combined = amenity_names(','.join(shared_name(name) or name for name in combined))
            text = ', '.join(combined)
            if len(text) > 500:
                self.add_error('shared_amenities', 'Danh sách tiện ích chung tối đa 500 ký tự.')
            else:
                data['shared_amenities'] = text
        return data


class RoomForm(BootstrapFormMixin, forms.ModelForm):
    amenity_choices = forms.MultipleChoiceField(label='Tiện ích trong phòng', required=False,
        choices=[(name, name) for name in ROOM_AMENITIES], widget=forms.CheckboxSelectMultiple)
    price = MoneyField(label='Giá thuê (đ/tháng)', max_digits=8, decimal_places=0, min_value=1)
    area = FlexibleDecimalField(
        label='Diện tích (m²)', max_digits=5, decimal_places=2, required=False, min_value=1,
        widget=PlainDecimalInput(attrs={'placeholder': 'VD: 20'}))
    photos = MultipleImagesField(label='Tải ảnh phòng', required=False, max_images=MAX_ROOM_PHOTOS,
                                     widget=MultipleImageInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
                                     help_text='Có thể chọn nhiều ảnh cùng lúc. JPG, PNG hoặc WebP, tối đa 5 MB/ảnh và 10 ảnh/phòng. Ảnh được hiển thị công khai.')
    delete_photos = forms.ModelMultipleChoiceField(label='Xóa ảnh', queryset=RoomPhoto.objects.none(), required=False)
    cover_photo = forms.ModelChoiceField(label='Ảnh đại diện', queryset=RoomPhoto.objects.none(), required=False)
    new_cover_index = forms.IntegerField(label='Ảnh đại diện mới', min_value=0, required=False, widget=forms.HiddenInput)

    class Meta:
        model = Room
        fields = ['room_number', 'floor', 'area', 'max_occupants', 'price', 'status', 'amenities', 'description']
        labels = {
            'room_number': 'Số phòng', 'floor': 'Tầng',
            'max_occupants': 'Sức chứa tối đa (người)', 'status': 'Tình trạng',
            'amenities': 'Tiện ích khác', 'description': 'Mô tả phòng',
        }
        help_texts = {'amenities': 'Nhập tiện ích riêng chưa có trong danh sách, cách nhau bằng dấu phẩy. Chỗ để xe, camera và khu vực chung được cập nhật tại Cấu hình → Thông tin nhà trọ.'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Giới thiệu ngắn để khách xem phòng'})}
        error_messages = {'room_number': {'unique': 'Số phòng này đã tồn tại.'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['amenity_choices'].widget.attrs['class'] = ''
        amenities = self.instance.amenity_list if self.instance.pk else []
        self.initial.setdefault('amenity_choices', [name for name in amenities if name in ROOM_AMENITIES])
        self.initial['amenities'] = ', '.join(name for name in amenities if name not in ROOM_AMENITIES)
        self.existing_photos = list(self.instance.photos.all()) if self.instance.pk else []
        photo_choices = RoomPhoto.objects.filter(room=self.instance) if self.instance.pk else RoomPhoto.objects.none()
        self.fields['delete_photos'].queryset = photo_choices
        self.fields['cover_photo'].queryset = photo_choices
        if self.existing_photos:
            self.initial.setdefault('cover_photo', self.existing_photos[0].pk)
        status = self.fields['status']
        has_contract = bool(self.instance.pk) and self.instance.contracts.filter(
            status=Contract.Status.HIEU_LUC).exists()
        if has_contract:
            status.disabled = True
            status.help_text = 'Phòng đang có hợp đồng nên tình trạng do hệ thống tự cập nhật.'
        else:
            status.choices = [(Room.Status.TRONG, 'Còn trống'), (Room.Status.BAO_TRI, 'Đang sửa chữa')]

    def clean_max_occupants(self):
        value = self.cleaned_data['max_occupants']
        if value < 1:
            raise forms.ValidationError('Sức chứa tối đa phải từ 1 người trở lên.')
        if self.instance.pk:
            people = self.instance.contracts.filter(status=Contract.Status.HIEU_LUC).values_list('contract_tenants__tenant_id', flat=True)
            count = len({pk for pk in people if pk is not None})
            if value < count:
                raise forms.ValidationError(f'Phòng đang có {count} người ở, không thể giảm sức chứa xuống {value}.')
        return value


    def clean(self):
        data = super().clean()
        if 'amenities' in data:
            names = data.get('amenity_choices', []) + data['amenities'].replace('\n', ',').split(',')
            seen, unique = set(), []
            for name in names:
                name = name.strip()
                if shared_name(name):
                    self.add_error('amenities', f'“{name}” là tiện ích chung. Hãy cập nhật tại Cấu hình → Thông tin nhà trọ.')
                    continue
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    unique.append(name)
            combined = ', '.join(unique)
            if len(combined) > 255:
                self.add_error('amenities', 'Danh sách tiện ích tối đa 255 ký tự. Vui lòng rút gọn tiện ích khác.')
            elif not self.has_error('amenities'):
                data['amenities'] = combined
        images = data.get('photos', [])
        removed = data.get('delete_photos', [])
        if len(self.existing_photos) - len(removed) + len(images) > MAX_ROOM_PHOTOS:
            self.add_error('photos', 'Mỗi phòng tối đa 10 ảnh. Hãy đánh dấu xóa ảnh cũ trước khi thêm.')
        index = data.get('new_cover_index')
        if index is not None and 'photos' in data and index >= len(images):
            self.add_error('new_cover_index', 'Hãy chọn ảnh đại diện trong các ảnh mới đã tải lên.')
        return data
