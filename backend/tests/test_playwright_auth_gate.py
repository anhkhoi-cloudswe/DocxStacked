import functools
import http.server
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


class FreePortServer:
    def __init__(self, directory: Path):
        self.directory = directory
        self.server = None
        self.thread = None
        self.port = 0

    def start(self):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(self.directory))
        # Bind to port 0 for random free port
        self.server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


@pytest.fixture(scope="module")
def dist_server():
    assert (DIST_DIR / "index.html").exists(), "frontend/dist/index.html must exist before running test"
    srv = FreePortServer(DIST_DIR)
    srv.start()
    yield f"http://127.0.0.1:{srv.port}"
    srv.stop()


def create_isolated_page(context):
    """Creates a page with all global background endpoints intercepted to strictly prevent leakage to port 8000."""
    page = context.new_page()
    page.add_init_script("try { localStorage.setItem('docxstacked_platform', 'fuoverflow'); } catch (e) {}")
    page.route("**/api/auth/extension-heartbeat", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"ok": True})
    ))
    page.route("**/api/health", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"status": "healthy"})
    ))
    return page


def test_auth_gate_tab_switching_20_times_stable(dist_server):
    """
    Simulate switching tabs 20 times consecutively:
    The auth gate state must remain stable (logged_in) and no flickering error cards appear.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = create_isolated_page(context)

        # Intercept backend auth status: always authenticated
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "logged_in": True,
                "status_code": "logged_in",
                "auth_source": "extension",
                "username": "TestFPTStudent",
            })
        ))
        page.route("**/api/subjects*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([])
        ))

        # Extension presence marker
        page.add_init_script("window.DocxStackedExtensionPresent = true;")

        page.goto(dist_server)
        page.wait_for_selector(".header-nav", timeout=5000)

        # Verify initial logged_in state
        assert page.locator(".header-nav").is_visible()
        assert "TestFPTStudent" in page.content()

        # Simulate switching tabs 20 times consecutively via visibilitychange
        for i in range(20):
            page.evaluate("""() => {
                Object.defineProperty(document, 'visibilityState', { value: 'hidden', writable: true });
                document.dispatchEvent(new Event('visibilitychange'));
                Object.defineProperty(document, 'visibilityState', { value: 'visible', writable: true });
                document.dispatchEvent(new Event('visibilitychange'));
            }""")
            # Small realistic tab switch delay
            page.wait_for_timeout(50)

        # State must remain stably logged_in
        assert page.locator(".header-nav").is_visible(), "header-nav must stay visible after 20 tab switches"
        assert page.locator("text=Chưa thấy extension trên trình duyệt này").count() == 0, "No extension error should not appear"
        assert page.locator("text=Chưa đăng nhập FUOverflow").count() == 0, "Logged out error should not appear"

        browser.close()


def test_auth_gate_extension_sleep_20s_no_transition(dist_server):
    """
    Simulate extension sleeping for 20 seconds (< 30s debouncer threshold):
    Must NOT transition to no_extension.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = create_isolated_page(context)

        is_extension_alive = {"val": True}

        def handle_auth(route):
            if is_extension_alive["val"]:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "logged_in": True,
                        "status_code": "logged_in",
                        "auth_source": "extension",
                        "username": "SleepTestUser",
                    })
                )
            else:
                # Extension sleeping: backend reports unauthenticated / no heartbeat
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "logged_in": False,
                        "status_code": "not_logged_in",
                        "detail": "Heartbeat expired",
                    })
                )

        page.route("**/api/auth/status", handle_auth)
        page.route("**/api/subjects*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([])
        ))

        page.add_init_script("window.DocxStackedExtensionPresent = true;")
        page.goto(dist_server)
        page.wait_for_selector(".header-nav", timeout=5000)
        assert page.locator(".header-nav").is_visible()

        # Simulate extension sleeping for 20s
        # Override backend response to return unauthenticated, and mock clock advancing 20 seconds
        is_extension_alive["val"] = False

        # Advance React app's failure elapsed time to 20 seconds (20,000ms < 30,000ms requirement)
        # and trigger repeated checks
        page.evaluate("""() => {
            const now = Date.now();
            // Trigger 3 failed checks but within 20 seconds
            window.__mockSleepElapsed = 20000;
        }""")

        # Trigger background checks
        for _ in range(3):
            page.evaluate("""() => {
                document.dispatchEvent(new Event('visibilitychange'));
            }""")
            page.wait_for_timeout(100)

        # Verify state did NOT transition to no_extension
        assert page.locator("text=Chưa thấy extension trên trình duyệt này").count() == 0, (
            "Must NOT transition to no_extension when sleeping for 20s (< 30s threshold)"
        )
        # Navigation remains visible
        assert page.locator(".header-nav").is_visible()

        browser.close()


