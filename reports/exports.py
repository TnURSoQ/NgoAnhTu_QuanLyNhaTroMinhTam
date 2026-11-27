"""Excel export of the same report figures displayed on screen."""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def report_excel(context):
    workbook = Workbook()
    workbook.remove(workbook.active)
    period = context['period']

    def sheet(name, headers, rows, money_columns=()):
        ws = workbook.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append([ILLEGAL_CHARACTERS_RE.sub('', value)[:32767] if isinstance(value, str) else value for value in row])
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = 's'  # Room numbers, phone numbers and notes must never become formulas.
                elif isinstance(cell.value, date):
                    cell.number_format = 'dd/mm/yyyy'
                elif isinstance(cell.value, Decimal) and name == 'Đối soát điện nước' and cell.column in (3, 4, 5):
                    cell.number_format = '#,##0.0'
                elif cell.column in money_columns and isinstance(cell.value, (int, Decimal)):
                    cell.number_format = '#,##0;[Red]-#,##0'
                cell.alignment = Alignment(vertical='top', wrap_text=True)
        for cell in ws[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='B55238')
        for index, header in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(index)].width = 38 if any(word in header for word in ('Ghi chú', 'Nội dung', 'Hạng mục')) else 22
        ws.freeze_panes = 'B2'
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.print_title_rows = '1:1'
        ws.oddFooter.center.text = 'Trang &P / &N'
        return ws

    dp = context['deposit_period']
    sheet('Tổng hợp', ['Hạng mục', 'Giá trị', 'Phạm vi / cách hiểu'], [
        ['Kỳ báo cáo', period.label, f'{period.first:%d/%m/%Y} – {period.last:%d/%m/%Y}'],
        ['Khu vực', period.scope_label, 'Áp dụng cho toàn bộ số liệu trong file'],
        ['Ngày lập báo cáo', context['today'], 'Công nợ, phòng và hợp đồng thể hiện tình trạng hiện tại'],
        ['Tiền mới nhận thanh toán hóa đơn', context['cash_received'], 'Theo ngày thu trong kỳ; không gồm cọc'],
        ['Thu tiền mặt hóa đơn', context['cash_collected'], 'Theo ngày thu trong kỳ'],
        ['Thu chuyển khoản hóa đơn', context['bank_collected'], 'Đã được ghi nhận; không gồm báo chuyển khoản chờ xác nhận'],
        ['Đối trừ cọc vào hóa đơn', context['deposit_applied'], 'Không phải tiền mới nhận'],
        ['Giá trị thanh toán hóa đơn', context['year_total'], 'Tiền mới nhận + đối trừ cọc trong kỳ'],
        ['Hóa đơn theo kỳ đã chọn', context['invoice_total'], 'Theo tháng/năm hóa đơn, không phải ngày thu'],
        ['Tiền phòng đã lập', context['invoice_room'], 'Theo kỳ hóa đơn'],
        ['Tiền điện đã lập', context['invoice_electric'], 'Theo kỳ hóa đơn'],
        ['Tiền nước đã lập', context['invoice_water'], 'Theo kỳ hóa đơn; giữ cách tính đã lưu của từng hóa đơn'],
        ['Dịch vụ / khoản khác đã lập', context['invoice_other'], 'Theo kỳ hóa đơn'],
        ['Hóa đơn kỳ đã chọn còn phải thu', context['invoice_remaining'], 'Số dư hiện tại của nhóm hóa đơn này'],
        ['Tổng công nợ hiện tại', context['total_debt'], 'Gồm mọi kỳ và hợp đồng đã bàn giao'],
        ['Nợ quá hạn hiện tại', context['overdue_debt'], 'Quá hạn thanh toán tính đến ngày lập báo cáo'],
        ['Nợ hợp đồng đã bàn giao', context['ended_debt'], 'Tiếp tục theo dõi, không xóa khi trả phòng'],
        *[[bucket['label'], bucket['amount'], f"{bucket['count']} hóa đơn · Công nợ hiện tại"] for bucket in context['aging']],
        ['Cọc đầu kỳ', dp['opening'], 'Theo sổ cọc trước ngày đầu kỳ'],
        ['Thu cọc trong kỳ', dp['receive'], 'Tiền cọc theo dõi riêng'],
        ['Hoàn cọc trong kỳ', dp['refund'], 'Tiền thực hoàn, không phải số dự kiến hoàn'],
        ['Khấu trừ cọc trong kỳ', dp['deduct'], 'Biến động cọc, không phải tiền mới thu'],
        ['Đối trừ cọc trong kỳ', dp['pay_invoice'], 'Giảm sổ cọc; không cộng thêm lần nữa vào thu tiền'],
        ['Chuyển cọc đến / đi trong kỳ', dp['transfer_in'] - dp['transfer_out'], 'Chuyển nội bộ, không phát sinh thu tiền mới'],
        ['Cọc cuối kỳ', dp['closing'], 'Đầu kỳ + thu + chuyển đến − hoàn − khấu trừ − đối trừ − chuyển đi'],
        ['Cọc thực tế đang giữ', context['deposit_held'], 'Số dư hiện tại, có thể khác cuối kỳ quá khứ'],
        ['Cọc chưa thu đủ', context['deposit_shortfall'], 'Chỉ hợp đồng đang thuê'],
        ['Cọc còn giữ sau bàn giao', context['deposit_ended'], 'Chưa phải số được hoàn ngay; cần quyết toán nợ, nháp và khấu trừ'],
        ['Tổng tiền nhận theo sổ thu và cọc', context['cash_in'], 'Thực thu hóa đơn + thu cọc; không phải doanh thu tiền thuê'],
        ['Tiền hoàn cọc thực tế', context['cash_out'], 'Chỉ phản ánh hoàn cọc; hệ thống chưa có sổ chi phí vận hành'],
        ['Phòng đang thuê / tổng số phòng', f"{context['room_stats']['dang_thue']}/{context['room_stats']['total']}", 'Tình trạng hiện tại'],
        ['Số người đang ở', context['people_count'], 'Người đại diện và người ở cùng đã duyệt trong hợp đồng hiệu lực'],
        ['Phòng trống hiện tại', context['room_stats']['trong'], 'Tình trạng hiện tại'],
        ['Phòng sửa chữa hiện tại', context['room_stats']['bao_tri'], 'Tình trạng hiện tại'],
        ['Hợp đồng hết hạn / sắp hết hạn', len(context['expiring']), 'Hợp đồng hiệu lực đã hết hạn hoặc còn tối đa 30 ngày'],
        ['Yêu cầu sửa chữa gửi trong kỳ', context['repair_stats']['total'], 'Theo ngày gửi'],
        ['Sửa chữa hoàn thành trong kỳ', context['repair_stats']['completed_in_period'], 'Theo ngày hoàn thành, gồm yêu cầu gửi từ kỳ trước'],
        ['Yêu cầu sửa chữa đang chờ / xử lý', context['repair_stats']['current_pending'], 'Tồn đọng hiện tại, mọi kỳ'],
    ], (2,))
    sheet('Thu theo tháng', ['Tháng', 'Tiền mặt (đ)', 'Chuyển khoản (đ)', 'Tiền mới nhận (đ)', 'Đối trừ cọc (đ)', 'Giá trị thanh toán (đ)'],
        [[f"{m['month']}/{period.year}", m['cash'], m['bank'], m['cash_received'], m['deposit'], m['total']] for m in context['months']], range(2, 7))
    sheet('Sổ thu và cọc', ['Ngày', 'Nhóm', 'Nội dung / mã', 'Hợp đồng', 'Phòng', 'Số tiền (đ)', 'Thu tiền mới (đ)', 'Hoàn cọc (đ)', 'Nội bộ (đ)', 'Hình thức', 'Ghi chú'],
        [[r['date'], r['group'], r['code'], r['contract'].display_code, r['room'], r['amount'], r['cash_in'], r['cash_out'], r['internal'], r['method'], r['note']] for r in context['cashbook']], range(6, 10))
    sheet('Hóa đơn trong kỳ', ['Hóa đơn', 'Kỳ', 'Phòng', 'Hợp đồng', 'Người đại diện', 'Tiền phòng (đ)', 'Điện (đ)', 'Nước (đ)', 'Khoản khác (đ)', 'Tổng tiền (đ)', 'Đã thanh toán đến nay (đ)', 'Còn nợ đến nay (đ)', 'Hạn thanh toán'],
        [[f"HĐ#{r['invoice'].pk}", f"{r['invoice'].month}/{r['invoice'].year}", r['invoice'].contract.room.room_number,
          r['invoice'].contract.display_code, r['tenant'].full_name if r['tenant'] else '', r['invoice'].room_fee,
          r['invoice'].electric_fee, r['invoice'].water_fee, r['other_fee'], r['invoice'].total_amount,
          r['paid'], r['remaining'], r['invoice'].due_date] for r in context['issued']], range(6, 13))
    sheet('Công nợ hiện tại', ['Hóa đơn', 'Phòng', 'Hợp đồng', 'Tình trạng hợp đồng', 'Kỳ', 'Người đại diện', 'Điện thoại', 'Tổng tiền (đ)', 'Đã thanh toán (đ)', 'Còn nợ (đ)', 'Hạn thanh toán', 'Ngày quá hạn'],
        [[f"HĐ#{r['invoice'].pk}", r['invoice'].contract.room.room_number, r['invoice'].contract.display_code,
          r['invoice'].contract.get_status_display(), f"{r['invoice'].month}/{r['invoice'].year}",
          r['tenant'].full_name if r['tenant'] else '', r['tenant'].phone if r['tenant'] else '',
          r['invoice'].total_amount, r['paid'], r['remaining'], r['invoice'].due_date, r['overdue_days']] for r in context['debts']], (8, 9, 10))
    sheet('Cọc hiện tại', ['Phòng', 'Hợp đồng', 'Tình trạng', 'Người đại diện', 'Cọc thỏa thuận (đ)', 'Cọc còn giữ (đ)', 'Cọc còn thiếu (đ)', 'Nợ hóa đơn (đ)', 'Nháp chưa chốt'],
        [[r['contract'].room.room_number, r['contract'].display_code, r['contract'].get_status_display(),
          r['tenant'].full_name if r['tenant'] else '', r['contract'].agreed_deposit, r['held'], r['shortfall'], r['debt'], r['drafts']] for r in context['deposit_contracts']], range(5, 9))
    sheet('Phòng và hợp đồng', ['Phòng', 'Tầng', 'Tình trạng', 'Số người', 'Giá thuê / tháng (đ)', 'Hợp đồng', 'Người đại diện', 'Ngày bắt đầu', 'Ngày hết hạn', 'Điện thoại'],
        [[r['room'].room_number, r['room'].floor, r['label'], r['people'], r['rent'],
          r['contract'].display_code if r['contract'] else '', r['tenant'].full_name if r['tenant'] else '',
          r['contract'].start_date if r['contract'] else None, r['contract'].end_date if r['contract'] else None,
          r['tenant'].phone if r['tenant'] else ''] for r in context['room_rows']], (5,))
    sheet('Sửa chữa và tồn đọng', ['Mã yêu cầu', 'Phòng', 'Người gửi', 'Nội dung', 'Danh mục', 'Ưu tiên', 'Trạng thái hiện tại', 'Ngày gửi', 'Ngày hoàn thành', 'Phạm vi'],
        [[r.display_code, r.room.room_number, r.tenant.full_name, r.title, r.get_category_display(),
          r.get_priority_display(), r.get_status_display(), timezone_date(r.created_at), timezone_date(r.resolved_at), r.report_scope] for r in context['repairs']])
    sheet('Đối soát điện nước', ['Phòng', 'Kỳ', 'Điện cũ', 'Điện mới', 'Điện tiêu thụ (kWh)', 'Đơn giá điện (đ/kWh)', 'Tiền điện (đ)',
        'Cách tính nước', 'Nước cũ', 'Nước mới', 'Nước tiêu thụ (m³)', 'Nước theo người (người-tháng)', 'Đơn giá nước (đ)', 'Tiền nước (đ)', 'Đối soát'],
        [[r['invoice'].contract.room.room_number, f"{r['invoice'].month}/{r['invoice'].year}",
          r['reading'].old_electric if r['reading'] else None, r['reading'].new_electric if r['reading'] else None,
          r['electric_usage'], r['invoice'].electric_unit_price, r['invoice'].electric_fee,
          'Theo người' if r['per_person'] else 'Theo công tơ',
          r['reading'].old_water if r['reading'] and not r['per_person'] else None,
          r['reading'].new_water if r['reading'] and not r['per_person'] else None,
          r['water_usage'], r['water_people'], r['invoice'].water_unit_price, r['invoice'].water_fee,
          'Khớp đơn giá' if r['electric_matches'] and r['water_matches'] else 'Cần đối chiếu'] for r in context['utility_rows']], (6, 7, 13, 14))
    workbook.properties.title = f'Báo cáo quản lý nhà trọ {period.label}'
    workbook.properties.creator = settings.SITE_NAME
    data = BytesIO()
    workbook.save(data)
    response = HttpResponse(data.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="bao-cao-{period.year}-{period.month:02d}.xlsx"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def timezone_date(value):
    from django.utils import timezone
    return timezone.localtime(value).date() if value else None
