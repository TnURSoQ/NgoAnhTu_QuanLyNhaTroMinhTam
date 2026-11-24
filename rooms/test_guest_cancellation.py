from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from support.models import NotificationRead
from support.notifications import unread_count
from support.services import owner_notification_feed
from .appointment_services import cancel_by_guest, change_status
from .models import AppointmentEmail, Contract, Room, ViewingAppointment as VA
from .services import create_contract


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PUBLIC_SITE_URL='https://nhatro.example',
    DEFAULT_FROM_EMAIL='Nhà trọ thử <owner@example.com>', EMAIL_REPLY_TO='',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class GuestCancellationTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = Room.objects.create(room_number='201', price=2500000)
        self.owner = User.objects.create_user('owner', role='owner')
        self.appointment = VA.objects.create(room=self.room, appointment_date=self.today + timedelta(days=2),
            slot='sang', visitor_name='Khách thử', visitor_email='guest@example.com', visitor_phone='0901111222',
            note='Ghi chú khi đặt lịch', owner_note='Lời nhắn trước đó của chủ trọ')
        self.url = reverse('appointment_cancel', args=[self.appointment.code])
        self.status_url = reverse('appointment_status', args=[self.appointment.code])

    def cancel(self, data=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data or {})

    def owner_panel(self):
        self.client.force_login(self.owner)
        return self.client.get(reverse('owner_notifications_panel'))

    def test_anonymous_can_cancel_without_reason_or_login(self):
        self.assertContains(self.client.get(self.status_url), 'Hủy lịch hẹn')
        response = self.cancel()
        self.assertRedirects(response, self.status_url)
        self.appointment.refresh_from_db()
        self.assertEqual((self.appointment.status, self.appointment.cancelled_by, self.appointment.cancellation_reason),
                         (VA.Status.HUY, VA.CancelledBy.GUEST, ''))
        self.assertIsNotNone(self.appointment.cancelled_at)
        self.assertEqual(unread_count(self.owner), 1)
        self.assertContains(self.client.get(self.status_url), 'Không ghi lý do')
        self.assertNotContains(self.client.get(self.status_url), 'data-bs-target="#cancelAppointmentModal"')

    def test_cancel_with_reason_preserves_original_notes_and_schedule(self):
        change_status(self.appointment.pk, VA.Status.DA_XAC_NHAN, start_time='09:00')
        self.cancel({'reason': '  Khách có việc đột xuất  '})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.cancellation_reason, 'Khách có việc đột xuất')
        self.assertEqual(self.appointment.note, 'Ghi chú khi đặt lịch')
        self.assertEqual(self.appointment.owner_note, 'Lời nhắn trước đó của chủ trọ')
        self.assertEqual(self.appointment.start_time.strftime('%H:%M'), '09:00')
        self.assertContains(self.owner_panel(), 'Khách có việc đột xuất')

    def test_blank_whitespace_reason_is_optional(self):
        self.cancel({'reason': ' \n\t '})
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.cancellation_reason, '')

    def test_overlong_reason_shows_form_error_without_cancelling(self):
        response = self.cancel({'reason': 'a' * 256})
        self.assertEqual(response.status_code, 200)
        self.assertIn('reason', response.context['cancel_form'].errors)
        self.assertContains(response, 'bootstrap.Modal.getOrCreateInstance')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, VA.Status.CHO_XAC_NHAN)
        self.assertFalse(AppointmentEmail.objects.exists())

    def test_service_also_enforces_reason_limit(self):
        with self.assertRaises(ValidationError):
            cancel_by_guest(self.appointment.code, 'a' * 256)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, VA.Status.CHO_XAC_NHAN)

    def test_get_and_missing_csrf_cannot_cancel(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.url).status_code, 403)
        client.get(self.status_url)
        token = client.cookies['csrftoken'].value
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(client.post(self.url, {'csrfmiddlewaretoken': token}).status_code, 302)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, VA.Status.HUY)

    def test_unknown_code_and_tampered_post_cannot_choose_another_appointment(self):
        other = VA.objects.create(room=self.room, appointment_date=self.appointment.appointment_date,
            visitor_name='Khách khác', visitor_phone='0902222333')
        self.assertEqual(self.client.post(reverse('appointment_cancel', args=['LHUNKNOWN'])).status_code, 404)
        self.cancel({'reason': '', 'pk': other.pk, 'code': other.code, 'status': 'da_chot',
                     'cancelled_by': 'owner', 'cancelled_at': '2000-01-01'})
        other.refresh_from_db()
        self.appointment.refresh_from_db()
        self.assertEqual(other.status, VA.Status.CHO_XAC_NHAN)
        self.assertEqual(self.appointment.cancelled_by, VA.CancelledBy.GUEST)

    def test_lowercase_lookup_code_can_cancel(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('appointment_cancel', args=[self.appointment.code.lower()]))
        self.assertRedirects(response, self.status_url)

    def test_repeated_cancel_does_not_duplicate_notification_email_or_change_audit(self):
        self.cancel({'reason': 'Lý do đầu tiên'})
        self.appointment.refresh_from_db()
        first_time = self.appointment.cancelled_at
        self.cancel({'reason': 'Gửi lặp'})
        self.appointment.refresh_from_db()
        self.assertEqual((self.appointment.cancelled_at, self.appointment.cancellation_reason), (first_time, 'Lý do đầu tiên'))
        self.assertEqual(AppointmentEmail.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(unread_count(self.owner), 1)

    def test_confirmed_hour_is_released_and_owner_cannot_reconfirm_cancelled_visit(self):
        change_status(self.appointment.pk, VA.Status.DA_XAC_NHAN, start_time='09:00')
        self.cancel()
        other = VA.objects.create(room=self.room, appointment_date=self.appointment.appointment_date,
            visitor_name='Khách khác', visitor_phone='0902222333')
        change_status(other.pk, VA.Status.DA_XAC_NHAN, start_time='09:00')
        with self.assertRaises(ValidationError):
            change_status(self.appointment.pk, VA.Status.DA_XAC_NHAN, start_time='09:30')

    def test_seen_and_leased_visits_cannot_be_cancelled_by_guest(self):
        for status in (VA.Status.DA_XEM, VA.Status.DA_CHOT):
            VA.objects.filter(pk=self.appointment.pk).update(status=status)
            self.assertEqual(self.cancel().status_code, 302)
            self.appointment.refresh_from_db()
            self.assertEqual(self.appointment.status, status)
            self.assertEqual(self.appointment.cancelled_by, '')
        self.assertFalse(AppointmentEmail.objects.exists())

    def test_contract_is_not_cancelled_or_affected(self):
        change_status(self.appointment.pk, VA.Status.DA_XAC_NHAN, start_time='09:00')
        tenant = Tenant.objects.create(full_name='Người thuê thử', id_card_number='099999999991', phone='0901111222')
        contract = create_contract(self.room, [tenant], tenant, self.today, self.today + timedelta(days=365),
                                   0, appointment_id=self.appointment.pk)
        self.cancel()
        self.appointment.refresh_from_db()
        contract.refresh_from_db()
        self.assertEqual((self.appointment.status, self.appointment.contract_id), (VA.Status.DA_CHOT, contract.pk))
        self.assertEqual(contract.status, Contract.Status.HIEU_LUC)

    def test_owner_reason_stays_required_and_guest_cannot_overwrite_owner_cancel(self):
        with self.assertRaises(ValidationError):
            change_status(self.appointment.pk, VA.Status.HUY)
        change_status(self.appointment.pk, VA.Status.HUY, 'Chủ trọ bận')
        self.cancel({'reason': 'Khách ghi lại'})
        self.appointment.refresh_from_db()
        self.assertEqual((self.appointment.cancelled_by, self.appointment.cancellation_reason), (VA.CancelledBy.OWNER, 'Chủ trọ bận'))
        self.assertEqual(unread_count(self.owner), 0)

    def test_owner_bell_links_to_cancelled_appointment_and_can_mark_read(self):
        self.cancel()
        response = self.owner_panel()
        item = response.context['notifications'][0]
        self.assertEqual(item['notification_kind'], NotificationRead.Kind.OWNER_APPOINTMENT_CANCEL)
        self.assertContains(response, 'Khách đã hủy lịch xem phòng')
        self.assertContains(response, 'Không ghi lý do')
        self.assertEqual(item['url'], reverse('appointment_detail', args=[self.appointment.pk]))
        self.assertTrue(item['is_unread'])
        self.assertEqual(unread_count(self.owner), 1)
        response = self.client.post(reverse('notification_mark_read'), {'token': item['read_token']})
        self.assertEqual(response.json()['unread_count'], 0)
        self.assertEqual(response.json()['url'], item['url'])
        self.assertFalse(self.owner_panel().context['notifications'][0]['is_unread'])

    def test_cancellation_is_unread_even_if_original_booking_was_read(self):
        original = self.owner_panel().context['notifications'][0]
        self.client.post(reverse('notification_mark_read'), {'token': original['read_token']})
        self.assertEqual(unread_count(self.owner), 0)
        self.client.logout()
        self.cancel()
        self.assertEqual(unread_count(self.owner), 1)
        second_owner = User.objects.create_user('another-owner', role='owner')
        self.owner_panel()
        item = self.owner_panel().context['notifications'][0]
        self.client.post(reverse('notification_mark_read'), {'token': item['read_token']})
        self.assertEqual(unread_count(second_owner), 1)

    def test_guest_receives_cancellation_receipt_with_optional_reason(self):
        self.cancel({'reason': 'Khách bận'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['guest@example.com'])
        self.assertIn('Bạn đã hủy lịch xem phòng', mail.outbox[0].subject)
        self.assertIn('Khách bận', mail.outbox[0].body)
        self.assertIn('Khách đặt lịch', mail.outbox[0].body)
        self.assertNotIn('Lời nhắn trước đó của chủ trọ', mail.outbox[0].body)

    def test_smtp_failure_does_not_undo_cancellation_or_owner_notification(self):
        with patch('rooms.appointment_emails.EmailMultiAlternatives.send', side_effect=OSError):
            self.cancel()
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, VA.Status.HUY)
        self.assertEqual(AppointmentEmail.objects.get().status, AppointmentEmail.Status.FAILED)
        self.assertEqual(unread_count(self.owner), 1)

    def test_no_email_legacy_guest_still_notifies_owner(self):
        VA.objects.filter(pk=self.appointment.pk).update(visitor_email='')
        self.cancel()
        self.assertFalse(AppointmentEmail.objects.exists())
        self.assertEqual(unread_count(self.owner), 1)

    def test_reason_is_escaped_on_public_owner_and_notification_pages(self):
        self.cancel({'reason': '<script>alert(1)</script>'})
        for response in (self.client.get(self.status_url), self.owner_panel(),
                         self.client.get(reverse('appointment_detail', args=[self.appointment.pk]))):
            self.assertNotContains(response, '<script>alert(1)</script>')
            self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_transaction_rollback_leaves_no_cancellation_notification_or_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError), transaction.atomic():
                cancel_by_guest(self.appointment.code)
                raise ValidationError('rollback')
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, VA.Status.CHO_XAC_NHAN)
        self.assertIsNone(self.appointment.cancelled_at)
        self.assertFalse(AppointmentEmail.objects.exists())
        cancellations = [item for item in owner_notification_feed(self.owner)
                         if item['notification_kind'] == 'owner_appointment_cancel']
        self.assertEqual(cancellations, [])

    def test_public_cancel_page_is_not_cached_and_closed_status_has_no_form(self):
        response = self.client.get(self.status_url)
        self.assertIn('no-store', response['Cache-Control'])
        self.cancel()
        response = self.client.get(self.status_url)
        self.assertNotContains(response, 'id="cancelAppointmentModal"')
