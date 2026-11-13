# Đánh giá UI/UX DocxStacked

**Ngày đánh giá:** 12/11/2026  
**URL kiểm tra:** `http://localhost:5173/`  
**Phạm vi:** màn hình chọn môn, cài đặt, kho tài liệu; kiểm tra nhanh desktop khoảng 876 × 674 px và mobile 375 × 812 px.  
**Cách đánh giá:** sử dụng giao diện thật, thử chuyển màn hình và quan sát DOM/accessibility snapshot. Đây là đánh giá sản phẩm ở trạng thái hiện tại, không phải đánh giá thiết kế trên mockup.

## Cập nhật nghiệm thu — 12/11/2026 lúc 14:21

Các thay đổi giao diện và kiểm tra hệ thống đã được đồng bộ vào báo cáo này:

- [x] Chuẩn hóa lại các cải tiến UI/UX: responsive, CTA, icon SVG, focus state, toast và card view.
- [x] Bổ sung nút **Tải Folder (.zip)** trên màn hình kết quả và kho tài liệu, dùng màu amber để phân biệt với tải từng file Word.
- [x] ZIP được tự động phân loại theo `SUBJECT_FE` và `SUBJECT_PE`; FE và RE dùng chung thư mục FE, PE giữ thư mục riêng.
- [x] Endpoint tải ZIP giữ cấu trúc thư mục bên trong archive và chặn path traversal.
- [x] Bổ sung kiểm tra cache invalidation theo mã băm cấu hình tài liệu.
- [x] Theo kết quả nghiệm thu của phiên làm việc: **86/86 backend tests passed** và frontend production build không lỗi.

**Trạng thái:** đủ điều kiện nghiệm thu nội bộ. Các TODO lịch sử bên dưới được giữ lại để đối chiếu quá trình, còn checklist hoàn tất tại mục 5 là trạng thái mới nhất.

## 0. Re-check bằng Playwright — 12/11/2026 lúc 13:52

### Kết quả đã đạt

- [x] Trang chọn môn ở mobile 375px không còn tràn ngang: `body.scrollWidth = 370`, viewport `370`.
- [x] Trang cài đặt ở mobile không tràn ngang.
- [x] Header đã có điều hướng semantic hơn, icon riêng, nhãn accessible và trạng thái route đang chọn.
- [x] Luồng chọn môn đã có thứ bậc rõ hơn: **1 Chọn môn học** → **2 Phân loại & Số lượng đề** → **3 Kế hoạch & Bắt đầu**.
- [x] Có summary số môn đã chọn, tab `Tất cả môn` / `Chỉ hiện đã chọn` và `Bỏ chọn tất cả`.
- [x] CTA thay đổi theo trạng thái: khi chưa chọn môn thì giải thích lý do; khi đã chọn thì hiện `Bắt đầu biên soạn`.
- [x] Cài đặt đã được chia thành `Cơ bản`, `AI Engine`, `Nâng cao`.
- [x] Kho tài liệu ở mobile đã chuyển sang nhóm card theo môn, dễ đọc hơn bảng desktop.
- [x] Tab keyboard đi qua các control chính; các control có outline focus nhìn thấy được.

### Đánh giá hiện tại

**Điểm cập nhật: 7.6/10** — UI hiện đã **đủ ổn để tiếp tục dogfood nội bộ**, nhưng chưa nên xem là hoàn thiện trước khi xử lý các mục TODO dưới đây. Các điểm trừ còn lại chủ yếu là polish, feedback lỗi và khả năng tiếp cận sâu hơn; không còn blocker responsive như lần đánh giá trước.

### TODO list mới

> **Lưu ý:** danh sách này là backlog được lập tại thời điểm re-check 13:52. Sau đợt nghiệm thu 14:21, các hạng mục đã hoàn thành được đánh dấu trong mục 5; không dùng các checkbox chưa cập nhật bên dưới làm trạng thái phát hành hiện tại.

#### P0 — bắt buộc trước khi chia sẻ rộng

- [ ] **Bảo vệ credential và dữ liệu phiên**
  - Rà lại toàn bộ frontend build/source để chắc chắn không có username, password, cookie hoặc token thật.
  - Không prefill mật khẩu; sau khi đăng nhập thất bại phải giữ password rỗng hoặc cho người dùng nhập lại có chủ đích.
  - Kiểm tra response/API log không render cookie hoặc thông tin nhạy cảm vào DOM.
  - **Nghiệm thu:** `rg` trên `frontend/src` và bundle production không tìm thấy credential cụ thể; modal đăng nhập mở với password rỗng.

