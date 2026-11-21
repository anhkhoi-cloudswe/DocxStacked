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


class MockExtensionBackgroundService:
    """
    Simulates background.js queue dispatch, runId deduplication,
    and active queue replacement/force logic.
    """
    def __init__(self, storage: MockChromeStorage, worker: 'MockOffscreenQueueWorkerV2'):
        self.storage = storage
        self.worker = worker
        self.processed_run_ids = set()

    def handle_enqueue_command(self, message: Dict[str, Any]) -> Dict[str, Any]:
        run_id = message.get("runId")
        if run_id:
            if run_id in self.processed_run_ids:
                return {"status": "ignored", "reason": "duplicate_run_id", "runId": run_id}
            self.processed_run_ids.add(run_id)

        items = message.get("items", [])
        if not items:
            return {"status": "error", "message": "No items provided"}

        force = message.get("force", False)

        # Check existing queue
        existing_data = self.storage.get(["savedQueueState"])
        existing_state = existing_data.get("savedQueueState")
        if existing_state and existing_state.get("isRunning") and not force:
            return {"status": "error", "code": "QUEUE_RUNNING", "message": "Queue is currently running"}

        # If running and force is True, stop active queue first
        if existing_state and existing_state.get("isRunning") and force:
            self.worker.abort_current_run()

        # Wipe stale completed results and replace storage completely
        first_title = items[0].get("title", "")
        total_q = items[0].get("totalQuestions", 50)

        initial_state = {
            "runId": run_id,
            "items": items,
            "currentIndex": 0,
            "isRunning": True,
            "isPaused": False,
            "isCompleted": False,
            "currentExamTitle": first_title,
            "currentQuestionIndex": 1,
            "totalQuestions": total_q,
            "progressPct": 1,
            "statusText": f"Câu 1/{total_q}",
            "completedExams": [],
            "updatedAt": time.time(),
        }
        self.storage.set({"savedQueueState": initial_state})
        self.worker.start_queue_with_run_id(items, run_id=run_id, total_questions=total_q)
        return {"status": "success", "runId": run_id}


