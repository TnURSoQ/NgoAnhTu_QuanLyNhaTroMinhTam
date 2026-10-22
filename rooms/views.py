from django.shortcuts import render

from accounts.decorators import tenant_required
from .models import Contract


@tenant_required
def my_contracts(request):
    contracts = (
        Contract.objects.filter(contract_tenants__tenant=request.tenant)
        .select_related('room')
        .prefetch_related('contract_tenants__tenant')
        .order_by('-start_date')
    )
    return render(request, 'rooms/contract_list.html', {'contracts': contracts})