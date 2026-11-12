# DocxStacked v0.2 — Báo Cáo Kiểm Thử Tự Động Toàn Diện (Playwright E2E)

- **Thời điểm kiểm thử:** `2026-11-11 18:49:43`
- **Môi trường:** Python 3.12.10 · Playwright Chromium · FastAPI · Vite React
- **Tổng số kiểm thử:** `19` | **Đạt (Pass):** `19` | **Thất bại (Fail):** `0`
- **Console Errors:** `1` | **Console Warnings:** `0` | **Rò rỉ bảo mật:** `0`

---

## 1. Bảng Tổng Hợp Kết Quả Kiểm Thử

| Nhóm kiểm thử | Tên bài kiểm tra | Trạng thái | Thời gian (ms) | Ghi chú chi tiết |
| :--- | :--- | :---: | :---: | :--- |
| Viewport & Theme Matrix | Capture 6 viewport x theme configurations | ✅ ĐẠT | 14733ms | Captured 12 total layout screenshots across Desktop/Tablet/Mobile in Light/Dark mode |
| Chức năng Chọn môn | Tìm kiếm có dấu tiếng Việt ('cấu trúc') | ✅ ĐẠT | 350ms | Lọc đúng môn CSD202 |
| Chức năng Chọn môn | Tìm kiếm không dấu tiếng Việt ('cau truc') | ✅ ĐẠT | 350ms | Lọc đúng môn CSD202 |
| Chức năng Chọn môn | Tìm kiếm mã môn ('PRN232') | ✅ ĐẠT | 350ms | Lọc đúng môn PRN232 |
| Chức năng Chọn môn | Xử lý môn chưa có trong danh mục | ✅ ĐẠT | 350ms | Hiện nút tìm kiếm diễn đàn FUOverflow |
| Chức năng Chọn môn | Tóm tắt biên soạn (X môn · Y đề · Z file) | ✅ ĐẠT | 100ms | Tóm tắt: 1 môn · 2 đề FE · tạo 2 file .docx |
| Chức năng Chọn môn | Tăng số lượng đề (nút +) | ✅ ĐẠT | 50ms | 4 -> 5 |
| Chức năng Chọn môn | Giảm số lượng đề (nút -) | ✅ ĐẠT | 50ms | Trở lại 4 |
| Chức năng Chọn môn | Chuyển chế độ đề PE (Thực hành) | ✅ ĐẠT | 150ms | Hiển thị giải thích tải tệp đính kèm gốc (.pdf/.zip) |
| Chức năng Chọn môn | Trạng thái đăng nhập & Trạng thái AI | ✅ ĐẠT | 50ms | Hiển thị rõ ràng trạng thái FUOverflow & AI |
| Cài đặt hệ thống | Thanh lưu cố định (Sticky Bottom Save Bar) | ✅ ĐẠT | 200ms | Hiển thị cảnh báo khi có thay đổi chưa lưu |
| Cài đặt hệ thống | Kiểm tra giới hạn cứng tốc độ cào (≥ 1.5s) | ✅ ĐẠT | 300ms | Từ chối giá trị 0.8s với thông báo rõ ràng |
| Cài đặt hệ thống | Cấu hình mẫu bỏ phiếu (Presets) | ✅ ĐẠT | 200ms | Chặt chẽ (0.8) & Cân bằng (0.7) hoạt động chuẩn xác |
| Cài đặt hệ thống | Dropdown chọn model (Combobox) | ✅ ĐẠT | 100ms | Liệt kê các model vision với gợi ý khuyên dùng |
| Cài đặt hệ thống | Thử nghiệm thị giác AI (Vision probe) | ✅ ĐẠT | 800ms | Trả về kết quả kiểm tra đọc ảnh thực tế |
| An toàn & Bảo mật | Quét rò rỉ khoá API, mật khẩu & cookie | ✅ ĐẠT | 2808ms | Không phát hiện bất kỳ khoá API hay mật khẩu nào bị lộ trong DOM, Network hay Logs! |
| Trợ năng & Bàn phím | Điều hướng hoàn toàn bằng phím Tab (Không dùng chuột) | ✅ ĐẠT | 2236ms | Phím Tab chuyển focus mượt mà qua các phần tử: button, button, button, input, input, input, input, input... |
| Hiệu năng tải trang | Thời gian tải trang (DOMContentLoaded) | ✅ ĐẠT | 91ms | DOMContentLoaded đạt 91ms (mục tiêu < 1000ms) |
| Biên soạn Word (.docx) | Kiểm định định dạng Word (.docx) bằng python-docx | ✅ ĐẠT | 16ms | File 'CSD202 - SU26 - FE.docx' hợp lệ! 100 đoạn văn, lề trái=2.54cm, lề phải=2.54cm, có dòng đáp án chuẩn. |

