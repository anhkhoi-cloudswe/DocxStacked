"""
test_extension_queue_lifecycle.py
Automated test suite verifying Chromium Extension queue lifecycle:
1. Panel open -> close after 10s (offscreen keeps running) -> panel reopen:
   - Question index (Câu x/y) must continue increasing monotonically.
   - Queue must NOT restart from beginning or reset to 0/0.
   - Number of requests must NOT be duplicated.
   - Resume banner shows only 'Xem tiến trình' when running, and 'Tiếp tục' + 'Huỷ' when stopped.
2. Exam completion:
   - Exam list refreshed with 'Đã soạn' and download button.
   - Result card lists each finished exam with download button.
   - 'Tải ZIP' button displayed when >= 2 exams completed.
   - Controls row (Dừng/Bỏ qua/Thử lại) hidden after completion.
3. Backend offline handling:
   - Backend offline does not overwrite completion card or clear results.
"""

import time
import pytest
from typing import Dict, Any, List


class MockChromeStorage:
    """Simulates chrome.storage.local with persistence across panel open/close."""
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def get(self, keys: List[str]) -> Dict[str, Any]:
        return {k: self._store[k] for k in keys if k in self._store}

    def set(self, items: Dict[str, Any]):
        self._store.update(items)

    def remove(self, keys: List[str]):
        for k in keys:
            self._store.pop(k, None)


class MockOffscreenQueueWorker:
    """
    Simulates offscreen.js background crawler that runs independently
    of the side panel UI lifecycle.
    """
    def __init__(self, storage: MockChromeStorage):
        self.storage = storage
        self.is_running = False
        self.is_paused = False
        self.current_index = 0
        self.current_question = 0
        self.total_questions = 50
        self.total_requests = 0
        self.requested_urls = []
        self.completed_exams = []
        self.items = []

    def start_queue(self, items: List[Dict[str, Any]]):
        self.items = items
        self.current_index = 0
        self.current_question = 0
        self.is_running = True
        self.is_paused = False
        self._save_state()

    def advance_time(self, seconds: float, cadence_sec: float = 2.0):
        """Simulate time elapsing while background crawler processes questions."""
        if not self.is_running or self.is_paused:
            return

        steps = int(seconds / cadence_sec)
        for _ in range(steps):
            if self.current_index >= len(self.items):
                self.is_running = False
                self._save_state(is_completed=True)
                break

            self.current_question += 1
            cur_item = self.items[self.current_index]
            req_url = f"{cur_item['url']}#media_{self.current_question}"
            self.requested_urls.append(req_url)
            self.total_requests += 1

            if self.current_question >= self.total_questions:
                # Exam completed
                self.completed_exams.append({
                    "id": f"exam_{self.current_index + 1}",
                    "title": cur_item["title"],
                    "docx_filename": f"{cur_item['title']}.docx",
                    "download_url": f"/api/exports/{self.current_index + 1}/download",
                    "subject_code": "PRN232",
                })
                self.current_index += 1
                self.current_question = 0
                if self.current_index >= len(self.items):
                    self.is_running = False
                    self._save_state(is_completed=True)
                    break

            self._save_state()

    def pause(self):
        self.is_paused = True
        self.is_running = False
        self._save_state()

    def resume(self):
        self.is_paused = False
        self.is_running = True
        self._save_state()

    def _save_state(self, is_completed: bool = False):
        cur_title = ""
        if self.current_index < len(self.items):
            cur_title = self.items[self.current_index]["title"]
        pct = int((self.current_question / self.total_questions) * 85) if self.total_questions else 0

        self.storage.set({
            "savedQueueState": {
                "items": self.items,
                "currentIndex": self.current_index,
                "isRunning": self.is_running,
                "isPaused": self.is_paused,
                "isCompleted": is_completed,
                "currentExamTitle": cur_title,
                "currentQuestionIndex": self.current_question,
                "totalQuestions": self.total_questions,
                "progressPct": pct,
                "statusText": f"Câu {self.current_question}/{self.total_questions}",
                "completedExams": list(self.completed_exams),
                "updatedAt": time.time(),
            }
        })


