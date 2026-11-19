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
  queueCompleted: false,
  expandedSubjects: new Set(),
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

// Clean exam title: strip notification prefix (e.g. '(2) '), XenForo badges, and forum suffix
function cleanExamTitle(rawTitle) {
  if (!rawTitle) return "";
  let t = rawTitle.trim();
  t = t.replace(/^\(\d+\)\s*/, "");
  t = t.replace(/\s*\|\s*FuOverflow\s*Community.*$/i, "");
  const badgeRegex = /^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+/i;
  t = t.replace(badgeRegex, "");
  return t.trim();
}

// Unified Local Machine Time Formatter (HH:MM DD/MM/YYYY or HH:MM)
function formatLocalTime(isoStr, includeDate = true) {
  if (!isoStr) return "--:--";
  try {
    const d = (isoStr instanceof Date) ? isoStr : new Date(isoStr);
    if (isNaN(d.getTime())) return String(isoStr);
    const pad = (n) => String(n).padStart(2, "0");
    const hours = pad(d.getHours());
    const minutes = pad(d.getMinutes());
    if (!includeDate) return `${hours}:${minutes}`;
    const day = pad(d.getDate());
    const month = pad(d.getMonth() + 1);
    const year = d.getFullYear();
    return `${hours}:${minutes} ${day}/${month}/${year}`;
  } catch (e) {
    return String(isoStr);
  }
}

function formatLocalTimeShort(isoStr) {
  return formatLocalTime(isoStr, false);
}

// DOM Elements
const elBackendStatus = document.getElementById("backend-status");
const elUiNoticeBox = document.getElementById("ui-notice-box");
const elQueueResumeBanner = document.getElementById("queue-resume-banner");
const elQueueResumeText = document.getElementById("queue-resume-text");
const elBannerActionsRunning = document.getElementById("banner-actions-running");
const elBannerActionsStopped = document.getElementById("banner-actions-stopped");
const elBtnBannerView = document.getElementById("btn-banner-view");
const elBtnBannerResume = document.getElementById("btn-banner-resume");
const elBtnBannerCancel = document.getElementById("btn-banner-cancel");
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
const elBtnStartQueue = document.getElementById("btn-start-queue");
const elBtnDownloadZip = document.getElementById("btn-download-zip");

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
const elResultCompletedList = document.getElementById("result-completed-list");
const elResultDownloadBtn = document.getElementById("result-download-btn");
const elResultDownloadZipBtn = document.getElementById("result-download-zip-btn");
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
const elInputSearchDasoan = document.getElementById("input-search-dasoan");
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
  if (elBackendStatus) {
    elBackendStatus.className = "status-chip chip-offline";
    elBackendStatus.innerText = "Backend Offline";
  }
  enableActionButtons(false);
  // Do not overwrite completed state if queue has finished
  if (!state.queueCompleted) {
    showNotice(noticeMsg || "Backend Offline. Mở terminal chạy: python run_dev.py");
  }
}

function enableActionButtons(enabled) {
  if (elBtnMainAction) elBtnMainAction.disabled = !enabled;
  if (elBtnStartQueue) elBtnStartQueue.disabled = !enabled;
  if (elBtnSyncTab) elBtnSyncTab.disabled = !enabled;
}

let isCheckingHealth = false;

async function checkBackendHealth() {
  if (isCheckingHealth) return;
  if (typeof document !== "undefined" && document.hidden) return;
  isCheckingHealth = true;

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
  } finally {
    isCheckingHealth = false;
  }
}

// Initial check on load
checkBackendHealth();

// Check health at most once every 30 seconds, paused when sidepanel is hidden
setInterval(() => {
  if (typeof document !== "undefined" && document.hidden) return;
  checkBackendHealth();
}, 30000);

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

function getFilteredExams() {
  const q = (elInputSearchExams ? elInputSearchExams.value.trim().toLowerCase() : "");
  const filterType = chondeState.filterType;

  return chondeState.exams.filter(ex => {
    if (filterType === "FE") {
      const isFE = ex.exam_type === "FE" || /FE|RE/i.test(ex.title);
      if (!isFE) return false;
    } else if (filterType === "PE") {
      const isPE = ex.exam_type === "PE" || /PE/i.test(ex.title);
      if (!isPE) return false;
    }
    if (q) {
      const matchTitle = (ex.title || "").toLowerCase().includes(q);
      const matchTerm = (ex.term || "").toLowerCase().includes(q);
      if (!matchTitle && !matchTerm) return false;
    }
    return true;
  });
}

