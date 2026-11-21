from .models import IdentityDocument


class IdentityCapture:
    """Keep file writes tied to the caller's database transaction."""
    def __init__(self):
        self.written = []

    def __enter__(self):
        return self

    def save(self, form, user, tenant=None):
        data = form.cleaned_data
        if not data.get('_identity_front'):
            return form.existing_identity_document
        recognized = data.get('_identity_recognized', {})
        number = data.get('id_card_number', '')
        document = IdentityDocument(uploaded_by=user, tenant=tenant, front=data['_identity_front'],
            back=data.get('_identity_back') or '', entered_id_number=number, recognized_fields=recognized,
            number_corrected=bool(recognized.get('id_card_number') and recognized['id_card_number'] != number))
        try:
            document.save()
        finally:
            for field in (document.front, document.back):
                if field and field._committed:
                    self.written.append((field.storage, field.name))
        return document

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            for storage, name in self.written:
                storage.delete(name)
        return False
