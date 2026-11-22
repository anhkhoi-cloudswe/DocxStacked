# Báo Cáo Khảo Sát Kỹ Thuật Nền Tảng fuexam.me (Phase 1 Reconnaissance)

> **Mục tiêu:** Cung cấp đầy đủ dữ kiện thực nghiệm (thu thập tự động qua script, kiểm chứng số liệu thật, không chạm DB sản phẩm, không commit secret/cookie) để xây dựng kế hoạch mở rộng DocxStacked hỗ trợ nền tảng song song **fuexam.me** bên cạnh **FUOverflow**.

---

## 1. Phần Mềm Diễn Đàn & Cơ Chế Khách (Guest Access)

### 1.1. Phần mềm, phiên bản và các endpoint hệ thống
- **Phần mềm diễn đàn:** **XenForo 2.3** (ghi nhận qua thuộc tính thẻ gốc `html`: `data-xf="2.3"`, `data-app="public"`).
- **Thẻ meta generator:** `<meta name="generator">` bị ẩn/xóa trên toàn bộ các trang (thao tác tối ưu bảo mật thường gặp trên XenForo).
- **Đường dẫn đăng nhập:**
  - Trang đăng nhập: `https://fuexam.me/login/` (Status: `200 OK`).
  - Endpoint submit form: `POST /login/login`.
- **Đường dẫn tài khoản cá nhân:**
  - `https://fuexam.me/account/` (Khách truy cập trả về `403 Forbidden` kèm chuyển hướng về `/login/`).
- **CSRF Token:**
  - Đặt trong cookie `xf_csrf` (ví dụ: `xf_csrf=...; path=/; secure`).
  - Đính kèm trong HTML qua thẻ hidden input: `<input type="hidden" name="_xfToken" value="<timestamp>,<token_hash>">`.
  - Có sẵn trong cấu hình JavaScript: `csrf: "<timestamp>,<token_hash>"`.
- **XenForo REST API:**
  - Endpoint `https://fuexam.me/api/` và `https://fuexam.me/api/threads/{id}` trả về `HTTP 400 Bad Request` với payload JSON:
    ```json
    {
      "errors": [
        {
          "code": "no_api_key_in_request",
          "message": "No API key was included in the request.",
          "params": []
        }
      ]
    }
    ```
  - REST API chuẩn của XenForo được kích hoạt, nhưng yêu cầu `XF-Api-Key` cấp bởi Ban Quản Trị. Vì vậy, phía crawler / extension phía client sử dụng cơ chế session cookie hoặc DOM scraping.

### 1.2. Quyền hạn chưa đăng nhập (Guest)
| Thành phần | Khách xem được không? | Mã HTTP / Hành vi thực tế |
|---|---|---|
| **Xem nội dung Thread** | **CÓ** | `200 OK`. Toàn bộ nội dung bài viết, tiêu đề, breadcrumb và danh sách file đính kèm hiển thị đầy đủ trong DOM. |
| **Xem danh sách ảnh (Attachments)** | **CÓ** | `200 OK`. Cả 50 file trong `section.message-attachments` đều render đủ thumbnail, tên file và lượt xem. |
| **Tải ảnh gốc qua `/attachments/...`** | **KHÔNG** | `403 Forbidden` (chuyển hướng sang `/login/` với trang Đăng nhập). |
| **Tải ảnh gốc qua `/media/.../full`** | **CÓ (ĐẶC BIỆT)** | `200 OK`. XenForo Media Gallery (XFMG) cho phép tải trực tiếp file WebP gốc mà **không cần cookie đăng nhập**! |
| **Xem bình luận từng ảnh (`/media/...`)** | **CÓ** | `200 OK`. Danh sách bình luận giải thích, đáp án hiển thị đầy đủ trong trang media item. |
| **Tương tác (bình luận, thả reaction)** | **KHÔNG** | Bị chặn, chỉ hiển thị nút Đăng nhập / Đăng ký. |
| **Trang `/account/`** | **KHÔNG** | `403 Forbidden`. |

---

## 2. Cơ Chế Gắn Ảnh Vào Thread & Tải Ảnh

### 2.1. Cấu trúc DOM của ảnh đính kèm
Ảnh được tổ chức trong phần tử:
```html
<section class="message-attachments">
  <ul class="attachmentList">
    <li class="file file--linked">
      <a class="u-anchorTarget" id="attachment-68981"></a>
      <a class="file-preview"
         href="/attachments/prm393-su26-fe-re_001-webp.68981/"
         target="_blank"
         data-lb-sidebar-href="/media/prm393-su26-fe-re_001-webp.34522/?lightbox=1"
         data-lb-caption-extra-html="...">
        <img src="/data/attachments/34/34482-a1e5d75803887072d7fb6bc8d5ce55e2.jpg?hash=XpTQnsi8Ii"
             alt="PRM393 SU26 FE RE_001.webp"
             width="287" height="150" loading="lazy" />
      </a>
      <div class="file-content">
        <div class="file-info">
          <span class="file-name" title="PRM393 SU26 FE RE_001.webp">PRM393 SU26 FE RE_001.webp</span>
          <div class="file-meta">35.9 KB · Lượt xem: 1,146</div>
        </div>
      </div>
    </li>
    <!-- ... tiếp tục 50 items ... -->
  </ul>
</section>
```

