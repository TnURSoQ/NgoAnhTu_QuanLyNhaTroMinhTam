# Website quản lý nhà trọ Minh Tâm Đà Nẵng

Ứng dụng Django cho một nhà trọ: khách xem phòng và đặt lịch; chủ trọ quản lý vận hành; người đại diện hợp đồng xem thông tin của mình.

## Chạy tại máy phát triển

Môi trường đã kiểm tra: Python 3.14.3, Django 5.2.1 và SQLite. Ảnh phòng dùng Pillow. Các phiên bản trong `requirements.txt` phản ánh môi trường kiểm tra hiện tại.

```powershell
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt
./venv/Scripts/python.exe -X utf8 scripts/install-identity-ocr.py
./venv/Scripts/python.exe -X utf8 manage.py migrate
./venv/Scripts/python.exe -X utf8 manage.py create_owner chutro
./venv/Scripts/python.exe -X utf8 manage.py runserver
```

Lệnh tạo chủ trọ hỏi mật khẩu trong terminal. Chủ trọ không cần quyền Django Admin. Người thuê chỉ được cấp tài khoản khi là đại diện hợp đồng. Tài khoản cũ dùng CCCD làm mật khẩu ban đầu; người thuê cần đổi mật khẩu sau khi nhận tài khoản.

## Luồng sử dụng

1. **Cấu hình:** nhập đơn giá điện nước, dịch vụ và thông tin ngân hàng.
2. **Phòng:** nhập giá niêm yết, diện tích, sức chứa, chọn tiện ích có sẵn hoặc nhập tiện ích khác và tải ảnh thật ngay khi **Thêm phòng / Sửa thông tin**. Có thể chọn nhiều ảnh, chọn ảnh đại diện và đánh dấu xóa ảnh cũ trước khi lưu. Bộ ảnh hiển thị trực tiếp trong chi tiết phòng. Mỗi phòng tối đa 10 ảnh JPG/PNG/WebP, mỗi ảnh tối đa 5 MB. Tiện ích phòng không tự phát sinh phí dịch vụ.
3. **Nhận phòng:** lập hợp đồng, chốt giá thuê thỏa thuận, chỉ số công tơ bàn giao, các dịch vụ sử dụng và cách thu tiền tháng đầu. Tiền cọc thỏa thuận và cọc đã thực nhận là hai giá trị khác nhau.
4. **Hằng tháng:** mở **Hóa đơn → Nhập điện nước / Chốt hóa đơn**. Hệ thống điền chỉ số cũ; chủ trọ nhập số mới, kiểm tra các khoản thu rồi chốt.
5. **Thu tiền:** ghi nhận tiền thực thu, hỗ trợ nhiều lần. Báo chuyển khoản của người thuê phải được chủ trọ đối chiếu rồi xác nhận. Khi đã thống nhất, có thể dùng **Đối trừ cọc** trên hóa đơn/hợp đồng; hệ thống giảm cọc và công nợ cùng lúc.
6. **Chuyển phòng / trả phòng:** ghi nhận bàn giao độc lập với việc hết nợ. Nếu còn nợ/nháp thì cần xác nhận tiếp tục theo dõi trên hợp đồng cũ; nháp vẫn được chốt sau khi bàn giao. Chuyển phòng chỉ chuyển phần cọc còn dư, giữ lại phần bảo đảm nợ hoặc phí chưa chốt. Trả phòng ghi khấu trừ có lý do và tình trạng phòng, chưa tự ghi đã hoàn tiền. Sau khi thực sự trả tiền, dùng **Ghi nhận đã hoàn cọc**, có thể hoàn nhiều lần.
7. **Báo cáo:** giá trị hóa đơn đã thanh toán được tách thành tiền mới nhận và đối trừ cọc. Sổ CSV có cột thu/chi thực tế và biến động nội bộ, tránh đếm khoản đối trừ thành tiền nhận lần nữa. Tiền cọc và công nợ hợp đồng đã bàn giao vẫn được theo dõi riêng. Có in hóa đơn hoặc lưu PDF bằng trình duyệt.
8. **Thông báo:** chủ trọ chọn tất cả phòng hoặc một/nhiều phòng cụ thể. Người thuê xem thông báo theo phòng đang ở tại **Thông báo**; người đã trả phòng không nhận các thông báo phòng hiện hành. Thông báo cũ mặc định giữ phạm vi tất cả phòng.
   Chuông có số chưa đọc, nền xanh nhẹ cho các mục chưa đọc. Chỉ khi bấm vào một mục mới đánh dấu đã đọc; mở bảng không tự đọc tất cả. Trạng thái lưu riêng cho từng tài khoản, bản cập nhật thông báo/phản hồi mới được tính lại là chưa đọc. Chủ trọ nhận yêu cầu sửa chữa, lịch hẹn và báo chuyển khoản đang chờ xử lý. Số đếm tự kiểm tra lại mỗi 30 giây khi trang đang mở.
