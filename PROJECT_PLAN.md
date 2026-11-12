# FUOverflow Exam Compiler — Project Plan (from scratch)

> Dán toàn bộ file này vào Antigravity. Bắt đầu bằng **Phase 0 (Discovery)** trước khi code bất cứ thứ gì, vì chưa ai xác nhận được cấu trúc DOM thật của site (site có bot-detection, có thể cần đăng nhập).

---

## 0. Prompt mở đầu cho Antigravity

```
Bạn là senior engineer. Hãy đọc PROJECT_PLAN.md và làm theo từng phase.
Quy tắc:
1. Bắt đầu bằng Phase 0: chỉ khảo sát site, KHÔNG viết code production.
   Cấu trúc repo: monorepo `backend/` (FastAPI, modular monolith, 2 process API + Worker) và `frontend/` (React + Vite + TS). Đọc mục 9–11 trước khi dựng khung dự án.
   Giao diện phải theo mục 10 (Design brief), tuyệt đối không dùng style "AI template" mặc định.
2. Sau mỗi phase: tóm tắt kết quả, chạy test, rồi dừng chờ tôi duyệt.
3. Mọi selector/URL phải nằm trong file config (selectors.yaml), không hardcode.
4. Ưu tiên lưu raw data (ảnh, HTML comment) để có thể parse lại không cần crawl lại.
```

---

## 1. Mục tiêu

Tool web riêng (local) cho phép:
1. Chọn **môn học** (1 hoặc nhiều) trên https://fuoverflow.com/.
2. Chọn loại thi: **FE** hoặc **PE**.
3. Chọn số đề cần soạn (**mặc định 4, cấu hình được, tối thiểu 1, khuyến nghị ≥ 4**).
4. Tool tự động:
   - Vào từng đề, chụp ảnh từng câu hỏi.
   - **FE**: đọc comment của người dùng cho từng câu → bỏ phiếu theo số đông → xác định đáp án (A/B/C/D, hỗ trợ 1 đáp án hoặc nhiều đáp án).
   - **PE**: chỉ lưu ảnh đề, không tìm đáp án.
5. Xuất file **.docx**: mỗi câu = 1 ảnh + đáp án (FE) + độ tin cậy.

---

## 2. Quyết định kỹ thuật

| Hạng mục | Lựa chọn | Lý do |
|---|---|---|
| Ngôn ngữ | Python 3.11+ | Hệ sinh thái crawl + docx tốt |
| Browser automation | **Playwright** (Chromium, `launch_persistent_context`) | Chụp element, đăng nhập 1 lần dùng lại, headed mode qua được bot-detection nhẹ |
| Backend API | **FastAPI** (Python) | Nhẹ, có SSE để đẩy tiến trình realtime, tự sinh OpenAPI |
| Frontend | **React + Vite + TypeScript**, Tailwind + Radix primitives (KHÔNG dùng shadcn nguyên bản) | Tách riêng deploy tĩnh lên CDN; tự chủ giao diện (xem mục 10) |
| Data fetching FE | TanStack Query + `openapi-typescript` sinh type từ OpenAPI của backend | Type-safe, đồng bộ contract |
| Worker | Process riêng (`apps/backend/app/worker.py`) lấy job từ bảng `jobs` trong DB | Không cần Celery/Redis; tách được khi deploy |
| DB | **SQLite** khi dev → **Postgres** (Neon/Supabase free) khi deploy, dùng SQLAlchemy + Alembic | Hosting free thường có ổ đĩa tạm (mất file khi restart) |
| Lưu file (ảnh, docx) | Local `data/` khi dev → **Cloudflare R2** (S3-compatible, free 10GB) khi deploy | Qua interface `Storage` để đổi backend không sửa logic |
| Xuất Word | `python-docx` | Chèn ảnh, định dạng ổn định |
| OCR (tuỳ chọn) | Tesseract hoặc vision-LLM | Phát hiện "chọn 1" hay "chọn nhiều" từ ảnh |
| Dedupe ảnh | `imagehash` (pHash) | Gộp câu trùng giữa các đề |
| Config | `config.yaml` + `selectors.yaml` | Sửa không cần đụng code |