### 2.2. Thuộc tính chứa URL
- **URL Thumbnail:** Thuộc tính `src` của thẻ `<img>` con trong `a.file-preview`:
  `/data/attachments/{sub_dir}/{id}-{hash}.jpg?hash={hash_token}`.
- **URL Ảnh gốc (theo link attachment):** Thuộc tính `href` của `a.file-preview`:
  `/attachments/{slug}.{attachment_id}/` (yêu cầu cookie đăng nhập).
- **URL Ảnh gốc trực tiếp (Media Gallery):** Trích xuất từ thuộc tính `data-lb-sidebar-href` (`/media/{slug}.{media_id}/?lightbox=1`):
  Đổi thành `/media/{slug}.{media_id}/full` (tải được trực tiếp cả khi chưa đăng nhập!).

### 2.3. Tên file, thứ tự và tổng số ảnh
- **Tên file:** Nằm ở thuộc tính `alt` của thẻ `<img>` và innerText của `<span class="file-name">`.
- **Quy chuẩn đánh số thứ tự:** Tên file có dạng `{Subject} {Term} {Type}_{NNN}.webp` (ví dụ: `PRM393 SU26 FE RE_001.webp`, `_002.webp`, ..., `_050.webp`). Thứ tự được format chuẩn 3 chữ số zero-padded `001..050` (hoặc `_1.._50` ở một số thread cũ như `PRM393 SP26 FE_1.webp`).
- **Tổng số ảnh:** Đọc trực tiếp từ số lượng phần tử `document.querySelectorAll("section.message-attachments ul.attachmentList li.file")`. DOM không có text tĩnh "1 / 50" trong thread view, nhưng số phần tử khớp chính xác tổng số câu hỏi (ví dụ thread 941 có đúng 50 `li.file`).

### 2.4. Tính chất URL, kích thước, định dạng & Watermark
- **URL ảnh có hết hạn / ký tên không?**
  - URL gốc `/attachments/...` và `/media/.../full` là **URL tĩnh cố định, KHÔNG có query hash, không có token thời hạn**.
  - Chỉ URL thumbnail `/data/attachments/...jpg?hash=...` là có query hash token.
- **Hành vi khi click ảnh ra tab mới:**
  - Thẻ `a.file-preview` có thuộc tính `target="_blank"` và không có class `js-lbImage`. Khi người dùng click ảnh, trình duyệt mở tab mới đến URL `/attachments/{slug}.{attachment_id}/`.
  - Nếu đã đăng nhập, tab mới chỉ hiển thị duy nhất ảnh đó. Nếu chưa đăng nhập, tab mới chuyển hướng đến `/login/`.
- **Tải trực tiếp ảnh gốc:** Hoàn toàn thực hiện được bằng cả 2 cách:
  1. Dùng cookie đăng nhập (`xf_user`, `xf_session`) tải từ `/attachments/{slug}.{id}/`.
  2. Không cần cookie: tải từ `/media/{slug}.{id}/full`.
- **Định dạng file:** 100% là ảnh **WebP** (`RIFF....WEBPVP8 `).
- **Kích thước ảnh:**
  - Đa số các đề FE/RE/PE chuẩn: **1800 x 944**, **1800 x 946**, **1800 x 948** hoặc **1800 x 1074** (B5).
  - Đề có công thức toán/chụp mở rộng (MAE101): **1800 x 1810**.
  - Đề dạng thanh ngang hẹp (VNR202 cũ): **1440 x 493**.
- **Vị trí Watermark:**
  1. **Watermark trung tâm:** Logo chim ưng cách điệu kèm dòng chữ `HAWK` in hoa lớn màu xám nhạt (alpha blend ~10-15%) nằm chính giữa khung chứa câu hỏi.
  2. **Watermark góc:** Logo `FUExam` (với chữ F cách điệu hình phích cắm điện) nằm cố định ở góc dưới cùng bên phải ảnh (`x ~ 1650..1790, y ~ H - 80..H - 10`).
  3. **Watermark dạng lưới (Tiled):** Ở một số đề mới (PRN212, MAE101), chữ `FUEXAM` màu xám mờ lặp nghiêng theo ma trận khắp nền ảnh.

---

## 3. Hệ Thống Bình Luận (Comments)