9. **Sửa chữa:** người thuê gửi mô tả kèm tối đa 5 ảnh JPG/PNG/WebP, mỗi ảnh tối đa 5 MB; có thể chọn ảnh hoặc dùng camera điện thoại nếu trình duyệt hỗ trợ. Ngày và buổi nằm chung nhóm **Thời gian thuận tiện**. Phản hồi của chủ trọ hiện trong chi tiết yêu cầu và **Thông báo**. Ảnh chỉ người gửi và chủ trọ được xem.
10. **Hồ sơ người thuê:** **Thông tin cá nhân** cho phép cập nhật họ tên, liên hệ, ngày sinh, quê quán, nghề nghiệp và số CCCD/CMND. Có tải ảnh/chụp mặt trước và mặt sau giấy tờ (JPG/PNG/WebP, tối đa 5 MB/ảnh). Bấm **Đọc CCCD và điền thông tin** để đọc số, họ tên, ngày sinh, quê quán vào các ô trống; có nút dùng kết quả thay nội dung đang nhập. Thông tin không đọc chắc chắn để trống, không lấy ngày hết hạn làm ngày sinh hoặc địa chỉ thường trú làm quê quán. Người dùng kiểm tra và sửa trước khi lưu; số khác kết quả đọc phải xác nhận đã đối chiếu, hai mặt đọc được số 12 chữ số khác nhau thì yêu cầu chọn lại ảnh. Đọc chữ không xác thực tính thật của giấy tờ. Kiểm tra định dạng và trùng số vẫn áp dụng; cập nhật CCCD không đổi tên đăng nhập. Chủ trọ cũng tải/đọc ảnh khi thêm hoặc sửa hồ sơ; số CCCD của hồ sơ có tài khoản vẫn giữ quy tắc chỉ người thuê tự cập nhật.
11. **In / Lưu PDF:** chủ trọ có bản in A4 cho thông tin hợp đồng, khoản thanh toán, giao dịch cọc, biên bản trả phòng, danh sách người đang ở, toàn bộ phòng, phiếu sửa chữa và báo cáo năm/công nợ. Nút in đặt ở màn hình tương ứng; trình duyệt hỗ trợ chọn máy in hoặc lưu PDF. Danh sách người đang ở và phòng dùng A4 ngang. Phiếu chỉ lấy giao dịch đã ghi nhận; khoản đối trừ được ghi rõ là biến động nội bộ. Bản thông tin hợp đồng dùng để đối chiếu hồ sơ, chưa thay thế mẫu hợp đồng có đầy đủ điều khoản hai bên ký. Hóa đơn và sổ CSV tiếp tục sử dụng như trước.
12. **Người ở cùng:** người đại diện hợp đồng đang hiệu lực vào **Người ở cùng → Thêm người ở cùng** để gửi họ tên, CCCD/CMND và thông tin liên hệ; có tải/chụp và đọc ảnh giấy tờ như hồ sơ cá nhân. Hồ sơ chờ xác nhận chưa tạo người thuê hoặc tăng số người ở. Chủ trọ vào **Người thuê → Duyệt người ở cùng** hoặc mở thông báo để đối chiếu thông tin với ảnh, xác nhận hay từ chối kèm lý do. Khi xác nhận, kiểm tra lại sức chứa và tình trạng hợp đồng; người ở cùng cùng ảnh giấy tờ được gắn vào hồ sơ, không tự cấp tài khoản mới. Nếu CCCD đã có, chủ trọ phải đối chiếu và xác nhận dùng hồ sơ hiện có; hệ thống không ghi đè dữ liệu cũ. Người đại diện được hủy hồ sơ đang chờ, hoặc sửa và gửi lại hồ sơ đã hủy/từ chối; có thể dùng lại ảnh lần trước, số thay đổi sẽ yêu cầu đối chiếu và có cảnh báo cho chủ trọ. Lần gửi và phản hồi cũ được giữ nguyên. Kết quả xử lý có thông báo riêng cho người gửi. Chưa tích hợp gửi đăng ký tạm trú tới cơ quan quản lý.

