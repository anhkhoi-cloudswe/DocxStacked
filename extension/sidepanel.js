// sidepanel.js - DocxStacked Chromium Extension (MV3)
// Merged 3-tab layout: Soạn đề | Đã soạn | Cài đặt
// Unified Queue Engine, Subject Combobox, Persistent API Key & Health Check

const BACKEND_URL = "http://127.0.0.1:8000";
const EXTENSION_ID = (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id) ? chrome.runtime.id : "kicplcdfmbcfjildbbimpfiljlmfokea";
const MIN_REQUEST_INTERVAL_MS = 2000; // Cadence: 1 req / 2.0s

const state = {
  isRunning: false,
  isStopped: false,
  isPaused: false,
  activeTab: "soande",
  settingsData: null,
  documentsData: [],
  existingExam: null,
  cachedSubjects: [],
  recentSubjects: [],
  backendOnline: false,
};

// Common API helper for Extension with pinned header
async function apiFetch(endpoint, options = {}) {
  const headers = options.headers || {};
  headers["X-DocxStacked-Ext"] = EXTENSION_ID;
  const userToken = (elInputIngestToken && elInputIngestToken.value.trim()) || "";
  if (userToken) {
    headers["X-Ingest-Token"] = userToken;
  }
  try {
    const res = await fetch(`${BACKEND_URL}${endpoint}`, {
      ...options,
      headers,
    });
    return res;
  } catch (err) {
    // Immediate network error flips backend to offline
    setBackendOffline("Lỗi kết nối Backend. Vui lòng mở terminal chạy: python run_dev.py");
    throw err;
  }
}

// DOM Elements
const elBackendStatus = document.getElementById("backend-status");
const elUiNoticeBox = document.getElementById("ui-notice-box");
const elThreadTitleDisplay = document.getElementById("thread-title-display");
const elInputThreadUrl = document.getElementById("input-thread-url");
const elBtnSyncTab = document.getElementById("btn-sync-tab");
const elOpenExamBadge = document.getElementById("open-exam-badge");
const elBtnMainAction = document.getElementById("btn-main-action");
const elBtnReopenDownload = document.getElementById("btn-reopen-download");
const elCheckRedownloadImages = document.getElementById("check-redownload-images");

// Combobox & Subject elements
const elInputSubjectCombobox = document.getElementById("input-subject-combobox");
const elBtnClearCombobox = document.getElementById("btn-clear-combobox");
const elSubjectDropdown = document.getElementById("subject-dropdown");
const elSelectedSubjectLabel = document.getElementById("selected-subject-label");
const elRecentSubjectsList = document.getElementById("recent-subjects-list");

// Exam list block in Soạn đề
const elCardExamList = document.getElementById("card-exam-list");
const elInputSearchExams = document.getElementById("input-search-exams");
const filterButtonsChonde = document.querySelectorAll(".filter-chip-btn");
const elCheckSelectAllChonde = document.getElementById("check-select-all-chonde");
const elBadgeChondeSelected = document.getElementById("badge-chonde-selected");
const elChondeListContainer = document.getElementById("chonde-list-container");

// Sticky Bottom Action Bar
const elStickyActionBar = document.getElementById("sticky-action-bar");
const elCheckUpdateCompiled = document.getElementById("check-update-compiled");
const elBtnStartQueue = document.getElementById("btn-start-queue");

// Unified Queue & Progress Elements
const elQueueProgressCard = document.getElementById("queue-progress-card");
const elQueueProgressTitle = document.getElementById("queue-progress-title");
const elQueueOverallRatio = document.getElementById("queue-overall-ratio");
const elProgressBar = document.getElementById("progress-bar");
const elStatsSummaryLine = document.getElementById("stats-summary-line");
const elQueueControlsRow = document.getElementById("queue-controls-row");
const elBtnQueuePause = document.getElementById("btn-queue-pause");
const elBtnQueueSkip = document.getElementById("btn-queue-skip");
const elBtnQueueRetry = document.getElementById("btn-queue-retry");

// Result Card & Logs
const elResultCard = document.getElementById("result-card");
const elResultFilename = document.getElementById("result-filename");
const elResultDownloadBtn = document.getElementById("result-download-btn");
const elBtnOpenFolder = document.getElementById("btn-open-folder");
const elLogBox = document.getElementById("log-box");
const elBtnCopyLog = document.getElementById("btn-copy-log");
const elInputIngestToken = document.getElementById("input-ingest-token");

// Tab elements
const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = {
  soande: document.getElementById("tab-panel-soande"),
  dasoan: document.getElementById("tab-panel-dasoan"),
  caidat: document.getElementById("tab-panel-caidat"),
};

// Đã soạn elements
const elDocsContainer = document.getElementById("docs-list-container");
const elBtnRefreshDocs = document.getElementById("btn-refresh-docs");
const elCheckSelectAllDasoan = document.getElementById("check-select-all-dasoan");
const elBadgeDasoanSelected = document.getElementById("badge-dasoan-selected");
const elBtnDownloadSelectedZip = document.getElementById("btn-download-selected-zip");
const elBtnDownloadSubjectFolder = document.getElementById("btn-download-subject-folder");
const elBtnOpenFolderDasoan = document.getElementById("btn-open-folder-dasoan");