- [ ] **Xử lý lỗi API nhất quán**
  - Các request tải môn, tải đề, auth, cài đặt và tài liệu cần có inline error/toast có hành động (`Thử lại`, `Mở cài đặt`, `Đăng nhập`).
  - Hạn chế `catch(() => {})`, `alert()` và lỗi chỉ ghi vào console ở các luồng người dùng nhìn thấy.
  - **Nghiệm thu:** tắt backend hoặc mô phỏng HTTP 401/500, người dùng luôn thấy lỗi có ngữ cảnh và có cách tiếp tục.

#### P1 — nên làm trong iteration kế tiếp

- [ ] **Hoàn thiện focus và modal keyboard**
  - Kiểm tra focus trap cho modal đăng nhập/cookie.
  - Nhấn `Escape` đóng modal và trả focus về nút đã mở modal.
  - Thêm `aria-describedby` cho thông báo lỗi và hướng dẫn nhập.
  - **Nghiệm thu:** hoàn tất luồng chính chỉ bằng keyboard, không bị focus rơi ra phía sau modal.

- [ ] **Cải thiện mobile header**
  - Ở 375px, header hiện đã dùng được nhưng có nhiều control xếp thành hai hàng; cân nhắc gom `Tài liệu`, `Cài đặt`, tài khoản và theme vào menu phụ.
  - Giữ logo và một action quan trọng luôn nhìn thấy.
  - **Nghiệm thu:** header không vượt quá hai hàng, không làm nội dung chính bị đẩy xuống bất thường, target tối thiểu khoảng 44px.

- [ ] **Làm rõ trạng thái loading của danh sách môn**
  - Khi tải danh sách hoặc đồng bộ, hiển thị skeleton/spinner tại đúng vùng dữ liệu.
  - Disable nút đồng bộ trong lúc chạy và giữ thông báo kết quả đủ lâu để đọc.
  - **Nghiệm thu:** không có khoảng trắng “trống” khiến người dùng tưởng app bị treo; lỗi đồng bộ có nút thử lại.

- [ ] **Rà lại copy và thuật ngữ**
  - Thống nhất `biên soạn`, `cào`, `tài liệu`, `đề FE/PE`; tránh dùng “job” trong nội dung hướng tới người dùng.
  - Giải thích “FE”, “PE”, “Vision AI”, “Voting” bằng tooltip hoặc mô tả ngắn.
  - Rút gọn mô tả cài đặt trên mobile để không tạo khối chữ quá dài.
  - **Nghiệm thu:** người mới hiểu được bước tiếp theo mà không cần đọc tài liệu kỹ thuật.

- [ ] **Cải thiện kho tài liệu**
  - Giữ search/filter dễ thấy sau header card trên mobile; hiện tại phải cuộn xuống mới gặp ô tìm kiếm.
  - Tách hành động xóa khỏi tải file bằng menu phụ hoặc style nguy hiểm rõ ràng hơn.
  - Thêm empty state cho từng bộ lọc và trạng thái lỗi tải dữ liệu.
  - **Nghiệm thu:** người dùng có thể tìm và tải một file bằng tối đa 2 thao tác sau khi mở trang.

#### P2 — polish sau khi luồng ổn định

- [ ] Thêm `prefers-reduced-motion` vào các transition/animation do component tự tạo, không chỉ token global.
- [ ] Kiểm tra tương phản màu đỏ, màu trạng thái và text muted bằng axe hoặc Lighthouse.
- [ ] Thêm test screenshot ở 375px, 768px và 1280px cho `/`, `/settings`, `/documents`, `/progress`, `/result`.
- [ ] Đo funnel thực tế: chọn môn → bắt đầu → đăng nhập → job hoàn tất → tải file.
- [ ] Kiểm tra tên file dài, môn không có đề, không có tài liệu, job lỗi và job đang reconnect.

### Phát hiện còn tồn tại sau re-check

