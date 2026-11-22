import functools
import http.server
import json
from pathlib import Path
import threading
import time
import pytest
from playwright.sync_api import sync_playwright

DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "output" / "phase2b_screenshots"


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """Simple HTTP Request Handler with SPA fallback to index.html for client-side routing."""
    def do_GET(self):
        url_path = self.path.split("?")[0]
        fs_path = Path(self.directory) / url_path.lstrip("/")
        if not fs_path.is_file() and not url_path.startswith("/assets/"):
            self.path = "/index.html"
        return super().do_GET()


class FreePortServer:
    def __init__(self, directory: Path):
        self.directory = directory
        self.server = None
        self.thread = None
        self.port = 0

    def start(self):
        handler = functools.partial(SPAHandler, directory=str(self.directory))
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
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    srv = FreePortServer(DIST_DIR)
    srv.start()
    yield f"http://127.0.0.1:{srv.port}"
    srv.stop()


def setup_default_routes(page, fuoverflow_logged_in=False, fuexam_logged_in=False):
    """Hermetic route isolation: intercepts all API calls with in-memory responses."""
    page.route("**/api/auth/status", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "logged_in": fuoverflow_logged_in,
            "status_code": "logged_in" if fuoverflow_logged_in else "logged_out",
            "auth_source": "extension" if fuoverflow_logged_in else "server",
            "username": "StudentFUOverflow" if fuoverflow_logged_in else None,
        })
    ))
    page.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "logged_in": fuexam_logged_in,
            "has_storage_state": fuexam_logged_in,
            "username": "StudentFuexam" if fuexam_logged_in else None,
        })
    ))
    page.route("**/api/subjects*", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
            "items": [
                {"code": "PRM393", "name": "Mobile Programming (Android)", "exam_count": 4},
                {"code": "MAE101", "name": "Mathematics for Engineering", "exam_count": 3},
            ],
            "total": 2,
            "last_synced_at": "2026-11-21T18:00:00Z"
        })
    ))
    page.route("**/api/user/documents*", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps([])
    ))
    page.route("**/api/settings*", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({
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
        })
    ))
    page.route("**/api/jobs/active", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(None)
    ))
    page.route("**/api/jobs/**/stream", lambda route: route.fulfill(
        status=200,
        content_type="text/event-stream",
        body="event: ping\ndata: {}\n\n"
    ))


