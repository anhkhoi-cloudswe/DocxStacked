# FUOverflow Site Notes (Discovery Phase 0)

> Tài liệu khảo sát cấu trúc thực tế của https://fuoverflow.com/ phục vụ crawler và parser.  
> Được thực hiện và xác minh trong Phase 0 qua headed browser, network inspection và phân tích DOM fixtures.

---

## 1. Nền tảng & Xác thực (Authentication & Bot Protection)

- **Nền tảng CMS:** **XenForo 2.3** (`data-xf="2.3"`), template hệ thống `forum_list`, `forum_view`, `thread_view`.
- **Yêu cầu đăng nhập:**
  - **Trang chủ, danh sách môn, danh sách đề:** Hoàn toàn **PUBLIC** (không cần đăng nhập).
  - **Trang chi tiết đề (xem danh sách câu hỏi và tải ảnh):** Hoàn toàn **PUBLIC** (Status 200).
  - **Trang xem bình luận câu hỏi (`/media/...`):** **BẮT BUỘC ĐĂNG NHẬP** (Nếu chưa đăng nhập sẽ nhận HTTP 403 và bị redirect về `/login/`).
- **Phương thức đăng nhập:**
  - Google OAuth (`/register/connected-accounts/google/?setup=1`) — thường dùng tài khoản email sinh viên FPT (`@fpt.edu.vn`).
  - Tài khoản thường XenForo (Username / Password).
  - Passkey.
- **Cơ chế chống bot:**
  - Cloudflare CDN / WAF (`server: cloudflare`, `cf-cache-status: DYNAMIC`).
  - Raw HTTP client không có header/cookie đầy đủ bị chặn 403 ở các route nhạy cảm.
  - Sử dụng Playwright Chromium (`launch_persistent_context` lưu tại `data/browser_profile/`) hoạt động ổn định, không bị chặn.

---

## 2. Cấu trúc URL & Điều hướng

| Mục đích | URL Pattern | Ví dụ thực tế | Quyền truy cập |
|---|---|---|---|
| Trang chủ | `https://fuoverflow.com/` | `https://fuoverflow.com/` | Public |
| Danh mục môn học | `https://fuoverflow.com/categories/subjects/` | `https://fuoverflow.com/categories/subjects/` | Public |
| Danh sách đề của 1 môn | `https://fuoverflow.com/forums/{SUBJECT_CODE}/` | `https://fuoverflow.com/forums/CSD202/`<br>`https://fuoverflow.com/forums/PRN212/` | Public |
| Chi tiết 1 đề thi | `https://fuoverflow.com/threads/{slug}.{thread_id}/` | `https://fuoverflow.com/threads/csd202-su26-fe.7086/`<br>`https://fuoverflow.com/threads/prn212-su26-b5-fe.7422/` | Public |
| Chi tiết câu hỏi & bình luận | `https://fuoverflow.com/media/{slug}.{media_id}/` | `https://fuoverflow.com/media/q1-webp.134314/` | **Cần đăng nhập** |

---

## 3. Phân biệt FE vs PE

Site phân loại cực kỳ rõ ràng qua 3 tiêu chí:
1. **Thread Label / Prefix:**
   - FE: `<span class="label label--...">Đề Thi FE</span>`
   - PE: `<span class="label label--...">Đề Thi PE</span>`
   - Ngoài ra có các nhãn phụ: `Đề Thi PT`, `Đề Thi Quiz`, `Đề Thi RE` (thi lại).
2. **Slug / Tiêu đề:**
   - Chứa `-fe.` hoặc `FE` đối với đề Final Exam.
   - Chứa `-pe-` hoặc `PE` đối với đề Practical Exam.
3. **Nội dung đính kèm:**
   - **FE:** Danh sách ~50 file ảnh câu hỏi (`Q1.webp` .. `Q50.webp`) trong XenForo Media Gallery.
   - **PE:** Thường đính kèm file nén `material_*.zip` và đề bài `paper.pdf` (hoặc ảnh chụp đề thực hành).

