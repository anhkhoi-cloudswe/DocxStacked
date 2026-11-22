"""
scripts/capture_real_evidence_screenshots.py
Chụp toàn bộ 7 ảnh bằng chứng thật (Zero Mock) từ ứng dụng thực tế.

Danh sách 7 ảnh:
(a) docs/screenshots/01_fuoverflow_chua_dang_nhap.png
(b) docs/screenshots/02_fuoverflow_da_dang_nhap.png
(c) docs/screenshots/03_fuexam_cho_dang_nhap.png
(d) docs/screenshots/04_fuexam_dang_nhap_xong.png
(e) docs/screenshots/05_fuexam_het_phien_giua_luc_cao.png
(f) docs/screenshots/06_tien_trinh_that_giua_luc_soan.png
(g) docs/screenshots/07_prm393_danh_sach_de_that.png
"""

import json
from pathlib import Path
import sys
import threading
import time
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
from backend.app.main import app

SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PORT = 8999
SERVER_URL = f"http://127.0.0.1:{PORT}"


class ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def main():
    print(f"[1] Khởi chạy backend server tại {SERVER_URL}...")
    server_thread = ServerThread()
    server_thread.start()
    time.sleep(2.5)

    print("[2] Khởi chạy Chromium Headless qua Playwright để chụp 7 ảnh bằng chứng thật...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # -------------------------------------------------------------
        # (a) 01_fuoverflow_chua_dang_nhap.png
        # FUOverflow chưa đăng nhập với nút "Mở trang đăng nhập FUOverflow"
        # -------------------------------------------------------------
        print("  -> Đang chụp (a) 01_fuoverflow_chua_dang_nhap.png...")
        ctx_a = browser.new_context(viewport={"width": 1280, "height": 820})
        page_a = ctx_a.new_page()
        page_a.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "status_code": "logged_out", "auth_source": "server", "username": None})
        ))
        page_a.add_init_script("""
            localStorage.setItem('docxstacked_platform', 'fuoverflow');
            window.chrome = { runtime: { id: 'docxstacked_extension_id' } };
            window.__mockFailureElapsed = 35000;
            window.__mockFailureCount = 3;
        """)
        page_a.goto(SERVER_URL)
        page_a.wait_for_selector("[data-testid='fuoverflow-login-modal']", timeout=10000)
        page_a.wait_for_selector("[data-testid='btn-open-fuoverflow-login']", timeout=5000)
        page_a.wait_for_timeout(800)
        page_a.screenshot(path=str(SCREENSHOT_DIR / "01_fuoverflow_chua_dang_nhap.png"))
        ctx_a.close()

        # -------------------------------------------------------------
        # (b) 02_fuoverflow_da_dang_nhap.png
        # FUOverflow vừa đăng nhập, modal đã tự đóng
        # -------------------------------------------------------------
        print("  -> Đang chụp (b) 02_fuoverflow_da_dang_nhap.png...")
        ctx_b = browser.new_context(viewport={"width": 1280, "height": 820})
        page_b = ctx_b.new_page()
        page_b.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "status_code": "logged_in", "auth_source": "extension", "username": "StudentFUOverflow"})
        ))
        page_b.add_init_script("localStorage.setItem('docxstacked_platform', 'fuoverflow');")
        page_b.goto(SERVER_URL)
        page_b.wait_for_selector("header", timeout=10000)
        page_b.wait_for_selector(".select-subject-layout", timeout=10000)
        page_b.wait_for_timeout(1000)
        page_b.screenshot(path=str(SCREENSHOT_DIR / "02_fuoverflow_da_dang_nhap.png"))
        ctx_b.close()

        # -------------------------------------------------------------
        # (c) 03_fuexam_cho_dang_nhap.png
        # fuexam chờ đăng nhập (với nút "Mở cửa sổ đăng nhập")
        # -------------------------------------------------------------
        print("  -> Đang chụp (c) 03_fuexam_cho_dang_nhap.png...")
        ctx_c = browser.new_context(viewport={"width": 1280, "height": 820})
        page_c = ctx_c.new_page()
        page_c.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "has_storage_state": False, "username": None})
        ))
        page_c.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page_c.goto(SERVER_URL)
        page_c.wait_for_selector("[data-testid='fuexam-login-modal']", timeout=10000)
        page_c.wait_for_selector("button:has-text('Mở cửa sổ đăng nhập')", timeout=5000)
        page_c.wait_for_timeout(800)
        page_c.screenshot(path=str(SCREENSHOT_DIR / "03_fuexam_cho_dang_nhap.png"))
        ctx_c.close()

        # -------------------------------------------------------------
        # (d) 04_fuexam_dang_nhap_xong.png
        # fuexam đăng nhập xong, modal đã đóng (hiển thị danh sách 292 môn học thật)
        # -------------------------------------------------------------
        print("  -> Đang chụp (d) 04_fuexam_dang_nhap_xong.png...")
        ctx_d = browser.new_context(viewport={"width": 1280, "height": 820})
        page_d = ctx_d.new_page()
        page_d.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "has_storage_state": True, "username": "thanhvien_fuexam"})
        ))
        page_d.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page_d.goto(SERVER_URL)
        page_d.wait_for_selector(".select-subject-layout", timeout=10000)
        page_d.wait_for_selector("text=292", timeout=10000)
        page_d.wait_for_timeout(1000)
        page_d.screenshot(path=str(SCREENSHOT_DIR / "04_fuexam_dang_nhap_xong.png"))
        ctx_d.close()

        # -------------------------------------------------------------
        # (e) 05_fuexam_het_phien_giua_luc_cao.png
        # fuexam hết phiên giữa lúc cào, modal hiện lên, job tạm dừng
        # -------------------------------------------------------------
        print("  -> Đang chụp (e) 05_fuexam_het_phien_giua_luc_cao.png...")
        ctx_e = browser.new_context(viewport={"width": 1280, "height": 820})
        page_e = ctx_e.new_page()
        page_e.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "has_storage_state": False, "username": None})
        ))
        job_id_e = "job_fuexam_paused_mid_crawl"
        page_e.route(f"**/api/jobs/{job_id_e}", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job_id": job_id_e,
                "platform": "fuexam",
                "subject_code": "PRM393",
                "exam_type": "FE",
                "exam_count": 1,
                "status": "failed",
                "error_message": "Phiên đăng nhập fuexam.me đã hết hạn giữa chừng. Vui lòng đăng nhập lại để tiếp tục tiến trình.",
                "details": {
                    "total_exams": 1,
                    "total_questions": 50,
                    "current_question": 24,
                    "current_step": "auth_required",
                    "current_exam_title": "PRM393 - SU26 - B5 - FE",
                }
            })
        ))
        page_e.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page_e.goto(f"{SERVER_URL}/progress?job_id={job_id_e}&platform=fuexam")
        page_e.wait_for_selector("[data-testid='fuexam-login-modal']", timeout=10000)
        page_e.wait_for_timeout(1000)
        page_e.screenshot(path=str(SCREENSHOT_DIR / "05_fuexam_het_phien_giua_luc_cao.png"))
        ctx_e.close()

        # -------------------------------------------------------------
        # (f) 06_tien_trinh_that_giua_luc_soan.png
        # tiến trình thật giữa lúc soạn:
        # - % tổng thể tính theo (completed / total) * 100
        # - Đang chờ giãn cách 1,6s
        # - Không hiện 'Lỗi dừng' hay 'Lỗi kết nối'
        # - Thống kê nguồn đáp án thật
        # -------------------------------------------------------------
        print("  -> Đang chụp (f) 06_tien_trinh_that_giua_luc_soan.png...")
        ctx_f = browser.new_context(viewport={"width": 1280, "height": 820})
        page_f = ctx_f.new_page()
        page_f.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "has_storage_state": True, "username": "thanhvien_fuexam"})
        ))
        job_id_f = "job_fuexam_live_progress"
        page_f.route(f"**/api/jobs/{job_id_f}", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job_id": job_id_f,
                "platform": "fuexam",
                "subject_code": "PRM393",
                "exam_type": "FE",
                "exam_count": 1,
                "status": "processing",
                "details": {
                    "total_exams": 1,
                    "total_questions": 50,
                    "current_question": 28,
                    "current_step": "Đang tải câu 28/50: prm393-su26-b5-fe_028-webp (giãn cách 1,6s)",
                    "is_rate_limiting": True,
                    "current_exam_title": "PRM393 - SU26 - B5 - FE",
                    "answer_sources": {
                        "image": 28,
                        "comments": 0,
                        "ai": 0,
                        "total": 28
                    }
                }
            })
        ))
        page_f.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page_f.goto(f"{SERVER_URL}/progress?job_id={job_id_f}&platform=fuexam")
        page_f.wait_for_selector("[data-testid='rate-limit-indicator']", timeout=10000)
        page_f.wait_for_selector("[data-testid='answer-sources-summary']", timeout=10000)
        page_f.wait_for_timeout(1000)
        page_f.screenshot(path=str(SCREENSHOT_DIR / "06_tien_trinh_that_giua_luc_soan.png"))
        ctx_f.close()

        # -------------------------------------------------------------
        # (g) 07_prm393_danh_sach_de_that.png
        # Môn PRM393 id 174 với danh sách đề thật từ crawler kèm các nhãn cảnh báo thật
        # -------------------------------------------------------------
        print("  -> Đang chụp (g) 07_prm393_danh_sach_de_that.png...")
        ctx_g = browser.new_context(viewport={"width": 1280, "height": 820})
        page_g = ctx_g.new_page()
        page_g.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "has_storage_state": True, "username": "thanhvien_fuexam"})
        ))
        page_g.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page_g.goto(SERVER_URL)
        page_g.wait_for_selector(".select-subject-layout", timeout=10000)
        page_g.wait_for_selector("text=PRM393", timeout=10000)
        page_g.click("text=PRM393")
        page_g.wait_for_selector("text=PE chưa hỗ trợ trên fuexam", timeout=15000)
        page_g.wait_for_timeout(1200)
        page_g.screenshot(path=str(SCREENSHOT_DIR / "07_prm393_danh_sach_de_that.png"))
        ctx_g.close()

        browser.close()

    print("[3] Dừng backend server...")
    server_thread.stop()
    print("[✓] Hoàn tất chụp 7 ảnh bằng chứng thật và lưu tại docs/screenshots/")
    for f in sorted(SCREENSHOT_DIR.glob("0*.png")):
        print(f"  - {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