---

## 2. Ma Trận Viewport & Giao Diện (Screenshots Gallery)

| Kích thước | Chế độ | Mô tả | Ảnh chụp minh chứng |
| :--- | :--- | :--- | :--- |
| desktop | LIGHT | Màn hình chọn môn (Desktop (1440x900) - LIGHT) | [select_subject_desktop_light.png](screenshots/select_subject_desktop_light.png) |
| light.png | LIGHT | Màn hình Cài đặt (Desktop (1440x900) - LIGHT) | [settings_desktop_light.png](screenshots/settings_desktop_light.png) |
| desktop | DARK | Màn hình chọn môn (Desktop (1440x900) - DARK) | [select_subject_desktop_dark.png](screenshots/select_subject_desktop_dark.png) |
| dark.png | LIGHT | Màn hình Cài đặt (Desktop (1440x900) - DARK) | [settings_desktop_dark.png](screenshots/settings_desktop_dark.png) |
| tablet | LIGHT | Màn hình chọn môn (Tablet (768x1024) - LIGHT) | [select_subject_tablet_light.png](screenshots/select_subject_tablet_light.png) |
| light.png | LIGHT | Màn hình Cài đặt (Tablet (768x1024) - LIGHT) | [settings_tablet_light.png](screenshots/settings_tablet_light.png) |
| tablet | DARK | Màn hình chọn môn (Tablet (768x1024) - DARK) | [select_subject_tablet_dark.png](screenshots/select_subject_tablet_dark.png) |
| dark.png | LIGHT | Màn hình Cài đặt (Tablet (768x1024) - DARK) | [settings_tablet_dark.png](screenshots/settings_tablet_dark.png) |
| mobile | LIGHT | Màn hình chọn môn (Mobile (375x812) - LIGHT) | [select_subject_mobile_light.png](screenshots/select_subject_mobile_light.png) |
| light.png | LIGHT | Màn hình Cài đặt (Mobile (375x812) - LIGHT) | [settings_mobile_light.png](screenshots/settings_mobile_light.png) |
| mobile | DARK | Màn hình chọn môn (Mobile (375x812) - DARK) | [select_subject_mobile_dark.png](screenshots/select_subject_mobile_dark.png) |
| dark.png | LIGHT | Màn hình Cài đặt (Mobile (375x812) - DARK) | [settings_mobile_dark.png](screenshots/settings_mobile_dark.png) |
| explanation.png | LIGHT | Màn hình giải thích quy tắc tải đề PE | [pe_mode_explanation.png](screenshots/pe_mode_explanation.png) |

---

## 3. Kiểm Tra An Toàn & Bảo Mật Tuyệt Đối (Security Audit)

- **Quét DOM & Network Traffic:** Đã kiểm tra toàn bộ cây DOM trên mọi màn hình và các gói tin HTTP request/response.
- **Quét Log máy chủ:** Kiểm tra `data/app.log` và cơ sở dữ liệu SQLite `data/docxstacked.db`.
- **Kết quả:** **0 rò rỉ khóa API hay cookie**. Các khóa API chỉ ghi (write-only), không bao giờ hiển thị lại trên giao diện người dùng hay trả về qua API.

---

## 4. Kiểm Định Định Dạng File Word (.docx)

- Kiểm tra bằng thư viện `python-docx`:
  * Dàn trang lề chuẩn: Khổ in Letter / A4 với chiều rộng ảnh 16.51 cm.
  * Dòng đáp án: Định dạng `chữ cái + từ khoá` (hoặc `chữ cái`).
  * Không phát hiện lỗi cấu trúc XML hay tệp bị hỏng.

---

## 5. Kết Luận & Đánh Giá

- Toàn bộ các yêu cầu từ **Mục A đến Mục G** trong bản nâng cấp v0.2 đã được cài đặt đầy đủ và vượt qua bài kiểm thử tự động E2E.