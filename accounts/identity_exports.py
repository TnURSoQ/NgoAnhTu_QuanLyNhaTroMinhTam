from collections import OrderedDict
from io import BytesIO
import re
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .decorators import owner_required
from .models import Tenant
from .tenant_records import tenant_rows


class IdentityExportForm(forms.Form):
    ids = forms.ModelMultipleChoiceField(queryset=Tenant.objects.all(), required=True)
    action = forms.ChoiceField(choices=[('images', 'In ảnh CCCD'), ('excel', 'Xuất Excel')])


def _photo(field):
    try:
        return bool(field and field.storage.exists(field.name))
    except OSError:
        return False


@owner_required
@never_cache
@require_POST
def export_identities(request):
    form = IdentityExportForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Hãy chọn ít nhất một hồ sơ hợp lệ và thao tác cần thực hiện.')
        query = urlencode({key: request.POST.get(key, '') for key in ('q', 'status')})
        return redirect(reverse('tenant_list') + ('?' + query if query else ''))
    rows = tenant_rows(form.cleaned_data['ids'].values_list('pk', flat=True))
    for row in rows:
        doc = row['document']
        row['has_front'] = _photo(doc.front) if doc else False
        row['has_back'] = _photo(doc.back) if doc else False
    if form.cleaned_data['action'] == 'excel':
        return _excel(rows)
    order = {'dang_thue': 0, 'da_tra': 1, 'chua_thue': 2}
    rows.sort(key=lambda row: (order[row['state']], row['room'].floor if row['room'] else 0,
        row['room'].room_number if row['room'] else '', row['tenant'].full_name, row['tenant'].pk))
    groups = OrderedDict()
    for row in rows:
        key = (row['state'], row['room'].pk if row['room'] else None)
        if key not in groups:
            groups[key] = {'state': row['state'], 'room': row['room'], 'people': []}
        groups[key]['people'].append(row)
    return render(request, 'print/identity_images.html', {'groups': groups.values(), 'selected_count': len(rows),
        'document_title': 'Danh sách căn cước người thuê', 'back_url': reverse('tenant_list')})


def _excel(rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    roster = workbook.active
    roster.title = 'Danh sách người ở'
    details = workbook.create_sheet('Chi tiết căn cước')
    roster_headers = ['STT', 'Phòng', 'Trạng thái', 'Vai trò', 'Họ và tên', 'Số CCCD/CMND', 'Ngày sinh',
        'Giới tính', 'Quốc tịch', 'Ngày bắt đầu hợp đồng', 'Ngày trả phòng theo HĐ', 'Điện thoại', 'Email', 'Địa chỉ nhà trọ đang ở']
    detail_headers = ['STT', 'Họ và tên', 'Loại giấy tờ', 'Số CCCD/CMND', 'Ngày sinh', 'Giới tính', 'Quốc tịch',
        'Nơi sinh', 'Nơi đăng ký khai sinh', 'Quê quán', 'Địa chỉ thường trú (theo căn cước)', 'Ngày cấp',
        'Ngày hết hạn', 'Không thời hạn', 'Cơ quan / nơi cấp', 'Nghề nghiệp', 'Phòng',
        'Trạng thái', 'Vai trò', 'Địa chỉ nhà trọ đang ở', 'Ảnh mặt trước', 'Ảnh mặt sau', 'Thông tin cần bổ sung',
        'Giấy tờ đã hết hạn', 'Ảnh cần đối chiếu lại số']
    data_rows = [[], []]
    for index, row in enumerate(rows, 1):
        person, ct, contract = row['tenant'], row['link'], row['contract']
        room = ('P.' + row['room'].room_number) if row['room'] else ''
        role = ('Người đại diện' if ct.is_representative else 'Người ở cùng') if ct else ''
        address = f'{room} · {settings.SITE_ADDRESS}' if row['state'] == 'dang_thue' else ''
        data_rows[0].append([index, room, row['label'], role, person.full_name, person.id_card_number,
            person.date_of_birth, person.get_gender_display(), person.nationality, contract.start_date if contract else None,
            contract.checkout_date if contract and row['state'] == 'da_tra' else None, person.phone, person.email or '', address])
        data_rows[1].append([index, person.full_name, person.get_document_type_display(), person.id_card_number,
            person.date_of_birth, person.get_gender_display(), person.nationality, person.place_of_birth,
            person.birth_registration_place, person.hometown or '', person.permanent_address,
            person.identity_issued_on, person.identity_expires_on, 'Có' if person.identity_no_expiry else '',
            person.identity_issued_by, person.occupation, room, row['label'], role, address,
            'Có' if row['has_front'] else 'Chưa có', 'Có' if row['has_back'] else 'Chưa có', ', '.join(row['identity_missing']),
            'Có' if person.identity_expired else '', 'Cần đối chiếu' if row['identity_mismatch'] else ''])
    invalid_xml = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]')
    for sheet, headers, values, table_name in [(roster, roster_headers, data_rows[0], 'ResidentRoster'),
                                              (details, detail_headers, data_rows[1], 'IdentityDetails')]:
        sheet.append(headers)
        for item in values:
            sheet.append([invalid_xml.sub('', value) if isinstance(value, str) else value for value in item])
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'  # Never interpret a person's name/address as an Excel formula.
                    cell.number_format = '@'
                elif getattr(cell.value, 'year', None):
                    cell.number_format = 'dd/mm/yyyy'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='B55238')
        for index, name in enumerate(headers, 1):
            sheet.column_dimensions[get_column_letter(index)].width = 42 if any(
                word in name for word in ('Địa chỉ', 'Nơi ', 'bổ sung', 'Cơ quan')) else (26 if name in ('Họ và tên', 'Email') else 20)
        sheet.row_dimensions[1].height = 32
        sheet.freeze_panes = 'E2' if sheet == roster else 'D2'
        table = Table(displayName=table_name, ref=f'A1:{get_column_letter(len(headers))}{sheet.max_row}')
        table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
        sheet.add_table(table)
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        sheet.print_title_rows = '1:1'
        sheet.print_options.horizontalCentered = True
        sheet.oddFooter.center.text = 'Trang &P / &N'
    workbook.properties.title = 'Hồ sơ người thuê và thông tin căn cước'
    workbook.properties.creator = settings.SITE_NAME
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="ho-so-cu-tru-{timezone.localdate():%Y%m%d}.xlsx"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