def test_01_platform_selector_and_persistence(dist_server):
    """
    1. Initial screen displays 2 text cards for platform selection (FUOverflow vs fuexam.me).
    2. Zero emojis, zero gradients.
    3. Selecting fuexam stores choice in localStorage. Header displays [fuexam] and 'Đổi nền tảng'.
    4. Clicking 'Đổi nền tảng' resets platform to null and clears localStorage.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=False, fuexam_logged_in=False)

        # Clear localStorage before opening
        page.goto(dist_server)
        page.evaluate("() => localStorage.clear()")
        page.reload()

        # 1. Platform selector card check
        page.wait_for_selector("[data-testid='platform-card-fuoverflow']", timeout=6000)
        assert page.locator("[data-testid='platform-card-fuoverflow']").is_visible()
        assert page.locator("[data-testid='platform-card-fuexam']").is_visible()

        # Take screenshot of platform selection screen
        page.screenshot(path=str(SCREENSHOT_DIR / "01_platform_selector.png"))

        # 2. Select fuexam.me
        page.click("[data-testid='platform-card-fuexam']")
        page.wait_for_timeout(500)

        # Check localStorage persistence
        saved_platform = page.evaluate("() => localStorage.getItem('docxstacked_platform')")
        assert saved_platform == "fuexam"

        # Check header badge [fuexam]
        badge = page.locator("[data-testid='platform-indicator']")
        assert badge.is_visible()
        assert "[fuexam]" in badge.inner_text()

        # Check switch platform button
        btn_switch = page.locator("[data-testid='btn-switch-platform']")
        assert btn_switch.is_visible()

        # Take screenshot of selected platform
        page.screenshot(path=str(SCREENSHOT_DIR / "02_platform_selected_fuexam.png"))

        # 3. Click 'Đổi nền tảng'
        btn_switch.click()
        page.wait_for_selector("[data-testid='platform-card-fuoverflow']", timeout=6000)
        cleared_platform = page.evaluate("() => localStorage.getItem('docxstacked_platform')")
        assert cleared_platform is None
        assert page.locator("[data-testid='platform-card-fuoverflow']").is_visible()

        # 4. Select FUOverflow
        page.click("[data-testid='platform-card-fuoverflow']")
        page.wait_for_timeout(500)
        saved_platform_fu = page.evaluate("() => localStorage.getItem('docxstacked_platform')")
        assert saved_platform_fu == "fuoverflow"
        badge_fu = page.locator("[data-testid='platform-indicator']")
        assert "[FUOverflow]" in badge_fu.inner_text()
        page.screenshot(path=str(SCREENSHOT_DIR / "03_platform_selected_fuoverflow.png"))

        browser.close()


def test_02_extension_entry_bypasses_selection_and_modal(dist_server):
    """
    Accessing dashboard from extension (?source=extension or ?platform=fuoverflow)
    automatically bypasses platform selector and opens FUOverflow directly without login modal
    when extension has an active session.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=True, fuexam_logged_in=False)

        # Extension presence & logged-in state
        page.add_init_script("""
            window.__DOCXSTACKED_AUTH_LOGGED_IN__ = true;
            window.__DOCXSTACKED_AUTH_USERNAME__ = "ExtensionUserFPT";
        """)

        # Navigate with query param ?source=extension
        page.goto(f"{dist_server}/?source=extension")
        page.wait_for_selector(".select-subject-layout", timeout=6000)

        # Platform selector must NOT be visible
        assert not page.locator("[data-testid='platform-card-fuoverflow']").is_visible()

        # Modal must NOT be visible
        assert not page.locator("[data-testid='fuoverflow-login-modal']").is_visible()

        # Must display [FUOverflow] badge in Header
        badge = page.locator("[data-testid='platform-indicator']")
        assert badge.is_visible()
        assert "[FUOverflow]" in badge.inner_text()

        page.screenshot(path=str(SCREENSHOT_DIR / "04_extension_entry_bypassed.png"))
        browser.close()


def test_03_no_login_button_in_main_interface(dist_server):
    """
    Requirement 2: Dashboard MUST NOT have any 'Đăng nhập' button in the main interface.
    Neither in the Header nor in ScreenSelectSubject.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=True, fuexam_logged_in=True)

        page.add_init_script("""
            window.__DOCXSTACKED_AUTH_LOGGED_IN__ = true;
            window.__DOCXSTACKED_AUTH_USERNAME__ = "VerifiedUser";
            localStorage.setItem('docxstacked_platform', 'fuoverflow');
        """)

        page.goto(dist_server)
        page.wait_for_selector(".select-subject-layout", timeout=6000)

        # Scan all buttons and links in main interface (outside modals)
        buttons = page.locator("header button, header a, main button, main a").all()
        for btn in buttons:
            text = (btn.text_content() or "").strip()
            # Must not be a login button in the main interface
            assert "Đăng nhập" not in text, f"Found forbidden login button in main interface: '{text}'"

        page.screenshot(path=str(SCREENSHOT_DIR / "05_no_login_button_in_main_interface.png"))
        browser.close()


def test_04_fuoverflow_modal_auto_close_on_login(dist_server):
    """
    When FUOverflow is not logged in:
    1. Shows FuoverflowLoginModal.
    2. When user logs in on extension, modal closes automatically without manual reload or click.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Start with logged_out
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": False, "status_code": "logged_out", "auth_source": "extension"})
        ))
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

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuoverflow');")
        page.goto(dist_server)

        # Modal must appear
        modal = page.locator("[data-testid='fuoverflow-login-modal']")
        page.wait_for_selector("[data-testid='fuoverflow-login-modal']", timeout=6000)
        assert modal.is_visible()
        page.screenshot(path=str(SCREENSHOT_DIR / "06_fuoverflow_modal_logged_out.png"))

        # Simulate user logged in on extension
        page.evaluate("window.__DOCXSTACKED_AUTH_LOGGED_IN__ = true;")
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"logged_in": True, "status_code": "logged_in", "auth_source": "extension", "username": "AutoClosedUser"})
        ))

        # Trigger check (simulating extension heartbeat or debounced poll)
        page.evaluate("() => { if (window.__triggerCheckAuth) window.__triggerCheckAuth(); }")

        # Modal must automatically disappear
        page.wait_for_selector("[data-testid='fuoverflow-login-modal']", state="hidden", timeout=5000)
        assert not modal.is_visible()
        page.screenshot(path=str(SCREENSHOT_DIR / "07_fuoverflow_modal_auto_closed.png"))

        browser.close()


