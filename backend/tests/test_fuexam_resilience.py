"""
Tests for fuexam resilience:
1. Timeout then success -> retry succeeds using real local mock HTTP server.
2. Persistent timeout on one media -> exam still completes, question is in fetch_failed_questions, NO empty cache written.
3. HTTP 429 with Retry-After header is respected.
4. Circuit breaker trips after N consecutive timeouts, pauses, and slows down.
5. Cancel during backoff wakes up immediately via cancel_event.
6. Per-exam isolation: one exam fails, another exam still completes, and POST /api/jobs/{id}/retry-failed retries only the failed exam.
7. Non-retryable 4xx (404) does not retry; 401/403 raises AuthenticationRequiredError.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

from PIL import Image
import pytest
import requests
from httpx import AsyncClient, ASGITransport

from backend.app.core.config import get_settings
from backend.app.db.session import init_db
from backend.app.main import app
from backend.app.modules.analysis.ai_check import AIQuestionAnalysis
from backend.app.modules.crawler import fuexam_crawler
from backend.app.modules.crawler.fuexam_crawler import (
    AuthenticationRequiredError,
    CommentFetchError,
    FuexamHttpClient,
    FuexamRequestError,
    JobCancelledError,
    fetch_and_cache_media_comments,
)
from backend.app.modules.export.image_cropper import CropResult
from backend.app.modules.jobs.orchestrator import get_orchestrator


class _MockState:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}
        self.handler_fn = None


def _start_mock_server(handler_fn):
    state = _MockState()
    state.handler_fn = handler_fn

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with state.lock:
                state.counts[self.path] = state.counts.get(self.path, 0) + 1
                attempt = state.counts[self.path]
            state.handler_fn(self, attempt)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


def test_timeout_then_success_retry_mock_server(tmp_path, monkeypatch):
    """Giả lập timeout lần 1 rồi thành công ở lần 2 -> retry thành công và ghi cache nguyên tử."""
    monkeypatch.setattr(fuexam_crawler, "CACHE_DIR", tmp_path / "cache")

    def handler(req, attempt):
        if attempt == 1:
            time.sleep(0.35)  # Exceeds read_timeout=0.15
        html = (
            '<html><body data-logged-in="true">'
            '<article class="message--comment" id="c1">'
            '<span class="username">sv1</span>'
            '<div class="bbWrapper">1A</div>'
            '</article></body></html>'
        ).encode("utf-8")
        try:
            req.send_response(200)
            req.send_header("Content-Type", "text/html; charset=utf-8")
            req.end_headers()
            req.wfile.write(html)
        except OSError:
            pass

    server, state = _start_mock_server(handler)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client = FuexamHttpClient(
            connect_timeout=1.0,
            read_timeout=0.15,
            max_attempts=4,
            backoff_base=0.05,
            min_delay_seconds=0.0,
            circuit_breaker_threshold=5,
        )
        session = requests.Session()
        comms, cached = fetch_and_cache_media_comments(
            media_id=5001,
            slug="q1",
            session=session,
            client=client,
            base_url=base_url,
        )
        assert cached is False
        assert len(comms) == 1
        assert comms[0]["raw_text"] == "1A"
        assert state.counts["/media/q1.5001/"] == 2
        assert client.retry_count == 1
        assert (tmp_path / "cache" / "media_5001" / "comments.json").exists()

        # Lần 2 đọc từ cache, không gọi server
        comms2, cached2 = fetch_and_cache_media_comments(
            media_id=5001,
            slug="q1",
            session=session,
            client=client,
            base_url=base_url,
        )
        assert cached2 is True
        assert len(comms2) == 1
        assert state.counts["/media/q1.5001/"] == 2
    finally:
        server.shutdown()
        server.server_close()


def test_429_retry_after_respected(tmp_path, monkeypatch):
    """429 có Retry-After được tôn trọng trước khi retry."""
    monkeypatch.setattr(fuexam_crawler, "CACHE_DIR", tmp_path / "cache")

    def handler(req, attempt):
        if attempt == 1:
            req.send_response(429)
            req.send_header("Retry-After", "0.25")
            req.end_headers()
            return
        html = b'<html><body data-logged-in="true"><div class="message--comment"><span class="username">u</span><div class="bbWrapper">B</div></div></body></html>'
        req.send_response(200)
        req.send_header("Content-Type", "text/html")
        req.end_headers()
        req.wfile.write(html)

    server, state = _start_mock_server(handler)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client = FuexamHttpClient(
            connect_timeout=1.0,
            read_timeout=2.0,
            max_attempts=4,
            backoff_base=0.01,
            min_delay_seconds=0.0,
        )
        t0 = time.monotonic()
        comms, _ = fetch_and_cache_media_comments(
            media_id=5002,
            slug="q2",
            session=requests.Session(),
            client=client,
            base_url=base_url,
        )
        elapsed = time.monotonic() - t0
        assert len(comms) == 1
        assert elapsed >= 0.22
        assert client.rate_limit_count == 1
        assert state.counts["/media/q2.5002/"] == 2
    finally:
        server.shutdown()
        server.server_close()


def test_non_retryable_4xx_and_auth_error(tmp_path, monkeypatch):
    """404 không retry; 401 ném AuthenticationRequiredError không retry."""
    monkeypatch.setattr(fuexam_crawler, "CACHE_DIR", tmp_path / "cache")

    def handler(req, attempt):
        if "404" in req.path:
            req.send_response(404)
            req.end_headers()
        else:
            req.send_response(401)
            req.end_headers()

    server, state = _start_mock_server(handler)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client = FuexamHttpClient(max_attempts=4, backoff_base=0.01, min_delay_seconds=0.0)
        s = requests.Session()

        with pytest.raises(CommentFetchError) as exc_info:
            fetch_and_cache_media_comments(404, "missing404", s, client=client, base_url=base_url)
        assert exc_info.value.error_type == "http_4xx"
        assert exc_info.value.error_code.startswith("NET-")
        assert state.counts["/media/missing404.404/"] == 1  # No retry!
        assert not (tmp_path / "cache" / "media_404" / "comments.json").exists()

        with pytest.raises(AuthenticationRequiredError):
            fetch_and_cache_media_comments(401, "unauth", s, client=client, base_url=base_url)
        assert state.counts["/media/unauth.401/"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_circuit_breaker_trips_and_slows_down():
    """Sau N timeout liên tiếp, circuit breaker tạm nghỉ và giảm tốc."""
    events = []

    def handler(req, attempt):
        time.sleep(0.25)

    server, _ = _start_mock_server(handler)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        client = FuexamHttpClient(
            connect_timeout=1.0,
            read_timeout=0.08,
            max_attempts=3,
            backoff_base=0.01,
            min_delay_seconds=0.05,
            circuit_breaker_threshold=3,
            circuit_breaker_pause_seconds=0.2,
            event_callback=events.append,
        )
        with pytest.raises(FuexamRequestError) as exc_info:
            client.get(requests.Session(), f"{base_url}/slow", expect_html=True)
        assert exc_info.value.error_type == "timeout"
        assert client.circuit_breaker_trips == 1
        assert client._slow_mode is True
        assert client._current_min_delay >= 1.2
        assert any(e.get("circuit_breaker") is True for e in events)
        assert any("fuexam phản hồi chậm" in (e.get("message") or "") for e in events)
    finally:
        server.shutdown()
        server.server_close()


def test_cancel_during_backoff():
    """Hủy giữa backoff phải thoát ngay lập tức qua cancel_event."""
    def handler(req, attempt):
        req.send_response(503)
        req.end_headers()

    server, _ = _start_mock_server(handler)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        cancel_ev = threading.Event()
        client = FuexamHttpClient(
            max_attempts=4,
            backoff_base=10.0,  # Long backoff (10s)
            min_delay_seconds=0.0,
            cancel_event=cancel_ev,
        )

        def trigger_cancel():
            time.sleep(0.15)
            cancel_ev.set()

        t = threading.Thread(target=trigger_cancel, daemon=True)
        t.start()
        t0 = time.monotonic()
        with pytest.raises(JobCancelledError):
            client.get(requests.Session(), f"{base_url}/retry-me")
        elapsed = time.monotonic() - t0
        assert elapsed < 1.5  # Exited immediately instead of waiting 10s
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_per_question_and_per_exam_isolation_and_retry_failed(tmp_path, monkeypatch):
    """
    - Timeout liên tục ở 1 media -> đề vẫn hoàn tất, câu đó nằm trong fetch_failed_questions & .meta.json, không lưu cache rỗng.
    - Một đề lỗi -> đề khác vẫn xong.
    - POST /api/jobs/{id}/retry-failed chạy lại chỉ phần lỗi.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "data" / "output")
    monkeypatch.setattr("backend.app.modules.jobs.orchestrator.settings.BASE_DIR", tmp_path)
    monkeypatch.setattr("backend.app.modules.export.docx_builder.settings.BASE_DIR", tmp_path)
    monkeypatch.setattr(fuexam_crawler, "CACHE_DIR", tmp_path / "data" / "cache" / "fuexam")

    auth_dir = settings.DATA_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "fuexam_storage_state.json").write_text(
        json.dumps({"cookies": [{"name": "xf_user", "value": "mock_user"}]}),
        encoding="utf-8",
    )

    sample_img = tmp_path / "sample.png"
    im = Image.new("RGB", (300, 150), color=(240, 240, 240))
    im.save(sample_img)

    fail_exam_2002 = {"fail": True}

    def mock_extract(url, session):
        if "2001" in url:
            return "HCM202 - FA26 - FE - D1 | FuExam", [
                {"index": 1, "title": "Câu 1", "slug": "q1", "media_id": 7001, "attachment_id": 7001, "attachment_url": "http://mock/att/1", "media_url": "http://mock/media/q1.7001/"},
                {"index": 2, "title": "Câu 2", "slug": "q2", "media_id": 7002, "attachment_id": 7002, "attachment_url": "http://mock/att/2", "media_url": "http://mock/media/q2.7002/"},
            ]
        if "2002" in url:
            if fail_exam_2002["fail"]:
                raise FuexamRequestError("Timeout loading thread 2002", error_type="timeout", error_code="NET-DEAD02")
            return "HCM202 - FA26 - FE - D2 | FuExam", [
                {"index": 1, "title": "Câu 1", "slug": "q1", "media_id": 7003, "attachment_id": 7003, "attachment_url": "http://mock/att/3", "media_url": "http://mock/media/q1.7003/"},
            ]
        return "Unknown", []

    def mock_fetch_img(*args, **kwargs):
        return sample_img, True

    def mock_fetch_comms(*args, **kwargs):
        m_id = kwargs.get("media_id") if "media_id" in kwargs else args[0]
        if m_id == 7002:
            raise CommentFetchError("ReadTimeout", media_id=7002, error_type="timeout", error_code="NET-TMO702")
        return [{"comment_id": 1, "author_hash": "abc", "raw_text": "1A"}], False

    def mock_crop(img_path, output_path=None, **kwargs):
        dest = Path(output_path) if output_path else Path(img_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest)
        return CropResult(cropped_image=im, box=(0, 0, 300, 150), layout="fuexam_2026", output_path=dest)

    with patch("backend.app.modules.crawler.fuexam_crawler.get_authenticated_session", return_value=requests.Session()), \
         patch("backend.app.modules.crawler.fuexam_crawler.check_session_validity", return_value=True), \
         patch("backend.app.modules.crawler.fuexam_crawler.extract_thread_questions", side_effect=mock_extract), \
         patch("backend.app.modules.crawler.fuexam_crawler.fetch_and_cache_media_image", side_effect=mock_fetch_img), \
         patch("backend.app.modules.crawler.fuexam_crawler.fetch_and_cache_media_comments", side_effect=mock_fetch_comms), \
         patch("backend.app.modules.export.image_cropper.crop_question_single", side_effect=mock_crop), \
         patch("backend.app.modules.analysis.ai_check.AICheckService.analyze_question_ensemble", return_value=[AIQuestionAnalysis(answers=["A"], confidence=0.9, provider="gemini", options={})]):

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/jobs", json={
                "subject_code": "HCM202",
                "exam_type": "FE",
                "limit": 2,
                "platform": "fuexam",
                "exam_ids": [2001, 2002],
                "exam_titles": {
                    "2001": "HCM202 - FA26 - FE - D1",
                    "2002": "HCM202 - FA26 - FE - D2",
                },
            })
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]

            orchestrator = get_orchestrator()
            await orchestrator._running_tasks[job_id]

            st = (await client.get(f"/api/jobs/{job_id}")).json()
            assert st["status"] == "completed"
            files = st["details"]["files"]
            assert len(files) == 1
            assert files[0]["fetch_failed_questions"] == [2]
            assert files[0]["status"] == "completed_with_warnings"

            meta_path = tmp_path / (files[0]["path"] + ".meta.json")
            meta_json = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta_json["fetch_failed_questions"] == [2]
            # Không lưu cache rỗng cho media 7002
            assert not (tmp_path / "data" / "cache" / "fuexam" / "media_7002" / "comments.json").exists()

            failed_exams = st["details"]["failed_exams"]
            assert len(failed_exams) == 1
            assert failed_exams[0]["thread_id"] == 2002
            assert failed_exams[0]["error_code"] == "NET-DEAD02"

            # Bây giờ cho đề 2002 hết lỗi và gọi retry-failed
            fail_exam_2002["fail"] = False
            retry_resp = await client.post(f"/api/jobs/{job_id}/retry-failed")
            assert retry_resp.status_code == 200
            await orchestrator._running_tasks[job_id]

            st2 = (await client.get(f"/api/jobs/{job_id}")).json()
            assert st2["status"] == "completed"
            assert len(st2["details"]["failed_exams"]) == 0
            assert len(st2["details"]["files"]) == 2
