// background.js - DocxStacked Chromium Extension (MV3)
// Configures side panel behavior to open when user clicks extension action icon.

const BACKGROUND_INSTANCE_ID = "bg_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 6);

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error) => console.error("Side panel behavior error:", error));

// In-memory auth state cached from fuoverflow.com session
let lastAuthStatus = {
  logged_in: false,
  username: null,
  timestamp: 0,
};

// Active runId tracked by background as Single Writer
let activeRunId = null;

// Restore persisted auth status & activeRunId on worker startup
chrome.storage.local.get(["lastAuthStatus", "savedQueueState"], (res) => {
  if (res && res.lastAuthStatus) {
    lastAuthStatus = res.lastAuthStatus;
  }
  if (res && res.savedQueueState && res.savedQueueState.runId) {
    activeRunId = res.savedQueueState.runId;
  }
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.lastAuthStatus && changes.lastAuthStatus.newValue) {
    lastAuthStatus = changes.lastAuthStatus.newValue;
  }
});

// Heartbeat function to report auth status to backend every 30-60s
async function sendAuthHeartbeat() {
  try {
    const res = await fetch("https://fuoverflow.com/", {
      method: "GET",
      credentials: "include",
    });
    if (!res.ok) return;
    const html = await res.text();
    const isLoggedIn = html.includes('data-logged-in="true"');
    let username = null;
    if (isLoggedIn) {
      const match = html.match(/class="[^"]*p-navgroup-linkText[^"]*">([^<]+)<\/span>/);
      if (match) {
        username = match[1].trim();
      }
    }

    lastAuthStatus = {
      logged_in: isLoggedIn,
      username: username,
      timestamp: Date.now(),
    };
    chrome.storage.local.set({ lastAuthStatus }).catch(() => {});

    // Ping backend with auth status
    await fetch("http://127.0.0.1:8000/api/auth/extension-heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        logged_in: isLoggedIn,
        username: username,
      }),
    });
  } catch (err) {
    // Backend or Fuoverflow offline
  }
}

// Setup periodic alarm for heartbeat (every 0.5 min = 30 seconds)
chrome.alarms.create("auth_heartbeat_alarm", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "auth_heartbeat_alarm") {
    sendAuthHeartbeat();
  }
});

// Immediate heartbeat on extension launch
sendAuthHeartbeat();

// Ensure Offscreen Document exists for background crawling
async function ensureOffscreenDocument() {
  if (chrome.offscreen && chrome.offscreen.hasDocument) {
    const hasDoc = await chrome.offscreen.hasDocument();
    if (!hasDoc) {
      await chrome.offscreen.createDocument({
        url: "offscreen.html",
        reasons: ["DOM_SCRAPING"],
        justification: "Chạy hàng đợi cào đề nền khi đóng sidepanel",
      });
    }
  }
}

async function appendLogToStorage(msg, level = "info") {
  try {
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
    const logItem = {
      text: `[${timeStr}] ${msg}`,
      rawMsg: msg,
      level: level,
      timestamp: Date.now(),
    };

    chrome.runtime.sendMessage({
      type: "APPEND_LOG",
      logItem: logItem,
    }).catch(() => {});

    const data = await chrome.storage.local.get(["recentLogs"]);
    const list = data.recentLogs || [];
    list.push(logItem);
    if (list.length > 50) list.shift();
    await chrome.storage.local.set({ recentLogs: list });
  } catch (e) {
    console.error("appendLogToStorage error:", e);
  }
}

function cleanExamTitle(rawTitle) {
  if (!rawTitle) return "";
  let t = rawTitle.trim();
  t = t.replace(/^\(\d+\)\s*/, "");
  t = t.replace(/\s*\|\s*FuOverflow\s*Community.*$/i, "");
  const badgeRegex = /^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+/i;
  t = t.replace(badgeRegex, "");
  return t.trim();
}

