from django.db.models import Prefetch

from rooms.models import Contract, ContractTenant
from .models import IdentityDocument, Tenant
from .text import normalize


TENANT_STATE_UI = {
    'dang_thue': ('Đang thuê', 'mint'), 'da_tra': ('Đã trả phòng', 'gray'), 'chua_thue': ('Chưa thuê', 'sky'),
}


def state_of(contract_tenants):
    current = next((ct for ct in contract_tenants if ct.contract.status == Contract.Status.HIEU_LUC), None)
    if current:
        return 'dang_thue', current
    return ('da_tra', contract_tenants[0]) if contract_tenants else ('chua_thue', None)


def tenant_rows(ids=None):
    cts = ContractTenant.objects.select_related('contract__room').order_by('-contract__start_date', '-contract__id')
    tenants = Tenant.objects.select_related('user').prefetch_related(
        Prefetch('contract_tenants', queryset=cts, to_attr='cts'),
        Prefetch('identity_documents', queryset=IdentityDocument.objects.order_by('-created_at', '-pk'),
                 to_attr='documents_for_selection')).order_by('full_name', 'pk')
    if ids is not None:
        tenants = tenants.filter(pk__in=ids)
    rows = []
    for tenant in tenants:
        state, ct = state_of(tenant.cts)
        label, tone = TENANT_STATE_UI[state]
        document = tenant.documents_for_selection[0] if tenant.documents_for_selection else None
        rows.append({'tenant': tenant, 'state': state, 'label': label, 'tone': tone,
            'contract': ct.contract if ct else None, 'link': ct, 'room': ct.contract.room if ct else None,
            'document': document, 'identity_missing': tenant.identity_missing_labels,
            'identity_mismatch': bool(document and (document.entered_id_number != tenant.id_card_number or document.number_corrected))})
    return rows


def filtered_rows(rows, status='', q=''):
    if status in TENANT_STATE_UI:
        rows = [row for row in rows if row['state'] == status]
    if q:
        query = normalize(q.strip())
        digits = ''.join(char for char in q if char.isdigit())
        rows = [row for row in rows if query in normalize(row['tenant'].full_name) or
                (digits and (digits in ''.join(char for char in row['tenant'].phone if char.isdigit()) or
                             digits in row['tenant'].id_card_number))]
    return rows
