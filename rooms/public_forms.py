import re
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from .models import ViewingAppointment

OPEN_STATUSES = (ViewingAppointment.Status.CHO_XAC_NHAN, ViewingAppointment.Status.DA_XAC_NHAN)
MAX_OPEN_PER_PHONE = 3
MAX_DAYS_AHEAD = 30


def _date_widget():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class BookingForm(BootstrapFormMixin, forms.Form):
    """Khách đặt lịch xem phòng (không cần đăng nhập)."""
    visitor_name = forms.CharField(label='Họ và tên', max_length=100)
    visitor_phone = forms.CharField(label='Số điện thoại', max_length=20)
    appointment_date = forms.DateField(label='Ngày muốn xem phòng', widget=_date_widget())
    slot = forms.ChoiceField(label='Buổi', choices=ViewingAppointment.Slot.choices)
    note = forms.CharField(label='Ghi chú (nếu có)', required=False, max_length=255,
                           widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.room = room
        today = timezone.localdate()
        widget = self.fields['appointment_date'].widget
        widget.attrs['min'] = today.isoformat()
        widget.attrs['max'] = (today + timedelta(days=MAX_DAYS_AHEAD)).isoformat()
        self.fields['appointment_date'].initial = today + timedelta(days=1)

    def clean_visitor_phone(self):
        value = re.sub(r'[\s.\-]', '', self.cleaned_data['visitor_phone'])
        if not re.fullmatch(r'\+?\d{9,12}', value):
            raise ValidationError('Số điện thoại không hợp lệ (9 đến 12 chữ số).')
        return value

    def clean_appointment_date(self):
        value = self.cleaned_data['appointment_date']
        today = timezone.localdate()
        if value < today:
            raise ValidationError('Ngày xem phòng không được ở quá khứ.')
        if value > today + timedelta(days=MAX_DAYS_AHEAD):
            raise ValidationError(f'Chỉ đặt lịch trong vòng {MAX_DAYS_AHEAD} ngày tới.')
        return value

    def clean(self):
        cleaned = super().clean()
        phone, date = cleaned.get('visitor_phone'), cleaned.get('appointment_date')
        if phone and date and self.room is not None:
            open_ones = ViewingAppointment.objects.filter(visitor_phone=phone, status__in=OPEN_STATUSES)
            if open_ones.filter(room=self.room, appointment_date=date).exists():
                raise ValidationError('Bạn đã đặt lịch xem phòng này vào ngày đó rồi. '
                                      'Hãy dùng chức năng tra cứu bằng mã lịch hẹn để xem lại.')
            if open_ones.filter(appointment_date__gte=timezone.localdate()).count() >= MAX_OPEN_PER_PHONE:
                raise ValidationError(f'Bạn đang có {MAX_OPEN_PER_PHONE} lịch hẹn chưa hoàn tất. '
                                      'Vui lòng đợi chủ trọ xử lý trước khi đặt thêm.')
        return cleaned


class RescheduleForm(BootstrapFormMixin, forms.Form):
    """Chủ trọ đổi ngày giờ hẹn."""
    appointment_date = forms.DateField(label='Ngày hẹn mới', widget=_date_widget())
    slot = forms.ChoiceField(label='Buổi', choices=ViewingAppointment.Slot.choices)

    def clean_appointment_date(self):
        value = self.cleaned_data['appointment_date']
        if value < timezone.localdate():
            raise ValidationError('Ngày hẹn không được ở quá khứ.')
        return value