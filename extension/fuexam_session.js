/**
 * extension/fuexam_session.js
 * Module đồng bộ phiên đăng nhập nền tảng fuexam.me cho extension DocxStacked.
 * 
 * Quy tắc bảo mật:
 * 1. Tuyệt đối KHÔNG ghi log giá trị cookie (xf_user, xf_session, xf_csrf) ở bất kỳ nơi nào.
 * 2. Chỉ trích xuất các cookie cần thiết: xf_user, xf_session, xf_csrf và cf_clearance (nếu có).
 * 3. Gửi về backend DocxStacked qua POST /api/auth/fuexam/extension-session với header X-Ingest-Token.
 */

// 1. Nhập nguyên vẹn service worker của FUOverflow (không làm thay đổi file cũ)
importScripts("background.js");

const BACKEND_BASE_URL = "http://127.0.0.1:8000";
let isSyncingFuexam = false;

/**
 * Lấy token Ingest từ local storage hoặc truy vấn backend nếu chưa lưu
 */
async function getOrFetchIngestToken() {
  try {
    const data = await chrome.storage.local.get(["ingestToken"]);
    if (data && data.ingestToken && data.ingestToken.trim()) {
      return data.ingestToken.trim();
    }
    // Nếu chưa lưu, truy vấn settings backend (chỉ kết nối localhost)
    const resp = await fetch(`${BACKEND_BASE_URL}/api/settings`);
    if (resp.ok) {
      const setJson = await resp.json();
      const token = setJson.extension?.ingest_token;
      if (token) {
        await chrome.storage.local.set({ ingestToken: token });
        return token;
      }
    }
  } catch (err) {
    // Backend offline
  }
  return "";
}

/**
 * Đọc cookie từ fuexam.me và gửi về backend DocxStacked
 */
async function syncFuexamSession() {
  if (isSyncingFuexam) return { ok: false, message: "Đang đồng bộ..." };
  isSyncingFuexam = true;

  try {
    const allCookies = await chrome.cookies.getAll({ domain: "fuexam.me" });
    if (!allCookies || allCookies.length === 0) {
      isSyncingFuexam = false;
      return { ok: false, message: "Không tìm thấy cookie nào cho domain fuexam.me." };
    }

    // Chỉ trích xuất các cookie XenForo cần thiết & cf_clearance
    // Lý do lấy cf_clearance: Cần thiết khi fuexam.me bật bảo vệ Cloudflare Challenge / DDoS
    const allowedNames = new Set(["xf_user", "xf_session", "xf_csrf", "cf_clearance"]);
    const relevantCookies = allCookies
      .filter((c) => allowedNames.has(c.name))
      .map((c) => ({
        name: c.name,
        value: c.value,
        domain: c.domain,
        path: c.path,
        secure: c.secure,
        httpOnly: c.httpOnly,
        sameSite: c.sameSite,
        expirationDate: c.expirationDate,
      }));

    // Bắt buộc phải có cookie xf_user với giá trị không rỗng
    const hasXfUser = relevantCookies.some((c) => c.name === "xf_user" && c.value && c.value.trim().length > 0);
    if (!hasXfUser) {
      isSyncingFuexam = false;
      return { ok: false, message: "Chưa đăng nhập fuexam.me trên trình duyệt (thiếu xf_user)." };
    }

    const ingestToken = await getOrFetchIngestToken();

    const headers = {
      "Content-Type": "application/json",
      "X-DocxStacked-Ext": "kicplcdfmbcfjildbbimpfiljlmfokea",
    };
    if (ingestToken) {
      headers["X-Ingest-Token"] = ingestToken;
    }

    const res = await fetch(`${BACKEND_BASE_URL}/api/auth/fuexam/extension-session`, {
      method: "POST",
      headers,
      body: JSON.stringify({ cookies: relevantCookies }),
    });

    const data = await res.json().catch(() => ({}));
    if (res.ok && data.success) {
      // Chỉ log tên tài khoản thật, TUYỆT ĐỐI không log cookie
      console.info(`[DocxStacked Fuexam] Đồng bộ phiên thành công cho tài khoản: ${data.username || "Thành viên"}`);
      isSyncingFuexam = false;
      return { ok: true, username: data.username };
    } else {
      console.warn(`[DocxStacked Fuexam] Backend từ chối phiên: ${data.detail || data.message || "Lỗi không xác định"}`);
      isSyncingFuexam = false;
      return { ok: false, message: data.detail || data.message };
    }
  } catch (err) {
    console.warn("[DocxStacked Fuexam] Lỗi kết nối khi đồng bộ phiên:", err.message);
    isSyncingFuexam = false;
    return { ok: false, message: err.message };
  }
}

/**
 * Kiểm tra xem backend có đang yêu cầu đồng bộ phiên fuexam.me không (fuexam_sync_requested=true)
 */
async function checkBackendFuexamSyncRequest() {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/auth/extension-heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        logged_in: typeof lastAuthStatus !== "undefined" ? Boolean(lastAuthStatus.logged_in) : false,
        username: typeof lastAuthStatus !== "undefined" ? lastAuthStatus.username : null,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data && (data.fuexam_sync_requested || data.fueuxam_sync_requested)) {
        await syncFuexamSession();
      }
    }
  } catch (e) {
    // Backend offline
  }
}

// 2. Thiết lập alarm kiểm tra định kỳ mỗi 15-30 giây
chrome.alarms.create("fuexam_sync_check_alarm", { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "fuexam_sync_check_alarm") {
    checkBackendFuexamSyncRequest();
  }
});

// 3. Lắng nghe thay đổi cookie trên fuexam.me để tự động nhận phiên ngay lập tức
if (chrome.cookies && chrome.cookies.onChanged) {
  chrome.cookies.onChanged.addListener((changeInfo) => {
    if (changeInfo.cookie && changeInfo.cookie.domain && changeInfo.cookie.domain.includes("fuexam.me")) {
      if (["xf_user", "xf_session"].includes(changeInfo.cookie.name) && !changeInfo.removed) {
        checkBackendFuexamSyncRequest();
      }
    }
  });
}

// 4. Lắng nghe thông điệp từ giao diện web DocxStacked (onMessageExternal)
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  if (message && (message.type === "TRIGGER_FUEXAM_SYNC" || message.type === "SYNC_FUEXAM_SESSION")) {
    syncFuexamSession().then((res) => sendResponse(res));
    return true; // async
  }
});