> Lưu ý: môi trường hiện tại có thể không cho cài package. Antigravity chạy trên máy bạn nên cứ `pip install` + `playwright install chromium` bình thường.

---

## 3. Kiến trúc

Monorepo, tách rõ `backend/` và `frontend/`. Backend là **modular monolith**: một codebase, các module tách bạch, chạy thành 2 process (API + Worker). Xem lý do ở mục 9.

```
<repo-name>/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                  # FastAPI entry (API process)
│  │  ├─ worker.py                # Worker entry (crawl + analyze + export)
│  │  ├─ api/                     # routers: subjects, jobs, exports, auth, health
│  │  ├─ schemas/                 # Pydantic models (request/response)
│  │  ├─ core/
│  │  │  ├─ config.py             # pydantic-settings, đọc env
│  │  │  ├─ security.py           # auth, CORS, rate limit API
│  │  │  └─ logging.py
│  │  ├─ modules/
│  │  │  ├─ crawler/              # browser.py, subjects.py, exams.py, questions.py, comments.py
│  │  │  ├─ analysis/             # parser.py, voting.py, qtype.py, dedupe.py
│  │  │  ├─ export/               # docx_builder.py (+ pdf, json tuỳ chọn)
│  │  │  └─ jobs/                 # orchestration, resume, trạng thái job
│  │  ├─ storage/                 # interface Storage + local.py + r2.py
│  │  └─ db/                      # models.py, session.py, migrations/ (Alembic)
│  ├─ config/                     # config.yaml, selectors.yaml
│  ├─ tests/ (unit, integration, fixtures/)
│  ├─ Dockerfile                  # base image Playwright cho worker
│  ├─ pyproject.toml
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ app/                     # router, providers, layout
│  │  ├─ pages/                   # Subjects, Configure, JobProgress, Results, Review
│  │  ├─ features/                # subject-picker, job-stream (SSE), answer-review, ...
│  │  ├─ components/ui/           # component nền tự viết theo design system
│  │  ├─ lib/                     # api client (sinh từ OpenAPI), utils
│  │  └─ styles/                  # tokens.css (màu, font, spacing), global.css
│  ├─ public/
│  ├─ index.html
│  ├─ vite.config.ts
│  ├─ package.json
│  └─ .env.example
├─ data/                          # CHỈ dùng local/dev, gitignore toàn bộ
│  ├─ browser_profile/            # cookie đăng nhập
│  ├─ raw/{subject}/{exam}/       # ảnh + html comment gốc
│  └─ output/                     # file .docx
├─ docs/                          # site_notes.md, architecture.md, design-brief.md
├─ .github/workflows/             # ci.yml, deploy-frontend.yml, deploy-backend.yml
├─ docker-compose.yml             # dev: api + worker + postgres
├─ .gitignore
└─ README.md
```

---

## 4. Các Phase

### Phase 0 — Discovery (BẮT BUỘC làm đầu tiên)
Mục tiêu: hiểu site thật, không đoán.
- Viết script `scripts/discover.py` mở Playwright **headed**, cho tôi đăng nhập thủ công, lưu profile.
- Khảo sát và ghi vào `docs/site_notes.md`:
  - Có cần đăng nhập không? Có Cloudflare/captcha không?
  - URL pattern: trang môn, trang danh sách đề, trang 1 đề, trang 1 câu.
  - Một đề hiển thị thế nào: tất cả câu trên 1 trang, hay phân trang/next?
  - Câu hỏi là `<img>` hay text? Có lazy-load không?
  - Comment: load sẵn hay "xem thêm"/phân trang/infinite scroll? Có upvote/like không? Comment lồng nhau (reply) không?
  - Phân biệt FE vs PE ở đâu (tag, danh mục, tên đề)?
  - Có API JSON nội bộ (xem tab Network) để dùng thay vì parse DOM không? Nếu có thì ưu tiên.
- Chụp 3–5 trang mẫu (HTML lưu lại) làm fixture cho test.
- Điền `selectors.yaml` ban đầu.
- **Deliverable**: `site_notes.md` + fixtures + `selectors.yaml`. Dừng lại chờ duyệt.

