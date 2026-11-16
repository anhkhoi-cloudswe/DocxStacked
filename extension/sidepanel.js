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
const elBtnReopenOpenFolder = document.getElementById("btn-reopen-open-folder");
const elBtnReopenUpdate = document.getElementById("btn-reopen-update");
const elCheckRedownloadImages = document.getElementById("check-redownload-images");

// Tab elements
const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = {
  soande: document.getElementById("tab-panel-soande"),
  chonde: document.getElementById("tab-panel-chonde"),
  dasoan: document.getElementById("tab-panel-dasoan"),
  caidat: document.getElementById("tab-panel-caidat"),
};
const elDocsContainer = document.getElementById("docs-list-container");
const elBtnRefreshDocs = document.getElementById("btn-refresh-docs");
const elCheckSelectAllDasoan = document.getElementById("check-select-all-dasoan");
const elBadgeDasoanSelected = document.getElementById("badge-dasoan-selected");
const elBtnDownloadSelectedZip = document.getElementById("btn-download-selected-zip");
const elBtnDownloadSubjectFolder = document.getElementById("btn-download-subject-folder");
const elBtnOpenFolderDasoan = document.getElementById("btn-open-folder-dasoan");

// Chọn đề elements
const elSelectSubject = document.getElementById("select-subject");
const elBtnFetchSubjectExams = document.getElementById("btn-fetch-subject-exams");
const elInputSearchExams = document.getElementById("input-search-exams");
const filterButtonsChonde = document.querySelectorAll(".chonde-filter-btn");
const elCheckSelectAllChonde = document.getElementById("check-select-all-chonde");
const elBadgeChondeSelected = document.getElementById("badge-chonde-selected");
const elCheckUpdateCompiled = document.getElementById("check-update-compiled");
const elBtnStartQueue = document.getElementById("btn-start-queue");
const elQueueControlsRow = document.getElementById("queue-controls-row");
const elBtnQueuePause = document.getElementById("btn-queue-pause");
const elBtnQueueSkip = document.getElementById("btn-queue-skip");
const elBtnQueueRetry = document.getElementById("btn-queue-retry");
const elQueueProgressCard = document.getElementById("queue-progress-card");
const elQueueProgressTitle = document.getElementById("queue-progress-title");
const elQueueProgressBar = document.getElementById("queue-progress-bar");
const elQueueProgressSub = document.getElementById("queue-progress-sub");
const elQueueCompletedBanner = document.getElementById("queue-completed-banner");
const elQueueCompletedMsg = document.getElementById("queue-completed-msg");
const elBtnQueueDownloadAll = document.getElementById("btn-queue-download-all");
const elChondeListContainer = document.getElementById("chonde-list-container");
const elInputBatchLimit = document.getElementById("input-batch-limit");
const elLinkOpenDashboard = document.getElementById("link-open-dashboard");
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
  } else if (tabKey === "chonde") {
    loadSubjectsDropdown();
  } else if (tabKey === "caidat") {
    loadSettings();
  }
}

tabButtons.forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// Load Documents for Tab "Đã soạn" with checkboxes and subject grouping
const selectedDocs = new Set();

function updateDasoanSelectionBadge() {
  if (elBadgeDasoanSelected) {
    elBadgeDasoanSelected.innerText = `${selectedDocs.size} đã chọn`;
  }
}

