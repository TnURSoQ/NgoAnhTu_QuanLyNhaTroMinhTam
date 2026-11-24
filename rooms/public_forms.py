import re
from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.forms import BootstrapFormMixin
from .models import ViewingAppointment
from .appointment_schedule import SLOT_STARTS, request_time_available, time_label

OPEN_STATUSES = (ViewingAppointment.Status.CHO_XAC_NHAN, ViewingAppointment.Status.DA_XAC_NHAN)
MAX_OPEN_PER_PHONE = 3
MAX_DAYS_AHEAD = 30


def _date_widget():
    return forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class BookingForm(BootstrapFormMixin, forms.Form):
    """Khách đặt lịch xem phòng (không cần đăng nhập)."""
    visitor_name = forms.CharField(label='Họ và tên', max_length=100)
    visitor_phone = forms.CharField(label='Số điện thoại', max_length=20)
    visitor_email = forms.EmailField(label='Email nhận thông báo', max_length=254,
        error_messages={'invalid': 'Địa chỉ email không hợp lệ. Vui lòng kiểm tra lại.'},
        help_text='Nhập Gmail hoặc email bạn đang sử dụng để nhận mã lịch hẹn và các cập nhật.',
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'Ví dụ: tenban@gmail.com'}))
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

    def clean_visitor_email(self):
        value = self.cleaned_data['visitor_email']
        local, domain = value.rsplit('@', 1)
        return local + '@' + domain.lower()

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
        if date and cleaned.get('slot') and not request_time_available(date, cleaned['slot']):
            self.add_error('slot', 'Buổi này không còn giờ xem trong tương lai. Hãy chọn buổi hoặc ngày khác.')
        if phone and date and self.room is not None:
            open_ones = ViewingAppointment.objects.filter(visitor_phone=phone, status__in=OPEN_STATUSES)
            if open_ones.filter(room=self.room, appointment_date=date).exists():
                raise ValidationError('Bạn đã đặt lịch xem phòng này vào ngày đó rồi. '
                                      'Hãy dùng chức năng tra cứu bằng mã lịch hẹn để xem lại.')
            if open_ones.filter(appointment_date__gte=timezone.localdate()).count() >= MAX_OPEN_PER_PHONE:
                raise ValidationError(f'Bạn đang có {MAX_OPEN_PER_PHONE} lịch hẹn chưa hoàn tất. '
                                      'Vui lòng đợi chủ trọ xử lý trước khi đặt thêm.')
        email = cleaned.get('visitor_email')
        if email and date and self.room is not None:
            email_bookings = ViewingAppointment.objects.filter(visitor_email__iexact=email, status__in=OPEN_STATUSES)
            if email_bookings.filter(room=self.room, appointment_date=date).exists():
                raise ValidationError('Email này đã đặt lịch xem phòng này vào ngày đó. Hãy kiểm tra email hoặc tra cứu mã lịch hẹn.')
            if email_bookings.filter(appointment_date__gte=timezone.localdate()).count() >= MAX_OPEN_PER_PHONE:
                raise ValidationError('Email này đang có 3 lịch hẹn chưa hoàn tất. Vui lòng đợi chủ trọ xử lý.')
        return cleaned


class ViewingTimeSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        for slot, starts in SLOT_STARTS.items():
            if str(value) in {f'{start:%H:%M}' for start in starts}:
                option['attrs']['data-slot'] = slot
        return option


def viewing_time_field(required=True):
    choices = [('', 'Chọn khung giờ xem phòng')]
    choices += [(dict(ViewingAppointment.Slot.choices)[slot], [(f'{start:%H:%M}', time_label(start)) for start in starts])
                for slot, starts in SLOT_STARTS.items()]
    return forms.ChoiceField(label='Giờ xem cụ thể (30 phút/lượt)', choices=choices, required=required,
                             widget=ViewingTimeSelect(attrs={'data-appointment-start': ''}))


class ConfirmAppointmentForm(BootstrapFormMixin, forms.Form):
    start_time = viewing_time_field()
    owner_note = forms.CharField(label='Lời nhắn cho khách', max_length=255, required=False,
                                widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, appointment, **kwargs):
        kwargs.setdefault('auto_id', 'confirm_%s')
        super().__init__(*args, **kwargs)
        self.appointment = appointment

    def clean_start_time(self):
        value = self.cleaned_data['start_time']
        starts = {f'{start:%H:%M}' for start in SLOT_STARTS[self.appointment.slot]}
        if value not in starts:
            raise forms.ValidationError('Giờ xem phải nằm trong buổi khách đã chọn. Muốn đổi buổi, hãy dùng Đổi lịch.')
        return value


class RescheduleForm(BootstrapFormMixin, forms.Form):
    """Chủ trọ đổi ngày giờ hẹn."""
    appointment_date = forms.DateField(label='Ngày hẹn mới', widget=_date_widget())
    slot = forms.ChoiceField(label='Buổi', choices=ViewingAppointment.Slot.choices)
    start_time = viewing_time_field(required=False)
    owner_note = forms.CharField(label='Lời nhắn về lịch mới', max_length=255, required=False,
        widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, appointment=None, **kwargs):
        kwargs.setdefault('auto_id', 'change_%s')
        super().__init__(*args, **kwargs)
        self.fields['start_time'].required = bool(appointment and appointment.status == ViewingAppointment.Status.DA_XAC_NHAN)

    def clean_appointment_date(self):
        value = self.cleaned_data['appointment_date']
        if value < timezone.localdate():
            raise ValidationError('Ngày hẹn không được ở quá khứ.')
        return value


class AppointmentEmailForm(BootstrapFormMixin, forms.Form):
    visitor_email = forms.EmailField(label='Email nhận thông báo', max_length=254,
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}))


class GuestCancelAppointmentForm(BootstrapFormMixin, forms.Form):
    reason = forms.CharField(label='Lý do hủy (không bắt buộc)', max_length=255, required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Bạn có thể để trống phần này.'}))
