# HƯỚNG DẪN VẬN HÀNH DOCXSTACKED & ĐĂNG NHẬP NỀN TẢNG

Tài liệu này hướng dẫn cách chạy hệ thống DocxStacked, khởi động giao diện Dashboard và đăng nhập hai nền tảng: **FUOverflow** và **fuexam.me**.

---

## 1. Khởi động Backend & Frontend

### 1.1 Khởi động Backend (FastAPI)
Để backend có toàn quyền tương tác với màn hình đồ hoạ Windows (mở trình duyệt Chromium cho việc đăng nhập fuexam.me), bạn **phải** chạy backend trong phiên Windows thực (PowerShell hoặc Terminal của VS Code/IDE trên máy):

```powershell
cd c:\AK\PET_PROJECTS\DocxStacked
.venv\Scripts\Activate.ps1
python run_dev.py
```

> [!IMPORTANT]
> **LƯU Ý VẬN HÀNH QUAN TRỌNG (ĐĂNG NHẬP CHROMIUM HEADED):**
> Nút *"Mở cửa sổ đăng nhập fuexam"* trên giao diện Dashboard sẽ yêu cầu backend khởi động một cửa sổ trình duyệt Chromium hiển thị (headed mode).
> 
> Trình duyệt hiển thị **chỉ có thể mở được** khi backend được khởi chạy từ phiên desktop/PowerShell của người dùng. Nếu backend được kích hoạt từ môi trường nền không tương tác (như CI/CD hoặc terminal ngầm của AI Agent không có desktop session), backend sẽ phát hiện và trả về mã lỗi rõ ràng kèm hướng dẫn:
> 
> ```
> Không thể mở cửa sổ trình duyệt Chromium từ môi trường ngầm hoặc phiên không tương tác.
> Vui lòng chạy backend từ PowerShell trên máy thật: python run_dev.py
> (hoặc mở trực tiếp cửa sổ Chromium từ PowerShell: python scripts/fuexam_login.py)
> ```
> 
> Giao diện Dashboard sẽ hiển thị thông báo lỗi trên ngay lập tức và **không bao giờ bị treo**.

---

## 2. Phương thức đăng nhập fuexam.me duy nhất (Cửa sổ Chromium thật)

Hệ thống tuân thủ nguyên tắc bảo mật: **không đọc hoặc xử lý mật khẩu người dùng qua mã nguồn hay console**. Đăng nhập fuexam chỉ có một cách duy nhất:

### Cách 1: Đăng nhập trực quan qua Dashboard
1. Truy cập Dashboard tại `http://localhost:5173` (hoặc `http://localhost:8000`).
2. Chọn thẻ nền tảng **fuexam.me**.
3. Nếu chưa có phiên làm việc, Dashboard sẽ hiện hộp thoại đăng nhập.
4. Nhấn nút **"Mở cửa sổ đăng nhập"**. Cửa sổ Chromium sẽ mở đến `https://fuexam.me/login/`.
5. Bạn tự nhập tài khoản và mật khẩu trực tiếp trên giao diện Chromium rồi nhấn "Đăng nhập".
6. Dashboard tự động phát hiện phiên đăng nhập thành công và đóng hộp thoại trong 1 giây mà không cần thao tác thêm.

### Cách 2: Mở cửa sổ Chromium qua dòng lệnh
Nếu bạn đang chạy từ PowerShell trên máy thật:
```powershell
.venv\Scripts\python.exe scripts/fuexam_login.py
```
- Cửa sổ Chromium thật sẽ xuất hiện để bạn tự nhập tài khoản và mật khẩu.
- Sau khi đăng nhập thành công, phiên tự động lưu vào `data/auth/fuexam_storage_state.json`.

### Kiểm tra trạng thái phiên
```powershell
.venv\Scripts\python.exe scripts/fuexam_login.py --status
```
Kết quả trả về:
- `logged_in`: Đã có phiên hợp lệ.
- `logged_out`: Chưa đăng nhập hoặc phiên đã hết hạn.

---

## 3. Quản lý phiên FUOverflow

- Nền tảng FUOverflow sử dụng **Extension DocxStacked trên trình duyệt Chrome/Edge** làm nguồn xác thực duy nhất (Single Source of Truth).
- Người dùng chỉ cần đăng nhập tài khoản FUOverflow trên trình duyệt có cài Extension.
- Dashboard tự động kết nối qua extension PING / externally_connectable với cơ chế debounce $\ge 30\text{s}$, không spam request.
- Khi truy cập Dashboard từ Extension (bấm "Mở dashboard" trên popup hoặc URL có tham số `?source=extension`), hệ thống tự động bỏ qua màn hình chọn nền tảng và vào thẳng FUOverflow mà không hiện modal.

---

## 4. Xoá phiên / Đăng xuất

- **fuexam.me**: Người dùng có thể nhấn nút **"Đăng xuất fuexam.me (Xoá tệp phiên)"** trong trang **Cài đặt** (Settings) hoặc trên thanh tiêu đề Header. Thao tác này sẽ xoá tệp `data/auth/fuexam_storage_state.json`.
- **FUOverflow**: Nhấn nút "Đăng xuất" trên Header để xoá phiên đăng nhập.

