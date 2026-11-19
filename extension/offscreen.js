// offscreen.js - Background scraping & queue runner for Chrome MV3
// Keeps crawling threads and lightboxes even when the side panel is closed.

const BACKEND_URL = "http://127.0.0.1:8000";
const MIN_REQUEST_INTERVAL_MS = 2000;
const PE_CHUNK_SIZE = 8 * 1024 * 1024; // 8 MB

let isRunning = false;
let isPaused = false;
let skipRequested = false;
let queueItems = [];
let currentIndex = 0;
let completedExams = [];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
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

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function parseSingleCommentScore(c) {
  // 1. First priority: forum author score displayed next to name in .message-attribution-user
  const voteEl = c.querySelector(".user-fuo-vote, .message-attribution-user .user-fuo-vote");
  if (voteEl) {
    const text = voteEl.innerText.trim();
    const mVote = text.match(/(-?\d+)/);
    if (mVote) {
      let score = parseInt(mVote[1], 10);
      if (score > 1000) score = 0; // Safeguard abnormal
      return score;
    }
  }

  // 2. Second priority: comment reaction count from reactionsBar
  const rxBar = c.querySelector(".reactionsBar");
  let upvotes = 0;
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
  if (upvotes > 1000) {
    upvotes = 0;
  }
  return upvotes;
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

    const upvotes = parseSingleCommentScore(c);

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
      });
      if (res.status === 429) {
        await sleep(delay);
        delay *= 2;
        continue;
      }
      return res;
    } catch (err) {
      if (attempt === maxRetries) throw err;
      await sleep(delay);
      delay *= 2;
    }
  }
}

async function saveState(extra = {}) {
  const currentItem = queueItems[currentIndex];
  const curExamTitle = extra.currentExamTitle || (currentItem ? cleanExamTitle(currentItem.title) : "");
  const state = {
    items: queueItems,
    currentIndex,
    isRunning,
    isPaused,
    isCompleted: extra.isCompleted !== undefined ? extra.isCompleted : (!isRunning && !isPaused && queueItems.length > 0 && currentIndex >= queueItems.length),
    currentExamTitle: curExamTitle,
    currentQuestionIndex: extra.currentQuestionIndex !== undefined ? extra.currentQuestionIndex : 0,
    totalQuestions: extra.totalQuestions !== undefined ? extra.totalQuestions : 0,
    progressPct: extra.progressPct !== undefined ? extra.progressPct : 0,
    statusText: extra.statusText || "",
    completedExams: completedExams,
    updatedAt: Date.now(),
  };

  try {
    await chrome.storage.local.set({ savedQueueState: state });
  } catch (e) {}

  try {
    chrome.runtime.sendMessage({
      type: "QUEUE_PROGRESS_UPDATE",
      data: state,
    }).catch(() => {});
  } catch (e) {}
}

