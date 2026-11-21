from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Tenant, User
from support.models import NotificationRead
from support.tests import SupportBase
from .cooccupants import cancel_request, review_request, submit_request
from .models import CoOccupantRequest as Request, Contract, ContractTenant


class CoOccupantTests(SupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.room.max_occupants = 3
        cls.room.save()
        cls.contract.contract_tenants.update(is_representative=True)

    def data(self, **changes):
        return {'full_name': 'Lê Văn Bình', 'id_card_number': '012345678901', 'phone': '0901111222',
                'email': 'binh@example.com', 'date_of_birth': '2001-05-12', 'hometown': 'Đà Nẵng',
                'occupation': 'Sinh viên', 'note': 'Đề nghị thêm người ở cùng', 'confirm_information': 'on', **changes}

    def proposal(self, **changes):
        return submit_request(self.contract, self.tenant, self.data(**changes))

    def approve(self, proposal, **changes):
        return review_request(proposal, self.owner, action='approve', confirm_information=True, **changes)

    def test_submit_is_staged_and_tampered_post_cannot_choose_room_status_or_sender(self):
        self.client.force_login(self.user)
        before = (Tenant.objects.count(), User.objects.count(), ContractTenant.objects.count())
        response = self.client.post(reverse('cooccupant_create'), self.data(
            contract=9999, submitted_by=self.other_tenant.pk, approved_tenant=self.other_tenant.pk,
            status='approved', is_representative='on', user=self.owner.pk))
        proposal = Request.objects.get()
        self.assertRedirects(response, reverse('my_cooccupant_detail', args=[proposal.pk]))
        self.assertEqual(proposal.contract_id, self.contract.pk)
        self.assertEqual(proposal.submitted_by_id, self.tenant.pk)
        self.assertEqual(proposal.status, Request.Status.PENDING)
        self.assertIsNone(proposal.approved_tenant_id)
        self.assertEqual(before, (Tenant.objects.count(), User.objects.count(), ContractTenant.objects.count()))
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('cooccupant_review_list')), proposal.full_name)
        self.assertNotContains(self.client.get(reverse('residents_print')), proposal.full_name)
        self.assertEqual(self.client.get(reverse('notification_count')).json()['unread_count'], 1)

    def test_approve_creates_cooccupant_without_login_and_includes_them_in_roster(self):
        proposal = self.proposal()
        users = User.objects.count()
        result = self.approve(proposal)
        tenant = result.approved_tenant
        self.assertIsNone(tenant.user_id)
        self.assertEqual(User.objects.count(), users)
        link = ContractTenant.objects.get(contract=self.contract, tenant=tenant)
        self.assertFalse(link.is_representative)
        self.assertEqual(result.reviewed_by, self.owner)
        self.assertIsNotNone(result.reviewed_at)
        self.assertEqual(self.contract.contract_tenants.count(), 2)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('residents_print')), tenant.full_name)
        self.assertEqual(self.client.get(reverse('notification_count')).json()['unread_count'], 0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('notification_count')).json()['unread_count'], 1)
        panel = self.client.get(reverse('my_notifications_panel'))
        self.assertContains(panel, reverse('my_cooccupant_detail', args=[proposal.pk]))
        self.assertContains(panel, 'Đã xác nhận')

    def test_reject_requires_reason_and_resubmission_preserves_history(self):
        proposal = self.proposal()
        with self.assertRaises(ValidationError):
            review_request(proposal, self.owner, action='reject')
        first = review_request(proposal, self.owner, action='reject', review_note='Kiểm tra lại số điện thoại')
        self.assertIsNone(first.approved_tenant_id)
        self.client.force_login(self.user)
        response = self.client.get(reverse('cooccupant_resubmit', args=[first.pk]))
        self.assertContains(response, 'Kiểm tra lại số điện thoại')
        response = self.client.post(reverse('cooccupant_resubmit', args=[first.pk]), self.data(phone='0905555666'))
        second = Request.objects.exclude(pk=first.pk).get()
        self.assertRedirects(response, reverse('my_cooccupant_detail', args=[second.pk]))
        self.assertEqual(second.previous_request_id, first.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, Request.Status.REJECTED)
        self.assertEqual(first.review_note, 'Kiểm tra lại số điện thoại')
        self.assertEqual(first.phone, '0901111222')
        self.assertEqual(self.approve(second).approved_tenant.phone, '0905555666')

    def test_only_active_representative_can_submit(self):
        self.client.force_login(self.other_user)
        self.assertRedirects(self.client.post(reverse('cooccupant_create'), self.data()), reverse('my_cooccupants'))
        ContractTenant.objects.create(contract=self.contract, tenant=self.other_tenant)
        self.assertRedirects(self.client.post(reverse('cooccupant_create'), self.data()), reverse('my_cooccupants'))
        self.client.force_login(self.user)
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        self.assertRedirects(self.client.post(reverse('cooccupant_create'), self.data()), reverse('my_cooccupants'))
        self.assertFalse(Request.objects.exists())

    def test_representative_and_tenant_status_cannot_be_bypassed_in_services(self):
        with self.assertRaises(PermissionDenied):
            submit_request(self.contract, self.other_tenant, self.data())
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        with self.assertRaises(ValidationError):
            self.proposal()

    def test_pending_and_already_linked_id_are_rejected_without_global_profile_leak(self):
        proposal = self.proposal()
        with self.assertRaises(ValidationError):
            self.proposal()
        self.assertEqual(Request.objects.count(), 1)
        self.approve(proposal)
        with self.assertRaises(ValidationError):
            self.proposal()
        self.assertEqual(Request.objects.count(), 1)

    def test_room_capacity_is_rechecked_when_two_proposals_compete_for_last_place(self):
        self.room.max_occupants = 2
        self.room.save()
        first = self.proposal()
        second = self.proposal(id_card_number='012345678902', full_name='Trần Văn Cường')
        self.approve(first)
        with self.assertRaises(ValidationError):
            self.approve(second)
        second.refresh_from_db()
        self.assertEqual(second.status, Request.Status.PENDING)
        self.assertFalse(Tenant.objects.filter(id_card_number=second.id_card_number).exists())
        self.assertEqual(self.contract.contract_tenants.count(), 2)

    def test_cannot_submit_to_full_room(self):
        self.room.max_occupants = 1
        self.room.save()
        with self.assertRaises(ValidationError):
            self.proposal()
        self.assertFalse(Request.objects.exists())

    def test_existing_profile_requires_owner_ack_and_never_overwrites_its_data(self):
        existing = Tenant.objects.create(full_name='Tên đã đối chiếu', id_card_number='012345678901',
                                          phone='0909999888', occupation='Hồ sơ đã có', note='Ghi chú riêng')
        proposal = self.proposal()
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse('my_cooccupant_detail', args=[proposal.pk])), existing.full_name)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('cooccupant_review', args=[proposal.pk])), existing.full_name)
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        result = self.approve(proposal, reuse_existing=True)
        self.assertEqual(result.approved_tenant_id, existing.pk)
        existing.refresh_from_db()
        self.assertEqual(existing.full_name, 'Tên đã đối chiếu')
        self.assertEqual(existing.phone, '0909999888')
        self.assertEqual(existing.note, 'Ghi chú riêng')

    def test_person_in_another_active_contract_cannot_be_approved(self):
        existing = Tenant.objects.create(full_name='Người đã thuê phòng khác', id_card_number='012345678901', phone='0901111222')
        other_contract = Contract.objects.create(room=self.other_room, start_date=self.contract.start_date,
                                                 end_date=self.contract.end_date)
        ContractTenant.objects.create(contract=other_contract, tenant=existing)
        proposal = self.proposal()
        with self.assertRaises(ValidationError):
            self.approve(proposal, reuse_existing=True)
        self.assertFalse(ContractTenant.objects.filter(contract=self.contract, tenant=existing).exists())

    def test_stale_approval_and_changed_representative_do_not_add_people(self):
        proposal = self.proposal()
        self.contract.contract_tenants.update(is_representative=False)
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        self.assertFalse(Tenant.objects.filter(id_card_number=proposal.id_card_number).exists())
        self.contract.contract_tenants.update(is_representative=True)
        self.approve(proposal)
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        self.assertEqual(self.contract.contract_tenants.count(), 2)

    def test_closed_contract_blocks_approval_but_can_be_rejected_with_explanation(self):
        proposal = self.proposal()
        self.contract.status = Contract.Status.KET_THUC
        self.contract.save()
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        result = review_request(proposal, self.owner, action='reject', review_note='Gửi theo hợp đồng mới')
        self.assertEqual(result.status, Request.Status.REJECTED)

    def test_cancel_is_post_only_owned_and_only_before_review(self):
        proposal = self.proposal()
        self.client.force_login(self.other_user)
        url = reverse('cooccupant_cancel', args=[proposal.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse('my_cooccupant_detail', args=[proposal.pk]))
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Request.Status.CANCELLED)
        with self.assertRaises(ValidationError):
            self.approve(proposal)
        self.client.post(reverse('cooccupant_resubmit', args=[proposal.pk]), self.data())
        self.assertEqual(Request.objects.count(), 2)

    def test_requests_are_private_and_only_owner_can_review(self):
        proposal = self.proposal()
        for account in [self.other_user, self.user]:
            self.client.force_login(account)
            self.assertRedirects(self.client.get(reverse('cooccupant_review', args=[proposal.pk])), reverse('home'))
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(reverse('my_cooccupant_detail', args=[proposal.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('my_cooccupants')), proposal.full_name)
        staff = User.objects.create_user('cooccupant-staff', is_staff=True)
        self.client.force_login(staff)
        self.assertRedirects(self.client.post(reverse('cooccupant_review', args=[proposal.pk]), {
            'action': 'approve', 'confirm_information': 'on'}), reverse('home'))
        self.client.logout()
        self.assertEqual(self.client.get(reverse('cooccupant_review_list')).status_code, 302)

    def test_invalid_submission_and_missing_confirmation_do_not_save(self):
        self.client.force_login(self.user)
        for changes in [{'id_card_number': 'bad'}, {'phone': 'abc'}, {'full_name': ''},
                        {'date_of_birth': (timezone.localdate() + timedelta(days=1)).isoformat()},
                        {'confirm_information': ''}]:
            response = self.client.post(reverse('cooccupant_create'), self.data(**changes))
            self.assertTrue(response.context['form'].errors)
            self.assertFalse(Request.objects.exists())

    def test_review_form_requires_confirmation_and_existing_profile_ack(self):
        Tenant.objects.create(full_name='Đã có hồ sơ', id_card_number='012345678901', phone='0908888999')
        proposal = self.proposal()
        self.client.force_login(self.owner)
        url = reverse('cooccupant_review', args=[proposal.pk])
        response = self.client.post(url, {'action': 'approve'})
        self.assertIn('confirm_information', response.context['form'].errors)
        self.assertIn('reuse_existing', response.context['form'].errors)
        response = self.client.post(url, {'action': 'reject'})
        self.assertIn('review_note', response.context['form'].errors)
        self.assertEqual(self.contract.contract_tenants.count(), 1)

    def test_create_and_review_require_csrf_and_reviewer_does_not_need_admin_role(self):
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.user)
        self.assertEqual(guarded.post(reverse('cooccupant_create'), self.data()).status_code, 403)
        proposal = self.proposal()
        guarded.force_login(self.owner)
        self.assertEqual(guarded.post(reverse('cooccupant_review', args=[proposal.pk]), {'action': 'approve'}).status_code, 403)
        self.owner.is_staff = False
        self.owner.save(update_fields=['is_staff'])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('cooccupant_review', args=[proposal.pk]), {
            'action': 'approve', 'confirm_information': 'on'}).status_code, 302)

    def test_notifications_use_correct_private_destinations_and_read_states(self):
        proposal = self.proposal()
        self.client.force_login(self.owner)
        panel = self.client.get(reverse('owner_notifications_panel'))
        item = panel.context['notifications'][0]
        self.assertEqual(item['notification_kind'], 'owner_cooccupant')
        result = self.client.post(reverse('notification_mark_read'), {'token': item['read_token']}).json()
        self.assertEqual(result['url'], reverse('cooccupant_review', args=[proposal.pk]))
        self.assertEqual(result['unread_count'], 0)
        review_request(proposal, self.owner, action='reject', review_note='Bổ sung thông tin liên hệ')
        self.client.force_login(self.user)
        panel = self.client.get(reverse('my_notifications_panel'))
        item = panel.context['notifications'][0]
        self.assertEqual(item['notification_kind'], 'cooccupant_decision')
        self.assertContains(panel, 'Bổ sung thông tin liên hệ')
        result = self.client.post(reverse('notification_mark_read'), {'token': item['read_token']}).json()
        self.assertEqual(result['url'], reverse('my_cooccupant_detail', args=[proposal.pk]))
        self.assertEqual(result['unread_count'], 0)
        self.assertEqual(NotificationRead.objects.count(), 2)