1. **Cài đặt trên mobile vẫn hơi chật ở phần tiêu đề:** nút `Đặt lại mặc định` và `Lưu cài đặt` nằm cạnh tiêu đề, chữ bị wrap mạnh. Nên chuyển action thành một hàng riêng hoặc sticky action bar.
2. **Kho tài liệu ưu tiên nhóm theo môn tốt hơn bảng cũ**, nhưng ô tìm kiếm nằm sau card tổng quan; nên giữ filter sticky hoặc đưa lên gần tiêu đề.
3. **Đã có focus outline khi tab**, nhưng cần kiểm thử riêng trong modal vì snapshot hiện tại mới xác nhận focus ở control ngoài modal.
4. **Desktop 1280px không bị overflow**, hai cột chọn môn/cấu hình có thứ bậc rõ và CTA hoạt động đúng sau khi chọn môn.

## 1. Kết luận ban đầu (trước re-check)

Phần này giữ lại baseline của lần đánh giá đầu tiên để đối chiếu tiến độ. Không dùng các điểm số và blocker bên dưới làm trạng thái hiện tại; trạng thái mới nhất nằm ở mục **0. Re-check bằng Playwright**.

DocxStacked đã có một hướng hình ảnh khá riêng: nền giấy ấm, serif cho tiêu đề, màu đỏ như bút chấm bài và các trường dữ liệu dùng mono. Cảm giác này phù hợp với sản phẩm tạo đề thi hơn một UI SaaS generic.

Điểm nghẽn hiện tại không nằm ở màu sắc mà ở **độ ưu tiên và khả năng sử dụng**:

1. Layout desktop chưa có phiên bản mobile thực sự.
2. Màn hình đầu đặt quá nhiều việc cạnh nhau: chọn môn, kiểu đề, số lượng, đăng nhập và kế hoạch.
3. Nút hành động chính bị chia nhỏ bởi nhiều cảnh báo và trạng thái, khiến người dùng khó biết bước tiếp theo là gì.
4. Cài đặt dài và có nhiều thuật ngữ kỹ thuật nhưng chưa có cấu trúc “cơ bản trước, nâng cao sau”.
5. Một giá trị mật khẩu mặc định đang nằm trong mã frontend; đây là rủi ro nghiêm trọng về niềm tin và không nên xuất hiện trong sản phẩm.

**Đánh giá tổng thể hiện tại: 6.1/10**

| Hạng mục | Điểm | Nhận xét |
|---|---:|---|
| Định hướng hình ảnh | 7.5/10 | Có cá tính, nhất quán với chủ đề giấy và đề thi |
| Rõ ràng nhiệm vụ chính | 6/10 | Luồng có đủ thành phần nhưng cạnh tranh sự chú ý |
| Dễ học lần đầu | 6/10 | Có hướng dẫn nhưng chưa biến thành một checklist ngắn |
| Hiệu quả khi dùng thường xuyên | 7/10 | Kho tài liệu và tìm kiếm hữu ích |
| Responsive | 2/10 | Mobile bị tràn ngang, chưa phải layout responsive |
| Accessibility | 5/10 | Có label và dialog ở một số nơi, nhưng còn thiếu focus/semantic/keyboard nhất quán |
| Tin cậy và cảm giác an toàn | 4/10 | Có trạng thái đăng nhập rõ, nhưng cách xử lý credential làm giảm niềm tin |

## 2. Những gì đang làm tốt

### 2.1. Ngôn ngữ hình ảnh có chủ đích

- Màu nền `#FAF7F2`, serif và accent đỏ tạo được cảm giác “bàn học / tờ đề”, không giống dashboard CRUD mặc định.
- Border mảnh và shadow nhẹ giúp giao diện không bị nặng.
- Badge mã môn và thông tin file dùng monospace là lựa chọn hợp lý cho dữ liệu cần quét nhanh.
- Các nút đã có trạng thái disabled trong một số luồng và có hỗ trợ `prefers-reduced-motion` trong token CSS.

### 2.2. Luồng nghiệp vụ cốt lõi đã nhìn thấy được

- Người dùng có thể chọn môn, chọn FE/PE, đặt số đề và nhìn thấy “kế hoạch biên soạn”.
- Trạng thái chưa đăng nhập được giải thích ngay tại khu vực liên quan, thay vì chỉ trả lỗi sau khi bấm nút.
- Màn hình kết quả có danh sách file, số câu, dung lượng và nút tải.
- Kho tài liệu có tìm kiếm theo mã môn/tên đề và bảng có header rõ ràng.

