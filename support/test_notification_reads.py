from datetime import timedelta
from unittest.mock import patch

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice, Payment, PaymentNotice
from rooms.models import ViewingAppointment
from .models import Announcement, MaintenanceRequest as MR, NotificationRead
from .notifications import read_token
from .services import transition
from .tests import SupportBase


class NotificationReadTests(SupportBase):
    def setUp(self):
        self.client.force_login(self.user)

    def announce(self, title='Thông báo mới'):
        return Announcement.objects.create(title=title, content='Nội dung thông báo', created_by=self.owner)

    def panel(self, owner=False):
        return self.client.get(reverse('owner_notifications_panel' if owner else 'my_notifications_panel'))

    def count(self):
        response = self.client.get(reverse('notification_count'))
        self.assertEqual(response.status_code, 200)
        return response.json()['unread_count']

    def read(self, token):
        return self.client.post(reverse('notification_mark_read'), {'token': token})

    def test_opening_panel_does_not_read_and_reading_one_leaves_other_unread(self):
        first, second = self.announce('Tin thứ nhất'), self.announce('Tin thứ hai')
        self.assertEqual(self.count(), 2)
        response = self.panel()
        self.assertEqual(response['X-Notification-Unread-Count'], '2')
        items = list(response.context['notifications'])
        self.assertTrue(all(item['is_unread'] for item in items))
        self.assertFalse(NotificationRead.objects.exists())
        item = next(item for item in items if item['id'] == first.pk)
        result = self.read(item['read_token'])
        self.assertEqual(result.json(), {'url': reverse('my_announcement_detail', args=[first.pk]),
                                         'is_unread': False, 'unread_count': 1})
        states = {item['id']: item['is_unread'] for item in self.panel().context['notifications']}
        self.assertFalse(states[first.pk])
        self.assertTrue(states[second.pk])
        self.assertEqual(self.read(item['read_token']).json()['unread_count'], 1)
        self.assertEqual(NotificationRead.objects.count(), 1)

    def test_read_state_survives_login_and_zero_badge_is_hidden(self):
        self.announce()
        token = self.panel().context['notifications'][0]['read_token']
        self.read(token)
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['notification_unread_count'], 0)
        self.assertContains(response, 'id="notificationUnreadCount" aria-hidden="true" hidden')
        response = self.panel()
        self.assertFalse(response.context['notifications'][0]['is_unread'])
        self.assertNotContains(response, 'is-unread')

    def test_each_user_reads_independently_and_cannot_reuse_another_users_token(self):
        repair = self.make_request()
        self.client.force_login(self.owner)
        token = self.panel(owner=True).context['notifications'][0]['read_token']
        another = User.objects.create_user('second-owner', role='owner')
        self.client.force_login(another)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.read(token).status_code, 400)
        self.assertFalse(NotificationRead.objects.exists())
        second_token = self.panel(owner=True).context['notifications'][0]['read_token']
        self.read(second_token)
        self.assertEqual(self.count(), 0)
        self.client.force_login(self.owner)
        self.assertEqual(self.count(), 1)
        self.assertEqual(NotificationRead.objects.get().object_id, repair.pk)

    def test_new_announcement_revision_becomes_unread_and_stale_click_does_not_read_it(self):
        item = self.announce()
        old_token = self.panel().context['notifications'][0]['read_token']
        self.read(old_token)
        self.assertEqual(self.count(), 0)
        item.content = 'Nội dung đã được cập nhật'
        item.save()
        self.assertEqual(self.count(), 1)
        result = self.read(old_token).json()
        self.assertTrue(result['is_unread'])
        self.assertEqual(result['unread_count'], 1)
        token = self.panel().context['notifications'][0]['read_token']
        self.read(token)
        result = self.read(old_token).json()
        self.assertFalse(result['is_unread'])
        self.assertEqual(result['unread_count'], 0)
        self.assertEqual(NotificationRead.objects.get().version, item.updated_at)

    def test_new_repair_reply_becomes_unread_again(self):
        repair = self.make_request()
        transition(repair, MR.Status.DANG_XU_LY, owner_note='Đã hẹn thợ')
        token = self.panel().context['notifications'][0]['read_token']
        self.read(token)
        self.assertEqual(self.count(), 0)
        transition(repair, MR.Status.HOAN_THANH, owner_note='Đã sửa xong')
        self.assertEqual(self.count(), 1)
        self.assertTrue(self.panel().context['notifications'][0]['is_unread'])

    def test_all_owner_kinds_read_separately_without_processing_business_actions(self):
        self.make_request()
        today = timezone.localdate()
        appointment = ViewingAppointment.objects.create(room=self.room, visitor_name='Khách', visitor_phone='0901234567',
                                                          appointment_date=today + timedelta(days=1), slot='sang')
        invoice = Invoice.objects.create(contract=self.contract, month=today.month, year=today.year,
                                         room_fee=2500000, total_amount=2500000, due_date=today + timedelta(days=10))
        notice = PaymentNotice.objects.create(invoice=invoice, tenant=self.tenant)
        self.client.force_login(self.owner)
        items = list(self.panel(owner=True).context['notifications'])
        self.assertEqual(self.count(), 3)
        for expected, item in zip([2, 1, 0], items):
            self.assertEqual(self.read(item['read_token']).json()['unread_count'], expected)
        self.assertEqual(NotificationRead.objects.count(), 3)
        self.assertEqual(self.panel(owner=True).context['notifications'].paginator.count, 3)
        notice.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(notice.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertEqual(appointment.status, ViewingAppointment.Status.CHO_XAC_NHAN)
        self.assertFalse(Payment.objects.exists())

    def test_hidden_or_wrong_room_notification_cannot_be_marked_read(self):
        item = self.announce()
        token = self.panel().context['notifications'][0]['read_token']
        item.is_active = False
        item.save()
        self.assertEqual(self.read(token).status_code, 404)
        self.assertEqual(self.count(), 0)
        item.is_active = True
        item.audience = 'rooms'
        item.save()
        item.rooms.set([self.other_room])
        self.assertEqual(self.read(token).status_code, 404)
        self.assertFalse(NotificationRead.objects.exists())

    def test_wrong_role_or_foreign_tenant_record_is_rejected_even_for_signed_payload(self):
        repair = self.make_request()
        payload = {'notification_kind': 'owner_maintenance', 'id': repair.pk, 'notification_time': repair.created_at}
        self.assertEqual(self.read(read_token(self.user, payload)).status_code, 403)
        transition(repair, MR.Status.DANG_XU_LY)
        self.client.force_login(self.other_user)
        payload.update(notification_kind='maintenance', notification_time=repair.updated_at)
        self.assertEqual(self.read(read_token(self.other_user, payload)).status_code, 404)
        self.assertFalse(NotificationRead.objects.exists())

    def test_read_requires_post_csrf_valid_signature_and_login(self):
        self.announce()
        token = self.panel().context['notifications'][0]['read_token']
        url = reverse('notification_mark_read')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.read('tampered').status_code, 400)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(guarded.post(url, {'token': token}).status_code, 403)
        guarded.get(reverse('home'))
        csrf = guarded.cookies['csrftoken'].value
        self.assertEqual(guarded.post(url, {'token': token}, HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.post(url, {'token': token}).status_code, 302)
        self.assertEqual(self.client.get(reverse('notification_count')).status_code, 302)

    def test_expired_token_does_not_change_read_state(self):
        item = self.announce()
        payload = {'notification_kind': 'announcement', 'id': item.pk, 'notification_time': item.updated_at}
        with patch('django.core.signing.time.time', return_value=(timezone.now() - timedelta(days=8)).timestamp()):
            token = read_token(self.user, payload)
        self.assertEqual(self.read(token).status_code, 400)
        self.assertFalse(NotificationRead.objects.exists())
