# BÁO CÁO TỔNG HỢP TIẾN TRÌNH & KIỂM DUYỆT HỆ THỐNG DOCXSTACKED
*(Tài liệu báo cáo kỹ thuật & kiểm duyệt quy trình dành cho Claude / QA Reviewer)*

**Dự án:** DocxStacked — Công cụ tự động thu thập và biên soạn tài liệu ôn thi trắc nghiệm (FE) và thực hành (PE) cho sinh viên Đại học FPT từ diễn đàn FUOverflow.  
**Thời gian cập nhật:** 12/11/2026  
**Trạng thái kiểm duyệt:** ✅ **100% Passed (72/72 Tests passed, Frontend Vite build 0 lỗi)**

---

## 1. TỔNG QUAN HỆ THỐNG & KIẾN TRÚC KỸ THUẬT

### 1.1. Mục tiêu bài toán
- Tự động hóa quá trình thu thập đề thi từ diễn đàn FUOverflow (cả trắc nghiệm FE và thực hành PE).
- Tải toàn bộ ảnh câu hỏi ở độ phân giải gốc cao nhất (CDN full-res hoặc Viewport screenshot), loại bỏ các dải quảng cáo, watermark và khung thừa bằng thuật toán thị giác máy tính (`image_cropper`).
- Phân tích bình luận, thảo luận của sinh viên dưới từng câu hỏi để tổng hợp đáp án có độ tin cậy cao nhất theo thuật toán bỏ phiếu (Voting tally + Keyword extraction).
- Biên soạn tài liệu ôn tập định dạng Microsoft Word (`.docx`) chuẩn trang Letter/A4, đánh số thứ tự từng câu (`Câu 1:`, `Câu 2:`...), in đậm đáp án đỏ 20pt, có dải phân cách ngang đôi (`===`) sắc nét giữa các câu.
- Cung cấp cơ chế lưu trữ, quản lý tài liệu cá nhân và cơ chế bộ nhớ đệm (Cache Hit / Deduplication) để tải lại tài liệu đã biên soạn ngay lập tức mà không cần cào lại từ đầu.

### 1.2. Tech Stack & Kiến trúc lõi
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 Async (`aiosqlite`), Playwright Chromium, `python-docx` (OpenXML engine), PIL (Pillow), Pydantic v2.
- **Frontend:** React 19, TypeScript, Vite, CSS Variables (hỗ trợ Light / Dark theme), Server-Sent Events (SSE) để truyền nhật ký và thanh tiến độ thời gian thực.
- **Cơ sở dữ liệu:** SQLite 3 chạy ở chế độ **WAL (Write-Ahead Logging)** kết hợp `busy_timeout = 30000ms`, tổ chức dữ liệu theo mô hình lai (Hybrid Relational + JSON).
- **Trình duyệt & Phiên đăng nhập:** Playwright Persistent Context lưu trữ tại `data/browser_profile/` và `data/auth/cookies.json`, kèm cơ chế tự động dọn dẹp tiến trình zombie (`clean_stale_profile_processes`).

---

## 2. BẢNG TỔNG HỢP CÁC VẤN ĐỀ ĐÃ PHÁT HIỆN & GIẢI PHÁP ĐÃ TRIỂN KHAI

