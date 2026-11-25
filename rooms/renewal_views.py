from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import owner_required, tenant_required
from accounts.permissions import is_owner
from accounts.models import User
from billing.models import UtilityRate
from billing.services import billable_services
from . import renewal_services as services
from .display import contract_status_ui
from .models import Contract, ContractDocument, MoveOutNotice, RenewalProposal
from .renewal_forms import (ContractDocumentForm, ContractTermsForm, MoveOutForm,
                            RenewalForm, ResponseForm)


def accessible_contracts(user):
    queryset = Contract.objects.select_related('room').prefetch_related('contract_tenants__tenant')
    if is_owner(user):
        return queryset
    if user.is_authenticated and user.role == 'tenant':
        return queryset.filter(contract_tenants__tenant__user=user)
    return queryset.none()


def detail_url(user, contract):
    return reverse('contract_detail' if is_owner(user) else 'my_contract_detail', args=[contract.pk])


def contract_context(contract, user):
    owner = is_owner(user)
    proposals = list(contract.renewal_proposals.select_related('created_by', 'responded_by').prefetch_related('documents'))
    representative = services.is_representative(user, contract)
    for proposal in proposals:
        proposal.can_respond = proposal.pending and (
            (owner and proposal.status == RenewalProposal.Status.OWNER) or
            (representative and proposal.status == RenewalProposal.Status.TENANT))
        proposal.can_withdraw = proposal.pending and proposal.created_by_id == user.pk
    return {
        'owner_view': owner, 'representative': representative,
        'proposals': proposals, 'pending_proposal': next((p for p in proposals if p.pending), None),
        'moveout_notices': contract.moveout_notices.select_related('submitted_by', 'responded_by'),
        'open_moveout': contract.moveout_notices.filter(status__in=services.OPEN_NOTICES).first(),
        'contract_documents': contract.documents.select_related('proposal'),
        'contract_events': contract.events.filter(audience='owner' if owner else 'tenant')[:20],
        'contract_detail_url': detail_url(user, contract),
    }


