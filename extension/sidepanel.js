// sidepanel.js - DocxStacked Chromium Extension (MV3)
// Persistent ingestion loop running directly in Side Panel context.

const BACKEND_URL = "http://127.0.0.1:8000";
const EXTENSION_ID = (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.id) ? chrome.runtime.id : "kicplcdfmbcfjildbbimpfiljlmfokea";
const LOCAL_INGEST_KEY = "docxstacked_local_secret_2026";
const MIN_REQUEST_INTERVAL_MS = 2000; // Hard cadence: 1 request every 2.0s

const state = {
  isRunning: false,
  isStopped: false,
  totalQuestions: 0,
  processedQuestions: 0,
  collectedComments: 0,
  crawledPages: 0,
  count403: 0,
  countRetries: 0,
  activeThread: null,
};

// DOM Elements
const elBackendStatus = document.getElementById("backend-status");
const elAuthBanner = document.getElementById("auth-banner");
const elAuthText = document.getElementById("auth-text");
const elAuthBadge = document.getElementById("auth-badge");
const elBtnRefreshAuth = document.getElementById("btn-refresh-auth");
const elInputIngestToken = document.getElementById("input-ingest-token");
const elInputThreadUrl = document.getElementById("input-thread-url");
const elThreadTitleDisplay = document.getElementById("thread-title-display");
const elBtnSyncTab = document.getElementById("btn-sync-tab");
const elBtnStart = document.getElementById("btn-start");
const elBtnStop = document.getElementById("btn-stop");
const elProgressStatus = document.getElementById("progress-status");
const elProgressPercent = document.getElementById("progress-percent");
const elProgressBar = document.getElementById("progress-bar");
const elStatQuestions = document.getElementById("stat-questions");
const elStatComments = document.getElementById("stat-comments");
const elStatPages = document.getElementById("stat-pages");
const elStat403 = document.getElementById("stat-403");
const elLogBox = document.getElementById("log-box");
const elResultCard = document.getElementById("result-card");
const elResultFilename = document.getElementById("result-filename");
const elResultDownloadBtn = document.getElementById("result-download-btn");
const elOfflineRecoveryRow = document.getElementById("offline-recovery-row");
const elBtnRetryIngest = document.getElementById("btn-retry-ingest");
const elBtnClearIdb = document.getElementById("btn-clear-idb");
const elUiNoticeBox = document.getElementById("ui-notice-box");

function showNotice(msg, type = "info") {
  if (!elUiNoticeBox) return;
  elUiNoticeBox.style.display = "block";
  if (type === "error") {
    elUiNoticeBox.style.background = "rgba(239, 68, 68, 0.2)";
    elUiNoticeBox.style.color = "#fca5a5";
    elUiNoticeBox.style.border = "1px solid rgba(239, 68, 68, 0.4)";
  } else if (type === "warn") {
    elUiNoticeBox.style.background = "rgba(245, 158, 11, 0.2)";
    elUiNoticeBox.style.color = "#fde047";
    elUiNoticeBox.style.border = "1px solid rgba(245, 158, 11, 0.4)";
  } else {
    elUiNoticeBox.style.background = "rgba(16, 185, 129, 0.2)";
    elUiNoticeBox.style.color = "#86efac";
    elUiNoticeBox.style.border = "1px solid rgba(16, 185, 129, 0.4)";
  }
  elUiNoticeBox.innerText = msg;
}

function hideNotice() {
  if (elUiNoticeBox) {
    elUiNoticeBox.style.display = "none";
  }
}

function log(msg, type = "info") {
  const line = document.createElement("div");
  line.className = `log-line log-${type}`;
  const now = new Date().toLocaleTimeString("vi-VN");
  line.innerText = `[${now}] ${msg}`;
  elLogBox.appendChild(line);
  elLogBox.scrollTop = elLogBox.scrollHeight;
}

function updateProgress(percent, statusText) {
  elProgressPercent.innerText = `${Math.min(100, Math.max(0, Math.round(percent)))}%`;
  elProgressBar.style.width = `${Math.min(100, Math.max(0, Math.round(percent)))}%`;
  if (statusText) elProgressStatus.innerText = statusText;
}