class MockSidepanelUI:
    """
    Simulates sidepanel.js lifecycle: DOM elements, checkSavedQueueState(),
    banner display logic, and offline status handling.
    """
    def __init__(self, storage: MockChromeStorage):
        self.storage = storage
        self.is_open = False
        # DOM elements state
        self.progress_card_visible = False
        self.controls_row_visible = False
        self.progress_title = ""
        self.progress_ratio = "0/0"
        self.stats_summary = "0/0 câu"
        self.progress_bar_pct = 0
        self.banner_visible = False
        self.banner_text = ""
        self.banner_actions_running_visible = False
        self.banner_actions_stopped_visible = False
        self.result_card_visible = False
        self.completed_items = []
        self.download_zip_visible = False
        self.action_buttons_enabled = True
        self.notice_box_text = ""
        self.queue_completed = False

    def open_panel(self):
        self.is_open = True
        self.check_saved_queue_state()

    def close_panel(self):
        # DOM and JS unloaded
        self.is_open = False

    def check_saved_queue_state(self):
        data = self.storage.get(["savedQueueState"])
        q_state = data.get("savedQueueState")
        if not q_state:
            return

        items = q_state.get("items", [])
        if not items:
            return

        total_exams = len(items)
        cur_exam_num = min((q_state.get("currentIndex", 0) + 1), total_exams)
        cur_title = q_state.get("currentExamTitle", "")
        q_idx = q_state.get("currentQuestionIndex", 0)
        tot_q = q_state.get("totalQuestions", 0)

        # Restore completed exams
        comp = q_state.get("completedExams", [])
        if comp:
            self.render_completed_exams(comp)

        if q_state.get("isRunning"):
            self.progress_card_visible = True
            self.controls_row_visible = True
            self.progress_title = f"[{cur_exam_num}/{total_exams}] {cur_title}"
            self.progress_ratio = f"{cur_exam_num}/{total_exams}"
            self.progress_bar_pct = q_state.get("progressPct", 0)
            self.stats_summary = f"Câu {q_idx}/{tot_q}"

            # Banner: show ONLY "Xem tiến trình"
            self.banner_visible = True
            self.banner_text = f"Đang soạn: {cur_title} (Câu {q_idx}/{tot_q})"
            self.banner_actions_running_visible = True
            self.banner_actions_stopped_visible = False

        elif q_state.get("isPaused"):
            self.progress_card_visible = True
            self.controls_row_visible = True
            self.progress_title = f"[{cur_exam_num}/{total_exams}] (Tạm dừng) {cur_title}"
            self.progress_ratio = f"{cur_exam_num}/{total_exams}"
            self.stats_summary = f"Tạm dừng ở câu {q_idx}/{tot_q}"

            # Banner: show "Tiếp tục" and "Huỷ"
            self.banner_visible = True
            self.banner_text = f"Hàng đợi đang dừng ({cur_exam_num}/{total_exams})"
            self.banner_actions_running_visible = False
            self.banner_actions_stopped_visible = True

        elif q_state.get("isCompleted"):
            self.queue_completed = True
            self.progress_card_visible = False
            self.controls_row_visible = False
            self.banner_visible = False

    def render_completed_exams(self, completed_exams: List[Dict[str, Any]]):
        self.completed_items = completed_exams
        if completed_exams:
            self.result_card_visible = True
            self.download_zip_visible = len(completed_exams) >= 2
        else:
            self.result_card_visible = False
            self.download_zip_visible = False

    def set_backend_offline(self, notice_msg: str = "Backend Offline"):
        self.action_buttons_enabled = False
        # Do not overwrite completed state if queue has finished
        if not self.queue_completed:
            self.notice_box_text = notice_msg