| STT | Vấn đề / Yêu cầu người dùng | Nguyên nhân kỹ thuật | Giải pháp triển khai & Kết quả |
| :--- | :--- | :--- | :--- |
| **1** | Lỗi Playwright Sync API inside Asyncio loop | Gọi hàm `sync_playwright` bên trong luồng asyncio của FastAPI gây xung đột event loop. | Đưa toàn bộ các tác vụ crawler vào tiến trình/thread cô lập (`asyncio.to_thread`), khởi tạo vòng lặp mới sạch sẽ cho Playwright. |
| **2** | Lỗi khóa hồ sơ trình duyệt (`Failed to create a ProcessSingleton`) | Các tiến trình Chrome chạy ngầm giữ lock thư mục `browser_profile` khiến lượt chạy sau bị từ chối mở context. | Bổ sung hàm `clean_stale_profile_processes` trong `BrowserManager.start_context`, dùng `psutil` quét và đóng sạch các tiến trình lock trước khi khởi chạy context mới. |
| **3** | Ảnh câu hỏi trong Word bị mờ hoặc chép nguyên thumbnail (câu 11 đến 60) | Phiên đăng nhập bị gián đoạn khiến crawler fallback về thumbnail (400x150, 2KB); ngưỡng cache cũ `> 500 bytes` không loại được ảnh thumbnail. | 1. Xóa bỏ hoàn toàn fallback thumbnail trong `questions.py`, chỉ chấp nhận ảnh full-res từ CDN hoặc element screenshot.<br>2. Nâng ngưỡng kiểm tra ảnh hợp lệ lên `> 8000 bytes` (8KB).<br>3. Bổ sung logic tự động re-crop trong `docx_builder.py` nếu phát hiện ảnh cũ hỏng chiều cao <= 150px. |
| **4** | Tên file Word tự động ép thành `FE` (làm mất chữ `RE` - thi lại) | Hàm `format_exam_docx_filename` lấy `exam.exam_type` (vốn là FE) thay vì giữ nguyên tiêu đề gốc của đề thi trên diễn đàn. | Cập nhật `format_exam_docx_filename` ưu tiên 100% `exam.title` gốc (lọc ký tự cấm của Windows). Đề `PRM392 - SP26 - RE` xuất ra chính xác file `PRM392 - SP26 - RE.docx`. |
| **5** | Thiếu dải phân cách giữa các câu trong Word | Tài liệu Word cũ chỉ có ảnh và đáp án, các câu nối liền nhau khó đọc. | Tích hợp OpenXML paragraph border `w:pBdr/w:bottom val="double"` sz="12" (tương đương người dùng gõ `===` và Enter trong Word), tạo đường kẻ đôi thanh lịch, rõ ràng giữa các câu. |
| **6** | Thiếu đánh số thứ tự câu hỏi (`Câu 1:`, `Câu 2:`...) | Trong ảnh gốc cắt ra từ diễn đàn, dải banner tiêu đề bị cắt bỏ dẫn tới câu hỏi không có số thứ tự. | Thêm khối tiêu đề đoạn văn bản: `Câu {q.index}:` (Font 13pt, in đậm, màu than `#111827`) đặt ngay phía trên ảnh từng câu hỏi. Đã kiểm tra đủ 60 câu trên đề PRM392. |
| **7** | Không đồng bộ giữa checkbox chọn đề bên trái và stepper bên phải | Khi bỏ tích đề ở danh sách bên dưới, con số "Số đề mới nhất mỗi môn" không cập nhật và ngược lại. | Xây dựng cơ chế **đồng bộ 2 chiều (Bidirectional Sync)**:<br>- Khi tích/bỏ tích checkbox: Số lượng bên phải tự động nhảy theo đúng số đề đã chọn.<br>- Khi bấm `+` / `-` ở stepper: Checkbox tự động tích thêm từ trên xuống hoặc **bỏ tích từ dưới lên trên**. |
| **8** | Tự động khóa stepper khi môn chỉ có 1 đề | Khi môn chỉ có 1 đề (như PRM393), stepper vẫn để 4 và hiện cảnh báo lệch số đề. | Khi môn có 1 đề, stepper tự chỉnh về 1, khóa cả 2 nút `+` và `-` (`disabled`, `cursor: not-allowed`), badge hiển thị `1 đề duy nhất`, không còn cảnh báo lệch số lượng. |
| **9** | Không có nút đăng nhập lại khi gặp thông báo ngắt phiên (1 phiên FUOverflow) | FUOverflow chỉ cho phép 1 phiên hoạt động. Khi bị ngắt, người dùng phải quay về trang chủ để đăng nhập lại. | Thêm nút **`🔑 Đăng nhập lại tài khoản`** ngay trong hộp thoại cảnh báo của `ScreenProgress`. Bấm vào sẽ mở popup Modal cho phép nhập Username/Password hoặc dán Cookie, sau đó tự động chạy tiếp từ đúng câu hỏi dở dang. |
| **10** | Quản lý tài khoản và xem tài liệu đã cào cá nhân | Chưa có giao diện để người dùng xem lại và tải nhanh các file Word đã tạo mà không cần cào lại. | 1. Thêm bảng `users` trong SQLite lưu thông tin tài khoản khớp FUOverflow.<br>2. Xây dựng màn hình `ScreenUserDocuments.tsx` (truy cập qua nút `📚 Tài liệu đã cào` trên Header) hiển thị bảng tài liệu tách riêng 2 cột "Số câu", "Dung lượng", kèm nút `📥 Tải file Word` và `🗑️ Xóa`.<br>3. Thêm API backend `GET /api/user/documents` và `DELETE /api/user/documents`. |
| **11** | Thiếu cơ chế Cache tương tự Redis khi nhiều người yêu cầu cùng 1 đề | Nếu nhiều lần yêu cầu cùng 1 đề thi thì hệ thống lại cào lại từ đầu, tốn thời gian và dễ bị khóa tài khoản. | Xây dựng cơ chế **Cache Hit (Deduplication)** trong `orchestrator.py`: Nếu đề thi đã có sẵn dữ liệu trong SQLite và file Word tồn tại trên đĩa, hệ thống trả về ngay lập tức trong **dưới 0.1 giây** (`⚡ [CACHE HIT]`), bỏ qua toàn bộ bước cào trình duyệt. |
| **12** | Thêm nút Đăng xuất trên thanh Header | Người dùng không thể chuyển đổi tài khoản FUOverflow khác một cách tiện lợi. | Bổ sung nút **`🚪 Đăng xuất`** trên Header, gọi API `POST /api/auth/logout` để xóa sạch cookie và phiên đăng nhập an toàn. |