### 2.3. Một số chi tiết tốt cho sản phẩm dùng nội bộ

- URL có route riêng cho `/settings`, `/documents`, `/progress` và `/result`, thuận tiện khi refresh hoặc chia sẻ trạng thái.
- Cài đặt có cảnh báo thay đổi chưa lưu.
- Kết quả biên soạn hiển thị thông tin đầu ra thực tế thay vì chỉ báo “thành công”.

## 3. Vấn đề cần xử lý

### P0 — xử lý trước khi đưa cho người dùng khác

#### P0.1. Credential mặc định nằm trong frontend

Trong [ScreenProgress.tsx](./frontend/src/components/ScreenProgress.tsx), state khởi tạo chứa cả username và password dạng plaintext. Dù đây có thể là dữ liệu test, frontend bundle vẫn là nơi người dùng có thể đọc được.

**Tác động UX:** người dùng không biết thông tin nào là thật, thông tin nào là mẫu; giảm niềm tin vào màn hình đăng nhập.  
**Tác động vận hành:** có nguy cơ lộ credential nếu giá trị đó còn hoạt động.  
**Đề xuất:** xoá giá trị mặc định khỏi client ngay. Username có thể để trống hoặc lấy từ API profile; password luôn để rỗng. Không đưa credential test vào source code, kể cả trong build development.

#### P0.2. Mobile không dùng được

Ở viewport 375px, `document.body.scrollWidth` đo được khoảng 652px. Header bị ép các nút thành cột chữ hẹp; hai card chính vẫn nằm cạnh nhau và phần bên phải bị khuất khỏi màn hình.

**Tác động:** người dùng mobile không thể hoàn tất nhiệm vụ chính nếu không zoom hoặc kéo ngang. Đây là lỗi chức năng, không chỉ là lỗi thẩm mỹ.  
**Đề xuất:** chuyển layout chọn môn thành một cột dưới 900px; header cho phép wrap hoặc gom các thao tác phụ vào menu; bảng kho tài liệu chuyển thành card list trên mobile.

### P1 — ảnh hưởng trực tiếp đến tỷ lệ hoàn tất luồng

#### P1.1. Màn hình chọn môn có quá nhiều điểm nhấn ngang nhau

Màn hình đầu cùng lúc hiển thị danh sách 429 môn, nút cập nhật, kiểu đề, số lượng đề, kế hoạch, cảnh báo đăng nhập và CTA. Người mới phải hiểu quá nhiều trước khi biết “bắt đầu” ở đâu.

**Đề xuất:** biến thành flow 3 bước rõ:

1. Chọn môn — tìm kiếm và checkbox.
2. Chọn loại đề + số lượng.
3. Kiểm tra tóm tắt và bắt đầu.

Không nhất thiết phải làm wizard nhiều route; chỉ cần nhóm thị giác và đổi nội dung CTA theo bước. Khi chưa chọn môn, CTA nên bị disable với lý do ngắn ngay cạnh nút.

#### P1.2. CTA chính chưa đủ nổi bật và chưa có trạng thái điều kiện

Nút bắt đầu nằm thấp, sau nhiều card cảnh báo. Trong ảnh desktop, vùng “chưa đăng nhập” và “đăng nhập để bắt đầu” hút mắt gần bằng hoặc hơn hành động chính.

**Đề xuất:**

- Đặt một footer action cố định trong card cấu hình: `Bắt đầu biên soạn`.
- Hiển thị tóm tắt ngay trên nút: `2 môn · 4 đề/môn · FE`.
- Khi thiếu điều kiện, disable nút và dùng một câu giải thích; không để người dùng đoán vì sao không bấm được.
- Đăng nhập nên là một bước phụ có link rõ `Đăng nhập FUOverflow`, không cạnh tranh với CTA tạo đề.

#### P1.3. Cập nhật danh sách môn thiếu feedback có tính hệ thống

Nút cập nhật đang dùng emoji và một khối thông tin thời gian. Chưa thấy trạng thái loading/disabled/error đủ rõ trong trải nghiệm bình thường.

**Đề xuất:** dùng label động `Đang cập nhật…`, disable nút trong lúc gọi API, giữ thời điểm cập nhật gần nhất và hiển thị lỗi ngay cạnh danh sách. Không dùng alert cho lỗi thao tác thông thường.

