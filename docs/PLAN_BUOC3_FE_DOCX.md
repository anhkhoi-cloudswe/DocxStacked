# Bước 3 — FE: ảnh gọn + đáp án theo số đông + Word đúng phong cách

> File này BỔ SUNG và GHI ĐÈ các mục Phase 3 (phần FE), Phase 5 và Phase 6 trong PROJECT_PLAN.md.
> Kèm theo `fe_reference.py`: code mẫu đã chạy thử (cắt ảnh, đọc comment, bỏ phiếu, ghi Word). Chuyển thành module chính thức, không copy nguyên xi.

## 1. Luồng cho 1 đề FE

1. Chọn mã môn → lấy N đề FE mới nhất (mặc định 4).
2. Với mỗi đề: tải ảnh gốc từng câu (đã làm ở Bước 2) → **cắt gọn** → lưu `q{idx:03d}.png`.
3. Với mỗi câu: vào trang `/media/{slug}.{media_id}/` bằng phiên đăng nhập, đọc comment → **bỏ phiếu**.
4. (Tuỳ chọn, bật mặc định) AI đọc ảnh câu hỏi và cho 1 phiếu thêm.
5. Ghi file Word theo mục 4.

## 2. Cắt ảnh (thay cho chụp màn hình)

Ảnh gốc 1920x720 có thanh tiêu đề xanh "MULTIPLE CHOICE" phía trên, logo FUOVERFLOW góc dưới trái, còn lại là nền trắng. Ảnh mẫu của chủ dự án chỉ giữ phần nội dung câu hỏi và đáp án A–D.

- Không cần chụp màn hình trình duyệt. Cắt trực tiếp từ ảnh gốc đã tải: che thanh tiêu đề và watermark bằng màu trắng rồi lấy khung bao quanh vùng có chữ, thêm lề khoảng 12px (xem `crop_question`).
- Đã thử trên ảnh thật: 1920x720 → 406x170, giữ đủ câu hỏi và 4 đáp án, không còn thanh xanh hay logo.
- Câu có đoạn code hoặc hình minh hoạ lớn: giữ nguyên toàn bộ vùng không trắng, không cắt lẹm. Nếu vùng cắt nhỏ bất thường (rộng < 150px hoặc cao < 40px) thì dùng ảnh gốc và ghi cảnh báo trong log.
- Giữ cả ảnh gốc trong `data/raw/` để cắt lại khi cần.

## 3. Đọc đáp án và bỏ phiếu

### 3.1 Nguồn phiếu
| Nguồn | Trọng số mặc định | Ghi chú |
|---|---|---|
| Mỗi comment có đáp án | `1 + log2(1 + số reaction)` | Reaction lấy từ `.reactionsBar` của comment |
| Comment đồng tình (`+1`, `đúng`, `chuẩn`, `ok`) | nửa phiếu của comment bị trích dẫn | Nhận ra comment cha qua `blockquote` (`quoted_comment_id`) |
| AI đọc ảnh | 1.0 (chỉnh trong config) | Là 1 người bỏ phiếu bình thường, không phải quyết định cuối |

"Đáp án nào chiếm số đông thì lấy" = cộng trọng số theo từng nguồn phía trên, đáp án (hoặc tập đáp án) cao nhất thắng.

### 3.2 Một đáp án hay nhiều đáp án
- Ưu tiên lấy từ AI/OCR đọc ảnh ("Select two", "Choose 2", "Select all that apply"). Nếu không có, suy từ comment: đa số comment có từ 2 chữ cái trở lên thì là câu nhiều đáp án.
- Câu một đáp án: lấy chữ cái có tổng trọng số cao nhất.
- Câu nhiều đáp án: mỗi chữ cái được tính đúng nếu chiếm ≥ 50% tổng trọng số. Nếu không chữ nào đủ thì lấy tập đáp án nguyên bản được nhiều phiếu nhất.

### 3.3 Trạng thái
- `confident`: tỷ lệ thắng ≥ 70% và có ≥ 2 nguồn (comment + AI tính chung).
- `weak`: ít nguồn hoặc tỷ lệ thấp.
- `conflict`: hai đáp án đầu sát nhau (chênh < 15%), **hoặc AI không đồng ý với đáp án số đông của comment**.
- `no_data`: không có comment và AI tắt hoặc lỗi.
- `conflict`, `weak`, `no_data` được đánh dấu "cần kiểm tra lại" trong Word và nổi bật trên màn hình review.

### 3.4 Quy tắc đọc comment
Các dạng đã có test trong `fe_reference.py` (19 trường hợp đạt): `b`, `B`, `đáp án C`, `dap an c`, `A,C`, `a và c`, `AC`, `A + D`, `chọn B`, `mình nghĩ đáp án c nhé`, `A đúng`, `không phải A, là B`, `ans: D`, `abd`, `+1`, `đúng`, `có đúng A không?` (bỏ qua), `ai biết đáp án không` (mơ hồ).
Lưu ý:
- Chỉ phân tích phần chữ của chính comment, **loại bỏ nội dung trong `blockquote`** trước khi đọc, nếu không đáp án của comment được trích dẫn sẽ bị tính lặp.
- Viết liền như `ac` chỉ nhận khi các chữ tăng dần, để không nhầm với từ thường như `da`, `ba`.
- Comment trả lời bằng nội dung đáp án thay vì chữ cái (ví dụ "Classes and objects") hiện coi là mơ hồ. Bước sau có thể so khớp với chữ đọc từ ảnh.
- Cần ≥ 60 comment thật làm test. Lấy từ các fixture đã lưu ở Phase 0.5 và từ lần crawl thật.

