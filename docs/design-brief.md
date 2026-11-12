# Gom Đề (`gomde`) — Design Brief & Hệ Thống Giao Diện

> Định hướng thiết kế: **"Bàn học & tờ đề thi in"** — Tối giản, thực dụng, tôn trọng ngữ cảnh học thuật và tránh tuyệt đối các đặc điểm giao diện AI rập khuôn.

---

## 1. Tinh thần thiết kế & Nguyên tắc cốt lõi

### 1.1 Khái niệm chủ đạo: "Tờ đề thi trên bàn học gỗ"
Gợi cảm giác một xấp đề in mực đậm, một cuốn sổ tay có dòng kẻ mỏng 1px, và một cây bút mực đỏ chấm bài của giảng viên:
- **Nền giấy ấm**: Màu ngà ấm (`#FAF7F2`) giảm mỏi mắt, không dùng màu trắng chói `#FFFFFF` toàn màn hình.
- **Mực in đậm**: Chữ dùng màu than nâu ấm (`#1F1B16`) có độ tương phản đạt chuẩn WCAG AAA.
- **Bút đỏ chấm bài**: Dùng màu đỏ gạch/đỏ bút chấm (`#B83227`) làm **màu nhấn duy nhất** cho nút hành động chính, viền tiêu điểm và trạng thái quan trọng.
- **Đường kẻ sổ**: Phân chia khối thông tin bằng đường kẻ mảnh 1px (`#E5DFD5`) thay vì bóng đổ mờ ảo (soft blur shadows) hay viền cong quá đà.

### 1.2 Danh sách "Dấu hiệu AI" cấm sử dụng
1. ❌ **Không** gradient tím–xanh neon, không nền glassmorphism mờ, không blob tròn xoay chuyển.
2. ❌ **Không** hero banner "Supercharge your workflow", không 3 thẻ tính năng icon tròn đều nhau.
3. ❌ **Không** emoji làm icon (như 🚀, 🔥, ⚡, 🤖, ✨) trong tiêu đề hay nút bấm.
4. ❌ **Không** bo góc lớn 16–24px kiểu đồ chơi (chỉ dùng bo góc sắc sảo 2–6px).
5. ❌ **Không** thẻ lồng thẻ nhiều tầng, không bóng đổ sâu đa lớp.
6. ❌ **Không** microcopy rập khuôn tiếng Anh ("Welcome back!", "Something went wrong"). Toàn bộ giao diện dùng tiếng Việt tự nhiên, dùng đúng thuật ngữ sinh viên FPT (ví dụ: `FE`, `PE`, `CSD202`, `PRN212`, `slot thi`, `đáp án`).
7. ❌ **Không** căn giữa mọi thứ: Bố cục thiên về căn trái, mật độ vừa phải, thể hiện danh sách có cấu trúc dạng bảng/sổ mục lục.

---

## 2. Hệ thống Tokens (Design Tokens)

### 2.1 Bảng màu (Color Palette)

| Token Name | Hex Light | Hex Dark | Mô tả / Ứng dụng |
|---|---|---|---|
| `--bg-canvas` | `#FAF7F2` | `#191715` | Nền canvas toàn trang (giấy ngà ấm / nâu than) |
| `--bg-surface` | `#FFFFFF` | `#23201C` | Nền khối nội dung, thẻ tài liệu, bảng dữ liệu |
| `--bg-subtle` | `#F3EFEA` | `#2C2824` | Nền khu vực phụ, tiêu đề bảng, thanh bộ lọc |
| `--bg-hover` | `#ECE7E0` | `#35302A` | Nền khi hover chuột trên hàng danh sách |
| `--text-primary` | `#1F1B16` | `#E8E3DC` | Chữ chính: độ tương phản cao, màu mực than |
| `--text-secondary` | `#5C554E` | `#A69F95` | Chữ phụ, nhãn thông tin phụ, mô tả ngắn |
| `--text-muted` | `#8C8278` | `#787167` | Chữ mờ, placeholder, ghi chú thời gian |
| `--border-subtle` | `#E5DFD5` | `#38322B` | Đường kẻ 1px ngăn dòng, lưới tài liệu |
| `--border-strong` | `#C8C0B2` | `#50483E` | Đường viền hộp nhập, viền nút phụ, viền thẻ |
| `--primary` | `#B83227` | `#D9483B` | Màu nhấn duy nhất: đỏ bút chấm bài |
| `--primary-hover` | `#9C281F` | `#EC5E51` | Trạng thái hover của nút chính |
| `--primary-subtle` | `#FDF1F0` | `#2F1E1D` | Nền mỏng của badge hoặc thông báo quan trọng |

#### Màu trạng thái độ tin cậy (Tông đất - Earth Tones)
*Quy tắc: Luôn kèm biểu tượng hình học hoặc nhãn chữ rõ ràng (Confident, Weak, Conflict, No Data), không chỉ dựa vào màu sắc để hỗ trợ người dùng mù màu.*

