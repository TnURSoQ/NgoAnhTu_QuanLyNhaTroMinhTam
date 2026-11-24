from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.storage import FileSystemStorage
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from accounts.forms import TenantForm, TenantProfileForm
from accounts.models import IdentityDocument, Tenant, User
from accounts.test_identity import photo
from rooms.cooccupants import review_request
from rooms.models import CoOccupantRequest, Contract, ContractTenant, Room


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], SITE_ADDRESS='Địa chỉ nhà trọ thử')
class IdentityRecordTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', role='owner')
        self.user = User.objects.create_user('tenant', role='tenant')
        self.person = Tenant.objects.create(user=self.user, full_name='Người ở thử', id_card_number='012345678901', phone='0901234567')
        self.other = Tenant.objects.create(full_name='Người ở cùng thử', id_card_number='012345678902', phone='0902222333')
        self.room = Room.objects.create(room_number='201', price=2500000, max_occupants=3)
        self.contract = Contract.objects.create(room=self.room, start_date=timezone.localdate(),
            end_date=timezone.localdate()+timedelta(days=365))
        ContractTenant.objects.create(contract=self.contract, tenant=self.person, is_representative=True)
        ContractTenant.objects.create(contract=self.contract, tenant=self.other, is_representative=False)
        self.client.force_login(self.owner)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = FileSystemStorage(location=self.directory.name)
        for side in ('front', 'back'):
            field = IdentityDocument._meta.get_field(side)
            original = field.storage
            field.storage = self.storage
            self.addCleanup(setattr, field, 'storage', original)
        self.url = reverse('identity_export')

    def data(self, **extra):
        return {'full_name': 'Người ở thử', 'id_card_number': '012345678901', 'phone': '0901234567',
            'date_of_birth': '2000-05-12', 'document_type': 'cccd', 'gender': 'female', 'nationality': 'Việt Nam',
            'hometown': 'Quê quán thử', 'place_of_birth': 'Nơi sinh thử', 'birth_registration_place': 'Nơi đăng ký thử',
            'permanent_address': 'Địa chỉ thường trú thử',
            'identity_issued_on': '2024-08-01', 'identity_expires_on': '2040-05-12',
            'identity_issued_by': 'Cơ quan cấp thử', **extra}

    def document(self, person=None, back=True, **extra):
        person = person or self.person
        return IdentityDocument.objects.create(tenant=person, uploaded_by=self.owner, front=photo(),
            back=photo('back.png') if back else '', entered_id_number=person.id_card_number, **extra)

    def export(self, action='images', ids=None, **extra):
        return self.client.post(self.url, {'action': action, 'ids': ids if ids is not None else [self.person.pk], **extra})

    def workbook(self, response):
        self.assertEqual(response.status_code, 200)
        return load_workbook(BytesIO(response.content), data_only=False)

    def test_owner_can_update_all_identity_fields_without_changing_login(self):
        response = self.client.post(reverse('tenant_update', args=[self.person.pk]), self.data())
        self.assertEqual(response.status_code, 302)
        self.person.refresh_from_db()
        self.assertEqual(self.person.permanent_address, 'Địa chỉ thường trú thử')
        self.assertEqual(self.person.hometown, 'Quê quán thử')
        self.assertEqual(self.person.birth_registration_place, 'Nơi đăng ký thử')
        self.assertEqual(self.person.identity_issued_on, date(2024, 8, 1))
        self.assertFalse(self.person.identity_missing_labels)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'tenant')

    def test_tenant_can_update_own_extended_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('my_profile'), self.data())
        self.assertEqual(response.status_code, 302)
        self.person.refresh_from_db()
        self.assertEqual(self.person.gender, 'female')
        self.assertEqual(self.person.nationality, 'Việt Nam')
        self.assertEqual(self.person.place_of_birth, 'Nơi sinh thử')

    def test_dates_are_validated_and_no_expiry_is_explicit(self):
        for changes, field in [
            ({'identity_issued_on': (timezone.localdate()+timedelta(days=1)).isoformat()}, 'identity_issued_on'),
            ({'identity_issued_on': '1990-01-01'}, 'identity_issued_on'),
            ({'identity_expires_on': '2020-01-01'}, 'identity_expires_on'),
            ({'identity_no_expiry': 'on'}, 'identity_expires_on'),
            ({'gender': 'invalid'}, 'gender'),
        ]:
            form = TenantProfileForm(self.data(**changes), instance=self.person)
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)
        form = TenantProfileForm(self.data(identity_no_expiry='on', identity_expires_on=''), instance=self.person)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().identity_no_expiry)

    def test_blank_new_fields_remain_unknown_and_legacy_records_can_be_edited(self):
        form = TenantProfileForm({'full_name': self.person.full_name, 'phone': self.person.phone,
            'id_card_number': self.person.id_card_number}, instance=self.person)
        self.assertTrue(form.is_valid(), form.errors)
        person = form.save()
        self.assertEqual(person.nationality, '')
        self.assertEqual(person.permanent_address, '')
        self.assertIsNone(person.identity_issued_on)
        self.assertTrue(person.identity_missing_labels)

    def test_new_card_requires_twelve_digits_but_cmnd_is_supported(self):
        form = TenantForm(self.data(id_card_number='123456789'), instance=self.other)
        self.assertFalse(form.is_valid())
        self.assertIn('id_card_number', form.errors)
        form = TenantForm(self.data(id_card_number='123456789', document_type='cmnd'), instance=self.other)
        self.assertTrue(form.is_valid(), form.errors)

    def test_expired_document_can_be_recorded_and_is_flagged(self):
        form = TenantProfileForm(self.data(identity_expires_on='2025-05-12'), instance=self.person)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.save().identity_expired)

    def test_cooccupant_submission_and_approval_preserve_extended_information(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('cooccupant_create'), self.data(id_card_number='099999999991',
            full_name='Người được thêm', confirm_information='on'))
        self.assertEqual(response.status_code, 302)
        proposal = CoOccupantRequest.objects.get()
        approved = review_request(proposal, self.owner, action='approve', confirm_information=True).approved_tenant
        self.assertIsNone(approved.user_id)
        self.assertEqual(approved.permanent_address, 'Địa chỉ thường trú thử')
        self.assertEqual(approved.identity_issued_on, date(2024, 8, 1))
        self.assertEqual(approved.gender, 'female')

    def test_table_shows_id_and_search_finds_leading_zero_id(self):
        response = self.client.get(reverse('tenant_list'), {'q': '012345678902'})
        self.assertContains(response, 'Số CCCD/CMND')
        self.assertEqual([r['tenant'].pk for r in response.context['rows']], [self.other.pk])
        self.assertContains(response, '012345678902')

    def test_print_uses_two_private_image_urls_for_selected_person(self):
        doc = self.document()
        response = self.export()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('identity_image', args=[doc.reference, 'front']))
        self.assertContains(response, reverse('identity_image', args=[doc.reference, 'back']))
        self.assertNotContains(response, '/media/identity/')
        self.assertNotContains(response, self.other.full_name)
        self.assertIn('no-store', response['Cache-Control'])

    def test_multiple_selection_is_grouped_by_room_and_ids_are_deduplicated(self):
        self.document()
        self.document(self.other)
        response = self.export(ids=[self.person.pk, self.other.pk, self.person.pk])
        groups = list(response.context['groups'])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]['people']), 2)
        self.assertEqual(response.context['selected_count'], 2)
        self.assertContains(response, 'P.201')

    def test_former_tenant_group_is_not_labelled_as_current_resident(self):
        self.contract.status = Contract.Status.KET_THUC
        self.contract.checkout_date = timezone.localdate()
        self.contract.save()
        response = self.export(ids=[self.person.pk, self.other.pk])
        self.assertContains(response, 'PHÒNG CŨ')
        self.assertContains(response, 'ĐÃ TRẢ PHÒNG')

    def test_missing_or_deleted_files_produce_clear_placeholders(self):
        doc = self.document(back=False)
        self.storage.delete(doc.front.name)
        response = self.export()
        self.assertContains(response, 'Chưa có ảnh mặt trước truy cập được')
        self.assertContains(response, 'Chưa có ảnh mặt sau truy cập được')

    def test_latest_image_is_selected_and_id_discrepancy_is_highlighted(self):
        old = self.document()
        latest = IdentityDocument.objects.create(
            tenant=self.person, uploaded_by=self.owner, front=photo(), entered_id_number='099999999999')
        response = self.export()
        self.assertContains(response, reverse('identity_image', args=[latest.reference, 'front']))
        self.assertNotContains(response, reverse('identity_image', args=[old.reference, 'front']))
        self.assertContains(response, 'cần được đối chiếu lại')

    def test_excel_is_real_xlsx_and_preserves_id_phone_dates_and_addresses(self):
        self.client.post(reverse('tenant_update', args=[self.person.pk]), self.data())
        self.document()
        response = self.export('excel')
        book = self.workbook(response)
        self.assertEqual(book.sheetnames, ['Danh sách người ở', 'Chi tiết căn cước'])
        roster, details = book.worksheets
        headers = [c.value for c in roster[1]]
        values = {header: roster.cell(2, i+1) for i, header in enumerate(headers)}
        self.assertEqual(values['Số CCCD/CMND'].value, '012345678901')
        self.assertEqual(values['Số CCCD/CMND'].data_type, 's')
        self.assertEqual(values['Điện thoại'].value, '0901234567')
        self.assertEqual(values['Ngày sinh'].value.date(), date(2000, 5, 12))
        self.assertEqual(values['Ngày sinh'].number_format, 'dd/mm/yyyy')
        self.assertIn('P.201', values['Địa chỉ nhà trọ đang ở'].value)
        data = {cell.value: details.cell(2, i+1).value for i, cell in enumerate(details[1])}
        self.assertEqual(data['Địa chỉ thường trú (theo căn cước)'], 'Địa chỉ thường trú thử')
        self.assertNotIn('Nơi cư trú trên thẻ', data)
        self.assertNotIn('Đặc điểm nhận dạng', data)
        self.assertEqual(data['Quê quán'], 'Quê quán thử')
        self.assertEqual(data['Ảnh mặt trước'], 'Có')
        self.assertEqual(data['Ảnh mặt sau'], 'Có')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertTrue({'no-cache', 'no-store', 'private'}.issubset(set(response['Cache-Control'].split(', '))))

    def test_excel_includes_approved_cooccupant_without_account(self):
        book = self.workbook(self.export('excel', ids=[self.person.pk, self.other.pk]))
        rows = list(book.worksheets[0].values)
        self.assertEqual(len(rows), 3)
        self.assertTrue(any('Người ở cùng' in row for row in rows[1:]))

    def test_excel_formulas_and_invalid_xml_characters_are_not_executed(self):
        Tenant.objects.filter(pk=self.person.pk).update(full_name='=HYPERLINK("https://example.com")', permanent_address='A\x01B')
        book = self.workbook(self.export('excel'))
        name = book.worksheets[0].cell(2, 5)
        self.assertEqual(name.data_type, 's')
        self.assertTrue(name.value.startswith('='))
        details = book.worksheets[1]
        header = [c.value for c in details[1]]
        self.assertEqual(details.cell(2, header.index('Địa chỉ thường trú (theo căn cước)')+1).value, 'AB')

    def test_identity_forms_share_one_card_choice_and_one_card_address(self):
        from rooms.cooccupant_forms import CoOccupantRequestForm
        for form in (TenantForm(), TenantProfileForm(instance=self.person), CoOccupantRequestForm()):
            with self.subTest(form=type(form).__name__):
                self.assertIn('permanent_address', form.fields)
                self.assertNotIn('residence_address', form.fields)
                self.assertNotIn('identifying_features', form.fields)
                choices = dict(form.fields['document_type'].choices)
                self.assertEqual(choices['cccd'], 'CCCD / Căn cước')
                self.assertNotIn('can_cuoc', choices)
        for name, args in [('tenant_create', []), ('tenant_detail', [self.person.pk])]:
            page = self.client.get(reverse(name, args=args))
            self.assertContains(page, 'Địa chỉ thường trú (theo căn cước)')
            self.assertNotContains(page, 'Đặc điểm nhận dạng')
            self.assertNotContains(page, 'Nơi cư trú trên thẻ')

    def test_empty_invalid_or_unknown_selection_is_not_exported(self):
        for data in ({'action': 'images'}, {'action': 'images', 'ids': ['bad']},
                     {'action': 'images', 'ids': [999999]}, {'action': 'bad', 'ids': [self.person.pk]}):
            self.assertEqual(self.client.post(self.url, data).status_code, 302)

    def test_export_requires_owner_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(self.url, {'action': 'images', 'ids': [self.person.pk]}).status_code, 403)
        for account in (self.user, User.objects.create_user('staff', role='tenant', is_staff=True)):
            self.client.force_login(account)
            self.assertEqual(self.export().status_code, 302)
            self.assertEqual(self.export('excel').status_code, 302)
        self.client.logout()
        self.assertEqual(self.export().status_code, 302)

    def test_pending_cooccupant_does_not_enter_official_exports(self):
        proposal = CoOccupantRequest.objects.create(contract=self.contract, submitted_by=self.person,
            full_name='Chưa được duyệt', id_card_number='099999999991', phone='0901111222')
        self.assertNotIn(proposal.full_name, str(list(self.workbook(self.export('excel', ids=[self.person.pk, self.other.pk])).worksheets[0].values)))
