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
2. **Phòng:** nhập giá niêm yết, diện tích, sức chứa, chọn tiện ích có sẵn hoặc nhập tiện ích khác và tải ảnh thật ngay khi **Thêm phòng / Sửa thông tin**. Có thể chọn nhiều ảnh, chọn ảnh đại diện và đánh dấu xóa ảnh cũ trước khi lưu. Bộ ảnh hiển thị trực tiếp trong chi tiết phòng; trang xem phòng công khai dùng một khung bắt đầu từ ảnh đại diện, có mũi tên và vuốt để chuyển ảnh. Mỗi phòng tối đa 10 ảnh JPG/PNG/WebP, mỗi ảnh tối đa 5 MB. Tiện ích phòng không tự phát sinh phí dịch vụ.
3. **Nhận phòng:** lập hợp đồng, chốt giá thuê thỏa thuận, chỉ số công tơ bàn giao, các dịch vụ sử dụng và cách thu tiền tháng đầu. Tiền cọc thỏa thuận và cọc đã thực nhận là hai giá trị khác nhau.
4. **Hằng tháng:** mở **Hóa đơn → Nhập điện nước / Chốt hóa đơn**. Hệ thống điền chỉ số cũ; chủ trọ nhập số mới, kiểm tra các khoản thu rồi chốt.
5. **Thu tiền:** ghi nhận tiền thực thu, hỗ trợ nhiều lần. Báo chuyển khoản của người thuê phải được chủ trọ đối chiếu rồi xác nhận. Khi đã thống nhất, có thể dùng **Đối trừ cọc** trên hóa đơn/hợp đồng; hệ thống giảm cọc và công nợ cùng lúc. Người thuê mở **Thanh toán**, bấm vào bất kỳ dòng giao dịch để xem mã TT, số tiền của lần đó, phương thức, ngày thu/đối trừ, thời điểm hệ thống ghi nhận, người ghi nhận và hóa đơn liên quan. Giao dịch mới lưu giờ và người thực hiện; giao dịch cũ thiếu giờ để rõ chưa có dữ liệu, không tự gán giờ. Khi nhập nhầm, chủ trọ vào lịch sử hóa đơn chọn **Điều chỉnh / Hủy**, bắt buộc ghi lý do. Hủy giữ nguyên giao dịch gốc và lưu người/thời điểm; điều chỉnh tạo giao dịch mới liên kết với bản gốc. Không sửa/xóa trực tiếp khoản thu đã ghi nhận, kể cả trong Admin. Công nợ và báo cáo chỉ tính giao dịch còn hiệu lực; CSV giữ dòng đã hủy với giá trị tính tiền bằng 0 để đối chiếu. Người thuê nhận thông báo riêng ở chuông, xem được lý do và bản thay thế; in lại bản đã hủy có dấu hiệu rõ, không còn là phiếu xác nhận thanh toán. Hủy ghi nhận không thực hiện hoàn tiền; đối trừ cọc không được hủy độc lập khỏi sổ cọc.
6. **Chuyển phòng / trả phòng:** ghi nhận bàn giao độc lập với việc hết nợ. Nếu còn nợ/nháp thì cần xác nhận tiếp tục theo dõi trên hợp đồng cũ; nháp vẫn được chốt sau khi bàn giao. Chuyển phòng chỉ chuyển phần cọc còn dư, giữ lại phần bảo đảm nợ hoặc phí chưa chốt. Trả phòng ghi khấu trừ có lý do và tình trạng phòng, chưa tự ghi đã hoàn tiền. Sau khi thực sự trả tiền, dùng **Ghi nhận đã hoàn cọc**, có thể hoàn nhiều lần.
7. **Báo cáo:** giá trị hóa đơn đã thanh toán được tách thành tiền mới nhận và đối trừ cọc. Sổ CSV có cột thu/chi thực tế và biến động nội bộ, tránh đếm khoản đối trừ thành tiền nhận lần nữa. Tiền cọc và công nợ hợp đồng đã bàn giao vẫn được theo dõi riêng. Có in hóa đơn hoặc lưu PDF bằng trình duyệt.
8. **Thông báo:** chủ trọ chọn tất cả phòng hoặc một/nhiều phòng cụ thể. Người thuê xem thông báo theo phòng đang ở tại **Thông báo**; người đã trả phòng không nhận các thông báo phòng hiện hành. Thông báo cũ mặc định giữ phạm vi tất cả phòng.
   Chuông có số chưa đọc, nền xanh nhẹ cho các mục chưa đọc. Chỉ khi bấm vào một mục mới đánh dấu đã đọc; mở bảng không tự đọc tất cả. Trạng thái lưu riêng cho từng tài khoản, bản cập nhật thông báo/phản hồi mới được tính lại là chưa đọc. Chủ trọ nhận yêu cầu sửa chữa, lịch hẹn và báo chuyển khoản đang chờ xử lý. Số đếm tự kiểm tra lại mỗi 30 giây khi trang đang mở.
