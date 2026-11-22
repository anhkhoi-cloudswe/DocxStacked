import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import List, Optional, Tuple
import urllib.request
import urllib.error
from fastapi import APIRouter
from pydantic import BaseModel
import psutil

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

import time

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOG_FILE = settings.DATA_DIR / "logs" / "login.log"
SESSION_FILE = settings.DATA_DIR / "auth" / "login_session.json"
PROFILE_DIR = settings.DATA_DIR / "browser_profile"

# In-memory store for recent extension heartbeat
_latest_extension_heartbeat: dict = {
    "timestamp": 0.0,
    "logged_in": False,
    "username": None,
}


class ExtensionHeartbeatRequest(BaseModel):
    logged_in: bool
    username: Optional[str] = None


class AuthStatusResponse(BaseModel):
    logged_in: bool
    status_code: str = "not_logged_in"  # "logged_in", "not_logged_in", "profile_locked", "network_error"
    auth_source: Optional[str] = "server"
    detail: str = "Chưa đăng nhập FUOverflow"
    username: Optional[str] = None
    expires_at: Optional[str] = None


class LoginTriggerResponse(BaseModel):
    success: bool
    logged_in: bool
    message: str


class LoginSessionResponse(BaseModel):
    state: str  # "idle", "opening", "waiting_for_user", "authenticated", "error", "cancelled"
    browser_used: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    recent_logs: List[str] = []
    updated_at: Optional[str] = None


class CookieImportRequest(BaseModel):
    cookie_string: str


class AccountLoginRequest(BaseModel):
    username: str
    password: str


def _get_profile_locking_pids() -> List[int]:
    """Find PIDs of any processes locking the browser_profile directory."""
    target = str(PROFILE_DIR.resolve()).lower()
    current_pid = os.getpid()
    locking = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            if target in " ".join(cmdline).lower():
                locking.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return locking


def _get_current_logged_in_username() -> Optional[str]:
    """Retrieve saved username of currently logged in user."""
    user_file = settings.DATA_DIR / "auth" / "current_user.json"
    if user_file.exists():
        try:
            data = json.loads(user_file.read_text(encoding="utf-8"))
            if data and data.get("username"):
                return data["username"]
        except Exception:
            pass
    return None


