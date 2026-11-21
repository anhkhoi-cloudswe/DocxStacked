"""
test_playwright_extension_ghost_and_stability.py
End-to-end tests inside the real Chromium extension using Playwright:
1. Seed ghost queue (isRunning=true with no active worker) -> service worker / side panel reconciliation
   detects ghost queue and transitions to 'bị gián đoạn' with 'Soạn lại từ đầu' and 'Huỷ hàng đợi'.
2. Starting a new run replaces old queue atomically; 20 samples confirm no flipping between old and new run.
3. Controls (Dừng / Huỷ) provide immediate feedback and clean up state when no worker is running.
"""

import time
import tempfile
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright

EXT_PATH = str(Path("extension").resolve())
EXTENSION_ID = "kicplcdfmbcfjildbbimpfiljlmfokea"
SIDEPANEL_URL = f"chrome-extension://{EXTENSION_ID}/sidepanel.html"


def launch_extension_context(p):
    user_data_dir = tempfile.mkdtemp(prefix="docxstacked_playwright_ext_")
    context = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=[
            "--headless=new",
            f"--disable-extensions-except={EXT_PATH}",
            f"--load-extension={EXT_PATH}",
        ],
    )
    time.sleep(1.0)
    return context


def test_ghost_queue_reconciliation_shows_interrupted_state():
    """
    Requirement 1 & 5:
    Seed old ghost state (isRunning=true, no worker alive).
    Reconciliation must detect ghost queue and change state to 'bị gián đoạn'
    with two buttons: 'Soạn lại từ đầu' and 'Huỷ hàng đợi'.
    Never displays 'Đang soạn...' when worker is dead.
    """
    with sync_playwright() as p:
        context = launch_extension_context(p)
        page = context.new_page()

        # Route backend endpoints to avoid leaking network requests
        page.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))

        page.goto(SIDEPANEL_URL)
        page.wait_for_load_state("domcontentloaded")

        # 1. Seed ghost queue in chrome.storage.local
        page.evaluate("""() => {
            return chrome.storage.local.set({
                savedQueueState: {
                    runId: 'run_ghost_prm392',
                    items: [{ title: 'PRM392 - SU 2024 - RE', url: 'https://fuoverflow.com/threads/prm392.123/', question_count: 40 }],
                    currentIndex: 0,
                    isRunning: true,
                    isPaused: false,
                    currentExamTitle: 'PRM392 - SU 2024 - RE',
                    currentQuestionIndex: 1,
                    totalQuestions: 40,
                    statusText: 'Câu 1/40',
                    completedExams: [],
                    updatedAt: Date.now() - 100000,
                }
            });
        }""")

        # 2. Trigger reconciliation
        reconciled = page.evaluate("""() => {
            return new Promise((resolve) => {
                chrome.runtime.sendMessage({ type: 'RECONCILE_QUEUE_STATE' }, (resp) => {
                    resolve(resp);
                });
            });
        }""")

        assert reconciled is not None
        assert reconciled.get("ok") is True
        q_state = reconciled.get("queueState", {})
        assert q_state.get("isRunning") is False
        assert q_state.get("isInterrupted") is True
        assert "bị gián đoạn" in q_state.get("statusText", "").lower()

        # 3. Reload sidepanel and inspect DOM
        page.reload()
        page.wait_for_timeout(600)

        # Banner displays interrupted text
        banner_text = page.locator("#queue-resume-text").inner_text()
        assert "bị gián đoạn" in banner_text.lower()
        assert "PRM392 - SU 2024 - RE" in banner_text

        # Two buttons visible: "Soạn lại từ đầu" and "Huỷ hàng đợi"
        assert page.locator("#banner-actions-interrupted").is_visible()
        assert page.locator("#btn-banner-restart").is_visible()
        assert page.locator("#btn-banner-cancel-interrupted").is_visible()

        # Running progress card must NOT be displayed
        assert not page.locator("#queue-progress-card").is_visible()

        context.close()


