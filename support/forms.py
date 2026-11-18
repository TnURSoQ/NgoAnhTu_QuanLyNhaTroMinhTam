from django import forms

from accounts.forms import BootstrapFormMixin
from .models import Announcement, MaintenanceRequest


class MaintenanceRequestForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ['title', 'category', 'description', 'priority', 'preferred_date', 'preferred_slot', 'contact_method']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5, 'placeholder': 'Mô tả tình trạng và vị trí xảy ra sự cố…'}),
            'preferred_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }


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
        fields = ['title', 'content', 'is_active']
        widgets = {'content': forms.Textarea(attrs={'rows': 7})}
