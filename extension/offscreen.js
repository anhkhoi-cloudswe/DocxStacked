// offscreen.js - Background scraping & queue runner for Chrome MV3
// Keeps crawling threads and lightboxes even when the side panel is closed.

const BACKEND_URL = "http://127.0.0.1:8000";
const MIN_REQUEST_INTERVAL_MS = 2000;

let isRunning = false;
let isPaused = false;
let queueItems = [];
let currentIndex = 0;

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

async function saveState() {
  await chrome.storage.local.set({
    savedQueueState: {
      items: queueItems,
      currentIndex,
      isRunning,
      isPaused,
      updatedAt: Date.now(),
    },
  });
}

async function runOffscreenQueue() {
  if (isRunning) return;
  isRunning = true;

  while (isRunning && currentIndex < queueItems.length) {
    if (isPaused) break;
    const item = queueItems[currentIndex];
    item.status = "running";
    await saveState();

    try {
      // Crawl thread
      const res = await fetch(item.url, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, "text/html");

      const titleEl = doc.querySelector("h1.p-title-value, title");
      const title = cleanExamTitle(titleEl ? titleEl.innerText : item.title);

      const attachmentItems = doc.querySelectorAll("section.message-attachments ul.attachmentList li.file");
      const questionsData = [];

      for (let idx = 0; idx < attachmentItems.length; idx++) {
        if (!isRunning || isPaused) break;
        const att = attachmentItems[idx];
        const qIndex = idx + 1;
        const previewEl = att.querySelector("a.file-preview");
        const sidebarHref = previewEl ? previewEl.getAttribute("data-lb-sidebar-href") || "" : "";
        const mediaPath = sidebarHref.split("?")[0];
        const mediaUrl = mediaPath.startsWith("/") ? `https://fuoverflow.com${mediaPath}` : mediaPath;
        const mId = mediaPath.match(/\/media\/[^.]+\.(\d+)/);
        const mediaId = mId ? mId[1] : null;

        let imageBase64 = null;
        let comments = [];

        if (mediaUrl) {
          await sleep(MIN_REQUEST_INTERVAL_MS);
          const mRes = await fetch(mediaUrl, { credentials: "include" });
          if (mRes.ok) {
            const mHtml = await mRes.text();
            const mDoc = new DOMParser().parseFromString(mHtml, "text/html");
            // Basic comment parser
            const cBlocks = mDoc.querySelectorAll(".message--comment, .message--mediaComment, .js-comment");
            cBlocks.forEach((cb, cIdx) => {
              const bodyEl = cb.querySelector(".message-body .bbWrapper, .comment-content, .message-content");
              if (!bodyEl) return;
              
              // Clone to avoid modifying DOM and strip quote blocks
              const clone = bodyEl.cloneNode(true);
              clone.querySelectorAll("blockquote, .bbCodeBlock--quote").forEach(q => q.remove());
              const rawText = clone.innerText.trim();
              if (!rawText) return;

              const authorEl = cb.querySelector(".message-name, .comment-user, .username, .comment-author");
              const authorName = authorEl ? authorEl.innerText.trim() : `user_${cIdx}`;

              let upvotes = 0;
              const rxBar = cb.querySelector(".reactionsBar");
              if (rxBar) {
                const nums = rxBar.innerText.match(/\d+/);
                if (nums) upvotes = parseInt(nums[0], 10);
              }
              // Check user reaction score if negative
              const scoreEl = cb.querySelector(".message-userExtras, .pairs--justified, .message-userDetails");
              if (scoreEl) {
                const mNeg = scoreEl.innerText.match(/(?:-\d+)/);
                if (mNeg) upvotes = parseInt(mNeg[0], 10);
              }

              const timeEl = cb.querySelector("time");
              const postedAt = timeEl ? (timeEl.getAttribute("datetime") || timeEl.innerText.trim()) : null;

              comments.push({
                comment_id: `c_${cIdx + 1}`,
                raw_text: rawText,
                author_name: authorName,
                upvotes: upvotes,
                posted_at: postedAt,
              });
            });

            const imgEl = mDoc.querySelector("img.js-mediaImage, .media-container img");
            if (imgEl && imgEl.getAttribute("src")) {
              const rawSrc = imgEl.getAttribute("src");
              const fullSrc = rawSrc.startsWith("/") ? `https://fuoverflow.com${rawSrc}` : rawSrc;
              await sleep(500);
              const imgRes = await fetch(fullSrc, { credentials: "include" });
              if (imgRes.ok) {
                const blob = await imgRes.blob();
                imageBase64 = await new Promise((resolve) => {
                  const reader = new FileReader();
                  reader.onloadend = () => resolve(reader.result);
                  reader.readAsDataURL(blob);
                });
              }
            }
          }
        }

        questionsData.push({
          index: qIndex,
          file_name: `Q${qIndex}.webp`,
          media_id: mediaId,
          media_url: mediaUrl,
          image_base64: imageBase64,
          comments: comments,
        });
      }

      // Send to Ingest
      const payload = {
        subject_code: item.subject_code || "TEST",
        exam_title: title,
        exam_url: item.url,
        questions: questionsData,
        options: { answer_format: "letter_keyword", multi_choice_format: "comma", ai_enabled: true },
      };

      const ingestRes = await fetch(`${BACKEND_URL}/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-DocxStacked-Ext": chrome.runtime.id },
        body: JSON.stringify(payload),
      });

      if (ingestRes.ok) {
        item.status = "done";
        item.compiled = true;
      } else {
        const errJson = await ingestRes.json().catch(() => ({}));
        item.status = "error";
        item.errorMessage = errJson.error || `HTTP ${ingestRes.status}`;
      }
    } catch (e) {
      item.status = "error";
      item.errorMessage = e.message;
    }

    currentIndex++;
    await saveState();
    await sleep(MIN_REQUEST_INTERVAL_MS);
  }

  isRunning = false;
  await saveState();
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "OFFSCREEN_START_QUEUE") {
    queueItems = msg.items || [];
    currentIndex = msg.currentIndex || 0;
    isPaused = false;
    runOffscreenQueue();
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "OFFSCREEN_STOP_QUEUE") {
    isRunning = false;
    isPaused = true;
    sendResponse({ ok: true });
    return true;
  }
});