async function executePeExamUpload(exam) {
  const threadUrl = exam.url;
  const resp = await fetchWithCadence(threadUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

  const html = await resp.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const titleEl = doc.querySelector("h1.p-title-value, title");
  const examTitle = cleanExamTitle(titleEl ? titleEl.innerText : exam.title);

  let subjectCode = exam.subject_code || "TEST";
  const mCode = examTitle.match(/^([A-Za-z]{2,5}\d{3}[A-Za-z]?)/);
  if (mCode) subjectCode = mCode[1].toUpperCase();

  const links = Array.from(doc.querySelectorAll("a[href*='/attachments/'], a[href*='.pdf'], a[href*='.zip']"));
  if (links.length === 0) return;

  for (let idx = 0; idx < links.length; idx++) {
    if (skipRequested) {
      skipRequested = false;
      throw new Error("USER_SKIPPED");
    }
    if (!isRunning || isPaused) throw new Error("USER_STOPPED");

    const a = links[idx];
    const fileUrl = a.href;
    const fileName = (a.innerText.trim() || `attachment_${idx + 1}`).replace(/[\\/:*?"<>|]/g, "_");

    const fileResp = await fetchWithCadence(fileUrl);
    if (!fileResp.ok) continue;

    const fileBlob = await fileResp.blob();
    const fileSize = fileBlob.size;
    const totalChunks = Math.ceil(fileSize / PE_CHUNK_SIZE) || 1;

    for (let cIdx = 0; cIdx < totalChunks; cIdx++) {
      if (skipRequested) {
        skipRequested = false;
        throw new Error("USER_SKIPPED");
      }
      if (!isRunning || isPaused) throw new Error("USER_STOPPED");

      const start = cIdx * PE_CHUNK_SIZE;
      const end = Math.min(start + PE_CHUNK_SIZE, fileSize);
      const chunkBlob = fileBlob.slice(start, end);
      const chunkB64 = await blobToBase64(chunkBlob);

      const chunkPayload = {
        subject_code: subjectCode,
        exam_title: examTitle,
        filename: fileName,
        chunk_index: cIdx,
        total_chunks: totalChunks,
        data_base64: chunkB64,
      };

      await fetch(`${BACKEND_URL}/api/ingest/pe-upload-chunk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(chunkPayload),
      });

      const filePct = Math.round(((cIdx + 1) / totalChunks) * 100);
      await saveState({
        currentExamTitle: examTitle,
        currentQuestionIndex: cIdx + 1,
        totalQuestions: totalChunks,
        progressPct: filePct,
        statusText: `PE: Tải lên ${fileName} (${cIdx + 1}/${totalChunks})`,
      });
    }
  }

  exam.status = "done";
  exam.compiled = true;
  completedExams.push({
    id: `pe_${Date.now()}`,
    title: examTitle,
    docx_filename: `${examTitle}.zip`,
    download_url: `/api/exports/bundle.zip?subject=${encodeURIComponent(subjectCode)}`,
    subject_code: subjectCode,
    compiled_at: new Date().toISOString(),
  });
}

async function executeFeExamCrawl(exam) {
  const url = exam.url;
  const isCommentUpdateOnly = exam.compiled && !exam.redownloadImages;

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

  const questionsData = [];

  for (let idx = 0; idx < attachmentItems.length; idx++) {
    if (skipRequested) {
      skipRequested = false;
      throw new Error("USER_SKIPPED");
    }
    if (!isRunning || isPaused) throw new Error("USER_STOPPED");

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
        comments = parseCommentsFromHtml(mediaHtml);

        const fullImgEl = parser.parseFromString(mediaHtml, "text/html").querySelector("img.js-mediaImage, .media-container img");
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

    questionsData.push({
      index: qIndex,
      file_name: fileName,
      media_id: mediaId,
      media_url: mediaUrl,
      image_base64: imageBase64,
      comments: comments,
    });

    const pct = Math.round((qIndex / totalQuestions) * 85);
    await saveState({
      currentExamTitle: threadTitle,
      currentQuestionIndex: qIndex,
      totalQuestions: totalQuestions,
      progressPct: pct,
      statusText: `Câu ${qIndex}/${totalQuestions}`,
    });
  }

  // Send payload to backend
  const payload = {
    subject_code: subjectCode,
    exam_title: threadTitle,
    exam_url: url,
    questions: questionsData,
    options: {
      answer_format: "letter_keyword",
      multi_choice_format: "comma",
      ai_enabled: true,
    },
  };

  await saveState({
    currentExamTitle: threadTitle,
    currentQuestionIndex: totalQuestions,
    totalQuestions: totalQuestions,
    progressPct: 90,
    statusText: "Backend đang xuất file Word...",
  });

  const res = await fetch(`${BACKEND_URL}/api/ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-DocxStacked-Ext": (typeof chrome !== "undefined" && chrome.runtime) ? chrome.runtime.id : "offscreen",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    throw new Error(`Ingest HTTP ${res.status}: ${errText.substring(0, 100)}`);
  }

  const result = await res.json();
  exam.status = "done";
  exam.compiled = true;
  exam.download_url = result.download_url;
  exam.docx_filename = result.docx_filename;

  const completedItem = {
    id: result.exam_id,
    title: threadTitle,
    docx_filename: result.docx_filename,
    download_url: result.download_url,
    subject_code: result.subject_code || subjectCode,
    compiled_at: new Date().toISOString(),
  };
  completedExams.push(completedItem);

  try {
    chrome.runtime.sendMessage({
      type: "EXAM_COMPLETED",
      exam: completedItem,
    }).catch(() => {});
  } catch (e) {}

  await saveState({
    currentExamTitle: threadTitle,
    currentQuestionIndex: totalQuestions,
    totalQuestions: totalQuestions,
    progressPct: 100,
    statusText: "Hoàn tất xuất Word!",
  });
}

async function runOffscreenQueue() {
  if (isRunning) return;
  isRunning = true;
  isPaused = false;

  while (isRunning && currentIndex < queueItems.length) {
    if (isPaused) break;
    const item = queueItems[currentIndex];
    item.status = "running";
    await saveState();

    try {
      if (item.exam_type === "PE") {
        await executePeExamUpload(item);
      } else {
        await executeFeExamCrawl(item);
      }
      item.status = "done";
      item.compiled = true;
    } catch (err) {
      if (err.message === "USER_SKIPPED") {
        item.status = "skipped";
      } else if (err.message === "USER_STOPPED") {
        item.status = "error";
        item.errorMessage = "Đã dừng bởi người dùng";
        break;
      } else {
        item.status = "error";
        item.errorMessage = err.message;
      }
    }

    currentIndex++;
    await saveState();
    await sleep(MIN_REQUEST_INTERVAL_MS);
  }

  if (currentIndex >= queueItems.length) {
    isRunning = false;
    isPaused = false;
    await saveState({
      isCompleted: true,
      currentExamTitle: "Đã hoàn thành tất cả",
      progressPct: 100,
      statusText: "Hoàn tất hàng đợi",
    });
    try {
      chrome.runtime.sendMessage({
        type: "QUEUE_ALL_COMPLETED",
        completedExams: completedExams,
      }).catch(() => {});
    } catch (e) {}
  } else {
    isRunning = false;
    await saveState();
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "OFFSCREEN_START_QUEUE") {
    queueItems = msg.items || [];
    currentIndex = msg.currentIndex || 0;
    completedExams = msg.completedExams || [];
    isPaused = false;
    skipRequested = false;
    runOffscreenQueue();
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_PAUSE_QUEUE") {
    isPaused = true;
    isRunning = false;
    saveState({ statusText: "Hàng đợi tạm dừng" });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_RESUME_QUEUE") {
    isPaused = false;
    runOffscreenQueue();
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_STOP_QUEUE") {
    isRunning = false;
    isPaused = false;
    queueItems = [];
    currentIndex = 0;
    completedExams = [];
    chrome.storage.local.remove(["savedQueueState"]);
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_SKIP_CURRENT") {
    skipRequested = true;
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_GET_STATUS") {
    sendResponse({
      isRunning,
      isPaused,
      currentIndex,
      totalExams: queueItems.length,
      currentExam: queueItems[currentIndex] || null,
      completedExams,
    });
    return true;
  }
});