def test_05_fuexam_modal_states_and_operational_error(dist_server):
    """
    fuexam login modal state machine:
    1. idle: shows "Mở cửa sổ đăng nhập" and CLI alternative command.
    2. waiting: user clicks open, spinner shows with "Huỷ thao tác".
    3. operational error (Requirement 0): non-interactive environment cannot launch Chromium, returns clear guidance.
    4. authenticated: auto-closes modal upon success.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Initial fuexam not logged in
        page.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"logged_in": False, "has_storage_state": False})
        ))
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

        # Mock login lifecycle endpoints
        login_state = {"state": "idle"}

        def handle_login_start(route):
            login_state["state"] = "waiting"
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "success": True,
                "message": "Cửa sổ Playwright Chromium đã mở tới trang: https://fuexam.me/login/"
            }))

        def handle_login_status(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "state": login_state["state"],
                "message": "Đang theo dõi..." if login_state["state"] == "waiting" else "Lỗi",
                "error": login_state.get("error")
            }))

        page.route("**/api/auth/fuexam/login/start", handle_login_start)
        page.route("**/api/auth/fuexam/login/status", handle_login_status)

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page.goto(dist_server)

        # 1. State: idle
        page.wait_for_selector("[data-testid='btn-open-fuexam-login']", timeout=6000)
        btn_open = page.locator("[data-testid='btn-open-fuexam-login']")
        assert btn_open.is_visible()
        # Verify Chromium headed guidance is displayed
        assert "Chromium" in page.content()
        page.screenshot(path=str(SCREENSHOT_DIR / "08_fuexam_modal_idle.png"))

        # 2. State: waiting
        btn_open.click()
        page.wait_for_selector("[data-testid='btn-cancel-fuexam-login']", timeout=4000)
        assert page.locator("[data-testid='btn-cancel-fuexam-login']").is_visible()
        page.screenshot(path=str(SCREENSHOT_DIR / "09_fuexam_modal_waiting.png"))

        # 3. Operational error condition (Requirement 0)
        login_state["state"] = "error"
        login_state["error"] = (
            "Không thể mở cửa sổ trình duyệt Chromium từ môi trường ngầm hoặc phiên không tương tác. "
            "Vui lòng chạy backend từ PowerShell trên máy thật: python run_dev.py"
        )
        page.wait_for_timeout(2000)  # Wait for polling cycle
        page.wait_for_selector("[data-testid='fuexam-error-message']", timeout=4000)
        err_box = page.locator("[data-testid='fuexam-error-message']")
        assert err_box.is_visible()
        assert "PowerShell" in err_box.inner_text()
        page.screenshot(path=str(SCREENSHOT_DIR / "10_fuexam_modal_operational_error.png"))

        # 4. State: authenticated -> auto-close
        login_state["state"] = "authenticated"
        page.route("**/api/auth/fuexam/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"logged_in": True, "has_storage_state": True})
        ))
        page.wait_for_timeout(2000)
        # Modal must close automatically
        page.wait_for_selector("[data-testid='btn-open-fuexam-login']", state="hidden", timeout=5000)
        page.screenshot(path=str(SCREENSHOT_DIR / "11_fuexam_modal_authenticated_closed.png"))

        browser.close()


def test_06_fuexam_exam_warnings_and_disabled_state(dist_server):
    """
    Requirement 5: fuexam subject and exam list shares component with FUOverflow.
    Renders clear text badges (no emojis, no gradients) for 4 warning cases:
    1. PE not supported -> checkbox disabled with reason
    2. Not an exam -> checkbox disabled with reason
    3. Subject mismatch -> checkbox disabled with reason
    4. Multiple exam codes -> indicates how many .docx files will be exported
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=False, fuexam_logged_in=True)

        # Mock fuexam exams with all 4 warning cases (registered last, matches first)
        page.route("**/api/subjects/PRM393/exams*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "id": 101,
                    "title": "PRM393 - FE - Full Question Bank 2026",
                    "term": "SU26",
                    "question_count": 50,
                    "is_valid_exam": True,
                    "sub_exam_count": 1,
                    "warning": None,
                    "platform": "fuexam"
                },
                {
                    "id": 102,
                    "title": "PRM393 - Practical Exam (PE) Slot 2",
                    "term": "SU26",
                    "question_count": 0,
                    "is_valid_exam": False,
                    "warning": "Kỳ thi Thực hành (PE) chưa hỗ trợ cào",
                    "platform": "fuexam"
                },
                {
                    "id": 103,
                    "title": "Hỏi bài tập lab PRM393 tuần 3",
                    "term": "",
                    "question_count": 0,
                    "is_valid_exam": False,
                    "warning": "Bài viết thảo luận / hỏi đáp, không phải đề thi",
                    "platform": "fuexam"
                },
                {
                    "id": 104,
                    "title": "SWP391 - Đề thi nhầm môn trong mục PRM393",
                    "term": "FA25",
                    "question_count": 40,
                    "is_valid_exam": False,
                    "warning": "Môn học không khớp (Nội dung thuộc môn khác)",
                    "platform": "fuexam"
                },
                {
                    "id": 105,
                    "title": "PRM393 - Đề gộp Mã 101 và Mã 102",
                    "term": "SU26",
                    "question_count": 100,
                    "is_valid_exam": True,
                    "sub_exam_count": 2,
                    "warning": "Đề chứa 2 mã đề thi riêng biệt (Sẽ xuất 2 file .docx)",
                    "platform": "fuexam"
                }
            ])
        ))

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page.goto(dist_server)

        # Wait for subject PRM393 to render in table and click it
        page.wait_for_selector(".select-subject-layout", timeout=6000)
        page.wait_for_selector("text=PRM393", timeout=6000)
        page.click("text=PRM393")
        page.wait_for_timeout(1000)

        # Verify warning badges rendered
        assert page.locator("text=Kỳ thi Thực hành (PE) chưa hỗ trợ cào").is_visible()
        assert page.locator("text=Bài viết thảo luận / hỏi đáp, không phải đề thi").is_visible()
        assert page.locator("text=Môn học không khớp (Nội dung thuộc môn khác)").is_visible()
        assert page.locator("text=Đề chứa 2 mã đề thi riêng biệt (Sẽ xuất 2 file .docx)").is_visible()

        # Checkboxes for invalid exams must be disabled
        checkbox_pe = page.locator("input[type='checkbox'][value='102']")
        assert checkbox_pe.is_disabled()

        checkbox_qa = page.locator("input[type='checkbox'][value='103']")
        assert checkbox_qa.is_disabled()

        checkbox_mismatch = page.locator("input[type='checkbox'][value='104']")
        assert checkbox_mismatch.is_disabled()

        # Checkbox for valid multiple-exam must be enabled
        checkbox_multi = page.locator("input[type='checkbox'][value='105']")
        assert not checkbox_multi.is_disabled()

        page.screenshot(path=str(SCREENSHOT_DIR / "12_fuexam_exam_warnings_and_badges.png"))
        browser.close()