9. **Sửa chữa:** người thuê gửi mô tả kèm tối đa 5 ảnh JPG/PNG/WebP, mỗi ảnh tối đa 5 MB; có thể chọn ảnh hoặc dùng camera điện thoại nếu trình duyệt hỗ trợ. Ngày và buổi nằm chung nhóm **Thời gian thuận tiện**. Chọn **Qua điện thoại** sẽ hiện số liên hệ bắt buộc, điền sẵn số hồ sơ và cho sửa riêng cho yêu cầu; chọn qua ứng dụng sẽ ẩn ô và không lưu số này. Số liên hệ hiển thị trong chi tiết và phiếu sửa chữa. Phản hồi của chủ trọ hiện trong chi tiết yêu cầu và **Thông báo**. Ảnh chỉ người gửi và chủ trọ được xem.
10. **Hồ sơ người thuê:** **Thông tin cá nhân** cho phép cập nhật họ tên, liên hệ, ngày sinh, giới tính, quốc tịch, nghề nghiệp, loại và số giấy tờ, ngày cấp/hết hạn, cơ quan cấp. Căn cước công dân và thẻ căn cước dùng chung lựa chọn **CCCD / Căn cước**; giữ lựa chọn CMND cho hồ sơ cũ. Chỉ nhập một ô **Địa chỉ thường trú (theo căn cước)**; phần đọc ảnh nhận cả nhãn “Nơi thường trú” và “Nơi cư trú” vào ô này. Quê quán, nơi sinh và nơi đăng ký khai sinh vẫn có ô riêng; phòng đang thuê lấy theo hợp đồng. Không thu thập đặc điểm nhận dạng. Hồ sơ cũ được bổ sung dần, có chỉ dẫn thông tin còn thiếu và cảnh báo giấy tờ hết hạn. Có tải ảnh/chụp hai mặt (JPG/PNG/WebP, tối đa 5 MB/ảnh). Khi tải hoặc chụp ảnh, hệ thống tự đọc các nhãn nhận diện được và điền vào ô trống; có trạng thái tiến trình và nút áp dụng lại nếu muốn thay nội dung đã nhập. Có thể chọn tiếp mặt sau, đổi hoặc bỏ ảnh trong lúc đọc; kết quả từ ảnh cũ bị hủy, giữ nội dung đã sửa tay. Không tự đoán thông tin chưa đọc được; người dùng phải kiểm tra và sửa trước khi lưu. Số khác kết quả đọc phải xác nhận đã đối chiếu, hai mặt đọc được số 12 chữ số khác nhau thì yêu cầu chọn lại ảnh. Đọc chữ không xác thực tính thật của giấy tờ. Kiểm tra định dạng và trùng số vẫn áp dụng; cập nhật CCCD không đổi tên đăng nhập. Chủ trọ cũng tải/đọc ảnh khi thêm hoặc sửa hồ sơ; số CCCD của hồ sơ có tài khoản vẫn giữ quy tắc chỉ người thuê tự cập nhật. Người đại diện gửi cùng các thông tin này cho người ở cùng để chủ trọ duyệt.
11. **In / Lưu PDF:** chủ trọ có bản in A4 cho thông tin hợp đồng, khoản thanh toán, giao dịch cọc, biên bản trả phòng, danh sách người đang ở, toàn bộ phòng, phiếu sửa chữa và báo cáo năm/công nợ. Nút in đặt ở màn hình tương ứng; trình duyệt hỗ trợ chọn máy in hoặc lưu PDF. Người thuê được in/lưu PDF hóa đơn thuộc hợp đồng mình tham gia, kể cả hợp đồng đã kết thúc; có phiếu xác nhận riêng từng giao dịch đã ghi nhận. Bản hóa đơn và số dư dùng chung cách tính với chủ trọ, tách tiền mặt/chuyển khoản và đối trừ cọc; báo chuyển khoản chưa xác nhận không được tính đã thanh toán. Hóa đơn còn nợ vẫn in được và ghi rõ số còn phải trả. Người cùng phòng ở hợp đồng khác không được xem hoặc in chứng từ của nhau. Danh sách người đang ở và phòng dùng A4 ngang. Phiếu chỉ lấy giao dịch đã ghi nhận; khoản đối trừ được ghi rõ là biến động nội bộ. Bản thông tin hợp đồng dùng để đối chiếu hồ sơ, chưa thay thế mẫu hợp đồng có đầy đủ điều khoản hai bên ký. Hóa đơn và sổ CSV tiếp tục sử dụng như trước.
12. **Người ở cùng:** người đại diện hợp đồng đang hiệu lực vào **Người ở cùng → Thêm người ở cùng** để gửi họ tên, CCCD/CMND và thông tin liên hệ; có tải/chụp và đọc ảnh giấy tờ như hồ sơ cá nhân. Hồ sơ chờ xác nhận chưa tạo người thuê hoặc tăng số người ở. Chủ trọ vào **Người thuê → Duyệt người ở cùng** hoặc mở thông báo để đối chiếu thông tin với ảnh, xác nhận hay từ chối kèm lý do. Khi xác nhận, kiểm tra lại sức chứa và tình trạng hợp đồng; người ở cùng cùng ảnh giấy tờ được gắn vào hồ sơ, không tự cấp tài khoản mới. Nếu CCCD đã có, chủ trọ phải đối chiếu và xác nhận dùng hồ sơ hiện có; hệ thống không ghi đè dữ liệu cũ. Người đại diện được hủy hồ sơ đang chờ, hoặc sửa và gửi lại hồ sơ đã hủy/từ chối; có thể dùng lại ảnh lần trước, số thay đổi sẽ yêu cầu đối chiếu và có cảnh báo cho chủ trọ. Lần gửi và phản hồi cũ được giữ nguyên. Kết quả xử lý có thông báo riêng cho người gửi. Chưa tích hợp gửi đăng ký tạm trú tới cơ quan quản lý.
13. **Đặt lịch xem phòng:** khách bấm **Đặt lịch xem phòng** để mở form, chọn ngày/buổi, nhập thông tin liên hệ và email bắt buộc. Nhiều khách khác nhau được gửi yêu cầu cùng phòng/cùng buổi; **chờ xác nhận** chưa giữ giờ hoặc giữ phòng. Chủ trọ xác nhận giờ cụ thể, mỗi lượt 30 phút: sáng 08:00–11:30, chiều 13:30–17:00, tối 18:00–20:00. Lịch dẫn xem dùng chung toàn nhà trọ, chặn cùng giờ kể cả khác phòng. Có lịch theo ngày và các giờ đã xác nhận trong chi tiết lịch hẹn. Đổi giờ được kiểm tra lại; hủy có lý do sẽ giải phóng khung giờ, giữ giờ cũ trong lịch sử. Không ghi nhận đã xem trước ngày/giờ hẹn. Phòng không còn trống sẽ không nhận yêu cầu mới hoặc xác nhận thêm. Lịch cũ thiếu giờ được giữ nguyên; cần bổ sung giờ cho các lịch đã xác nhận trước khi xác nhận thêm cùng buổi.
14. **Chốt thuê và email lịch hẹn:** trạng thái **Đã chốt thuê** gắn với hợp đồng thực tế, không chuyển bằng một nút đánh dấu riêng. Khi lập hợp đồng từ lịch đã xác nhận/đã xem, lịch nguồn được liên kết hợp đồng; các yêu cầu đang chờ và lịch đã xác nhận sắp tới của phòng đó tự hủy với lý do phòng đã có người thuê, có email và đường dẫn tra cứu để chọn phòng khác. Lập hợp đồng trực tiếp hoặc chuyển người thuê sang phòng khác cũng xử lý lịch sắp tới ở phòng được nhận. Không tự sửa các lịch đã diễn ra. Email tiếp nhận, xác nhận, đổi ngày/buổi/giờ, hủy, đã xem và chốt thuê có mã, phòng, giờ cụ thể nếu đã chốt, trạng thái, địa chỉ, lời nhắn và liên kết tra cứu; đổi lịch có cả lịch cũ/mới. Chủ trọ xem lịch sử gửi, gửi lại thư lỗi và sửa email liên hệ. Trang công khai che bớt địa chỉ email. Giữ toàn bộ thay đổi lịch, hợp đồng và các thông báo trong cùng giao dịch; chỉ gửi thư khi giao dịch đã lưu thành công.
15. **Khách tự hủy lịch:** tại **Tra cứu lịch hẹn**, khách có mã được mở **Hủy lịch hẹn**, nhập lý do nếu muốn rồi xác nhận; không cần đăng nhập và lý do không bắt buộc. Chỉ lịch đang chờ/đã xác nhận, chưa chuyển thành hợp đồng được tự hủy. Lịch chuyển sang đã hủy ngay, giải phóng giờ đã giữ; chủ trọ nhận thông báo chưa đọc riêng ở chuông, khách có email xác nhận hủy nếu đã cung cấp địa chỉ. Lưu riêng bên hủy, thời điểm và lý do, giữ nguyên ghi chú đặt lịch và lời nhắn trước đó. Gửi lặp không tạo thêm email/thông báo; hủy không được làm thay đổi hợp đồng hoặc lịch đã xem/chốt thuê. Giữ mã lịch riêng tư để quản lý lịch; các thao tác ghi dùng POST và CSRF. Chủ trọ vẫn cần lý do khi chủ động hủy lịch.
16. **In căn cước / Excel:** tại **Người thuê**, tìm theo tên/điện thoại/số CCCD, lọc trạng thái rồi chọn một, nhiều hoặc tất cả kết quả đang hiển thị. **In ảnh CCCD** mở bản A4: chia theo phòng, ghi tên và đặt ảnh gốc mặt trước/mặt sau cạnh nhau, giữ hai mặt cùng trang. Người đã trả phòng được ghi rõ là phòng cũ; ảnh chưa có hoặc không truy cập được có ô báo thiếu, ảnh có số cần đối chiếu có nhắc kiểm tra. **Xuất Excel** tải tệp `.xlsx` gồm danh sách người ở và chi tiết căn cước; giữ số 0 đầu của CCCD/điện thoại, ngày theo định dạng ngày và nội dung nhập dưới dạng văn bản. Excel chứa thông tin hồ sơ và tình trạng ảnh; ảnh hai mặt nằm trong bản in riêng. Người ở cùng đã được xác nhận có mặt trong kết quả dù không có tài khoản. Các thao tác xuất dành cho chủ trọ; ảnh vẫn qua đường dẫn riêng có kiểm tra quyền, không công khai qua thư mục media. Đây là công cụ chuẩn bị hồ sơ, chưa tích hợp nộp/hoàn thành đăng ký tạm trú.