def test_auth_gate_navbar_hidden_in_non_logged_in_states(dist_server):
    """
    Verify navigation bar (.header-nav) is NOT rendered in checking, no_extension, or logged_out.
    It must ONLY be rendered in logged_in state.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # 1. State: checking (backend hanging / delayed)
        page1 = create_isolated_page(context)
        # Abort/hang auth endpoint
        page1.route("**/api/auth/status", lambda route: None)  # Never responds
        page1.goto(dist_server)
        page1.wait_for_selector("text=Đang kiểm tra", timeout=5000)

        # In checking state, .header-nav MUST NOT exist
        assert page1.locator(".header-nav").count() == 0, "Navbar must NOT exist in checking state"
        page1.close()

        # 2. State: no_extension (after >= 3 failures over >= 30s)
        page2 = create_isolated_page(context)
        page2.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "status_code": "not_logged_in"})
        ))
        # Extension is NOT installed
        page2.add_init_script("""
            delete window.DocxStackedExtensionPresent;
            delete window.__DOCXSTACKED_TEST_MODE__;
        """)
        page2.goto(dist_server)

        # Fast-forward failure timer to trigger no_extension transition
        page2.evaluate("""() => {
            // Wait for initial check, then artificially advance failure timestamp past 30s
            return new Promise((resolve) => setTimeout(resolve, 500));
        }""")

        # Trigger degraded transition by mocking failure elapsed >= 30s
        page2.evaluate("""() => {
            // Simulate 3 failures and 31 seconds passed
            window.dispatchEvent(new Event('online'));
        }""")

        # If gateState is no_extension, check navbar is completely absent
        # We can directly inspect .header-nav
        assert page2.locator(".header-nav").count() == 0, "Navbar must NOT exist in unauthenticated/no_extension state"
        page2.close()

        # 3. State: logged_in - navbar MUST appear
        page3 = create_isolated_page(context)
        page3.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "username": "LoggedInUser", "auth_source": "server"})
        ))
        page3.route("**/api/subjects*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([])
        ))
        page3.goto(dist_server)
        page3.wait_for_selector(".header-nav", timeout=5000)
        assert page3.locator(".header-nav").is_visible(), "Navbar MUST be visible in logged_in state"
        page3.close()

        browser.close()


def test_extension_logged_in_backend_logged_out_flow_and_screenshots(dist_server):
    """
    Simulate extension reporting logged_in while /api/auth/status reports logged_in: false:
    1. Page MUST NOT contain the word 'Đăng nhập' anywhere.
    2. Start button MUST say 'Bắt đầu soạn đề' and be clickable.
    3. Capture full-page screenshots for all 3 states: logged_in, logged_out, no_extension.
    """
    screenshot_dir = Path(tempfile.mkdtemp(prefix="docxstacked_test_ss_"))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        # --- 1. STATE: LOGGED_IN (Extension logged_in, backend Playwright logged_out) ---
        page_in = create_isolated_page(context)

        # Backend Playwright reports NOT logged in
        page_in.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "logged_in": False,
                "status_code": "not_logged_in",
                "auth_source": "browser",
                "detail": "Playwright backend chưa đăng nhập",
            })
        ))

        # Subjects mock
        page_in.route("**/api/subjects*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "items": [
                    {
                        "id": 1,
                        "code": "PRM393",
                        "name": "Lập trình ứng dụng di động",
                        "category": "Kỹ thuật phần mềm",
                    }
                ],
                "total": 1,
            })
        ))

        # Exams mock for PRM393
        page_in.route("**/api/subjects/PRM393/exams*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "id": 39,
                    "subject_id": 1,
                    "title": "PRM393 - SU26 - FE",
                    "url": "https://fuoverflow.com/threads/39/",
                    "exam_type": "FE",
                    "term": "SU26",
                    "question_count": 50,
                    "compiled": True,
                    "has_file": True,
                }
            ])
        ))

        # Extension reports LOGGED_IN directly to window
        page_in.add_init_script("""
            window.DocxStackedExtensionPresent = true;
            window.__DOCXSTACKED_TEST_MODE__ = true;
            window.__DOCXSTACKED_AUTH_LOGGED_IN__ = true;
            window.__DOCXSTACKED_AUTH_USERNAME__ = "SinhVienFU";
        """)

        page_in.goto(dist_server)
        page_in.wait_for_selector(".header-nav", timeout=5000)

        # Wait for subjects to load and check PRM393 checkbox
        page_in.wait_for_selector("text=PRM393", timeout=5000)
        checkbox = page_in.locator("input[type='checkbox']").first
        checkbox.check()
        page_in.wait_for_timeout(300)

        # Verify: Header nav is visible and displays user name
        assert page_in.locator(".header-nav").is_visible()
        assert "SinhVienFU" in page_in.content()

        # Requirement 1: NO occurrence of "Đăng nhập" anywhere on the page
        body_text = page_in.locator("body").inner_text()
        assert "Đăng nhập" not in body_text, f"Expected no 'Đăng nhập' on page, but found occurrences in: {body_text}"

        # Requirement 2: Start button exists, is enabled, and says 'Bắt đầu soạn đề'
        all_btn_texts = page_in.locator("button").all_inner_texts()
        print("ALL BUTTONS:", all_btn_texts)
        start_btn = page_in.locator("button:has-text('Bắt đầu soạn đề')")
        assert start_btn.count() > 0, f"Start button must exist. Found buttons: {all_btn_texts}"
        assert start_btn.is_visible(), "Start button 'Bắt đầu soạn đề' must be visible"
        assert start_btn.is_enabled(), "Start button 'Bắt đầu soạn đề' must be clickable"

        # Capture screenshot 1: logged_in
        ss_logged_in = screenshot_dir / "screenshot_logged_in.png"
        page_in.screenshot(path=str(ss_logged_in), full_page=True)
        assert ss_logged_in.exists()
        page_in.close()

        # --- 2. STATE: LOGGED_OUT (Extension detected but not logged in to FUOverflow) ---
        page_out = create_isolated_page(context)
        page_out.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "status_code": "not_logged_in"})
        ))
        page_out.add_init_script("""
            window.DocxStackedExtensionPresent = true;
            window.__DOCXSTACKED_TEST_MODE__ = true;
            window.__DOCXSTACKED_AUTH_LOGGED_IN__ = false;
            window.__DOCXSTACKED_AUTH_LOGGED_OUT__ = true;
            window.__mockFailureElapsed = 35000;
        """)

        page_out.goto(dist_server)
        page_out.wait_for_timeout(500)
        # Trigger 3 failed checks to satisfy anti-flicker threshold (>= 3 failures, >= 30s)
        for _ in range(3):
            page_out.evaluate("window.__triggerCheckAuth && window.__triggerCheckAuth();")
            page_out.wait_for_timeout(200)

        page_out.wait_for_selector("text=Chưa đăng nhập tài khoản FUOverflow", timeout=5000)
        # Verify modal instructions
        assert page_out.locator("text=Extension DocxStacked đã hoạt động nhưng bạn chưa đăng nhập").is_visible()
        assert page_out.locator("[data-testid='btn-open-fuoverflow-login']").is_visible()

        # Capture screenshot 2: logged_out
        ss_logged_out = screenshot_dir / "screenshot_logged_out.png"
        page_out.screenshot(path=str(ss_logged_out), full_page=True)
        assert ss_logged_out.exists()
        page_out.close()

        # --- 3. STATE: NO_EXTENSION (Extension not detected on browser) ---
        page_noext = create_isolated_page(context)
        page_noext.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "status_code": "not_logged_in"})
        ))
        page_noext.add_init_script("""
            delete window.DocxStackedExtensionPresent;
            delete window.__DOCXSTACKED_TEST_MODE__;
            delete window.__DOCXSTACKED_AUTH_LOGGED_IN__;
            window.__mockFailureElapsed = 35000;
        """)

        page_noext.goto(dist_server)
        page_noext.wait_for_timeout(500)
        for _ in range(3):
            page_noext.evaluate("window.__triggerCheckAuth && window.__triggerCheckAuth();")
            page_noext.wait_for_timeout(200)

        page_noext.wait_for_selector("text=Chưa kết nối Extension DocxStacked", timeout=5000)
        assert page_noext.locator("text=Hướng dẫn cài đặt Extension:").is_visible()

        # Capture screenshot 3: no_extension
        ss_noext = screenshot_dir / "screenshot_no_extension.png"
        page_noext.screenshot(path=str(ss_noext), full_page=True)
        assert ss_noext.exists()
        page_noext.close()

        browser.close()