// Settings elements
const elInputBatchLimit = document.getElementById("input-batch-limit");
const elLinkOpenDashboard = document.getElementById("link-open-dashboard");
const elProvidersContainer = document.getElementById("providers-list-container");
const elOptMultiComma = document.getElementById("opt-multi-comma");
const elOptMultiJoined = document.getElementById("opt-multi-joined");
const elBtnOpenFolderSettings = document.getElementById("btn-open-folder-settings");
const elBtnCleanData = document.getElementById("btn-clean-data");

// Queue State
const queueEngine = {
  items: [],
  currentIndex: 0,
  activeExam: null,
  isRunning: false,
  isPaused: false,
  skipCurrent: false,
};

const chondeState = {
  selectedSubject: null,
  exams: [],
  filterType: "ALL", // ALL, FE, PE
  selectedUrls: new Set(),
};

// UI Notice & Log helpers
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
  if (elStatsSummaryLine && statusText) {
    elStatsSummaryLine.innerText = statusText;
  }
}

// -------------------------------------------------------------
// PART B: REAL BACKEND STATUS CHECK (Interval 5s, Timeout 2s)
// -------------------------------------------------------------
function setBackendOnline(dashboardUrl) {
  state.backendOnline = true;
  elBackendStatus.className = "status-chip chip-online";
  elBackendStatus.innerText = "Backend Online";
  hideNotice();
  enableActionButtons(true);
  if (dashboardUrl && elLinkOpenDashboard) {
    elLinkOpenDashboard.href = dashboardUrl;
  }
}

function setBackendOffline(noticeMsg) {
  state.backendOnline = false;
  elBackendStatus.className = "status-chip chip-offline";
  elBackendStatus.innerText = "Backend Offline";
  enableActionButtons(false);
  showNotice(noticeMsg || "Backend Offline. Mở terminal chạy: python run_dev.py");
}

function enableActionButtons(enabled) {
  if (elBtnMainAction) elBtnMainAction.disabled = !enabled;
  if (elBtnStartQueue) elBtnStartQueue.disabled = !enabled;
  if (elBtnSyncTab) elBtnSyncTab.disabled = !enabled;
}

async function checkBackendHealth() {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 2000);

  try {
    const res = await fetch(`${BACKEND_URL}/api/health`, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      setBackendOnline(data.dashboard_url);
      return true;
    } else {
      setBackendOffline();
      return false;
    }
  } catch (err) {
    clearTimeout(timeoutId);
    setBackendOffline();
    return false;
  }
}

// Check every 5 seconds
setInterval(checkBackendHealth, 5000);

// -------------------------------------------------------------
// TAB SWITCHING LOGIC (3 TABS)
// -------------------------------------------------------------
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

// -------------------------------------------------------------
// PART A: COMBOBOX SUBJECT SEARCH & RECENT SUBJECTS
// -------------------------------------------------------------
function removeAccents(str) {
  if (!str) return "";
  return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
}

async function initSubjectsCache() {
  // Load cached subjects from storage if available
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["docxstacked_subjects", "docxstacked_recent_subjects"], (res) => {
      if (res.docxstacked_subjects && res.docxstacked_subjects.length > 0) {
        state.cachedSubjects = res.docxstacked_subjects;
      }
      if (res.docxstacked_recent_subjects && Array.isArray(res.docxstacked_recent_subjects)) {
        state.recentSubjects = res.docxstacked_recent_subjects;
        renderRecentSubjects();
      }
    });
  }

  // Fetch 406 subjects once from backend
  try {
    const res = await apiFetch("/api/subjects?limit=500");
    if (res.ok) {
      const data = await res.json();
      const items = data.items || [];
      if (items.length > 0) {
        state.cachedSubjects = items;
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
          chrome.storage.local.set({ docxstacked_subjects: items });
        }
      }
    }
  } catch (err) {
    // If offline, cachedSubjects from local storage will be used
  }
}

function renderRecentSubjects() {
  if (!elRecentSubjectsList) return;
  if (!state.recentSubjects || state.recentSubjects.length === 0) {
    elRecentSubjectsList.innerHTML = '<span style="color: var(--muted); font-size: 10px;">(chưa có)</span>';
    return;
  }
  elRecentSubjectsList.innerHTML = "";
  state.recentSubjects.slice(0, 5).forEach(code => {
    const chip = document.createElement("span");
    chip.className = "recent-chip";
    chip.innerText = code;
    chip.addEventListener("click", () => {
      selectSubject(code);
    });
    elRecentSubjectsList.appendChild(chip);
  });
}

function recordRecentSubject(code) {
  if (!code) return;
  let recents = (state.recentSubjects || []).filter(c => c !== code);
  recents.unshift(code);
  recents = recents.slice(0, 5);
  state.recentSubjects = recents;
  renderRecentSubjects();
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set({ docxstacked_recent_subjects: recents });
  }
}

// Combobox Autocomplete & Keyboard navigation
let activeDropdownIndex = -1;