async def _check_browser_auth_async() -> AuthStatusResponse:
    """
    Live check of FUOverflow authentication executed strictly in an isolated child process.
    Never launches Playwright or touches event loops in the server process.
    """
    # 1. Verify if profile directory is currently locked by stale browser processes
    locking_pids = _get_profile_locking_pids()
    if locking_pids:
        return AuthStatusResponse(
            logged_in=False,
            status_code="profile_locked",
            detail=f"Thư mục hồ sơ đang bị {len(locking_pids)} tiến trình chạy ngầm giữ (PIDs: {locking_pids}).",
        )

    # 2. Check if cookies exist
    cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
    if not cookies_file.exists():
        return AuthStatusResponse(
            logged_in=False,
            status_code="not_logged_in",
            detail="Chưa đăng nhập FUOverflow (chưa có phiên lưu trữ).",
        )

    # 3. Live verification via dedicated subprocess
    login_script = settings.BASE_DIR / "scripts" / "login.py"
    if not login_script.exists():
        return AuthStatusResponse(
            logged_in=False,
            status_code="network_error",
            detail="Không tìm thấy tệp scripts/login.py để kiểm tra phiên.",
        )

    try:
        res = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(login_script), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            cwd=str(settings.BASE_DIR),
        )
        if res.stdout:
            for line in reversed(res.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
                    return AuthStatusResponse(
                        logged_in=bool(data.get("logged_in")),
                        status_code=data.get("status_code", "not_logged_in"),
                        detail=data.get("detail", ""),
                        username=data.get("username"),
                        expires_at=data.get("expires_at"),
                    )
        logger.warning(f"Auth check subprocess returned unexpected output: {res.stderr or res.stdout}")
    except subprocess.TimeoutExpired:
        logger.warning("Auth check subprocess timed out after 15s")
        return AuthStatusResponse(
            logged_in=False,
            status_code="network_error",
            detail="Quá thời gian kiểm tra phiên đăng nhập (timeout 15s).",
        )
    except Exception as e:
        logger.warning(f"Error during live auth check subprocess: {e}")
        return AuthStatusResponse(
            logged_in=False,
            status_code="network_error",
            detail=f"Không thể kiểm tra phiên: {e}",
        )

    return AuthStatusResponse(
        logged_in=False,
        status_code="not_logged_in",
        detail="Chưa đăng nhập FUOverflow.",
    )


@router.post("/extension-heartbeat")
async def extension_heartbeat(payload: ExtensionHeartbeatRequest):
    """
    Called by browser extension (every 30-60s via alarms or upon opening sidepanel)
    to notify backend that the user is logged into fuoverflow.com.
    """
    global _latest_extension_heartbeat
    _latest_extension_heartbeat = {
        "timestamp": time.time(),
        "logged_in": bool(payload.logged_in),
        "username": payload.username,
    }
    logger.debug(f"Received extension heartbeat: logged_in={payload.logged_in}, user={payload.username}")
    try:
        from backend.app.api.ingest import touch_active_run_activity
        touch_active_run_activity()
    except Exception:
        pass
    return {"status": "ok", "recorded": _latest_extension_heartbeat}


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status():
    """
    Check FUOverflow authentication status:
    1. Check if extension heartbeat reported logged_in within the last 90 seconds.
    2. Fallback to live Playwright cookies check.
    """
    global _latest_extension_heartbeat
    now = time.time()
    # Extension sends heartbeat every 30s. Heartbeat is valid for 120s (4x cycle, >= 2x required).
    if (now - _latest_extension_heartbeat.get("timestamp", 0.0)) < 120.0:
        if _latest_extension_heartbeat.get("logged_in"):
            return AuthStatusResponse(
                logged_in=True,
                status_code="logged_in",
                auth_source="extension",
                detail="Đã đăng nhập FUOverflow (xác thực từ Extension).",
                username=_latest_extension_heartbeat.get("username") or "Extension User",
            )

    return await _check_browser_auth_async()


# Compatibility alias
_check_browser_auth_sync = _check_browser_auth_async


def _read_recent_logs(max_lines: int = 8) -> List[str]:
    """Read the tail of data/logs/login.log."""
    if not LOG_FILE.exists():
        return []
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


@router.get("/login-session", response_model=LoginSessionResponse)
async def get_login_session():
    """Poll live state of browser login workflow."""
    recent_logs = _read_recent_logs(8)

    if not SESSION_FILE.exists():
        return LoginSessionResponse(
            state="idle",
            message="Chưa có phiên đăng nhập nào đang chạy.",
            recent_logs=recent_logs,
        )

    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        state = data.get("state", "idle")
        pid = data.get("pid")

        # Verify if process is still alive when in active state
        if state in ("opening", "waiting_for_user") and pid:
            try:
                proc = psutil.Process(pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    # Process died unexpectedly
                    state = "error"
                    data["state"] = "error"
                    data["message"] = "Tiến trình đăng nhập đã dừng bất thường."
                    data["error"] = "Tiến trình trình duyệt đã thoát."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                state = "error"
                data["state"] = "error"
                data["message"] = "Tiến trình đăng nhập đã kết thúc."
                data["error"] = "Tiến trình trình duyệt không còn tồn tại."

        return LoginSessionResponse(
            state=state,
            browser_used=data.get("browser_used"),
            message=data.get("message", ""),
            error=data.get("error"),
            recent_logs=recent_logs,
            updated_at=data.get("updated_at"),
        )
    except Exception as e:
        return LoginSessionResponse(
            state="error",
            message=f"Lỗi đọc trạng thái phiên: {e}",
            recent_logs=recent_logs,
        )


@router.post("/login-session/cancel")
async def cancel_login_session():
    """Cancel the active login session and terminate its process."""
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid:
                try:
                    proc = psutil.Process(pid)
                    proc.kill()
                except Exception:
                    pass
            data["state"] = "cancelled"
            data["message"] = "Người dùng đã bấm huỷ phiên đăng nhập từ giao diện."
            data["updated_at"] = datetime.now().isoformat()
            SESSION_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Error cancelling session: {e}")

    # Also clean up any processes holding the profile
    _unlock_profile_sync()
    return {"success": True, "message": "Đã huỷ phiên đăng nhập thành công."}


def _unlock_profile_sync() -> int:
    """Kill only processes matching browser_profile in their cmdline."""
    target = str(PROFILE_DIR.resolve()).lower()
    current_pid = os.getpid()
    killed = 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            if target in " ".join(cmdline).lower():
                proc.kill()
                killed += 1
        except Exception:
            continue
    return killed


@router.post("/login-session/unlock")
async def unlock_profile():
    """Explicitly terminate stale processes locking browser_profile."""
    count = await asyncio.to_thread(_unlock_profile_sync)
    return {
        "success": True,
        "killed_count": count,
        "message": f"Đã giải phóng {count} tiến trình đang giữ thư mục hồ sơ." if count > 0 else "Thư mục hồ sơ không bị khoá.",
    }


@router.post("/login", response_model=LoginTriggerResponse)
async def trigger_login():
    """Trigger FUOverflow login window in headed browser via dedicated process."""
    login_script = settings.BASE_DIR / "scripts" / "login.py"
    if not login_script.exists():
        return LoginTriggerResponse(
            success=False,
            logged_in=False,
            message="Không tìm thấy tệp scripts/login.py",
        )

    # Check if a session is already waiting
    if SESSION_FILE.exists():
        try:
            sess = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if sess.get("state") in ("opening", "waiting_for_user"):
                pid = sess.get("pid")
                if pid and psutil.pid_exists(pid):
                    return LoginTriggerResponse(
                        success=True,
                        logged_in=False,
                        message="Đã có phiên đăng nhập đang mở. Vui lòng kiểm tra cửa sổ trình duyệt.",
                    )
        except Exception:
            pass

    try:
        # Write initial session state
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        init_payload = {
            "state": "opening",
            "message": "Đang chuẩn bị và khởi động trình duyệt...",
            "browser_used": None,
            "error": None,
            "updated_at": datetime.now().isoformat(),
        }
        SESSION_FILE.write_text(json.dumps(init_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        # Launch login.py in separate independent process
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [sys.executable, str(login_script)],
            cwd=str(settings.BASE_DIR),
            creationflags=flags,
        )

        init_payload["pid"] = proc.pid
        SESSION_FILE.write_text(json.dumps(init_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        return LoginTriggerResponse(
            success=True,
            logged_in=False,
            message="Đang mở trình duyệt đăng nhập...",
        )
    except Exception as e:
        logger.error(f"Error spawning login process: {e}")
        return LoginTriggerResponse(
            success=False,
            logged_in=False,
            message=f"Lỗi khi mở trình duyệt: {e}",
        )


def _parse_and_apply_cookies_sync(raw_input: str) -> tuple[bool, str]:
    """Parse raw cookie header or JSON, validate via probe endpoint, and persist."""
    raw_input = raw_input.strip()
    if not raw_input:
        return False, "Chuỗi cookie trống."

    cookies_to_add = []
    # Check if JSON
    if raw_input.startswith("[") or raw_input.startswith("{"):
        try:
            data = json.loads(raw_input)
            if isinstance(data, list):
                cookies_to_add = data
            elif isinstance(data, dict):
                for k, v in data.items():
                    cookies_to_add.append({
                        "name": k,
                        "value": str(v),
                        "domain": ".fuoverflow.com",
                        "path": "/",
                    })
        except Exception as e:
            logger.debug(f"JSON cookie parse error: {e}")

    # Fallback to key=value; key=value string
    if not cookies_to_add:
        pairs = raw_input.split(";")
        for pair in pairs:
            if "=" in pair:
                name, val = pair.split("=", 1)
                name = name.strip()
                val = val.strip().strip('"').strip("'")
                if name:
                    cookies_to_add.append({
                        "name": name,
                        "value": val,
                        "domain": ".fuoverflow.com",
                        "path": "/",
                    })

    if not cookies_to_add:
        return False, "Không tìm thấy cookie hợp lệ. Hãy dán chuỗi có dạng 'xf_user=...; xf_session=...'"

    # Build Cookie header string for validation
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies_to_add if c.get("name") and c.get("value"))

    # Validate against FUOverflow media probe endpoint
    probe_url = "https://fuoverflow.com/media/q1-webp.134314/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_header,
    }

    try:
        req = urllib.request.Request(probe_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
                cookies_file.parent.mkdir(parents=True, exist_ok=True)
                cookies_file.write_text(json.dumps(cookies_to_add, indent=2, ensure_ascii=False), encoding="utf-8")
                return True, "Đăng nhập thành công qua Cookie!"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "Diễn đàn từ chối Cookie này (403 Forbidden). Có thể thiếu cookie cf_clearance hoặc phiên đã hết hạn."
        return False, f"Lỗi máy chủ diễn đàn: HTTP {e.code}"
    except Exception as e:
        logger.error(f"Error probing cookies: {e}")
        has_user = any(c.get("name") in ("xf_user", "xf_user_session") for c in cookies_to_add)
        if has_user:
            cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
            cookies_file.parent.mkdir(parents=True, exist_ok=True)
            cookies_file.write_text(json.dumps(cookies_to_add, indent=2, ensure_ascii=False), encoding="utf-8")
            return True, "Đã lưu Cookie thành công!"
        return False, f"Không thể kiểm tra cookie: {e}"

    return False, "Không xác thực được phiên đăng nhập với diễn đàn."


@router.post("/cookies", response_model=LoginTriggerResponse)
async def import_cookies(req: CookieImportRequest):
    """Import and validate FUOverflow cookies without logging secrets."""
    success, message = await asyncio.to_thread(_parse_and_apply_cookies_sync, req.cookie_string)
    return LoginTriggerResponse(
        success=success,
        logged_in=success,
        message=message,
    )


@router.post("/logout")
async def logout():
    """Logout current user by removing saved cookies and user session files."""
    cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
    user_file = settings.DATA_DIR / "auth" / "current_user.json"
    session_file = settings.DATA_DIR / "auth" / "login_session.json"

    for f in (cookies_file, user_file, session_file):
        try:
            if f.exists():
                f.unlink()
        except Exception as e:
            logger.warning(f"Could not delete {f.name}: {e}")

    try:
        from backend.app.modules.crawler.browser import SessionManager, run_in_browser_thread
        await run_in_browser_thread(SessionManager.invalidate)
    except Exception as e:
        logger.warning(f"Error invalidating session during logout: {e}")

    logger.info("User logged out successfully.")
    return {"success": True, "message": "Đã đăng xuất thành công."}


def _login_with_credentials_subprocess(username: str, password: str) -> tuple[bool, str]:
    """Run credentials login strictly in an isolated child process without touching server loop."""
    login_script = settings.BASE_DIR / "scripts" / "login.py"
    if not login_script.exists():
        return False, "Không tìm thấy scripts/login.py"

    input_payload = json.dumps({"username": username, "password": password})
    try:
        res = subprocess.run(
            [sys.executable, str(login_script), "--login-credentials"],
            input=input_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=35,
            cwd=str(settings.BASE_DIR),
        )
        if res.stdout:
            for line in reversed(res.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
                    return bool(data.get("success")), data.get("message", "")
        return False, f"Lỗi tiến trình đăng nhập: {res.stderr or 'Không có phản hồi'}"
    except subprocess.TimeoutExpired:
        return False, "Quá thời gian kết nối đăng nhập (35s)."
    except Exception as e:
        return False, f"Lỗi khi thực hiện đăng nhập: {e}"


@router.post("/login-account", response_model=LoginTriggerResponse)
async def login_with_account(req: AccountLoginRequest):
    """Direct login using username and password via child process without logging credentials."""
    username_clean = req.username.strip()
    success, message = await asyncio.to_thread(_login_with_credentials_subprocess, username_clean, req.password)
    if success:
        # Save user session info locally
        try:
            user_file = settings.DATA_DIR / "auth" / "current_user.json"
            user_file.parent.mkdir(parents=True, exist_ok=True)
            user_file.write_text(
                json.dumps({
                    "username": username_clean,
                    "logged_in_at": datetime.utcnow().isoformat(),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as file_err:
            logger.warning(f"Failed to write current_user.json: {file_err}")

        # Upsert user record in Database
        try:
            from backend.app.db.session import async_session_factory
            from backend.app.db.models import User
            from sqlalchemy import select

            async with async_session_factory() as db:
                res = await db.execute(select(User).where(User.username == username_clean))
                u = res.scalar_one_or_none()
                if not u:
                    u = User(username=username_clean, display_name=username_clean)
                    db.add(u)
                u.last_login_at = datetime.utcnow()
                await db.commit()
                logger.info(f"Persisted authenticated user '{username_clean}' into database.")
        except Exception as db_err:
            logger.warning(f"Could not upsert user to database: {db_err}")

        # Ensure browser manager closes any existing context to pick up fresh cookies
        try:
            from backend.app.modules.crawler.browser import SessionManager, run_in_browser_thread
            await run_in_browser_thread(SessionManager.invalidate)
        except Exception:
            pass

    return LoginTriggerResponse(
        success=success,
        logged_in=success,
        message=message,
    )


# =====================================================================
# FUEXAM.ME AUTHENTICATION ENDPOINTS
# =====================================================================

FUEXAM_AUTH_FILE = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"


class FuexamAuthStatusResponse(BaseModel):
    logged_in: bool
    status_code: str  # "logged_in", "expired", "not_logged_in"
    username: Optional[str] = None
    detail: str = ""


class FuexamLoginSessionResponse(BaseModel):
    state: str  # "idle", "waiting", "authenticated", "timeout", "error", "cancelled"
    message: str = ""
    error: Optional[str] = None
    started_at: Optional[float] = None


_fuexam_session_state: dict = {
    "state": "idle",
    "pid": None,
    "started_at": 0.0,
    "message": "Chưa có phiên đăng nhập nào đang chạy.",
    "error": None,
}


def _check_fuexam_auth_file() -> Tuple[bool, str, Optional[str]]:
    """Check if fuexam_storage_state.json exists and has valid cookies."""
    if not FUEXAM_AUTH_FILE.exists():
        return False, "not_logged_in", None
    try:
        data = json.loads(FUEXAM_AUTH_FILE.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        has_auth = any(
            c.get("name") in ("xf_user", "xf_session", "xf_user_session") and c.get("value")
            for c in cookies
        )
        if has_auth:
            return True, "logged_in", "fuexam_member"
        return False, "expired", None
    except Exception as e:
        logger.warning(f"Error reading fuexam auth file: {e}")
        return False, "not_logged_in", None


@router.get("/fuexam/status", response_model=FuexamAuthStatusResponse)
async def get_fuexam_auth_status():
    """Kiểm tra trạng thái phiên đăng nhập của nền tảng fuexam.me."""
    logged_in, status_code, username = _check_fuexam_auth_file()
    detail = "Đã đăng nhập fuexam.me." if logged_in else "Chưa đăng nhập fuexam.me."
    return FuexamAuthStatusResponse(
        logged_in=logged_in,
        status_code=status_code,
        username=username,
        detail=detail,
    )


@router.post("/fuexam/login/start", response_model=FuexamLoginSessionResponse)
async def start_fuexam_login():
    """
    Khởi động cửa sổ Chromium headed để người dùng đăng nhập fuexam.me.
    Lưu ý vận hành (Requirement 0): Chỉ hoạt động khi backend chạy trong phiên
    Windows tương tác của người dùng (PowerShell hoặc IDE).
    Nếu không thể mở Chromium, trả lỗi rõ ràng kèm hướng dẫn khắc phục.
    """
    global _fuexam_session_state

    # 1. Nếu đã đăng nhập rồi
    logged_in, _, _ = _check_fuexam_auth_file()
    if logged_in:
        _fuexam_session_state = {
            "state": "authenticated",
            "pid": None,
            "started_at": time.time(),
            "message": "Đã có phiên đăng nhập fuexam.me hợp lệ.",
            "error": None,
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state)

    # 2. Kiểm tra nếu phiên trước đang chạy
    pid = _fuexam_session_state.get("pid")
    if pid and _fuexam_session_state.get("state") == "waiting":
        if psutil.pid_exists(pid):
            return FuexamLoginSessionResponse(**_fuexam_session_state)

    # 3. Khởi chạy scripts/fuexam_login.py với browser chromium
    login_script = settings.BASE_DIR / "scripts" / "fuexam_login.py"
    if not login_script.exists():
        _fuexam_session_state = {
            "state": "error",
            "pid": None,
            "started_at": time.time(),
            "message": "Không tìm thấy tệp scripts/fuexam_login.py",
            "error": "Tệp scripts/fuexam_login.py không tồn tại.",
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state)

    try:
        flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            [sys.executable, str(login_script), "--browser", "chromium"],
            cwd=str(settings.BASE_DIR),
            creationflags=flags,
        )

        # Allow process to start or detect immediate failure
        await asyncio.sleep(0.8)
        poll_res = proc.poll()
        if poll_res is not None and poll_res != 0:
            # Process failed immediately
            err_msg = (
                "Không thể mở cửa sổ trình duyệt Chromium từ môi trường ngầm hoặc phiên không tương tác. "
                "Vui lòng chạy backend từ PowerShell trên máy thật (python run_dev.py) để hiển thị cửa sổ Chromium."
            )
            _fuexam_session_state = {
                "state": "error",
                "pid": None,
                "started_at": time.time(),
                "message": "Không thể mở cửa sổ trình duyệt",
                "error": err_msg,
            }
            return FuexamLoginSessionResponse(**_fuexam_session_state)

        _fuexam_session_state = {
            "state": "waiting",
            "pid": proc.pid,
            "started_at": time.time(),
            "message": "Hãy đăng nhập trong cửa sổ trình duyệt vừa mở.",
            "error": None,
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state)

    except Exception as e:
        logger.error(f"Error launching fuexam login: {e}")
        err_msg = (
            f"Lỗi khởi chạy Chromium: {e}. "
            "Khắc phục: Chạy backend từ cửa sổ PowerShell trên máy thật (python run_dev.py) để hiển thị cửa sổ Chromium."
        )
        _fuexam_session_state = {
            "state": "error",
            "pid": None,
            "started_at": time.time(),
            "message": "Lỗi khởi chạy trình duyệt",
            "error": err_msg,
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state)


@router.get("/fuexam/login/status", response_model=FuexamLoginSessionResponse)
async def get_fuexam_login_status():
    """Theo dõi tiến độ đăng nhập fuexam.me."""
    global _fuexam_session_state

    # 1. Kiểm tra nếu file storage_state đã xuất hiện phiên hợp lệ
    logged_in, _, _ = _check_fuexam_auth_file()
    if logged_in:
        _fuexam_session_state["state"] = "authenticated"
        _fuexam_session_state["message"] = "Đăng nhập fuexam.me thành công!"
        _fuexam_session_state["error"] = None
        return FuexamLoginSessionResponse(**_fuexam_session_state)

    # 2. Nếu đang ở trạng thái waiting, kiểm tra thời gian timeout 5 phút (300 giây)
    if _fuexam_session_state.get("state") == "waiting":
        started = _fuexam_session_state.get("started_at", 0.0)
        if time.time() - started > 300:
            pid = _fuexam_session_state.get("pid")
            if pid and psutil.pid_exists(pid):
                try:
                    psutil.Process(pid).kill()
                except Exception:
                    pass
            _fuexam_session_state["state"] = "timeout"
            _fuexam_session_state["message"] = "Quá thời hạn chờ 5 phút mà chưa hoàn tất đăng nhập."
            _fuexam_session_state["error"] = "Hết thời gian chờ (5 phút)."
            return FuexamLoginSessionResponse(**_fuexam_session_state)

        # Kiểm tra xem tiến trình trình duyệt còn sống không
        pid = _fuexam_session_state.get("pid")
        if pid:
            try:
                proc = psutil.Process(pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    _fuexam_session_state["state"] = "error"
                    _fuexam_session_state["message"] = "Cửa sổ trình duyệt đã bị đóng."
                    _fuexam_session_state["error"] = "Cửa sổ trình duyệt đã bị đóng trước khi hoàn tất đăng nhập."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                _fuexam_session_state["state"] = "error"
                _fuexam_session_state["message"] = "Tiến trình trình duyệt đã kết thúc."
                _fuexam_session_state["error"] = "Cửa sổ trình duyệt đã bị đóng trước khi hoàn tất đăng nhập."

    return FuexamLoginSessionResponse(**_fuexam_session_state)


@router.post("/fuexam/login/cancel")
async def cancel_fuexam_login():
    """Huỷ phiên đăng nhập fuexam.me và đóng tiến trình."""
    global _fuexam_session_state
    pid = _fuexam_session_state.get("pid")
    if pid and psutil.pid_exists(pid):
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass
    _fuexam_session_state = {
        "state": "cancelled",
        "pid": None,
        "started_at": 0.0,
        "message": "Người dùng đã huỷ phiên đăng nhập.",
        "error": None,
    }
    return {"success": True, "message": "Đã huỷ phiên đăng nhập."}


@router.post("/fuexam/logout")
async def logout_fuexam():
    """Đăng xuất fuexam.me bằng cách xoá data/auth/fuexam_storage_state.json."""
    global _fuexam_session_state
    if FUEXAM_AUTH_FILE.exists():
        try:
            FUEXAM_AUTH_FILE.unlink()
        except Exception as e:
            logger.warning(f"Error deleting fuexam storage state: {e}")
    _fuexam_session_state = {
        "state": "idle",
        "pid": None,
        "started_at": 0.0,
        "message": "Chưa có phiên đăng nhập nào đang chạy.",
        "error": None,
    }
    return {"success": True, "message": "Đã đăng xuất fuexam.me thành công."}
