from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db import DatabaseError

from accounts.decorators import owner_required, tenant_required
from accounts.models import Tenant
from .cooccupant_forms import CoOccupantRequestForm, CoOccupantReviewForm, PROFILE_FIELDS
from .cooccupants import cancel_request, representative_contract, review_request, submit_request
from .models import CoOccupantRequest as Request


def _requests():
    return Request.objects.select_related('contract__room', 'submitted_by', 'approved_tenant', 'reviewed_by', 'previous_request', 'identity_document')


@tenant_required
@require_GET
def my_cooccupants(request):
    contract = representative_contract(request.tenant)
    people = list(contract.contract_tenants.select_related('tenant')) if contract else []
    items = Paginator(_requests().filter(submitted_by=request.tenant), 15).get_page(request.GET.get('page'))
    return render(request, 'rooms/cooccupants/list.html', {'contract': contract, 'people': people, 'items': items,
        'can_add': bool(contract and len(people) < contract.room.max_occupants)})


@tenant_required
@require_http_methods(['GET', 'POST'])
def cooccupant_create(request, previous_pk=None):
    contract = representative_contract(request.tenant)
    if contract is None:
        messages.error(request, 'Chỉ người đại diện của hợp đồng đang hiệu lực được gửi thông tin người ở cùng.')
        return redirect('my_cooccupants')
    previous = None
    initial = {}
    if previous_pk is not None:
        previous = get_object_or_404(_requests(), pk=previous_pk, submitted_by=request.tenant, contract=contract,
                                     status__in=[Request.Status.REJECTED, Request.Status.CANCELLED])
        initial = {key: getattr(previous, key) for key in PROFILE_FIELDS}
    form = CoOccupantRequestForm(request.POST if request.method == 'POST' else None, request.FILES or None,
        initial=initial, existing_identity_document=previous.identity_document if previous else None)
    if request.method == 'POST' and form.is_valid():
        try:
            proposal = submit_request(contract, request.tenant, form.cleaned_data, previous_request=previous, identity_form=form)
        except ValidationError as error:
            form.add_error(None, error)
        except (OSError, DatabaseError):
            form.add_error(None, 'Chưa lưu được hồ sơ và ảnh giấy tờ. Vui lòng thử lại.')
        else:
            messages.success(request, 'Đã gửi hồ sơ người ở cùng. Chủ trọ sẽ kiểm tra và xác nhận.')
            return redirect('my_cooccupant_detail', pk=proposal.pk)
    return render(request, 'rooms/cooccupants/form.html', {'contract': contract, 'form': form, 'previous': previous})


@tenant_required
@require_GET
def my_cooccupant_detail(request, pk):
    proposal = get_object_or_404(_requests(), pk=pk, submitted_by=request.tenant)
    current = representative_contract(request.tenant)
    can_resubmit = bool(current and current.pk == proposal.contract_id and
                         proposal.status in (Request.Status.REJECTED, Request.Status.CANCELLED))
    return render(request, 'rooms/cooccupants/detail.html', {'proposal': proposal, 'can_resubmit': can_resubmit})


@tenant_required
@require_POST
def cooccupant_cancel(request, pk):
    proposal = get_object_or_404(_requests(), pk=pk, submitted_by=request.tenant)
    try:
        cancel_request(proposal, request.tenant)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    else:
        messages.success(request, 'Đã hủy hồ sơ chờ xác nhận.')
    return redirect('my_cooccupant_detail', pk=pk)


@owner_required
@require_GET
def cooccupant_review_list(request):
    status = request.GET.get('status', Request.Status.PENDING)
    if status not in Request.Status.values and status != '':
        status = Request.Status.PENDING
    items = _requests()
    if status:
        items = items.filter(status=status)
    items = Paginator(items, 20).get_page(request.GET.get('page'))
    return render(request, 'rooms/cooccupants/list.html', {'owner_view': True, 'items': items,
        'status': status, 'statuses': Request.Status.choices, 'hide_admin_navigation': True})


@owner_required
@require_http_methods(['GET', 'POST'])
def cooccupant_review(request, pk):
    proposal = get_object_or_404(_requests(), pk=pk)
    existing = Tenant.objects.filter(id_card_number=proposal.id_card_number).first()
    form = CoOccupantReviewForm(request.POST if request.method == 'POST' else None, existing_tenant=existing)
    if request.method == 'POST' and form.is_valid():
        try:
            review_request(proposal, request.user, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, 'Đã xử lý hồ sơ và gửi phản hồi cho người đại diện.')
            return redirect('cooccupant_review', pk=pk)
    current_count = proposal.contract.contract_tenants.count()
    return render(request, 'rooms/cooccupants/detail.html', {'proposal': proposal, 'owner_view': True,
        'form': form, 'existing_tenant': existing, 'current_count': current_count,
        'hide_admin_navigation': True})
