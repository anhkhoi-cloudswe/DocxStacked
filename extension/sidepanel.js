// sidepanel.js - DocxStacked Chromium Extension (MV3)
// Minimalist, robust ingestion loop directly in Side Panel.

const BACKEND_URL = "http://127.0.0.1:8000";
const EXTENSION_ID = (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id) ? chrome.runtime.id : "kicplcdfmbcfjildbbimpfiljlmfokea";
const MIN_REQUEST_INTERVAL_MS = 2000; // Cadence: 1 req / 2.0s

const state = {
  isRunning: false,
  isStopped: false,
  totalQuestions: 0,
  processedQuestions: 0,
  collectedComments: 0,
  crawledPages: 0,
  count403: 0,
  countRetries: 0,
  existingExam: null,
  activeTab: "soande",
  settingsData: null,
  documentsData: [],
};

// Common API helper for Extension with pinned header
async function apiFetch(endpoint, options = {}) {
  const headers = options.headers || {};
  headers["X-DocxStacked-Ext"] = EXTENSION_ID;
  const userToken = (elInputIngestToken && elInputIngestToken.value.trim()) || "";
  if (userToken) {
    headers["X-Ingest-Token"] = userToken;
  }
  return fetch(`${BACKEND_URL}${endpoint}`, {
    ...options,
    headers,
  });
}

// DOM Elements
const elBackendStatus = document.getElementById("backend-status");
const elUiNoticeBox = document.getElementById("ui-notice-box");
const elThreadTitleDisplay = document.getElementById("thread-title-display");
const elInputThreadUrl = document.getElementById("input-thread-url");
const elBtnSyncTab = document.getElementById("btn-sync-tab");
const elBtnMainAction = document.getElementById("btn-main-action");
const elProgressBar = document.getElementById("progress-bar");
const elStatsSummaryLine = document.getElementById("stats-summary-line");
const elOfflineRecoveryRow = document.getElementById("offline-recovery-row");
const elBtnRetryIngest = document.getElementById("btn-retry-ingest");
const elBtnClearIdb = document.getElementById("btn-clear-idb");
const elResultCard = document.getElementById("result-card");
const elResultFilename = document.getElementById("result-filename");
const elResultDownloadBtn = document.getElementById("result-download-btn");
const elBtnOpenFolder = document.getElementById("btn-open-folder");
const elLogBox = document.getElementById("log-box");
const elBtnCopyLog = document.getElementById("btn-copy-log");
const elInputIngestToken = document.getElementById("input-ingest-token");

// Reopen elements
const elReopenCard = document.getElementById("reopen-card");
const elReopenText = document.getElementById("reopen-text");
const elBtnReopenDownload = document.getElementById("btn-reopen-download");
const elBtnReopenUpdate = document.getElementById("btn-reopen-update");
const elCheckRedownloadImages = document.getElementById("check-redownload-images");

// Tab elements
const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = {
  soande: document.getElementById("tab-panel-soande"),
  dasoan: document.getElementById("tab-panel-dasoan"),
  caidat: document.getElementById("tab-panel-caidat"),
};
const elDocsContainer = document.getElementById("docs-list-container");
const elBtnRefreshDocs = document.getElementById("btn-refresh-docs");
const elProvidersContainer = document.getElementById("providers-list-container");
const elOptMultiComma = document.getElementById("opt-multi-comma");
const elOptMultiJoined = document.getElementById("opt-multi-joined");
const elBtnOpenFolderSettings = document.getElementById("btn-open-folder-settings");
const elBtnCleanData = document.getElementById("btn-clean-data");

function showNotice(msg) {
  if (!elUiNoticeBox) return;
  elUiNoticeBox.innerText = msg;
  elUiNoticeBox.style.display = "block";
}

function hideNotice() {
  if (elUiNoticeBox) elUiNoticeBox.style.display = "none";
}

function log(msg, level = "info") {
  if (!elLogBox) return;
  const line = document.createElement("div");
  line.className = `log-line log-${level}`;
  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  line.innerText = `[${timeStr}] ${msg}`;
  line.title = msg;
  elLogBox.appendChild(line);
  elLogBox.scrollTop = elLogBox.scrollHeight;
}

