from django.shortcuts import render

from accounts.decorators import tenant_required
from .models import Contract
from django.utils import timezone
from .display import contract_status_ui


@tenant_required
def my_contracts(request):
    contracts = (
        Contract.objects.filter(contract_tenants__tenant=request.tenant)
        .select_related('room')
        .prefetch_related('contract_tenants__tenant')
        .order_by('-start_date')
    )
    rows = []
    for contract in contracts:
        key, label, tone = contract_status_ui(contract, timezone.localdate())
        rows.append({'contract': contract, 'key': key, 'label': label, 'tone': tone,
                     'days_left': (contract.end_date - timezone.localdate()).days})
    return render(request, 'rooms/contract_list.html', {'rows': rows})