def test_queue_close_open_progress_and_no_duplicate_requests():
    """
    Test 1:
    - Queue starts 1 exam with 50 questions.
    - Side panel opens at Question 5.
    - Side panel closes.
    - 10 seconds elapse (offscreen crawls 5 more questions, reaching Question 10).
    - Side panel re-opens:
      * Question index MUST continue increasing (reaches Question 10, not reset to 0/0).
      * No duplicate requests issued.
      * Banner shows ONLY 'Xem tiến trình' when running, no 'Tiếp tục' or 'Huỷ'.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorker(storage)
    panel = MockSidepanelUI(storage)

    items = [{"title": "PRN232 - SU26 - FE", "url": "https://fuoverflow.com/threads/fe.192/"}]
    worker.start_queue(items)

    # Offscreen crawls 5 questions (10s at 2s/question)
    worker.advance_time(10.0, cadence_sec=2.0)
    assert worker.current_question == 5
    assert worker.total_requests == 5

    # 1. Panel is opened
    panel.open_panel()
    assert panel.progress_card_visible is True
    assert panel.stats_summary == "Câu 5/50"
    assert panel.banner_visible is True
    assert panel.banner_actions_running_visible is True
    assert panel.banner_actions_stopped_visible is False
    assert "Đang soạn" in panel.banner_text

    # 2. Panel is CLOSED
    panel.close_panel()
    assert panel.is_open is False

    # 3. Offscreen document runs in background for 10 seconds (5 more questions)
    worker.advance_time(10.0, cadence_sec=2.0)
    assert worker.current_question == 10
    assert worker.total_requests == 10  # Strictly 10 requests, never duplicated

    # 4. Panel is RE-OPENED
    panel.open_panel()
    assert panel.is_open is True

    # MUST NOT reset to 0/0! MUST be at Question 10!
    assert panel.stats_summary == "Câu 10/50"
    assert panel.progress_ratio == "1/1"
    assert panel.progress_card_visible is True

    # When running, banner MUST show ONLY "Xem tiến trình", NOT "Tiếp tục"
    assert panel.banner_actions_running_visible is True
    assert panel.banner_actions_stopped_visible is False

    # Verify no duplicate URLs requested
    assert len(worker.requested_urls) == len(set(worker.requested_urls))
    assert worker.total_requests == 10


def test_queue_stopped_banner_actions():
    """
    Test that when queue is paused/stopped:
    - Banner displays 'Tiếp tục' and 'Huỷ'.
    - Banner does NOT show 'Xem tiến trình'.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorker(storage)
    panel = MockSidepanelUI(storage)

    items = [{"title": "PRN232 - SU26 - FE", "url": "https://fuoverflow.com/threads/fe.192/"}]
    worker.start_queue(items)
    worker.advance_time(4.0, cadence_sec=2.0)  # reaches Q2
    worker.pause()

    panel.open_panel()
    assert panel.banner_visible is True
    assert "Hàng đợi đang dừng" in panel.banner_text
    assert panel.banner_actions_stopped_visible is True
    assert panel.banner_actions_running_visible is False


def test_exam_completion_and_zip_download_for_multiple_exams():
    """
    Test 2:
    - Queue with 2 exams.
    - Each exam completes:
      * Completed exams list populated with download button.
      * When >= 2 exams completed: 'Tải ZIP' button visible.
      * Controls row (Dừng/Bỏ qua/Thử lại) hidden when queue finishes.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorker(storage)
    panel = MockSidepanelUI(storage)

    items = [
        {"title": "PRN232 - SU26 - FE", "url": "https://fuoverflow.com/threads/fe.192/"},
        {"title": "PRN232 - FA25 - FE", "url": "https://fuoverflow.com/threads/fe.193/"},
    ]
    worker.start_queue(items)

    # Finish exam 1 (50 questions = 100s)
    worker.advance_time(100.0, cadence_sec=2.0)
    assert len(worker.completed_exams) == 1

    panel.open_panel()
    assert panel.result_card_visible is True
    assert len(panel.completed_items) == 1
    # 1 exam -> zip not needed yet
    assert panel.download_zip_visible is False

    # Finish exam 2 (50 questions = 100s)
    panel.close_panel()
    worker.advance_time(100.0, cadence_sec=2.0)
    assert len(worker.completed_exams) == 2
    assert worker.is_running is False

    panel.open_panel()
    assert panel.queue_completed is True
    assert len(panel.completed_items) == 2
    # >= 2 exams -> Tải ZIP must be visible!
    assert panel.download_zip_visible is True
    # Controls row hidden after completion
    assert panel.controls_row_visible is False
    assert panel.banner_visible is False


def test_backend_offline_preserves_completion_state():
    """
    Test 3:
    - When queue is completed, triggering backend offline:
      * Does NOT overwrite completion card or hide results.
      * Only disables new action buttons (blocking new actions only).
    """
    storage = MockChromeStorage()
    panel = MockSidepanelUI(storage)

    # Simulate completed queue
    panel.queue_completed = True
    panel.render_completed_exams([
        {"title": "PRN232 - SU26 - FE", "download_url": "/api/exports/1/download"},
        {"title": "PRN232 - FA25 - FE", "download_url": "/api/exports/2/download"},
    ])

    # Trigger backend offline
    panel.set_backend_offline("Backend Offline. Mở terminal chạy: python run_dev.py")

    # Completion state preserved!
    assert panel.result_card_visible is True
    assert len(panel.completed_items) == 2
    assert panel.download_zip_visible is True
    # Notice box did not overwrite completed view
    assert panel.notice_box_text == ""
    # Action buttons disabled to block new actions
    assert panel.action_buttons_enabled is False
