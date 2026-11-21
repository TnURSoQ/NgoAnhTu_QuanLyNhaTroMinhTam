# Kết quả xác minh

Đối chiếu lần cuối ngày 21/11/2026 trên môi trường phát triển hiện tại.

| Hạng mục | Kết quả |
|---|---|
| Toàn bộ bộ kiểm thử chức năng Django | 452/452 đạt ở lượt chạy đầy đủ cuối; log tại `.backups/identity-ocr/full-tests.log` |
| Cấu hình băm mật khẩu trong lượt kiểm thử nhanh cuối | MD5 chỉ trong tiến trình kiểm thử, nhằm giảm thời gian tạo tài khoản thử; không thay cấu hình ứng dụng hoặc dữ liệu thật |
| Kiểm thử riêng với cấu hình băm mặc định | 21 kiểm thử mới cho thông báo theo phòng, ảnh sửa chữa, hồ sơ cá nhân và tiện ích đạt; các bộ nghiệp vụ trước đã được chạy riêng |
| Django system check | Không có lỗi |
| Trạng thái migration | Đã áp dụng đến accounts.0003, billing.0012, rooms.0010 và support.0004 trên dữ liệu hiện tại; không còn thay đổi model thiếu migration |
| Ảnh CCCD riêng tư | 18 kiểm thử mới đạt: tải/chụp ảnh, hai mặt và giới hạn tệp, đối chiếu số và xác nhận sửa, dữ liệu OCR không ghi đè hồ sơ phía máy chủ, quyền xem riêng, gửi duyệt/chuyển ảnh sang người ở cùng, gửi lại, hoàn tác cơ sở dữ liệu và tệp khi lỗi, xóa ảnh sau commit |
| Bộ đọc CCCD trong trình duyệt | Chạy Tesseract.js thực với mô hình tiếng Việt và ảnh chữ mẫu tự tạo, không chứa giấy tờ/thông tin cá nhân thật. Đọc số, ngày sinh, quê quán đúng; tên cần sửa một dấu trước khi gửi. Đã kiểm tra điền ô trống, giữ số điện thoại nhập tay, cảnh báo khác số, nút áp dụng lại, tải ảnh riêng tư và trang 375px không tràn. Tài nguyên và yêu cầu mạng đều tới máy chủ nội bộ. Chưa đánh giá độ chính xác trên ảnh CCCD thật hoặc camera vật lý |
| Phân tích kết quả đọc | 13 kiểm tra Node đạt: số 9/12 chữ số, số bị tách khoảng trắng, số mâu thuẫn, nhãn tiếng Việt/Anh, họ HỒ, ngày sai/tương lai, không nhầm ngày hết hạn và địa chỉ thường trú |
| Bảo toàn dữ liệu khi nâng cấp ảnh CCCD | Sao lưu `.backups/identity-ocr/before-20261121-152458.sqlite3`; đối chiếu toàn bộ dữ liệu các cột cũ của 28 bảng ứng dụng trước/sau, không thay đổi dữ liệu hiện có |
| Người ở cùng gửi duyệt | 18 kiểm thử mới đạt với cấu hình băm mặc định: chỉ đại diện được gửi, chống giả phòng/người gửi/trạng thái, duyệt không tạo tài khoản, kiểm tra lại sức chứa, không cho một người thuộc hai hợp đồng hiệu lực, đối chiếu hồ sơ CCCD đã có, hủy/gửi lại giữ lịch sử, CSRF và thông báo riêng đúng tài khoản |
| Trình duyệt luồng người ở cùng | Đã chạy trên dữ liệu thử riêng: gửi → từ chối có lý do → sửa và gửi lại → xác nhận; người được duyệt xuất hiện trong danh sách đang ở, chưa có tài khoản; trang kết quả trên màn hình 375px không bị tràn |
| Bảo toàn dữ liệu khi nâng cấp người ở cùng | Sao lưu tại `.backups/cooccupant-approval/`; so sánh các cột cũ và dữ liệu của 27 bảng ứng dụng, không thay đổi dữ liệu hiện có |
| Đã đọc / chưa đọc | 10 kiểm thử mới đạt với cấu hình băm mặc định: đếm riêng theo tài khoản, mở bảng không tự đọc, POST có CSRF, token gắn tài khoản và bản nội dung, không đọc thay bản cập nhật mới, phản hồi mới trở lại chưa đọc |
| Trình duyệt thông báo | Đã kiểm tra trên Chrome với cơ sở dữ liệu thử riêng: chủ trọ đếm 4 → 3 → 0, khách thuê 2 → 1; nền đã đọc/chưa đọc khác nhau, đọc không xác nhận giao dịch, bảng không tràn màn hình điện thoại |
| Bản in | 8 kiểm thử mới đạt với cấu hình băm mặc định; xuất thử 9 PDF gồm hóa đơn hiện có và 8 loại bản in mới, xác nhận khổ A4 dọc/ngang. Kiểm tra hình thức hợp đồng, danh sách người ở và biên bản trả phòng; toàn bộ dùng dữ liệu thử riêng |
| Bảo toàn dữ liệu khi nâng cấp support.0003 | Đã sao lưu tại `.backups/notification-reads/`; đối chiếu các cột cũ của 26 bảng ứng dụng trước/sau, không đổi dữ liệu hiện có |
| Thông báo, ảnh sửa chữa, hồ sơ, tiện ích | 21 kiểm thử mới đạt: lọc theo phòng hiện tại, không lộ thông báo/ảnh cho người khác, tải/chụp ảnh và hoàn tác khi lỗi, kiểm tra CCCD trùng và chỉ sửa hồ sơ chính mình, bảo toàn tiện ích cũ |
| Bảo toàn dữ liệu khi nâng cấp support.0002 | Đã sao lưu SQLite tại `.backups/room-communications/`; đối chiếu dữ liệu các cột cũ của 24 bảng ứng dụng trước/sau, không thay đổi |
| Dữ liệu thực tế | 3 phòng, 4 hợp đồng; lệnh rà soát báo 0 lỗi và 4 mục cần đối chiếu |
| Lịch tự tạo nháp Windows | Log xác nhận đã chạy lúc 00:10 ngày 19/11/2026, không tạo trùng |
| JavaScript hóa đơn/nháp | Kiểm tra cú pháp đạt; có kiểm tra logic nhập chỉ số, tổng tiền và chuyển phòng được chọn |
| Luồng ảnh phòng tích hợp | 14 kiểm thử đạt: thêm/sửa phòng cùng ảnh, ảnh đại diện, xóa/thay ảnh, phân quyền, giới hạn và hoàn tác khi lỗi lưu tệp; chi tiết phòng hiển thị bộ ảnh trực tiếp |
| Bàn giao, công nợ và cọc | 18 kiểm thử mới đạt với cấu hình băm mặc định; bàn giao khi còn khoản chưa tất toán có xác nhận, chốt nháp sau bàn giao, hoàn tiền từng lần, đối trừ cọc đồng thời với hóa đơn và phân biệt tiền mới nhận với biến động nội bộ |
| Word đề cương cập nhật | Kiểm tra gói DOCX, XML, namespace và các thay đổi phạm vi đạt; giữ file gốc riêng |
| PostgreSQL | Kiểm tra phân tích DATABASE_URL và sslmode đạt; chưa kết nối máy chủ PostgreSQL thật |

## Bốn mục dữ liệu cần chủ trọ đối chiếu

- HD-0002: thiếu chỉ số điện nước bàn giao ban đầu.
- HD-0004: thiếu chỉ số điện nước bàn giao ban đầu.
- HD-0004: cọc thực thu chưa đủ hoặc chưa được ghi nhận.
- HD-0004: còn hóa đơn nháp chờ nhập/chốt.

Các mục này chưa được tự điền vì cần chứng từ hoặc số đọc thực tế. Chạy lại `python -X utf8 manage.py audit_rental_data` sau khi đối chiếu để xem trạng thái mới.

## Phạm vi xác minh còn lại

Đã kiểm tra trình duyệt cho bảng thông báo và bản in, chưa nghiệm thu tự động toàn bộ giao diện, chưa xem bản Word bằng Microsoft Word hoặc nghiệm thu PostgreSQL thật. Cần đăng ảnh phòng thật, kiểm tra camera trên điện thoại và kiểm tra phục hồi dữ liệu/ảnh trước khi triển khai lâu dài. Các giới hạn nghiệp vụ còn lại được ghi ở `business-review.md`.
