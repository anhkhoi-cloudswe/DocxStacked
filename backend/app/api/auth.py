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

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOG_FILE = settings.DATA_DIR / "logs" / "login.log"
SESSION_FILE = settings.DATA_DIR / "auth" / "login_session.json"
PROFILE_DIR = settings.DATA_DIR / "browser_profile"


class AuthStatusResponse(BaseModel):
    logged_in: bool
    status_code: str = "not_logged_in"  # "logged_in", "not_logged_in", "profile_locked", "network_error"
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


def _check_browser_auth_sync() -> AuthStatusResponse:
    """Synchronous check of FUOverflow authentication via saved cookies and profile state."""
    cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
    saved_username = _get_current_logged_in_username() or "Thành viên FUOverflow"

    if cookies_file.exists():
        try:
            cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
            if isinstance(cookies, list):
                for c in cookies:
                    if c.get("name") in ("xf_user", "xf_session", "xf_user_session") and c.get("value"):
                        exp = c.get("expires", 0)
                        if exp and exp > 0:
                            exp_dt = datetime.fromtimestamp(exp)
                            if exp_dt < datetime.now():
                                return AuthStatusResponse(
                                    logged_in=False,
                                    status_code="not_logged_in",
                                    detail="Phiên đăng nhập đã hết hạn.",
                                )
                            return AuthStatusResponse(
                                logged_in=True,
                                status_code="logged_in",
                                detail="Đã đăng nhập FUOverflow",
                                username=saved_username,
                                expires_at=exp_dt.isoformat(),
                            )
                        return AuthStatusResponse(
                            logged_in=True,
                            status_code="logged_in",
                            detail="Đã đăng nhập FUOverflow",
                            username=saved_username,
                        )
        except Exception as e:
            logger.debug(f"Error checking cookies.json: {e}")

    # Check if profile directory is currently locked by stale browser processes
    locking_pids = _get_profile_locking_pids()
    if locking_pids:
        return AuthStatusResponse(
            logged_in=False,
            status_code="profile_locked",
            detail=f"Thư mục hồ sơ đang bị {len(locking_pids)} tiến trình chạy ngầm giữ (PIDs: {locking_pids}).",
        )

    return AuthStatusResponse(
        logged_in=False,
        status_code="not_logged_in",
        detail="Chưa đăng nhập FUOverflow.",
    )


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status():
    """Check FUOverflow authentication status with distinct codes."""
    return _check_browser_auth_sync()


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
        from backend.app.modules.crawler.browser import SessionManager
        SessionManager.invalidate()
    except Exception as e:
        logger.warning(f"Error invalidating session during logout: {e}")

    logger.info("User logged out successfully.")
    return {"success": True, "message": "Đã đăng xuất thành công."}


def _login_with_credentials_sync(username: str, password: str) -> tuple[bool, str]:
    """Log into FUOverflow using Playwright headless with credentials without logging secrets."""
    import asyncio
    try:
        asyncio._set_running_loop(None)
    except Exception:
        pass
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass

    from playwright.sync_api import sync_playwright
    cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto("https://fuoverflow.com/login/", wait_until="domcontentloaded", timeout=25000)
            page.fill('form[action*="/login"] input[name="login"]', username)
            page.fill('form[action*="/login"] input[name="password"]', password)
            try:
                page.check('form[action*="/login"] input[name="remember"]')
            except Exception:
                pass
            page.press('form[action*="/login"] input[name="password"]', "Enter")
            page.wait_for_timeout(5000)

            cookies = context.cookies()
            has_user = any(c.get("name") in ("xf_user", "xf_session", "xf_user_session") for c in cookies)

            # Check for error message on forum page
            error_el = page.query_selector(".blockMessage--error, .formSubmitRow-errors")
            if error_el:
                err_text = error_el.inner_text().strip()
                browser.close()
                return False, f"Đăng nhập thất bại: {err_text}"

            if has_user:
                cookies_file.parent.mkdir(parents=True, exist_ok=True)
                cookies_file.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
                browser.close()
                return True, "Đăng nhập thành công!"

            browser.close()
            return False, "Không nhận được phiên đăng nhập từ diễn đàn."
    except Exception as e:
        logger.error(f"Error during headless account login: {e}")
        return False, f"Lỗi kết nối khi đăng nhập: {e}"
    finally:
        try:
            asyncio._set_running_loop(None)
        except Exception:
            pass
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass


@router.post("/login-account", response_model=LoginTriggerResponse)
async def login_with_account(req: AccountLoginRequest):
    """Direct login using username and password via headless browser without logging credentials."""
    username_clean = req.username.strip()
    success, message = await asyncio.to_thread(_login_with_credentials_sync, username_clean, req.password)
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
            from backend.app.modules.crawler.browser import SessionManager
            SessionManager.invalidate()
        except Exception:
            pass

    return LoginTriggerResponse(
        success=success,
        logged_in=success,
        message=message,
    )
