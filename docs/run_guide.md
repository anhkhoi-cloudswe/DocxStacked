# HƯỚNG DẪN VẬN HÀNH DOCXSTACKED & ĐĂNG NHẬP NỀN TẢNG

Tài liệu này hướng dẫn cách chạy hệ thống DocxStacked, cài đặt/tải lại Extension và cơ chế đồng bộ phiên cho hai nền tảng: **FUOverflow** và **fuexam.me**.

---

## 1. Khởi động Backend & Frontend

### 1.1 Khởi động toàn bộ môi trường phát triển
```powershell
cd c:\AK\PET_PROJECTS\DocxStacked
.venv\Scripts\Activate.ps1
python run_dev.py
```
- `run_dev.py` sẽ khởi động FastAPI backend (cổng 8000), Vite frontend (cổng 5173), kiểm tra health check `/api/health` trước khi sẵn sàng.
- Khi truy cập `http://localhost:5173`, nếu backend chưa hoàn toàn sẵn sàng, frontend sẽ hiển thị banner thông báo *"Backend chưa sẵn sàng, đang thử lại..."* và vô hiệu hoá các nút bấm đăng nhập cho tới khi kết nối ổn định.

---

## 2. Cài đặt / Tải lại Extension DocxStacked (Chrome & Edge)

Extension DocxStacked chịu trách nhiệm hỗ trợ cào đề FUOverflow và tự động đồng bộ phiên đăng nhập của `fuexam.me`.

### 2.1 Cách tải lại Extension Unpacked sau khi cập nhật
Khi `manifest.json` được bổ sung quyền mới (`cookies` và host permission `https://fuexam.me/*`), trình duyệt Chrome/Edge yêu cầu tải lại extension unpacked:

1. Mở trình duyệt Chrome hoặc Edge:
   - Trên Chrome: truy cập thanh địa chỉ `chrome://extensions`
   - Trên Edge: truy cập thanh địa chỉ `edge://extensions`
2. Bật chế độ **Developer mode** (Chế độ dành cho nhà phát triển) ở góc trên bên phải.
3. Tìm extension **DocxStacked**:
   - Nếu đã cài đặt trước đó: Nhấn nút **Tải lại (Reload / biểu tượng mũi tên xoay)** trên thẻ extension.
   - Nếu cài mới lần đầu: Nhấn **Tải tiện ích đã giải nén (Load unpacked)** -> Chọn thư mục `extension` trong dự án (`c:\AK\PET_PROJECTS\DocxStacked\extension`).
4. Nếu trình duyệt hiện popup yêu cầu xác nhận quyền mới:
   - Xác nhận chấp thuận cấp quyền **"Đọc và thay đổi dữ liệu của bạn trên fuexam.me"** và **"Cookies"**.

---

## 3. Cơ chế đăng nhập fuexam.me qua Extension (Mặc định)

DocxStacked sử dụng phương án **đồng bộ phiên qua Extension làm mặc định** cho fuexam.me:
- Người dùng **chỉ cần đăng nhập trên trình duyệt thật của mình** tại tab `https://fuexam.me/login/`.
- Extension tự động đọc các cookie cần thiết (`xf_user`, `xf_session`, `xf_csrf`, `cf_clearance`) và gửi về backend qua API bảo mật `POST /api/auth/fuexam/extension-session` với header `X-Ingest-Token`.
- **Bảo mật tuyệt đối**: DocxStacked không ghi log giá trị cookie ở bất kỳ file nhật ký hay console nào.
- Backend probe kiểm tra phiên trực tiếp trên `https://fuexam.me/` (xác nhận HTTP 200 và thẻ `html[data-logged-in="true"]`), trích xuất tên tài khoản thật (ví dụ: *Đông Khởi*) và đánh dấu phiên thành công.
- Modal trên Dashboard tự động phát hiện và đóng trong 1 giây.

### 3.1 Khi phiên hết hạn giữa lúc đang cào (Mid-Job)
- Nếu phiên fuexam.me hết hạn khi đang tải tài liệu đề thi, job sẽ tự động **tạm dừng an toàn**.
- Hộp thoại cảnh báo xuất hiện: *"Đăng nhập lại fuexam.me ở tab trình duyệt, DocxStacked sẽ tự nhận"*.
- Người dùng chỉ cần chuyển sang tab trình duyệt đăng nhập lại, DocxStacked sẽ tự động nhận phiên mới và tiếp tục cào mà không cần tạo lại job.

### 3.2 Ngắt kết nối phiên Extension
- Nhấn nút **"Ngắt kết nối DocxStacked"** trên Header hoặc trong trang **Cài đặt**.
- Thao tác này **chỉ xoá phiên lưu cục bộ trên DocxStacked**, tuyệt đối **KHÔNG gọi server-side logout** trên fuexam.me, giúp tài khoản trên trình duyệt thật của bạn vẫn duy trì đăng nhập bình thường.

---

## 4. Lựa chọn nâng cao: Dùng cửa sổ Chromium riêng (Headed Playwright)

Dành cho trường hợp người dùng không thể cài extension hoặc môi trường thử nghiệm độc lập:
- Trong modal đăng nhập fuexam.me, mở phần **"Nâng cao: Dùng cửa sổ Chromium riêng (thu gọn mặc định)"**.
- Bấm nút *"Mở cửa sổ Chromium riêng"*. Backend sẽ khởi chạy cửa sổ Playwright headed với tiêu đề *"DocxStacked - Đăng nhập fuexam"*.
- Chế độ này có watchdog tự động dọn dẹp profile tạm và tiến trình chrome mồ côi nếu có lỗi.
- Khi đăng xuất từ chế độ này, backend sẽ thực hiện dọn dẹp profile và gọi server-side logout để đóng phiên.

---

## 5. Quản lý phiên FUOverflow

- FUOverflow vẫn sử dụng Extension DocxStacked làm nguồn xác thực duy nhất (Single Source of Truth) qua cơ chế ingest/externally_connectable hiện có.
- Tất cả các module và file mã nguồn của FUOverflow trong extension (`background.js`, `content.js`, `sidepanel.js`, `offscreen.js`) được bảo toàn nguyên vẹn 100%.