## Bật gửi email lịch hẹn qua Gmail

Ứng dụng tự đọc `.env` ở thư mục dự án; biến môi trường hệ điều hành được ưu tiên. Tạo `.env` từ `.env.example` nếu chưa có, rồi điền thông tin tài khoản gửi. `.env` đã được bỏ qua trong Git. Mặc định dùng backend console để xem thử, **chưa gửi thư thật**; màn hình chủ trọ hiển thị rõ chế độ này.

Với tài khoản Gmail có hỗ trợ mật khẩu ứng dụng, bật xác minh hai bước rồi tạo mật khẩu ứng dụng theo [hướng dẫn Google](https://support.google.com/accounts/answer/185833?hl=vi). Điền mật khẩu ứng dụng trực tiếp trên máy, không dùng mật khẩu đăng nhập Gmail thông thường và không gửi mật khẩu qua chat. Các tài khoản do tổ chức quản lý có thể bị hạn chế tính năng này. Cấu hình SMTP dựa trên [thông số Gmail](https://support.google.com/mail/answer/7104828?hl=en-GB):

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
EMAIL_HOST_USER=dia-chi-gui@gmail.com
EMAIL_HOST_PASSWORD="mat-khau-ung-dung-cua-ban"
DEFAULT_FROM_EMAIL="Nhà trọ Minh Tâm <dia-chi-gui@gmail.com>"
EMAIL_REPLY_TO=dia-chi-gui@gmail.com
PUBLIC_SITE_URL=http://127.0.0.1:8000
SITE_ADDRESS="Địa chỉ cụ thể của nhà trọ"
SITE_PHONE=so-dien-thoai-chu-tro
```

Thay các giá trị mẫu bằng thông tin thực và bỏ khoảng trắng phân nhóm trong mật khẩu ứng dụng nếu có. Khi triển khai, `PUBLIC_SITE_URL` phải là tên miền khách truy cập được, ví dụ `https://ten-mien-nha-tro.vn`; địa chỉ `127.0.0.1` chỉ dùng khi thử trên cùng máy. Liên kết email lấy từ cấu hình này, không lấy từ Host do người truy cập gửi lên. Thư đang chờ sẽ cập nhật liên kết nếu website đổi sang tên miền mới. Khởi động lại ứng dụng sau khi sửa `.env`.

```powershell
python -X utf8 manage.py send_appointment_emails --check-config
python -X utf8 manage.py send_appointment_emails
```

Lệnh đầu chỉ kiểm tra đủ thông tin cấu hình, không xác thực đăng nhập SMTP hay gửi thư thật. Lệnh sau xử lý các thư đang chờ đến hạn; không gửi lại thư đã gửi hoặc bản lịch cũ đã được thay thế. Thư chỉ gửi sau khi giao dịch lưu lịch/trạng thái thành công; lỗi gửi không làm mất lịch hẹn. Lỗi SMTP được lưu bằng mã và thông báo dễ hiểu, không ghi mật khẩu hoặc phản hồi thô của máy chủ. Khi gửi lỗi, chủ trọ có thể bấm **Gửi lại email đang chờ / bị lỗi** ngay tại chi tiết lịch hẹn. Backend SMTP, thư HTML và bản văn bản dùng [cơ chế email Django](https://docs.djangoproject.com/en/5.2/topics/email/).

Để tự gửi lại thư lỗi trên máy Windows đang chạy dự án, đăng ký sau khi đã cấu hình gửi thật:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-appointment-email-task.ps1
```

Tác vụ `MinhTam-AppointmentEmails` kiểm tra mỗi 5 phút, tối đa 20 thư mỗi lượt. Thử lại sau 5, 15, 45, 135 phút và dừng tự động sau 5 lần thử; chủ trọ vẫn có thể chủ động gửi lại sau khi sửa cấu hình. Tác vụ dùng Python đang có trong PATH, chạy khi máy bật và tài khoản Windows hiện tại đăng nhập; log ở `.backups/appointment-emails.log`. Cần đăng ký lại khi đổi Python, thư mục hoặc chuyển máy. Khi triển khai trên máy chủ khác, chạy lệnh gửi theo lịch tại chính máy chủ đó. Script không tự được đăng ký khi chạy ứng dụng.

“Đã gửi” nghĩa là máy chủ thư đã tiếp nhận; khách vẫn có thể cần kiểm tra mục Thư rác. Hệ thống chống gửi lặp khi bấm lại cùng thao tác và bỏ thư đang chờ nếu đã có thông tin mới hơn. SMTP không cung cấp giao dịch nguyên tử cùng cơ sở dữ liệu: nếu tiến trình dừng sau khi máy chủ nhận thư nhưng trước khi lưu kết quả, một lần gửi lại có thể lặp thư. Mỗi thông báo dùng Message-ID ổn định và liên kết tra cứu luôn hiển thị trạng thái mới nhất.

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

Biến môi trường khác được liệt kê trong `.env.example`; ứng dụng tự đọc `.env` bằng python-dotenv và không ghi đè biến môi trường đã có. Khi triển khai, đặt `DJANGO_DEBUG=0`, khóa `DJANGO_SECRET_KEY` riêng, tên miền trong `DJANGO_ALLOWED_HOSTS` và nơi lưu/serve ảnh bền vững. Django chỉ tự phục vụ ảnh bằng URL `/media/` trong chế độ phát triển. Chạy lệnh tạo nháp theo lịch trên chính máy chủ chứa cơ sở dữ liệu triển khai; tác vụ Windows cục bộ không xử lý cơ sở dữ liệu ở máy chủ khác.

## Tài liệu đồ án

- [Rà soát và quyết định phạm vi](docs/business-review.md).
- [Yêu cầu, quy tắc và sơ đồ dữ liệu](docs/requirements-and-design.md).
- [Kịch bản nghiệm thu](docs/acceptance-checklist.md).
- [Kết quả xác minh và dữ liệu cần đối chiếu](docs/verification.md).
- [Bản chụp SQL schema SQLite để tham khảo](docs/schema-sqlite.sql); cấu trúc cập nhật được quản lý bằng Django migrations.
- Bản đề cương cập nhật trong `docs/`, được tạo riêng để đối chiếu với bản đã gửi giảng viên.