function showSubjectSuggestions(query) {
  if (!elSubjectDropdown) return;
  const qClean = removeAccents(query.trim());
  if (!qClean) {
    elSubjectDropdown.style.display = "none";
    if (elBtnClearCombobox) elBtnClearCombobox.style.display = "none";
    return;
  }

  if (elBtnClearCombobox) elBtnClearCombobox.style.display = "block";

  // Filter cached subjects (code or name match partial accent-insensitive)
  const matches = state.cachedSubjects.filter(s => {
    const codeClean = removeAccents(s.code);
    const nameClean = removeAccents(s.name);
    return codeClean.includes(qClean) || nameClean.includes(qClean);
  });

  activeDropdownIndex = -1;
  elSubjectDropdown.innerHTML = "";

  if (matches.length === 0) {
    elSubjectDropdown.innerHTML = `<div class="combobox-empty">Không có môn nào khớp '${query.trim()}'</div>`;
    elSubjectDropdown.style.display = "block";
    return;
  }

  const max8 = matches.slice(0, 8);
  max8.forEach((s, idx) => {
    const item = document.createElement("div");
    item.className = "combobox-item";
    item.dataset.index = idx;
    item.dataset.code = s.code;
    item.innerHTML = `
      <span class="combobox-item-code">${s.code}</span>
      <span class="combobox-item-name" title="${s.name}">${s.name}</span>
    `;
    item.addEventListener("click", () => {
      selectSubject(s.code);
    });
    elSubjectDropdown.appendChild(item);
  });

  elSubjectDropdown.style.display = "block";
}

function selectSubject(code) {
  chondeState.selectedSubject = code;
  recordRecentSubject(code);
  if (elInputSubjectCombobox) {
    elInputSubjectCombobox.value = code;
  }
  if (elSubjectDropdown) elSubjectDropdown.style.display = "none";
  if (elSelectedSubjectLabel) elSelectedSubjectLabel.innerText = `[${code}]`;
  if (elBtnClearCombobox) elBtnClearCombobox.style.display = "block";

  // Auto-fetch exam list with spinner (No "Lấy đề" button)
  fetchExamsForSelectedSubject(code);
}

if (elInputSubjectCombobox) {
  elInputSubjectCombobox.addEventListener("input", (e) => {
    showSubjectSuggestions(e.target.value);
  });

  elInputSubjectCombobox.addEventListener("keydown", (e) => {
    if (!elSubjectDropdown || elSubjectDropdown.style.display === "none") return;
    const items = elSubjectDropdown.querySelectorAll(".combobox-item");
    if (items.length === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeDropdownIndex = (activeDropdownIndex + 1) % items.length;
      updateDropdownActive(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeDropdownIndex = (activeDropdownIndex - 1 + items.length) % items.length;
      updateDropdownActive(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeDropdownIndex >= 0 && activeDropdownIndex < items.length) {
        const code = items[activeDropdownIndex].dataset.code;
        selectSubject(code);
      } else if (items.length > 0) {
        selectSubject(items[0].dataset.code);
      }
    } else if (e.key === "Escape") {
      elSubjectDropdown.style.display = "none";
    }
  });
}

function updateDropdownActive(items) {
  items.forEach((it, idx) => {
    if (idx === activeDropdownIndex) {
      it.classList.add("active");
      it.scrollIntoView({ block: "nearest" });
    } else {
      it.classList.remove("active");
    }
  });
}

if (elBtnClearCombobox) {
  elBtnClearCombobox.addEventListener("click", () => {
    if (elInputSubjectCombobox) elInputSubjectCombobox.value = "";
    elBtnClearCombobox.style.display = "none";
    if (elSubjectDropdown) elSubjectDropdown.style.display = "none";
    if (elSelectedSubjectLabel) elSelectedSubjectLabel.innerText = "";
    chondeState.selectedSubject = null;
    if (elCardExamList) elCardExamList.style.display = "none";
    if (elStickyActionBar) elStickyActionBar.style.display = "none";
  });
}

// Close dropdown on click outside
document.addEventListener("click", (e) => {
  if (elSubjectDropdown && !e.target.closest(".combobox-container")) {
    elSubjectDropdown.style.display = "none";
  }
});

// Fetch exams automatically on subject select
async function fetchExamsForSelectedSubject(code) {
  if (elCardExamList) elCardExamList.style.display = "flex";
  if (elStickyActionBar) elStickyActionBar.style.display = "flex";
  chondeState.selectedUrls.clear();
  updateChondeSelectionBadge();

  if (elChondeListContainer) {
    elChondeListContainer.innerHTML = `
      <div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">
        <div style="display: inline-block; width: 14px; height: 14px; border: 2px solid #6366f1; border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
        <div style="margin-top: 6px;">Đang tải danh sách đề môn ${code}...</div>
      </div>
    `;
  }

  try {
    const forumUrl = `https://fuoverflow.com/forums/${encodeURIComponent(code)}/`;
    let html = "";
    try {
      const resp = await fetch(forumUrl, { method: "GET", credentials: "include" });
      if (resp.ok) html = await resp.text();
    } catch (netErr) {
      log(`Không thể kết nối trực tiếp FuOverflow: ${netErr.message}`, "warn");
    }

    if (!html) {
      const res = await apiFetch(`/api/subjects/${encodeURIComponent(code)}/exams?type=FE`);
      if (res.ok) {
        const items = await res.json();
        chondeState.exams = items.map(e => ({
          title: e.title,
          url: e.url,
          exam_type: e.exam_type || "FE",
          term: e.term || "",
          post_date: e.post_date,
          question_count: e.question_count || 40,
          compiled: false,
          compiled_at: null,
          subject_code: code,
        }));
      }
    } else {
      const parseResp = await apiFetch("/api/subjects/parse-forum-html", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ html: html, subject_code: code }),
      });
      if (!parseResp.ok) throw new Error(`Lỗi phân tích backend: HTTP ${parseResp.status}`);
      const parsedData = await parseResp.json();
      chondeState.exams = parsedData.items || [];
    }

    renderExamList();
  } catch (err) {
    if (elChondeListContainer) {
      elChondeListContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 12px;">Lỗi tải đề: ${err.message}</div>`;
    }
  }
}