### 3.5 AI kiểm tra đáp án
- Dùng API của Claude đọc ảnh đã cắt, trả về JSON `{"answers": ["B"], "type": "single|multiple", "confidence": 0-1}`. Dùng model nhỏ, rẻ cho khối lượng lớn.
- **Khoá API chỉ để trong `backend/.env` (`ANTHROPIC_API_KEY`)**, không commit, không in ra log. Khi deploy thì cấu hình trong biến môi trường của nơi chạy backend.
- Bộ nhớ đệm theo pHash của ảnh: câu trùng giữa các đề chỉ gọi AI một lần.
- AI chỉ là một phiếu. Với câu có ghi chú riêng của khoá học hoặc kiến thức theo giáo trình trường, AI có thể sai, vì thế khi AI bất đồng với số đông comment thì phải đánh dấu `conflict` chứ không tự thắng.
- Bật, tắt bằng `analysis.use_ai: true|false`; lỗi mạng hoặc hết hạn mức thì bỏ qua AI và vẫn xuất file.

## 4. File Word (phong cách của chủ dự án, theo hai file mẫu MLN122 và PRN232)

Quan sát từ hai file mẫu:
- Không có trang bìa, tiêu đề hay mục lục. Chỉ gồm các cặp đoạn **ảnh → đáp án** nối tiếp nhau.
- Khổ giấy **Letter** (21,59 x 27,94 cm), lề 2,54 cm.
- Ảnh căn trái, hiển thị theo kích thước thật khoảng **120 dpi** (ảnh 654px → 13,84 cm), **tối đa 16,51 cm** chiều rộng.
- Dòng đáp án: **in đậm, cỡ 20pt, màu đỏ `#EE0000`**, font mặc định của Word.
- Đáp án thường chỉ là chữ cái (`B`), đôi khi kèm nội dung và ghi chú tự thêm (`C. GET`, `A [FromHeader]`).

Yêu cầu cho `docx_builder.py`:
- Giống hệt phong cách trên, không thêm tiêu đề, heading, bảng, hay khối trang trí.
- `export.answer_format`: `letter` (mặc định, ví dụ `B`) hoặc `letter_text` (ví dụ `B. Classes and objects`, cần nội dung đáp án từ AI/OCR).
- Câu nhiều đáp án: `A, C`. Câu `no_data`: `?`.
- Câu `conflict/weak/no_data`: thêm sau đáp án một ghi chú nhỏ màu xám 11pt `(cần kiểm tra lại)`, giữ nguyên phong cách còn lại. Có tuỳ chọn tắt ghi chú này.
- Chuyển ảnh webp sang png trước khi chèn (python-docx không chèn được webp).
- Tên file: `{MaMon} - {Kỳ} - FE.docx` (ví dụ `PRN232 - SP26 - FE.docx`). **Bỏ lỗi lặp tên** hiện tại `CSD202_CSD202_-_SU26_-_FE.docx`.
- Mặc định **mỗi đề một file**. Tuỳ chọn `export.merge: true` gộp 4 đề vào một file, mỗi đề cách nhau bằng ngắt trang. Chỉ khi gộp mới thêm một dòng tên đề.
- Thứ tự câu đúng thứ tự Q1…Qn của đề, không tự sắp xếp lại.

## 5. Màn hình review

Bắt buộc có vì đáp án là số đông, không phải đáp án chính thức:
- Hiện ảnh câu hỏi, đáp án đang chọn, chi tiết phiếu (từng comment: chữ cái, số reaction, đóng góp), phiếu AI, trạng thái.
- Lọc nhanh các câu `conflict/weak/no_data`.
- Sửa đáp án bằng một cú bấm (A/B/C/D, chọn nhiều), lưu cờ "đã sửa tay" và xuất lại Word.

## 6. Việc sửa so với kết quả Bước 2 của Antigravity

1. Ảnh trong Word hiện là ảnh gốc 16 cm, chưa cắt → đổi sang ảnh đã cắt, kích thước theo mục 4.
2. Dòng "Đáp án: chưa phân tích" → đổi sang phong cách mục 4 (đỏ, đậm, 20pt).
3. Tên file bị lặp mã môn → sửa theo mục 4.
4. Xác nhận file `.env` không bị commit (đã có `.gitignore`), thêm `ANTHROPIC_API_KEY` vào `.env.example` dưới dạng giá trị trống.
5. Kiểm tra trên đề thật có ≥ 3 loại câu: một đáp án, nhiều đáp án, câu có đoạn code, rồi so sánh với file mẫu của bạn.

## 7. Tiêu chí hoàn thành Bước 3
- [ ] Chạy một đề FE thật, ra file Word có cặp ảnh gọn + đáp án đỏ đậm 20pt, mở lên giống file mẫu.
- [ ] Mọi câu có dòng đáp án; câu thiếu dữ liệu hiện `?` kèm ghi chú.
- [ ] Parser pass bộ test comment (≥ 60 mẫu thật).
- [ ] Câu AI bất đồng với số đông comment được đánh dấu `conflict`.
- [ ] Review được và sửa tay đáp án rồi xuất lại.
- [ ] Chạy lại không crawl lại phần đã có (resume), không gọi lại AI cho câu đã có kết quả.