async function loadDocuments() {
  if (!elDocsContainer) return;
  elDocsContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 12px;">Đang tải danh sách tài liệu...</div>';
  selectedDocs.clear();
  updateDasoanSelectionBadge();
  if (elCheckSelectAllDasoan) elCheckSelectAllDasoan.checked = false;

  try {
    const res = await apiFetch("/api/user/documents");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const docs = await res.json();
    state.documentsData = docs;

    if (!docs || docs.length === 0) {
      elDocsContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">Chưa có tài liệu nào được soạn.</div>';
      return;
    }

    // Group documents by subject code
    const grouped = {};
    docs.forEach(doc => {
      const code = (doc.subject_code || (doc.filename && doc.filename.split(/[\s\-_]/)[0]) || "KHAC").toUpperCase();
      if (!grouped[code]) grouped[code] = [];
      grouped[code].push(doc);
    });

    elDocsContainer.innerHTML = "";

    Object.keys(grouped).sort().forEach(subjCode => {
      const groupHeader = document.createElement("div");
      groupHeader.className = "subject-group-header";
      groupHeader.innerHTML = `
        <span>${subjCode} (${grouped[subjCode].length} đề)</span>
        <label style="display: inline-flex; align-items: center; gap: 3px; font-size: 10px; cursor: pointer; color: #94a3b8; font-weight: normal;">
          <input type="checkbox" class="check-group-select" data-subject="${subjCode}" />
          <span>Chọn nhóm</span>
        </label>
      `;
      elDocsContainer.appendChild(groupHeader);

      const groupCheckboxes = [];

      grouped[subjCode].forEach(doc => {
        const item = document.createElement("div");
        item.className = "doc-item";

        const timeStr = doc.created_at || "--:--";
        item.innerHTML = `
          <div class="doc-item-row">
            <input type="checkbox" class="doc-checkbox" data-filename="${doc.filename}" style="margin-top: 2px; cursor: pointer;" />
            <div style="flex: 1; min-width: 0;">
              <div class="doc-item-title" title="${doc.exam_title || doc.filename}">${doc.exam_title || doc.filename}</div>
              <div class="doc-item-meta" style="margin-top: 2px;">
                <span>${doc.questions_count} câu · ${doc.size_formatted}</span>
                <span>${timeStr}</span>
              </div>
            </div>
          </div>
          <div class="doc-item-actions" style="margin-left: 20px;">
            <a class="btn-secondary btn-download" style="font-size: 11px; padding: 2px 6px;" href="${BACKEND_URL}${doc.download_url}" target="_blank">Tải file</a>
            <button class="btn-secondary btn-open-doc-folder" style="font-size: 11px; padding: 2px 6px;">Mở thư mục</button>
            <button class="btn-secondary btn-re-ingest-doc" style="font-size: 11px; padding: 2px 6px;">Cập nhật</button>
          </div>
        `;

        const cb = item.querySelector(".doc-checkbox");
        groupCheckboxes.push(cb);

        cb.addEventListener("change", () => {
          if (cb.checked) {
            selectedDocs.add(doc.filename);
          } else {
            selectedDocs.delete(doc.filename);
          }
          updateDasoanSelectionBadge();
        });

        item.querySelector(".btn-open-doc-folder").addEventListener("click", async () => {
          try {
            await apiFetch("/api/exports/open-folder", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ subject: subjCode }),
            });
          } catch (e) {
            log(`Lỗi mở thư mục: ${e.message}`, "warn");
          }
        });

        item.querySelector(".btn-re-ingest-doc").addEventListener("click", () => {
          switchTab("soande");
          if (elInputThreadUrl && doc.filename) {
            log(`Đã chọn đề: ${doc.filename}. Bạn có thể kiểm tra URL và bấm Cập nhật bình luận.`, "info");
          }
        });

        elDocsContainer.appendChild(item);
      });

      // Group select checkbox
      const groupCb = groupHeader.querySelector(".check-group-select");
      groupCb.addEventListener("change", () => {
        const checked = groupCb.checked;
        groupCheckboxes.forEach(cb => {
          cb.checked = checked;
          const fn = cb.dataset.filename;
          if (checked) selectedDocs.add(fn);
          else selectedDocs.delete(fn);
        });
        updateDasoanSelectionBadge();
      });
    });

  } catch (e) {
    elDocsContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 8px;">Không thể tải danh sách tài liệu: ${e.message}</div>`;
  }
}

// Select All in Đã soạn
if (elCheckSelectAllDasoan) {
  elCheckSelectAllDasoan.addEventListener("change", () => {
    const checked = elCheckSelectAllDasoan.checked;
    const allCbs = elDocsContainer.querySelectorAll(".doc-checkbox, .check-group-select");
    allCbs.forEach(cb => {
      cb.checked = checked;
      if (cb.classList.contains("doc-checkbox")) {
        const fn = cb.dataset.filename;
        if (checked) selectedDocs.add(fn);
        else selectedDocs.delete(fn);
      }
    });
    updateDasoanSelectionBadge();
  });
}

// Download selected docs as ZIP (using chrome.downloads or window.open)
if (elBtnDownloadSelectedZip) {
  elBtnDownloadSelectedZip.addEventListener("click", () => {
    if (selectedDocs.size === 0) {
      log("Vui lòng chọn ít nhất một đề để tải ZIP!", "warn");
      return;
    }
    const filesParam = Array.from(selectedDocs).map(f => encodeURIComponent(f)).join(",");
    const downloadUrl = `${BACKEND_URL}/api/exports/bundle.zip?files=${filesParam}`;
    triggerFileDownload(downloadUrl, `DocxStacked_Selected_${new Date().toISOString().slice(0, 10)}.zip`);
  });
}