if (elBtnCopyLog) {
  elBtnCopyLog.addEventListener("click", () => {
    const text = Array.from(elLogBox.querySelectorAll(".log-line")).map(el => el.innerText).join("\n");
    navigator.clipboard.writeText(text).then(() => {
      const orig = elBtnCopyLog.innerText;
      elBtnCopyLog.innerText = "Đã chép!";
      setTimeout(() => { elBtnCopyLog.innerText = orig; }, 1500);
    });
  });
}

function updateProgress(percent, statusText) {
  if (elProgressBar) elProgressBar.style.width = `${percent}%`;
  updateStatsLine(statusText);
}

function updateStatsLine(overrideStatus) {
  if (!elStatsSummaryLine) return;
  let text = "";
  if (state.isRunning) {
    text = `${state.processedQuestions}/${state.totalQuestions} câu · ${state.collectedComments} bình luận`;
  } else if (overrideStatus) {
    text = overrideStatus;
  } else {
    text = `${state.processedQuestions}/${state.totalQuestions} câu · ${state.collectedComments} bình luận`;
  }
  if (state.count403 > 0) {
    text += ` · ${state.count403} lỗi 403`;
  }
  elStatsSummaryLine.innerText = text;
}

// Tab Switching Logic
function switchTab(tabKey) {
  state.activeTab = tabKey;
  tabButtons.forEach(btn => {
    if (btn.dataset.tab === tabKey) btn.classList.add("active");
    else btn.classList.remove("active");
  });
  Object.keys(tabPanels).forEach(key => {
    if (key === tabKey && tabPanels[key]) tabPanels[key].classList.add("active");
    else if (tabPanels[key]) tabPanels[key].classList.remove("active");
  });

  if (tabKey === "dasoan") {
    loadDocuments();
  } else if (tabKey === "caidat") {
    loadSettings();
  }
}

tabButtons.forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Load Documents for Tab "Đã soạn"
async function loadDocuments() {
  if (!elDocsContainer) return;
  elDocsContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 12px;">Đang tải danh sách tài liệu...</div>';
  try {
    const res = await apiFetch("/api/user/documents");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const docs = await res.json();
    state.documentsData = docs;

    if (!docs || docs.length === 0) {
      elDocsContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">Chưa có tài liệu nào được soạn.</div>';
      return;
    }

    elDocsContainer.innerHTML = "";
    docs.forEach(doc => {
      const item = document.createElement("div");
      item.className = "doc-item";

      const timeStr = doc.created_at || "--:--";
      item.innerHTML = `
        <div class="doc-item-title" title="${doc.exam_title || doc.filename}">${doc.exam_title || doc.filename}</div>
        <div class="doc-item-meta">
          <span>${doc.questions_count} câu · ${doc.size_formatted}</span>
          <span>${timeStr}</span>
        </div>
        <div class="doc-item-actions">
          <a class="btn-secondary btn-download" style="font-size: 11px; padding: 3px 6px;" href="${BACKEND_URL}${doc.download_url}" target="_blank">Tải file</a>
          <button class="btn-secondary btn-open-doc-folder" style="font-size: 11px; padding: 3px 6px;">Mở thư mục</button>
          <button class="btn-secondary btn-re-ingest-doc" style="font-size: 11px; padding: 3px 6px;">Cập nhật</button>
        </div>
      `;

      item.querySelector(".btn-open-doc-folder").addEventListener("click", async () => {
        try {
          await apiFetch("/api/exports/open-folder", { method: "POST" });
        } catch (e) {
          log(`Lỗi mở thư mục: ${e.message}`, "warn");
        }
      });

      item.querySelector(".btn-re-ingest-doc").addEventListener("click", () => {
        switchTab("soande");
        // Pre-fill thread URL based on subject/title if available
        if (elInputThreadUrl && doc.filename) {
          const matchCode = doc.filename.match(/^([A-Za-z0-9]+)/);
          log(`Đã chọn đề: ${doc.filename}. Bạn có thể kiểm tra URL và bấm Cập nhật bình luận.`, "info");
        }
      });

      elDocsContainer.appendChild(item);
    });
  } catch (e) {
    elDocsContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 8px;">Không thể tải danh sách tài liệu: ${e.message}</div>`;
  }
}

