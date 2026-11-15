import sys
import http.server
import socketserver
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("docs/qa/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

WIDTHS = [320, 400, 500]

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

def capture_sidepanel_responsive():
    sidepanel_html = Path("extension/sidepanel.html").resolve()
    if not sidepanel_html.exists():
        print("extension/sidepanel.html not found!")
        sys.exit(1)

    PORT = 5176
    httpd = socketserver.TCPServer(('127.0.0.1', PORT), QuietHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{PORT}/extension/sidepanel.html"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for width in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": 650})
                page = context.new_page()

                # 1. State: idle (chờ)
                page.goto(url)
                page.evaluate("""() => {
                    document.getElementById('backend-status').className = 'status-chip chip-online';
                    document.getElementById('backend-status').innerText = 'Backend Online';
                    document.getElementById('thread-title-display').innerText = 'MLN122 - SU26 - RE';
                    document.getElementById('input-thread-url').value = 'https://fuoverflow.com/threads/mln122-su26-re.7207/';
                    document.getElementById('stats-summary-line').innerText = '0/60 câu · 0 bình luận';
                }""")
                page.wait_for_timeout(200)
                p_idle = SCREENSHOT_DIR / f"sidepanel_{width}px_idle.png"
                page.screenshot(path=str(p_idle))
                print(f"Captured: {p_idle}")

                # 2. State: running (đang chạy - animation settled, single status line)
                page.evaluate("""() => {
                    document.getElementById('btn-main-action').innerText = 'Dừng';
                    document.getElementById('btn-main-action').className = 'btn-main btn-stop';
                    const bar = document.getElementById('progress-bar');
                    bar.style.width = '45%';
                    document.getElementById('stats-summary-line').innerText = '27/60 câu · 84 bình luận';
                    const log = document.getElementById('log-box');
                    const line = document.createElement('div');
                    line.className = 'log-line log-info';
                    line.innerText = '[12:00:15] [27/60] Media 137178: 4 bình luận (HTTP 200, 180ms)';
                    log.appendChild(line);
                }""")
                page.wait_for_timeout(300) # wait for animation settle
                p_run = SCREENSHOT_DIR / f"sidepanel_{width}px_running.png"
                page.screenshot(path=str(p_run))
                print(f"Captured: {p_run}")

                # 3. State: completed (xong - 100% fully filled)
                page.evaluate("""() => {
                    document.getElementById('btn-main-action').innerText = 'Bắt đầu soạn';
                    document.getElementById('btn-main-action').className = 'btn-main btn-start';
                    const bar = document.getElementById('progress-bar');
                    bar.style.width = '100%';
                    document.getElementById('stats-summary-line').innerText = '60/60 câu · 207 bình luận';
                    document.getElementById('result-card').style.display = 'flex';
                    document.getElementById('result-filename').innerText = 'MLN122 - SU26 - RE.docx';
                }""")
                page.wait_for_timeout(300) # wait for animation settle
                p_comp = SCREENSHOT_DIR / f"sidepanel_{width}px_completed.png"
                page.screenshot(path=str(p_comp))
                print(f"Captured: {p_comp}")

                # 4. State: backend_error (lỗi backend)
                page.evaluate("""() => {
                    document.getElementById('result-card').style.display = 'none';
                    document.getElementById('backend-status').className = 'status-chip chip-offline';
                    document.getElementById('backend-status').innerText = 'Backend Offline';
                    const notice = document.getElementById('ui-notice-box');
                    notice.style.display = 'block';
                    notice.innerText = 'Backend chưa chạy. Mở terminal và chạy: python run_dev.py';
                }""")
                p_err = SCREENSHOT_DIR / f"sidepanel_{width}px_backend_error.png"
                page.screenshot(path=str(p_err))
                print(f"Captured: {p_err}")

                # 5. State: not_logged_in (chưa đăng nhập FUOverflow)
                page.evaluate("""() => {
                    document.getElementById('backend-status').className = 'status-chip chip-online';
                    document.getElementById('backend-status').innerText = 'Backend Online';
                    const notice = document.getElementById('ui-notice-box');
                    notice.style.display = 'block';
                    notice.innerText = 'Chưa đăng nhập FUOverflow. Mở fuoverflow.com và đăng nhập trước khi soạn.';
                }""")
                p_not_login = SCREENSHOT_DIR / f"sidepanel_{width}px_not_logged_in.png"
                page.screenshot(path=str(p_not_login))
                print(f"Captured: {p_not_login}")

                # 6. Specific workflows for 320px and 400px: reopen card & reopen updating
                if width in [320, 400]:
                    # Reopen card: "Đã soạn lúc HH:MM (60 câu) - Tải file / Cập nhật bình luận"
                    page.evaluate("""() => {
                        const notice = document.getElementById('ui-notice-box');
                        notice.style.display = 'none';
                        const reopenCard = document.getElementById('reopen-card');
                        reopenCard.style.display = 'flex';
                        document.getElementById('reopen-text').innerText = 'Đã soạn lúc 12:27 (60 câu)';
                    }""")
                    page.wait_for_timeout(100)
                    p_reopen = SCREENSHOT_DIR / f"sidepanel_{width}px_reopen_card.png"
                    page.screenshot(path=str(p_reopen))
                    print(f"Captured: {p_reopen}")

                    # Reopen updating: Clicking "Cập nhật bình luận"
                    page.evaluate("""() => {
                        const reopenCard = document.getElementById('reopen-card');
                        reopenCard.style.display = 'flex';
                        document.getElementById('btn-reopen-update').innerText = 'Đang cập nhật...';
                        document.getElementById('btn-reopen-update').disabled = true;
                        document.getElementById('stats-summary-line').innerText = 'Đang tải bình luận (bỏ qua ảnh)... 15/60';
                        const bar = document.getElementById('progress-bar');
                        bar.style.width = '25%';
                    }""")
                    page.wait_for_timeout(200)
                    p_reopen_updating = SCREENSHOT_DIR / f"sidepanel_{width}px_reopen_updating.png"
                    page.screenshot(path=str(p_reopen_updating))
                    print(f"Captured: {p_reopen_updating}")

                # 7. Tab Đã soạn
                page.evaluate("""() => {
                    const reopenCard = document.getElementById('reopen-card');
                    if (reopenCard) reopenCard.style.display = 'none';
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                    document.querySelectorAll('.tab-btn')[1].classList.add('active');
                    const panel = document.getElementById('tab-panel-dasoan');
                    panel.classList.add('active');
                    const listContainer = document.getElementById('docs-list-container');
                    listContainer.innerHTML = `
                      <div class=\"dasoan-item\">
                        <div class=\"dasoan-title\" title=\"MLN122 - SU26 - RE\">MLN122 - SU26 - RE</div>
                        <div class=\"dasoan-meta\">60 câu · Đã soạn 12:27 15/11/2026</div>
                        <div class=\"dasoan-actions\">
                          <button class=\"btn-dasoan-action\">Tải file</button>
                          <button class=\"btn-dasoan-action\">Mở thư mục</button>
                          <button class=\"btn-dasoan-action\">Cập nhật</button>
                        </div>
                      </div>
                      <div class=\"dasoan-item\">
                        <div class=\"dasoan-title\" title=\"ACC101 - FA25 - EXAM\">ACC101 - FA25 - EXAM</div>
                        <div class=\"dasoan-meta\">45 câu · Đã soạn 09:14 14/11/2026</div>
                        <div class=\"dasoan-actions\">
                          <button class=\"btn-dasoan-action\">Tải file</button>
                          <button class=\"btn-dasoan-action\">Mở thư mục</button>
                          <button class=\"btn-dasoan-action\">Cập nhật</button>
                        </div>
                      </div>
                    `;
                }""")
                p_tab_docs = SCREENSHOT_DIR / f"sidepanel_{width}px_tab_dasoan.png"
                page.screenshot(path=str(p_tab_docs))
                print(f"Captured: {p_tab_docs}")

                # 8. Tab Cài đặt
                page.evaluate("""() => {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                    document.querySelectorAll('.tab-btn')[2].classList.add('active');
                    const panel = document.getElementById('tab-panel-caidat');
                    panel.classList.add('active');
                    const pContainer = document.getElementById('providers-list-container');
                    pContainer.innerHTML = `
                      <div class=\"provider-row\">
                        <div class=\"provider-header\">
                          <span style=\"font-weight: 600; font-size: 12px;\">GEMINI</span>
                          <label style=\"display: inline-flex; align-items: center; gap: 3px; font-size: 11px;\"><input type=\"checkbox\" checked /><span>Bật</span></label>
                        </div>
                        <div style=\"font-size: 11px; color: var(--muted);\">gemini-2.5-flash · ••••VQVg</div>
                        <div style=\"display: flex; gap: 4px; margin-top: 2px;\">
                          <input type=\"password\" class=\"thread-url-input\" placeholder=\"Nhập khoá mới để lưu\" style=\"font-size: 11px; padding: 4px 6px;\" />
                          <button class=\"btn-secondary\" style=\"flex: 0; padding: 4px 8px; font-size: 11px;\">Lưu</button>
                        </div>
                      </div>
                      <div class=\"provider-row\">
                        <div class=\"provider-header\">
                          <span style=\"font-weight: 600; font-size: 12px;\">ANTHROPIC</span>
                          <div style=\"display: flex; gap: 4px; align-items: center;\">
                            <span class=\"badge-invalid\">Khoá không hợp lệ</span>
                            <label style=\"display: inline-flex; align-items: center; gap: 3px; font-size: 11px;\"><input type=\"checkbox\" /><span>Tắt</span></label>
                          </div>
                        </div>
                        <div style=\"font-size: 11px; color: var(--muted);\">claude-3-5-haiku-20241022 · ••••9876</div>
                        <div style=\"display: flex; gap: 4px; margin-top: 2px;\">
                          <input type=\"password\" class=\"thread-url-input\" placeholder=\"Nhập khoá mới để lưu\" style=\"font-size: 11px; padding: 4px 6px;\" />
                          <button class=\"btn-secondary\" style=\"flex: 0; padding: 4px 8px; font-size: 11px;\">Lưu</button>
                        </div>
                      </div>
                    `;
                }""")
                p_tab_settings = SCREENSHOT_DIR / f"sidepanel_{width}px_tab_caidat.png"
                page.screenshot(path=str(p_tab_settings))
                print(f"Captured: {p_tab_settings}")

                context.close()

            browser.close()
    finally:
        httpd.shutdown()
    print("Done capturing all sidepanel states and tabs!")

if __name__ == "__main__":
    capture_sidepanel_responsive()