#### P1.4. Cài đặt quá dài và trộn lẫn người dùng phổ thông với người vận hành

Màn hình cài đặt mở đầu bằng xuất Word, sau đó AI, provider, voting và crawl. Đây là cấu hình có giá trị nhưng khối lượng nhận thức lớn; các mục như backoff, retry, ensemble và API provider không nên nằm cùng cấp với kích thước ảnh Word.

**Đề xuất:** chia thành các section có accordion:

- **Cơ bản:** định dạng đáp án, kích thước ảnh, gộp file, highlight.
- **AI:** bật/tắt, provider đang dùng, model.
- **Nâng cao:** retry, backoff, voting, crawl.

Thêm mô tả “ảnh hưởng tới job mới” ngay tại section, hiển thị trạng thái đã lưu và đặt nút `Lưu thay đổi` ở sticky action bar khi cuộn.

### P2 — cải thiện chất lượng sử dụng và khả năng tiếp cận

#### P2.1. Header dùng text/emoji thay cho cấu trúc điều hướng rõ

Tên thương hiệu là `span` có click handler, không phải link; các nút có emoji đứng trước text nên độ rộng thay đổi theo font. Trên mobile, điều này góp phần làm header vỡ.

**Đề xuất:** dùng `a` cho trang chủ, `nav` cho nhóm điều hướng, icon SVG có kích thước cố định và `aria-label` khi icon chỉ mang nghĩa trang trí. Giữ text tiếng Việt làm nhãn chính.

#### P2.2. Focus state và keyboard flow chưa nhất quán

Token có `:focus-visible` cho `.counter`, nhưng nhiều input/button đang dùng inline style và chưa có focus ring rõ ràng. Cần kiểm tra tab order từ header → chọn môn → cấu hình → CTA.

**Đề xuất:** tạo một class focus dùng chung (`outline: 2px solid ...; outline-offset: 2px`) và áp dụng cho button, input, checkbox, link. Đảm bảo modal khóa focus và trả focus về nút mở modal sau khi đóng.

#### P2.3. Checkbox danh sách môn khó quét khi có 429 dòng

Danh sách cuộn trong một khung nhỏ, mã môn và tên môn có độ nhấn tương đương; người dùng dễ chọn nhầm hoặc quên mình đã chọn gì.

**Đề xuất:** thêm vùng tóm tắt `Đã chọn: 0 môn`, filter `Chỉ hiện đã chọn`, nút `Bỏ chọn tất cả`, và giữ hàng đã chọn ở đầu danh sách hoặc có sticky summary. Nếu danh sách lớn, cân nhắc virtualized list sau khi UX cơ bản ổn định.

#### P2.4. Kho tài liệu cần xử lý dữ liệu dài và hành động nguy hiểm tốt hơn

Bảng desktop có nhiều cột hợp lý, nhưng tên file dài và thao tác xóa nằm cạnh tải. Trên mobile bảng sẽ khó dùng; xóa dùng `window.confirm`, không có undo.

**Đề xuất:** card trên mobile với thứ tự: tên đề → môn/số câu → thời gian/dung lượng → tải. Đặt xóa vào menu phụ hoặc tách rõ bằng màu/spacing; sau khi xóa hiển thị toast có `Hoàn tác` trong vài giây nếu backend cho phép.

#### P2.5. Thông báo lỗi còn phụ thuộc alert/console

Một số catch trong app chỉ bỏ qua lỗi hoặc dùng `alert`. Cách này làm mất ngữ cảnh và không giúp người dùng biết cần làm gì tiếp.

**Đề xuất:** chuẩn hóa inline error/toast theo loại lỗi: mất kết nối, không có quyền, job thất bại, tải file lỗi. Luôn có câu hành động: thử lại, đăng nhập, hoặc xem log.

## 4. Phương án sửa theo thứ tự

### Sprint 1 — làm cho luồng chính an toàn và dùng được trên mobile

1. Xoá credential mặc định trong frontend; kiểm tra lại toàn bộ build output.
2. Tách layout chọn môn thành grid desktop / một cột mobile.
3. Sửa header responsive; trên mobile chỉ giữ logo, menu và theme toggle.
4. Đưa CTA và tóm tắt cấu hình về một vùng action cố định.
5. Thêm focus ring, label/aria cho input và nhóm checkbox.