@tenant_required
@never_cache
@require_GET
def my_contract_detail(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    key, label, tone = contract_status_ui(contract, timezone.localdate())
    landlord = User.objects.filter(role='owner', is_active=True).order_by('pk').first()
    return render(request, 'rooms/contracts/tenant_detail.html', {
        **contract_context(contract, request.user), 'contract': contract,
        'status_key': key, 'label': label, 'tone': tone,
        'days_left': (contract.end_date - timezone.localdate()).days,
        'active': contract.status == Contract.Status.HIEU_LUC,
        'people': sorted(contract.contract_tenants.all(), key=lambda item: not item.is_representative),
        'utility_rate': UtilityRate.current(), 'contract_services': billable_services(contract),
        'landlord_name': (landlord.get_full_name() if landlord else '') or settings.SITE_NAME,
        'landlord_address': settings.SITE_ADDRESS,
        'landlord_phone': settings.SITE_PHONE,
        'deposit_balance': contract.deposit_balance,
    })


@login_required
@never_cache
def renewal_create(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    owner = is_owner(request.user)
    if not owner and not services.is_representative(request.user, contract):
        raise Http404
    if contract.status != Contract.Status.HIEU_LUC:
        messages.error(request, 'Hợp đồng đã bàn giao phòng, không thể gia hạn.')
        return redirect(detail_url(request.user, contract))
    # The route determines offline recording; POST cannot silently change the mode.
    offline = request.resolver_match.url_name == 'contract_renew_offline'
    if offline and not owner:
        raise Http404
    pending = contract.renewal_proposals.filter(status__in=services.PENDING).first()
    form = RenewalForm(contract, request.POST if request.method == 'POST' else None,
                       request.FILES or None, owner=owner, offline=offline)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop('confirm')
        upload = data.pop('signed_file', None)
        # An explicit immutable ID prevents a stale counter-offer replacing a newer one.
        replace_id = request.POST.get('replace_id', '')
        data['replace_id'] = int(replace_id) if replace_id.isdigit() else None
        try:
            if offline:
                services.record_offline(contract, request.user, upload, **data)
            else:
                services.propose(contract, request.user, **data)
        except (ValidationError, OSError, DatabaseError) as error:
            form.add_error(None, error if isinstance(error, ValidationError) else 'Chưa lưu được tài liệu. Vui lòng thử lại.')
        else:
            messages.success(request, 'Đã ghi nhận gia hạn đã thỏa thuận và phụ lục đã ký.' if offline
                             else 'Đã gửi đề nghị gia hạn. Hợp đồng chỉ được cập nhật khi bên còn lại đồng ý.')
            return redirect(detail_url(request.user, contract))
    return render(request, 'rooms/contracts/renewal_form.html', {
        'contract': contract, 'form': form, 'owner_view': owner, 'offline': offline,
        'pending_proposal': pending, 'contract_detail_url': detail_url(request.user, contract),
        'next_rent': contract.rent_on(contract.end_date), 'next_deposit': contract.deposit_on(contract.end_date),
    })


@login_required
@require_POST
def renewal_respond(request, pk):
    proposal = get_object_or_404(RenewalProposal.objects.select_related('contract__room'),
        pk=pk, contract__in=accessible_contracts(request.user))
    form = ResponseForm(request.POST)
    action = request.POST.get('action')
    if form.is_valid():
        if action == 'accept' and not form.cleaned_data['confirm']:
            messages.error(request, 'Hãy xác nhận đã đọc và đồng ý đề nghị trước khi chấp thuận.')
        else:
            try:
                services.respond(proposal, request.user, action, form.cleaned_data['note'])
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
            else:
                messages.success(request, 'Đã cập nhật phản hồi đề nghị gia hạn.')
    else:
        messages.error(request, 'Phản hồi không hợp lệ; tối đa 1.000 ký tự.')
    return redirect(detail_url(request.user, proposal.contract))


@tenant_required
def moveout_create(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    if not services.is_representative(request.user, contract):
        raise Http404
    form = MoveOutForm(request.POST if request.method == 'POST' else None,
                       initial={'planned_date': max(contract.end_date, timezone.localdate())})
    if request.method == 'POST' and form.is_valid():
        try:
            services.notify_moveout(contract, request.user, form.cleaned_data['planned_date'], form.cleaned_data['reason'])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Đã gửi lịch dự kiến trả phòng cho chủ trọ.')
            return redirect(detail_url(request.user, contract))
    return render(request, 'rooms/contracts/intent_form.html', {'contract': contract, 'form': form,
        'title': 'Thông báo dự kiến trả phòng', 'submit_label': 'Gửi lịch dự kiến',
        'contract_detail_url': detail_url(request.user, contract),
        'notice': 'Chủ trọ sẽ trao đổi lịch bàn giao, chốt điện nước, công nợ và cọc. Lịch dự kiến không tự kết thúc hợp đồng.'})


@login_required
@require_POST
def moveout_respond(request, pk):
    notice = get_object_or_404(MoveOutNotice.objects.select_related('contract__room'),
        pk=pk, contract__in=accessible_contracts(request.user))
    try:
        services.respond_moveout(notice, request.user, request.POST.get('action'), request.POST.get('note', ''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, 'Đã cập nhật lịch dự kiến trả phòng. Chưa ghi nhận bàn giao thực tế.')
    return redirect(detail_url(request.user, notice.contract))


@owner_required
def contract_document_upload(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    form = ContractDocumentForm(contract, request.POST if request.method == 'POST' else None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        document = None
        try:
            with transaction.atomic():
                document = services.save_document(contract, request.user, upload=form.cleaned_data['file'],
                    title=form.cleaned_data['title'], kind=form.cleaned_data['kind'], proposal=form.cleaned_data['proposal'])
                services.event(contract, 'tenant', 'Đã bổ sung tài liệu hợp đồng', document.title)
        except (OSError, ValidationError, DatabaseError):
            if document:
                document.file.delete(save=False)
            form.add_error(None, 'Chưa lưu được tài liệu. Vui lòng thử lại.')
        else:
            messages.success(request, 'Đã lưu tài liệu đã ký.')
            return redirect('contract_detail', pk=pk)
    return render(request, 'rooms/contracts/intent_form.html', {'contract': contract, 'form': form,
        'title': 'Bổ sung tài liệu đã ký', 'submit_label': 'Lưu tài liệu',
        'contract_detail_url': detail_url(request.user, contract)})


@login_required
@never_cache
@require_GET
def contract_document_download(request, pk):
    document = get_object_or_404(ContractDocument, pk=pk, contract__in=accessible_contracts(request.user))
    ext = Path(document.file.name).suffix.lower()
    try:
        response = FileResponse(document.file.open('rb'), as_attachment=True,
            filename=f'{document.contract.display_code}-{document.pk}{ext}')
    except OSError:
        raise Http404
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@owner_required
def contract_terms(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    form = ContractTermsForm(request.POST if request.method == 'POST' else None, instance=contract)
    if request.method == 'POST' and form.is_valid():
        try:
            services.record_terms(contract, request.user, form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Đã lưu điều khoản để đối chiếu với tài liệu đã ký.')
            return redirect('contract_detail', pk=pk)
    return render(request, 'rooms/contracts/intent_form.html', {'contract': contract, 'form': form,
        'title': 'Ghi nhận điều khoản đã thỏa thuận', 'submit_label': 'Lưu điều khoản',
        'notice': 'Nhập theo tài liệu hai bên đã ký. Nội dung chưa có sẽ hiển thị là chưa ghi nhận; hệ thống không tự đặt điều khoản.',
        'contract_detail_url': detail_url(request.user, contract)})


@tenant_required
@never_cache
@require_GET
def my_contract_print(request, pk):
    contract = get_object_or_404(accessible_contracts(request.user), pk=pk)
    return render(request, 'print/contract.html', {'contract': contract, 'utility_rate': UtilityRate.current(),
        'people': contract.contract_tenants.all(), 'document_title': f'Thông tin hợp đồng {contract.display_code}'})


@login_required
@never_cache
@require_GET
def renewal_print(request, pk):
    proposal = get_object_or_404(RenewalProposal.objects.select_related('contract__room', 'created_by', 'responded_by'),
        pk=pk, contract__in=accessible_contracts(request.user))
    return render(request, 'print/renewal.html', {'proposal': proposal, 'contract': proposal.contract,
        'people': proposal.contract.contract_tenants.select_related('tenant'),
        'document_title': f'Thông tin gia hạn {proposal.display_code}'})