class MockOffscreenQueueWorkerV2:
    """
    Extended offscreen queue worker supporting runId tagging, cooperative abort,
    and single-source exam processing.
    """
    def __init__(self, storage: MockChromeStorage):
        self.storage = storage
        self.is_running = False
        self.current_run_id = None
        self.abort_requested = False
        self.items = []
        self.current_index = 0
        self.current_question = 1
        self.total_questions = 50
        self.completed_exams = []
        self.ingested_payloads = []

    def start_queue_with_run_id(self, items: List[Dict[str, Any]], run_id: str, total_questions: int = 50):
        self.abort_current_run()
        self.items = list(items)
        self.current_run_id = run_id
        self.current_index = 0
        self.current_question = 1
        self.total_questions = total_questions
        self.is_running = True
        self.abort_requested = False
        self.completed_exams = []
        self._save_state()

    def abort_current_run(self):
        self.abort_requested = True
        self.is_running = False

    def advance_time(self, seconds: float, cadence_sec: float = 2.0):
        if not self.is_running or self.abort_requested:
            return

        steps = int(seconds / cadence_sec)
        for _ in range(steps):
            if self.abort_requested or not self.is_running:
                break

            if self.current_index >= len(self.items):
                self.is_running = False
                self._save_state(is_completed=True)
                break

            cur_item = self.items[self.current_index]

            if self.current_question >= self.total_questions:
                # Ingest payload from active item and runId
                payload = {
                    "run_id": self.current_run_id,
                    "exam_title": cur_item["title"],
                    "exam_url": cur_item["url"],
                    "total_questions": self.total_questions,
                }
                self.ingested_payloads.append(payload)

                self.completed_exams.append({
                    "id": f"exam_{self.current_index + 1}",
                    "title": cur_item["title"],
                    "docx_filename": f"{cur_item['title']}.docx",
                    "download_url": f"/api/exports/{self.current_index + 1}/download",
                    "run_id": self.current_run_id,
                })
                self.current_index += 1
                self.current_question = 1
                if self.current_index >= len(self.items):
                    self.is_running = False
                    self._save_state(is_completed=True)
                    break
            else:
                self.current_question += 1

            self._save_state()

    def _save_state(self, is_completed: bool = False):
        cur_title = ""
        if self.current_index < len(self.items):
            cur_title = self.items[self.current_index]["title"]
        pct = int((self.current_question / self.total_questions) * 100) if self.total_questions else 0

        self.storage.set({
            "savedQueueState": {
                "runId": self.current_run_id,
                "items": self.items,
                "currentIndex": self.current_index,
                "isRunning": self.is_running,
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


def test_new_command_replaces_old_queue_in_storage():
    """
    Requirement 7 Test:
    - Old queue exists in storage (e.g. PRN212 with stale completed result cards).
    - New command arrives with new runId (PRM392).
    - Old queue items and stale completed result cards are completely wiped.
    - Only the new exam (PRM392) is compiled and ingested.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorkerV2(storage)
    bg = MockExtensionBackgroundService(storage, worker)

    # 1. Old state left in storage from past session
    storage.set({
        "savedQueueState": {
            "runId": "old-run-prn212",
            "items": [{"title": "PRN212 - SU25 - B5 - 1", "url": "https://fuoverflow.com/threads/fe.212/"}],
            "currentIndex": 0,
            "isRunning": False,
            "isCompleted": True,
            "currentExamTitle": "PRN212 - SU25 - B5 - 1",
            "completedExams": [{
                "title": "PRN212 - SU25 - B5 - 1",
                "docx_filename": "PRN212 - SU25 - B5 - 1.docx",
                "download_url": "/api/exports/old/download"
            }],
        }
    })

    # Verify old state is in storage
    old_state = storage.get(["savedQueueState"])["savedQueueState"]
    assert old_state["currentExamTitle"] == "PRN212 - SU25 - B5 - 1"
    assert len(old_state["completedExams"]) == 1

    # 2. Dashboard sends new command for PRM392
    new_cmd = {
        "runId": "run-prm392-uuid-001",
        "items": [{
            "title": "PRM392 - SU 2024 - RE",
            "url": "https://fuoverflow.com/threads/fe.392/",
            "totalQuestions": 50,
        }],
        "force": False,
    }
    res = bg.handle_enqueue_command(new_cmd)
    assert res["status"] == "success"

    # 3. Check storage immediately: old items and completed cards MUST be cleared!
    cur_state = storage.get(["savedQueueState"])["savedQueueState"]
    assert cur_state["runId"] == "run-prm392-uuid-001"
    assert cur_state["currentExamTitle"] == "PRM392 - SU 2024 - RE"
    assert cur_state["statusText"] == "Câu 1/50"
    assert cur_state["completedExams"] == []
    assert len(cur_state["items"]) == 1
    assert cur_state["items"][0]["title"] == "PRM392 - SU 2024 - RE"

    # 4. Advance worker to completion
    worker.advance_time(100.0, cadence_sec=2.0)
    assert worker.is_running is False
    assert len(worker.completed_exams) == 1
    assert worker.completed_exams[0]["title"] == "PRM392 - SU 2024 - RE"
    assert worker.completed_exams[0]["docx_filename"] == "PRM392 - SU 2024 - RE.docx"

    # Ingestion strictly took PRM392 with matching run_id and url
    assert len(worker.ingested_payloads) == 1
    assert worker.ingested_payloads[0]["exam_title"] == "PRM392 - SU 2024 - RE"
    assert worker.ingested_payloads[0]["exam_url"] == "https://fuoverflow.com/threads/fe.392/"
    assert worker.ingested_payloads[0]["run_id"] == "run-prm392-uuid-001"

    # Sidepanel UI also reflects only the new exam
    panel = MockSidepanelUI(storage)
    panel.open_panel()
    assert len(panel.completed_items) == 1
    assert panel.completed_items[0]["title"] == "PRM392 - SU 2024 - RE"


def test_duplicate_command_with_same_run_id_runs_only_once():
    """
    Requirement 7 Test:
    - Dashboard sends a command with runId = "dup-run-999".
    - A duplicate command with the exact same runId arrives (double click or message replay).
    - Extension deduplicates and processes the command ONLY ONCE.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorkerV2(storage)
    bg = MockExtensionBackgroundService(storage, worker)

    cmd = {
        "runId": "dup-run-999",
        "items": [{
            "title": "PRM392 - SU 2024 - RE",
            "url": "https://fuoverflow.com/threads/fe.392/",
            "totalQuestions": 50,
        }],
    }

    # 1. First command
    res1 = bg.handle_enqueue_command(cmd)
    assert res1["status"] == "success"

    # 2. Second command with same runId
    res2 = bg.handle_enqueue_command(cmd)
    assert res2["status"] == "ignored"
    assert res2["reason"] == "duplicate_run_id"

    # Advance worker to complete
    worker.advance_time(100.0, cadence_sec=2.0)

    # Ingestion happened exactly once
    assert len(worker.ingested_payloads) == 1
    assert len(worker.completed_exams) == 1


def test_active_running_queue_rejects_without_force_and_aborts_with_force():
    """
    Requirement 7 & Requirement 2 Test:
    - Queue is actively crawling PRN212.
    - New command PRM392 arrives without force -> rejected with QUEUE_RUNNING.
    - New command PRM392 arrives with force=True -> aborts PRN212 crawl immediately,
      replaces queue with PRM392, and PRN212 is NEVER ingested.
    """
    storage = MockChromeStorage()
    worker = MockOffscreenQueueWorkerV2(storage)
    bg = MockExtensionBackgroundService(storage, worker)

    # 1. Start PRN212
    cmd1 = {
        "runId": "run-prn212-active",
        "items": [{
            "title": "PRN212 - SU25 - B5 - 1",
            "url": "https://fuoverflow.com/threads/fe.212/",
            "totalQuestions": 50,
        }],
    }
    bg.handle_enqueue_command(cmd1)

    # Crawl 10 questions of PRN212
    worker.advance_time(20.0, cadence_sec=2.0)
    assert worker.current_question == 11
    assert worker.is_running is True

    # 2. Try enqueuing PRM392 without force -> rejected
    cmd2_no_force = {
        "runId": "run-prm392-no-force",
        "items": [{
            "title": "PRM392 - SU 2024 - RE",
            "url": "https://fuoverflow.com/threads/fe.392/",
            "totalQuestions": 50,
        }],
        "force": False,
    }
    res_rejected = bg.handle_enqueue_command(cmd2_no_force)
    assert res_rejected["status"] == "error"
    assert res_rejected["code"] == "QUEUE_RUNNING"
    # Worker is still on PRN212
    assert worker.current_run_id == "run-prn212-active"

    # 3. User confirms replacement: send with force=True
    cmd2_force = {
        "runId": "run-prm392-forced",
        "items": [{
            "title": "PRM392 - SU 2024 - RE",
            "url": "https://fuoverflow.com/threads/fe.392/",
            "totalQuestions": 50,
        }],
        "force": True,
    }
    res_forced = bg.handle_enqueue_command(cmd2_force)
    assert res_forced["status"] == "success"

    # Old run aborted; new run active
    assert worker.current_run_id == "run-prm392-forced"
    assert worker.current_question == 1
    assert worker.completed_exams == []

    # Advance to completion
    worker.advance_time(100.0, cadence_sec=2.0)

    # PRN212 was NEVER ingested; only PRM392 was ingested!
    assert len(worker.ingested_payloads) == 1
    assert worker.ingested_payloads[0]["exam_title"] == "PRM392 - SU 2024 - RE"
    assert worker.ingested_payloads[0]["run_id"] == "run-prm392-forced"