function updateStats() {
  if (elStatQuestions) elStatQuestions.innerText = `${state.processedQuestions}/${state.totalQuestions || 0}`;
  if (elStatComments) elStatComments.innerText = state.collectedComments;
  if (elStatPages) elStatPages.innerText = state.crawledPages;
  if (elStat403) elStat403.innerText = state.count403;
}

// ==========================================
// IndexedDB Storage Helpers (Offline Buffer)
// ==========================================
const IDB_NAME = "DocxStackedBuffer";
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
    log(`[IndexedDB] Đã lưu đệm dữ liệu đề thi vào máy (${examData.questions.length} câu).`, "info");
  } catch (err) {
    log(`[IndexedDB] Lỗi lưu đệm: ${err.message}`, "warn");
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
    log("[IndexedDB] Đã dọn dẹp vùng đệm của đề thi này.", "info");
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
    const res = await fetch(`${BACKEND_URL}/api/health`, {
      method: "GET",
      headers: { "X-DocxStacked-Ext": EXTENSION_ID },
    });
    if (res.ok) {
      elBackendStatus.className = "badge-status badge-online";
      elBackendStatus.innerText = "● Backend Online";
      return true;
    }
  } catch (e) {
    // Offline
  }
  elBackendStatus.className = "badge-status badge-offline";
  elBackendStatus.innerText = "● Backend Offline";
  return false;
}

// 2. Check FuOverflow Authentication via Credentials: include
async function checkFuOverflowAuth() {
  elAuthText.innerText = "Đang kiểm tra phiên FuOverflow...";
  elAuthBadge.className = "badge-status badge-offline";
  elAuthBadge.innerText = "Đang kiểm tra";

  try {
    const res = await fetch("https://fuoverflow.com/", {
      method: "GET",
      credentials: "include",
    });

    if (!res.ok) {
      elAuthText.innerText = `Lỗi kết nối máy chủ (${res.status})`;
      elAuthBadge.innerText = "Lỗi HTTP";
      return false;
    }

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
      elAuthText.innerText = `Đã đăng nhập: ${username}`;
      elAuthBadge.className = "badge-status badge-online";
      elAuthBadge.innerText = "Đã xác thực";
      log(`Phiên đăng nhập FuOverflow hợp lệ (${username}).`, "success");

      // Notify backend immediately of active login
      try {
        await fetch(`${BACKEND_URL}/api/auth/extension-heartbeat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-DocxStacked-Ext": EXTENSION_ID,
          },
          body: JSON.stringify({ logged_in: true, username: username }),
        });
      } catch (e) {
        // Backend might be offline
      }

      return true;
    } else {
      elAuthText.innerText = "Chưa đăng nhập FuOverflow";
      elAuthBadge.className = "badge-status badge-offline";
      elAuthBadge.innerText = "Chưa đăng nhập";
      log("Chưa phát hiện phiên đăng nhập FuOverflow. Vui lòng mở tab FuOverflow và đăng nhập.", "warn");

      try {
        await fetch(`${BACKEND_URL}/api/auth/extension-heartbeat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-DocxStacked-Ext": EXTENSION_ID,
          },
          body: JSON.stringify({ logged_in: false, username: null }),
        });
      } catch (e) {}

      return false;
    }
  } catch (err) {
    elAuthText.innerText = "Không thể kết nối fuoverflow.com";
    elAuthBadge.className = "badge-status badge-offline";
    elAuthBadge.innerText = "Lỗi mạng";
    log(`Lỗi kiểm tra auth: ${err.message}`, "error");
    return false;
  }
}