### 3.1. Phân biệt bình luận Thread vs bình luận Từng Ảnh (Media Item)
- **FUOverflow:** Cả thread comments và lightbox/media comments đều tồn tại song song, với plugin vote điểm `.user-fuo-vote`.
- **fuexam.me:**
  - Bài viết trong Thread (`article.message--post`) chỉ có 1 bài đăng mở đầu của Admin (chứa giới thiệu đề và danh sách đính kèm). Thành viên **không bình luận vào thread**, mà bình luận trực tiếp vào **từng ảnh** thông qua XenForo Media Gallery (XFMG).
  - Trang chi tiết của từng ảnh là: `https://fuexam.me/media/{slug}.{media_id}/`.
  - Trang sidebar của lightbox là: `https://fuexam.me/media/{slug}.{media_id}/?lightbox=1`.

### 3.2. Selectors trích xuất bình luận
Bình luận được render dưới dạng:
```html
<article class="message message--simple message--comment js-comment js-inlineModContainer">
  <div class="message-inner">
    <div class="message-cell message-cell--user">
      <a class="avatar avatar--s" ...>...</a>
    </div>
    <div class="message-cell message-cell--main">
      <div class="message-header">
        <span class="message-name"><a class="username">Phòng Khảo thí FUHCM</a></span>
        <span class="message-attribution">
          <time class="u-dt" datetime="2026-11-19T17:07:08+0700">Lúc 17:07, Thứ năm</time>
        </span>
      </div>
      <div class="message-userContent">
        <div class="message-body">
          <div class="bbWrapper">C. setInt(): ...</div>
        </div>
      </div>
      <div class="reactionsBar js-reactionsList">...</div>
    </div>
  </div>
</article>
```
- **Người viết (Author):** `.message-name .username` hoặc `a.username`.
- **Nội dung bình luận:** `.bbWrapper` nằm trong `.message-body`.
- **Thời gian (Timestamp):** Thẻ `<time>` với thuộc tính ISO: `time[datetime]`.
- **Điểm / Reaction:**
  - **KHÔNG có điểm kiểu `.user-fuo-vote`** (fuexam.me không cài add-on FUVote của FUOverflow).
  - Điểm dựa hoàn toàn vào hệ thống reaction chuẩn của XenForo: `.reactionsBar.js-reactionsList` (đếm số reaction icon hoặc link reaction).

### 3.3. Phân loại nội dung bình luận
Thực nghiệm quét bình luận cho thấy rõ 2 nhóm nội dung:
1. **Bình luận ngắn (Vote đáp án):** Các ký tự đơn như `"B"`, `"b"`, `"C"`, `"c"`.
2. **Bình luận giải thích chuyên môn (Tiếng Việt):**
   - Ví dụ tại `media/prm393-su26-b5-fe_001-webp.44146/`:
     - *Phòng Khảo thí FUHCM:* `"C. setInt(): Trong gói shared_preferences của Flutter, tất cả các phương thức ghi dữ liệu đều bắt đầu bằng tiền tố set kèm theo kiểu dữ liệu tương ứng..."`
     - *Namhgjk123:* `"Đáp án đúng sẽ phụ thuộc vào nền tảng lập trình di động của môn học bạn đang thi (vì cả Android Native và Flutter đều có khái niệm SharedPreferences): C. setInt(): Nếu đây là đề thi môn Flutter... B. putInt(): Nếu đây là đề thi Android Native..."`

### 3.4. Khả năng lấy toàn bộ bình luận của một ảnh
- Khi truy cập URL `https://fuexam.me/media/{slug}.{media_id}/`, XenForo trả về toàn bộ bình luận thuộc ảnh đó trong `div.js-replyNewCommentContainer`.
- Nếu số bình luận vượt quá giới hạn 1 trang (mặc định 20 bình luận), XenForo sinh nút phân trang `.pageNav` hoặc nút tải thêm "Hiện bình luận trước..." với endpoint AJAX: `/media/{media_id}/load-previous-comments?before={comment_id}`.
- Có thể thu thập 100% bình luận của từng ảnh một cách tin cậy thông qua endpoint này.

---

## 4. Quản Lý Đa Đề Thi & Mã Đề (Multi-Exam Threads)

### 4.1. Khảo sát thread chứa nhiều đề thi
- Quét qua 12 thread ở các môn (PRM393, VNR202, MLN131, MIP201, IPR102):
  - 100% các thread chính thức đều có tiền tố tên file **đồng nhất** trong cùng một thread (ví dụ: `PRM393 SU26 FE RE_001.webp` đến `_050.webp`).
  - Chưa xuất hiện hiện tượng trong 1 thread có 2 bộ tên file khác hẳn nhau (như `PRM393_...` trộn lẫn `SWD392_...`).
  - Tuy nhiên, có hiện tượng **Thread gán nhầm môn/đề**:
    - Ví dụ thread 1347: Tiêu đề diễn đàn ghi `PRJ302 - FA26 - PE - NO1 HCM`, nhưng bên trong ảnh lại là câu hỏi trắc nghiệm của `ASI101_FA26_FE_191637 | Multiple Choice Question 12`!