### Phase 1 — Nền tảng
- Khởi tạo project, `pyproject.toml`, logging, config loader.
- `browser.py`: persistent context, hàm `ensure_logged_in()` (nếu chưa login → mở headed, chờ tôi đăng nhập, rồi lưu).
- Rate limiter: delay ngẫu nhiên 1.5–4s giữa request, tối đa N request song song = 1.
- DB models: `Subject`, `Exam(type FE/PE, term, url)`, `Question(index, image_path, phash, qtype)`, `Comment(raw_text, votes, author_hash)`, `Answer(question_id, answer_set, confidence, status)`, `Job`.

### Phase 2 — Crawl danh sách
- `subjects.py`: lấy toàn bộ môn → cache DB.
- `exams.py`: với môn đã chọn, lấy danh sách đề FE / PE, sắp xếp **mới nhất trước**, lấy `N` đề theo config (mặc định 4).
- Nếu số đề có sẵn < N → vẫn chạy, cảnh báo rõ trên UI.

### Phase 3 — Chụp câu hỏi (FE) & Tải file đính kèm (PE)
- **FE**: Với mỗi đề FE: duyệt từng câu, ưu tiên tải ảnh gốc từ CDN `data.fuoverflow.com`, chỉ screenshot khi tải lỗi. Số câu mỗi đề lấy theo thực tế, không hardcode 50. Lưu `data/raw/{subject}/{exam}/q{idx:03d}.webp` (hoặc `.png`), tính pHash. Resume: câu nào đã có file + DB thì bỏ qua.
- **PE (Quy tắc lưu PE - Phương án b đã chốt)**:
  - **KHÔNG render PDF thành ảnh, KHÔNG tạo docx cho PE.**
  - Với mỗi đề PE: crawler tải toàn bộ file đính kèm của bài đăng gốc (`paper.pdf`, `material_*.zip`, và mọi ảnh nếu có).
  - Lưu tất cả vào **MỘT thư mục** đặt tên theo tiêu đề bài đăng của người post (ví dụ: `data/output/{subject}/{post_title}/`).
  - Không crawl comment, không phân tích đáp án cho đề PE.

### Phase 4 — Thu thập comment (chỉ FE)
- Mở hết comment (click "xem thêm", scroll, phân trang) cho từng câu.
- Lưu **raw text + số upvote + thời gian + có phải reply không**. Ẩn danh hoá tên tác giả (hash) nếu lưu.
- Lưu thêm HTML comment thô vào `raw/` để parse lại về sau.

### Phase 5 — Phân tích đáp án (trọng tâm)

**5.1 Parse comment → tập đáp án** (`parser.py`)
- Chuẩn hoá: lowercase, bỏ dấu câu thừa, unicode normalize.
- Nhận diện các dạng thường gặp:
  - `A`, `a`, `đáp án B`, `dap an c`, `ans: D`, `chọn A`, `A đúng`, `câu này B`
  - Nhiều đáp án: `A,C`, `A C`, `AC`, `A và C`, `A+C`, `a/c`, `A, B, D`
  - Phủ định / sửa sai: `không phải A`, `sai rồi, là B`, `A sai` → loại hoặc giảm trọng số
  - Câu hỏi/nghi vấn: `có đúng A không?`, `ai biết đáp án` → **bỏ qua**
  - Reply đồng tình: `+1`, `đúng`, `chuẩn`, `ok` → cộng phiếu cho đáp án của comment cha
- Regex trước; comment mơ hồ → đánh dấu `ambiguous`. **Tuỳ chọn**: gọi LLM nhỏ để phân loại các comment ambiguous (bật/tắt trong config, mặc định tắt).