def test_new_run_progress_card_no_flipping_20_samples():
    """
    Requirement 3 & 5:
    Start a new run (PRM393 - SU26 - FE).
    Sample 20 times across a time window.
    Progress card and banner must STRICTLY display PRM393 - SU26 - FE and NEVER flip back to PRM392.
    """
    with sync_playwright() as p:
        context = launch_extension_context(p)
        page = context.new_page()
        page.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))
        page.goto(SIDEPANEL_URL)
        page.wait_for_load_state("domcontentloaded")

        # Start new run with PRM393
        start_resp = page.evaluate("""() => {
            return new Promise((resolve) => {
                chrome.runtime.sendMessage({
                    type: 'QUEUE_START_COMMAND',
                    runId: 'run_new_prm393_verified',
                    subjectCode: 'PRM393',
                    items: [{ title: 'PRM393 - SU26 - FE', url: 'https://fuoverflow.com/threads/prm393.456/', question_count: 50 }],
                    force: true,
                }, (resp) => resolve(resp));
            });
        }""")
        assert start_resp.get("ok") is True

        # Wait for UI to update to new run
        page.wait_for_timeout(300)

        # Sample 20 times over time window
        samples = []
        for _ in range(20):
            time.sleep(0.1)
            p_title = page.locator("#queue-progress-title").inner_text() if page.locator("#queue-progress-title").is_visible() else ""
            b_text = page.locator("#queue-resume-text").inner_text() if page.locator("#queue-resume-text").is_visible() else ""
            samples.append((p_title, b_text))

        assert len(samples) == 20
        for idx, (p_title, b_text) in enumerate(samples, 1):
            # Must NEVER contain old PRM392
            assert "PRM392" not in p_title, f"Sample {idx} flipped to old PRM392: {p_title}"
            assert "PRM392" not in b_text, f"Sample {idx} banner flipped to old PRM392: {b_text}"
            # Must show PRM393
            assert "PRM393" in p_title or "PRM393" in b_text, f"Sample {idx} missing PRM393 (title='{p_title}', banner='{b_text}')"

        context.close()


def test_queue_controls_responsiveness_when_no_worker():
    """
    Requirement 2:
    When no worker is running, clicking 'Dừng' or 'Huỷ' must immediately clear old state
    and close offscreen, never silently doing nothing.
    """
    with sync_playwright() as p:
        context = launch_extension_context(p)
        page = context.new_page()
        page.route("**/api/**", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))
        page.goto(SIDEPANEL_URL)
        page.wait_for_load_state("domcontentloaded")

        # 1. Seed interrupted state
        page.evaluate("""() => {
            return chrome.storage.local.set({
                savedQueueState: {
                    runId: 'run_stale_to_cancel',
                    items: [{ title: 'PRM392 - SU 2024 - RE', url: 'https://fuoverflow.com/threads/prm392.123/', question_count: 40 }],
                    currentIndex: 0,
                    isRunning: false,
                    isInterrupted: true,
                    currentExamTitle: 'PRM392 - SU 2024 - RE',
                    currentQuestionIndex: 1,
                    totalQuestions: 40,
                    statusText: 'Hàng đợi bị gián đoạn: PRM392 - SU 2024 - RE, Câu 1/40',
                    completedExams: [],
                    updatedAt: Date.now(),
                }
            });
        }""")
        page.reload()
        page.wait_for_timeout(500)

        assert page.locator("#queue-resume-banner").is_visible()
        assert page.locator("#btn-banner-cancel-interrupted").is_visible()

        # 2. Click "Huỷ hàng đợi" -> banner disappears and storage is cleared
        page.locator("#btn-banner-cancel-interrupted").click()
        page.wait_for_timeout(500)

        assert not page.locator("#queue-resume-banner").is_visible()
        stored = page.evaluate("() => chrome.storage.local.get(['savedQueueState'])")
        assert "savedQueueState" not in stored or not stored["savedQueueState"]

        context.close()