---

## 3. CƠ CẤU CƠ SỞ DỮ LIỆU (DATABASE SCHEMA)

Cơ sở dữ liệu lưu tại `data/docxstacked.db` gồm 8 bảng quan hệ:
1. **`users`**: Quản lý tài khoản FUOverflow (`id`, `username`, `display_name`, `fuo_user_id`, `last_login_at`).
2. **`subjects`**: Quản lý danh mục môn học FPT (`code`, `name`, `forum_url`, `exam_count`, `last_synced_at`).
3. **`exams`**: Quản lý danh sách các đề thi đã quét (`subject_id`, `title`, `url`, `term`, `exam_type`, `question_count`, `status`).
4. **`questions`**: Quản lý chi tiết câu hỏi (`exam_id`, `index`, `file_name`, `local_image_path`, `phash`, `media_id`).
5. **`comments`**: Quản lý các thảo luận dưới mỗi câu (`question_id`, `author_hash`, `raw_text`, `upvotes`).
6. **`answers`**: Quản lý kết quả đáp án suy luận (`question_id`, `answer_set`, `confidence`, `status`, `vote_breakdown`).
7. **`jobs`**: Quản lý phiên chạy biên soạn (`job_id`, `user_id`, `username`, `subject_code`, `status`, `progress_percentage`, `details`).
8. **`settings`**: Lưu trữ cấu hình ứng dụng động (`key`, `value` JSON).

---

## 4. KẾT QUẢ KIỂM DUYỆT & TEST SUITE

- **Backend Pytest:**
  - Tổng số test case: **72/72 tests**
  - Trạng thái: **PASSED 100%** (thời gian thực thi ~10.72s)
  - Bao gồm: Test thuật toán bỏ phiếu, Test cắt ảnh PIL, Test OpenXML Word builder (`Câu N:`, `===`, `20pt red`), Test API xác thực & Logout, Test User Documents & Cache Hit, Test deduplication pHash.
- **Frontend Vite & TypeScript:**
  - `tsc -b && vite build` hoàn thành trong **222ms**, **0 lỗi TypeScript, 0 cảnh báo cú pháp**.
- **Dữ liệu thực nghiệm:**
  - Đề thi `PRM392 - SP26 - RE.docx` được tạo thành công với dung lượng **4.2 MB**, 60/60 câu hỏi rõ nét chuẩn A4, đáp án đỏ to nổi bật và đầy đủ đường kẻ đôi phân cách.