**5.2 Bỏ phiếu** (`voting.py`)
- Mỗi comment hợp lệ = 1 phiếu, trọng số `w = 1 + log2(1 + upvotes)` (cấu hình được).
- **Câu 1 đáp án**: chọn đáp án có tổng trọng số cao nhất.
- **Câu nhiều đáp án**: coi mỗi lựa chọn (A/B/C/D) là 1 ô độc lập; một lựa chọn được tính là đúng nếu tỷ lệ phiếu chứa nó ≥ ngưỡng (mặc định 50% số comment hợp lệ). Ngoài ra thử so khớp nguyên tập (vd `{A,C}`) xuất hiện nhiều nhất.
- Tính **confidence** = (phiếu thắng) / (tổng phiếu), kèm số comment hợp lệ.
- Trạng thái: `confident` (≥ 0.7 và ≥ 3 comment), `weak` (0.5–0.7 hoặc ít comment), `conflict` (top-2 sát nhau), `no_data` (không có comment).

**5.3 Xác định loại câu (single/multiple)** (`qtype.py`)
- Ưu tiên: OCR ảnh tìm cụm "Select one", "Select all that apply", "Choose two", "(Choose 2)"… (config danh sách regex).
- Nếu không OCR được: suy từ comment (đa số comment có nhiều đáp án → multiple).
- Lưu `qtype` + nguồn suy luận.

**5.4 Dedupe giữa các đề**
- Các đề FE thường lặp câu. Dùng pHash (ngưỡng Hamming ≤ 6) gộp câu trùng, **gộp luôn phiếu comment** → độ tin cậy cao hơn.
- Config: `dedupe: true/false`. Nếu bật, trong docx ghi "xuất hiện ở đề 1, 3".

### Phase 6 — Xuất Word
- `docx_builder.py` dùng `python-docx`.
- Cấu trúc file:
  - Trang bìa: Tên môn, loại thi, số đề, ngày tạo, nguồn.
  - Mục lục (heading để Word tự tạo TOC).
  - Mỗi đề = 1 Heading 1; mỗi câu = Heading 2 `Câu {n}` + ảnh (scale vừa khổ A4, giữ tỷ lệ) + dòng **Đáp án: A** hoặc **Đáp án: A, C** + dòng nhỏ `(tin cậy 85% — 12 comment)`.
  - Câu `weak/conflict/no_data` đánh dấu màu (vàng/đỏ) + ghi "cần kiểm tra lại".
  - **PE**: chỉ ảnh, không có dòng đáp án, không crawl comment (bỏ qua Phase 4–5).
- Phụ lục cuối file: bảng tổng hợp đáp án nhanh (Câu → Đáp án).
- Tên file: `{MaMon}_{FE|PE}_{N}de_{YYYYMMDD}.docx`.
- Tuỳ chọn thêm xuất PDF (qua LibreOffice) và JSON dữ liệu thô.

### Phase 7 — Frontend (React, thư mục `frontend/`)
- **Bắt buộc đọc mục 10 (Design brief) trước khi viết dòng CSS đầu tiên.** Làm design tokens trước, component sau.
- Kết nối backend qua REST + SSE; type sinh tự động từ OpenAPI.
- Trang 1: ô tìm kiếm + danh sách môn (checkbox nhiều môn).
- Trang 2 (cấu hình): loại thi FE/PE, số đề (mặc định 4), tuỳ chọn dedupe, ngưỡng tin cậy, có dùng LLM phân loại comment không.
- Trang 3 (tiến trình): SSE hiển thị `Môn X → Đề 2/4 → Câu 17/50`, log realtime, nút Pause/Cancel/Resume.
- Trang 4 (kết quả): danh sách file .docx để tải, thống kê số câu `confident/weak/conflict`, **màn hình review thủ công** để sửa đáp án trước khi xuất lại.
- Nút "Đăng nhập lại" khi session hết hạn.

### Phase 8 — Độ bền & chất lượng
- Retry có backoff, timeout từng bước, phát hiện bị chặn/captcha → tạm dừng và báo UI thay vì spam.
- Resume job sau crash (dựa vào DB + file raw).
- Unit test: parser (≥ 60 mẫu comment thật), voting, qtype, docx_builder (mở lại file kiểm tra số ảnh).
- Integration test dùng HTML fixture từ Phase 0 (không gọi mạng).
- Logging có cấu trúc, file log xoay vòng.

### Phase 9 — Đóng gói & CI/CD
- `README.md`: cài đặt, đăng nhập lần đầu, chạy, config.
- `docker-compose.yml` cho dev (api + worker + postgres); script `run.bat` / `run.sh`.
- `.gitignore` cho `data/`, `.env*`, `browser_profile/`.
- GitHub Actions: lint + test cho cả hai phía, build, deploy (chi tiết mục 11).