function renderExamList() {
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
    elChondeListContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 16px;">Không tìm thấy đề thi phù hợp trong môn này.</div>';
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
  const count = chondeState.selectedUrls.size;
  if (elBadgeChondeSelected) {
    elBadgeChondeSelected.innerText = `${count} đã chọn`;
  }
  if (elBtnStartQueue) {
    elBtnStartQueue.innerText = `Soạn ${count} đề đã chọn`;
  }
}

if (elInputSearchExams) {
  elInputSearchExams.addEventListener("input", renderExamList);
}

filterButtonsChonde.forEach(btn => {
  btn.addEventListener("click", () => {
    filterButtonsChonde.forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    chondeState.filterType = btn.dataset.type;
    renderExamList();
  });
});

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

// -------------------------------------------------------------
// UNIFIED QUEUE ENGINE (Single exam or multiple exams)
// -------------------------------------------------------------
function startUnifiedQueue(items) {
  if (queueEngine.isRunning) {
    log("Hàng đợi đang chạy!", "warn");
    return;
  }
  if (!items || items.length === 0) {
    log("Không có đề nào trong hàng đợi!", "warn");
    return;
  }

  queueEngine.items = items;
  queueEngine.currentIndex = 0;
  queueEngine.isRunning = true;
  queueEngine.isPaused = false;
  queueEngine.skipCurrent = false;

  if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
  if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
  if (elBtnQueuePause) elBtnQueuePause.innerText = "Dừng";

  runUnifiedQueueLoop();
}

async function runUnifiedQueueLoop() {
  while (queueEngine.isRunning && queueEngine.currentIndex < queueEngine.items.length) {
    if (queueEngine.isPaused) break;

    const currentItem = queueEngine.items[queueEngine.currentIndex];
    queueEngine.activeExam = currentItem;
    currentItem.status = "running";
    renderExamList();

    const totalItems = queueEngine.items.length;
    const itemNum = queueEngine.currentIndex + 1;
    if (elQueueProgressTitle) {
      elQueueProgressTitle.innerText = `[${itemNum}/${totalItems}] ${currentItem.title || "Đang soạn..."}`;
    }
    if (elQueueOverallRatio) {
      elQueueOverallRatio.innerText = `${itemNum}/${totalItems}`;
    }

    try {
      if (currentItem.exam_type === "PE") {
        await executePeExamUpload(currentItem);
      } else {
        await executeFeExamCrawl(currentItem);
      }
      currentItem.status = "done";
      currentItem.compiled = true;
      log(`Hoàn thành đề: ${currentItem.title}`, "success");
    } catch (err) {
      if (err.message === "USER_SKIPPED") {
        currentItem.status = "skipped";
        log(`Đã bỏ qua đề: ${currentItem.title}`, "warn");
      } else if (err.message === "USER_STOPPED") {
        currentItem.status = "error";
        log("Đã dừng hàng đợi.", "warn");
        break;
      } else {
        currentItem.status = "error";
        log(`Lỗi đề ${currentItem.title}: ${err.message}`, "error");
      }
    }

    renderExamList();
    queueEngine.currentIndex++;
    await sleep(MIN_REQUEST_INTERVAL_MS);
  }

  finishUnifiedQueue();
}

function finishUnifiedQueue() {
  queueEngine.isRunning = false;
  queueEngine.isPaused = false;
  if (elBtnMainAction) {
    elBtnMainAction.innerText = state.existingExam ? "Cập nhật bình luận" : "Soạn đề này";
    elBtnMainAction.className = "btn-main btn-start";
  }
  if (elQueueProgressCard) {
    setTimeout(() => {
      if (!queueEngine.isRunning) elQueueProgressCard.style.display = "none";
    }, 4000);
  }
}

if (elBtnQueuePause) {
  elBtnQueuePause.addEventListener("click", () => {
    if (queueEngine.isRunning && !queueEngine.isPaused) {
      queueEngine.isPaused = true;
      elBtnQueuePause.innerText = "Tiếp tục";
      log("Đã tạm dừng hàng đợi.", "warn");
    } else if (queueEngine.isRunning && queueEngine.isPaused) {
      queueEngine.isPaused = false;
      elBtnQueuePause.innerText = "Dừng";
      log("Tiếp tục hàng đợi...", "info");
      runUnifiedQueueLoop();
    } else {
      queueEngine.isRunning = false;
      if (elQueueProgressCard) elQueueProgressCard.style.display = "none";
    }
  });
}