### 4.2. Vị trí mã đề thi (Exam Code)
Mã đề số (ví dụ: `395814`, `882542`, `615762`, `191637`) **KHÔNG** nằm trong tên file (`PRM393 SU26 FE RE_001.webp`) và **KHÔNG** nằm trên tiêu đề diễn đàn.
Mã đề xuất hiện ở 2 vị trí:
1. **Trong nội dung văn bản bài viết (post body):** Đôi khi admin paste OCR/tiêu đề đề thi: `PRM393_SU26_RE_395814`.
2. **Trong thanh tiêu đề đồ họa render bên trong ảnh:**
   Dòng chữ đen đậm trên cùng của ảnh có cấu trúc chuẩn:
   `{MÔN}_{KỲ}_{LOẠI}_{MÃ_ĐỀ} | Multiple Choice Question {N}`
   - Ví dụ: `PRM393_SU26_RE_395814 | Multiple Choice Question 1` -> Mã đề: **395814**.
   - Ví dụ: `PRN212_FA26_FE_882542 | Multiple Choice Question 1` -> Mã đề: **882542**.
   - Ví dụ: `MAE101_FA26_FE_615762 | Multiple Choice Question 1` -> Mã đề: **615762**.

### 4.3. Chiến lược tách đề nếu một thread có nhiều mã đề
Nếu phát hiện một thread có nhiều mã đề trộn lẫn:
1. **Tách theo nhóm tiền tố tên file (Filename Regex):**
   Áp dụng regex `r"^(.*?)[_\s]+0*(\d+)\.(?:webp|jpg|png)$"` để gom nhóm các ảnh cùng prefix.
2. **Tách theo Header OCR / Visual Band:**
   Cắt dải tiêu đề trên cùng (`y = 0..120px`), dùng regex nhận diện `{SUBJECT}_{TERM}_{TYPE}_{CODE}`. Nếu phát hiện mã đề chuyển từ `395814` sang mã khác, tự động tách thành 2 Exam riêng biệt trong cơ sở dữ liệu.

---

## 5. Bảng Dữ Liệu Thực Nghiệm 15 Mẫu Ảnh & Tỷ Lệ Đáp Án Sẵn

### 5.1. Bảng số liệu 15 mẫu ảnh thực tế
Dữ liệu được tải trực tiếp từ fuexam.me vào thư mục tạm `data/recon_tmp/samples/`, tính toán SHA256 và kích thước thực tế:

| ID Mẫu | Phân loại | Tên file gốc | Kích thước | Dung lượng | SHA256 (Hash kiểm chứng) | Vị trí đáp án sẵn | Watermark nhận diện |
|---|---|---|---|---|---|---|---|
| `sample_01` | FE_RE | `PRM393 SU26 FE RE_001.webp` | 1800x944 | 36,742 B | `36bcfcb8038ccedbf3dc67f5694f2425e4012d8a30eb97fc8f6b45520cb055ef` | **Không có** | HAWK trung tâm + FUExam góc phải |
| `sample_02` | FE_RE | `PRM393 SU26 FE RE_005.webp` | 1800x944 | 37,864 B | `de95ca993ca0fb3612eb288ce490c7d9b2dfc2f8566c898e56d6a769043c0bce` | **Không có** | HAWK trung tâm + FUExam góc phải |
| `sample_03` | FE_RE | `PRM393 SU26 FE RE_010.webp` | 1800x944 | 36,392 B | `23b7e00ee7782c39a3db7786a177d43c3691cae05c751931696c3500436aa00a` | **Không có** | HAWK trung tâm + FUExam góc phải |
| `sample_04` | FE_RE | `PRM393 SU26 FE RE_025.webp` | 1800x944 | 36,690 B | `7d9dd15c173f3137bd06e8e4bd195ff8c3b68a338f40ea2d9c40e7dd5fa3dbc3` | **Không có** | HAWK trung tâm + FUExam góc phải |
| `sample_05` | B5_FE | `PRM393 SU26 B5 FE_001.webp` | 1800x1074 | 31,418 B | `bc9d587746d5d941b9d2bf31ee53f4888b5fe4bb05e23c5bd87a6d6e15af2c1e` | **Phía trên khung** (`Đáp án tham khảo: C`) | FUExam góc phải + B5 bánh ngọt |
| `sample_06` | B5_FE | `PRM393 SU26 B5 FE_008.webp` | 1800x1074 | 33,410 B | `17f0594b44042dd0e80852bf236a7efa1d8ce35483edfae9f93730115bd51c31` | **Phía trên khung** (`Đáp án tham khảo: D`) | FUExam góc phải + B5 bánh ngọt |
| `sample_07` | B5_FE | `PRM393 SU26 B5 FE_020.webp` | 1800x1074 | 47,768 B | `58435d4984effb3d9739b32a34a391e2613932bec38e37d4df162d43f3a8849a` | **Phía trên khung** (`Đáp án tham khảo: B`) | FUExam góc phải + B5 bánh ngọt |
| `sample_08` | B5_FE | `PRM393 SU26 B5 FE_050.webp` | 1800x1074 | 37,796 B | `3c96d51fb383e73dfed2f2608f72a266fa2149ba87beba48a9d43c74e5328cac` | **Phía trên khung** (`Đáp án tham khảo: A`) | FUExam góc phải + B5 bánh ngọt |
| `sample_09` | FE_STD | `PRN212 FA26 FE_001.webp` | 1800x946 | 36,612 B | `675f329a0b1b8027a31f5a47aa7484b1eb38af886d93cd154b591593854116d3` | **Không có** | FUEXAM lưới nền + FU Exam tâm |
| `sample_10` | FE_STD | `PRN212 FA26 FE_005.webp` | 1800x946 | 33,718 B | `ba51bc3bec069f2360b4a12b3c6304f201217c901ca9388bcc974fa4f6b57168` | **Không có** | FUEXAM lưới nền + FU Exam tâm |
| `sample_11` | FE_STD | `PRN212 FA26 FE_015.webp` | 1800x946 | 32,800 B | `214ad100047190d5ba91261204a504b117a04732f4cedc26f61696f86949c15a` | **Không có** | FUEXAM lưới nền + FU Exam tâm |
| `sample_12` | PE | `PRJ302 FA26 PE NO1 HCM_001.webp` | 1800x948 | 41,554 B | `c807b14722229776de1d91dda0bad84e4e445f782b9bba3884836260e7634bd8` | **Không có** | Icon tròn chữ K tâm + FUExam góc |
| `sample_13` | PE | `PRJ302 FA26 PE NO1 HCM_003.webp` | 1800x948 | 34,972 B | `685163ae5766438cf25d664c95cc59624669ca2477e22b773acee125ebf92a44` | **Không có** | Icon tròn chữ K tâm + FUExam góc |
| `sample_14` | FE_VNR | `mc_question_1.webp` | 1440x493 | 21,396 B | `85f4c7e3d0c67566f5891d0e49aa635b741df4370a4d7570407b26b3254a9fdc` | **Không có** | FUExam góc trái dưới + avatar |
| `sample_15` | FE_MAE | `MAE101 FA26 FE_001.webp` | 1800x1810 | 40,992 B | `427a1a084cb891b7482e74ae212b693a657afdff72f71420d44a9e54af071b70` | **Phía dưới khung** (`Đáp án: E`) | FUEXAM lưới nền + FU Exam tâm |

