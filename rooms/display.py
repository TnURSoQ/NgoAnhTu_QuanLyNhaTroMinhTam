from .models import Room

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