### Phase 10 — Deploy (sau khi bản local chạy ổn)
- Làm theo mục 11. Chỉ deploy sau khi đã chốt quyết định về phạm vi công khai (mục 11.4).

---

## 5. Config mẫu (`config.yaml`)

```yaml
exam:
  default_count: 4        # số đề mặc định, người dùng chỉnh trên UI
  min_count: 1
  order: newest_first
crawl:
  delay_seconds: [1.5, 4.0]
  concurrency: 1
  headless: false          # để false giúp qua bot-detection và đăng nhập
  max_retries: 3
analysis:
  vote_weight: log_upvotes
  multi_choice_threshold: 0.5
  confident_min_ratio: 0.7
  confident_min_comments: 3
  use_llm_for_ambiguous: false
  dedupe: true
  dedupe_hamming: 6
export:
  formats: [docx]          # thêm pdf, json nếu cần
  image_width_cm: 16
  highlight_low_confidence: true
```

---

## 6. Rủi ro & cách xử lý

| Rủi ro | Xử lý |
|---|---|
| Site chặn bot (đã thấy khi thử truy cập tự động) | Playwright headed + profile đăng nhập thật; delay ngẫu nhiên; nếu có API nội bộ ổn định thì dùng; dừng khi gặp captcha |
| Cần đăng nhập (tài khoản sinh viên) | Đăng nhập thủ công 1 lần, lưu persistent profile; **không lưu mật khẩu trong code** |
| DOM đổi | Selector tách riêng `selectors.yaml`; test bằng fixture; log rõ khi selector không khớp |
| Comment nhiễu, sai đáp án | Bỏ phiếu có trọng số + confidence + đánh dấu cần kiểm tra + màn hình review thủ công |
| Câu nhiều đáp án khó parse (`AC`, `A,C`) | Parser riêng + test case dày; fallback LLM tuỳ chọn |
| Ảnh lazy-load, chụp thiếu | Chờ `naturalWidth`, scroll vào view, kiểm tra kích thước ảnh tối thiểu |
| Crawl quá nhanh → bị khoá tài khoản | Giới hạn tốc độ, 1 luồng, cache triệt để, không crawl lại dữ liệu đã có |
| Pháp lý / điều khoản | Chỉ dùng cá nhân, tốc độ thấp, không công khai lại nội dung; kiểm tra ToS của site trước khi dùng |
| Độ chính xác đáp án | Đây là đáp án tham khảo từ cộng đồng, không phải đáp án chính thức — ghi rõ trong file xuất |

---

## 7. Tiêu chí hoàn thành (Definition of Done)

- [ ] Chọn môn + FE/PE + số đề trên UI, bấm chạy, nhận được file .docx không cần thao tác thêm.
- [ ] FE: mỗi câu có ảnh + đáp án + confidence; câu nhiều đáp án hiển thị đúng `A, C`.
- [ ] PE: chỉ có ảnh, không crawl comment.
- [ ] Đổi số đề (vd 6) hoạt động; thiếu đề thì cảnh báo thay vì lỗi.
- [ ] Dừng giữa chừng rồi Resume không crawl lại phần đã xong.
- [ ] Parser đạt ≥ 90% đúng trên bộ 60+ comment mẫu.
- [ ] Có màn hình review để sửa tay đáp án rồi xuất lại.
- [ ] README đủ để cài và chạy trên máy mới.

---

## 8. Thứ tự làm đề xuất

`Phase 0 → 1 → 2 → 3 (tải file PE và ảnh FE) → 4 (comment FE) → 5 → 6 (xuất docx FE) → 7 → 8 → 9`

Làm PE tải trọn bộ file đính kèm theo thư mục bài đăng, sau đó hoàn thiện nhánh FE (comment + bỏ phiếu + docx).

---

## 9. Quyết định kiến trúc: Modular Monolith, KHÔNG microservices

**Kết luận: dùng monolith có module rõ ràng, deploy thành 2 process (API + Worker).**

