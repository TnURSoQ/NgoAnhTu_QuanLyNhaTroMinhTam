# Kịch bản nghiệm thu và minh chứng đồ án

## Trước khi trình bày với giảng viên

- [ ] Đăng ảnh thật cho từng phòng dùng demo; nhập tiện ích, diện tích, sức chứa, giá thuê và đơn giá điện nước.
- [ ] Trang chủ hiển thị đúng ảnh phòng, giá theo tháng, điện/kWh, nước/người/tháng (mặc định 50.000đ); chi tiết có đủ tiện ích và phí có thể đăng ký.
- [ ] Các ảnh minh họa chung được ghi rõ là minh họa; không gọi ảnh tạo/ảnh mẫu là ảnh thật của phòng.
- [ ] Tên đề tài, tác nhân và phạm vi trong đề cương khớp sản phẩm. Khách không đăng nhập vẫn có luồng xem phòng.
- [ ] Thống nhất cách ghi SQLite phát triển và PostgreSQL triển khai; không nói đã triển khai PostgreSQL nếu chưa kiểm tra máy chủ đó.

## Kịch bản demo xuyên suốt

1. Khách vào trang chủ, lọc phòng, mở bộ ảnh, xem giá tháng/điện/nước/tiện ích và đặt lịch.
2. Chủ trọ xem lịch, lập hồ sơ người thuê và chọn một đại diện; không cấp tài khoản riêng cho người ở chung.
3. Lập hợp đồng có giá thỏa thuận khác giá niêm yết, chỉ số bàn giao và chỉ chọn Wifi; không áp dịch vụ giữ xe nếu không đăng ký.
4. Ghi nhận thu một phần cọc. Kiểm tra số dư cọc thực giữ, không thấy khoản này cộng vào báo cáo thực thu hóa đơn.
5. Tạo nháp tháng, kiểm tra giá thuê theo hợp đồng, số cũ tự điền; để trống nước và lưu dở.
6. Thử số mới nhỏ hơn số cũ để thấy lỗi; nhập đúng rồi chọn chốt. Ô chưa nhập không bị coi là 0.
7. Người thuê xem đúng hóa đơn của mình, báo đã chuyển khoản; chủ trọ đối chiếu rồi xác nhận. Thử xác nhận lại để kiểm tra chống trùng.
8. Thu tiền nhiều lần, đối chiếu số đã thu/còn nợ, bản in và báo cáo.
9. Thử trả phòng khi còn nháp/nợ: hệ thống liệt kê các khoản và yêu cầu xác nhận tiếp tục theo dõi. Sau bàn giao, phòng được giải phóng nhưng hóa đơn vẫn ở hợp đồng cũ.
10. Ghi khấu trừ tài sản có lý do và chọn phòng cần vệ sinh/sửa chữa; kiểm tra chưa tự ghi hoàn cọc. Chốt nháp cũ, đối trừ cọc vào hóa đơn theo thỏa thuận, sau đó ghi nhận số tiền thực tế đã hoàn. Kiểm tra số cọc dư và công nợ sau từng giao dịch.
11. Chuyển phòng ở kịch bản khác: cọc thực giữ chuyển sang hợp đồng mới; phòng cũ và hóa đơn cũ giữ lịch sử.
12. Đổi khách trong cùng phòng và cùng tháng: hai hóa đơn và hai bộ chỉ số thuộc hai hợp đồng khác nhau, khách mới tính từ chỉ số bàn giao của mình.

## Kiểm thử dữ liệu và phân quyền

- [ ] Một phòng không có hai hợp đồng hiệu lực; không có hai đại diện trong cùng hợp đồng.
- [ ] Không giảm sức chứa thấp hơn số đang ở.
- [ ] Cọc không thu vượt thỏa thuận; không khấu trừ vượt số đang giữ; giao dịch gửi lại cùng mã không thu hai lần.
- [ ] Không cho người thuê vào trang chủ trọ, tải ảnh, thu cọc, in hóa đơn quản lý hoặc xuất sổ CSV.
- [ ] Người thuê không xem được hợp đồng/hóa đơn của người khác bằng cách đổi ID.
- [ ] Không tải được HTML/SVG giả dạng ảnh; không quá 10 ảnh/phòng và 5 MB/ảnh.
- [ ] Kiểm tra kích thước màn hình điện thoại và máy tính, bàn phím và thông báo lỗi.
- [ ] Chạy `python -X utf8 manage.py audit_rental_data` và xử lý từng cảnh báo bằng hồ sơ thật.
- [ ] Sao lưu và phục hồi thử cả cơ sở dữ liệu và thư mục ảnh.

## Minh chứng trong báo cáo

Lưu ảnh chụp màn hình từ dữ liệu demo không chứa thông tin cá nhân thật. Với mỗi use case, ghi điều kiện đầu vào, bước thực hiện, kết quả mong đợi, kết quả thực tế và ngày kiểm thử. Giữ output lệnh kiểm thử tự động và tách riêng những phần chưa được kiểm thử trên trình duyệt hoặc PostgreSQL thật.