if (elBtnRefreshDocs) {
  elBtnRefreshDocs.addEventListener("click", loadDocuments);
}

// Load Settings for Tab "Cài đặt"
async function loadSettings() {
  if (!elProvidersContainer) return;
  elProvidersContainer.innerHTML = '<div style="color: var(--muted); font-size: 11px;">Đang tải cấu hình...</div>';
  try {
    const res = await apiFetch("/api/settings");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.settingsData = data;

    // Multi choice format radio
    const multiFmt = data.export?.multi_choice_format || "comma";
    if (multiFmt === "joined") {
      if (elOptMultiJoined) elOptMultiJoined.checked = true;
    } else {
      if (elOptMultiComma) elOptMultiComma.checked = true;
    }

    // Providers
    const providers = data.ai?.providers || [];
    elProvidersContainer.innerHTML = "";

    providers.forEach((p, idx) => {
      const pRow = document.createElement("div");
      pRow.className = "provider-row";

      const isInvalid = p.key_invalid || p.status === "key_invalid";
      const masked = p.masked_key || (p.has_api_key ? "•••• Đã lưu" : "Chưa có khoá");
      const isEnabled = p.enabled ?? true;

      pRow.innerHTML = `
        <div class="provider-header">
          <span style="font-weight: 600; font-size: 12px; text-transform: uppercase;">${p.name}</span>
          <div style="display: flex; gap: 4px; align-items: center;">
            ${isInvalid ? '<span class="badge-invalid">Khoá không hợp lệ</span>' : ''}
            <label style="display: inline-flex; align-items: center; gap: 3px; font-size: 11px; cursor: pointer;">
              <input type="checkbox" class="check-provider-toggle" ${isEnabled ? "checked" : ""} />
              <span>${isEnabled ? "Bật" : "Tắt"}</span>
            </label>
          </div>
        </div>
        <div style="font-size: 11px; color: var(--muted);">${p.model} · ${masked}</div>
        <div style="display: flex; gap: 4px; margin-top: 2px;">
          <input type="password" class="thread-url-input input-api-key" placeholder="Nhập khoá mới để lưu" style="font-size: 11px; padding: 4px 6px;" />
          <button class="btn-secondary btn-save-key" style="flex: 0; padding: 4px 8px; font-size: 11px;">Lưu</button>
        </div>
      `;

      // Toggle provider enabled
      pRow.querySelector(".check-provider-toggle").addEventListener("change", async (e) => {
        const checked = e.target.checked;
        try {
          const payload = { ...state.settingsData };
          payload.ai.providers[idx].enabled = checked;
          await apiFetch("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          log(`Đã ${checked ? "bật" : "tắt"} provider ${p.name}`, "info");
        } catch (err) {
          log(`Lỗi cập nhật provider: ${err.message}`, "error");
        }
      });

      // Save new API key (Write-only)
      pRow.querySelector(".btn-save-key").addEventListener("click", async () => {
        const keyInput = pRow.querySelector(".input-api-key");
        const newKey = keyInput.value.trim();
        if (!newKey) return;
        try {
          const payload = { ...state.settingsData };
          payload.ai.providers[idx].api_key = newKey;
          await apiFetch("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          keyInput.value = "";
          log(`Đã cập nhật khoá mới cho ${p.name}`, "success");
          loadSettings();
        } catch (err) {
          log(`Lỗi lưu khoá: ${err.message}`, "error");
        }
      });

      elProvidersContainer.appendChild(pRow);
    });

  } catch (e) {
    elProvidersContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px;">Lỗi tải cài đặt: ${e.message}</div>`;
  }
}

// Multi-choice format change listener
[elOptMultiComma, elOptMultiJoined].forEach(radio => {
  if (radio) {
    radio.addEventListener("change", async () => {
      const val = elOptMultiJoined && elOptMultiJoined.checked ? "joined" : "comma";
      if (!state.settingsData) return;
      try {
        const payload = { ...state.settingsData };
        if (!payload.export) payload.export = {};
        payload.export.multi_choice_format = val;
        await apiFetch("/api/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        log(`Đã đổi định dạng đa đáp án sang: ${val === "joined" ? "ABC" : "A, B, C"}`, "info");
      } catch (err) {
        log(`Lỗi lưu định dạng: ${err.message}`, "error");
      }
    });
  }
});

if (elBtnOpenFolderSettings) {
  elBtnOpenFolderSettings.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
    } catch (e) {
      log(`Lỗi mở thư mục: ${e.message}`, "warn");
    }
  });
}