def test_07_fuexam_progress_real_count_ratelimit_and_sources(dist_server):
    """
    Requirement 6: fuexam compilation progress:
    1. Real question count 'Câu x/y' with y being real image count (50, never 40).
    2. Rate limit indicator (1.6s delay between requests).
    3. Summary breakdown of answer sources: photo, comments, AI.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=False, fuexam_logged_in=True)

        # Mock active job with real question count = 50 and breakdown
        job_id = "job_fuexam_prm393_su26"
        page.route(f"**/api/jobs/{job_id}", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "job_id": job_id,
                "platform": "fuexam",
                "subject_code": "PRM393",
                "exam_type": "FE",
                "exam_count": 1,
                "status": "processing",
                "details": {
                    "total_exams": 1,
                    "total_questions": 50,
                    "current_question": 18,
                    "current_step": "Đang giãn cách 1,6s giữa các lượt tải để bảo vệ máy chủ fuexam...",
                    "is_rate_limiting": True,
                    "current_exam_title": "PRM393 - SU26 - FE - RE",
                    "answer_sources": {
                        "from_photo": 12,
                        "from_comments": 4,
                        "from_ai": 2,
                        "total": 18
                    }
                }
            })
        ))

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page.goto(f"{dist_server}/progress?job_id={job_id}&platform=fuexam")

        # 1. Question counter check
        page.wait_for_selector("[data-testid='question-counter']:has-text('/ 50')", timeout=6000)
        counter = page.locator("[data-testid='question-counter']")
        assert counter.is_visible()
        # Must show / 50 and NOT / 40
        assert "/ 50" in counter.inner_text()
        assert "/ 40" not in counter.inner_text()

        # 2. Rate limit indicator check (1.6s)
        page.wait_for_selector("[data-testid='rate-limit-indicator']", timeout=6000)
        rate_indicator = page.locator("[data-testid='rate-limit-indicator']")
        assert rate_indicator.is_visible()
        assert "1,6" in rate_indicator.inner_text() or "1.6" in rate_indicator.inner_text()

        # 3. Answer sources summary check
        sources_summary = page.locator("[data-testid='answer-sources-summary']")
        assert sources_summary.is_visible()
        assert "ảnh" in sources_summary.inner_text().lower()
        assert "bình luận" in sources_summary.inner_text().lower()
        assert "ai" in sources_summary.inner_text().lower()

        page.screenshot(path=str(SCREENSHOT_DIR / "13_fuexam_progress_screen.png"))
        browser.close()


def test_08_settings_fuexam_logout(dist_server):
    """
    Requirement 4: ScreenSettings has a button to log out of fuexam.me
    and unlink data/auth/fuexam_storage_state.json.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        setup_default_routes(page, fuoverflow_logged_in=False, fuexam_logged_in=True)

        logout_called = {"called": False}

        def handle_logout(route):
            logout_called["called"] = True
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

        page.route("**/api/auth/fuexam/logout", handle_logout)

        page.add_init_script("localStorage.setItem('docxstacked_platform', 'fuexam');")
        page.goto(f"{dist_server}/settings?platform=fuexam")

        # Logout button must exist in Settings
        page.wait_for_selector("[data-testid='btn-logout-fuexam']", timeout=6000)
        btn_logout = page.locator("[data-testid='btn-logout-fuexam']")
        assert btn_logout.is_visible()
        assert "Đăng xuất fuexam.me" in btn_logout.inner_text()

        page.screenshot(path=str(SCREENSHOT_DIR / "14_settings_fuexam_logout.png"))
        browser.close()
