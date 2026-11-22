"""
backend/tests/test_fuexam_login_statemachine.py
Kiểm thử tự động máy trạng thái đăng nhập fuexam:
1. idle, starting, waiting, success, failed, timeout
2. Giả lập tiến trình con chết sớm (exit code khác 0) -> chuyển sang 'failed' kèm lý do ngắn
3. Giả lập tiến trình con bị đóng giữa chừng khi đang ở 'waiting' -> chuyển sang 'failed'
4. Lọc bỏ cookie/token trong 20 dòng log cuối trả về
5. API chromium-self-check
"""

import json
from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.core.config import get_settings
import backend.app.api.auth as auth_mod


@pytest.fixture(autouse=True)
def reset_fuexam_state():
    """Reset in-memory state before and after each test."""
    settings = get_settings()
    auth_mod._fuexam_session_state = {
        "state": "idle",
        "pid": None,
        "started_at": 0.0,
        "message": "Chưa có phiên đăng nhập nào đang chạy.",
        "error": None,
    }
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"
    if ipc_file.exists():
        ipc_file.unlink()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    if auth_file.exists():
        auth_file.unlink()
    yield
    if ipc_file.exists():
        ipc_file.unlink()
    if auth_file.exists():
        auth_file.unlink()


@pytest.mark.asyncio
async def test_01_initial_state_idle():
    """Trạng thái ban đầu của máy trạng thái là 'idle'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/fuexam/login/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "idle"
        assert "recent_logs" in data


@pytest.mark.asyncio
async def test_02_child_process_dies_immediately_returns_failed():
    """Giả lập tiến trình con chết ngay khi khởi động (exit code 1) -> state=failed kèm lý do."""
    mock_proc = MagicMock()
    mock_proc.pid = 99991
    # proc.poll() returns 1 (process exited with error)
    mock_proc.poll.return_value = 1

    with patch("subprocess.Popen", return_value=mock_proc):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/start")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "failed", f"Kỳ vọng state 'failed' nhưng nhận được: {data['state']}"
            assert "thoát sớm" in data["error"] or "mã lỗi 1" in data["error"]

            # Kiểm tra tiếp qua GET /status
            status_resp = await client.get("/api/auth/fuexam/login/status")
            status_data = status_resp.json()
            assert status_data["state"] == "failed"
            assert "thoát sớm" in status_data["error"]


@pytest.mark.asyncio
async def test_03_child_process_signals_waiting_via_ipc():
    """Script con tạo file IPC với đúng run_id, pid và stage='page_loaded' -> login/start trả waiting."""
    settings = get_settings()
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"

    import os
    real_pid = os.getpid()
    mock_proc = MagicMock()
    mock_proc.pid = real_pid
    mock_proc.poll.return_value = None  # process is alive

    def mock_popen(*args, **kwargs):
        # Retrieve the run_id passed in cmdline
        cmd = args[0] if args else kwargs.get("args", [])
        run_id = ""
        for i, token in enumerate(cmd):
            if token == "--run-id" and i + 1 < len(cmd):
                run_id = cmd[i + 1]
                break
        ipc_file.parent.mkdir(parents=True, exist_ok=True)
        ipc_file.write_text(json.dumps({
            "run_id": run_id,
            "pid": real_pid,
            "stage": "page_loaded",
            "state": "waiting",
            "message": "Trình duyệt Chromium đã mở trang đăng nhập.",
            "timestamp": time.time(),
        }), encoding="utf-8")
        return mock_proc

    with patch("subprocess.Popen", side_effect=mock_popen):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/start")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "waiting"
            assert data["stage"] == "page_loaded"
            assert auth_mod._fuexam_session_state["pid"] == real_pid

            # GET status cũng trả 'waiting' vì tiến trình PID thật đang chạy
            status_resp = await client.get("/api/auth/fuexam/login/status")
            assert status_resp.json()["state"] == "waiting"


@pytest.mark.asyncio
async def test_03b_mismatched_run_id_or_pid_ignored():
    """File IPC có run_id hoặc pid cũ không khớp -> backend bỏ qua, không nhận waiting."""
    settings = get_settings()
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"

    import os
    real_pid = os.getpid()
    mock_proc = MagicMock()
    mock_proc.pid = real_pid
    # Proc dies to end loop quickly
    mock_proc.poll.return_value = 0

    def mock_popen(*args, **kwargs):
        ipc_file.parent.mkdir(parents=True, exist_ok=True)
        ipc_file.write_text(json.dumps({
            "run_id": "old_stale_run_999",
            "pid": 88888,
            "stage": "page_loaded",
            "state": "waiting",
        }), encoding="utf-8")
        return mock_proc

    with patch("subprocess.Popen", side_effect=mock_popen):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/start")
            assert resp.status_code == 200
            data = resp.json()
            # Must NOT be waiting because run_id and pid did not match!
            assert data["state"] != "waiting"


@pytest.mark.asyncio
async def test_03c_stage_before_page_loaded_does_not_transition_to_waiting():
    """Giai đoạn 'before_launch' hoặc 'after_goto' chưa phải là 'page_loaded' -> không được trả waiting."""
    settings = get_settings()
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"

    import os
    real_pid = os.getpid()
    mock_proc = MagicMock()
    mock_proc.pid = real_pid
    # Proc dies to end loop quickly
    mock_proc.poll.return_value = 1

    def mock_popen(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        run_id = ""
        for i, token in enumerate(cmd):
            if token == "--run-id" and i + 1 < len(cmd):
                run_id = cmd[i + 1]
                break
        ipc_file.parent.mkdir(parents=True, exist_ok=True)
        ipc_file.write_text(json.dumps({
            "run_id": run_id,
            "pid": real_pid,
            "stage": "after_launch",
            "state": "starting",
        }), encoding="utf-8")
        return mock_proc

    with patch("subprocess.Popen", side_effect=mock_popen):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/start")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "failed"
            assert "after_launch" in data["error"]


@pytest.mark.asyncio
async def test_04_child_process_dies_while_in_waiting():
    """Khi đang ở trạng thái waiting, nếu tiến trình con chết -> GET status chuyển sang 'failed'."""
    settings = get_settings()
    auth_mod._fuexam_session_state = {
        "state": "waiting",
        "pid": 99993,
        "started_at": time.time(),
        "message": "Hãy đăng nhập trong cửa sổ vừa mở.",
        "error": None,
    }

    # Giả lập PID 99993 không còn tồn tại
    with patch("psutil.Process") as mock_psutil_proc:
        import psutil
        mock_psutil_proc.side_effect = psutil.NoSuchProcess(99993)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/auth/fuexam/login/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "failed"
            assert "đã bị đóng" in data["error"] or "đã kết thúc" in data["error"]


@pytest.mark.asyncio
async def test_05_sanitizes_cookies_and_tokens_in_log_tail():
    """Đảm bảo 20 dòng log cuối không chứa cookie hay token."""
    settings = get_settings()
    log_file = settings.DATA_DIR / "logs" / "fuexam_login.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Ghi log chứa cookie và token nhạy cảm
    sensitive_lines = [
        "[2026-11-22 10:00:00] [INFO] Khởi động trình duyệt",
        "[2026-11-22 10:00:01] [INFO] Request header xf_user=123456%2Csecret_user_hash; xf_session=ab9876543210",
        "[2026-11-22 10:00:02] [INFO] Form payload _xfToken=1732000000%2Csecret_token_12345",
        "[2026-11-22 10:00:03] [INFO] cookies: [{\"name\": \"xf_user\", \"value\": \"leaked_val\"}]",
    ]
    log_file.write_text("\n".join(sensitive_lines), encoding="utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/fuexam/login/status")
        assert resp.status_code == 200
        logs = resp.json().get("recent_logs", [])
        assert len(logs) > 0
        log_text = "\n".join(logs)

        # Kiểm tra không chứa các giá trị nhạy cảm
        assert "secret_user_hash" not in log_text
        assert "ab9876543210" not in log_text
        assert "secret_token_12345" not in log_text
        assert "leaked_val" not in log_text
        assert "[REDACTED]" in log_text


@pytest.mark.asyncio
async def test_06_timeout_after_300_seconds():
    """Khi waiting quá 300 giây -> timeout."""
    auth_mod._fuexam_session_state = {
        "state": "waiting",
        "pid": 99994,
        "started_at": time.time() - 305,  # 305s ago
        "message": "Hãy đăng nhập trong cửa sổ vừa mở.",
        "error": None,
    }

    with patch("psutil.pid_exists", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/auth/fuexam/login/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "timeout"
            assert "Hết thời gian chờ" in data["error"]


@pytest.mark.asyncio
async def test_07_success_when_authenticated():
    """Khi có xf_user và fuexam_user.json -> state=success."""
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"

    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps({
        "cookies": [{"name": "xf_user", "value": "valid_user_cookie"}]
    }), encoding="utf-8")
    user_file.write_text(json.dumps({"username": "TestMember"}), encoding="utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/fuexam/login/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "success"
        assert "TestMember" in data["message"]


@pytest.mark.asyncio
async def test_08_chromium_self_check_endpoint():
    """Endpoint chromium-self-check gọi logic kiểm tra."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/auth/fuexam/chromium-self-check")
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "browser" in data
        assert "message" in data


