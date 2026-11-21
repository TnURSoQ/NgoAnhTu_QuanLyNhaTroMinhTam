# Rà soát nghiệp vụ và đối chiếu đề cương

Cập nhật ngày 18/11/2026, dựa trên mã nguồn, đề cương `2251220045_NgoAnhTu_DeCuongDATN.docx` và góp ý giảng viên do sinh viên cung cấp. Đây là mô hình nghiệp vụ của sản phẩm, không phải kết quả khảo sát được tự suy đoán tại nhà trọ.

## Những chỗ thiếu hoặc chưa hợp lý đã xử lý

| Vấn đề trước khi rà soát | Điều chỉnh trong phần mềm |
|---|---|
| Danh sách phòng dùng hình cửa minh họa, chưa có ảnh riêng | Chủ trọ tải ảnh từng phòng; danh sách dùng ảnh đại diện; chi tiết có bộ ảnh. Chưa có ảnh thật thì ghi rõ đang cập nhật |
| Khách không xem được đơn giá điện nước ngay khi chọn phòng | Giá tháng, tiện ích, đơn giá điện/kWh, nước/m³ và danh mục phí có thể đăng ký được công khai |
| Đề cương loại chức năng khách vãng lai, trái với góp ý mới | Bản đề cương cập nhật bổ sung khách xem thông tin phòng; vẫn chỉ có hai vai trò đăng nhập |
| Đề cương ghi PostgreSQL, môi trường hiện tại là SQLite | Bổ sung cấu hình PostgreSQL qua DATABASE_URL, phụ thuộc và hướng dẫn; ghi rõ chưa xác minh kết nối PostgreSQL thực tế |
| Giá hợp đồng lấy trực tiếp từ giá phòng | Lưu giá thuê thỏa thuận riêng. Đổi giá niêm yết không làm thay đổi giá hợp đồng hoặc hóa đơn đã lập |
| Mọi phòng mặc định bị tính cùng danh mục phí | Hợp đồng mới chọn dịch vụ sử dụng; nháp và màn hình lập hóa đơn dùng danh sách đó |
| Nhận phòng giữa tháng không có quy tắc rõ | Hợp đồng chọn thu trọn tháng hoặc tính tháng đầu theo số ngày ở/số ngày trong tháng; hóa đơn vẫn cho chủ trọ đối chiếu khoản thu |
| Chưa có chỉ số điện nước bàn giao | Ghi chỉ số ban đầu trên hợp đồng. Các kỳ sau tự lấy chỉ số cũ; không tự đoán mức tiêu thụ mới |
| Khóa chỉ số theo phòng/tháng làm kẹt khi đổi khách cùng tháng | Lưu chỉ số theo hợp đồng/tháng. Hai khách kế tiếp trong cùng phòng có dữ liệu riêng, không ghi đè kỳ trước |
| Cọc thỏa thuận bị hiểu như tiền đã thu | Có sổ thu cọc từng lần; chỉ ghi nhận thực thu; có chống gửi trùng và không thu vượt thỏa thuận |
| Chuyển phòng chưa theo dõi dòng tiền cọc | Ghi chuyển cọc ra/vào giữa hai hợp đồng; không ghi nhận thu tiền mặt lần nữa |
| Trả phòng chỉ đổi trạng thái | Lưu biên bản quyết toán cọc, khấu trừ có lý do, số tiền hoàn và phòng sẵn sàng hay cần vệ sinh/sửa chữa |
| Có thể bỏ qua bản nháp khi trả/chuyển phòng | Chặn thao tác khi còn nháp; liên kết trực tiếp đến kỳ cần hoàn tất |
| Lưu lại hợp đồng cũ có thể làm phòng đang thuê thành trống | Trạng thái phòng được tính theo hợp đồng còn hiệu lực; giữ phòng đang bảo trì |
| Chưa có công cụ đối chiếu ngoài màn hình | Có bản in hóa đơn, lưu PDF bằng trình duyệt và xuất CSV sổ thực thu/cọc tách riêng |
| Thiếu kiểm tra dữ liệu vận hành | Bổ sung lệnh audit_rental_data chỉ đọc và công việc nhắc chốt điện nước trên Tổng quan |

## Quyết định nghiệp vụ cần ghi rõ khi bảo vệ

