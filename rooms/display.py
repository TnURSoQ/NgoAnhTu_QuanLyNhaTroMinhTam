from .models import Contract, Room

# Nhãn và tông màu hiển thị của trạng thái phòng
ROOM_STATUS_UI = {
    Room.Status.DANG_THUE.value: ('Đang thuê', 'peach'),
    Room.Status.TRONG.value: ('Còn trống', 'mint'),
    Room.Status.BAO_TRI.value: ('Đang sửa', 'amber'),
}


def room_status_ui(room):
    return ROOM_STATUS_UI.get(room.status, (room.get_status_display(), 'amber'))


def representative_of(contract):
    """Người đại diện của hợp đồng (cần prefetch contract_tenants__tenant)."""
    return next(
        (ct.tenant for ct in contract.contract_tenants.all() if ct.is_representative),
        None,
    )


def contract_status_ui(contract, today):
    """Trả về (khóa, nhãn, màu) của hợp đồng tại ngày today."""
    if contract.status != Contract.Status.HIEU_LUC:
        return 'ket_thuc', 'Đã kết thúc', 'gray'
    days = (contract.end_date - today).days
    if days < 0:
        return 'het_han', 'Đã hết hạn', 'rose'
    if days <= 30:
        return 'sap_het', 'Sắp hết hạn', 'amber'
    return 'hieu_luc', 'Đang hiệu lực', 'mint'