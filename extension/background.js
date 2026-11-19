// background.js - DocxStacked Chromium Extension (MV3)
// Configures side panel behavior to open when user clicks extension action icon.

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
  }
});

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
      version: "1.0.0",
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

    if (!Array.isArray(exams) || exams.length === 0) {
      sendResponse({ ok: false, error: "Danh sách đề trống" });
      return;
    }

    (async () => {
      try {
        // 1. Ensure Offscreen document is created and ready
        await ensureOffscreenDocument();

        // 2. Clear previous queue state and save initial queue state directly in storage
        const initialQueueState = {
          items: exams,
          currentIndex: 0,
          isRunning: true,
          isPaused: false,
          isCompleted: false,
          currentExamTitle: exams[0].title || "Đang soạn...",
          currentQuestionIndex: 0,
          totalQuestions: exams[0].question_count || 40,
          progressPct: 0,
          statusText: `Đã nhận ${exams.length} đề, đang soạn...`,
          completedExams: [],
          updatedAt: Date.now(),
        };

        await chrome.storage.local.set({
          savedQueueState: initialQueueState,
          externalQueueRequest: {
            subjectCode,
            exams,
            timestamp: Date.now(),
          },
        });

        // 3. Immediately kick off offscreen queue without waiting for sidepanel
        chrome.runtime.sendMessage({
          type: "OFFSCREEN_START_QUEUE",
          items: exams,
          currentIndex: 0,
          completedExams: [],
        }).catch(() => {});

        // 4. Try opening side panel in active tab
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
          queued_count: exams.length,
          message: `Đã nhận ${exams.length} đề, đang soạn`,
        });
      } catch (err) {
        console.error("Error enqueuing exams:", err);
        sendResponse({ ok: false, error: err.message || "Lỗi khởi động hàng đợi" });
      }
    })();

    return true; // Keep channel open for async response
  }
});