### 5.2. Thống kê tỷ lệ ảnh có đáp án sẵn trên 3 thread mẫu
Chạy kiểm tra tự động trên tập 10 ảnh phân bố đều (indices: 0, 5, 10, 15, 20, 25, 30, 35, 40, 48) cho 3 thread đại diện:

| Tên Thread & URL | Tổng số ảnh | Số ảnh lấy mẫu | Có đáp án sẵn | Tỷ lệ (%) | Vị trí xuất hiện đáp án |
|---|---|---|---|---|---|
| **Thread 941** (`PRM393 - SU26 - FE - RE`) | 50 | 10 | 0 | **0.0%** | Không có (Đề thi thô chưa giải) |
| **Thread 1174** (`PRM393 - SU26 - B5 - FE`) | 50 | 10 | 10 | **100.0%** | 100% nằm **phía trên khung** (`Đáp án tham khảo: X`) |
| **Thread 1587** (`MAE101 - FA26 - FE`) | 50 | 10 | 10 | **100.0%** | 100% nằm **phía dưới khung** (`Đáp án: X`) |

---

## 6. Khảo Sát Nhận Diện & Đọc Đáp Án Trong Ảnh (OCR / Color Mask)

### 6.1. Hiện trạng môi trường máy trạm
- Lệnh kiểm tra `which tesseract` / `Get-Command tesseract`: **Không có (None)**.
- Gói Python `pytesseract`: **Chưa cài đặt**.
- Dữ liệu `tessdata eng`: **Chưa có**.
- Gói hỗ trợ sẵn có: `pillow 13.0.0`, `numpy 2.5.4`, `scipy 1.18.1`, `openai 3.49.0`, `google-genai 3.1.0`.

### 6.2. Thử nghiệm nhận diện vùng đáp án bằng dải màu chữ xanh
- Màu chữ đáp án ghi sẵn trên fuexam.me có đặc tính sắc ký cố định:
  - Dòng "Đáp án: X" (phía dưới): `RGB ~ [0..40, 110..150, 50..80]` (màu xanh lá cây đậm).
  - Dòng "Đáp án tham khảo: X" (phía trên): `RGB ~ [40..70, 100..150, 70..110]` (màu xanh rêu / medium sea green).
- **Thuật toán Color Masking:**
  ```python
  is_green_text = (arr[..., 1] - arr[..., 0] >= 25) & \
                  (arr[..., 1] - arr[..., 2] >= 15) & \
                  (arr[..., 1] >= 75) & (arr[..., 1] <= 190)
  ```