// -------------------------------------------------------------
// RECONCILIATION & QUEUE SINGLE WRITER ENGINE
// -------------------------------------------------------------
async function isOffscreenWorkerActive(expectedRunId) {
  if (!chrome.offscreen || !chrome.offscreen.hasDocument) return false;
  try {
    const hasDoc = await chrome.offscreen.hasDocument();
    if (!hasDoc) return false;
  } catch (e) {
    return false;
  }

  try {
    const status = await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 1500);
      chrome.runtime.sendMessage({ type: "OFFSCREEN_GET_STATUS" }, (resp) => {
        clearTimeout(timer);
        if (chrome.runtime.lastError) resolve(null);
        else resolve(resp);
      });
    });

    if (!status || !status.isRunning) return false;
    if (expectedRunId && status.runId !== expectedRunId) return false;

    // Requirement 1: Kiểm tra lastProgressAt không quá 60s
    const now = Date.now();
    const lastProgress = status.lastProgressAt || 0;
    if (lastProgress > 0 && now - lastProgress > 60000) {
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

async function reconcileQueueState() {
  const data = await chrome.storage.local.get(["savedQueueState"]);
  const qState = data.savedQueueState;
  if (!qState) return null;

  activeRunId = qState.runId || null;

  if (qState.isRunning) {
    const alive = await isOffscreenWorkerActive(qState.runId);
    if (!alive) {
      // Requirement 1: Phát hiện hàng đợi ma khi khởi động lại hoặc mở sidepanel
      const examTitle = cleanExamTitle(qState.currentExamTitle || (qState.items && qState.items[0]?.title) || "Đề thi");
      const qIdx = qState.currentQuestionIndex || 1;
      const totQ = qState.totalQuestions || (qState.items && qState.items[0]?.question_count) || 40;
      qState.isRunning = false;
      qState.isInterrupted = true;
      qState.interruptedAt = Date.now();
      qState.statusText = `Hàng đợi bị gián đoạn: ${examTitle}, Câu ${qIdx}/${totQ}`;
      qState.updatedAt = Date.now();

      // Only background writes savedQueueState (Requirement 3)
      await chrome.storage.local.set({ savedQueueState: qState });
      await appendLogToStorage(`[Reconcile] Phát hiện hàng đợi ma (runId: ${qState.runId}). Đã đổi trạng thái thành Bị gián đoạn.`, "warn");
    }
  }
  return qState;
}

// In-memory processed runIds to deduplicate commands
const processedRunIds = new Set();

async function startQueueRun({ runId, items, subjectCode, force = false }) {
  await reconcileQueueState();
  const storageData = await chrome.storage.local.get(["savedQueueState"]);
  const prevQueue = storageData.savedQueueState;

  if (prevQueue && prevQueue.isRunning && !force) {
    const busyTitle = prevQueue.currentExamTitle || "Đang soạn đề";
    return {
      ok: false,
      error: "QUEUE_RUNNING",
      currentExamTitle: busyTitle,
      runId: prevQueue.runId,
      message: `Hàng đợi đang soạn đề: "${busyTitle}". Vui lòng đợi hoàn tất hoặc chọn thay thế.`,
    };
  }

  processedRunIds.add(runId);
  if (processedRunIds.size > 200) {
    const first = processedRunIds.values().next().value;
    processedRunIds.delete(first);
  }

  activeRunId = runId;

  if (prevQueue && prevQueue.isRunning && force) {
    await appendLogToStorage(`[Hàng đợi] Dừng và thay thế hàng đợi cũ bằng phiên mới (${runId})`, "warn");
    try {
      await chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP_QUEUE" });
    } catch (e) {}
  } else {
    await appendLogToStorage(`[Hàng đợi] Bắt đầu ${items.length} đề (runId: ${runId})`, "info");
  }

  await ensureOffscreenDocument();

  const taggedExams = items.map((ex) => ({
    ...ex,
    runId: runId,
  }));

  const firstTitle = cleanExamTitle(taggedExams[0].title || "Đang soạn...");
  const firstTotalQ = taggedExams[0].question_count || 40;

  // Single Writer: Atomically wipe old state and set initial state
  const initialQueueState = {
    runId: runId,
    items: taggedExams,
    currentIndex: 0,
    isRunning: true,
    isPaused: false,
    isCompleted: false,
    isInterrupted: false,
    currentExamTitle: firstTitle,
    currentQuestionIndex: 1,
    totalQuestions: firstTotalQ,
    progressPct: 0,
    statusText: `Câu 1/${firstTotalQ}`,
    completedExams: [],
    lastProgressAt: Date.now(),
    updatedAt: Date.now(),
  };

  await chrome.storage.local.set({
    savedQueueState: initialQueueState,
  });

  // Notify sidepanel atomically
  try {
    chrome.runtime.sendMessage({
      type: "QUEUE_RESET",
      runId: runId,
    }).catch(() => {});
  } catch (e) {}

  // Register with backend
  try {
    await fetch("http://127.0.0.1:8000/api/ingest/register-run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DocxStacked-Ext": chrome.runtime.id,
      },
      body: JSON.stringify({
        runId: runId,
        subjectCode: subjectCode || taggedExams[0].subject_code || "TEST",
        examUrls: taggedExams.map((e) => e.url),
      }),
    });
  } catch (e) {}

  // Start offscreen worker
  let offscreenStarted = false;
  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      const resp = await chrome.runtime.sendMessage({
        type: "OFFSCREEN_START_QUEUE",
        runId: runId,
        items: taggedExams,
        currentIndex: 0,
        completedExams: [],
      });
      if (resp && resp.ok) {
        offscreenStarted = true;
        break;
      }
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 150));
  }

  if (!offscreenStarted) {
    throw new Error("Offscreen scraper không phản hồi sau 5 lần thử");
  }

  return {
    ok: true,
    ack: true,
    runId: runId,
    queued_count: items.length,
    message: `Đã nhận ${items.length} đề, đang soạn`,
  };
}