Lý do:
- Domain nhỏ và chặt: crawl → phân tích → xuất file là một pipeline tuần tự, dùng chung DB và storage. Tách service chỉ thêm network call, serialization, versioning và debug phân tán mà không đem lại lợi ích.
- Không có nhu cầu scale độc lập từng phần: tải thực tế là 1 job crawl tại 1 thời điểm (cố ý giới hạn để không bị chặn).
- Nhóm nhỏ (1–2 người): chi phí vận hành microservices (nhiều pipeline CI, service discovery, tracing, nhiều bill hosting) lớn hơn nhiều so với giá trị.
- Free-tier hosting không hợp với nhiều service: mỗi service thường sleep riêng, cold start cộng dồn.

Cái đáng tách duy nhất là **Worker** (chạy Playwright/Chromium nặng RAM, chạy lâu) khỏi **API** (nhẹ, phải luôn phản hồi nhanh). Hai process cùng một codebase, giao tiếp qua bảng `jobs` trong DB. Nhờ ranh giới module (`crawler/`, `analysis/`, `export/`) và interface `Storage`, sau này nếu thật sự cần tách service thì cắt rất dễ.

Khi nào xem xét lại: có nhiều người dùng đồng thời cần scale crawl ngang, hoặc nhiều team cùng sửa code.

---

## 10. Design brief — giao diện không "AI generated"

Mục tiêu: trông như sản phẩm do một designer có chủ ý làm, không phải template mặc định.

### 10.1 Danh sách "dấu hiệu AI" phải tránh
- Gradient tím–xanh, nền glassmorphism, glow/neon, blob mờ ở nền.
- Hero "Supercharge your workflow", ba thẻ tính năng đều nhau có icon tròn.
- Emoji làm icon, emoji trong tiêu đề, dấu "✨" ở mọi nơi.
- Bo góc 16–24px đồng loạt, bóng đổ mềm trên mọi thẻ, thẻ lồng thẻ.
- Giữ nguyên shadcn/Material mặc định, font Inter + màu slate mặc định không chỉnh.
- Microcopy rập khuôn ("Welcome back!", "Something went wrong"), số liệu giả đẹp, ảnh stock.
- Căn giữa mọi thứ, khoảng trắng quá thoáng, mọi thành phần cùng một độ nhấn.

### 10.2 Hướng thiết kế đề xuất: "bàn học / tờ đề thi in"
Gợi cảm giác tờ giấy, sổ ghi chép, tài liệu ôn thi — hợp với nội dung, và tự nhiên khác với template SaaS.
- **Nền**: trắng ngà ấm (vd `#FAF7F2`), chữ gần đen ấm (`#1F1B16`), đường kẻ mảnh 1px thay vì bóng đổ để phân vùng.
- **Một màu nhấn duy nhất** (đề xuất đỏ bút chấm bài hoặc xanh mực): dùng cho hành động chính và trạng thái quan trọng. Không dùng nhiều màu nhấn.
- **Màu trạng thái độ tin cậy** (confident / weak / conflict / no_data): tông đất dịu (xanh rêu, vàng nghệ, đỏ gạch, xám), kèm nhãn chữ và icon, không chỉ dựa vào màu (hỗ trợ người mù màu).
- **Typography là nhân vật chính**: tiêu đề dùng serif có hỗ trợ tiếng Việt đầy đủ (vd *Newsreader*, *Source Serif 4*, *Be Vietnam Pro* cho phần UI). Phần số liệu/mã môn dùng mono (vd *JetBrains Mono*). Kiểm tra dấu tiếng Việt ở mọi cỡ chữ.
- **Bố cục**: lưới 8px, căn trái, mật độ thông tin vừa phải (dạng bảng/danh sách như sổ), bố cục bất đối xứng ở trang chủ thay vì hero căn giữa.
- **Bo góc nhỏ** (2–6px), bóng đổ gần như không có; hover/focus bằng viền và đổi nền, focus ring rõ ràng.
- **Chi tiết có gu**: dùng thuật ngữ thật của sinh viên FPT (mã môn như `PRN212`, `SWT301`), trạng thái trống có câu chữ riêng, "tiến trình" hiển thị như dòng log từng câu thay vì thanh phần trăm chung chung.
- **Chuyển động tiết chế**: chỉ animate những gì có ý nghĩa (tiến trình, thay đổi trạng thái), 120–200ms, tôn trọng `prefers-reduced-motion`.
- **Dark mode**: làm từ token, không đảo màu máy móc; giữ tông giấy tối (nâu than), không dùng đen tuyền.