if (elBtnCleanData) {
  elBtnCleanData.addEventListener("click", async () => {
    if (!confirm("Dọn dẹp ảnh tạm của các đề thi đã hoàn tất?")) return;
    try {
      const res = await apiFetch("/api/settings/clean-data", { method: "POST" });
      const data = await res.json();
      log(`Đã dọn dẹp dữ liệu tạm (${data.message || "hoàn tất"}).`, "info");
    } catch (e) {
      log(`Lỗi dọn dữ liệu: ${e.message}`, "warn");
    }
  });
}

// IndexedDB Helper
const IDB_NAME = "docxstacked_offline_cache";
const IDB_STORE = "crawled_exams";

function openIndexedDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) {
        db.createObjectStore(IDB_STORE, { keyPath: "exam_url" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveExamToIndexedDB(examData) {
  try {
    const db = await openIndexedDB();
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).put(examData);
    await new Promise((res, rej) => {
      tx.oncomplete = res;
      tx.onerror = rej;
    });
  } catch (err) {
    console.warn("saveExamToIndexedDB error:", err);
  }
}

async function getExamFromIndexedDB(examUrl) {
  try {
    const db = await openIndexedDB();
    const tx = db.transaction(IDB_STORE, "readonly");
    const req = tx.objectStore(IDB_STORE).get(examUrl);
    return new Promise((resolve) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function deleteExamFromIndexedDB(examUrl) {
  try {
    const db = await openIndexedDB();
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).delete(examUrl);
    await new Promise((res) => {
      tx.oncomplete = res;
      tx.onerror = res;
    });
  } catch (err) {
    console.warn("deleteExamFromIndexedDB error:", err);
  }
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 1. Check Backend Connectivity
async function checkBackend() {
  try {
    const res = await apiFetch("/api/health", { method: "GET" });
    if (res.ok) {
      elBackendStatus.className = "status-chip chip-online";
      elBackendStatus.innerText = "Backend Online";
      return true;
    }
  } catch (e) {
    // Offline
  }
  elBackendStatus.className = "status-chip chip-offline";
  elBackendStatus.innerText = "Backend Offline";
  return false;
}

// 2. Check FUOverflow Authentication
async function checkFuOverflowAuth() {
  try {
    const res = await fetch("https://fuoverflow.com/", {
      method: "GET",
      credentials: "include",
    });

    if (!res.ok) return false;

    const html = await res.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");

    const isLoggedIn = doc.documentElement.getAttribute("data-logged-in") === "true";
    if (isLoggedIn) {
      let username = "Thành viên";
      const userEl = doc.querySelector(".p-navgroup-link--user .p-navgroup-linkText, .username--style1, .username--style2, [data-xf-init='member-tooltip']");
      if (userEl && userEl.innerText.trim()) {
        username = userEl.innerText.trim();
      }

      // Notify backend immediately
      try {
        await apiFetch("/api/auth/extension-heartbeat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ logged_in: true, username: username }),
        });
      } catch (e) {}

      return true;
    } else {
      try {
        await apiFetch("/api/auth/extension-heartbeat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ logged_in: false, username: null }),
        });
      } catch (e) {}
      return false;
    }
  } catch (err) {
    return false;
  }
}

// Check if current thread URL already exists in backend
async function checkExamAlreadyCompiled(url) {
  if (!url || !url.includes("fuoverflow.com/threads/")) {
    if (elReopenCard) elReopenCard.style.display = "none";
    state.existingExam = null;
    return;
  }
  try {
    const res = await apiFetch(`/api/ingest/check-exam?url=${encodeURIComponent(url)}`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      if (data.exists) {
        state.existingExam = data;
        if (elReopenCard && elReopenText && elBtnReopenDownload) {
          const timeLabel = data.compiled_time_short || data.compiled_at || "--:--";
          elReopenText.innerText = `Đã soạn lúc ${timeLabel} (${data.question_count} câu)`;
          elBtnReopenDownload.href = `${BACKEND_URL}${data.download_url}`;
          elReopenCard.style.display = "flex";
        }
        return;
      }
    }
  } catch (e) {
    // Offline or check failed
  }
  if (elReopenCard) elReopenCard.style.display = "none";
  state.existingExam = null;
}

// Fetch with Cadence & Retry
async function fetchWithCadence(url, maxRetries = 3) {
  let delay = 1000;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    if (state.isStopped) throw new Error("USER_STOPPED");
    try {
      const res = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" },
      });

      if (res.status === 403) {
        state.count403++;
        updateStatsLine();
      }
      return res;
    } catch (err) {
      if (attempt === maxRetries) throw err;
      state.countRetries++;
      await sleep(delay);
      delay = delay * 2;
    }
  }
  throw new Error(`Thất bại sau ${maxRetries} lần thử: ${url}`);
}