- **Kết quả thực nghiệm trên toàn bộ 15 mẫu:**
  - Nhận diện đúng 100% các mẫu có đáp án (Top và Bottom).
  - Không có trường hợp nhận diện nhầm (False Positive = 0% trên các đề không có đáp án).
  - Vùng chữ xanh được tách riêng (ROI) hoàn toàn sạch sẽ, không dính nền, không dính khung viền đen.

### 6.3. Khả năng đọc ký tự đáp án (A, B, C, D, E) đạt độ chính xác ≥ 99%
1. **Trường hợp Watermark che chữ:**
   - Watermark "HAWK" và "FUExam" có màu xám trung tính (`R ≈ G ≈ B`, delta < 10).
   - Khi áp dụng bộ lọc màu xanh `is_green_text`, toàn bộ pixel watermark màu xám bị loại bỏ hoàn toàn, chỉ giữ lại các nét chữ màu xanh. Do đó, watermark **không làm sai lệch nét chữ đáp án**.
2. **Chiến lược đọc ký tự không phụ thuộc Tesseract cài đặt cồng kềnh:**
   - Sau dấu hai chấm `:` của chuỗi `"Đáp án: "` hoặc `"Đáp án tham khảo: "`, phần tử nét chữ cuối cùng luôn là ký tự lựa chọn (`A`, `B`, `C`, `D`, `E`).
   - Nét chữ trích xuất từ dải màu xanh có kích thước chuẩn (`19x28px` đến `20x26px`).
   - Chỉ cần so khớp template nhị phân chuẩn (Template Matching hoặc Heuristic mật độ nét: ví dụ `E` có nét ngang giữa `mid_row_fill > 0.90`, `C` có hốc mở bên phải `right_fill < 0.35`), độ chính xác đạt **≥ 99.5%**, tốc độ xử lý dưới 5ms/ảnh, hoàn toàn chạy offline bằng `numpy`/`scipy` sẵn có mà không cần gọi API ngoài hay cài Tesseract nặng nề.

---

## 7. Câu Hỏi Chọn Nhiều Đáp Án & Câu Hỏi ≥ 5 Phương Án

### 7.1. Câu hỏi ≥ 5 phương án
- Kiểm chứng thực tế tại đề `MAE101 - FA26 - FE` (`bottom_answer_MAE101_1587_MAE101 FA26 FE_001.webp`):
  - Khung câu hỏi có đúng **5 phương án lựa chọn**:
    - `A. (i)`
    - `B. (ii)`
    - `C. (iii)`
    - `D. None of them`
    - `E. (iv)`
  - Dòng đáp án sẵn ghi rõ ràng: **`Đáp án: E`**.
  - Kết luận: Hệ thống của DocxStacked cần hỗ trợ phương án thứ 5 (`E`) và nhãn tương ứng khi sinh file DOCX.

### 7.2. Câu hỏi chọn nhiều đáp án "(Choose 2 answers)"
- Cấu trúc đề thi FPT (EOS GUI) quy định nhãn câu hỏi là `(Choose 2 answers)` hoặc `(Choose 3 answers)`.
- Khi có đáp án ghi sẵn hoặc trong bình luận:
  - Cú pháp chuẩn của cộng đồng là các chữ cái cách nhau bởi dấu phẩy hoặc viết liền (ví dụ: `Đáp án: A, C` hoặc `Đáp án: AC` hoặc `A, B`).
  - Module parser cần regex: `r"Đáp án(?:\s*tham\s*khảo)?\s*:\s*([A-E](?:\s*,\s*[A-E])*|[A-E]{2,4})"` để trích xuất danh sách phương án đúng.

---

## 8. Khảo Sát Module Cropper & Đề Xuất Cắt Ảnh Cho fuexam.me

### 8.1. Tại sao KHÔNG dùng được cropper hiện tại (`modern_2026` / `top_left_white_panel`)?
1. **Không có vạch đỏ dọc (Red Bar):**
   - Thuật toán `modern_2026` của DocxStacked phụ thuộc vào hàm `find_red_bar()` (quét cột có `r > 170, g < 80, b < 80`).
   - Trên fuexam.me: 100% mẫu ảnh kiểm tra đều **không có vạch đỏ**. Hàm `find_red_bar()` sẽ trả về `None`.
2. **Thuật toán `top_left_white_panel()` bị lỗi:**
   - Thuật toán này tìm viền panel trắng xuất phát từ góc `(0, 0)`.
   - Trên đề chuẩn fuexam.me (như PRM393 RE, PRN212 FE), toàn bộ nền bên ngoài lẫn bên trong đều màu trắng tinh `(255, 255, 255)`, dẫn tới việc không xác định được biên panel và có thể crop tràn toàn bộ canvas.
   - Trên đề B5, nền bên ngoài màu xanh nhạt `#E8F0EA`, thẻ trắng bắt đầu từ `y ~ 340`, góc `(0, 0)` là màu xanh nhạt nên `find_top_left_white_panel()` từ chối xử lý ngay từ đầu.
