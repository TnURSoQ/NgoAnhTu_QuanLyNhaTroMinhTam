# Hóa đơn nháp và điện nước theo tháng

Trong **Hóa đơn**, mở **Nhập điện nước / Chốt hóa đơn**. Mỗi phòng là một dòng:

1. Kiểm tra tháng/năm. Tháng hiện tại tự tạo nháp khi chủ trọ mở danh sách hóa đơn. Nút **Nhập điện nước / Chốt hóa đơn** bổ sung các phòng chưa có nháp trong kỳ đã chọn rồi mở bảng nhập.
2. Chỉ số cũ lấy từ kỳ trước của hợp đồng hoặc chỉ số bàn giao nhận phòng và không cần nhập lại. Nếu chưa có cả hai, nhập chỉ số ban đầu theo hồ sơ thực tế. Nhập điện mới và nước mới; được để trống để lưu dở. Chỉ số mới phải lớn hơn hoặc bằng chỉ số cũ; nhập bằng nhau để xác nhận không tiêu thụ. Khi kỳ trước được chốt muộn, hệ thống cập nhật chỉ số cũ theo kỳ đó để tránh tính trùng lượng tiêu thụ.
3. Kiểm tra tiền phòng, dịch vụ, đơn giá, tổng dự kiến và hạn thanh toán. Để trống hạn: hệ thống dùng ngày chốt cộng 10 ngày.
4. Bấm **Lưu chỉ số / bản nháp**, hoặc chọn các phòng rồi bấm **Lưu và chốt các phòng đã chọn**. Phòng thiếu chỉ số hay đơn giá vẫn được lưu nháp. Phòng đủ dữ liệu trở thành hóa đơn chính thức.

Nháp không xuất hiện cho người thuê, trong công nợ, báo cáo doanh thu hoặc nhắc quá hạn. Đơn giá điện nước, tiền phòng theo hợp đồng và dịch vụ đăng ký được lưu tại lúc tạo nháp; thay đổi cấu hình sau đó không làm thay đổi nháp đã có. Tiền phòng tháng đầu dùng cách tính đã chọn trên hợp đồng. Nếu thiếu đơn giá lúc tạo, hệ thống bổ sung đơn giá hiện hành khi mở/lưu bảng sau khi cấu hình.

Màn hình **Tạo hóa đơn** cũng tự điền và khóa chỉ số cũ theo kỳ trước của phòng đã chọn. Đổi phòng hoặc đổi tháng/năm sẽ tải chỉ số tương ứng. Hệ thống kiểm tra lại chỉ số cũ khi lưu, kể cả khi dữ liệu gửi lên bị sửa. Các hóa đơn đã chốt giữ nguyên chỉ số lịch sử của kỳ đó.

Mỗi lần lưu bảng thực hiện trong một giao dịch. Dữ liệu sai ở bất kỳ dòng nào làm cả lần lưu được hoàn tác. Nếu hai cửa sổ cùng sửa bảng, cửa sổ cũ phải tải lại để tránh ghi đè. Hóa đơn chốt thủ công từ màn hình cũ cũng đóng nháp tương ứng, tránh chốt trùng.

Chỉ tự tạo nháp cho hợp đồng đang ở trạng thái hiệu lực có ngày thuê giao với kỳ hóa đơn. Nháp của hợp đồng đã bàn giao vẫn hiện để hoàn tất, và chỉ được chốt trong thời gian thuê thực tế đến ngày bàn giao. Không tạo cho kỳ tương lai hoặc hợp đồng đã có hóa đơn/nháp cùng kỳ. Khi đổi khách trong cùng tháng, hợp đồng mới có nháp và chỉ số riêng; nợ/phí cũ vẫn gắn với hợp đồng cũ. Không tự truy thu các kỳ bị bỏ lỡ; chọn từng tháng cũ khi cần.

## Chạy tự động khi không mở website

Chạy lệnh sau hằng ngày bằng Task Scheduler (Windows) hoặc cron (Linux). Lệnh luôn xử lý tháng hiện tại, an toàn khi chạy nhiều lần và bổ sung cả hợp đồng phát sinh giữa tháng. Không tự chốt hoặc gửi hóa đơn.

```powershell
python -X utf8 manage.py generate_monthly_invoice_drafts
```

Kiểm tra trước mà không lưu:

```powershell
python -X utf8 manage.py generate_monthly_invoice_drafts --dry-run
python -X utf8 manage.py generate_monthly_invoice_drafts --month 10 --year 2026 --dry-run
```

Trên Windows, dùng script `scripts/install-monthly-billing-task.ps1` từ thư mục dự án. Script đăng ký tác vụ `MinhTam-MonthlyInvoiceDrafts` chạy lúc 00:10 hằng ngày, chạy bù khi máy khởi động lại, chạy bằng tài khoản Windows hiện tại khi đã đăng nhập. Máy cần bật và người dùng cần đăng nhập để tác vụ chạy. Log nằm trong `.backups/monthly-billing.log`. Khi chuyển máy hoặc môi trường Python, đăng ký lại từ đường dẫn mới.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-monthly-billing-task.ps1
```

Máy chủ Linux: dùng đường dẫn Python và `manage.py` tuyệt đối, đặt múi giờ lịch chạy theo `Asia/Ho_Chi_Minh`. Ví dụ cron:

```cron
10 0 * * * cd /path/to/project && /path/to/venv/bin/python manage.py generate_monthly_invoice_drafts >> /path/to/monthly-billing.log 2>&1
```

Tạo nháp không gửi email. Chức năng nhắc nợ cũ chỉ xử lý hóa đơn đã chốt.