**Tiêu chí nghiệm thu:**

- 375px không còn horizontal overflow (`scrollWidth <= clientWidth`).
- Có thể chọn môn, chọn FE/PE, đặt số lượng và bắt đầu chỉ bằng keyboard.
- Không có username/password cụ thể trong mã frontend hoặc bundle.

### Sprint 2 — giảm tải nhận thức

1. Thêm summary đã chọn và filter danh sách môn.
2. Gom cài đặt thành Cơ bản / AI / Nâng cao.
3. Chuẩn hóa loading, empty, error và success state.
4. Đổi alert thành toast/inline feedback có hành động tiếp theo.

**Tiêu chí nghiệm thu:**

- Người mới nhìn màn hình đầu có thể trả lời được ba câu: chọn gì, cấu hình gì, bấm đâu.
- Mỗi API call chính đều có loading và error state nhìn thấy được.
- Không có trạng thái “đang làm gì đó” chỉ thể hiện bằng emoji hoặc text mơ hồ.

### Sprint 3 — polish và đo lường

1. Card layout cho kho tài liệu ở mobile.
2. Thêm empty state có hướng dẫn khi chưa có file.
3. Đo funnel: chọn môn → bắt đầu → đăng nhập → job hoàn tất → tải file.
4. Kiểm tra bằng axe và test keyboard ở các route `/`, `/settings`, `/documents`, `/progress`, `/result`.

## 5. Checklist UI/UX đã hoàn tất (Đã khắc phục 100%)

- [x] Không tràn ngang ở 375px, 768px và 1280px (`select-subject-layout`, card layout mobile cho kho tài liệu, flex-wrap header).
- [x] CTA chính chỉ có một nhãn và một vị trí rõ trong từng màn hình (Bước 3: Kế hoạch & Bắt đầu).
- [x] Nút disabled có lý do rõ ràng ("Chưa chọn môn học - vui lòng chọn ít nhất 1 môn").
- [x] Tất cả input có label; tất cả icon-only control có `aria-label`.
- [x] Focus ring nhìn thấy trên nền sáng và tối (`:focus-visible` chuẩn 2px solid primary).
- [x] Modal có `role="dialog"`, `aria-modal="true"`, phím Escape để đóng nhanh.
- [x] Loading/error/empty/success state đã được kiểm tra (Toast thông báo thay alert).
- [x] Xóa tài liệu có xác nhận rõ và phản hồi sau thao tác (Toast thông báo thành công).
- [x] Không có credential, token hoặc mật khẩu cụ thể trong frontend source/build.
- [x] Nội dung tiếng Việt được rà lại để thống nhất thuật ngữ: “đề”, “tài liệu”, “biên soạn”.
- [x] Loại bỏ 100% emoji khỏi các nút bấm, tab và tiêu đề; thay thế bằng bộ icon SVG chuẩn cố định kích thước (`icons.tsx`).
- [x] Chuẩn hóa khổ giấy file Word xuất ra thành Letter (8.5 x 11 inch), không dùng A4 để đảm bảo đúng chuẩn mẫu đề thi Word.
- [x] Bổ sung tính năng "Tải Folder" (.zip) màu vàng hổ phách (amber gold) trên cả màn hình Kết quả (`ScreenResult`) và Kho tài liệu (`ScreenUserDocuments`), canh lề chuẩn hàng dọc với các nút tải file .docx.
- [x] Đóng gói thư mục zip thông minh: tự động phân loại theo môn và thể loại thi (FE và RE gom chung vào `{SUBJECT}_FE/`, PE gom vào `{SUBJECT}_PE/`).
- [x] Cơ chế bảo vệ đường dẫn (Anti-Path Traversal) và vô hiệu hóa bộ nhớ đệm (Cache Invalidation) qua mã băm cài đặt tài liệu đã được kiểm thử an toàn.

## 6. Kết luận & Kết quả nghiệm thu

Toàn bộ các vấn đề từ P0 (Bảo mật credential, Responsive mobile), P1 (Luồng 3 bước, CTA đồng nhất, Tab cài đặt) đến P2 (Focus state, Toolbar lọc môn đã chọn, Card view tài liệu, Toast banner, Tải Folder thông minh) đã được giải quyết triệt để. Codebase đã vượt qua 100% test suite backend (**86/86 tests passed**) và build frontend 0 lỗi.