---

## 4. Cấu trúc Hiển thị Đề & Câu hỏi (FE)

- **Phân trang:** Toàn bộ câu hỏi nằm trong **bài viết đầu tiên** (`article.message:first-of-type`) của thread. Không phân trang giữa các câu hỏi trong đề.
- **Vị trí câu hỏi:** Nằm trong khối đính kèm:
  ```css
  section.message-attachments ul.attachmentList li.file
  ```
- **Mỗi câu hỏi (`li.file`):**
  - **Tên câu:** `.file-name` (chứa `Q1.webp`, `Q2.webp`...)
  - **Ảnh câu hỏi:** `img[src*="data.fuoverflow.com/attachments/"]` (hoặc link thumbnail/full size `a.file-preview`).
  - **Ảnh có thuộc tính `loading="lazy"`:** Cần đảm bảo ảnh đã load (`naturalWidth > 0`).
  - **Link tới phần bình luận:** Nằm trong `data-lb-caption-extra-html` hoặc `data-lb-sidebar-href` trỏ tới `/media/q{idx}-webp.{media_id}/`.

---

## 5. Cấu trúc Bình luận & Thảo luận (Comments - Đã xác minh Phase 0.5)

- Được quản lý bởi **XenForo Media Gallery (XFMG)** tại `/media/{slug}.{media_id}/`.
- **Cơ chế xác thực xem comment**: Bắt buộc đăng nhập (`data-logged-in="true"`). Đã lưu phiên đăng nhập bền vững vào `data/browser_profile/`.
- **Ánh xạ từ câu hỏi thread (`Q{n}.webp`) -> `media_id`**:
  - Tại bài viết thread (`/threads/{slug}.{thread_id}/`), mỗi câu hỏi nằm trong `li.file.file--linked`.
  - Thẻ `a.file-preview` chứa thuộc tính `data-lb-sidebar-href="/media/{slug}.{media_id}/?lightbox=1"`.
  - Regex trích xuất media_id: `/media/[^.]+\.(\d+)/`.
- **Cấu trúc DOM bình luận trong trang media**:
  - Mỗi comment là một node: `.message--comment`, `.message--simple`, `.js-comment`.
  - Tác giả comment: `.message-name .username`, `.comment-author`.
  - Nội dung comment: `.message-body .bbWrapper` (chứa text sinh viên thảo luận đáp án: `a`, `b`, `c`, `d`, giải thích).
  - Thời gian comment: `time[datetime]` (ISO 8601, vd `2026-08-12T07:08:55+0700`).
- **Cấu trúc Reply & Trích dẫn (Nested / Quotes)**:
  - XenForo XFMG không phân cấp DOM tree dạng lồng thẻ div cha con sâu vô tận.
  - Khi sinh viên reply một comment: hệ thống sinh block trích dẫn BBCode:
    ```html
    <blockquote class="bbCodeBlock bbCodeBlock--quote" data-quote="AuthorName">
      <div class="bbCodeBlock-title"><a href="/media/comments/{comment_id}/">Author said:</a></div>
      <div class="bbCodeBlock-content">...nội dung được quote...</div>
    </blockquote>
    ```
  - Nút reply trên từng comment: `a.actionBar-action--reply` trỏ tới `/media/media-comments/{media_slug}.{media_id}/comment?quote={comment_id}`.
- **Cách lấy số Reaction / Upvote**:
  - Khi comment có phản ứng (like/upvote): xuất hiện container `.reactionsBar.js-reactionsList.is-active`.
  - Danh sách icon phản ứng: `.reaction-image` (Like, Love, Haha...).
  - Tổng số vote: link `.reactionsBar-linkTotal` hoặc text `.reactionsBar-link` (vd `5 người khác` hoặc link popup danh sách người reaction `/media/comments/{comment_id}/reactions`).
