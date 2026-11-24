from datetime import time, timedelta
from io import StringIO
from smtplib import SMTPAuthenticationError, SMTPRecipientsRefused
from unittest.mock import patch
from email import policy
from email.parser import BytesParser
from socketserver import StreamRequestHandler, TCPServer
from threading import Thread

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from .appointment_emails import dispatch_email, pending_email_ids
from .appointment_services import book_appointment, change_status, reschedule, update_email
from .appointment_schedule import start_datetime
from .models import AppointmentEmail as Mail, Room, ViewingAppointment as VA


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PUBLIC_SITE_URL='https://minhtam.example', DEFAULT_FROM_EMAIL='Minh Tâm <chutro@example.com>',
    EMAIL_REPLY_TO='chutro@example.com', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AppointmentEmailTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.room = Room.objects.create(room_number='201', price=2500000, max_occupants=2)
        self.owner = User.objects.create_user('owner', role='owner')
        self.url = reverse('public_room_detail', args=[self.room.pk])

    def data(self, **changes):
        return {'visitor_name': 'Khách Thử', 'visitor_phone': '0901234567', 'visitor_email': 'khach@example.com',
            'appointment_date': (self.today + timedelta(days=2)).isoformat(), 'slot': 'sang', 'note': '', **changes}

    def book(self, **changes):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, self.data(**changes))
        self.assertEqual(response.status_code, 302)
        return VA.objects.latest('pk')

    def action(self, appointment, status, note=''):
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('appointment_set_status', args=[appointment.pk]),
                                    {'status': status, 'owner_note': note, 'start_time': '09:00'})

    def test_booking_requires_valid_email_and_rejects_header_injection(self):
        for email in ('', 'sai-email', 'khach@example.com\r\nBcc:other@example.com', 'a' * 250 + '@example.com'):
            response = self.client.post(self.url, self.data(visitor_email=email))
            self.assertEqual(response.status_code, 200)
            self.assertIn('visitor_email', response.context['form'].errors)
        self.assertFalse(VA.objects.exists())
        self.assertFalse(Mail.objects.exists())

    def test_booking_only_sends_after_commit_and_remains_pending_confirmation(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(self.url, self.data(visitor_email='khach@EXAMPLE.COM'))
        appointment = VA.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(appointment.visitor_email, 'khach@example.com')
        self.assertEqual(appointment.status, VA.Status.CHO_XAC_NHAN)
        record = Mail.objects.get()
        self.assertEqual(record.status, Mail.Status.PENDING)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        for value in (appointment.code, 'P.201', f'{appointment.appointment_date:%d/%m/%Y}', 'Chờ xác nhận',
                      'Đây chưa phải lịch đã được xác nhận.', 'https://minhtam.example/tra-cuu-lich-hen/'):
            self.assertIn(value, message.body)
        self.assertEqual(message.to, ['khach@example.com'])
        self.assertEqual(message.reply_to, ['chutro@example.com'])
        self.assertEqual(message.alternatives[0].mimetype, 'text/html')
        record.refresh_from_db()
        self.assertEqual(record.status, Mail.Status.SENT)
        self.assertIsNotNone(record.sent_at)

    def test_confirmation_cancellation_and_reason_are_emailed_once(self):
        appointment = self.book()
        self.action(appointment, 'da_xac_nhan', 'Gọi chủ trọ khi đến')
        self.assertIn('Lịch xem phòng đã được xác nhận', mail.outbox[-1].subject)
        self.assertIn('Gọi chủ trọ khi đến', mail.outbox[-1].body)
        self.action(appointment, 'da_xac_nhan')
        self.assertEqual(len(mail.outbox), 2)
        self.action(appointment, 'huy', 'Phòng cần sửa đường nước, xin lỗi khách')
        self.assertIn('Lịch xem phòng đã được hủy', mail.outbox[-1].subject)
        self.assertIn('Phòng cần sửa đường nước', mail.outbox[-1].body)
        self.assertIn('Vui lòng không đến theo lịch cũ', mail.outbox[-1].body)
        self.action(appointment, 'huy', 'Lặp thao tác')
        self.assertEqual(len(mail.outbox), 3)

    def test_invalid_jump_and_cancellation_without_reason_do_not_send(self):
        appointment = self.book()
        self.action(appointment, 'da_chot')
        self.action(appointment, 'huy')
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, VA.Status.CHO_XAC_NHAN)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Mail.objects.count(), 1)

    def test_visited_and_leased_updates_also_send(self):
        appointment = self.book()
        for status in ('da_xac_nhan', 'da_xem'):
            if status == 'da_xem':
                visit_at = start_datetime(appointment.appointment_date, time(9)) + timedelta(minutes=30)
                with patch('rooms.appointment_schedule.timezone.now', return_value=visit_at):
                    self.action(appointment, status)
            else:
                self.action(appointment, status)
        tenant = Tenant.objects.create(full_name='Khách Thử', id_card_number='099999999992', phone='0901234567')
        from .services import create_contract
        with self.captureOnCommitCallbacks(execute=True):
            create_contract(self.room, [tenant], tenant, self.today, self.today + timedelta(days=365), 0,
                            appointment_id=appointment.pk)
        self.assertEqual(list(appointment.emails.values_list('event', flat=True)),
                         ['leased', 'visited', 'confirmed', 'booked'])
        self.assertEqual(len(mail.outbox), 4)

    def test_reschedule_contains_old_and_new_time_and_preserves_status(self):
        appointment = self.book()
        self.action(appointment, 'da_xac_nhan')
        self.client.force_login(self.owner)
        date = self.today + timedelta(days=5)
        payload = {'appointment_date': date.isoformat(), 'slot': 'toi', 'start_time': '18:00', 'owner_note': 'Mời khách đến buổi tối'}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('appointment_reschedule', args=[appointment.pk]), payload)
        message = mail.outbox[-1]
        self.assertIn('Lịch cũ:', message.body)
        self.assertIn(f'{appointment.appointment_date:%d/%m/%Y}', message.body)
        self.assertIn(f'Lịch mới: {date:%d/%m/%Y}', message.body)
        self.assertIn('Buổi tối', message.body)
        self.assertIn('Mời khách đến buổi tối', message.body)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, VA.Status.DA_XAC_NHAN)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('appointment_reschedule', args=[appointment.pk]), payload)
        self.assertEqual(len(mail.outbox), 3)

    def test_invalid_reschedule_and_closed_appointment_do_not_send(self):
        appointment = self.book()
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('appointment_reschedule', args=[appointment.pk]),
                {'appointment_date': (self.today - timedelta(days=1)).isoformat(), 'slot': 'sang'})
        self.action(appointment, 'huy', 'Khách bận')
        with self.assertRaises(ValidationError):
            reschedule(appointment.pk, {'appointment_date': self.today, 'slot': 'chieu'})
        self.assertEqual(len(mail.outbox), 2)

    def test_failed_mail_never_discards_booking_and_owner_can_retry(self):
        with patch('rooms.appointment_emails.EmailMultiAlternatives.send',
                   side_effect=SMTPAuthenticationError(535, b'secret-do-not-show')):
            appointment = self.book()
        record = Mail.objects.get()
        self.assertEqual((record.status, record.error_code, record.attempts), ('failed', 'authentication', 1))
        self.assertIsNotNone(record.next_attempt_at)
        self.assertFalse(dispatch_email(record.pk))  # Wait for backoff unless an owner explicitly retries.
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('appointment_detail', args=[appointment.pk])), 'secret-do-not-show')
        retry = reverse('appointment_retry_email', args=[appointment.pk])
        self.assertEqual(self.client.post(retry).status_code, 302)
        record.refresh_from_db()
        self.assertEqual((record.status, record.attempts), ('sent', 2))
        self.client.post(retry)
        self.assertEqual(len(mail.outbox), 1)

    def test_zero_accepted_messages_is_a_failure(self):
        with patch('rooms.appointment_emails.EmailMultiAlternatives.send', return_value=0):
            self.book()
        self.assertEqual(Mail.objects.get().status, Mail.Status.FAILED)

    def test_recipient_failure_is_safe_and_shown_only_to_owner(self):
        with patch('rooms.appointment_emails.EmailMultiAlternatives.send',
                   side_effect=SMTPRecipientsRefused({'khach@example.com': (550, b'private server text')})):
            appointment = self.book()
        record = Mail.objects.get()
        self.assertEqual(record.error_code, 'recipient')
        response = self.client.get(reverse('appointment_status', args=[appointment.code]))
        self.assertContains(response, 'email thông báo chưa gửi thành công')
        self.assertNotContains(response, 'private server text')
        self.assertNotContains(response, 'khach@example.com')
        self.assertContains(response, 'k***@example.com')

    def test_console_backend_is_preview_and_can_send_after_configuration_changes(self):
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'), patch('sys.stdout', new=StringIO()):
            appointment = self.book()
            self.assertEqual(appointment.emails.first().status, Mail.Status.PREVIEW)
            self.client.force_login(self.owner)
            self.assertContains(self.client.get(reverse('appointment_detail', args=[appointment.pk])), 'chưa gửi thư thật')
        record = appointment.emails.first()
        self.assertIn(record.pk, pending_email_ids())
        self.assertTrue(dispatch_email(record.pk))
        record.refresh_from_db()
        self.assertEqual(record.status, Mail.Status.SENT)

    def test_missing_smtp_configuration_queues_without_using_an_attempt(self):
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST=''):
            self.book()
            with self.assertRaises(CommandError):
                call_command('send_appointment_emails', stdout=StringIO())
        record = Mail.objects.get()
        self.assertEqual((record.status, record.attempts, record.error_code), ('pending', 0, 'not_configured'))

    def test_queued_email_uses_new_public_domain_after_configuration_changes(self):
        self.client.post(self.url, self.data())
        record = Mail.objects.get()
        with override_settings(PUBLIC_SITE_URL='https://nhatro-moi.example'):
            self.assertTrue(dispatch_email(record.pk))
        message = mail.outbox[-1]
        self.assertIn('https://nhatro-moi.example/tra-cuu-lich-hen/', message.body)
        self.assertNotIn('https://minhtam.example/', message.body)
        self.assertIn('https://nhatro-moi.example/tra-cuu-lich-hen/', message.alternatives[0].content)

    def test_invalid_public_url_does_not_send_broken_links(self):
        with override_settings(PUBLIC_SITE_URL='javascript:alert(1)'):
            self.book()
        record = Mail.objects.get()
        self.assertEqual((record.status, record.attempts, record.error_code), ('pending', 0, 'site_url'))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ALLOWED_HOSTS=['testserver', 'attacker.example'])
    def test_links_ignore_request_host_and_html_is_escaped(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, self.data(visitor_name='<img src=x onerror=alert(1)> & Khách'), HTTP_HOST='attacker.example')
        message = mail.outbox[0]
        self.assertNotIn('attacker.example', message.body)
        self.assertIn('https://minhtam.example/tra-cuu-lich-hen/', message.body)
        self.assertIn('<img src=x onerror=alert(1)> & Khách', message.body)
        html = message.alternatives[0].content
        self.assertNotIn('<img src=x onerror=', html)
        self.assertIn('&lt;img', html)

    def test_rollback_discards_appointment_outbox_and_on_commit_callback(self):
        data = self.data(appointment_date=self.today + timedelta(days=2))
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(ValidationError), transaction.atomic():
                book_appointment(self.room, data)
                raise ValidationError('rollback')
        self.assertFalse(VA.objects.exists())
        self.assertFalse(Mail.objects.exists())
        self.assertEqual(callbacks, [])
        self.assertEqual(len(mail.outbox), 0)

    def test_pending_old_messages_are_superseded_by_cancellation(self):
        with self.captureOnCommitCallbacks(execute=False):
            response = self.client.post(self.url, self.data())
            self.assertEqual(response.status_code, 302)
            appointment = VA.objects.get()
            first = appointment.emails.first()
            change_status(appointment.pk, VA.Status.HUY, 'Phòng đang sửa chữa')
        first.refresh_from_db()
        latest = appointment.emails.first()
        self.assertEqual(first.status, Mail.Status.SUPERSEDED)
        self.assertFalse(dispatch_email(first.pk, force=True))
        self.assertTrue(dispatch_email(latest.pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('đã được hủy', mail.outbox[0].subject)

    def test_correcting_email_sends_current_details_and_stops_old_recipient(self):
        self.client.post(self.url, self.data())
        appointment = VA.objects.get()
        first = appointment.emails.first()
        self.client.force_login(self.owner)
        url = reverse('appointment_update_email', args=[appointment.pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'visitor_email': 'dung@example.com'})
        self.assertEqual(mail.outbox[-1].to, ['dung@example.com'])
        self.assertIn('Chờ xác nhận', mail.outbox[-1].body)
        first.refresh_from_db()
        self.assertEqual(first.status, Mail.Status.SUPERSEDED)
        self.assertFalse(dispatch_email(first.pk, force=True))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'visitor_email': 'dung@example.com'})
            self.client.post(url, {'visitor_email': 'invalid'})
        self.assertEqual(len(mail.outbox), 1)

    def test_legacy_appointment_without_email_can_be_updated_without_invented_address(self):
        appointment = VA.objects.create(room=self.room, visitor_name='Lịch cũ', visitor_phone='0901234567',
            appointment_date=self.today + timedelta(days=2), slot='sang')
        self.action(appointment, 'da_xac_nhan')
        self.assertFalse(appointment.emails.exists())
        with self.captureOnCommitCallbacks(execute=True):
            update_email(appointment.pk, 'khach@example.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Đã xác nhận', mail.outbox[0].body)

    def test_delivery_command_obeys_backoff_and_does_not_repeat_sent_mail(self):
        with patch('rooms.appointment_emails.EmailMultiAlternatives.send', side_effect=TimeoutError):
            self.book()
        record = Mail.objects.get()
        self.assertNotIn(record.pk, pending_email_ids())
        Mail.objects.filter(pk=record.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        call_command('send_appointment_emails', stdout=StringIO())
        call_command('send_appointment_emails', stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        record.refresh_from_db()
        self.assertEqual(record.status, Mail.Status.SENT)

    def test_active_send_cannot_be_claimed_twice_but_abandoned_send_can_recover(self):
        self.client.post(self.url, self.data())
        record = Mail.objects.get()
        Mail.objects.filter(pk=record.pk).update(status='sending', attempted_at=timezone.now(), attempts=1)
        self.assertFalse(dispatch_email(record.pk, force=True))
        Mail.objects.filter(pk=record.pk).update(attempted_at=timezone.now() - timedelta(minutes=6))
        self.assertTrue(dispatch_email(record.pk))
        self.assertEqual(len(mail.outbox), 1)

    def test_automatic_retry_stops_at_limit_but_owner_can_retry_after_fix(self):
        self.client.post(self.url, self.data())
        record = Mail.objects.get()
        Mail.objects.filter(pk=record.pk).update(status='failed', attempts=5)
        self.assertNotIn(record.pk, pending_email_ids())
        self.assertFalse(dispatch_email(record.pk))
        self.assertTrue(dispatch_email(record.pk, force=True))
        self.assertEqual(len(mail.outbox), 1)

    def test_owner_only_post_actions_and_csrf(self):
        appointment = self.book()
        tenant_user = User.objects.create_user('tenant', role='tenant')
        Tenant.objects.create(user=tenant_user, full_name='Tenant', id_card_number='012345678901', phone='0900000000')
        urls = [reverse(name, args=[appointment.pk]) for name in ('appointment_update_email', 'appointment_retry_email')]
        for url in urls:
            self.assertEqual(self.client.post(url, {'visitor_email': 'attack@example.com'}).status_code, 302)
        self.client.force_login(tenant_user)
        for url in urls:
            self.assertRedirects(self.client.post(url), reverse('home'), fetch_redirect_response=False)
        self.client.force_login(self.owner)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(csrf.post(url).status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.visitor_email, 'khach@example.com')

    def test_email_duplicates_are_blocked_even_with_a_different_phone(self):
        self.book()
        response = self.client.post(self.url, self.data(visitor_phone='0901111222', visitor_email='KHACH@EXAMPLE.COM'))
        self.assertContains(response, 'Email này đã đặt lịch')
        self.assertEqual(VA.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_contract_creation_sends_leased_notification(self):
        appointment = self.book()
        appointment.status = VA.Status.DA_XEM
        appointment.save(update_fields=['status'])
        tenant = Tenant.objects.create(full_name='Khách Thử', id_card_number='099999999991', phone='0901234567')
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('contract_create'), {'room': self.room.pk,
                'tenants': [tenant.pk], 'representative': tenant.pk, 'appointment': appointment.pk,
                'start_date': self.today.isoformat(), 'end_date': (self.today + timedelta(days=365)).isoformat(), 'deposit': 0})
        self.assertEqual(response.status_code, 302)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, VA.Status.DA_CHOT)
        self.assertEqual(appointment.emails.first().event, Mail.Event.LEASED)
        self.assertEqual(len(mail.outbox), 2)

    def test_email_search_and_owner_history(self):
        appointment = self.book(visitor_email='khach-lookup@example.com')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('appointment_list'), {'q': 'khach-lookup@example.com'})
        self.assertEqual(len(response.context['items']), 1)
        self.assertContains(response, 'khach-lookup@example.com')
        self.assertContains(self.client.get(reverse('appointment_detail', args=[appointment.pk])), 'Email cho khách')

    def test_real_smtp_transport_with_private_local_test_server(self):
        class Handler(StreamRequestHandler):
            def handle(self):
                self.wfile.write(b'220 localhost test SMTP\r\n')
                while line := self.rfile.readline():
                    command = line.split(b' ', 1)[0].strip().upper()
                    if command in (b'EHLO', b'HELO'):
                        self.wfile.write(b'250 localhost\r\n')
                    elif command == b'DATA':
                        self.wfile.write(b'354 End with dot\r\n')
                        payload = []
                        while (part := self.rfile.readline()) not in (b'.\r\n', b''):
                            payload.append(part[1:] if part.startswith(b'..') else part)
                        self.server.messages.append(b''.join(payload))
                        self.wfile.write(b'250 Accepted\r\n')
                    elif command == b'QUIT':
                        self.wfile.write(b'221 Bye\r\n')
                        return
                    else:
                        self.wfile.write(b'250 OK\r\n')
        with TCPServer(('127.0.0.1', 0), Handler) as server:
            server.messages = []
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                    EMAIL_HOST='127.0.0.1', EMAIL_PORT=server.server_address[1], EMAIL_HOST_USER='',
                    EMAIL_HOST_PASSWORD='', EMAIL_USE_TLS=False, EMAIL_USE_SSL=False, EMAIL_TIMEOUT=2):
                    appointment = self.book()
                self.assertEqual(appointment.emails.first().status, Mail.Status.SENT)
                self.assertEqual(len(server.messages), 1)
                received = BytesParser(policy=policy.default).parsebytes(server.messages[0])
                self.assertEqual(received['To'], 'khach@example.com')
                self.assertIn(appointment.code, str(received['Subject']))
                self.assertIn('Chờ xác nhận', received.get_body(preferencelist=('plain',)).get_content())
                self.assertIn('Tra cứu lịch hẹn', received.get_body(preferencelist=('html',)).get_content())
            finally:
                server.shutdown()
                thread.join(timeout=3)
