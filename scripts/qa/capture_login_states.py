import http.server
import socketserver
import threading
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image

SCREENSHOT_DIR = Path("docs/qa/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
PORT = 5174

def capture_login_states():
    dist_dir = Path("frontend/dist").resolve()
    if not dist_dir.exists():
        print("frontend/dist does not exist! Run npm run build first.")
        sys.exit(1)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", PORT), QuietHandler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{PORT}"

    captured_files = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})

        # 1. State: checking (Đang kiểm tra)
        page1 = context.new_page()
        # Delay the /api/auth/status route indefinitely
        page1.route("**/api/auth/status", lambda route: None)
        page1.goto(base_url)
        page1.wait_for_selector("text=Đang kiểm tra", timeout=5000)
        p1 = SCREENSHOT_DIR / "auth_state_1_checking.png"
        page1.screenshot(path=str(p1))
        captured_files.append(p1)
        page1.close()

        # 2. State: backend_offline (Không kết nối được backend)
        page2 = context.new_page()
        page2.route("**/api/auth/status", lambda route: route.abort())
        page2.goto(base_url)
        page2.wait_for_selector("text=Không kết nối được backend", timeout=5000)
        p2 = SCREENSHOT_DIR / "auth_state_2_backend_offline.png"
        page2.screenshot(path=str(p2))
        captured_files.append(p2)
        page2.close()

        # 3. State: extension_missing (Chưa thấy extension trên trình duyệt này)
        page3 = context.new_page()
        page3.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"logged_in": false, "status_code": "not_logged_in", "detail": "Chưa có phiên."}'
        ))
        page3.goto(base_url)
        page3.wait_for_selector("text=Chưa thấy extension trên trình duyệt này", timeout=5000)
        p3 = SCREENSHOT_DIR / "auth_state_3_extension_missing.png"
        page3.screenshot(path=str(p3))
        captured_files.append(p3)
        page3.close()

        # 4. State: not_logged_in (Chưa đăng nhập FUOverflow)
        page4 = context.new_page()
        page4.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"logged_in": false, "status_code": "not_logged_in", "detail": "Chưa có phiên."}'
        ))
        # Mark extension present on browser
        page4.add_init_script("window.DocxStackedExtensionPresent = true;")
        page4.goto(base_url)
        page4.wait_for_selector("text=Chưa đăng nhập FUOverflow", timeout=5000)
        p4 = SCREENSHOT_DIR / "auth_state_4_not_logged_in.png"
        page4.screenshot(path=str(p4))
        captured_files.append(p4)
        page4.close()

        browser.close()

    httpd.shutdown()

    # Validation: Ensure none of the images are monochromatic
    print("\n=== VALIDATING SCREENSHOT IMAGES ===")
    all_valid = True
    for img_path in captured_files:
        im = Image.open(img_path)
        colors = im.getcolors(maxcolors=256)
        num_colors = len(colors) if colors else ">256"
        is_monochrome = (num_colors == 1)
        status_str = "FAILED (Monochrome)" if is_monochrome else "PASSED (Multi-color content)"
        print(f"{img_path.name}: {im.size}, colors: {num_colors} -> {status_str}")
        if is_monochrome:
            all_valid = False

    if not all_valid:
        print("ERROR: One or more screenshots were monochromatic!")
        sys.exit(1)
    else:
        print("All 4 login states captured and validated successfully!\n")

if __name__ == "__main__":
    capture_login_states()