async function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function parseCommentsFromHtml(htmlStr) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(htmlStr, "text/html");
  const commentEls = doc.querySelectorAll(".message--comment, .message--mediaComment, .js-comment");
  const comments = [];

  commentEls.forEach((c) => {
    const rawId = c.getAttribute("data-content") || c.getAttribute("id") || "";
    const mId = rawId.match(/\d+/);
    const commentId = mId ? mId[0] : null;

    const authorEl = c.querySelector(".message-name, .comment-user, .username, .comment-author");
    const authorName = authorEl ? authorEl.innerText.trim() : (c.getAttribute("data-author") || "Unknown");

    const rxBar = c.querySelector(".reactionsBar");
    let upvotes = 0;
    if (rxBar) {
      const nums = rxBar.innerText.match(/\d+/);
      if (nums) upvotes = parseInt(nums[0], 10);
      else if (rxBar.querySelectorAll("li, a, bdo").length > 0) {
        upvotes = rxBar.querySelectorAll("li, a, bdo").length;
      }
    }

    const timeEl = c.querySelector("time");
    const postedAt = timeEl ? (timeEl.getAttribute("datetime") || timeEl.innerText.trim()) : null;

    let parentId = null;
    let isReply = false;
    const parentAttr = c.getAttribute("data-parent-id");
    if (parentAttr) {
      const pm = parentAttr.match(/\d+/);
      if (pm) {
        parentId = parseInt(pm[0], 10);
        isReply = true;
      }
    }

    const bodyEl = c.querySelector(".message-body .bbWrapper, .comment-content, .message-content");
    const rawText = bodyEl ? bodyEl.innerText.trim() : "";

    if (rawText) {
      comments.push({
        comment_id: commentId,
        author_name: authorName,
        raw_text: rawText,
        upvotes: upvotes,
        quoted_comment_id: parentId,
        is_reply: isReply,
        posted_at: postedAt,
      });
    }
  });

  return comments;
}