if (elBtnQueueSkip) {
  elBtnQueueSkip.addEventListener("click", () => {
    queueEngine.skipCurrent = true;
    log("Yêu cầu bỏ qua đề hiện tại...", "warn");
  });
}

if (elBtnQueueRetry) {
  elBtnQueueRetry.addEventListener("click", () => {
    const failedItems = queueEngine.items.filter(it => it.status === "error");
    if (failedItems.length > 0) {
      startUnifiedQueue(failedItems);
    } else {
      log("Không có đề nào bị lỗi để thử lại.", "info");
    }
  });
}

// -------------------------------------------------------------
// KHỐI 1: ĐỀ ĐANG MỞ (Check Fuoverflow tab, compile / update / download)
// -------------------------------------------------------------
async function checkOpenExamStatus(url) {
  if (!url || !url.includes("fuoverflow.com/threads/")) {
    if (elOpenExamBadge) {
      elOpenExamBadge.className = "badge-status badge-status-uncompiled";
      elOpenExamBadge.innerText = "Chưa soạn";
    }
    if (elBtnMainAction) elBtnMainAction.innerText = "Soạn đề này";
    if (elBtnReopenDownload) elBtnReopenDownload.style.display = "none";
    state.existingExam = null;
    return;
  }

  try {
    const res = await apiFetch(`/api/ingest/check-exam?url=${encodeURIComponent(url)}`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      if (data.exists) {
        state.existingExam = data;
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

        if (elOpenExamBadge) {
          elOpenExamBadge.className = "badge-status badge-status-compiled";
          elOpenExamBadge.innerText = `Đã soạn lúc ${timeLabel}`;
        }
        if (elBtnMainAction) elBtnMainAction.innerText = "Cập nhật bình luận";
        if (elBtnReopenDownload) {
          elBtnReopenDownload.href = `${BACKEND_URL}${data.download_url}`;
          elBtnReopenDownload.style.display = "inline-flex";
        }
        return;
      }
    }
  } catch (err) {}

  if (elOpenExamBadge) {
    elOpenExamBadge.className = "badge-status badge-status-uncompiled";
    elOpenExamBadge.innerText = "Chưa soạn";
  }
  if (elBtnMainAction) elBtnMainAction.innerText = "Soạn đề này";
  if (elBtnReopenDownload) elBtnReopenDownload.style.display = "none";
  state.existingExam = null;
}

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
        checkOpenExamStatus(cleanUrl);
      } else {
        showNotice("Tab hiện tại không phải trang đề thi FuOverflow (/threads/...)!");
      }
    }
  } catch (e) {
    log(`Lỗi đồng bộ tab: ${e.message}`, "error");
  }
}

if (elBtnSyncTab) elBtnSyncTab.addEventListener("click", syncFromActiveTab);

if (elInputThreadUrl) {
  elInputThreadUrl.addEventListener("change", () => {
    checkOpenExamStatus(elInputThreadUrl.value.trim());
  });
}

// Main button "Soạn đề này" / "Cập nhật bình luận"
if (elBtnMainAction) {
  elBtnMainAction.addEventListener("click", () => {
    const url = elInputThreadUrl.value.trim();
    if (!url || !url.includes("fuoverflow.com/threads/")) {
      showNotice("Vui lòng nhập hoặc đồng bộ URL đề thi hợp lệ!");
      return;
    }
    const isUpdate = !!state.existingExam;
    const title = elThreadTitleDisplay.innerText || "Đề thi FuOverflow";
    const mCode = title.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
    const subjCode = mCode ? mCode[1].toUpperCase() : "TEST";

    const item = {
      title: title,
      url: url,
      exam_type: "FE",
      subject_code: subjCode,
      compiled: isUpdate,
      redownloadImages: elCheckRedownloadImages ? elCheckRedownloadImages.checked : false,
    };

    startUnifiedQueue([item]);
  });
}

// Queue button "Soạn N đề đã chọn"
if (elBtnStartQueue) {
  elBtnStartQueue.addEventListener("click", () => {
    if (chondeState.selectedUrls.size === 0) {
      log("Vui lòng chọn ít nhất một đề!", "warn");
      return;
    }

    const limit = parseInt(elInputBatchLimit ? elInputBatchLimit.value : "20", 10) || 20;
    const selectedExams = chondeState.exams.filter(ex => chondeState.selectedUrls.has(ex.url));
    const updateCompiled = elCheckUpdateCompiled ? elCheckUpdateCompiled.checked : false;

    const queueItems = selectedExams.filter(ex => {
      if (!updateCompiled && ex.compiled) return false;
      return true;
    });

    if (queueItems.length === 0) {
      log("Tất cả đề đã chọn đều đã soạn. Hãy tích 'Cập nhật cả đề đã soạn' nếu muốn làm lại!", "warn");
      return;
    }

    if (queueItems.length > limit) {
      log(`Giới hạn an toàn: Tối đa ${limit} đề mỗi lượt. Đã cắt còn ${limit} đề!`, "warn");
      queueItems.length = limit;
    }

    startUnifiedQueue(queueItems);
  });
}

