import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("docs/qa/screenshots").resolve()
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

WIDTHS = [320, 400, 500]
EXT_ID = "kicplcdfmbcfjildbbimpfiljlmfokea"
EXT_URL = f"chrome-extension://{EXT_ID}/sidepanel.html"

def capture_real_extension_sidepanel():
    ext_path = Path("extension").resolve()
    if not ext_path.exists():
        print("Extension directory not found!")
        sys.exit(1)

    with sync_playwright() as p:
        # Launch Chromium with real unpacked extension in headless=new mode
        context = p.chromium.launch_persistent_context(
            user_data_dir="temp_ext_user_data",
            headless=False,
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
                "--headless=new",
            ]
        )
        time.sleep(1.5)

        for width in WIDTHS:
            page = context.new_page()
            page.set_viewport_size({"width": width, "height": 650})
            page.goto(EXT_URL)
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)

            # 1. State: idle (chờ) on tab Soạn đề
            page.evaluate("""() => {
                switchTab('soande');
                document.getElementById('thread-title-display').innerText = 'MLN122 - SU26 - RE';
                document.getElementById('input-thread-url').value = 'https://fuoverflow.com/threads/mln122-su26-re.7207/';
                document.getElementById('stats-summary-line').innerText = '0/60 câu · 0 bình luận';
            }""")
            time.sleep(0.3)
            p_idle = SCREENSHOT_DIR / f"sidepanel_{width}px_idle.png"
            page.screenshot(path=str(p_idle))
            print(f"Captured: {p_idle}")

            # 2. State: running (đang chạy) on tab Soạn đề
            page.evaluate("""() => {
                switchTab('soande');
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
            time.sleep(0.3)
            p_run = SCREENSHOT_DIR / f"sidepanel_{width}px_running.png"
            page.screenshot(path=str(p_run))
            print(f"Captured: {p_run}")

            # 3. State: completed (xong - 100% đầy) on tab Soạn đề
            page.evaluate("""() => {
                switchTab('soande');
                document.getElementById('btn-main-action').innerText = 'Bắt đầu soạn';
                document.getElementById('btn-main-action').className = 'btn-main btn-start';
                const bar = document.getElementById('progress-bar');
                bar.style.width = '100%';
                document.getElementById('stats-summary-line').innerText = '60/60 câu · 207 bình luận';
                document.getElementById('result-card').style.display = 'flex';
                document.getElementById('result-filename').innerText = 'MLN122 - SU26 - RE.docx';
            }""")
            time.sleep(0.3)
            p_comp = SCREENSHOT_DIR / f"sidepanel_{width}px_completed.png"
            page.screenshot(path=str(p_comp))
            print(f"Captured: {p_comp}")

            # 4. State: backend_error (khi backend báo offline) on tab Soạn đề
            page.evaluate("""() => {
                switchTab('soande');
                document.getElementById('result-card').style.display = 'none';
                document.getElementById('backend-status').className = 'status-chip chip-offline';
                document.getElementById('backend-status').innerText = 'Backend Offline';
                showNotice('Backend chưa chạy. Mở terminal và chạy: python run_dev.py');
            }""")
            time.sleep(0.3)
            p_err = SCREENSHOT_DIR / f"sidepanel_{width}px_backend_error.png"
            page.screenshot(path=str(p_err))
            print(f"Captured: {p_err}")

            # 5. State: not_logged_in on tab Soạn đề (Banner chỉ hiện ở tab Soạn đề)
            page.evaluate("""() => {
                switchTab('soande');
                document.getElementById('backend-status').className = 'status-chip chip-online';
                document.getElementById('backend-status').innerText = 'Backend Online';
                showNotice('Chưa đăng nhập FUOverflow. Mở fuoverflow.com và đăng nhập trước khi soạn!');
            }""")
            time.sleep(0.3)
            p_not_login = SCREENSHOT_DIR / f"sidepanel_{width}px_not_logged_in.png"
            page.screenshot(path=str(p_not_login))
            print(f"Captured: {p_not_login}")

            # 6. Specific workflows for 320px and 400px: reopen card & reopen updating
            if width in [320, 400]:
                # Reopen card: "Đã soạn lúc HH:MM (60 câu) - Tải file / Cập nhật bình luận"
                page.evaluate("""() => {
                    switchTab('soande');
                    hideNotice();
                    const reopenCard = document.getElementById('reopen-card');
                    reopenCard.style.display = 'flex';
                    document.getElementById('reopen-text').innerText = 'Đã soạn lúc 12:27 (60 câu)';
                }""")
                time.sleep(0.3)
                p_reopen = SCREENSHOT_DIR / f"sidepanel_{width}px_reopen_card.png"
                page.screenshot(path=str(p_reopen))
                print(f"Captured: {p_reopen}")

                # Reopen updating: Clicking "Cập nhật bình luận"
                page.evaluate("""() => {
                    switchTab('soande');
                    const reopenCard = document.getElementById('reopen-card');
                    reopenCard.style.display = 'flex';
                    document.getElementById('btn-reopen-update').innerText = 'Đang cập nhật...';
                    document.getElementById('btn-reopen-update').disabled = true;
                    document.getElementById('stats-summary-line').innerText = 'Đang tải bình luận (bỏ qua ảnh)... 15/60';
                    const bar = document.getElementById('progress-bar');
                    bar.style.width = '25%';
                }""")
                time.sleep(0.3)
                p_reopen_updating = SCREENSHOT_DIR / f"sidepanel_{width}px_reopen_updating.png"
                page.screenshot(path=str(p_reopen_updating))
                print(f"Captured: {p_reopen_updating}")

            # 7. Tab Đã soạn: Real API call to /api/user/documents from real extension sidepanel
            page.evaluate("""() => {
                switchTab('dasoan');
            }""")
            # Wait for documents to load from real backend
            page.wait_for_selector(".doc-item", timeout=5000)
            time.sleep(0.5)
            p_tab_docs = SCREENSHOT_DIR / f"sidepanel_{width}px_tab_dasoan.png"
            page.screenshot(path=str(p_tab_docs))
            print(f"Captured: {p_tab_docs}")

            # 8. Tab Cài đặt: Real API call to /api/settings with all configured providers
            page.evaluate("""() => {
                switchTab('caidat');
            }""")
            page.wait_for_selector(".provider-row", timeout=5000)
            time.sleep(0.5)
            p_tab_settings = SCREENSHOT_DIR / f"sidepanel_{width}px_tab_caidat.png"
            page.screenshot(path=str(p_tab_settings))
            print(f"Captured: {p_tab_settings}")

            # 9. Tab Chọn đề: Real UI with subject select & multi-exam selection
            page.evaluate("""() => {
                switchTab('chonde');
                const sel = document.getElementById('select-subject');
                sel.innerHTML = '<option value="MLN122">MLN122 - Triết học Mác - Lênin</option>';
                sel.value = 'MLN122';
                chondeState.selectedSubject = 'MLN122';
                chondeState.exams = [
                    { title: 'MLN122 - SU26 - RE', url: 'https://fuoverflow.com/threads/mln122-su26-re.7207/', exam_type: 'FE', term: 'SU26', question_count: 60, compiled: true, compiled_at: '12:27 15/11/2026' },
                    { title: 'MLN122 - SU26 - FE - C1', url: 'https://fuoverflow.com/threads/mln122-su26-fe-c1.7097/', exam_type: 'FE', term: 'SU26', question_count: 60, compiled: false, compiled_at: null },
                    { title: 'MLN122 - SU26 - FE - C2', url: 'https://fuoverflow.com/threads/mln122-su26-fe-c2.7098/', exam_type: 'FE', term: 'SU26', question_count: 60, compiled: false, compiled_at: null },
                    { title: 'MLN122 - SP26 - C1FE', url: 'https://fuoverflow.com/threads/mln122-sp26-c1fe.6344/', exam_type: 'FE', term: 'SP26', question_count: 60, compiled: false, compiled_at: null },
                    { title: 'MLN122 - SP26 - C2FE', url: 'https://fuoverflow.com/threads/mln122-sp26-c2fe.6343/', exam_type: 'FE', term: 'SP26', question_count: 60, compiled: false, compiled_at: null }
                ];
                chondeState.selectedUrls.clear();
                chondeState.selectedUrls.add('https://fuoverflow.com/threads/mln122-su26-fe-c1.7097/');
                chondeState.selectedUrls.add('https://fuoverflow.com/threads/mln122-su26-fe-c2.7098/');
                renderChondeList();
                updateChondeSelectionBadge();
            }""")
            time.sleep(0.5)
            p_chonde = SCREENSHOT_DIR / f"sidepanel_{width}px_tab_chonde.png"
            page.screenshot(path=str(p_chonde))
            print(f"Captured: {p_chonde}")

            # 10. Queue Running state (with 1 simulated error state & question progress)
            page.evaluate("""() => {
                switchTab('chonde');
                document.getElementById('queue-controls-row').style.display = 'flex';
                document.getElementById('queue-progress-card').style.display = 'block';
                document.getElementById('queue-completed-banner').style.display = 'none';
                chondeState.activeQueue = [
                    { title: 'MLN122 - SU26 - FE - C1', url: 'https://fuoverflow.com/threads/mln122-su26-fe-c1.7097/', status: 'done', compiled: true },
                    { title: 'MLN122 - SU26 - FE - C2', url: 'https://fuoverflow.com/threads/mln122-su26-fe-c2.7098/', status: 'error', compiled: false },
                    { title: 'MLN122 - SP26 - C1FE', url: 'https://fuoverflow.com/threads/mln122-sp26-c1fe.6344/', status: 'running', compiled: false }
                ];
                chondeState.queueIndex = 2;
                chondeState.isQueueRunning = true;
                updateQueueProgressUI('MLN122 - SP26 - C1FE', 23, 60);
                chondeState.exams[1].status = 'error';
                renderChondeList();
            }""")
            time.sleep(0.5)
            p_queue_run = SCREENSHOT_DIR / f"sidepanel_{width}px_queue_running.png"
            page.screenshot(path=str(p_queue_run))
            print(f"Captured: {p_queue_run}")

            # 11. Queue Completed state
            page.evaluate("""() => {
                switchTab('chonde');
                document.getElementById('queue-controls-row').style.display = 'none';
                document.getElementById('queue-progress-card').style.display = 'none';
                const banner = document.getElementById('queue-completed-banner');
                banner.style.display = 'flex';
                document.getElementById('queue-completed-msg').innerText = 'Xong 1 · Lỗi 1 · Bỏ qua 1';
                chondeState.isQueueRunning = false;
            }""")
            time.sleep(0.5)
            p_queue_comp = SCREENSHOT_DIR / f"sidepanel_{width}px_queue_completed.png"
            page.screenshot(path=str(p_queue_comp))
            print(f"Captured: {p_queue_comp}")

            # Check horizontal scroll on Tab Đã soạn
            page.evaluate("""() => {
                switchTab('dasoan');
            }""")
            time.sleep(0.5)
            scroll_check = page.evaluate("""() => {
                const el = document.documentElement;
                const body = document.body;
                const maxScrollWidth = Math.max(el.scrollWidth, body.scrollWidth);
                const clientWidth = el.clientWidth;
                return {
                    scrollWidth: maxScrollWidth,
                    clientWidth: clientWidth,
                    hasHorizontalScroll: maxScrollWidth > clientWidth
                };
            }""")
            print(f"[{width}px Scroll Check Tab Đã Soạn] scrollWidth={scroll_check['scrollWidth']}, clientWidth={scroll_check['clientWidth']}, hasHorizontalScroll={scroll_check['hasHorizontalScroll']}")
            assert not scroll_check['hasHorizontalScroll'], f"Horizontal scroll detected at {width}px: {scroll_check}"

            # 12. Tab Đã soạn with multi-select active
            page.evaluate("""() => {
                switchTab('dasoan');
            }""")
            time.sleep(0.8)
            page.evaluate("""() => {
                const cbs = document.querySelectorAll('#tab-panel-dasoan .doc-checkbox');
                if (cbs.length >= 2) {
                    cbs[0].checked = true;
                    cbs[1].checked = true;
                    selectedDocs.add(cbs[0].dataset.filename);
                    selectedDocs.add(cbs[1].dataset.filename);
                    updateDasoanSelectionBadge();
                }
            }""")
            time.sleep(0.4)
            p_dasoan_multi = SCREENSHOT_DIR / f"sidepanel_{width}px_dasoan_multiselect.png"
            page.screenshot(path=str(p_dasoan_multi))
            print(f"Captured: {p_dasoan_multi}")

            page.close()

        context.close()
    print("Done capturing all sidepanel states from real extension sidepanel!")

if __name__ == "__main__":
    capture_real_extension_sidepanel()