// 3. Fetch with 1 req / 2s Cadence and Exponential Retry on 429/5xx
async function fetchWithCadence(url, options = {}, maxRetries = 3) {
  if (state.isStopped) throw new Error("USER_STOPPED");

  let delay = 1000;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const startTime = Date.now();
    try {
      const res = await fetch(url, {
        ...options,
        credentials: "include",
      });

      const elapsedMs = Date.now() - startTime;

      if (res.status === 403) {
        state.count403++;
        updateStats();
        log(`[${elapsedMs}ms] Máy chủ từ chối (HTTP 403 Forbidden) tại: ${url}`, "error");
        return res;
      }

      if (res.status === 429 || (res.status >= 500 && res.status < 600)) {
        state.countRetries++;
        updateStats();
        log(`[${elapsedMs}ms] Gặp HTTP ${res.status} tại ${url}. Thử lại lần ${attempt}/${maxRetries} sau ${delay}ms...`, "warn");
        await sleep(delay);
        delay = delay * 2 + Math.floor(Math.random() * 500);
        continue;
      }

      if (!res.ok) {
        log(`[${elapsedMs}ms] Yêu cầu gặp lỗi HTTP ${res.status} tại: ${url}`, "warn");
      }

      return res;
    } catch (err) {
      const elapsedMs = Date.now() - startTime;
      if (attempt === maxRetries) {
        log(`[${elapsedMs}ms] Lỗi mạng nghiêm trọng (${err.message}) tại: ${url}`, "error");
        throw err;
      }
      state.countRetries++;
      updateStats();
      log(`[${elapsedMs}ms] Lỗi mạng kết nối (${err.message}). Thử lại sau ${delay}ms...`, "warn");
      await sleep(delay);
      delay = delay * 2;
    }
  }
  throw new Error(`Thất bại sau ${maxRetries} lần thử lại: ${url}`);
}

// Convert Blob to Base64
async function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// 4. Parse Comments from Media HTML
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

    // Reactions
    const rxBar = c.querySelector(".reactionsBar");
    let upvotes = 0;
    if (rxBar) {
      const text = rxBar.innerText || "";
      const mTotal = text.match(/(\d+)\s+(?:reactions|lượt thích|phản ứng)/i);
      if (mTotal) {
        upvotes = parseInt(mTotal[1], 10);
      } else {
        const bdis = rxBar.querySelectorAll("bdi").length;
        const mOthers = text.match(/(?:and|và)\s+(\d+)\s+(?:others|người khác)/i);
        const others = mOthers ? parseInt(mOthers[1], 10) : 0;
        upvotes = bdis + others;
        if (upvotes === 0 && (rxBar.querySelector(".reaction, .reaction-image") || rxBar.classList.contains("is-active"))) {
          upvotes = 1;
        }
      }
    }

    // Quoted Comment ID & reply flag
    let quotedCommentId = null;
    let isReply = false;
    const quoteBlock = c.querySelector("blockquote, .bbCodeBlock--quote");
    if (quoteBlock) {
      isReply = true;
      const titleLink = quoteBlock.querySelector(".bbCodeBlock-title a");
      if (titleLink && titleLink.getAttribute("href")) {
        const mQ = titleLink.getAttribute("href").match(/\/comments\/(\d+)/);
        if (mQ) quotedCommentId = parseInt(mQ[1], 10);
      }
    }
    if (!quotedCommentId && c.querySelector(".comment--reply, .message--response")) {
      isReply = true;
    }

    // Posted time
    const timeEl = c.querySelector("time.u-dt, time");
    let postedAt = null;
    if (timeEl) {
      postedAt = timeEl.getAttribute("datetime") || timeEl.getAttribute("data-date") || timeEl.innerText.trim();
    }

    // Text without quote contents
    const bb = c.querySelector(".message-body .bbWrapper, .message-body, .comment-content");
    let rawText = "";
    if (bb) {
      const clone = bb.cloneNode(true);
      clone.querySelectorAll("blockquote, .bbCodeBlock--quote").forEach((q) => q.remove());
      rawText = clone.innerText.trim();
    }

    if (rawText) {
      comments.push({
        comment_id: commentId,
        author_name: authorName,
        raw_text: rawText,
        upvotes: upvotes,
        quoted_comment_id: quotedCommentId,
        is_reply: isReply,
        posted_at: postedAt,
      });
    }
  });

  return comments;
}