// -------------------------------------------------------------
// CRAWL & INGEST EXECUTION LOGIC (FE & PE)
// -------------------------------------------------------------
async function executeFeExamCrawl(exam) {
  const url = exam.url;
  const isCommentUpdateOnly = exam.compiled && !exam.redownloadImages;

  log(`[FE] Bắt đầu đề: ${exam.title}`, "info");
  const threadRes = await fetchWithCadence(url);
  if (!threadRes.ok) throw new Error(`HTTP ${threadRes.status}`);

  const html = await threadRes.text();
  const parser = new DOMParser();
  const threadDoc = parser.parseFromString(html, "text/html");

  const titleEl = threadDoc.querySelector("h1.p-title-value, title");
  const threadTitle = titleEl ? titleEl.innerText.replace(" | FuOverflow Community", "").trim() : exam.title;

  let subjectCode = exam.subject_code || "TEST";
  const mCode = threadTitle.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
  if (mCode) subjectCode = mCode[1].toUpperCase();

  const attachmentItems = threadDoc.querySelectorAll("section.message-attachments ul.attachmentList li.file");
  const totalQuestions = attachmentItems.length || exam.question_count || 40;

  const existingMediaSet = new Set(
    (!exam.redownloadImages && state.existingExam && state.existingExam.existing_media_ids)
      ? state.existingExam.existing_media_ids
      : []
  );

  const questionsData = [];

  for (let idx = 0; idx < attachmentItems.length; idx++) {
    if (queueEngine.skipCurrent) {
      queueEngine.skipCurrent = false;
      throw new Error("USER_SKIPPED");
    }
    if (!queueEngine.isRunning) throw new Error("USER_STOPPED");

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
        const mediaHtml = await mediaRes.text();
        const mediaDoc = parser.parseFromString(mediaHtml, "text/html");
        comments = parseCommentsFromHtml(mediaHtml);

        const canSkipImage = isCommentUpdateOnly && mediaId && existingMediaSet.has(mediaId);
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

    const pct = Math.round((qIndex / totalQuestions) * 85);
    updateProgress(pct, `Câu ${qIndex}/${totalQuestions}`);
  }

  // Send payload to backend
  const payload = {
    subject_code: subjectCode,
    exam_title: threadTitle,
    exam_url: url,
    questions: questionsData,
    options: {
      answer_format: "letter_keyword",
      multi_choice_format: elOptMultiJoined && elOptMultiJoined.checked ? "joined" : "comma",
      ai_enabled: true,
    },
  };

  updateProgress(90, "Backend đang xuất file Word...");
  const res = await apiFetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new Error(`Ingest HTTP ${res.status}`);
  const result = await res.json();
  updateProgress(100, "Hoàn tất xuất Word!");

  if (elResultFilename && elResultDownloadBtn && elResultCard) {
    elResultFilename.innerText = `${result.docx_filename}`;
    elResultDownloadBtn.href = `${BACKEND_URL}${result.download_url}`;
    elResultCard.style.display = "block";
  }
}

// -------------------------------------------------------------
// PART E: PE EXAM HANDLING (Download in browser, chunk upload 8MB)
// -------------------------------------------------------------
const PE_CHUNK_SIZE = 8 * 1024 * 1024; // 8 MB

async function executePeExamUpload(exam) {
  log(`[PE] Đang thu thập tài liệu thực hành: ${exam.title}`, "info");
  const threadUrl = exam.url;
  const resp = await fetchWithCadence(threadUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

  const html = await resp.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const titleEl = doc.querySelector("h1.p-title-value, title");
  const examTitle = titleEl ? titleEl.innerText.replace(" | FuOverflow Community", "").trim() : exam.title;

  let subjectCode = exam.subject_code || "TEST";
  const mCode = examTitle.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
  if (mCode) subjectCode = mCode[1].toUpperCase();

  const links = Array.from(doc.querySelectorAll("a[href*='/attachments/'], a[href*='.pdf'], a[href*='.zip']"));
  if (links.length === 0) {
    log(`[PE] Không tìm thấy file đính kèm trong thread này.`, "warn");
    return;
  }

  log(`[PE] Tìm thấy ${links.length} tệp đính kèm. Đang tải và gửi lên backend...`, "info");

  for (let idx = 0; idx < links.length; idx++) {
    if (queueEngine.skipCurrent) throw new Error("USER_SKIPPED");
    if (!queueEngine.isRunning) throw new Error("USER_STOPPED");

    const a = links[idx];
    const fileUrl = a.href;
    const fileName = (a.innerText.trim() || `attachment_${idx + 1}`).replace(/[\\/:*?"<>|]/g, "_");

    log(`[PE] Đang tải tệp [${idx + 1}/${links.length}]: ${fileName}...`, "info");
    const fileResp = await fetchWithCadence(fileUrl);
    if (!fileResp.ok) {
      log(`[PE] Lỗi tải tệp: HTTP ${fileResp.status}`, "warn");
      continue;
    }

    const fileBlob = await fileResp.blob();
    const fileSize = fileBlob.size;
    const totalChunks = Math.ceil(fileSize / PE_CHUNK_SIZE) || 1;

    for (let cIdx = 0; cIdx < totalChunks; cIdx++) {
      const start = cIdx * PE_CHUNK_SIZE;
      const end = Math.min(start + PE_CHUNK_SIZE, fileSize);
      const chunkBlob = fileBlob.slice(start, end);
      const chunkB64 = await blobToBase64(chunkBlob);

      // Upload chunk with retry
      let uploaded = false;
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          const chunkPayload = {
            subject_code: subjectCode,
            exam_title: examTitle,
            filename: fileName,
            chunk_index: cIdx,
            total_chunks: totalChunks,
            data_base64: chunkB64,
          };

          const upRes = await apiFetch("/api/ingest/pe-upload-chunk", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(chunkPayload),
          });

          if (upRes.ok) {
            uploaded = true;
            break;
          }
        } catch (e) {
          await sleep(1000 * attempt);
        }
      }

      if (!uploaded) {
        throw new Error(`Tải lên tệp ${fileName} thất bại ở khối ${cIdx + 1}/${totalChunks}`);
      }

      const filePct = Math.round(((cIdx + 1) / totalChunks) * 100);
      updateProgress(filePct, `PE: Đang tải lên ${fileName} (${cIdx + 1}/${totalChunks})`);
    }

    log(`[PE] Tải lên thành công tệp: ${fileName} (${(fileSize / (1024 * 1024)).toFixed(2)} MB)`, "success");
  }
}