## Dữ liệu và lịch tự động

- `db.sqlite3`, `media/` (ảnh phòng công khai) và `private-media/` (ảnh sửa chữa và CCCD riêng tư) là dữ liệu thực tế; sao lưu cả ba khi chuyển máy. Không cấu hình máy chủ phục vụ công khai thư mục `private-media/`; ảnh riêng được trả qua đường dẫn có kiểm tra đăng nhập và quyền. Ảnh CCCD nằm ở `private-media/identity/`, chỉ chủ trọ, người gửi hoặc chủ hồ sơ có quyền xem.
- Bộ đọc ảnh chạy trong trình duyệt, dùng tài nguyên được cài vào `static/vendor/identity-ocr/`; ảnh chỉ gửi về ứng dụng khi lưu hồ sơ, không gửi tới dịch vụ OCR bên ngoài. Thư mục bộ đọc được tạo bởi `scripts/install-identity-ocr.py` và không đưa vào Git: cần chạy lệnh cài trên máy mới, có Internet lúc cài, và phục vụ đầy đủ tài nguyên static khi triển khai. Script ghim phiên bản, kiểm tra SHA-512 gói tải xuống, giữ giấy phép và danh sách SHA-256 tệp. Cách dùng đường dẫn cục bộ theo [tài liệu Tesseract.js](https://github.com/naptha/tesseract.js/blob/v6.0.1/docs/local-installation.md). Khi không đọc được ảnh, vẫn có thể nhập tay và gửi hồ sơ để chủ trọ kiểm tra.
- `.backups/` chứa bản sao lưu trước các đợt nâng cấp; không đưa vào Git.
- Lịch tự tạo nháp trên máy Windows được mô tả tại [docs/monthly-billing.md](docs/monthly-billing.md). Khi đổi sang `venv`, đăng ký lại script để lịch dùng đúng Python mới.
- Kiểm tra dữ liệu mà không sửa: `python -X utf8 manage.py audit_rental_data`.
- Kiểm thử: `python -X utf8 manage.py test`.

## PostgreSQL và triển khai

SQLite đang là cơ sở dữ liệu thực tế của môi trường này. Dự án có cấu hình PostgreSQL qua `DATABASE_URL`; việc cấu hình này không tự chuyển dữ liệu SQLite sang PostgreSQL và chưa có máy chủ PostgreSQL được kết nối để kiểm tra trong phiên làm việc.

```powershell
./venv/Scripts/python.exe -m pip install -r requirements-postgres.txt
$env:DATABASE_URL = 'postgresql://username:password@localhost:5432/nhatro?sslmode=prefer'
$env:DJANGO_ALLOWED_HOSTS = 'localhost,127.0.0.1'
./venv/Scripts/python.exe -X utf8 manage.py migrate
```

Biến môi trường khác được liệt kê trong `.env.example`; tệp đó chỉ là mẫu, ứng dụng không tự đọc `.env`. Khi triển khai, đặt `DJANGO_DEBUG=0`, khóa `DJANGO_SECRET_KEY` riêng, tên miền trong `DJANGO_ALLOWED_HOSTS` và nơi lưu/serve ảnh bền vững. Django chỉ tự phục vụ ảnh bằng URL `/media/` trong chế độ phát triển. Chạy lệnh tạo nháp theo lịch trên chính máy chủ chứa cơ sở dữ liệu triển khai; tác vụ Windows cục bộ không xử lý cơ sở dữ liệu ở máy chủ khác.

## Tài liệu đồ án

- [Rà soát và quyết định phạm vi](docs/business-review.md).
- [Yêu cầu, quy tắc và sơ đồ dữ liệu](docs/requirements-and-design.md).
- [Kịch bản nghiệm thu](docs/acceptance-checklist.md).
- [Kết quả xác minh và dữ liệu cần đối chiếu](docs/verification.md).
- [Bản chụp SQL schema SQLite để tham khảo](docs/schema-sqlite.sql); cấu trúc cập nhật được quản lý bằng Django migrations.
- Bản đề cương cập nhật trong `docs/`, được tạo riêng để đối chiếu với bản đã gửi giảng viên.