| Trạng thái | Mã màu (Text/Icon) | Mã màu (Nền) | Viền | Ý nghĩa |
|---|---|---|---|---|
| **Confident** | `#2D6A4F` (Xanh rêu rừng) | `#EBF4EF` | `#BDDFCB` | Đạt ngưỡng tin cậy cao (≥ 70% đồng thuận) |
| **Weak** | `#B7791F` (Vàng nghệ ấm) | `#FEF8EC` | `#F5DCB0` | Thiếu số lượng bình chọn (< 3 bình chọn) |
| **Conflict** | `#B83227` (Đỏ gạch) | `#FDF1F0` | `#F1B8B3` | Tranh cãi / phiếu phân tán ngang nhau |
| **No Data** | `#6B7280` (Xám chì) | `#F2EFEA` | `#DDD8CE` | Chưa phân tích hoặc chưa có comment |

---

### 2.2 Typography (Kiểu chữ)

- **Tiêu đề lớn & tên trang**: Dùng font **Serif** tao nhã, chuẩn mực, hỗ trợ tiếng Việt đầy đủ (`Source Serif 4`, `Newsreader`, `Lora`, `Georgia`, serif).
- **Giao diện & nội dung (Body UI)**: Dùng font **Sans-serif** hiện đại, dấu thanh sắc nét (`Be Vietnam Pro`, `system-ui`, `-apple-system`, sans-serif).
- **Mã môn, chỉ số, thời gian, tên file**: Dùng font **Monospace** rõ ràng (`JetBrains Mono`, `Fira Code`, monospace).

```css
--font-serif: "Source Serif 4", "Newsreader", "Lora", Georgia, serif;
--font-sans: "Be Vietnam Pro", system-ui, -apple-system, sans-serif;
--font-mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
```

---

### 2.3 Khoảng cách & Kích thước (Spacing & Sizing)
Tuân thủ hệ thống lưới **8px**:
- `--space-1`: `4px`
- `--space-2`: `8px`
- `--space-3`: `12px`
- `--space-4`: `16px`
- `--space-5`: `20px`
- `--space-6`: `24px`
- `--space-8`: `32px`
- `--space-10`: `40px`

Bo góc (Radius): Giữ góc gần vuông, chắc chắn như giấy in:
- Nhỏ: `2px` (nhãn badge, input)
- Vừa: `4px` (nút bấm, thanh tiến trình)
- Lớn: `6px` (hộp thoại, khung viền ngoài)

---

## 3. Cấu trúc 3 Màn hình trong Lát Cắt Dọc (Bước 2)

### Màn hình 1: Chọn môn & Cấu hình biên soạn
- **Tiêu đề**: "Biên soạn đề thi" (Serif) kèm mã môn đang chọn hiển thị rõ dạng mono badge.
- **Thanh tìm kiếm & danh sách môn**: Lưới danh sách môn học (ví dụ: `CSD202`, `PRN212`, `MAS291`...) hiển thị trực quan số lượng đề hiện có trên hệ thống.
- **Bộ lọc loại đề**: Nút chuyển đổi chọn `FE` (Đề Final Exam) hoặc `PE` (Đề Practical Exam).
- **Số lượng đề cần gộp**: Ô nhập số đề cần gom (mặc định 4, có thể điều chỉnh 1-10).
- **Nút hành động chính**: "Bắt đầu gom đề" (Nền đỏ `#B83227`, chữ trắng, viền sắc, có icon mũi tên tiến trình).

### Màn hình 2: Tiến trình biên soạn thời gian thực
- **Thanh tiến trình 2px**: Chạy tinh tế trên đầu thẻ.
- **Thông số nhịp nhàng**: Hiển thị rõ: *Đề đang xử lý (vd 2/4)*, *Số câu đã tải*, *Tốc độ rate limit*.
- **Cửa sổ dòng log (Console nhật ký)**: Font monospace, nền giấy phụ `--bg-subtle`, hiển thị từng hành động cụ thể:
  - `[12:30:15] Kiểm tra phiên đăng nhập: Hợp lệ.`
  - `[12:30:18] Tải đề 1: CSD202_FE_SU23 (30 câu)`
  - `[12:30:20] Đã tải Q1.webp (full-res qua CDN/Session)`
- **Xử lý đăng nhập lại**: Nếu phiên hết hạn, hiển thị khung viền đỏ gạch cảnh báo "Cần đăng nhập lại" và nút mở lại trình duyệt đăng nhập mà không làm sập ứng dụng.

### Màn hình 3: Kết quả & Tải file Word
- **Bảng tổng kết tài liệu**: Tên file xuất `.docx`, dung lượng, tổng số câu hỏi đã ghép nối.
- **Ghi chú tính năng**: Thông báo rõ ràng: *"Đề đã được dàn trang Word chuẩn 16cm. Mỗi câu gồm ảnh gốc và dòng chú thích 'Đáp án: chưa phân tích' (sẽ hoàn thiện bộ phân tích bình chọn ở bước tiếp theo)"*.
- **Nút tải**: Nút đỏ nổi bật "Tải tập đề .docx", và nút phụ "Biên soạn môn khác".

---

## 4. Cam kết bảo mật & Trải nghiệm
- **Không lưu, không in mật khẩu hoặc cookie người dùng** ra log hay console.
- **Responsive**: Trải nghiệm mượt mà từ màn hình điện thoại 375px đến máy tính bảng và desktop.
- **Hỗ trợ chế độ đọc ban đêm (Dark mode)** chuẩn tông nâu than không gây chói.

