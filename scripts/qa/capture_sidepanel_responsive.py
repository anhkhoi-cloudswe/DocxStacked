import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("docs/qa/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

WIDTHS = [320, 400, 500]
STATES = ["idle", "running", "completed", "backend_error", "not_logged_in"]

def capture_sidepanel_responsive():
    sidepanel_html = Path("extension/sidepanel.html").resolve()
    if not sidepanel_html.exists():
        print("extension/sidepanel.html not found!")
        sys.exit(1)

    file_url = f"file:///{sidepanel_html.as_posix()}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for width in WIDTHS:
            context = browser.new_context(viewport={"width": width, "height": 600})
            page = context.new_page()

            # 1. State: idle (chờ)
            page.goto(file_url)
            page.evaluate("""() => {
                document.getElementById('backend-status').className = 'status-chip chip-online';
                document.getElementById('backend-status').innerText = 'Backend Online';
                document.getElementById('thread-title-display').innerText = 'MLN122 - SU26 - RE';
                document.getElementById('input-thread-url').value = 'https://fuoverflow.com/threads/mln122-su26-re.7207/';
                document.getElementById('stats-summary-line').innerText = '0/60 câu · 0 bình luận';
            }""")
            p_idle = SCREENSHOT_DIR / f"sidepanel_{width}px_idle.png"
            page.screenshot(path=str(p_idle))
            print(f"Captured: {p_idle}")

            # 2. State: running (đang chạy)
            page.evaluate("""() => {
                document.getElementById('btn-main-action').innerText = 'Dừng';
                document.getElementById('btn-main-action').className = 'btn-main btn-stop';
                document.getElementById('progress-bar').style.width = '45%';
                document.getElementById('progress-percent').innerText = '45%';
                document.getElementById('progress-status').innerText = 'Đang thu thập câu 27/60';
                document.getElementById('stats-summary-line').innerText = '27/60 câu · 84 bình luận';
                const log = document.getElementById('log-box');
                const line = document.createElement('div');
                line.className = 'log-line log-info';
                line.innerText = '[12:00:15] [27/60] Media 137178: 4 bình luận (HTTP 200, 180ms)';
                log.appendChild(line);
            }""")
            p_run = SCREENSHOT_DIR / f"sidepanel_{width}px_running.png"
            page.screenshot(path=str(p_run))
            print(f"Captured: {p_run}")

            # 3. State: completed (xong)
            page.evaluate("""() => {
                document.getElementById('btn-main-action').innerText = 'Bắt đầu soạn';
                document.getElementById('btn-main-action').className = 'btn-main btn-start';
                document.getElementById('progress-bar').style.width = '100%';
                document.getElementById('progress-percent').innerText = '100%';
                document.getElementById('progress-status').innerText = 'Hoàn tất!';
                document.getElementById('stats-summary-line').innerText = '60/60 câu · 207 bình luận';
                document.getElementById('result-card').style.display = 'flex';
                document.getElementById('result-filename').innerText = 'MLN122 - SU26 - RE.docx';
            }""")
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

            # 5. State: not_logged_in (chưa đăng nhập)
            page.evaluate("""() => {
                document.getElementById('backend-status').className = 'status-chip chip-online';
                document.getElementById('backend-status').innerText = 'Backend Online';
                const notice = document.getElementById('ui-notice-box');
                notice.style.display = 'block';
                notice.innerText = 'Chưa đăng nhập FUOverflow. Mở fuoverflow.com và đăng nhập trước khi soạn!';
            }""")
            p_nli = SCREENSHOT_DIR / f"sidepanel_{width}px_not_logged_in.png"
            page.screenshot(path=str(p_nli))
            print(f"Captured: {p_nli}")

            context.close()

        browser.close()
    print("Done capturing responsive sidepanel states!")

if __name__ == "__main__":
    capture_sidepanel_responsive()
