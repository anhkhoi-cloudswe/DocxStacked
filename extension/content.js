// content.js - Injected into https://fuoverflow.com/threads/*

(function () {
  if (window.__docxstacked_injected) return;
  window.__docxstacked_injected = true;

  function showToast(message) {
    const existing = document.querySelector(".docxstacked-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.className = "docxstacked-toast";
    toast.innerHTML = `<span>⚡</span> <span>${message}</span>`;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  function getCleanTitle() {
    let raw = "";
    const titleEl = document.querySelector(".p-title-value");
    if (titleEl) {
      const clone = titleEl.cloneNode(true);
      clone.querySelectorAll(".label, .label--accent, .label--primary").forEach(b => b.remove());
      raw = clone.innerText.trim();
    } else {
      raw = (document.title || "").replace(/\s*\|\s*FuOverflow\s*Community.*$/i, "").trim();
    }
    // Clean notification prefix like '(2) ' and XenForo badge prefixes
    raw = raw.replace(/^\(\d+\)\s*/, "");
    raw = raw.replace(/^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+/i, "");
    return raw.trim();
  }

  function injectComposeButton() {
    if (document.getElementById("docxstacked-compose-btn")) return;

    // Check if on a thread page
    if (!window.location.pathname.includes("/threads/")) return;

    // Target location: .p-title-action or next to .p-title-value
    const actionContainer = document.querySelector(".p-title-action");
    const titleValue = document.querySelector(".p-title-value");

    const btnWrapper = document.createElement("span");
    btnWrapper.className = "docxstacked-btn-container";

    const btn = document.createElement("button");
    btn.id = "docxstacked-compose-btn";
    btn.className = "docxstacked-btn";
    btn.type = "button";
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
      </svg>
      <span>Soạn đề này bằng DocxStacked</span>
    `;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const threadUrl = window.location.href.split("?")[0];
      const threadTitle = getCleanTitle();
      const isLoggedIn = document.documentElement.getAttribute("data-logged-in") === "true";

      const threadData = {
        url: threadUrl,
        title: threadTitle,
        isLoggedIn: isLoggedIn,
        selectedAt: Date.now(),
      };

      // Save to storage
      chrome.storage.local.set({ activeThread: threadData }, () => {
        // Send message to open sidepanel
        chrome.runtime.sendMessage({ type: "OPEN_SIDEPANEL" });
        chrome.runtime.sendMessage({ type: "THREAD_SELECTED", data: threadData });
        showToast("Đã chọn đề! Hãy mở Side Panel để bắt đầu thu thập & xuất Word.");
      });
    });

    btnWrapper.appendChild(btn);

    if (actionContainer) {
      actionContainer.prepend(btnWrapper);
    } else if (titleValue && titleValue.parentNode) {
      titleValue.parentNode.appendChild(btnWrapper);
    }
  }

  // Attempt initial injection and watch for SPA / dynamic loads
  injectComposeButton();
  setTimeout(injectComposeButton, 1000);
})();