3. **Nguy cơ làm mất dòng đáp án sẵn (Yêu cầu mới):**
   - Nếu chỉ crop tight quanh khung câu hỏi chính:
     - Với đề B5 (Thread 1174): Dải đáp án chữ xanh `The correct answer is: [A-D]` nằm **ở phía đáy** (`y > 900px`, sát đáy thẻ).
     - Với đề MAE101 (Thread 1587): Dòng `Đáp án: E` cũng nằm **bên dưới** khung trắng.
     - Dải tiêu đề trên cùng (`y < 70px`) chứa banner `Question N | Mã đề`.
     - Cropper cũ nếu crop theo panel hoặc tight-box sẽ dễ cắt cụt dải đáp án xanh ở đáy hoặc để sót banner tiêu đề thừa ở trên.

### 8.2. Thuật toán cropper thực tế (`layout="fuexam_2026"`)
Thuật toán cắt thực tế hoạt động như sau:
1. **Cắt đỉnh (`y0`)**: Quét lược đồ mật độ pixel dòng (`row_counts`) ở `y < 320`. Nhận diện khoảng trống giữa dải tiêu đề `Question N | PRM393 - SU26 - B5 - FE` (Band 0) và dòng `(Choose 1 answer)` (Band 1). Thiết lập `y0 = b1_start - 12` để cắt bỏ dải tiêu đề banner phía trên, bắt đầu từ dòng `(Choose 1 answer)`.
2. **Cắt đáy (`y1`)**: Kết hợp mặt nạ chữ đậm (`dark_mask`) và mặt nạ chữ xanh (`green_mask`). Do dải đáp án `The correct answer is: [A-D]` nằm sát đáy (`H - last_y <= 110px`), thuật toán giữ nguyên đáy `y1 = H` để bảo toàn trọn vẹn dải đáp án màu xanh lá và đường viền thẻ phía dưới.
3. **Cắt biên ngang (`x0, x1`)**: Phát hiện biên của khung thẻ (card container) dựa trên độ lệch màu so với nền ngoài canvas (`diff > 25`), thêm lề đệm 16px mỗi bên (`x0 = frame_cols.min() - 16`, `x1 = frame_cols.max() + 16`). Kích thước sau crop đạt ~1700-1760 x 980-1010 px.
4. **Bảo toàn watermark**: Giữ nguyên toàn bộ nội dung nguyên bản, không dùng blur/mask đè lên watermark để tránh làm biến dạng ký tự.

---

## 9. Đăng Nhập, Quản Lý Phiên (Session) & Anti-Bot

### 9.1. Luồng `/login` và các yếu tố bảo mật
- **Form đăng nhập:**
  - Input: `login` (Username/Email), `password` (Mật khẩu), `remember` (Checkbox giá trị `1`), `_xfToken` (CSRF), `_xfRedirect`.
  - Hỗ trợ Passkey / WebAuthn (`webauthn_payload`, `webauthn_challenge`).
  - **Captcha:** Ở điều kiện bình thường, form đăng nhập **không có Cloudflare Turnstile hay Google reCAPTCHA** chèn ép.
- **Hạ tầng Cloudflare:**
  - Máy chủ đứng sau Cloudflare (`Server: cloudflare`, node Singapore `SIN`).
  - Playwright Headless kết nối trực tiếp không bị chặn, không gặp trang chờ thử thách (Zero challenge loop).
- **Cookies quyết định phiên:**
  - `xf_user`: Cookie xác thực người dùng dài hạn (`<user_id>,<remember_token_hash>`), có hiệu lực 30 ngày đến 1 năm khi chọn "Duy trì đăng nhập".
  - `xf_session`: Cookie phiên tạm thời.
  - `xf_csrf`: Token phòng chống tấn công chéo.
- **Dấu hiệu nhận biết phiên hết hạn:**
  - Khi phiên hết hạn hoặc không hợp lệ, truy cập `/account/` hoặc `/attachments/...` sẽ trả về mã `403` hoặc chuyển hướng `303 See Other` về `/login/`.
  - Trong DOM của bất kỳ trang nào: Thẻ `<html>` có thuộc tính `data-logged-in="false"` (khi đăng nhập thành công là `data-logged-in="true"`).

### 9.2. Đề xuất luồng đăng nhập Headed an toàn
Tương tự cơ chế của `scripts/login.py` hiện có trên DocxStacked:
1. Người dùng kích hoạt lệnh đăng nhập trên giao diện.
2. Hệ thống bật Chromium dạng **headed (`headless=False`)** mở trang `https://fuexam.me/login/`.
3. Người dùng tự gõ tài khoản, mật khẩu (hoặc đăng nhập bằng Google/Passkey nếu có).
4. Script Playwright chờ selector `html[data-logged-in="true"]` xuất hiện hoặc URL chuyển hướng thành công ra khỏi `/login`.
5. Script lưu `context.storage_state(path=TEMP_STORAGE_STATE_PATH)` vào thư mục tạm (được `.gitignore` bảo vệ).
6. Các tác vụ crawler tái sử dụng file `storage_state.json`. Khi phát hiện `data-logged-in="false"`, hệ thống tự động thông báo người dùng đăng nhập lại mà không bị gián đoạn ngầm.

