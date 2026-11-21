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

// Restore persisted auth status on worker startup
chrome.storage.local.get(["lastAuthStatus"], (res) => {
  if (res && res.lastAuthStatus) {
    lastAuthStatus = res.lastAuthStatus;
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "OPEN_SIDEPANEL") {
    const tabId = sender.tab ? sender.tab.id : undefined;
    if (tabId) {
      chrome.sidePanel.open({ tabId }).catch((err) => console.error("Error opening side panel:", err));
    }
    sendResponse({ ok: true });
    return true;
  } else if (message.type === "TRIGGER_HEARTBEAT") {
    sendAuthHeartbeat().then(() => sendResponse({ ok: true }));
    return true;
  } else if (message.type === "SETUP_OFFSCREEN") {
    ensureOffscreenDocument().then(() => sendResponse({ ok: true }));
    return true;
  } else if (message.type === "GET_BACKGROUND_VERSION") {
    sendResponse({
      ok: true,
      version: chrome.runtime.getManifest().version,
      instanceId: BACKGROUND_INSTANCE_ID,
    });
    return true;
  }
});

function cleanExamTitle(rawTitle) {
  if (!rawTitle) return "";
  let t = rawTitle.trim();
  t = t.replace(/^\(\d+\)\s*/, "");
  t = t.replace(/\s*\|\s*FuOverflow\s*Community.*$/i, "");
  const badgeRegex = /^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+/i;
  t = t.replace(badgeRegex, "");
  return t.trim();
}

// In-memory processed runIds to deduplicate dashboard commands
const processedRunIds = new Set();

// External messages from web dashboard (http://127.0.0.1:8000, http://localhost:5173, etc.)
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
    // Opportunistically refresh heartbeat on ping
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

    // 1. Chống trùng theo runId: nếu runId đã xử lý, trả ack trùng ngay lập tức, không chạy lại
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

    (async () => {
      try {
        const storageData = await chrome.storage.local.get(["savedQueueState"]);
        const prevQueue = storageData.savedQueueState;

        // 2. Nếu hàng đợi cũ ĐANG CHẠY mà không có cờ force -> từ chối kèm lý do rõ ràng
        if (prevQueue && prevQueue.isRunning && !force) {
          const busyTitle = prevQueue.currentExamTitle || "Đang soạn đề";
          sendResponse({
            ok: false,
            error: "QUEUE_RUNNING",
            currentExamTitle: busyTitle,
            runId: prevQueue.runId,
            message: `Hàng đợi đang soạn đề: "${busyTitle}". Vui lòng đợi hoàn tất hoặc chọn thay thế.`,
          });
          return;
        }

        // Đánh dấu đã nhận runId để chống trùng
        processedRunIds.add(runId);
        if (processedRunIds.size > 200) {
          const first = processedRunIds.values().next().value;
          processedRunIds.delete(first);
        }

        // 3. Nếu đang chạy mà force=true: dừng hàng đợi cũ và abort ngay lập tức
        if (prevQueue && prevQueue.isRunning && force) {
          await appendLogToStorage(`[Dashboard] Dừng và thay thế hàng đợi cũ bằng phiên mới (${runId})`, "warn");
          try {
            await chrome.runtime.sendMessage({ type: "OFFSCREEN_STOP_QUEUE" });
          } catch (e) {}
        } else {
          await appendLogToStorage(`[Dashboard] Nhận lệnh ${exams.length} đề (runId: ${runId})`, "info");
        }

        // Ensure Offscreen document is ready
        await ensureOffscreenDocument();

        // Gắn runId vào từng đề để đồng bộ xuyên suốt
        const taggedExams = exams.map((ex) => ({
          ...ex,
          runId: runId,
        }));

        const firstTitle = cleanExamTitle(taggedExams[0].title || "Đang soạn...");
        const firstTotalQ = taggedExams[0].question_count || 40;

        // 4. THAY THẾ hoàn toàn: xoá mục cũ, xoá thẻ kết quả cũ, bắt đầu từ Câu 1/y thật
        const initialQueueState = {
          runId: runId,
          items: taggedExams,
          currentIndex: 0,
          isRunning: true,
          isPaused: false,
          isCompleted: false,
          currentExamTitle: firstTitle,
          currentQuestionIndex: 1, // Hiển thị "Câu 1/y" thật từ khi bắt đầu (Requirement 4)
          totalQuestions: firstTotalQ,
          progressPct: 0,
          statusText: `Câu 1/${firstTotalQ}`, // Không để "Đã nhận 1 đề..."
          completedExams: [], // Xoá danh sách kết quả cũ (Requirement 2)
          updatedAt: Date.now(),
        };

        await chrome.storage.local.set({
          savedQueueState: initialQueueState,
        });

        // Báo sidepanel reset thẻ kết quả cũ
        try {
          chrome.runtime.sendMessage({
            type: "QUEUE_RESET",
            runId: runId,
          }).catch(() => {});
        } catch (e) {}

        // Đăng ký active run trên backend (nếu backend đang chạy)
        try {
          await fetch("http://127.0.0.1:8000/api/ingest/register-run", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-DocxStacked-Ext": chrome.runtime.id,
            },
            body: JSON.stringify({
              runId: runId,
              subjectCode: subjectCode,
              examUrls: taggedExams.map((e) => e.url),
            }),
          });
        } catch (e) {}

        // 5. Khởi động offscreen queue với runId đồng bộ
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

        // 6. Mở sidepanel
        try {
          const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
          if (tabs && tabs[0]) {
            await chrome.sidePanel.open({ tabId: tabs[0].id });
          }
        } catch (e) {
          console.warn("Could not auto-open side panel:", e);
        }

        sendResponse({
          ok: true,
          ack: true,
          runId: runId,
          queued_count: exams.length,
          message: `Đã nhận ${exams.length} đề, đang soạn`,
        });
      } catch (err) {
        console.error("Error enqueuing exams:", err);
        await appendLogToStorage(`[Lỗi] Không thể khởi động hàng đợi: ${err.message}`, "error");
        sendResponse({ ok: false, error: err.message || "Lỗi khởi động hàng đợi" });
      }
    })();

    return true; // Keep channel open for async response
  }
});