// -------------------------------------------------------------
// PART C: API KEY STATUS PERSISTENCE & SETTINGS
// -------------------------------------------------------------
async function loadSettings() {
  if (!elProvidersContainer) return;
  elProvidersContainer.innerHTML = '<div style="color: var(--muted); font-size: 11px;">Đang tải cấu hình...</div>';

  try {
    const [resSettings, resKeyStatus] = await Promise.all([
      apiFetch("/api/settings"),
      apiFetch("/api/settings/keys/status"),
    ]);

    if (!resSettings.ok) throw new Error(`HTTP ${resSettings.status}`);
    const data = await resSettings.json();
    state.settingsData = data;

    let keyStatusMap = {};
    if (resKeyStatus.ok) {
      const ksData = await resKeyStatus.json();
      (ksData.providers || []).forEach(item => {
        keyStatusMap[item.provider] = item;
      });
    }

    // Format radio
    const multiFmt = data.export?.multi_choice_format || "comma";
    if (multiFmt === "joined") {
      if (elOptMultiJoined) elOptMultiJoined.checked = true;
    } else {
      if (elOptMultiComma) elOptMultiComma.checked = true;
    }

    // Providers list
    const providers = data.ai?.providers || [];
    elProvidersContainer.innerHTML = "";

    providers.forEach((p, idx) => {
      const pRow = document.createElement("div");
      pRow.className = "provider-row";

      const ks = keyStatusMap[p.name] || {};
      const isEnabled = p.enabled ?? ks.enabled ?? false;
      const hasKey = p.has_api_key ?? ks.has_key ?? false;
      const last4 = ks.last4 || p.last4 || "";
      const valid = ks.valid;
      const valTime = ks.validation_time;

      // Persistent status text
      let persistentStatusHtml = "";
      if (hasKey) {
        let validText = valid === true ? "Hợp lệ" : (valid === false ? "Không hợp lệ" : "Đã lưu");
        let timeSuffix = valTime ? ` (kiểm tra ${valTime})` : "";
        let colorClass = valid === true ? "#86efac" : (valid === false ? "#fca5a5" : "#a5b4fc");
        persistentStatusHtml = `<div style="font-size: 11px; color: ${colorClass}; margin-top: 2px;">Đã có khoá ••••${last4 || "••••"} · ${validText}${timeSuffix}</div>`;
      } else {
        persistentStatusHtml = `<div style="font-size: 11px; color: var(--muted); margin-top: 2px;">Chưa có khoá</div>`;
      }

      pRow.innerHTML = `
        <div class="provider-header">
          <span style="font-weight: 600; font-size: 12px; text-transform: uppercase;">${p.name}</span>
          <div style="display: flex; gap: 4px; align-items: center;">
            <label style="display: inline-flex; align-items: center; gap: 3px; font-size: 11px; cursor: pointer;">
              <input type="checkbox" class="check-provider-toggle" ${isEnabled ? "checked" : ""} ${!hasKey ? "disabled" : ""} />
              <span>${isEnabled ? "Bật" : "Tắt"}</span>
            </label>
          </div>
        </div>
        <div style="font-size: 11px; color: var(--muted);">${p.model || ""}</div>
        ${persistentStatusHtml}
        <div class="provider-action-status" style="font-size: 11px; margin-top: 2px; display: none;"></div>
        <div style="display: flex; gap: 4px; margin-top: 4px; flex-wrap: wrap;">
          <input type="password" class="thread-url-input input-api-key" placeholder="Nhập khoá mới để lưu" style="font-size: 11px; padding: 4px 6px; flex: 1; min-width: 120px;" />
          <button class="btn-secondary btn-save-key" style="padding: 4px 8px; font-size: 11px;">Lưu</button>
          <button class="btn-secondary btn-test-key" style="padding: 4px 8px; font-size: 11px;" ${!hasKey ? "disabled" : ""}>Kiểm tra</button>
          <button class="btn-secondary btn-delete-key" style="padding: 4px 8px; font-size: 11px; color: #fca5a5;" ${!hasKey ? "disabled" : ""}>Xoá</button>
        </div>
      `;

      const statusLine = pRow.querySelector(".provider-action-status");

      // Provider Enable Toggle
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
          loadSettings();
        } catch (err) {
          log(`Lỗi cập nhật provider: ${err.message}`, "error");
        }
      });

      // Save Key
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
          log(`Đã lưu khoá mới cho ${p.name}`, "success");
          setTimeout(loadSettings, 500);
        } catch (err) {
          statusLine.style.display = "block";
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Lỗi lưu khoá: ${err.message}`;
        }
      });

      // Delete Key
      pRow.querySelector(".btn-delete-key").addEventListener("click", async () => {
        try {
          const res = await apiFetch(`/api/settings/keys/${encodeURIComponent(p.name)}`, { method: "DELETE" });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          log(`Đã xoá khoá cho ${p.name}`, "warn");
          setTimeout(loadSettings, 500);
        } catch (err) {
          statusLine.style.display = "block";
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Lỗi xoá khoá: ${err.message}`;
        }
      });

      // Test Key Connection
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
            setTimeout(loadSettings, 1000);
          } else {
            statusLine.style.color = "#fca5a5";
            statusLine.innerText = `Không hợp lệ: ${result.message || ""}`;
            setTimeout(loadSettings, 1500);
          }
        } catch (err) {
          statusLine.style.color = "#fca5a5";
          statusLine.innerText = `Lỗi: ${err.message}`;
        }
      });

      elProvidersContainer.appendChild(pRow);
    });

  } catch (err) {
    elProvidersContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px;">Lỗi tải cài đặt: ${err.message}</div>`;
  }
}

