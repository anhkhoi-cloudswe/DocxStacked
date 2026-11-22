import asyncio
from datetime import datetime
import glob
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Optional, Tuple
import urllib.request
import urllib.error
import uuid
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
import psutil

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

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

# In-memory flag to signal extension to sync fuexam cookies
_fuexam_sync_requested: bool = False


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
    Returns fuexam_sync_requested=true when backend is awaiting fuexam login sync.
    """
    global _latest_extension_heartbeat, _fuexam_sync_requested, _fuexam_session_state
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

    # Kiểm tra xem có đang cần đồng bộ phiên fuexam.me từ extension không
    is_fuexam_logged, _, _, _ = _check_fuexam_auth_file()
    sync_needed = bool(
        (_fuexam_sync_requested or _fuexam_session_state.get("state") in ("waiting", "starting"))
        and not is_fuexam_logged
    )

    return {
        "status": "ok",
        "recorded": _latest_extension_heartbeat,
        "fuexam_sync_requested": sync_needed,
        "fueuxam_sync_requested": sync_needed,
    }


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
    auth_source: Optional[str] = None
    detail: str = ""
    extension_heartbeat_alive: bool = False
    last_extension_heartbeat_age: Optional[float] = None


class FuexamLoginSessionResponse(BaseModel):
    state: str  # "idle", "starting", "waiting", "success", "failed", "timeout", "cancelled"
    stage: Optional[str] = None
    run_id: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    started_at: Optional[float] = None
    recent_logs: List[str] = []


class FuexamExtensionSessionRequest(BaseModel):
    cookies: List[dict]


class FuexamModalMetricRequest(BaseModel):
    duration_ms: int
    outcome: str
    sync_method: Optional[str] = "unknown"
    username: Optional[str] = None
    extension_id: Optional[str] = None


_fuexam_session_state: dict = {
    "state": "idle",
    "stage": "idle",
    "run_id": None,
    "pid": None,
    "started_at": 0.0,
    "message": "Chưa có phiên đăng nhập nào đang chạy.",
    "error": None,
}


def cleanup_fuexam_chrome_and_profiles():
    """
    Dọn dẹp triệt để mọi tiến trình chrome.exe mồ côi và profile tạm:
    - Tìm và kill tiến trình có cmdline chứa 'fuexam_fresh_profile' hoặc 'browser_profile_fuexam' hoặc 'fuexam_selfcheck'.
    - Xoá các thư mục tempfile có tiền tố 'fuexam_fresh_profile_' hoặc 'fuexam_selfcheck_'.
    """
    current_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower()
            if "fuexam_fresh_profile" in cmd_str or "fuexam_selfcheck" in cmd_str or "browser_profile_fuexam" in cmd_str:
                p = psutil.Process(proc.info["pid"])
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    import glob
    import shutil
    temp_dir = Path(tempfile.gettempdir())
    for p_str in glob.glob(str(temp_dir / "fuexam_fresh_profile_*")) + glob.glob(str(temp_dir / "fuexam_selfcheck_*")):
        try:
            shutil.rmtree(p_str, ignore_errors=True)
        except Exception:
            pass


def _get_recent_fuexam_logs(max_lines: int = 20) -> List[str]:
    """Lấy tối đa 20 dòng cuối của fuexam_login.log, đã lọc sạch không chứa cookie/token."""
    log_file = get_settings().DATA_DIR / "logs" / "fuexam_login.log"
    if not log_file.exists():
        return []
    try:
        import re
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:]
        sanitized = []
        patterns = [
            (re.compile(r'(xf_user|xf_session|xf_csrf|_xfToken|token|cookie)=([^\s;&,]+)', re.IGNORECASE), r'\1=[REDACTED]'),
            (re.compile(r'("?(?:xf_user|xf_session|xf_csrf|_xfToken|token|password)"?\s*:\s*)"([^"]+)"', re.IGNORECASE), r'\1"[REDACTED]"'),
            (re.compile(r'cookies:\s*\[.*?\]', re.IGNORECASE), r'cookies: [REDACTED]'),
        ]
        for line in tail:
            masked = line
            for pat, repl in patterns:
                masked = pat.sub(repl, masked)
            sanitized.append(masked)
        return sanitized
    except Exception as e:
        logger.warning(f"Error reading fuexam_login.log: {e}")
        return []


def _check_fuexam_auth_file() -> Tuple[bool, str, Optional[str], Optional[str]]:
    """Check if fuexam_storage_state.json exists and has valid cookies. Returns (logged_in, status_code, username, auth_source)."""
    auth_file = get_settings().DATA_DIR / "auth" / "fuexam_storage_state.json"
    if not auth_file.exists():
        return False, "logged_out", None, None
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        cookies = data.get("cookies", [])
        cookies_dict = {c.get("name"): c.get("value") for c in cookies}
        # Must have xf_user with non-empty value (xf_session alone is NOT accepted)
        if not cookies_dict.get("xf_user"):
            return False, "logged_out", None, None

        # Load real username and auth_source from user info file
        username = None
        auth_source = "headed_chromium"
        user_file = get_settings().DATA_DIR / "auth" / "fuexam_user.json"
        if user_file.exists():
            try:
                u_data = json.loads(user_file.read_text(encoding="utf-8"))
                username = u_data.get("username")
                auth_source = u_data.get("auth_source", "headed_chromium")
            except Exception:
                pass

        return True, "logged_in", username or "Thành viên fuexam", auth_source
    except Exception as e:
        logger.warning(f"Error reading fuexam auth file: {e}")
        return False, "logged_out", None, None


@router.get("/fuexam/status", response_model=FuexamAuthStatusResponse)
async def get_fuexam_auth_status():
    """Kiểm tra trạng thái phiên đăng nhập của nền tảng fuexam.me."""
    logged_in, status_code, username, auth_source = _check_fuexam_auth_file()
    now = time.time()
    last_hb = _latest_extension_heartbeat.get("timestamp", 0.0)
    hb_age = now - last_hb if last_hb > 0 else 999999.0
    hb_alive = hb_age <= 30.0

    detail = f"Đã đăng nhập fuexam.me ({username})." if logged_in else "Chưa đăng nhập fuexam.me."
    return FuexamAuthStatusResponse(
        logged_in=logged_in,
        status_code=status_code,
        username=username,
        auth_source=auth_source,
        detail=detail,
        extension_heartbeat_alive=hb_alive,
        last_extension_heartbeat_age=hb_age if last_hb > 0 else None,
    )


@router.post("/fuexam/sync-request")
async def request_fuexam_sync():
    """Bật cờ yêu cầu extension đồng bộ phiên fuexam.me (khi modal mở hoặc người dùng bấm)."""
    global _fuexam_sync_requested, _fuexam_session_state
    _fuexam_sync_requested = True
    _fuexam_session_state["state"] = "waiting"
    _fuexam_session_state["stage"] = "waiting_for_extension"
    _fuexam_session_state["message"] = "Đang chờ Extension DocxStacked gửi phiên đăng nhập fuexam.me..."
    _fuexam_session_state["error"] = None
    return {"success": True, "sync_requested": True}


@router.post("/fuexam/extension-session")
async def receive_fuexam_extension_session(
    payload: FuexamExtensionSessionRequest,
    request: Request,
    x_ingest_token: Optional[str] = Header(None, alias="X-Ingest-Token"),
    x_docxstacked_ext: Optional[str] = Header(None, alias="X-DocxStacked-Ext"),
):
    """
    Tiếp nhận cookies phiên đăng nhập fuexam.me từ extension:
    - Kiểm tra token (403 nếu sai).
    - Bắt buộc có xf_user không rỗng (400 nếu thiếu).
    - Probe GET https://fuexam.me/ cần HTTP 200 và html[data-logged-in="true"].
    - Thành công: lưu data/auth/fuexam_storage_state.json và fuexam_user.json (auth_source="extension").
    - Thất bại: trả lỗi rõ, không lưu.
    - TUYỆT ĐỐI không ghi log giá trị cookie ở bất kỳ nơi nào.
    """
    global _fuexam_session_state, _fuexam_sync_requested
    import requests
    from bs4 import BeautifulSoup

    # 1. Kiểm tra Token Ingest
    expected_token = (get_settings().INGEST_TOKEN or "").strip()
    if not expected_token:
        expected_token = getattr(get_settings(), "LOCAL_INGEST_KEY", "docxstacked_local_secret_2026")

    provided_token = (x_ingest_token or "").strip()
    configured_ext_id = (get_settings().EXTENSION_ID or "kicplcdfmbcfjildbbimpfiljlmfokea").strip()
    origin_header = request.headers.get("origin", "")
    is_trusted_origin = origin_header.startswith(f"chrome-extension://{configured_ext_id}")
    is_trusted_header = x_docxstacked_ext == configured_ext_id

    # If neither valid token nor trusted extension origin/header
    token_valid = bool(provided_token and provided_token == expected_token)
    if not token_valid and not (is_trusted_origin or is_trusted_header):
        logger.warning("[FUEXAM EXTENSION AUTH] Từ chối request do sai Ingest Token và không có Origin extension hợp lệ.")
        raise HTTPException(status_code=403, detail="Xác thực Ingest Token không hợp lệ.")

    # 2. Kiểm tra danh sách cookies
    raw_cookies = payload.cookies or []
    cookies_dict = {}
    playwright_cookies = []

    for c in raw_cookies:
        name = c.get("name")
        val = c.get("value")
        if name and val is not None:
            cookies_dict[name] = val
            playwright_cookies.append({
                "name": name,
                "value": val,
                "domain": c.get("domain") or ".fuexam.me",
                "path": c.get("path") or "/",
                "expires": c.get("expirationDate", -1),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": c.get("sameSite", "Lax"),
            })

    xf_user = cookies_dict.get("xf_user")
    if not xf_user or not str(xf_user).strip():
        logger.warning("[FUEXAM EXTENSION AUTH] Thiếu cookie xf_user hoặc giá trị rỗng.")
        raise HTTPException(
            status_code=400,
            detail="Thiếu cookie xf_user hoặc cookie rỗng. Bạn chưa đăng nhập tài khoản trên fuexam.me.",
        )

    # 3. Probe GET https://fuexam.me/ để xác minh phiên
    is_valid = False
    real_username = None
    probe_url = "https://fuexam.me/"
    probe_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    }

    try:
        resp = await asyncio.to_thread(
            requests.get,
            probe_url,
            cookies=cookies_dict,
            headers=probe_headers,
            timeout=10,
        )
        if resp.status_code == 200 and 'data-logged-in="true"' in resp.text:
            is_valid = True
            from scripts.fuexam_login import extract_real_username_from_html
            real_username = extract_real_username_from_html(resp.text)
    except Exception as e:
        logger.warning(f"[FUEXAM EXTENSION AUTH] Probe requests thất bại: {e}. Thử fallback Playwright headless...")

    # Fallback Playwright headless nếu requests bị chặn hoặc lỗi
    if not is_valid:
        try:
            def _playwright_probe():
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    ctx = browser.new_context()
                    ctx.add_cookies(playwright_cookies)
                    page = ctx.new_page()
                    page.goto(probe_url, wait_until="domcontentloaded", timeout=15000)
                    content = page.content()
                    browser.close()
                    if 'data-logged-in="true"' in content:
                        from scripts.fuexam_login import extract_real_username_from_html
                        u = extract_real_username_from_html(content)
                        return True, u
                    return False, None

            is_valid, real_username = await asyncio.to_thread(_playwright_probe)
        except Exception as e:
            logger.warning(f"[FUEXAM EXTENSION AUTH] Playwright headless probe thất bại: {e}")

    if not is_valid:
        logger.warning("[FUEXAM EXTENSION AUTH] Xác minh phiên fuexam.me thất bại (không có data-logged-in='true').")
        raise HTTPException(
            status_code=400,
            detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn trên fuexam.me (trang web không trả về data-logged-in='true'). Vui lòng đăng nhập lại trên trình duyệt.",
        )

    # 4. Lưu storage_state.json và fuexam_user.json
    current_settings = get_settings()
    auth_dir = current_settings.DATA_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "fuexam_storage_state.json"
    user_file = auth_dir / "fuexam_user.json"

    storage_state_data = {
        "cookies": playwright_cookies,
        "origins": [],
    }
    auth_file.write_text(json.dumps(storage_state_data, indent=2, ensure_ascii=False), encoding="utf-8")

    final_username = real_username or "Thành viên fuexam"
    user_data = {
        "username": final_username,
        "logged_in_at": datetime.now().isoformat(),
        "auth_source": "extension",
    }
    user_file.write_text(json.dumps(user_data, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        from scripts.fuexam_login import set_owner_only_permissions
        set_owner_only_permissions(auth_file)
        set_owner_only_permissions(user_file)
    except Exception:
        pass

    # 5. Cập nhật state
    _fuexam_session_state = {
        "run_id": None,
        "state": "success",
        "stage": "authenticated",
        "pid": None,
        "started_at": time.time(),
        "message": f"Đồng bộ phiên fuexam.me thành công từ extension ({final_username}).",
        "error": None,
    }
    _fuexam_sync_requested = False

    logger.info(f"[FUEXAM EXTENSION AUTH] Đã đồng bộ thành công phiên fuexam.me từ extension cho tài khoản '{final_username}'.")
    return {
        "success": True,
        "username": final_username,
        "message": f"Đã đồng bộ phiên fuexam.me thành công ({final_username}).",
    }


@router.post("/fuexam/modal-session-metric")
async def record_fuexam_modal_session_metric(payload: FuexamModalMetricRequest):
    """
    Ghi lại thời gian mở modal đồng bộ phiên thực tế (tính bằng mili giây) vào log backend
    để người dùng gửi lại; không tự khẳng định 'dưới 3 giây' khi chưa có số đo thật.
    """
    log_msg = (
        f"[FUEXAM_SYNC_TIMING] Modal session completed in {payload.duration_ms} ms "
        f"(outcome='{payload.outcome}', method='{payload.sync_method}', user='{payload.username}', ext_id='{payload.extension_id}')"
    )
    logger.info(log_msg)
    try:
        append_log(
            f"[THỜI GIAN ĐỒNG BỘ] Modal hoàn tất sau {payload.duration_ms} ms "
            f"(kết quả: {payload.outcome}, phương thức: {payload.sync_method})",
            level="INFO",
        )
    except Exception:
        pass
    return {"status": "ok", "duration_ms": payload.duration_ms}


@router.post("/fuexam/login/start", response_model=FuexamLoginSessionResponse)
async def start_fuexam_login():
    """
    Khởi động cửa sổ Chromium headed để người dùng đăng nhập fuexam.me.
    - Xoá fuexam_login_ipc.json và truncate fuexam_login.log trước mỗi lần start.
    - Cấp run_id ngẫu nhiên cho mỗi phiên, script con phải ghi đúng run_id + pid mới chấp nhận.
    - Chỉ trả trạng thái 'waiting' sau khi script con đã ghi stage 'page_loaded' (sau khi goto xong).
    - Watchdog 30s: nếu chưa tới 'page_loaded', kill tiến trình con, dọn chrome.exe mồ côi và báo lỗi kèm tên giai đoạn.
    """
    global _fuexam_session_state

    # 1. Nếu đã đăng nhập rồi
    logged_in, _, username, _ = _check_fuexam_auth_file()
    if logged_in:
        _fuexam_session_state = {
            "run_id": None,
            "state": "success",
            "stage": "authenticated",
            "pid": None,
            "started_at": time.time(),
            "message": f"Đã có phiên đăng nhập fuexam.me hợp lệ ({username}).",
            "error": None,
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

    # 2. Kiểm tra nếu phiên trước đang chạy
    pid = _fuexam_session_state.get("pid")
    if pid and _fuexam_session_state.get("state") == "waiting":
        if psutil.pid_exists(pid):
            return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

    current_settings = get_settings()

    # Dọn dẹp tiến trình chrome mồ côi và profile tạm từ phiên trước
    cleanup_fuexam_chrome_and_profiles()

    login_script = current_settings.BASE_DIR / "scripts" / "fuexam_login.py"
    if not login_script.exists():
        _fuexam_session_state = {
            "run_id": None,
            "state": "failed",
            "stage": "init",
            "pid": None,
            "started_at": time.time(),
            "message": "Không tìm thấy tệp scripts/fuexam_login.py",
            "error": "Tệp scripts/fuexam_login.py không tồn tại.",
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

    # 3. Xoá file báo hiệu IPC cũ
    ipc_file = current_settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"
    try:
        if ipc_file.exists():
            ipc_file.unlink()
    except Exception:
        pass

    # 4. Truncate file log fuexam_login.log cho lần chạy này
    log_file_path = current_settings.DATA_DIR / "logs" / "fuexam_login.log"
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    try:
        with open(log_file_path, "w", encoding="utf-8") as f:
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            f.write(f"[{now_iso}] [INFO] [STAGE: init] Khởi tạo phiên đăng nhập mới (run_id: {run_id})\n")
    except Exception:
        pass

    try:
        _fuexam_session_state = {
            "run_id": run_id,
            "state": "starting",
            "stage": "init",
            "pid": None,
            "started_at": time.time(),
            "message": "Đang khởi động trình duyệt Chromium...",
            "error": None,
        }

        # Khởi chạy với CREATE_NEW_CONSOLE trên Windows, stdin=DEVNULL
        creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        cmd = [sys.executable, str(login_script), "--browser", "chromium", "--run-id", run_id]

        proc = subprocess.Popen(
            cmd,
            cwd=str(current_settings.BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            creationflags=creationflags,
            env=os.environ.copy(),
        )
        _fuexam_session_state["pid"] = proc.pid

        # 5. Watchdog 30 giây: theo dõi tiến trình con & chỉ nhận waiting khi stage == "page_loaded"
        wait_start = time.time()
        last_stage = "init"
        while time.time() - wait_start < 30.0:
            # A. Đọc file IPC trước để cập nhật stage mới nhất (kể cả khi tiến trình vừa ghi xong rồi thoát)
            if ipc_file.exists():
                try:
                    ipc_data = json.loads(ipc_file.read_text(encoding="utf-8"))
                    if ipc_data.get("run_id") == run_id and ipc_data.get("pid") == proc.pid:
                        curr_stage = ipc_data.get("stage", "starting")
                        last_stage = curr_stage
                        _fuexam_session_state["stage"] = curr_stage
                        if curr_stage == "page_loaded" and ipc_data.get("state") == "waiting":
                            _fuexam_session_state["state"] = "waiting"
                            _fuexam_session_state["message"] = "Hãy đăng nhập trong cửa sổ vừa mở."
                            return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))
                        elif ipc_data.get("state") == "failed":
                            cleanup_fuexam_chrome_and_profiles()
                            _fuexam_session_state["state"] = "failed"
                            _fuexam_session_state["error"] = ipc_data.get("message", "Lỗi trong tiến trình đăng nhập.")
                            return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))
                except Exception:
                    pass

            # B. Kiểm tra nếu tiến trình thoát sớm
            poll_res = proc.poll()
            if poll_res is not None:
                cleanup_fuexam_chrome_and_profiles()
                err_msg = f"Tiến trình Chromium đã thoát sớm (mã lỗi {poll_res}) tại giai đoạn '{last_stage}'."
                if poll_res != 0:
                    err_msg += " Cửa sổ Chromium đã bị đóng hoặc lỗi môi trường đồ hoạ."
                _fuexam_session_state = {
                    "run_id": run_id,
                    "state": "failed",
                    "stage": last_stage,
                    "pid": None,
                    "started_at": time.time(),
                    "message": "Không thể mở cửa sổ trình duyệt",
                    "error": err_msg,
                }
                return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

            await asyncio.sleep(0.3)

        # C. Watchdog 30s kích hoạt nếu chưa đạt stage 'page_loaded'
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        cleanup_fuexam_chrome_and_profiles()
        _fuexam_session_state = {
            "run_id": run_id,
            "state": "failed",
            "stage": last_stage,
            "pid": None,
            "started_at": time.time(),
            "message": "Khởi động trình duyệt quá thời gian (watchdog 30s)",
            "error": f"Watchdog timeout (30s): Chromium chưa tải xong trang đăng nhập. Điểm dừng cuối cùng: '{last_stage}'. Cửa sổ trình duyệt có thể bị chặn hoặc đóng.",
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

    except Exception as e:
        logger.error(f"Error launching fuexam login: {e}")
        cleanup_fuexam_chrome_and_profiles()
        _fuexam_session_state = {
            "run_id": run_id,
            "state": "failed",
            "stage": "init",
            "pid": None,
            "started_at": time.time(),
            "message": "Lỗi khởi chạy trình duyệt",
            "error": f"Lỗi khởi chạy Chromium: {e}",
        }
        return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))


@router.get("/fuexam/login/status", response_model=FuexamLoginSessionResponse)
async def get_fuexam_login_status():
    """Theo dõi tiến độ đăng nhập fuexam.me kèm 20 dòng log mới nhất đã lọc sạch token."""
    global _fuexam_session_state

    # 1. Kiểm tra nếu file storage_state đã xuất hiện phiên hợp lệ
    logged_in, _, username, _ = _check_fuexam_auth_file()
    if logged_in:
        cleanup_fuexam_chrome_and_profiles()
        _fuexam_session_state["state"] = "success"
        _fuexam_session_state["stage"] = "authenticated"
        _fuexam_session_state["message"] = f"Đăng nhập fuexam.me thành công! Tài khoản: {username}"
        _fuexam_session_state["error"] = None
        return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

    # 2. Nếu đang ở trạng thái waiting hoặc starting, kiểm tra thời gian timeout 5 phút (300 giây)
    if _fuexam_session_state.get("state") in ("waiting", "starting"):
        started = _fuexam_session_state.get("started_at", 0.0)
        if time.time() - started > 300:
            pid = _fuexam_session_state.get("pid")
            if pid and psutil.pid_exists(pid):
                try:
                    psutil.Process(pid).kill()
                except Exception:
                    pass
            cleanup_fuexam_chrome_and_profiles()
            _fuexam_session_state["state"] = "timeout"
            _fuexam_session_state["stage"] = "timeout"
            _fuexam_session_state["message"] = "Quá thời hạn chờ 5 phút mà chưa hoàn tất đăng nhập."
            _fuexam_session_state["error"] = "Hết thời gian chờ (5 phút)."
            return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))

        # Kiểm tra xem tiến trình trình duyệt còn sống không
        pid = _fuexam_session_state.get("pid")
        if pid:
            try:
                proc = psutil.Process(pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    cleanup_fuexam_chrome_and_profiles()
                    _fuexam_session_state["state"] = "failed"
                    _fuexam_session_state["stage"] = "closed"
                    _fuexam_session_state["message"] = "Cửa sổ trình duyệt đã bị đóng."
                    _fuexam_session_state["error"] = "Cửa sổ Chromium đã bị đóng hoặc tiến trình đã dừng trước khi hoàn tất đăng nhập."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                cleanup_fuexam_chrome_and_profiles()
                _fuexam_session_state["state"] = "failed"
                _fuexam_session_state["stage"] = "closed"
                _fuexam_session_state["message"] = "Tiến trình trình duyệt đã kết thúc."
                _fuexam_session_state["error"] = "Cửa sổ Chromium đã bị đóng hoặc tiến trình đã dừng trước khi hoàn tất đăng nhập."

    return FuexamLoginSessionResponse(**_fuexam_session_state, recent_logs=_get_recent_fuexam_logs(20))


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
    cleanup_fuexam_chrome_and_profiles()
    current_settings = get_settings()
    ipc_file = current_settings.DATA_DIR / "auth" / "fuexam_login_ipc.json"
    try:
        if ipc_file.exists():
            ipc_file.unlink()
    except Exception:
        pass
    _fuexam_session_state = {
        "run_id": None,
        "state": "idle",
        "stage": "idle",
        "pid": None,
        "started_at": 0.0,
        "message": "Người dùng đã huỷ phiên đăng nhập.",
        "error": None,
    }
    return {"success": True, "message": "Đã huỷ phiên đăng nhập."}


@router.post("/fuexam/chromium-self-check")
async def check_chromium_self_check():
    """Chạy self-check kiểm tra khả năng mở Chromium thật trên máy người dùng."""
    login_script = settings.BASE_DIR / "scripts" / "fuexam_login.py"
    if not login_script.exists():
        return {
            "success": False,
            "browser": "Chromium",
            "executable_path": "",
            "message": "Không tìm thấy scripts/fuexam_login.py",
        }
    try:
        res = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, str(login_script), "--self-check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            cwd=str(settings.BASE_DIR),
        )
        success = (res.returncode == 0)
        output = (res.stdout or "") + "\n" + (res.stderr or "")
        exec_path = ""
        for line in output.splitlines():
            if "Đường dẫn thực thi" in line and ":" in line:
                exec_path = line.split(":", 1)[1].strip()
        return {
            "success": success,
            "browser": "Playwright Chromium",
            "executable_path": exec_path,
            "message": "Chromium mở và đóng bình thường (3s test)." if success else (res.stderr or res.stdout or "Không thể mở Chromium"),
            "output": output.strip(),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "browser": "Chromium",
            "executable_path": "",
            "message": "Self-check quá thời gian (timeout 20s).",
        }
    except Exception as e:
        return {
            "success": False,
            "browser": "Chromium",
            "executable_path": "",
            "message": f"Lỗi khi chạy self-check: {e}",
        }


def _perform_fuexam_logout_sync() -> tuple[bool, str]:
    """
    Exhaustive logout for fuexam:
    1. Check auth_source in fuexam_user.json. If auth_source == "extension",
       DO NOT call server-side logout on fuexam.me (as this would invalidate user's session in their browser).
       Only call server-side logout if auth_source != "extension".
    2. Terminate any browser processes locking fuexam profile dirs.
    3. Delete storage_state.json and fuexam_user.json.
    4. Delete all profile/user_data_dir directories of Chromium used for fuexam.
    """
    import shutil
    import requests
    from bs4 import BeautifulSoup

    current_settings = get_settings()
    auth_file = current_settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = current_settings.DATA_DIR / "auth" / "fuexam_user.json"
    profile_dir = current_settings.DATA_DIR / "browser_profile_fuexam"

    # Check auth_source
    auth_source = None
    if user_file.exists():
        try:
            udata = json.loads(user_file.read_text(encoding="utf-8"))
            auth_source = udata.get("auth_source")
        except Exception:
            pass

    # 1. Server-side logout (ONLY if not extension auth)
    if auth_source == "extension":
        logger.info("Extension auth mode detected: Skipping server-side logout to preserve browser session.")
    elif auth_file.exists():
        try:
            state_data = json.loads(auth_file.read_text(encoding="utf-8"))
            cookies = {c["name"]: c["value"] for c in state_data.get("cookies", [])}
            if "xf_user" in cookies or "xf_session" in cookies:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://fuexam.me/",
                }
                resp = requests.get("https://fuexam.me/logout/", cookies=cookies, headers=headers, timeout=10)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    token = None
                    form = soup.find("form", action=lambda a: a and "logout" in a)
                    if form:
                        inp = form.find("input", attrs={"name": "_xfToken"})
                        if inp:
                            token = inp.get("value")
                    if not token:
                        inp = soup.find("input", attrs={"name": "_xfToken"})
                        if inp:
                            token = inp.get("value")
                    if token:
                        requests.post(
                            "https://fuexam.me/logout/",
                            data={"_xfToken": token, "_xfRedirect": "https://fuexam.me/"},
                            cookies=cookies,
                            headers=headers,
                            timeout=10,
                        )
                        logger.info("Sent server-side logout request to fuexam.me successfully.")
        except Exception as e:
            logger.warning(f"Server-side logout warning: {e}")

    # 2. Terminate running browser processes
    try:
        from scripts.fuexam_login import terminate_profile_locks
        terminate_profile_locks(profile_dir)
        for p in current_settings.DATA_DIR.glob("fuexam_*profile*"):
            if p.is_dir():
                terminate_profile_locks(p)
    except Exception as e:
        logger.warning(f"Error terminating profile locks: {e}")

    # 3. Delete auth files
    for f in (auth_file, user_file):
        try:
            if f.exists():
                f.unlink()
        except Exception as e:
            logger.warning(f"Could not delete {f.name}: {e}")

    # 4. Delete all Chromium profile / user_data directories for fuexam
    try:
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
        for p in current_settings.DATA_DIR.glob("fuexam_*profile*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Error deleting fuexam profile directory: {e}")

    if auth_source == "extension":
        return True, "Đã ngắt kết nối phiên fuexam.me trên DocxStacked (không đăng xuất trình duyệt thật)."
    return True, "Đã đăng xuất fuexam.me thành công."


@router.post("/fuexam/logout")
async def logout_fuexam():
    """Đăng xuất fuexam.me: xoá tệp phiên, profile Chromium, và gọi logout máy chủ."""
    global _fuexam_session_state
    success, message = await asyncio.to_thread(_perform_fuexam_logout_sync)
    _fuexam_session_state = {
        "state": "idle",
        "pid": None,
        "started_at": 0.0,
        "message": "Chưa có phiên đăng nhập nào đang chạy.",
        "error": None,
    }
    return {"success": success, "message": message}