### 10.3 Quy trình làm
1. Viết `docs/design-brief.md` + `frontend/src/styles/tokens.css` (màu, font, cỡ chữ, spacing, radius, border) **trước**.
2. Dựng 3 màn hình then chốt trước (Chọn môn, Tiến trình job, Review đáp án), duyệt, rồi mới làm các trang còn lại.
3. Review responsive (mobile 375px, tablet, desktop), kiểm tra tương phản WCAG AA, điều hướng bàn phím.
4. Tiếng Việt tự nhiên cho toàn bộ microcopy, không dịch máy từ tiếng Anh.

---

## 11. Deployment & CI/CD (chuẩn bị public)

### 11.1 Ràng buộc kỹ thuật quyết định lựa chọn
- **Backend có Playwright/Chromium** → không chạy được trên Cloudflare Workers hay Vercel Functions (serverless, không có browser, giới hạn thời gian chạy). Cần container/VM thật.
- **Free tier hay sleep + ổ đĩa tạm** (Render free sleep sau ~15 phút không dùng, mất file khi restart; RAM 512MB thường không đủ cho Chromium ổn định) → dùng Postgres + R2 bên ngoài, và worker cần chỗ có ≥ 1GB RAM.
- **Crawl cần phiên đăng nhập tài khoản sinh viên thật**, thường kèm bot-detection; IP datacenter dễ bị chặn hơn IP nhà.

### 11.2 Tư vấn: ba phương án

| | Frontend | API | Worker (crawl) | DB / Files | Nhận xét |
|---|---|---|---|---|---|
| **A (khuyến nghị cho bắt đầu)** | Cloudflare Pages | Render / Koyeb (free) hoặc VPS | **Chạy trên máy bạn** (agent local, đẩy kết quả lên R2 + Postgres) | Neon + R2 | Free, ít rủi ro bị chặn nhất vì crawl bằng IP + phiên đăng nhập của bạn |
| **B** | Cloudflare Pages | 1 VPS chạy Docker Compose (api + worker) | Cùng VPS | Postgres trong VPS + R2 | Đơn giản, 1 chỗ để quản lý. Oracle Cloud Always Free (ARM, tới 24GB RAM) là lựa chọn free mạnh nhất nhưng đăng ký hơi khó; hoặc VPS 5 USD/tháng |
| **C** | Vercel | Render | Render (paid) | Neon + R2 | Dễ nhưng tốn tiền khi cần worker có Chromium; Vercel Hobby ràng buộc dùng phi thương mại |

**Chọn Cloudflare Pages hay Vercel cho frontend?** Chọn **Cloudflare Pages**: băng thông không giới hạn ở gói free, nằm cùng hệ với R2/DNS/WAF, ít giới hạn thương mại hơn Vercel Hobby. Vercel chỉ hơn ở trải nghiệm preview deploy, mà Pages cũng có preview theo branch/PR.

**Không đưa backend lên Cloudflare Workers** vì lý do ở 11.1. Cloudflare chỉ nên giữ: Pages (frontend), R2 (file), DNS + proxy/WAF (bảo vệ API, rate limit).

**Khuyến nghị**: bắt đầu **phương án A**, nâng lên **B** khi cần chạy tự động trên server.

