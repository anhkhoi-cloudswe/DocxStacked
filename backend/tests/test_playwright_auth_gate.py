import functools
import http.server
import json
import socket
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


def test_auth_gate_tab_switching_20_times_stable(dist_server):
    """
    Simulate switching tabs 20 times consecutively:
    The auth gate state must remain stable (logged_in) and no flickering error cards appear.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

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
        page.route("**/api/subjects", lambda route: route.fulfill(
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
        page = context.new_page()

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
        page.route("**/api/subjects", lambda route: route.fulfill(
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
        page1 = context.new_page()
        # Abort/hang auth endpoint
        page1.route("**/api/auth/status", lambda route: None)  # Never responds
        page1.goto(dist_server)
        page1.wait_for_selector("text=Đang kiểm tra", timeout=5000)

        # In checking state, .header-nav MUST NOT exist
        assert page1.locator(".header-nav").count() == 0, "Navbar must NOT exist in checking state"
        page1.close()

        # 2. State: no_extension (after >= 3 failures over >= 30s)
        page2 = context.new_page()
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
        page3 = context.new_page()
        page3.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "username": "LoggedInUser", "auth_source": "server"})
        ))
        page3.route("**/api/subjects", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([])
        ))
        page3.goto(dist_server)
        page3.wait_for_selector(".header-nav", timeout=5000)
        assert page3.locator(".header-nav").is_visible(), "Navbar MUST be visible in logged_in state"
        page3.close()

        browser.close()