// Main Ingestion Loop
async function startIngestion(options = {}) {
  const isCommentUpdateOnly = options.commentOnly || false;
  const redownloadImages = options.redownloadImages ?? true;

  if (state.isRunning) return;

  hideNotice();
  const url = elInputThreadUrl.value.trim();
  if (!url || !url.includes("fuoverflow.com/threads/")) {
    showNotice("Vui lòng nhập hoặc đồng bộ URL đề thi hợp lệ trên fuoverflow.com!");
    return;
  }

  // 1. Verify Backend Connectivity before starting
  try {
    const pingRes = await apiFetch("/api/ingest/ping", { method: "GET" });
    if (!pingRes.ok) {
      showNotice("Lỗi xác thực với backend (401/403). Kiểm tra Token hoặc Extension ID!");
      return;
    }
  } catch (e) {
    showNotice("Backend chưa chạy. Mở terminal và chạy: python run_dev.py");
    return;
  }

  // 2. Verify FUOverflow login
  const isAuth = await checkFuOverflowAuth();
  if (!isAuth) {
    showNotice("Chưa đăng nhập FUOverflow. Mở fuoverflow.com và đăng nhập trước khi soạn!");
    return;
  }

  // Set running UI state
  state.isRunning = true;
  state.isStopped = false;
  state.processedQuestions = 0;
  state.collectedComments = 0;
  state.crawledPages = 0;
  state.count403 = 0;
  state.countRetries = 0;

  elBtnMainAction.innerText = "Dừng";
  elBtnMainAction.className = "btn-main btn-stop";
  if (elResultCard) elResultCard.style.display = "none";
  if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";

  const modeText = isCommentUpdateOnly ? "Cập nhật bình luận..." : "Bắt đầu tải đề thi...";
  updateProgress(5, modeText);
  log(isCommentUpdateOnly ? "Bắt đầu chế độ cập nhật bình luận..." : "Bắt đầu thu thập dữ liệu đề thi...", "info");

  const existingMediaSet = new Set(
    (!redownloadImages && state.existingExam && state.existingExam.existing_media_ids)
      ? state.existingExam.existing_media_ids
      : []
  );

  const questionsData = [];
  let subjectCode = "TEST";
  let threadTitle = "Đề thi FuOverflow";

  try {
    // Step 1: Fetch thread main page
    const threadRes = await fetchWithCadence(url);
    if (!threadRes.ok) {
      throw new Error(`Không thể mở trang đề thi (HTTP ${threadRes.status})`);
    }

    const threadHtml = await threadRes.text();
    const parser = new DOMParser();
    const threadDoc = parser.parseFromString(threadHtml, "text/html");

    const titleEl = threadDoc.querySelector("h1.p-title-value, title");
    threadTitle = titleEl ? titleEl.innerText.replace(" | FuOverflow Community", "").trim() : elThreadTitleDisplay.innerText;
    elThreadTitleDisplay.innerText = threadTitle;
    elThreadTitleDisplay.title = threadTitle;

    const mCode = threadTitle.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
    if (mCode) subjectCode = mCode[1].toUpperCase();

    const attachmentItems = threadDoc.querySelectorAll("section.message-attachments ul.attachmentList li.file");
    if (!attachmentItems.length) {
      throw new Error("Không tìm thấy danh sách câu hỏi đính kèm trong thread này.");
    }

    state.totalQuestions = attachmentItems.length;
    updateStatsLine();
    log(`Tìm thấy ${state.totalQuestions} câu hỏi. Đang xử lý...`, "info");

    // Step 2: Loop questions
    for (let idx = 0; idx < attachmentItems.length; idx++) {
      if (state.isStopped) throw new Error("USER_STOPPED");

      const item = attachmentItems[idx];
      const qIndex = idx + 1;

      const nameEl = item.querySelector(".file-name");
      const fileName = nameEl ? nameEl.innerText.trim() : `Q${qIndex}.webp`;

      const previewEl = item.querySelector("a.file-preview");
      const sidebarHref = previewEl ? previewEl.getAttribute("data-lb-sidebar-href") || "" : "";
      const mediaPath = sidebarHref.split("?")[0];
      const mediaUrl = mediaPath.startsWith("/") ? `https://fuoverflow.com${mediaPath}` : mediaPath;
      const mId = mediaPath.match(/\/media\/[^.]+\.(\d+)/);
      const mediaId = mId ? mId[1] : null;

      let imageBase64 = null;
      let comments = [];

      if (mediaUrl) {
        await sleep(MIN_REQUEST_INTERVAL_MS);

        const mediaRes = await fetchWithCadence(mediaUrl);
        if (mediaRes.ok) {
          state.crawledPages++;
          const mediaHtml = await mediaRes.text();
          const mediaDoc = parser.parseFromString(mediaHtml, "text/html");

          comments = parseCommentsFromHtml(mediaHtml);
          state.collectedComments += comments.length;

          // Check if image already exists in backend and we're skipping image redownload
          const canSkipImage = mediaId && existingMediaSet.has(mediaId);

          if (!canSkipImage) {
            const fullImgEl = mediaDoc.querySelector("img.js-mediaImage, .media-container img");
            if (fullImgEl && fullImgEl.getAttribute("src")) {
              const rawSrc = fullImgEl.getAttribute("src");
              const fullImgUrl = rawSrc.startsWith("/") ? `https://fuoverflow.com${rawSrc}` : rawSrc;

              await sleep(500);
              const imgRes = await fetchWithCadence(fullImgUrl);
              if (imgRes.ok) {
                const blob = await imgRes.blob();
                imageBase64 = await blobToBase64(blob);
              }
            }
          } else {
            log(`[${qIndex}/${state.totalQuestions}] Câu ${qIndex}: Dùng ảnh gốc đã có trên hệ thống.`, "info");
          }
        }
      }

      questionsData.push({
        index: qIndex,
        file_name: fileName,
        media_id: mediaId,
        media_url: mediaUrl,
        image_base64: imageBase64,
        comments: comments,
      });

      state.processedQuestions++;
      updateStatsLine();
      const pct = 10 + Math.round((state.processedQuestions / state.totalQuestions) * 75);
      const statusMsg = isCommentUpdateOnly ? `Cập nhật câu ${qIndex}/${state.totalQuestions}` : `Đã thu thập câu ${qIndex}/${state.totalQuestions}`;
      updateProgress(pct, statusMsg);
    }

    // Step 3: Buffer in IndexedDB & send to backend
    const examBuffer = {
      subject_code: subjectCode,
      exam_title: threadTitle,
      exam_url: url,
      questions: questionsData,
      crawled_at: Date.now(),
      comments_count: state.collectedComments,
    };
    await saveExamToIndexedDB(examBuffer);
    await sendPayloadToBackend(examBuffer);

  } catch (err) {
    if (err.message === "USER_STOPPED") {
      log("Đã dừng tiến trình theo yêu cầu.", "warn");
      updateProgress(0, "Đã dừng");
    } else {
      log(`Lỗi: ${err.message}`, "error");
      updateProgress(0, "Gặp lỗi");
      if (questionsData.length > 0 && elOfflineRecoveryRow) {
        elOfflineRecoveryRow.style.display = "flex";
      }
    }
  } finally {
    state.isRunning = false;
    elBtnMainAction.innerText = "Bắt đầu soạn";
    elBtnMainAction.className = "btn-main btn-start";
    checkExamAlreadyCompiled(url);
  }
}