@pytest.mark.asyncio
async def test_09_watchdog_timeout_kills_process_and_reports_stage():
    """Watchdog 30s kích hoạt khi tiến trình không đến được 'page_loaded' -> kill tiến trình và báo lỗi kèm tên giai đoạn."""
    mock_proc = MagicMock()
    mock_proc.pid = 99995
    mock_proc.poll.return_value = None  # Process stays alive but hangs

    settings = get_settings()
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"

    def mock_popen(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        run_id = ""
        for i, token in enumerate(cmd):
            if token == "--run-id" and i + 1 < len(cmd):
                run_id = cmd[i + 1]
                break
        ipc_file.parent.mkdir(parents=True, exist_ok=True)
        # Writes stage 'before_launch' then hangs
        ipc_file.write_text(json.dumps({
            "run_id": run_id,
            "pid": 99995,
            "stage": "before_launch",
            "state": "starting",
        }), encoding="utf-8")
        return mock_proc

    # Mock time.time to simulate 31 seconds passing during watchdog
    time_calls = [100.0]
    def fake_time():
        val = time_calls[0]
        time_calls[0] += 5.0  # increments by 5s each check
        return val

    with patch("subprocess.Popen", side_effect=mock_popen), \
         patch("time.time", side_effect=fake_time), \
         patch("asyncio.sleep", return_value=None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/start")
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "failed"
            assert "Watchdog timeout (30s)" in data["error"]
            assert "before_launch" in data["error"]
            mock_proc.kill.assert_called()


@pytest.mark.asyncio
async def test_10_log_truncation_before_start():
    """Mỗi lần start_fuexam_login phải truncate file log fuexam_login.log."""
    settings = get_settings()
    log_file = settings.DATA_DIR / "logs" / "fuexam_login.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("DONG LOG CU TU PHIEN TRUOC\n" * 50, encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.pid = 99996
    mock_proc.poll.return_value = 0  # exits right away

    with patch("subprocess.Popen", return_value=mock_proc):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/auth/fuexam/login/start")
            content = log_file.read_text(encoding="utf-8")
            assert "DONG LOG CU TU PHIEN TRUOC" not in content
            assert "Khởi tạo phiên đăng nhập mới" in content


@pytest.mark.asyncio
async def test_11_cancel_login_cleans_resources():
    """Hủy đăng nhập kill tiến trình, dọn dẹp file IPC và đưa về idle."""
    settings = get_settings()
    ipc_file = settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"
    ipc_file.parent.mkdir(parents=True, exist_ok=True)
    ipc_file.write_text(json.dumps({"state": "waiting"}), encoding="utf-8")

    auth_mod._fuexam_session_state = {
        "run_id": "run_cancel_1",
        "state": "waiting",
        "stage": "page_loaded",
        "pid": 99997,
        "started_at": time.time(),
        "message": "Chờ đăng nhập...",
        "error": None,
    }

    with patch("psutil.pid_exists", return_value=True), patch("psutil.Process"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/login/cancel")
            assert resp.status_code == 200
            assert resp.json()["success"] is True
            assert auth_mod._fuexam_session_state["state"] == "idle"
            assert not ipc_file.exists()