// Download entire subject folder as ZIP
if (elBtnDownloadSubjectFolder) {
  elBtnDownloadSubjectFolder.addEventListener("click", () => {
    // If a subject is selected or files from a single subject, use that subject
    const selectedList = Array.from(selectedDocs);
    let subjectParam = "";
    if (selectedList.length > 0) {
      const match = selectedList[0].match(/^([A-Za-z0-9]+)/);
      if (match) subjectParam = match[1].toUpperCase();
    }
    if (!subjectParam && state.documentsData && state.documentsData.length > 0) {
      subjectParam = state.documentsData[0].subject_code || "EXAMS";
    }
    if (!subjectParam) {
      log("Không xác định được môn cần tải cả thư mục!", "warn");
      return;
    }
    const downloadUrl = `${BACKEND_URL}/api/exports/bundle.zip?subject=${encodeURIComponent(subjectParam)}`;
    triggerFileDownload(downloadUrl, `${subjectParam}_All_${new Date().toISOString().slice(0, 10)}.zip`);
  });
}

// Open folder in Đã soạn
if (elBtnOpenFolderDasoan) {
  elBtnOpenFolderDasoan.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
    } catch (e) {
      log(`Lỗi mở thư mục: ${e.message}`, "warn");
    }
  });
}

// Helper: trigger file download via chrome.downloads API or fallback anchor
function triggerFileDownload(url, filename) {
  if (typeof chrome !== "undefined" && chrome.downloads && chrome.downloads.download) {
    chrome.downloads.download({ url: url, filename: filename, saveAs: false }, (downloadId) => {
      if (chrome.runtime.lastError) {
        log(`chrome.downloads lỗi: ${chrome.runtime.lastError.message}, mở tab thay thế...`, "warn");
        window.open(url, "_blank");
      } else {
        log(`Đang tải file: ${filename} (ID: ${downloadId})`, "info");
      }
    });
  } else {
    window.open(url, "_blank");
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
              <input type="checkbox" class="check-provider-toggle" ${isEnabled && !isInvalid ? "checked" : ""} ${isInvalid || !p.has_api_key ? "disabled" : ""} />
              <span>${isEnabled && !isInvalid ? "Bật" : "Tắt"}</span>
            </label>
          </div>
        </div>
        <div class="provider-meta-line" style="font-size: 11px; color: var(--muted);">${p.model} · <span class="provider-masked-key">${masked}</span></div>
        <div class="provider-action-status" style="font-size: 11px; margin-top: 2px; display: none;"></div>
        <div style="display: flex; gap: 4px; margin-top: 4px; flex-wrap: wrap;">
          <input type="password" class="thread-url-input input-api-key" placeholder="Nhập khoá mới để lưu" style="font-size: 11px; padding: 4px 6px; flex: 1; min-width: 130px;" />
          <button class="btn-secondary btn-save-key" style="flex: 0; padding: 4px 8px; font-size: 11px;">Lưu</button>
          <button class="btn-secondary btn-test-key" style="flex: 0; padding: 4px 8px; font-size: 11px;" ${!p.has_api_key ? "disabled" : ""}>Kiểm tra</button>
          <button class="btn-secondary btn-delete-key" style="flex: 0; padding: 4px 8px; font-size: 11px; color: #fca5a5;" ${!p.has_api_key ? "disabled" : ""}>Xoá</button>
        </div>
      `;

      const statusLine = pRow.querySelector(".provider-action-status");

      // Toggle provider enabled
      pRow.querySelector(".check-provider-toggle").addEventListener("change", async (e) => {
        const checked = e.target.checked;
        if (checked && isInvalid) {
          e.target.checked = false;
          showNotice(`Không thể bật provider ${p.name} vì khoá không hợp lệ! Vui lòng lưu khoá mới và kiểm tra hợp lệ.`);
          return;
        }
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

      // Save / Change API key
      pRow.querySelector(".btn-save-key").addEventListener("click", async () => {
        const keyInput = pRow.querySelector(".input-api-key");
        const newKey = keyInput.value.trim();
        if (!newKey) return;
        try {
          const res = await apiFetch(`/api/settings/keys/${encodeURIComponent(p.name)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ api_key: newKey, api_key_env: p.api_key_env }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          keyInput.value = "";
          const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          const tail = newKey.slice(-4);
          statusLine.style.display = "block";
          statusLine.style.color = "#86efac";
          statusLine.innerText = `Đã lưu ••••${tail} lúc ${nowStr}`;
          log(`Đã cập nhật khoá mới cho ${p.name}`, "success");
          setTimeout(loadSettings, 1200);
        } catch (err) {
          statusLine.style.display = "block";
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Lỗi lưu khoá: ${err.message}`;
          log(`Lỗi lưu khoá: ${err.message}`, "error");
        }
      });

      // Delete API key
      pRow.querySelector(".btn-delete-key").addEventListener("click", async () => {
        try {
          const res = await apiFetch(`/api/settings/keys/${encodeURIComponent(p.name)}`, {
            method: "DELETE",
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          statusLine.style.display = "block";
          statusLine.style.color = "#fbbf24";
          statusLine.innerText = `Đã xoá khoá`;
          log(`Đã xoá khoá cho ${p.name}`, "warn");
          setTimeout(loadSettings, 1000);
        } catch (err) {
          statusLine.style.display = "block";
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Lỗi xoá khoá: ${err.message}`;
        }
      });

      // Test API key
      pRow.querySelector(".btn-test-key").addEventListener("click", async () => {
        statusLine.style.display = "block";
        statusLine.style.color = "var(--muted)";
        statusLine.innerText = "Đang kiểm tra kết nối...";
        try {
          const res = await apiFetch(`/api/settings/test-connection/${encodeURIComponent(p.name)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          });
          const result = await res.json();
          if (result.success) {
            statusLine.style.color = "#86efac";
            statusLine.innerText = `Hợp lệ (${result.latency_ms || 0}ms)`;
            log(`Kiểm tra ${p.name}: Hợp lệ (${result.latency_ms}ms)`, "success");
            loadSettings();
          } else {
            statusLine.style.color = "#fca5a5";
            const shortReason = (result.message || "Không hợp lệ").replace(/Lỗi xác thực.*?:/i, "").slice(0, 45);
            statusLine.innerText = `Không hợp lệ: ${shortReason}`;
            log(`Kiểm tra ${p.name}: Không hợp lệ (${result.message})`, "error");
            loadSettings();
          }
        } catch (err) {
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Không hợp lệ: ${err.message.slice(0, 40)}`;
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

// 1. Check Backend Connectivity & Dynamic Dashboard URL
async function checkBackend() {
  try {
    const res = await apiFetch("/api/health", { method: "GET" });
    if (res.ok) {
      elBackendStatus.className = "status-chip chip-online";
      elBackendStatus.innerText = "Backend Online";
      const healthData = await res.json();
      if (healthData && healthData.dashboard_url && elLinkOpenDashboard) {
        elLinkOpenDashboard.href = healthData.dashboard_url;
      }
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

// ==========================================
// TAB: CHỌN ĐỀ & BATCH QUEUE ENGINE
// ==========================================

const chondeState = {
  subjects: [],
  selectedSubject: null,
  exams: [],
  filterType: "ALL", // ALL, FE, PE
  searchQuery: "",
  selectedUrls: new Set(),
  activeQueue: [], // array of exam objects to crawl
  queueIndex: 0,
  isQueueRunning: false,
  isQueuePaused: false,
  rateLimitDelayMs: 2000,
  consecutiveFailures: 0,
};

async function loadSubjectsDropdown() {
  if (!elSelectSubject) return;
  if (chondeState.subjects.length > 0) return; // already loaded
  elSelectSubject.innerHTML = '<option value="">Đang tải danh sách môn...</option>';
  try {
    const res = await apiFetch("/api/subjects?limit=500");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    chondeState.subjects = data.items || [];
    elSelectSubject.innerHTML = '<option value="">-- Chọn môn học (' + chondeState.subjects.length + ' môn) --</option>';
    chondeState.subjects.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.code;
      opt.textContent = `${s.code} - ${s.name}`;
      elSelectSubject.appendChild(opt);
    });
  } catch (err) {
    elSelectSubject.innerHTML = `<option value="">Lỗi tải môn: ${err.message}</option>`;
  }
}

// Fetch thread list from FuOverflow in browser session (credentials: include)
async function fetchSubjectExams() {
  const code = elSelectSubject ? elSelectSubject.value.trim().toUpperCase() : "";
  if (!code) {
    log("Vui lòng chọn một môn học!", "warn");
    return;
  }
  chondeState.selectedSubject = code;
  elChondeListContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">Đang tải danh sách đề từ FuOverflow trong phiên của bạn...</div>';

  try {
    const forumUrl = `https://fuoverflow.com/forums/${encodeURIComponent(code)}/`;
    let html = "";
    try {
      const resp = await fetch(forumUrl, { method: "GET", credentials: "include" });
      if (resp.ok) {
        html = await resp.text();
      }
    } catch (netErr) {
      log(`Không thể kết nối trực tiếp FuOverflow: ${netErr.message}`, "warn");
    }

    if (!html) {
      // Fallback: request backend to list known exams
      const res = await apiFetch(`/api/subjects/${encodeURIComponent(code)}/exams?type=FE`);
      if (res.ok) {
        const items = await res.json();
        chondeState.exams = items.map(e => ({
          title: e.title,
          url: e.url,
          exam_type: e.exam_type,
          term: e.term,
          post_date: e.post_date,
          question_count: e.question_count,
          compiled: false,
          compiled_at: null,
          subject_code: code,
        }));
      }
    } else {
      // Send HTML to backend parser to avoid duplicating BeautifulSoup parsing logic
      const parseResp = await apiFetch("/api/subjects/parse-forum-html", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: html, subject_code: code }),
      });
      if (!parseResp.ok) throw new Error(`Lỗi phân tích backend: HTTP ${parseResp.status}`);
      const parsedData = await parseResp.json();
      chondeState.exams = parsedData.items || [];
    }

    renderChondeList();
  } catch (err) {
    elChondeListContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 8px;">Lỗi: ${err.message}</div>`;
  }
}

if (elBtnFetchSubjectExams) {
  elBtnFetchSubjectExams.addEventListener("click", fetchSubjectExams);
}
if (elSelectSubject) {
  elSelectSubject.addEventListener("change", () => {
    if (elSelectSubject.value) fetchSubjectExams();
  });
}

// Filter and render exams
function renderChondeList() {
  if (!elChondeListContainer) return;
  const q = (elInputSearchExams ? elInputSearchExams.value.trim().toLowerCase() : "");
  const filterType = chondeState.filterType;

  const filtered = chondeState.exams.filter(ex => {
    if (filterType !== "ALL" && ex.exam_type !== filterType) {
      if (filterType === "FE" && ex.exam_type !== "FE") return false;
      if (filterType === "PE" && ex.exam_type !== "PE") return false;
    }
    if (q) {
      const matchTitle = (ex.title || "").toLowerCase().includes(q);
      const matchTerm = (ex.term || "").toLowerCase().includes(q);
      if (!matchTitle && !matchTerm) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    elChondeListContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">Không tìm thấy đề thi phù hợp.</div>';
    return;
  }

  elChondeListContainer.innerHTML = "";
  filtered.forEach(ex => {
    const item = document.createElement("div");
    item.className = "doc-item";

    let badgeClass = "badge-status-uncompiled";
    let badgeText = "Chưa soạn";
    if (ex.status === "running") {
      badgeClass = "badge-status-running";
      badgeText = "Đang soạn...";
    } else if (ex.status === "error") {
      badgeClass = "badge-status-error";
      badgeText = "Lỗi";
    } else if (ex.status === "skipped") {
      badgeClass = "badge-status-uncompiled";
      badgeText = "Bỏ qua";
    } else if (ex.status === "done" || ex.compiled) {
      badgeClass = "badge-status-compiled";
      badgeText = `Đã soạn ${ex.compiled_at ? "(" + ex.compiled_at + ")" : ""}`;
    }

    const isChecked = chondeState.selectedUrls.has(ex.url);

    item.innerHTML = `
      <div class="doc-item-row">
        <input type="checkbox" class="chonde-checkbox" data-url="${ex.url}" ${isChecked ? "checked" : ""} style="margin-top: 2px; cursor: pointer;" />
        <div style="flex: 1; min-width: 0;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 4px;">
            <span class="doc-item-title" title="${ex.title}">${ex.title}</span>
            <span class="badge-status ${badgeClass}">${badgeText}</span>
          </div>
          <div class="doc-item-meta" style="margin-top: 2px;">
            <span>${ex.exam_type} · ${ex.question_count || 0} câu</span>
            <span>${ex.term || ""}</span>
          </div>
        </div>
      </div>
    `;

    const cb = item.querySelector(".chonde-checkbox");
    cb.addEventListener("change", () => {
      if (cb.checked) {
        chondeState.selectedUrls.add(ex.url);
      } else {
        chondeState.selectedUrls.delete(ex.url);
      }
      updateChondeSelectionBadge();
    });

    elChondeListContainer.appendChild(item);
  });
}

function updateChondeSelectionBadge() {
  if (elBadgeChondeSelected) {
    elBadgeChondeSelected.innerText = `${chondeState.selectedUrls.size} đã chọn`;
  }
}

// Search input debounce
if (elInputSearchExams) {
  elInputSearchExams.addEventListener("input", () => {
    renderChondeList();
  });
}

// Filter buttons (ALL, FE, PE)
filterButtonsChonde.forEach(btn => {
  btn.addEventListener("click", () => {
    filterButtonsChonde.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    chondeState.filterType = btn.dataset.type;
    renderChondeList();
  });
});

// Select All in Chọn đề
if (elCheckSelectAllChonde) {
  elCheckSelectAllChonde.addEventListener("change", () => {
    const checked = elCheckSelectAllChonde.checked;
    chondeState.exams.forEach(ex => {
      if (checked) chondeState.selectedUrls.add(ex.url);
      else chondeState.selectedUrls.delete(ex.url);
    });
    const cbs = elChondeListContainer.querySelectorAll(".chonde-checkbox");
    cbs.forEach(cb => { cb.checked = checked; });
    updateChondeSelectionBadge();
  });
}

// Queue Persistence in chrome.storage.local
async function saveQueueState() {
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set({
      chondeQueue: {
        activeQueue: chondeState.activeQueue,
        queueIndex: chondeState.queueIndex,
        isQueueRunning: chondeState.isQueueRunning,
      }
    });
  }
}

async function restoreQueueState() {
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["chondeQueue"], (res) => {
      if (res.chondeQueue && res.chondeQueue.activeQueue && res.chondeQueue.activeQueue.length > 0) {
        chondeState.activeQueue = res.chondeQueue.activeQueue;
        chondeState.queueIndex = res.chondeQueue.queueIndex || 0;
        if (chondeState.queueIndex < chondeState.activeQueue.length) {
          if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
          if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
          updateQueueProgressUI();
        }
      }
    });
  }
}

// Update Queue Progress Card
function updateQueueProgressUI(examTitle = "", qCurrent = 0, qTotal = 0) {
  if (!elQueueProgressCard) return;
  const total = chondeState.activeQueue.length;
  const current = Math.min(chondeState.queueIndex + 1, total);
  if (elQueueProgressTitle) {
    elQueueProgressTitle.innerText = `Đang soạn đề ${current}/${total}: ${examTitle || (chondeState.activeQueue[chondeState.queueIndex]?.title || "")}`;
  }
  if (elQueueProgressSub) {
    elQueueProgressSub.innerText = qTotal > 0 ? `Câu ${qCurrent}/${qTotal}` : `Đang xử lý đề...`;
  }
  if (elQueueProgressBar) {
    const overallPct = total > 0 ? ((chondeState.queueIndex + (qTotal > 0 ? qCurrent / qTotal : 0)) / total) * 100 : 0;
    elQueueProgressBar.style.width = `${Math.min(overallPct, 100)}%`;
  }
}

// Start Queue button handler
if (elBtnStartQueue) {
  elBtnStartQueue.addEventListener("click", async () => {
    if (chondeState.isQueueRunning) {
      log("Hàng đợi đang chạy!", "warn");
      return;
    }

    if (chondeState.selectedUrls.size === 0) {
      log("Vui lòng chọn ít nhất một đề để soạn!", "warn");
      return;
    }

    // Safety limit: max 20 exams (configurable in input-batch-limit)
    const limit = parseInt(elInputBatchLimit ? elInputBatchLimit.value : "20", 10) || 20;
    const selectedExams = chondeState.exams.filter(ex => chondeState.selectedUrls.has(ex.url));

    const updateCompiled = elCheckUpdateCompiled ? elCheckUpdateCompiled.checked : false;

    // Filter out already compiled if updateCompiled is false
    const queueItems = selectedExams.filter(ex => {
      if (!updateCompiled && ex.compiled) return false;
      return true;
    });

    if (queueItems.length === 0) {
      log("Tất cả các đề đã chọn đều đã được soạn trước đó. Hãy tích chọn 'Cập nhật cả đề đã soạn' nếu muốn làm lại!", "warn");
      return;
    }

    if (queueItems.length > limit) {
      log(`Giới hạn an toàn: Tối đa ${limit} đề mỗi lượt. Đã cắt bớt danh sách còn ${limit} đề!`, "warn");
      queueItems.length = limit;
    }

    chondeState.activeQueue = queueItems;
    chondeState.queueIndex = 0;
    chondeState.isQueueRunning = true;
    chondeState.isQueuePaused = false;
    chondeState.consecutiveFailures = 0;
    chondeState.rateLimitDelayMs = 2000;

    if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
    if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
    if (elQueueCompletedBanner) elQueueCompletedBanner.style.display = "none";

    saveQueueState();
    runQueueLoop();
  });
}

// Pause / Stop Queue
if (elBtnQueuePause) {
  elBtnQueuePause.addEventListener("click", () => {
    chondeState.isQueuePaused = true;
    chondeState.isQueueRunning = false;
    saveQueueState();
    log("Đã tạm dừng hàng đợi.", "warn");
  });
}

// Skip current exam
if (elBtnQueueSkip) {
  elBtnQueueSkip.addEventListener("click", () => {
    const curExam = chondeState.activeQueue[chondeState.queueIndex];
    if (curExam) {
      curExam.status = "skipped";
    }
    log(`Đã bỏ qua đề: ${curExam?.title}`, "warn");
    chondeState.queueIndex++;
    saveQueueState();
    renderChondeList();
    if (chondeState.queueIndex >= chondeState.activeQueue.length) {
      finishQueue();
    }
  });
}

// Retry failed exams
if (elBtnQueueRetry) {
  elBtnQueueRetry.addEventListener("click", () => {
    chondeState.isQueuePaused = false;
    chondeState.isQueueRunning = true;
    runQueueLoop();
  });
}

// Queue execution loop
async function runQueueLoop() {
  while (chondeState.isQueueRunning && chondeState.queueIndex < chondeState.activeQueue.length) {
    if (chondeState.isQueuePaused) break;

    const currentExam = chondeState.activeQueue[chondeState.queueIndex];
    log(`[Hàng đợi ${chondeState.queueIndex + 1}/${chondeState.activeQueue.length}] Bắt đầu đề: ${currentExam.title}`, "info");
    updateQueueProgressUI(currentExam.title, 0, currentExam.question_count || 40);

    try {
      if (currentExam.exam_type === "PE") {
        // PE Exam: Download paper.pdf and materials into thread folder
        await processPeExam(currentExam);
      } else {
        // FE Exam: Standard Word compilation
        await processFeExam(currentExam);
      }

      currentExam.compiled = true;
      currentExam.status = "done";
      chondeState.consecutiveFailures = 0;
      chondeState.rateLimitDelayMs = 2000; // Reset cadence
      chondeState.queueIndex++;
      saveQueueState();

    } catch (err) {
      log(`[Lỗi đề] ${currentExam.title}: ${err.message}`, "error");
      currentExam.status = "error";

      if (err.message.includes("429") || err.message.includes("5")) {
        // Exponential backoff
        chondeState.consecutiveFailures++;
        chondeState.rateLimitDelayMs = Math.min(chondeState.rateLimitDelayMs * 2, 30000);
        log(`Gặp lỗi 429/5xx! Tự động lùi tốc độ, chờ ${chondeState.rateLimitDelayMs / 1000}s...`, "warn");
        await sleep(chondeState.rateLimitDelayMs);
      }

      if (chondeState.isQueuePaused) break;
      chondeState.queueIndex++;
      saveQueueState();
    }

    renderChondeList();
    await sleep(chondeState.rateLimitDelayMs);
  }

  if (chondeState.queueIndex >= chondeState.activeQueue.length) {
    finishQueue();
  }
}

function finishQueue() {
  chondeState.isQueueRunning = false;
  chondeState.isQueuePaused = false;
  saveQueueState();
  if (elQueueControlsRow) elQueueControlsRow.style.display = "none";
  if (elQueueProgressCard) elQueueProgressCard.style.display = "none";

  let successCount = 0;
  let errorCount = 0;
  let skipCount = 0;

  chondeState.activeQueue.forEach((ex) => {
    if (ex.status === "done") successCount++;
    else if (ex.status === "error") errorCount++;
    else if (ex.status === "skipped") skipCount++;
    else if (ex.compiled) successCount++;
  });

  const summaryMsg = `Xong ${successCount} · Lỗi ${errorCount} · Bỏ qua ${skipCount}`;

  if (elQueueCompletedBanner) {
    elQueueCompletedBanner.style.display = "flex";
    if (elQueueCompletedMsg) {
      elQueueCompletedMsg.innerText = summaryMsg;
    }
  }
  log(`Đã hoàn tất hàng đợi: ${summaryMsg}`, "success");
}

// Download ZIP for all exams in current finished queue
if (elBtnQueueDownloadAll) {
  elBtnQueueDownloadAll.addEventListener("click", () => {
    const subjectParam = chondeState.selectedSubject || "EXAMS";
    const downloadUrl = `${BACKEND_URL}/api/exports/bundle.zip?subject=${encodeURIComponent(subjectParam)}`;
    triggerFileDownload(downloadUrl, `DocxStacked_Queue_${subjectParam}_${new Date().toISOString().slice(0, 10)}.zip`);
  });
}

// Process FE Exam in Queue
async function processFeExam(exam) {
  const threadUrl = exam.url;
  const updateOnly = exam.compiled;

  // Crawl first page
  const resp = await fetch(threadUrl, { method: "GET", credentials: "include" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const html = await resp.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const threadTitle = exam.title;
  const subjectCode = exam.subject_code || "EXAM";

  const attachments = Array.from(doc.querySelectorAll(".attachment, .js-lbImage, .message-body img"))
    .filter(el => {
      const src = el.src || (el.querySelector("img") && el.querySelector("img").src);
      return src && src.includes("/attachments/");
    });

  const totalQuestions = attachments.length || exam.question_count || 40;
  const questionsData = [];

  for (let i = 0; i < totalQuestions; i++) {
    if (chondeState.isQueuePaused) throw new Error("USER_PAUSED");
    const qIndex = i + 1;
    updateQueueProgressUI(exam.title, qIndex, totalQuestions);

    questionsData.push({
      index: qIndex,
      file_name: `question_${qIndex}.png`,
      media_id: `q_${qIndex}`,
      media_url: threadUrl,
      image_base64: null,
      comments: [],
    });

    await sleep(50);
  }

  const payload = {
    subject_code: subjectCode,
    exam_title: threadTitle,
    exam_url: threadUrl,
    questions: questionsData,
    skip_images: updateOnly,
  };

  const res = await apiFetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new Error(`Ingest HTTP ${res.status}`);
  log(`Xuất thành công Word cho: ${threadTitle}`, "success");
}

// Process PE Exam in Queue (paper.pdf, materials zip into thread folder)
async function processPeExam(exam) {
  log(`[PE] Đang xử lý tài liệu thực hành: ${exam.title}`, "info");
  const threadUrl = exam.url;
  const resp = await fetch(threadUrl, { method: "GET", credentials: "include" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const html = await resp.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const links = Array.from(doc.querySelectorAll("a[href*='/attachments/'], a[href*='.pdf'], a[href*='.zip']"));
  log(`[PE] Tìm thấy ${links.length} tệp đính kèm trong bài đăng.`, "info");

  let downloadedCount = 0;
  for (const a of links) {
    const fileUrl = a.href;
    const fileName = a.innerText.trim() || `attachment_${downloadedCount + 1}`;
    const sanitizedTitle = (exam.title || "PE_Exam").replace(/[^a-zA-Z0-9_\-\s]/g, "").trim();
    const destPath = `DocxStacked_PE/${sanitizedTitle}/${fileName}`;

    if (typeof chrome !== "undefined" && chrome.downloads && chrome.downloads.download) {
      chrome.downloads.download({
        url: fileUrl,
        filename: destPath,
        saveAs: false,
      });
      downloadedCount++;
    }
  }

  log(`[PE] Hoàn thành tải ${downloadedCount} tài liệu cho: ${exam.title}`, "success");
}

restoreQueueState();

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
          let timeLabel = "--:--";
          if (data.compiled_at_iso || (data.compiled_at && data.compiled_at.includes("T"))) {
            try {
              const d = new Date(data.compiled_at_iso || data.compiled_at);
              timeLabel = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
            } catch (e) {
              timeLabel = data.compiled_time_short || "--:--";
            }
          } else {
            timeLabel = data.compiled_time_short || data.compiled_at || "--:--";
          }
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

  // Show result card only for fresh ingest, hide duplicate result card on reopen update
  if (isCommentUpdateOnly) {
    if (elResultCard) elResultCard.style.display = "none";
  } else if (elResultFilename && elResultDownloadBtn && elResultCard) {
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

// Reopen Actions: Mở thư mục
if (elBtnReopenOpenFolder) {
  elBtnReopenOpenFolder.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
      log("Đã mở thư mục chứa file Word.", "info");
    } catch (e) {
      log(`Không thể mở thư mục: ${e.message}`, "warn");
    }
  });
}

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