async function sendPayloadToBackend(examBuffer) {
  if (state.isStopped) throw new Error("USER_STOPPED");
  log("Đang gửi dữ liệu sang Backend xuất file Word...", "info");
  updateProgress(88, "Backend đang xuất file Word...");

  const payload = {
    subject_code: examBuffer.subject_code,
    exam_title: examBuffer.exam_title,
    exam_url: examBuffer.exam_url,
    questions: examBuffer.questions,
    options: {
      answer_format: "letter_keyword",
      multi_choice_format: elOptMultiJoined && elOptMultiJoined.checked ? "joined" : "comma",
      ai_enabled: true,
    },
  };

  const ingestRes = await apiFetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!ingestRes.ok) {
    const errText = await ingestRes.text();
    if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "flex";
    throw new Error(`Backend từ chối (${ingestRes.status}): ${errText}`);
  }

  const result = await ingestRes.json();
  log(`Xuất file Word thành công: ${result.docx_filename}`, "success");
  updateProgress(100, "Hoàn tất!");

  await deleteExamFromIndexedDB(examBuffer.exam_url);
  if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";

  // Show result card
  if (elResultFilename && elResultDownloadBtn && elResultCard) {
    elResultFilename.innerText = `${result.docx_filename}`;
    elResultDownloadBtn.href = `${BACKEND_URL}${result.download_url}`;
    elResultCard.style.display = "flex";
  }
}

// Main Button Toggle (Bắt đầu soạn / Dừng)
elBtnMainAction.addEventListener("click", () => {
  if (state.isRunning) {
    state.isStopped = true;
    log("Đang gửi tín hiệu dừng...", "warn");
  } else {
    startIngestion({ commentOnly: false, redownloadImages: true });
  }
});

// Reopen Actions: Cập nhật bình luận
if (elBtnReopenUpdate) {
  elBtnReopenUpdate.addEventListener("click", () => {
    const redownload = elCheckRedownloadImages ? elCheckRedownloadImages.checked : false;
    startIngestion({ commentOnly: true, redownloadImages: redownload });
  });
}

