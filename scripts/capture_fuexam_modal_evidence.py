"""
scripts/capture_fuexam_modal_evidence.py
Tự động chụp ảnh màn hình bằng chứng cho các trạng thái UI:
1. Failed do backend chưa sẵn sàng (kèm banner "Backend chưa sẵn sàng, đang thử lại")
2. Starting (Đang khởi động cửa sổ Chromium, chưa vào waiting)
3. Waiting (Đang mở cửa sổ Chromium và chờ người dùng đăng nhập)
4. Failed do tiến trình con chết (hiện lý do cụ thể và nút thử lại)
5. Settings - Kiểm tra Chromium (Nút "Kiểm tra Chromium" và kết quả)
"""

import json
from pathlib import Path
import time
import http.server
import socketserver
import threading
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "temp_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """Simple HTTP Request Handler with SPA fallback to index.html for client-side routing."""
    def do_GET(self):
        url_path = self.path.split("?")[0]
        fs_path = Path(self.directory) / url_path.lstrip("/")
        if not fs_path.is_file() and not url_path.startswith("/assets/"):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        pass

def run_capture():
    import functools
    handler = functools.partial(SPAHandler, directory=str(DIST_DIR))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        page = context.new_page()

        # Shared mock data
        page.route("**/api/subjects*", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "items": [{"code": "PRM393", "name": "Mobile Programming", "exam_count": 4}],
                "total": 1
            })
        ))
        page.route("**/api/user/documents*", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps([])
        ))
        page.route("**/api/jobs/active", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(None)
        ))
        page.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "logged_in": False,
                "status_code": "logged_out",
                "username": None
            })
        ))

        # -------------------------------------------------------------
        # 1. Evidence 1: Backend chưa sẵn sàng (Banner + disabled button)
        # -------------------------------------------------------------
        print("Capturing 1: Backend chưa sẵn sàng...", flush=True)
        page.route("**/api/health", lambda route: route.fulfill(status=503, body="Service Unavailable"))
        page.route("**/api/auth/fuexam/login/status", lambda route: route.fulfill(
            status=503, body="Service Unavailable"
        ))

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page.goto(base_url)
        page.wait_for_selector("[data-testid='backend-not-ready-banner']", timeout=6000)
        page.wait_for_selector("[data-testid='fuexam-backend-not-ready-notice']", timeout=6000)
        time.sleep(0.5)
        path1 = SCREENSHOT_DIR / "MOCK_evidence_01_backend_not_ready.png"
        page.screenshot(path=str(path1))
        print(f"Saved: {path1}", flush=True)

        # -------------------------------------------------------------
        # 2. Evidence 2: State = 'starting'
        # -------------------------------------------------------------
        print("Capturing 2: State starting...", flush=True)
        page.route("**/api/health", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"status": "ok"})
        ))
        page.route("**/api/auth/fuexam/login/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "state": "starting",
                "message": "Đang kết nối và khởi động cửa sổ Chromium..."
            })
        ))

        page.reload()
        page.wait_for_selector("text=Đang khởi động cửa sổ Chromium...", timeout=6000)
        time.sleep(0.5)
        path2 = SCREENSHOT_DIR / "MOCK_evidence_02_starting.png"
        page.screenshot(path=str(path2))
        print(f"Saved: {path2}", flush=True)

        # -------------------------------------------------------------
        # 3. Evidence 3: State = 'waiting' (Chromium opened, awaiting login)
        # -------------------------------------------------------------
        print("Capturing 3: State waiting...", flush=True)
        page.route("**/api/auth/fuexam/login/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "state": "waiting",
                "message": "Cửa sổ Chromium với tiêu đề 'DocxStacked - Đăng nhập fuexam' đã mở.",
                "recent_logs": [
                    "[2026-11-22 17:15:00] [INFO] Khởi tạo Chromium mới với profile tạm: C:\\temp\\fuexam_fresh",
                    "[2026-11-22 17:15:02] [INFO] Đã mở trang đăng nhập https://fuexam.me/login/",
                    "[2026-11-22 17:15:03] [INFO] Tiêu đề: DocxStacked - Đăng nhập fuexam (Đã đưa lên trước)",
                    "[2026-11-22 17:15:04] [INFO] Báo hiệu IPC state: waiting tới backend"
                ]
            })
        ))
        page.reload()
        page.wait_for_selector("[data-testid='btn-cancel-fuexam-login']", timeout=6000)
        # Click view recent logs to display in screenshot
        show_logs_btn = page.locator("button:has-text('Xem nhật ký')")
        if show_logs_btn.is_visible():
            show_logs_btn.click()
            time.sleep(0.3)
        time.sleep(0.4)
        path3 = SCREENSHOT_DIR / "MOCK_evidence_03_waiting.png"
        page.screenshot(path=str(path3))
        print(f"Saved: {path3}", flush=True)

        # -------------------------------------------------------------
        # 4. Evidence 4: State = 'failed' do tiến trình con chết
        # -------------------------------------------------------------
        print("Capturing 4: State failed (tiến trình con chết)...", flush=True)
        page.route("**/api/auth/fuexam/login/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "state": "failed",
                "message": "Tiến trình trình duyệt đã dừng bất thường",
                "error": "Tiến trình Chromium đã thoát sớm với mã lỗi 1. Cửa sổ Chromium đã bị đóng trước khi hoàn tất đăng nhập."
            })
        ))
        page.reload()
        page.wait_for_selector("[data-testid='btn-retry-fuexam-login']", timeout=6000)
        page.wait_for_selector("[data-testid='fuexam-error-message']", timeout=6000)
        time.sleep(0.4)
        path4 = SCREENSHOT_DIR / "MOCK_evidence_04_failed_child_process_dead.png"
        page.screenshot(path=str(path4))
        print(f"Saved: {path4}", flush=True)

        # -------------------------------------------------------------
        # 5. Evidence 5: Settings - Kiểm tra Chromium
        # -------------------------------------------------------------
        print("Capturing 5: Settings - Kiểm tra Chromium...", flush=True)
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "logged_in": True,
                "status_code": "logged_in",
                "auth_source": "extension",
                "username": "Đông Khởi"
            })
        ))
        page.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "logged_in": True,
                "status_code": "logged_in",
                "username": "Đông Khởi"
            })
        ))
        page.route("**/api/auth/fuexam/login/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "state": "success",
                "message": "Đã đăng nhập"
            })
        ))
        def handle_settings(route):
            if "chromium-self-check" in route.request.url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "success": True,
                    "browser": "Playwright Chromium",
                    "executable_path": "C:\\Users\\Admin\\AppData\\Local\\ms-playwright\\chromium-1254\\chrome-win64\\chrome.exe",
                    "message": "Chromium mở và đóng bình thường (3s test)."
                }))
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "export": {
                        "formats": ["docx"],
                        "image_width_cm": 16.51,
                        "highlight_low_confidence": False,
                        "answer_format": "letter",
                        "multi_choice_format": "comma",
                        "merge": True
                    },
                    "crawler": {"delay_between_requests": 1.6},
                    "crawl": {
                        "delay_seconds": [1.6, 2.0],
                        "concurrency": 1,
                        "headless": True,
                        "max_retries": 3
                    },
                    "storage": {"retention_days": 14},
                    "extension": {"ingest_token": "random_test_token_8a7d6e5c4b3a2f1e"},
                    "voting": {
                        "confident_min_ratio": 0.7,
                        "confident_min_voters": 3,
                        "multi_choice_threshold": 0.5,
                        "vote_weight": "uniform",
                        "ai_weight": 1.0
                    },
                    "ai": {
                        "enabled": True,
                        "ensemble": False,
                        "max_ai_calls": 50,
                        "backoff_seconds": 2,
                        "max_retries": 3,
                        "providers": []
                    }
                }))

        page.route("**/api/settings/chromium-self-check", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({
                "success": True,
                "browser": "Playwright Chromium",
                "executable_path": "C:\\Users\\Admin\\AppData\\Local\\ms-playwright\\chromium-1254\\chrome-win64\\chrome.exe",
                "message": "Chromium mở và đóng bình thường (3s test)."
            })
        ))
        page.route("**/api/settings", handle_settings)
        page.route("**/api/settings?*", handle_settings)

        page.goto(f"{base_url}/settings?platform=fuexam")
        page.wait_for_selector("text=3. Nâng cao", timeout=6000)
        page.locator("text=3. Nâng cao").click()
        time.sleep(0.4)

        page.wait_for_selector("[data-testid='btn-test-chromium']", timeout=6000)
        btn_test_chrom = page.locator("[data-testid='btn-test-chromium']")
        btn_test_chrom.click()

        page.wait_for_selector("text=Kiểm tra Chromium thành công!", timeout=6000)
        time.sleep(0.4)
        path5 = SCREENSHOT_DIR / "MOCK_evidence_05_settings_chromium_check.png"
        page.screenshot(path=str(path5))
        print(f"Saved: {path5}", flush=True)

        browser.close()
    server.shutdown()
    print("All evidence screenshots captured successfully!", flush=True)

if __name__ == "__main__":
    run_capture()