function renderExamList() {
  if (!elChondeListContainer) return;
  const filtered = getFilteredExams();

  // Auto-deselect exams hidden by current filters or search
  const visibleUrls = new Set(filtered.map(ex => ex.url));
  for (const u of Array.from(chondeState.selectedUrls)) {
    if (!visibleUrls.has(u)) {
      chondeState.selectedUrls.delete(u);
    }
  }

  // Update "Chọn tất cả" checkbox: indeterminate when partially selected
  if (elCheckSelectAllChonde) {
    const totalVisible = filtered.length;
    let selectedVisible = 0;
    filtered.forEach(ex => {
      if (chondeState.selectedUrls.has(ex.url)) selectedVisible++;
    });

    if (totalVisible === 0 || selectedVisible === 0) {
      elCheckSelectAllChonde.checked = false;
      elCheckSelectAllChonde.indeterminate = false;
    } else if (selectedVisible === totalVisible) {
      elCheckSelectAllChonde.checked = true;
      elCheckSelectAllChonde.indeterminate = false;
    } else {
      elCheckSelectAllChonde.checked = false;
      elCheckSelectAllChonde.indeterminate = true;
    }
  }

  updateChondeSelectionBadge();

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
    } else if (ex.missing_file) {
      badgeClass = "badge-status-error";
      badgeText = "Chưa có file";
    } else if (ex.status === "done" || (ex.compiled && ex.has_file !== false)) {
      badgeClass = "badge-status-compiled";
      const timeStr = formatLocalTime(ex.compiled_at_iso || ex.compiled_at);
      badgeText = timeStr ? `Đã soạn (${timeStr})` : "Đã soạn";
    }

    const isChecked = chondeState.selectedUrls.has(ex.url);
    const cleanTitle = cleanExamTitle(ex.title);
    const isCompiled = (ex.status === "done" || (ex.compiled && ex.has_file !== false));

    item.innerHTML = `
      <div class="doc-item-row" style="align-items: flex-start;">
        <input type="checkbox" class="chonde-checkbox" data-url="${ex.url}" ${isChecked ? "checked" : ""} style="margin-top: 3px; cursor: pointer;" />
        <div style="flex: 1; min-width: 0;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 4px;">
            <span class="doc-item-title" title="${cleanTitle}">${cleanTitle}</span>
            <span class="badge-status ${badgeClass}" style="flex-shrink: 0;">${badgeText}</span>
          </div>
          <div class="doc-item-meta" style="margin-top: 4px; display: flex; justify-content: space-between; align-items: center;">
            <span>${ex.exam_type} · ${ex.question_count || 0} câu${ex.term ? ' · ' + ex.term : ''}</span>
            <div style="display: flex; gap: 4px; align-items: center;">
              ${isCompiled ? `
                <button type="button" class="btn-item-download" data-url="${ex.url}" style="background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #34d399; border-radius: 4px; padding: 2px 7px; font-size: 10px; cursor: pointer; white-space: nowrap;">Tải file</button>
                <button type="button" class="btn-item-update" data-url="${ex.url}" style="background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.4); color: #a5b4fc; border-radius: 4px; padding: 2px 7px; font-size: 10px; cursor: pointer; white-space: nowrap;">Cập nhật</button>
              ` : (ex.missing_file ? `
                <button type="button" class="btn-item-retry" data-url="${ex.url}" style="background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); color: #fbbf24; border-radius: 4px; padding: 2px 7px; font-size: 10px; cursor: pointer; white-space: nowrap;">Soạn lại</button>
              ` : '')}
            </div>
          </div>
          ${ex.status === "error" ? `
            <div style="font-size: 10px; color: #fca5a5; margin-top: 3px; display: flex; justify-content: space-between; align-items: center; background: rgba(239, 68, 68, 0.1); padding: 3px 6px; border-radius: 4px;">
              <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 210px;" title="${ex.errorMessage || 'Lỗi xử lý'}">
                ${ex.errorMessage || 'Lỗi xử lý'}
              </span>
              <button type="button" class="btn-retry-single" data-url="${ex.url}" style="background: transparent; border: 1px solid #f87171; color: #f87171; border-radius: 3px; padding: 1px 6px; font-size: 9px; cursor: pointer; white-space: nowrap; margin-left: 4px;">
                Thử lại
              </button>
            </div>
          ` : ""}
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
      renderExamList();
    });

    const dlBtn = item.querySelector(".btn-item-download");
    if (dlBtn) {
      dlBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (ex.download_url) {
          window.open(`${BACKEND_URL}${ex.download_url}`, "_blank");
        } else if (ex.id) {
          window.open(`${BACKEND_URL}/api/exports/${ex.id}/download`, "_blank");
        } else {
          const subj = ex.subject_code || chondeState.selectedSubject || "PRN232";
          window.open(`${BACKEND_URL}/api/exports/download?file=data/output/${subj}/${cleanTitle}.docx`, "_blank");
        }
      });
    }

    const updateBtn = item.querySelector(".btn-item-update");
    if (updateBtn) {
      updateBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startUnifiedQueue([ex]);
      });
    }

    const retryMissingBtn = item.querySelector(".btn-item-retry");
    if (retryMissingBtn) {
      retryMissingBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startUnifiedQueue([ex]);
      });
    }

    const retryBtn = item.querySelector(".btn-retry-single");
    if (retryBtn) {
      retryBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        startUnifiedQueue([ex]);
      });
    }

    elChondeListContainer.appendChild(item);
  });
}

function updateChondeSelectionBadge() {
  const filtered = getFilteredExams();
  const selectedExams = filtered.filter(ex => chondeState.selectedUrls.has(ex.url));
  const count = selectedExams.length;

  if (elBadgeChondeSelected) {
    elBadgeChondeSelected.innerText = `${count} đã chọn`;
  }

  const uncompiledExams = selectedExams.filter(ex => (!ex.compiled || ex.missing_file));
  const compiledExams = selectedExams.filter(ex => (ex.compiled && !ex.missing_file));

  const uCount = uncompiledExams.length;
  const cCount = compiledExams.length;

  if (elBtnStartQueue) {
    if (count === 0) {
      elBtnStartQueue.innerText = "Soạn 0 đề đã chọn";
      elBtnStartQueue.disabled = true;
    } else if (cCount === 0 && uCount > 0) {
      // Chỉ có đề chưa soạn
      elBtnStartQueue.innerText = `Soạn ${uCount} đề`;
      elBtnStartQueue.disabled = false;
    } else if (uCount === 0 && cCount > 0) {
      // Chỉ có đề đã soạn
      elBtnStartQueue.innerText = `Cập nhật ${cCount} đề`;
      elBtnStartQueue.disabled = false;
    } else {
      // Trộn cả chưa soạn và đã soạn
      elBtnStartQueue.innerText = `Soạn ${uCount} · Cập nhật ${cCount}`;
      elBtnStartQueue.disabled = false;
    }
  }

  if (elBtnDownloadZip) {
    if (cCount > 0) {
      elBtnDownloadZip.style.display = "inline-flex";
      elBtnDownloadZip.innerText = "Tải ZIP";
    } else {
      elBtnDownloadZip.style.display = "none";
    }
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
    const filtered = getFilteredExams();
    filtered.forEach(ex => {
      if (checked) chondeState.selectedUrls.add(ex.url);
      else chondeState.selectedUrls.delete(ex.url);
    });
    renderExamList();
  });
}

// -------------------------------------------------------------
// UNIFIED QUEUE ENGINE (Offscreen Worker & UI State Synchronization)
// -------------------------------------------------------------
function saveQueueProgress() {
  try {
    chrome.storage.local.set({
      savedQueueState: {
        items: queueEngine.items,
        currentIndex: queueEngine.currentIndex,
        isRunning: queueEngine.isRunning,
        isPaused: queueEngine.isPaused,
        updatedAt: Date.now(),
      },
    });
  } catch (e) {}
}

function clearSavedQueueProgress() {
  try {
    chrome.storage.local.remove(["savedQueueState"]);
    if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";
  } catch (e) {}
}

function renderCompletedExamsList(completedExams) {
  if (!elResultCard || !elResultCompletedList) return;
  if (!completedExams || completedExams.length === 0) {
    elResultCard.style.display = "none";
    return;
  }

  elResultCompletedList.innerHTML = "";
  completedExams.forEach((ex) => {
    const row = document.createElement("div");
    row.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 4px 6px; background: rgba(255,255,255,0.04); border: 1px solid var(--border); border-radius: 4px; font-size: 11px; margin-bottom: 2px;";
    row.innerHTML = `
      <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 65%; color: #f8fafc; font-weight: 500;" title="${ex.title}">${ex.title}</span>
      <a href="${BACKEND_URL}${ex.download_url}" target="_blank" class="btn-secondary btn-download" style="padding: 2px 8px; font-size: 11px; text-decoration: none; white-space: nowrap;">Tải file</a>
    `;
    elResultCompletedList.appendChild(row);
  });

  if (completedExams.length >= 2) {
    if (elResultDownloadZipBtn) {
      const subj = chondeState.selectedSubject || completedExams[0]?.subject_code || "PRN232";
      elResultDownloadZipBtn.href = `${BACKEND_URL}/api/exports/bundle.zip?subject=${encodeURIComponent(subj)}`;
      elResultDownloadZipBtn.style.display = "inline-flex";
    }
  } else {
    if (elResultDownloadZipBtn) elResultDownloadZipBtn.style.display = "none";
  }

  elResultCard.style.display = "block";
}

function markExamCompletedInList(completedExam) {
  if (chondeState.exams && chondeState.exams.length > 0) {
    const found = chondeState.exams.find(e => (e.url && completedExam.url && e.url === completedExam.url) || (e.title && completedExam.title && cleanExamTitle(e.title) === cleanExamTitle(completedExam.title)));
    if (found) {
      found.compiled = true;
      found.status = "done";
      found.download_url = completedExam.download_url;
      found.compiled_at = completedExam.compiled_at || new Date().toISOString();
    }
    renderExamList();
  }

  if (elInputThreadUrl && elInputThreadUrl.value && completedExam.url && elInputThreadUrl.value.includes(completedExam.url)) {
    checkOpenExamStatus(completedExam.url);
  }
}

async function startUnifiedQueue(items) {
  if (!items || items.length === 0) {
    log("Không có đề nào trong hàng đợi!", "warn");
    return;
  }

  queueEngine.items = items;
  queueEngine.currentIndex = 0;
  queueEngine.isRunning = true;
  queueEngine.isPaused = false;
  state.queueCompleted = false;

  if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";
  if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
  if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
  if (elBtnQueuePause) elBtnQueuePause.innerText = "Dừng";

  const totalItems = items.length;
  const firstTitle = cleanExamTitle(items[0].title || "Đang soạn...");
  if (elQueueProgressTitle) {
    elQueueProgressTitle.innerText = `[1/${totalItems}] ${firstTitle}`;
  }
  if (elQueueOverallRatio) {
    elQueueOverallRatio.innerText = `1/${totalItems}`;
  }
  updateProgress(0, "Đang kết nối tiến trình cào đề nền...");

  // Ensure offscreen document is ready
  try {
    await chrome.runtime.sendMessage({ type: "SETUP_OFFSCREEN" });
  } catch (e) {}

  // Send start command to offscreen
  try {
    chrome.runtime.sendMessage({
      type: "OFFSCREEN_START_QUEUE",
      items: items,
      currentIndex: 0,
      completedExams: [],
    });
  } catch (e) {}
}

if (elBtnBannerView) {
  elBtnBannerView.addEventListener("click", () => {
    if (elQueueProgressCard) {
      elQueueProgressCard.style.display = "block";
      elQueueProgressCard.scrollIntoView({ behavior: "smooth" });
    }
  });
}

if (elBtnBannerResume) {
  elBtnBannerResume.addEventListener("click", () => {
    chrome.storage.local.get(["savedQueueState"], (data) => {
      const qState = data.savedQueueState;
      if (!qState || !qState.items) return;
      if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";

      queueEngine.items = qState.items;
      queueEngine.currentIndex = qState.currentIndex || 0;
      queueEngine.isRunning = true;
      queueEngine.isPaused = false;

      if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
      if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
      if (elBtnQueuePause) elBtnQueuePause.innerText = "Dừng";

      chrome.runtime.sendMessage({ type: "OFFSCREEN_RESUME_QUEUE" }).catch(() => {});
      log("Tiếp tục hàng đợi...", "info");
      renderExamList();
    });
  });
}

if (elBtnBannerCancel) {
  elBtnBannerCancel.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP_QUEUE" }).catch(() => {});
    clearSavedQueueProgress();
    queueEngine.isRunning = false;
    queueEngine.isPaused = false;
    queueEngine.items = [];
    if (elQueueProgressCard) elQueueProgressCard.style.display = "none";
    if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";
    log("Đã huỷ hàng đợi đã lưu.", "info");
  });
}

if (elBtnQueuePause) {
  elBtnQueuePause.addEventListener("click", () => {
    if (queueEngine.isRunning && !queueEngine.isPaused) {
      queueEngine.isPaused = true;
      queueEngine.isRunning = false;
      elBtnQueuePause.innerText = "Tiếp tục";
      chrome.runtime.sendMessage({ type: "OFFSCREEN_PAUSE_QUEUE" }).catch(() => {});
      log("Đã tạm dừng hàng đợi.", "warn");
    } else if (queueEngine.isPaused) {
      queueEngine.isPaused = false;
      queueEngine.isRunning = true;
      elBtnQueuePause.innerText = "Dừng";
      chrome.runtime.sendMessage({ type: "OFFSCREEN_RESUME_QUEUE" }).catch(() => {});
      log("Tiếp tục hàng đợi...", "info");
    }
  });
}

if (elBtnQueueSkip) {
  elBtnQueueSkip.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_SKIP_CURRENT" }).catch(() => {});
    log("Yêu cầu bỏ qua đề hiện tại...", "warn");
  });
}

if (elBtnQueueRetry) {
  elBtnQueueRetry.addEventListener("click", () => {
    chrome.storage.local.get(["savedQueueState"], (data) => {
      const qState = data.savedQueueState;
      const items = (qState && qState.items) ? qState.items : queueEngine.items;
      const failedItems = items.filter(it => it.status === "error");
      if (failedItems.length > 0) {
        startUnifiedQueue(failedItems);
      } else {
        log("Không có đề nào bị lỗi để thử lại.", "info");
      }
    });
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
        const timeLabel = formatLocalTime(data.compiled_at_iso || data.compiled_at);

        if (elOpenExamBadge) {
          elOpenExamBadge.className = "badge-status badge-status-compiled";
          elOpenExamBadge.innerText = `Đã soạn (${timeLabel})`;
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
        const cleanTitle = cleanExamTitle(tabs[0].title || "");
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

// Queue button "Soạn N đề" / "Cập nhật N đề" / "Soạn X · Cập nhật Y"
if (elBtnStartQueue) {
  elBtnStartQueue.addEventListener("click", () => {
    if (chondeState.selectedUrls.size === 0) {
      log("Vui lòng chọn ít nhất một đề!", "warn");
      return;
    }

    const limit = parseInt(elInputBatchLimit ? elInputBatchLimit.value : "20", 10) || 20;
    const filtered = getFilteredExams();
    const queueItems = filtered.filter(ex => chondeState.selectedUrls.has(ex.url));

    if (queueItems.length === 0) {
      log("Không tìm thấy đề nào được chọn!", "warn");
      return;
    }

    if (queueItems.length > limit) {
      log(`Giới hạn an toàn: Tối đa ${limit} đề mỗi lượt. Đã cắt còn ${limit} đề!`, "warn");
      queueItems.length = limit;
    }

    startUnifiedQueue(queueItems);
  });
}

// Download ZIP button for compiled exams
if (elBtnDownloadZip) {
  elBtnDownloadZip.addEventListener("click", () => {
    const subj = chondeState.selectedSubject || "PRN232";
    const zipUrl = `${BACKEND_URL}/api/exports/bundle.zip?subject=${encodeURIComponent(subj)}`;
    window.open(zipUrl, "_blank");
    log(`Đang tải file ZIP cho các đề môn ${subj}...`, "info");
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
  const threadTitle = cleanExamTitle(titleEl ? titleEl.innerText : exam.title);

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

  if (!res.ok) {
    if (res.status === 422) {
      const errData = await res.json().catch(() => ({}));
      const reason = errData.error || errData.detail || "Cổng chất lượng chặn (ảnh không đạt chuẩn)";
      const failedQs = (errData.failed_questions && errData.failed_questions.length > 0)
        ? ` (câu: ${errData.failed_questions.join(", ")})`
        : "";
      const err = new Error(`${reason}${failedQs}`);
      err.status = 422;
      err.shortReason = reason;
      throw err;
    }
    const errText = await res.text().catch(() => "");
    throw new Error(`Ingest HTTP ${res.status}${errText ? ": " + errText.substring(0, 100) : ""}`);
  }
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
        <div style="display: flex; align-items: center; gap: 6px; margin-top: 3px;">
          <span style="font-size: 11px; color: var(--muted);">Model:</span>
          <select class="select-provider-model" style="font-size: 11px; padding: 2px 4px; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 3px; max-width: 180px;">
            <option value="${p.model || ''}">${p.model || 'Chọn model'}</option>
          </select>
          <button class="btn-secondary btn-fetch-models" style="padding: 2px 6px; font-size: 10px;" title="Tải danh sách model trực tiếp từ khoá">Tải model</button>
        </div>
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
      const modelSelect = pRow.querySelector(".select-provider-model");
      const btnFetchModels = pRow.querySelector(".btn-fetch-models");

      // Populate models dynamically
      const loadModelsForSelect = async () => {
        try {
          btnFetchModels.innerText = "...";
          const mRes = await apiFetch(`/api/settings/providers/${encodeURIComponent(p.name)}/models`);
          if (mRes.ok) {
            const mData = await mRes.json();
            const list = mData.models || [];
            if (list.length > 0) {
              const curModel = p.model;
              modelSelect.innerHTML = list.map(m => `<option value="${m.id}" ${m.id === curModel ? "selected" : ""}>${m.name || m.id}</option>`).join("");
              if (!list.some(m => m.id === curModel) && curModel) {
                modelSelect.insertAdjacentHTML("afterbegin", `<option value="${curModel}" selected>${curModel} (Hiện tại)</option>`);
              }
            }
          }
        } catch (e) {
        } finally {
          btnFetchModels.innerText = "Tải model";
        }
      };

      btnFetchModels.addEventListener("click", loadModelsForSelect);

      // Model change
      modelSelect.addEventListener("change", async (e) => {
        const newModel = e.target.value;
        try {
          const payload = { ...state.settingsData };
          payload.ai.providers[idx].model = newModel;
          await apiFetch("/api/settings", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          log(`Đã đổi model cho ${p.name} thành ${newModel}`, "info");
        } catch (err) {
          log(`Lỗi đổi model: ${err.message}`, "error");
        }
      });

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

function saveExpandedSubjects() {
  const storage = (typeof chrome !== "undefined" && chrome.storage && (chrome.storage.session || chrome.storage.local)) || null;
  if (storage) {
    try {
      storage.set({ dasoan_expanded_subjects: Array.from(state.expandedSubjects) });
    } catch (e) {}
  }
}

async function loadExpandedSubjects() {
  const storage = (typeof chrome !== "undefined" && chrome.storage && (chrome.storage.session || chrome.storage.local)) || null;
  if (storage) {
    return new Promise((resolve) => {
      try {
        storage.get(["dasoan_expanded_subjects"], (res) => {
          if (res && Array.isArray(res.dasoan_expanded_subjects)) {
            state.expandedSubjects = new Set(res.dasoan_expanded_subjects);
          }
          resolve();
        });
      } catch (e) {
        resolve();
      }
    });
  }
}

function filterDasoanDocuments() {
  if (!elDocsContainer) return;
  const q = (elInputSearchDasoan && elInputSearchDasoan.value.trim()) || "";
  const qClean = removeAccents(q);
  const isSearching = qClean.length > 0;

  const groups = elDocsContainer.querySelectorAll(".dasoan-group");
  let matchCount = 0;

  groups.forEach(group => {
    const subjCode = group.dataset.subject || "";
    const subjName = group.dataset.subjectName || "";
    const codeClean = removeAccents(subjCode);
    const nameClean = removeAccents(subjName);
    const isMatch = !isSearching || codeClean.includes(qClean) || nameClean.includes(qClean);

    const arrow = group.querySelector(".dasoan-arrow");
    const docsWrap = group.querySelector(".dasoan-group-docs");

    if (isMatch) {
      group.style.display = "flex";
      matchCount++;
      if (isSearching) {
        if (arrow) arrow.classList.add("expanded");
        if (docsWrap) docsWrap.classList.add("expanded");
      } else {
        const wasExpanded = state.expandedSubjects.has(subjCode);
        if (arrow) arrow.classList.toggle("expanded", wasExpanded);
        if (docsWrap) docsWrap.classList.toggle("expanded", wasExpanded);
      }
    } else {
      group.style.display = "none";
    }
  });

  let noMatchEl = document.getElementById("dasoan-no-match");
  if (isSearching && matchCount === 0 && groups.length > 0) {
    if (!noMatchEl) {
      noMatchEl = document.createElement("div");
      noMatchEl.id = "dasoan-no-match";
      noMatchEl.style.cssText = "text-align: center; color: var(--muted); font-size: 11px; padding: 16px;";
      elDocsContainer.appendChild(noMatchEl);
    }
    noMatchEl.innerText = `Không tìm thấy môn nào khớp với "${q}".`;
  } else if (noMatchEl) {
    noMatchEl.remove();
  }
}

function formatSubjectGroupHeader(subjCode, rawName) {
  const code = (subjCode || "").trim().toUpperCase();
  if (!rawName) return { title: code, display: code, cleanName: "" };

  let name = rawName.trim();
  // Strip parentheses/brackets containing the subject code, e.g. (PRN232) or [PRN232]
  const parenRegex = new RegExp(`[\\(\\[\\{]\\s*${code}\\s*[\\)\\]\\}]`, "gi");
  name = name.replace(parenRegex, "").trim();

  // Strip leading subject code e.g. "PRN232 - " or "PRN232: " or "PRN232 "
  const prefixRegex = new RegExp(`^${code}\\s*[-–—:·.]*\\s*`, "gi");
  name = name.replace(prefixRegex, "").trim();

  // Strip trailing subject code e.g. " - PRN232"
  const suffixRegex = new RegExp(`\\s*[-–—:·.]*\\s*${code}$`, "gi");
  name = name.replace(suffixRegex, "").trim();

  // If the remaining name is empty or identical to subject code (case-insensitive)
  if (!name || name.toUpperCase() === code) {
    return { title: code, display: code, cleanName: "" };
  }

  const fullDisplay = `${code} · ${name}`;
  return { title: fullDisplay, display: fullDisplay, cleanName: name };
}

async function loadDocuments() {
  if (!elDocsContainer) return;
  elDocsContainer.innerHTML = '<div style="text-align: center; color: var(--muted); font-size: 11px; padding: 12px;">Đang tải danh sách tài liệu...</div>';
  selectedDocs.clear();
  updateDasoanSelectionBadge();
  if (elCheckSelectAllDasoan) elCheckSelectAllDasoan.checked = false;

  await loadExpandedSubjects();

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
      const subjObj = (state.cachedSubjects || []).find(s => (s.code || "").toUpperCase() === subjCode.toUpperCase());
      const rawSubjName = subjObj ? (subjObj.name || "") : "";
      const { display: displayTitle, cleanName } = formatSubjectGroupHeader(subjCode, rawSubjName);
      const count = grouped[subjCode].length;

      const groupEl = document.createElement("div");
      groupEl.className = "dasoan-group";
      groupEl.dataset.subject = subjCode;
      groupEl.dataset.subjectName = cleanName || rawSubjName;

      const groupHeader = document.createElement("div");
      groupHeader.className = "dasoan-group-header";
      groupHeader.innerHTML = `
        <div style="display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; margin-right: 8px;">
          <span class="dasoan-arrow"></span>
          <span class="dasoan-group-title" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0;" title="${displayTitle}">${displayTitle}</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
          <span class="dasoan-group-count" style="font-size: 11px; color: #94a3b8; font-weight: normal; white-space: nowrap;">${count} đề</span>
          <label style="display: inline-flex; align-items: center; gap: 3px; font-size: 10px; cursor: pointer; color: #94a3b8; font-weight: normal; flex-shrink: 0;" onclick="event.stopPropagation();">
            <input type="checkbox" class="check-group-select" data-subject="${subjCode}" />
            <span>Chọn nhóm</span>
          </label>
        </div>
      `;

      const groupDocsWrap = document.createElement("div");
      groupDocsWrap.className = "dasoan-group-docs";

      const isExpanded = state.expandedSubjects.has(subjCode);
      if (isExpanded) {
        groupHeader.querySelector(".dasoan-arrow").classList.add("expanded");
        groupDocsWrap.classList.add("expanded");
      }

      // Toggle group expansion on header click
      groupHeader.addEventListener("click", (e) => {
        if (e.target.closest("label") || e.target.closest("input")) return;
        const arrow = groupHeader.querySelector(".dasoan-arrow");
        const willExpand = !groupDocsWrap.classList.contains("expanded");
        groupDocsWrap.classList.toggle("expanded", willExpand);
        arrow.classList.toggle("expanded", willExpand);

        const q = (elInputSearchDasoan && elInputSearchDasoan.value.trim()) || "";
        if (!q) {
          if (willExpand) state.expandedSubjects.add(subjCode);
          else state.expandedSubjects.delete(subjCode);
          saveExpandedSubjects();
        }
      });

      const groupCheckboxes = [];
      grouped[subjCode].forEach(doc => {
        const item = document.createElement("div");
        item.className = "doc-item";
        const timeStr = formatLocalTime(doc.created_at);

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

        groupDocsWrap.appendChild(item);
      });

      const groupCb = groupHeader.querySelector(".check-group-select");
      groupCb.addEventListener("change", (e) => {
        e.stopPropagation();
        const checked = groupCb.checked;
        groupCheckboxes.forEach(cb => {
          cb.checked = checked;
          const fn = cb.dataset.filename;
          if (checked) selectedDocs.add(fn);
          else selectedDocs.delete(fn);
        });
        updateDasoanSelectionBadge();
      });

      groupEl.appendChild(groupHeader);
      groupEl.appendChild(groupDocsWrap);
      elDocsContainer.appendChild(groupEl);
    });

    filterDasoanDocuments();

  } catch (err) {
    elDocsContainer.innerHTML = `<div style="color: #fca5a5; font-size: 11px; padding: 8px;">Lỗi: ${err.message}</div>`;
  }
}

if (elInputSearchDasoan) {
  elInputSearchDasoan.addEventListener("input", filterDasoanDocuments);
}

if (elCheckSelectAllDasoan) {
  elCheckSelectAllDasoan.addEventListener("change", () => {
    const checked = elCheckSelectAllDasoan.checked;
    const allCbs = elDocsContainer.querySelectorAll(".dasoan-group:not([style*='display: none']) .doc-checkbox, .dasoan-group:not([style*='display: none']) .check-group-select");
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

    // Score parsing: prioritize .user-fuo-vote next to name, fallback to reactionsBar
    let upvotes = 0;
    const voteEl = c.querySelector(".user-fuo-vote, .message-attribution-user .user-fuo-vote");
    if (voteEl) {
      const text = voteEl.innerText.trim();
      const mVote = text.match(/(-?\d+)/);
      if (mVote) {
        upvotes = parseInt(mVote[1], 10);
      }
    } else {
      const rxBar = c.querySelector(".reactionsBar");
      if (rxBar && (rxBar.classList.contains("is-active") || rxBar.querySelector(".reaction-image, .reaction"))) {
        const rxText = rxBar.innerText.trim();
        const bdis = rxBar.querySelectorAll("a.reactionsBar-link bdi, .reactionsBar bdi");
        const namedCount = bdis.length;

        const mOthers = rxText.match(/(?:and|và)\s+(\d+)\s+(?:others|người khác)/i);
        const othersCount = mOthers ? parseInt(mOthers[1], 10) : 0;

        const mTotal = rxText.match(/(\d+)\s+(?:reactions|lượt thích|phản ứng)/i);
        if (mTotal) {
          upvotes = parseInt(mTotal[1], 10);
        } else if (namedCount > 0 || othersCount > 0) {
          upvotes = namedCount + othersCount;
        } else {
          const icons = rxBar.querySelectorAll(".reaction-image, .reaction[data-reaction-id]").length;
          upvotes = Math.max(icons, 1);
        }
      }
    }
    if (upvotes > 1000) {
      upvotes = 0;
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

function applyQueueStateToUi(qState) {
  if (!qState || !qState.items || qState.items.length === 0) return;

  queueEngine.items = qState.items;
  queueEngine.currentIndex = qState.currentIndex || 0;
  queueEngine.isRunning = !!qState.isRunning;
  queueEngine.isPaused = !!qState.isPaused;

  const total = qState.items.length;
  const cur = Math.min((qState.currentIndex || 0) + 1, total);
  const curTitle = qState.currentExamTitle || cleanExamTitle(qState.items[qState.currentIndex]?.title || "Đang soạn...");

  // Render completed list if present
  if (qState.completedExams && qState.completedExams.length > 0) {
    renderCompletedExamsList(qState.completedExams);
  }

  if (qState.isRunning) {
    // 1. Show running progress card with current stats (DO NOT RESET TO 0/0)
    if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
    if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
    if (elBtnQueuePause) elBtnQueuePause.innerText = "Dừng";

    if (elQueueProgressTitle) elQueueProgressTitle.innerText = `[${cur}/${total}] ${curTitle}`;
    if (elQueueOverallRatio) elQueueOverallRatio.innerText = `${cur}/${total}`;
    if (elProgressBar && qState.progressPct !== undefined) elProgressBar.style.width = `${qState.progressPct}%`;
    if (elStatsSummaryLine) {
      elStatsSummaryLine.innerText = qState.statusText || `Câu ${qState.currentQuestionIndex || 0}/${qState.totalQuestions || 0}`;
    }

    // 2. Banner: Show ONLY "Xem tiến trình"
    if (elQueueResumeBanner && elQueueResumeText) {
      const qText = qState.statusText || `Câu ${qState.currentQuestionIndex || 0}/${qState.totalQuestions || 0}`;
      elQueueResumeText.innerText = `Đang soạn: ${curTitle} (${qText})`;
      if (elBannerActionsRunning) elBannerActionsRunning.style.display = "block";
      if (elBannerActionsStopped) elBannerActionsStopped.style.display = "none";
      elQueueResumeBanner.style.display = "block";
    }
  } else if (qState.isPaused) {
    if (elQueueProgressCard) elQueueProgressCard.style.display = "block";
    if (elQueueControlsRow) elQueueControlsRow.style.display = "flex";
    if (elBtnQueuePause) elBtnQueuePause.innerText = "Tiếp tục";

    if (elQueueProgressTitle) elQueueProgressTitle.innerText = `[${cur}/${total}] (Tạm dừng) ${curTitle}`;
    if (elQueueOverallRatio) elQueueOverallRatio.innerText = `${cur}/${total}`;
    if (elProgressBar && qState.progressPct !== undefined) elProgressBar.style.width = `${qState.progressPct}%`;
    if (elStatsSummaryLine) {
      elStatsSummaryLine.innerText = qState.statusText || `Tạm dừng ở câu ${qState.currentQuestionIndex || 0}/${qState.totalQuestions || 0}`;
    }

    // Banner: Show "Tiếp tục" and "Huỷ"
    if (elQueueResumeBanner && elQueueResumeText) {
      elQueueResumeText.innerText = `Hàng đợi đang dừng (${cur}/${total})`;
      if (elBannerActionsRunning) elBannerActionsRunning.style.display = "none";
      if (elBannerActionsStopped) elBannerActionsStopped.style.display = "flex";
      elQueueResumeBanner.style.display = "block";
    }
  } else if (qState.isCompleted) {
    state.queueCompleted = true;
    if (elQueueControlsRow) elQueueControlsRow.style.display = "none";
    if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";
  }

  renderExamList();
}

async function checkSavedQueueState() {
  chrome.storage.local.get(["savedQueueState"], (data) => {
    if (data.savedQueueState) {
      applyQueueStateToUi(data.savedQueueState);
    }
  });
}

async function checkExternalQueueRequest() {
  chrome.storage.local.get(["externalQueueRequest"], (data) => {
    const req = data.externalQueueRequest;
    if (!req || !req.exams || req.exams.length === 0) return;
    chrome.storage.local.remove(["externalQueueRequest"]);
    log(`Nhận yêu cầu soạn ${req.exams.length} đề từ Web Dashboard. Bắt đầu...`, "info");
    startUnifiedQueue(req.exams);
  });
}

// -------------------------------------------------------------
// INITIALIZATION
// -------------------------------------------------------------
async function initExtension() {
  checkBackendHealth();
  initSubjectsCache();
  syncFromActiveTab();
  checkSavedQueueState();
  checkExternalQueueRequest();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "THREAD_SELECTED" && message.data) {
    const data = message.data;
    if (elInputThreadUrl) elInputThreadUrl.value = data.url;
    const cleanTitle = cleanExamTitle(data.title);
    if (elThreadTitleDisplay) {
      elThreadTitleDisplay.innerText = cleanTitle;
      elThreadTitleDisplay.title = cleanTitle;
    }
    checkOpenExamStatus(data.url);
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "QUEUE_PROGRESS_UPDATE" && message.data) {
    applyQueueStateToUi(message.data);
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "EXAM_COMPLETED" && message.exam) {
    markExamCompletedInList(message.exam);
    chrome.storage.local.get(["savedQueueState"], (d) => {
      if (d.savedQueueState && d.savedQueueState.completedExams) {
        renderCompletedExamsList(d.savedQueueState.completedExams);
      }
    });
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === "QUEUE_ALL_COMPLETED") {
    state.queueCompleted = true;
    queueEngine.isRunning = false;
    queueEngine.isPaused = false;
    if (elQueueControlsRow) elQueueControlsRow.style.display = "none";
    if (elQueueResumeBanner) elQueueResumeBanner.style.display = "none";
    if (message.completedExams) {
      renderCompletedExamsList(message.completedExams);
    }
    renderExamList();
    sendResponse({ ok: true });
    return true;
  }
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && changes.savedQueueState) {
    applyQueueStateToUi(changes.savedQueueState.newValue);
  }
});

initExtension();