### 11.3 CI/CD với GitHub Actions
- `ci.yml` (mọi PR/push): backend `ruff` + `mypy` + `pytest`; frontend `eslint` + `tsc` + `vitest` + build thử.
- **Frontend**: dùng **tích hợp Git của Cloudflare Pages** (kết nối repo, root `frontend/`, build `npm run build`) là đủ và đơn giản nhất; hoặc dùng Action `cloudflare/wrangler-action` nếu muốn kiểm soát trong workflow. Mỗi PR có URL preview.
- **Backend**: workflow build Docker image → push GitHub Container Registry → gọi deploy hook của Render/Koyeb (hoặc `ssh` + `docker compose pull && up -d` nếu dùng VPS). Chạy migration Alembic như một bước trong deploy.
- **Secrets**: để trong *GitHub Secrets / Environments* (tách `staging`, `production`, bật required reviewers cho production). Các biến dự kiến: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `DATABASE_URL`, `RENDER_DEPLOY_HOOK_URL` (hoặc SSH key), `APP_SECRET_KEY`.
  - **Chỉ secret của hạ tầng** nằm ở GitHub. **Secret runtime** (DATABASE_URL, khoá R2...) cấu hình ở nền tảng chạy app (Render/VPS env), không in ra log.
  - **Tuyệt đối không** đưa mật khẩu/cookie tài khoản FUOverflow lên GitHub hay server công khai. Cookie nằm trong `browser_profile/` ở máy chạy worker, được gitignore.
  - Bật Dependabot + secret scanning của GitHub; token Cloudflare dùng quyền tối thiểu (scoped token).
- Môi trường: `dev` (local), `staging` (branch `develop`), `production` (branch `main`, deploy sau khi duyệt).

### 11.4 Cảnh báo quan trọng trước khi public
Cân nhắc kỹ, vì nó ảnh hưởng đến thiết kế:
- Tool này tải ảnh đề và comment của người khác rồi tổng hợp lại. **Công khai lại nội dung đó cho mọi người** có rủi ro vi phạm điều khoản của FUOverflow và quyền của người đăng/nhà trường, có thể dẫn tới bị khoá tài khoản hoặc bị yêu cầu gỡ.
- Phương án an toàn hơn: **public chỉ phần giao diện và code**, còn crawl + lưu dữ liệu chạy riêng cho từng người dùng (mỗi người tự đăng nhập bằng tài khoản của họ), hoặc triển khai ở chế độ **private có đăng nhập** (allowlist email/Cloudflare Access) cho nhóm bạn.
- Nếu public bản có sẵn dữ liệu: bắt buộc có trang điều khoản + cơ chế gỡ nội dung khi được yêu cầu, và không ghi tên tác giả comment.
- Backend công khai cần: xác thực, rate limit theo IP/người dùng, CORS chỉ cho domain frontend, giới hạn số job đồng thời, kiểm tra input chặt (chống SSRF khi nhận URL), không để lộ endpoint điều khiển trình duyệt.

---

## 12. Gợi ý tên dự án / tên repo

Tránh dùng chữ "fuoverflow" hoặc logo của họ trong tên để không bị hiểu là sản phẩm chính thức hay vi phạm nhãn hiệu. Tên repo dùng chữ thường, gạch ngang.

| Tên | Repo | Ý nghĩa |
|---|---|---|
| **Gomde** | `gomde` | "Gom đề": ngắn, thuần Việt, dễ nhớ, đọc lên rõ nghĩa |
| **Đề Bìa / DeBia** | `de-bia` | "Bìa" như bìa tập đề; hơi lạ, có chất |
| **Ôn Đề** | `on-de` | Gắn với mục đích ôn thi, thân thiện |
| **ExamLoom** | `examloom` | "Dệt" các đề lại thành một bộ; tên quốc tế dễ làm brand |
| **ExamFold** | `examfold` | Gấp gọn nhiều đề thành một tập |
| **Penmark** | `penmark` | Bút chấm bài, hợp với hướng thiết kế "tờ đề thi" |
| **Sổ Đề** | `so-de` | Cuốn sổ chép đề, gần gũi |
| **FE Binder** | `fe-binder` | Cặp hồ sơ tập hợp đề FE; mô tả đúng chức năng |

**Gợi ý chọn**: `gomde` (nếu muốn Việt hoá, dễ nhớ) hoặc `examloom` (nếu muốn tên tiếng Anh gọn). Tên hiển thị trên giao diện có thể có dấu ("Gom Đề"). Trước khi chốt, kiểm tra tên repo/GitHub org còn trống và tên miền (`.dev`, `.app`, `.vn`) còn đăng ký được không.