async function cancelQueueRun(targetRunId) {
  try {
    const data = await chrome.storage.local.get(["savedQueueState"]);
    const q = data.savedQueueState;
    const runIdToCancel = targetRunId || q?.runId || activeRunId;

    try {
      await chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP_QUEUE" });
    } catch (e) {}

    await chrome.storage.local.remove(["savedQueueState"]);
    activeRunId = null;

    if (chrome.offscreen && chrome.offscreen.closeDocument) {
      try {
        const hasDoc = await chrome.offscreen.hasDocument();
        if (hasDoc) await chrome.offscreen.closeDocument();
      } catch (e) {}
    }

    try {
      await fetch("http://127.0.0.1:8000/api/ingest/cancel-run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-DocxStacked-Ext": chrome.runtime.id,
        },
        body: JSON.stringify({ runId: runIdToCancel }),
      });
    } catch (e) {}

    await appendLogToStorage(`Đã huỷ hàng đợi (runId: ${runIdToCancel})`, "info");
    return { ok: true, cancelled_run_id: runIdToCancel };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// Internal Messages Listener
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "OPEN_SIDEPANEL") {
    const tabId = sender.tab ? sender.tab.id : undefined;
    if (tabId) {
      chrome.sidePanel.open({ tabId }).catch((err) => console.error("Error opening side panel:", err));
    }
    sendResponse({ ok: true });
    return true;
  }
  if (message.type === "TRIGGER_HEARTBEAT") {
    sendAuthHeartbeat().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message.type === "SETUP_OFFSCREEN") {
    ensureOffscreenDocument().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message.type === "GET_BACKGROUND_VERSION") {
    sendResponse({
      ok: true,
      version: chrome.runtime.getManifest().version,
      instanceId: BACKGROUND_INSTANCE_ID,
    });
    return true;
  }
  if (message.type === "RECONCILE_QUEUE_STATE") {
    reconcileQueueState().then((state) => {
      sendResponse({ ok: true, queueState: state });
    });
    return true;
  }
  if (message.type === "CHECK_WORKER_ALIVE") {
    isOffscreenWorkerActive(activeRunId).then((alive) => {
      sendResponse({ ok: true, alive: alive, activeRunId: activeRunId });
    });
    return true;
  }
  if (message.type === "QUEUE_START_COMMAND") {
    startQueueRun({
      runId: message.runId,
      items: message.items,
      subjectCode: message.subjectCode,
      force: Boolean(message.force),
    }).then((res) => sendResponse(res));
    return true;
  }
  if (message.type === "QUEUE_CANCEL_COMMAND" || message.type === "QUEUE_STOP_COMMAND") {
    cancelQueueRun(message.runId).then((res) => sendResponse(res));
    return true;
  }
  if (message.type === "QUEUE_PAUSE_COMMAND") {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_PAUSE_QUEUE" }).catch(() => {});
    chrome.storage.local.get(["savedQueueState"], (d) => {
      if (d.savedQueueState) {
        d.savedQueueState.isPaused = true;
        d.savedQueueState.isRunning = false;
        d.savedQueueState.updatedAt = Date.now();
        chrome.storage.local.set({ savedQueueState: d.savedQueueState });
      }
    });
    sendResponse({ ok: true });
    return true;
  }
  if (message.type === "QUEUE_RESUME_COMMAND") {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_RESUME_QUEUE" }).catch(() => {});
    chrome.storage.local.get(["savedQueueState"], (d) => {
      if (d.savedQueueState) {
        d.savedQueueState.isPaused = false;
        d.savedQueueState.isRunning = true;
        d.savedQueueState.updatedAt = Date.now();
        chrome.storage.local.set({ savedQueueState: d.savedQueueState });
      }
    });
    sendResponse({ ok: true });
    return true;
  }
  if (message.type === "QUEUE_SKIP_COMMAND") {
    chrome.runtime.sendMessage({ type: "OFFSCREEN_SKIP_CURRENT" }).catch(() => {});
    sendResponse({ ok: true });
    return true;
  }

  // Single Writer: Save progress update from offscreen
  if (message.type === "QUEUE_PROGRESS_UPDATE" && message.data) {
    const data = message.data;
    if (activeRunId && data.runId && data.runId !== activeRunId) {
      console.warn(`[Background] Stale progress update from ${data.runId} ignored (active: ${activeRunId})`);
      chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP_QUEUE" }).catch(() => {});
      return;
    }
    if (data.runId) activeRunId = data.runId;
    data.lastProgressAt = Date.now();
    data.updatedAt = Date.now();
    chrome.storage.local.set({ savedQueueState: data }).catch(() => {});
    return;
  }

  if (message.type === "QUEUE_ALL_COMPLETED") {
    chrome.storage.local.get(["savedQueueState"], (res) => {
      if (res && res.savedQueueState) {
        const q = res.savedQueueState;
        q.isRunning = false;
        q.isCompleted = true;
        q.completedExams = message.completedExams || q.completedExams;
        q.updatedAt = Date.now();
        chrome.storage.local.set({ savedQueueState: q });
      }
    });
    return;
  }
});

