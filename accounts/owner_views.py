from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, UpdateView

from billing.models import Invoice, Payment
from rooms.models import Contract, ContractTenant
from .decorators import owner_required
from .forms import TenantForm
from .mixins import OwnerRequiredMixin
from .models import Tenant
from .text import normalize

# trạng thái hiển thị: (nhãn, màu)
TENANT_STATE_UI = {
    'dang_thue': ('Đang thuê', 'mint'),
    'da_tra': ('Đã trả phòng', 'gray'),
    'chua_thue': ('Chưa thuê', 'sky'),
}


def _state_of(contract_tenants):
    """contract_tenants đã sắp xếp mới nhất trước. Trả về (trạng thái, liên kết hợp đồng hiển thị)."""
    current = next((ct for ct in contract_tenants if ct.contract.status == Contract.Status.HIEU_LUC), None)
    if current:
        return 'dang_thue', current
    if contract_tenants:
        return 'da_tra', contract_tenants[0]
    return 'chua_thue', None


@owner_required
def tenant_list(request):
    cts = ContractTenant.objects.select_related('contract__room').order_by(
        '-contract__start_date', '-contract__id')
    tenants = Tenant.objects.select_related('user').prefetch_related(
        Prefetch('contract_tenants', queryset=cts, to_attr='cts')).order_by('full_name')

    rows = []
    for t in tenants:
        state, ct = _state_of(t.cts)
        label, tone = TENANT_STATE_UI[state]
        rows.append({
            'tenant': t, 'state': state, 'label': label, 'tone': tone,
            'contract': ct.contract if ct else None,
            'room': ct.contract.room if ct else None,
        })

    total = len(rows)
    counts = {k: sum(1 for r in rows if r['state'] == k) for k in TENANT_STATE_UI}
    pct = lambda n: round(n * 100 / total, 1) if total else 0

    status = request.GET.get('status', '')
    if status not in TENANT_STATE_UI:
        status = ''
    q = request.GET.get('q', '').strip()
    shown = rows
    if status:
        shown = [r for r in shown if r['state'] == status]
    if q:
        nq = normalize(q)
        digits = ''.join(c for c in q if c.isdigit())
        shown = [
            r for r in shown
            if nq in normalize(r['tenant'].full_name)
            or (digits and digits in ''.join(c for c in r['tenant'].phone if c.isdigit()))
        ]

    return render(request, 'accounts/tenant_list.html', {
        'rows': shown, 'total': total, 'counts': counts,
        'pct_dang': pct(counts['dang_thue']), 'pct_tra': pct(counts['da_tra']),
        'status': status, 'q': q, 'state_ui': TENANT_STATE_UI,
    })


@owner_required
def tenant_detail(request, pk):
    tenant = get_object_or_404(Tenant.objects.select_related('user'), pk=pk)
    cts = list(
        ContractTenant.objects.filter(tenant=tenant).select_related('contract__room')
        .order_by('-contract__start_date', '-contract__id')
    )
    state, current = _state_of(cts)
    label, tone = TENANT_STATE_UI[state]
    payments = (
        Payment.objects.filter(invoice__contract__contract_tenants__tenant=tenant)
        .select_related('invoice__contract__room').order_by('-paid_date', '-id')
    )
    invoices = (
        Invoice.objects.filter(contract__contract_tenants__tenant=tenant).prefetch_related('payments')
    )
    debt = 0
    unpaid_count = 0
    for inv in invoices:
        if inv.status == Invoice.Status.DA_THANH_TOAN:
            continue
        remaining = inv.total_amount - sum((p.amount for p in inv.payments.all()), 0)
        if remaining > 0:
            debt += remaining
            unpaid_count += 1
    return render(request, 'accounts/tenant_detail.html', {
        'tenant': tenant, 'state': state, 'label': label, 'tone': tone,
        'current': current, 'history': cts, 'payments': payments,
        'debt': debt, 'unpaid_count': unpaid_count,
    })


class TenantFormMixin(OwnerRequiredMixin, SuccessMessageMixin):
    model = Tenant
    form_class = TenantForm
    template_name = '_crud/form.html'
    success_message = 'Đã lưu hồ sơ %(full_name)s.'

    def get_success_url(self):
        return reverse('tenant_detail', args=[self.object.pk])


class TenantCreateView(TenantFormMixin, CreateView):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_title='Thêm người thuê',
                   subtitle='Tài khoản đăng nhập sẽ tự tạo khi người này được chọn làm người đại diện hợp đồng.',
                   back_url=reverse('tenant_list'), submit_label='Lưu người thuê')
        return ctx


class TenantUpdateView(TenantFormMixin, UpdateView):
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(page_title=f'Sửa hồ sơ {self.object.full_name}',
                   subtitle='Chỉnh sửa rồi bấm Lưu thay đổi.',
                   back_url=reverse('tenant_detail', args=[self.object.pk]),
                   submit_label='Lưu thay đổi')
        return ctx


@owner_required
def tenant_delete(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    blocked = tenant.contract_tenants.exists()
    if request.method == 'POST':
        if blocked:
            messages.error(request, 'Người thuê đã có hợp đồng nên không thể xóa.')
            return redirect('tenant_detail', pk=pk)
        name = tenant.full_name
        tenant.delete()
        messages.success(request, f'Đã xóa hồ sơ {name}.')
        return redirect('tenant_list')
    return render(request, '_crud/confirm_delete.html', {
        'title': f'Xóa hồ sơ {tenant.full_name}?',
        'message': 'Thao tác này không thể hoàn tác.',
        'blocked': blocked,
        'blocked_message': 'Người này đã từng có hợp đồng nên không thể xóa để giữ lịch sử thuê và hóa đơn.',
        'back_url': reverse('tenant_detail', args=[tenant.pk]),
    })


@owner_required
@require_POST
def tenant_reset_password(request, pk):
    tenant = get_object_or_404(Tenant.objects.select_related('user'), pk=pk)
    if not tenant.user:
        messages.error(request, 'Người này chưa có tài khoản đăng nhập.')
    else:
        tenant.user.set_password(tenant.id_card_number)
        tenant.user.save()
        messages.success(request, f'Đã đặt lại mật khẩu của {tenant.full_name} về số CCCD.')
    return redirect('tenant_detail', pk=pk)


@owner_required
@require_POST
def tenant_toggle_active(request, pk):
    tenant = get_object_or_404(Tenant.objects.select_related('user'), pk=pk)
    if not tenant.user:
        messages.error(request, 'Người này chưa có tài khoản đăng nhập.')
    else:
        user = tenant.user
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        messages.success(
            request, f'Đã {"mở khóa" if user.is_active else "khóa"} tài khoản của {tenant.full_name}.')
    return redirect('tenant_detail', pk=pk)