from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice, Payment, PaymentNotice
from rooms.models import ViewingAppointment
from .models import MaintenanceRequest as MR
from .tests import SupportBase


class OwnerNotificationTests(SupportBase):
    def setUp(self):
        self.client.force_login(self.owner)

    def appointment(self, **changes):
        return ViewingAppointment.objects.create(
            room=self.room, visitor_name='Khách đặt lịch', visitor_phone='0901234567',
            appointment_date=timezone.localdate() + timedelta(days=1), slot='sang', **changes)

    def transfer(self, **changes):
        today = timezone.localdate()
        invoice = Invoice.objects.create(contract=self.contract, month=today.month, year=today.year,
                                         room_fee=2500000, total_amount=2500000, due_date=today + timedelta(days=10))
        return PaymentNotice.objects.create(invoice=invoice, tenant=self.tenant, amount=2500000, **changes)

    def test_all_pending_types_have_correct_links_without_changing_finances(self):
        repair = self.make_request()
        appointment = self.appointment()
        transfer = self.transfer()
        response = self.client.get(reverse('owner_notifications_panel'))
        self.assertEqual(response.context['notifications'].paginator.count, 3)
        self.assertContains(response, 'Yêu cầu sửa chữa:')
        self.assertContains(response, 'Lịch hẹn xem phòng mới')
        self.assertContains(response, 'Báo chuyển khoản chờ xác nhận')
        self.assertContains(response, 'Ngày xem phòng:')
        for route, pk in [('maintenance_detail', repair.pk), ('appointment_detail', appointment.pk),
                          ('invoice_detail', transfer.invoice_id)]:
            self.assertContains(response, reverse(route, args=[pk]))
        times = [item['notification_time'] for item in response.context['notifications']]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, PaymentNotice.Status.CHO_XAC_NHAN)
        self.assertFalse(Payment.objects.exists())

    def test_handled_items_are_excluded_and_empty_state_is_one_message(self):
        for status in [MR.Status.DANG_XU_LY, MR.Status.HOAN_THANH, MR.Status.DA_HUY]:
            self.make_request(status=status)
        for status in [ViewingAppointment.Status.DA_XAC_NHAN, ViewingAppointment.Status.HUY]:
            self.appointment(status=status)
        self.transfer(status=PaymentNotice.Status.DA_XAC_NHAN)
        response = self.client.get(reverse('owner_notifications_panel'))
        self.assertHTMLEqual(response.content.decode(), '<p class="notification-empty">Không có thông báo</p>')

    def test_paginated_panel_keeps_owner_endpoint_and_escapes_content(self):
        for index in range(11):
            self.make_request(title=f'Sự cố {index:02d}')
        self.make_request(title='<script>alert(1)</script>')
        url = reverse('owner_notifications_panel')
        response = self.client.get(url)
        self.assertEqual(len(response.context['notifications']), 10)
        self.assertContains(response, url + '?page=2')
        self.assertNotContains(response, reverse('my_notifications_panel') + '?page=2')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertEqual(len(self.client.get(url, {'page': 2}).context['notifications']), 2)

    def test_owner_without_admin_permissions_can_read_but_tenants_staff_and_guests_cannot(self):
        self.owner.is_staff = False
        self.owner.save(update_fields=['is_staff'])
        url = reverse('owner_notifications_panel')
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(url), reverse('home'))
        staff = User.objects.create_user('notification-staff', is_staff=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(url), reverse('home'))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
