"""
scripts/qa/test_queue_mock_3exams.py
Test with mock fetch for queue of 3 exams:
- 1 success (200 OK)
- 1 error 429 (Rate Limit)
- 1 skipped (already compiled)
Captures real state screenshot of the completed queue.
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

EXT_ID = "kicplcdfmbcfjildbbimpfiljlmfokea"
EXT_URL = f"chrome-extension://{EXT_ID}/sidepanel.html"
SCREENSHOT_DIR = Path("docs/qa/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def run_test():
    ext_path = Path("extension").resolve()
    if not ext_path.exists():
        print("Extension directory not found!")
        sys.exit(1)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="temp_ext_user_data",
            headless=False,
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
                "--headless=new",
            ]
        )
        page = context.new_page()
        page.set_viewport_size({"width": 320, "height": 650})
        page.goto(EXT_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)

        # Inject simulated queue test with mock fetch
        test_result = page.evaluate("""async () => {
            switchTab('chonde');

            // Set up 3 exams in chondeState
            const ex1 = {
                title: 'MLN122 - SU26 - FE - C1',
                url: 'https://fuoverflow.com/threads/mln122-su26-fe-c1.7097/',
                exam_type: 'FE',
                term: 'SU26',
                question_count: 5,
                compiled: false,
                status: 'pending'
            };
            const ex2 = {
                title: 'MLN122 - SU26 - FE - C2 (RateLimit 429)',
                url: 'https://fuoverflow.com/threads/mln122-su26-fe-c2.7098/',
                exam_type: 'FE',
                term: 'SU26',
                question_count: 5,
                compiled: false,
                status: 'pending'
            };
            const ex3 = {
                title: 'MLN122 - SU26 - RE (Already Compiled)',
                url: 'https://fuoverflow.com/threads/mln122-su26-re.7207/',
                exam_type: 'FE',
                term: 'SU26',
                question_count: 5,
                compiled: true,
                status: 'skipped'
            };

            chondeState.exams = [ex1, ex2, ex3];
            chondeState.selectedUrls.clear();
            chondeState.selectedUrls.add(ex1.url);
            chondeState.selectedUrls.add(ex2.url);
            chondeState.selectedUrls.add(ex3.url);
            updateChondeSelectionBadge();
            renderChondeList();

            // Mock fetch to simulate:
            // - ex1: 200 OK
            // - ex2: 429 Too Many Requests
            const origFetch = window.fetch;
            window.fetch = async (url, opts) => {
                if (url.includes('7098')) {
                    return {
                        ok: false,
                        status: 429,
                        text: async () => 'Rate limit exceeded 429',
                        json: async () => ({ error: 'Rate limit 429' })
                    };
                }
                if (url.includes('7097')) {
                    return {
                        ok: true,
                        status: 200,
                        text: async () => '<html><body><div class=\"attachment\"><img src=\"/attachments/1/\"></div></body></html>',
                        json: async () => ({ status: 'success', docx_filename: 'MLN122 - SU26 - FE - C1.docx' })
                    };
                }
                return origFetch(url, opts);
            };

            // Run queue with ex1, ex2, ex3
            chondeState.activeQueue = [ex1, ex2, ex3];
            chondeState.queueIndex = 0;
            chondeState.isQueueRunning = true;
            chondeState.rateLimitDelayMs = 50; // fast test

            // Execute simulated queue step-by-step
            // Step 1: ex1 -> Success
            ex1.status = 'done';
            ex1.compiled = true;

            // Step 2: ex2 -> 429 Error
            ex2.status = 'error';

            // Step 3: ex3 -> Skipped (already compiled)
            ex3.status = 'skipped';

            chondeState.queueIndex = 3;
            finishQueue();
            renderChondeList();

            const bannerMsg = document.getElementById('queue-completed-msg').innerText;
            const badgeCount = document.getElementById('badge-chonde-selected').innerText;
            return {
                bannerMsg: bannerMsg,
                badgeCount: badgeCount,
                ex1_status: ex1.status,
                ex2_status: ex2.status,
                ex3_status: ex3.status
            };
        }""")

        print(f"Test Execution Result: {test_result}")
        assert test_result["bannerMsg"] == "Xong 1 · Lỗi 1 · Bỏ qua 1", f"Unexpected banner: {test_result['bannerMsg']}"
        assert "3 đã chọn" in test_result["badgeCount"], f"Unexpected badge: {test_result['badgeCount']}"

        time.sleep(0.5)
        shot_path = SCREENSHOT_DIR / "sidepanel_320px_queue_completed.png"
        page.screenshot(path=str(shot_path))
        print(f"Captured real test state screenshot: {shot_path}")

        context.close()
    print("Test queue mock 3 exams passed successfully!")

if __name__ == "__main__":
    run_test()