// -------------------------------------------------------------
// TAB: ĐÃ SOẠN (Documents list)
// -------------------------------------------------------------
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

    const grouped = {};
    docs.forEach(doc => {
      const code = (doc.subject_code || (doc.filename && doc.filename.split(/[\s\-_]/)[0]) || "KHAC").toUpperCase();
      if (!grouped[code]) grouped[code] = [];
      grouped[code].push(doc);
    });

    elDocsContainer.innerHTML = "";
    Object.keys(grouped).sort().forEach(subjCode => {
      const groupHeader = document.createElement("div");
      groupHeader.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 4px 6px; background: #1e293b; border-radius: 4px; font-weight: 700; font-size: 11px; color: #93c5fd; margin-top: 4px;";
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
          <div style="display: flex; gap: 4px; margin-left: 18px; margin-top: 2px;">
            <a class="btn-secondary btn-download" style="font-size: 10px; padding: 2px 6px;" href="${BACKEND_URL}${doc.download_url}" target="_blank">Tải file</a>
            <button class="btn-secondary btn-open-doc-folder" style="font-size: 10px; padding: 2px 6px;">Mở thư mục</button>
          </div>
        `;

        const cb = item.querySelector(".doc-checkbox");
        groupCheckboxes.push(cb);

        cb.addEventListener("change", () => {
          if (cb.checked) selectedDocs.add(doc.filename);
          else selectedDocs.delete(doc.filename);
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

        elDocsContainer.appendChild(item);
      });

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

  } catch (err) {
    elDocsContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 8px;">Lỗi: ${err.message}</div>`;
  }
}

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

if (elBtnDownloadSubjectFolder) {
  elBtnDownloadSubjectFolder.addEventListener("click", () => {
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
      log("Không xác định được môn cần tải!", "warn");
      return;
    }
    const downloadUrl = `${BACKEND_URL}/api/exports/bundle.zip?subject=${encodeURIComponent(subjectParam)}`;
    triggerFileDownload(downloadUrl, `${subjectParam}_All_${new Date().toISOString().slice(0, 10)}.zip`);
  });
}

if (elBtnOpenFolderDasoan) {
  elBtnOpenFolderDasoan.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
    } catch (e) {
      log(`Lỗi mở thư mục: ${e.message}`, "warn");
    }
  });
}

if (elBtnRefreshDocs) elBtnRefreshDocs.addEventListener("click", loadDocuments);

// Folder open helpers
if (elBtnOpenFolder) {
  elBtnOpenFolder.addEventListener("click", async () => {
    try {
      await apiFetch("/api/exports/open-folder", { method: "POST" });
      log("Đã mở thư mục chứa file Word.", "info");
    } catch (e) {
      log(`Lỗi mở thư mục: ${e.message}`, "warn");
    }
  });
}

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

// Download helper
function triggerFileDownload(url, filename) {
  if (typeof chrome !== "undefined" && chrome.downloads && chrome.downloads.download) {
    chrome.downloads.download({ url: url, filename: filename, saveAs: false }, (id) => {
      if (chrome.runtime.lastError) {
        window.open(url, "_blank");
      } else {
        log(`Đang tải file: ${filename}`, "info");
      }
    });
  } else {
    window.open(url, "_blank");
  }
}

// Comments parser
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

async function fetchWithCadence(url, maxRetries = 3) {
  let delay = 1000;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const res = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" },
      });
      return res;
    } catch (err) {
      if (attempt === maxRetries) throw err;
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

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// -------------------------------------------------------------
// INITIALIZATION
// -------------------------------------------------------------
async function initExtension() {
  checkBackendHealth();
  initSubjectsCache();
  syncFromActiveTab();
}

initExtension();