// 5. Ingestion Pipeline Execution
async function startIngestion() {
  const url = elInputThreadUrl.value.trim();
  if (!url || !url.startsWith("http")) {
    showNotice("Vui lòng nhập đường dẫn URL hợp lệ của đề thi trên FuOverflow!", "warn");
    log("Vui lòng nhập đường dẫn URL hợp lệ của đề thi trên FuOverflow!", "warn");
    return;
  }

  // Pre-flight check (GET /api/ingest/ping). Token is purely optional.
  const userToken = (elInputIngestToken && elInputIngestToken.value.trim()) || "";
  const pingHeaders = {
    "X-DocxStacked-Ext": EXTENSION_ID,
  };
  if (userToken) {
    pingHeaders["X-Ingest-Token"] = userToken;
  }

  log("Đang kiểm tra kết nối với backend...", "info");
  try {
    const pingRes = await fetch(`${BACKEND_URL}/api/ingest/ping`, {
      method: "GET",
      headers: pingHeaders,
    });
    if (!pingRes.ok) {
      const errDetail = await pingRes.text();
      log(`[Xác thực thất bại] Không thể xác thực với backend (${pingRes.status}). Hệ thống dừng ngay!`, "error");
      showNotice(`Lỗi xác thực với backend (${pingRes.status}). Kiểm tra lại cấu hình Origin hoặc Token.`, "error");
      return;
    }
    hideNotice();
    log("Kết nối backend hợp lệ! Sẵn sàng thu thập dữ liệu đề thi.", "success");
    if (userToken) {
      chrome.storage.local.set({ ingestToken: userToken });
    }
  } catch (netErr) {
    log(`[Mất kết nối Backend] Không thể kết nối tới ${BACKEND_URL}/api/ingest/ping: ${netErr.message}`, "error");
    showNotice("Backend chưa chạy. Mở terminal và chạy: python run_dev.py", "error");
    return;
  }

  // Reset state
  state.isRunning = true;
  state.isStopped = false;
  state.processedQuestions = 0;
  state.totalQuestions = 0;
  state.collectedComments = 0;
  state.crawledPages = 0;
  state.count403 = 0;
  state.countRetries = 0;
  updateStats();
  elResultCard.style.display = "none";
  if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";

  elBtnStart.disabled = true;
  elBtnStop.disabled = false;
  log(`Bắt đầu quy trình thu thập đề thi từ: ${url}`, "info");
  updateProgress(5, "Đang tải trang thread...");

  let questionsData = [];
  let subjectCode = "MLN122";
  let threadTitle = elThreadTitleDisplay.innerText;

  try {
    // Step 1: Fetch thread HTML
    const threadRes = await fetchWithCadence(url);
    if (!threadRes.ok) {
      throw new Error(`Tải trang đề thi thất bại với mã lỗi HTTP ${threadRes.status}`);
    }
    const threadHtml = await threadRes.text();
    const parser = new DOMParser();
    const threadDoc = parser.parseFromString(threadHtml, "text/html");

    // Extract Title
    const titleEl = threadDoc.querySelector(".p-title-value");
    threadTitle = titleEl ? titleEl.innerText.trim() : elThreadTitleDisplay.innerText;
    elThreadTitleDisplay.innerText = threadTitle;
    log(`Tiêu đề đề thi: "${threadTitle}"`, "info");

    // Extract Subject code from title
    const mCode = threadTitle.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
    if (mCode) subjectCode = mCode[1].toUpperCase();

    // Extract question attachments
    const attachmentItems = threadDoc.querySelectorAll("section.message-attachments ul.attachmentList li.file");
    if (!attachmentItems.length) {
      throw new Error("Không tìm thấy danh sách file đính kèm câu hỏi trong thread này.");
    }

    state.totalQuestions = attachmentItems.length;
    updateStats();
    log(`Tìm thấy ${state.totalQuestions} câu hỏi đính kèm. Bắt đầu thu thập từng câu...`, "success");

    // Step 2: Loop over attachment items with 2.0s cadence
    for (let idx = 0; idx < attachmentItems.length; idx++) {
      if (state.isStopped) throw new Error("USER_STOPPED");

      const item = attachmentItems[idx];
      const qIndex = idx + 1;

      const nameEl = item.querySelector(".file-name");
      const fileName = nameEl ? nameEl.innerText.trim() : `Q${qIndex}.webp`;

      // Extract media page link
      const previewEl = item.querySelector("a.file-preview");
      const sidebarHref = previewEl ? previewEl.getAttribute("data-lb-sidebar-href") || "" : "";
      const mediaPath = sidebarHref.split("?")[0];
      const mediaUrl = mediaPath.startsWith("/") ? `https://fuoverflow.com${mediaPath}` : mediaPath;
      const mId = mediaPath.match(/\/media\/[^.]+\.(\d+)/);
      const mediaId = mId ? mId[1] : null;

      log(`[${qIndex}/${state.totalQuestions}] Bắt đầu xử lý: ${fileName} (URL: ${mediaUrl || "N/A"})`, "info");

      let imageBase64 = null;
      let comments = [];

      if (mediaUrl) {
        // Enforce 2.0s cadence between requests
        await sleep(MIN_REQUEST_INTERVAL_MS);

        // Fetch media detail page
        const tStartMedia = Date.now();
        const mediaRes = await fetchWithCadence(mediaUrl);
        const tMediaElapsed = Date.now() - tStartMedia;

        if (mediaRes.ok) {
          state.crawledPages++;
          const mediaHtml = await mediaRes.text();
          const mediaDoc = parser.parseFromString(mediaHtml, "text/html");

          // Extract Comments
          comments = parseCommentsFromHtml(mediaHtml);
          state.collectedComments += comments.length;

          // Count comment pages if pagination exists
          const pageNavEl = mediaDoc.querySelector(".pageNav-page, .pageNavSimple");
          const pageCount = pageNavEl ? (mediaDoc.querySelectorAll(".pageNav-page").length || 1) : 1;

          log(`[${qIndex}/${state.totalQuestions}] Media ${mediaId || fileName}: ${comments.length} bình luận (trang 1/${pageCount}, lấy trong ${tMediaElapsed}ms, HTTP ${mediaRes.status})`);

          // Find full image URL
          const fullImgEl = mediaDoc.querySelector("img.js-mediaImage, .media-container img");
          if (fullImgEl && fullImgEl.getAttribute("src")) {
            const rawSrc = fullImgEl.getAttribute("src");
            const fullImgUrl = rawSrc.startsWith("/") ? `https://fuoverflow.com${rawSrc}` : rawSrc;

            // Fetch image binary
            await sleep(500);
            const tStartImg = Date.now();
            const imgRes = await fetchWithCadence(fullImgUrl);
            const tImgElapsed = Date.now() - tStartImg;

            if (imgRes.ok) {
              const blob = await imgRes.blob();
              imageBase64 = await blobToBase64(blob);
              log(`[${qIndex}/${state.totalQuestions}] Tải ảnh gốc thành công: ${(blob.size / 1024).toFixed(1)} KB (HTTP ${imgRes.status}, ${tImgElapsed}ms)`, "success");
            } else {
              log(`[${qIndex}/${state.totalQuestions}] Không thể tải ảnh gốc (HTTP ${imgRes.status}, URL: ${fullImgUrl})`, "warn");
            }
          } else {
            log(`[${qIndex}/${state.totalQuestions}] Không tìm thấy link ảnh gốc trong media HTML`, "warn");
          }
        } else {
          log(`[${qIndex}/${state.totalQuestions}] Lỗi tải trang media (HTTP ${mediaRes.status}, ${tMediaElapsed}ms): ${mediaUrl}`, "error");
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
      updateStats();
      const pct = 10 + Math.round((state.processedQuestions / state.totalQuestions) * 75);
      updateProgress(pct, `Đã thu thập câu ${qIndex}/${state.totalQuestions}`);
    }

    // Save full collected data into IndexedDB immediately after crawling
    const examBuffer = {
      subject_code: subjectCode,
      exam_title: threadTitle,
      exam_url: url,
      questions: questionsData,
      crawled_at: Date.now(),
      comments_count: state.collectedComments,
    };
    await saveExamToIndexedDB(examBuffer);

    // Step 3: Send ingested payload to Backend
    await sendPayloadToBackend(examBuffer, userToken);

  } catch (err) {
    if (err.message === "USER_STOPPED") {
      log("Người dùng đã dừng tiến trình thu thập đề thi.", "warn");
      updateProgress(0, "Đã dừng");
    } else {
      log(`Lỗi trong tiến trình: ${err.message}`, "error");
      updateProgress(0, "Gặp lỗi");
      // Check if we have buffered data in IndexedDB to offer retry
      if (questionsData.length > 0 && elOfflineRecoveryRow) {
        elOfflineRecoveryRow.style.display = "flex";
      }
    }
  } finally {
    state.isRunning = false;
    elBtnStart.disabled = false;
    elBtnStop.disabled = true;
  }
}

async function sendPayloadToBackend(examBuffer, userToken) {
  if (state.isStopped) throw new Error("USER_STOPPED");
  log("Đang chuyển toàn bộ dữ liệu sang Backend để cắt ảnh, bỏ phiếu & tạo file Word...", "info");
  updateProgress(88, "Backend đang xử lý & xuất file Word...");

  const payload = {
    subject_code: examBuffer.subject_code,
    exam_title: examBuffer.exam_title,
    exam_url: examBuffer.exam_url,
    questions: examBuffer.questions,
    options: {
      answer_format: "letter_keyword",
      multi_choice_format: "comma",
      ai_enabled: true,
    },
  };

  const headers = {
    "Content-Type": "application/json",
    "X-DocxStacked-Ext": EXTENSION_ID,
  };
  if (userToken) {
    headers["X-Ingest-Token"] = userToken;
  }

  const ingestRes = await fetch(`${BACKEND_URL}/api/ingest`, {
    method: "POST",
    headers: headers,
    body: JSON.stringify(payload),
  });

  if (!ingestRes.ok) {
    const errText = await ingestRes.text();
    // Ingestion failed, preserve IndexedDB buffer and show retry button
    if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "flex";
    throw new Error(`Backend từ chối yêu cầu (${ingestRes.status}): ${errText}`);
  }

  const result = await ingestRes.json();
  log(`Xuất file Word thành công: ${result.docx_filename}`, "success");
  updateProgress(100, "Hoàn tất!");

  // Success: delete from IndexedDB
  await deleteExamFromIndexedDB(examBuffer.exam_url);
  if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";

  // Show result card
  elResultFilename.innerText = `${result.docx_filename} (${result.questions_ingested} câu, ${result.comments_ingested} bình luận)`;
  elResultDownloadBtn.href = `${BACKEND_URL}${result.download_url}`;
  elResultCard.style.display = "flex";
}

// Event Listeners
elBtnStart.addEventListener("click", startIngestion);

elBtnStop.addEventListener("click", () => {
  if (state.isRunning) {
    state.isStopped = true;
    log("Đang gửi tín hiệu dừng...", "warn");
  }
});

// Retry ingest without re-crawling
if (elBtnRetryIngest) {
  elBtnRetryIngest.addEventListener("click", async () => {
    const url = elInputThreadUrl.value.trim();
    const userToken = (elInputIngestToken && elInputIngestToken.value.trim()) || "";
    const bufferedExam = await getExamFromIndexedDB(url);
    if (!bufferedExam) {
      showNotice("Không tìm thấy dữ liệu đệm của đề thi này trong IndexedDB. Vui lòng cào lại.", "warn");
      if (elOfflineRecoveryRow) elOfflineRecoveryRow.style.display = "none";
      return;
    }
    try {
      log(`[IndexedDB] Đang gửi lại ${bufferedExam.questions.length} câu từ bộ đệm...`, "info");
      await sendPayloadToBackend(bufferedExam, userToken);
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
    log("[IndexedDB] Đã xoá toàn bộ dữ liệu đệm lưu tạm.", "warn");
  });
}

elBtnRefreshAuth.addEventListener("click", checkFuOverflowAuth);

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
        log(`Đã đồng bộ từ Tab: ${cleanTitle}`, "info");
        hideNotice();
      } else {
        showNotice("Tab hiện tại không phải trang đề thi FuOverflow (/threads/...)!", "warn");
      }
    }
  } catch (e) {
    log(`Lỗi đồng bộ tab: ${e.message}`, "error");
  }
}

elBtnSyncTab.addEventListener("click", syncFromActiveTab);

// Automatically read active tab URL on open & on switch
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
          log(`Tự động nhận diện đề thi từ tab: "${cleanTitle}"`, "info");
        }
      }
    }
  } catch (e) {
    console.debug("autoReadActiveTab error:", e);
  }
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
    log(`Đã nhận đề từ trang: "${msg.data.title}"`, "info");
  }
});

// Restore saved active thread and token
chrome.storage.local.get(["activeThread", "ingestToken"], (res) => {
  if (res.activeThread && !elInputThreadUrl.value) {
    elInputThreadUrl.value = res.activeThread.url;
    elThreadTitleDisplay.innerText = res.activeThread.title;
  }
  if (res.ingestToken && elInputIngestToken) {
    elInputIngestToken.value = res.ingestToken;
  }
});

// Initialize
checkBackend();
checkFuOverflowAuth();
autoReadActiveTab();
setInterval(checkBackend, 10000);