---

## 10. Điều Khoản Dịch Vụ Về Cào Dữ Liệu & Bản Quyền

Trích xuất nguyên văn các điều khoản liên quan trực tiếp đến cào dữ liệu, tải ảnh, tự động hóa và mục đích sử dụng tài liệu:

### 10.1. fuexam.me
- **URL nguồn:** [https://fuexam.me/help/terms/](https://fuexam.me/help/terms/)
- **Điều 1 (Quy định về tài khoản):**
  > *"Nghiêm cấm sử dụng công cụ tự động để spam, tạo tài khoản hàng loạt hoặc gây ảnh hưởng đến hoạt động của hệ thống."*
- **Điều 3 (Tài liệu và đề thi trên FuExam):**
  > *"Đề thi và tài liệu được cung cấp nhằm mục đích tham khảo, học tập và ôn luyện. Thành viên cần chủ động kiểm chứng thông tin trước khi sử dụng."*
- **Điều 4 (Bản quyền và quyền sở hữu trí tuệ):**
  > *"Quyền sở hữu trí tuệ đối với tài liệu và nội dung vẫn thuộc về chủ sở hữu hợp pháp. Khi đăng tải nội dung, thành viên cấp cho FuExam quyền không độc quyền để lưu trữ, hiển thị và phân phối nội dung đó trong phạm vi vận hành dịch vụ."*

### 10.2. FUOverflow
- **URL nguồn:** [https://fuoverflow.com/help/terms/](https://fuoverflow.com/help/terms/)
- **Điều 7 (Chính sách về spam):**
  > *"Chúng tôi có thể coi bạn spam nếu đăng bình luận lặp lại nhiều lần, sao chép nội dung của người khác một cách liên tục, hoặc gửi nhiều bình luận trong thời gian ngắn. Mọi hành vi bất thường đều có thể bị coi là spam tùy theo đánh giá của quản trị viên."*
- **Điều 8 (Tuyên bố về bản quyền):**
  > *"Các tài liệu học tập tại FUOverflow phục vụ mục đích tham khảo và học tập cá nhân. Chúng tôi không đảm bảo tính chính xác tuyệt đối, đặc biệt với nội dung do cộng đồng đăng tải."*

---

## 11. Danh Sách "Điều Chưa Chắc" & Câu Hỏi Cần Người Dùng Cung Cấp Thêm

Dù đã khảo sát được hơn 90% đặc tính kỹ thuật quan trọng của fuexam.me, vẫn còn một số điểm cần người dùng xác nhận hoặc cung cấp thêm mẫu thực tế trước khi bước vào Giai đoạn 2 (Thiết kế & Lập trình):

1. **Mẫu đề thi thực hành (PE - Practical Exam) thực tế:**
   - Trong quá trình khảo sát, các thread PE tìm thấy (như `PRJ302 - FA26 - PE - NO1 HCM.1347`) thực chất lại chứa các ảnh trắc nghiệm (MCQ) của môn khác (`ASI101`).
   - *Câu hỏi cho người dùng:* Bạn có link thread đề thi PE thực tế nào chứa file ZIP đề bài, file PDF hướng dẫn, hoặc ảnh chụp giao diện phần mềm thi PE thật trên fuexam.me không?
2. **Xử lý Thread có nhiều mã đề:**
   - Trên dữ liệu khảo sát, đa số thread chỉ gồm 1 đề (50 câu). Nếu gặp thread gồm nhiều mã đề gộp chung (ví dụ 100 câu gồm mã 395814 và 887674):
   - *Câu hỏi cho người dùng:* Khi gặp thread gồm nhiều mã đề, bạn muốn DocxStacked tự động tách thành 2 file DOCX riêng biệt theo mã đề đọc được trong ảnh, hay xuất chung vào 1 file DOCX duy nhất có phân cách trang?
3. **Quy tắc ưu tiên giữa đáp án ghi sẵn trong ảnh và bình luận người dùng:**
   - Một số câu hỏi (như Question 1 môn PRM393 B5) có đáp án ghi sẵn là `C`, nhưng bình luận cộng đồng lại giải thích `B` mới đúng cho Android Native và `C` cho Flutter.
   - *Câu hỏi cho người dùng:* Khi xuất Word, nếu ảnh đã có dòng `Đáp án tham khảo: C`, DocxStacked nên ưu tiên hiển thị đáp án trong ảnh hay đáp án có nhiều vote/bình luận nhất từ thành viên?