- **Phân trang / Tải thêm bình luận (Pagination / Load More)**:
  - Nếu số comment ≤ 20: render đầy đủ trong SSR HTML.
  - Khi vượt quá giới hạn trang: XenForo hiển thị cụm phân trang `.pageNav` với nút `.pageNav-jump--next` hoặc `.js-loadMore`.
  - Bản AJAX (`X-Requested-With: XMLHttpRequest` tới `?lightbox=1`): trả về template HTML fragment `xfmg_media_lightbox_sidebar` chứa toàn bộ danh sách comment phục vụ lightbox sidebar.
- **Cơ chế tải ảnh đề thi chất lượng cao (CDN vs Direct)**:
  - **Ảnh thumbnail**: `https://data.fuoverflow.com/xfmg/thumbnail/...` -> tải trực tiếp **KHÔNG CẦN COOKIE** (HTTP 200).
  - **Ảnh full-res**: thẻ `img.js-mediaImage` có src `/media/{slug}.{media_id}/full?fuo_h={hash}&fuo_e={expiry}` -> tải qua host `fuoverflow.com` **CẦN SESSION/COOKIE ĐÃ ĐĂNG NHẬP** (Nếu không có cookie sẽ nhận 403 Forbidden).

---

## 6. Đánh giá API JSON nội bộ & AJAX Fragment

- Trang web là **XenForo 2.3 SSR** thuần (PHP sinh mã HTML ở server), không phải SPA React/Next.js gọi REST API lấy JSON.
- XenForo hỗ trợ request AJAX fragment khi gửi kèm header `X-Requested-With: XMLHttpRequest` (ví dụ `?lightbox=1` trả về HTML sidebar đầy đủ comment).
- **Kết luận kiến trúc crawler:** Sử dụng Playwright Persistent Context:
  1. Quét danh sách câu hỏi đề thi và link media từ thread view.
  2. Dùng context đã đăng nhập để tải trực tiếp ảnh full-res (`/media/.../full`) và nạp HTML comment.
  3. Lưu raw HTML và ảnh vào `data/raw/` phục vụ parsing offline.

---

## 7. Danh sách Fixtures đã lưu

### Fixtures thô (trong `data/fixtures/` - đã gitignore):
| File Fixture | Mục đích / Nội dung |
|---|---|
| `sample_subject_csd202.html` | Trang môn CSD202 (danh sách thread đề thi FE và PE) |
| `sample_thread_fe_csd202.html` | Chi tiết đề FE CSD202 (50 câu hỏi đính kèm XFMG) |
| `sample_thread_fe_prn212.html` | Chi tiết đề FE PRN212 (50 câu hỏi đính kèm XFMG) |
| `sample_thread_pe_csd202.html` | Chi tiết đề PE CSD202 (file nén material và PDF) |
| `raw/media_q11-webp_137454_full.html` & `_ajax.html` & `.png` | Media câu 11 môn VNR202 (14 bình luận, reaction, reply) |
| `raw/media_q35-webp_130984_full.html` & `_ajax.html` & `.png` | Media câu 35 môn SWD392 (9 bình luận) |
| `raw/media_q36-webp_130985_full.html` & `_ajax.html` & `.png` | Media câu 36 môn SWD392 (8 bình luận) |
| `raw/media_q1-webp_134314_full.html` & `_ajax.html` & `.png` | Media câu 1 môn CSD202 (2 bình luận) |
| `raw/media_q2-webp_134315_full.html` & `_ajax.html` & `.png` | Media câu 2 môn CSD202 (2 bình luận) |

### Fixtures sạch dùng cho Unit Test (trong `backend/tests/fixtures/`):
- `media_q11-webp_137454_clean.html` (đã xóa token, ẩn danh tên người dùng)
- `media_q35-webp_130984_clean.html`
- `media_q36-webp_130985_clean.html`
- `media_q1-webp_134314_clean.html`
- `media_q2-webp_134315_clean.html`