- Phạm vi là **một nhà trọ**, không phải nền tảng cho nhiều chủ nhà đăng tin.
- Khách vãng lai không phải vai trò tài khoản thứ ba. Khách chỉ xem phòng, giá và đặt lịch; chỉ người đại diện hợp đồng có tài khoản người thuê.
- Hợp đồng được kích hoạt khi nhận phòng. Chưa có quy trình đặt cọc giữ chỗ/giữ phòng cho hợp đồng tương lai; không tạo hợp đồng hiệu lực trước ngày nhận phòng qua màn hình nghiệp vụ.
- Chỉ số bàn giao của hợp đồng mới là mốc bắt đầu tính cho khách mới. Không bắt khách mới gánh mức tiêu thụ của khách trước.
- Công thức tháng đầu được lựa chọn khi lập hợp đồng; không áp một công thức pháp lý mặc định. Chỉ tiền phòng được chia theo ngày; phí dịch vụ chủ trọ kiểm tra theo thỏa thuận.
- Điện nước cần số đọc công tơ thực tế. Không tự điền số mới bằng số cũ, không coi ô trống là tiêu thụ bằng 0.
- Bàn giao phòng khác với tất toán. Chủ trọ có thể xác nhận bàn giao khi còn nợ hoặc nháp; các khoản này tiếp tục ở hợp đồng cũ, không chuyển sang khách mới. Chỉ khi đã chốt phí, hết nợ và không còn cọc đang giữ mới hiển thị đã tất toán.
- Hoàn cọc là giao dịch riêng, chỉ ghi sau khi thực trả và có xác nhận. Có thể hoàn từng phần, không vượt cọc dư sau khi giữ lại phần bảo đảm nợ; còn nháp thì chưa xác định số có thể hoàn. Đối trừ cọc vào hóa đơn cần thống nhất với người thuê, đồng thời ghi giảm cọc và thanh toán hóa đơn; không tính là tiền mới nhận.
- Báo chuyển khoản của khách chỉ là thông báo. Chỉ chủ trọ xác nhận mới tạo khoản thanh toán.
- Báo cáo là **thực thu hóa đơn**, không phải lợi nhuận. Tiền cọc không cộng vào doanh thu tiền thuê. Chưa có phân hệ chi phí để kết luận lợi nhuận.
- Bản in là chứng từ theo dõi nội bộ; hệ thống chưa tích hợp phát hành hóa đơn điện tử hay cổng thanh toán.

## Dữ liệu cũ và giới hạn cần xử lý trung thực

- Giá thuê hợp đồng cũ được chụp lại từ giá niêm yết tại lúc nâng cấp. Không thể tự khôi phục giá đã ký trong quá khứ nếu trước đây chưa lưu; cần đối chiếu hợp đồng giấy.
- Không tự tạo phiếu thu cọc cho các hợp đồng cũ. Nếu đã nhận tiền trước đây, chủ trọ cần ghi nhận từ chứng từ thật bằng **Ghi nhận thu cọc**.
- Không tự tạo ảnh phòng. Chủ trọ tải ảnh ngay khi **Thêm phòng** hoặc **Sửa thông tin phòng**. Bộ ảnh hiển thị trực tiếp trong chi tiết phòng, không tách thành trang quản lý ảnh riêng.
- Chỉ số bàn giao cũ còn thiếu không được tự suy đoán. Kỳ có lịch sử chỉ số vẫn được lấy tiếp từ kỳ trước; kỳ đầu cần đối chiếu số ban đầu.
- Khi trả phòng, chủ trọ cần chốt các khoản cuối kỳ. Chưa có hóa đơn bổ sung cho phần sử dụng sau khi hóa đơn tháng đó đã được chốt; trường hợp này cần luồng điều chỉnh/hủy và lập lại có lưu vết trong giai đoạn tiếp theo.
- Chưa có nhật ký đầy đủ cho việc sửa/xóa mọi nghiệp vụ, chưa có phân hệ chi phí, công nợ nhà cung cấp, đa nhà trọ, thanh toán tự động hoặc ứng dụng di động.
- Chưa kiểm tra trình duyệt bằng công cụ tự động trong môi trường này; phần giao diện có kiểm tra phản hồi Django và logic JavaScript, cần nghiệm thu màn hình trên thiết bị thực theo checklist.

## Phần có thể thừa hoặc nên để giai đoạn sau

| Nội dung | Đề xuất phạm vi |
|---|---|
| Hai nút cùng đưa vào bảng điện nước | Đã gộp thành một nút |
| Trang Django Admin xuất hiện trong luồng chủ trọ | Dùng giao diện nghiệp vụ; Admin dành cho kỹ thuật |
| Đặt lịch xem phòng | Có sẵn, giữ như chức năng hỗ trợ; không dành phần lớn báo cáo cho tính năng này |
| Nhiều nhà trọ, đăng tin như sàn, chat, app di động | Để hướng phát triển; chưa cần để đáp ứng đề tài một nhà trọ |
| Thanh toán trực tuyến, tự đối soát ngân hàng | Chưa tuyên bố đã có; hiện chỉ ghi nhận và xác nhận chuyển khoản thủ công |
| Báo cáo lợi nhuận khi chưa có sổ chi | Không gọi thực thu là lợi nhuận |

## Ưu tiên tiếp theo trước khi sử dụng vận hành lâu dài

1. Lưu vết chỉnh sửa, hủy và điều chỉnh hóa đơn/phiếu thu thay vì xóa khỏi lịch sử; xử lý hóa đơn bổ sung cuối kỳ.
2. Bổ sung sổ chi phí sửa chữa, điện nước đầu vào, vệ sinh để đối chiếu dòng tiền và tính kết quả kinh doanh.
3. Cải thiện cấp mật khẩu ban đầu, quy trình đổi/reset mật khẩu và phục hồi tài khoản.
4. Kết nối PostgreSQL thật, chuyển dữ liệu có kiểm tra và diễn tập phục hồi cả dữ liệu lẫn ảnh trước khi triển khai.
5. Đối chiếu nghiệp vụ với chủ trọ thực tế và ghi nhận minh chứng khảo sát; không ghi trong báo cáo rằng đã khảo sát/phỏng vấn nếu chưa thực hiện.
