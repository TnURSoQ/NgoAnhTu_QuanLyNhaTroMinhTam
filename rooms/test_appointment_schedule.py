from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from .appointment_schedule import SLOT_STARTS, lock_calendar
from .appointment_services import book_appointment, change_status, reschedule
from .models import AppointmentCalendar, AppointmentEmail, Contract, Room, ViewingAppointment as VA
from .public_forms import BookingForm
from .services import create_contract, transfer_contract


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PUBLIC_SITE_URL='https://nhatro.example',
    EMAIL_REPLY_TO='', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AppointmentScheduleTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.day = self.today + timedelta(days=2)
        self.room = Room.objects.create(room_number='201', price=2500000)
        self.other = Room.objects.create(room_number='202', price=2300000)
        self.owner = User.objects.create_user('owner', role='owner')
        self.index = 0

    def pending(self, room=None, day=None, slot='sang', **extra):
        self.index += 1
        return VA.objects.create(room=room or self.room, appointment_date=day or self.day, slot=slot,
            visitor_name=f'Khách thử {self.index}', visitor_phone=f'090000{self.index:04d}',
            visitor_email=f'guest{self.index}@example.com', **extra)

    def confirm(self, appointment, start='09:00'):
        return change_status(appointment.pk, VA.Status.DA_XAC_NHAN, start_time=start)[0]

    def booking_data(self, **extra):
        return {'visitor_name': 'Khách thử', 'visitor_phone': '0901234567', 'visitor_email': 'guest@example.com',
            'appointment_date': self.day, 'slot': 'sang', 'note': '', **extra}

    def tenant(self):
        return Tenant.objects.create(full_name='Người thuê thử', id_card_number='099999999991', phone='0901234567')

    def lease(self, room=None, appointment=None):
        person = self.tenant()
        return create_contract(room or self.room, [person], person, self.today,
            self.today + timedelta(days=365), 0, appointment_id=appointment.pk if appointment else None)

    def test_multiple_different_customers_can_request_same_room_and_session(self):
        for number in range(3):
            book_appointment(self.room, self.booking_data(visitor_phone=f'090123456{number}',
                visitor_email=f'guest{number}@example.com'))
        self.assertEqual(VA.objects.filter(status=VA.Status.CHO_XAC_NHAN, start_time__isnull=True).count(), 3)
        self.assertEqual(Tenant.objects.count(), 0)

    def test_service_rechecks_duplicates_and_does_not_trust_stale_form(self):
        data = self.booking_data()
        self.assertTrue(BookingForm(data, room=self.room).is_valid())
        book_appointment(self.room, data)
        with self.assertRaises(ValidationError):
            book_appointment(self.room, data)
        self.assertEqual(VA.objects.count(), 1)

    def test_confirmation_requires_exact_time(self):
        appointment = self.pending()
        with self.assertRaises(ValidationError):
            change_status(appointment.pk, VA.Status.DA_XAC_NHAN)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, VA.Status.CHO_XAC_NHAN)
        self.assertFalse(appointment.emails.exists())

    def test_same_time_is_blocked_for_same_room(self):
        self.confirm(self.pending())
        second = self.pending()
        with self.assertRaises(ValidationError):
            self.confirm(second)
        second.refresh_from_db()
        self.assertEqual(second.status, VA.Status.CHO_XAC_NHAN)

    def test_calendar_is_shared_across_different_rooms(self):
        self.confirm(self.pending())
        with self.assertRaises(ValidationError):
            self.confirm(self.pending(room=self.other))

    def test_adjacent_half_hours_are_allowed(self):
        self.confirm(self.pending(), '09:00')
        result = self.confirm(self.pending(room=self.other), '09:30')
        self.assertEqual(result.time_label, '09:30–10:00')

    def test_different_dates_do_not_conflict(self):
        self.confirm(self.pending())
        result = self.confirm(self.pending(day=self.day + timedelta(days=1)))
        self.assertEqual(result.status, VA.Status.DA_XAC_NHAN)

    def test_bad_grid_seconds_and_wrong_session_are_rejected(self):
        appointment = self.pending()
        for start in ('09:15', '09:00:01', '13:30', '11:30', '07:30', 'bad'):
            with self.subTest(start=start), self.assertRaises(ValidationError):
                self.confirm(appointment, start)

    def test_last_slots_finish_at_session_end(self):
        for slot, start, label in [('sang', '11:00', '11:00–11:30'), ('chieu', '16:30', '16:30–17:00'),
                                    ('toi', '19:30', '19:30–20:00')]:
            self.assertEqual(self.confirm(self.pending(slot=slot), start).time_label, label)
        self.assertEqual(sum(map(len, SLOT_STARTS.values())), 18)

    def test_past_confirmation_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.confirm(self.pending(day=self.today - timedelta(days=1)))

    def test_request_for_finished_session_is_rejected(self):
        midday = timezone.make_aware(datetime.combine(self.today, time(12)))
        with patch('rooms.appointment_schedule.timezone.now', return_value=midday):
            form = BookingForm(self.booking_data(appointment_date=self.today), room=self.room)
            self.assertFalse(form.is_valid())
            self.assertIn('slot', form.errors)

    def test_cancellation_releases_the_time(self):
        first = self.confirm(self.pending())
        change_status(first.pk, VA.Status.HUY, 'Khách xin hủy')
        second = self.confirm(self.pending(room=self.other))
        self.assertEqual(second.start_time, time(9))
        first.refresh_from_db()
        self.assertEqual(first.start_time, time(9))  # Preserve the cancelled schedule as history.

    def test_reschedule_only_time_changes_and_releases_old_time(self):
        first = self.confirm(self.pending())
        with self.captureOnCommitCallbacks(execute=True):
            changed, did_change = reschedule(first.pk, {'appointment_date': self.day, 'slot': 'sang', 'start_time': '09:30'})
        self.assertTrue(did_change)
        self.assertEqual(changed.start_time, time(9, 30))
        self.assertIn('09:00–09:30', mail.outbox[-1].body)
        self.assertIn('09:30–10:00', mail.outbox[-1].body)
        self.confirm(self.pending(room=self.other), '09:00')

    def test_failed_reschedule_preserves_old_time_status_and_email_version(self):
        first = self.confirm(self.pending())
        second = self.confirm(self.pending(room=self.other), '09:30')
        version = first.notification_version
        with self.assertRaises(ValidationError):
            reschedule(first.pk, {'appointment_date': self.day, 'slot': 'sang', 'start_time': '09:30'})
        first.refresh_from_db()
        self.assertEqual((first.start_time, first.status, first.notification_version), (time(9), VA.Status.DA_XAC_NHAN, version))
        self.assertEqual(second.status, VA.Status.DA_XAC_NHAN)

    def test_pending_reschedule_never_reserves_a_time(self):
        pending = self.pending()
        updated, _ = reschedule(pending.pk, {'appointment_date': self.day, 'slot': 'chieu', 'start_time': '14:00'})
        self.assertIsNone(updated.start_time)
        self.assertEqual(updated.status, VA.Status.CHO_XAC_NHAN)

    def test_legacy_confirmations_block_new_requests_until_their_times_are_resolved(self):
        legacy = self.pending(status=VA.Status.DA_XAC_NHAN)
        another_legacy = self.pending(room=self.other, status=VA.Status.DA_XAC_NHAN)
        candidate = self.pending()
        with self.assertRaises(ValidationError):
            self.confirm(candidate)
        reschedule(legacy.pk, {'appointment_date': self.day, 'slot': 'sang', 'start_time': '09:00'})
        with self.assertRaises(ValidationError):
            self.confirm(candidate, '10:00')
        reschedule(another_legacy.pk, {'appointment_date': self.day, 'slot': 'sang', 'start_time': '09:30'})
        self.confirm(candidate, '10:00')

    def test_database_rejects_confirmed_double_booking_and_invalid_grid(self):
        self.confirm(self.pending())
        second = self.pending(room=self.other)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VA.objects.filter(pk=second.pk).update(status=VA.Status.DA_XAC_NHAN, start_time=time(9))
        with self.assertRaises(IntegrityError), transaction.atomic():
            VA.objects.filter(pk=second.pk).update(start_time=time(9, 15))

    def test_stale_room_object_cannot_accept_new_booking(self):
        Room.objects.filter(pk=self.room.pk).update(status=Room.Status.BAO_TRI)
        with self.assertRaises(ValidationError):
            book_appointment(self.room, self.booking_data())
        self.assertFalse(VA.objects.exists())

    def test_confirmation_does_not_reserve_or_rent_room(self):
        self.confirm(self.pending())
        self.room.refresh_from_db()
        self.assertEqual(self.room.status, Room.Status.TRONG)
        self.assertFalse(Contract.objects.exists())

    def test_contract_converts_source_cancels_upcoming_others_and_preserves_history(self):
        source = self.confirm(self.pending())
        waiting = self.pending()
        confirmed = self.confirm(self.pending(), '09:30')
        other_room = self.confirm(self.pending(room=self.other), '10:00')
        old = self.pending(day=self.today - timedelta(days=1))
        seen = self.pending(status=VA.Status.DA_XEM)
        with self.captureOnCommitCallbacks(execute=True):
            contract = self.lease(appointment=source)
        source.refresh_from_db()
        self.assertEqual((source.status, source.contract_id), (VA.Status.DA_CHOT, contract.pk))
        for appointment in (waiting, confirmed):
            appointment.refresh_from_db()
            self.assertEqual(appointment.status, VA.Status.HUY)
            self.assertIn('Phòng đã có người thuê', appointment.owner_note)
            self.assertEqual(appointment.emails.first().event, AppointmentEmail.Event.CANCELLED)
        for appointment, status in [(other_room, VA.Status.DA_XAC_NHAN), (old, VA.Status.CHO_XAC_NHAN), (seen, VA.Status.DA_XEM)]:
            appointment.refresh_from_db()
            self.assertEqual(appointment.status, status)
        self.assertEqual(sum('chốt thuê' in message.subject for message in mail.outbox), 1)
        self.assertEqual(sum('đã được hủy' in message.subject for message in mail.outbox), 2)

    def test_contract_without_source_still_cancels_future_requests(self):
        waiting = self.pending()
        self.lease()
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, VA.Status.HUY)

    def test_contract_source_must_be_valid_and_same_room(self):
        wrong_room = self.confirm(self.pending(room=self.other))
        with self.assertRaises(ValidationError):
            self.lease(appointment=wrong_room)
        self.assertFalse(Contract.objects.exists())
        pending = self.pending()
        person = Tenant.objects.first()
        with self.assertRaises(ValidationError):
            create_contract(self.room, [person], person, self.today, self.day, 0, appointment_id=pending.pk)

    def test_manual_status_cannot_fake_a_signed_contract(self):
        appointment = self.pending(status=VA.Status.DA_XEM)
        with self.assertRaises(ValidationError):
            change_status(appointment.pk, VA.Status.DA_CHOT)

    def test_future_visit_cannot_release_a_confirmed_time_early(self):
        appointment = self.confirm(self.pending())
        with self.assertRaises(ValidationError):
            change_status(appointment.pk, VA.Status.DA_XEM)
        with self.assertRaises(ValidationError):
            self.confirm(self.pending(room=self.other))

    def test_rollback_of_contract_restores_all_appointments_and_sends_nothing(self):
        waiting = self.pending()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValidationError), transaction.atomic():
                self.lease()
                raise ValidationError('rollback')
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, VA.Status.CHO_XAC_NHAN)
        self.assertFalse(Contract.objects.exists())
        self.assertFalse(AppointmentEmail.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_transfer_cancels_requests_in_new_room(self):
        old_contract = self.lease()
        target = self.pending(room=self.other)
        transfer_contract(old_contract, self.other, self.today, self.day)
        target.refresh_from_db()
        self.assertEqual(target.status, VA.Status.HUY)

    def test_direct_model_contract_creation_reconciles_after_commit(self):
        waiting = self.pending()
        with self.captureOnCommitCallbacks(execute=True):
            Contract.objects.create(room=self.room, start_date=self.today, end_date=self.day)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, VA.Status.HUY)

    def test_calendar_page_shows_confirmed_times_and_other_rooms(self):
        appointment = self.confirm(self.pending(room=self.other))
        self.client.force_login(self.owner)
        response = self.client.get(reverse('appointment_list'), {'calendar_date': self.day.isoformat()})
        self.assertContains(response, '09:00–09:30')
        self.assertEqual(response.context['calendar_items'], [appointment])
        candidate = self.pending()
        self.assertContains(self.client.get(reverse('appointment_detail', args=[candidate.pk])), 'P.202')

    def test_confirmation_form_enforces_time_and_preserves_error(self):
        appointment = self.pending()
        self.client.force_login(self.owner)
        url = reverse('appointment_set_status', args=[appointment.pk])
        response = self.client.post(url, {'status': VA.Status.DA_XAC_NHAN})
        self.assertEqual(response.status_code, 200)
        self.assertIn('start_time', response.context['confirmation_form'].errors)
        self.assertEqual(self.client.post(url, {'status': VA.Status.DA_XAC_NHAN, 'start_time': '09:00'}).status_code, 302)
        self.assertContains(self.client.get(reverse('appointment_status', args=[appointment.code])), '09:00–09:30')

    def test_calendar_lock_is_transactional_and_recreated_if_missing(self):
        AppointmentCalendar.objects.all().delete()
        with transaction.atomic():
            lock_calendar()
        self.assertTrue(AppointmentCalendar.objects.filter(pk=1).exists())