// External messages from web dashboard
chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  const allowedOrigins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
  ];

  if (!sender.origin || !allowedOrigins.includes(sender.origin)) {
    sendResponse({ ok: false, error: "Origin not allowed" });
    return;
  }

  if (message.type === "PING_EXTENSION" || message.type === "PING") {
    sendResponse({
      ok: true,
      version: chrome.runtime.getManifest().version,
      name: "DocxStacked",
      logged_in: Boolean(lastAuthStatus.logged_in),
      username: lastAuthStatus.username,
      timestamp: lastAuthStatus.timestamp,
    });
    sendAuthHeartbeat().catch(() => {});
    return;
  }

  if (message.type === "ENQUEUE_EXAMS") {
    const payload = message.payload || {};
    const exams = payload.exams || [];
    const subjectCode = payload.subjectCode || "TEST";
    const runId = payload.runId || ("run_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 6));
    const force = Boolean(payload.force);

    if (!Array.isArray(exams) || exams.length === 0) {
      sendResponse({ ok: false, error: "Danh sách đề trống" });
      return;
    }

    // 1. Chống trùng theo runId
    if (processedRunIds.has(runId)) {
      sendResponse({
        ok: true,
        ack: true,
        duplicate: true,
        runId: runId,
        queued_count: exams.length,
        message: `Lệnh trùng (${runId}) đã được tiếp nhận, bỏ qua không xử lý lại.`,
      });
      return;
    }

    startQueueRun({
      runId: runId,
      items: exams,
      subjectCode: subjectCode,
      force: force,
    })
      .then(async (res) => {
        if (res.ok) {
          try {
            const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tabs && tabs[0]) {
              await chrome.sidePanel.open({ tabId: tabs[0].id });
            }
          } catch (e) {}
        }
        sendResponse(res);
      })
      .catch((err) => {
        sendResponse({ ok: false, error: err.message || "Lỗi khởi động hàng đợi" });
      });

    return true; // Keep channel open for async response
  }
});

// Startup & install reconciliation
chrome.runtime.onStartup.addListener(() => {
  reconcileQueueState();
  sendAuthHeartbeat();
});
chrome.runtime.onInstalled.addListener(() => {
  reconcileQueueState();
  sendAuthHeartbeat();
});

// Immediate run on service worker init
reconcileQueueState();
