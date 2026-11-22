# Kế Hoạch Thiết Kế: Đồng Bộ Phiên Đăng Nhập fuexam.me Qua Chrome Extension

## 1. Bối cảnh & Mục tiêu
Khi người dùng gặp rào cản môi trường không thể mở trực tiếp cửa sổ Playwright Chromium headed từ backend (ví dụ: máy chạy trong môi trường container/sandbox, bị phần mềm diệt virus chặn tiến trình con, hoặc xung đột desktop window station), phương án sử dụng **Chrome Extension** (đã được cài đặt sẵn trên trình duyệt Chrome hàng ngày của người dùng) để trích xuất cookie phiên là một giải pháp dự phòng mạnh mẽ và thân thiện nhất:
- Người dùng đã đăng nhập sẵn tài khoản fuexam.me trên trình duyệt Chrome cá nhân của họ.
- Không cần mở thêm một cửa sổ Chromium mới và không cần người dùng nhập lại tài khoản/mật khẩu.

---

## 2. Quyền Cần Thêm Trong Extension (`manifest.json`)
Hiện tại extension của DocxStacked đã có quyền thao tác trên một số trang và kết nối API. Để trích xuất phiên fuexam.me, extension cần bổ sung các quyền sau trong `manifest.json` (Manifest V3):

```json
{
  "permissions": [
    "cookies",
    "storage"
  ],
  "host_permissions": [
    "https://fuexam.me/*",
    "http://127.0.0.1:8000/*"
  ]
}
```

- **`cookies` permission**: Cho phép Extension đọc cookie có cờ `HttpOnly` thuộc domain `fuexam.me` thông qua API `chrome.cookies.getAll(...)`. Content script thông thường (`document.cookie`) **không thể đọc được** cookie `HttpOnly` (như `xf_user`, `xf_session`), do đó quyền `cookies` trong background service worker là điều kiện bắt buộc.
- **`host_permissions`**: Cấp quyền truy cập domain `https://fuexam.me/*` để đọc cookie và domain `http://127.0.0.1:8000/*` để gửi dữ liệu về backend qua HTTP POST.

---

## 3. Cách Trích Xuất & Gửi Về Backend Bằng Token Ingest Hiện Có

### 3.1. Luồng hoạt động phía Extension (Background Service Worker / Popup):
1. Khi người dùng bấm nút *"Đồng bộ phiên fuexam từ trình duyệt"* trên Popup Extension (hoặc dashboard DocxStacked gửi message):
2. Service worker gọi:
   ```javascript
   chrome.cookies.getAll({ domain: "fuexam.me" }, async (cookies) => {
     // Lọc các cookie cần thiết của XenForo
     const relevantCookies = cookies.filter(c => 
       ["xf_user", "xf_session", "xf_csrf"].includes(c.name)
     );
     
     // Lấy Ingest Token đã lưu trong extension settings
     const { ingestToken } = await chrome.storage.local.get("ingestToken");

     // Gửi payload về backend
     const resp = await fetch("http://127.0.0.1:8000/api/auth/fuexam/extension-session", {
       method: "POST",
       headers: {
         "Content-Type": "application/json",
         "X-Ingest-Token": ingestToken
       },
       body: JSON.stringify({
         source: "chrome_extension",
         cookies: relevantCookies.map(c => ({
           name: c.name,
           value: c.value,
           domain: c.domain,
           path: c.path,
           httpOnly: c.httpOnly,
           secure: c.secure,
           sameSite: c.sameSite
         }))
       })
     });
   });
   ```

### 3.2. Cơ chế bảo vệ với Ingest Token hiện có:
- Endpoint `POST /api/auth/fuexam/extension-session` tái sử dụng `settings.INGEST_TOKEN` (đã được sinh ngẫu nhiên an toàn trong `.env` và hiển thị trong cài đặt DocxStacked).
- Backend kiểm tra header `X-Ingest-Token` trùng khớp với `settings.INGEST_TOKEN`. Bất kỳ request nào không có token hoặc token không hợp lệ đều bị từ chối với HTTP 403 Forbidden.

---

## 4. Cách Xác Minh Phiên Bằng `data-logged-in="true"` Phía Backend
Sau khi nhận được danh sách cookie từ Extension, backend không lưu ngay mà thực hiện xác minh nghiêm ngặt:

1. **Kiểm tra cookie bắt buộc**: Phải có cookie `xf_user` với giá trị không rỗng (chỉ có `xf_session` là chưa đăng nhập).
2. **Gửi probe request kiểm tra**:
   - Backend sử dụng `httpx` hoặc `requests` gửi request `GET https://fuexam.me/` với danh sách cookie vừa nhận.
   - Thêm `User-Agent` tiêu chuẩn giống trình duyệt để tránh bị chặn.
3. **Điều kiện xác nhận phiên hợp lệ**:
   - HTTP Status Code trả về phải là `200`.
   - Nội dung HTML phải chứa chuỗi thuộc tính `data-logged-in="true"` (thuộc tính chuẩn trên thẻ `<html>` của XenForo khi người dùng đã đăng nhập).
4. **Trích xuất tên tài khoản thật & Lưu trữ**:
   - Phân tích HTML bằng BeautifulSoup để lấy tên tài khoản từ `.p-navgroup-link--user .p-navgroup-linkText`.
   - Ghi cookie vào `data/auth/fuexam_storage_state.json` theo định dạng Playwright Storage State.
   - Ghi thông tin người dùng vào `data/auth/fuexam_user.json` (`{"username": real_username, "auth_source": "extension"}`).
   - Gán quyền truy cập tệp chỉ cho người dùng hiện tại (chống lộ token sang user khác).

---

## 5. Rủi Ro & Biện Pháp Giảm Thiểu (Risk Assessment & Mitigations)

| Rủi ro | Mức độ | Biện pháp giảm thiểu |
| :--- | :---: | :--- |
| **Lộ Ingest Token trong Extension** | Trung bình | Token chỉ được lưu trong `chrome.storage.local` của Extension cá nhân, chỉ gửi đến `127.0.0.1`. Người dùng có thể đổi token mới bất kỳ lúc nào từ màn hình Cài đặt của DocxStacked. |
| **Phiên hết hạn trên fuexam.me** | Thấp | Probe request kiểm tra `data-logged-in="true"` sẽ phát hiện ngay lập tức nếu phiên không còn hiệu lực và trả thông báo yêu cầu người dùng đăng nhập lại trên trang web fuexam.me. |
| **Cảnh báo quyền khi cài đặt extension** | Thấp | Quyền `cookies` có thể hiển thị cảnh báo *"Đọc và thay đổi dữ liệu duyệt web"*. Cần ghi chú rõ ràng trong tài liệu hướng dẫn extension rằng quyền này chỉ áp dụng giới hạn cho domain `fuexam.me` nhằm mục đích đồng bộ phiên thi. |
| **Người dùng chưa cài extension** | Trung bình | Giữ nguyên phương án mở cửa sổ Playwright Chromium (`scripts/fuexam_login.py`) làm kênh đăng nhập mặc định. Phương án extension hoạt động song song như một phương án thay thế tiện lợi (one-click sync). |
