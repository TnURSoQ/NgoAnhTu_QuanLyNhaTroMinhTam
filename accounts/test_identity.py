import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import override_settings
from django.urls import reverse

from accounts.forms import TenantForm, TenantProfileForm
from accounts.models import IdentityDocument, Tenant, User
from rooms.cooccupants import review_request
from rooms.models import CoOccupantRequest
from support.tests import SupportBase


def photo(name='front.png', fmt='PNG'):
    content = BytesIO()
    Image.new('RGB', (300, 180), 'white').save(content, fmt)
    return SimpleUploadedFile(name, content.getvalue(), content_type='image/png')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IdentityCaptureTests(SupportBase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.storage = FileSystemStorage(location=self.directory.name)
        for side in ('front', 'back'):
            field = IdentityDocument._meta.get_field(side)
            original = field.storage
            field.storage = self.storage
            self.addCleanup(setattr, field, 'storage', original)
        self.room.max_occupants = 3
        self.room.save()
        self.contract.contract_tenants.update(is_representative=True)
        self.client.force_login(self.user)

    def data(self, **changes):
        return {'full_name': 'Nguyễn Văn Thử', 'phone': '0901234567', 'email': 'thu@example.com',
                'id_card_number': '099999999991', 'date_of_birth': '2001-05-12',
                'hometown': 'Đà Nẵng', 'occupation': 'Sinh viên', **changes}

    def recognized(self, **changes):
        return json.dumps({'id_card_number': '099999999991', 'full_name': 'NGUYỄN VĂN THỬ', **changes})

    def upload_profile(self, **changes):
        return self.client.post(reverse('my_profile'), self.data(identity_front=photo(),
            identity_recognition=self.recognized(), **changes))

    def submit_cooccupant(self, **changes):
        response = self.client.post(reverse('cooccupant_create'), self.data(
            identity_front=photo(), identity_recognition=self.recognized(), confirm_information='on', **changes))
        self.assertEqual(response.status_code, 302)
        return CoOccupantRequest.objects.latest('pk')

    def image_url(self, document, side='front'):
        return reverse('identity_image', args=[document.reference, side])

    def test_profile_upload_preserves_entered_fields_and_saves_two_private_sides(self):
        response = self.upload_profile(identity_back=photo('back.png'))
        self.assertEqual(response.status_code, 302)
        document = IdentityDocument.objects.get()
        self.assertEqual(document.tenant, self.tenant)
        self.assertEqual(document.uploaded_by, self.user)
        self.assertEqual(document.recognized_fields['full_name'], 'NGUYỄN VĂN THỬ')
        self.assertFalse(document.number_corrected)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.full_name, 'Nguyễn Văn Thử')
        self.assertEqual(self.tenant.phone, '0901234567')
        self.assertTrue(Path(document.front.path).is_file())
        self.assertTrue(Path(document.back.path).is_file())
        self.assertNotEqual(document.front.name, document.back.name)
        self.assertTrue(document.front.name.startswith(f'identity/{document.reference}/'))
        self.assertNotContains(self.client.get(reverse('my_profile')), '/media/identity/')

    def test_image_access_is_scoped_and_not_publicly_cacheable(self):
        self.upload_profile()
        document = IdentityDocument.objects.get()
        for account in (self.user, self.owner):
            self.client.force_login(account)
            response = self.client.get(self.image_url(document))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            response.close()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.image_url(document)).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.image_url(document)).status_code, 302)

    def test_missing_side_or_file_is_404(self):
        self.upload_profile()
        document = IdentityDocument.objects.get()
        for side in ('back', 'unknown'):
            self.assertEqual(self.client.get(self.image_url(document, side)).status_code, 404)
        self.storage.delete(document.front.name)
        self.assertEqual(self.client.get(self.image_url(document)).status_code, 404)

    def test_mismatch_requires_explicit_correction_and_records_it(self):
        response = self.upload_profile(id_card_number='099999999992')
        self.assertIn('confirm_identity_correction', response.context['form'].errors)
        self.assertFalse(IdentityDocument.objects.exists())
        self.assertEqual(self.upload_profile(id_card_number='099999999992',
            confirm_identity_correction='on').status_code, 302)
        document = IdentityDocument.objects.get()
        self.assertTrue(document.number_corrected)
        self.assertEqual(document.entered_id_number, '099999999992')

    def test_owner_cannot_attach_a_different_card_to_locked_id(self):
        self.tenant.id_card_number = '099999999992'
        self.tenant.save()
        form = TenantForm(data=self.data(confirm_identity_correction='on',
            identity_recognition=self.recognized()), files={'identity_front': photo()}, instance=self.tenant)
        self.assertFalse(form.is_valid())
        self.assertIn('identity_front', form.errors)

    def test_different_front_and_back_numbers_are_rejected(self):
        response = self.client.post(reverse('my_profile'), self.data(identity_front=photo(),
            identity_back=photo('back.png'), identity_recognition=self.recognized(back_id_card_number='099999999992'),
            confirm_identity_correction='on'))
        self.assertIn('identity_back', response.context['form'].errors)
        self.assertFalse(IdentityDocument.objects.exists())

    def test_invalid_files_and_back_without_front_are_rejected(self):
        for files, error_field in [
            ({'identity_front': SimpleUploadedFile('fake.png', b'not an image')}, 'identity_front'),
            ({'identity_front': photo('front.gif', 'GIF')}, 'identity_front'),
            ({'identity_front': photo('front.txt')}, 'identity_front'),
            ({'identity_back': photo('back.png')}, 'identity_front'),
            ({'identity_front': photo(), 'identity_front_camera': photo('camera.png')}, 'identity_front'),
        ]:
            form = TenantProfileForm(data=self.data(), files=files, instance=self.tenant)
            self.assertFalse(form.is_valid())
            self.assertIn(error_field, form.errors)

    def test_camera_input_is_saved_and_scanner_is_optional(self):
        response = self.client.post(reverse('my_profile'), self.data(identity_front_camera=photo('camera.png')))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IdentityDocument.objects.get().recognized_fields, {})

    def test_oversized_upload_is_rejected(self):
        upload = photo()
        upload.size = 5 * 1024 * 1024 + 1
        form = TenantProfileForm(data=self.data(), files={'identity_front': upload}, instance=self.tenant)
        self.assertFalse(form.is_valid())
        self.assertIn('identity_front', form.errors)

    def test_untrusted_recognition_cannot_overwrite_profile_or_choose_document(self):
        response = self.client.post(reverse('my_profile'), self.data(identity_front=photo(),
            identity_document=999, tenant=self.other_tenant.pk, uploaded_by=self.owner.pk,
            identity_recognition=self.recognized(role='owner', tenant=self.other_tenant.pk)))
        self.assertEqual(response.status_code, 302)
        document = IdentityDocument.objects.get()
        self.assertNotIn('role', document.recognized_fields)
        self.assertNotIn('tenant', document.recognized_fields)
        self.assertEqual(document.tenant, self.tenant)
        self.assertEqual(document.uploaded_by, self.user)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.full_name, 'Nguyễn Văn Thử')

    def test_bad_recognition_data_shows_validation_error(self):
        for raw in ('[]', '{invalid', '{"full_name": 123}'):
            form = TenantProfileForm(data=self.data(identity_recognition=raw),
                files={'identity_front': photo()}, instance=self.tenant)
            self.assertFalse(form.is_valid())
            self.assertIn('identity_recognition', form.errors)

    def test_pending_photos_only_become_tenant_documents_on_approval(self):
        users, tenants = User.objects.count(), Tenant.objects.count()
        proposal = self.submit_cooccupant()
        document = proposal.identity_document
        self.assertIsNone(document.tenant_id)
        self.assertEqual(Tenant.objects.count(), tenants)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.image_url(document)).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('cooccupant_review', args=[proposal.pk])), self.image_url(document))
        approved = review_request(proposal, self.owner, action='approve', confirm_information=True)
        document.refresh_from_db()
        self.assertEqual(document.tenant, approved.approved_tenant)
        self.assertIsNone(approved.approved_tenant.user_id)
        self.assertEqual(User.objects.count(), users)
        self.assertContains(self.client.get(reverse('tenant_detail', args=[approved.approved_tenant_id])), self.image_url(document))

    def test_resubmission_reuses_private_document_without_reupload(self):
        first = self.submit_cooccupant()
        review_request(first, self.owner, action='reject', review_note='Kiểm tra điện thoại')
        response = self.client.post(reverse('cooccupant_resubmit', args=[first.pk]), self.data(confirm_information='on'))
        self.assertEqual(response.status_code, 302)
        second = CoOccupantRequest.objects.exclude(pk=first.pk).get()
        self.assertEqual(second.identity_document_id, first.identity_document_id)
        self.assertEqual(IdentityDocument.objects.count(), 1)
        review_request(second, self.owner, action='reject', review_note='Kiểm tra số giấy tờ')
        response = self.client.post(reverse('cooccupant_resubmit', args=[second.pk]), self.data(
            id_card_number='099999999992', confirm_information='on', confirm_identity_correction='on'))
        self.assertEqual(response.status_code, 302)
        third = CoOccupantRequest.objects.latest('pk')
        self.assertEqual(third.identity_document_id, first.identity_document_id)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('cooccupant_review', args=[third.pk])),
            'Số giấy tờ hiện tại 099999999992 khác số đã lưu kèm ảnh 099999999991')

    def test_save_without_new_photo_keeps_document_and_compares_changed_number(self):
        self.upload_profile()
        self.assertEqual(self.client.post(reverse('my_profile'), self.data()).status_code, 302)
        response = self.client.post(reverse('my_profile'), self.data(id_card_number='099999999992'))
        self.assertIn('confirm_identity_correction', response.context['form'].errors)
        self.assertEqual(IdentityDocument.objects.count(), 1)

    def test_database_failure_rolls_back_profile_and_removes_written_files(self):
        original = IdentityDocument.save
        def fail_after_file_write(document, *args, **kwargs):
            original(document, *args, **kwargs)
            raise DatabaseError('simulated database failure')
        with patch.object(IdentityDocument, 'save', fail_after_file_write):
            response = self.upload_profile()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertFalse(IdentityDocument.objects.exists())
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.id_card_number, '001')
        self.assertFalse(any(path.is_file() for path in Path(self.directory.name).rglob('*')))

    def test_storage_failure_rolls_back_staged_proposal(self):
        with patch.object(self.storage, 'save', side_effect=OSError('disk full')):
            response = self.client.post(reverse('cooccupant_create'), self.data(
                identity_front=photo(), confirm_information='on'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CoOccupantRequest.objects.exists())
        self.assertFalse(IdentityDocument.objects.exists())

    def test_delete_cleans_up_private_files_after_commit(self):
        self.upload_profile()
        document = IdentityDocument.objects.get()
        name = document.front.name
        with self.captureOnCommitCallbacks(execute=True):
            document.delete()
            self.assertTrue(self.storage.exists(name))
        self.assertFalse(self.storage.exists(name))

    def test_owner_can_add_document_to_new_tenant_without_creating_login(self):
        self.client.force_login(self.owner)
        count = User.objects.count()
        response = self.client.post(reverse('tenant_create'), self.data(identity_front=photo()))
        self.assertEqual(response.status_code, 302)
        document = IdentityDocument.objects.get()
        self.assertEqual(document.uploaded_by, self.owner)
        self.assertIsNone(document.tenant.user_id)
        self.assertEqual(User.objects.count(), count)
