from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import IdentityDocument
from .permissions import is_owner


@login_required
@require_GET
def identity_image(request, reference, side):
    documents = IdentityDocument.objects.all()
    if not is_owner(request.user):
        if request.user.role != 'tenant':
            raise Http404
        documents = documents.filter(Q(uploaded_by=request.user) | Q(tenant__user=request.user))
    document = get_object_or_404(documents, reference=reference)
    if side not in ('front', 'back'):
        raise Http404
    field = getattr(document, side)
    if not field:
        raise Http404
    try:
        response = FileResponse(field.open('rb'), content_type={'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.webp': 'image/webp'}.get(Path(field.name).suffix.lower(), 'application/octet-stream'))
    except OSError:
        raise Http404
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
