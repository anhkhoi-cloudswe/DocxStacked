import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path("docs/qa/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def capture_login_states():
    # Load frontend built files
    dist_dir = Path("frontend/dist")
    if not dist_dir.exists():
        print("frontend/dist does not exist! Run npm run build first.")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Helper to set up mock routes for each state
        # 1. State: checking
        def route_checking(route):
            # Hang response to keep in 'checking' state
            pass

        # We can test by serving dist files with custom route mocks for /api/auth/status
        # In Playwright, we can intercept requests:
        page.route("**/api/auth/status", lambda route: route.abort())

        # Let's start an internal static server or load file directly:
        # Better: use python's http.server in background or file:// uri
        file_url = f"file:///{dist_dir.resolve().as_posix()}/index.html"
        
        # State 2: backend_offline (abort fetch to /api/auth/status)
        page.unroute("**/api/auth/status")
        page.route("**/api/auth/status", lambda route: route.abort())
        page.goto(file_url)
        page.wait_for_timeout(1000)
        p2 = SCREENSHOT_DIR / "auth_state_2_backend_offline.png"
        page.screenshot(path=str(p2))
        print(f"Captured: {p2}")

        # State 3: extension_missing (backend returns logged_in=False, no extension)
        page.unroute("**/api/auth/status")
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"logged_in": false, "status_code": "not_logged_in", "detail": "Chưa có phiên."}'
        ))
        page.goto(file_url)
        page.wait_for_timeout(1000)
        p3 = SCREENSHOT_DIR / "auth_state_3_extension_missing.png"
        page.screenshot(path=str(p3))
        print(f"Captured: {p3}")

        # State 4: not_logged_in (extension present on browser, but not logged into FUOverflow)
        page.unroute("**/api/auth/status")
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"logged_in": false, "status_code": "not_logged_in", "detail": "Chưa có phiên."}'
        ))
        # Inject extension marker
        page.add_init_script("window.DocxStackedExtensionPresent = true;")
        page.goto(file_url)
        page.wait_for_timeout(1000)
        p4 = SCREENSHOT_DIR / "auth_state_4_not_logged_in.png"
        page.screenshot(path=str(p4))
        print(f"Captured: {p4}")

        # State 1: checking (delay response or hang)
        page.unroute("**/api/auth/status")
        page.route("**/api/auth/status", lambda route: time.sleep(10))
        page.goto(file_url)
        page.wait_for_timeout(500)
        p1 = SCREENSHOT_DIR / "auth_state_1_checking.png"
        page.screenshot(path=str(p1))
        print(f"Captured: {p1}")

        browser.close()
    print("Done capturing login states!")

if __name__ == "__main__":
    capture_login_states()