// Result Action: Mở thư mục
if (elBtnOpenFolder) {
  elBtnOpenFolder.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
      log("Đã mở thư mục chứa file Word.", "info");
    } catch (e) {
      log(`Không thể mở thư mục: ${e.message}`, "warn");
    }
  });
}

// Retry ingest from IndexedDB
if (elBtnRetryIngest) {
  elBtnRetryIngest.addEventListener("click", async () => {
    const url = elInputThreadUrl.value.trim();
    const bufferedExam = await getExamFromIndexedDB(url);
    if (!bufferedExam) {
      showNotice("Không tìm thấy dữ liệu đệm trong máy!");
      if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";
      return;
    }
    try {
      log(`[IndexedDB] Đang gửi lại ${bufferedExam.questions.length} câu từ bộ đệm...`, "info");
      await sendPayloadToBackend(bufferedExam);
    } catch (err) {
      log(`[Gửi lại thất bại] ${err.message}`, "error");
    }
  });
}

// Clear buffered data
if (elBtnClearIdb) {
  elBtnClearIdb.addEventListener("click", async () => {
    const url = elInputThreadUrl.value.trim();
    await deleteExamFromIndexedDB(url);
    if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";
    log("Đã xoá dữ liệu đệm lưu tạm.", "warn");
  });
}

// Sync from Active Tab
async function syncFromActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0] && tabs[0].url) {
      const tabUrl = tabs[0].url;
      if (tabUrl.includes("fuoverflow.com/threads/")) {
        const cleanUrl = tabUrl.split("?")[0];
        elInputThreadUrl.value = cleanUrl;
        const cleanTitle = (tabs[0].title || "").replace(" | FuOverflow Community", "").trim();
        elThreadTitleDisplay.innerText = cleanTitle;
        elThreadTitleDisplay.title = cleanTitle;
        hideNotice();
        checkExamAlreadyCompiled(cleanUrl);
      } else {
        showNotice("Tab hiện tại không phải trang đề thi FuOverflow (/threads/...)!");
      }
    }
  } catch (e) {
    log(`Lỗi đồng bộ tab: ${e.message}`, "error");
  }
}

elBtnSyncTab.addEventListener("click", syncFromActiveTab);

// Auto-read active tab on startup & activation
async function autoReadActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0] && tabs[0].url) {
      const tabUrl = tabs[0].url;
      if (tabUrl.includes("fuoverflow.com/threads/")) {
        const cleanUrl = tabUrl.split("?")[0];
        if (!elInputThreadUrl.value || elInputThreadUrl.value !== cleanUrl) {
          elInputThreadUrl.value = cleanUrl;
          const cleanTitle = (tabs[0].title || "").replace(" | FuOverflow Community", "").trim();
          elThreadTitleDisplay.innerText = cleanTitle;
          elThreadTitleDisplay.title = cleanTitle;
          checkExamAlreadyCompiled(cleanUrl);
        }
      }
    }
  } catch (e) {}
}

if (chrome.tabs && chrome.tabs.onActivated) {
  chrome.tabs.onActivated.addListener(() => {
    if (!state.isRunning) {
      autoReadActiveTab();
    }
  });
}

// Listen for message from content script
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "THREAD_SELECTED" && msg.data) {
    elInputThreadUrl.value = msg.data.url;
    elThreadTitleDisplay.innerText = msg.data.title;
    elThreadTitleDisplay.title = msg.data.title;
    checkExamAlreadyCompiled(msg.data.url);
  }
});

// Restore saved settings
chrome.storage.local.get(["activeThread", "ingestToken"], (res) => {
  if (res.activeThread && !elInputThreadUrl.value) {
    elInputThreadUrl.value = res.activeThread.url;
    elThreadTitleDisplay.innerText = res.activeThread.title;
    checkExamAlreadyCompiled(res.activeThread.url);
  }
  if (res.ingestToken && elInputIngestToken) {
    elInputIngestToken.value = res.ingestToken;
  }
});

// URL input change listener to recheck already compiled exam
elInputThreadUrl.addEventListener("change", () => {
  checkExamAlreadyCompiled(elInputThreadUrl.value.trim());
});

// Initialize
checkBackend();
checkFuOverflowAuth();
autoReadActiveTab();
setInterval(checkBackend, 10000);
